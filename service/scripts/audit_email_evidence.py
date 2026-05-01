"""
audit_email_evidence.py — Cross-batch evidence validation.

Scans every batch in storage/outputs, reads audit.json and
email_evidence/by_awb/{awb}.json, compares what audit says happened vs
what evidence store says, and prints a mismatch table.

Usage:
    python scripts/audit_email_evidence.py [--storage PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── Storage resolution ────────────────────────────────────────────────────────

def _resolve_storage(override: Optional[str]) -> Path:
    if override:
        return Path(override)
    try:
        from app.core.config import settings
        return settings.storage_root
    except Exception:
        default = Path.home() / "Library" / "Application Support" / "estrellajewels" / "storage"
        return default


# ── JSON loader ────────────────────────────────────────────────────────────────

def _load(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else {}
    except Exception:
        return {}


# ── Evidence summary extractor ────────────────────────────────────────────────

def _default_summary() -> Dict[str, bool]:
    return {
        "dhl_request_received":    False,
        "our_dhl_reply_sent":      False,
        "our_dhl_reply_queued":    False,
        "dhl_documents_received":  False,
        "agency_forward_sent":     False,
        "agency_forward_queued":   False,
        "agency_sad_received":     False,
        "dhl_invoice_received":    False,
        "agency_invoice_received": False,
    }


# ── Audit-side truth extraction ───────────────────────────────────────────────

def _audit_expects(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Derive what the audit file says *should* be true about the email evidence.
    Returns a dict of field -> expected_value with a 'source' note.
    """
    expects: Dict[str, Any] = {}

    # DHL request received
    dhl_email = audit.get("dhl_email") or {}
    dhl_ticket = audit.get("dhl_ticket") or ""
    timeline_dhl_events = [
        e for e in (audit.get("timeline") or [])
        if e.get("event") in ("dhl_customs_email_received", "dhl_reply_sent_verified",
                               "dhl_reply_package_auto_built")
    ]
    if dhl_email or dhl_ticket or timeline_dhl_events:
        expects["dhl_request_received"] = {
            "expect": True,
            "source": f"dhl_ticket={dhl_ticket!r}" if dhl_ticket else "dhl_email field or timeline",
        }

    # Our DHL reply
    drp = audit.get("dhl_reply_package") or {}
    drp_sent = bool(drp.get("sent_at")) and (drp.get("status") == "sent" or drp.get("send_verified"))
    drp_queued = bool(drp.get("queued_at") or drp.get("email_id")) and not drp_sent
    timeline_reply_sent = any(
        e.get("event") == "dhl_reply_sent_verified"
        for e in (audit.get("timeline") or [])
    )
    if drp_sent or timeline_reply_sent:
        expects["our_dhl_reply_sent"] = {"expect": True, "source": "dhl_reply_package.sent_at / dhl_reply_sent_verified"}
    elif drp_queued:
        expects["our_dhl_reply_queued"] = {"expect": True, "source": "dhl_reply_package queued"}

    # Agency forward
    arp = audit.get("agency_reply_package") or {}
    arp_sent = bool(arp.get("sent_at")) and (arp.get("status") == "sent" or arp.get("send_verified"))
    arp_queued = bool(arp.get("queued_at") or arp.get("email_id")) and not arp_sent
    timeline_agency_sent = any(
        e.get("event") in ("agency_email_sent_verified", "agency_email_sent")
        for e in (audit.get("timeline") or [])
    )
    if arp_sent or timeline_agency_sent:
        expects["agency_forward_sent"] = {"expect": True, "source": "agency_reply_package.sent_at / agency_email_sent_verified"}
    elif arp_queued:
        expects["agency_forward_queued"] = {"expect": True, "source": "agency_reply_package queued"}

    return expects


# ── Email queue reader ────────────────────────────────────────────────────────

def _read_email_queue(batch_dir: Path) -> Optional[Dict[str, Any]]:
    p = batch_dir / "email_queue.json"
    return _load(p) if p.exists() else None


# ── Mismatch detection ────────────────────────────────────────────────────────

def _detect_mismatches(
    audit: Dict[str, Any],
    evidence: Dict[str, Any],
    email_queue: Optional[Dict[str, Any]],
    expects: Dict[str, Any],
) -> List[Dict[str, Any]]:
    summary = evidence.get("summary") or _default_summary()
    mismatches = []

    for field, exp_info in expects.items():
        actual = summary.get(field, False)
        expected = exp_info["expect"]
        if actual != expected:
            mismatches.append({
                "field":     field,
                "expected":  expected,
                "actual":    actual,
                "source":    exp_info["source"],
                "fix":       _recommend_fix(field, audit, evidence),
            })

    # Check for message_id=None (backfill) entries that were never promoted
    null_id_count = sum(
        1 for t in evidence.get("threads", [])
        for m in t.get("messages", [])
        if m.get("message_id") is None and m.get("source") == "audit_backfill"
    )
    if null_id_count:
        mismatches.append({
            "field":    "backfill_entries_unpromoted",
            "expected": 0,
            "actual":   null_id_count,
            "source":   "evidence threads",
            "fix":      "Run rescan to find Zoho message_ids and promote backfill entries.",
        })

    return mismatches


