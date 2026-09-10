#!/usr/bin/env python3
"""
IR anemometer — waveform + RPM + wind speed monitor.

Stream 1: raw photodiode signal (u16) at 200Hz
Stream 2: rpm(f32), mps(f32), thr(u16) at 1Hz from firmware

Layout:
  Top    : raw waveform strip chart with threshold line
  Middle : RPM strip chart
  Bottom : Wind speed strip chart
  Right  : Controls — threshold (auto/manual), calibration

Usage:
  python plot_wind_speed.py --port /dev/tty.usbmodemXXXX
"""
import argparse
import time
from collections import deque
import numpy as np

import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button, TextBox
import serial

SAMPLE_HZ = 200.0

def write_cmd(ser, s):
    s = s.strip()
    if not s:
        return
    print(f">>> {s}", flush=True)
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
    ap.add_argument("--chart", type=int, default=400,
                    help="raw samples shown (400 = 2s at 200Hz)")
    args = ap.parse_args()

    print(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0)
    ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!rate:200")
    send_and_wait(ser, "!stream:+1")   # raw waveform
    send_and_wait(ser, "!stream:+2")   # RPM/speed
    ser.reset_input_buffer()
    print("[INFO] Streaming.")

    N = args.chart
    raw_buf = deque([0]*N,    maxlen=N)
    rpm_buf = deque([0.0]*60, maxlen=60)
    mps_buf = deque([0.0]*60, maxlen=60)

    last_raw = [0]
    last_rpm = [0.0]
    last_mps = [0.0]
    threshold = [512]
    auto_mode = [True]   # auto threshold = midpoint of signal range

    # Python-side pulse counting (mirrors firmware, used for auto threshold)
    prev_raw   = [0]
    refractory = [int(SAMPLE_HZ * 0.02)]   # 20ms refractory
    since_last = [refractory[0] + 1]
    beat_count = [0]
    window_raw_buf = deque(maxlen=int(SAMPLE_HZ))  # 1s of raw for auto threshold

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(13, 8))
    fig.suptitle("IR Anemometer — Photodiode Pulse Counter", fontsize=12)

    gs = gridspec.GridSpec(3, 2, figure=fig,
                           width_ratios=[2.8, 1.0],
                           height_ratios=[1.5, 1.0, 1.0],
                           hspace=0.45, wspace=0.3)

    ax_raw = fig.add_subplot(gs[0, 0])
    ax_rpm = fig.add_subplot(gs[1, 0])
    ax_mps = fig.add_subplot(gs[2, 0])
    ax_pan = fig.add_subplot(gs[:, 1])
    ax_pan.set_visible(False)

    t_raw = list(range(-N, 0))
    t_60  = list(range(-60, 0))

    raw_line,  = ax_raw.plot(t_raw, list(raw_buf), color="steelblue", lw=0.8)
    thr_line   = ax_raw.axhline(threshold[0], color="tomato", lw=1.0,
                                ls="--", label="threshold")
    ax_raw.set_ylabel("ADC counts")
    ax_raw.set_xlabel("samples")
    ax_raw.set_ylim(0, 1023)
    ax_raw.grid(True, alpha=0.3)
    ax_raw.legend(fontsize=7, loc="upper right")
    ax_raw.set_title("Raw photodiode signal — blade passages = dips", fontsize=9)

    rpm_line, = ax_rpm.plot(t_60, list(rpm_buf), color="mediumseagreen", lw=1.2)
    ax_rpm.set_ylabel("RPM")
    ax_rpm.set_xlabel("seconds")
    ax_rpm.set_ylim(0, 1000)
    ax_rpm.grid(True, alpha=0.3)
    ax_rpm.set_title("Rotation speed (RPM)", fontsize=9)

    mps_line, = ax_mps.plot(t_60, list(mps_buf), color="orange", lw=1.2)
    ax_mps.set_ylabel("m/s")
    ax_mps.set_xlabel("seconds")
    ax_mps.set_ylim(0, 20)
    ax_mps.grid(True, alpha=0.3)
    ax_mps.set_title("Wind speed (m/s) — calibrate with wind.blades and wind.circ", fontsize=9)

    status = fig.text(0.01, 0.01,
        "raw=--  rpm=--  mps=--  thr=--",
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
    textbox = TextBox(ax_tb, "", initial="!wind.thr:512")
    y -= BH + BG
    btn_send = mkbtn("Send", y, color="0.82"); y -= BH + BG*2

    lbl("── threshold ──", y + BH*0.1); y -= BH*0.6
    btn_auto = mkbtn("auto (midpoint)", y, w=0.48, color="0.78")
    btn_man  = mkbtn("manual",          y, w=0.48, xoff=0.52)
    y -= BH + BG
    ax_thr = fig.add_axes([PX, y, PW, BH*0.85])
    tb_thr = TextBox(ax_thr, "", initial="512")
    y -= BH + BG
    btn_thr_set = mkbtn("set threshold", y, color="0.80"); y -= BH + BG*2

    lbl("── calibration ──", y + BH*0.1); y -= BH*0.6
    fig.text(PX, y+BH*0.25, "blades:", fontsize=7)
    y -= BH*0.7
    ax_bl = fig.add_axes([PX, y, PW, BH*0.85])
    tb_bl = TextBox(ax_bl, "", initial="3")
    y -= BH + BG
    btn_bl = mkbtn("set blades", y); y -= BH + BG

    fig.text(PX, y+BH*0.25, "circumference (m):", fontsize=7)
    y -= BH*0.7
    ax_ci = fig.add_axes([PX, y, PW, BH*0.85])
    tb_ci = TextBox(ax_ci, "", initial="0.05")
    y -= BH + BG
    btn_ci = mkbtn("set circ", y); y -= BH + BG*2

    lbl("── rate ──", y + BH*0.1); y -= BH*0.6
    _rate_btns = []
    for ltext, val in [("50Hz",50),("100Hz",100),("200Hz",200)]:
        ax_b = fig.add_axes([PX + len(_rate_btns)*(PW/3),
                              y, PW/3-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7.5)
        def mk_rate(v): return lambda e: write_cmd(ser, f"!rate:{v}")
        b.on_clicked(mk_rate(val))
        _rate_btns.append(b)

    # log
    ax_log = fig.add_axes([PX, 0.02, PW, 0.08])
    ax_log.axis("off")
    log_lines = [""] * 3
    log_text = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")

    def log(msg):
        print(msg, flush=True)
        log_lines.pop(0); log_lines.append(msg[:36])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    def do_send(text):
        cmd = text.strip()
        if cmd: write_cmd(ser, cmd); log(f">>> {cmd}")
    textbox.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(textbox.text))

    def apply_threshold(t):
        threshold[0] = t
        thr_line.set_ydata([t, t])
        write_cmd(ser, f"!wind.thr:{t}")
        tb_thr.set_val(str(t))
        log(f"  threshold → {t}")

    def cb_auto(e):
        auto_mode[0] = True
        vals = list(raw_buf)
        lo = min(vals); hi = max(vals)
        mid = (lo + hi) // 2
        apply_threshold(mid)
        log(f"  auto: [{lo}–{hi}] → {mid}")

    def cb_manual(e):
        auto_mode[0] = False
        log("  manual threshold mode")

    def cb_thr_set(e):
        auto_mode[0] = False
        try:
            t = int(tb_thr.text.strip())
            apply_threshold(max(0, min(1023, t)))
        except ValueError:
            log("  ! invalid threshold")

    btn_auto.on_clicked(cb_auto)
    btn_man.on_clicked(cb_manual)
    btn_thr_set.on_clicked(cb_thr_set)

    def cb_blades(e):
        try:
            b = int(tb_bl.text.strip())
            write_cmd(ser, f"!wind.blades:{b}")
            log(f"  blades → {b}")
        except ValueError:
            log("  ! invalid blade count")

    def cb_circ(e):
        try:
            c = float(tb_ci.text.strip())
            write_cmd(ser, f"!wind.circ:{c:.4f}")
            log(f"  circ → {c:.4f}m")
        except ValueError:
            log("  ! invalid circumference")

    btn_bl.on_clicked(cb_blades)
    btn_ci.on_clicked(cb_circ)

    plt.show(block=False)
    plt.pause(0.05)

    # ── receive loop ──────────────────────────────────────────────────────────
    rxbuf     = b""
    last_draw = time.time()
    new_raw   = False
    new_wind  = False
    line_count = [0]

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

                # Stream 1: single u16
                if len(parts) == 1:
                    try:
                        raw = int(parts[0])
                        last_raw[0] = raw
                        raw_buf.append(raw)
                        window_raw_buf.append(raw)
                        new_raw = True

                        # auto threshold update every 100 samples
                        line_count[0] += 1
                        if auto_mode[0] and line_count[0] % 100 == 0:
                            vals = list(window_raw_buf)
                            lo = min(vals); hi = max(vals)
                            if hi - lo > 20:  # only if signal has swing
                                mid = (lo + hi) // 2
                                if abs(mid - threshold[0]) > 5:
                                    apply_threshold(mid)
                    except ValueError:
                        pass

                # Stream 2: rpm, mps, thr
                elif len(parts) == 3:
                    try:
                        rpm = float(parts[0])
                        mps = float(parts[1])
                        thr = int(parts[2])
                        last_rpm[0] = rpm
                        last_mps[0] = mps
                        rpm_buf.append(rpm)
                        mps_buf.append(mps)
                        # sync threshold from firmware
                        if not auto_mode[0] and thr != threshold[0]:
                            threshold[0] = thr
                            thr_line.set_ydata([thr, thr])
                        new_wind = True
                    except ValueError:
                        pass
                else:
                    if not line.startswith(("{","OK","ERR")):
                        log(f"  {line[:34]}")

            now = time.time()
            if (new_raw or new_wind) and (now - last_draw) >= 0.04:
                last_draw = now
                new_raw = False; new_wind = False

                t_raw = list(range(-N, 0))
                raw_line.set_data(t_raw, list(raw_buf))
                # autoscale raw chart with margin
                vals = list(raw_buf)
                lo = min(vals); hi = max(vals)
                span = max(hi - lo, 30)
                ax_raw.set_ylim(lo - span*0.3, hi + span*0.3)

                t_60 = list(range(-len(rpm_buf), 0))
                rpm_line.set_data(t_60, list(rpm_buf))
                mps_line.set_data(t_60, list(mps_buf))
                ax_rpm.relim(); ax_rpm.autoscale_view()
                ax_mps.relim(); ax_mps.autoscale_view()

                status.set_text(
                    f"raw={last_raw[0]:4d}  "
                    f"rpm={last_rpm[0]:6.1f}  "
                    f"mps={last_mps[0]:.2f}  "
                    f"thr={threshold[0]}  "
                    f"{'AUTO' if auto_mode[0] else 'MAN'}"
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