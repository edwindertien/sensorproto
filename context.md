# UniProto — Context & Decision Log

Running log of bugs found, decisions made, and lessons learned across
development sessions.

---

## Architecture Decisions

### PlatformIO multi-environment structure
`src_dir = .` in `[platformio]` (not in `[env:*]`) with per-env
`build_src_filter = -<*> +<src_name/>` resolves "undefined reference to
setup/loop" and "Nothing to build" errors when sharing a repo across setups.

### Binary framing
`w.begin(sid, payloadLen)` requires an explicit payload length. Omitting it
(using default `payloadLen=0`) silently no-ops all subsequent field writes.
Payload length = sum of all field byte sizes: u16=2, i32=4, f32=4, u8[N]=N.

### EU grading formula (rubric tools)
`grade = 1 + 9 × (earned / max)`

---

## Python Reader Patterns

### Non-blocking serial
```python
ser = serial.Serial(port, baud, timeout=0.0)
time.sleep(2.0); ser.reset_input_buffer()
# in loop:
waiting = ser.in_waiting
if waiting: rxbuf += ser.read(waiting)
```

### Parse-first receive
Try comma-split and int/float parse; if fails → log as text. Never
pre-filter on first character — negative CSV values start with `-`
which fails `.isdigit()`.

```python
parts = [p.strip() for p in line.split(",")]
if len(parts) != N:
    log(f"  {line}")   # text response
    continue
try:
    val = float(parts[0])
    ...
except ValueError:
    log(f"  {line}")
    continue
```

### Matplotlib Button GC
Buttons created in loops must be stored in a list:
```python
_btns = []
for ...:
    b = Button(...)
    b.on_clicked(...)
    _btns.append(b)   # ← essential, prevents GC killing event handlers
```

### TextBox double-fire
`on_submit` fires on both Enter keypress and focus-loss. Use a simple
debounce or just accept the duplicate (Arduino ignores repeated same command).

### Matplotlib redraw at fixed interval
```python
last_draw = time.time()
if new_data and (now - last_draw) >= 0.04:
    last_draw = now; new_data = False
    # update plots
    fig.canvas.draw_idle(); fig.canvas.flush_events()
else:
    plt.pause(0.005)
```

---

## Sensor-Specific Notes

### HX711 (load_cell, kitchen_scales)

- **Wrong param prefix bug:** `defaultUno2()` sets `prefix="hx2"`. Override
  with `c.prefix = "hx"` in `makeCfg()` if you only want `hx.*` params.
- **Blocking reads stall serial:** `readAvg(4)` at 100ms per sample = 400ms
  blocking per emit. Fix: non-blocking `readOnce()` in emit (returns stale
  if DOUT not ready); averaging via accumulator in `poll()` called from `loop()`.
- **TextBox double-fire:** see above.
- **Non-data responses swallowed:** receive loop only parsed 2-field CSV lines.
  Fix: parse-first pattern above.
- **Negative value gating:** `line[0].lstrip("-").isdigit()` incorrectly
  rejects negative CSV values. Fix: parse-first, classify by parse failure.

### AS5600 + BLDC Gimbal

- **Magnet range:** 4mm diametric disc magnet gives 12-bit range (0–4095)
  not 14-bit (0–16383). Scale: `raw / 4095.0 * 2π`.
- **Startup zero:** initialise `_prev` to first AS5600 reading so `_angle`
  starts at 0 naturally. Do NOT subtract a `_start_offset` — this creates
  spurious wraps when the raw reading crosses zero, corrupting `_angle` by
  ±2π and causing the spring to push away instead of pull back.
- **FOC on Uno:** SimpleFOC exceeds 32KB flash (33.9KB). Custom minimal
  FOC implemented instead.
- **PWM symmetry:** Timer1 (pins 9,10) must use same range as Timer2 (pin 11).
  Set `ICR1=255` so all three phases use 0–255 — otherwise phase C has half
  the resolution and the three-phase symmetry breaks, creating a preferred
  rotation direction.
- **Electrical angle negation:** with `diff = -diff` (CW=positive mechanical),
  electrical angle must be `-_angle * poles` to produce symmetric torque.
  Spring `vq = -k * err` is then correct (negative vq when error is positive).
- **Pole pairs (BDUA 2204):** 7 pole pairs confirmed by open-loop stable
  point count and 1/7-revolution-per-electrical-revolution sweep test.
