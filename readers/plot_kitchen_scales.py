#!/usr/bin/env python3
"""
Kitchen scales — live monitor with 7-segment digital readout + calibration.

Usage:
  python plot_kitchen_scales.py --port /dev/tty.usbmodemXXXX
"""
import argparse
import time
from collections import deque

import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.widgets import TextBox, Button
import serial

# ── serial ────────────────────────────────────────────────────────────────────

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

# ── 7-segment digit renderer ──────────────────────────────────────────────────

SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd",
    "4": "fgbc",   "5": "afgcd", "6": "afgedc", "7": "abc",
    "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "",
}

def draw_digit(ax, x0, on_segs, w=0.8, h=1.6, on_color="#ff3b30", off_color="#2a0805"):
    t = 0.10
    hw, hh = w/2, h/2

    def seg(name, x, y, sw, sh):
        color = on_color if name in on_segs else off_color
        ax.add_patch(mpatches.FancyBboxPatch(
            (x0 + x, y), sw, sh,
            boxstyle="round,pad=0,rounding_size=0.03",
            linewidth=0, facecolor=color
        ))

    seg("a", -hw+t, h-t,        w-2*t, t)
    seg("f", -hw,   hh+t/2,     t,     hh-t)
    seg("b", hw-t,  hh+t/2,     t,     hh-t)
    seg("g", -hw+t, hh-t/2,     w-2*t, t)
    seg("e", -hw,   t/2,        t,     hh-t)
    seg("c", hw-t,  t/2,        t,     hh-t)
    seg("d", -hw+t, 0,          w-2*t, t)

def draw_value(ax, value_str, digit_w=0.8, gap=0.30):
    """
    Draws value_str as 7-seg digits. A '.' attaches a decimal point
    to the PREVIOUS digit (bottom-right), like a real display module,
    rather than consuming its own slot.
    """
    ax.clear()

    # Count actual digit slots (chars excluding '.')
    n_slots = sum(1 for ch in value_str if ch != ".")
    ax.set_xlim(0, n_slots * (digit_w + gap) + gap)
    ax.set_ylim(0, 1.8)
    ax.set_facecolor("#120202")
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    x = gap
    last_digit_x = None
    for ch in value_str:
        if ch == ".":
            if last_digit_x is not None:
                # place dot at bottom-right of the digit just drawn
                ax.add_patch(mpatches.Circle(
                    (last_digit_x + digit_w/2 + 0.08, 0.08),
                    0.06, color="#ff3b30"))
            continue
        segs = SEGMENTS.get(ch, " ")
        draw_digit(ax, x, segs, w=digit_w)
        last_digit_x = x
        x += digit_w + gap

