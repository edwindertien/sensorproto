#!/usr/bin/env python3
"""
UniProto launcher (web) — pick a serial port once, click a setup, its reader starts.

  python launcher.py                  start the launcher and open http://127.0.0.1:5050
  python launcher.py --port COM3      ...with a port preselected
  python launcher.py --flask-port N   serve on another port (default 5050)
  python launcher.py --no-browser     do not open the browser automatically
  python launcher.py --check          list which reader scripts / icons exist, and exit
  python launcher.py --list-ports     list serial ports, and exit

What a click does:
  * starts  <python> readers/<script> --port <port in the box>  as its own process
    (same Python / venv as the launcher; every reader keeps its own plot window)
  * only ONE reader may hold the serial port at a time — a second one is refused
    until the first window is closed
  * Python-only readers (lidar, kinect) start without --port
  * the row under the grid lists every reader of the selected setup; "debug" readers
    (raw probes) stay hidden until you tick "Show debug readers"
  * a reader's script may live outside readers/ (a path from readers/ or from the repo
    root, e.g. kinect/app.py); it is then started from its own folder
  * "server" readers (kinect/app.py, hokuyo/app.py) have no window to close: the launcher
    reads the web address they print, opens it, lists them under the grid and offers Stop

Close reader windows with the window's × button (not Ctrl-C): the Leonardo needs the
clean close to drop DTR, see docs/context.md.

The server only starts scripts listed in setups.py, binds to 127.0.0.1 by default and
accepts JSON posts from its own page only. Needs: flask, pyserial (requirements.txt).
No tkinter involved.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from setups import SETUPS, GROUPS, GRID_COLS, NOT_SETUPS, Reader, Setup   # noqa: E402

SETTINGS = Path.home() / ".uniproto_launcher.json"
LOG_DIR = Path(tempfile.gettempdir()) / "uniproto_launcher"
ICONS = ROOT / "docs" / "icons"
DEFAULT_FLASK_PORT = 5050            # not 5000: macOS AirPlay Receiver sits on 5000
IDLE_HELP = ("Click an icon to start its reader.  Close reader windows with the "
             "window's × button, not Ctrl-C (the Leonardo needs a clean close).")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


# ── pure helpers (no web; unit-tested) ────────────────────────────────────────
def find_ports():
    """[(device, description, likely_arduino)] — Arduino-like first."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        dev = p.device or ""
        if any(x in dev for x in ("Bluetooth", "debug-console", "wlan-debug")):
            continue
        text = f"{p.description} {p.manufacturer or ''}".lower()
        likely = (p.vid in (0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4)
                  or any(k in text for k in ("arduino", "ch340", "ftdi", "usb serial", "cp210")))
        out.append((dev, p.description or "", likely))
    # on macOS list tty.* before cu.* (what the readers have always used)
    out.sort(key=lambda t: (not t[2], "/cu." in t[0], t[0]))
    return out


def valid_port(port: str) -> bool:
    """A port string goes into argv: no spaces, never looks like an option."""
    return bool(re.fullmatch(r"[A-Za-z0-9_./:@+\\-]{1,200}", port)) and not port.startswith("-")


def script_path(reader: Reader, readers_dir: Path = HERE) -> Path:
    """readers/<script> if it exists, else <repo root>/<script> (so kinect/app.py works either way)."""
    p = (Path(readers_dir) / reader.script).resolve()
    if not p.is_file():
        alt = (Path(readers_dir).parent / reader.script).resolve()
        if alt.is_file():
            return alt
    return p


def reader_available(reader: Reader, readers_dir: Path = HERE) -> bool:
    return script_path(reader, readers_dir).is_file()


def primary_reader(setup: Setup, readers_dir: Path = HERE):
    """What a click starts: the first available non-debug reader, else the first available."""
    avail = [r for r in setup.readers if reader_available(r, readers_dir)]
    normal = [r for r in avail if not r.debug]
    return (normal or avail or [None])[0]


def build_command(reader: Reader, port: str, readers_dir: Path = HERE):
    py = sys.executable
    if reader.python:
        py = str((Path(readers_dir) / reader.python).resolve()) if not Path(reader.python).is_absolute() \
            else reader.python
    cmd = [py, str(script_path(reader, readers_dir))]
    if reader.port and port:
        cmd += ["--port", port]
    return cmd + list(reader.args)


