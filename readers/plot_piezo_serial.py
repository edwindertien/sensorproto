#!/usr/bin/env python3
"""
Piezo plates — waveform strip charts + impact heatmap.

Stream 1: raw A0-A3 ADC at 200Hz (waveforms)
Stream 2: strike events (channel, peak amplitude)

Layout:
  Left  : 4 strip charts — one per piezo
  Right : 2×2 grid of circles, colour = impact intensity (heatmap style)
          Colour fades from last impact over ~2 seconds

Usage:
  python plot_piezo.py --port /dev/tty.usbmodemXXXX
"""
import argparse, time
from collections import deque
import numpy as np
import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
import serial

N = 300   # samples per waveform chart (300/200Hz = 1.5s)
FADE_S = 2.0  # seconds for impact colour to fade

LABELS  = ["A0 — Kick", "A1 — Snare", "A2 — HH closed", "A3 — HH open"]
COLORS  = ["#2d7dd2", "#e84855", "#3bb273", "#f18f01"]
CMAP    = matplotlib.colormaps["YlOrRd"]

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
    ap.add_argument("--threshold", type=int, default=80)
    args = ap.parse_args()

    # Leonardo: open port WITHOUT asserting DTR/RTS to avoid bootloader reset.
    # Standard pyserial open asserts DTR which resets Leonardo into bootloader.
    ser = serial.Serial()
    ser.port     = args.port
    ser.baudrate = args.baud
    ser.timeout  = 0.1
    ser.dtr      = False   # critical: don't reset into bootloader
    ser.rts      = False
    ser.open()
    print("[INFO] Port opened (DTR suppressed).")

    # Short settle — sketch is already running, no boot wait needed
    time.sleep(0.5)
    ser.reset_input_buffer()

    send_and_wait(ser, "!format:csv",                  pause=0.2)
    send_and_wait(ser, "!timestamp:0",                 pause=0.2)
    send_and_wait(ser, "!rate:200",                    pause=0.2)
    send_and_wait(ser, f"!piezo.thr:{args.threshold}", pause=0.2)
    send_and_wait(ser, "!stream:+1",                   pause=0.2)
    send_and_wait(ser, "!stream:+2",                   pause=0.2)
    ser.timeout = 0.0
    ser.reset_input_buffer()
    print("[INFO] Ready. Hit the piezo plates!")

    bufs  = [deque([512.0]*N, maxlen=N) for _ in range(4)]
    last  = [512.0] * 4

    # Impact state: (peak 0-512, time of impact)
    impacts = [(0, 0.0)] * 4   # (peak, timestamp)

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(13, 8))
    fig.suptitle("Piezo Drum Pads", fontsize=12)

    gs = gridspec.GridSpec(4, 2, figure=fig,
                           width_ratios=[2.5, 1.0],
                           hspace=0.45, wspace=0.3)

    t_ax = list(range(-N, 0))
    ax_waves = []
    lines    = []
    for i in range(4):
        ax = fig.add_subplot(gs[i, 0])
        l, = ax.plot(t_ax, list(bufs[i]), color=COLORS[i], lw=0.8)
        ax.axhline(512, color="gray", lw=0.5)
        ax.set_ylim(0, 1023)
        ax.set_ylabel(LABELS[i], fontsize=7)
        ax.tick_params(labelsize=6)
        ax.grid(True, alpha=0.25)
        ax_waves.append(ax)
        lines.append(l)

    # ── heatmap circles ───────────────────────────────────────────────────────
    ax_pad = fig.add_subplot(gs[:, 1])
    ax_pad.set_xlim(0, 2); ax_pad.set_ylim(0, 2)
    ax_pad.set_aspect("equal")
    ax_pad.axis("off")
    ax_pad.set_title("Impact intensity", fontsize=9)

    # 2×2 grid positions: (col, row) → (x, y) centre
    POS = [(0.5, 1.5), (1.5, 1.5), (0.5, 0.5), (1.5, 0.5)]  # TL, TR, BL, BR
    circles = []
    pad_labels = []
    norm = Normalize(vmin=0, vmax=512)
    sm   = ScalarMappable(cmap=CMAP, norm=norm)

    for i, (cx, cy) in enumerate(POS):
        c = mpatches.Circle((cx, cy), 0.38,
                             facecolor="#eee", edgecolor="#ccc",
                             linewidth=2.0, zorder=2)
        ax_pad.add_patch(c)
        circles.append(c)
        ax_pad.text(cx, cy - 0.48, LABELS[i].split("—")[1].strip(),
                    ha="center", fontsize=7, color="#555")
        ax_pad.text(cx, cy, f"A{i}",
                    ha="center", va="center", fontsize=10,
                    fontweight="bold", color="#888", zorder=3)
        pad_labels.append(ax_pad.text(cx, cy + 0.48, "",
                    ha="center", fontsize=7.5, color="#333", zorder=3))

    # Colourbar
    cbar = fig.colorbar(sm, ax=ax_pad, orientation="horizontal",
                        fraction=0.04, pad=0.02)
    cbar.set_label("Peak amplitude", fontsize=7)
    cbar.ax.tick_params(labelsize=6)

    status = fig.text(0.01, 0.01,
        "A0=-- A1=-- A2=-- A3=--",
        fontsize=8, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])
    plt.show(block=False); plt.pause(0.05)

    # ── receive ───────────────────────────────────────────────────────────────
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

                if len(vals) == 5 and int(vals[0]) == 1:   # sid=1, A0-A3
                    for i in range(4):
                        bufs[i].append(vals[i+1])
                        last[i] = vals[i+1]
                    new_data = True
                elif len(vals) == 4:      # no sid prefix, A0-A3
                    for i in range(4):
                        bufs[i].append(vals[i])
                        last[i] = vals[i]
                    new_data = True
                elif len(vals) == 3 and int(vals[0]) == 2:  # sid=2, ch, peak
                    ch   = int(vals[1])
                    peak = vals[2]
                    if 0 <= ch < 4:
                        impacts[ch] = (peak, time.time())
                elif len(vals) == 2:      # no sid prefix, ch, peak
                    try:
                        ch   = int(vals[0])
                        peak = vals[1]
                        if 0 <= ch < 4:
                            impacts[ch] = (peak, time.time())
                    except (ValueError, IndexError):
                        pass

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False
                t_ax = list(range(-N, 0))

                # Update waveforms
                for i in range(4):
                    lines[i].set_data(t_ax, list(bufs[i]))

                # Update circles with faded colour
                for i, (cx, cy) in enumerate(POS):
                    peak, t_hit = impacts[i]
                    age = now - t_hit
                    fade = max(0.0, 1.0 - age / FADE_S)
                    effective = peak * fade
                    rgba = sm.to_rgba(effective)
                    circles[i].set_facecolor(rgba)
                    if age < FADE_S and peak > 0:
                        pad_labels[i].set_text(f"{int(effective)}")
                    else:
                        pad_labels[i].set_text("")

                status.set_text(
                    f"A0={last[0]:.0f}  A1={last[1]:.0f}  "
                    f"A2={last[2]:.0f}  A3={last[3]:.0f}"
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