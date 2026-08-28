#!/usr/bin/env python3
"""
DC Motor — single motor monitor with integrated control panel.

Stream 1: pos(i32), set(f32), cmd(i32), err(f32), vel(f32)  — 5 fields

Layout:
  Top    : position + setpoint strip chart
  Middle : velocity strip chart
  Bottom : PWM command strip chart
  Right  : control panel

Usage:
  python plot_dc_motor.py --port /dev/tty.usbmodemXXXX
"""
import argparse, time
from collections import deque

import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button, TextBox
import serial

N = 300   # samples in chart

def write_cmd(ser, s):
    s = s.strip()
    if not s: return
    print(f">>> {s}", flush=True)
    ser.write((s+"\n").encode("ascii","ignore")); ser.flush()

def send_and_wait(ser, cmd, pause=0.12):
    write_cmd(ser, cmd); time.sleep(pause)
    while ser.in_waiting: ser.readline()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",  required=True)
    ap.add_argument("--baud",  type=int, default=115200)
    ap.add_argument("--rate",  type=int, default=50)
    ap.add_argument("--chart", type=int, default=N)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0); ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, f"!rate:{args.rate}")
    send_and_wait(ser, "!stream:+1")
    ser.reset_input_buffer()
    print("[INFO] Ready.")

    Nc = args.chart
    pos_buf = deque([0.0]*Nc, maxlen=Nc)
    set_buf = deque([0.0]*Nc, maxlen=Nc)
    vel_buf = deque([0.0]*Nc, maxlen=Nc)
    cmd_buf = deque([0.0]*Nc, maxlen=Nc)
    err_buf = deque([0.0]*Nc, maxlen=Nc)
    cur_buf = deque([0.0]*Nc, maxlen=Nc)

    last = {"pos":0,"set":0,"cmd":0,"err":0,"vel":0,"mA":0}

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 8))
    fig.suptitle("DC Motor — single axis controller", fontsize=11)
    gs = gridspec.GridSpec(4, 2, figure=fig,
                           width_ratios=[2.2, 1.3],
                           hspace=0.5, wspace=0.3)

    t_ax = list(range(-Nc, 0))

    ax_pos = fig.add_subplot(gs[0, 0])
    pos_line, = ax_pos.plot(t_ax, list(pos_buf), color="#2d7dd2", lw=0.9, label="pos (ticks)")
    set_line, = ax_pos.plot(t_ax, list(set_buf), color="#2d7dd2", lw=0.7,
                            ls="--", alpha=0.5, label="setpoint")
    ax_pos.set_ylabel("position (ticks)"); ax_pos.set_xlabel("samples")
    ax_pos.legend(fontsize=7, loc="upper left"); ax_pos.grid(True, alpha=0.3)

    ax_vel = fig.add_subplot(gs[1, 0])
    vel_line, = ax_vel.plot(t_ax, list(vel_buf), color="#3bb273", lw=0.9, label="vel (cnt/s)")
    ax_vel.axhline(0, color="gray", lw=0.5)
    set_vel_line, = ax_vel.plot(t_ax, list(set_buf), color="#3bb273", lw=0.7,
                                ls="--", alpha=0.5, label="set (vel mode)")
    ax_vel.set_ylabel("velocity (cnt/s)"); ax_vel.set_xlabel("samples")
    ax_vel.legend(fontsize=7, loc="upper left"); ax_vel.grid(True, alpha=0.3)

    ax_cmd = fig.add_subplot(gs[2, 0])
    ax_cur = fig.add_subplot(gs[3, 0])
    cmd_line, = ax_cmd.plot(t_ax, list(cmd_buf), color="#e84855", lw=0.9, label="PWM cmd")
    err_line, = ax_cmd.plot(t_ax, list(err_buf), color="#f18f01", lw=0.7,
                            alpha=0.6, label="error")
    cur_line, = ax_cur.plot(t_ax, list(cur_buf), color="#7b2d8b", lw=0.9, label="current (mA)")
    ax_cur.axhline(0, color="gray", lw=0.5)
    ax_cur.set_ylabel("current (mA)"); ax_cur.set_xlabel("samples")
    ax_cur.legend(fontsize=7, loc="upper left"); ax_cur.grid(True, alpha=0.3)
    ax_cmd.axhline(0, color="gray", lw=0.5)
    ax_cmd.set_ylim(-270, 270)
    ax_cmd.set_ylabel("PWM / error"); ax_cmd.set_xlabel("samples")
    ax_cmd.legend(fontsize=7, loc="upper left"); ax_cmd.grid(True, alpha=0.3)

    status = fig.text(0.01, 0.01,
        "pos=-- set=-- cmd=-- err=-- vel=--",
        fontsize=8, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])

    # ── control panel ─────────────────────────────────────────────────────────
    PX, PW, BH, BG = 0.70, 0.28, 0.040, 0.005

    def lbl(text, y):
        fig.text(PX, y, text, fontsize=7, fontweight="bold", color="0.35")

    def mkbtn(text, y, w=1.0, xoff=0.0, color="0.88"):
        ax_b = fig.add_axes([PX+xoff*PW, y, PW*w-0.003, BH*0.85])
        b = Button(ax_b, text, color=color, hovercolor="0.72")
        b.label.set_fontsize(6.5); return b

    def row3(y, items):
        """3 equal buttons on one row."""
        btns = []
        for xi, (ltext, cmd) in enumerate(items):
            ax_b = fig.add_axes([PX+xi*(PW/3), y, PW/3-0.003, BH*0.85])
            b = Button(ax_b, ltext, color="0.88", hovercolor="0.72")
            b.label.set_fontsize(6.5)
            def mk(c): return lambda e: write_cmd(ser, c)
            b.on_clicked(mk(cmd)); btns.append(b)
        return btns

    y = 0.90
    # Send box
    ax_tb = fig.add_axes([PX, y, PW, BH*0.9])
    tb = TextBox(ax_tb, "", initial="!mot.kp:2.0")
    y -= BH + BG
    btn_send = mkbtn("Send", y, color="0.80"); y -= BH + BG*2

    # Enable / mode
    lbl("enable / mode", y); y -= BH*0.7
    btn_en  = mkbtn("enable",  y, w=0.48, color="0.75")
    btn_dis = mkbtn("disable", y, w=0.48, xoff=0.52)
    y -= BH + BG
    _mode_btns = row3(y, [("0 PWM","!mot.mode:0"),("1 pos","!mot.mode:1"),("2 vel","!mot.mode:2")])
    y -= BH + BG*2

    # Actions
    lbl("actions", y); y -= BH*0.7
    btn_zero  = mkbtn("@mot.zero",  y, w=0.33)
    btn_brake = mkbtn("@mot.brake", y, w=0.33, xoff=0.34)
    btn_coast = mkbtn("@mot.coast", y, w=0.33, xoff=0.67)
    y -= BH + BG*2

    # Setpoint
    lbl("setpoint (ticks)", y); y -= BH*0.7
    _sp_btns = row3(y, [("0","!mot.set:0"),("+½rev","!mot.set:6000"),("-½rev","!mot.set:-6000")])
    y -= BH + BG
    _sp2_btns = row3(y, [("+1rev","!mot.set:12000"),("-1rev","!mot.set:-12000"),("@zero","@mot.zero")])
    y -= BH + BG*2

    # PWM limit
    lbl("PWM limit", y); y -= BH*0.7
    _lim_btns = row3(y, [("50","!mot.pwm_lim:50"),("100","!mot.pwm_lim:100"),("200","!mot.pwm_lim:200")])
    y -= BH + BG*2

    # Velocity filter
    lbl("vel filter (α: 1=off, low=smooth)", y); y -= BH*0.7
    _flt_btns = row3(y, [("α=1 off","!mot.vel_alpha:1.0"),("α=0.5","!mot.vel_alpha:0.5"),("α=0.2","!mot.vel_alpha:0.2")])
    y -= BH + BG*2

    # Control loop rate
    lbl("ctrl loop Hz (default 500)", y); y -= BH*0.7
    _hz_btns = row3(y, [("50 Hz","!mot.ctrl_hz:50"),("500 Hz","!mot.ctrl_hz:500"),("2000 Hz","!mot.ctrl_hz:2000")])
    y -= BH + BG*2

    # PID gains — 3 rows of 3: Kp, Ki, Kd
    lbl("PID gains", y); y -= BH*0.7
    _pid_btns  = row3(y, [("Kp 0.5","!mot.kp:0.5"),("Kp 2","!mot.kp:2.0"),("Kp 5","!mot.kp:5.0")])
    y -= BH + BG
    _pid_btns2 = row3(y, [("Ki 0","!mot.ki:0"),("Ki 0.1","!mot.ki:0.1"),("Ki 1","!mot.ki:1.0")])
    y -= BH + BG
    _pid_btns3 = row3(y, [("Kd 0","!mot.kd:0"),("Kd 0.05","!mot.kd:0.05"),("Kd 0.1","!mot.kd:0.1")])
    y -= BH + BG*2

    # log
    ax_log = fig.add_axes([PX, 0.02, PW, 0.06])
    ax_log.axis("off")
    log_lines = [""]*3
    log_txt = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")
    def log(msg):
        log_lines.pop(0); log_lines.append(msg[:36])
        log_txt.set_text("\n".join(log_lines)); fig.canvas.draw_idle()

    def do_send(text):
        cmd = text.strip()
        if cmd: write_cmd(ser, cmd); log(f">>> {cmd}")
    tb.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(tb.text))
    btn_en.on_clicked(lambda e:   write_cmd(ser, "!mot.enable:1"))
    btn_dis.on_clicked(lambda e:  write_cmd(ser, "!mot.enable:0"))
    btn_zero.on_clicked(lambda e: write_cmd(ser, "@mot.zero"))
    btn_brake.on_clicked(lambda e:write_cmd(ser, "@mot.brake"))
    btn_coast.on_clicked(lambda e:write_cmd(ser, "@mot.coast"))

    plt.show(block=False); plt.pause(0.05)

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
                if len(parts) != 6: continue
                try:
                    vals = [float(p) for p in parts]
                except ValueError:
                    continue
                last["pos"] = vals[0]; last["set"] = vals[1]
                last["cmd"] = vals[2]; last["err"] = vals[3]
                last["vel"] = vals[4]; last["mA"]  = vals[5]
                pos_buf.append(vals[0]); set_buf.append(vals[1])
                cmd_buf.append(vals[2]); err_buf.append(vals[3])
                vel_buf.append(vals[4]); cur_buf.append(vals[5])
                new_data = True

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False
                t_ax = list(range(-Nc, 0))
                pos_line.set_data(t_ax, list(pos_buf))
                set_line.set_data(t_ax, list(set_buf))
                vel_line.set_data(t_ax, list(vel_buf))
                set_vel_line.set_data(t_ax, list(set_buf))
                cmd_line.set_data(t_ax, list(cmd_buf))
                err_line.set_data(t_ax, list(err_buf))
                cur_line.set_data(t_ax, list(cur_buf))
                ax_pos.relim(); ax_pos.autoscale_view()
                ax_vel.relim(); ax_vel.autoscale_view()
                ax_cur.relim(); ax_cur.autoscale_view()
                status.set_text(
                    f"pos={last['pos']:.0f}  set={last['set']:.0f}  "
                    f"cmd={last['cmd']:.0f}  err={last['err']:.1f}  "
                    f"vel={last['vel']:.0f}cnt/s  {last['mA']:.0f}mA"
                )
                fig.canvas.draw_idle(); fig.canvas.flush_events()

            plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser, "!mot.enable:0")
        write_cmd(ser, "!stream:0")
        ser.close(); print("\n[INFO] Closed.")

if __name__ == "__main__":
    main()