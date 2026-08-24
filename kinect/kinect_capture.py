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
    """Real Kinect v1 via libfreenect."""

    def __init__(self, device_index: int = 0):
        if not HAVE_FREENECT:
            raise KinectError(
                "freenect module not found -- libfreenect's Python bindings "
                "need to be built from source. See README.md."
            )
        self._index = device_index

    def get_frames(self):
        """Returns (rgb, depth_mm): rgb is HxWx3 uint8 RGB order,
        depth_mm is HxW uint16 in millimetres."""
        rgb, _ = freenect.sync_get_video(self._index)
        raw_depth, _ = freenect.sync_get_depth(self._index)
        return rgb, raw_depth_to_mm(raw_depth)

    def close(self):
        if HAVE_FREENECT:
            freenect.sync_stop()


class SimulatedKinectSource:
    """Synthetic RGB + depth frames at the Kinect's native 640x480, for
    building and testing the dashboard without hardware attached."""

    WIDTH, HEIGHT = 640, 480

    def __init__(self):
        self._t0 = time.time()
        yy, xx = np.mgrid[0:self.HEIGHT, 0:self.WIDTH]
        self._xx = xx.astype(np.float32)
        self._yy = yy.astype(np.float32)

    def get_frames(self):
        t = time.time() - self._t0
        xx, yy = self._xx, self._yy

        r = 128 + 127 * np.sin(xx / 40.0 + t)
        g = 128 + 127 * np.sin(yy / 40.0 + t * 1.3)
        b = 128 + 127 * np.sin((xx + yy) / 60.0 + t * 0.7)
        rgb = np.stack([r, g, b], axis=-1)

        cx = self.WIDTH * (0.5 + 0.3 * math.sin(t * 0.6))
        cy = self.HEIGHT * (0.5 + 0.2 * math.cos(t * 0.4))
        blob = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2)) / (2 * 40.0 ** 2))
        rgb = np.clip(rgb + blob[..., None] * 255, 0, 255).astype(np.uint8)

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
        return rgb, depth_mm

    def close(self):
        pass