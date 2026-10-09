#!/usr/bin/env python3
"""
UniProto dashboard — one web page for ANY UniProto sketch. Prototype.

  python dashboard.py --port /dev/tty.usbmodem21201      connect, then open http://127.0.0.1:5000
  python dashboard.py                                    start, pick the port in the page
  python dashboard.py --port P --stream 1 --rate 50      ...and start streaming stream 1 at 50 Hz
  http://127.0.0.1:5000/?layout=one&window=5             page options: layout=one|stack, window=2|5|10|30|60, view=time|row, skip=N
  python dashboard.py --flask-port 5001 --no-browser     other web port, don't open a tab
  python dashboard.py --list-ports

No hardware?   python dashboard/uniproto_sim.py     (prints a port to pass as --port)

What it does
  * owns the serial port (Leonardo-safe: DTR low -> high on open, dropped again on close)
  * asks the sketch what it has ('?'): streams, parameters, actions
  * you pick ONE stream; it is charted live — one chart per field, or all in one chart,
    with a time window, pause, and peak-preserving drawing (spikes are never dropped)
  * parameters become inputs (current values are read back from the board), actions become
    buttons, and there is a console / command box like a serial monitor
  * "Save CSV" downloads what you see; "Rec" streams every row to recordings/*.csv

Why one stream at a time: CSV lines carry no stream id, so two enabled streams of
different widths cannot be told apart reliably. The page switches streams for you.

Field names come from the sketch's `units` string when it has exactly one unique name per
field (e.g. "pos,set,cmd,err,vel"); otherwise the fields are called f0, f1, ...  A field
called "sid" (an explicit stream-id column) starts hidden.

No external libraries (works offline): the charts are drawn on a plain canvas.
Needs: flask, pyserial (dashboard/requirements.txt). Listens on this computer only unless you
pass --host; anyone who can reach it can drive the connected hardware.
"""
import argparse
import csv
import json
import math
import os
import queue
import re
import signal
import sys
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime
from itertools import islice
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEB_PORT = 5000
# Ports that browsers refuse to connect to (ERR_UNSAFE_PORT) — 5060/5061 are the SIP phone ports.
UNSAFE_BROWSER_PORTS = {2049, 3659, 4045, 5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
CORE_PARAMS = ("rate", "format", "timestamp", "stream")      # managed by the dashboard itself
BUF_ROWS = 20000                                              # samples kept server side
MAX_ROWS_PER_POLL = 3000

_TOKEN = re.compile(r"^[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?|nan|inf|ovf)$", re.I)
_REPLY = re.compile(r"^([A-Za-z_][\w.\-]*):(.*)$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


# ── pure helpers (unit-tested) ────────────────────────────────────────────────
def classify(line: str):
    """-> (kind, payload): data|caps|reply|ok|err|text"""
    s = line.strip()
    if not s:
        return "text", ""
    if s[0] == "{":
        try:
            return "caps", json.loads(s)
        except ValueError:
            return "text", s
    if s == "OK":
        return "ok", s
    if s.startswith("ERR"):
        return "err", s
    toks = [t.strip() for t in s.split(",")]
    if all(_TOKEN.match(t) for t in toks):
        vals = []
        for t in toks:
            tl = t.lower()
            vals.append(float("nan") if tl in ("ovf", "nan") else float(t))
        return "data", vals
    m = _REPLY.match(s)
    if m:
        return "reply", (m.group(1), m.group(2).strip())
    return "text", s


def label_fields(units: str, n: int):
    """[{'name', 'hidden'}] for n fields. Names come from `units` only if unambiguous."""
    names = [u.strip() for u in (units or "").split(",")] if units else []
    if len(names) == n and all(names) and len(set(names)) == n:
        pass
    else:
        names = [f"f{i}" for i in range(n)]
    return [{"name": nm, "hidden": nm.lower() == "sid"} for nm in names]


def infer_param(key: str, value):
    """Guess an input type from the value the board reports."""
    if value is None:
        return "text"
    v = str(value).strip()
    if v in ("0", "1") and re.search(r"(enable|enabled|active|on|invert|inverted|flag)$", key, re.I):
        return "bool"
    if re.fullmatch(r"[-+]?\d+", v):
        return "int"
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", v):
        return "float"
    return "text"


def clean(x):
    """JSON has no NaN/Infinity."""
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


def valid_command(line: str) -> bool:
    return bool(line) and len(line) <= 63 and line[0] in "!?@" and not _CTRL.search(line)


def valid_value(v: str) -> bool:
    return len(v) <= 40 and not _CTRL.search(v)


def list_ports():
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return []
    out = []
    for p in lp.comports():
        dev = p.device or ""
        if any(x in dev for x in ("Bluetooth", "debug-console", "wlan-debug")):
            continue
        text = f"{p.description} {p.manufacturer or ''}".lower()
        likely = (p.vid in (0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4)
                  or any(k in text for k in ("arduino", "ch340", "ftdi", "usb serial", "cp210")))
        out.append({"device": dev, "description": p.description or "", "likely": likely})
    out.sort(key=lambda d: (not d["likely"], "/cu." in d["device"], d["device"]))
    return out


# ── the device ────────────────────────────────────────────────────────────────
class Device:
    """Owns the serial port: a reader thread classifies every line, commands are serialised."""

    def __init__(self, record_dir, boot_wait=2.0, caps_attempts=4):
        self.record_dir = Path(record_dir)
        self.boot_wait = boot_wait
        self.caps_attempts = caps_attempts     # tries at the '?' handshake (boards may still be booting)
        self.lock = threading.RLock()          # state + buffers (never held while waiting for a reply)
        self.cmd_lock = threading.Lock()       # one command/reply exchange at a time
        self.replies = queue.Queue()
        self.ser = None
        self.thread = None
        self._stop = threading.Event()
        self.state, self.error, self.port, self.baud = "disconnected", "", "", 115200
        self.caps, self.cv = None, 0
        self.params = {}                       # name -> value string (None = unreadable)
        self._reset_stream_state()
        self.console, self.cseq = deque(maxlen=500), 0
        self.rows, self.seq, self.epoch = deque(maxlen=BUF_ROWS), 0, 0
        self.rate, self.ts_dev = None, False
        self.rec = {"fh": None, "wr": None, "path": "", "rows": 0}
        self.t0 = time.time()
        self.boot = int(self.t0 * 1000)        # identifies this server instance to open pages

    # -- internals --
    def _reset_stream_state(self):
        self.stream, self.stream_name = None, ""
        self.units = ""
        self.fields, self.n_cols = [], None
        self._pending = []
        self._switch = None                    # ("stream", id) / ("rate", n) awaiting the device's OK
        self.bad = 0

    def _log(self, mark, text):
        with self.lock:
            self.cseq += 1
            self.console.append((self.cseq, f"{mark} {text}"))

    def _write(self, cmd):
        ser = self.ser
        if ser is None:
            raise OSError("not connected")
        self._log(">", cmd)
        ser.write((cmd + "\n").encode("ascii", "replace"))
        ser.flush()

    def _xchg(self, cmd, want, timeout=1.5, key=None):
        """Send cmd, wait for the matching reply. want: caps | ok | reply | any. -> (kind, payload) | None"""
        with self.cmd_lock:
            while True:
                try:
                    self.replies.get_nowait()
                except queue.Empty:
                    break
            try:
                self._write(cmd)
            except (OSError, ValueError) as ex:
                self._lost(str(ex))
                return None
            end = time.time() + timeout
            while True:
                left = end - time.time()
                if left <= 0:
                    return None
                try:
                    kind, payload = self.replies.get(timeout=left)
                except queue.Empty:
                    return None
                if want == "any":
                    return kind, payload
                if want == "caps" and kind == "caps":
                    return kind, payload
                if want == "ok" and kind in ("ok", "err"):
                    return kind, payload
                if want == "reply" and kind == "err":
                    return kind, payload
                if want == "reply" and kind == "reply" and (key is None or payload[0] == key):
                    return kind, payload

    # -- reader thread --
    def _reader(self, ser):
        buf = b""
        while not self._stop.is_set():
            try:
                data = ser.read(ser.in_waiting or 1)
            except Exception as ex:
                if not self._stop.is_set():
                    self._lost(f"{type(ex).__name__}: {ex}")
                return
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self._handle(raw.decode("utf-8", "replace").strip("\r \t"))
            if len(buf) > 65536:
                buf = buf[-1024:]

    def _handle(self, line):
        kind, payload = classify(line)
        if kind == "data":
            self._on_data(payload)
            return
        if kind == "caps":
            self._log("<", "(capabilities received)")
            self.replies.put((kind, payload))
            return
        if kind == "text" and not payload:
            return
        self._log("<", line)
        if kind in ("ok", "err"):
            with self.lock:                    # apply a pending stream/rate change at the OK itself:
                sw, self._switch = self._switch, None   # everything after it belongs to the new state
                if sw and kind == "ok":
                    if sw[0] == "stream":
                        self._apply_stream(sw[1])
                    elif sw[0] == "rate":
                        self.rate = sw[1]
        if kind in ("ok", "err", "reply"):
            self.replies.put((kind, payload))

    def _apply_stream(self, sid):
        """Called under self.lock, from the reader thread, right after the device's OK."""
        self.epoch += 1
        self.rows.clear()
        self._pending, self.n_cols, self.fields, self.bad = [], None, [], 0
        self._close_record()
        if sid:
            s = next((x for x in (self.caps or {}).get("streams", []) if x.get("id") == sid), None)
            self.stream, self.stream_name = sid, (s or {}).get("name", "")
            self.units = (s or {}).get("units", "")
        else:
            self.stream, self.stream_name, self.units = None, "", ""

    def _on_data(self, vals):
        with self.lock:
            if self.stream is None:
                return                          # stray line (stream just stopped): ignore
            if self.n_cols is None:
                self._pending.append(vals)
                last = self._pending[-3:]
                if len(last) == 3 and len({len(v) for v in last}) == 1:
                    n = len(last[0])
                    k = n - 1 if self.ts_dev else n
                    if k < 1:
                        self._pending = []
                        return
                    self.n_cols = n
                    self.fields = label_fields(self.units, k)
                    for v in [v for v in self._pending if len(v) == n]:
                        self._store(v)
                    self._pending = []
                elif len(self._pending) > 12:
                    self._pending = self._pending[-6:]
                return
            if len(vals) != self.n_cols:
                self.bad += 1
                return
            self._store(vals)

    def _store(self, vals):
        if self.ts_dev:
            t, v = vals[0], vals[1:]
        else:
            t, v = time.time() - self.t0, vals
        self.seq += 1
        self.rows.append((self.seq, t, v))
        if self.rec["wr"]:
            try:
                self.rec["wr"].writerow([f"{t:.4f}"] + [("" if not math.isfinite(x) else x) for x in v])
                self.rec["rows"] += 1
                if self.rec["rows"] % 50 == 0:
                    self.rec["fh"].flush()
            except (OSError, ValueError):
                self._close_record()

    # -- connection --
    def connect(self, port, baud=115200, stream=None, rate=None):
        with self.lock:
            if self.state in ("connecting", "connected"):
                return False, "Already connected — disconnect first."
            self.state, self.error, self.port, self.baud = "connecting", "", port, baud
            self.caps = None
            self.cv += 1
            self.params = {}
            self._reset_stream_state()
            self.epoch += 1
            self.rows.clear()
        threading.Thread(target=self._connect_worker, args=(port, baud, stream, rate), daemon=True).start()
        return True, "Connecting …"

    def _fail(self, msg):
        with self.lock:
            self.state, self.error = "error", msg
        self._close_port()

    def _connect_worker(self, port, baud, stream=None, rate=None):
        try:
            import serial
        except ImportError:
            return self._fail("pyserial is not installed (pip install -r requirements.txt)")
        try:
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout, ser.write_timeout = port, baud, 0.05, 1.0
            ser.dtr, ser.rts = False, False       # Leonardo: low first ...
            ser.open()
        except Exception as ex:
            hint = " The port is probably in use — close other readers / serial monitors." \
                if "busy" in str(ex).lower() or "denied" in str(ex).lower() or "Errno 16" in str(ex) else ""
            return self._fail(f"Could not open {port}: {ex}.{hint}")
        time.sleep(0.3)
        try:
            ser.dtr, ser.rts = True, True          # ... then high: the edge `while(!Serial)` waits for
        except Exception:
            pass                                   # pseudo-terminals / some adapters refuse; harmless
        self.ser = ser
        self._stop.clear()
        self.thread = threading.Thread(target=self._reader, args=(ser,), daemon=True)
        self.thread.start()
        time.sleep(self.boot_wait)                 # Uno/Duemilanove reset on open; Leonardo starts here

        caps = None
        for _ in range(self.caps_attempts):
            if self.state != "connecting":
                return
            self._xchg("!stream:0", "ok", timeout=0.8)
            res = self._xchg("?", "caps", timeout=1.2)
            if res:
                caps = res[1]
                break
            time.sleep(0.4)
        if caps is None:
            return self._fail("The board did not answer '?'. Is this a UniProto sketch, is the baud rate right "
                              f"({baud}), and has the board finished booting?")
        res = self._xchg("!format:csv", "ok")
        if not res or res[0] != "ok":
            self._log("!", "could not set CSV format — data may not parse")
        res = self._xchg("!timestamp:1", "ok")
        ts = bool(res and res[0] == "ok")
        res = self._xchg("?rate", "reply", key="rate")
        board_rate = None                          # NOT `rate`: that is the caller's requested rate
        if res and res[0] == "reply":
            try:
                board_rate = int(res[1][1])
            except ValueError:
                pass
        values = {}
        for name in caps.get("params", []):
            if name in CORE_PARAMS:
                continue
            r = self._xchg(f"?{name}", "reply", key=name, timeout=0.8)
            values[name] = r[1][1] if r and r[0] == "reply" else None
        with self.lock:
            if self.state != "connecting":
                return
            self.caps, self.ts_dev, self.rate, self.params = caps, ts, board_rate, values
            self.cv += 1
            self.state, self.error = "connected", ""
        self._log("*", f"connected to {caps.get('device', '?')} on {port}")
        if rate:
            self.set_rate(rate)
        if stream:
            self.set_stream(stream)

    def _close_port(self):
        self._stop.set()
        ser, self.ser = self.ser, None
        if ser is not None:
            try:
                ser.dtr = False                    # next open gets a genuine low -> high edge
            except Exception:
                pass
            try:
                ser.close()
            except Exception:
                pass
        th = self.thread
        if th is not None and th is not threading.current_thread():
            th.join(timeout=1.0)
        self.thread = None

    def _lost(self, msg):
        with self.lock:
            if self.state not in ("connected", "connecting"):
                return
            self.state, self.error = "disconnected", f"Device disconnected ({msg})"
            self._reset_stream_state()
            self._close_record()
        threading.Thread(target=self._close_port, daemon=True).start()
        self._log("*", "device disconnected")

    def disconnect(self):
        with self.lock:
            was = self.state
        if was == "connected":
            try:
                self._xchg("!stream:0", "ok", timeout=0.5)
            except Exception:
                pass
        with self.lock:
            self.state, self.error = "disconnected", ""
            self._reset_stream_state()
            self._close_record()
        self._close_port()

    # -- commands from the page --
    def _need(self):
        if self.state != "connected":
            return "Not connected."
        return None

    def set_stream(self, sid):
        err = self._need()
        if err:
            return False, err
        if sid is not None:
            ids = [s.get("id") for s in (self.caps or {}).get("streams", [])]
            if sid not in ids:
                return False, f"Unknown stream {sid}."
        with self.lock:
            self._switch = ("stream", sid or 0)
        res = self._xchg(f"!stream:{sid or 0}", "ok")
        if not res or res[0] != "ok":
            with self.lock:
                self._switch = None
            return False, f"The board refused: {res[1] if res else 'no answer'}"
        return True, "Streaming stopped." if not sid else f"Streaming stream {sid}."

    def set_rate(self, n):
        err = self._need()
        if err:
            return False, err
        n = max(1, min(500, int(n)))
        with self.lock:
            self._switch = ("rate", n)
        res = self._xchg(f"!rate:{n}", "ok")
        if not res or res[0] != "ok":
            with self.lock:
                self._switch = None
            return False, f"The board refused: {res[1] if res else 'no answer'}"
        return True, f"Rate {n} Hz."

    def set_param(self, name, value):
        err = self._need()
        if err:
            return False, err
        if name not in self.params:
            return False, f"Unknown parameter {name!r}."
        if not valid_value(value):
            return False, "That value is not allowed."
        res = self._xchg(f"!{name}:{value}", "ok")
        if not res:
            return False, "No answer from the board."
        if res[0] == "err":
            return False, res[1]
        r = self._xchg(f"?{name}", "reply", key=name, timeout=0.8)
        with self.lock:
            self.params[name] = r[1][1] if r and r[0] == "reply" else value
        return True, f"{name} = {self.params[name]}"

    def refresh_params(self):
        err = self._need()
        if err:
            return False, err
        for name in list(self.params):
            r = self._xchg(f"?{name}", "reply", key=name, timeout=0.8)
            with self.lock:
                self.params[name] = r[1][1] if r and r[0] == "reply" else None
        return True, "Values refreshed."

    def action(self, name, args=""):
        err = self._need()
        if err:
            return False, err
        if name not in (self.caps or {}).get("actions", []):
            return False, f"Unknown action {name!r}."
        if args and not valid_value(args):
            return False, "Those arguments are not allowed."
        res = self._xchg(f"@{name}" + (f":{args}" if args else ""), "ok")
        if not res:
            return False, "No answer from the board."
        return res[0] == "ok", ("OK" if res[0] == "ok" else res[1])

    def command(self, line):
        err = self._need()
        if err:
            return False, err
        if not valid_command(line):
            return False, "Commands start with ! ? or @ and are at most 63 characters."
        res = self._xchg(line, "any", timeout=1.0)
        if res is None:
            return True, "(no reply)"
        kind, payload = res
        return kind != "err", (payload if isinstance(payload, str) else
                               (f"{payload[0]}:{payload[1]}" if kind == "reply" else "(capabilities)"))

    # -- recording --
    def start_record(self):
        with self.lock:
            if self.stream is None or not self.fields:
                return False, "Start a stream and wait for data first."
            if self.rec["fh"]:
                return True, self.rec["path"]
            self.record_dir.mkdir(parents=True, exist_ok=True)
            dev = re.sub(r"[^\w.-]+", "_", (self.caps or {}).get("device", "device"))
            name = re.sub(r"[^\w.-]+", "_", self.stream_name or f"stream{self.stream}")
            path = self.record_dir / f"{dev}_{name}_{datetime.now():%Y%m%d_%H%M%S}.csv"
            fh = open(path, "w", newline="")
            wr = csv.writer(fh, lineterminator="\n")        # same line endings as the Save CSV download
            wr.writerow(["t_s"] + [f["name"] for f in self.fields])
            self.rec = {"fh": fh, "wr": wr, "path": str(path), "rows": 0}
            return True, str(path)

    def _close_record(self):
        with self.lock:
            fh, self.rec = self.rec["fh"], {"fh": None, "wr": None, "path": self.rec["path"], "rows": self.rec["rows"]}
            if fh:
                try:
                    fh.close()
                except OSError:
                    pass

    def stop_record(self):
        with self.lock:
            n, path = self.rec["rows"], self.rec["path"]
            self._close_record()
        return True, f"Saved {n} rows to {path}"

    def csv_text(self):
        with self.lock:
            names = [f["name"] for f in self.fields]
            rows = list(self.rows)
        out = [",".join(["t_s"] + names)]
        for _, t, v in rows:
            out.append(",".join([f"{t:.4f}"] + ["" if not math.isfinite(x) else repr(x) for x in v]))
        return "\n".join(out) + "\n"

    # -- what the page polls --
    def snapshot(self, since, csince):
        with self.lock:
            rows, last_seq = [], since
            if self.rows:
                first = self.rows[0][0]                    # rows are contiguous: seq = first + index
                start = max(0, since + 1 - first)
                for _, t, v in islice(self.rows, start, start + MAX_ROWS_PER_POLL):
                    rows.append([clean(t)] + [clean(x) for x in v])
                if rows:
                    last_seq = first + start + len(rows) - 1
            console = [[n, t] for n, t in self.console if n > csince]
            streams = (self.caps or {}).get("streams", [])
            return {
                "boot": self.boot,
                "state": self.state, "error": self.error, "port": self.port, "baud": self.baud,
                "device": (self.caps or {}).get("device", ""),
                "cv": self.cv, "streams": streams,
                "actions": (self.caps or {}).get("actions", []),
                "params": [{"name": k, "value": v, "type": infer_param(k, v)} for k, v in self.params.items()],
                "stream": self.stream, "rate": self.rate, "ts": self.ts_dev,
                "fields": self.fields, "epoch": self.epoch, "bad": self.bad,
                "seq": last_seq, "rows": rows,
                "console": console, "cseq": self.cseq,
                "rec": {"on": bool(self.rec["fh"]), "rows": self.rec["rows"], "path": self.rec["path"]},
            }


# ── the web page ──────────────────────────────────────────────────────────────
CSS = r"""
*{box-sizing:border-box}
body{margin:0;background:#F4F4F2;font:13px/1.4 -apple-system,Helvetica,Arial,sans-serif;color:#222}
#wrap{width:1090px;margin:0 auto;padding:10px 12px 20px}
#top{height:42px;border-bottom:1px solid #d8d8d4;margin-bottom:10px}
#top h1{display:inline-block;font-size:18px;margin:6px 14px 0 0;vertical-align:top}
#pill{display:inline-block;margin-top:9px;padding:1px 9px;border-radius:10px;background:#999;color:#fff;font-size:12px}
#pill.connected{background:#2EB872}#pill.connecting{background:#E0A030}#pill.error{background:#C0392B}
#conn{float:right;margin-top:6px}#conn input{width:260px;padding:4px 6px;font-size:13px}
button{font-size:12px;padding:4px 10px;margin-left:4px;border:1px solid #bbb;border-radius:4px;background:#e9e9e6;cursor:pointer}
button:hover{background:#dcdcd8}button:disabled{color:#999;background:#efefed;cursor:default}
select,input[type=text],input[type=number]{font-size:12px;padding:3px 4px}
#banner{display:none;margin-bottom:8px;padding:7px 10px;background:#FBEAE8;border:1px solid #E5A9A3;color:#8E2B20}
#main{float:left;width:720px}#side{float:left;width:330px;margin-left:12px}
#bar{margin-bottom:8px;line-height:28px}.g{display:inline-block;white-space:nowrap;margin-right:4px}#bar label{margin:0 4px 0 10px;color:#555}#bar label:first-child{margin-left:0}
#charts{background:#fff;border:1px solid #d8d8d4;padding:4px}
.cv{display:block;width:710px}
#legend{margin-top:8px;font-size:12px}#legend div{display:inline-block;width:170px;margin:2px 4px 2px 0;white-space:nowrap}
.sw{display:inline-block;width:10px;height:10px;margin:0 4px 0 2px}.val{color:#555;margin-left:4px}
.box{background:#fff;border:1px solid #d8d8d4;margin-bottom:10px}
.box h2{margin:0;padding:5px 9px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;background:#ecece8;color:#555}
.box .in{padding:7px 9px}
#params table{width:100%;border-collapse:collapse}#params td{padding:2px 3px}#params td.n{width:130px;word-break:break-all}
#params input[type=text],#params input[type=number]{width:100px}
#acts button{margin:2px 4px 2px 0}
#console{height:150px;overflow:auto;margin:0;padding:5px 7px;background:#1f2328;color:#d6dbe0;font:11px/1.35 Menlo,Consolas,monospace;white-space:pre-wrap}
#cmd{width:240px}.hint{color:#777;font-size:11px}
"""

JS = r"""
(function () {
  'use strict';
  var COLORS = ['#2d7dd2','#e84855','#3bb273','#f18f01','#7b2d8b','#00a6a6','#c9a227','#666666','#d1495b','#66a182'];
  var $ = function (id) { return document.getElementById(id); };

  /* ---------- pure helpers (also used by the tests) ---------- */
  var UD = {};
  UD.niceTicks = function (lo, hi, n) {
    var span = hi - lo; if (!(span > 0)) return [lo];
    var raw = span / n, mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), norm = raw / mag;
    var step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    var first = Math.ceil(lo / step - 1e-9), out = [], i;
    for (i = first; i * step <= hi + step * 1e-9; i++) out.push(parseFloat((i * step).toPrecision(12)));
    return out;
  };
  UD.fmt = function (v) {
    if (v === null || v === undefined || !isFinite(v)) return '–';
    var a = Math.abs(v);
    if (a !== 0 && (a < 0.001 || a >= 100000)) return v.toExponential(2);
    var s = parseFloat(v.toPrecision(5)).toString();
    return s;
  };
  /* first index with T[i] >= t (T ascending) */
  UD.lowerBound = function (T, t) {
    var lo = 0, hi = T.length;
    while (lo < hi) { var m = (lo + hi) >> 1; if (T[m] < t) lo = m + 1; else hi = m; }
    return lo;
  };
  /* Peak-preserving reduction: at most ~2 points per pixel column, nulls stay as gaps.
     Returns {x:[...], y:[...]} where y may contain null (line break). */
  UD.decimate = function (T, Y, i0, i1, t0, t1, wpx) {
    var xs = [], ys = [], n = i1 - i0, i;
    if (n <= 2 * wpx) {
      for (i = i0; i < i1; i++) { xs.push(T[i]); ys.push(Y[i]); }
      return {x: xs, y: ys};
    }
    var span = (t1 - t0) || 1, col = -1, mn, mx, imn, imx, gap = false;
    function flush() {
      if (col < 0) return;
      if (imn === imx) { xs.push(T[imn]); ys.push(mn); }
      else if (imn < imx) { xs.push(T[imn]); ys.push(mn); xs.push(T[imx]); ys.push(mx); }
      else { xs.push(T[imx]); ys.push(mx); xs.push(T[imn]); ys.push(mn); }
    }
    for (i = i0; i < i1; i++) {
      var y = Y[i];
      if (y === null || y === undefined) {
        flush(); col = -1; if (!gap) { xs.push(T[i]); ys.push(null); gap = true; } continue;
      }
      gap = false;
      var c = Math.floor((T[i] - t0) / span * wpx);
      if (c !== col) { flush(); col = c; mn = mx = y; imn = imx = i; }
      else { if (y < mn) { mn = y; imn = i; } if (y > mx) { mx = y; imx = i; } }
    }
    flush();
    return {x: xs, y: ys};
  };
  /* The last `count` rows ending at index `end`, each as an array of the values of fields skip.. */
  UD.rowSlice = function (V, end, count, skip) {
    var rows = [], r, j;
    for (r = Math.max(0, end - count + 1); r <= end; r++) {
      var row = [];
      for (j = skip; j < V.length; j++) { var y = V[j][r]; row.push(y === undefined ? null : y); }
      rows.push(row);
    }
    return rows;
  };
  window.UD = UD;

  /* ---------- state ---------- */
  var S = null, T = [], V = [], seq = 0, epoch = -1, cseq = 0, cv = -1, fieldsKey = '', bootId = null;
  var hidden = [], paused = false, frozenT = 0, frozenIdx = 0, windowS = 10, layout = 'stack', layoutTouched = false;
  var viewMode = 'time', viewTouched = false, skipN = 0;
  var charts = [], lastT = null, bannerMsg = '';

  function api(path, body, cb) {
    var x = new XMLHttpRequest();
    x.open(body === undefined ? 'GET' : 'POST', path, true);
    if (body !== undefined) x.setRequestHeader('Content-Type', 'application/json');
    x.onreadystatechange = function () {
      if (x.readyState !== 4) return;
      var j = null; try { j = JSON.parse(x.responseText); } catch (e) {}
      if (cb) cb(x.status, j);
    };
    x.send(body === undefined ? null : JSON.stringify(body));
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e;
  }
  function clear(e) { while (e.firstChild) e.removeChild(e.firstChild); }

  function banner(msg) {
    var b = $('banner'); bannerMsg = msg;
    b.style.display = msg ? 'block' : 'none'; b.textContent = msg || '';
  }

  /* ---------- capabilities, parameters, actions ---------- */
  function buildStreams() {
    var sel = $('stream'); clear(sel);
    var o = el('option', '', '— no stream —'); o.value = ''; sel.appendChild(o);
    S.streams.forEach(function (s) {
      var op = el('option', '', s.id + ' · ' + s.name); op.value = String(s.id);
      op.title = (s.units || '') + (s.schema ? '   [' + s.schema + ']' : ''); sel.appendChild(op);
    });
  }
  function buildActions() {
    var box = $('acts'); clear(box);
    if (!S.actions.length) { box.appendChild(el('span', 'hint', 'This sketch has no actions.')); return; }
    S.actions.forEach(function (a) {
      var b = el('button', '', '@' + a);
      b.addEventListener('click', function () {
        api('/api/action', {name: a}, function (st, j) { log(j ? (j.ok ? '✓ ' : '✗ ') + j.message : 'request failed'); });
      });
      box.appendChild(b);
    });
  }
  function buildParams() {
    var box = $('params'); clear(box);
    if (!S.params.length) { box.appendChild(el('span', 'hint', 'This sketch has no parameters.')); return; }
    var tbl = el('table'); box.appendChild(tbl);
    S.params.forEach(function (p) {
      var tr = el('tr'), td = el('td', 'n', p.name); tr.appendChild(td);
      var td2 = el('td'), inp, b;
      if (p.type === 'bool') {
        inp = el('input'); inp.type = 'checkbox';
        inp.addEventListener('change', function () { sendParam(p.name, inp.checked ? '1' : '0', inp); });
      } else {
        inp = el('input'); inp.type = p.type === 'text' ? 'text' : 'number'; if (p.type !== 'text') inp.step = 'any';
        inp.addEventListener('input', function () { inp.setAttribute('data-dirty', '1'); });
        inp.addEventListener('keydown', function (e) { if (e.keyCode === 13) sendParam(p.name, inp.value, inp); });
        b = el('button', '', 'Set'); b.addEventListener('click', function () { sendParam(p.name, inp.value, inp); });
      }
      inp.setAttribute('data-param', p.name);
      td2.appendChild(inp); if (b) td2.appendChild(b); tr.appendChild(td2); tbl.appendChild(tr);
    });
  }
  function sendParam(name, value, inp) {
    api('/api/param', {name: name, value: String(value)}, function (st, j) {
      inp.removeAttribute('data-dirty');
      log(j ? (j.ok ? '✓ ' : '✗ ') + j.message : 'request failed');
    });
  }
  function updateParamValues() {
    var inputs = document.querySelectorAll('#params [data-param]'), i;
    for (i = 0; i < inputs.length; i++) {
      var inp = inputs[i], name = inp.getAttribute('data-param'), p = null, k;
      for (k = 0; k < S.params.length; k++) if (S.params[k].name === name) p = S.params[k];
      if (!p || document.activeElement === inp || inp.getAttribute('data-dirty') === '1') continue;
      if (inp.type === 'checkbox') inp.checked = p.value === '1'; else inp.value = p.value === null ? '' : p.value;
      if (p.value === null) inp.placeholder = 'unreadable';
    }
  }

  /* ---------- console ---------- */
  function log(text) {
    var c = $('console'); c.appendChild(document.createTextNode(text + '\n'));
    c.scrollTop = c.scrollHeight;
  }
  function appendConsole(lines) {
    if (!lines.length) return;
    var c = $('console'), near = c.scrollTop + c.clientHeight >= c.scrollHeight - 30, i;
    for (i = 0; i < lines.length; i++) c.appendChild(document.createTextNode(lines[i][1] + '\n'));
    while (c.childNodes.length > 400) c.removeChild(c.firstChild);
    if (near) c.scrollTop = c.scrollHeight;
  }

  /* ---------- fields, legend, chart canvases ---------- */
  function visibleIdx() { var out = [], i; for (i = 0; i < S.fields.length; i++) if (!hidden[i]) out.push(i); return out; }

  function buildFields() {
    var lg = $('legend'); clear(lg);
    S.fields.forEach(function (f, i) {
      var d = el('div'), sw = el('span', 'sw'), cb = el('input'), name = el('span', '', f.name), val = el('span', 'val', '');
      sw.style.background = COLORS[i % COLORS.length];
      cb.type = 'checkbox'; cb.checked = !hidden[i]; cb.id = 'fld' + i;
      cb.addEventListener('change', function () { hidden[i] = !cb.checked; buildCharts(); draw(); });
      val.id = 'val' + i; d.appendChild(cb); d.appendChild(sw); d.appendChild(name); d.appendChild(val); lg.appendChild(d);
    });
    if (!layoutTouched) { layout = (S.fields.length > 1 && S.fields.length <= 12) ? 'stack' : 'one'; $('layout').value = layout; }
    if (!viewTouched) { viewMode = S.fields.length > 12 ? 'row' : 'time'; $('view').value = viewMode; }
    showSkip();
    buildCharts();
  }
  function showSkip() { $('skipbox').style.display = viewMode === 'row' ? 'inline-block' : 'none'; }
  function buildCharts() {
    var box = $('charts'); clear(box); charts = [];
    if (viewMode === 'row' && S && S.fields.length) { charts.push({row: true, canvas: mkCanvas(box, 340), last: true}); return; }
    var ids = visibleIdx(), n = ids.length, i;
    if (!n) { box.appendChild(el('div', 'hint', S && S.stream ? 'Waiting for data …' : 'Pick a stream above to start.')); return; }
    var forced = layout === 'stack' && n > 24;      /* far too many canvases: fall back to one chart */
    if (layout === 'one' || forced) {
      if (forced) box.appendChild(el('div', 'hint', n + ' fields: too many for one chart each — showing all in one chart. Untick fields to focus.'));
      charts.push({ids: ids, canvas: mkCanvas(box, 330), last: true});
    } else {
      var h = Math.max(70, Math.min(150, Math.floor(560 / n)));
      for (i = 0; i < n; i++) charts.push({ids: [ids[i]], canvas: mkCanvas(box, h + (i === n - 1 ? 18 : 0)), last: i === n - 1});
    }
  }
  function mkCanvas(box, h) {
    var c = el('canvas', 'cv'); c.style.height = h + 'px'; c.height = h; c.width = 710; box.appendChild(c); return c;
  }

  /* ---------- drawing ---------- */
  function drawChart(ch) {
    var c = ch.canvas, ctx = c.getContext ? c.getContext('2d') : null;
    if (!ctx) return;
    var dpr = window.devicePixelRatio || 1, w = c.clientWidth || 710, h = c.clientHeight || parseInt(c.style.height, 10) || 100;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    var L = 56, R = 8, Tp = 6, B = ch.last ? 20 : 4, pw = w - L - R, ph = h - Tp - B;
    var tmax = paused ? frozenT : (T.length ? T[T.length - 1] : 0), t0 = tmax - windowS;
    var i0 = UD.lowerBound(T, t0), i1 = T.length, k, i;
    var lo = Infinity, hi = -Infinity;
    for (k = 0; k < ch.ids.length; k++) { var Y = V[ch.ids[k]]; if (!Y) continue;
      for (i = i0; i < i1; i++) { var y = Y[i]; if (y === null || y === undefined) continue; if (y < lo) lo = y; if (y > hi) hi = y; } }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (hi - lo < 1e-9) { lo -= 1; hi += 1; } else { var pad = (hi - lo) * 0.06; lo -= pad; hi += pad; }
    function X(t) { return L + (t - t0) / windowS * pw; }
    function Yp(v) { return Tp + (hi - v) / (hi - lo) * ph; }
    ctx.font = '10px Helvetica, Arial, sans-serif'; ctx.lineWidth = 1;
    var ticks = UD.niceTicks(lo, hi, Math.max(3, Math.floor(ph / 26)));
    ctx.fillStyle = '#666'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (i = 0; i < ticks.length; i++) {
      var yy = Math.round(Yp(ticks[i])) + 0.5;
      ctx.strokeStyle = ticks[i] === 0 ? '#bbb' : '#eee'; ctx.beginPath(); ctx.moveTo(L, yy); ctx.lineTo(L + pw, yy); ctx.stroke();
      ctx.fillText(UD.fmt(ticks[i]), L - 5, yy);
    }
    ctx.strokeStyle = '#ccc'; ctx.strokeRect(L + 0.5, Tp + 0.5, pw, ph);
    if (ch.last) {
      ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillStyle = '#666';
      var xt = UD.niceTicks(-windowS, 0, 5);
      for (i = 0; i < xt.length; i++) { var xx = X(tmax + xt[i]); ctx.fillText(xt[i] === 0 ? 'now' : xt[i] + ' s', xx, Tp + ph + 4); }
    }
    ctx.save(); ctx.beginPath(); ctx.rect(L, Tp, pw, ph); ctx.clip(); ctx.lineWidth = 1.2;
    for (k = 0; k < ch.ids.length; k++) {
      var f = ch.ids[k], series = V[f]; if (!series) continue;
      var d = UD.decimate(T, series, i0, i1, t0, tmax, pw), pen = false;
      ctx.strokeStyle = COLORS[f % COLORS.length]; ctx.beginPath();
      for (i = 0; i < d.x.length; i++) {
        if (d.y[i] === null) { pen = false; continue; }
        if (!pen) { ctx.moveTo(X(d.x[i]), Yp(d.y[i])); pen = true; } else ctx.lineTo(X(d.x[i]), Yp(d.y[i]));
      }
      ctx.stroke();
    }
    ctx.restore();
    if (ch.ids.length === 1) {                      /* stacked: name in the corner */
      ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillStyle = COLORS[ch.ids[0] % COLORS.length];
      ctx.font = 'bold 11px Helvetica, Arial, sans-serif'; ctx.fillText(S.fields[ch.ids[0]].name, L + 6, Tp + 3);
    }
  }
  function drawRow(ch) {
    var c = ch.canvas, ctx = c.getContext ? c.getContext('2d') : null;
    if (!ctx) return;
    var dpr = window.devicePixelRatio || 1, w = c.clientWidth || 710, h = c.clientHeight || parseInt(c.style.height, 10) || 340;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    var end = paused ? frozenIdx : T.length - 1;
    if (end < 0 || !V.length) return;
    var rows = UD.rowSlice(V, end, 9, skipN), m = rows[rows.length - 1].length, r, j, i;
    if (m < 1) return;
    var L = 56, R = 10, Tp = 18, B = 22, pw = w - L - R, ph = h - Tp - B, lo = Infinity, hi = -Infinity;
    for (r = 0; r < rows.length; r++) for (j = 0; j < rows[r].length; j++) {
      var y = rows[r][j]; if (y === null) continue; if (y < lo) lo = y; if (y > hi) hi = y;
    }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (hi - lo < 1e-9) { lo -= 1; hi += 1; } else { var pad = (hi - lo) * 0.06; lo -= pad; hi += pad; }
    function X(k) { return m === 1 ? L + pw / 2 : L + k / (m - 1) * pw; }
    function Yp(v) { return Tp + (hi - v) / (hi - lo) * ph; }
    ctx.font = '10px Helvetica, Arial, sans-serif'; ctx.lineWidth = 1;
    var ticks = UD.niceTicks(lo, hi, Math.max(3, Math.floor(ph / 26)));
    ctx.fillStyle = '#666'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (i = 0; i < ticks.length; i++) {
      var yy = Math.round(Yp(ticks[i])) + 0.5;
      ctx.strokeStyle = ticks[i] === 0 ? '#bbb' : '#eee'; ctx.beginPath(); ctx.moveTo(L, yy); ctx.lineTo(L + pw, yy); ctx.stroke();
      ctx.fillText(UD.fmt(ticks[i]), L - 5, yy);
    }
    ctx.strokeStyle = '#ccc'; ctx.strokeRect(L + 0.5, Tp + 0.5, pw, ph);
    ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillStyle = '#666';
    var xt = UD.niceTicks(0, Math.max(1, m - 1), 8);
    for (i = 0; i < xt.length; i++) if (xt[i] <= m - 1) ctx.fillText(String(xt[i] + skipN), X(xt[i]), Tp + ph + 4);
    ctx.save(); ctx.beginPath(); ctx.rect(L - 4, Tp - 4, pw + 8, ph + 8); ctx.clip();
    for (r = 0; r < rows.length; r++) {                       /* oldest first: faint ghosts, then the latest row on top */
      var latest = r === rows.length - 1, row = rows[r], pen = false;
      ctx.strokeStyle = latest ? '#2d7dd2' : 'rgba(45,125,210,' + (0.06 + 0.1 * r / rows.length).toFixed(3) + ')';
      ctx.lineWidth = latest ? 1.8 : 1; ctx.beginPath();
      for (j = 0; j < row.length; j++) {
        if (row[j] === null) { pen = false; continue; }
        if (!pen) { ctx.moveTo(X(j), Yp(row[j])); pen = true; } else ctx.lineTo(X(j), Yp(row[j]));
      }
      ctx.stroke();
      if (latest && m <= 64) {
        ctx.fillStyle = '#2d7dd2';
        for (j = 0; j < row.length; j++) if (row[j] !== null) { ctx.beginPath(); ctx.arc(X(j), Yp(row[j]), 2.6, 0, 6.2832); ctx.fill(); }
      }
    }
    ctx.restore();
    ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillStyle = '#2d7dd2'; ctx.font = 'bold 11px Helvetica, Arial, sans-serif';
    ctx.fillText('latest row — fields ' + skipN + ' … ' + (skipN + m - 1) + '  (' + m + ' values, faint = previous rows)', L + 2, 2);
  }
  function draw() {
    var i; for (i = 0; i < charts.length; i++) { if (charts[i].row) drawRow(charts[i]); else drawChart(charts[i]); }
    if (S && T.length) for (i = 0; i < S.fields.length; i++) {
      var v = $('val' + i); if (v) v.textContent = UD.fmt(V[i] ? V[i][V[i].length - 1] : null);
    }
  }

  /* ---------- applying a poll ---------- */
  function apply(j) {
    if (j.boot !== bootId) {                       /* new server instance: start over */
      bootId = j.boot; seq = 0; cseq = 0; cv = -1; epoch = -1; fieldsKey = ''; T = []; V = [];
      clear($('console'));
    }
    S = j;
    $('pill').textContent = j.state; $('pill').className = j.state;
    $('devname').textContent = j.device ? j.device + '  ·  ' + j.port : (j.port || '');
    var connected = j.state === 'connected', connecting = j.state === 'connecting';
    $('connect').style.display = connected || connecting ? 'none' : '';
    $('disconnect').style.display = connected || connecting ? '' : 'none';
    $('port').disabled = connected || connecting;
    banner(j.state === 'error' || (j.state === 'disconnected' && j.error) ? j.error : '');
    ['stream', 'rate', 'setrate', 'rec', 'refreshp', 'cmd', 'send'].forEach(function (id) { $(id).disabled = !connected; });

    if (j.cv !== cv) { cv = j.cv; buildStreams(); buildActions(); buildParams(); }
    updateParamValues();
    if (j.epoch !== epoch) { epoch = j.epoch; T = []; V = []; lastT = null; fieldsKey = ''; }
    var key = j.fields.map(function (f) { return f.name; }).join('|');
    if (key !== fieldsKey) {
      fieldsKey = key; hidden = j.fields.map(function (f) { return !!f.hidden; });
      V = j.fields.map(function () { return []; }); T = []; buildFields();
    }
    var sel = $('stream'); var want = j.stream === null ? '' : String(j.stream);
    if (document.activeElement !== sel && sel.value !== want) sel.value = want;
    if (j.rate !== null && document.activeElement !== $('rate')) $('rate').value = j.rate;
    $('rec').textContent = j.rec.on ? '■ Stop (' + j.rec.rows + ')' : '● Rec';
    $('recinfo').textContent = j.rec.path ? j.rec.path.split(/[\\/]/).pop() : '';
    $('status2').textContent = (j.stream !== null ? 'stream ' + j.stream + ' · ' + j.fields.length + ' fields · ' : '') +
      (j.ts ? 'device timestamps' : 'PC timestamps') + (j.bad ? ' · ' + j.bad + ' malformed lines skipped' : '');

    var r, i, k;
    for (r = 0; r < j.rows.length; r++) {
      var row = j.rows[r];
      if (lastT !== null && row[0] < lastT - 0.5) { T = []; V = j.fields.map(function () { return []; }); }   /* device rebooted */
      lastT = row[0]; T.push(row[0]);
      for (k = 0; k < V.length; k++) V[k].push(row[k + 1] === undefined ? null : row[k + 1]);
    }
    if (T.length > 30000) { var cut = T.length - 20000; T.splice(0, cut); for (k = 0; k < V.length; k++) V[k].splice(0, cut); }
    seq = j.seq; cseq = j.cseq; appendConsole(j.console);
    draw();
  }

  function poll() {
    api('/api/poll?since=' + seq + '&csince=' + cseq, undefined, function (st, j) {
      if (st === 200 && j) { if (bannerMsg.indexOf('Lost connection') === 0) banner(''); apply(j); }
      else banner('Lost connection to the dashboard server — is it still running?');
      setTimeout(poll, j && j.state === 'connected' ? 100 : 500);
    });
  }

  /* ---------- toolbar wiring ---------- */
  function post(path, body, cb) { api(path, body, function (st, j) { if (j && j.message) log((j.ok ? '✓ ' : '✗ ') + j.message); if (cb) cb(j); }); }
  $('connect').addEventListener('click', function () { post('/api/connect', {port: $('port').value.trim()}); });
  $('disconnect').addEventListener('click', function () { post('/api/disconnect', {}); });
  $('port').addEventListener('keydown', function (e) { if (e.keyCode === 13) $('connect').click(); });
  $('port').addEventListener('focus', function () {
    api('/api/ports', undefined, function (st, j) {
      var dl = $('portlist'); clear(dl);
      ((j && j.ports) || []).forEach(function (p) { var o = el('option'); o.value = p.device; o.label = p.description; dl.appendChild(o); });
    });
  });
  $('stream').addEventListener('change', function () { post('/api/stream', {id: this.value ? parseInt(this.value, 10) : null}); });
  $('setrate').addEventListener('click', function () { post('/api/rate', {rate: parseInt($('rate').value, 10) || 20}); });
  $('rate').addEventListener('keydown', function (e) { if (e.keyCode === 13) $('setrate').click(); });
  $('win').addEventListener('change', function () { windowS = parseFloat(this.value); draw(); });
  $('layout').addEventListener('change', function () { layout = this.value; layoutTouched = true; if (S) { buildCharts(); draw(); } });
  $('view').addEventListener('change', function () { viewMode = this.value; viewTouched = true; showSkip(); if (S) { buildCharts(); draw(); } });
  function setSkip() { skipN = Math.max(0, parseInt($('skip').value, 10) || 0); draw(); }
  $('skip').addEventListener('input', setSkip); $('skip').addEventListener('change', setSkip);
  $('pause').addEventListener('click', function () {
    paused = !paused; frozenT = T.length ? T[T.length - 1] : 0; frozenIdx = T.length - 1; this.textContent = paused ? 'Resume' : 'Pause'; draw();
  });
  $('rec').addEventListener('click', function () { post('/api/record', {on: !(S && S.rec.on)}); });
  $('refreshp').addEventListener('click', function () { post('/api/params/refresh', {}); });
  function sendCmd() { var v = $('cmd').value.trim(); if (!v) return; $('cmd').value = ''; post('/api/command', {line: v}); }
  $('send').addEventListener('click', sendCmd);
  $('cmd').addEventListener('keydown', function (e) { if (e.keyCode === 13) sendCmd(); });
  window.addEventListener('resize', function () { draw(); });

  (function () {                                    /* ?layout=one&window=5 */
    var q = location.search.replace(/^\?/, '').split('&'), i;
    for (i = 0; i < q.length; i++) {
      var kv = q[i].split('=');
      if (kv[0] === 'layout' && (kv[1] === 'one' || kv[1] === 'stack')) { layout = kv[1]; layoutTouched = true; $('layout').value = kv[1]; }
      if (kv[0] === 'window' && /^\d+$/.test(kv[1])) { windowS = parseFloat(kv[1]); $('win').value = kv[1]; }
      if (kv[0] === 'view' && (kv[1] === 'row' || kv[1] === 'time')) { viewMode = kv[1]; viewTouched = true; $('view').value = kv[1]; showSkip(); }
      if (kv[0] === 'skip' && /^\d+$/.test(kv[1])) { skipN = parseInt(kv[1], 10); $('skip').value = kv[1]; }
    }
  })();

  poll();
})();
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>UniProto dashboard</title>
<style>{{ css|safe }}</style></head><body><div id="wrap">
<div id="top"><h1>UniProto dashboard</h1><span id="pill">disconnected</span>
 <span id="devname" class="hint" style="margin-left:10px"></span>
 <div id="conn"><input type="text" id="port" list="portlist" value="{{ port }}" placeholder="/dev/tty.usbmodem…  or  COM3"
  autocomplete="off" spellcheck="false"><datalist id="portlist"></datalist>
  <button id="connect">Connect</button><button id="disconnect" style="display:none">Disconnect</button></div></div>
<div id="banner"></div>
<div id="main">
 <div id="bar"><span class="g"><label>Stream</label><select id="stream" disabled><option value="">— no stream —</option></select></span>
  <span class="g"><label>Rate</label><input type="number" id="rate" value="20" min="1" max="500" style="width:58px" disabled>
  <button id="setrate" disabled>Set</button></span>
  <span class="g"><label>Window</label><select id="win"><option value="2">2 s</option><option value="5">5 s</option>
   <option value="10" selected>10 s</option><option value="30">30 s</option><option value="60">60 s</option></select></span>
  <span class="g"><label>Layout</label><select id="layout"><option value="stack">one chart per field</option><option value="one">all in one</option></select></span>
  <span class="g"><label>View</label><select id="view"><option value="time">over time</option><option value="row">latest row</option></select></span>
  <span class="g" id="skipbox" style="display:none"><label>skip first</label><input type="number" id="skip" value="0" min="0" style="width:50px"></span>
  <span class="g"><button id="pause">Pause</button> <a href="/api/csv" download="uniproto_buffer.csv"><button>Save CSV</button></a>
  <button id="rec" disabled>● Rec</button><span id="recinfo" class="hint"></span></span></div>
 <div id="charts"><div class="hint">Connect to a board, then pick a stream.</div></div>
 <div id="legend"></div><div id="status2" class="hint" style="margin-top:6px"></div>
</div>
<div id="side">
 <div class="box"><h2>Parameters</h2><div class="in"><div id="params"><span class="hint">Not connected.</span></div>
  <div style="margin-top:6px"><button id="refreshp" disabled>Refresh values</button></div></div></div>
 <div class="box"><h2>Actions</h2><div class="in" id="acts"><span class="hint">Not connected.</span></div></div>
 <div class="box"><h2>Console</h2><pre id="console"></pre>
  <div class="in"><input type="text" id="cmd" placeholder="!mot.kp:2.0   ?rate   @mot.zero" disabled>
   <button id="send" disabled>Send</button></div></div>
</div>
<div style="clear:both"></div>
</div><script>{{ js|safe }}</script></body></html>
"""


def create_app(device=None, strict_host=True, record_dir=ROOT / "recordings", port="", boot_wait=2.0):
    try:
        from flask import Flask, Response, abort, jsonify, render_template_string, request
    except ImportError:
        sys.exit("Flask is not installed. Run:  pip install -r requirements.txt")

    app = Flask(__name__)
    dev = device or Device(record_dir, boot_wait)
    app.dev = dev

    @app.before_request
    def guard():
        if strict_host and urlsplit("//" + request.host).hostname not in LOOPBACK:
            abort(403)                       # DNS-rebinding guard
        if request.method == "POST" and not request.is_json:
            abort(415)                       # cross-site form posts cannot send JSON

    @app.get("/")
    def index():
        return render_template_string(PAGE, css=CSS, js=JS, port=port or dev.port)

    @app.get("/api/ports")
    def api_ports():
        return jsonify(ports=list_ports())

    @app.get("/api/poll")
    def api_poll():
        try:
            since, csince = int(request.args.get("since", 0)), int(request.args.get("csince", 0))
        except ValueError:
            since = csince = 0
        return jsonify(dev.snapshot(since, csince))

    def body():
        return request.get_json(silent=True) or {}

    def result(ok_msg):
        ok, msg = ok_msg
        return jsonify(ok=ok, message=msg)

    @app.post("/api/connect")
    def api_connect():
        p = str(body().get("port") or "").strip()
        if not p or _CTRL.search(p) or len(p) > 200:
            return jsonify(ok=False, message="Enter a serial port first."), 400
        return result(dev.connect(p, int(body().get("baud") or 115200)))

    @app.post("/api/disconnect")
    def api_disconnect():
        dev.disconnect()
        return jsonify(ok=True, message="Disconnected.")

    @app.post("/api/stream")
    def api_stream():
        sid = body().get("id")
        if sid is not None and not isinstance(sid, int):
            return jsonify(ok=False, message="bad stream id"), 400
        return result(dev.set_stream(sid))

    @app.post("/api/rate")
    def api_rate():
        try:
            n = int(body().get("rate"))
        except (TypeError, ValueError):
            return jsonify(ok=False, message="bad rate"), 400
        return result(dev.set_rate(n))

    @app.post("/api/param")
    def api_param():
        return result(dev.set_param(str(body().get("name") or ""), str(body().get("value") if body().get("value") is not None else "")))

    @app.post("/api/params/refresh")
    def api_params_refresh():
        return result(dev.refresh_params())

    @app.post("/api/action")
    def api_action():
        return result(dev.action(str(body().get("name") or ""), str(body().get("args") or "")))

    @app.post("/api/command")
    def api_command():
        return result(dev.command(str(body().get("line") or "").strip()))

    @app.post("/api/record")
    def api_record():
        return result(dev.start_record() if body().get("on") else dev.stop_record())

    @app.get("/api/csv")
    def api_csv():
        return Response(dev.csv_text(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=uniproto_buffer.csv"})

    return app


def main():
    ap = argparse.ArgumentParser(description="UniProto dashboard (generic web UI for any UniProto sketch)")
    ap.add_argument("--port", default="", help="serial port to connect to at start")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--stream", type=int, default=None, help="stream id to start streaming at connect")
    ap.add_argument("--rate", type=int, default=None, help="rate in Hz to set at connect")
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    ap.add_argument("--flask-port", type=int, default=DEFAULT_WEB_PORT, help="web port (default 5000)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--boot-wait", type=float, default=2.0, help="seconds to wait after opening the port")
    ap.add_argument("--record-dir", default=str(ROOT / "recordings"))
    ap.add_argument("--list-ports", action="store_true")
    args = ap.parse_args()

    if args.list_ports:
        for p in list_ports():
            print(f"{p['device']:36s} {'*' if p['likely'] else ' '} {p['description']}")
        return

    strict = args.host in ("127.0.0.1", "localhost", "::1")
    if not strict:
        print(f"WARNING: listening on {args.host} — anyone who can reach this address can drive the "
              f"connected hardware.", flush=True)
    if args.flask_port in UNSAFE_BROWSER_PORTS:
        print(f"WARNING: browsers refuse to open port {args.flask_port} (ERR_UNSAFE_PORT). "
              f"Use another one, e.g. --flask-port 5000.", flush=True)
    dev = Device(args.record_dir, args.boot_wait)
    app = create_app(dev, strict_host=strict, port=args.port)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.flask_port}"
    print(f"UniProto dashboard: {url}   (Ctrl-C to stop)", flush=True)

    def on_term(signum, frame):
        sys.exit(0)                          # lets the finally block drop DTR before the process ends
    signal.signal(signal.SIGTERM, on_term)

    if args.port:
        ok, msg = dev.connect(args.port, args.baud, args.stream, args.rate)
        print(msg, flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        app.run(host=args.host, port=args.flask_port, threaded=True, use_reloader=False)
    except OSError as ex:
        sys.exit(f"Could not listen on port {args.flask_port}: {ex}\n"
                 f"Another program has it (the sensor-shield viewer also uses 5000; on macOS so can "
                 f"AirPlay Receiver).\nTry:  python dashboard.py --flask-port {args.flask_port + 1}")
    finally:
        print("UniProto dashboard: closing the serial port", flush=True)
        dev.disconnect()


if __name__ == "__main__":
    main()
