#!/usr/bin/env python3
"""
SessionStart gap-detection scanner — structural-risk reporter for Claude Code.

Runs once at session start. Scans the *uncommitted* working tree (the work
being created now) against the tracked tree (the established baseline) and
reports four classes of structural risk:

  1. Duplicate module/file creation  — new file whose basename already exists
                                        elsewhere in the tracked tree.
  2. Files outside approved root      — new file introducing a top-level dir
                                        not already part of the project.
  3. Parallel backend/frontend struct — new file with a parallel-impl naming
                                        smell (_new/_copy/_old/_final/...), or
                                        a second app-like structure tree.
  4. Stale PROJECT_STATE.md           — Last-run-at older than STALE_DAYS.

ANTI-HOLD: this scanner NEVER blocks. It prints observations and exits 0.
It reports; it does not gate. Any error fails open (exit 0, no output).
"""
import sys
import os
import re
import subprocess
from datetime import date, datetime

PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
STATE_FILE = os.path.join(PROJECT_DIR, ".claude", "memory", "PROJECT_STATE.md")
STALE_DAYS = 5

# Basenames that legitimately recur across packages — never a duplicate smell.
EXEMPT_BASENAMES = {
    "__init__.py", "conftest.py", ".gitkeep", "index.html",
    "components.js", "components.jsx", "README.md", "Makefile",
}

# New-file naming smells indicating a parallel/throwaway implementation.
SMELL_RE = re.compile(
    r".*_(new|copy|old|backup|final|temp|tmp|orig|v\d+|duplicate|2)\.(py|js|jsx|html|ts|tsx)$",
    re.IGNORECASE,
)

# App-structure marker directories — a new tree containing these mirrors the app.
APP_STRUCTURE_MARKERS = {"api", "services", "agents", "core"}