def find_url(text: str) -> str:
    """First web address in a program's output, preferring this computer's."""
    urls = [u.rstrip(".,;)'\"") for u in re.findall(r"https?://[^\s'\"<>]+", text)]
    local = [u for u in urls if re.match(r"https?://(127\.0\.0\.1|localhost|\[::1\])", u)]
    return (local or urls or [""])[0]


def last_log_line(path: Path) -> str:
    try:
        lines = [l.strip() for l in Path(path).read_text(errors="replace").splitlines() if l.strip()]
        return lines[-1] if lines else ""
    except OSError:
        return ""


def load_settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(d):
    try:
        SETTINGS.write_text(json.dumps(d))
    except OSError:
        pass


def check_report(readers_dir: Path = HERE, icons_dir: Path = ICONS / "sm"):
    """Text table: reader scripts / icons that exist, and scripts nobody registered.
    Returns (text, n_problems)."""
    lines, missing = [f"{'setup':16s} {'reader script':40s} status", "-" * 70], 0
    referenced = set()
    for s in SETUPS:
        if not s.readers:
            lines.append(f"{s.id:16s} {'(no reader)':40s} -")
        for r in s.readers:
            ok = reader_available(r, readers_dir)
            referenced.add(Path(r.script).name)
            missing += (not ok)
            tag = ("ok" if ok else "MISSING") + ("  (debug)" if r.debug else "")
            lines.append(f"{s.id:16s} {r.script:40s} {tag}")
    present = {p.name for p in Path(readers_dir).glob("*.py")}
    orphans = sorted(n for n in present - referenced - set(NOT_SETUPS) if n.startswith("plot_"))
    no_icon = [s.id for s in SETUPS if not (Path(icons_dir) / f"{s.id}.png").is_file()]
    lines += ["", f"{missing} registered reader script(s) missing",
              f"scripts in {Path(readers_dir).name}/ that are not in setups.py: {orphans if orphans else 'none'}",
              f"icons missing: {no_icon if no_icon else 'none'}"]
    return "\n".join(lines), missing + len(orphans)


# ── process bookkeeping ───────────────────────────────────────────────────────
@dataclass
class Proc:
    popen: subprocess.Popen
    setup: Setup
    reader: Reader
    port: str
    log_path: Path
    log_fh: object
    t0: float
    url: str = ""
    stopped: bool = False


