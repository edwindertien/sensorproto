#!/usr/bin/env python3
import argparse
import time
from collections import deque

import serial
import matplotlib.pyplot as plt


def send(ser, cmd, echo=True, delay=0.03):
    if not cmd.endswith("\n"):
        cmd += "\n"
    if echo:
        print(f">> {cmd.strip()}")
    ser.write(cmd.encode("utf-8"))
    ser.flush()
    if delay:
        time.sleep(delay)


def parse_sample(line: str, timestamp_enabled: bool):
    """
    Returns (t_dev_seconds_or_None, value_float) or None if not a sample line.
    Expected formats:
      - timestamp off: "<val>"
      - timestamp on (CSV): "<t>,<val>"
    Ignores OK/ERR/JSON lines.
    """
    s = line.strip()
    if not s:
        return None
    if s.startswith("OK") or s.startswith("ERR") or s.startswith("{"):
        return None

    parts = s.split(",")
    try:
        if timestamp_enabled:
            if len(parts) < 2:
                return None
            t_dev = float(parts[0])
            val = float(parts[1])
            return (t_dev, val)
        else:
            val = float(parts[0])
            return (None, val)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser(description="Live plot for Sharp GP2Y0A710 PSD (UniProto CSV) — lag-free")
    ap.add_argument("--port", required=True, help="Serial port, e.g. /dev/tty.usbmodem1101 or COM5")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--stream", type=int, default=5, help="PSD stream id (default 5)")
    ap.add_argument("--rate", type=int, default=50, help="UniProto stream rate Hz")
    ap.add_argument("--window", type=int, default=10, help="Averaging window (psd.window)")
    ap.add_argument("--cal_a", type=float, default=137.5, help="Calibration A for cm = A/(V-B)")
    ap.add_argument("--cal_b", type=float, default=1.125, help="Calibration B for cm = A/(V-B)")
    ap.add_argument("--cm_min", type=float, default=100.0)
    ap.add_argument("--cm_max", type=float, default=550.0)
    ap.add_argument("--seconds", type=float, default=20.0, help="Visible time window")
    ap.add_argument("--plot_hz", type=float, default=20.0, help="Plot update rate (Hz)")
    ap.add_argument("--timestamp", action="store_true", help="Enable device timestamp (adds first CSV column)")
    ap.add_argument("--quiet", action="store_true", help="Less console output")
    ap.add_argument("--drop_backlog", action="store_true", help="Drop backlog if input buffer grows too large")
    ap.add_argument("--drop_threshold", type=int, default=8000, help="Bytes threshold for backlog drop")
    args = ap.parse_args()

    def log(msg):
        if not args.quiet:
            print(msg)

    log(f"[INFO] Opening serial port {args.port} @ {args.baud} ...")
    ser = serial.Serial(args.port, args.baud, timeout=0.02)

    # Uno resets on open
    log("[INFO] Waiting for board reset (2.0s) ...")
    time.sleep(2.0)
    ser.reset_input_buffer()
    log("[INFO] Port opened OK; input buffer cleared.")

    # Configure device
    log("[INFO] Sending configuration ...")
    send(ser, "!format:csv", echo=not args.quiet)
    send(ser, f"!timestamp:{1 if args.timestamp else 0}", echo=not args.quiet)
    send(ser, f"!rate:{args.rate}", echo=not args.quiet)
    send(ser, f"!stream:{args.stream}", echo=not args.quiet)

    # PSD module config
    send(ser, "!psd.mode:5", echo=not args.quiet)            # avg cm
    send(ser, f"!psd.window:{args.window}", echo=not args.quiet)
    send(ser, f"!psd.cal_a:{args.cal_a}", echo=not args.quiet)
    send(ser, f"!psd.cal_b:{args.cal_b}", echo=not args.quiet)
    send(ser, f"!psd.cm_min:{args.cm_min}", echo=not args.quiet)
    send(ser, f"!psd.cm_max:{args.cm_max}", echo=not args.quiet)

    log("[INFO] Config sent. Starting plot. Close window to exit.")
    log("[INFO] Tip: if you still see lag, increase --plot_hz modestly or use --drop_backlog.")

    # Plot setup
    plt.ion()
    fig, ax = plt.subplots()
    (line_plot,) = ax.plot([], [])
    ax.set_xlabel("time (s)")
    ax.set_ylabel("distance (cm)")
    ax.grid(True)

    # Data buffers
    xs = deque()
    ys = deque()

    # Timing
    t0 = time.time()
    next_plot = time.time()
    last_latency_print = time.time()

    # Live stats
    samples_total = 0
    samples_last = 0
    last_rate_check = time.time()

    while plt.fignum_exists(fig.number):
        # Optional backlog drop (keeps you “current” even if plotting hiccups)
        if args.drop_backlog and ser.in_waiting > args.drop_threshold:
            log(f"[WARN] Backlog {ser.in_waiting} bytes -> dropping input buffer to catch up.")
            ser.reset_input_buffer()

        # Drain buffered lines quickly (don’t block UI)
        drained = 0
        max_lines_per_loop = 300  # prevents UI freeze if flooded
        while ser.in_waiting and drained < max_lines_per_loop:
            raw = ser.readline()
            drained += 1
            if not raw:
                break

            s = raw.decode("utf-8", errors="ignore")
            parsed = parse_sample(s, args.timestamp)
            if parsed is None:
                continue

            t_dev, val = parsed
            now = time.time() - t0

            xs.append(now)
            ys.append(val)
            samples_total += 1

            # Keep last N seconds
            win = args.seconds
            while xs and (xs[-1] - xs[0]) > win:
                xs.popleft()
                ys.popleft()

            # Latency print (only meaningful when timestamp enabled)
            if args.timestamp and t_dev is not None:
                # device timestamp is seconds since boot; align to PC by using first sample as reference
                # simplest: estimate "how old is this sample compared to now" relative to wall clock
                # We'll display lag growth, not absolute time sync.
                # Compute approximate lag: (pc_elapsed - (t_dev - t_dev0))
                # Initialize t_dev0 once.
                if not hasattr(main, "_t_dev0"):
                    main._t_dev0 = t_dev
                lag = now - (t_dev - main._t_dev0)
                if (time.time() - last_latency_print) > 1.0:
                    log(f"[INFO] approx lag: {lag:.3f} s (if it grows, Python is falling behind)")
                    last_latency_print = time.time()

        # Print receive rate occasionally
        if (time.time() - last_rate_check) > 1.0:
            hz = samples_total - samples_last
            samples_last = samples_total
            last_rate_check = time.time()
            if not args.quiet:
                print(f"[INFO] rx ~{hz} samples/s, in_waiting={ser.in_waiting} bytes")

        # Plot at fixed rate
        if time.time() >= next_plot:
            next_plot = time.time() + (1.0 / max(1e-6, args.plot_hz))

            if xs:
                line_plot.set_data(list(xs), list(ys))
                ax.set_xlim(max(0.0, xs[-1] - args.seconds), xs[-1] + 0.001)

                ymin, ymax = min(ys), max(ys)
                if ymin == ymax:
                    ymin -= 1.0
                    ymax += 1.0
                ax.set_ylim(ymin - 5.0, ymax + 5.0)

            fig.canvas.draw()
            fig.canvas.flush_events()

        time.sleep(0.001)

    log("[INFO] Closing serial port.")
    ser.close()


if __name__ == "__main__":
    main()
