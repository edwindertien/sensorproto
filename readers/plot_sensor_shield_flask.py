#!/usr/bin/env python3
"""
Sensor Shield — browser visualiser using Flask + Server-Sent Events.

Opens at http://localhost:5000  — live updating charts in any browser.
No matplotlib, no macOS backend needed.
Charts rendered with Chart.js (loaded from CDN).

Usage:
  pip install flask pyserial
  python plot_sensor_shield_flask.py --port /dev/tty.usbmodemXXXX
  then open http://localhost:5000 in your browser
"""
import argparse
import json
import threading
import time
from collections import deque

import serial
from flask import Flask, Response, render_template_string

# ── shared state (thread-safe deques) ─────────────────────────────────────────
N = 100
state = {k: deque([0.0]*N, maxlen=N) for k in [
    "A0","A1","A2","A3","A4","A5",
    "foil","strain","hall",
    "enc_pos","enc_vel",
    "capA","capB","cap_pos",
    "rc","rc_ref","us",
]}
last = {k: 0.0 for k in state}
status_str = ["connecting..."]

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Sensor Shield</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body { font-family: system-ui, sans-serif; background:#f4f6f9; margin:0; padding:12px; }
  h1   { font-size:18px; color:#333; margin:0 0 10px; }
  #status { font-size:11px; font-family:monospace; color:#666;
            background:#eee; padding:4px 8px; border-radius:4px; margin-bottom:10px; }
  .grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
  .card { background:white; border-radius:8px; padding:10px;
          box-shadow:0 1px 4px rgba(0,0,0,.08); }
  .card h3 { font-size:11px; color:#555; margin:0 0 6px; font-weight:600; }
  canvas   { width:100% !important; height:120px !important; }
  .val     { font-size:20px; font-weight:bold; color:#2d7dd2;
             text-align:center; padding:4px 0; }
  .unit    { font-size:11px; color:#999; text-align:center; }
</style>
</head>
<body>
<h1>Sensor Shield — Live Monitor</h1>
<div id="status">connecting...</div>
<div class="grid" id="grid"></div>

<script>
const N = 100;
const labels = Array.from({length:N},(_,i)=>i-N);

const SENSORS = [
  {id:"A0",    title:"A0 Potentiometer", unit:"raw",  color:"#2d7dd2", min:0, max:1023},
  {id:"A1",    title:"A1 External J1",  unit:"raw",  color:"#3bb273", min:0, max:1023},
  {id:"A2",    title:"A2 Foil (raw)",   unit:"raw",  color:"#e84855", min:0, max:1023},
  {id:"A3",    title:"A3 Strain (raw)", unit:"raw",  color:"#f18f01", min:0, max:1023},
  {id:"A4",    title:"A4 Hall A",       unit:"raw",  color:"#7b2d8b", min:0, max:1023},
  {id:"A5",    title:"A5 Hall B",       unit:"raw",  color:"#8a8fa8", min:0, max:1023},
  {id:"foil",  title:"Foil Pressure",   unit:"g",    color:"#e84855"},
  {id:"strain",title:"Strain Gauge",    unit:"g",    color:"#f18f01"},
  {id:"hall",  title:"Hall Angle",      unit:"°",    color:"#7b2d8b"},
  {id:"enc_pos",title:"Encoder Pos",    unit:"cnt",  color:"#2d7dd2"},
  {id:"enc_vel",title:"Encoder Vel",    unit:"c/s",  color:"#3bb273"},
  {id:"capA",  title:"Cap Slider A",    unit:"raw",  color:"#e84855"},
  {id:"capB",  title:"Cap Slider B",    unit:"raw",  color:"#f18f01"},
  {id:"cap_pos",title:"Cap Position",   unit:"mm",   color:"#7b2d8b", min:0, max:50},
  {id:"rc",    title:"RC-ADC Count",    unit:"cnt",  color:"#2d7dd2"},
  {id:"rc_ref",title:"RC Reference",    unit:"V",    color:"#3bb273", min:0, max:3.3},
  {id:"us",    title:"Ultrasonic",      unit:"cm",   color:"#e84855"},
];

const charts = {};
const grid = document.getElementById('grid');

SENSORS.forEach(s => {
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `<h3>${s.title}</h3>
    <div class="val" id="val_${s.id}">--</div>
    <div class="unit">${s.unit}</div>
    <canvas id="c_${s.id}"></canvas>`;
  grid.appendChild(card);

  const ctx = document.getElementById('c_'+s.id).getContext('2d');
  charts[s.id] = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets:[{
        data: Array(N).fill(0),
        borderColor: s.color,
        borderWidth: 1.2,
        pointRadius: 0,
        tension: 0.2,
      }]
    },
    options: {
      animation: false,
      plugins: { legend:{display:false} },
      scales: {
        x: { display:false },
        y: {
          min: s.min !== undefined ? s.min : undefined,
          max: s.max !== undefined ? s.max : undefined,
          ticks: { font:{size:9}, maxTicksLimit:4 },
          grid: { color:'rgba(0,0,0,.05)' }
        }
      }
    }
  });
});

// ── SSE updates ───────────────────────────────────────────────────────────────
const evtSrc = new EventSource('/stream');
evtSrc.onmessage = e => {
  const d = JSON.parse(e.data);
  if (d.status) document.getElementById('status').textContent = d.status;
  if (d.values) {
    Object.entries(d.values).forEach(([k,v]) => {
      if (!charts[k]) return;
      const ds = charts[k].data.datasets[0];
      ds.data.push(v);
      if (ds.data.length > N) ds.data.shift();
      charts[k].update('none');
      const el = document.getElementById('val_'+k);
      if (el) el.textContent = typeof v === 'number' ? v.toFixed(1) : v;
    });
  }
};
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/stream")
def stream():
    def generate():
        prev = {k: None for k in state}
        while True:
            changed = {}
            for k in state:
                v = list(state[k])[-1]
                if v != prev[k]:
                    changed[k] = round(float(v), 2)
                    prev[k] = v
            if changed:
                data = json.dumps({"values": changed, "status": status_str[0]})
                yield f"data: {data}\n\n"
            time.sleep(0.05)
    return Response(generate(), mimetype="text/event-stream")

# ── serial reader thread ───────────────────────────────────────────────────────

def serial_reader(port, baud):
    def write_cmd(ser, s):
        ser.write((s.strip() + "\n").encode("ascii", errors="ignore"))
        ser.flush()
        time.sleep(0.15)
        while ser.in_waiting: ser.readline()

    ser = serial.Serial(port, baud, timeout=0.0)
    time.sleep(2.0); ser.reset_input_buffer()
    write_cmd(ser, "!format:csv")
    write_cmd(ser, "!timestamp:0")
    write_cmd(ser, "!rate:10")
    for i in range(1, 8): write_cmd(ser, f"!stream:+{i}")
    ser.reset_input_buffer()
    status_str[0] = f"streaming from {port}"
    print(f"[INFO] Streaming from {port}")

    rxbuf = b""
    try:
        while True:
            waiting = ser.in_waiting
            if waiting: rxbuf += ser.read(waiting)
            while b"\n" in rxbuf:
                line_b, rxbuf = rxbuf.split(b"\n", 1)
                line = line_b.decode("utf-8", errors="ignore").strip()
                if not line: continue
                parts = [p.strip() for p in line.split(",")]
                try:
                    vals = [float(p) for p in parts]
                except ValueError:
                    continue
                if len(vals) < 2: continue
                try:
                    sid  = int(vals[0])
                    rest = vals[1:]
                except (ValueError, IndexError):
                    continue
                if   sid == 1 and len(rest) == 6:
                    for i,k in enumerate(["A0","A1","A2","A3","A4","A5"]):
                        state[k].append(rest[i])
                elif sid == 2 and len(rest) == 2:
                    state["foil"].append(rest[0]); state["strain"].append(rest[1])
                elif sid == 3 and len(rest) == 1:
                    state["hall"].append(rest[0])
                elif sid == 4 and len(rest) == 2:
                    state["enc_pos"].append(rest[0]); state["enc_vel"].append(rest[1])
                elif sid == 5 and len(rest) == 3:
                    state["capA"].append(rest[0]); state["capB"].append(rest[1])
                    state["cap_pos"].append(max(-1.0, rest[2]))
                elif sid == 6 and len(rest) == 2:
                    state["rc"].append(rest[0]); state["rc_ref"].append(rest[1])
                elif sid == 7 and len(rest) == 1:
                    state["us"].append(rest[0])
                status_str[0] = (
                    f"A0={state['A0'][-1]:.0f} foil={state['foil'][-1]:.0f}g "
                    f"hall={state['hall'][-1]:.1f}° enc={state['enc_pos'][-1]:.0f} "
                    f"cap={state['cap_pos'][-1]:.1f}mm us={state['us'][-1]:.1f}cm"
                )
            time.sleep(0.002)
    except Exception as e:
        status_str[0] = f"ERROR: {e}"
    finally:
        ser.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--flask-port", type=int, default=5000)
    args = ap.parse_args()

    t = threading.Thread(target=serial_reader, args=(args.port, args.baud), daemon=True)
    t.start()

    print(f"[INFO] Open http://{args.host}:{args.flask_port} in your browser")
    app.run(host=args.host, port=args.flask_port, debug=False)