#!/usr/bin/env python3
"""
Dual motor — live monitor with integrated command panel.

Left  : position strip chart (pos0, pos1, setpoints)
Middle: PWM command strip chart
Right : command panel — free-text send box + preset script buttons

Usage:
  python plot_dual_motor.py --port /dev/tty.usbmodemXXXX
  python plot_dual_motor.py --port /dev/tty.usbmodemXXXX --rate 50 --chart 300
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

# ── serial helpers ────────────────────────────────────────────────────────────

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

def parse_stream3(line):
    """pos0,pos1,set0,set1,cmd0,cmd1,err0,err1"""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 8:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None

# ── preset scripts ────────────────────────────────────────────────────────────
# Each entry: (button label, list of commands to send in sequence)

PRESETS = [
    ("zero encoders",   ["@motor.zero"]),
    ("stop all",        ["@motor.stop",
                         "!motor.link:0"]),
    ("PID defaults",    ["!motor0.kp:1.5", "!motor0.ki:0.0", "!motor0.kd:0.0",
                         "!motor1.kp:1.5", "!motor1.ki:0.0", "!motor1.kd:0.0",
                         "!motor0.pwm_lim:180", "!motor1.pwm_lim:180"]),
    ("enable both",     ["!motor0.enable:1", "!motor1.enable:1"]),
    ("disable both",    ["!motor0.enable:0", "!motor1.enable:0"]),
    ("link bidir",      ["!motor.link:3", "!motor.link_scale:1.0"]),
    ("link soft",       ["!motor.link:3", "!motor.link_scale:0.5"]),
    ("link off",        ["!motor.link:0"]),
    ("step m0 +1rev",   ["!motor0.set:500"]),
    ("step m0 -1rev",   ["!motor0.set:-500"]),
    ("step m0 home",    ["!motor0.set:0"]),
    ("step m1 +1rev",   ["!motor1.set:500"]),
    ("step m1 -1rev",   ["!motor1.set:-500"]),
    ("step m1 home",    ["!motor1.set:0"]),
    ("open loop m0+",   ["!motor0.enable:0", "!motor0.pwm:100"]),
    ("open loop m0-",   ["!motor0.enable:0", "!motor0.pwm:-100"]),
    ("open loop off",   ["!motor0.pwm:0",    "!motor1.pwm:0"]),
    ("caps query",      ["?"]),
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
    send_and_wait(ser, "!stream:3")
    ser.reset_input_buffer()
    print("[INFO] Ready.")

    # ── data ─────────────────────────────────────────────────────────────────
    N = args.chart
    pos0_buf = deque([0.0]*N, maxlen=N)
    pos1_buf = deque([0.0]*N, maxlen=N)
    set0_buf = deque([0.0]*N, maxlen=N)
    set1_buf = deque([0.0]*N, maxlen=N)
    cmd0_buf = deque([0.0]*N, maxlen=N)
    cmd1_buf = deque([0.0]*N, maxlen=N)

    # ── figure layout ─────────────────────────────────────────────────────────
    # 3 columns: [pos chart | cmd chart | control panel]
    fig = plt.figure(figsize=(14, 7))
    fig.suptitle("Dual motor monitor", fontsize=11)

    gs = gridspec.GridSpec(
        1, 3,
        figure=fig,
        width_ratios=[2, 2, 1.4],
        wspace=0.35,
    )

    ax_pos = fig.add_subplot(gs[0])
    ax_cmd = fig.add_subplot(gs[1])
    ax_pan = fig.add_subplot(gs[2])   # panel axes (invisible, used for layout)
    ax_pan.set_visible(False)

    # position chart
    t_ax = list(range(-N, 0))
    p0l, = ax_pos.plot(t_ax, list(pos0_buf), color="steelblue", lw=0.9, label="pos0")
    p1l, = ax_pos.plot(t_ax, list(pos1_buf), color="tomato",    lw=0.9, label="pos1")
    s0l, = ax_pos.plot(t_ax, list(set0_buf), color="steelblue", lw=0.6,
                       linestyle="--", alpha=0.5, label="set0")
    s1l, = ax_pos.plot(t_ax, list(set1_buf), color="tomato",    lw=0.6,
                       linestyle="--", alpha=0.5, label="set1")
    ax_pos.set_ylabel("position (ticks)")
    ax_pos.set_xlabel("samples")
    ax_pos.legend(loc="upper left", fontsize=7)
    ax_pos.grid(True, alpha=0.3)

    # command chart
    c0l, = ax_cmd.plot(t_ax, list(cmd0_buf), color="steelblue", lw=0.9, label="cmd0")
    c1l, = ax_cmd.plot(t_ax, list(cmd1_buf), color="tomato",    lw=0.9, label="cmd1")
    ax_cmd.axhline(0, color="gray", lw=0.5)
    ax_cmd.set_ylabel("PWM command")
    ax_cmd.set_xlabel("samples")
    ax_cmd.set_ylim(-270, 270)
    ax_cmd.legend(loc="upper left", fontsize=7)
    ax_cmd.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    # ── control panel ─────────────────────────────────────────────────────────
    # Place widgets in the right third of the figure using figure coordinates.
    # Panel starts at x=0.72, spans to x=0.98; top to bottom with small gaps.

    PANEL_X  = 0.725
    PANEL_W  = 0.255
    BTN_H    = 0.040
    BTN_GAP  = 0.006
    TOP_Y    = 0.88   # top of first button
    LOG_H    = 0.10   # height of log box at bottom

    # Send box label + text input
    fig.text(PANEL_X, TOP_Y + BTN_H + 0.015, "Send command:", fontsize=8,
             verticalalignment="bottom")
    ax_tb = fig.add_axes([PANEL_X, TOP_Y, PANEL_W, BTN_H])
    textbox = TextBox(ax_tb, "", initial="!motor0.kp:1.5")

    # Send button
    y = TOP_Y - BTN_H - BTN_GAP
    ax_send = fig.add_axes([PANEL_X, y, PANEL_W, BTN_H])
    btn_send = Button(ax_send, "Send", color="0.85", hovercolor="0.70")

    # Divider label
    y -= BTN_H + BTN_GAP * 2
    fig.text(PANEL_X, y + BTN_H * 0.5, "── presets ──",
             fontsize=7, color="0.45", ha="left")

    # Preset buttons — two columns
    COL2_X = PANEL_X + PANEL_W * 0.51
    COL_W  = PANEL_W * 0.48
    preset_btns = []
    for i, (label, _) in enumerate(PRESETS):
        col   = i % 2
        row   = i // 2
        bx    = PANEL_X if col == 0 else COL2_X
        by    = y - (row + 1) * (BTN_H + BTN_GAP)
        if by < LOG_H + 0.02:
            break   # don't overflow into log area
        ax_b  = fig.add_axes([bx, by, COL_W, BTN_H * 0.9])
        btn   = Button(ax_b, label, color="0.88", hovercolor="0.72")
        btn.label.set_fontsize(7)
        preset_btns.append(btn)

    # Log box (static text, updated each send)
    ax_log = fig.add_axes([PANEL_X, 0.02, PANEL_W, LOG_H])
    ax_log.set_xlim(0, 1); ax_log.set_ylim(0, 1)
    ax_log.axis("off")
    log_lines = [""] * 5
    log_text  = ax_log.text(0, 1, "", fontsize=6.5, va="top",
                            family="monospace", wrap=True)

    def update_log(msg):
        log_lines.pop(0)
        log_lines.append(msg[:42])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    # ── widget callbacks ──────────────────────────────────────────────────────

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
                parsed = parse_stream3(line)
                if parsed is None:
                    continue
                pos0, pos1, set0, set1, cmd0, cmd1, _, _ = parsed
                pos0_buf.append(pos0); pos1_buf.append(pos1)
                set0_buf.append(set0); set1_buf.append(set1)
                cmd0_buf.append(cmd0); cmd1_buf.append(cmd1)
                new_data = True

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False
                t_ax = list(range(-N, 0))
                p0l.set_data(t_ax, list(pos0_buf))
                p1l.set_data(t_ax, list(pos1_buf))
                s0l.set_data(t_ax, list(set0_buf))
                s1l.set_data(t_ax, list(set1_buf))
                c0l.set_data(t_ax, list(cmd0_buf))
                c1l.set_data(t_ax, list(cmd1_buf))
                ax_pos.relim(); ax_pos.autoscale_view()
                ax_cmd.relim(); ax_cmd.autoscale_view()
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
            else:
                plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser, "@motor.stop")
        write_cmd(ser, "!stream:0")
        ser.close()
        print("\n[INFO] Closed.")

if __name__ == "__main__":
    main()