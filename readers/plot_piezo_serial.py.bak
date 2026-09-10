#!/usr/bin/env python3
"""
Piezo plates — raw + derivative + impact heatmap + drum sounds.

Stream: A0,A1,A2,A3,dA0,dA1,dA2,dA3 (8 fields)

Leonardo USB CDC fix: open with timeout=0.1 to complete CDC handshake,
then switch to non-blocking for the receive loop.

Sounds generated with pygame/numpy — no audio files needed.
  A0 = Kick, A1 = Snare, A2 = HH closed, A3 = HH open / Crash

Usage:
  python plot_piezo.py --port /dev/tty.usbmodemXXXX
"""
import argparse, time, threading
from collections import deque
import numpy as np
import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.widgets import Button
import serial

N=200; FADE_S=1.0
LABELS=["Kick","Snare","HH cl.","HH op."]
COLORS=["#2d7dd2","#e84855","#3bb273","#f18f01"]
CMAP=matplotlib.colormaps["YlOrRd"]

# ── sound synthesis ───────────────────────────────────────────────────────────
try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
    SOUND_ON = True
except Exception:
    SOUND_ON = False
    print("[WARN] pygame not available — no sound")

SR = 44100

def make_sound(samples):
    """Convert float32 samples (-1..1) to pygame Sound."""
    s = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(s)

def synth_kick(dur=0.4):
    t = np.linspace(0, dur, int(SR*dur), False)
    freq = 80 * np.exp(-t * 25)          # pitch drop
    phase = 2*np.pi * np.cumsum(freq) / SR
    env = np.exp(-t * 8)
    return make_sound(np.sin(phase) * env * 0.9)

def synth_snare(dur=0.2):
    t = np.linspace(0, dur, int(SR*dur), False)
    tone = np.sin(2*np.pi * 200 * t) * np.exp(-t * 25)
    noise = np.random.randn(len(t)) * np.exp(-t * 15)
    return make_sound((tone*0.4 + noise*0.6) * 0.8)

def synth_hh_closed(dur=0.05):
    t = np.linspace(0, dur, int(SR*dur), False)
    noise = np.random.randn(len(t))
    # High-pass character: emphasise high freq with simple filter
    env = np.exp(-t * 80)
    return make_sound(noise * env * 0.6)

def synth_hh_open(dur=0.3):
    t = np.linspace(0, dur, int(SR*dur), False)
    noise = np.random.randn(len(t))
    env = np.exp(-t * 8)
    return make_sound(noise * env * 0.5)

if SOUND_ON:
    print("[INFO] Synthesising drum sounds...", end="", flush=True)
    SOUNDS = [synth_kick(), synth_snare(), synth_hh_closed(), synth_hh_open()]
    print(" done")
else:
    SOUNDS = [None]*4

def play_sound(ch, velocity):
    """Play drum sound for channel ch, scaled by velocity 0-1."""
    if not SOUND_ON or SOUNDS[ch] is None: return
    vol = min(1.0, velocity / 150.0)
    SOUNDS[ch].set_volume(vol)
    SOUNDS[ch].play()

# ── serial helpers ────────────────────────────────────────────────────────────
def write_cmd(ser, s):
    s = s.strip()
    if not s: return
    ser.write((s+"\n").encode("ascii","ignore")); ser.flush()

def send_and_wait(ser, cmd, pause=0.2):
    write_cmd(ser, cmd); time.sleep(pause)
    while ser.in_waiting: ser.readline()

