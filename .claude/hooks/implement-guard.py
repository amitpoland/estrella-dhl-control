#!/usr/bin/env python3
"""
EJ implementer guard (PreToolUse) - slice-03 MERGED: reports-dedup, Edit-only,
derive-from-disk, line-ending-agnostic. Single authority file; replaces all
prior slice-03 guard versions in place.

BODY excision accepts TWO shapes (checked in this order):
  PRIMARY (empty-new): new == ""  and old == disk_lf[idx(H1):idx(H2)]
    removes H1 + function + trailing blank; H2 stays untouched. No box-drawing
    glyph generation required (U+2500 appears only in old, copied from Read).
  FALLBACK (copy-H2):  new == H2  and old == disk_lf[idx(H1):idx(H2)+len(H2)]
Both require H1 and H2 each unique in the file; otherwise deny (drift).
Comparison is line-ending-agnostic: disk and incoming strings are canonicalized
CRLF->LF before byte-compare. Only line-ending representation is normalized;
every other byte is exact-matched, so content drift fails closed.
Active only when EJ_IMPLEMENT=1 AND EJ_CENSUS unset. Fail-closed if both set.
Inert (exit 0) unless EJ_IMPLEMENT == "1".
"""
import json, os, sys

H1  = "// ── Reports Page"
H2  = "// ── Learning / Parser Page"
REG_LF = "\n  ReportsPage,"

PAGES_SUFFIX         = "service/app/static/v2/pages.jsx"
PROJECT_STATE_SUFFIX = ".claude/memory/project_state.md"
SLICE_REPORT_TOKEN   = "reports/implement/"
DECISIONS_HEADER     = "# DECISIONS"

RO_GIT_PREFIXES = ("git rev-parse", "git status", "git diff", "git ls-files",
                   "git cat-file", "git show", "git log", "git rev-list")
GIT_WRITE_TOKENS = (" commit", " push", " add ", " reset", " restore", " checkout",
                    " rm ", " mv ", " clean", " stash", " merge", " rebase",
                    " tag ", " branch -", " gc", " fetch", " pull", " config",
                    " apply", " cherry-pick", " revert")
SHELL_OPERATORS = ("&&", "||", ";", "|", "`", "$(", ">", "<", "&", "\n")

def deny(msg):
    sys.stderr.write("IMPLEMENT GUARD BLOCKED (slice-03): " + msg + "\n")
    sys.exit(2)

def lf(s):
    return s.replace("\r\n", "\n")

def repo_root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

def read_pages_lf():
    p = os.path.join(repo_root(), "service", "app", "static", "v2", "pages.jsx")
    try:
        with open(p, "r", encoding="utf-8", newline="") as f:
            return lf(f.read())
    except Exception:
        return None

def main():
    census    = os.environ.get("EJ_CENSUS")
    implement = os.environ.get("EJ_IMPLEMENT")
    if census and implement:
        deny("ambiguous mode: EJ_CENSUS and EJ_IMPLEMENT both set. Fail-closed.")
    if implement != "1":
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = data.get("tool_name") or ""
    tl = tool.lower()
    ti = data.get("tool_input") or {}

    if tl in ("write", "multiedit", "notebookedit"):
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        norm = path.replace("\\", "/").lower()
        if tl == "write" and SLICE_REPORT_TOKEN in norm:
            sys.exit(0)
        deny(tool + " to '" + path + "' not permitted. slice-03 is Edit-only; "
             "only a slice-record Write under reports/implement/ is allowed.")

    if tl == "edit":
        path = ti.get("file_path") or ""
        norm = path.replace("\\", "/").lower()
        old = lf(ti.get("old_string") or "")
        new = lf(ti.get("new_string") or "")

        if norm.endswith(PROJECT_STATE_SUFFIX):
            if DECISIONS_HEADER not in old:
                deny("PROJECT_STATE Edit must anchor on the DECISIONS header.")
            if not new.startswith(old):
                deny("PROJECT_STATE Edit must be append-after-anchor (new startswith old).")
            sys.exit(0)

        if norm.endswith(PAGES_SUFFIX):
            disk = read_pages_lf()
            if disk is None:
                deny("could not read pages.jsx to derive the expected span.")

            if new == "":
                if disk.count(H1) != 1 or disk.count(H2) != 1:
                    deny("anchor drift: H1=%d, H2=%d (need 1 and 1)." % (disk.count(H1), disk.count(H2)))
                s = disk.index(H1); e = disk.index(H2)
                if old == disk[s:e]:
                    sys.exit(0)
                deny("BODY(empty-new) old_string does not byte-match the derived "
                     "H1..pre-H2 span (LF-canonical). Drift or malformed. Deny + abort.")

            if new == H2:
                if disk.count(H1) != 1 or disk.count(H2) != 1:
                    deny("anchor drift: H1=%d, H2=%d (need 1 and 1)." % (disk.count(H1), disk.count(H2)))
                s = disk.index(H1); e = disk.index(H2) + len(H2)
                if old == disk[s:e]:
                    sys.exit(0)
                deny("BODY(fallback) old_string does not byte-match the derived "
                     "H1..H2 span (LF-canonical). Deny + abort.")

            if REG_LF in old:
                if disk.count(REG_LF) != 1:
                    deny("REG anchor drift: count=%d (need 1)." % disk.count(REG_LF))
                if old not in disk:
                    deny("REG old_string is not a substring of pages.jsx (drift). Deny + abort.")
                if old.count(REG_LF) != 1:
                    deny("REG old_string must contain the registration line exactly once.")
                expected_new = old.replace(REG_LF, "", 1)
                if new == expected_new and new != old:
                    sys.exit(0)
                deny("REG new_string must equal old_string minus the single ReportsPage line.")

            deny("pages.jsx Edit matched no allowed shape: BODY empty-new, BODY fallback, or REG.")

        deny("Edit to '" + path + "' not permitted in slice-03.")

    if tl in ("bash", "powershell"):
        cmd = (ti.get("command") or ti.get("script") or ti.get("code") or "").strip()
        for op in SHELL_OPERATORS:
            if op in cmd:
                deny("shell operator %r not permitted (single read-only git command only)." % op)
        if any(cmd.startswith(p) for p in RO_GIT_PREFIXES):
            padded = " " + cmd.lower() + " "
            for bad in GIT_WRITE_TOKENS:
                if bad in padded:
                    deny("git write subcommand '%s' not permitted." % bad.strip())
            sys.exit(0)
        deny("shell command not in slice-03 allow-list: " + cmd[:160])

    sys.exit(0)

if __name__ == "__main__":
    main()
