# UniProto sensor readers — setup guide

Quick setup for running the sensor visualisers on macOS, Windows, or Linux.

---

## 1. Prerequisites

- **Python 3.10 or newer** — [python.org](https://www.python.org/downloads/)
- **pip** (comes with Python)
- **Arduino drivers** installed for your board (Uno/Duemilanove: CH340 or FTDI; Leonardo: built-in USB)

---

## 2. Install dependencies

A virtual environment keeps things clean and avoids conflicts with other Python projects.

### macOS / Linux

```bash
cd sensorproto/readers
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows

```bat
cd sensorproto\readers
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

After activation your prompt will show `(.venv)`. Run `deactivate` to leave the venv.

### Without a venv (quick and dirty)

```bash
pip install -r requirements.txt
# or: pip3 install -r requirements.txt
```

---

## 3. Finding your serial port

Plug in your Arduino and find its port:

| OS      | Command                          | Typical result              |
|---------|----------------------------------|-----------------------------|
| macOS   | `ls /dev/tty.usb*`               | `/dev/tty.usbmodem21201`    |
| Linux   | `ls /dev/ttyACM* /dev/ttyUSB*`   | `/dev/ttyACM0`              |
| Windows | Device Manager → Ports (COM & LPT) | `COM3`, `COM7`, etc.      |

On Linux you may need to add yourself to the `dialout` group:

```bash
sudo usermod -aG dialout $USER
# then log out and back in
```

---

## 4. Run a visualiser

```bash
# macOS / Linux
python plot_sensor_shield.py --port /dev/tty.usbmodem21201

# Windows
python plot_sensor_shield.py --port COM3
```

All scripts accept `--port` and `--baud` (default 115200).

---

## 5. Platform notes

### matplotlib backend

On **macOS**, scripts use the `MacOSX` backend automatically.
On **Windows** and **Linux**, they fall back to `TkAgg`.

If you see `UserWarning: cannot load backend 'MacOSX'` on Linux/Windows — this is expected and handled automatically. If you see a blank window or an error about Tk, install Tkinter:

```bash
# Ubuntu / Debian
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter
```

### pygame (piezo sounds)

If you don't need drum sounds, `pygame` is optional. The `plot_piezo.py` script will run without it (sounds silently disabled). To skip:

```bash
pip install pyserial matplotlib numpy flask
```

### Windows COM port permissions

No special permissions needed on Windows — just ensure the Arduino IDE serial monitor is **closed** before running a Python script (only one process can open a COM port at a time).

### Leonardo on Windows

The Arduino Leonardo uses a composite USB device. Windows 10/11 includes the CDC driver automatically. On Windows 7, you may need to install the driver from the Arduino IDE installation.

---

## 6. All scripts at a glance

| Script | Sensor | Board |
|--------|--------|-------|
| `plot_sensor_shield.py` | Full sensor shield | Uno |
| `plot_sensor_shield_flask.py` | Same, browser view | Uno |
| `plot_sensor_shield_weight.py` | Foil vs strain XY | Uno |
| `plot_sensor_shield_angle.py` | Pot vs Hall angle XY | Uno |
| `plot_bldc_gimbal.py` | BLDC FOC gimbal | Uno |
| `plot_biosensors.py` | GSR + heart rate | Uno |
| `plot_wind_speed.py` | Anemometer | Uno |
| `plot_piezo.py` | Piezo drum pads | Leonardo |
| `plot_dc_motor.py` | DC motor PID | Uno |
| `plot_qtr8.py` | QTR-8RC reflectance | Duemilanove |
| `plot_us_distance.py` | HC-SR04 ultrasonic | Uno |
| `plot_lvdt.py` | LVDT position | Uno |
| `plot_synchro.py` | 3-phase synchro | Uno |
| `plot_dual_motor.py` | Dual motor haptic | Uno |

---

## 7. Updating dependencies

```bash
pip install -r requirements.txt --upgrade
```