def _recommend_fix(field: str, audit: Dict[str, Any], evidence: Dict[str, Any]) -> str:
    if field == "dhl_request_received":
        ticket = audit.get("dhl_ticket") or ""
        if ticket:
            return f"Run backfill_from_audit — audit has dhl_ticket={ticket!r} but evidence missing dhl_request."
        return "Run email rescan (Zoho) to find incoming DHL email."

    if field == "our_dhl_reply_sent":
        drp = audit.get("dhl_reply_package") or {}
        if drp.get("sent_at"):
            return "Run backfill_from_audit — audit confirms sent but evidence missing."
        return "Check email_sender logs. DHL reply may not have been sent yet."

    if field == "our_dhl_reply_queued":
        return "DHL reply package queued but not confirmed sent. Check email_sender queue."

    if field == "agency_forward_sent":
        arp = audit.get("agency_reply_package") or {}
        if arp.get("sent_at"):
            return "Run backfill_from_audit — audit confirms agency forward sent."
        return "Agency forward queued but not confirmed sent. Check email_sender logs."

    if field == "agency_forward_queued":
        return "Agency forward is queued in audit but missing from evidence. Run backfill_from_audit."

    return "Investigate manually."


# ── Per-batch audit ───────────────────────────────────────────────────────────

def audit_batch(batch_dir: Path, storage_root: Path) -> Dict[str, Any]:
    audit_path = batch_dir / "audit.json"
    if not audit_path.exists():
        return {"batch_id": batch_dir.name, "error": "no audit.json"}

    audit = _load(audit_path)
    if not audit:
        return {"batch_id": batch_dir.name, "error": "audit.json empty/invalid"}

    awb = str(audit.get("awb") or audit.get("tracking_no") or "").strip()
    if not awb:
        return {"batch_id": batch_dir.name, "error": "no AWB in audit"}

    batch_id     = audit.get("batch_id") or batch_dir.name
    clearance    = audit.get("clearance_status") or ""
    pz_status    = audit.get("status") or ""

    evidence_path = storage_root / "email_evidence" / "by_awb" / f"{awb}.json"
    evidence = _load(evidence_path)

    email_queue = _read_email_queue(batch_dir)
    expects = _audit_expects(audit)
    mismatches = _detect_mismatches(audit, evidence, email_queue, expects)

    msg_count = sum(
        len(t.get("messages", []))
        for t in evidence.get("threads", [])
    )

    return {
        "batch_id":       batch_id,
        "awb":            awb,
        "clearance":      clearance,
        "pz_status":      pz_status,
        "evidence_exists": bool(evidence),
        "message_count":  msg_count,
        "last_scan_at":   evidence.get("last_scan_at"),
        "summary":        evidence.get("summary") or _default_summary(),
        "expects":        expects,
        "mismatches":     mismatches,
        "has_mismatches": bool(mismatches),
    }


# ── Table printer ─────────────────────────────────────────────────────────────

_COL_BATCH  = 50
_COL_AWB    = 14
_COL_CLR    = 30
_COL_MSGS   = 5
_COL_STATUS = 8


def _print_table(results: List[Dict[str, Any]]) -> None:
    sep = "-" * 120
    header = (
        f"{'BATCH_ID':<{_COL_BATCH}}  {'AWB':>{_COL_AWB}}  "
        f"{'CLEARANCE':<{_COL_CLR}}  {'MSGS':>{_COL_MSGS}}  {'OK?':<{_COL_STATUS}}"
    )
    print(sep)
    print(header)
    print(sep)

    ok_count   = 0
    warn_count = 0
    err_count  = 0

    for r in results:
        if "error" in r:
            err_count += 1
            print(f"{'[ERROR] ' + r['batch_id']:<{_COL_BATCH}}  {'':>{_COL_AWB}}  {r['error']}")
            continue

        status_marker = "OK" if not r["has_mismatches"] else "MISMATCH"
        if r["has_mismatches"]:
            warn_count += 1
        else:
            ok_count += 1

        print(
            f"{r['batch_id']:<{_COL_BATCH}}  {r['awb']:>{_COL_AWB}}  "
            f"{r['clearance']:<{_COL_CLR}}  {r['message_count']:>{_COL_MSGS}}  "
            f"{status_marker:<{_COL_STATUS}}"
        )

        for mm in r["mismatches"]:
            print(f"  {'':>{_COL_AWB}}  MISMATCH  field={mm['field']!r}  "
                  f"expected={mm['expected']}  actual={mm['actual']}")
            print(f"  {'':>{_COL_AWB}}  FIX:      {mm['fix']}")

    print(sep)
    print(f"  {len(results)} batches  |  {ok_count} OK  |  {warn_count} mismatches  |  {err_count} errors")
    print(sep)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--storage", help="Override storage root path")
    ap.add_argument("--batch",   help="Audit a single batch_id only")
    ap.add_argument("--json",    action="store_true", help="Output JSON instead of table")
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

    results = [audit_batch(d, storage) for d in batch_dirs]

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        _print_table(results)


if __name__ == "__main__":
    main()
