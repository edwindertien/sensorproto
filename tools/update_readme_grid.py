#!/usr/bin/env python3
"""
update_readme_grid.py — keep the README icon grid in sync with dashboard/setups.py.

  python tools/update_readme_grid.py           rewrite the grid in README.md
  python tools/update_readme_grid.py --check   report drift, change nothing

The grid lives between these two markers in README.md:
    <!-- GRID:START -->
    <!-- GRID:END -->

--check verifies that
  * every setup has an   <a id="<anchor>"></a>   section in README.md
  * every setup has an icon in docs/icons/ (README) and docs/icons/sm/ (launcher)
  * the grid in README.md equals what this script would generate
Exit status is 1 if anything is out of date, so it can run in CI / a git hook.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
from setups import SETUPS, GROUPS, GRID_COLS   # noqa: E402

README = ROOT / "README.md"
START, END = "<!-- GRID:START -->", "<!-- GRID:END -->"
ICON_W = 96
SQUARES = ["🟦", "🟩", "🟧", "🟪"]       # blue, teal(≈green), amber, purple


def build_grid() -> str:
    rows = []
    for r in range(0, len(SETUPS), GRID_COLS):
        cells = []
        for s in SETUPS[r:r + GRID_COLS]:
            cells.append(
                f'<td align="center" valign="top" width="{100 // GRID_COLS}%">'
                f'<a href="#{s.anchor}"><img src="docs/icons/{s.id}.png" width="{ICON_W}" '
                f'alt="{s.title}"><br><b>{s.title}</b></a><br><sub>{s.tagline}</sub></td>')
        rows.append("<tr>\n" + "\n".join(cells) + "\n</tr>")
    legend = "  ·  ".join(f"{SQUARES[i]} {name}" for i, (name, _) in enumerate(GROUPS))
    return "<table>\n" + "\n".join(rows) + f"\n</table>\n\n<sub>Rows: {legend}</sub>"


def splice(text: str, grid: str) -> str:
    if START not in text or END not in text:
        sys.exit(f"README.md needs the markers {START} and {END}")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n{grid}\n{END}{tail}"


def check(text: str) -> int:
    problems = []
    anchors = set(re.findall(r'<a id="([\w-]+)"></a>', text))
    for s in SETUPS:
        if s.anchor not in anchors:
            problems.append(f"README has no section  <a id=\"{s.anchor}\"></a>  for '{s.title}'")
        for sub in ("", "sm/"):
            if not (ROOT / "docs" / "icons" / f"{sub}{s.id}.png").is_file():
                problems.append(f"missing icon docs/icons/{sub}{s.id}.png")
    stale = anchors - {s.anchor for s in SETUPS}
    for a in sorted(stale):
        problems.append(f"README anchor '{a}' is not in setups.py (renamed or removed?)")
    if START in text and END in text:
        cur = text.split(START, 1)[1].split(END, 1)[0].strip()
        if cur != build_grid().strip():
            problems.append("grid in README.md is out of date — run tools/update_readme_grid.py")
    else:
        problems.append("README.md has no GRID markers")
    for p in problems:
        print("  ✗", p)
    print("README is in sync with setups.py" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = README.read_text(encoding="utf-8")
    if args.check:
        sys.exit(check(text))
    README.write_text(splice(text, build_grid()), encoding="utf-8")
    print(f"grid updated: {len(SETUPS)} setups, {len(SETUPS) // GRID_COLS} rows x {GRID_COLS} columns")


if __name__ == "__main__":
    main()
