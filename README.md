# UniProto — Sensor Streaming Library

Modular Arduino sensor streaming library with CSV/binary serial output and
Python visualisers. Built for the *Mastering Tinkering* and *Social Robot
Design* courses at the University of Twente.

---

## Architecture

```
project root/
  platformio.ini          per-environment build config
  lib/
    uniproto/             UniProto core (UniProto.h/cpp, UniWriter.h/cpp)
    modules/              mod_adc, mod_hx711, mod_adns2610, mod_synchro, ...
  src_<setup>/            one directory per hardware setup
  readers/                Python visualisers (one per setup)
  docs/                   manuals, context log, figures
```

Each setup has its own `[env:name]` in `platformio.ini` with a
`build_src_filter` pointing to its `src_<name>/` directory.
The `src_dir = .` global setting allows sharing `lib/` across all envs.

**Key architectural decision:** `src_dir = .` in `[platformio]` (not in
`[env:*]`), with per-env `build_src_filter = -<*> +<src_name/>`.
This was the fix for "undefined reference to setup/loop" errors.

---

## Setups

| env | hardware | board | firmware | visualiser | status |
|---|---|---|---|---|---|
| `psd_distance` | Sharp GP2Y0A710 IR distance | Uno | `mod_adc` | `plot_psd_distance.py` | ✅ |
| `optical_mouse` | ADNS-2610 optical sensor | Uno | `mod_adns2610` | `plot_adns_picture.py`, `plot_adns_motion.py` | ✅ |
| `haptic` | 2× Maxon mini + L293 | Uno | `mod_motors` | `plot_dual_motor.py` | ✅ |
| `load_cell` | HX711, DOUT=A3, SCK=A2 | Uno | `mod_hx711` | `plot_load_cell.py` | ✅ |
| `kitchen_scales` | HX711, DOUT=A1, SCK=A0 | Uno | `mod_hx711` | `plot_kitchen_scales.py` | ✅ |
| `accelerometer` | MMA7260, SLEEP=2, GS1=3, GS2=4 | Uno | `mod_adc` | `plot_accelerometer.py` | ✅ |
| `cap_sense` | 200pF variable cap, SENSE=A0, SEND=A3 | **Duemilanove 168** | inline | `plot_cap_sense.py` | ✅ |
| `synchro` | 3-phase PWM + receiver coil A1 | Uno | `mod_synchro` | `plot_synchro.py` | ✅ |
| `bldc_gimbal` | DRV8313 LittleFOC + AS5600 + BDUA 2204 | Uno | minimal FOC | `plot_bldc_gimbal.py` | ✅ |
| `wind_speed` | optical gate, A0 | Uno | `mod_adc` | `plot_wind_raw.py` | 🔧 |
| `bldc_servo`, `pneumatic`, `stepper`, `dc_motor`, `lvdt`, `sensor_shield`, `qtr8`, `biosensors`, `piezo_midi`, `us_distance`, `wiimote` | various | Uno/Leonardo | — | — | ⬜ |

---

## UniProto Protocol

### Commands (Arduino ← PC)

| Command | Example | Effect |
|---|---|---|
| `?` | `?` | Query capabilities (JSON) |
| `?key` | `?hx.scale` | Get parameter value |
| `!key:value` | `!rate:20` | Set parameter |
| `@action` | `@foc.zero` | Trigger action |

### Core parameters (all setups)

| Param | Example | Description |
|---|---|---|
| `rate` | `!rate:50` | Stream rate in Hz |
| `format` | `!format:csv` | Output format: `csv` or `bin` |
| `timestamp` | `!timestamp:0` | Include timestamp in frames |
| `stream` | `!stream:1` | Enable stream by ID |

### CSV format

```
value1,value2,...\n
```

### Binary format

```
0xAA 0x55 stream_id flags payload_len[2] [timestamp[4]] payload...
```

---

## Python Readers

All readers follow the same pattern:

```python
ser = serial.Serial(port, 115200, timeout=0.0)
time.sleep(2.0); ser.reset_input_buffer()
send_and_wait(ser, "!format:csv")
send_and_wait(ser, "!rate:20")
send_and_wait(ser, "!stream:1")
```

**Non-blocking serial pattern:** `timeout=0.0`, drain with `ser.in_waiting`,
parse all lines, redraw at fixed interval (~40ms).

**Parse-first pattern:** try to split and parse as numbers; if that fails,
treat as a text response (OK, ERR, param reply) and log it. Never
pre-filter by first character — negative values start with `-` which is
not a digit.

**Button GC rule:** all Button objects created in loops must be stored in
a list (`_btns = []`, `_btns.append(b)`) or Python garbage-collects them
and their click handlers stop working.

---

## Key Learnings

- **PlatformIO multi-env:** `src_dir = .` in `[platformio]` only
- **Binary framing:** `w.begin(sid, payloadLen)` requires explicit length;
  `payloadLen=0` silently no-ops all writes
- **Matplotlib GC:** buttons in loops must be kept in a list
- **Negative CSV values:** parse-first, not character-filter
- **TextBox double-fire:** `on_submit` fires on Enter AND focus-loss
- **AS5600 + BLDC:** 4mm diametric magnet gives 12-bit range (0–4095);
  startup offset handled by initialising `_prev` to first reading
- **FOC on Uno:** SimpleFOC exceeds 32KB flash; custom minimal FOC needed
- **PWM symmetry:** Timer1 and Timer2 must use identical ranges for
  symmetric three-phase generation (ICR1=255 = Timer2 8-bit range)
- **HX711 blocking:** `readAvg()` in emit handler blocks serial; use
  non-blocking `readOnce()` in emit, average in `poll()` via `loop()`
- **Cap sense:** `_delay_us` is reserved in AVR libc — rename to `_chargeUs`

---

## Documentation

- [`docs/bldc_gimbal.md`](docs/bldc_gimbal.md) — BLDC gimbal full manual
- [`docs/context.md`](docs/context.md) — running decision and bug log