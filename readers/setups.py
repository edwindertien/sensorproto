"""
setups.py — single source of truth for every UniProto setup.

Read by:
  readers/launcher.py          the click-to-start launcher
  tools/make_icons.py          generates docs/icons/<id>.png
  tools/update_readme_grid.py  rebuilds the icon grid in README.md

To add a setup: add one Setup(...) entry below (keep 24 for a 4x6 grid, or
change GRID_COLS), add its glyph in tools/make_icons.py, re-run the two tools.

Run `python readers/launcher.py --check` to see which reader scripts exist.
"""
from dataclasses import dataclass

GRID_COLS = 6

# (name, tile colour) — one group per grid row
GROUPS = [
    ("Motion & actuation",      "#2B6CB0"),   # blue
    ("Position & angle",        "#0F8B8D"),   # teal
    ("Force, touch & distance", "#C96F1A"),   # amber
    ("Bio, sound & vision",     "#7A4FB5"),   # purple
]


@dataclass(frozen=True)
class Reader:
    script: str            # file in readers/, or a path from readers/ or from the repo root (kinect/app.py)
    label: str             # shown on the launcher button
    args: tuple = ()       # extra command-line arguments
    port: bool = True      # False = script does not take --port
    debug: bool = False    # raw probes etc.: hidden in the launcher unless "Show debug readers"
    server: bool = False   # a long-running app (e.g. Flask) with no window of its own: the launcher
                           # shows Stop + the address it prints, and opens that address
    python: str = ""       # optional interpreter for this script (path relative to readers/, or absolute);
                           # default = the Python that runs the launcher


@dataclass(frozen=True)
class Setup:
    id: str                # icon file name + README anchor (underscores -> hyphens)
    title: str
    tagline: str
    env: str               # PlatformIO environment ('' = Python only)
    board: str
    group: int             # index into GROUPS
    readers: tuple = ()    # first non-debug reader = what a click starts
    note: str = ""         # shown when the setup has no reader

    @property
    def anchor(self) -> str:
        return self.id.replace("_", "-")


R = Reader