def open_serial(port, baud):
    """Leonardo: needs a clean DTR low→high transition.
    Explicitly drop DTR first (in case previous run left it high),
    wait, then assert DTR high to give while(!Serial) its rising edge."""
    ser = serial.Serial()
    ser.port = port; ser.baudrate = baud; ser.timeout = 0.0
    ser.dtr = False; ser.rts = False
    ser.open()
    time.sleep(0.3)          # hold DTR low — OS must see it de-asserted
    ser.dtr = True           # rising edge: releases while(!Serial)
    ser.rts = True
    time.sleep(1.5)          # give setup() time to complete
    ser.reset_input_buffer()
    return ser

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--thr",  type=int, default=30)
    ap.add_argument("--nosound", action="store_true")
    args = ap.parse_args()
    if args.nosound:
        global SOUND_ON; SOUND_ON = False

    ser = open_serial(args.port, args.baud)
    send_and_wait(ser, "!stream:0")      # stop anything left from previous run
    ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!rate:200")
    send_and_wait(ser, "!stream:+1")
    time.sleep(0.3); ser.reset_input_buffer()
    print("[INFO] Ready.")

    raw_bufs  =[deque([512]*N,maxlen=N) for _ in range(4)]
    deriv_bufs=[deque([0]*N,  maxlen=N) for _ in range(4)]
    last_raw=[512]*4; impacts=[(0,0.0)]*4; threshold=[args.thr]
    last_hit=[0.0]*4   # timestamp of last sound trigger per channel

    # ── figure ────────────────────────────────────────────────────────────────
    fig=plt.figure(figsize=(15,9)); fig.suptitle("Piezo Drum Pads",fontsize=12)
    gs=gridspec.GridSpec(4,3,figure=fig,width_ratios=[2.0,2.0,1.0],hspace=0.45,wspace=0.35)
    t_ax=list(range(-N,0)); raw_lines=[]; drv_lines=[]; thr_lines=[]

    for i in range(4):
        ax_r=fig.add_subplot(gs[i,0])
        lr,=ax_r.plot(t_ax,list(raw_bufs[i]),color=COLORS[i],lw=0.8)
        ax_r.axhline(512,color="gray",lw=0.5,ls="--"); ax_r.set_ylim(0,1023)
        ax_r.set_ylabel(f"A{i}",fontsize=7); ax_r.tick_params(labelsize=6)
        ax_r.grid(True,alpha=0.25)
        if i==0: ax_r.set_title("Raw ADC",fontsize=8)
        raw_lines.append(lr)

        ax_d=fig.add_subplot(gs[i,1])
        ld,=ax_d.plot(t_ax,list(deriv_bufs[i]),color=COLORS[i],lw=0.8)
        tp=ax_d.axhline( threshold[0],color="tomato",lw=0.8,ls="--",alpha=0.7)
        tn=ax_d.axhline(-threshold[0],color="tomato",lw=0.8,ls="--",alpha=0.7)
        ax_d.axhline(0,color="gray",lw=0.5); ax_d.set_ylim(-200,200)
        ax_d.set_ylabel(f"dA{i}",fontsize=7); ax_d.tick_params(labelsize=6)
        ax_d.grid(True,alpha=0.25)
        if i==0: ax_d.set_title("Derivative",fontsize=8)
        drv_lines.append(ld); thr_lines.append((tp,tn))

    ax_pad=fig.add_subplot(gs[:,2]); ax_pad.set_xlim(0,2); ax_pad.set_ylim(0,2)
    ax_pad.set_aspect("equal"); ax_pad.axis("off"); ax_pad.set_title("Impact",fontsize=9)
    POS=[(0.5,1.5),(1.5,1.5),(0.5,0.5),(1.5,0.5)]
    norm=Normalize(vmin=0,vmax=200); sm=ScalarMappable(cmap=CMAP,norm=norm)
    circles=[]; val_txts=[]
    for i,(cx,cy) in enumerate(POS):
        c=mpatches.Circle((cx,cy),0.40,facecolor="#eee",edgecolor="#ccc",lw=2.0,zorder=2)
        ax_pad.add_patch(c); circles.append(c)
        ax_pad.text(cx,cy+0.12,f"A{i}",ha="center",va="center",fontsize=13,fontweight="bold",color="#888",zorder=3)
        ax_pad.text(cx,cy-0.20,LABELS[i],ha="center",fontsize=7,color="#666")
        val_txts.append(ax_pad.text(cx,cy-0.50,"",ha="center",fontsize=7,color="#333"))
    fig.colorbar(sm,ax=ax_pad,orientation="horizontal",fraction=0.04,pad=0.02).set_label("Peak deriv",fontsize=7)

    def _update_thr():
        for tp,tn in thr_lines:
            tp.set_ydata([ threshold[0], threshold[0]])
            tn.set_ydata([-threshold[0],-threshold[0]])

    _btns=[]
    for xi,(lbl,fn) in enumerate([
        ("thr +5", lambda: threshold.__setitem__(0,min(200,threshold[0]+5))),
        ("thr -5", lambda: threshold.__setitem__(0,max(5,  threshold[0]-5))),
        ("smooth+",lambda: write_cmd(ser,"!piezo.smooth:0.9")),
        ("smooth-",lambda: write_cmd(ser,"!piezo.smooth:0.4")),
    ]):
        ax_b=fig.add_axes([0.54+xi*0.11,0.01,0.10,0.03])
        b=Button(ax_b,lbl,color="0.88",hovercolor="0.72"); b.label.set_fontsize(7)
        def mk(f): return lambda e:(f(),_update_thr())
        b.on_clicked(mk(fn)); _btns.append(b)

    closed = [False]
    def do_close():
        if closed[0]: return
        closed[0] = True
        if ser.is_open:
            write_cmd(ser, "!stream:0")
            ser.dtr = False
            time.sleep(0.1)
            ser.close()
        print("\n[INFO] Closed.")

    fig.canvas.mpl_connect('close_event', lambda e: do_close())

    status=fig.text(0.01,0.01,"A0=-- A1=-- A2=-- A3=--  thr=--",fontsize=7.5,family="monospace",color="0.35")
    plt.tight_layout(rect=[0,0.06,1,0.96]); plt.show(block=False); plt.pause(0.1)

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

                now=time.time()
                for i in range(4):
                    last_raw[i]=vals[i]
                    raw_bufs[i].append(vals[i])
                    deriv_bufs[i].append(vals[i+4])
                    av=abs(vals[i+4])
                    if av>=threshold[0]:
                        pk,th=impacts[i]
                        if av>pk or (now-th)>0.05:
                            impacts[i]=(av,now)
                            # trigger sound with retrigger guard
                            if (now-last_hit[i])>0.08:
                                last_hit[i]=now
                                threading.Thread(target=play_sound,
                                                 args=(i,av),daemon=True).start()
                new_data=True

            now=time.time()
            if new_data and (now-last_draw)>=0.04:
                last_draw=now
                t_ax=list(range(-N,0))
                for i in range(4):
                    raw_lines[i].set_data(t_ax,list(raw_bufs[i]))
                    drv_lines[i].set_data(t_ax,list(deriv_bufs[i]))
                for i in range(4):
                    pk,th=impacts[i]
                    fade=max(0.0,1.0-(now-th)/FADE_S)
                    circles[i].set_facecolor(sm.to_rgba(pk*fade))
                    val_txts[i].set_text(f"{int(pk*fade)}" if fade>0.05 else "")
                status.set_text(f"A0={last_raw[0]:.0f} A1={last_raw[1]:.0f} A2={last_raw[2]:.0f} A3={last_raw[3]:.0f}  thr={threshold[0]}")
                fig.canvas.draw_idle(); fig.canvas.flush_events()

            plt.pause(0.005)

    except KeyboardInterrupt:
        do_close()
    except Exception as e:
        print(f"\n[ERR] {e}")
        do_close()
    finally:
        try:
            do_close()
        except Exception:
            pass

if __name__=="__main__":
    main()