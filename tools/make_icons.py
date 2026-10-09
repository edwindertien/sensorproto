#!/usr/bin/env python3
"""
make_icons.py — draw one pictogram tile per setup in dashboard/setups.py.

Output (relative to the repo root):
  docs/icons/<id>.png       128 px   used by README.md
  docs/icons/sm/<id>.png     96 px   used by dashboard/launcher.py
  docs/icons/_sheet.png      preview of the whole grid

Only needs matplotlib + numpy. Re-run after changing setups.py or a glyph:
  python tools/make_icons.py

Want a photo instead of a pictogram? Drop your own PNG with the same file
name into docs/icons/ (and docs/icons/sm/) — the README and launcher just
load whatever file is there. Just don't re-run this script over it.
"""
import math
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Polygon

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
from setups import SETUPS, GROUPS, GRID_COLS   # noqa: E402

FIG_IN = 1.28                    # figure size in inches -> 128 px at dpi 100
SIZES = {"": 100, "sm": 75}      # sub-folder -> dpi  (128 px / 96 px)


# ── tiny drawing toolkit (0..100 coordinate box, y up) ────────────────────────
class G:
    def __init__(self, ax, bg):
        self.ax, self.bg = ax, bg

    def _c(self, a=1.0, color=None):
        return color if color else (1, 1, 1, a)

    def line(self, pts, lw=4, a=1.0, color=None, ls="-"):
        xs, ys = zip(*pts)
        self.ax.plot(xs, ys, color=self._c(a, color), lw=lw, linestyle=ls,
                     solid_capstyle="round", solid_joinstyle="round",
                     dash_capstyle="round")

    def circle(self, c, r, lw=4, fill=0.0, a=1.0, color=None):
        self.ax.add_patch(Circle(
            c, r, lw=lw,
            fc=self._c(fill, color) if fill else "none",
            ec=self._c(a, color) if lw else "none"))

    def rect(self, x, y, w, h, r=3, lw=4, fill=0.0, a=1.0, color=None):
        self.ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", lw=lw,
            fc=self._c(fill, color) if fill else "none",
            ec=self._c(a, color) if lw else "none"))

    def poly(self, pts, lw=0, fill=1.0, a=1.0, color=None):
        self.ax.add_patch(Polygon(
            pts, closed=True, lw=lw, joinstyle="round",
            fc=self._c(fill, color) if fill else "none",
            ec=self._c(a, color) if lw else "none"))

    def head(self, tip, ang_deg, size=9):
        """Filled arrow head with its tip at `tip`, pointing along ang_deg."""
        a = math.radians(ang_deg)
        back = a + math.pi
        p1 = (tip[0] + size * math.cos(back + 0.45), tip[1] + size * math.sin(back + 0.45))
        p2 = (tip[0] + size * math.cos(back - 0.45), tip[1] + size * math.sin(back - 0.45))
        self.poly([tip, p1, p2])

    def polar(self, c, r, deg):
        a = math.radians(deg)
        return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))


# ── 24 glyphs ─────────────────────────────────────────────────────────────────
def bldc_gimbal(g):
    g.circle((50, 50), 30)
    for k in range(6):
        g.line([g.polar((50, 50), 30, 60 * k + 30), g.polar((50, 50), 40, 60 * k + 30)], lw=7)
    g.circle((50, 50), 14, lw=0, fill=1)
    g.line([(50, 50), g.polar((50, 50), 9, 55)], lw=4, color=g.bg)


def bldc_servo(g):
    g.rect(12, 32, 52, 36, r=6)
    g.circle((72, 50), 10, lw=0, fill=1)
    g.circle((72, 50), 3.5, lw=0, fill=1, color=g.bg)
    g.line([(72, 50), (90, 72)], lw=7)
    for x in (24, 34, 44):
        g.line([(x, 32), (x, 17)], lw=3, a=0.85)


