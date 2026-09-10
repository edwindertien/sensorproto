#!/usr/bin/env python3
"""
HC-SR04 Ultrasonic — oscilloscope-style pulse visualiser + distance.

Stream 1: trig_us, echo_us, echo_dur, cm  (4 fields)
  trig_us  = trigger leading edge timestamp (µs from Arduino session start)
  echo_us  = echo leading edge timestamp (µs from session start)
  echo_dur = echo pulse duration (µs), 0 = timeout
  cm       = calculated distance

Layout:
  Top    : Trigger pulse oscilloscope (zoomed to one trigger + echo pair)
  Middle : Echo pulse oscilloscope (same timebase)
  Bottom : Distance strip chart

Timebase control: adjustable window width to zoom in/out on the pulses.
  Wide timebase: see multiple pulse cycles (pulse train)
  Narrow timebase: see trigger+echo gap = acoustic travel time

Usage:
  python plot_us_distance.py --port /dev/tty.usbmodemXXXX
"""
import argparse, time
from collections import deque
import numpy as np
import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button, Slider
import serial

DIST_N = 200   # distance strip chart samples

def write_cmd(ser, s):
    s = s.strip()
    if not s: return
    ser.write((s+"\n").encode("ascii","ignore")); ser.flush()

def send_and_wait(ser, cmd, pause=0.15):
    write_cmd(ser, cmd); time.sleep(pause)
    while ser.in_waiting: ser.readline()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",  required=True)
    ap.add_argument("--baud",  type=int, default=115200)
    ap.add_argument("--rate",  type=int, default=10)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0); ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, f"!rate:{args.rate}")
    send_and_wait(ser, "!stream:+1")
    time.sleep(0.3); ser.reset_input_buffer()
    print("[INFO] Ready.")

    # Keep last N pulse records for oscilloscope view
    PULSE_N = 20   # number of pulses to show in oscilloscope
    pulses  = deque(maxlen=PULSE_N)   # each: (trig_us, echo_us, echo_dur, cm)
    dist_buf = deque([np.nan]*DIST_N, maxlen=DIST_N)
    last_cm  = [0.0]

    # Timebase: width of oscilloscope window in µs
    # Default shows ~2 pulse cycles
    rate_us   = 1_000_000 // args.rate  # period between triggers in µs
    timebase  = [rate_us * 2.5]         # show 2.5 periods by default

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(13, 9))
    fig.suptitle("HC-SR04 Ultrasonic — Oscilloscope View", fontsize=12)

    gs = gridspec.GridSpec(4, 2, figure=fig,
                           width_ratios=[3.0, 1.0],
                           height_ratios=[1.0, 1.0, 0.3, 1.2],
                           hspace=0.5, wspace=0.3)

    # Oscilloscope axes — trigger and echo
    ax_trig = fig.add_subplot(gs[0, 0])
    ax_echo = fig.add_subplot(gs[1, 0])
    ax_sld  = fig.add_subplot(gs[2, 0])   # slider row
    ax_dist = fig.add_subplot(gs[3, 0])

    # Trigger oscilloscope
    ax_trig.set_ylim(-0.2, 1.4)
    ax_trig.set_ylabel("Trigger", fontsize=8)
    ax_trig.set_xlabel("time (µs)", fontsize=7)
    ax_trig.set_title("Trigger pulses  (10µs wide)", fontsize=8)
    ax_trig.grid(True, alpha=0.25)
    ax_trig.axhline(0.5, color="gray", lw=0.4, ls=":")
    trig_lines = []   # drawn per frame

    # Echo oscilloscope
    ax_echo.set_ylim(-0.2, 1.4)
    ax_echo.set_ylabel("Echo", fontsize=8)
    ax_echo.set_xlabel("time (µs)", fontsize=7)
    ax_echo.set_title("Echo pulses  (width = acoustic travel time × 2)", fontsize=8)
    ax_echo.grid(True, alpha=0.25)
    ax_echo.axhline(0.5, color="gray", lw=0.4, ls=":")
    echo_lines = []

    # Timebase slider
    ax_sld.axis("off")
    ax_sl = fig.add_axes([0.07, 0.435, 0.55, 0.018])
    sl_tb = Slider(ax_sl, "Timebase (µs)", 100, rate_us*6,
                   valinit=timebase[0], color="steelblue")
    sl_tb.label.set_fontsize(7); sl_tb.valtext.set_fontsize(7)
    def on_tb(val): timebase[0] = val
    sl_tb.on_changed(on_tb)

    # Distance strip chart
    t_ax = list(range(-DIST_N, 0))
    dist_line, = ax_dist.plot(t_ax, list(dist_buf), color="#e84855", lw=1.0)
    ax_dist.set_ylim(-5, 500)
    ax_dist.set_ylabel("Distance (cm)", fontsize=8)
    ax_dist.set_xlabel("samples", fontsize=7)
    ax_dist.set_title("Distance", fontsize=8)
    ax_dist.grid(True, alpha=0.25)
    ax_dist.axhline(0, color="gray", lw=0.5)

    # Big distance readout
    dist_txt = fig.text(0.76, 0.35, "--",
        fontsize=44, fontweight="bold", color="#e84855",
        ha="center", va="center")
    fig.text(0.76, 0.28, "cm", fontsize=14, color="gray",
             ha="center", va="center")

    status = fig.text(0.01, 0.01,
        "trig=-- echo=-- dur=-- cm=--",
        fontsize=7.5, family="monospace", color="0.35")

    # ── right panel ───────────────────────────────────────────────────────────
    ax_pan = fig.add_subplot(gs[:, 1]); ax_pan.axis("off")
    PX, PW, BH, BG = 0.74, 0.23, 0.044, 0.007

    def lbl(text, y):
        fig.text(PX, y, text, fontsize=7.5, fontweight="bold", color="0.35")
    def mkbtn(text, y, w=1.0, xoff=0.0, color="0.88"):
        ax_b = fig.add_axes([PX+xoff*PW, y, PW*w-0.003, BH*0.85])
        b = Button(ax_b, text, color=color, hovercolor="0.72")
        b.label.set_fontsize(7); return b

    y = 0.88
    lbl("── rate (Hz) ──", y); y -= BH*0.7
    _r_btns = []
    for xi, (ltext, val) in enumerate([("1 Hz","!us.rate:1"),
                                        ("5 Hz","!us.rate:5"),
                                        ("10 Hz","!us.rate:10")]):
        ax_b = fig.add_axes([PX+xi*(PW/3), y, PW/3-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72"); b.label.set_fontsize(7)
        def mk(c): return lambda e: write_cmd(ser, c)
        b.on_clicked(mk(val)); _r_btns.append(b)
    y -= BH + BG*2

    lbl("── timebase ──", y); y -= BH*0.7
    _tb_btns = []
    for xi, (ltext, val) in enumerate([("100µs",100),("1ms",1000),
                                        ("10ms",10000),("100ms",100000),
                                        ("500ms",500000)]):
        bx = PX + (xi%2)*(PW*0.52)
        by = y - (xi//2)*(BH+BG)
        ax_b = fig.add_axes([bx, by, PW*0.48-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72"); b.label.set_fontsize(7)
        def mk(v): return lambda e: (sl_tb.set_val(v), on_tb(v))
        b.on_clicked(mk(val)); _tb_btns.append(b)
    y -= 3*(BH+BG) + BG*2

    lbl("── timeout ──", y); y -= BH*0.7
    _to_btns = []
    for xi, (ltext, val) in enumerate([("1m","!us.timeout:6000"),
                                        ("2m","!us.timeout:12000"),
                                        ("4m","!us.timeout:24000")]):
        ax_b = fig.add_axes([PX+xi*(PW/3), y, PW/3-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72"); b.label.set_fontsize(7)
        def mk(c): return lambda e: write_cmd(ser, c)
        b.on_clicked(mk(val)); _to_btns.append(b)
    y -= BH + BG*2

    lbl("── distance range ──", y); y -= BH*0.7
    _dr_btns = []
    for xi, (ltext, val) in enumerate([("50cm",50),("200cm",200),("500cm",500)]):
        ax_b = fig.add_axes([PX+xi*(PW/3), y, PW/3-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72"); b.label.set_fontsize(7)
        def mk(v): return lambda e: ax_dist.set_ylim(-5, v)
        b.on_clicked(mk(val)); _dr_btns.append(b)

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])
    plt.show(block=False); plt.pause(0.1)

    # ── helpers for oscilloscope waveform ─────────────────────────────────────
    def build_waveform(pulses, t_start, t_end, kind):
        """
        Build a step waveform for oscilloscope display.
        kind='trig': 10µs pulse at trig_us
        kind='echo': pulse from echo_us to echo_us+echo_dur
        Returns (xs, ys) arrays.
        """
        xs = [t_start]
        ys = [0.0]
        for trig_us, echo_us, echo_dur, cm in pulses:
            if kind == 'trig':
                p_start = trig_us
                p_end   = trig_us + 10   # 10µs trigger pulse
            else:
                if echo_dur == 0:        # timeout — no echo
                    continue
                p_start = echo_us
                p_end   = echo_us + echo_dur

            # Normalise to window
            ps = p_start % (t_end - t_start) + t_start if t_end > t_start else p_start
            pe = ps + (p_end - p_start)

            if pe < t_start or ps > t_end:
                continue
            ps = max(ps, t_start)
            pe = min(pe, t_end)

            xs += [ps, ps, pe, pe]
            ys += [0.0, 1.0, 1.0, 0.0]

        xs.append(t_end); ys.append(0.0)
        return xs, ys

    # ── receive loop ──────────────────────────────────────────────────────────
    rxbuf = b""; last_draw = time.time()

    try:
        while plt.fignum_exists(fig.number):
            w = ser.in_waiting
            if w: rxbuf += ser.read(w)

            new_data = False
            while b"\n" in rxbuf:
                lb, rxbuf = rxbuf.split(b"\n", 1)
                line = lb.decode("utf-8","ignore").strip()
                if not line: continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) != 4: continue
                try:
                    trig_us  = float(parts[0])
                    echo_us  = float(parts[1])
                    echo_dur = float(parts[2])
                    cm       = float(parts[3])
                except ValueError:
                    continue

                pulses.append((trig_us, echo_us, echo_dur, cm))
                dist_buf.append(cm if cm > 0 else np.nan)
                last_cm[0] = cm
                new_data = True

            now = time.time()
            if new_data and (now - last_draw) >= 0.05:
                last_draw = now

                # ── oscilloscope view ─────────────────────────────────────────
                if pulses:
                    # Anchor timebase to latest trigger
                    latest = pulses[-1]
                    t_end   = latest[0] + timebase[0]
                    t_start = latest[0]

                    # Trig waveform
                    xs_t, ys_t = build_waveform(pulses, t_start, t_end, 'trig')
                    ax_trig.cla()
                    ax_trig.plot(xs_t, ys_t, color="#2d7dd2", lw=1.5)
                    ax_trig.set_ylim(-0.2, 1.4)
                    ax_trig.set_ylabel("Trigger", fontsize=8)
                    ax_trig.set_xlabel("µs from last trigger", fontsize=7)
                    ax_trig.set_title(f"Trigger pulses  (10µs wide, {args.rate}Hz rate)", fontsize=8)
                    ax_trig.set_xlim(t_start, t_end)
                    ax_trig.grid(True, alpha=0.25)

                    # Echo waveform
                    xs_e, ys_e = build_waveform(pulses, t_start, t_end, 'echo')
                    ax_echo.cla()
                    ax_echo.plot(xs_e, ys_e, color="#e84855", lw=1.5)
                    ax_echo.set_ylim(-0.2, 1.4)
                    ax_echo.set_ylabel("Echo", fontsize=8)
                    ax_echo.set_xlabel("µs from last trigger", fontsize=7)
                    ax_echo.set_title(
                        f"Echo  dur={int(latest[2])}µs → {latest[3]:.1f}cm" if latest[2] > 0
                        else "Echo  (timeout — no object)", fontsize=8)
                    ax_echo.set_xlim(t_start, t_end)
                    ax_echo.grid(True, alpha=0.25)
                    # Mark acoustic gap
                    if latest[2] > 0:
                        gap_start = latest[0] + 10
                        gap_end   = latest[1]
                        ax_echo.axvspan(gap_start, gap_end,
                                        alpha=0.08, color="orange",
                                        label=f"gap={int(gap_end-gap_start)}µs")
                        ax_echo.legend(fontsize=6, loc="upper right")

                # Distance strip chart
                t_ax = list(range(-DIST_N, 0))
                dist_line.set_data(t_ax, list(dist_buf))
                ax_dist.relim(); ax_dist.autoscale_view()

                # Big readout
                if last_cm[0] > 0:
                    dist_txt.set_text(f"{last_cm[0]:.1f}")
                    dist_txt.set_color("#e84855")
                else:
                    dist_txt.set_text("---")
                    dist_txt.set_color("#aaa")

                status.set_text(
                    f"trig={int(latest[0])}µs  "
                    f"echo={int(latest[1])}µs  "
                    f"dur={int(latest[2])}µs  "
                    f"dist={latest[3]:.1f}cm" if pulses else "no data"
                )

                fig.canvas.draw_idle(); fig.canvas.flush_events()

            plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser, "!stream:0"); ser.close(); print("\n[INFO] Closed.")

if __name__ == "__main__":
    main()