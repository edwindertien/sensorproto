#!/usr/bin/env python3
"""
Pololu QTR-8RC visualiser.

Connects to stream 1 (raw 8 values) only.
All processing done in Python: binary, gray code, line position.

Layout:
  Top    : 8 heatmap squares (raw decay time → colour)
  Row 2  : 8 binary squares + binary value + gray code value
  Row 3  : raw decay strip charts (all 8 overlaid)
  Bottom : line position strip chart

Usage:
  python plot_qtr8.py --port /dev/tty.usbmodemXXXX [--thr 1000] [--timeout 2500]
"""
import argparse, time
from collections import deque
import numpy as np
import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.widgets import Button, TextBox
import serial

N       = 200    # strip chart samples
TIMEOUT = 2500

def write_cmd(ser, s):
    s = s.strip()
    if not s: return
    ser.write((s+"\n").encode("ascii","ignore")); ser.flush()

def send_and_wait(ser, cmd, pause=0.15):
    write_cmd(ser, cmd); time.sleep(pause)
    while ser.in_waiting: ser.readline()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",    required=True)
    ap.add_argument("--baud",    type=int, default=115200)
    ap.add_argument("--thr",     type=int, default=1000,
                    help="binary threshold in µs")
    ap.add_argument("--timeout", type=int, default=TIMEOUT,
                    help="full-black timeout in µs")
    ap.add_argument("--rate",    type=int, default=20)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0); ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, f"!rate:{args.rate}")
    send_and_wait(ser, f"!qtr.thr:{args.thr}")
    send_and_wait(ser, f"!qtr.timeout:{args.timeout}")
    send_and_wait(ser, "!stream:+1")   # raw only
    time.sleep(0.3); ser.reset_input_buffer()
    print("[INFO] Ready.")

    raw_bufs = [deque([0]*N, maxlen=N) for _ in range(8)]
    last_raw = [0]*8
    threshold = [args.thr]
    timeout_v = [args.timeout]

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 9))
    fig.suptitle("Pololu QTR-8RC Reflectance Sensor", fontsize=12)
    gs = gridspec.GridSpec(4, 2, figure=fig,
                           width_ratios=[3.5, 1.0],
                           height_ratios=[0.7, 0.7, 1.5, 1.0],
                           hspace=0.55, wspace=0.3)

    # Row 0: heatmap squares
    ax_h = fig.add_subplot(gs[0,0])
    ax_h.set_xlim(-0.5,7.5); ax_h.set_ylim(-0.5,0.5)
    ax_h.set_aspect("equal"); ax_h.axis("off")
    ax_h.set_title("Raw reflectance  (green=white surface, red=black surface)", fontsize=8)
    norm_r = Normalize(vmin=0, vmax=TIMEOUT)
    cmap_r = matplotlib.colormaps["RdYlGn_r"]
    sm_r   = ScalarMappable(cmap=cmap_r, norm=norm_r)
    heat_rects=[]; heat_txts=[]
    for i in range(8):
        r = mpatches.FancyBboxPatch((i-0.45,-0.45),0.9,0.9,
            boxstyle="round,pad=0.05",facecolor="0.8",edgecolor="white",lw=1.5,zorder=2)
        ax_h.add_patch(r); heat_rects.append(r)
        ax_h.text(i,0.28,f"S{i}",ha="center",fontsize=8,fontweight="bold",color="white",zorder=3)
        heat_txts.append(ax_h.text(i,-0.12,"---",ha="center",fontsize=7,color="white",zorder=3))
    fig.colorbar(sm_r,ax=ax_h,orientation="vertical",fraction=0.015,pad=0.01).set_label("µs",fontsize=7)

    # Row 1: binary squares + values
    ax_b = fig.add_subplot(gs[1,0])
    ax_b.set_xlim(-0.5,7.5); ax_b.set_ylim(-0.5,0.5)
    ax_b.set_aspect("equal"); ax_b.axis("off")
    ax_b.set_title("Binary threshold", fontsize=8)
    bin_rects=[]
    for i in range(8):
        r = mpatches.FancyBboxPatch((i-0.45,-0.45),0.9,0.9,
            boxstyle="round,pad=0.05",facecolor="#eee",edgecolor="#ccc",lw=1.5,zorder=2)
        ax_b.add_patch(r); bin_rects.append(r)
        ax_b.text(i,0.0,f"S{i}",ha="center",fontsize=8,fontweight="bold",color="#888",zorder=3)
    bin_val_txt  = ax_b.text(7.8, 0.3,"bin:\n---",  fontsize=7.5,va="top",family="monospace")
    gray_val_txt = ax_b.text(7.8,-0.1,"gray:\n---", fontsize=7.5,va="top",family="monospace")

    # Row 2: raw strip charts
    ax_r = fig.add_subplot(gs[2,0])
    colors8 = plt.cm.tab10(np.linspace(0,0.8,8))
    raw_lines=[]
    t_ax = list(range(-N,0))
    for i in range(8):
        l,=ax_r.plot(t_ax,list(raw_bufs[i]),color=colors8[i],lw=0.8,
                     label=f"S{i}",alpha=0.85)
        raw_lines.append(l)
    thr_line = ax_r.axhline(threshold[0],color="red",lw=1.0,ls="--",alpha=0.7,label="thr")
    ax_r.set_ylim(0,TIMEOUT)
    ax_r.set_ylabel("Decay (µs)",fontsize=8); ax_r.set_xlabel("samples",fontsize=7)
    ax_r.set_title("Raw decay times — all 8 sensors",fontsize=8)
    ax_r.legend(fontsize=6,loc="upper right",ncol=4); ax_r.grid(True,alpha=0.25)

    # Row 3: binary value, gray code, sub-pixel line position — all 0..255
    ax_p = fig.add_subplot(gs[3,0])
    bin_buf  = deque([0]*N, maxlen=N)
    gray_buf = deque([0]*N, maxlen=N)
    line_buf = deque([np.nan]*N, maxlen=N)
    bin_line,  = ax_p.plot(t_ax, list(bin_buf),  color="#2d7dd2", lw=1.0, label="binary (0–255)")
    gray_line, = ax_p.plot(t_ax, list(gray_buf), color="#3bb273", lw=1.0, label="gray code (0–255)")
    line_line, = ax_p.plot(t_ax, list(line_buf), color="#e84855", lw=1.5, label="line pos (0–255)")
    ax_p.set_ylim(-5, 260)
    ax_p.set_ylabel("Value (0–255)", fontsize=8)
    ax_p.set_xlabel("samples", fontsize=7)
    ax_p.set_title("Binary  |  Gray code  |  Line position  — 0–255", fontsize=8)
    ax_p.grid(True, alpha=0.25)
    val_txt = ax_p.text(0.01, 0.95, "", transform=ax_p.transAxes,
                        fontsize=7.5, va="top", family="monospace")

    # Checkboxes to toggle each line
    from matplotlib.widgets import CheckButtons
    ax_chk = fig.add_axes([0.01, 0.05, 0.08, 0.10])
    chk = CheckButtons(ax_chk, ["binary","gray","line pos"], [True, True, True])
    chk.labels[0].set_fontsize(7); chk.labels[1].set_fontsize(7); chk.labels[2].set_fontsize(7)
    def cb_chk(label):
        if label == "binary":  bin_line.set_visible(not bin_line.get_visible())
        if label == "gray":    gray_line.set_visible(not gray_line.get_visible())
        if label == "line pos":line_line.set_visible(not line_line.get_visible())
        fig.canvas.draw_idle()
    chk.on_clicked(cb_chk)

    # ── controls ──────────────────────────────────────────────────────────────
    ax_pan=fig.add_subplot(gs[:,1]); ax_pan.axis("off")
    PX,PW,BH,BG = 0.775, 0.20, 0.045, 0.007

    def lbl(text,y): fig.text(PX,y,text,fontsize=7.5,fontweight="bold",color="0.35")
    def mkbtn(text,y,w=1.0,xoff=0.0,color="0.88"):
        ax_b=fig.add_axes([PX+xoff*PW,y,PW*w-0.003,BH*0.85])
        b=Button(ax_b,text,color=color,hovercolor="0.72"); b.label.set_fontsize(7); return b

    y=0.88
    lbl("── threshold (µs) ──",y); y-=BH*0.7
    ax_tb=fig.add_axes([PX,y,PW,BH*0.85])
    tb_thr=TextBox(ax_tb,"",initial=str(args.thr))
    y-=BH+BG
    btn_thr=mkbtn("set threshold",y,color="0.80"); y-=BH+BG*2

    lbl("── presets ──",y); y-=BH*0.7
    _p_btns=[]
    for xi,(lt,v) in enumerate([("500",500),("1000",1000),("1500",1500),("2000",2000)]):
        ax_b=fig.add_axes([PX+(xi%2)*(PW*0.52),y-(xi//2)*(BH+BG),PW*0.48-0.003,BH*0.85])
        b=Button(ax_b,lt,color="0.88",hovercolor="0.72"); b.label.set_fontsize(7)
        def mk(val): return lambda e:_set_thr(val)
        b.on_clicked(mk(v)); _p_btns.append(b)
    y-=2*(BH+BG)+BG*2

    lbl("── calibrate ──",y); y-=BH*0.7
    btn_cal=mkbtn("auto-calibrate",y,color="0.78"); y-=BH+BG*2

    lbl("── timeout (µs) ──",y); y-=BH*0.7
    ax_to=fig.add_axes([PX,y,PW,BH*0.85])
    tb_to=TextBox(ax_to,"",initial=str(args.timeout))
    y-=BH+BG
    btn_to=mkbtn("set timeout",y); y-=BH+BG*2

    lbl("── rate ──",y); y-=BH*0.7
    _r_btns=[]
    for xi,(lt,v) in enumerate([("10Hz",10),("20Hz",20),("50Hz",50)]):
        ax_b=fig.add_axes([PX+xi*(PW/3),y,PW/3-0.003,BH*0.85])
        b=Button(ax_b,lt,color="0.88",hovercolor="0.72"); b.label.set_fontsize(7)
        def mkr(val): return lambda e:write_cmd(ser,f"!rate:{val}")
        b.on_clicked(mkr(v)); _r_btns.append(b)

    ax_log=fig.add_axes([PX,0.02,PW,0.08]); ax_log.axis("off")
    log_lines=[""]*4
    log_txt=ax_log.text(0,1,"",fontsize=6.5,va="top",family="monospace")
    def log(msg):
        log_lines.pop(0); log_lines.append(msg[:32])
        log_txt.set_text("\n".join(log_lines)); fig.canvas.draw_idle()

    status=fig.text(0.01,0.01,"s0=-- ... s7=--  thr=--  pos=--",
                    fontsize=7.5,family="monospace",color="0.35")

    def _set_thr(v):
        threshold[0]=v; tb_thr.set_val(str(v))
        write_cmd(ser,f"!qtr.thr:{v}")
        thr_line.set_ydata([v,v]); log(f"  thr → {v}µs")

    def _auto_cal():
        """Set threshold to midpoint of current raw values."""
        if any(r > 0 for r in last_raw):
            mid = (min(last_raw) + max(last_raw)) // 2
            _set_thr(mid); log(f"  auto thr → {mid}µs")

    btn_thr.on_clicked(lambda e: _set_thr(int(tb_thr.text.strip()) if tb_thr.text.strip().isdigit() else threshold[0]))
    btn_cal.on_clicked(lambda e: _auto_cal())

    def cb_to(e):
        try:
            v=int(tb_to.text.strip())
            timeout_v[0]=v; write_cmd(ser,f"!qtr.timeout:{v}")
            ax_r.set_ylim(0,v); log(f"  timeout → {v}µs")
        except ValueError: log("  ! invalid")
    btn_to.on_clicked(cb_to)

    plt.tight_layout(rect=[0,0.04,1,0.97])
    plt.show(block=False); plt.pause(0.1)

    # ── receive loop ──────────────────────────────────────────────────────────
    rxbuf=b""; last_draw=time.time()

    try:
        while plt.fignum_exists(fig.number):
            w=ser.in_waiting
            if w: rxbuf+=ser.read(w)

            new_data=False
            while b"\n" in rxbuf:
                lb,rxbuf=rxbuf.split(b"\n",1)
                line=lb.decode("utf-8","ignore").strip()
                if not line: continue
                parts=[p.strip() for p in line.split(",")]
                if len(parts)!=8: continue
                try:
                    vals=[float(p) for p in parts]
                except ValueError:
                    continue

                # Stream 1: 8 raw decay times
                last_raw[:] = [int(v) for v in vals]
                for i in range(8):
                    raw_bufs[i].append(last_raw[i])

                # Derive binary
                thr = threshold[0]
                binary = [1 if r >= thr else 0 for r in last_raw]

                # Binary value 0..255 (S0=MSB, S7=LSB)
                bin_val = sum(binary[i] << (7-i) for i in range(8))

                # Gray code 0..255
                gray_val = bin_val ^ (bin_val >> 1)

                # Line position 0..255: weighted centroid of all 8 sensors.
                # No threshold — raw decay values as weights directly.
                w_sum = sum(last_raw)
                if w_sum > 0:
                    centroid = sum(i * last_raw[i] for i in range(8)) / w_sum
                    line_pos = centroid / 7.0 * 255.0
                else:
                    line_pos = np.nan

                bin_buf.append(bin_val)
                gray_buf.append(gray_val)
                line_buf.append(line_pos)

                new_data = True

            now=time.time()
            if new_data and (now-last_draw)>=0.04:
                last_draw=now
                # Derive for display
                thr=threshold[0]
                binary=[1 if r>=thr else 0 for r in last_raw]
                bin_val = sum(binary[i]<<(7-i) for i in range(8))
                gray_val = bin_val ^ (bin_val >> 1)

                # Heatmap
                for i in range(8):
                    heat_rects[i].set_facecolor(sm_r.to_rgba(last_raw[i]))
                    heat_txts[i].set_text(str(last_raw[i]))

                # Binary squares
                for i in range(8):
                    if binary[i]:
                        bin_rects[i].set_facecolor("#111")
                        bin_rects[i].set_edgecolor("#111")
                    else:
                        bin_rects[i].set_facecolor("#f0f0f0")
                        bin_rects[i].set_edgecolor("#ccc")
                bin_val_txt.set_text(f"bin:\n{bin_val:08b}\n({bin_val})")
                gray_val_txt.set_text(f"gray:\n{gray_val:08b}\n({gray_val})")

                # Strip charts
                t_ax=list(range(-N,0))
                for i in range(8):
                    raw_lines[i].set_data(t_ax,list(raw_bufs[i]))

                # Bottom: all three 0-255 values
                bin_line.set_data(t_ax,  list(bin_buf))
                gray_line.set_data(t_ax, list(gray_buf))
                line_line.set_data(t_ax, list(line_buf))

                lp_vals = [v for v in line_buf if not np.isnan(v)]
                lp_str  = f"{lp_vals[-1]:.1f}" if lp_vals else "---"
                val_txt.set_text(
                    f"bin={bin_val:3d} ({bin_val:08b})  "
                    f"gray={gray_val:3d} ({gray_val:08b})  "
                    f"line={lp_str}"
                )

                pos_str = lp_str
                status.set_text(
                    f"s0={last_raw[0]} s1={last_raw[1]} s2={last_raw[2]} s3={last_raw[3]} "
                    f"s4={last_raw[4]} s5={last_raw[5]} s6={last_raw[6]} s7={last_raw[7]}  "
                    f"thr={thr}  pos={pos_str}"
                )
                fig.canvas.draw_idle(); fig.canvas.flush_events()

            plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser,"!stream:0"); ser.close(); print("\n[INFO] Closed.")

if __name__=="__main__":
    main()