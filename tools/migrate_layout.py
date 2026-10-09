#!/usr/bin/env python3
"""
migrate_layout.py — one-time restructure of the repository.

  BEFORE                                          AFTER
  src_<name>/main.cpp  (one folder per setup)     src/<name>/main.cpp
  readers/launcher.py, dashboard.py, setups.py    dashboard/launcher.py, dashboard.py, setups.py
  tools/uniproto_sim.py                           dashboard/uniproto_sim.py
  platformio.ini   src_dir = .                    src_dir = src
                   build_src_filter = -<*> +<src_NAME/>      -<*> +<NAME/>
  readers/ (the per-setup plotters)               unchanged

  python tools/migrate_layout.py            show the plan and every diff — changes NOTHING
  python tools/migrate_layout.py --apply    do it

Safety
  * dry run unless you pass --apply
  * in a git repository it refuses to run on a dirty working tree (commit first, ideally on a
    new branch:  git checkout -b restructure)  and moves with `git mv`, so history follows
  * outside git it keeps platformio.ini.bak
  * platformio.ini is re-read afterwards: every [env] must select a folder that exists
  * documentation (*.md) is rewritten; mentions inside code (.py .cpp .h …) are only REPORTED
  * submodules / nested repositories (e.g. kinect/libfreenect) are never touched or scanned, and
    local changes inside them do not count as a dirty tree
  * running it twice is harmless ("already migrated")

After --apply, copy in the updated Python files (dashboard/*.py, tools/*.py, README.md) and
build one environment, e.g.  pio run -e dc_motor
"""
import argparse
import configparser
import difflib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE_SUFFIXES = {".cpp", ".c", ".ino", ".h", ".hpp"}
TEXT_SUFFIXES = {".py", ".cpp", ".c", ".ino", ".h", ".hpp", ".json", ".yml", ".yaml", ".toml", ".txt", ".cfg", ".ini"}
DASHBOARD_FILES = [
    ("readers/launcher.py", "dashboard/launcher.py"),
    ("readers/dashboard.py", "dashboard/dashboard.py"),
    ("readers/setups.py", "dashboard/setups.py"),
    ("tools/uniproto_sim.py", "dashboard/uniproto_sim.py"),
]
OLD_COMMENT = ("; Set project root as the source root so build_src_filter patterns\n"
               "; match src_<name>/ folders directly.\n")
NEW_COMMENT = ("; All firmware lives in src/<name>/ — one folder per setup.\n"
               "; Each [env] picks its folder with  build_src_filter = -<*> +<name/>\n")
OLD_EXCLUDE = "Also exclude lib/ and readers/ so only src_<name>/ is compiled."
NEW_EXCLUDE = "(lib/, readers/, dashboard/ … are outside src_dir, so they are never compiled.)"


# ── helpers ───────────────────────────────────────────────────────────────────
class Git:
    def __init__(self, root):
        self.root = root
        r = self.run("rev-parse", "--is-inside-work-tree")
        self.ok = r.returncode == 0 and r.stdout.strip() == "true"

    def run(self, *args):
        try:
            return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        except FileNotFoundError:
            return subprocess.CompletedProcess(args, 127, "", "git not installed")

    def clean(self):
        """Clean = nothing to commit in THIS repository. Changes inside a submodule (e.g. a patched or
        built libfreenect) are not ours to commit and are not touched by the restructure."""
        return self.run("status", "--porcelain", "--ignore-submodules=dirty").stdout.strip() == ""

    def submodules(self):
        """[(path, has_local_changes)] for every submodule."""
        out = self.run("ls-files", "--stage").stdout.splitlines()
        paths = [l.split("\t", 1)[1] for l in out if l.startswith("160000")]
        full = set(self.run("status", "--porcelain").stdout.splitlines())
        dirty = full - set(self.run("status", "--porcelain", "--ignore-submodules=dirty").stdout.splitlines())
        return [(p, any(l[3:].strip() == p for l in dirty)) for p in paths]

    def tracked(self, rel):
        return bool(self.run("ls-files", "--", rel).stdout.strip())

    def mv(self, src, dst):
        return self.run("mv", src, dst).returncode == 0


