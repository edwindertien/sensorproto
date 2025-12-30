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


def raw_preview(ser, seconds=1.5):
    print(f"[INFO] Raw preview {seconds:.1f}s...")
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
    raw_preview(ser, 1.0)

    send_cmd(ser, "!format:csv")
    send_cmd(ser, "!timestamp:0")
    send_cmd(ser, "!rate:50")
    send_cmd(ser, "!stream:3")

    send_cmd(ser, "!motor0.kp:3.0")
    send_cmd(ser, "!motor1.kp:3.0")

    send_cmd(ser, "!motor.link:3")


    raw_preview(ser, 1.0)


def parse_stream3_csv(line: str):
    # Accept:
    # 8 cols: pos0,pos1,set0,set1,cmd0,cmd1,err0,err1
    # (optional timestamp column would make 9, but we set timestamp=0)
    parts = [p.strip() for p in line.split(",") if p.strip() != ""]
    if len(parts) != 8:
        return None
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None
    pos0, pos1, set0, set1, cmd0, cmd1, err0, err1 = vals
    return pos0, pos1, set0, set1, cmd0, cmd1, err0, err1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--rate", type=int, default=100)
    ap.add_argument("--pwm-lim", type=int, default=200)
    ap.add_argument("--seconds", type=int, default=10)
    args = ap.parse_args()

    print(f"[INFO] Opening {args.port} @ {args.baud} ...")
    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    time.sleep(2.0)  # Uno reset
    ser.reset_input_buffer()
    print("[OK] Port open")

    configure(ser, args.rate, args.pwm_lim)

    # buffers
    maxlen = max(50, args.rate * args.seconds)
    t0 = time.time()
    xs = deque(maxlen=maxlen)
    pos0s = deque(maxlen=maxlen); pos1s = deque(maxlen=maxlen)
    set0s = deque(maxlen=maxlen); set1s = deque(maxlen=maxlen)
    cmd0s = deque(maxlen=maxlen); cmd1s = deque(maxlen=maxlen)
    err0s = deque(maxlen=maxlen); err1s = deque(maxlen=maxlen)

    # plot
    plt.ion()
    fig = plt.figure()
    ax1 = fig.add_subplot(3, 1, 1)
    ax2 = fig.add_subplot(3, 1, 2)
    ax3 = fig.add_subplot(3, 1, 3)

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
    ax3.set_ylabel("ticks"); ax3.set_xlabel("time (s)")
    ax3.grid(True); ax3.legend(loc="upper left")

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
                # Uncomment if you want to see non-CSV lines:
                # print("[RX?]", s)
                continue

            pos0, pos1, set0, set1, cmd0, cmd1, err0, err1 = parsed
            x = time.time() - t0

            xs.append(x)
            pos0s.append(pos0); pos1s.append(pos1)
            set0s.append(set0); set1s.append(set1)
            cmd0s.append(cmd0); cmd1s.append(cmd1)
            err0s.append(err0); err1s.append(err1)

            now = time.time()
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

                for ax in (ax1, ax2, ax3):
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
