"""
Live browser visualiser for the Hokuyo URG-04LX-UG01.

    python app.py --port /dev/tty.usbmodemXXXX      # real sensor
    python app.py --simulate                        # no hardware needed

Then open http://127.0.0.1:5001
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import random
import threading
import time
from typing import Iterator

from flask import Flask, Response, render_template

from hokuyo_driver import HokuyoURG, Scan, START_STEP, END_STEP, FRONT_STEP, STEP_ANGLE_DEG

app = Flask(__name__)

# Every connected browser tab gets its own queue; the reader thread below
# fans each new scan out to all of them.
_subscribers: list[queue.Queue] = []
_subscribers_lock = threading.Lock()


def _broadcast(scan: Scan) -> None:
    payload = json.dumps({
        "t": scan.timestamp,
        "angles": [round(a, 2) for a in scan.angles_deg],
        "distances": scan.distances_mm,
    })
    with _subscribers_lock:
        for q in _subscribers:
            # Drop instead of blocking a slow client -- lidar data is only
            # useful fresh, so a client that falls behind should just skip
            # ahead to the next scan.
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


def _simulated_scans() -> Iterator[Scan]:
    """Synthetic 'room' scan: four walls at varying distance plus noise,
    so the front end can be built and tested without the sensor attached."""
    t0 = time.time()
    while True:
        elapsed = time.time() - t0
        angles, distances = [], []
        step = START_STEP
        while step <= END_STEP:
            angle_deg = (step - FRONT_STEP) * STEP_ANGLE_DEG
            angle_rad = math.radians(angle_deg)
            # A roughly rectangular room ~2.5m away, slowly "breathing",
            # with a moving near obstacle sweeping across the field of view.
            base = 2500 + 400 * math.sin(2 * angle_rad + elapsed * 0.3)
            obstacle_center = 60 * math.sin(elapsed * 0.5)
            obstacle = 900 * math.exp(-((angle_deg - obstacle_center) ** 2) / (2 * 12 ** 2))
            dist = max(60, base - obstacle + random.uniform(-15, 15))
            angles.append(angle_deg)
            distances.append(int(dist))
            step += 1
        yield Scan(timestamp=time.time(), angles_deg=angles, distances_mm=distances)
        time.sleep(0.1)  # ~10 Hz, matching the real sensor's scan rate


def _reader_thread(port: str | None) -> None:
    if port is None:
        source = _simulated_scans()
    else:
        sensor = HokuyoURG(port)
        source = sensor.iter_scans()

    for scan in source:
        _broadcast(scan)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/stream")
def stream():
    client_queue: queue.Queue = queue.Queue(maxsize=2)
    with _subscribers_lock:
        _subscribers.append(client_queue)

    def gen():
        try:
            while True:
                payload = client_queue.get()
                yield f"data: {payload}\n\n"
        finally:
            with _subscribers_lock:
                _subscribers.remove(client_queue)

    return Response(gen(), mimetype="text/event-stream")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None, help="Serial device, e.g. /dev/tty.usbmodem1234")
    parser.add_argument("--simulate", action="store_true", help="Run with synthetic scan data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=5001)
    args = parser.parse_args()

    if not args.simulate and args.port is None:
        parser.error("pass --port /dev/tty.usbmodemXXXX or --simulate")

    thread = threading.Thread(target=_reader_thread, args=(None if args.simulate else args.port,), daemon=True)
    thread.start()

    app.run(host=args.host, port=args.http_port, threaded=True)


if __name__ == "__main__":
    main()
