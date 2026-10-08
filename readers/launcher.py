#!/usr/bin/env python3
"""
UniProto launcher — pick a serial port once, click a setup, its reader starts.

  python launcher.py                 open the launcher
  python launcher.py --port COM3     ...with a port preselected
  python launcher.py --check         list which reader scripts / icons exist
  python launcher.py --list-ports    list serial ports and exit

What a click does:
  * starts  <python> readers/<script> --port <selected port>  as its own process
    (same Python / venv as the launcher, so every reader keeps its own window)
  * only ONE reader may hold the serial port at a time — the launcher blocks a
    second one until the first window is closed
  * Python-only readers (lidar, kinect) start without --port
  * the row under the grid lists every reader of the selected setup

Close reader windows with the window's × button (not Ctrl-C): the Leonardo
needs the clean close to drop DTR, see docs/context.md.

The setup list, scripts and icons all come from readers/setups.py.
Needs tkinter (bundled with python.org installers; Linux: sudo apt install
python3-tk; Homebrew: brew install python-tk) and pyserial (for the port list).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from setups import SETUPS, GROUPS, GRID_COLS, Reader, Setup   # noqa: E402

SETTINGS = Path.home() / ".uniproto_launcher.json"
LOG_DIR = Path(tempfile.gettempdir()) / "uniproto_launcher"

# ── layout ────────────────────────────────────────────────────────────────────
ICON = 96
CELL_W, CELL_H = 146, 150
PAD = 12
BG = "#F4F4F2"
IDLE_HELP = ("Click an icon to start its reader.  Close reader windows with the "
             "window's × button, not Ctrl-C (the Leonardo needs a clean close).")


# ── pure helpers (no GUI; unit-tested) ────────────────────────────────────────
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


def script_path(reader: Reader, readers_dir: Path = HERE) -> Path:
    return Path(readers_dir) / reader.script


def reader_available(reader: Reader, readers_dir: Path = HERE) -> bool:
    return script_path(reader, readers_dir).is_file()


def build_command(reader: Reader, port: str, readers_dir: Path = HERE):
    cmd = [sys.executable, str(script_path(reader, readers_dir))]
    if reader.port and port:
        cmd += ["--port", port]
    return cmd + list(reader.args)


def last_log_line(path: Path) -> str:
    try:
        lines = [l.strip() for l in Path(path).read_text(errors="replace").splitlines() if l.strip()]
        return lines[-1] if lines else ""
    except OSError:
        return ""


def tint(hexcolor: str, f: float) -> str:
    """Blend a #rrggbb colour towards white by fraction f."""
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(int(c + (255 - c) * f) for c in (r, g, b))


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


def check_report(readers_dir: Path = HERE, icons_dir: Path = ROOT / "docs" / "icons" / "sm"):
    """Text table: which reader scripts / icons exist. Returns (text, n_missing)."""
    lines, missing = [f"{'setup':16s} {'reader script':32s} status", "-" * 62], 0
    for s in SETUPS:
        if not s.readers:
            lines.append(f"{s.id:16s} {'(no reader — firmware only)':32s} -")
        for r in s.readers:
            ok = reader_available(r, readers_dir)
            missing += (not ok)
            lines.append(f"{s.id:16s} {r.script:32s} {'ok' if ok else 'MISSING'}")
    no_icon = [s.id for s in SETUPS if not (Path(icons_dir) / f"{s.id}.png").is_file()]
    lines += ["", f"{missing} reader script(s) missing",
              f"icons missing: {no_icon if no_icon else 'none'}"]
    return "\n".join(lines), missing


@dataclass
class Proc:
    popen: subprocess.Popen
    setup: Setup
    reader: Reader
    port: str
    log_path: Path
    log_fh: object
    t0: float


# ── GUI ───────────────────────────────────────────────────────────────────────
def run_gui(port_hint="", readers_dir=HERE, icons_dir=ROOT / "docs" / "icons" / "sm"):
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        sys.exit("tkinter is not installed.\n"
                 "  Linux:    sudo apt install python3-tk\n"
                 "  Homebrew: brew install python-tk\n"
                 "  Windows/macOS python.org installers include it.")
    app = make_launcher_class(tk, ttk)(port_hint, Path(readers_dir), Path(icons_dir))
    app.mainloop()


