#!/usr/bin/env python3
"""
HX711 load cell — live monitor + calibration.
Single cell, stream 1, prefix "hx".

Usage:
  python plot_load_cell.py --port /dev/tty.usbmodemXXXX
  python plot_load_cell.py --port /dev/tty.usbmodemXXXX --units g
"""
import argparse
import time
from collections import deque

import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import TextBox, Button
import serial

def write_cmd(ser, s):
    s = s.strip()  # remove any \r, \n, spaces
    s += "\n"     # add exactly one \n
    ser.write(s.encode("ascii", errors="ignore"))
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
    ap.add_argument("--rate",  type=int, default=10)
    ap.add_argument("--chart", type=int, default=200)
    ap.add_argument("--units", default="g")
    args = ap.parse_args()

    print(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0)
    ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, f"!rate:{args.rate}")
    send_and_wait(ser, "!stream:1")
    ser.reset_input_buffer()
    print("[INFO] Ready.")

    # ── state — use lists so closures always see current value ────────────────
    N        = args.chart
    raw_buf  = deque([0]*N, maxlen=N)
    val_buf  = deque([0.0]*N, maxlen=N)
    last_raw = [0]      # list so callbacks see live value
    last_val = [0.0]    # list so callbacks see live value
    tare_raw = [0]

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(13, 6))
    fig.suptitle("HX711 load cell — monitor + calibration", fontsize=11)

    gs = gridspec.GridSpec(2, 2, figure=fig,
                           width_ratios=[2.8, 1.0],
                           height_ratios=[1, 1],
                           wspace=0.35, hspace=0.4)

    ax_raw = fig.add_subplot(gs[0, 0])
    ax_val = fig.add_subplot(gs[1, 0])
    ax_pan = fig.add_subplot(gs[:, 1])
    ax_pan.set_visible(False)

    t_ax = list(range(-N, 0))

    raw_line,  = ax_raw.plot(t_ax, list(raw_buf), color="steelblue", lw=0.8)
    tare_hline = ax_raw.axhline(0, color="tomato", lw=0.8, ls="--", label="tare")
    ax_raw.set_ylabel("raw counts")
    ax_raw.set_xlabel("samples")
    ax_raw.grid(True, alpha=0.3)
    ax_raw.legend(fontsize=7, loc="upper left")

    val_line,  = ax_val.plot(t_ax, list(val_buf), color="mediumseagreen", lw=0.9)
    ax_val.axhline(0, color="gray", lw=0.5)
    ax_val.set_ylabel(f"weight ({args.units})")
    ax_val.set_xlabel("samples")
    ax_val.grid(True, alpha=0.3)

    status = fig.text(0.01, 0.01,
        "raw=--  tared=--  val=--",
        fontsize=8, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])

    # ── control panel ─────────────────────────────────────────────────────────
    PX = 0.735
    PW = 0.24
    BH = 0.055
    BG = 0.008

    def label(text, y):
        fig.text(PX, y, text, fontsize=7.5, fontweight="bold", color="0.35")

    def mkbtn(text, y, color="0.88", w=1.0, xoff=0.0):
        ax_b = fig.add_axes([PX + xoff*PW, y, PW*w - 0.003, BH*0.85])
        b = Button(ax_b, text, color=color, hovercolor="0.72")
        b.label.set_fontsize(8)
        return b

    y = 0.84
    label("── send ──", y + BH*0.1);        y -= BH*0.6
    ax_tb   = fig.add_axes([PX, y, PW, BH*0.9])
    textbox = TextBox(ax_tb, "", initial="!hx.avg:4")
    y -= BH + BG
    btn_send = mkbtn("Send", y, color="0.82"); y -= BH + BG*3

    label("── calibration ──", y + BH*0.1); y -= BH*0.6
    btn_zero   = mkbtn("1.  zero  (no weight)", y);  y -= BH + BG
    btn_cap    = mkbtn("2.  capture tare",       y);  y -= BH + BG

    ax_kw = fig.add_axes([PX, y, PW*0.58, BH*0.85])
    tb_kw = TextBox(ax_kw, "", initial="500")
    fig.text(PX + PW*0.61, y + BH*0.25, f"known ({args.units})", fontsize=7.5)
    y -= BH + BG

    btn_cal    = mkbtn("3.  calc scale", y, color="0.78"); y -= BH + BG
    btn_verify = mkbtn("4.  verify",     y);                y -= BH + BG*3

    label("── rate ──", y + BH*0.1);        y -= BH*0.6
    btn_r10  = mkbtn("10 Hz", y, w=0.48)
    btn_r2   = mkbtn("2 Hz",  y, w=0.48, xoff=0.52)
    y -= BH + BG

    label("── avg ──", y + BH*0.1);         y -= BH*0.6
    btn_a1   = mkbtn("avg 1",  y, w=0.31,        xoff=0.0)
    btn_a4   = mkbtn("avg 4",  y, w=0.31,        xoff=0.35)
    btn_a16  = mkbtn("avg 16", y, w=0.31,        xoff=0.69)
    y -= BH + BG

    # log strip
    ax_log = fig.add_axes([PX, 0.02, PW, 0.10])
    ax_log.axis("off")
    log_lines = [""] * 4
    log_text  = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")

    def log(msg):
        print(msg)
        log_lines.pop(0)
        log_lines.append(msg[:38])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    def send(cmd):
        write_cmd(ser, cmd)
        log(f">>> {cmd}")

    # ── callbacks ─────────────────────────────────────────────────────────────
    _pending = [False]
    def do_send(text):
        cmd = text.strip()
        if not cmd or _pending[0]:
            return
        _pending[0] = True
        send(cmd)
    def on_submit(text):
        do_send(text)
        _pending[0] = False
    def on_btn_send(e):
        _pending[0] = False   # reset so button always works
        do_send(textbox.text)
        _pending[0] = False
    textbox.on_submit(on_submit)
    btn_send.on_clicked(on_btn_send)

    def cb_zero(e):
        send("!hx.zero:1")
        tare_raw[0] = last_raw[0]
        tare_hline.set_ydata([last_raw[0], last_raw[0]])
        log(f"  tare = {tare_raw[0]}")

    def cb_cap(e):
        tare_raw[0] = last_raw[0]
        tare_hline.set_ydata([last_raw[0], last_raw[0]])
        log(f"  tare = {tare_raw[0]}")

    def cb_cal(e):
        try:
            kw = float(tb_kw.text.strip())
        except ValueError:
            log("  ! invalid weight value"); return
        delta = last_raw[0] - tare_raw[0]
        if abs(delta) < 500:
            log(f"  ! delta={delta} too small — add weight"); return
        scale = delta / kw
        send(f"!hx.scale:{scale:.4f}")
        log(f"  {delta}/{kw:.1f} = {scale:.4f}")

    def cb_verify(e):
        send("?hx.scale")
        log(f"  raw={last_raw[0]}  val={last_val[0]:.3f} {args.units}")

    btn_zero.on_clicked(cb_zero)
    btn_cap.on_clicked(cb_cap)
    btn_cal.on_clicked(cb_cal)
    btn_verify.on_clicked(cb_verify)

    btn_r10.on_clicked(lambda e: send("!rate:10"))
    btn_r2.on_clicked( lambda e: send("!rate:2"))
    btn_a1.on_clicked( lambda e: send("!hx.avg:1"))
    btn_a4.on_clicked( lambda e: send("!hx.avg:4"))
    btn_a16.on_clicked(lambda e: send("!hx.avg:16"))

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
                # Log any non-data response (OK, ERR, param replies, tare=...)
                if not line[0].lstrip("-").isdigit():
                    log(f"  {line}")
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) != 2:
                    continue
                try:
                    last_raw[0] = int(parts[0])
                    last_val[0] = float(parts[1])
                    raw_buf.append(last_raw[0])
                    val_buf.append(last_val[0])
                    new_data = True
                except ValueError:
                    pass

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False
                t_ax = list(range(-N, 0))
                raw_line.set_data(t_ax, list(raw_buf))
                val_line.set_data(t_ax, list(val_buf))
                ax_raw.relim(); ax_raw.autoscale_view()
                ax_val.relim(); ax_val.autoscale_view()
                tared = last_raw[0] - tare_raw[0]
                status.set_text(
                    f"raw={last_raw[0]:+10d}   tared={tared:+10d}   "
                    f"val={last_val[0]:8.3f} {args.units}"
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