def _git(args):
    try:
        out = subprocess.run(
            ["git", "-C", PROJECT_DIR] + args,
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout
    except Exception:
        return ""


def _untracked_and_added():
    """Return list of new file paths (untracked '??' or added 'A ').

    Uses --untracked-files=all so that fully-new directories are expanded to
    their individual files (git otherwise collapses them to a single 'dir/'
    entry, which would hide parallel-app-structure trees from the scan).
    """
    porcelain = _git(["status", "--porcelain", "--untracked-files=all"])
    new_files = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip()
        # Untracked or newly added; ignore renames/deletes/modifications.
        if status.strip() in ("??", "A", "AM"):
            # strip optional quoting
            path = path.strip('"')
            new_files.append(path)
    return new_files


def _tracked_basenames():
    """Map basename -> first tracked path, for the whole repo."""
    bn = {}
    for p in _git(["ls-files"]).splitlines():
        p = p.strip()
        if not p:
            continue
        base = os.path.basename(p)
        bn.setdefault(base, p)
    return bn


def _tracked_top_level():
    tops = set()
    for p in _git(["ls-files"]).splitlines():
        p = p.strip()
        if p:
            tops.add(p.split("/", 1)[0])
    return tops


def check_duplicates(new_files, tracked_bn):
    findings = []
    for f in new_files:
        if not f.endswith((".py", ".js", ".jsx", ".html", ".ts", ".tsx")):
            continue
        base = os.path.basename(f)
        if base in EXEMPT_BASENAMES or base.startswith("test_") or base.endswith("_test.py"):
            continue
        existing = tracked_bn.get(base)
        if existing and existing != f:
            findings.append((f, existing))
    return findings


def check_outside_root(new_files, tracked_tops):
    # Dedupe by new top-level dir; report each once with a sample file.
    seen = {}
    for f in new_files:
        top = f.split("/", 1)[0]
        # A new top-level entry that the project has never had before.
        if "/" in f and top not in tracked_tops:
            seen.setdefault(top, f)
    return [(sample, top) for top, sample in sorted(seen.items())]


def check_parallel_structures(new_files):
    smells, struct = [], []
    new_dirs = {}
    for f in new_files:
        base = os.path.basename(f)
        if SMELL_RE.match(base) and base not in EXEMPT_BASENAMES:
            smells.append(f)
        # Track directories that newly contain app-structure markers.
        parts = f.split("/")
        for i, part in enumerate(parts[:-1]):
            if part in APP_STRUCTURE_MARKERS:
                parent = "/".join(parts[:i]) or "."
                new_dirs.setdefault(parent, set()).add(part)
    for parent, markers in new_dirs.items():
        # A non-service/app parent gaining >=2 app markers = parallel app tree.
        if len(markers) >= 2 and not parent.startswith("service/app"):
            struct.append((parent, sorted(markers)))
    return smells, struct


def check_stale_state():
    if not os.path.exists(STATE_FILE):
        return ("missing", None)
    try:
        content = open(STATE_FILE, encoding="utf-8").read(4000)
    except Exception:
        return (None, None)
    m = re.search(r"\*\*Last-run-at:\*\*\s*(\d{4}-\d{2}-\d{2})", content)
    if not m:
        m = re.search(r"[Ll]ast.updated\s+on\s+(\d{4}-\d{2}-\d{2})", content)
    if not m:
        return (None, None)
    try:
        last = datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except Exception:
        return (None, None)
    age = (date.today() - last).days
    return (age, m.group(1))


def main():
    try:
        try:
            sys.stdin.read()
        except Exception:
            pass

        new_files = _untracked_and_added()
        tracked_bn = _tracked_basenames()
        tracked_tops = _tracked_top_level()

        dupes = check_duplicates(new_files, tracked_bn)
        outside = check_outside_root(new_files, tracked_tops)
        smells, struct = check_parallel_structures(new_files)
        age, last_date = check_stale_state()

        blocks = []

        if dupes:
            lines = ["⚠  DUPLICATE MODULE — new file shares a basename with an existing module:"]
            for new, existing in dupes:
                lines.append(f"     new:      {new}")
                lines.append(f"     existing: {existing}")
            lines.append("     → Extend the existing module instead of creating a parallel one.")
            blocks.append("\n".join(lines))

        if outside:
            lines = ["⚠  OUTSIDE APPROVED ROOT — new file introduces a top-level directory the project has never had:"]
            for f, top in outside:
                lines.append(f"     {f}   (new top-level: {top}/)")
            lines.append("     → Confirm this directory is intended; most work belongs under service/, .claude/, docs/, scripts/.")
            blocks.append("\n".join(lines))

        if smells:
            lines = ["⚠  PARALLEL-IMPLEMENTATION SMELL — new file name suggests a throwaway/parallel copy:"]
            for f in smells:
                lines.append(f"     {f}")
            lines.append("     → Edit the canonical file in place; avoid _new/_copy/_old/_final/_v2 variants.")
            blocks.append("\n".join(lines))

        if struct:
            lines = ["⚠  PARALLEL APP STRUCTURE — a non-service/app directory now mirrors the application tree:"]
            for parent, markers in struct:
                lines.append(f"     {parent}/  contains app markers: {', '.join(markers)}")
            lines.append("     → The backend lives in service/app/. Do not create a second app structure.")
            blocks.append("\n".join(lines))

        if age == "missing":
            blocks.append("⚠  PROJECT_STATE.md MISSING — run /update-state to initialize project state.")
        elif isinstance(age, int) and age > STALE_DAYS:
            blocks.append(
                f"⚠  STALE PROJECT_STATE.md — last updated {last_date} ({age} days ago, > {STALE_DAYS}).\n"
                f"     → Run /update-state to refresh FACTS / DECISIONS / OPEN QUESTIONS before new work."
            )

        if blocks:
            print("─── GAP-DETECTION · structural-risk scan ───────────────────────────")
            print("\n".join(blocks))
            print("(advisory only — not a block; address structural items before proceeding)")
            print("────────────────────────────────────────────────────────────────────")
        return 0
    except Exception:
        # Fail open — a scanner must never wedge a session.
        return 0


if __name__ == "__main__":
    sys.exit(main())
