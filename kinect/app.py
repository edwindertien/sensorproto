"""
Live browser visualiser for the Kinect for Xbox 360 (RGB + depth).

    python app.py                 # real Kinect via libfreenect
    python app.py --simulate      # no hardware / no libfreenect build needed

Then open http://127.0.0.1:5002

For a 3D point cloud snapshot, use render_pointcloud.py as a SEPARATE
process rather than a route in this app -- see the "Point cloud" section
of the README. Rendering an 8000+ point matplotlib 3D scatter is CPU-heavy
enough, in pure-Python-held-GIL time, that doing it inside this same
process was found to disrupt the reader thread's ability to keep servicing
the Kinect's USB stream promptly -- not a crash, just enough contention to
break the underlying hardware communication under sustained load. Keeping
this process doing only cheap, fast work (JPEG encoding, raw array dumps)
and pushing anything CPU-heavy into a fully separate process with its own
GIL avoids that class of problem entirely, rather than trying to tune
around it.
"""
from __future__ import annotations

import argparse
import os
import signal
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, render_template, request

from kinect_capture import KinectSource, SimulatedKinectSource, VIDEO_MODE_IR, VIDEO_MODE_RGB

app = Flask(__name__)

_lock = threading.Lock()
_latest_video = None       # HxWx3 uint8 RGB, or HxW uint8 grayscale in IR mode
_latest_video_mode = VIDEO_MODE_RGB
_latest_depth_mm = None    # HxW uint16
_requested_video_mode = VIDEO_MODE_RGB
_frame_times: list[float] = []
_frames_received = 0
_last_frame_time: float | None = None
_last_error: str | None = None


