#!/usr/bin/env python3
"""
Grove GSR + ear-clip heart rate — live monitor.

Stream 1 CSV: gsr(u16), hr_raw(u16)

Layout:
  Top    : GSR strip chart (skin conductance, slow signal)
  Middle : Heart rate raw waveform (fast, shows individual beats)
  Bottom : BPM readout (calculated from peak intervals)

BPM calculation: peak detection on the hr_raw waveform using a
simple threshold crossing with refractory period.

Usage:
  python plot_biosensors.py --port /dev/tty.usbmodemXXXX
"""
import argparse
import time
from collections import deque

import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button, TextBox
import numpy as np

import serial

SAMPLE_HZ = 50.0   # must match firmware rate

def write_cmd(ser, s):
    s = s.strip()
    if not s:
        return
    ser.write((s + "\n").encode("ascii", errors="ignore"))
    ser.flush()

def send_and_wait(ser, cmd, pause=0.15):
    write_cmd(ser, cmd)
    time.sleep(pause)
    while ser.in_waiting:
        ser.readline()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",  required=True)
    ap.add_argument("--baud",  type=int, default=115200)
    ap.add_argument("--chart", type=int, default=300,
                    help="samples shown in chart (300 = 6s at 50Hz)")
    args = ap.parse_args()

    print(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0)
    ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!rate:50")
    send_and_wait(ser, "!stream:1")
    ser.reset_input_buffer()
    print("[INFO] Streaming. Attach GSR electrodes to fingers, ear-clip to ear.")

    N = args.chart
    gsr_buf = deque([0]*N,   maxlen=N)
    hr_buf  = deque([0]*N,   maxlen=N)
    bpm_buf = deque([0.0]*60, maxlen=60)   # BPM history (60 estimates)

    last_gsr = 0
    last_hr  = 0
    last_bpm = 0.0
    gsr_ymin = [0]
    gsr_ymax = [1023]

    # ── peak detection state ──────────────────────────────────────────────────
    # For a clean digital swing (0 ↔ 1023):
    # Detect rising edge (signal crosses threshold LOW→HIGH).
    # Refractory: 300ms minimum between beats (allows up to 200 BPM).
    # IBI sanity: reject intervals outside 30–200 BPM range.
    hr_threshold  = [512]
    refractory    = int(SAMPLE_HZ * 0.3)   # 300ms = 15 samples at 50Hz
    since_last    = [refractory + 1]
    beat_intervals= deque(maxlen=8)
    prev_hr       = [0]
    sample_count  = [0]   # total samples for IBI calculation

    def detect_peak(val):
        """Detect rising edge: was below threshold, now at or above."""
        was_low = prev_hr[0] < hr_threshold[0]
        is_high = val >= hr_threshold[0]
        prev_hr[0] = val
        since_last[0] += 1
        sample_count[0] += 1
        if was_low and is_high and since_last[0] > refractory:
            ibi = since_last[0]
            since_last[0] = 0
            # Sanity: 30–200 BPM → IBI 0.3s–2.0s → 15–100 samples at 50Hz
            if int(SAMPLE_HZ * 0.3) <= ibi <= int(SAMPLE_HZ * 2.0):
                beat_intervals.append(ibi)
            return True
        return False

    def compute_bpm():
        if len(beat_intervals) < 2:
            return 0.0
        avg_ibi = sum(beat_intervals) / len(beat_intervals)
        return 60.0 * SAMPLE_HZ / avg_ibi

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(13, 8))
    fig.suptitle("Biosensors — GSR + Heart Rate", fontsize=12)

    gs = gridspec.GridSpec(3, 2, figure=fig,
                           width_ratios=[2.8, 1.0],
                           height_ratios=[1.2, 1.5, 0.8],
                           hspace=0.45, wspace=0.3)

    ax_gsr = fig.add_subplot(gs[0, 0])
    ax_hr  = fig.add_subplot(gs[1, 0])
    ax_bpm = fig.add_subplot(gs[2, 0])
    ax_pan = fig.add_subplot(gs[:, 1])
    ax_pan.set_visible(False)

    t_ax = list(range(-N, 0))
    t_bpm = list(range(-60, 0))

    # GSR
    gsr_line, = ax_gsr.plot(t_ax, list(gsr_buf), color="steelblue", lw=0.9)
    ax_gsr.set_ylabel("GSR (raw)")
    ax_gsr.set_xlabel("samples")
    ax_gsr.set_ylim(0, 1023)   # overridden by gsr_ymin/gsr_ymax below
    ax_gsr.grid(True, alpha=0.3)
    ax_gsr.set_title("Galvanic Skin Response (slow — attach to 2 fingers)", fontsize=9)

    # Heart rate waveform
    hr_line, = ax_hr.plot(t_ax, list(hr_buf), color="tomato", lw=0.9)
    thr_line = ax_hr.axhline(hr_threshold[0], color="orange", lw=0.8,
                              ls="--", label=f"threshold")
    ax_hr.set_ylabel("HR signal (raw)")
    ax_hr.set_xlabel("samples")
    ax_hr.set_ylim(-50, 1100)
    ax_hr.grid(True, alpha=0.3)
    ax_hr.legend(fontsize=7, loc="upper right")
    ax_hr.set_title("Heart rate waveform (ear-clip on A4) — peaks = beats", fontsize=9)

    # BPM history
    bpm_line, = ax_bpm.plot(t_bpm, list(bpm_buf), color="mediumseagreen", lw=1.2)
    ax_bpm.set_ylabel("BPM")
    ax_bpm.set_xlabel("beat estimates")
    ax_bpm.set_ylim(30, 180)
    ax_bpm.grid(True, alpha=0.3)
    ax_bpm.set_title("Heart rate (BPM)", fontsize=9)

    # Big BPM text
    bpm_text = fig.text(0.74, 0.22,
        "--", fontsize=52, fontweight="bold",
        color="tomato", ha="center", va="center")
    fig.text(0.74, 0.15, "BPM", fontsize=14, color="gray",
             ha="center", va="center")

    status = fig.text(0.01, 0.01,
        "gsr=--  hr=--  bpm=--",
        fontsize=8, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])

    # ── panel ─────────────────────────────────────────────────────────────────
    PX, PW, BH, BG = 0.755, 0.22, 0.048, 0.008

    def lbl(text, y):
        fig.text(PX, y, text, fontsize=7.5, fontweight="bold", color="0.35")

    def mkbtn(text, y, w=1.0, xoff=0.0, color="0.88"):
        ax_b = fig.add_axes([PX + xoff*PW, y, PW*w - 0.003, BH*0.85])
        b = Button(ax_b, text, color=color, hovercolor="0.72")
        b.label.set_fontsize(7.5)
        return b

    y = 0.88
    lbl("── send ──", y + BH*0.1);   y -= BH*0.6
    ax_tb   = fig.add_axes([PX, y, PW, BH*0.9])
    textbox = TextBox(ax_tb, "", initial="!rate:50")
    y -= BH + BG
    btn_send = mkbtn("Send", y, color="0.82"); y -= BH + BG*2

    lbl("── GSR Y range ──", y + BH*0.1); y -= BH*0.6
    fig.text(PX,          y + BH*0.25, "min:", fontsize=7)
    fig.text(PX + PW*0.5, y + BH*0.25, "max:", fontsize=7)
    y -= BH*0.7
    ax_gmin = fig.add_axes([PX,          y, PW*0.44, BH*0.85])
    ax_gmax = fig.add_axes([PX+PW*0.52,  y, PW*0.44, BH*0.85])
    tb_gmin = TextBox(ax_gmin, "", initial="0")
    tb_gmax = TextBox(ax_gmax, "", initial="1023")
    y -= BH + BG

    btn_gsr_set  = mkbtn("set range",  y, w=0.48, color="0.82")
    btn_gsr_auto = mkbtn("auto-fit",   y, w=0.48, xoff=0.52, color="0.78")
    y -= BH + BG*2

    def cb_gsr_set(e):
        try:
            lo = int(tb_gmin.text.strip())
            hi = int(tb_gmax.text.strip())
            if hi > lo:
                gsr_ymin[0] = lo
                gsr_ymax[0] = hi
                log(f"  GSR Y: {lo}–{hi}")
        except ValueError:
            log("  ! invalid range")

    def cb_gsr_auto(e):
        vals = list(gsr_buf)
        lo = min(vals); hi = max(vals)
        span = max(hi - lo, 20)
        margin = int(span * 0.5)
        lo = max(0, lo - margin)
        hi = min(1023, hi + margin)
        gsr_ymin[0] = lo; gsr_ymax[0] = hi
        tb_gmin.set_val(str(lo)); tb_gmax.set_val(str(hi))
        log(f"  GSR auto: {lo}–{hi}")

    btn_gsr_set.on_clicked(cb_gsr_set)
    btn_gsr_auto.on_clicked(cb_gsr_auto)

    lbl("── HR threshold ──", y + BH*0.1); y -= BH*0.6
    fig.text(PX, y + BH*0.25, "threshold (0–1023):", fontsize=7)
    y -= BH*0.7
    ax_thr = fig.add_axes([PX, y, PW, BH*0.85])
    tb_thr = TextBox(ax_thr, "", initial="512")
    y -= BH + BG

    btn_thr = mkbtn("set threshold", y, color="0.80"); y -= BH + BG*2

    lbl("── rate ──", y + BH*0.1);    y -= BH*0.6
    _rate_btns = []
    for ltext, val in [("10 Hz", 10), ("25 Hz", 25), ("50 Hz", 50)]:
        ax_b = fig.add_axes([PX + len(_rate_btns)*(PW/3),
                              y, PW/3-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7.5)
        def mk_rate(v): return lambda e: write_cmd(ser, f"!rate:{v}")
        b.on_clicked(mk_rate(val))
        _rate_btns.append(b)
    y -= BH + BG*2

    lbl("── GSR avg ──", y + BH*0.1); y -= BH*0.6
    lbl("(adjust !adc.window if mod_adc used)", y); y -= BH + BG

    # log
    ax_log = fig.add_axes([PX, 0.02, PW, 0.10])
    ax_log.axis("off")
    log_lines = [""] * 4
    log_text = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")

    def log(msg):
        log_lines.pop(0); log_lines.append(msg[:36])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    def do_send(text):
        cmd = text.strip()
        if cmd:
            write_cmd(ser, cmd)
            log(f">>> {cmd}")
    textbox.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(textbox.text))

    def cb_set_thr(e):
        try:
            t = int(tb_thr.text.strip())
            t = max(0, min(1023, t))
            hr_threshold[0] = t
            thr_line.set_ydata([t, t])
            log(f"  threshold → {t}")
        except ValueError:
            log("  ! invalid threshold")
    btn_thr.on_clicked(cb_set_thr)

    plt.show(block=False)
    plt.pause(0.05)

    # ── receive loop ──────────────────────────────────────────────────────────
    rxbuf     = b""
    last_draw = time.time()
    new_data  = False

    try:
        while plt.fignum_exists(fig.number):
            waiting = ser.in_waiting
            if waiting:
                rxbuf += ser.read(waiting)

            while b"\n" in rxbuf:
                line_b, rxbuf = rxbuf.split(b"\n", 1)
                line = line_b.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) != 2:
                    if not line.startswith(("{", "OK", "ERR")):
                        log(f"  {line[:34]}")
                    continue
                try:
                    gsr = int(parts[0])
                    hr  = int(parts[1])
                    last_gsr = gsr
                    last_hr  = hr
                    gsr_buf.append(gsr)
                    hr_buf.append(hr)

                    # peak detection
                    if detect_peak(hr):
                        last_bpm = compute_bpm()
                        if last_bpm > 0:
                            bpm_buf.append(last_bpm)

                    new_data = True
                except ValueError:
                    log(f"  {line[:34]}")

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False

                t_ax = list(range(-N, 0))
                gsr_line.set_data(t_ax, list(gsr_buf))
                hr_line.set_data(t_ax, list(hr_buf))
                ax_gsr.set_ylim(gsr_ymin[0], gsr_ymax[0])

                t_bpm = list(range(-len(bpm_buf), 0))
                bpm_line.set_data(t_bpm, list(bpm_buf))

                bpm_display = f"{last_bpm:.0f}" if last_bpm > 0 else "--"
                bpm_text.set_text(bpm_display)

                status.set_text(
                    f"gsr={last_gsr:4d}  "
                    f"hr={last_hr:4d}  "
                    f"bpm={last_bpm:.1f}  "
                    f"thr={hr_threshold[0]}"
                )
                fig.canvas.draw_idle()
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