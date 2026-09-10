#!/usr/bin/env python3
import argparse
import struct
import time
import sys

import matplotlib
matplotlib.use("MacOSX")          # macOS: use TkAgg so plt.ion() + plt.pause() work
                                  # if TkAgg not available try: matplotlib.use("Qt5Agg")
import matplotlib.pyplot as plt
import serial
import numpy as np

SYNC = b"\xAA\x55"

def log(msg):
    print(msg, flush=True)

def write_cmd(ser: serial.Serial, s: str):
    if not s.endswith("\n"):
        s += "\n"
    log(f">>> {s.strip()}")
    ser.write(s.encode("ascii", errors="ignore"))
    ser.flush()

def try_parse_one(buf: bytearray):
    """
    Parses UniProto binary packets:
      AA 55  streamId u8  flags u8  payloadLen u16 LE
      [timestamp u32 LE] if flags&1
      payload bytes[payloadLen]
    Returns (pkt_dict, consumed) or (None, 0).
    """
    i = buf.find(SYNC)
    if i < 0:
        if len(buf) > 8192:
            del buf[:-2]
        return None, 0
    if i > 0:
        del buf[:i]
    if len(buf) < 6:
        return None, 0

    stream_id   = buf[2]
    flags       = buf[3]
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

    payload  = bytes(buf[idx:idx+payload_len])
    consumed = idx + payload_len
    return {"sid": stream_id, "flags": flags, "ts": ts,
            "len": payload_len, "payload": payload}, consumed

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
    ap.add_argument("--port",       required=True)
    ap.add_argument("--baud",       type=int, default=115200)
    ap.add_argument("--stream",     type=int, default=7)
    ap.add_argument("--rate",       type=int, default=200)
    ap.add_argument("--continuous", action="store_true",
                    help="auto-request new frame after each complete one")
    ap.add_argument("--flip_x",     action="store_true")
    ap.add_argument("--flip_y",     action="store_true")
    args = ap.parse_args()

    log(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.1)
    ser.dtr = False; time.sleep(0.2)
    ser.reset_input_buffer(); ser.reset_output_buffer()
    ser.dtr = True;  time.sleep(2.0)
    ser.reset_input_buffer(); ser.reset_output_buffer()
    log("[INFO] Port open.")

    write_cmd(ser, f"!rate:{args.rate}")
    write_cmd(ser, "!timestamp:0")
    write_cmd(ser, "!format:bin")
    write_cmd(ser, f"!stream:{args.stream}")
    write_cmd(ser, "!adns.capture:1")

    # ---- matplotlib setup ----
    plt.ion()
    fig, ax = plt.subplots()
    W, H = 18, 18
    blank = np.zeros((H, W), dtype=np.float32)
    img_plot = ax.imshow(blank, vmin=0, vmax=1,
                         cmap="gray", interpolation="nearest")
    fig.colorbar(img_plot, ax=ax)
    ax.set_title("ADNS2610 — waiting for first frame…")
    plt.show(block=False)
    plt.pause(0.1)

    # ---- receive loop ----
    rx          = bytearray()
    total_rx    = 0
    last_report = time.time()
    pkt_count   = 0
    cur_id      = None
    frame       = np.zeros(W * H, dtype=np.uint8)
    got         = np.zeros(W * H, dtype=np.bool_)

    while plt.fignum_exists(fig.number):   # exits cleanly when window is closed
        chunk = ser.read(512)
        if chunk:
            rx.extend(chunk)
            total_rx += len(chunk)

        now = time.time()
        if now - last_report >= 2.0:
            log(f"[RX] total={total_rx}B  buf={len(rx)}B  pkts={pkt_count}")
            last_report = now

        pkt, consumed = try_parse_one(rx)
        if pkt is None:
            plt.pause(0.001)
            continue

        del rx[:consumed]
        pkt_count += 1

        if pkt["sid"] != args.stream:
            continue

        parsed = parse_adns_chunk(pkt["payload"])
        if not parsed:
            log("[WARN] invalid chunk payload")
            continue

        frame_id, w, h, off, n, data = parsed

        if cur_id != frame_id or w != W or h != H:
            cur_id = frame_id
            W, H   = w, h
            frame  = np.zeros(W * H, dtype=np.uint8)
            got    = np.zeros(W * H, dtype=np.bool_)

        if off + n <= frame.size:
            frame[off:off+n] = np.frombuffer(data, dtype=np.uint8)
            got[off:off+n]   = True

        if got.all():
            log(f"[FRAME] id={cur_id}")
            img2 = frame.reshape(H, W).astype(np.float32) / 63.0
            if args.flip_y: img2 = np.flipud(img2)
            if args.flip_x: img2 = np.fliplr(img2)
            img_plot.set_data(img2)
            ax.set_title(f"ADNS2610  frame {cur_id}")
            fig.canvas.draw()
            plt.pause(0.001)

            if args.continuous:
                write_cmd(ser, "!adns.capture:1")

    write_cmd(ser, "!format:csv")
    write_cmd(ser, "!stream:0")
    ser.close()
    log("[INFO] Closed.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Exit.")