#!/usr/bin/env python3
"""
Variable capacitor — dual strip chart (raw ADC + calculated pF) + tuning panel.

Capacitance from RC charge equation:
  C = -t / (R * ln(1 - V/Vcc))
  where t = charge delay (s), R = 10MΩ, V = ADC * Vcc/1023

Usage:
  python plot_cap_sense.py --port /dev/tty.usbmodemXXXX
"""
import argparse
import math
import time
from collections import deque

import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button, TextBox
import serial

# ── physics ───────────────────────────────────────────────────────────────────
R_OHM   = 10e6     # 10 MΩ charge resistor
VCC     = 5.0      # Arduino Vcc
ADC_MAX = 1023.0

def adc_to_pf(adc, delay_us):
    """Convert ADC count to capacitance in pF using RC charge equation."""
    v = adc / ADC_MAX * VCC
    # Clamp to avoid log(0) or log(negative)
    ratio = v / VCC
    ratio = max(0.001, min(0.999, ratio))
    t = delay_us * 1e-6   # µs → s
    c = -t / (R_OHM * math.log(1.0 - ratio))
    return c * 1e12        # F → pF

# ── serial ────────────────────────────────────────────────────────────────────

def write_cmd(ser, s):
    s = s.strip()
    if not s:
        return
    print(f">>> {s}", flush=True)
    ser.write((s + "\n").encode("ascii", errors="ignore"))
    ser.flush()

