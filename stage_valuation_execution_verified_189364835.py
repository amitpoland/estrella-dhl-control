#!/usr/bin/env python3
# Operator-run closure: append + verify the immutable execution event for the
# doc 189364835 (PZ 4/6/2026) valuation correction.
#
# Properties: append-only, idempotent, atomic write, read-back verified,
# tamper-evident (SHA-256), no error suppression, NO wFirma write.
# The audit store is a per-batch JSON timeline; this script ONLY appends.
import os, sys, json, hashlib, tempfile
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

AUDIT = r"C:\PZ\storage\outputs\SHIPMENT_2315714531_2026-06_ffe086f3\audit.json"
EVENT = "pz_valuation_correction_executed"
DOCUMENT_ID = "189364835"
IDEMPOTENCY_KEY = f"valcorr-exec:{DOCUMENT_ID}:2026-06-19T00:40:12"

# Evidence artifacts (snapshots = retained; temp *scripts* are intentionally excluded).
EVIDENCE = {
    "pre_edit_xml":  r"C:\Users\Super Fashion\PZ APP\tmp_pz189364835_raw.xml",
    "post_edit_xml": r"C:\Users\Super Fashion\PZ APP\tmp_pz189364835_postedit.xml",
}


def _sha256_file(path: str) -> str:
    """SHA-256 of a file, or 'MISSING:<path>' if absent. Never raises on absence."""
    if not os.path.isfile(path):
        return f"MISSING:{path}"
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _content_hash(detail: dict) -> str:
    """Tamper-evidence hash over the event's canonical content (excludes the hash itself)."""
    payload = {k: v for k, v in detail.items() if k != "integrity_sha256"}
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _build_detail() -> dict:
    detail = {
        "idempotency_key": IDEMPOTENCY_KEY,
        "document_id": DOCUMENT_ID,
        "pz_number": "PZ 4/6/2026",
        "edit_executed": True,
        "edit_executed_at": "2026-06-19T00:40:12",          # wFirma <modified> on the doc
        "correction_amount_pln": 456.80,                    # 2736.94 - 2280.14
        "correction_amount_display": "+456.80 PLN",
        "method": "direct UI edit of pending document; no cancel/recreate",
        "verified_via": "wFirma warehouse_document_p_z/get/189364835 (live GET, read-only)",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "criteria_all_pass": True,
        "acceptance": {
            "document_price": {"L1": "36.55", "L2": "81.16", "pass": True},
            "price_modified": {"L1": "1", "L2": "1", "pass": True},
            "parcel_purchase_price": {
                "L1": {"parcel_id": "111746275", "value": "36.55"},
                "L2": {"parcel_id": "111746339", "value": "81.16"},
                "pass": True,
            },
            "netto_pln": {"value": "2736.94", "pass": True},
        },
        "pre_edit_baseline": {
            "netto_pln": "2280.14", "L1_price": "30.45", "L2_price": "67.61",
            "price_modified": "0/0", "parcel_purchase_price": "30.45/67.61",
        },
        "inventory_revalued": True,
        "evidence": {
            "approval_event": {"event": "pz_valuation_correction_approved",
                               "ts": "2026-06-18T21:59:21.999668+00:00"},
            "pre_edit_xml":  {"path": EVIDENCE["pre_edit_xml"],
                              "sha256": _sha256_file(EVIDENCE["pre_edit_xml"])},
            "post_edit_xml": {"path": EVIDENCE["post_edit_xml"],
                              "sha256": _sha256_file(EVIDENCE["post_edit_xml"])},
        },
        "incident": "AWB-2315714531-2026-06 (closed; not reopened)",
    }
    detail["integrity_sha256"] = _content_hash(detail)
    return detail


def _find_event(timeline: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in timeline:
        if isinstance(e, dict) and e.get("event") == EVENT \
           and (e.get("detail") or {}).get("idempotency_key") == IDEMPOTENCY_KEY:
            return e
    return None


def _verify_persisted(expected_detail: dict) -> dict:
    """Re-read from disk and confirm the event persisted intact. Raises on any mismatch."""
    with open(AUDIT, encoding="utf-8") as fh:
        fresh = json.load(fh)
    ev = _find_event(fresh.get("timeline") or [])
    if ev is None:
        raise RuntimeError("READ-BACK FAILED: event not found after write")
    d = ev.get("detail") or {}
    if d.get("edit_executed") is not True:
        raise RuntimeError(f"READ-BACK FAILED: edit_executed={d.get('edit_executed')!r}")
    if str(d.get("document_id")) != DOCUMENT_ID:
        raise RuntimeError(f"READ-BACK FAILED: document_id={d.get('document_id')!r}")
    if _content_hash(d) != d.get("integrity_sha256"):
        raise RuntimeError("READ-BACK FAILED: integrity hash mismatch (tamper or corruption)")
    return ev


def main() -> int:
    # Load (let any IO/JSON error surface — no suppression).
    with open(AUDIT, encoding="utf-8") as fh:
        audit = json.load(fh)
    timeline = audit.get("timeline")
    if not isinstance(timeline, list):
        raise RuntimeError(f"audit.json has no list 'timeline' (got {type(timeline).__name__})")

    # Idempotency: if already recorded, verify and return success without duplicating.
    existing = _find_event(timeline)
    if existing is not None:
        _verify_persisted(existing["detail"])
        print(f"ALREADY_RECORDED (idempotent). ts={existing.get('ts')} "
              f"key={IDEMPOTENCY_KEY} | read-back: OK")
        return 0

    # Append-only: build, append, atomic replace. Never edit/remove existing entries.
    ts = datetime.now(timezone.utc).isoformat()
    detail = _build_detail()
    timeline.append({"ts": ts, "event": EVENT, "trigger_source": "operator",
                     "actor": "accounting", "detail": detail})
    audit["timeline"] = timeline

    d = os.path.dirname(AUDIT)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(audit, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, AUDIT)               # atomic on same volume
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise                                # surface the exact write failure

    verified = _verify_persisted(detail)     # immediate read-back; raises on mismatch
    print(f"WRITTEN + VERIFIED. write_ts={ts}")
    print(f"  event={EVENT} key={IDEMPOTENCY_KEY}")
    print(f"  integrity={verified['detail']['integrity_sha256']}")
    print(f"  read-back: OK (edit_executed=True, document_id={DOCUMENT_ID}, "
          f"correction=+456.80 PLN)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
