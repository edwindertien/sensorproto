#!/usr/bin/env python3
"""
Synchro transformer — oscilloscope view + rotation angle readout.

Stream 1 (syn.angle): computed angle via cross-correlation
Stream 2 (syn.frame):  full 480-sample raw capture (binary, chunked)

Reproduces the original Processing oscilloscope (amplitude/offset/timescale
controls, dual cursor dt/Hz measurement) plus a live angle readout and
polar dial showing rotor position.

Usage:
  python plot_synchro.py --port /dev/tty.usbmodemXXXX
"""
import argparse
import math
import struct
import time
from collections import deque

import matplotlib
matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button, TextBox
import numpy as np
import serial

SYNC = b"\xAA\x55"
FRAME_SAMPLES = 480
SAMPLE_HZ = 5000.0   # capture rate, fixed by ISR

# ── serial ────────────────────────────────────────────────────────────────────

def write_cmd(ser, s):
    s = s.strip()
    if not s:
        return
    ser.write((s + "\n").encode("ascii", errors="ignore"))
    ser.flush()

def send_and_wait(ser, cmd, pause=0.15):
    write_cmd(ser, cmd)
    time.sleep(pause)
    while ser.in_waiting:
        ser.readline()

# ── binary packet parsing (same UniProto framing as ADNS reader) ─────────────

def try_parse_one(buf: bytearray):
    i = buf.find(SYNC)
    if i < 0:
        if len(buf) > 8192:
            del buf[:-2]
        return None, 0
    if i > 0:
        del buf[:i]
    if len(buf) < 6:
        return None, 0
    stream_id   = buf[2]
    flags       = buf[3]
    payload_len = struct.unpack_from("<H", buf, 4)[0]
    idx = 6
    ts = None
    if flags & 0x01:
        if len(buf) < idx + 4:
            return None, 0
        ts = struct.unpack_from("<I", buf, idx)[0]
        idx += 4
    if len(buf) < idx + payload_len:
        return None, 0
    payload  = bytes(buf[idx:idx+payload_len])
    consumed = idx + payload_len
    return {"sid": stream_id, "payload": payload}, consumed

