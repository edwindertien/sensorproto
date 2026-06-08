# UniProto — Project Context & Debug Log

Running record of environment issues, design decisions, and hardware findings
encountered during bring-up. Newest entries at the top of each section.

---

## Environment

| item | value |
|------|-------|
| Host OS | macOS |
| PlatformIO Python | 3.11 (embedded at `~/.platformio/penv/`) |
| System Python | 3.14 (brew) |
| Arduino framework | atmelavr (PlatformIO) |
| Primary board | Arduino Uno |
| Secondary board | Arduino Leonardo (piezo_midi) |

---

## PlatformIO / build issues

### `build_src_filter` does not work in `[env:*]` sections (resolved)
**Symptom:** `undefined reference to setup / loop` at link time, or
`Nothing to build. Please put your source code files to the 'src' folder`.  
**Cause:** `build_src_filter` patterns are always relative to `src_dir`
(default `src/`). Setting it per-env does not change `src_dir`, so patterns
like `+<src_optical_mouse/>` resolve to `src/src_optical_mouse/` — which
does not exist.  
`src_dir` itself is only honoured in `[platformio]`, not in `[env:*]`.  
**Fix:** Add `[platformio] src_dir = .` (project root) and use
`build_src_filter = -<*> +<src_optical_mouse/>` per env.
Patterns now resolve from the project root.

---

## Python / matplotlib issues

### TkAgg backend unavailable in PlatformIO's embedded Python (resolved)
**Symptom:**
```
ModuleNotFoundError: No module named '_tkinter'
```
**Cause:** PlatformIO ships its own Python 3.11 at `~/.platformio/penv/`.
`brew install python-tk` installs tkinter for the system Python (3.14),
not for PlatformIO's Python 3.11.  
**Fix:** Use `matplotlib.use("MacOSX")` in all reader scripts.
The `MacOSX` backend is native to macOS matplotlib wheels and requires
no additional packages.  
**Alternative:** Run readers with system Python (`python3 plot_*.py ...`)
after `pip3 install pyserial matplotlib numpy` there.

### `plot_adns_picture.py` exits immediately with no output (resolved)
**Symptom:** Script prints the three setup commands then terminates with
`zsh: terminated`.  
**Cause 1:** `plt.ion()` with a non-interactive or unavailable backend
raises an unhandled exception that kills the process before the `while True`
loop starts.  
**Cause 2:** `--show` flag was absent — the original script skipped all
matplotlib setup when `--show` was not passed, so no window appeared even
when data was flowing.  
**Fix:** Rewrite `plot_adns_picture.py` to always create the window, add
`matplotlib.use("MacOSX")` before the import, and use
`plt.fignum_exists(fig.number)` as the loop condition so the script exits
cleanly when the window is closed.

---

### Serial buffer lag in visualiser scripts (resolved)
**Symptom:** Cursor and strip chart continue moving for several seconds after
motion has stopped.  
**Cause:** Using `readline()` in the main loop reads one line per iteration.
If the draw step takes longer than the sample interval the OS serial buffer
fills up and the backlog grows unboundedly — the visualiser is always showing
the past, not the present.  
**Fix:** Use `timeout=0.0` (non-blocking) and `ser.in_waiting` to drain
all available bytes in one `ser.read()` call each iteration. Parse every
complete line in the resulting buffer so all queued samples update the internal
state, but only draw once per frame (every ~40 ms). Also call
`ser.reset_input_buffer()` after the setup commands to discard anything
queued during the connect/config delay.  
**Pattern to use in all future readers:**
```python
ser = serial.Serial(port, baud, timeout=0.0)   # non-blocking
# in the loop:
waiting = ser.in_waiting
if waiting:
    rxbuf += ser.read(waiting)
while b"\n" in rxbuf:
    line, rxbuf = rxbuf.split(b"\n", 1)
    # parse line, update state
# draw only at fixed interval, not per line
```

### `UNIPROTO_MAX_PARAMS` redefined warnings (resolved)
**Symptom:** Dozens of `warning: "UNIPROTO_MAX_PARAMS" redefined` during compilation.  
**Cause:** `build_flags` in `[env]` included `-DUNIPROTO_MAX_PARAMS=32`, and
envs that needed a higher value appended `${env.build_flags} -DUNIPROTO_MAX_PARAMS=40`,
defining it twice. PlatformIO passes all flags to every translation unit so the
warning fires once per .cpp file.  
**Fix:** Move shared flags to a `[common]` section with a `build_flags_base` key.
`[env]` inherits via `build_flags = ${common.build_flags_base}`. Envs that need
different values define `build_flags` explicitly without inheriting, so no
double-definition occurs.

