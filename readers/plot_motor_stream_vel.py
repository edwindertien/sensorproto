#!/usr/bin/env python3
import argparse
import time
from collections import deque

import serial
import matplotlib.pyplot as plt


def send_cmd(ser, cmd):
    if not cmd.endswith("\n"):
        cmd += "\n"
    print(f"[TX] {cmd.strip()}")
    ser.write(cmd.encode("utf-8"))
    ser.flush()
    time.sleep(0.05)


def raw_preview(ser, seconds=1.0):
    t_end = time.time() + seconds
    got = False
    while time.time() < t_end:
        line = ser.readline()
        if line:
            got = True
            print("[RX]", line.decode("utf-8", errors="ignore").rstrip())
    if not got:
        print("[WARN] No RX during preview")


def configure(ser, rate_hz, pwm_lim):
    send_cmd(ser, "?")
    raw_preview(ser, 0.8)

    send_cmd(ser, "!format:csv")
    send_cmd(ser, "!timestamp:0")
    send_cmd(ser, "!rate:50")
    send_cmd(ser, "!stream:3")

    send_cmd(ser, "!motor0.kp:3.0")
    send_cmd(ser, "!motor1.kp:3.0")

    send_cmd(ser, "!motor.link:3")


    raw_preview(ser, 0.8)


def parse_stream3_csv(line: str):
    parts = [p.strip() for p in line.split(",") if p.strip() != ""]
    if len(parts) != 8:
        return None
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None
    return vals  # pos0,pos1,set0,set1,cmd0,cmd1,err0,err1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--rate", type=int, default=50)
    ap.add_argument("--pwm-lim", type=int, default=80)
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--vel-alpha", type=float, default=0.25,
                    help="EWMA smoothing for velocity (0..1). Higher = less smoothing.")
    args = ap.parse_args()

    print(f"[INFO] Opening {args.port} @ {args.baud} ...")
    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    time.sleep(2.0)
    ser.reset_input_buffer()
    print("[OK] Port open")

    configure(ser, args.rate, args.pwm_lim)

    maxlen = max(50, args.rate * args.seconds)
    t0 = time.time()
    xs = deque(maxlen=maxlen)

    pos0s = deque(maxlen=maxlen); pos1s = deque(maxlen=maxlen)
    set0s = deque(maxlen=maxlen); set1s = deque(maxlen=maxlen)
    cmd0s = deque(maxlen=maxlen); cmd1s = deque(maxlen=maxlen)
    err0s = deque(maxlen=maxlen); err1s = deque(maxlen=maxlen)
    vel0s = deque(maxlen=maxlen); vel1s = deque(maxlen=maxlen)

    # velocity state
    last_t = None
    last_pos0 = None
    last_pos1 = None
    v0 = 0.0
    v1 = 0.0
    alpha = max(0.0, min(1.0, args.vel_alpha))

    plt.ion()
    fig = plt.figure()
    ax1 = fig.add_subplot(4, 1, 1)
    ax2 = fig.add_subplot(4, 1, 2)
    ax3 = fig.add_subplot(4, 1, 3)
    ax4 = fig.add_subplot(4, 1, 4)

    (l_pos0,) = ax1.plot([], [], label="pos0")
    (l_set0,) = ax1.plot([], [], label="set0")
    (l_pos1,) = ax1.plot([], [], label="pos1")
    (l_set1,) = ax1.plot([], [], label="set1")
    ax1.set_ylabel("ticks"); ax1.grid(True); ax1.legend(loc="upper left")

    (l_cmd0,) = ax2.plot([], [], label="cmd0")
    (l_cmd1,) = ax2.plot([], [], label="cmd1")
    ax2.set_ylabel("PWM"); ax2.grid(True); ax2.legend(loc="upper left")

    (l_err0,) = ax3.plot([], [], label="err0")
    (l_err1,) = ax3.plot([], [], label="err1")
    ax3.set_ylabel("ticks"); ax3.grid(True); ax3.legend(loc="upper left")

    (l_vel0,) = ax4.plot([], [], label="vel0")
    (l_vel1,) = ax4.plot([], [], label="vel1")
    ax4.set_ylabel("ticks/s"); ax4.set_xlabel("time (s)")
    ax4.grid(True); ax4.legend(loc="upper left")

    last_draw = 0.0

    try:
        while True:
            raw = ser.readline()
            if not raw:
                plt.pause(0.001)
                continue

            s = raw.decode("utf-8", errors="ignore").strip()
            if not s:
                continue

            parsed = parse_stream3_csv(s)
            if parsed is None:
                continue

            pos0, pos1, set0, set1, cmd0, cmd1, err0, err1 = parsed
            now = time.time()
            x = now - t0

            # velocity estimate
            if last_t is not None and last_pos0 is not None:
                dt = now - last_t
                if dt > 1e-4:
                    inst0 = (pos0 - last_pos0) / dt
                    inst1 = (pos1 - last_pos1) / dt
                    # EWMA smooth
                    v0 = (1.0 - alpha) * v0 + alpha * inst0
                    v1 = (1.0 - alpha) * v1 + alpha * inst1
            last_t = now
            last_pos0 = pos0
            last_pos1 = pos1

            xs.append(x)
            pos0s.append(pos0); pos1s.append(pos1)
            set0s.append(set0); set1s.append(set1)
            cmd0s.append(cmd0); cmd1s.append(cmd1)
            err0s.append(err0); err1s.append(err1)
            vel0s.append(v0); vel1s.append(v1)

            if now - last_draw > 0.05 and len(xs) > 2:
                last_draw = now
                xlist = list(xs)

                l_pos0.set_data(xlist, list(pos0s))
                l_set0.set_data(xlist, list(set0s))
                l_pos1.set_data(xlist, list(pos1s))
                l_set1.set_data(xlist, list(set1s))

                l_cmd0.set_data(xlist, list(cmd0s))
                l_cmd1.set_data(xlist, list(cmd1s))

                l_err0.set_data(xlist, list(err0s))
                l_err1.set_data(xlist, list(err1s))

                l_vel0.set_data(xlist, list(vel0s))
                l_vel1.set_data(xlist, list(vel1s))

                for ax in (ax1, ax2, ax3, ax4):
                    ax.relim()
                    ax.autoscale_view()

                plt.pause(0.001)

    except KeyboardInterrupt:
        pass
    finally:
        try:
            send_cmd(ser, "action motor.stop")
        except Exception:
            pass
        ser.close()
        print("[INFO] Closed")


if __name__ == "__main__":
    main()
