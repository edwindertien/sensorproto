#!/usr/bin/env python3
"""
HX711 load cell — live monitor + calibration panel.

Supports two load cells (hx and hx2) simultaneously.
Calibration procedure is guided via the control panel.

Usage:
  python plot_load_cell.py --port /dev/tty.usbmodemXXXX
  python plot_load_cell.py --port /dev/tty.usbmodemXXXX --units N --rate 5
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

# ── serial ────────────────────────────────────────────────────────────────────

def write_cmd(ser, s):
    if not s.endswith("\n"):
        s += "\n"
    ser.write(s.encode("ascii", errors="ignore"))
    ser.flush()

def send_and_wait(ser, cmd, pause=0.15):
    write_cmd(ser, cmd)
    time.sleep(pause)
    while ser.in_waiting:
        ser.readline()

def parse_stream(line):
    """raw(i32), value(f32)"""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), float(parts[1])
    except ValueError:
        return None

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",   required=True)
    ap.add_argument("--baud",   type=int,   default=115200)
    ap.add_argument("--rate",   type=int,   default=5)
    ap.add_argument("--chart",  type=int,   default=120)
    ap.add_argument("--units",  default="g", help="unit label for Y axis (g, N, kg)")
    args = ap.parse_args()

    print(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    time.sleep(2.0)
    ser.reset_input_buffer()
    send_and_wait(ser, "!format:csv")
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, f"!rate:{args.rate}")
    # enable both streams
    send_and_wait(ser, "!stream:+1")
    send_and_wait(ser, "!stream:+2")
    ser.reset_input_buffer()
    print("[INFO] Ready.")

    # ── state ─────────────────────────────────────────────────────────────────
    N = args.chart
    val1_buf = deque([0.0]*N, maxlen=N)
    val2_buf = deque([0.0]*N, maxlen=N)
    raw1_last = 0
    raw2_last = 0
    val1_last = 0.0
    val2_last = 0.0

    # calibration state per cell
    tare_raw = [0, 0]       # captured tare counts
    cal_raw  = [0, 0]       # captured counts at known weight
    cal_done = [False, False]

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 7))
    fig.suptitle("HX711 load cell monitor + calibration", fontsize=11)

    gs = gridspec.GridSpec(1, 2, figure=fig, width_ratios=[2.5, 1.2], wspace=0.35)
    ax_val = fig.add_subplot(gs[0])
    ax_pan = fig.add_subplot(gs[1])
    ax_pan.set_visible(False)

    t_ax = list(range(-N, 0))
    v1l, = ax_val.plot(t_ax, list(val1_buf), color="steelblue", lw=1.0, label=f"cell 1 ({args.units})")
    v2l, = ax_val.plot(t_ax, list(val2_buf), color="tomato",    lw=1.0, label=f"cell 2 ({args.units})")
    ax_val.axhline(0, color="gray", lw=0.5)
    ax_val.set_ylabel(f"weight ({args.units})")
    ax_val.set_xlabel("samples")
    ax_val.legend(loc="upper left", fontsize=8)
    ax_val.grid(True, alpha=0.3)

    status = fig.text(0.01, 0.01,
        "cell1: raw=-- val=--   cell2: raw=-- val=--",
        fontsize=7.5, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])

    # ── control panel ─────────────────────────────────────────────────────────
    PX = 0.655
    PW = 0.32
    BH = 0.042
    BG = 0.006
    TY = 0.88

    fig.text(PX, TY + BH + 0.012, "Send command:", fontsize=8, va="bottom")
    ax_tb = fig.add_axes([PX, TY, PW, BH])
    textbox = TextBox(ax_tb, "", initial="!hx.scale:825.0")

    y = TY - BH - BG
    ax_send = fig.add_axes([PX, y, PW, BH])
    btn_send = Button(ax_send, "Send", color="0.85", hovercolor="0.70")

    # ── calibration section ───────────────────────────────────────────────────
    def section(label, ypos):
        fig.text(PX, ypos, label, fontsize=7.5, fontweight="bold", color="0.3")

    def btn(label, ypos, w_frac=1.0, x_off=0.0, color="0.88"):
        ax_b = fig.add_axes([PX + x_off*PW, ypos, PW*w_frac - 0.004, BH*0.9])
        b = Button(ax_b, label, color=color, hovercolor="0.72")
        b.label.set_fontsize(7.5)
        return b

    y -= BH + BG * 3
    section("── cell 1 (hx) ──", y + BH * 0.3)
    y -= BH + BG

    b1_zero  = btn("1. zero  (remove weight)", y);          y -= BH + BG
    b1_cap   = btn("2. capture tare raw",       y);          y -= BH + BG
    ax_kw1   = fig.add_axes([PX, y, PW*0.55, BH])
    tb_kw1   = TextBox(ax_kw1, "", initial="500")
    fig.text(PX + PW*0.57, y + BH*0.3, f"known ({args.units})", fontsize=7)
    y -= BH + BG
    b1_cal   = btn("3. place weight + calc scale", y, color="0.80"); y -= BH + BG
    b1_verify= btn("4. verify / show scale",       y);                y -= BH + BG * 3

    section("── cell 2 (hx2) ──", y + BH * 0.3)
    y -= BH + BG

    b2_zero  = btn("1. zero  (remove weight)", y);          y -= BH + BG
    b2_cap   = btn("2. capture tare raw",       y);          y -= BH + BG
    ax_kw2   = fig.add_axes([PX, y, PW*0.55, BH])
    tb_kw2   = TextBox(ax_kw2, "", initial="500")
    fig.text(PX + PW*0.57, y + BH*0.3, f"known ({args.units})", fontsize=7)
    y -= BH + BG
    b2_cal   = btn("3. place weight + calc scale", y, color="0.80"); y -= BH + BG
    b2_verify= btn("4. verify / show scale",       y);                y -= BH + BG * 3

    section("── both cells ──", y + BH * 0.3)
    y -= BH + BG
    b_rate_lo = btn("rate 2 Hz",  y, 0.48)
    b_rate_hi = btn("rate 10 Hz", y, 0.48, 0.52)
    y -= BH + BG
    b_avg4    = btn("avg 4",  y, 0.48)
    b_avg16   = btn("avg 16", y, 0.48, 0.52)

    # log
    LOG_H = 0.08
    ax_log = fig.add_axes([PX, 0.02, PW, LOG_H])
    ax_log.axis("off")
    log_lines = [""] * 4
    log_text = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")

    def log(msg):
        print(msg)
        log_lines.pop(0)
        log_lines.append(msg[:46])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    def send(cmd):
        write_cmd(ser, cmd)
        log(f">>> {cmd}")

    # ── callbacks ─────────────────────────────────────────────────────────────

    def do_send(text):
        if text.strip(): send(text.strip())
    textbox.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(textbox.text))

    # Cell 1
    def cb_1_zero(e):
        send("!hx.zero:1")
        tare_raw[0] = raw1_last
        log(f"  tare captured: {tare_raw[0]}")
    def cb_1_cap(e):
        tare_raw[0] = raw1_last
        log(f"  tare raw = {tare_raw[0]}")
    def cb_1_cal(e):
        try:
            kw = float(tb_kw1.text.strip())
        except ValueError:
            log("  ! enter a valid known weight"); return
        cal_raw[0] = raw1_last
        delta = cal_raw[0] - tare_raw[0]
        if abs(delta) < 100:
            log("  ! reading too close to tare — add weight first"); return
        scale = delta / kw
        send(f"!hx.scale:{scale:.4f}")
        log(f"  scale = {delta}/{kw:.1f} = {scale:.4f}")
        cal_done[0] = True
    def cb_1_verify(e):
        send("?hx.scale")
        log(f"  raw={raw1_last}  val={val1_last:.3f} {args.units}")

    b1_zero.on_clicked(cb_1_zero)
    b1_cap.on_clicked(cb_1_cap)
    b1_cal.on_clicked(cb_1_cal)
    b1_verify.on_clicked(cb_1_verify)

    # Cell 2
    def cb_2_zero(e):
        send("!hx2.zero:1")
        tare_raw[1] = raw2_last
        log(f"  tare captured: {tare_raw[1]}")
    def cb_2_cap(e):
        tare_raw[1] = raw2_last
        log(f"  tare raw = {tare_raw[1]}")
    def cb_2_cal(e):
        try:
            kw = float(tb_kw2.text.strip())
        except ValueError:
            log("  ! enter a valid known weight"); return
        cal_raw[1] = raw2_last
        delta = cal_raw[1] - tare_raw[1]
        if abs(delta) < 100:
            log("  ! reading too close to tare — add weight first"); return
        scale = delta / kw
        send(f"!hx2.scale:{scale:.4f}")
        log(f"  scale = {delta}/{kw:.1f} = {scale:.4f}")
        cal_done[1] = True
    def cb_2_verify(e):
        send("?hx2.scale")
        log(f"  raw={raw2_last}  val={val2_last:.3f} {args.units}")

    b2_zero.on_clicked(cb_2_zero)
    b2_cap.on_clicked(cb_2_cap)
    b2_cal.on_clicked(cb_2_cal)
    b2_verify.on_clicked(cb_2_verify)

    # Both
    b_rate_lo.on_clicked(lambda e: send("!rate:2"))
    b_rate_hi.on_clicked(lambda e: send("!rate:10"))
    b_avg4.on_clicked(lambda e:  [send("!hx.avg:4"),  send("!hx2.avg:4")])
    b_avg16.on_clicked(lambda e: [send("!hx.avg:16"), send("!hx2.avg:16")])

    plt.show(block=False)
    plt.pause(0.05)

    # ── receive loop ──────────────────────────────────────────────────────────
    rxbuf     = b""
    last_draw = time.time()
    new_data  = False

    # track which stream last line came from via context
    # UniProto CSV doesn't prepend stream id — we rely on the fact that
    # stream 1 and 2 both emit the same format; we distinguish by watching
    # the raw value jump patterns. A simpler approach: enable streams one
    # at a time and log separately. But with two identical-format streams
    # interleaved we need a counter trick:
    # stream 1 and 2 alternate if both enabled at same rate.
    # We tag by enabling timestamps and parsing, OR by toggling streams.
    # Simplest robust approach: enable only one stream at a time via the panel,
    # OR add a stream-id prefix by using !format:txt temporarily.
    # For now: the two streams alternate, track by line parity.
    line_counter = 0

    try:
        while plt.fignum_exists(fig.number):
            waiting = ser.in_waiting
            if waiting:
                rxbuf += ser.read(waiting)

            while b"\n" in rxbuf:
                line_b, rxbuf = rxbuf.split(b"\n", 1)
                line = line_b.decode("utf-8", errors="ignore").strip()
                if not line or line.startswith(("{", "OK", "ERR", "rate",
                                                "format", "stream", "hx")):
                    continue
                parsed = parse_stream(line)
                if parsed is None:
                    continue

                raw, val = parsed
                line_counter += 1
                # streams alternate 1,2,1,2... when both enabled at same rate
                if line_counter % 2 == 1:
                    raw1_last = raw; val1_last = val
                    val1_buf.append(val)
                else:
                    raw2_last = raw; val2_last = val
                    val2_buf.append(val)
                new_data = True

            now = time.time()
            if new_data and (now - last_draw) >= 0.05:
                last_draw = now; new_data = False
                t_ax = list(range(-N, 0))
                v1l.set_data(t_ax, list(val1_buf))
                v2l.set_data(t_ax, list(val2_buf))
                ax_val.relim(); ax_val.autoscale_view()
                status.set_text(
                    f"cell1: raw={raw1_last:+9d}  val={val1_last:8.3f} {args.units}    "
                    f"cell2: raw={raw2_last:+9d}  val={val2_last:8.3f} {args.units}"
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