def dc_motor(g):
    g.rect(8, 36, 44, 28, r=6)
    g.rect(52, 42, 8, 16, r=2, lw=0, fill=1)
    g.line([(60, 50), (68, 50)], lw=4)
    g.circle((80, 50), 9, lw=3)
    for k in range(8):
        g.line([g.polar((80, 50), 9, 45 * k), g.polar((80, 50), 14, 45 * k)], lw=4)


def dual_motor(g):
    for cx in (22, 78):
        g.circle((cx, 50), 15)
        g.circle((cx, 50), 4, lw=0, fill=1)
    g.line([(37, 50), (42, 50), (46, 63), (52, 37), (58, 63), (62, 50), (63, 50)], lw=3.5)


def stepper(g):
    g.rect(18, 18, 64, 64, r=8)
    g.circle((50, 50), 17, lw=3)
    for k in range(12):
        g.line([g.polar((50, 50), 21, 30 * k), g.polar((50, 50), 25, 30 * k)], lw=3)
    g.line([(50, 50), (50, 66)], lw=5)
    for dx in (-1, 1):
        for dy in (-1, 1):
            g.circle((50 + 36 * dx, 50 + 36 * dy), 2.6, lw=0, fill=1)


def pneumatic(g):
    g.rect(10, 36, 50, 26, r=4)
    g.rect(24, 40, 7, 18, r=1.5, lw=0, fill=1)
    g.line([(60, 49), (86, 49)], lw=5)
    g.rect(84, 38, 7, 22, r=2, lw=0, fill=1)
    for (x, y, r) in ((16, 76, 4), (31, 82, 3), (45, 74, 3.6)):
        g.circle((x, y), r, lw=2.5)


def lvdt(g):
    g.rect(10, 34, 80, 32, r=6, lw=3.5)
    for x0 in (16, 44, 72):
        for k in range(4):
            g.line([(x0 + 4 * k, 38), (x0 + 4 * k, 62)], lw=2.6, a=0.75)
    g.rect(24, 45, 56, 10, r=5, lw=0, fill=1)
    g.line([(30, 20), (70, 20)], lw=3.5)
    g.head((26, 20), 180, 8)
    g.head((74, 20), 0, 8)


def synchro(g):
    g.circle((50, 50), 34, lw=3.5)
    for a in (90, 210, 330):
        end = g.polar((50, 50), 24, a)
        g.line([(50, 50), end], lw=4.5)
        g.circle(end, 4.5, lw=0, fill=1)
    g.circle((50, 50), 5.5, lw=0, fill=1)


def optical_mouse(g):
    g.rect(27, 10, 46, 80, r=22, lw=4)
    g.line([(27, 64), (73, 64)], lw=3)
    g.line([(50, 64), (50, 90)], lw=3)
    alphas = [[.95, .35, .65], [.45, .9, .3], [.7, .25, .85]]
    for j in range(3):
        for i in range(3):
            g.rect(36 + i * 10, 22 + j * 11, 8, 9, r=1, lw=0, fill=alphas[j][i])


def qtr8(g):
    alphas = [.28, .28, .5, 1, 1, .5, .28, .28]
    for i, a in enumerate(alphas):
        g.rect(8 + i * 10.6, 56, 8.4, 22, r=2, lw=0, fill=a)
    g.line([(8, 40), (92, 40)], lw=2.5, a=0.5, ls=(0, (1, 3)))
    g.line([(40, 24), (60, 24)], lw=8)


def accelerometer(g):
    o = (42, 44)
    g.line([o, (84, 44)], lw=4.5); g.head((90, 44), 0, 11)
    g.line([o, (42, 84)], lw=4.5); g.head((42, 90), 90, 11)
    g.line([o, (20, 22)], lw=4.5); g.head((13, 15), 225, 11)
    g.rect(35, 37, 14, 14, r=3, lw=0, fill=1)


