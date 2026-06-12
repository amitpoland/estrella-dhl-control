#!/usr/bin/env python3
"""
backfill_skip_events_f255bbb5.py — One-shot backfill for PR 1 visibility.

Purpose
-------
Batch ``SHIPMENT_7123231135_2026-06_f255bbb5`` had 7 uploaded packing lists but
only 5 generated proforma drafts.  The 2 missing drafts (EJL/26-27/258 and
EJL/26-27/260) were silently dropped by ``proforma_draft_sync`` because their
``sales_documents.client_name`` was empty at sync time.  PR 1 makes that
visible at upload time going forward; this script back-fills the visibility
events for the historical batch so the audit reflects the same evidence.

Safety
------
- Idempotent: if a matching ``proforma_draft_creation_*`` event already exists
  for the same sales_doc_id, no new event is appended.
- Atomic write (tmp + replace).
- Dry-run by default; pass ``--write`` to persist.
- NEVER touches drafts, invoices, PZ, customs, or verification — only
  ``audit.json["timeline"]``.

Usage
-----
    python3 service/scripts/backfill_skip_events_f255bbb5.py
    python3 service/scripts/backfill_skip_events_f255bbb5.py --write
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

# Hard-coded targets — this is a one-shot for a specific incident batch.
BATCH_ID = "SHIPMENT_7123231135_2026-06_f255bbb5"
AUDIT_PATH = pathlib.Path(r"C:\PZ\storage\outputs") / BATCH_ID / "audit.json"

# Two sales_documents whose client_name was empty at sync time.
# See PROJECT_STATE.md / the f255bbb5 investigation notes.
TARGETS = [
    {
        "sales_doc_id": "3a5474b0",
        "sales_doc_no": "EJL/26-27/258",
        "source_file_hint": "EJL-26-27-258",
        # No usable preamble signals observed for /258 → SKIPPED.
        "signals": {"vat": None, "heading_candidate": None},
    },
    {
        "sales_doc_id": "d96fa983",
        "sales_doc_no": "EJL/26-27/260",
        "source_file_hint": "EJL-26-27-260",
        # /260 contains "Jozef Horňák-HORNAK klenoty" + VAT SK107095376.
        "signals": {
            "vat": "SK107095376",
            "heading_candidate": "Jozef Horňák-HORNAK klenoty",
        },
    },
]

EV_PENDING = "proforma_draft_creation_pending_resolution"
EV_SKIPPED = "proforma_draft_creation_skipped"


def _write_atomic(path: pathlib.Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _already_emitted(timeline: list, sales_doc_id: str) -> bool:
    for ev in timeline:
        if ev.get("event") not in (EV_PENDING, EV_SKIPPED):
            continue
        detail = ev.get("detail") or {}
        if str(detail.get("sales_doc_id") or "") == sales_doc_id:
            return True
    return False


def _build_event(target: dict) -> dict:
    signals = target["signals"]
    has_signal = bool(signals.get("vat") or signals.get("heading_candidate"))
    event_name = EV_PENDING if has_signal else EV_SKIPPED
    if signals.get("vat"):
        next_action = "vat_resolver_will_auto_bind_post_pr2"
    elif signals.get("heading_candidate"):
        next_action = "heading_candidate_requires_corroboration"
    else:
        next_action = "operator_bind_client_name_manually"
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_name,
        "trigger_source": "backfill_skip_events_f255bbb5",
        "actor": "system",
        "detail": {
            "batch_id":                  BATCH_ID,
            "sales_doc_id":              target["sales_doc_id"],
            "sales_doc_no":              target["sales_doc_no"],
            "source_file_hint":          target["source_file_hint"],
            "reason":                    "client_name_unresolved_historical_backfill",
            "lines_count":               None,
            "value":                     None,
            "currency":                  None,
            "resolver_signals_seen":     signals,
            "resolver_passes_attempted": [
                "packing_row",
                "sales_doc",
                "shipment_doc_contractor",
                "filename",
                "preamble",
            ],
            "next_action":               next_action,
            "backfill_note":             (
                "Backfilled by PR 1 (Draft-birth visibility) for historical "
                "batch; original silent-drop was not audit-visible."
            ),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="Persist changes (default: dry-run).")
    args = ap.parse_args()

    if not AUDIT_PATH.exists():
        print(f"ERROR: audit.json not found at {AUDIT_PATH}", file=sys.stderr)
        return 2

    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    timeline = audit.setdefault("timeline", [])

    appended = 0
    skipped_already = 0
    plan = []
    for tgt in TARGETS:
        if _already_emitted(timeline, tgt["sales_doc_id"]):
            skipped_already += 1
            plan.append(f"SKIP (already emitted) sales_doc_id={tgt['sales_doc_id']} ({tgt['sales_doc_no']})")
            continue
        ev = _build_event(tgt)
        plan.append(f"APPEND event={ev['event']} sales_doc_id={tgt['sales_doc_id']} ({tgt['sales_doc_no']})")
        timeline.append(ev)
        appended += 1

    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"=== Backfill plan ({mode}) — batch {BATCH_ID} ===")
    for line in plan:
        print(f"  {line}")
    print(f"  → would append: {appended} ; already present: {skipped_already}")

    if not args.write:
        print("\nDry-run complete. Re-run with --write to persist.")
        return 0

    if appended == 0:
        print("Nothing to write.")
        return 0

    _write_atomic(AUDIT_PATH, audit)
    print(f"\nWrote {appended} new event(s) to {AUDIT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