class Supervisor:
    """Starts readers, notices when they end, keeps the last status message."""

    def __init__(self, readers_dir: Path):
        self.readers_dir = Path(readers_dir)
        self.procs: list[Proc] = []
        self.lock = threading.RLock()
        self.status = {"id": 0, "text": IDLE_HELP, "err": False, "log": None}
        self.on_url = None            # called once with the address a server reader prints

    def say(self, text, err=False, log=None):
        with self.lock:
            self.status = {"id": self.status["id"] + 1, "text": text, "err": err, "log": log}

    def port_holder(self):
        return next((p for p in self.procs if p.reader.port), None)

    def poll(self):
        """Reap finished readers, report them, find the address of server readers."""
        with self.lock:
            for p in [p for p in self.procs if p.popen.poll() is not None]:
                self.procs.remove(p)
                p.log_fh.close()
                rc = p.popen.returncode
                if p.stopped:
                    self.say(f"{p.reader.script} stopped.")
                elif rc == 0:
                    self.say(f"{p.reader.script} closed.")
                else:
                    tail = last_log_line(p.log_path)
                    self.say(f"{p.reader.script} exited with code {rc}: {tail}",
                             err=True, log=Path(p.reader.script).stem)
            for p in self.procs:
                if p.reader.server and not p.url and time.time() - p.t0 < 60:
                    try:
                        url = find_url(p.log_path.read_text(errors="replace"))
                    except OSError:
                        url = ""
                    if url:
                        p.url = url
                        self.say(f"{p.reader.script} is serving {url}")
                        if self.on_url:
                            try:
                                self.on_url(url)
                            except Exception:
                                pass

    def stop(self, script: str):
        """Stop a server reader (readers with a window are closed with their own × button)."""
        with self.lock:
            p = next((p for p in self.procs if p.reader.script == script and p.reader.server), None)
            if p is None:
                return False, "That reader is not a running server."
            p.stopped = True
            self._kill_tree(p.popen, signal.SIGTERM)
            threading.Timer(3.0, lambda: self._kill_tree(p.popen, getattr(signal, "SIGKILL", signal.SIGTERM))).start()
            return True, f"Stopping {script} …"

    @staticmethod
    def _kill_tree(popen, sig):
        """Servers run in their own process group so a reloading Flask app dies with its child."""
        if popen.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(popen.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.killpg(popen.pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                popen.terminate()
            except OSError:
                pass

    def launch(self, s: Setup, r: Reader, port: str):
        """Returns (ok, message); also updates self.status."""
        with self.lock:
            self.poll()
            if any(p.reader is r for p in self.procs):
                msg = f"{r.script} is already running."
                self.say(msg)
                return False, msg
            if r.port:
                if not port:
                    msg = "Select a serial port first (top left)."
                    self.say(msg, err=True)
                    return False, msg
                busy = self.port_holder()
                if busy:
                    msg = (f"{busy.reader.script} still holds {busy.port}. Close its window "
                           f"(× button) before starting {r.script}.")
                    self.say(msg, err=True)
                    return False, msg
            cmd = build_command(r, port, self.readers_dir)
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = LOG_DIR / f"{Path(r.script).stem}.log"
            fh = open(log_path, "w")
            fh.write("$ " + " ".join(cmd) + "\n")
            fh.flush()
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            env["PYTHONPATH"] = os.pathsep.join(
                [str(self.readers_dir)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
            kw = {}
            if r.server:
                if os.name == "nt":
                    kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    kw["start_new_session"] = True
            try:
                popen = subprocess.Popen(cmd, cwd=str(script_path(r, self.readers_dir).parent),
                                         stdout=fh, stderr=subprocess.STDOUT, env=env, **kw)
            except OSError as ex:
                fh.close()
                msg = f"could not start {r.script}: {ex}"
                self.say(msg, err=True)
                return False, msg
            self.procs.append(Proc(popen, s, r, port if r.port else "", log_path, fh, time.time()))
            msg = f"{r.script} started" + (f" on {port}" if r.port else "") + \
                  (".  Waiting for its web address …" if r.server else ".  Close its window (×) when done.")
            self.say(msg)
            return True, msg

    def setup_state(self, s: Setup):
        """'running' | 'ready' | 'missing' | 'info'"""
        if any(p.setup.id == s.id for p in self.procs):
            return "running"
        if not s.readers:
            return "info"
        return "ready" if primary_reader(s, self.readers_dir) else "missing"


# ── the web app ───────────────────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#F4F4F2;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#222}
.wrap{width:900px;margin:0 auto;padding:12px 12px 18px}
.top{margin-bottom:8px}.top label{font-weight:bold;font-size:14px;margin-right:8px}
#port{width:300px;padding:5px 6px;font-size:14px}
button{font-size:13px;padding:5px 12px;margin-left:6px;border:1px solid #bbb;border-radius:5px;
  background:#e9e9e6;cursor:pointer}
button:hover{background:#dcdcd8}button:disabled{color:#999;cursor:default;background:#efefed}
#portinfo{margin-left:10px;color:#666;font-size:13px}
.grid{width:876px;font-size:0}
.card{display:inline-block;vertical-align:top;width:138px;height:152px;margin:4px;padding:8px 4px 0;
  background:#fff;border:1px solid #DDDDD8;text-align:center;font-size:12px;position:relative;
  cursor:pointer;user-select:none}
.card img{width:96px;height:96px;display:block;margin:0 auto 4px}
.card .t{font-weight:bold;font-size:13px;color:#222}.card .s{color:#777;font-size:11px;margin-top:2px}
.card.info,.card.missing{cursor:default}
.card .dot{display:none;position:absolute;top:8px;right:14px;width:14px;height:14px;border-radius:7px;
  background:#2EB872;border:2px solid #fff}
.card.running .dot{display:block}
.card .badge{display:none;position:absolute;left:39px;top:79px;width:60px;padding:1px 0;background:#C0392B;
  color:#fff;font-size:10px;font-weight:bold}
.card.missing .badge{display:block}
.g0:hover,.g0.selected{border-color:#2B6CB0}.g1:hover,.g1.selected{border-color:#0F8B8D}
.g2:hover,.g2.selected{border-color:#C96F1A}.g3:hover,.g3.selected{border-color:#7A4FB5}
.card:hover{border-width:3px;padding:6px 2px 0}.card.selected{border-width:2px;padding:7px 3px 0;background:#F1F5FA}
.legend{font-size:12px;color:#555;margin:8px 0 0;overflow:hidden}
.legend i{display:inline-block;width:12px;height:12px;margin:0 4px -2px 0}
.legend span{margin-right:14px}.legend label{float:right}
#readers{margin-top:10px;min-height:30px;font-size:13px}#readers b{margin-right:6px}
#running{margin-top:6px;font-size:13px}#running div{margin:3px 0}#running a{margin:0 8px}
#running button{padding:2px 9px;margin-left:4px}
#status{margin-top:8px;font-size:13px;min-height:36px;color:#333}#status.err{color:#B03A2E}
#status a{margin-left:8px}
"""

JS = r"""
(function () {
  var $ = function (s) { return document.querySelector(s); };
  var state = null, selected = null, hover = null, lastStatusId = -1, current = null;
  var showDebug = localStorage.getItem('showDebug') === '1';
  $('#debug').checked = showDebug;

  function api(path, body) {
    var opt = body === undefined ? {} :
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
    return fetch(path, opt).then(function (r) { return r.json(); });
  }
  function setupById(id) { return state && state.setups.filter(function (s) { return s.id === id; })[0]; }

  function say(text, err, log) {
    var el = $('#status');
    el.className = err ? 'err' : '';
    el.textContent = text;
    if (log) {
      var a = document.createElement('a');
      a.href = '/log/' + log; a.target = '_blank'; a.textContent = 'show log';
      el.appendChild(a);
    }
  }
  function showCurrent() { if (current) say(current.text, current.err, current.log); }

  function visibleReaders(s) {
    var normal = s.readers.filter(function (r) { return !r.debug; });
    return (showDebug || !normal.length) ? s.readers : normal;
  }
  function info(s) {
    var names = visibleReaders(s).map(function (r) { return r.script; }).join(', ') || 'no reader';
    return s.title + ' — ' + s.tagline + '   |   board: ' + s.board + '   |   env: ' + (s.env || 'python only') +
           '   |   ' + names;
  }

  function renderReaders() {
    var box = $('#readers'); box.textContent = '';
    var s = selected && setupById(selected);
    if (!s || !s.readers.length) return;
    var b = document.createElement('b'); b.textContent = s.title + ':'; box.appendChild(b);
    visibleReaders(s).forEach(function (r) {
      var btn = document.createElement('button');
      btn.textContent = r.label + (r.debug ? ' (debug)' : '');
      btn.disabled = !r.available;
      btn.addEventListener('click', function () { launch(s.id, r.script); });
      box.appendChild(btn);
    });
  }

  function renderRunning() {
    var box = $('#running'); box.textContent = '';
    (state.running || []).forEach(function (p) {
      var row = document.createElement('div');
      row.appendChild(document.createTextNode('● ' + p.label + (p.port ? ' on ' + p.port : '') + ' — running'));
      if (p.url) {
        var a = document.createElement('a'); a.href = p.url; a.target = '_blank'; a.textContent = 'open ' + p.url;
        row.appendChild(a);
      }
      if (p.server) {
        var b = document.createElement('button'); b.textContent = 'Stop';
        b.addEventListener('click', function () {
          api('/api/stop', {script: p.script}).then(function (res) { say(res.message, !res.ok); refresh(); });
        });
        row.appendChild(b);
      }
      box.appendChild(row);
    });
  }

  function paint() {
    state.setups.forEach(function (s) {
      var el = document.getElementById('card-' + s.id);
      el.classList.toggle('running', s.state === 'running');
      el.classList.toggle('missing', s.state === 'missing');
      el.classList.toggle('info', s.state === 'info');
      el.classList.toggle('selected', s.id === selected);
    });
    var key = state.ports.map(function (p) { return p.device; }).join('|');
    if (key !== paint.key) {                       // only touch the list when it changed
      paint.key = key;
      var dl = $('#portlist'); dl.textContent = '';
      state.ports.forEach(function (p) {
        var o = document.createElement('option'); o.value = p.device; o.label = p.description; dl.appendChild(o);
      });
    }
    var cur = $('#port').value.trim();
    var m = state.ports.filter(function (p) { return p.device === cur; })[0];
    $('#portinfo').textContent = m ? m.description : (cur ? '(not in port list)' : '');
    if (state.status.id !== lastStatusId) {
      lastStatusId = state.status.id; current = state.status;
      if (!hover) showCurrent();
    }
    renderReaders();
    renderRunning();
  }

  function refresh() {
    return api('/api/state').then(function (s) { state = s; paint(); }).catch(function () {
      say('Lost connection to the launcher (is it still running?)', true);
    });
  }

  function launch(setupId, script) {
    return api('/api/launch', {setup: setupId, reader: script, port: $('#port').value.trim()})
      .then(function (res) { say(res.message, !res.ok); return refresh(); });
  }

  document.querySelectorAll('.card').forEach(function (el) {
    var id = el.dataset.id;
    el.addEventListener('click', function () { selected = id; if (state) paint(); launch(id, null); });
    el.addEventListener('mouseenter', function () { hover = id; var s = setupById(id); if (s) say(info(s)); });
    el.addEventListener('mouseleave', function () { hover = null; showCurrent(); });
  });
  $('#refresh').addEventListener('click', function () {
    api('/api/state?rescan=1').then(function (s) {
      state = s; paint();
      say(s.ports.length + ' serial port(s) found.' + (s.ports.length ? '' : ' Plug in the board, then Refresh.'));
    });
  });
  $('#debug').addEventListener('change', function () {
    showDebug = this.checked; localStorage.setItem('showDebug', showDebug ? '1' : '0'); renderReaders();
  });
  $('#port').addEventListener('input', function () { if (state) paint(); });

  refresh();
  setInterval(refresh, 1000);
})();
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>UniProto launcher</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{{ css|safe }}</style></head>
<body><div class="wrap">
<div class="top"><label for="port">Serial port</label>
<input id="port" list="portlist" value="{{ default_port }}" placeholder="/dev/tty.usbmodem…  or  COM3"
 autocomplete="off" spellcheck="false"><datalist id="portlist"></datalist>
<button id="refresh">Refresh</button><span id="portinfo"></span></div>
<div class="grid">
{% for s in setups %}<div class="card g{{ s.group }}" id="card-{{ s.id }}" data-id="{{ s.id }}"><img src="/icons/{{ s.id }}.png" alt=""><div class="t">{{ s.title }}</div><div class="s">{{ s.tagline }}</div><span class="dot"></span><span class="badge">no script</span></div>
{% endfor %}</div>
<div class="legend">{% for name, color in groups %}<span><i style="background:{{ color }}"></i>{{ name }}</span>{% endfor %}
<label><input type="checkbox" id="debug"> Show debug readers</label></div>
<div id="readers"></div>
<div id="running"></div>
<div id="status">{{ idle }}</div>
</div><script>{{ js|safe }}</script></body></html>
"""


def create_app(readers_dir=HERE, icons_dir=ICONS, default_port="", strict_host=True, open_browser=False):
    try:
        from flask import Flask, Response, abort, jsonify, render_template_string, request, send_file
    except ImportError:
        sys.exit("Flask is not installed. Run:  pip install -r requirements.txt")

    readers_dir, icons_dir = Path(readers_dir), Path(icons_dir)
    app = Flask(__name__)
    sup = Supervisor(readers_dir)
    app.sup = sup
    if open_browser:
        sup.on_url = webbrowser.open
    by_id = {s.id: s for s in SETUPS}
    cache = {"t": 0.0, "ports": []}

    def ports(force=False):
        if force or time.time() - cache["t"] > 3.0:
            cache["ports"], cache["t"] = find_ports(), time.time()
        return cache["ports"]

    def choose_default():
        if default_port:
            return default_port
        pl = ports()
        saved = load_settings().get("port", "")
        if any(d == saved for d, _, _ in pl):
            return saved
        likely = [d for d, _, lk in pl if lk]
        return likely[0] if likely else (pl[0][0] if pl else "")

    def watcher():
        while True:
            time.sleep(0.5)
            try:
                sup.poll()
            except Exception:
                pass
    threading.Thread(target=watcher, daemon=True).start()

    @app.before_request
    def guard():
        # only answer to loopback host names (DNS-rebinding guard) unless the user bound it elsewhere
        if strict_host:
            host = urlsplit("//" + request.host).hostname
            if host not in LOOPBACK:
                abort(403)
        if request.method == "POST" and not request.is_json:
            abort(415)           # a cross-site form post cannot send JSON without a CORS preflight

    @app.get("/")
    def index():
        return render_template_string(PAGE, css=CSS, js=JS, setups=SETUPS, groups=GROUPS,
                                      default_port=choose_default(), idle=IDLE_HELP)

    @app.get("/icons/<sid>.png")
    def icon(sid):
        if sid not in by_id:
            abort(404)
        for d in (icons_dir, icons_dir / "sm"):
            f = d / f"{sid}.png"
            if f.is_file():
                return send_file(f, mimetype="image/png")
        color = GROUPS[by_id[sid].group][1]
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="96" height="96" '
               f'rx="16" fill="{color}"/><text x="48" y="54" fill="#fff" font-size="12" font-family="sans-serif" '
               f'text-anchor="middle">{sid}</text></svg>')
        return Response(svg, mimetype="image/svg+xml")

    @app.get("/api/state")
    def api_state():
        sup.poll()
        pl = ports(force=bool(request.args.get("rescan")))
        out = []
        with sup.lock:
            for s in SETUPS:
                out.append({
                    "id": s.id, "title": s.title, "tagline": s.tagline, "board": s.board, "env": s.env,
                    "group": s.group, "state": sup.setup_state(s), "note": s.note,
                    "readers": [{"script": r.script, "label": r.label, "debug": r.debug,
                                 "available": reader_available(r, readers_dir)} for r in s.readers]})
            running = [{"script": p.reader.script, "label": p.reader.label, "port": p.port, "pid": p.popen.pid,
                        "secs": int(time.time() - p.t0), "server": p.reader.server, "url": p.url}
                       for p in sup.procs]
            status = dict(sup.status)
        return jsonify(ports=[{"device": d, "description": desc, "likely": lk} for d, desc, lk in pl],
                       setups=out, running=running, status=status)

    @app.post("/api/launch")
    def api_launch():
        data = request.get_json(silent=True) or {}
        s = by_id.get(data.get("setup"))
        if s is None:
            return jsonify(ok=False, message="unknown setup"), 400
        port = str(data.get("port") or "").strip()
        if port and not valid_port(port):
            return jsonify(ok=False, message="that does not look like a serial port name"), 400
        if not s.readers:
            msg = s.note or "This setup has no Python reader."
            sup.say(msg)
            return jsonify(ok=False, message=msg)
        want = data.get("reader")
        if want:
            r = next((x for x in s.readers if x.script == want), None)
            if r is None:
                return jsonify(ok=False, message="unknown reader for this setup"), 400
            if not reader_available(r, readers_dir):
                msg = f"{r.script} not found in {readers_dir}. Add the script or fix the name in readers/setups.py."
                sup.say(msg, err=True)
                return jsonify(ok=False, message=msg)
        else:
            r = primary_reader(s, readers_dir)
            if r is None:
                msg = (f"{s.readers[0].script} not found in {readers_dir}. "
                       f"Add the script or fix the name in readers/setups.py.")
                sup.say(msg, err=True)
                return jsonify(ok=False, message=msg)
        ok, msg = sup.launch(s, r, port)
        if ok and r.port and port:
            save_settings({"port": port})
        return jsonify(ok=ok, message=msg)

    @app.post("/api/stop")
    def api_stop():
        data = request.get_json(silent=True) or {}
        ok, msg = sup.stop(str(data.get("script") or ""))
        if ok:
            sup.say(msg)
        return jsonify(ok=ok, message=msg)

    @app.get("/log/<stem>")
    def log(stem):
        stems = {Path(r.script).stem for s in SETUPS for r in s.readers}
        if stem not in stems:
            abort(404)
        f = LOG_DIR / f"{stem}.log"
        text = f.read_text(errors="replace") if f.is_file() else "(no log yet)"
        return Response("\n".join(text.splitlines()[-200:]) + "\n", mimetype="text/plain; charset=utf-8")

    return app


def main():
    ap = argparse.ArgumentParser(description="UniProto launcher (web)")
    ap.add_argument("--port", default="", help="preselect a serial port")
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    ap.add_argument("--flask-port", type=int, default=DEFAULT_FLASK_PORT, help="web port (default 5050)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    ap.add_argument("--check", action="store_true", help="list reader scripts / icons and exit")
    ap.add_argument("--list-ports", action="store_true", help="list serial ports and exit")
    args = ap.parse_args()

    if args.list_ports:
        for dev, desc, likely in find_ports():
            print(f"{dev:36s} {'*' if likely else ' '} {desc}")
        return
    if args.check:
        text, _ = check_report()
        print(text)
        return

    strict = args.host in ("127.0.0.1", "localhost", "::1")
    if not strict:
        print(f"WARNING: listening on {args.host} — anyone who can reach this address can start "
              f"readers on this computer.", flush=True)
    app = create_app(default_port=args.port, strict_host=strict, open_browser=not args.no_browser)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.flask_port}"
    print(f"UniProto launcher: {url}   (Ctrl-C to stop; readers keep running)", flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        app.run(host=args.host, port=args.flask_port, threaded=True, use_reloader=False)
    except OSError as ex:
        sys.exit(f"Could not listen on port {args.flask_port}: {ex}\n"
                 f"Try:  python launcher.py --flask-port {args.flask_port + 1}")


if __name__ == "__main__":
    main()