def _reader_thread(source) -> None:
    global _latest_video, _latest_video_mode, _latest_depth_mm
    global _frames_received, _last_frame_time, _last_error
    last_heartbeat = time.time()
    while True:
        with _lock:
            requested_mode = _requested_video_mode
        try:
            video_frame, depth_mm, actual_mode = source.get_frames(requested_mode)
        except Exception as exc:
            with _lock:
                _last_error = str(exc)
            print(f"[kinect] Frame read failed: {exc}")
            time.sleep(1)  # avoid hammering a failing device in a tight loop
            continue
        with _lock:
            _latest_video = video_frame
            _latest_video_mode = actual_mode
            _latest_depth_mm = depth_mm
            _frame_times.append(time.time())
            del _frame_times[:-60]  # keep a rolling window for the fps readout
            _frames_received += 1
            _last_frame_time = time.time()
            _last_error = None

        if _frames_received == 1:
            print("[kinect] First frame received successfully -- streaming.")

        now = time.time()
        if now - last_heartbeat > 10:
            print(f"[kinect] Heartbeat: {_frames_received} frames received so far, "
                  f"current rate {_current_fps():.1f}fps, mode={_latest_video_mode}")
            last_heartbeat = now
        time.sleep(1 / 30)


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
    colour = cv2.applyColorMap(255 - normalised, cv2.COLORMAP_TURBO)
    # No-return pixels (IR shadow behind an edge, out of range, reflective
    # surfaces) blacked out AFTER the colormap, not before -- forcing the
    # pre-colormap value to 0 made these indistinguishable from real
    # close-range objects, since a real surface at the minimum clamp
    # distance maps to that same index.
    colour[depth_mm == 0] = (0, 0, 0)
    ok, buf = cv2.imencode(".jpg", colour, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else b""


def _video_to_jpeg(payload) -> bytes:
    video_frame, mode = payload
    if mode == VIDEO_MODE_IR:
        # Raw grayscale, deliberately not embellished with a colormap --
        # the point of this view is to see the sensor's actual output.
        ok, buf = cv2.imencode(".jpg", video_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    else:
        bgr = cv2.cvtColor(video_frame, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else b""


def _get_latest_video():
    with _lock:
        if _latest_video is None:
            return None
        return (_latest_video, _latest_video_mode)


def _get_latest_depth():
    with _lock:
        return _latest_depth_mm


def _mjpeg_stream(encode_fn, get_frame_fn):
    # get_frame_fn owns its own locking (see _get_latest_video /
    # _get_latest_depth) -- do not also lock here, or a get_frame_fn that
    # locks internally deadlocks against a non-reentrant Lock.
    while True:
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


@app.route("/video_feed")
def video_feed():
    return Response(
        _mjpeg_stream(_video_to_jpeg, _get_latest_video),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/set_video_mode")
def set_video_mode():
    global _requested_video_mode
    mode = request.args.get("mode", VIDEO_MODE_RGB)
    if mode not in (VIDEO_MODE_RGB, VIDEO_MODE_IR):
        return {"error": f"unknown mode {mode!r}"}, 400
    with _lock:
        _requested_video_mode = mode
    return {"mode": mode}


@app.route("/depth_feed")
def depth_feed():
    return Response(
        _mjpeg_stream(_depth_to_jpeg, _get_latest_depth),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/depth_snapshot.npy")
def depth_snapshot():
    """Dumps the current raw depth frame (uint16, millimetres) as a .npy
    file. Deliberately cheap: no matplotlib, no CPU-heavy work, nothing
    that could compete with the reader thread for GIL time. Feed the
    downloaded file to render_pointcloud.py, run as its own separate
    process, to actually generate a 3D point cloud image."""
    with _lock:
        depth = _latest_depth_mm
    if depth is None:
        return "No depth data yet -- give the sensor a moment to start streaming.", 503
    import io
    buf = io.BytesIO()
    np.save(buf, depth)
    buf.seek(0)
    return Response(
        buf.getvalue(),
        mimetype="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=depth_snapshot.npy"},
    )


@app.route("/stats")
def stats():
    with _lock:
        depth = _latest_depth_mm
        mode = _latest_video_mode
        frames_received = _frames_received
        last_frame_time = _last_frame_time
        last_error = _last_error
    nearest = int(depth[depth > 0].min()) if depth is not None and (depth > 0).any() else None
    last_frame_age = round(time.time() - last_frame_time, 1) if last_frame_time else None
    return {
        "fps": round(_current_fps(), 1),
        "nearest_mm": nearest,
        "video_mode": mode,
        "frames_received": frames_received,
        "last_frame_age_s": last_frame_age,
        "last_error": last_error,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true", help="Run with synthetic RGB/depth frames")
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=5002)
    args = parser.parse_args()

    source_holder: dict = {}

    def handle_sigint(signum, frame):
        # Ctrl+C. Registered BEFORE the source is created deliberately --
        # KinectSource's connection attempt is the one place most likely
        # to hang (a stuck libusb call), and if the handler weren't
        # already active by then, Ctrl+C would do nothing during exactly
        # the moment it's most needed. Werkzeug's threaded dev server also
        # spins up a thread per connection that never naturally finishes
        # on its own, which can hang Python's normal shutdown sequence
        # once streaming has started -- and a hung shutdown here doesn't
        # just fail to exit cleanly, it can leave the process still
        # holding the Kinect's USB device open, making the *next*
        # `python app.py` hang at "Connecting..." since the device is
        # already claimed. os._exit() sidesteps all of that: best-effort
        # sensor cleanup first, but it must not be allowed to block the
        # exit either.
        print("\nShutting down...")
        source = source_holder.get("source")
        if source is not None:
            try:
                source.close()
            except Exception as exc:
                print(f"Error closing sensor during shutdown (harmless if it was already disconnected): {exc}")
        os._exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    source = SimulatedKinectSource() if args.simulate else KinectSource(args.device_index)
    source_holder["source"] = source

    thread = threading.Thread(target=_reader_thread, args=(source,), daemon=True)
    thread.start()

    app.run(host=args.host, port=args.http_port, threaded=True)


if __name__ == "__main__":
    main()