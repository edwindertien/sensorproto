#!/usr/bin/env python3
"""
Sensor Shield — Potentiometer (A0) vs Hall angle XY plot.

Streams used: 1 (analog, for A0 raw) + 3 (hall deg)
X axis: potentiometer A0 raw ADC (0..675 at 3.3V shield / 5V Arduino)
Y axis: Hall angle (degrees, unwrapped)

Plots the relationship between the reference potentiometer and the
Hall effect rotation sensor — should be a straight line if both are
on the same shaft. Deviation from linearity shows hysteresis or slip.

Usage:
  python plot_sensor_shield_angle.py --port /dev/tty.usbmodemXXXX
"""
import argparse, time
from collections import deque
import numpy as np
import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import serial

N = 500

def write_cmd(ser, s):
    s = s.strip()
    if not s: return
    ser.write((s+"\n").encode("ascii","ignore")); ser.flush()

def send_and_wait(ser, cmd, pause=0.15):
    write_cmd(ser, cmd); time.sleep(pause)
    while ser.in_waiting: ser.readline()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0); ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!rate:20")
    send_and_wait(ser, "!stream:+1")   # analog (for A0)
    send_and_wait(ser, "!stream:+3")   # hall angle
    ser.reset_input_buffer()
    print("[INFO] Ready. Rotate potentiometer slowly through full range.")

    a0_buf   = deque(maxlen=N)
    hall_buf = deque(maxlen=N)

    # Latest values from each stream — paired when both updated
    cur_a0   = [0.0]
    cur_hall = [0.0]

    fig, ax = plt.subplots(figsize=(7, 7))
    fig.suptitle("Potentiometer (A0) vs Hall Angle", fontsize=12)
    ax.set_xlabel("Potentiometer A0 (raw ADC, 0–675)")
    ax.set_ylabel("Hall angle (°)")
    ax.grid(True, alpha=0.3)

    lc = LineCollection([], cmap="coolwarm", linewidth=1.2)
    ax.add_collection(lc)
    dot, = ax.plot([], [], "o", color="red", ms=6, zorder=5)

    # Reference line: ideal linear relationship
    ref_line, = ax.plot([], [], "--", color="gray", lw=0.8,
                        alpha=0.5, label="ideal linear")
    ax.legend(fontsize=8)

    status = fig.text(0.01, 0.01, "A0=--  hall=--°",
                      fontsize=8, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])
    def on_key(event):
        if event.key == 'c':
            a0_buf.clear();   a0_buf.clear()
            hall_buf.clear(); hall_buf.clear()
            lc.set_segments([])
            dot.set_data([], [])
            ref_line.set_data([], [])
            fig.canvas.draw_idle()

    fig.canvas.mpl_connect('key_press_event', on_key)
    plt.show(block=False); plt.pause(0.05)

    rxbuf = b""; last_draw = time.time(); new_data = False

    try:
        while plt.fignum_exists(fig.number):
            w = ser.in_waiting
            if w: rxbuf += ser.read(w)

            while b"\n" in rxbuf:
                lb, rxbuf = rxbuf.split(b"\n", 1)
                line = lb.decode("utf-8","ignore").strip()
                if not line: continue
                parts = [p.strip() for p in line.split(",")]
                try:
                    vals = [float(p) for p in parts]
                except ValueError:
                    continue
                if len(vals) < 2: continue
                try:
                    sid = int(vals[0])
                except ValueError:
                    continue

                if sid == 1 and len(vals) == 7:   # analog: sid,A0,A1,A2,A3,A4,A5
                    cur_a0[0] = vals[1]            # A0 is second field
                    a0_buf.append(cur_a0[0])
                    hall_buf.append(cur_hall[0])
                    new_data = True
                elif sid == 3 and len(vals) == 2:  # hall: sid, deg
                    cur_hall[0] = vals[1]

            now = time.time()
            if new_data and (now - last_draw) >= 0.05:
                last_draw = now; new_data = False

                xs = np.array(a0_buf)
                ys = np.array(hall_buf)

                if len(xs) > 1:
                    pts = np.c_[xs, ys].reshape(-1, 1, 2)
                    segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
                    t = np.linspace(0, 1, len(segs))
                    lc.set_segments(segs)
                    lc.set_array(t)
                    lc.set_clim(0, 1)

                dot.set_data([cur_a0[0]], [cur_hall[0]])

                # Draw ideal linear reference line from min to max of seen data
                if (xs.max()-xs.min()) > 5 and (ys.max()-ys.min()) > 1:
                    xm = (xs.max()-xs.min()) * 0.05
                    ym = (ys.max()-ys.min()) * 0.05
                    ax.set_xlim(xs.min()-xm, xs.max()+xm)
                    ax.set_ylim(ys.min()-ym, ys.max()+ym)
                    # fit and draw reference line
                    coeffs = np.polyfit(xs, ys, 1)
                    xl = np.array([xs.min(), xs.max()])
                    ref_line.set_data(xl, np.polyval(coeffs, xl))

                status.set_text(
                    f"A0={cur_a0[0]:.0f}  hall={cur_hall[0]:.1f}°"
                )
                fig.canvas.draw_idle(); fig.canvas.flush_events()
            else:
                plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser,"!stream:0"); ser.close(); print("\n[INFO] Closed.")

if __name__ == "__main__":
    main()