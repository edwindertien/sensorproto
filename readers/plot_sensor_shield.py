#!/usr/bin/env python3
"""
Sensor Shield — matplotlib visualiser.
Parses stream ID from first field — no ambiguity between streams.

Usage:
  python plot_sensor_shield.py --port /dev/tty.usbmodemXXXX
"""
import argparse, time
from collections import deque
import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import serial

N = 150

def write_cmd(ser, s):
    s = s.strip()
    if not s: return
    print(f">>> {s}", flush=True)
    ser.write((s+"\n").encode("ascii","ignore")); ser.flush()

def send_and_wait(ser, cmd, pause=0.15):
    write_cmd(ser, cmd); time.sleep(pause)
    while ser.in_waiting: ser.readline()

def mkbuf(): return deque([0.0]*N, maxlen=N)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0); ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!rate:20")
    for i in range(1,8): send_and_wait(ser, f"!stream:+{i}")
    ser.reset_input_buffer()
    print("[INFO] Ready.")

    # buffers — keyed by name
    keys = ["A0","A1","A2","A3","A4","A5",
            "foil","strain","hall",
            "enc_pos","enc_vel",
            "capA","capB","cap_pos",
            "rc","rc_ref","us"]
    bufs = {k: mkbuf() for k in keys}
    last = {k: 0.0 for k in keys}

    def push(k, v):
        bufs[k].append(float(v)); last[k] = float(v)

    # ── layout: 5 rows × 4 cols ───────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle("Sensor Shield — all sensors", fontsize=12)
    gs = gridspec.GridSpec(5, 4, figure=fig, hspace=0.55, wspace=0.35)
    t = list(range(-N, 0))

    CLR = {
        "A0":"#2d7dd2","A1":"#3bb273","A2":"#e84855","A3":"#f18f01",
        "A4":"#7b2d8b","A5":"#555",
        "foil":"#e84855","strain":"#f18f01",
        "hall":"#7b2d8b",
        "enc_pos":"#2d7dd2","enc_vel":"#3bb273",
        "capA":"#e84855","capB":"#f18f01","cap_pos":"#7b2d8b",
        "rc":"#2d7dd2","rc_ref":"#3bb273","us":"#e84855",
    }
    axes  = {}
    lines = {}

    def make(ax, key, title, ylabel, ylim=None):
        axes[key] = ax
        l, = ax.plot(t, list(bufs[key]), color=CLR[key], lw=0.9)
        lines[key] = l
        ax.set_title(title, fontsize=8, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=7)
        ax.tick_params(labelsize=6)
        ax.grid(True, alpha=0.3)
        if ylim: ax.set_ylim(*ylim)

    # Row 0: raw analog A0–A3
    make(fig.add_subplot(gs[0,0]), "A0", "A0  Potentiometer",  "raw", (0,1023))
    make(fig.add_subplot(gs[0,1]), "A1", "A1  External J1",    "raw", (0,1023))
    make(fig.add_subplot(gs[0,2]), "A2", "A2  Foil raw",       "raw", (0,1023))
    make(fig.add_subplot(gs[0,3]), "A3", "A3  Strain raw",     "raw", (0,1023))

    # Row 1: raw A4–A5 + calibrated force
    make(fig.add_subplot(gs[1,0]), "A4",     "A4  Hall A raw",   "raw", (0,1023))
    make(fig.add_subplot(gs[1,1]), "A5",     "A5  Hall B raw",   "raw", (0,1023))
    make(fig.add_subplot(gs[1,2]), "foil",   "Foil Pressure",    "g")
    make(fig.add_subplot(gs[1,3]), "strain", "Strain Gauge",     "g")

    # Row 2: hall + encoder
    make(fig.add_subplot(gs[2,0]), "hall",    "Hall Angle",        "°")
    make(fig.add_subplot(gs[2,1]), "enc_pos", "Encoder Position",  "cnt")
    make(fig.add_subplot(gs[2,2]), "enc_vel", "Encoder Velocity",  "cnt/s")
    make(fig.add_subplot(gs[2,3]), "capA",    "Cap Slider A",      "raw")

    # Row 3: cap + RC
    make(fig.add_subplot(gs[3,0]), "capB",    "Cap Slider B",      "raw")
    make(fig.add_subplot(gs[3,1]), "cap_pos", "Cap Position",      "mm",  (-5,55))
    make(fig.add_subplot(gs[3,2]), "rc",      "RC-ADC Count",      "cnt")
    make(fig.add_subplot(gs[3,3]), "rc_ref",  "RC Reference V",    "V",   (0,5))

    # Row 4: ultrasonic + status
    make(fig.add_subplot(gs[4,0]), "us", "Ultrasonic", "cm")
    ax_st = fig.add_subplot(gs[4,1:])
    ax_st.axis("off")
    st_txt = ax_st.text(0.01, 0.85, "connecting...",
        fontsize=7.5, family="monospace", transform=ax_st.transAxes, va="top")

    plt.tight_layout(rect=[0,0.01,1,0.97])
    plt.show(block=False); plt.pause(0.05)

    # ── receive ───────────────────────────────────────────────────────────────
    rxbuf = b""; last_draw = time.time(); new_data = False

    try:
        while plt.fignum_exists(fig.number):
            w = ser.in_waiting
            if w: rxbuf += ser.read(w)

            while b"\n" in rxbuf:
                lb, rxbuf = rxbuf.split(b"\n", 1)
                line = lb.decode("utf-8","ignore").strip()
                if not line: continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2: continue

                # First field is always stream ID 1-7
                try:
                    sid = int(parts[0])
                    vals = [float(p) for p in parts[1:]]
                except ValueError:
                    continue
                if sid < 1 or sid > 7:
                    continue

                if sid == 1 and len(vals) == 6:   # analog
                    for i,k in enumerate(["A0","A1","A2","A3","A4","A5"]):
                        push(k, vals[i])
                elif sid == 2 and len(vals) == 2:  # force
                    push("foil", vals[0]); push("strain", vals[1])
                elif sid == 3 and len(vals) == 1:  # hall
                    push("hall", vals[0])
                elif sid == 4 and len(vals) == 2:  # encoder
                    push("enc_pos", vals[0]); push("enc_vel", vals[1])
                elif sid == 5 and len(vals) == 3:  # cap
                    push("capA", vals[0]); push("capB", vals[1])
                    push("cap_pos", vals[2])
                elif sid == 6 and len(vals) == 2:  # rc
                    push("rc", vals[0]); push("rc_ref", vals[1])
                elif sid == 7 and len(vals) == 1:  # us
                    push("us", vals[0])
                else:
                    continue
                new_data = True

            now = time.time()
            if new_data and (now - last_draw) >= 0.05:
                last_draw = now; new_data = False
                t = list(range(-N, 0))
                for k, l in lines.items():
                    l.set_data(t, list(bufs[k]))
                fixed = {"A0","A1","A2","A3","A4","A5","cap_pos","rc_ref"}
                for k, ax in axes.items():
                    if k not in fixed:
                        ax.relim(); ax.autoscale_view()
                st_txt.set_text(
                    f"A0={last['A0']:.0f}  A2={last['A2']:.0f}  "
                    f"foil={last['foil']:.0f}g  strain={last['strain']:.0f}g  "
                    f"hall={last['hall']:.1f}°  enc={last['enc_pos']:.0f}  "
                    f"cap={last['cap_pos']:.1f}mm  rc={last['rc']:.0f}  "
                    f"us={last['us']:.1f}cm"
                )
                fig.canvas.draw_idle(); fig.canvas.flush_events()
            else:
                plt.pause(0.005)

    except KeyboardInterrupt:
        pass
    finally:
        write_cmd(ser,"!stream:0"); ser.close(); print("\n[INFO] Closed.")

if __name__ == "__main__":
    main()