def send_and_wait(ser, cmd, pause=0.12):
    write_cmd(ser, cmd)
    time.sleep(pause)
    while ser.in_waiting:
        ser.readline()

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",     required=True)
    ap.add_argument("--baud",     type=int,   default=115200)
    ap.add_argument("--rate",     type=int,   default=20)
    ap.add_argument("--chart",    type=int,   default=200)
    ap.add_argument("--delay_us", type=int,   default=200,
                    help="charge delay in µs — must match !cap.delay on Arduino")
    args = ap.parse_args()

    # current delay and mode — updated when buttons clicked
    delay_us = [args.delay_us]
    mode     = [0]   # 0=analog voltage, 1=count-to-threshold

    print(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0)
    ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, f"!rate:{args.rate}")
    send_and_wait(ser, "!stream:1")
    ser.reset_input_buffer()
    print("[INFO] Streaming.")

    N       = args.chart
    raw_buf = deque([0]*N,   maxlen=N)
    pf_buf  = deque([0.0]*N, maxlen=N)
    last_raw = [0]
    last_pf  = [0.0]
    ref_raw  = [0]

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(12, 6))
    fig.suptitle("Variable capacitor — RC cap sense", fontsize=11)

    gs = gridspec.GridSpec(2, 2, figure=fig,
                           width_ratios=[2.2, 1.0],
                           hspace=0.45, wspace=0.35)

    ax_raw = fig.add_subplot(gs[0, 0])
    ax_pf  = fig.add_subplot(gs[1, 0])
    ax_pan = fig.add_subplot(gs[:, 1])
    ax_pan.set_visible(False)

    t_ax = list(range(-N, 0))

    raw_line, = ax_raw.plot(t_ax, list(raw_buf), color="steelblue", lw=0.9)
    ref_hline = ax_raw.axhline(0, color="tomato", lw=0.8, ls="--", label="ref")
    ax_raw.set_ylabel("ADC counts")
    ax_raw.set_xlabel("samples")
    ax_raw.grid(True, alpha=0.3)
    ax_raw.legend(fontsize=7, loc="upper left")

    pf_line,  = ax_pf.plot(t_ax, list(pf_buf), color="mediumseagreen", lw=0.9)
    ax_pf.set_ylabel("capacitance (pF)")
    ax_pf.set_xlabel("samples")
    ax_pf.grid(True, alpha=0.3)

    status = fig.text(0.01, 0.01,
        "raw=--   pF=--   ref=--   delay=--µs",
        fontsize=8, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])

    # ── panel ─────────────────────────────────────────────────────────────────
    PX = 0.72
    PW = 0.26
    BH = 0.055
    BG = 0.008

    def label(text, y):
        fig.text(PX, y, text, fontsize=7.5, fontweight="bold", color="0.35")

    def mkbtn(text, y, w=1.0, xoff=0.0, color="0.88"):
        ax_b = fig.add_axes([PX + xoff*PW, y, PW*w - 0.004, BH*0.85])
        b = Button(ax_b, text, color=color, hovercolor="0.72")
        b.label.set_fontsize(7.5)
        return b

    y = 0.87
    label("── send ──", y + BH*0.1);          y -= BH*0.55
    ax_tb   = fig.add_axes([PX, y, PW, BH*0.9])
    textbox = TextBox(ax_tb, "", initial="!cap.delay:200")
    y -= BH + BG
    btn_send = mkbtn("Send", y, color="0.82"); y -= BH + BG*2

    label("── reference ──", y + BH*0.1);     y -= BH*0.55
    btn_ref  = mkbtn("set ref", y);            y -= BH + BG*2

    label("── mode ──", y + BH*0.1);           y -= BH*0.55
    btn_m0 = mkbtn("mode 0  analog",  y, w=0.48,       color="0.80")
    btn_m1 = mkbtn("mode 1  count",   y, w=0.48, xoff=0.52)
    y -= BH + BG*2

    label("── charge delay ──", y + BH*0.1);  y -= BH*0.55
    _delay_btns = []
    for i, (lbl, val) in enumerate([("50µs",50),("200µs",200),
                                     ("500µs",500),("2ms",2000)]):
        bx = PX + (i % 2) * PW * 0.52
        by = y - (i // 2) * (BH + BG)
        ax_b = fig.add_axes([bx, by, PW*0.48-0.004, BH*0.85])
        b = Button(ax_b, lbl, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7.5)
        def mk_delay(v):
            def cb(e):
                delay_us[0] = v
                write_cmd(ser, f"!cap.delay:{v}")
                log(f"  delay → {v}µs")
            return cb
        b.on_clicked(mk_delay(val))
        _delay_btns.append(b)
    y -= 2*(BH + BG) + BG*2

    label("── samples ──", y + BH*0.1);       y -= BH*0.55
    _samp_btns = []
    for i, (lbl, val) in enumerate([("1",1),("4",4),("8",8),("16",16)]):
        bx = PX + (i % 2) * PW * 0.52
        by = y - (i // 2) * (BH + BG)
        ax_b = fig.add_axes([bx, by, PW*0.48-0.004, BH*0.85])
        b = Button(ax_b, f"avg {lbl}", color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7.5)
        def mk_samp(v):
            def cb(e): write_cmd(ser, f"!cap.samples:{v}")
            return cb
        b.on_clicked(mk_samp(val))
        _samp_btns.append(b)
    y -= 2*(BH + BG) + BG*2

    label("── rate ──", y + BH*0.1);          y -= BH*0.55
    _rate_btns = []
    for i, (lbl, val) in enumerate([("5Hz",5),("20Hz",20),("50Hz",50)]):
        ax_b = fig.add_axes([PX + i*(PW/3), y, PW/3-0.004, BH*0.85])
        b = Button(ax_b, lbl, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7.5)
        def mk_rate(v):
            def cb(e): write_cmd(ser, f"!rate:{v}")
            return cb
        b.on_clicked(mk_rate(val))
        _rate_btns.append(b)

    # log strip
    ax_log = fig.add_axes([PX, 0.02, PW, 0.09])
    ax_log.axis("off")
    log_lines = [""] * 4
    log_text  = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")

    def log(msg):
        print(msg, flush=True)
        log_lines.pop(0)
        log_lines.append(msg[:36])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    # ── callbacks ─────────────────────────────────────────────────────────────
    def do_send(text):
        cmd = text.strip()
        if cmd:
            write_cmd(ser, cmd)
    textbox.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(textbox.text))

    def cb_ref(e):
        ref_raw[0] = last_raw[0]
        ref_hline.set_ydata([ref_raw[0], ref_raw[0]])
        log(f"  ref = {ref_raw[0]}  ({last_pf[0]:.1f} pF)")
    btn_ref.on_clicked(cb_ref)

    def cb_m0(e):
        mode[0] = 0
        write_cmd(ser, "!cap.mode:0")
        ax_pf.set_ylabel("capacitance (pF)")
        log("  mode 0 — analog voltage → pF")
    def cb_m1(e):
        mode[0] = 1
        write_cmd(ser, "!cap.mode:1")
        ax_pf.set_ylabel("count (relative, mode 1)")
        log("  mode 1 — count to threshold")
    btn_m0.on_clicked(cb_m0)
    btn_m1.on_clicked(cb_m1)

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
                text = line_b.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue
                if not text[0].lstrip("-").isdigit():
                    log(f"  {text}")
                    continue
                try:
                    raw = int(text)
                    if mode[0] == 0:
                        pf = adc_to_pf(raw, delay_us[0])
                    else:
                        pf = float(raw)   # counts — relative, no conversion
                    last_raw[0] = raw
                    last_pf[0]  = pf
                    raw_buf.append(raw)
                    pf_buf.append(pf)
                    new_data = True
                except ValueError:
                    pass

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False
                t_ax = list(range(-N, 0))
                raw_line.set_data(t_ax, list(raw_buf))
                pf_line.set_data(t_ax, list(pf_buf))
                ax_raw.relim(); ax_raw.autoscale_view()
                ax_pf.relim();  ax_pf.autoscale_view()
                delta = last_raw[0] - ref_raw[0]
                status.set_text(
                    f"raw={last_raw[0]:4d}   "
                    f"pF={last_pf[0]:7.1f}   "
                    f"ref={ref_raw[0]:4d}   "
                    f"Δraw={delta:+4d}   "
                    f"delay={delay_us[0]}µs   mode={mode[0]}"
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