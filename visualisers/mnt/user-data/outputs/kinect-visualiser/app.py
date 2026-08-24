"""
Live browser visualiser for the Kinect for Xbox 360 (RGB + depth).

    python app.py                 # real Kinect via libfreenect
    python app.py --simulate      # no hardware / no libfreenect build needed

Then open http://127.0.0.1:5002
"""
from __future__ import annotations

import argparse
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, render_template

from kinect_capture import KinectSource, SimulatedKinectSource

app = Flask(__name__)

_lock = threading.Lock()
_latest_rgb = None       # HxWx3 uint8, RGB order
_latest_depth_mm = None  # HxW uint16
_frame_times: list[float] = []


def _reader_thread(source) -> None:
    global _latest_rgb, _latest_depth_mm
    while True:
        rgb, depth_mm = source.get_frames()
        with _lock:
            _latest_rgb = rgb
            _latest_depth_mm = depth_mm
            _frame_times.append(time.time())
            del _frame_times[:-60]  # keep a rolling window for the fps readout


def _current_fps() -> float:
    with _lock:
        times = list(_frame_times)
    if len(times) < 2:
        return 0.0
    return (len(times) - 1) / (times[-1] - times[0])


def _depth_to_jpeg(depth_mm: np.ndarray) -> bytes:
    # Clamp to a working range and map to a perceptual colormap -- this is
    # measurement data, so the colour scale is chosen for readability, not
    # to match the rest of the page's palette.
    clamped = np.clip(depth_mm, 400, 4000).astype(np.float32)
    normalised = ((clamped - 400) / (4000 - 400) * 255).astype(np.uint8)
    normalised[depth_mm == 0] = 0  # no-return pixels rendered black
    colour = cv2.applyColorMap(255 - normalised, cv2.COLORMAP_TURBO)
    ok, buf = cv2.imencode(".jpg", colour, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else b""


def _rgb_to_jpeg(rgb: np.ndarray) -> bytes:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else b""


def _mjpeg_stream(encode_fn, get_frame_fn):
    while True:
        with _lock:
            frame = get_frame_fn()
        if frame is None:
            time.sleep(0.05)
            continue
        jpeg = encode_fn(frame)
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
        time.sleep(1 / 30)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/rgb_feed")
def rgb_feed():
    return Response(
        _mjpeg_stream(_rgb_to_jpeg, lambda: _latest_rgb),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/depth_feed")
def depth_feed():
    return Response(
        _mjpeg_stream(_depth_to_jpeg, lambda: _latest_depth_mm),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/stats")
def stats():
    with _lock:
        depth = _latest_depth_mm
    nearest = int(depth[depth > 0].min()) if depth is not None and (depth > 0).any() else None
    return {"fps": round(_current_fps(), 1), "nearest_mm": nearest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true", help="Run with synthetic RGB/depth frames")
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=5002)
    args = parser.parse_args()

    source = SimulatedKinectSource() if args.simulate else KinectSource(args.device_index)

    thread = threading.Thread(target=_reader_thread, args=(source,), daemon=True)
    thread.start()

    try:
        app.run(host=args.host, port=args.http_port, threaded=True)
    finally:
        source.close()


if __name__ == "__main__":
    main()