def make_launcher_class(tk, ttk):
    class _Launcher(tk.Tk):
        def __init__(self, port_hint, readers_dir, icons_dir):
            super().__init__()
            self.readers_dir, self.icons_dir = readers_dir, icons_dir
            self.title("UniProto launcher")
            self.configure(bg=BG)
            self.resizable(False, False)
            self.procs: list[Proc] = []
            self.hover = -1
            self.selected = -1
            self._imgs = {}
            self.cells = []
            self._port_desc = {}

            self._build_header(port_hint)
            self._build_canvas()
            self._build_footer()
            self.refresh_ports(initial=True, hint=port_hint)
            self._draw_grid()
            self._refresh_states()
            self.protocol("WM_DELETE_WINDOW", self._quit)
            self.bind("<F5>", lambda e: self.refresh_ports())
            self.after(500, self._poll)
            self.after(4000, self._auto_refresh)

        # ── widgets ───────────────────────────────────────────────────────────
        def _build_header(self, hint):
            f = tk.Frame(self, bg=BG)
            f.pack(fill="x", padx=PAD, pady=(10, 2))
            tk.Label(f, text="Serial port", bg=BG, font=("Helvetica", 11, "bold")).pack(side="left")
            self.port_var = tk.StringVar(value=hint)
            self.combo = ttk.Combobox(f, textvariable=self.port_var, width=34)
            self.combo.pack(side="left", padx=8)
            self.combo.bind("<<ComboboxSelected>>", lambda e: self._port_changed())
            self.combo.bind("<FocusOut>", lambda e: self._port_changed())
            ttk.Button(f, text="Refresh", command=self.refresh_ports).pack(side="left")
            self.port_info = tk.Label(f, text="", bg=BG, fg="#666", font=("Helvetica", 10))
            self.port_info.pack(side="left", padx=10)

        def _build_canvas(self):
            w = PAD * 2 + GRID_COLS * CELL_W
            h = PAD * 2 + (len(SETUPS) // GRID_COLS) * CELL_H
            self.canvas = tk.Canvas(self, width=w, height=h, bg=BG, highlightthickness=0)
            self.canvas.pack(padx=0, pady=0)
            self.canvas.bind("<Motion>", self._on_motion)
            self.canvas.bind("<Leave>", lambda e: self._set_hover(-1))
            self.canvas.bind("<Button-1>", self._on_click)

        def _build_footer(self):
            leg = tk.Frame(self, bg=BG)
            leg.pack(fill="x", padx=PAD)
            for name, color in GROUPS:
                chip = tk.Canvas(leg, width=12, height=12, bg=BG, highlightthickness=0)
                chip.create_rectangle(0, 0, 12, 12, fill=color, outline="")
                chip.pack(side="left", padx=(0, 4))
                tk.Label(leg, text=name, bg=BG, fg="#555", font=("Helvetica", 9)).pack(side="left", padx=(0, 14))

            self.alt = tk.Frame(self, bg=BG)
            self.alt.pack(fill="x", padx=PAD, pady=(8, 0))

            self.status_var = tk.StringVar(value=IDLE_HELP)
            self.status = tk.Label(self, textvariable=self.status_var, bg=BG, fg="#333",
                                   anchor="w", justify="left", wraplength=GRID_COLS * CELL_W - 10,
                                   font=("Helvetica", 10))
            self.status.pack(fill="x", padx=PAD, pady=(6, 10))

        # ── ports ─────────────────────────────────────────────────────────────
        def refresh_ports(self, initial=False, hint=""):
            ports = find_ports()
            self._port_desc = {d: desc for d, desc, _ in ports}
            self.combo["values"] = [d for d, _, _ in ports]
            cur = self.port_var.get().strip()
            if initial and not cur:
                saved = load_settings().get("port", "")
                if saved in self._port_desc:
                    cur = saved
                else:
                    likely = [d for d, _, lk in ports if lk]
                    cur = likely[0] if likely else (ports[0][0] if ports else "")
                self.port_var.set(cur)
            self._port_changed(save=False)
            if not initial:
                self.say(f"{len(ports)} serial port(s) found." if ports
                         else "No serial ports found — plug in the board, then Refresh (F5).")

        def _auto_refresh(self):
            try:
                ports = find_ports()
                self._port_desc = {d: desc for d, desc, _ in ports}
                self.combo["values"] = [d for d, _, _ in ports]   # list only; keeps your text
                self._port_changed(save=False)
            finally:
                self.after(4000, self._auto_refresh)

        def _port_changed(self, save=True):
            p = self.port_var.get().strip()
            self.port_info.config(text=self._port_desc.get(p, "" if p in ("", None) else "(not in port list)"))
            if save and p:
                save_settings({"port": p})

        # ── grid drawing ──────────────────────────────────────────────────────
        def _icon(self, setup):
            path = self.icons_dir / f"{setup.id}.png"
            if setup.id not in self._imgs:
                try:
                    self._imgs[setup.id] = tk.PhotoImage(file=str(path))
                except tk.TclError:
                    self._imgs[setup.id] = None
            return self._imgs[setup.id]

        def _cell_xy(self, i):
            return PAD + (i % GRID_COLS) * CELL_W, PAD + (i // GRID_COLS) * CELL_H

        def _draw_grid(self):
            c = self.canvas
            for i, s in enumerate(SETUPS):
                x0, y0 = self._cell_xy(i)
                color = GROUPS[s.group][1]
                bg = c.create_rectangle(x0 + 4, y0 + 4, x0 + CELL_W - 4, y0 + CELL_H - 4,
                                        fill="white", outline="#DDDDD8", width=1)
                cx = x0 + CELL_W // 2
                img = self._icon(s)
                if img:
                    c.create_image(cx, y0 + 12 + ICON // 2, image=img)
                else:
                    c.create_rectangle(cx - ICON // 2, y0 + 12, cx + ICON // 2, y0 + 12 + ICON,
                                       fill=color, outline="")
                    c.create_text(cx, y0 + 12 + ICON // 2, text=s.id, fill="white",
                                  font=("Helvetica", 9, "bold"), width=ICON - 8)
                c.create_text(cx, y0 + 12 + ICON + 14, text=s.title,
                              font=("Helvetica", 11, "bold"), fill="#222")
                c.create_text(cx, y0 + 12 + ICON + 30, text=s.tagline,
                              font=("Helvetica", 9), fill="#777", width=CELL_W - 14)
                dot = c.create_oval(x0 + CELL_W - 26, y0 + 12, x0 + CELL_W - 12, y0 + 26,
                                    fill="#2EB872", outline="white", width=2, state="hidden")
                badge = c.create_text(cx, y0 + 12 + ICON - 8, text="no script",
                                      font=("Helvetica", 8, "bold"), fill="white",
                                      state="hidden")
                badge_bg = c.create_rectangle(cx - 30, y0 + 12 + ICON - 16, cx + 30,
                                              y0 + 12 + ICON, fill="#C0392B", outline="",
                                              state="hidden")
                c.tag_raise(badge)
                self.cells.append(dict(bg=bg, dot=dot, badge=badge, badge_bg=badge_bg,
                                       color=color))

        def _setup_state(self, s):
            """('running'|'ready'|'missing'|'info')"""
            if any(p.setup is s for p in self.procs):
                return "running"
            if not s.readers:
                return "info"
            return "ready" if any(reader_available(r, self.readers_dir) for r in s.readers) else "missing"

        def _refresh_states(self):
            c = self.canvas
            for i, s in enumerate(SETUPS):
                st = self._setup_state(s)
                cell = self.cells[i]
                c.itemconfigure(cell["dot"], state="normal" if st == "running" else "hidden")
                show_badge = "normal" if st == "missing" else "hidden"
                c.itemconfigure(cell["badge_bg"], state=show_badge)
                c.itemconfigure(cell["badge"], state=show_badge)
                self._paint_cell(i)

        def _paint_cell(self, i):
            cell = self.cells[i]
            hot = (i == self.hover)
            sel = (i == self.selected)
            self.canvas.itemconfigure(
                cell["bg"],
                fill=tint(cell["color"], 0.90) if sel else "white",
                outline=cell["color"] if (hot or sel) else "#DDDDD8",
                width=3 if hot else (2 if sel else 1))

        # ── interaction ───────────────────────────────────────────────────────
        def _index_at(self, x, y):
            col, row = (x - PAD) // CELL_W, (y - PAD) // CELL_H
            if 0 <= col < GRID_COLS and row >= 0:
                i = int(row) * GRID_COLS + int(col)
                if 0 <= i < len(SETUPS):
                    return i
            return -1

        def _set_hover(self, i):
            if i == self.hover:
                return
            old, self.hover = self.hover, i
            if old >= 0:
                self._paint_cell(old)
            if i >= 0:
                self._paint_cell(i)
                s = SETUPS[i]
                names = ", ".join(r.script for r in s.readers) or "no reader"
                env = s.env or "python only"
                self.say(f"{s.title} — {s.tagline}   |   board: {s.board}   |   env: {env}   |   {names}")
                st = self._setup_state(s)
                self.canvas.config(cursor="hand2" if st in ("ready", "running", "info") else "arrow")
            else:
                self.say(IDLE_HELP)
                self.canvas.config(cursor="arrow")

        def _on_motion(self, e):
            self._set_hover(self._index_at(e.x, e.y))

        def _on_click(self, e):
            i = self._index_at(e.x, e.y)
            if i >= 0:
                self.click_setup(i)

        def click_setup(self, i):
            """What a click does — also callable from tests."""
            s = SETUPS[i]
            old, self.selected = self.selected, i
            if old >= 0:
                self._paint_cell(old)
            self._paint_cell(i)
            self._show_readers(s)
            if not s.readers:
                self.say(s.note or "This setup has no Python reader.")
                return
            avail = [r for r in s.readers if reader_available(r, self.readers_dir)]
            if not avail:
                self.say(f"✗ {s.readers[0].script} not found in {self.readers_dir}. "
                         f"Add the script or fix the name in readers/setups.py.", err=True)
                return
            self.launch(s, avail[0])

        def _show_readers(self, s):
            for w in self.alt.winfo_children():
                w.destroy()
            if not s.readers:
                return
            tk.Label(self.alt, text=f"{s.title}:", bg=BG, font=("Helvetica", 10, "bold")).pack(side="left")
            for r in s.readers:
                ok = reader_available(r, self.readers_dir)
                ttk.Button(self.alt, text=r.label, state="normal" if ok else "disabled",
                           command=lambda r=r, s=s: self.launch(s, r)).pack(side="left", padx=4)

        # ── launching ─────────────────────────────────────────────────────────
        def port_holder(self):
            return next((p for p in self.procs if p.reader.port), None)

        def launch(self, s: Setup, r: Reader):
            if any(p.reader is r for p in self.procs):
                self.say(f"{r.script} is already running.")
                return None
            port = self.port_var.get().strip()
            if r.port:
                if not port:
                    self.say("Select a serial port first (top left).", err=True)
                    self.combo.focus_set()
                    return None
                busy = self.port_holder()
                if busy:
                    self.say(f"{busy.reader.script} still holds {busy.port}. Close its window "
                             f"(× button) before starting {r.script}.", err=True)
                    return None
            cmd = build_command(r, port, self.readers_dir)
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = LOG_DIR / f"{Path(r.script).stem}.log"
            fh = open(log_path, "w")
            fh.write("$ " + " ".join(cmd) + "\n")
            fh.flush()
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            try:
                popen = subprocess.Popen(cmd, cwd=str(self.readers_dir), stdout=fh,
                                         stderr=subprocess.STDOUT, env=env)
            except OSError as ex:
                fh.close()
                self.say(f"✗ could not start {r.script}: {ex}", err=True)
                return None
            p = Proc(popen, s, r, port if r.port else "", log_path, fh, time.time())
            self.procs.append(p)
            where = f" on {port}" if r.port else ""
            self.say(f"▶ {r.script} started{where}.  Close its window (×) when done.")
            self._refresh_states()
            return p

        def _poll(self):
            done = [p for p in self.procs if p.popen.poll() is not None]
            for p in done:
                self.procs.remove(p)
                p.log_fh.close()
                rc = p.popen.returncode
                if rc == 0:
                    self.say(f"{p.reader.script} closed.")
                else:
                    tail = last_log_line(p.log_path)
                    self.say(f"✗ {p.reader.script} exited with code {rc}: {tail}\n(full log: {p.log_path})",
                             err=True)
            if done:
                self._refresh_states()
            self.after(500, self._poll)

        # ── misc ──────────────────────────────────────────────────────────────
        def say(self, text, err=False):
            self.status_var.set(text)
            self.status.config(fg="#B03A2E" if err else "#333")

        def _quit(self):
            running = [p for p in self.procs if p.popen.poll() is None]
            if running:
                names = ", ".join(p.reader.script for p in running)
                print(f"[launcher] leaving running: {names}", flush=True)
            self.destroy()

    return _Launcher


def main():
    ap = argparse.ArgumentParser(description="UniProto launcher")
    ap.add_argument("--port", default="", help="preselect a serial port")
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
    run_gui(args.port)


if __name__ == "__main__":
    main()
