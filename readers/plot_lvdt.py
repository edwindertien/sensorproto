#!/usr/bin/env python3
"""
LVDT — Linear Variable Differential Transformer visualiser.

Stream 1: lvdt.pos  — single f32 position value (-1 to +1)
Stream 2: lvdt.frame — 480-sample frame chunks (id, off, cnt, raw bytes)

Layout:
  Top    : AC waveform oscilloscope (480-sample frame, ~10 excitation cycles)
           Shows excitation reference overlaid with received signal.
           Phase and amplitude reveal core position.
  Bottom : Position strip chart (-1 to +1, 0 = centre)
           Large position readout.

Usage:
  python plot_lvdt.py --port /dev/tty.usbmodemXXXX
"""
import argparse, time, struct
from collections import deque
import numpy as np
import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button
import serial

FRAME_N  = 480
CYCLE_N  = 48
POS_N    = 200

def write_cmd(ser, s):
    s = s.strip()
    if not s: return
    ser.write((s+"\n").encode("ascii","ignore")); ser.flush()

def send_and_wait(ser, cmd, pause=0.15):
    write_cmd(ser, cmd); time.sleep(pause)
    while ser.in_waiting: ser.readline()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",  required=True)
    ap.add_argument("--baud",  type=int, default=38400)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0); ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!stream:+1")
    send_and_wait(ser, "!stream:+2")
    time.sleep(0.3); ser.reset_input_buffer()
    print("[INFO] Ready.")

    # Frame reassembly
    frames      = {}   # frame_id -> bytearray of FRAME_N
    last_frame  = np.zeros(FRAME_N)
    frame_ready = [False]

    # Position buffer
    pos_buf  = deque([0.0]*POS_N, maxlen=POS_N)
    last_pos = [0.0]

    # Reference sine (what pin 9 outputs, 0-255, normalised to -1..+1)
    ref = np.array([np.sin(2*np.pi*n/CYCLE_N) for n in range(CYCLE_N)])
    ref_full = np.tile(ref, FRAME_N//CYCLE_N)  # 480 samples

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(13, 8))
    fig.suptitle("LVDT — Linear Variable Differential Transformer", fontsize=12)
    gs = gridspec.GridSpec(2, 2, figure=fig,
                           width_ratios=[3.0, 1.0],
                           height_ratios=[1.5, 1.0],
                           hspace=0.45, wspace=0.3)

    # Oscilloscope
    ax_osc = fig.add_subplot(gs[0, 0])
    x_osc  = np.arange(FRAME_N)
    ref_line, = ax_osc.plot(x_osc, ref_full, color="#aaa", lw=0.7,
                             ls="--", label="excitation ref", alpha=0.6)
    sig_line, = ax_osc.plot(x_osc, np.zeros(FRAME_N), color="#2d7dd2",
                             lw=1.0, label="receiver signal")
    ax_osc.set_ylim(-1.5, 1.5)
    ax_osc.set_xlim(0, FRAME_N)
    ax_osc.set_ylabel("Amplitude (normalised)")
    ax_osc.set_xlabel(f"samples  ({CYCLE_N} samples = 1 cycle = 10ms at 100Hz)")
    ax_osc.set_title("AC waveform — 480 samples = 10 excitation cycles", fontsize=9)
    ax_osc.legend(fontsize=7, loc="upper right")
    ax_osc.axhline(0, color="gray", lw=0.4)
    ax_osc.grid(True, alpha=0.25)

    # Cycle zoom (show just one cycle)
    ax_cyc = fig.add_subplot(gs[1, 0])
    x_cyc = np.arange(CYCLE_N)
    refz_line, = ax_cyc.plot(x_cyc, ref, color="#aaa", lw=0.8, ls="--",
                              label="excitation ref", alpha=0.6)
    sigz_line, = ax_cyc.plot(x_cyc, np.zeros(CYCLE_N), color="#e84855",
                              lw=1.2, label="receiver (last cycle)")
    ax_cyc.set_ylim(-1.5, 1.5)
    ax_cyc.set_xlim(0, CYCLE_N-1)
    ax_cyc.set_ylabel("Amplitude")
    ax_cyc.set_xlabel("samples in one cycle")
    ax_cyc.set_title("Single cycle zoom — phase shift = position direction", fontsize=9)
    ax_cyc.legend(fontsize=7, loc="upper right")
    ax_cyc.axhline(0, color="gray", lw=0.4)
    ax_cyc.grid(True, alpha=0.25)

    # ── right panel ───────────────────────────────────────────────────────────
    ax_pan = fig.add_subplot(gs[:, 1]); ax_pan.axis("off")

    # Big position readout
    pos_txt = fig.text(0.81, 0.72, "0.000",
        fontsize=36, fontweight="bold", color="#2d7dd2",
        ha="center", va="center")
    fig.text(0.81, 0.64, "position (-1 to +1)", fontsize=8, color="gray",
             ha="center", va="center")

    # Position bar
    ax_bar = fig.add_axes([0.76, 0.52, 0.16, 0.08])
    ax_bar.set_xlim(-1.1, 1.1); ax_bar.set_ylim(0, 1)
    ax_bar.axvline(0, color="gray", lw=0.5)
    ax_bar.set_xticks([-1, -0.5, 0, 0.5, 1])
    ax_bar.tick_params(axis='x', labelsize=7)
    ax_bar.get_yaxis().set_visible(False)
    ax_bar.set_frame_on(True)
    pos_bar = ax_bar.barh([0.5], [0.0], height=0.6,
                           color="#2d7dd2", align="center")[0]
    ax_bar.set_title("position bar", fontsize=7)

    PX, PW, BH, BG = 0.75, 0.22, 0.044, 0.007

    def lbl(text, y):
        fig.text(PX, y, text, fontsize=7.5, fontweight="bold", color="0.35")
    def mkbtn(text, y, w=1.0, xoff=0.0, color="0.88"):
        ax_b = fig.add_axes([PX+xoff*PW, y, PW*w-0.003, BH*0.85])
        b = Button(ax_b, text, color=color, hovercolor="0.72")
        b.label.set_fontsize(7); return b
    def row3(y, items):
        btns = []
        for xi,(ltext,cmd) in enumerate(items):
            ax_b = fig.add_axes([PX+xi*(PW/3), y, PW/3-0.003, BH*0.85])
            b = Button(ax_b, ltext, color="0.88", hovercolor="0.72")
            b.label.set_fontsize(6.5)
            def mk(c): return lambda e: write_cmd(ser, c)
            b.on_clicked(mk(cmd)); btns.append(b)
        return btns

    y = 0.48
    lbl("── zero / calibrate ──", y); y -= BH*0.7
    btn_zero  = mkbtn("@lvdt.zero", y, w=0.48, color="0.75")
    btn_scale = mkbtn("?lvdt.pos",  y, w=0.48, xoff=0.52)
    y -= BH + BG*2

    lbl("── scale ──", y); y -= BH*0.7
    _s_btns = row3(y, [("×0.5","!lvdt.scale:0.5"),("×1","!lvdt.scale:1.0"),("×2","!lvdt.scale:2.0")])
    y -= BH + BG*2

    lbl("── streams ──", y); y -= BH*0.7
    btn_both = mkbtn("pos + frame", y, w=0.48, color="0.80")
    btn_pos  = mkbtn("pos only",   y, w=0.48, xoff=0.52)
    y -= BH + BG*2

    lbl("── status ──", y); y -= BH*0.7
    ax_log = fig.add_axes([PX, y-0.08, PW, 0.10])
    ax_log.axis("off")
    log_lines = [""]*4
    log_txt = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")
    def log(msg):
        log_lines.pop(0); log_lines.append(msg[:28])
        log_txt.set_text("\n".join(log_lines)); fig.canvas.draw_idle()

    status = fig.text(0.01, 0.01, "pos=--  frames=0",
        fontsize=7.5, family="monospace", color="0.35")

    btn_zero.on_clicked(lambda e: (write_cmd(ser,"@lvdt.zero"), log("zeroed")))
    btn_scale.on_clicked(lambda e: log(f"pos={last_pos[0]:.4f}"))
    btn_both.on_clicked(lambda e: (write_cmd(ser,"!stream:+1"),write_cmd(ser,"!stream:+2")))
    btn_pos.on_clicked(lambda e:  (write_cmd(ser,"!stream:0"), write_cmd(ser,"!stream:+1")))

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])
    plt.show(block=False); plt.pause(0.1)

    # ── receive loop ──────────────────────────────────────────────────────────
    rxbuf = b""; last_draw = time.time(); frame_count = [0]

    try:
        while plt.fignum_exists(fig.number):
            w = ser.in_waiting
            if w: rxbuf += ser.read(w)

            new_pos = False; new_frame = False
            while b"\n" in rxbuf:
                lb, rxbuf = rxbuf.split(b"\n", 1)
                line = lb.decode("utf-8","ignore").strip()
                if not line: continue
                parts = [p.strip() for p in line.split(",")]

                if len(parts) == 1:       # stream 1: position
                    try:
                        p = float(parts[0])
                        last_pos[0] = p
                        pos_buf.append(p)
                        new_pos = True
                    except ValueError:
                        pass

                elif len(parts) >= 4:     # stream 2: frame chunk
                    # format: id, off, cnt, b0, b1, ... bN
                    try:
                        fid   = int(parts[0])
                        off   = int(parts[1])
                        cnt   = int(parts[2])
                        raw   = bytes([int(x) for x in parts[3:3+cnt]])
                    except (ValueError, IndexError):
                        continue
                    if fid not in frames:
                        frames[fid] = bytearray(FRAME_N)
                    frames[fid][off:off+cnt] = raw
                    if off + cnt >= FRAME_N:
                        arr = np.frombuffer(frames[fid], dtype=np.uint8).astype(float)
                        last_frame[:] = (arr - 127.0) / 127.0   # normalise to -1..+1
                        del frames[fid]
                        frame_count[0] += 1
                        new_frame = True

            now = time.time()
            if (new_pos or new_frame) and (now - last_draw) >= 0.05:
                last_draw = now

                if new_frame:
                    sig_line.set_ydata(last_frame)
                    # Last cycle
                    last_cycle = last_frame[-CYCLE_N:]
                    sigz_line.set_ydata(last_cycle)

                pos_txt.set_text(f"{last_pos[0]:+.3f}")
                color = "#e84855" if abs(last_pos[0]) > 0.8 else "#2d7dd2"
                pos_txt.set_color(color)
                # Position bar
                pos_bar.set_width(last_pos[0])
                pos_bar.set_x(min(0, last_pos[0]))
                pos_bar.set_color(color)

                status.set_text(
                    f"pos={last_pos[0]:+.4f}  frames={frame_count[0]}"
                )
                fig.canvas.draw_idle(); fig.canvas.flush_events()

            plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser,"!stream:0"); ser.close(); print("\n[INFO] Closed.")

if __name__ == "__main__":
    main()