"""
boardconfig.py — per-board configuration for the generic dashboard (dashboard.json).

A board config makes the dashboard fit ONE board: names and units for the fields, which charts to
show on which tab, which parameters get sliders / menus / presets, which buttons exist, and one-click
command presets.  It is optional: without one the dashboard works from what the board reports.

WHERE IT LIVES
  src/<setup>/dashboard.json     next to the sketch (PlatformIO ignores it)
  dashboard/boards/*.json        for boards without a sketch here (e.g. the simulator)
  --config FILE                  an explicit file
The right file is found by "device": the name the sketch gives UniProto,  UniProto proto(Serial, "DCMotor").
Edit the file and the dashboard picks it up within a second — no restart.  Mistakes are shown in the
page (never a crash), with a "did you mean ...?" for misspelt keys.

REFERENCE   (everything is optional except "device")
{
  "device": "DCMotor",              must equal the name the board reports
  "title": "DC motor",              page title
  "autostart": true,                start the first view when connected (default: true if there are views)
  "stream_picker": true,            keep the raw stream drop-down next to the tabs
  "hide_unlisted_params": false,    show only the parameters listed under "params"
  "hide_unlisted_actions": false,

  "streams": { "1": { "fields": [                       key = stream id or name
        "pos",                                           a name, or:
        { "name": "vel", "label": "Velocity", "unit": "counts/s",
          "scale": 0.1, "offset": 0, "hidden": false } ] } },     scale/offset are applied to every value
                                                                    (charts, CSV download and recording)
  "views": [ {                                          one tab each
      "name": "Control", "stream": 1,                    stream id or name
      "rate": 50, "window": 10,                          Hz to ask for; seconds shown
      "widgets": [                                       omit for the automatic view
        { "type": "chart", "title": "Position", "fields": ["pos", "set"],     fields: names or numbers
          "unit": "ticks", "min": 0, "max": 100 },                            min/max fix the y-axis
        { "type": "row",   "title": "Per sensor", "skip": 0, "min": 0, "max": 2500 },   latest row vs index
        { "type": "value", "fields": ["pos", "vel"] } ] } ],                  big numbers

  "params": [ { "name": "mot.kp", "label": "Kp", "unit": "", "group": "PID", "help": "tooltip",
        "min": 0, "max": 20, "step": 0.1,                 min/max are ENFORCED: the dashboard refuses values outside
        "widget": "slider",                               slider | number | select | checkbox | text
        "options": { "0": "PWM", "1": "position" },       a menu: value -> label (only these can be sent)
        "presets": [0.5, 2, 5],                           one-click values
        "readonly": false, "hidden": false } ],
  "actions": [ { "name": "mot.zero", "label": "Zero encoder", "group": "...",
        "confirm": "Really?", "style": "danger" } ],
  "presets": [ { "label": "Velocity control",             buttons that run several commands in a row
        "commands": [ "!mot.mode:2", { "wait": 0.2 }, "!mot.kp:0.5", "@mot.zero" ] } ]
}
"""
import difflib
import json
import math
import re
from pathlib import Path

CORE_PARAMS = ("rate", "format", "timestamp", "stream")      # managed by the dashboard itself
_CTRL = re.compile(r"[\x00-\x1f\x7f]")

TOP_KEYS = {"device", "title", "autostart", "stream_picker", "hide_unlisted_params", "hide_unlisted_actions",
            "streams", "views", "params", "actions", "presets"}
FIELD_KEYS = {"name", "label", "unit", "scale", "offset", "hidden", "color"}
VIEW_KEYS = {"name", "stream", "rate", "window", "widgets"}
WIDGET_KEYS = {"type", "title", "fields", "unit", "min", "max", "skip"}
WIDGET_TYPES = ("chart", "row", "value")
PARAM_KEYS = {"name", "label", "unit", "group", "help", "min", "max", "step", "widget", "options", "presets",
              "readonly", "hidden"}
