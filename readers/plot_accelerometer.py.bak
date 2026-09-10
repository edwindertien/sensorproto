#!/usr/bin/env python3
"""
MMA7260 accelerometer — strip charts + 3D orientation cube.

Layout:
  Left col : X, Y, Z strip charts (g values)
  Right col : 3D wireframe cube showing pitch/roll orientation

The cube is drawn with matplotlib 3D — pitch from X/Z, roll from Y/Z.
Yaw is not observable from a static accelerometer.

Usage:
  python plot_accelerometer.py --port /dev/tty.usbmodemXXXX
  python plot_accelerometer.py --port /dev/tty.usbmodemXXXX --rate 50 --grange 1.5
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
from mpl_toolkits.mplot3d import Axes3D          # noqa: F401
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
import serial

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

# ── MMA7260 conversion ────────────────────────────────────────────────────────
# Vref=3.3V, sensitivity=800mV/g, zero=Vcc/2=1.65V
# raw 0..1023 → V = raw/1023*3.3 → g = (V-1.65)/0.8

VREF        = 3.3
SENSITIVITY = 0.800   # V/g
VZERO       = VREF / 2.0

def raw_to_g(raw):
    v = raw / 1023.0 * VREF
    return (v - VZERO) / SENSITIVITY

# ── cube geometry ─────────────────────────────────────────────────────────────

# Unit cube vertices centred at origin
_VERTS = np.array([
    [-1,-1,-1],[+1,-1,-1],[+1,+1,-1],[-1,+1,-1],
    [-1,-1,+1],[+1,-1,+1],[+1,+1,+1],[-1,+1,+1],
], dtype=float) * 0.5

_FACES = [
    [0,1,2,3],[4,5,6,7],[0,1,5,4],
    [2,3,7,6],[0,3,7,4],[1,2,6,5],
]

FACE_COLORS = [
    "#4a90d9","#e05a4a","#5cb85c",
    "#f0ad4e","#9b59b6","#aaaaaa"
]

def rotate_cube(pitch_rad, roll_rad):
    """Rotate cube vertices by pitch (around Y) and roll (around X)."""
    cp, sp = math.cos(pitch_rad), math.sin(pitch_rad)
    cr, sr = math.cos(roll_rad),  math.sin(roll_rad)

    Ry = np.array([[cp, 0, sp],[0, 1, 0],[-sp, 0, cp]])
    Rx = np.array([[1, 0, 0],[0, cr,-sr],[0, sr, cr]])

    R = Rx @ Ry
    return (_VERTS @ R.T)

def make_face_polys(verts):
    return [[verts[i] for i in face] for face in _FACES]

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",   required=True)
    ap.add_argument("--baud",   type=int,   default=115200)
    ap.add_argument("--rate",   type=int,   default=50)
    ap.add_argument("--chart",  type=int,   default=150)
    ap.add_argument("--grange", type=float, default=2.0,
                    help="Y-axis range in g for strip charts (±)")
    ap.add_argument("--vzero",  type=float, default=VZERO,
                    help="Zero-g voltage (default Vcc/2 = 1.65V)")
    args = ap.parse_args()

    vzero = args.vzero

    print(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0)
    ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!adc.mode:0")    # raw mode — convert in Python
    send_and_wait(ser, f"!rate:{args.rate}")
    send_and_wait(ser, "!stream:1")
    ser.reset_input_buffer()
    print("[INFO] Streaming.")

    # ── buffers ───────────────────────────────────────────────────────────────
    N = args.chart
    gx_buf = deque([0.0]*N, maxlen=N)
    gy_buf = deque([0.0]*N, maxlen=N)
    gz_buf = deque([0.0]*N, maxlen=N)
    gx = [0.0]; gy = [0.0]; gz = [0.0]
    pitch = [0.0]; roll = [0.0]

    # ── figure layout ─────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 7))
    fig.suptitle("MMA7260 accelerometer", fontsize=11)

    gs = gridspec.GridSpec(
        3, 2, figure=fig,
        width_ratios=[1.6, 1.0],
        hspace=0.45, wspace=0.35
    )

    ax_x  = fig.add_subplot(gs[0, 0])
    ax_y  = fig.add_subplot(gs[1, 0])
    ax_z  = fig.add_subplot(gs[2, 0])
    ax_3d = fig.add_subplot(gs[:, 1], projection="3d")

    t_ax = list(range(-N, 0))
    GR   = args.grange

    def setup_strip(ax, label, color):
        line, = ax.plot(t_ax, [0.0]*N, color=color, lw=0.9)
        ax.axhline(0, color="gray", lw=0.5)
        ax.set_ylim(-GR, GR)
        ax.set_ylabel(label, fontsize=8)
        ax.set_xlabel("samples", fontsize=7)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=7)
        return line

    lx = setup_strip(ax_x, "X (g)", "steelblue")
    ly = setup_strip(ax_y, "Y (g)", "tomato")
    lz = setup_strip(ax_z, "Z (g)", "mediumseagreen")

    # 3D cube
    ax_3d.set_xlim(-1, 1); ax_3d.set_ylim(-1, 1); ax_3d.set_zlim(-1, 1)
    ax_3d.set_title("orientation\n(pitch/roll)", fontsize=8)
    ax_3d.set_axis_off()

    verts = rotate_cube(0, 0)
    cube  = Poly3DCollection(
        make_face_polys(verts),
        facecolors=FACE_COLORS,
        edgecolors="k",
        linewidths=0.5,
        alpha=0.85
    )
    ax_3d.add_collection3d(cube)

    # axis arrows
    def draw_arrow(ax, start, end, color, label):
        ax.quiver(*start, *(np.array(end)-np.array(start)),
                  color=color, linewidth=1.0, arrow_length_ratio=0.3)
        ax.text(*end, label, color=color, fontsize=7)

    draw_arrow(ax_3d, [0,0,0], [0.8,0,0], "steelblue", "X")
    draw_arrow(ax_3d, [0,0,0], [0,0.8,0], "tomato",    "Y")
    draw_arrow(ax_3d, [0,0,0], [0,0,0.8], "seagreen",  "Z")

    status = fig.text(0.01, 0.01,
        "X=-- g  Y=-- g  Z=-- g   pitch=--°  roll=--°",
        fontsize=8, family="monospace", color="0.35")

    # ── control panel ─────────────────────────────────────────────────────────
    # Small panel below the 3D cube
    PX, PW, BH, BG = 0.60, 0.36, 0.045, 0.006

    fig.text(PX, 0.27, "Send:", fontsize=7.5)
    ax_tb = fig.add_axes([PX, 0.22, PW, BH])
    textbox = TextBox(ax_tb, "", initial="!rate:50")

    ax_send = fig.add_axes([PX, 0.17, PW*0.48, BH])
    ax_zero = fig.add_axes([PX + PW*0.52, 0.17, PW*0.48, BH])
    btn_send = Button(ax_send, "Send",       color="0.85", hovercolor="0.70")
    btn_zero = Button(ax_zero, "zero offset",color="0.88", hovercolor="0.72")
    btn_send.label.set_fontsize(7.5)
    btn_zero.label.set_fontsize(7.5)

    # rate buttons
    fig.text(PX, 0.15, "rate:", fontsize=7, color="0.4")
    ax_r20  = fig.add_axes([PX,           0.10, PW*0.31, BH])
    ax_r50  = fig.add_axes([PX+PW*0.35,   0.10, PW*0.31, BH])
    ax_r100 = fig.add_axes([PX+PW*0.69,   0.10, PW*0.31, BH])
    _rate_btns = []
    for ax_r, label, rate in [(ax_r20,"20Hz",20),(ax_r50,"50Hz",50),(ax_r100,"100Hz",100)]:
        b = Button(ax_r, label, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7.5)
        b.on_clicked(lambda e, r=rate: write_cmd(ser, f"!rate:{r}"))
        _rate_btns.append(b)

    # avg buttons — uses adc.window param
    fig.text(PX, 0.08, "avg:", fontsize=7, color="0.4")
    ax_a1   = fig.add_axes([PX,           0.03, PW*0.31, BH])
    ax_a4   = fig.add_axes([PX+PW*0.35,   0.03, PW*0.31, BH])
    ax_a16  = fig.add_axes([PX+PW*0.69,   0.03, PW*0.31, BH])
    _avg_btns = []
    for ax_a, label, avg in [(ax_a1,"avg 1",1),(ax_a4,"avg 4",4),(ax_a16,"avg 16",16)]:
        b = Button(ax_a, label, color="0.88", hovercolor="0.72")
        b.label.set_fontsize(7.5)
        def mk_avg(a):
            def cb(e): write_cmd(ser, '!adc.mode:2'); write_cmd(ser, f'!adc.window:{a}')
            return cb
        b.on_clicked(mk_avg(avg))
        _avg_btns.append(b)

    # Per-axis g offsets — subtracted after conversion
    # Capture current g values when flat to zero out bias
    g_offset = [0.0, 0.0, 0.0]   # [x, y, z]

    def cb_zero(e):
        # Store current readings as offsets (flat on table: X≈0, Y≈0, Z≈-1)
        # We zero X and Y only — leave Z alone (it carries gravity)
        g_offset[0] = gx[0]
        g_offset[1] = gy[0]
        g_offset[2] = gz[0] + 1.0
        print(f"[zero] offsets: X={g_offset[0]:+.3f}  Y={g_offset[1]:+.3f}  Z={g_offset[2]:+.3f}")

    btn_zero.on_clicked(cb_zero)

    def do_send(text):
        cmd = text.strip()
        if cmd:
            write_cmd(ser, cmd)
    textbox.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(textbox.text))

    plt.tight_layout(rect=[0, 0.06, 1, 0.96])
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
                if not line or not line[0].lstrip("-").isdigit():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) != 3:
                    continue
                try:
                    rx, ry, rz = int(parts[0]), int(parts[1]), int(parts[2])
                    gx[0] = raw_to_g(rx) - g_offset[0]
                    gy[0] = raw_to_g(ry) - g_offset[1]
                    gz[0] = raw_to_g(rz) - g_offset[2]
                    gx_buf.append(gx[0])
                    gy_buf.append(gy[0])
                    gz_buf.append(gz[0])
                    new_data = True
                except ValueError:
                    pass

            now = time.time()
            if new_data and (now - last_draw) >= 0.04:
                last_draw = now; new_data = False

                t_ax = list(range(-N, 0))
                lx.set_data(t_ax, list(gx_buf))
                ly.set_data(t_ax, list(gy_buf))
                lz.set_data(t_ax, list(gz_buf))

                # compute pitch and roll from gravity vector using atan2
                # atan2 gives full ±180° range, not limited to ±90° like asin
                pitch[0] = math.atan2(gx[0], math.sqrt(gy[0]**2 + gz[0]**2))
                roll[0]  = math.atan2(gy[0], math.sqrt(gx[0]**2 + gz[0]**2))

                # update cube
                verts = rotate_cube(pitch[0], roll[0])
                cube.set_verts(make_face_polys(verts))

                status.set_text(
                    f"X={gx[0]:+.3f}g  Y={gy[0]:+.3f}g  Z={gz[0]:+.3f}g"
                    f"   pitch={math.degrees(pitch[0]):+.1f}°"
                    f"  roll={math.degrees(roll[0]):+.1f}°"
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