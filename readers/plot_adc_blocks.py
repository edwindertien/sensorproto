import time
import struct
import argparse
import serial
import matplotlib.pyplot as plt

MAGIC = b"\xAA\x55"

def send_cmd(ser, s: str):
    ser.write((s.strip() + "\n").encode("ascii"))
    ser.flush()
    time.sleep(0.05)

def read_frames(ser, buf: bytearray):
    """Generator yielding (stream_id, flags, ts_ms_or_None, payload_bytes)."""
    while True:
        chunk = ser.read(512)
        if chunk:
            buf += chunk

        # Find frames in buffer
        while True:
            i = buf.find(MAGIC)
            if i < 0:
                # avoid unbounded growth
                if len(buf) > 4096:
                    del buf[:-64]
                break
            if i > 0:
                del buf[:i]

            # Need at least header: magic(2)+id(1)+flags(1)+len(2) = 6 bytes
            if len(buf) < 6:
                break

            stream_id = buf[2]
            flags = buf[3]
            payload_len = buf[4] | (buf[5] << 8)
            ts_len = 4 if (flags & 0x01) else 0
            total_len = 6 + ts_len + payload_len

            if len(buf) < total_len:
                break

            frame = bytes(buf[:total_len])
            del buf[:total_len]

            off = 6
            ts = None
            if ts_len:
                ts = struct.unpack_from("<I", frame, off)[0]
                off += 4

            payload = frame[off:off + payload_len]
            yield stream_id, flags, ts, payload

        if not chunk:
            # no data right now
            return

def payload_to_channels(payload: bytes, nch: int):
    """Interleaved u8 payload -> list of nch lists."""
    xs = [[] for _ in range(nch)]
    n = len(payload) // nch
    for i in range(n):
        base = i * nch
        for ch in range(nch):
            xs[ch].append(payload[base + ch])
    return xs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="e.g. COM5 or /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--nch", type=int, default=3, help="channel count (interleaving)")
    ap.add_argument("--stream", type=int, default=2, help="block stream id")
    ap.add_argument("--payload", type=int, default=300, help="expected payload length")
    ap.add_argument("--rate", type=int, default=200, help="proto tick rate=Hz (rate=...)")
    ap.add_argument("--block_hz", type=int, default=1000, help="adc.block_hz (fill speed)")
    ap.add_argument("--timestamp", type=int, default=0, choices=[0,1])
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.1)
    time.sleep(2.0)  # allow board reset on open

    # Configure device
    send_cmd(ser, f"!stream:{args.stream}")
    send_cmd(ser, "!format:bin")
    send_cmd(ser, f"!timestamp:{args.timestamp}")
    send_cmd(ser, f"!rate:{args.rate}")
    send_cmd(ser, f"!adc.block_hz:{args.block_hz}")

    print("Configured. Waiting for frames...")

    # Plot setup
    plt.ion()
    fig, ax = plt.subplots()
    lines = []
    for ch in range(args.nch):
        (ln,) = ax.plot([], [], label=f"ch{ch}")
        lines.append(ln)
    ax.set_title(f"Block stream {args.stream} (u8 interleaved, payload={args.payload})")
    ax.set_xlabel("sample")
    ax.set_ylabel("value (0..255)")
    ax.set_ylim(0, 255)
    ax.legend(loc="upper right")

    buf = bytearray()
    last_plot = time.time()
    latest = None  # latest channels

    try:
        while True:
            for stream_id, flags, ts, payload in read_frames(ser, buf):
                if stream_id != args.stream:
                    continue
                if len(payload) != args.payload:
                    print(f"Skipping: stream={stream_id} payload_len={len(payload)} (expected {args.payload})")
                    continue

                chans = payload_to_channels(payload, args.nch)
                latest = chans
                if ts is not None:
                    print(f"Frame ts={ts}ms")

            # Update plot ~20 fps max
            now = time.time()
            if latest is not None and (now - last_plot) > 0.05:
                last_plot = now
                n = len(latest[0])
                x = list(range(n))
                for ch, ln in enumerate(lines):
                    ln.set_data(x, latest[ch])
                ax.set_xlim(0, n - 1 if n > 1 else 1)
                fig.canvas.draw()
                fig.canvas.flush_events()

    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
