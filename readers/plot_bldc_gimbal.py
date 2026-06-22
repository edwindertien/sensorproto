#!/usr/bin/env python3
"""
BLDC gimbal motor — live monitor + control panel.

Stream 1 CSV: pos(rad), vel(rad/s), set(rad), vq(V), cnt(raw)

Layout:
  Top-left    : position + setpoint strip chart
  Bottom-left : velocity + vq strip chart
  Top-right   : polar dial showing rotor angle
  Bottom-right: control panel

Usage:
  python plot_bldc_gimbal.py --port /dev/tty.usbmodemXXXX
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

# ── serial ────────────────────────────────────────────────────────────────────

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

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",  required=True)
    ap.add_argument("--baud",  type=int, default=115200)
    ap.add_argument("--rate",  type=int, default=50)
    ap.add_argument("--chart", type=int, default=200)
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
    print("[INFO] Ready. Motor disabled — click 'enable' to activate.")

    # ── buffers ───────────────────────────────────────────────────────────────
    N = args.chart
    pos_buf = deque([0.0]*N, maxlen=N)
    set_buf = deque([0.0]*N, maxlen=N)
    vel_buf = deque([0.0]*N, maxlen=N)
    vq_buf  = deque([0.0]*N, maxlen=N)

    last = {"pos": 0.0, "vel": 0.0, "set": 0.0, "vq": 0.0, "cnt": 0}

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(15, 7))
    fig.suptitle("BLDC gimbal — FOC monitor", fontsize=11)

    gs = gridspec.GridSpec(2, 3, figure=fig,
                           width_ratios=[2.2, 2.2, 1.2],
                           hspace=0.45, wspace=0.35)

    ax_pos  = fig.add_subplot(gs[0, 0])
    ax_vel  = fig.add_subplot(gs[1, 0])
    ax_vq   = fig.add_subplot(gs[1, 1])
    ax_dial = fig.add_subplot(gs[0, 1], projection="polar")
    ax_pan  = fig.add_subplot(gs[:, 2])
    ax_pan.set_visible(False)

    t_ax = list(range(-N, 0))

    # position chart
    pos_line, = ax_pos.plot(t_ax, list(pos_buf), color="steelblue", lw=0.9, label="pos (rad)")
    set_line, = ax_pos.plot(t_ax, list(set_buf), color="steelblue", lw=0.6, ls="--", alpha=0.5, label="set")
    ax_pos.set_ylabel("angle (rad)"); ax_pos.set_xlabel("samples")
    ax_pos.legend(fontsize=7, loc="upper left"); ax_pos.grid(True, alpha=0.3)

    # velocity chart
    vel_line, = ax_vel.plot(t_ax, list(vel_buf), color="mediumseagreen", lw=0.9, label="vel (rad/s)")
    ax_vel.axhline(0, color="gray", lw=0.5)
    ax_vel.set_ylabel("vel (rad/s)"); ax_vel.set_xlabel("samples")
    ax_vel.legend(fontsize=7, loc="upper left"); ax_vel.grid(True, alpha=0.3)

    # vq chart
    vq_line, = ax_vq.plot(t_ax, list(vq_buf), color="tomato", lw=0.9, label="vq (V)")
    ax_vq.axhline(0, color="gray", lw=0.5)
    ax_vq.set_ylabel("effort vq (V)"); ax_vq.set_xlabel("samples")
    ax_vq.legend(fontsize=7, loc="upper left"); ax_vq.grid(True, alpha=0.3)

    # polar dial
    ax_dial.set_theta_zero_location("N")
    ax_dial.set_theta_direction(-1)
    ax_dial.set_ylim(0, 1); ax_dial.set_yticks([])
    needle, = ax_dial.plot([0, 0], [0, 1], color="tomato", lw=2.5)
    ax_dial.set_title("rotor angle", fontsize=9)

    status = fig.text(0.01, 0.01,
        "pos=-- rad  vel=-- rad/s  vq=--V  cnt=--",
        fontsize=8, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])

    # ── control panel ─────────────────────────────────────────────────────────
    PX, PW, BH, BG = 0.79, 0.19, 0.042, 0.006

    def mkbtn(text, y, w=1.0, xoff=0.0, color="0.88"):
        ax_b = fig.add_axes([PX + xoff*PW, y, PW*w - 0.003, BH*0.85])
        b = Button(ax_b, text, color=color, hovercolor="0.72")
        b.label.set_fontsize(7)
        return b

    def lbl(text, y):
        fig.text(PX, y, text, fontsize=7, color="0.4")

    y = 0.88
    ax_tb = fig.add_axes([PX, y, PW, BH*0.9])
    textbox = TextBox(ax_tb, "", initial="!foc.k:2.0")
    y -= BH + BG
    btn_send = mkbtn("Send", y, color="0.82"); y -= BH + BG*2

    lbl("── enable ──", y); y -= BH*0.6
    btn_en   = mkbtn("enable",  y, w=0.48, color="0.78")
    btn_dis  = mkbtn("disable", y, w=0.48, xoff=0.52)
    y -= BH + BG

    btn_zero = mkbtn("@foc.zero", y); y -= BH + BG*2

    lbl("── mode ──", y); y -= BH*0.6
    _mode_btns = []
    modes = [("0 open",0),("1 spring",1),("2 detent",2),("3 damp",3),("4 sp+d",4),("5 sweep",5)]
    for i, (mlbl, mval) in enumerate(modes):
        bx = PX + (i%2)*PW*0.52
        by = y - (i//2)*(BH+BG)
        ax_b = fig.add_axes([bx, by, PW*0.48-0.003, BH*0.85])
        b = Button(ax_b, mlbl, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(6.5)
        def mk_mode(v): return lambda e: write_cmd(ser, f"!foc.mode:{v}")
        b.on_clicked(mk_mode(mval))
        _mode_btns.append(b)
    y -= 3*(BH+BG) + BG*2

    lbl("── spring ──", y); y -= BH*0.6
    _sp_btns = []
    for ltext, cmd in [("k 1.0","!foc.k:1.0"),("k 2.0","!foc.k:2.0"),
                       ("k 5.0","!foc.k:5.0"),("set 0","!foc.set:0.0")]:
        bx = PX + (len(_sp_btns)%2)*PW*0.52
        by = y - (len(_sp_btns)//2)*(BH+BG)
        ax_b = fig.add_axes([bx, by, PW*0.48-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7)
        def mk_cmd(c): return lambda e: write_cmd(ser, c)
        b.on_clicked(mk_cmd(cmd))
        _sp_btns.append(b)
    y -= 2*(BH+BG) + BG*2

    lbl("── damping ──", y); y -= BH*0.6
    _d_btns = []
    for ltext, cmd in [("b 0","!foc.b:0.0"),("b 0.3","!foc.b:0.3"),
                       ("b 1.0","!foc.b:1.0"),("b 3.0","!foc.b:3.0")]:
        bx = PX + (len(_d_btns)%2)*PW*0.52
        by = y - (len(_d_btns)//2)*(BH+BG)
        ax_b = fig.add_axes([bx, by, PW*0.48-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7)
        def mk_cmd2(c): return lambda e: write_cmd(ser, c)
        b.on_clicked(mk_cmd2(cmd))
        _d_btns.append(b)
    y -= 2*(BH+BG) + BG*2

    lbl("── vlimit ──", y); y -= BH*0.6
    _v_btns = []
    for ltext, cmd in [("1V","!foc.vlimit:1.0"),("2V","!foc.vlimit:2.0"),
                       ("3V","!foc.vlimit:3.0"),("5V","!foc.vlimit:5.0")]:
        bx = PX + (len(_v_btns)%2)*PW*0.52
        by = y - (len(_v_btns)//2)*(BH+BG)
        ax_b = fig.add_axes([bx, by, PW*0.48-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7)
        def mk_cmd3(c): return lambda e: write_cmd(ser, c)
        b.on_clicked(mk_cmd3(cmd))
        _v_btns.append(b)
    y -= 2*(BH+BG) + BG*2

    lbl("── sweep ──", y); y -= BH*0.6
    _sw_btns = []
    for ltext, cmd in [("▶ 0.5","!foc.sweep_hz:0.5"),("▶▶ 2","!foc.sweep_hz:2.0"),
                       ("◀ -0.5","!foc.sweep_hz:-0.5"),("stop","!foc.sweep_hz:0.0")]:
        bx = PX + (len(_sw_btns)%2)*PW*0.52
        by = y - (len(_sw_btns)//2)*(BH+BG)
        ax_b = fig.add_axes([bx, by, PW*0.48-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7)
        def mk_cmd4(c): return lambda e: write_cmd(ser, c)
        b.on_clicked(mk_cmd4(cmd))
        _sw_btns.append(b)
    y -= 2*(BH+BG) + BG*2

    lbl("── phase offset (foc.ph) ──", y); y -= BH*0.6
    _ph_btns = []
    for ltext, cmd in [("-π/4","!foc.ph:-0.7854"),("0","!foc.ph:0.0"),
                       ("+π/4","!foc.ph:0.7854"),("+π/2","!foc.ph:1.5708")]:
        bx = PX + (len(_ph_btns)%2)*PW*0.52
        by = y - (len(_ph_btns)//2)*(BH+BG)
        ax_b = fig.add_axes([bx, by, PW*0.48-0.003, BH*0.85])
        b = Button(ax_b, ltext, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7)
        def mk_ph(c): return lambda e: write_cmd(ser, c)
        b.on_clicked(mk_ph(cmd))
        _ph_btns.append(b)

    # log
    ax_log = fig.add_axes([PX, 0.02, PW, 0.07])
    ax_log.axis("off")
    log_lines = [""] * 3
    log_text = ax_log.text(0, 1, "", fontsize=6, va="top", family="monospace")

    def log(msg):
        log_lines.pop(0); log_lines.append(msg[:34])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    def do_send(text):
        cmd = text.strip()
        if cmd: write_cmd(ser, cmd); log(f">>> {cmd}")
    textbox.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(textbox.text))
    btn_en.on_clicked(lambda e: (write_cmd(ser, "!foc.enable:1"), log(">>> enable")))
    btn_dis.on_clicked(lambda e: (write_cmd(ser, "!foc.enable:0"), log(">>> disable")))
    btn_zero.on_clicked(lambda e: (write_cmd(ser, "@foc.zero"), log(">>> zero")))

    plt.show(block=False)
    plt.pause(0.05)

    # ── receive loop ──────────────────────────────────────────────────────────
    rxbuf = b""
    last_draw = time.time()
    new_data = False

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
                if len(parts) != 5:
                    if not line.startswith(("{","OK","ERR")):
                        log(f"  {line[:34]}")
                    continue
                try:
                    pos = float(parts[0])
                    vel = float(parts[1])
                    sp  = float(parts[2])
                    vq  = float(parts[3])
                    cnt = int(parts[4])
                    last.update(pos=pos, vel=vel, set=sp, vq=vq, cnt=cnt)
                    pos_buf.append(pos); set_buf.append(sp)
                    vel_buf.append(vel); vq_buf.append(vq)
                    new_data = True
                except ValueError:
                    pass

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False
                t_ax = list(range(-N, 0))
                pos_line.set_data(t_ax, list(pos_buf))
                set_line.set_data(t_ax, list(set_buf))
                vel_line.set_data(t_ax, list(vel_buf))
                vq_line.set_data(t_ax, list(vq_buf))
                for ax in [ax_pos, ax_vel, ax_vq]:
                    ax.relim(); ax.autoscale_view()

                theta = math.fmod(last["pos"], 2*math.pi)
                if theta < 0: theta += 2*math.pi
                needle.set_data([theta, theta], [0, 1])

                status.set_text(
                    f"pos={last['pos']:+.3f}rad "
                    f"({math.degrees(last['pos']):+.1f}°)  "
                    f"vel={last['vel']:+.2f}rad/s  "
                    f"vq={last['vq']:+.2f}V  "
                    f"cnt={last['cnt']}"
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