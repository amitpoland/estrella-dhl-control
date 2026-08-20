#!/usr/bin/env python
"""Emit a durable session checkpoint block for .claude/memory/TASK_STATE.md.

A degraded session must hand back to a FRESH session without relying on the
transcript.  This collects the facts a successor actually needs -- worktree,
branch, HEAD, ancestry vs origin/main, changed files, session-owned processes
-- and prints a paste-ready block.  It deliberately EXTENDS the existing
TASK_STATE.md authority instead of creating a second state file.

It never writes to TASK_STATE.md itself: what is worth persisting is a human
(or agent) judgement, and silently rewriting the state file would destroy the
audit trail the file exists to keep.

Usage:
  python .claude/scripts/session-handoff.py \
      --objective "..." --next "exact next command" [--blocker "..."] \
      [--test "carrier suite: exit=1 758 passed vs floor 604 (PRE_EXISTING)"]

Bounded by design: every subprocess call has a timeout, output is capped, and
full detail goes to --out (default: the scratch dir) rather than to stdout.
"""
import argparse, json, os, subprocess, sys, datetime

# The block below is pasted into a UTF-8 markdown file; a cp1252 console
# would otherwise mojibake em-dashes and section marks on the way out.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MAX_FILES = 40          # changed files listed inline; the rest go to --out
CMD_TIMEOUT = 15        # seconds; a handoff must never hang


def run(*args, cwd=None):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=CMD_TIMEOUT)
        return r.stdout.strip(), r.returncode
    except Exception as exc:                       # timeout, missing binary, ...
        return f"<unavailable: {exc.__class__.__name__}>", 1


def git(*args, cwd=None):
    return run("git", *args, cwd=cwd)[0]


def session_processes():
    """Session-owned dev processes, identified by PID+start+commandline.

    Never by image name alone (Lesson S rule 6): killing or reporting by name
    would sweep up other sessions' work and service-managed processes.
    """
    ps = ("Get-CimInstance Win32_Process -Filter "
          "\"Name='python.exe' or Name='node.exe' or Name='pytest.exe'\" | "
          "Select-Object ProcessId,CreationDate,"
          "@{n='cmd';e={$_.CommandLine.Substring(0,[Math]::Min(110,$_.CommandLine.Length))}} | "
          "ConvertTo-Json -Compress")
    out, rc = run("powershell", "-NoProfile", "-NonInteractive", "-Command", ps)
    if rc or not out.startswith(("[", "{")):
        return []
    try:
        d = json.loads(out)
    except Exception:
        return []
    return d if isinstance(d, list) else [d]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--objective", required=True)
    ap.add_argument("--next", required=True, help="exact next command or action")
    ap.add_argument("--blocker", default="")
    ap.add_argument("--decision", action="append", default=[])
    ap.add_argument("--test", action="append", default=[],
                    help="test verdict lines (verdict + counts, NOT raw output)")
    ap.add_argument("--state", default="EXECUTION_BLOCKED")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    root = git("rev-parse", "--show-toplevel") or os.getcwd()
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    head = git("rev-parse", "HEAD", cwd=root)
    head_short = head[:8]
    subject = git("log", "-1", "--format=%s", cwd=root)[:90]
    origin_main = git("rev-parse", "origin/main", cwd=root)
    _, behind_rc = run("git", "merge-base", "--is-ancestor", "HEAD", "origin/main", cwd=root)
    ancestry = ("HEAD is an ancestor of origin/main (behind, not diverged)"
                if behind_rc == 0 else "HEAD is NOT an ancestor of origin/main")
    dirty = [l for l in git("status", "--porcelain", cwd=root).splitlines() if l.strip()]
    stash = git("stash", "list", cwd=root).count("\n") + (1 if git("stash", "list", cwd=root) else 0)
    procs = session_processes()

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        "## Session checkpoint (resumable)",
        "",
        f"- **Recorded:** {now}",
        f"- **State:** `{a.state}`",
        f"- **Objective:** {a.objective}",
        f"- **Worktree:** `{root}`",
        f"- **Branch:** `{branch}`",
        f"- **HEAD:** `{head_short}` — {subject}",
        f"- **origin/main:** `{origin_main[:8]}` — {ancestry}",
        f"- **Working tree:** {'clean' if not dirty else f'{len(dirty)} changed path(s)'}"
        + (f", {stash} stash entr{'y' if stash == 1 else 'ies'}" if stash else ""),
    ]
    if dirty:
        lines.append("- **Changed paths:**")
        for l in dirty[:MAX_FILES]:
            lines.append(f"    - `{l.strip()}`")
        if len(dirty) > MAX_FILES:
            lines.append(f"    - … {len(dirty) - MAX_FILES} more (full list in the detail file)")
    if a.test:
        lines.append("- **Test verdicts:**")
        lines += [f"    - {t}" for t in a.test]
    if a.decision:
        lines.append("- **Decisions made this session:**")
        lines += [f"    - {d}" for d in a.decision]
    lines.append(f"- **Blocker:** {a.blocker or '(none)'}")
    lines.append(f"- **NEXT ACTION (exact):** `{a.next}`")
    if procs:
        lines.append(f"- **Live python/node processes at checkpoint:** {len(procs)} "
                     "(see detail file; identify by PID + start time + command line, never by name)")
    else:
        lines.append("- **Live python/node processes at checkpoint:** none detected")
    block = "\n".join(lines)

    out = a.out or os.path.join(os.environ.get("TEMP") or ".",
                                f"session-handoff-{head_short}.json")
    try:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"recorded": now, "root": root, "branch": branch, "head": head,
                       "origin_main": origin_main, "ancestry_ok": behind_rc == 0,
                       "dirty": dirty, "processes": procs, "block": block}, fh, indent=1)
    except OSError:
        out = "<detail file not written>"

    print(block)
    print(f"\n<!-- full detail: {out} -->")
    print("<!-- paste the block above into .claude/memory/TASK_STATE.md, then exit "
          "the session; a fresh session resumes from it (see "
          "docs/governance/session-performance-guard.md §6). -->")


if __name__ == "__main__":
    sys.exit(main())