PARAM_WIDGETS = ("slider", "number", "select", "checkbox", "text")
ACTION_KEYS = {"name", "label", "group", "confirm", "style", "hidden"}
ACTION_STYLES = ("normal", "danger")
PRESET_KEYS = {"label", "commands"}
MAX_WAIT_S = 5.0


class ConfigError(ValueError):
    """The file cannot be used at all (not JSON, not an object, no device)."""


# ── small validators ──────────────────────────────────────────────────────────
def valid_command(line: str) -> bool:
    """What may be sent to a board: !key:value, ?key or @action, short, no control characters."""
    return bool(line) and len(line) <= 63 and line[0] in "!?@" and not _CTRL.search(line)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _unknown(d, allowed, where, warn):
    for k in d:
        if k not in allowed:
            near = difflib.get_close_matches(str(k), sorted(allowed), n=1, cutoff=0.6)
            hint = f" — did you mean '{near[0]}'?" if near else f" (allowed: {', '.join(sorted(allowed))})"
            warn.append(f"{where + ': ' if where else ''}unknown key '{k}'{hint}")


def _str(d, key, where, warn, default=""):
    v = d.get(key)
    if v is None:
        return default
    if not isinstance(v, str):
        warn.append(f"{where}.{key} must be text — ignored")
        return default
    return v.strip()


def _bool(d, key, default):
    v = d.get(key)
    return v if isinstance(v, bool) else default


def _numkey(d, key, where, warn):
    v = d.get(key)
    if v is None:
        return None
    if not _is_num(v):
        warn.append(f"{where}.{key} must be a number — ignored")
        return None
    return v


def parse_step(cmd: str):
    """'!name:value' -> ('set', name, value) · '@name[:args]' -> ('act', name, args) · '?x' -> ('get', x, '')"""
    if cmd[0] == "!":
        body = cmd[1:]
        name, sep, value = body.partition(":")
        return ("set", name, value) if sep and name else ("bad", cmd, "")
    if cmd[0] == "@":
        name, _, args = cmd[1:].partition(":")
        return ("act", name, args)
    return ("get", cmd[1:], "")


def check_param_value(spec, value: str):
    """Refuse a value the board config forbids. spec = a normalized params entry (or None). -> error | None"""
    if spec is None:
        return None
    if spec.get("readonly"):
        return f"{spec['name']} is read-only in the board config"
    opts = spec.get("options")
    if opts and value not in opts:
        return f"{spec['name']} accepts only: " + ", ".join(f"{k} ({v})" for k, v in opts.items())
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None or hi is not None:
        try:
            x = float(value)
        except ValueError:
            return f"{spec['name']} needs a number"
        if (lo is not None and x < lo) or (hi is not None and x > hi):
            rng = f"{'-∞' if lo is None else lo} … {'∞' if hi is None else hi}"
            return f"{value} is outside the allowed range of {spec['name']} ({rng})"
    return None


# ── parse + normalize ─────────────────────────────────────────────────────────
def parse_text(text: str):
    """-> (raw dict, None) or (None, 'JSON error at line L, column C: ...')"""
    try:
        return json.loads(text), None
    except json.JSONDecodeError as ex:
        return None, f"JSON error at line {ex.lineno}, column {ex.colno}: {ex.msg}"


def _field(f, where, warn):
    if isinstance(f, str):
        f = {"name": f}
    if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not f["name"].strip():
        warn.append(f"{where}: a field needs a name — ignored")
        return None
    _unknown(f, FIELD_KEYS, where, warn)
    out = {"name": f["name"].strip(), "label": _str(f, "label", where, warn), "unit": _str(f, "unit", where, warn),
           "hidden": _bool(f, "hidden", False), "color": _str(f, "color", where, warn)}
    for k, dflt in (("scale", 1.0), ("offset", 0.0)):
        v = _numkey(f, k, where, warn)
        out[k] = dflt if v is None else v
    return out


