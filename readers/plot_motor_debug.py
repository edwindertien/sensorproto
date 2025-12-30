#!/usr/bin/env python3
import time
import serial
import argparse


def open_serial(port, baud):
    print(f"[INFO] Opening serial port {port} @ {baud} baud...")
    ser = serial.Serial(port, baudrate=baud, timeout=0.2)
    time.sleep(2.0)  # allow Arduino auto-reset
    ser.reset_input_buffer()
    print("[OK] Serial port opened")
    return ser


def send_cmd(ser, cmd):
    if not cmd.endswith("\n"):
        cmd += "\n"
    print(f"[TX] {cmd.strip()}")
    ser.write(cmd.encode("utf-8"))
    ser.flush()
    time.sleep(0.05)


def raw_read_preview(ser, seconds=2.0):
    print(f"[INFO] Raw read preview for {seconds:.1f}s...")
    t_end = time.time() + seconds
    got_any = False
    while time.time() < t_end:
        raw = ser.readline()
        if raw:
            got_any = True
            print("[RX]", raw.decode("utf-8", errors="ignore").rstrip())
    if not got_any:
        print("[WARN] No data received during preview")
    print("[INFO] End raw preview")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    ser = open_serial(args.port, args.baud)

    print("[INFO] Sending probe '?'")
    send_cmd(ser, "?")
    raw_read_preview(ser, 2.0)

    print("[INFO] Sending configuration commands")

    send_cmd(ser, "!format:csv")
    send_cmd(ser, "!timestamp:0")
    send_cmd(ser, "!rate:50")
    send_cmd(ser, "!stream:3")

    send_cmd(ser, "!motor0.kp:3.0")
    send_cmd(ser, "!motor1.kp:3.0")

    send_cmd(ser, "!motor.link:3")


    print("[INFO] Waiting for stream data (5s)...")
    raw_read_preview(ser, 5.0)

    print("[INFO] Done. Leaving port open for inspection.")
    print("Press Ctrl+C to exit.")

    try:
        while True:
            raw = ser.readline()
            if raw:
                print("[RX]", raw.decode("utf-8", errors="ignore").rstrip())
    except KeyboardInterrupt:
        pass
    finally:
        print("[INFO] Closing serial port")
        ser.close()


if __name__ == "__main__":
    main()
