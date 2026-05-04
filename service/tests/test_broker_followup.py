"""
test_broker_followup.py — broker follow-up detector + send-flow coverage.

Covers
------
  Detector:
   1. detect invoice_refs_match → eligible
   2. detect cif_match → eligible
   3. extract single missing invoice ID
   4. extract multiple missing invoice IDs
   5. extract CIF totals and difference
   6. ineligible when status != blocked
   7. ineligible when only cn_match fails (override-eligible only)
   8. live-draft guard: no duplicate when 'draft' status exists
   9. live-draft guard: no duplicate when 'sent' status exists
  Routes:
  10. GET creates draft for eligible batch
  11. GET is idempotent on second call
  12. GET does not modify failed_checks / status / amendment_flags
  13. GET ignores override-eligible cn_match-only batches
  14. POST 404 when batch missing
  15. POST 409 when no draft exists
  16. POST 400 when 'to' is empty
  17. POST sends draft and marks status=sent
  18. POST does not modify failed_checks / status
  19. POST records queue_id and sent_at
  20. PRESERVED_KEYS includes broker_followup_drafts
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import require_api_key
from app.services import broker_followup_detector as bfd
from app.services.audit_merge import PRESERVED_KEYS


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_audit(
    *,
    batch_id: str = "B1",
    status: str = "blocked",
    failed_checks: List[str] | None = None,
    amendment_flags: List[str] | None = None,
    awb: str = "9765416334",
    mrn: str = "26PL44302D000W39R7",
    drafts: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "batch_id":       batch_id,
        "status":         status,
        "failed_checks":  failed_checks or [],
        "amendment_flags": amendment_flags or [],
        "inputs":         {"awb": f"{awb} Tracking.pdf"},
        "customs_declaration": {"mrn": mrn},
        "broker_followup_drafts": drafts or [],
    }


def _make_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    from app.api import routes_dashboard as rd
    from app.core.config import settings as s

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr(s, "storage_root", tmp_path)
    monkeypatch.setattr(rd, "_OUTPUTS", outputs, raising=False)

    app = FastAPI()
    app.include_router(rd.router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True), outputs


def _write_audit(outputs: Path, batch_id: str, audit: Dict[str, Any]) -> Path:
    d = outputs / batch_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


# ═══════════════════════════════════════════════════════════════════════════════
# Detector tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_detector_invoice_refs_match_eligible():
    audit = _make_audit(failed_checks=["invoice_refs_match"])
    assert bfd.is_eligible(audit) is True


def test_detector_cif_match_eligible():
    audit = _make_audit(failed_checks=["cif_match"])
    assert bfd.is_eligible(audit) is True


def test_detector_ineligible_when_not_blocked():
    audit = _make_audit(status="partial", failed_checks=["cif_match"])
    assert bfd.is_eligible(audit) is False


def test_detector_ineligible_when_only_cn_match():
    """cn_match alone is operator-overridable — no broker email needed."""
    audit = _make_audit(failed_checks=["cn_match"])
    assert bfd.is_eligible(audit) is False


def test_extract_single_missing_invoice():
    flags = ["SAD lists invoices not in PDF set: EJL/25-26/1043"]
    assert bfd.extract_missing_invoices(flags) == ["EJL/25-26/1043"]


def test_extract_multiple_missing_invoices():
    flags = ["SAD lists invoices not in PDF set: EJL/25-26/1043, EJL/25-26/1044"]
    assert bfd.extract_missing_invoices(flags) == [
        "EJL/25-26/1043",
        "EJL/25-26/1044",
    ]


def test_extract_cif_gap():
    flags = [
        "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
    ]
    gap = bfd.extract_cif_gap(flags)
    assert gap is not None
    assert gap["invoices"] == 11237.0
    assert gap["sad"]      == 17049.0
    assert gap["diff"]     == -5812.0


def test_no_live_draft_when_status_draft():
    drafts = [{"reason": bfd.DRAFT_REASON, "status": "draft"}]
    audit  = _make_audit(failed_checks=["cif_match"], drafts=drafts)
    assert bfd.has_live_draft(audit) is True


def test_no_live_draft_when_status_sent():
    drafts = [{"reason": bfd.DRAFT_REASON, "status": "sent"}]
    audit  = _make_audit(failed_checks=["cif_match"], drafts=drafts)
    assert bfd.has_live_draft(audit) is True


def test_build_draft_returns_none_when_live_draft_exists():
    drafts = [{"reason": bfd.DRAFT_REASON, "status": "draft"}]
    audit  = _make_audit(failed_checks=["cif_match"], drafts=drafts)
    assert bfd.build_draft(audit) is None


def test_normalize_awb_strips_spaces_in_tracking_no():
    audit = {
        "tracking_no": "97 6541 6334",
        "inputs": {"awb": "9765416334 Tracking.pdf"},
    }
    assert bfd._normalize_awb(audit) == "9765416334"


def test_normalize_awb_strips_filename_suffix():
    audit = {"inputs": {"awb": "9765416334 Tracking.pdf"}}
    assert bfd._normalize_awb(audit) == "9765416334"


def test_normalize_awb_clean_value_unchanged():
    audit = {"inputs": {"awb": "9765416334"}}
    assert bfd._normalize_awb(audit) == "9765416334"


def test_normalize_awb_mixed_separators():
    audit = {"tracking_no": "AWB-976 5416 334"}
    assert bfd._normalize_awb(audit) == "9765416334"


def test_normalize_awb_returns_empty_when_no_digits():
    audit = {"tracking_no": "no digits here", "inputs": {"awb": "AWB only"}}
    assert bfd._normalize_awb(audit) == ""


def test_normalize_awb_skips_short_candidate_to_next():
    """First candidate has fewer than 8 digits → fall through to next."""
    audit = {
        "tracking_no": "12-34",                       # 4 digits, too short
        "inputs": {"awb": "9765416334 Tracking.pdf"}, # valid
    }
    assert bfd._normalize_awb(audit) == "9765416334"


def test_draft_subject_uses_normalized_awb_from_spaced_tracking_no():
    """End-to-end: spaced tracking_no must yield clean AWB in subject."""
    audit = _make_audit(
        failed_checks=["cif_match"],
        amendment_flags=[
            "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
        ],
    )
    audit["tracking_no"]   = "97 6541 6334"
    audit["inputs"]["awb"] = "9765416334 Tracking.pdf"
    draft = bfd.build_draft(audit)
    assert draft is not None
    assert "AWB 9765416334" in draft["subject"]
    assert "97 6541 6334"   not in draft["subject"]
    assert "AWB: 9765416334" in draft["body"]


def test_build_draft_renders_full_email():
    audit = _make_audit(
        failed_checks=["invoice_refs_match", "cif_match"],
        amendment_flags=[
            "SAD lists invoices not in PDF set: EJL/25-26/1043",
            "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
        ],
    )
    draft = bfd.build_draft(audit)
    assert draft is not None
    assert draft["status"] == "draft"
    assert draft["reason"] == bfd.DRAFT_REASON
    assert "9765416334"        in draft["subject"]
    assert "26PL44302D000W39R7" in draft["subject"]
    assert "EJL/25-26/1043"     in draft["body"]
    assert "USD 5,812"          in draft["body"]
    assert "USD 17,049"         in draft["body"]


# ═══════════════════════════════════════════════════════════════════════════════
# Route tests — GET /dashboard/broker-followups
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_creates_draft(tmp_path, monkeypatch):
    client, outputs = _make_client(tmp_path, monkeypatch)
    audit = _make_audit(
        batch_id="B_CIF",
        failed_checks=["cif_match"],
        amendment_flags=[
            "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
        ],
    )
    _write_audit(outputs, "B_CIF", audit)

    r = client.get("/dashboard/broker-followups")
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1
    assert len(body["drafts"]) == 1
    assert body["drafts"][0]["batch_id"] == "B_CIF"

    # Persisted to disk
    on_disk = json.loads((outputs / "B_CIF" / "audit.json").read_text())
    assert len(on_disk["broker_followup_drafts"]) == 1
    assert on_disk["broker_followup_drafts"][0]["status"] == "draft"


def test_get_is_idempotent(tmp_path, monkeypatch):
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B_IDEM", _make_audit(
        batch_id="B_IDEM",
        failed_checks=["cif_match"],
        amendment_flags=[
            "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
        ],
    ))

    r1 = client.get("/dashboard/broker-followups")
    r2 = client.get("/dashboard/broker-followups")
    assert r1.json()["created"] == 1
    assert r2.json()["created"] == 0
    assert len(r2.json()["drafts"]) == 1

    # Disk still has exactly one draft
    on_disk = json.loads((outputs / "B_IDEM" / "audit.json").read_text())
    assert len(on_disk["broker_followup_drafts"]) == 1


def test_get_does_not_modify_other_audit_fields(tmp_path, monkeypatch):
    client, outputs = _make_client(tmp_path, monkeypatch)
    audit = _make_audit(
        batch_id="B_PURE",
        failed_checks=["cif_match", "cn_match"],
        amendment_flags=[
            "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
            "Review needed: SAD / invoice set may require amendment.",
        ],
    )
    audit["status"] = "blocked"
    _write_audit(outputs, "B_PURE", audit)

    client.get("/dashboard/broker-followups")
    on_disk = json.loads((outputs / "B_PURE" / "audit.json").read_text())

    assert on_disk["status"] == "blocked"
    assert on_disk["failed_checks"] == ["cif_match", "cn_match"]
    assert on_disk["amendment_flags"] == audit["amendment_flags"]
    assert on_disk["customs_declaration"] == audit["customs_declaration"]


def test_get_ignores_cn_match_only_batches(tmp_path, monkeypatch):
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B_CN", _make_audit(
        batch_id="B_CN",
        failed_checks=["cn_match", "exporter_match"],
        amendment_flags=[
            "Exporter mismatch — invoice: 'Estrella Jewels LLP' / SAD: 'ESTRELLA'",
        ],
    ))

    r = client.get("/dashboard/broker-followups")
    body = r.json()
    assert body["created"] == 0
    assert body["drafts"]  == []


# ═══════════════════════════════════════════════════════════════════════════════
# Route tests — POST /dashboard/broker-followups/{batch_id}/send
# ═══════════════════════════════════════════════════════════════════════════════

def test_post_404_when_batch_missing(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    r = client.post(
        "/dashboard/broker-followups/NOPE/send",
        json={"to": "broker@example.com"},
    )
    assert r.status_code == 404


def test_post_409_when_no_draft(tmp_path, monkeypatch):
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B_NO_DRAFT", _make_audit(
        batch_id="B_NO_DRAFT",
        failed_checks=["cif_match"],
    ))   # eligible but no GET called → no draft yet
    r = client.post(
        "/dashboard/broker-followups/B_NO_DRAFT/send",
        json={"to": "broker@example.com"},
    )
    assert r.status_code == 409


def test_post_400_when_to_empty(tmp_path, monkeypatch):
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B_BAD_TO", _make_audit(
        batch_id="B_BAD_TO",
        failed_checks=["cif_match"],
        amendment_flags=[
            "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
        ],
    ))
    client.get("/dashboard/broker-followups")   # create draft
    r = client.post("/dashboard/broker-followups/B_BAD_TO/send", json={"to": ""})
    assert r.status_code == 400


def test_post_sends_draft_and_marks_sent(tmp_path, monkeypatch):
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B_SEND", _make_audit(
        batch_id="B_SEND",
        failed_checks=["cif_match"],
        amendment_flags=[
            "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
        ],
    ))
    client.get("/dashboard/broker-followups")   # creates draft

    # Stub queue_email to avoid hitting the real queue
    from app.api import routes_dashboard as rd
    monkeypatch.setattr(rd._email_svc, "queue_email",
                        lambda **kw: "fake-queue-id-123")

    r = client.post(
        "/dashboard/broker-followups/B_SEND/send",
        json={"to": "broker@example.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"]    == "sent"
    assert body["queue_id"]  == "fake-queue-id-123"
    assert body["sent_to"]   == "broker@example.com"

    on_disk = json.loads((outputs / "B_SEND" / "audit.json").read_text())
    drafts = on_disk["broker_followup_drafts"]
    assert len(drafts) == 1
    assert drafts[0]["status"]    == "sent"
    assert drafts[0]["queue_id"]  == "fake-queue-id-123"
    assert "sent_at" in drafts[0]


def test_post_does_not_modify_failed_checks_or_status(tmp_path, monkeypatch):
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B_PURE_SEND", _make_audit(
        batch_id="B_PURE_SEND",
        failed_checks=["cif_match", "invoice_refs_match"],
        amendment_flags=[
            "SAD lists invoices not in PDF set: EJL/25-26/1043",
            "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
        ],
    ))
    client.get("/dashboard/broker-followups")

    from app.api import routes_dashboard as rd
    monkeypatch.setattr(rd._email_svc, "queue_email",
                        lambda **kw: "qid-987")

    client.post(
        "/dashboard/broker-followups/B_PURE_SEND/send",
        json={"to": "broker@example.com"},
    )
    on_disk = json.loads((outputs / "B_PURE_SEND" / "audit.json").read_text())
    assert on_disk["status"] == "blocked"
    assert set(on_disk["failed_checks"]) == {"cif_match", "invoice_refs_match"}
    assert on_disk["amendment_flags"][0].startswith("SAD lists invoices")


def test_post_after_send_no_new_draft_on_rescan(tmp_path, monkeypatch):
    """Once 'sent', subsequent GET must not create a new draft (idempotency)."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B_RESCAN", _make_audit(
        batch_id="B_RESCAN",
        failed_checks=["cif_match"],
        amendment_flags=[
            "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)",
        ],
    ))
    client.get("/dashboard/broker-followups")

    from app.api import routes_dashboard as rd
    monkeypatch.setattr(rd._email_svc, "queue_email", lambda **kw: "qid-555")

    client.post("/dashboard/broker-followups/B_RESCAN/send",
                json={"to": "broker@example.com"})

    r2 = client.get("/dashboard/broker-followups")
    assert r2.json()["created"] == 0
    on_disk = json.loads((outputs / "B_RESCAN" / "audit.json").read_text())
    # Still exactly one entry, status=sent
    assert len(on_disk["broker_followup_drafts"]) == 1
    assert on_disk["broker_followup_drafts"][0]["status"] == "sent"


# ═══════════════════════════════════════════════════════════════════════════════
# audit_merge integration
# ═══════════════════════════════════════════════════════════════════════════════

def test_preserved_keys_includes_broker_followup_drafts():
    assert "broker_followup_drafts" in PRESERVED_KEYS


def test_drafts_survive_audit_regen():
    """merge_regenerated_audit must preserve broker_followup_drafts."""
    from app.services.audit_merge import merge_regenerated_audit
    existing = {
        "batch_id": "B1",
        "status":   "blocked",
        "broker_followup_drafts": [
            {"draft_id": "abc", "status": "draft", "reason": bfd.DRAFT_REASON},
        ],
    }
    regenerated = {
        "batch_id": "B1",
        "status":   "blocked",
        # engine never sets this key
    }
    merged = merge_regenerated_audit(existing, regenerated)
    assert merged.get("broker_followup_drafts") == existing["broker_followup_drafts"]
