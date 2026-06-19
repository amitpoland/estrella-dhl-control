#!/usr/bin/env python3
"""
UserPromptSubmit hook: injects PROJECT_STATE.md summary into context
on the first user message of each OS session (detected via /tmp/ marker).
"""
import sys
import os
import re
import hashlib

PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
STATE_FILE = os.path.join(PROJECT_DIR, ".claude", "memory", "PROJECT_STATE.md")

_h = hashlib.md5(PROJECT_DIR.encode()).hexdigest()[:8]
MARKER = f"/tmp/pz-state-injected-{_h}"


def main():
    try:
        sys.stdin.read()
    except Exception:
        pass

    if os.path.exists(MARKER):
        return 0
    try:
        open(MARKER, "w").close()
    except Exception:
        pass

    if not os.path.exists(STATE_FILE):
        print("[session] PROJECT_STATE.md missing — run /update-state to initialize.")
        return 0

    try:
        content = open(STATE_FILE, encoding="utf-8").read()
    except Exception:
        return 0

    # Extract date from **Last-run-at:** YYYY-MM-DD
    date_match = re.search(r"\*\*Last-run-at:\*\*\s*(\d{4}-\d{2}-\d{2})", content)
    if not date_match:
        date_match = re.search(r"[Ll]ast.updated\s+on\s+(\d{4}-\d{2}-\d{2})", content)
    updated = date_match.group(1) if date_match else "unknown"

    # Extract OPEN QUESTIONS section titles (## OQ-* headings), first 5 max
    oq_titles = re.findall(r"^## (OQ-[^\n]+)", content, re.MULTILINE)
    if oq_titles:
        oq_lines = [f"  · {t}" for t in oq_titles[:5]]
        if len(oq_titles) > 5:
            oq_lines.append(f"  · ... and {len(oq_titles) - 5} more (see PROJECT_STATE.md)")
        oq_block = "\n".join(oq_lines)
    else:
        # Fallback: look for the OPEN QUESTIONS section body
        oq_match = re.search(
            r"#\s+OPEN QUESTIONS?\s*\n(.*?)(?=\n#\s|\Z)",
            content, re.DOTALL | re.IGNORECASE
        )
        body = oq_match.group(1).strip() if oq_match else ""
        if body:
            lines = [l for l in body.splitlines() if l.strip()][:6]
            oq_block = "\n".join(f"  {l}" for l in lines)
        else:
            oq_block = "  (none)"

    # Extract GATE 2 state from dense header block
    gate2_match = re.search(r"GATE 2[:\s]+\*\*([^*]+)\*\*", content)
    gate2 = gate2_match.group(1).strip() if gate2_match else ""

    lines = [
        f"─── SESSION START · PROJECT_STATE as of {updated} ───",
    ]
    if gate2:
        lines.append(f"GATE 2 (max 3 open PRs): {gate2}")
    lines += [
        "",
        f"OPEN QUESTIONS ({len(oq_titles)} total) — review before starting work:",
        oq_block,
        "",
        "Read .claude/memory/PROJECT_STATE.md for full context.",
        "Run /update-state after task completion to keep state current.",
        "────────────────────────────────────────────────────────────",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