def normalize(raw, caps=None):
    """Validate a parsed config. -> (config, [warnings]).  Raises ConfigError for an unusable file.
    With `caps` (the board's '?' answer) names of streams, parameters and actions are checked too."""
    warn = []
    if not isinstance(raw, dict):
        raise ConfigError("the file must contain one JSON object { ... }")
    dev = raw.get("device")
    if not isinstance(dev, str) or not dev.strip():
        raise ConfigError('missing "device" — the name the board reports, e.g. "DCMotor"')
    _unknown(raw, TOP_KEYS, "", warn)
    cstreams = {s.get("id"): s for s in (caps or {}).get("streams", [])}
    cnames = {str(s.get("name", "")).lower(): s.get("id") for s in cstreams.values()}
    cparams = set((caps or {}).get("params", [])) - set(CORE_PARAMS)
    cactions = set((caps or {}).get("actions", []))

    cfg = {"device": dev.strip(), "title": _str(raw, "title", "", warn), "views": [], "params": [], "actions": [],
           "presets": [], "streams": {},
           "stream_picker": _bool(raw, "stream_picker", True),
           "hide_unlisted_params": _bool(raw, "hide_unlisted_params", False),
           "hide_unlisted_actions": _bool(raw, "hide_unlisted_actions", False)}

    # streams
    rs = raw.get("streams") or {}
    if not isinstance(rs, dict):
        warn.append("streams must be an object {\"1\": {...}} — ignored"); rs = {}
    for key, sv in rs.items():
        where = f"streams.{key}"
        fl = sv.get("fields") if isinstance(sv, dict) else None
        if not isinstance(fl, list):
            warn.append(f"{where}: needs a \"fields\" list — ignored"); continue
        if isinstance(sv, dict):
            _unknown(sv, {"fields"}, where, warn)
        fields = [f for f in (_field(f, f"{where}.fields[{i}]", warn) for i, f in enumerate(fl)) if f]
        names = [f["name"].lower() for f in fields]
        for n in {n for n in names if names.count(n) > 1}:
            warn.append(f"{where}: the field name '{n}' appears more than once")
        cfg["streams"][str(key)] = {"fields": fields}

    # params
    rp = raw.get("params") or []
    if not isinstance(rp, list):
        warn.append("params must be a list — ignored"); rp = []
    for i, p in enumerate(rp):
        where = f"params[{i}]"
        if not isinstance(p, dict) or not isinstance(p.get("name"), str):
            warn.append(f"{where}: needs a \"name\" — ignored"); continue
        _unknown(p, PARAM_KEYS, f"{where} ({p['name']})", warn)
        name = p["name"].strip()
        if name in CORE_PARAMS:
            warn.append(f"{where}: '{name}' is managed by the dashboard itself — ignored"); continue
        if caps is not None and name not in cparams:
            near = difflib.get_close_matches(name, sorted(cparams), n=1, cutoff=0.6)
            warn.append(f"{where}: the board has no parameter '{name}'" + (f" — did you mean '{near[0]}'?" if near else "") + " — ignored")
            continue
        spec = {"name": name, "label": _str(p, "label", where, warn), "unit": _str(p, "unit", where, warn),
                "group": _str(p, "group", where, warn), "help": _str(p, "help", where, warn),
                "min": _numkey(p, "min", where, warn), "max": _numkey(p, "max", where, warn),
                "step": _numkey(p, "step", where, warn), "widget": _str(p, "widget", where, warn),
                "options": None, "presets": [], "readonly": _bool(p, "readonly", False), "hidden": _bool(p, "hidden", False)}
        if spec["min"] is not None and spec["max"] is not None and spec["min"] > spec["max"]:
            warn.append(f"{where} ({name}): min is larger than max — range ignored")
            spec["min"] = spec["max"] = None
        if spec["step"] is not None and spec["step"] <= 0:
            warn.append(f"{where} ({name}): step must be positive — ignored"); spec["step"] = None
        if spec["widget"] and spec["widget"] not in PARAM_WIDGETS:
            warn.append(f"{where} ({name}): unknown widget '{spec['widget']}' (use {', '.join(PARAM_WIDGETS)}) — automatic instead")
            spec["widget"] = ""
        opts = p.get("options")
        if opts is not None:
            if isinstance(opts, dict) and opts:
                spec["options"] = {str(k): str(v) for k, v in opts.items()}
            else:
                warn.append(f"{where} ({name}): options must be an object {{\"0\": \"label\"}} — ignored")
        pr = p.get("presets")
        if pr is not None:
            if isinstance(pr, list) and all(_is_num(x) or isinstance(x, str) for x in pr):
                spec["presets"] = [str(x) if not isinstance(x, float) or not x.is_integer() else str(int(x)) for x in pr]
                for v in spec["presets"]:
                    bad = check_param_value({**spec, "readonly": False}, v)
                    if bad:
                        warn.append(f"{where} ({name}): preset {v} — {bad}")
            else:
                warn.append(f"{where} ({name}): presets must be a list of values — ignored")
        if spec["widget"] == "slider" and (spec["min"] is None or spec["max"] is None):
            warn.append(f"{where} ({name}): a slider needs both min and max — plain number input instead")
            spec["widget"] = "number"
        cfg["params"].append(spec)
    pmap = {p["name"]: p for p in cfg["params"]}

    # actions
    ra = raw.get("actions") or []
    if not isinstance(ra, list):
        warn.append("actions must be a list — ignored"); ra = []
    for i, a in enumerate(ra):
        where = f"actions[{i}]"
        if not isinstance(a, dict) or not isinstance(a.get("name"), str):
            warn.append(f"{where}: needs a \"name\" — ignored"); continue
        _unknown(a, ACTION_KEYS, f"{where} ({a['name']})", warn)
        name = a["name"].strip()
        if caps is not None and name not in cactions:
            near = difflib.get_close_matches(name, sorted(cactions), n=1, cutoff=0.6)
            warn.append(f"{where}: the board has no action '{name}'" + (f" — did you mean '{near[0]}'?" if near else "") + " — ignored")
            continue
        style = _str(a, "style", where, warn) or "normal"
        if style not in ACTION_STYLES:
            warn.append(f"{where} ({name}): unknown style '{style}' (use normal or danger)"); style = "normal"
        cfg["actions"].append({"name": name, "label": _str(a, "label", where, warn), "group": _str(a, "group", where, warn),
                               "confirm": _str(a, "confirm", where, warn), "style": style, "hidden": _bool(a, "hidden", False)})

    # views
    rv = raw.get("views") or []
    if not isinstance(rv, list):
        warn.append("views must be a list — ignored"); rv = []
    for i, v in enumerate(rv):
        where = f"views[{i}]"
        if not isinstance(v, dict):
            warn.append(f"{where}: must be an object — ignored"); continue
        _unknown(v, VIEW_KEYS, f"{where} ({v.get('name', '?')})", warn)
        ref = v.get("stream")
        sid = None
        if isinstance(ref, int) and not isinstance(ref, bool):
            sid = ref
        elif isinstance(ref, str) and ref.strip().isdigit():
            sid = int(ref.strip())
        elif isinstance(ref, str) and ref.strip():
            sid = cnames.get(ref.strip().lower()) if caps is not None else ref.strip()
        if ref is None:
            warn.append(f"{where}: needs a \"stream\" (id or name) — ignored"); continue
        if caps is not None and (sid is None or (isinstance(sid, int) and sid not in cstreams)):
            names = ", ".join(f"{k} ({s.get('name')})" for k, s in cstreams.items())
            warn.append(f"{where}: the board has no stream {ref!r} (it has: {names}) — ignored"); continue
        view = {"name": _str(v, "name", where, warn) or f"View {i + 1}", "stream": sid, "rate": None, "window": None, "widgets": None}
        r = v.get("rate")
        if r is not None:
            if isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= 500:
                view["rate"] = r
            else:
                warn.append(f"{where}: rate must be a whole number from 1 to 500 — ignored")
        w = _numkey(v, "window", where, warn)
        if w is not None:
            if w > 0:
                view["window"] = w
            else:
                warn.append(f"{where}: window must be positive — ignored")
        wl = v.get("widgets")
        if wl is not None:
            if not isinstance(wl, list):
                warn.append(f"{where}.widgets must be a list — automatic view instead")
            else:
                view["widgets"] = []
                for wi, wd in enumerate(wl):
                    ww = f"{where}.widgets[{wi}]"
                    if not isinstance(wd, dict):
                        warn.append(f"{ww}: must be an object — ignored"); continue
                    _unknown(wd, WIDGET_KEYS, ww, warn)
                    t = wd.get("type", "chart")
                    if t not in WIDGET_TYPES:
                        near = difflib.get_close_matches(str(t), WIDGET_TYPES, n=1, cutoff=0.5)
                        warn.append(f"{ww}: unknown type '{t}'" + (f" — did you mean '{near[0]}'?" if near else f" (use {', '.join(WIDGET_TYPES)})") + " — ignored")
                        continue
                    fl2 = wd.get("fields")
                    if fl2 is not None and not (isinstance(fl2, list) and all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in fl2)):
                        warn.append(f"{ww}: fields must be a list of names or numbers — all fields instead"); fl2 = None
                    skip = wd.get("skip", 0)
                    if not (isinstance(skip, int) and not isinstance(skip, bool) and skip >= 0):
                        warn.append(f"{ww}: skip must be a whole number ≥ 0 — ignored"); skip = 0
                    lo, hi = _numkey(wd, "min", ww, warn), _numkey(wd, "max", ww, warn)
                    if lo is not None and hi is not None and lo >= hi:
                        warn.append(f"{ww}: min must be smaller than max — fixed range ignored"); lo = hi = None
                    view["widgets"].append({"type": t, "title": _str(wd, "title", ww, warn), "fields": fl2,
                                            "unit": _str(wd, "unit", ww, warn), "min": lo, "max": hi, "skip": skip})
        cfg["views"].append(view)
    cfg["autostart"] = _bool(raw, "autostart", bool(cfg["views"]))

    # presets (command sequences)
    rpre = raw.get("presets") or []
    if not isinstance(rpre, list):
        warn.append("presets must be a list — ignored"); rpre = []
    for i, p in enumerate(rpre):
        where = f"presets[{i}]"
        if not isinstance(p, dict) or not isinstance(p.get("label"), str) or not isinstance(p.get("commands"), list) or not p["commands"]:
            warn.append(f"{where}: needs a \"label\" and a non-empty \"commands\" list — ignored"); continue
        _unknown(p, PRESET_KEYS, where, warn)
        steps, ok = [], True
        for si, c in enumerate(p["commands"]):
            sw = f"{where} ({p['label']}) step {si + 1}"
            if isinstance(c, dict) and set(c) == {"wait"} and _is_num(c["wait"]) and 0 <= c["wait"] <= MAX_WAIT_S:
                steps.append({"wait": float(c["wait"])}); continue
            if not isinstance(c, str) or not valid_command(c):
                warn.append(f"{sw}: not a valid command (start with ! ? or @, at most 63 characters; or {{\"wait\": seconds up to {MAX_WAIT_S:g}}}) — preset ignored")
                ok = False; break
            kind, name, value = parse_step(c)
            if kind == "bad":
                warn.append(f"{sw}: '{c}' needs the form !name:value — preset ignored"); ok = False; break
            if kind == "set":
                if name in ("format", "timestamp", "stream"):
                    warn.append(f"{sw}: '{name}' is managed by the dashboard — preset ignored"); ok = False; break
                if name != "rate" and caps is not None and name not in cparams:
                    warn.append(f"{sw}: the board has no parameter '{name}' — preset ignored"); ok = False; break
                bad = check_param_value({**pmap[name], "readonly": False}, value) if name in pmap else None
                if bad:
                    warn.append(f"{sw}: {bad} — preset ignored"); ok = False; break
            if kind == "act" and caps is not None and name not in cactions:
                warn.append(f"{sw}: the board has no action '{name}' — preset ignored"); ok = False; break
            steps.append({"cmd": c})
        if ok:
            cfg["presets"].append({"label": p["label"].strip(), "steps": steps})
    return cfg, warn