def wiimote(g):
    g.rect(35, 6, 30, 88, r=10)
    g.line([(44, 78), (56, 78)], lw=4.5)
    g.line([(50, 72), (50, 84)], lw=4.5)
    g.circle((50, 56), 6.5, lw=0, fill=1)
    g.circle((43, 38), 3, lw=0, fill=0.8)
    g.circle((57, 38), 3, lw=0, fill=0.8)
    g.line([(42, 22), (58, 22)], lw=3, a=0.7)
    g.line([(44, 14), (56, 14)], lw=3, a=0.7)


def load_cell(g):
    g.rect(10, 42, 76, 18, r=5)
    g.circle((38, 51), 5, lw=3)
    g.circle((58, 51), 5, lw=3)
    g.rect(8, 30, 22, 12, r=2, lw=0, fill=1)
    g.line([(76, 90), (76, 70)], lw=5)
    g.head((76, 62), -90, 12)


def kitchen_scales(g):
    g.poly([(22, 60), (78, 60), (88, 18), (12, 18)], lw=4, fill=0)
    g.rect(14, 64, 72, 7, r=2.5, lw=0, fill=1)
    g.rect(36, 30, 28, 16, r=3, lw=0, fill=0.9)
    g.line([(42, 38), (58, 38)], lw=2.5, color=g.bg)
    g.circle((50, 84), 8, lw=3.5)


def cap_sense(g):
    g.line([(18, 40), (82, 40)], lw=7)
    g.line([(18, 62), (82, 62)], lw=7)
    g.line([(50, 40), (50, 18)], lw=4.5)
    g.line([(50, 62), (50, 84)], lw=4.5)
    for x in (30, 50, 70):
        g.line([(x, 45), (x, 57)], lw=2.5, a=0.6, ls=(0, (1, 2.4)))


def psd_distance(g):
    g.rect(6, 38, 24, 24, r=4)
    g.circle((14, 50), 3, lw=0, fill=1)
    g.circle((22, 50), 3, lw=0, fill=0.7)
    g.poly([(30, 47), (30, 53), (74, 68), (74, 32)], lw=0, fill=0.22)
    g.line([(30, 47), (74, 32)], lw=2.5, ls=(0, (1, 2.6)))
    g.line([(30, 53), (74, 68)], lw=2.5, ls=(0, (1, 2.6)))
    g.line([(82, 16), (82, 84)], lw=8)


def us_distance(g):
    g.rect(8, 30, 84, 40, r=7)
    for cx in (30, 70):
        g.circle((cx, 50), 14, lw=4)
        g.circle((cx, 50), 6, lw=0, fill=0.9)
    for x in (34, 44, 56, 66):
        g.line([(x, 30), (x, 18)], lw=3.5)


def sensor_shield(g):
    g.rect(8, 22, 84, 54, r=6)
    for i in range(8):
        g.rect(14 + i * 9.4, 76, 5.5, 8, r=1, lw=0, fill=1)
    g.rect(16, 36, 22, 24, r=3, lw=0, fill=0.9)
    xs = np.linspace(46, 84, 40)
    g.line(list(zip(xs, 48 + 8 * np.sin((xs - 46) / 38 * 4 * np.pi))), lw=3)


def biosensors(g):
    t = np.linspace(0, 2 * np.pi, 240)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    g.poly(list(zip(50 + 2.5 * x, 57 + 2.5 * y)), lw=0, fill=0.95)
    ecg = [(12, 40), (32, 40), (39, 52), (46, 24), (54, 60), (61, 40), (88, 40)]
    g.line(ecg, lw=8, a=1)
    g.line(ecg, lw=3.5, color=g.bg)


def wind_speed(g):
    g.line([(50, 52), (50, 8)], lw=5)
    for a in (90, 210, 330):
        end = g.polar((50, 52), 27, a)
        g.line([(50, 52), end], lw=4)
        g.circle(end, 9.5, lw=0, fill=0.95)
    g.circle((50, 52), 5, lw=0, fill=1)


def piezo_serial(g):
    g.rect(8, 24, 84, 52, r=7, lw=3.5)
    xs = np.linspace(14, 86, 120)
    env = np.exp(-(xs - 26) / 14.0)
    y = np.where(xs < 26, 0, env * np.sin((xs - 26) * 0.9))
    g.line(list(zip(xs, 50 + 20 * y)), lw=3.5)
    g.circle((16, 50), 2.5, lw=0, fill=1)


