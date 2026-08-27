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
manual build. This recipe is the one actually verified working end to
end on macOS (Apple Silicon, AppleClang 17, Python 3.11 via venv) — a
plain `cmake .. -DBUILD_PYTHON3=ON` is not enough; each piece below
addresses a specific failure hit along the way.

**One source change is required first.** libfreenect's own
`wrappers/python/CMakeLists.txt` links the extension module directly
against `Python3_LIBRARIES`. On this toolchain that resolves to the
*static* `libpython3.11.a`, which pulls a whole second copy of CPython's
built-in modules (`_ssl`, `posix`, `gc`, ...) into `freenect.so` —
two interpreters colliding in one process, which crashes on import with
a segfault. Open `wrappers/python/CMakeLists.txt`, find (around line 66):

```
target_link_libraries(cython${Python_BUILD_VERSION}_freenect
  freenect_sync
  ${Python${Python_BUILD_VERSION}_LIBRARIES})
```

and delete the `${Python${Python_BUILD_VERSION}_LIBRARIES}` line, so it
reads just:

```
target_link_libraries(cython${Python_BUILD_VERSION}_freenect
  freenect_sync)
```

Then, with the venv for this project active (`source venv/bin/activate`,
so `numpy` is already installed and CMake targets the right Python):

```
brew install libusb cmake pkg-config
pip install cython setuptools   # setuptools restores distutils, removed in Python 3.12+

git clone https://github.com/OpenKinect/libfreenect
cd libfreenect
# apply the CMakeLists.txt edit above before configuring

rm -rf build
mkdir build && cd build

cmake .. \
  -DBUILD_PYTHON3=ON \
  -DBUILD_CPP=OFF \
  -DPython3_EXECUTABLE=$(which python3) \
  -DCMAKE_MODULE_LINKER_FLAGS="-undefined dynamic_lookup -Wl,-no_fixup_chains" \
  -DCMAKE_INSTALL_PREFIX="$VIRTUAL_ENV" \
  -DCMAKE_INSTALL_RPATH="$VIRTUAL_ENV/lib" \
  -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON

make
make install
```

What each non-default flag is for, in case a future rebuild only hits
some of these:

| Flag | Fixes |
|---|---|
| `-DBUILD_CPP=OFF` | Skips libfreenect's C++ demo viewer, unrelated to Python bindings and broken by a separate stale-CommandLineTools issue on this machine |
| `-DPython3_EXECUTABLE=$(which python3)` | Forces CMake to target the venv's Python, not Homebrew's system default |
| `-DCMAKE_MODULE_LINKER_FLAGS="-undefined dynamic_lookup -Wl,-no_fixup_chains"` | Lets Python symbols resolve at runtime instead of statically, and keeps that compatible with newer macOS "chained fixups" linking |
| `-DCMAKE_INSTALL_PREFIX="$VIRTUAL_ENV"` | Installs straight into the venv's site-packages, no manual symlinking |
| `-DCMAKE_INSTALL_RPATH="$VIRTUAL_ENV/lib"` + `-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON` | Lets `freenect.so` actually find `libfreenect_sync.dylib` at import time |
| CMakeLists.txt edit above | The actual crash fix — stops a second CPython from getting linked into the module |

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