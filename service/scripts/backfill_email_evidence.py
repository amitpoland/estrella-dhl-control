#!/usr/bin/env python3
"""
backfill_email_evidence.py

Walk every audit.json and create email evidence entries from existing fields:
  - dhl_email / dhl_email_received_at      → dhl_request (incoming)
  - dhl_reply_package                      → our_dhl_reply (outgoing)
  - dhl_documents_received                 → dhl_documents (incoming)
  - agency_reply_package                   → agency_forward (outgoing)
  - agency_documents                       → agency_sad_reply (incoming)
  - service_invoices[]                     → dhl_invoice / agency_invoice
  - dhl_followup events (each followup)    → our_dhl_reply (outgoing, follow-up)

All backfilled records:
  - source = "audit_backfill"
  - message_id = None  (later real Zoho fetch can promote them)
  - attachments = pre-existing local file paths only — never fabricated bytes

Read-only over audit.json. Never mutates audit, financial, customs or sent records.

Usage:
  python3 service/scripts/backfill_email_evidence.py
  python3 service/scripts/backfill_email_evidence.py --batch SHIPMENT_xxx
  python3 service/scripts/backfill_email_evidence.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402
from app.services import email_evidence_store as evs  # noqa: E402

OUTPUTS = settings.storage_root / "outputs"


def _to_list(v):
    if v is None: return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _backfill_dhl_request(awb: str, audit: dict, dry: bool):
    de = audit.get("dhl_email") or {}
    rcv_at = audit.get("dhl_email_received_at") or de.get("received_at")
    if not (de or rcv_at):
        return 0
    msg = {
        "message_id":   None,
        "thread_id":    f"backfill:dhl_request:{awb}",
        "direction":    "incoming",
        "sender":       de.get("from") or "odprawacelna@dhl.com",
        "subject":      de.get("subject", f"DHL request — {awb}"),
        "body_text":    de.get("body_text", ""),
        "timestamp":    rcv_at or "",
        "event_type":   "dhl_request",
        "matched_identifiers": {"awb": True},
        "attachments":  [],
    }
    if not dry: evs.save_message(awb, msg, source="audit_backfill")
    return 1


def _backfill_our_dhl_reply(awb: str, audit: dict, dry: bool):
    drp = audit.get("dhl_reply_package") or {}
    if not (drp.get("status") or drp.get("sent_at") or drp.get("queue_id")):
        return 0
    files = drp.get("files", []) or []
    sent_at = drp.get("sent_at") or ""
    truly_sent = bool(sent_at) and (drp.get("status") == "sent" or drp.get("send_verified") is True)
    msg = {
        "message_id":   None,
        "thread_id":    f"backfill:our_dhl_reply:{awb}",
        "direction":    "outgoing",
        "sender":       "import@estrellajewels.eu",
        "to":           drp.get("to", ["odprawacelna@dhl.com"]),
        "subject":      drp.get("subject", f"AC DHL — {awb}"),
        "body_text":    "",
        "timestamp":    sent_at or drp.get("queued_at", ""),
        "event_type":   "our_dhl_reply",
        "matched_identifiers": {"awb": True},
        "attachments":  [
            {"filename": Path(f).name if isinstance(f, str) else f.get("name", ""),
             "local_path": f if isinstance(f, str) else f.get("path", ""),
             "sha256": "", "document_type": ""}
            for f in files
        ],
        "processed":    truly_sent,
        # Queued vs sent distinction — Email Evidence V2 hardening
        "delivery_status": "sent" if truly_sent else "queued",
        "sent_at":         sent_at if truly_sent else None,
        "queued_at":       drp.get("queued_at"),
    }
    if not dry: evs.save_message(awb, msg, source="audit_backfill")
    return 1


def _backfill_dhl_documents(awb: str, audit: dict, dry: bool):
    dd = audit.get("dhl_documents_received") or {}
    files = dd.get("files", []) or []
    if not files:
        return 0
    msg = {
        "message_id":   None,
        "thread_id":    f"backfill:dhl_documents:{awb}",
        "direction":    "incoming",
        "sender":       "odprawacelna@dhl.com",
        "subject":      f"DHL documents — {awb}",
        "body_text":    "",
        "timestamp":    dd.get("received_at", ""),
        "event_type":   "dhl_documents",
        "matched_identifiers": {"awb": True},
        "attachments":  [
            {"filename": f.get("name", "") or Path(str(f.get("path", ""))).name,
             "local_path": f.get("path", ""), "sha256": "",
             "document_type": f.get("type", "")}
            for f in files
        ],
    }
    if not dry: evs.save_message(awb, msg, source="audit_backfill")
    return 1


def _backfill_agency_forward(awb: str, audit: dict, dry: bool):
    arp = audit.get("agency_reply_package") or {}
    if not (arp.get("status") or arp.get("sent_at") or arp.get("queue_id")):
        return 0
    files = arp.get("files", []) or []
    sent_at = arp.get("sent_at") or ""
    # Truly sent only when the audit positively confirms it. Old records that
    # only carry a queue_id (no sent_at, no status='sent') are queued, NOT sent.
    truly_sent = bool(sent_at) and (arp.get("status") == "sent" or arp.get("send_verified") is True)
    msg = {
        "message_id":   None,
        "thread_id":    f"backfill:agency_forward:{awb}",
        "direction":    "outgoing",
        "sender":       "import@estrellajewels.eu",
        "to":           arp.get("to", ["piotr@acspedycja.pl"]),
        "subject":      arp.get("subject", f"Agency forward — {awb}"),
        "body_text":    "",
        "timestamp":    sent_at or arp.get("queued_at", ""),
        "event_type":   "agency_forward",
        "matched_identifiers": {"awb": True},
        "attachments":  [
            {"filename": Path(str(f)).name if isinstance(f, str) else f.get("name", ""),
             "local_path": f if isinstance(f, str) else f.get("path", ""),
             "sha256": "", "document_type": ""}
            for f in files
        ],
        "processed":    truly_sent,
        "delivery_status": "sent" if truly_sent else "queued",
        "sent_at":         sent_at if truly_sent else None,
        "queued_at":       arp.get("queued_at"),
    }
    if not dry: evs.save_message(awb, msg, source="audit_backfill")
    return 1


def _backfill_agency_sad_reply(awb: str, audit: dict, dry: bool):
    ad = audit.get("agency_documents") or {}
    files = ad.get("files", []) or []
    if not (files or ad.get("received_at")):
        return 0
    msg = {
        "message_id":   None,
        "thread_id":    f"backfill:agency_sad_reply:{awb}",
        "direction":    "incoming",
        "sender":       "piotr@acspedycja.pl",
        "subject":      f"SAD/PZC reply — {awb}",
        "body_text":    "",
        "timestamp":    ad.get("received_at", ""),
        "event_type":   "agency_sad_reply",
        "matched_identifiers": {"awb": True},
        "attachments":  [
            {"filename": f.get("name", "") or Path(str(f.get("path", ""))).name,
             "local_path": f.get("path", ""), "sha256": "",
             "document_type": f.get("type", "")}
            for f in files
        ],
    }
    if not dry: evs.save_message(awb, msg, source="audit_backfill")
    return 1


def _backfill_service_invoices(awb: str, audit: dict, dry: bool):
    invs = audit.get("service_invoices") or []
    n = 0
    for inv in invs:
        vendor = (inv.get("vendor") or "").lower()
        ev_type = "dhl_invoice" if "dhl" in vendor else (
                  "agency_invoice" if any(k in vendor for k in ("acspedycja", "ganther", "agency")) else "agency_invoice")
        sender  = "odprawacelna@dhl.com" if ev_type == "dhl_invoice" else "piotr@acspedycja.pl"
        msg = {
            "message_id":   None,
            "thread_id":    f"backfill:{ev_type}:{awb}:{inv.get('invoice_no','?')}",
            "direction":    "incoming",
            "sender":       sender,
            "subject":      f"Service invoice {inv.get('invoice_no','?')} — {awb}",
            "body_text":    "",
            "timestamp":    inv.get("received_at", ""),
            "event_type":   ev_type,
            "matched_identifiers": {"awb": True, "invoice_numbers": [inv.get("invoice_no")] if inv.get("invoice_no") else []},
            "attachments":  [
                {"filename": Path(str(inv.get("file", ""))).name,
                 "local_path": inv.get("file", ""), "sha256": "",
                 "document_type": "invoice"}
            ] if inv.get("file") else [],
        }
        if not dry: evs.save_message(awb, msg, source="audit_backfill")
        n += 1
    return n


BACKFILLERS = (
    _backfill_dhl_request,
    _backfill_our_dhl_reply,
    _backfill_dhl_documents,
    _backfill_agency_forward,
    _backfill_agency_sad_reply,
    _backfill_service_invoices,
)


def backfill_one(batch_dir: Path, dry: bool) -> dict:
    audit_path = batch_dir / "audit.json"
    if not audit_path.exists():
        return {"batch_id": batch_dir.name, "error": "audit missing"}
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"batch_id": batch_dir.name, "error": f"audit unreadable: {e}"}
    awb = audit.get("awb") or audit.get("tracking_no") or ""
    if not awb:
        return {"batch_id": batch_dir.name, "error": "no AWB"}
    counts = {}
    for fn in BACKFILLERS:
        n = fn(str(awb), audit, dry)
        if n:
            counts[fn.__name__.replace("_backfill_", "")] = n
    if not dry:
        evs.link_batch(str(awb), batch_dir.name)
    return {"batch_id": batch_dir.name, "awb": str(awb), "events": counts, "total": sum(counts.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", help="Single batch_id to backfill")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.batch:
        batches = [OUTPUTS / args.batch]
    else:
        batches = sorted(p for p in OUTPUTS.iterdir() if p.is_dir() and (p / "audit.json").exists())

    grand_total = 0
    for d in batches:
        r = backfill_one(d, args.dry_run)
        if "error" in r:
            print(f"  [SKIP] {r['batch_id']}: {r['error']}")
            continue
        marker = "·" if not r["total"] else "✓"
        print(f"  {marker} {r['batch_id']:55s} awb={r['awb']:>14}  events={r['total']:2}  {r['events'] or ''}")
        grand_total += r["total"]
    print(f"\n--- {len(batches)} batches scanned · {grand_total} evidence events {'(dry-run, not written)' if args.dry_run else 'written'}")


if __name__ == "__main__":
    main()
