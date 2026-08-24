# Kinect for Xbox 360 live visualiser

Standalone Flask dashboard showing the Kinect v1's RGB and depth streams
side by side. Not wired into the UniProto Arduino stream — this talks
straight to the Kinect over its own USB connection via libfreenect.

## 1. Try it without hardware

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py --simulate
```

Open http://127.0.0.1:5002 — synthetic RGB and depth frames let you check
the layout before touching libfreenect or the sensor.

## 2. Build libfreenect + its Python bindings (macOS)

Homebrew's `libfreenect` bottle doesn't include the Python module (a past
PR to add it was rejected upstream over a linking issue), so it needs a
manual build:

```
brew install libusb cmake pkg-config
git clone https://github.com/OpenKinect/libfreenect
cd libfreenect
mkdir build && cd build
cmake .. -DBUILD_PYTHON3=ON
make
sudo make install
```

This installs a `freenect` module onto your system Python. If you're
using a venv and it isn't picked up, check where `make install` put the
`.so`/`.dylib` (`find / -name "freenect*" 2>/dev/null`) and either
symlink it into your venv's site-packages or add it to `PYTHONPATH`.

Sanity-check the driver on its own before involving Flask:

```python
import freenect
rgb, _ = freenect.sync_get_video()
print(rgb.shape)   # expect (480, 640, 3)
```

If that raises a USB permissions/access error, unplug and replug the
Kinect (it needs both USB and its separate power supply connected) and
try again; on first connect macOS may also prompt for a permission
dialog you need to approve.

## 3. Run against real hardware

```
python app.py
```

## Files

- `kinect_capture.py` — thin wrapper around `freenect.sync_get_video()` /
  `sync_get_depth()`, plus the raw-disparity-to-millimetres conversion
  and the `SimulatedKinectSource` fallback.
- `app.py` — background capture thread + Flask routes: `/rgb_feed` and
  `/depth_feed` as MJPEG streams, `/stats` for frame rate and nearest
  point, `/` for the page.
- `templates/index.html` — two-panel page, polls `/stats` once a second.

## Notes

- Depth is requested in the sensor's native 11-bit raw format and
  converted to millimetres with the standard community-derived formula
  (documented in `kinect_capture.py`); it hasn't been checked against a
  hand-measured distance yet, since testing so far has been simulate-mode
  only — worth a quick sanity check once the sensor is attached, the same
  way as with the Hokuyo tool.
- The depth panel uses a fixed 0.4–4.0 m colour scale (`COLORMAP_TURBO`)
  rather than auto-ranging per frame, so distances stay visually
  comparable across frames. Adjust the clamp range in `_depth_to_jpeg()`
  in `app.py` if your setup needs a different working distance.
- RGB and depth are pulled independently and aren't guaranteed
  frame-synchronised; fine for a live view, not for anything that needs
  precise RGB-depth correspondence.