SETUPS = [
    # ── row 1: motion & actuation ────────────────────────────────────────────
    Setup("bldc_gimbal", "BLDC gimbal", "FOC haptic knob", "bldc_gimbal", "Uno", 0,
          (R("plot_bldc_gimbal.py", "Gimbal control"),)),
    Setup("bldc_servo", "BLDC servo", "ESC, 50 Hz PWM", "bldc_servo", "Uno", 0, (),
          note="No Python reader yet. Talk to it with: pio device monitor -e bldc_servo"),
    Setup("dc_motor", "DC motor", "PID position / velocity", "dc_motor", "Uno", 0,
          (R("plot_dc_motor.py", "Motor monitor"),)),
    Setup("dual_motor", "Dual motor", "haptic master-slave", "haptic", "Uno", 0,
          (R("plot_haptic_dual_motor.py", "Dual motor monitor"),
           R("plot_dual_motor.py", "Monitor + rec/save"),
           R("plot_haptic_dual_motor_stream.py", "Stream plot"),
           R("plot_haptic_dual_motor_stream_vel.py", "Stream + velocity"),
           R("plot_haptic_dual_motor_debug.py", "Raw probe", debug=True))),
    Setup("stepper", "Stepper", "MKS SERVO42D", "stepper", "Uno", 0, (),
          note="No Python reader yet. Talk to it with: pio device monitor -e stepper"),
    Setup("pneumatic", "Pneumatic", "pump + pressure", "pneumatic", "Uno", 0, (),
          note="No Python reader yet. Talk to it with: pio device monitor -e pneumatic"),

    # ── row 2: position & angle ──────────────────────────────────────────────
    Setup("lvdt", "LVDT", "AC position sensor", "lvdt", "Uno", 1,
          (R("plot_lvdt.py", "LVDT waveforms"),)),
    Setup("synchro", "Synchro", "3-phase angle", "synchro", "Uno", 1,
          (R("plot_synchro.py", "Synchro angle"),)),
    Setup("optical_mouse", "Optical mouse", "ADNS-2610 camera", "optical_mouse", "Uno", 1,
          (R("plot_adns_picture.py", "Picture 18x18"),
           R("plot_adns_motion.py", "Motion dx/dy"),
           R("plot_adns_debug.py", "Raw debug", debug=True))),
    Setup("qtr8", "QTR-8", "line / gray-code strip", "qtr8", "Duemilanove 328p", 1,
          (R("plot_qtr8.py", "Reflectance array"),)),
    Setup("accelerometer", "Accelerometer", "MMA7260, 3 axes", "accelerometer", "Uno", 1,
          (R("plot_accelerometer.py", "Accelerometer"),)),
    Setup("wiimote", "Wiimote IR", "IR camera via I2C", "wiimote", "Uno", 1, (),
          note="No Python reader yet. Talk to it with: pio device monitor -e wiimote"),

    # ── row 3: force, touch & distance ───────────────────────────────────────
    Setup("load_cell", "Load cell", "HX711 amplifier", "load_cell", "Uno", 2,
          (R("plot_load_cell.py", "Load cell"),)),
    Setup("kitchen_scales", "Kitchen scales", "load cell + HX711", "kitchen_scales", "Uno", 2,
          (R("plot_kitchen_scales.py", "Scales"),
           R("plot_load_cell.py", "Calibrate"))),
    Setup("cap_sense", "Cap sense", "variable capacitor", "cap_sense", "Duemilanove 168", 2,
          (R("plot_cap_sense.py", "Capacitance"),)),
    Setup("psd_distance", "IR distance", "Sharp PSD", "psd_distance", "Uno", 2,
          (R("plot_psd_distance.py", "IR distance"),)),
    Setup("us_distance", "Ultrasonic", "HC-SR04 scope view", "us_distance", "Uno", 2,
          (R("plot_us_distance.py", "Pulse scope"),)),
    Setup("sensor_shield", "Sensor shield", "7 sensors, 1 board", "sensor_shield", "Uno", 2,
          (R("plot_sensor_shield.py", "All sensors"),
           R("plot_sensor_shield_flask.py", "Browser view"),
           R("plot_sensor_shield_weight.py", "Foil vs strain"),
           R("plot_sensor_shield_angle.py", "Pot vs Hall"))),

    # ── row 4: bio, sound & vision ───────────────────────────────────────────
    Setup("biosensors", "Biosensors", "GSR + heart rate", "biosensors", "Uno", 3,
          (R("plot_biosensors.py", "GSR + heart rate"),)),
    Setup("wind_speed", "Wind speed", "optical anemometer", "wind_speed", "Uno", 3,
          (R("plot_wind_speed.py", "Anemometer"),)),
    Setup("piezo_serial", "Piezo drums", "stream + heatmap", "piezo_serial", "Leonardo", 3,
          (R("plot_piezo_serial.py", "Pads + sounds"),)),
    Setup("piezo_midi", "Piezo MIDI", "USB-MIDI drum kit", "piezo_midi", "Leonardo", 3, (),
          note="Firmware only: the Leonardo shows up as a USB-MIDI device "
               "(notes 36/38/42/46 on channel 10). Flash with: "
               "pio run -e piezo_midi -t upload"),
    Setup("lidar", "Lidar", "Hokuyo laser scanner", "", "PC", 3,
          (R("hokuyo/app.py", "Hokuyo app", port=False, server=True),)),
    Setup("kinect", "Kinect", "depth camera", "", "PC", 3,
          (R("kinect/app.py", "Kinect app", port=False, server=True),)),
]

# Scripts in readers/ that belong to no single setup. `launcher.py --check` lists every other
# plot_*.py that is not referenced above as "not in setups.py".
NOT_SETUPS = {
    "plot_adc_blocks.py": "generic viewer for binary ADC-block streams",
    "example.py": "template for a new reader",
    "launcher.py": "this launcher",
    "setups.py": "the setup list",
    "uniproto_backend.py": "matplotlib backend picker",
}

assert len(SETUPS) % GRID_COLS == 0, "grid is not rectangular"
assert len({s.id for s in SETUPS}) == len(SETUPS), "duplicate setup id"