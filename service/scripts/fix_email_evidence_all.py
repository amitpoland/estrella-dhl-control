#!/usr/bin/env python3
"""
fix_email_evidence_all.py — Run backfill_from_audit against all batches.

Walks every batch in storage/outputs, reads audit.json, and calls
backfill_from_audit to create missing email evidence entries from audit fields.

This is idempotent: running it multiple times will not create duplicate entries.

Usage:
    python3 scripts/fix_email_evidence_all.py [--storage PATH] [--batch BATCH_ID] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


def _resolve_storage(override: Optional[str]) -> Path:
    if override:
        return Path(override)
    try:
        from app.core.config import settings
        return settings.storage_root
    except Exception:
        return Path.home() / "Library" / "Application Support" / "estrellajewels" / "storage"


def _load(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else {}
    except Exception:
        return {}


def fix_batch(batch_dir: Path, dry_run: bool) -> Dict[str, Any]:
    """Run backfill_from_audit for a single batch."""
    audit_path = batch_dir / "audit.json"
    if not audit_path.exists():
        return {"batch_id": batch_dir.name, "status": "skip", "reason": "no audit.json"}

    audit = _load(audit_path)
    if not audit:
        return {"batch_id": batch_dir.name, "status": "skip", "reason": "audit.json empty/invalid"}

    awb = str(audit.get("awb") or audit.get("tracking_no") or "").strip()
    if not awb:
        return {"batch_id": batch_dir.name, "status": "skip", "reason": "no AWB"}

    batch_id = audit.get("batch_id") or batch_dir.name

    if dry_run:
        # Analyse what would be done without writing
        timeline = audit.get("timeline") or []
        actions = []

        drp = audit.get("dhl_reply_package") or {}
        arp = audit.get("agency_reply_package") or {}
        dhl_email = audit.get("dhl_email") or {}
        ticket = audit.get("dhl_ticket") or ""

        if dhl_email or ticket:
            actions.append("would_add: dhl_request")
        if drp.get("queued_at") or drp.get("sent_at"):
            status = "sent" if (drp.get("sent_at") and (drp.get("status") == "sent" or drp.get("send_verified"))) else "queued"
            actions.append(f"would_add: our_dhl_reply [{status}]")
        if arp.get("queued_at") or arp.get("sent_at"):
            status = "sent" if (arp.get("sent_at") and (arp.get("status") == "sent" or arp.get("send_verified"))) else "queued"
            actions.append(f"would_add: agency_forward [{status}]")

        return {
            "batch_id":   batch_id,
            "awb":        awb,
            "status":     "dry_run",
            "actions":    actions,
        }

    try:
        from app.services.email_evidence_backfill import backfill_from_audit
        result = backfill_from_audit(awb, batch_id, audit_path, audit)
        return {
            "batch_id":    batch_id,
            "awb":         awb,
            "status":      "ok",
            "total_added": result["total_added"],
            "added":       result["added"],
            "skipped":     result["skipped"],
        }
    except Exception as exc:
        return {
            "batch_id": batch_id,
            "awb":      awb,
            "status":   "error",
            "error":    str(exc),
        }


def _print_results(results: List[Dict[str, Any]], dry_run: bool) -> None:
    sep = "-" * 100
    marker = "(DRY RUN)" if dry_run else ""
    print(f"\nEmail Evidence Backfill {marker}")
    print(sep)

    total_added   = 0
    total_ok      = 0
    total_skipped = 0
    total_errors  = 0

    for r in results:
        status = r.get("status", "?")
        batch  = r.get("batch_id", "?")
        awb    = r.get("awb", "")

        if status == "skip":
            total_skipped += 1
            print(f"  SKIP   {batch:<55}  {r.get('reason', '')}")

        elif status == "dry_run":
            total_ok += 1
            actions = r.get("actions") or []
            print(f"  DRY    {batch:<55}  awb={awb:<14}  {len(actions)} actions")
            for a in actions:
                print(f"         {'':>55}  - {a}")

        elif status == "ok":
            total_ok += 1
            n = r.get("total_added", 0)
            total_added += n
            added_summary = ", ".join(
                f"{a['event_type']}[{a.get('delivery_status', '?')}]"
                for a in (r.get("added") or [])
            )
            marker = "+" if n else "·"
            print(f"  {marker}      {batch:<55}  awb={awb:<14}  added={n}  {added_summary or '(nothing new)'}")

        elif status == "error":
            total_errors += 1
            print(f"  ERROR  {batch:<55}  {r.get('error', '')}")

    print(sep)
    print(f"  {len(results)} batches  |  {total_ok} processed  |  {total_added} entries added  "
          f"|  {total_skipped} skipped  |  {total_errors} errors")
    print(sep)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--storage", help="Override storage root path")
    ap.add_argument("--batch",   help="Process a single batch_id only")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be done without writing")
    ap.add_argument("--json",    action="store_true", help="Output JSON")
    args = ap.parse_args()

    storage = _resolve_storage(args.storage)
    outputs = storage / "outputs"

    if not outputs.exists():
        print(f"[ERROR] outputs directory not found: {outputs}", file=sys.stderr)
        sys.exit(1)

    if args.batch:
        batch_dirs = [outputs / args.batch]
    else:
        batch_dirs = sorted(p for p in outputs.iterdir() if p.is_dir())

    results = [fix_batch(d, args.dry_run) for d in batch_dirs]

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        _print_results(results, args.dry_run)


if __name__ == "__main__":
    main()
