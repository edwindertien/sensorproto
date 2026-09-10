#!/usr/bin/env python3
"""
LVDT — Linear Variable Differential Transformer visualiser.

Stream 1: lvdt.pos  — f32 position (-1 to +1)
Stream 2: lvdt.frame — frame chunks: id, off, cnt, s0..sN (CSV integers)

Layout:
  Top    : Full 480-sample oscilloscope (receiver + reference overlay)
  Middle : Single cycle zoom (last cycle, shows phase shift clearly)
  Bottom : Position strip chart + large readout

Usage:
  python plot_lvdt.py --port /dev/tty.usbmodemXXXX
"""
import argparse, time
from collections import deque
import numpy as np
import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button
import serial

FRAME_N = 480
CYCLE_N = 48
POS_N   = 200

def write_cmd(ser, s):
    s = s.strip()
    if not s: return
    ser.write((s+"\n").encode("ascii","ignore")); ser.flush()

def send_and_wait(ser, cmd, pause=0.15):
    write_cmd(ser, cmd); time.sleep(pause)
    while ser.in_waiting: ser.readline()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=38400)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0); ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!stream:+1")
    send_and_wait(ser, "!stream:+2")
    time.sleep(0.3); ser.reset_input_buffer()
    print("[INFO] Ready.")

    # Frame assembly
    frames     = {}   # fid -> np.ndarray(FRAME_N)
    last_frame = np.full(FRAME_N, 127.0)
    frame_count = [0]

    # Reference: sine 0..255 as the firmware generates on pin 9
    ref_raw = np.array([127*np.sin(2*np.pi*n/CYCLE_N)+127 for n in range(CYCLE_N)])
    ref_full = np.tile(ref_raw, FRAME_N//CYCLE_N)  # 480 samples, 0..255

    # Position
    pos_buf  = deque([0.0]*POS_N, maxlen=POS_N)
    last_pos = [0.0]

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 9))
    fig.suptitle("LVDT — Linear Variable Differential Transformer", fontsize=12)
    gs = gridspec.GridSpec(3, 2, figure=fig,
                           width_ratios=[3.0, 1.0],
                           height_ratios=[1.4, 1.0, 1.0],
                           hspace=0.5, wspace=0.3)

    x480 = np.arange(FRAME_N)
    x48  = np.arange(CYCLE_N)

    # Row 0: full frame oscilloscope
    ax_osc = fig.add_subplot(gs[0, 0])
    ref_osc, = ax_osc.plot(x480, ref_full, color="#aaa", lw=0.7, ls="--",
                            alpha=0.6, label="excitation ref (pin 9)")
    sig_osc, = ax_osc.plot(x480, last_frame, color="#2d7dd2", lw=0.9,
                            label="receiver (A1)")
    ax_osc.set_ylim(-10, 265)
    ax_osc.set_xlim(0, FRAME_N)
    ax_osc.set_ylabel("ADC counts (0–255)")
    ax_osc.set_xlabel(f"sample  ({CYCLE_N} per cycle = 10ms at 100Hz)")
    ax_osc.set_title("480-sample frame — 10 excitation cycles", fontsize=9)
    ax_osc.legend(fontsize=7, loc="upper right"); ax_osc.grid(True, alpha=0.25)
    ax_osc.axhline(127, color="gray", lw=0.4, ls=":")

    # Row 1: single cycle zoom
    ax_cyc = fig.add_subplot(gs[1, 0])
    ref_cyc, = ax_cyc.plot(x48, ref_raw, color="#aaa", lw=0.8, ls="--",
                            alpha=0.6, label="excitation ref")
    sig_cyc, = ax_cyc.plot(x48, last_frame[-CYCLE_N:], color="#e84855",
                            lw=1.3, label="receiver last cycle")
    ax_cyc.set_ylim(-10, 265)
    ax_cyc.set_xlim(0, CYCLE_N-1)
    ax_cyc.set_ylabel("ADC counts")
    ax_cyc.set_xlabel("sample in cycle")
    ax_cyc.set_title("Single cycle zoom — amplitude=displacement, phase=direction", fontsize=9)
    ax_cyc.legend(fontsize=7, loc="upper right"); ax_cyc.grid(True, alpha=0.25)
    ax_cyc.axhline(127, color="gray", lw=0.4, ls=":")

    # Row 2: position strip chart
    ax_pos = fig.add_subplot(gs[2, 0])
    t_ax   = list(range(-POS_N, 0))
    pos_line, = ax_pos.plot(t_ax, list(pos_buf), color="#3bb273", lw=1.0)
    ax_pos.axhline(0, color="gray", lw=0.5)
    ax_pos.set_ylim(-1.2, 1.2)
    ax_pos.set_ylabel("position"); ax_pos.set_xlabel("samples")
    ax_pos.set_title("Position (0=centre, ±1=full scale)", fontsize=9)
    ax_pos.grid(True, alpha=0.25)

    status = fig.text(0.01, 0.01, "pos=--  frames=0",
        fontsize=7.5, family="monospace", color="0.35")

    # ── right panel ───────────────────────────────────────────────────────────
    ax_pan = fig.add_subplot(gs[:, 1]); ax_pan.axis("off")

    pos_txt = fig.text(0.81, 0.72, "+0.000",
        fontsize=36, fontweight="bold", color="#3bb273",
        ha="center", va="center")
    fig.text(0.81, 0.65, "position", fontsize=9, color="gray",
             ha="center", va="center")

    ax_bar = fig.add_axes([0.755, 0.58, 0.18, 0.05])
    ax_bar.set_xlim(-1.1, 1.1); ax_bar.set_ylim(0,1)
    ax_bar.axvline(0, color="gray", lw=0.8)
    ax_bar.set_xticks([-1, 0, 1]); ax_bar.tick_params(labelsize=7)
    ax_bar.get_yaxis().set_visible(False)
    pos_bar = ax_bar.barh([0.5],[0.0],height=0.5,color="#3bb273",align="center")[0]

    PX, PW, BH, BG = 0.75, 0.22, 0.044, 0.007
    def lbl(text,y): fig.text(PX,y,text,fontsize=7.5,fontweight="bold",color="0.35")
    def mkbtn(text,y,w=1.0,xoff=0.0,color="0.88"):
        ax_b=fig.add_axes([PX+xoff*PW,y,PW*w-0.003,BH*0.85])
        b=Button(ax_b,text,color=color,hovercolor="0.72"); b.label.set_fontsize(7); return b
    def row3(y,items):
        btns=[]
        for xi,(lt,cmd) in enumerate(items):
            ax_b=fig.add_axes([PX+xi*(PW/3),y,PW/3-0.003,BH*0.85])
            b=Button(ax_b,lt,color="0.88",hovercolor="0.72"); b.label.set_fontsize(6.5)
            def mk(c): return lambda e: write_cmd(ser,c)
            b.on_clicked(mk(cmd)); btns.append(b)
        return btns

    y=0.52
    lbl("── zero / scale ──",y); y-=BH*0.7
    btn_zero=mkbtn("@lvdt.zero",y,w=0.48,color="0.75")
    btn_q=mkbtn("?lvdt.pos",y,w=0.48,xoff=0.52); y-=BH+BG*2
    _s_btns=row3(y,[("×0.5","!lvdt.scale:0.5"),("×1","!lvdt.scale:1.0"),("×2","!lvdt.scale:2.0")])
    y-=BH+BG*2

    lbl("── streams ──",y); y-=BH*0.7
    btn_both=mkbtn("pos+frame",y,w=0.48,color="0.80")
    btn_pos=mkbtn("pos only",y,w=0.48,xoff=0.52); y-=BH+BG*2

    ax_log=fig.add_axes([PX,y-0.10,PW,0.10]); ax_log.axis("off")
    log_lines=[""]*4
    log_txt=ax_log.text(0,1,"",fontsize=6.5,va="top",family="monospace")
    def log(msg):
        log_lines.pop(0); log_lines.append(msg[:28])
        log_txt.set_text("\n".join(log_lines)); fig.canvas.draw_idle()

    btn_zero.on_clicked(lambda e:(write_cmd(ser,"@lvdt.zero"),log("zeroed")))
    btn_q.on_clicked(lambda e:log(f"pos={last_pos[0]:.4f}"))
    btn_both.on_clicked(lambda e:(write_cmd(ser,"!stream:+1"),write_cmd(ser,"!stream:+2")))
    btn_pos.on_clicked(lambda e:(write_cmd(ser,"!stream:0"),write_cmd(ser,"!stream:+1")))

    plt.tight_layout(rect=[0,0.04,1,0.96])
    plt.show(block=False); plt.pause(0.1)

    # ── receive loop ──────────────────────────────────────────────────────────
    rxbuf=b""; last_draw=time.time()

    try:
        while plt.fignum_exists(fig.number):
            w=ser.in_waiting
            if w: rxbuf+=ser.read(w)

            new_pos=False; new_frame=False
            while b"\n" in rxbuf:
                lb,rxbuf=rxbuf.split(b"\n",1)
                line=lb.decode("utf-8","ignore").strip()
                if not line: continue
                parts=[p.strip() for p in line.split(",")]
                try:
                    vals=[float(p) for p in parts]
                except ValueError:
                    continue

                n=len(vals)
                if n==1:                          # stream 1: position
                    last_pos[0]=vals[0]
                    pos_buf.append(vals[0])
                    new_pos=True
                elif n>=4:                        # stream 2: frame chunk
                    try:
                        fid=int(vals[0]); off=int(vals[1]); cnt=int(vals[2])
                        samples=vals[3:3+cnt]
                        if fid not in frames:
                            frames[fid]=np.full(FRAME_N,127.0)
                        frames[fid][off:off+cnt]=samples
                        if off+cnt>=FRAME_N:
                            last_frame[:]=frames.pop(fid)
                            frame_count[0]+=1
                            new_frame=True
                    except (ValueError,IndexError):
                        pass

            now=time.time()
            if (new_pos or new_frame) and (now-last_draw)>=0.05:
                last_draw=now

                if new_frame:
                    sig_osc.set_ydata(last_frame)
                    sig_cyc.set_ydata(last_frame[-CYCLE_N:])

                t_ax=list(range(-POS_N,0))
                pos_line.set_data(t_ax,list(pos_buf))

                p=last_pos[0]
                pos_txt.set_text(f"{p:+.3f}")
                col="#e84855" if abs(p)>0.8 else "#3bb273"
                pos_txt.set_color(col)
                pos_bar.set_width(p); pos_bar.set_x(min(0,p)); pos_bar.set_color(col)

                status.set_text(f"pos={p:+.4f}  frames={frame_count[0]}")
                fig.canvas.draw_idle(); fig.canvas.flush_events()

            plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser,"!stream:0"); ser.close(); print("\n[INFO] Closed.")

if __name__=="__main__":
    main()