#!/usr/bin/env python3
"""
Wind speed sensor — raw analog signal viewer.
Shows A0 waveform at high rate so we can characterise the optical gate output
before deciding on counting/calibration strategy.

Usage:
  python plot_wind_raw.py --port /dev/tty.usbmodemXXXX
  python plot_wind_raw.py --port /dev/tty.usbmodemXXXX --rate 200
"""
import argparse
import time
from collections import deque

import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
import serial

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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",  required=True)
    ap.add_argument("--baud",  type=int, default=115200)
    ap.add_argument("--rate",  type=int, default=200)
    ap.add_argument("--chart", type=int, default=300)
    args = ap.parse_args()

    print(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0)
    ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!adc.mode:0")   # raw counts
    send_and_wait(ser, "!adc.window:1") # no averaging — keep waveform shape
    send_and_wait(ser, f"!rate:{args.rate}")
    send_and_wait(ser, "!stream:1")
    ser.reset_input_buffer()
    print("[INFO] Streaming raw A0.")

    N       = args.chart
    sig_buf = deque([0]*N, maxlen=N)
    last    = [0]

    # ── figure ────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(11, 4))
    plt.subplots_adjust(right=0.78, bottom=0.15)
    fig.suptitle("Wind speed — raw optical gate signal (A0)", fontsize=11)

    t_ax   = list(range(-N, 0))
    line,  = ax.plot(t_ax, list(sig_buf), color="steelblue", lw=0.8)
    ax.set_ylim(-50, 1100)
    ax.set_ylabel("ADC counts (0–1023)")
    ax.set_xlabel("samples")
    ax.grid(True, alpha=0.3)
    ax.axhline(512, color="gray", lw=0.5, ls="--", label="mid")
    ax.legend(fontsize=7)

    status = fig.text(0.01, 0.01, "val=--",
                      fontsize=8, family="monospace", color="0.35")

    # ── buttons ───────────────────────────────────────────────────────────────
    PX, PW, BH, BG = 0.80, 0.18, 0.07, 0.010

    def mkbtn(label, y, color="0.88"):
        ax_b = fig.add_axes([PX, y, PW, BH*0.85])
        b = Button(ax_b, label, color=color, hovercolor="0.72")
        b.label.set_fontsize(8)
        return b

    fig.text(PX, 0.88, "rate:", fontsize=7.5, color="0.35")
    _rate_btns = []
    for lbl, val in [("50 Hz",50),("100 Hz",100),("200 Hz",200)]:
        b = mkbtn(lbl, 0.78 - _rate_btns.__len__()*( BH + BG))
        b.on_clicked(lambda e, v=val: write_cmd(ser, f"!rate:{v}"))
        _rate_btns.append(b)

    fig.text(PX, 0.44, "avg:", fontsize=7.5, color="0.35")
    _avg_btns = []
    for lbl, val in [("avg 1",1),("avg 4",4),("avg 8",8)]:
        b = mkbtn(lbl, 0.34 - _avg_btns.__len__()*(BH + BG))
        b.on_clicked(lambda e, v=val: write_cmd(ser, f"!adc.window:{v}"))
        _avg_btns.append(b)

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
                if not text or not text[0].lstrip("-").isdigit():
                    continue
                # stream 1 emits "signal,ref" — take first value only
                parts = text.split(",")
                try:
                    last[0] = int(parts[0])
                    sig_buf.append(last[0])
                    new_data = True
                except ValueError:
                    pass

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False
                t_ax = list(range(-N, 0))
                line.set_data(t_ax, list(sig_buf))
                ax.relim(); ax.autoscale_view()
                status.set_text(f"val={last[0]:4d}   rate={args.rate} Hz")
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