- **Sweep direction:** with negated electrical angle, `_th_open -= sweep_hz * dt`
  gives CW = positive `sweep_hz`.
- **Phase offset `foc.ph`:** adjustable to compensate for minor CW/CCW
  speed asymmetry in sweep mode.

### Cap sense (Duemilanove 168)

- Board ID: `diecimilaatmega168` (not `diecimila`)
- Only 14KB flash / 1KB RAM → reduced UniProto limits in build flags
- `_delay_us` is a reserved function name in AVR libc. Rename to `_chargeUs`.
- 200pF + 10MΩ: τ = 2ms. Mode 0 at 200µs charge delay works well.
- Non-linear range or sudden drop to zero: check for bent rotor plate
  (shorting stator). Confirmed fix: bend plate back with toothpick.

### Synchro transformer

- Timer2 used for 5kHz ISR (not PWM output). Timer0/Timer1 set for
  fast PWM on phase output pins.
- Timer0 prescaler change (`TCCR0B = 1`) breaks `millis()` — UniProto's
  rate limiter is affected but communication still works.
- Binary framing required for frame data. Startup sequence must silence
  stream first (`!stream:0`) before switching format.
- `w.begin(sid)` with no payload length silently drops all data in binary
  mode. Must pass explicit `payloadLen = 3*2 + count`.
- Angle cross-correlation: torn-read race between ISR writing `_capture[]`
  and main loop reading it. Angle values erratic. TODO: double-buffer.

### MMA7260 accelerometer

- SLEEP, GS1, GS2 must be driven as digital outputs before sensor works.
- g-select: GS1=0, GS2=0 → ±1.5g, 800mV/g, Vzero=1.65V.
- `atan2` for pitch/roll (not `asin`): `asin` compresses large angles
  by ~6×. `atan2(gx, sqrt(gy²+gz²))` gives correct ±90° range.
- Matplotlib button GC bug affected avg/rate buttons in loop — fixed with
  `_rate_btns = []` / `_avg_btns = []` lists.

---

## BLDC Gimbal — Debugging Chronicle

Long debug trail worth documenting to avoid repeating.

1. **M5Stack DRV11873** — wrong driver. Sensorless BEMF trapezoidal,
   minimum speed required. Unsuitable for gimbal.
2. **SimpleFOC** — too large for Uno (33.9KB > 32KB). Custom FOC written.
3. **38400 baud** — left over from original Processing sketch. Changed to
   115200 to match rest of project. Was causing "no response" symptom.
4. **Binary framing** — `w.begin(sid)` with no payload length silently
   dropped all data. Fixed by passing explicit `payloadLen`.
5. **PWM asymmetry** — Timer1 using `ICR1=511` (0–511 range) while Timer2
   used 0–255. Caused preferred rotation direction. Fixed: `ICR1=255`.
6. **`_start_offset` bug** — subtracting startup position from raw reading
   caused a spurious `±2π` jump in `_angle` whenever the raw sensor crossed
   zero, depending on startup position. Spring then applied wrong-direction
   force at that angular position. Fixed: removed `_start_offset` entirely;
   initialise `_prev` to first reading instead.
7. **Electrical angle sign** — with CW=positive `_angle` (via `diff = -diff`),
   must use `-_angle * poles` for electrical angle. Spring `vq = -k * err`
   is then correct. Sweep uses `_th_open -= sweep_hz * dt`.
8. **Pole pairs** — confirmed 7 by two methods: open-loop stable point count
   (4 originally confused us, but was actually TWO separate issues at once),
   and 1/7-revolution per electrical sweep.

---

## TODO

- [ ] **bldc_gimbal:** Verify spring symmetry after latest firmware fixes
- [ ] **bldc_gimbal:** Tune spring/damper, step response testing
- [ ] **bldc_gimbal:** Implement detent mode verification
- [ ] **synchro:** Fix angle cross-correlation torn-read race (double-buffer)
- [ ] **wind_speed:** Add pulse counting for calibrated flow measurement
- [ ] **kitchen_scales:** Verify calibration after parser fixes
- [ ] **readers/unistream.py:** Extract common serial boilerplate
- [ ] Apply parse-first pattern to `plot_cap_sense.py` and `plot_wind_raw.py`
- [ ] **NAO robot:** USB recovery flash to NAOqi 2.1 (Project Glasswing pending)
- [ ] **DRV8313 SimpleFOC on Mega:** mod_simplefoc wrapper when hardware arrives