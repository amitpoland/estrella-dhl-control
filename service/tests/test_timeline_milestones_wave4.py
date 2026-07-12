"""
test_timeline_milestones_wave4.py — EJ Dashboard Stabilization Wave 4.

Pins the canonical workflow-milestone read-model that reconciles the V2 Timeline
against the REAL emitted events + audit fields. Covers each of the 9 operator
milestones and the specific frontend↔backend mismatches the trace found.
"""
from __future__ import annotations

from app.services.timeline_milestones import build_milestones


def _ms(audit):
    return {m["key"]: m for m in build_milestones(audit)}


def _ev(*events):
    return {"timeline": [{"ts": f"2026-07-13T10:{i:02d}:00+00:00", "event": e} for i, e in enumerate(events)]}


# ── Structure ───────────────────────────────────────────────────────────────

def test_read_model_shape_and_order():
    out = build_milestones({})
    assert isinstance(out, list) and len(out) == 16
    for m in out:
        assert set(m) == {"key", "label", "done", "ts", "source"}
        assert m["done"] is False and m["ts"] is None and m["source"] is None
    # canonical order starts with creation and ends with wFirma export
    keys = [m["key"] for m in out]
    assert keys[0] == "batch_created" and keys[-1] == "wfirma_pz_created"


# ── The 8 reconciled mismatches (real emitted event → correct milestone) ─────

def test_polish_description_from_description_ready_event():
    m = _ms(_ev("description_ready"))["polish_description_generated"]
    assert m["done"] is True and m["source"] == "event" and m["ts"]


def test_reply_package_from_any_of_four_emitters():
    for e in ("dsk_generated", "dhl_reply_package_auto_built",
              "dhl_self_clearance_reply_auto_built", "agency_package_auto_built"):
        assert _ms(_ev(e))["reply_package_generated"]["done"] is True, e


def test_reply_sent_from_dhl_or_agency_emitters():
    # DHL path (dsk_transfer_sent / reply_approved) AND agency/ACS path
    # (agency_email_sent) both satisfy "Reply sent".
    assert _ms(_ev("reply_approved"))["reply_sent"]["done"] is True
    assert _ms(_ev("dsk_transfer_sent"))["reply_sent"]["done"] is True
    assert _ms(_ev("agency_email_sent"))["reply_sent"]["done"] is True


def test_customs_parsed_from_parse_event_only():
    # agency_sad_parsed is a real PARSE event → done.
    assert _ms(_ev("agency_sad_parsed"))["customs_parsed"]["done"] is True


def test_customs_docs_imported_marks_upload_not_parsed():
    # customs_docs_imported fires when the SAD PDF lands on disk, BEFORE any
    # MRN/duty extraction — it must mark the UPLOAD milestone done but must NOT
    # falsely mark "Customs values parsed" done on an un-parsed upload.
    ms = _ms(_ev("customs_docs_imported"))
    assert ms["sad_imported"]["done"] is True
    assert ms["customs_parsed"]["done"] is False


def test_pz_generated_from_pz_generated_event_not_pz_created():
    # backend emits 'pz_generated'; milestone key is 'pz_created'
    m = _ms(_ev("pz_generated"))["pz_created"]
    assert m["done"] is True and m["source"] == "event"


def test_pz_confirmed_from_wfirma_events():
    assert _ms(_ev("wfirma_pz_created"))["pz_confirmed"]["done"] is True
    assert _ms(_ev("wfirma_pz_adopted"))["pz_confirmed"]["done"] is True


def test_dhl_precheck_direct_match():
    assert _ms(_ev("dhl_precheck_completed"))["dhl_precheck_completed"]["done"] is True


# ── The 3 event-less milestones (audit-field truth) ──────────────────────────

def test_verification_from_audit_field_no_event():
    # No timeline event; safe_to_run_pz is the canonical "verified" signal.
    m = _ms({"agency_sad_decision": {"safe_to_run_pz": True}})["verification_checks_passed"]
    assert m["done"] is True and m["source"] == "audit_field" and m["ts"] is None
    # cif_match also satisfies it (self-clearance path with no agency decision)
    assert _ms({"verification": {"cif_match": True}})["verification_checks_passed"]["done"] is True
    # a BLOCKED decision does NOT mark it done
    assert _ms({"agency_sad_decision": {"safe_to_run_pz": False}})["verification_checks_passed"]["done"] is False


def test_verification_agency_block_overrides_cif_match():
    # M1 regression: a recorded agency BLOCK is the final gate — even when the
    # CIF numbers matched, a blocked batch must NOT read "Verification passed".
    blocked = {"verification": {"cif_match": True},
               "agency_sad_decision": {"safe_to_run_pz": False}}
    assert _ms(blocked)["verification_checks_passed"]["done"] is False


