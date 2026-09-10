#!/usr/bin/env python3
"""
ADNS2610 motion visualiser — stream 6 (dx, dy)

Left panel : accumulated cursor position (XY trail)
Right panel: rolling strip chart of raw dx and dy

Usage:
  python plot_adns_motion.py --port /dev/tty.usbmodemXXXX
  python plot_adns_motion.py --port /dev/tty.usbmodemXXXX --rate 50 --trail 300
"""
import argparse
import time
from collections import deque

import matplotlib
matplotlib.use("MacOSX")   # Linux: change to "TkAgg" or "Qt5Agg"
import matplotlib.pyplot as plt
import numpy as np
import serial

# ── serial helpers ────────────────────────────────────────────────────────────

def write_cmd(ser, s):
    if not s.endswith("\n"):
        s += "\n"
    ser.write(s.encode("ascii", errors="ignore"))
    ser.flush()

def send_and_wait(ser, cmd, pause=0.12):
    write_cmd(ser, cmd)
    time.sleep(pause)
    while ser.in_waiting:
        ser.readline()

def parse_motion_csv(line: str):
    """Stream 6 CSV: dx,dy — two signed integers."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",  required=True)
    ap.add_argument("--baud",  type=int, default=115200)
    ap.add_argument("--rate",  type=int, default=50,  help="stream rate in Hz")
    ap.add_argument("--trail", type=int, default=200, help="cursor trail length (samples)")
    ap.add_argument("--chart", type=int, default=150, help="strip chart width (samples)")
    args = ap.parse_args()

    print(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.0)  # non-blocking
    time.sleep(2.0)
    ser.reset_input_buffer()

    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, f"!rate:{args.rate}")
    send_and_wait(ser, "!stream:6")
    ser.reset_input_buffer()   # discard anything queued during setup
    print("[INFO] Streaming — move sensor over a surface. Ctrl+C to quit.")

    # ── data buffers ──────────────────────────────────────────────────────────
    cx, cy = 0.0, 0.0
    trail_x = deque([0.0], maxlen=args.trail)
    trail_y = deque([0.0], maxlen=args.trail)
    dx_buf  = deque([0] * args.chart, maxlen=args.chart)
    dy_buf  = deque([0] * args.chart, maxlen=args.chart)
    t_head  = 0

    # ── figure ────────────────────────────────────────────────────────────────
    plt.ion()
    fig, (ax_xy, ax_dxy) = plt.subplots(1, 2, figsize=(11, 5))
    fig.suptitle("ADNS2610 — motion stream 6", fontsize=11)

    ax_xy.set_aspect("equal")
    ax_xy.set_title("cursor trail")
    ax_xy.set_xlabel("x (counts)")
    ax_xy.set_ylabel("y (counts)")
    ax_xy.grid(True, alpha=0.3)
    trail_line, = ax_xy.plot([], [], "-", linewidth=0.8, alpha=0.6, color="steelblue")
    cursor_dot, = ax_xy.plot([], [], "o", markersize=7, color="tomato")
    ax_xy.set_xlim(-200, 200)
    ax_xy.set_ylim(-200, 200)

    ax_dxy.set_title("dx / dy")
    ax_dxy.set_xlabel("samples")
    ax_dxy.set_ylabel("counts")
    ax_dxy.grid(True, alpha=0.3)
    ax_dxy.axhline(0, color="gray", linewidth=0.5)
    t_axis = list(range(-args.chart, 0))
    dx_line, = ax_dxy.plot(t_axis, list(dx_buf), color="steelblue", linewidth=0.9, label="dx")
    dy_line, = ax_dxy.plot(t_axis, list(dy_buf), color="tomato",    linewidth=0.9, label="dy")
    ax_dxy.legend(loc="upper right", fontsize=8)
    ax_dxy.set_ylim(-30, 30)
    ax_dxy.set_xlim(-args.chart, 0)

    plt.tight_layout()
    plt.show(block=False)
    plt.pause(0.05)

    DRAW_INTERVAL = 0.04        # ~25 fps
    last_draw     = time.time()
    rxbuf         = b""
    new_data      = False

    try:
        while plt.fignum_exists(fig.number):

            # ── drain everything available right now ───────────────────────
            # Read in chunks until the OS buffer is empty, then process only
            # the lines we got. This prevents lag from building up.
            waiting = ser.in_waiting
            if waiting:
                rxbuf += ser.read(waiting)

            # parse all complete lines in the buffer
            while b"\n" in rxbuf:
                line_bytes, rxbuf = rxbuf.split(b"\n", 1)
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if not line or line.startswith(("{", "OK", "ERR")):
                    continue
                parsed = parse_motion_csv(line)
                if parsed is None:
                    continue
                dx, dy = parsed
                cx += dx
                cy += dy
                trail_x.append(cx)
                trail_y.append(cy)
                t_head += 1
                dx_buf.append(dx)
                dy_buf.append(dy)
                new_data = True

            # ── redraw at fixed rate ───────────────────────────────────────
            now = time.time()
            if new_data and (now - last_draw) >= DRAW_INTERVAL:
                last_draw = now
                new_data  = False

                # XY trail
                tx = list(trail_x)
                ty = list(trail_y)
                trail_line.set_data(tx, ty)
                cursor_dot.set_data([tx[-1]], [ty[-1]])

                # auto-expand XY axes
                margin = 50
                xlo, xhi = ax_xy.get_xlim()
                ylo, yhi = ax_xy.get_ylim()
                changed = False
                if cx - margin < xlo: xlo = cx - margin * 3; changed = True
                if cx + margin > xhi: xhi = cx + margin * 3; changed = True
                if cy - margin < ylo: ylo = cy - margin * 3; changed = True
                if cy + margin > yhi: yhi = cy + margin * 3; changed = True
                if changed:
                    ax_xy.set_xlim(xlo, xhi)
                    ax_xy.set_ylim(ylo, yhi)

                # strip chart — x axis is always "last N samples ago"
                t_axis = list(range(-args.chart, 0))
                dx_line.set_data(t_axis, list(dx_buf))
                dy_line.set_data(t_axis, list(dy_buf))

                peak = max(max(abs(v) for v in dx_buf),
                           max(abs(v) for v in dy_buf), 5)
                ax_dxy.set_ylim(-peak * 1.3, peak * 1.3)

                fig.canvas.draw()
                fig.canvas.flush_events()
            else:
                plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser, "!stream:0")
        ser.close()
        print("\n[INFO] Closed.")

if __name__ == "__main__":
    main()