# Hokuyo URG-04LX-UG01 live visualiser

Standalone Flask + SSE dashboard for the Hokuyo scanning rangefinder.
Not wired into the UniProto Arduino stream — this talks straight to the
sensor over its own USB serial port.

## Setup (macOS)

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

Try it without hardware first:

```
python app.py --simulate
```

Open http://127.0.0.1:5001 — you should see a synthetic scan sweeping and
breathing so you can check the layout and HUD before touching the sensor.

With the sensor plugged in, find its port:

```
ls /dev/tty.usbmodem*
```

then:

```
python app.py --port /dev/tty.usbmodem1234
```

## Files

- `hokuyo_driver.py` — SCIP 2.0 protocol driver (serial I/O, GD/MD commands,
  distance decoding). No hardware to test against here, so **the first
  live run should be sanity-checked**: point the sensor at a wall you've
  measured by hand and confirm the "nearest point" reading on the
  dashboard agrees before trusting anything further downstream.
- `app.py` — background reader thread + Flask routes (`/` for the page,
  `/stream` for the SSE scan feed).
- `templates/index.html` — canvas polar plot, HUD (nearest point, scan
  rate, point count), all client-side JS, no build step.

## Notes

- Default serial settings: 115200 baud, matching the sensor's USB-CDC
  default. If `HokuyoURG(...)` raises on connect, check the port path
  is right and that nothing else (e.g. a leftover `screen` session) has
  it open.
- The scan uses cluster_count=0 (full resolution, no on-sensor
  averaging) across the full 682-point, 240 degree sweep (steps 44–725).
- If the plotted shape looks mirrored versus the room, flip the sign in
  `polarToXY()` in `index.html` — that's a display convention, not a
  data problem.
- If a previous run was stopped uncleanly (Ctrl+C without it shutting
  down, a crash), the sensor can be left mid continuous-scan and won't
  respond correctly to a fresh connect. Unplugging and replugging the
  sensor resets it and clears this.