def test_pz_unlocked_only_when_safe_to_run_true():
    assert _ms({"agency_sad_decision": {"safe_to_run_pz": True}})["pz_unlocked"]["done"] is True
    # the agency_sad_decision EVENT fires for a block too — must NOT mark unlocked
    blocked = {"agency_sad_decision": {"safe_to_run_pz": False},
               "timeline": [{"ts": "2026-07-13T10:00:00+00:00", "event": "agency_sad_decision"}]}
    assert _ms(blocked)["pz_unlocked"]["done"] is False


def test_pz_unlocked_from_clearance_status_self_clearance():
    # Self-clearance path never records an agency decision; the state engine sets
    # clearance_status == "pz_unlocked" instead. That must unlock the milestone.
    assert _ms({"clearance_status": "pz_unlocked"})["pz_unlocked"]["done"] is True
    # a non-unlocked clearance status must NOT
    assert _ms({"clearance_status": "dhl_email_received"})["pz_unlocked"]["done"] is False


def test_creation_milestones_survive_event_truncation():
    # timeline.py keeps only the last 200 events; the earliest creation events are
    # truncated first. Field fallbacks keep the first milestones honest.
    a = {"batch_id": "SHIPMENT_X", "inputs": {"invoices": ["inv.pdf"], "awb": "awb.pdf"},
         "timeline": []}
    ms = _ms(a)
    assert ms["batch_created"]["done"] is True and ms["batch_created"]["source"] == "audit_field"
    assert ms["invoice_uploaded"]["done"] is True
    assert ms["awb_uploaded"]["done"] is True
    # empty audit stays all-pending
    empty = _ms({})
    assert empty["batch_created"]["done"] is False


def test_pz_confirmed_from_doc_no_field_when_no_event():
    # /confirm-pz sets doc_no + pz_confirmed but emits no event
    assert _ms({"doc_no": "PZ/1/2026"})["pz_confirmed"]["done"] is True
    assert _ms({"pz_confirmed": True})["pz_confirmed"]["done"] is True


def test_customs_parsed_from_mrn_field_when_no_event():
    assert _ms({"customs_declaration": {"mrn": "26PL123456"}})["customs_parsed"]["done"] is True


# ── ts derivation + honesty ──────────────────────────────────────────────────

def test_ts_is_earliest_matching_event():
    audit = {"timeline": [
        {"ts": "2026-07-13T12:00:00+00:00", "event": "dsk_generated"},
        {"ts": "2026-07-13T09:00:00+00:00", "event": "agency_package_auto_built"},
    ]}
    assert _ms(audit)["reply_package_generated"]["ts"] == "2026-07-13T09:00:00+00:00"


def test_no_completion_without_signal():
    # An unrelated event does not complete an unrelated milestone.
    assert _ms(_ev("email_queued"))["pz_created"]["done"] is False
    assert _ms(_ev("email_queued"))["reply_sent"]["done"] is False


# ── Route integration: batch-detail injects the read-model ───────────────────

def test_batch_detail_includes_timeline_milestones(tmp_path, monkeypatch):
    """GET /api/v1/dashboard/batches/{id} must inject the canonical
    timeline_milestones projection (read-time, from the batch's audit.json)."""
    import json
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings

    root = tmp_path
    batch_id = "SHIPMENT_TLMS_2026-07_deadbeef"
    outdir = root / "outputs" / batch_id
    outdir.mkdir(parents=True)
    (outdir / "audit.json").write_text(json.dumps({
        "batch_id": batch_id, "tracking_no": "TLMS-1", "carrier": "DHL",
        "timeline": [
            {"ts": "2026-07-13T10:00:00+00:00", "event": "batch_created"},
            {"ts": "2026-07-13T11:00:00+00:00", "event": "description_ready"},
            {"ts": "2026-07-13T12:00:00+00:00", "event": "pz_generated"},
        ],
        "agency_sad_decision": {"safe_to_run_pz": True},
        "doc_no": "PZ/9/2026",
    }), encoding="utf-8")

    # batch_detail resolves via the module-level _OUTPUTS (bound at import), so
    # patch that directly rather than settings.storage_root.
    with patch("app.api.routes_dashboard._OUTPUTS", root / "outputs"):
        with patch.object(settings, "storage_root", root):
            with TestClient(app) as c:
                r = c.get(f"/api/v1/dashboard/batches/{batch_id}",
                          headers={"X-API-KEY": settings.api_key or "test-key"})
    assert r.status_code == 200, r.text
    ms = {m["key"]: m for m in r.json().get("timeline_milestones", [])}
    assert len(ms) == 16
    assert ms["batch_created"]["done"] is True
    assert ms["polish_description_generated"]["done"] is True   # description_ready
    assert ms["pz_created"]["done"] is True                     # pz_generated
    assert ms["verification_checks_passed"]["done"] is True     # safe_to_run_pz field
    assert ms["pz_confirmed"]["done"] is True                   # doc_no field
    assert ms["reply_sent"]["done"] is False                    # no signal
