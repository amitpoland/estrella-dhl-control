#!/usr/bin/env python
"""Session-health status line: CTX / AGE / CMP / health, from stdin only.

Contract (measured against claude.exe 2.1.234): Claude Code pipes a JSON
payload to the statusLine command on stdin.  Every field this script reads
is already in that payload -- `context_window.{total_input_tokens,
context_window_size,used_percentage}`, `cost.total_duration_ms`,
`session_id`, `model.display_name` -- so the script performs NO git call,
NO network call, NO MCP query and NO transcript scan.  Measured budget:
one Python start plus one small state read/write.  Measured p50 on the
reference Windows box: 85 ms, of which ~57 ms is the interpreter itself.
The state file also counts its own invocations (`n`) so the guard's true
per-session cost can be audited without adding instrumentation.

Compaction count is not in the payload.  It is derived instead of scanned:
a compaction is the only thing that makes total_input_tokens fall sharply,
so the script keeps a tiny per-session state file (last/max occupancy,
compaction count and the time of the previous compaction) under the
scratch dir.  That keeps the count O(1) rather than O(transcript).

Fails silently (prints a minimal line, exit 0) on any error: a status line
must never wedge or slow a session.

Health states are calibrated in docs/governance/session-performance-guard.md;
edit both together.
"""
import sys, os, json

# Compaction detector: occupancy must fall by at least this much to count.
DROP_ABS = 20_000
DROP_FRAC = 0.20
# Health thresholds (fraction of the context window in use).
WARN_PCT, DEGRADED_PCT = 0.60, 0.80
# Repeated compaction is the stronger degradation signal.
WARN_CMP, DEGRADED_CMP = 2, 3
RAPID_CYCLE_MS = 10 * 60 * 1000   # two compactions inside this = DEGRADED


def human(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def age(ms):
    s = int(ms / 1000)
    if s < 3600:
        return f"{s//60}m"
    return f"{s//3600}h{(s%3600)//60:02d}m"


def state_path(sid):
    d = os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or ".",
                     "claude-session-health")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    safe = "".join(c for c in str(sid) if c.isalnum() or c in "-_")[:64] or "unknown"
    return os.path.join(d, safe + ".json")


def track(sid, occ, elapsed_ms):
    """Return (compaction_count, rapid_cycle) with O(1) work."""
    p = state_path(sid)
    if not p:
        return 0, False
    st = {"last": occ, "max": occ, "cmp": 0, "last_cmp_ms": None}
    try:
        with open(p, encoding="utf-8") as fh:
            st.update(json.load(fh))
    except Exception:
        pass
    rapid = False
    last = st.get("last") or occ
    drop = last - occ
    if drop >= DROP_ABS and drop >= last * DROP_FRAC:
        prev = st.get("last_cmp_ms")
        if prev is not None and (elapsed_ms - prev) <= RAPID_CYCLE_MS:
            rapid = True
        st["cmp"] = int(st.get("cmp", 0)) + 1
        st["last_cmp_ms"] = elapsed_ms
        st["rapid"] = st.get("rapid", False) or rapid
    rapid = rapid or bool(st.get("rapid"))
    st["last"] = occ
    st["max"] = max(int(st.get("max", 0)), occ)
    st["n"] = int(st.get("n", 0)) + 1          # invocations, for cost auditing
    st["elapsed_ms"] = elapsed_ms
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh)
        os.replace(tmp, p)
    except Exception:
        pass
    return int(st.get("cmp", 0)), rapid


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print("CTX ?")
        return
    cw = payload.get("context_window") or {}
    occ = int(cw.get("total_input_tokens") or 0)
    size = int(cw.get("context_window_size") or 0)
    used = cw.get("used_percentage")
    if used is None:
        used = (100.0 * occ / size) if size else 0.0
    elapsed = int((payload.get("cost") or {}).get("total_duration_ms") or 0)
    sid = payload.get("session_id") or "unknown"

    cmp_count, rapid = track(sid, occ, elapsed)

    frac = (used or 0) / 100.0
    if frac >= DEGRADED_PCT or cmp_count >= DEGRADED_CMP or rapid:
        health = "DEGRADED"
    elif frac >= WARN_PCT or cmp_count >= WARN_CMP:
        health = "WARN"
    else:
        health = "OK"

    parts = [f"CTX {human(occ)}/{human(size) if size else '?'} {used:.0f}%",
             f"AGE {age(elapsed)}",
             f"CMP {cmp_count}"]
    if health != "OK":
        parts.append(health)
    print(" | ".join(parts))


if __name__ == "__main__":
    # A status line must never wedge or crash a session: any unexpected error
    # degrades to a minimal line, never to a traceback or a non-zero exit.
    try:
        main()
    except Exception:
        try:
            print("CTX ?")
        except Exception:
            pass
    sys.exit(0)
