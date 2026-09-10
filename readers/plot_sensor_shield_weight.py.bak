#!/usr/bin/env python3
"""
Sensor Shield — Foil vs Strain XY hysteresis plot.

Streams used: 2 (force: foil_g, strain_g)
X axis: strain gauge (g)
Y axis: foil pressure (g)
Colour: fades from blue (old) to red (new) to show hysteresis loop direction.

Usage:
  python plot_sensor_shield_weight.py --port /dev/tty.usbmodemXXXX
"""
import argparse, time
from collections import deque
import numpy as np
import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import serial

N = 500   # points in the trail

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
    send_and_wait(ser, "!stream:+2")   # force only
    ser.reset_input_buffer()
    print("[INFO] Ready. Apply and release force to trace hysteresis loop.")

    foil_buf   = deque(maxlen=N)
    strain_buf = deque(maxlen=N)

    fig, ax = plt.subplots(figsize=(7, 7))
    fig.suptitle("Foil vs Strain — Hysteresis", fontsize=12)
    ax.set_xlabel("Strain gauge (g)")
    ax.set_ylabel("Foil pressure (g)")
    ax.grid(True, alpha=0.3)
    ax.set_aspect("auto")

    # Coloured trail: LineCollection with age-based colour
    lc = LineCollection([], cmap="coolwarm", linewidth=1.2)
    ax.add_collection(lc)
    dot, = ax.plot([], [], "o", color="red", ms=6, zorder=5)

    status = fig.text(0.01, 0.01, "foil=--g  strain=--g",
                      fontsize=8, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])
    def on_key(event):
        if event.key == 'c':
            foil_buf.clear();   foil_buf.clear()
            strain_buf.clear(); strain_buf.clear()
            lc.set_segments([])
            dot.set_data([], [])
            fig.canvas.draw_idle()

    fig.canvas.mpl_connect('key_press_event', on_key)
    plt.show(block=False); plt.pause(0.05)

    rxbuf = b""; last_draw = time.time(); new_data = False
    last_foil = 0.0; last_strain = 0.0

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
                if len(vals) < 3: continue
                try:
                    sid = int(vals[0])
                except ValueError:
                    continue
                if sid == 2 and len(vals) == 3:
                    last_foil   = vals[1]
                    last_strain = vals[2]
                    foil_buf.append(last_foil)
                    strain_buf.append(last_strain)
                    new_data = True

            now = time.time()
            if new_data and (now - last_draw) >= 0.05:
                last_draw = now; new_data = False

                xs = np.array(strain_buf)
                ys = np.array(foil_buf)

                # Build segments for LineCollection
                if len(xs) > 1:
                    pts = np.c_[xs, ys].reshape(-1, 1, 2)
                    segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
                    t = np.linspace(0, 1, len(segs))
                    lc.set_segments(segs)
                    lc.set_array(t)
                    lc.set_clim(0, 1)

                dot.set_data([last_strain], [last_foil])

                # Autoscale with margin
                if (xs.max()-xs.min()) > 0 or (ys.max()-ys.min()) > 0:
                    xm = (xs.max()-xs.min()) * 0.1 or 10
                    ym = (ys.max()-ys.min()) * 0.1 or 10
                    ax.set_xlim(xs.min()-xm, xs.max()+xm)
                    ax.set_ylim(ys.min()-ym, ys.max()+ym)

                status.set_text(f"foil={last_foil:.1f}g  strain={last_strain:.1f}g")
                fig.canvas.draw_idle(); fig.canvas.flush_events()
            else:
                plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser,"!stream:0"); ser.close(); print("\n[INFO] Closed.")

if __name__ == "__main__":
    main()