# ── discovery with hot reload ─────────────────────────────────────────────────
class ConfigStore:
    """Finds the dashboard.json for a device, re-reading it when the file changes."""

    def __init__(self, roots=(), files=()):
        self.roots = [Path(r) for r in roots]
        self.files = [Path(f) for f in files]
        self._cache = {}                       # path -> (signature, raw | None, error | None)

    def candidates(self):
        seen, out = set(), []
        paths = list(self.files)
        for r in self.roots:
            if r.is_dir():
                paths += sorted(r.glob("*/dashboard.json")) + sorted(r.glob("*.json"))
        for p in paths:
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp); out.append(p)
        return out

    def _read(self, p):
        try:
            st = p.stat()
        except OSError as ex:
            return None, None, f"cannot read the file: {ex.strerror or ex}"
        sig = (st.st_mtime_ns, st.st_size)
        hit = self._cache.get(p)
        if hit and hit[0] == sig:
            return hit
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as ex:
            res = (sig, None, f"cannot read the file: {ex}")
        else:
            raw, err = parse_text(text)
            res = (sig, raw, err)
        self._cache[p] = res
        return res

    def find(self, device):
        """-> {'path','raw','sig','others'} for the first file whose "device" matches (case-insensitive), or None"""
        want = (device or "").strip().lower()
        hits = []
        for p in self.candidates():
            sig, raw, err = self._read(p)
            if isinstance(raw, dict) and str(raw.get("device", "")).strip().lower() == want:
                hits.append((p, sig, raw))
        if not hits:
            return None
        p, sig, raw = hits[0]
        return {"path": str(p), "raw": raw, "sig": sig, "others": [str(h[0]) for h in hits[1:]]}

    def problems(self):
        """[(path, message)] for config files that cannot be used (broken JSON, no device) — shown to the user."""
        out = []
        for p in self.candidates():
            sig, raw, err = self._read(p)
            if err:
                out.append((str(p), err))
            elif not isinstance(raw, dict) or not isinstance(raw.get("device"), str):
                out.append((str(p), 'no "device" — the file is ignored'))
        return out

    def stamp(self):
        """Changes whenever any candidate file is added, removed or edited (cheap: a few stat calls)."""
        out = []
        for p in self.candidates():
            try:
                st = p.stat()
                out.append((str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                out.append((str(p), 0, 0))
        return tuple(out)

    def signature(self, device):
        f = self.find(device)
        return (f["path"], f["sig"]) if f else None


# ── resolution at run time ────────────────────────────────────────────────────
def stream_fields_cfg(cfg, stream_id, stream_name):
    if not cfg:
        return None
    s = cfg["streams"].get(str(stream_id)) or cfg["streams"].get(str(stream_name))
    if s:
        return s["fields"]
    for key, v in cfg["streams"].items():
        if key.lower() == str(stream_name).lower():
            return v["fields"]
    return None


def field_specs(cfg, stream_id, stream_name, k, units, label_fields):
    """The k fields of a stream as dicts {name,label,unit,scale,offset,hidden,color}. Returns (specs, [warnings])."""
    warn = []
    fl = stream_fields_cfg(cfg, stream_id, stream_name)
    if fl is not None and len(fl) != k:
        warn.append(f"streams.{stream_id}: the config names {len(fl)} fields but the board sends {k} — using automatic names")
        fl = None
    if fl is not None:
        return [dict(f) for f in fl], warn
    return [{"name": f["name"], "label": "", "unit": "", "scale": 1.0, "offset": 0.0, "hidden": f["hidden"], "color": ""}
            for f in label_fields(units, k)], warn


def _field_index(ref, fields):
    if isinstance(ref, int) and not isinstance(ref, bool):
        return ref if 0 <= ref < len(fields) else None
    r = str(ref).strip().lower()
    for i, f in enumerate(fields):
        if f["name"].lower() == r or (f.get("label") or "").lower() == r:
            return i
    return None


def resolve_widgets(view, fields):
    """A view's widgets with field names turned into indices. -> (widgets | None, [warnings])"""
    if not view or view.get("widgets") is None:
        return None, []
    out, warn = [], []
    for wi, w in enumerate(view["widgets"]):
        ids = []
        if w["fields"] is None:
            ids = [i for i, f in enumerate(fields) if not f.get("hidden")]
        else:
            for ref in w["fields"]:
                idx = _field_index(ref, fields)
                if idx is None:
                    near = difflib.get_close_matches(str(ref), [f["name"] for f in fields], n=1, cutoff=0.6)
                    warn.append(f"view '{view['name']}' widget {wi + 1}: no field '{ref}'" + (f" — did you mean '{near[0]}'?" if near else "") + " — skipped")
                else:
                    ids.append(idx)
        if not ids and w["type"] != "row":
            warn.append(f"view '{view['name']}' widget {wi + 1}: no fields to show — skipped")
            continue
        unit = w["unit"]
        if not unit:
            units = {fields[i].get("unit", "") for i in ids}
            unit = units.pop() if len(units) == 1 else ""
        out.append({"type": w["type"], "title": w["title"], "ids": ids, "unit": unit,
                    "ymin": w["min"], "ymax": w["max"], "skip": w["skip"]})
    return out, warn


def merge_params(cfg, values, infer):
    """The parameters to show: board values + config. values: {name: str|None}. -> list of dicts for the page."""
    out = []
    listed = {}
    if cfg:
        for spec in cfg["params"]:
            if spec["name"] in values:
                listed[spec["name"]] = spec
    for name, val in values.items():
        spec = listed.get(name)
        if spec is None and cfg and cfg["hide_unlisted_params"]:
            continue
        base = {"name": name, "value": val, "type": infer(name, val), "label": "", "unit": "", "group": "", "help": "",
                "min": None, "max": None, "step": None, "widget": "", "options": None, "presets": [],
                "readonly": False, "hidden": False}
        if spec:
            base.update({k: spec[k] for k in ("label", "unit", "group", "help", "min", "max", "step", "widget",
                                              "options", "presets", "readonly", "hidden")})
        out.append(base)
    order = {n: i for i, n in enumerate(s["name"] for s in (cfg["params"] if cfg else []))}
    out.sort(key=lambda p: (order.get(p["name"], 10 ** 6), ))
    return out


def merge_actions(cfg, names):
    out, listed = [], {}
    if cfg:
        for spec in cfg["actions"]:
            if spec["name"] in names:
                listed[spec["name"]] = spec
    for n in names:
        spec = listed.get(n)
        if spec is None and cfg and cfg["hide_unlisted_actions"]:
            continue
        out.append({"name": n, "label": (spec or {}).get("label", ""), "group": (spec or {}).get("group", ""),
                    "confirm": (spec or {}).get("confirm", ""), "style": (spec or {}).get("style", "normal"),
                    "hidden": (spec or {}).get("hidden", False)})
    order = {n: i for i, n in enumerate(s["name"] for s in (cfg["actions"] if cfg else []))}
    out.sort(key=lambda a: order.get(a["name"], 10 ** 6))
    return out