def piezo_midi(g):
    g.circle((50, 50), 36, lw=4)
    for a in (180, 135, 90, 45, 0):
        g.circle(g.polar((50, 50), 21, a), 4.2, lw=0, fill=1)
    g.rect(43, 6, 14, 9, r=2, lw=0, fill=1)
    g.line([(30, 28), (70, 28)], lw=3, a=0.55)


def lidar(g):
    rs = [30, 33, 38, 42, 38, 31, 27, 33, 41, 43, 38, 33, 30, 27, 30, 32]
    for k, r in enumerate(rs):
        a = 360 / len(rs) * k
        e = g.polar((50, 50), r, a)
        g.line([g.polar((50, 50), 9, a), e], lw=1.6, a=0.4)
        g.circle(e, 2.8, lw=0, fill=1)
    g.poly([(50, 50), g.polar((50, 50), 40, 20), g.polar((50, 50), 40, 55)], lw=0, fill=0.28)
    g.circle((50, 50), 6, lw=0, fill=1)


def kinect(g):
    g.rect(5, 38, 90, 26, r=10, lw=3.5, fill=0.12)
    g.circle((22, 51), 6.5, lw=3.2)
    g.circle((50, 51), 6.5, lw=3.2)
    g.circle((78, 51), 6.5, lw=3.2)
    g.circle((50, 51), 2.2, lw=0, fill=1)
    g.rect(43, 22, 14, 16, r=2, lw=0, fill=1)
    g.line([(30, 20), (70, 20)], lw=5)


GLYPHS = {f.__name__: f for f in (
    bldc_gimbal, bldc_servo, dc_motor, dual_motor, stepper, pneumatic,
    lvdt, synchro, optical_mouse, qtr8, accelerometer, wiimote,
    load_cell, kitchen_scales, cap_sense, psd_distance, us_distance, sensor_shield,
    biosensors, wind_speed, piezo_serial, piezo_midi, lidar, kinect)}


# ── rendering ─────────────────────────────────────────────────────────────────
def draw_tile(ax, setup):
    color = GROUPS[setup.group][1]
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.set_aspect("equal"); ax.axis("off")
    ax.add_patch(FancyBboxPatch((1, 1), 98, 98, boxstyle="round,pad=0,rounding_size=17",
                                fc=color, ec="none"))
    GLYPHS[setup.id](G(ax, color))


def render_icons():
    missing = [s.id for s in SETUPS if s.id not in GLYPHS]
    if missing:
        sys.exit(f"no glyph defined for: {missing}")
    for sub, dpi in SIZES.items():
        out = ROOT / "docs" / "icons" / sub
        out.mkdir(parents=True, exist_ok=True)
        for s in SETUPS:
            fig = plt.figure(figsize=(FIG_IN, FIG_IN))
            ax = fig.add_axes([0, 0, 1, 1])
            draw_tile(ax, s)
            fig.savefig(out / f"{s.id}.png", dpi=dpi, transparent=True)
            plt.close(fig)
    print(f"wrote {len(SETUPS)} icons x {len(SIZES)} sizes -> {ROOT / 'docs' / 'icons'}")


def render_sheet():
    rows = len(SETUPS) // GRID_COLS
    fig, axes = plt.subplots(rows, GRID_COLS, figsize=(GRID_COLS * 1.6, rows * 1.85))
    fig.patch.set_facecolor("white")
    for ax, s in zip(axes.flat, SETUPS):
        draw_tile(ax, s)
        ax.set_title(s.title, fontsize=8, pad=3)
    fig.tight_layout(pad=0.6)
    fig.savefig(ROOT / "docs" / "icons" / "_sheet.png", dpi=110)
    plt.close(fig)
    print("wrote docs/icons/_sheet.png")


if __name__ == "__main__":
    render_icons()
    render_sheet()
