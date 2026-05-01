#!/usr/bin/env python3
"""
audit_dashboard_actions.py

Walk every batch in storage/outputs and report:
  - visible / enabled action counts per section
  - disabled-with-reason actions
  - broken endpoints (missing routes / method mismatches)
  - stale-state mismatches (e.g. status=processing but PZ files exist)

Usage:
  python3 service/scripts/audit_dashboard_actions.py
  python3 service/scripts/audit_dashboard_actions.py --batch SHIPMENT_xxx
  python3 service/scripts/audit_dashboard_actions.py --csv > report.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Ensure service/ on sys.path
_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402
from app.services.batch_state_normalizer import normalize_batch_state  # noqa: E402
from app.services.dashboard_action_registry import (  # noqa: E402
    build_actions_for_batch,
    all_action_endpoints,
)
from app.services.route_contract_validator import validate_endpoints  # noqa: E402

OUTPUTS = settings.storage_root / "outputs"


def _load_app():
    """Import the FastAPI app (so route validator can introspect routes)."""
    from app.main import app
    return app


def audit_batch(app, batch_dir: Path) -> dict:
    audit_path = batch_dir / "audit.json"
    if not audit_path.exists():
        return {"batch_id": batch_dir.name, "error": "audit.json missing"}
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"batch_id": batch_dir.name, "error": f"audit.json unreadable: {e}"}

    n = normalize_batch_state(audit, batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    broken = validate_endpoints(app, all_action_endpoints(n))

    counts = {"visible": 0, "enabled": 0, "disabled_with_reason": 0}
    by_section = {}
    for sec, actions in sections.items():
        s_counts = {"total": len(actions), "enabled": 0, "disabled": 0}
        for a in actions:
            counts["visible"] += 1 if a.visible else 0
            counts["enabled"] += 1 if a.enabled else 0
            if (not a.enabled) and a.reason:
                counts["disabled_with_reason"] += 1
            if a.enabled: s_counts["enabled"] += 1
            else: s_counts["disabled"] += 1
        by_section[sec] = s_counts

    # Stale-state checks
    stale = []
    if n.audit_status == "processing" and (n.has_pz_pdf and n.has_pz_xlsx):
        stale.append("status=processing but PZ files exist on disk")
    if n.audit_status == "blocked" and n.pz_generated:
        stale.append("status=blocked but PZ files exist on disk")
    if n.has_polish_description and not n.polish_desc_filename:
        stale.append("polish desc file present but audit.polish_desc_filename empty")

    return {
        "batch_id":             n.batch_id,
        "audit_status":         n.audit_status,
        "overall_status":       n.overall_status,
        "pz_generated":         n.pz_generated,
        "wfirma_ready":         n.wfirma_ready,
        "agency_path":          n.clearance_path == "external_agency_clearance",
        "broken_actions":       [b.to_dict() for b in broken],
        "broken_count":         len(broken),
        "stale_state":          stale,
        "counts":               counts,
        "by_section":           by_section,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", help="Single batch_id to audit")
    ap.add_argument("--csv", action="store_true", help="Emit CSV summary")
    args = ap.parse_args()

    app = _load_app()

    if args.batch:
        batches = [OUTPUTS / args.batch]
    else:
        batches = sorted(p for p in OUTPUTS.iterdir() if p.is_dir() and (p / "audit.json").exists())

    if args.csv:
        w = csv.writer(sys.stdout)
        w.writerow(["batch_id", "audit_status", "pz_generated", "wfirma_ready",
                    "broken_count", "stale_state", "visible", "enabled", "disabled_with_reason"])
        for d in batches:
            r = audit_batch(app, d)
            if "error" in r:
                w.writerow([r["batch_id"], "ERROR", "", "", "", r["error"], "", "", ""])
                continue
            w.writerow([
                r["batch_id"], r["audit_status"], r["pz_generated"], r["wfirma_ready"],
                r["broken_count"], "; ".join(r["stale_state"]),
                r["counts"]["visible"], r["counts"]["enabled"], r["counts"]["disabled_with_reason"],
            ])
        return

    # Human-readable output
    total_broken = 0
    total_stale  = 0
    for d in batches:
        r = audit_batch(app, d)
        if "error" in r:
            print(f"[ERROR] {r['batch_id']}: {r['error']}")
            continue
        marker = "✗" if (r["broken_count"] or r["stale_state"]) else "✓"
        print(f"\n{marker} {r['batch_id']}")
        print(f"  status={r['audit_status']!r:15} pz_generated={r['pz_generated']} wfirma_ready={r['wfirma_ready']} agency_path={r['agency_path']}")
        print(f"  actions: visible={r['counts']['visible']} enabled={r['counts']['enabled']} disabled_with_reason={r['counts']['disabled_with_reason']}")
        if r["broken_count"]:
            total_broken += r["broken_count"]
            print(f"  BROKEN ROUTES ({r['broken_count']}):")
            for b in r["broken_actions"]:
                print(f"    - {b['action_id']}: {b['method']} {b['endpoint']} ({b['reason']})")
        if r["stale_state"]:
            total_stale += len(r["stale_state"])
            print(f"  STALE STATE:")
            for s in r["stale_state"]:
                print(f"    - {s}")
    print(f"\n--- {len(batches)} batches scanned · {total_broken} broken routes · {total_stale} stale-state issues")


if __name__ == "__main__":
    main()
