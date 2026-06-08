#!/usr/bin/env python3
import argparse
import struct
import time
import sys

import serial
import numpy as np
import matplotlib.pyplot as plt

SYNC = b"\xAA\x55"

def log(msg):
    print(msg, flush=True)

def write_cmd(ser: serial.Serial, s: str):
    # UniProto reads until '\n' so '\n' is sufficient
    if not s.endswith("\n"):
        s += "\n"
    log(f">>> {s.strip()}")
    ser.write(s.encode("ascii", errors="ignore"))
    ser.flush()

def try_parse_one(buf: bytearray):
    """
    Parses UniProto binary packets:
      AA 55
      streamId u8
      flags u8
      payloadLen u16 LE
      [timestamp u32 LE] if flags&1
      payload bytes[payloadLen]
    Returns (pkt_dict, consumed) or (None, 0).
    """
    i = buf.find(SYNC)
    if i < 0:
        # prevent unbounded growth
        if len(buf) > 8192:
            del buf[:-2]
        return None, 0

    # drop junk before sync (this will discard "OK\n" etc)
    if i > 0:
        del buf[:i]

    if len(buf) < 2 + 1 + 1 + 2:
        return None, 0

    stream_id = buf[2]
    flags = buf[3]
    payload_len = struct.unpack_from("<H", buf, 4)[0]
    idx = 6

    ts = None
    if flags & 0x01:
        if len(buf) < idx + 4:
            return None, 0
        ts = struct.unpack_from("<I", buf, idx)[0]
        idx += 4

    if len(buf) < idx + payload_len:
        return None, 0

    payload = bytes(buf[idx:idx+payload_len])
    consumed = idx + payload_len

    return {
        "sid": stream_id,
        "flags": flags,
        "ts": ts,
        "len": payload_len,
        "payload": payload,
    }, consumed

def parse_adns_chunk(payload: bytes):
    if len(payload) < 10:
        return None
    frame_id, w, h, off, n = struct.unpack_from("<HHHHH", payload, 0)
    data = payload[10:]
    if len(data) != n:
        return None
    return frame_id, w, h, off, n, data

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--stream", type=int, default=7, help="adns.frame stream id")
    ap.add_argument("--rate", type=int, default=200)
    ap.add_argument("--show", action="store_true", help="show reconstructed 18x18 image")
    ap.add_argument("--continuous", action="store_true", help="request a new capture after each completed frame")
    args = ap.parse_args()

    log(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.1)

    # Many Arduino boards reset on DTR toggle; do it explicitly and wait.
    ser.dtr = False
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.dtr = True
    time.sleep(2.0)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    log("[INFO] Port open, Arduino reset window passed, buffers cleared.")

    # Send config commands
    write_cmd(ser, f"!rate:{args.rate}")
    write_cmd(ser, "!timestamp:0")
    write_cmd(ser, "!format:bin")
    write_cmd(ser, f"!stream:{args.stream}")
    write_cmd(ser, "!adns.capture:1")

    rx = bytearray()
    total_rx = 0
    last_report = time.time()

    # frame reconstruction
    W = 18
    H = 18
    cur_id = None
    frame = np.zeros(W*H, dtype=np.uint8)
    got = np.zeros(W*H, dtype=np.uint8)

    if args.show:
        plt.ion()
        fig, ax = plt.subplots()
        img = ax.imshow(frame.reshape(H, W).astype(np.float32) / 63.0, interpolation="nearest")
        ax.set_title("ADNS2610")
        plt.show()

    pkt_count = 0

    while True:
        chunk = ser.read(512)
        if chunk:
            rx.extend(chunk)
            total_rx += len(chunk)

        # periodic raw RX report
        now = time.time()
        if now - last_report >= 1.0:
            if total_rx == 0:
                log("[RX] 0 bytes received so far (check: stream enabled? another app using port?)")
            else:
                # show last up to 16 bytes
                tail = bytes(rx[-16:]) if len(rx) >= 16 else bytes(rx)
                log(f"[RX] total={total_rx}B  buf={len(rx)}B  tail={tail.hex(' ')}")
            last_report = now

        pkt, consumed = try_parse_one(rx)
        if pkt is None:
            continue

        del rx[:consumed]
        pkt_count += 1
        log(f"[PKT] #{pkt_count} sid={pkt['sid']} flags=0x{pkt['flags']:02X} ts={pkt['ts']} len={pkt['len']}")

        if pkt["sid"] != args.stream:
            continue

        parsed = parse_adns_chunk(pkt["payload"])
        if not parsed:
            log("  [WARN] payload is not a valid ADNS chunk (header/length mismatch)")
            continue

        frame_id, w, h, off, n, data = parsed
        log(f"  [ADNS] frame={frame_id} {w}x{h} off={off} n={n}")

        if cur_id != frame_id or w != W or h != H:
            cur_id = frame_id
            W, H = w, h
            frame = np.zeros(W*H, dtype=np.uint8)
            got = np.zeros(W*H, dtype=np.uint8)

        if off + n <= frame.size:
            frame[off:off+n] = np.frombuffer(data, dtype=np.uint8)
            got[off:off+n] = 1

        if got.all():
            log(f"[FRAME DONE] id={cur_id}")
            if args.show:
                img.set_data(frame.reshape(H, W).astype(np.float32) / 63.0)
                plt.pause(0.001)

            if args.continuous:
                write_cmd(ser, "!adns.capture:1")
            else:
                log("[INFO] One frame complete; waiting for Ctrl+C.")
                # continue waiting (so you can still see packets)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Exit.")