def format_weight(grams):
    """Fixed-format: sign + 4 integer digits + 1 decimal, e.g. ' 187.3' or '-12.0'."""
    grams = max(-9999.9, min(9999.9, grams))  # clamp to display range
    s = f"{grams:.1f}"
    # Pad to consistent width: up to 4 int digits + '.' + 1 decimal = 6-7 chars
    return s.rjust(7)

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",  required=True)
    ap.add_argument("--baud",  type=int, default=115200)
    ap.add_argument("--rate",  type=int, default=5)
    ap.add_argument("--chart", type=int, default=150)
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

    N        = args.chart
    val_buf  = deque([0.0]*N, maxlen=N)
    last_raw = [0]
    last_val = [0.0]
    tare_raw = [0]

    fig = plt.figure(figsize=(13, 6.5))
    fig.suptitle("Kitchen scales", fontsize=12)

    gs = gridspec.GridSpec(2, 2, figure=fig,
                           width_ratios=[2.6, 1.1],
                           height_ratios=[0.8, 1.3],
                           hspace=0.35, wspace=0.30)

    ax_digit = fig.add_subplot(gs[0, 0])
    ax_chart = fig.add_subplot(gs[1, 0])
    ax_pan   = fig.add_subplot(gs[:, 1])
    ax_pan.set_visible(False)

    draw_value(ax_digit, format_weight(0.0))
    ax_digit.set_aspect("equal")

    t_ax = list(range(-N, 0))
    chart_line, = ax_chart.plot(t_ax, list(val_buf), color="mediumseagreen", lw=1.0)
    ax_chart.axhline(0, color="gray", lw=0.5)
    ax_chart.set_ylabel("weight (g)")
    ax_chart.set_xlabel("samples")
    ax_chart.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0.02, 1, 0.95])

    PX, PW, BH, BG = 0.745, 0.23, 0.052, 0.008

    def label(text, y):
        fig.text(PX, y, text, fontsize=7.5, fontweight="bold", color="0.35")

    def mkbtn(text, y, w=1.0, xoff=0.0, color="0.88"):
        ax_b = fig.add_axes([PX + xoff*PW, y, PW*w - 0.004, BH*0.85])
        b = Button(ax_b, text, color=color, hovercolor="0.72")
        b.label.set_fontsize(7.5)
        return b

    y = 0.84
    label("── send ──", y + BH*0.1);        y -= BH*0.55
    ax_tb   = fig.add_axes([PX, y, PW, BH*0.9])
    textbox = TextBox(ax_tb, "", initial="!hx.avg:4")
    y -= BH + BG
    btn_send = mkbtn("Send", y, color="0.82"); y -= BH + BG*3

    label("── calibration ──", y + BH*0.1); y -= BH*0.55
    btn_zero = mkbtn("1.  zero  (empty scale)", y); y -= BH + BG
    btn_cap  = mkbtn("2.  capture tare",         y); y -= BH + BG

    ax_kw = fig.add_axes([PX, y, PW*0.58, BH*0.85])
    tb_kw = TextBox(ax_kw, "", initial="200")
    fig.text(PX + PW*0.61, y + BH*0.25, "known (g)", fontsize=7.5)
    y -= BH + BG

    btn_cal    = mkbtn("3.  calc scale", y, color="0.78"); y -= BH + BG
    btn_verify = mkbtn("4.  verify",     y);                y -= BH + BG*3

    label("── tare ──", y + BH*0.1); y -= BH*0.55
    btn_tare = mkbtn("re-tare (empty scale)", y, color="0.80"); y -= BH + BG*2

    label("── avg ──", y + BH*0.1);  y -= BH*0.55
    btn_a1  = mkbtn("avg 1",  y, w=0.31, xoff=0.0)
    btn_a4  = mkbtn("avg 4",  y, w=0.31, xoff=0.35)
    btn_a16 = mkbtn("avg 16", y, w=0.31, xoff=0.69)

    ax_log = fig.add_axes([PX, 0.02, PW, 0.10])
    ax_log.axis("off")
    log_lines = [""] * 4
    log_text = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")

    def log(msg):
        log_lines.pop(0)
        log_lines.append(msg[:40])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    def send(cmd):
        write_cmd(ser, cmd)
        log(f">>> {cmd}")

    def do_send(text):
        cmd = text.strip()
        if cmd:
            send(cmd)
    textbox.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(textbox.text))

    def cb_zero(e):
        send("!hx.zero:1")
        tare_raw[0] = last_raw[0]
        log(f"  tare = {tare_raw[0]}")
    def cb_cap(e):
        tare_raw[0] = last_raw[0]
        log(f"  tare = {tare_raw[0]}")
    def cb_cal(e):
        try:
            kw = float(tb_kw.text.strip())
        except ValueError:
            log("  ! invalid weight"); return
        delta = last_raw[0] - tare_raw[0]
        if abs(delta) < 200:
            log(f"  ! delta={delta} too small"); return
        scale = delta / kw
        send(f"!hx.scale:{scale:.4f}")
        log(f"  {delta}/{kw:.1f} = {scale:.4f}")
    def cb_verify(e):
        send("?hx.scale")
        log(f"  raw={last_raw[0]}  val={last_val[0]:.1f} g")
    def cb_tare(e):
        send("!hx.zero:1")
        log("  re-tared")

    btn_zero.on_clicked(cb_zero)
    btn_cap.on_clicked(cb_cap)
    btn_cal.on_clicked(cb_cal)
    btn_verify.on_clicked(cb_verify)
    btn_tare.on_clicked(cb_tare)

    btn_a1.on_clicked(lambda e: send("!hx.avg:1"))
    btn_a4.on_clicked(lambda e: send("!hx.avg:4"))
    btn_a16.on_clicked(lambda e: send("!hx.avg:16"))

    plt.show(block=False)
    plt.pause(0.05)

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
                    log(f"  {line}")
                    continue
                try:
                    last_raw[0] = int(parts[0])
                    last_val[0] = float(parts[1])
                    val_buf.append(last_val[0])
                    new_data = True
                except ValueError:
                    log(f"  {line}")
                    continue

            now = time.time()
            if new_data and (now - last_draw) >= 0.08:
                last_draw = now; new_data = False
                t_ax = list(range(-N, 0))
                chart_line.set_data(t_ax, list(val_buf))
                ax_chart.relim(); ax_chart.autoscale_view()
                draw_value(ax_digit, format_weight(last_val[0]))
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