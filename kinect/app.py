"""
Live browser visualiser for the Kinect for Xbox 360 (RGB + depth).

    python app.py                 # real Kinect via libfreenect
    python app.py --simulate      # no hardware / no libfreenect build needed

Then open http://127.0.0.1:5002
"""
from __future__ import annotations

import argparse
import io
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, render_template, request

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive, pure-rendering backend -- must
    # be set before any other matplotlib import, or it can try to
    # auto-select a GUI backend at import time, which can misbehave in a
    # threaded server context depending on the system.
    from matplotlib.figure import Figure
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 -- registers the 3d projection
    HAVE_MATPLOTLIB = True
except ImportError:
    HAVE_MATPLOTLIB = False

from kinect_capture import KinectSource, SimulatedKinectSource, VIDEO_MODE_IR, VIDEO_MODE_RGB

app = Flask(__name__)

_lock = threading.Lock()
_latest_video = None       # HxWx3 uint8 RGB, or HxW uint8 grayscale in IR mode
_latest_video_mode = VIDEO_MODE_RGB
_latest_depth_mm = None    # HxW uint16
_requested_video_mode = VIDEO_MODE_RGB
_frame_times: list[float] = []


def _reader_thread(source) -> None:
    global _latest_video, _latest_video_mode, _latest_depth_mm
    while True:
        with _lock:
            requested_mode = _requested_video_mode
        video_frame, depth_mm, actual_mode = source.get_frames(requested_mode)
        with _lock:
            _latest_video = video_frame
            _latest_video_mode = actual_mode
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


POINTCLOUD_STRIDE = 6  # coarse enough for matplotlib to render quickly; a
                        # static snapshot doesn't need every pixel like a
                        # live view might eventually want
FX = FY = 525.0         # approximate uncalibrated Kinect v1 intrinsics --
CX, CY = 320, 240       # see the earlier back-projection explanation


def _depth_to_pointcloud_png(depth_mm: np.ndarray, elev: float = 20, azim: float = -60) -> bytes:
    """Back-projects the current depth frame into 3D and renders it with
    matplotlib -- entirely server-side, no browser/WebGL involved. This
    exists specifically so the result can be sanity-checked by looking at
    an actual image, rather than trusting client-side rendering blind."""
    grid = depth_mm[::POINTCLOUD_STRIDE, ::POINTCLOUD_STRIDE]
    ys, xs = np.mgrid[0:grid.shape[0], 0:grid.shape[1]]
    u = xs * POINTCLOUD_STRIDE
    v = ys * POINTCLOUD_STRIDE
    d = grid.astype(np.float32)
    valid = d > 0

    meters = d / 1000.0
    x = (u - CX) * meters / FX
    y = -(v - CY) * meters / FY
    z = -meters
    x, y, z, d_valid = x[valid], y[valid], z[valid], d[valid]

    fig = Figure(figsize=(6.5, 5.5), dpi=110, facecolor="#14171c")
    ax = fig.add_subplot(111, projection="3d", facecolor="#14171c")
    if len(x):
        # Depth (z, "into the scene") plotted on the plot's own Y axis and
        # up (y) on the plot's Z axis -- this just orients the default
        # matplotlib 3D view sensibly for a scene viewed roughly head-on.
        ax.scatter(x, z, y, c=d_valid, cmap="turbo", s=3, depthshade=True)
    ax.set_xlabel("X (m)", color="#7d8496", fontsize=8)
    ax.set_ylabel("depth (m)", color="#7d8496", fontsize=8)
    ax.set_zlabel("Y (m, up)", color="#7d8496", fontsize=8)
    ax.tick_params(colors="#7d8496", labelsize=7)
    ax.view_init(elev=elev, azim=azim)
    ax.set_title(f"{len(x)} points", color="#e7e9ee", fontsize=10)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    return buf.getvalue()


@app.route("/pointcloud_snapshot.png")
def pointcloud_snapshot():
    if not HAVE_MATPLOTLIB:
        return (
            "matplotlib isn't installed in this environment -- "
            "run: pip install matplotlib (or pip install -r requirements.txt)",
            503,
        )
    with _lock:
        depth = _latest_depth_mm
    if depth is None:
        return "No depth data yet -- give the sensor a moment to start streaming.", 503
    elev = request.args.get("elev", 20, type=float)
    azim = request.args.get("azim", -60, type=float)
    png_bytes = _depth_to_pointcloud_png(depth, elev=elev, azim=azim)
    return Response(png_bytes, mimetype="image/png")


@app.route("/stats")
def stats():
    with _lock:
        depth = _latest_depth_mm
        mode = _latest_video_mode
    nearest = int(depth[depth > 0].min()) if depth is not None and (depth > 0).any() else None
    return {"fps": round(_current_fps(), 1), "nearest_mm": nearest, "video_mode": mode}


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