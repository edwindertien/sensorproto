"""
kinect_capture.py

Wraps libfreenect's `freenect` Python module to grab RGB + depth frames
from a Kinect for Xbox 360 (Kinect v1, model 1414). Falls back to
synthetic frames when `freenect` isn't importable, so the dashboard can
be built and tested before libfreenect is built from source.

libfreenect's Homebrew bottle does NOT ship Python bindings (a past PR to
add them was rejected upstream over a linking issue), so `freenect` has
to be built manually on macOS:

    brew install libusb cmake pkg-config
    git clone https://github.com/OpenKinect/libfreenect
    cd libfreenect && mkdir build && cd build
    cmake .. -DBUILD_PYTHON3=ON
    make
    sudo make install

See this project's README for the full walkthrough and troubleshooting.
"""
from __future__ import annotations

import math
import time

import numpy as np

try:
    import freenect
    HAVE_FREENECT = True
except ImportError:
    HAVE_FREENECT = False


class KinectError(RuntimeError):
    pass


VIDEO_MODE_RGB = "rgb"
VIDEO_MODE_IR = "ir"


def raw_depth_to_mm(raw: np.ndarray) -> np.ndarray:
    """Kinect v1 raw 11-bit IR disparity -> millimetres.

    This is the standard community-derived conversion used throughout the
    OpenKinect ecosystem (e.g. the Stanford graphics course notes on the
    Kinect, widely mirrored). Values at/near the 2047 'no return' sentinel,
    or that resolve to nonsensical distances, are zeroed out.
    """
    raw = raw.astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        meters = 1.0 / (raw * -0.0030711016 + 3.3309495161)
    meters = np.where((raw >= 2047) | (meters <= 0) | (meters > 8), 0, meters)
    return (meters * 1000).astype(np.uint16)


class KinectSource:
    """Real Kinect v1 via libfreenect.

    The colour camera and the raw IR camera are the same physical video
    channel on this hardware -- the device is in RGB mode or IR mode, not
    both at once, so get_frames() takes the currently-requested mode and
    switches the video stream to match. Depth is a separate channel and
    is always fetched regardless of video mode.
    """

    def __init__(self, device_index: int = 0):
        if not HAVE_FREENECT:
            raise KinectError(
                "freenect module not found -- libfreenect's Python bindings "
                "need to be built from source. See README.md."
            )
        self._index = device_index

    def get_frames(self, video_mode: str = VIDEO_MODE_RGB):
        """Returns (video_frame, depth_mm, video_mode).
        video_frame is HxWx3 uint8 RGB order for VIDEO_MODE_RGB, or
        HxW uint8 grayscale for VIDEO_MODE_IR (the raw speckle pattern).
        depth_mm is HxW uint16 in millimetres."""
        if video_mode == VIDEO_MODE_IR:
            frame, _ = freenect.sync_get_video(self._index, format=freenect.VIDEO_IR_8BIT)
        else:
            frame, _ = freenect.sync_get_video(self._index, format=freenect.VIDEO_RGB)
        raw_depth, _ = freenect.sync_get_depth(self._index)
        return frame, raw_depth_to_mm(raw_depth), video_mode

    def close(self):
        if HAVE_FREENECT:
            freenect.sync_stop()


class SimulatedKinectSource:
    """Synthetic RGB/IR + depth frames at the Kinect's native 640x480, for
    building and testing the dashboard without hardware attached."""

    WIDTH, HEIGHT = 640, 480

    def __init__(self):
        self._t0 = time.time()
        yy, xx = np.mgrid[0:self.HEIGHT, 0:self.WIDTH]
        self._xx = xx.astype(np.float32)
        self._yy = yy.astype(np.float32)
        # Fixed jittered dot centres, generated once -- the real projector's
        # pattern is fixed too, it doesn't reshuffle every frame. This is a
        # rough visual approximation for exercising the UI/toggle, not a
        # reproduction of the real (pseudo-random, ~30k dot) pattern, which
        # only real hardware can actually show.
        rng = np.random.default_rng(0)
        n_dots = 1400
        self._dot_x = rng.uniform(0, self.WIDTH, n_dots).astype(np.float32)
        self._dot_y = rng.uniform(0, self.HEIGHT, n_dots).astype(np.float32)

    def get_frames(self, video_mode: str = VIDEO_MODE_RGB):
        t = time.time() - self._t0
        xx, yy = self._xx, self._yy

        cx = self.WIDTH * (0.5 + 0.3 * math.sin(t * 0.6))
        cy = self.HEIGHT * (0.5 + 0.2 * math.cos(t * 0.4))
        blob = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2)) / (2 * 40.0 ** 2))

        if video_mode == VIDEO_MODE_IR:
            video_frame = self._synthetic_ir_frame(t)
        else:
            video_frame = self._synthetic_rgb_frame(t, xx, yy, blob)

        base_mm = 1800 + 300 * np.sin(xx / 80.0) + 200 * np.cos(yy / 60.0 + t)
        depth_mm = np.clip(base_mm - blob * 900, 400, 4000).astype(np.uint16)

        # Real structured-light sensors leave a no-return "shadow" strip
        # just beside a near object (the IR projector and camera are a few
        # cm apart, so each blocks a sliver of the other's view past an
        # edge). Mimicking that here means the depth panel's invalid-pixel
        # rendering is actually exercised in simulate mode, not just on
        # real hardware: a thin ring just outside the blob's visible
        # radius, on one side only.
        dist_from_center = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        one_side = (xx - cx) > 0
        shadow_ring = (dist_from_center >= 45) & (dist_from_center <= 58) & one_side
        depth_mm[shadow_ring] = 0

        time.sleep(1 / 30)  # ~30 fps, matching the real sensor
        return video_frame, depth_mm, video_mode

    def _synthetic_rgb_frame(self, t, xx, yy, blob):
        r = 128 + 127 * np.sin(xx / 40.0 + t)
        g = 128 + 127 * np.sin(yy / 40.0 + t * 1.3)
        b = 128 + 127 * np.sin((xx + yy) / 60.0 + t * 0.7)
        rgb = np.stack([r, g, b], axis=-1)
        rgb = np.clip(rgb + blob[..., None] * 255, 0, 255).astype(np.uint8)
        return rgb

    def _synthetic_ir_frame(self, t):
        # Dim, low-contrast background (matches the real sensor's raw IR
        # feed, which is much less punchy than a normal camera image) with
        # bright small dots at the fixed jittered centres, flickering
        # slightly frame to frame the way real IR speckle amplitude does.
        frame = np.full((self.HEIGHT, self.WIDTH), 18, dtype=np.float32)
        flicker = 0.85 + 0.15 * np.sin(t * 13.0 + np.arange(len(self._dot_x)))
        for x, y, f in zip(self._dot_x[::3], self._dot_y[::3], flicker[::3]):
            # Sparser subsample per frame for speed; still visually dense
            # enough at 640x480 to read as a scattered dot field.
            xi, yi = int(x), int(y)
            frame[max(0, yi - 1):yi + 2, max(0, xi - 1):xi + 2] = 200 * f
        return np.clip(frame, 0, 255).astype(np.uint8)

    def close(self):
        pass