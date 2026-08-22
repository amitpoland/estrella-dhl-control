"""W0 census — reproduces every figure in campaign/reports/W0-report.md.

Usage:  python census.py projection_all_2026-08-21T2315Z.json
Read-only. No network, no writes.
"""
import collections
import json
import statistics
import sys
from datetime import datetime

CARRIER = {"tracking_cache", "tracking_db", "carrier_shipments"}
INVALIDATING = {
    "invalid_timestamp_order_delivery_before_created",
    "tracking_evidence_missing",
    "delivered_claim_without_carrier_terminal",
}


def _iso(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def contamination(d):
    """§1 — N + excluded_n must equal the direction cohort for every stage."""
    out = []
    for scope in ("inbound", "outbound"):
        cohort = sum(1 for r in d["rows"] if r.get("direction") == scope)
        for key, v in d["analytics"]["fixed_transitions_" + scope].items():
            n, ex = v.get("n") or 0, v.get("excluded_n") or 0
            out.append((scope, key, n, ex, n + ex, cohort, v.get("exclusion_reason_counts") or {}))
    return out


def zombie_split(d):
    """§4 — GENUINE / SUSPECT / ZOMBIE by milestone authority."""
    c = collections.Counter()
    for r in d["rows"]:
        auth = {str(m.get("authority")) for m in (r.get("milestones") or [])}
        flags = set(r.get("data_quality") or [])
        if not auth & CARRIER:
            k = "ZOMBIE"
        elif flags & INVALIDATING:
            k = "SUSPECT"
        else:
            k = "GENUINE"
        c[(r["direction"], k)] += 1
    return c


def email_to_dsk(d):
    """§3 — per-sample forensic for the DHL email -> DSK stage."""
    samples = []
    for r in d["rows"]:
        if r.get("direction") != "inbound":
            continue
        ms = {}
        for m in r.get("milestones") or []:
            ms.setdefault(str(m.get("stage_id")), m)
        e, k = ms.get("dhl_email"), ms.get("dsk")
        et, kt = (_iso(e["timestamp_utc"]) if e else None), (_iso(k["timestamp_utc"]) if k else None)
        if et and kt:
            samples.append(((kt - et).total_seconds() / 3600.0, et, kt, r["awb"]))
    return sorted(samples)


def dsk_histogram(d):
    """§3 — day-level DSK stamp histogram, the backfill test."""
    h = collections.Counter()
    for r in d["rows"]:
        for m in r.get("milestones") or []:
            if m.get("stage_id") == "dsk":
                h[str(m["timestamp_utc"])[:10]] += 1
    return h


def main(path):
    d = json.load(open(path))
    print("generated_at_utc:", d["generated_at_utc"], "rows:", len(d["rows"]))

    print("\n== §1 CONTAMINATION ==")
    bad = 0
    for scope, key, n, ex, tot, cohort, reasons in contamination(d):
        ok = "OK" if tot == cohort else "SPINE-BREAK"
        bad += tot != cohort
        print("%-9s %-30s N=%-3d excl=%-3d tot=%-3d cohort=%-3d %-11s %.1f%% %s"
              % (scope, key, n, ex, tot, cohort, ok, 100.0 * ex / tot if tot else 0, reasons))
    assert bad == 0, "cohort spine broken on %d stage(s)" % bad
    print("cohort spine: N + excluded == cohort on all 16 stages")

    print("\n== §4 ZOMBIE SPLIT ==")
    c = zombie_split(d)
    for k in sorted(c):
        print("  %-9s %-8s %d" % (k[0], k[1], c[k]))

    print("\n== §3 DSK DAY HISTOGRAM ==")
    h = dsk_histogram(d)
    for k in sorted(h):
        print("  %s %s %d" % (k, "#" * h[k], h[k]))
    window = sum(v for k, v in h.items() if "2026-04-27" <= k <= "2026-05-06")
    pre_june = sum(v for k, v in h.items() if k < "2026-06")
    print("  backfill window 2026-04-27..05-06: %d of %d pre-June stamps" % (window, pre_june))

    print("\n== §3 email -> DSK SAMPLES ==")
    s = email_to_dsk(d)
    for hrs, et, kt, awb in s:
        print("  %-12s %s -> %s  %10.2f h" % (awb, et.strftime("%Y-%m-%d %H:%M"), kt.strftime("%Y-%m-%d %H:%M"), hrs))
    pos = [x[0] for x in s if x[0] >= 0]
    post = [x[0] for x in s if x[0] >= 0 and x[2].strftime("%Y-%m-%d") > "2026-05-06"]
    print("  positive n=%d median=%.2fh (%.1fd)" % (len(pos), statistics.median(pos), statistics.median(pos) / 24))
    print("  post-backfill n=%d max=%.2fh   <- every one beats the 24h target" % (len(post), max(post)))
    print("  inverted (DSK before email) n=%d" % sum(1 for x in s if x[0] < 0))

    print("\n== §5 BOTTLENECKS AS RENDERED ==")
    neg = 0
    for i, b in enumerate(d["intelligence"]["bottlenecks"], 1):
        neg += (b["excess_vs_target_hours"] or 0) < 0
        print("  %-3d %-9s %-30s excess=%-10s N=%-4s contrib=%-10s d%%=%s"
              % (i, b["scope"], b["id"], b["excess_vs_target_hours"], b["n"],
                 b["contribution_hours"], b["delta_pct_vs_previous_30d"]))
    print("  entries beating target yet ranked as bottlenecks: %d of %d"
          % (neg, len(d["intelligence"]["bottlenecks"])))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "projection_all_2026-08-21T2315Z.json")