def walk_files(root, suffixes):
    """Text files under root, skipping hidden folders, virtual environments and build output."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv", "env"}
                       and not (Path(dirpath) / d / ".git").exists()]       # a nested repo is somebody else's code
        for f in filenames:
            p = Path(dirpath) / f
            if p.suffix.lower() in suffixes:
                yield p


def has_sources(folder):
    return any(p.suffix.lower() in SOURCE_SUFFIXES for p in folder.rglob("*") if p.is_file())


def names_pattern(names):
    return "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True))


def rewrite_ini(text, names):
    """platformio.ini: src_dir = src and <src_NAME/> -> <NAME/> in every filter."""
    text = text.replace(OLD_COMMENT, NEW_COMMENT)
    text = text.replace(OLD_EXCLUDE, NEW_EXCLUDE)
    text = text.replace("src_<name>/", "src/<name>/")
    # [platformio] section: set / add src_dir
    m = re.search(r"(?m)^\[platformio\][ \t]*$", text)
    if m:
        nxt = re.search(r"(?m)^\[", text[m.end():])
        end = m.end() + (nxt.start() if nxt else len(text) - m.end())
        section = text[m.end():end]
        if re.search(r"(?m)^[ \t]*src_dir[ \t]*=", section):
            section = re.sub(r"(?m)^([ \t]*src_dir[ \t]*=[ \t]*).*$", r"\1src", section)
        else:
            section = "\nsrc_dir = src" + section
        text = text[:m.end()] + section + text[end:]
    else:
        text = "[platformio]\nsrc_dir = src\n\n" + text
    # filters:  <src_NAME/>  <src_NAME>  <src_NAME/file.cpp>
    alt = names_pattern(names)
    if alt:
        text = re.sub(rf"<src_({alt})(?=[/>])", r"<\1", text)
    return text


def rewrite_md(text, names):
    text = text.replace("src_<name>/", "src/<name>/").replace("src_<setup>/", "src/<setup>/")
    alt = names_pattern(names)
    if alt:
        text = re.sub(rf"(?<![A-Za-z0-9_])src_({alt})/", r"src/\1/", text)
    return text


def leftover_mentions(text, names):
    """Lines that still mention an old folder name (src_NAME) — for the human to look at."""
    alt = names_pattern(names)
    if not alt:
        return []
    pat = re.compile(rf"(?<![A-Za-z0-9_])src_({alt})\b")
    return [(i + 1, line.strip()) for i, line in enumerate(text.splitlines()) if pat.search(line)]


def verify_ini(root):
    """Re-read platformio.ini: src_dir must be 'src' and every env must select an existing folder."""
    ini = root / "platformio.ini"
    cp = configparser.ConfigParser(interpolation=None, strict=False, comment_prefixes=(";", "#"),
                                   inline_comment_prefixes=None)
    cp.read(ini, encoding="utf-8")
    problems = []
    if cp.get("platformio", "src_dir", fallback="").strip() != "src":
        problems.append("[platformio] src_dir is not 'src'")
    common = cp.get("env", "build_src_filter", fallback="")
    checked = 0
    for sec in cp.sections():
        if not sec.startswith("env:"):
            continue
        flt = cp.get(sec, "build_src_filter", fallback=common)
        wanted = re.findall(r"\+<([A-Za-z0-9_]+)[/>]", flt)
        if not wanted:
            problems.append(f"[{sec}] selects no folder (build_src_filter = {flt.strip()!r})")
        for name in wanted:
            d = root / "src" / name
            if not (d.is_dir() and has_sources(d)):
                problems.append(f"[{sec}] selects src/{name}/, which does not exist or has no sources")
        checked += 1
    return checked, problems


def unified(path, old, new, root):
    rel = path.relative_to(root).as_posix()
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}", n=1))


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="restructure: src_<name>/ -> src/<name>/, dashboard files -> dashboard/")
    ap.add_argument("--apply", action="store_true", help="make the changes (default: only show the plan)")
    ap.add_argument("--force", action="store_true", help="run even if the git working tree is not clean")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="repository root")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    ini = root / "platformio.ini"
    if not ini.is_file():
        sys.exit(f"No platformio.ini in {root} — run this from the repository (or pass --root).")

    git = Git(root)
    src_dirs = sorted(p for p in root.glob("src_*") if p.is_dir())
    movable = [p for p in src_dirs if has_sources(p)]
    skipped = [p for p in src_dirs if p not in movable]
    names = [p.name[len("src_"):] for p in movable]
    dash_moves = [(a, b) for a, b in DASHBOARD_FILES if (root / a).is_file() and not (root / b).exists()]

    src_new = root / "src"
    if not movable and not dash_moves:
        ok_dirs = [d for d in src_new.iterdir() if d.is_dir()] if src_new.is_dir() else []
        print("Nothing to do — already migrated." if ok_dirs else "Nothing to do — no src_<name>/ folders found.")
        checked, problems = verify_ini(root)
        print(f"platformio.ini: {checked} environment(s) checked, " + ("all select an existing folder." if not problems else "PROBLEMS:"))
        for p in problems:
            print("  ✗", p)
        return 1 if problems else 0

    # ── pre-flight ──
    errors = []
    if src_new.exists():
        leftovers = [p.name for p in src_new.iterdir() if p.name not in names]
        if leftovers:
            errors.append(f"src/ already exists and contains: {', '.join(sorted(leftovers))}. "
                          f"Move or remove those first (PlatformIO's default src/ may hold a stray main.cpp).")
    for n in names:
        if (src_new / n).exists():
            errors.append(f"src/{n} already exists — would be overwritten")
    for a, b in DASHBOARD_FILES:
        if (root / a).is_file() and (root / b).exists():
            errors.append(f"{b} already exists — {a} would be overwritten")
    if git.ok and not git.clean() and not args.force:
        errors.append("the git working tree has uncommitted changes. Commit or stash them (or use --force). "
                      "Tip: git checkout -b restructure")
    if errors:
        print("Cannot continue:")
        for e in errors:
            print("  ✗", e)
        return 1

    # ── plan ──
    print(f"Repository: {root}   ({'git' if git.ok else 'no git — will keep platformio.ini.bak'})")
    if git.ok:
        for path, dirty in git.submodules():
            print(f"Submodule {path}: left alone" + (" (it has local changes — they stay exactly as they are)" if dirty else ""))
    print(f"\n1. Firmware folders → src/   ({len(movable)})")
    for p in movable:
        print(f"   {p.name}/  →  src/{p.name[4:]}/")
    for p in skipped:
        print(f"   (left alone: {p.name}/ has no source files)")
    print(f"\n2. Dashboard files → dashboard/   ({len(dash_moves)})")
    for a, b in dash_moves:
        print(f"   {a}  →  {b}")
    if not dash_moves:
        print("   (none found in readers/ or tools/)")

    old_ini = ini.read_text(encoding="utf-8")
    new_ini = rewrite_ini(old_ini, names)
    print("\n3. platformio.ini")
    d = unified(ini, old_ini, new_ini, root)
    print("".join("   " + l for l in d.splitlines(True)) if d else "   (no change)")
    left = leftover_mentions(new_ini, names)

    md_changes = []
    for p in walk_files(root, {".md"}):
        old = p.read_text(encoding="utf-8", errors="replace")
        new = rewrite_md(old, names)
        if new != old:
            md_changes.append((p, old, new))
    print(f"\n4. Documentation — {len(md_changes)} file(s) mention the old folders")
    for p, old, new in md_changes:
        n = sum(1 for a, b in zip(old.splitlines(), new.splitlines()) if a != b)
        print(f"   {p.relative_to(root).as_posix()}: {n} line(s)")

    code_hits = []
    for p in walk_files(root, TEXT_SUFFIXES):
        if p == ini or p == Path(__file__).resolve():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for ln, line in leftover_mentions(text, names):
            code_hits.append((p.relative_to(root).as_posix(), ln, line))
    print(f"\n5. Mentions in code/config that this script does NOT change — please look: {len(code_hits) + len(left)}")
    for ln, line in left:
        print(f"   platformio.ini:{ln}: {line[:100]}")
    for f, ln, line in code_hits[:30]:
        print(f"   {f}:{ln}: {line[:100]}")
    if len(code_hits) > 30:
        print(f"   … and {len(code_hits) - 30} more")

    if not args.apply:
        print("\nDry run — nothing was changed. Run again with --apply to do it.")
        return 0

    # ── apply ──
    print("\nApplying …")
    src_new.mkdir(exist_ok=True)

    def move(rel_a, rel_b):
        a, b = root / rel_a, root / rel_b
        b.parent.mkdir(parents=True, exist_ok=True)
        if git.ok and git.tracked(rel_a) and git.mv(rel_a, rel_b):
            return "git mv"
        shutil.move(str(a), str(b))
        return "move" if not git.ok else "move (not tracked by git)"

    for p in movable:
        how = move(p.name, f"src/{p.name[4:]}")
        print(f"   {how:26s} {p.name} → src/{p.name[4:]}")
    for a, b in dash_moves:
        how = move(a, b)
        print(f"   {how:26s} {a} → {b}")
    if not git.ok:
        shutil.copy2(ini, root / "platformio.ini.bak")
        print("   saved                      platformio.ini.bak")
    ini.write_text(new_ini, encoding="utf-8")
    print("   rewritten                  platformio.ini")
    for p, old, new in md_changes:
        p.write_text(new, encoding="utf-8")
        print(f"   rewritten                  {p.relative_to(root).as_posix()}")

    checked, problems = verify_ini(root)
    print(f"\nVerification: {checked} environment(s) in platformio.ini, " +
          ("each selects an existing src/<name>/ folder." if not problems else "PROBLEMS:"))
    for pr in problems:
        print("  ✗", pr)
    print("\nNext:\n"
          "  1. copy in the updated files: dashboard/*.py, tools/make_icons.py, tools/update_readme_grid.py, README.md\n"
          "  2. python dashboard/launcher.py --check          (reader scripts found?)\n"
          "  3. pio run -e dc_motor                           (or any env: does it still build?)\n"
          "  4. git status  /  git commit -m 'Restructure: src/, dashboard/'")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())