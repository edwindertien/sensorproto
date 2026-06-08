#!/usr/bin/env python3
"""
BLDC gimbal motor — live monitor with integrated control panel.

Stream 6 CSV: pos(rad), vel(rad/s), set(rad), cmd, mode, src, rpm_fb

Left  : position + setpoint (rad) and velocity (rad/s)
Middle: command (PWM effort) and RPM feedback
Right : control panel — send box + preset buttons

Usage:
  python plot_bldc_gimbal.py --port /dev/tty.usbmodemXXXX
  python plot_bldc_gimbal.py --port /dev/tty.usbmodemXXXX --rate 50
"""
import argparse
import math
import time
from collections import deque

import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import TextBox, Button
import serial

# ── serial ────────────────────────────────────────────────────────────────────

def write_cmd(ser, s):
    if not s.endswith("\n"):
        s += "\n"
    ser.write(s.encode("ascii", errors="ignore"))
    ser.flush()

def send_and_wait(ser, cmd, pause=0.12):
    write_cmd(ser, cmd)
    time.sleep(pause)
    while ser.in_waiting:
        ser.readline()

def parse_stream6(line):
    """pos_rad, vel_rad/s, set_rad, cmd, mode, src, rpm_fb"""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 7:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None

# ── presets ───────────────────────────────────────────────────────────────────
# (label, [commands])