def parse_frame_chunk(payload: bytes):
    if len(payload) < 6:
        return None
    fid, off, count = struct.unpack_from("<HHH", payload, 0)
    data = payload[6:]
    if len(data) != count:
        return None
    return fid, off, count, data

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    print(f"[INFO] Opening {args.port} @ {args.baud}")
    ser = serial.Serial(args.port, args.baud, timeout=0.0)
    ser.dtr = False; time.sleep(0.2)
    ser.reset_input_buffer(); ser.reset_output_buffer()
    ser.dtr = True;  time.sleep(2.0)
    ser.reset_input_buffer(); ser.reset_output_buffer()
    print("[INFO] Port open.")

    send_and_wait(ser, "!stream:0")     # silence first — avoid commands landing mid-flood
    send_and_wait(ser, "!timestamp:0")
    send_and_wait(ser, "!format:bin")
    send_and_wait(ser, "!stream:2")     # frame capture
    send_and_wait(ser, "!syn.capture:1")
    print("[INFO] Streaming frames.")

    # ── state ─────────────────────────────────────────────────────────────────
    frame = np.full(FRAME_SAMPLES, 127, dtype=np.uint8)
    got   = np.zeros(FRAME_SAMPLES, dtype=bool)
    cur_fid = None

    angle_buf = deque([0.0]*100, maxlen=100)
    angle_deg = [0.0]

    view = {
        "amplitude": 1.0,
        "timescale": 1.0,
        "offset_px": 0,
    }
    cursors = [None, None]   # ms positions

    # ── figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 7))
    fig.suptitle("Synchro transformer — oscilloscope + angle", fontsize=11)

    gs = gridspec.GridSpec(2, 2, figure=fig,
                           width_ratios=[2.6, 1.0],
                           height_ratios=[1.4, 1.0],
                           hspace=0.4, wspace=0.32)

    ax_scope = fig.add_subplot(gs[0, 0])
    ax_angle = fig.add_subplot(gs[1, 0])
    ax_dial  = fig.add_subplot(gs[0, 1], projection="polar")
    ax_pan   = fig.add_subplot(gs[1, 1])
    ax_pan.set_visible(False)

    t_samples = np.arange(FRAME_SAMPLES) / SAMPLE_HZ * 1000.0  # ms
    scope_line, = ax_scope.plot(t_samples, frame.astype(float), color="mediumseagreen", lw=0.8)
    ax_scope.set_xlabel("time (ms)")
    ax_scope.set_ylabel("ADC (8-bit)")
    ax_scope.set_ylim(-10, 265)
    ax_scope.grid(True, alpha=0.3)
    cursor1_line = ax_scope.axvline(-100, color="blue", lw=0.8, visible=False)
    cursor2_line = ax_scope.axvline(-100, color="blue", lw=0.8, visible=False)
    cursor_text  = ax_scope.text(0.02, 0.95, "", transform=ax_scope.transAxes,
                                 fontsize=8, color="blue", va="top")

    t_ax = list(range(-100, 0))
    angle_line, = ax_angle.plot(t_ax, list(angle_buf), color="tomato", lw=1.0)
    ax_angle.set_ylim(0, 360)
    ax_angle.set_ylabel("angle (deg)")
    ax_angle.set_xlabel("samples")
    ax_angle.grid(True, alpha=0.3)

    ax_dial.set_theta_zero_location("N")
    ax_dial.set_theta_direction(-1)
    ax_dial.set_ylim(0, 1)
    ax_dial.set_yticks([])
    needle, = ax_dial.plot([0, 0], [0, 1], color="tomato", lw=2.5)
    ax_dial.set_title("rotor angle", fontsize=9)

    status = fig.text(0.01, 0.01,
        "angle=--°   amp=1.0  time=1.0  offset=0px",
        fontsize=8, family="monospace", color="0.35")

    plt.tight_layout(rect=[0, 0.04, 1, 0.95])

    # ── panel ─────────────────────────────────────────────────────────────────
    # Dial occupies roughly fig-y 0.55–0.95 (top-right quadrant).
    # Panel starts below it, in the bottom-right quadrant.
    PX, PW, BH, BG = 0.755, 0.22, 0.038, 0.006

    def label(text, y):
        fig.text(PX, y, text, fontsize=7, fontweight="bold", color="0.35")

    def mkbtn(text, y, w=1.0, xoff=0.0, color="0.88"):
        ax_b = fig.add_axes([PX + xoff*PW, y, PW*w - 0.004, BH*0.85])
        b = Button(ax_b, text, color=color, hovercolor="0.72")
        b.label.set_fontsize(6.8)
        return b

    # Denser layout: send box on its own row, everything else in
    # tight 2-column rows to fit below the dial without overflowing.
    y = 0.40   # start below the dial, clear of its lower edge

    ax_tb   = fig.add_axes([PX, y, PW, BH*0.9])
    textbox = TextBox(ax_tb, "", initial="!syn.offset:0.0")
    y -= BH + BG*0.5

    btn_send    = mkbtn("Send",            y, w=0.48, color="0.82")
    btn_capture = mkbtn("new capture",     y, w=0.48, xoff=0.52, color="0.80")
    y -= BH + BG*0.5

    btn_zero    = mkbtn("zero angle",      y, w=0.48)
    btn_reset   = mkbtn("reset view",      y, w=0.48, xoff=0.52)
    y -= BH + BG*0.5

    btn_amp_p = mkbtn("amp +",    y, w=0.48)
    btn_amp_m = mkbtn("amp -",    y, w=0.48, xoff=0.52)
    y -= BH + BG*0.5

    btn_t_p = mkbtn("time +",     y, w=0.48)
    btn_t_m = mkbtn("time -",     y, w=0.48, xoff=0.52)
    y -= BH + BG*0.5

    btn_o_p = mkbtn("offset +",   y, w=0.48)
    btn_o_m = mkbtn("offset -",   y, w=0.48, xoff=0.52)
    y -= BH + BG*0.5

    btn_clear_cursors = mkbtn("clear cursors", y)
    y -= BH + BG

    ax_log = fig.add_axes([PX, 0.02, PW, 0.06])
    ax_log.axis("off")
    log_lines = [""] * 3
    log_text = ax_log.text(0, 1, "", fontsize=6.5, va="top", family="monospace")

    def log(msg):
        log_lines.pop(0)
        log_lines.append(msg[:36])
        log_text.set_text("\n".join(log_lines))
        fig.canvas.draw_idle()

    # ── callbacks ─────────────────────────────────────────────────────────────
    def do_send(text):
        cmd = text.strip()
        if cmd:
            write_cmd(ser, cmd)
            log(f">>> {cmd}")
    textbox.on_submit(do_send)
    btn_send.on_clicked(lambda e: do_send(textbox.text))

    btn_capture.on_clicked(lambda e: (write_cmd(ser, "!syn.capture:1"), log("  capture requested")))
    btn_zero.on_clicked(lambda e: (write_cmd(ser, f"!syn.offset:{angle_deg[0]:.2f}"),
                                   log(f"  zeroed at {angle_deg[0]:.1f}°")))

    def adj_amp(d):
        view["amplitude"] = max(0.1, view["amplitude"] + d)
    def adj_time(d):
        view["timescale"] = max(0.1, view["timescale"] + d)
    def adj_off(d):
        view["offset_px"] += d

    btn_amp_p.on_clicked(lambda e: adj_amp(+0.1))
    btn_amp_m.on_clicked(lambda e: adj_amp(-0.1))
    btn_t_p.on_clicked(lambda e: adj_time(+0.1))
    btn_t_m.on_clicked(lambda e: adj_time(-0.1))
    btn_o_p.on_clicked(lambda e: adj_off(+5))
    btn_o_m.on_clicked(lambda e: adj_off(-5))

    def cb_reset(e):
        view["amplitude"] = 1.0
        view["timescale"] = 1.0
        view["offset_px"] = 0
    btn_reset.on_clicked(cb_reset)

    def cb_clear_cursors(e):
        cursors[0] = None
        cursors[1] = None
        cursor1_line.set_visible(False)
        cursor2_line.set_visible(False)
        cursor_text.set_text("")
    btn_clear_cursors.on_clicked(cb_clear_cursors)

    def on_scope_click(event):
        if event.inaxes != ax_scope or event.xdata is None:
            return
        t_ms = event.xdata
        if event.button == 1:
            cursors[0] = t_ms
        elif event.button == 3:
            cursors[1] = t_ms
    fig.canvas.mpl_connect("button_press_event", on_scope_click)

    plt.show(block=False)
    plt.pause(0.05)

    # ── receive loop ──────────────────────────────────────────────────────────
    rxbuf     = bytearray()
    last_draw = time.time()
    new_frame = False
    new_angle = False
    angle_calc_t = time.time()

    try:
        while plt.fignum_exists(fig.number):
            waiting = ser.in_waiting
            if waiting:
                rxbuf.extend(ser.read(waiting))

            pkt, consumed = try_parse_one(rxbuf)
            while pkt is not None:
                del rxbuf[:consumed]
                if pkt["sid"] == 2:
                    parsed = parse_frame_chunk(pkt["payload"])
                    if parsed:
                        fid, off, count, data = parsed
                        if cur_fid != fid:
                            cur_fid = fid
                            got[:] = False
                        if off + count <= FRAME_SAMPLES:
                            frame[off:off+count] = np.frombuffer(data, dtype=np.uint8)
                            got[off:off+count] = True
                        if got.all():
                            new_frame = True
                            write_cmd(ser, "!syn.capture:1")  # request next frame
                pkt, consumed = try_parse_one(rxbuf)

            now = time.time()
            # Compute angle locally from the captured frame via cross-correlation
            # against a reference sine — same method as mod_synchro on-device,
            # done here so we don't need to switch serial formats mid-stream.
            if now - angle_calc_t > 0.2 and got.all():
                ref = 127.0 * np.sin(2*np.pi*np.arange(48)/48)
                seg = frame[-48:].astype(float) - 127.0
                best_corr = -1e18
                best_shift = 0
                for shift in range(48):
                    corr = np.dot(seg, np.roll(ref, shift))
                    if corr > best_corr:
                        best_corr = corr
                        best_shift = shift
                angle_deg[0] = (360.0 * best_shift / 48.0) % 360.0
                angle_buf.append(angle_deg[0])
                new_angle = True
                angle_calc_t = now

            if (new_frame or new_angle) and (now - last_draw) >= 0.05:
                last_draw = now
                new_frame = False
                new_angle = False

                amp = view["amplitude"]
                ts  = view["timescale"]
                off = view["offset_px"]
                y_vals = (frame.astype(float) - 127.0) * amp + 127.0 + off
                x_vals = t_samples / ts
                scope_line.set_data(x_vals, y_vals)
                ax_scope.set_xlim(0, t_samples[-1] / ts)

                if cursors[0] is not None:
                    cursor1_line.set_xdata([cursors[0], cursors[0]])
                    cursor1_line.set_visible(True)
                if cursors[1] is not None:
                    cursor2_line.set_xdata([cursors[1], cursors[1]])
                    cursor2_line.set_visible(True)
                if cursors[0] is not None and cursors[1] is not None:
                    dt = abs(cursors[1] - cursors[0])
                    hz = 1000.0 / dt if dt > 0 else 0.0
                    cursor_text.set_text(f"dt={dt:.2f}ms  f={hz:.1f}Hz")
                elif cursors[0] is not None:
                    cursor_text.set_text(f"t1={cursors[0]:.2f}ms")
                elif cursors[1] is not None:
                    cursor_text.set_text(f"t2={cursors[1]:.2f}ms")

                t_ax = list(range(-100, 0))
                angle_line.set_data(t_ax, list(angle_buf))

                theta = math.radians(angle_deg[0])
                needle.set_data([theta, theta], [0, 1])

                status.set_text(
                    f"angle={angle_deg[0]:6.1f}°   "
                    f"amp={view['amplitude']:.1f}  "
                    f"time={view['timescale']:.1f}  "
                    f"offset={view['offset_px']}px"
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