### `i2cScan()` defined but not used warning (known, low priority)
`static void i2cScan()` is defined in `mod_bldc.h` as a bring-up helper.
Being `static` in a header means it gets compiled into every TU that includes
the header, even when not called. Fix: move to `mod_bldc.cpp` behind an
`#ifdef BLDC_ENABLE_I2C_SCAN` guard. Deferred until bldc_gimbal is verified.

## Hardware findings

### optical_mouse — ADNS2610 motion (plot_adns_motion.py)
- `plot_adns_motion.py` — XY cursor trail (left) + dx/dy strip chart (right).
  Non-blocking serial drain pattern required to avoid lag (see serial buffer
  lag issue above).
- Strip chart x-axis uses `range(-N, 0)` (samples ago) rather than absolute
  counter — feels like a scrolling window.

### optical_mouse (ADNS2610)

- **Stuck pixel at (10, 4):** One pixel consistently reads maximum brightness (value 63/63)
  regardless of scene content. Confirmed sensor artefact — remains bright with lens
  fully covered. Not a communication error (all frame chunks arrive with correct
  offsets and counts; stuck value is always 63, not random).
  ADNS-2610 is a circa-2002 sensor with no on-chip bad-pixel correction.
  Mitigation: mask and interpolate in the visualiser if needed.

- **Binary framing verified:** 6 chunks × 54 pixels = 324 = 18×18 ✅.
  Frame IDs increment correctly. `plot_adns_debug.py` confirms clean reception
  before attempting visualisation.

- **CSV mode drops pixel bytes by design:** `UniCsvWriter::bytes()` is a no-op —
  frame data only transfers correctly in `!format:bin`. The 5 CSV header fields
  (frame_id, w, h, offset, count) print correctly but pixel payload is silently
  discarded. This is intentional in UniProto.

### psd_distance (Sharp GP2Y0A710)

- Default calibration constants (A=137.5, B=1.125) are for the GP2Y0A710K0F
  variant. If readings are consistently offset, adjust `!psd.cal_a` and
  `!psd.cal_b` at runtime — no reflash needed.
- Default range clamped to 100–550 cm. Can be tuned at runtime:
  `!psd.cm_min:20.0` / `!psd.cm_max:550.0`. Accuracy degrades below ~100 cm
  due to the steep inverse calibration curve.

---

## Design decisions

### Project structure: `src_dir = .` + per-env `build_src_filter`
Each setup lives in `src_<name>/main.cpp` at the project root.
`lib/` is shared across all envs via PlatformIO's LDF (no explicit config needed).
Chosen over separate repos, submodules, or a single `src/` with `#ifdef` guards.

### Inline HX711 driver (load_cell, kitchen_scales, pneumatic)
Three setups share an identical minimal inline HX711 read loop rather than a
proper `mod_hx711` module. To be refactored into `lib/modules/mod_hx711.h/.cpp`
once all three setups are hardware-verified.

### matplotlib backend strategy
All reader scripts use `matplotlib.use("MacOSX")` placed before the matplotlib
import. This must come before any `import matplotlib.pyplot` line. If porting
to Linux replace with `"TkAgg"` or `"Qt5Agg"`.

### Binary vs CSV for pixel/block data
`UniCsvWriter::bytes()` is intentionally a no-op. Any setup streaming bulk
data (ADNS frame, ADC block) must use `!format:bin`. The reader scripts handle
the switch automatically — do not manually set binary mode in the monitor when
a reader script will be used, as they set it themselves on connect.

---

### haptic — dual Maxon motor + L293

- **500 ticks/rev** confirmed on output shaft (measured with spin tool, 5s at PWM=80).
  Likely 100 PPR encoder × 5:1 gear, exact split unknown but irrelevant for control.
- **~220 RPM output** at PWM=80 (~31% duty, 5V supply).
- **Kp=1.5, pwm_lim=180** gives textbook step response: ~5% overshoot, single
  correction pulse, locks on target. No Ki or Kd needed for basic positioning.
- Bidirectional haptic link (`!motor.link:3`) works. `!motor.link_scale:0.5`
  gives softer coupling feel.
- `plot_dual_motor.py` has integrated command panel (send box + preset buttons)
  so no second serial terminal is needed during tuning.

## TODO

- [ ] `lib/modules/mod_hx711.h/.cpp` — shared HX711 driver
- [ ] `lib/modules/mod_hc_sr04.h` — HC-SR04 as proper module  
- [ ] `lib/modules/mod_wiimote.h` — Wiimote IR camera module
- [ ] Dead-pixel correction option in `plot_adns_picture.py` (`--deadpix x,y`)
- [ ] `readers/unistream.py` base class — extract common serial boilerplate
      (after all setups verified)