PRESETS = [
    # ── basics ──
    ("stop",            ["@bldc.stop"]),
    ("zero pos",        ["@bldc.zero"]),
    ("enable",          ["!bldc.enable:1"]),
    ("disable",         ["!bldc.enable:0"]),

    # ── source selection ──
    ("src: external",   ["!bldc.src:0"]),
    ("src: STM32 rpm",  ["!bldc.src:1"]),

    # ── external modes (src=0) ──
    ("mode: open-loop", ["!bldc.src:0", "!bldc.mode:0"]),
    ("mode: PID pos",   ["!bldc.src:0", "!bldc.mode:1"]),
    ("mode: spring",    ["!bldc.src:0", "!bldc.mode:2"]),
    ("mode: endstops",  ["!bldc.src:0", "!bldc.mode:3"]),
    ("mode: detents",   ["!bldc.src:0", "!bldc.mode:4"]),

    # ── PID position preset ──
    ("PID defaults",    ["!bldc.kp:2.0", "!bldc.ki:0.0", "!bldc.kd:0.0",
                         "!bldc.cmd_lim:255", "!bldc.src:0", "!bldc.mode:1"]),

    # ── spring-damper preset ──
    ("spring default",  ["!bldc.spring_k:5.0", "!bldc.damp_b:0.3",
                         "!bldc.src:0", "!bldc.mode:2", "!bldc.set:0.0"]),
    ("spring soft",     ["!bldc.spring_k:2.0", "!bldc.damp_b:0.5"]),
    ("spring stiff",    ["!bldc.spring_k:10.0", "!bldc.damp_b:0.2"]),

    # ── detents preset ──
    ("detents 30°",     ["!bldc.detent_step:0.5236",   # π/6 = 30°
                         "!bldc.detent_k:6.0", "!bldc.detent_b:0.15",
                         "!bldc.src:0", "!bldc.mode:4"]),
    ("detents 45°",     ["!bldc.detent_step:0.7854",   # π/4 = 45°
                         "!bldc.detent_k:6.0", "!bldc.detent_b:0.15",
                         "!bldc.src:0", "!bldc.mode:4"]),

    # ── setpoints ──
    ("set 0 rad",       ["!bldc.set:0.0"]),
    ("set +π/2",        ["!bldc.set:1.5708"]),
    ("set -π/2",        ["!bldc.set:-1.5708"]),
    ("set +π",          ["!bldc.set:3.1416"]),

    # ── endstops preset ──
    ("endstops ±π",     ["!bldc.min:-3.1416", "!bldc.max:3.1416",
                         "!bldc.stop_k:10.0", "!bldc.stop_b:0.3",
                         "!bldc.src:0", "!bldc.mode:3"]),

    # ── open-loop nudge ──
    ("cmd +50",         ["!bldc.mode:0", "!bldc.cmd:50"]),
    ("cmd -50",         ["!bldc.mode:0", "!bldc.cmd:-50"]),
    ("cmd 0",           ["!bldc.cmd:0"]),

    # ── STM32 speed ──
    ("rpm +60",         ["!bldc.src:1", "!bldc.rpm:60.0"]),
    ("rpm +120",        ["!bldc.src:1", "!bldc.rpm:120.0"]),
    ("rpm 0",           ["!bldc.rpm:0.0"]),

    # ── misc ──
    ("caps query",      ["?"]),
    ("i2c scan",        ["@bldc.zero"]),   # placeholder; i2cScan is a manual step
]

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
    send_and_wait(ser, "!stream:6")
    ser.reset_input_buffer()
    print("[INFO] Ready. Motor disabled on start — click 'enable' to activate.")

    # ── buffers ───────────────────────────────────────────────────────────────
    N = args.chart
    pos_buf = deque([0.0]*N, maxlen=N)
    set_buf = deque([0.0]*N, maxlen=N)
    vel_buf = deque([0.0]*N, maxlen=N)
    cmd_buf = deque([0.0]*N, maxlen=N)
    rpm_buf = deque([0.0]*N, maxlen=N)

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(15, 7))
    fig.suptitle("BLDC gimbal monitor", fontsize=11)

    gs = gridspec.GridSpec(1, 3, figure=fig,
                           width_ratios=[2, 2, 1.5], wspace=0.35)

    ax_pos = fig.add_subplot(gs[0])
    ax_cmd = fig.add_subplot(gs[1])
    ax_pan = fig.add_subplot(gs[2])
    ax_pan.set_visible(False)

    t_ax = list(range(-N, 0))

    # position / velocity (twin y)
    ax_vel = ax_pos.twinx()
    posl,  = ax_pos.plot(t_ax, list(pos_buf), color="steelblue", lw=0.9, label="pos (rad)")
    setl,  = ax_pos.plot(t_ax, list(set_buf), color="steelblue", lw=0.6,
                         linestyle="--", alpha=0.5, label="setpoint")
    vell,  = ax_vel.plot(t_ax, list(vel_buf), color="mediumseagreen", lw=0.8,
                         alpha=0.7, label="vel (rad/s)")
    ax_pos.set_ylabel("position (rad)", color="steelblue")
    ax_vel.set_ylabel("velocity (rad/s)", color="mediumseagreen")
    ax_pos.set_xlabel("samples")
    ax_pos.grid(True, alpha=0.3)
    lines1 = [posl, setl, vell]
    labs1  = [l.get_label() for l in lines1]
    ax_pos.legend(lines1, labs1, loc="upper left", fontsize=7)

    # command / rpm
    ax_rpm = ax_cmd.twinx()
    cmdl,  = ax_cmd.plot(t_ax, list(cmd_buf), color="tomato",    lw=0.9, label="cmd")
    rpml,  = ax_rpm.plot(t_ax, list(rpm_buf), color="darkorange", lw=0.8,
                         alpha=0.7, label="rpm_fb")
    ax_cmd.axhline(0, color="gray", lw=0.5)
    ax_cmd.set_ylabel("effort cmd", color="tomato")
    ax_rpm.set_ylabel("RPM feedback", color="darkorange")
    ax_cmd.set_xlabel("samples")
    ax_cmd.grid(True, alpha=0.3)
    lines2 = [cmdl, rpml]
    labs2  = [l.get_label() for l in lines2]
    ax_cmd.legend(lines2, labs2, loc="upper left", fontsize=7)

    # status bar (mode / src / pos / vel live readout)
    status_text = fig.text(
        0.01, 0.01, "pos=-- rad  vel=-- rad/s  cmd=--  mode=--  src=--  rpm=--",
        fontsize=7.5, family="monospace", color="0.35"
    )

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])

    # ── control panel ─────────────────────────────────────────────────────────
    PANEL_X = 0.705
    PANEL_W = 0.270
    BTN_H   = 0.038
    BTN_GAP = 0.005
    TOP_Y   = 0.88
    LOG_H   = 0.09

    fig.text(PANEL_X, TOP_Y + BTN_H + 0.012, "Send command:", fontsize=8,
             verticalalignment="bottom")
    ax_tb = fig.add_axes([PANEL_X, TOP_Y, PANEL_W, BTN_H])
    textbox = TextBox(ax_tb, "", initial="!bldc.kp:2.0")

    y = TOP_Y - BTN_H - BTN_GAP
    ax_send = fig.add_axes([PANEL_X, y, PANEL_W, BTN_H])
    btn_send = Button(ax_send, "Send", color="0.85", hovercolor="0.70")

    y -= BTN_H + BTN_GAP * 2
    fig.text(PANEL_X, y + BTN_H * 0.5, "── presets ──",
             fontsize=7, color="0.45", ha="left")

    COL2_X = PANEL_X + PANEL_W * 0.51
    COL_W  = PANEL_W * 0.48
    preset_btns = []
    for i, (label, _) in enumerate(PRESETS):
        col = i % 2
        row = i // 2
        bx  = PANEL_X if col == 0 else COL2_X
        by  = y - (row + 1) * (BTN_H + BTN_GAP)
        if by < LOG_H + 0.02:
            break
        ax_b = fig.add_axes([bx, by, COL_W, BTN_H * 0.9])
        btn  = Button(ax_b, label, color="0.88", hovercolor="0.72")
        btn.label.set_fontsize(7)
        preset_btns.append(btn)

    ax_log = fig.add_axes([PANEL_X, 0.02, PANEL_W, LOG_H])
    ax_log.set_xlim(0, 1); ax_log.set_ylim(0, 1)
    ax_log.axis("off")
    log_lines = [""] * 4
    log_text  = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")

    def update_log(msg):
        log_lines.pop(0)
        log_lines.append(msg[:44])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    # ── callbacks ─────────────────────────────────────────────────────────────

    def do_send(text):
        cmd = text.strip()
        if not cmd:
            return
        write_cmd(ser, cmd)
        update_log(f">>> {cmd}")
        print(f"[TX] {cmd}")

    def make_preset_cb(cmds):
        def cb(event):
            for c in cmds:
                write_cmd(ser, c)
                update_log(f">>> {c}")
                print(f"[TX] {c}")
                time.sleep(0.05)
        return cb

    textbox.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(textbox.text))
    for btn, (_, cmds) in zip(preset_btns, PRESETS):
        btn.on_clicked(make_preset_cb(cmds))

    plt.show(block=False)
    plt.pause(0.05)

    # ── receive loop ──────────────────────────────────────────────────────────
    MODE_NAMES = {0: "open", 1: "PID", 2: "spring", 3: "endstop", 4: "detent"}
    SRC_NAMES  = {0: "ext", 1: "stm32-spd", 2: "stm32-pos"}

    rxbuf     = b""
    last_draw = time.time()
    new_data  = False
    last_parsed = None

    try:
        while plt.fignum_exists(fig.number):
            waiting = ser.in_waiting
            if waiting:
                rxbuf += ser.read(waiting)

            while b"\n" in rxbuf:
                line_b, rxbuf = rxbuf.split(b"\n", 1)
                line = line_b.decode("utf-8", errors="ignore").strip()
                parsed = parse_stream6(line)
                if parsed is None:
                    continue
                pos, vel, setpt, cmd, mode, src, rpm = parsed
                pos_buf.append(pos);  set_buf.append(setpt)
                vel_buf.append(vel);  cmd_buf.append(cmd)
                rpm_buf.append(rpm)
                last_parsed = parsed
                new_data = True

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False

                t_ax = list(range(-N, 0))
                posl.set_data(t_ax, list(pos_buf))
                setl.set_data(t_ax, list(set_buf))
                vell.set_data(t_ax, list(vel_buf))
                cmdl.set_data(t_ax, list(cmd_buf))
                rpml.set_data(t_ax, list(rpm_buf))

                ax_pos.relim(); ax_pos.autoscale_view()
                ax_vel.relim(); ax_vel.autoscale_view()
                ax_cmd.relim(); ax_cmd.autoscale_view()
                ax_rpm.relim(); ax_rpm.autoscale_view()

                if last_parsed:
                    pos, vel, setpt, cmd, mode, src, rpm = last_parsed
                    mname = MODE_NAMES.get(int(mode), str(int(mode)))
                    sname = SRC_NAMES.get(int(src),   str(int(src)))
                    status_text.set_text(
                        f"pos={pos:+.3f} rad ({math.degrees(pos):+.1f}°)  "
                        f"vel={vel:+.2f} rad/s  cmd={int(cmd):+4d}  "
                        f"mode={mname}  src={sname}  rpm={rpm:.1f}"
                    )

                fig.canvas.draw_idle()
                fig.canvas.flush_events()
            else:
                plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser, "@bldc.stop")
        write_cmd(ser, "!stream:0")
        ser.close()
        print("\n[INFO] Closed.")

if __name__ == "__main__":
    main()
    