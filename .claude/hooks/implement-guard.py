#!/usr/bin/env python3
"""
EJ implementer guard (PreToolUse hook) — slice-01: shipment-authority.

ACTIVE only when EJ_IMPLEMENT=1 AND EJ_CENSUS is unset.
FAIL-CLOSED (deny everything) if EJ_IMPLEMENT and EJ_CENSUS are both set.
INERT (allow) when EJ_IMPLEMENT != 1.

Unlike the census pack, the implementer agent HOLDS a shell tool. Safety therefore
rests on THIS guard, not on tool-absence. This file is the audit target.

Exhaustive allow-list for slice-01 (everything else denied):
  EDIT  -> .claude/memory/PROJECT_STATE.md, iff:
             DECISIONS_HEADER present in old_string, AND
             new_string.startswith(old_string)   (append-after-header only)
  WRITE -> paths under reports/implement/            (slice-record only)
  SHELL (Bash|PowerShell), single command, no chaining/redirection:
             - read-only git (rev-parse|status|diff|ls-files|cat-file|show|log),
               with no write subcommand present
             - EXACTLY one of the two literal Remove-Item strings (byte-compared)

Block protocol: exit code 2 + stderr reason.

>>> CONFIRM DURING VERIFY STEP 0 <<<
DECISIONS_HEADER must byte-match the real header line in PROJECT_STATE.md.
"""
import json, os, sys

# ---- CONFIRM/SET in verify Step 0 to match PROJECT_STATE.md exactly ----
DECISIONS_HEADER = "# DECISIONS"
# -----------------------------------------------------------------------

PROJECT_STATE_SUFFIX = ".claude/memory/project_state.md"   # normalized lower
SLICE_REPORT_TOKEN   = "reports/implement/"

DELETE_LITERALS = {
    r'Remove-Item -LiteralPath "C:\PZ-verify\service\app\static\v2\shipment-detail-page.v1.jsx"',
    r'Remove-Item -LiteralPath "C:\PZ-verify\service\app\static\v2\shipment-detail-page.v2.jsx"',
}

RO_GIT_PREFIXES = (
    "git rev-parse", "git status", "git diff", "git ls-files",
    "git cat-file", "git show", "git log",
)
GIT_WRITE_TOKENS = (
    "commit", "push", " add ", "add.", "reset", "restore", "checkout",
    " rm ", " mv ", "clean", "stash", "merge", "rebase", "tag ",
    "branch -", " gc", "fetch", "pull", "config",
)
SHELL_OPERATORS = ("&&", "||", ";", "|", "`", "$(", ">", "<", "&", "\n")

def deny(reason):
    sys.stderr.write("IMPLEMENT GUARD BLOCKED: " + reason +
                     "\nslice-01 allow-list: 1 Edit (PROJECT_STATE DECISIONS append) + "
                     "2 Remove-Item literals + read-only git + slice-record Write. Nothing else.\n")
    sys.exit(2)

def main():
    census    = os.environ.get("EJ_CENSUS")
    implement = os.environ.get("EJ_IMPLEMENT")

    # fail closed on ambiguous / dual mode
    if census and implement:
        deny("ambiguous mode: EJ_CENSUS and EJ_IMPLEMENT both set. Refusing (fail-closed).")
    if implement != "1":
        sys.exit(0)  # inert outside implement mode

    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never block on hook parse failure

    tool = (data.get("tool_name") or "")
    tl   = tool.lower()
    ti   = data.get("tool_input") or {}

    # ---------- WRITE / MULTIEDIT / NOTEBOOKEDIT ----------
    if tl in ("write", "multiedit", "notebookedit"):
        path = (ti.get("file_path") or ti.get("notebook_path") or "")
        norm = path.replace("\\", "/").lower()
        if tl == "write" and SLICE_REPORT_TOKEN in norm:
            sys.exit(0)  # slice-record permitted
        deny(f"{tool} to '{path}' not permitted. DECISIONS uses single Edit only; "
             "only slice-record Write under reports/implement/.")

    # ---------- EDIT ----------
    if tl == "edit":
        path = (ti.get("file_path") or "")
        norm = path.replace("\\", "/").lower()
        if norm.endswith(PROJECT_STATE_SUFFIX):
            old = ti.get("old_string") or ""
            new = ti.get("new_string") or ""
            if DECISIONS_HEADER not in old:
                deny("Edit to PROJECT_STATE.md must anchor on the DECISIONS header in old_string.")
            if not new.startswith(old):
                deny("Edit to PROJECT_STATE.md must preserve old_string verbatim at the start "
                     "of new_string (append-after-header only; no rewrite).")
            sys.exit(0)
        deny(f"Edit to '{path}' not permitted in slice-01 (only PROJECT_STATE.md DECISIONS).")

    # ---------- SHELL ----------
    if tl in ("bash", "powershell"):
        cmd = (ti.get("command") or ti.get("script") or ti.get("code") or "").strip()

        # exact delete literals (byte-compare) — checked before operator rejection
        if cmd in DELETE_LITERALS:
            sys.exit(0)

        for op in SHELL_OPERATORS:
            if op in cmd:
                deny(f"shell operator '{op!r}' not permitted in slice-01 (no chaining/redirection/multiline).")

        if any(cmd.startswith(p) for p in RO_GIT_PREFIXES):
            low = " " + cmd.lower() + " "
            for bad in GIT_WRITE_TOKENS:
                if bad in low:
                    deny(f"git write/state subcommand '{bad.strip()}' not permitted (read-only git only).")
            sys.exit(0)

        deny(f"shell command not in slice-01 allow-list: {cmd[:160]}")

    # any other tool
    sys.exit(0)

if __name__ == "__main__":
    main()
