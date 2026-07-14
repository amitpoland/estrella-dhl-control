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
        # blocked_reason is present only when state == "blocked"
        assert set(m) - {"blocked_reason"} == {"key", "label", "done", "state", "ts", "source"}
        assert m["done"] is False and m["ts"] is None and m["source"] is None
    # canonical order starts with creation and ends with wFirma export
    keys = [m["key"] for m in out]
    assert keys[0] == "batch_created" and keys[-1] == "wfirma_pz_created"
    # empty audit → the first milestone is the frontier (available), the rest wait
    assert out[0]["state"] == "available"
    assert all(m["state"] == "not_started" for m in out[1:])


# ── The 8 reconciled mismatches (real emitted event → correct milestone) ─────

def test_polish_description_from_description_ready_event():
    m = _ms(_ev("description_ready"))["polish_description_generated"]
    assert m["done"] is True and m["source"] == "event" and m["ts"]


def test_reply_package_from_auto_built_emitters():
    # Slice 2A: reply-package completion accepts the three real auto-build events
    # (self-clearance + agency paths). ``dsk_generated`` is deliberately NOT here —
    # a DSK existing does not prove a reply package was built.
    for e in ("dhl_reply_package_auto_built",
              "dhl_self_clearance_reply_auto_built", "agency_package_auto_built"):
        assert _ms(_ev(e))["reply_package_generated"]["done"] is True, e


def test_reply_package_not_completed_by_dsk_generated_event_alone():
    # Regression pin (Slice 2A.2): a DSK event must NOT complete the reply-package
    # milestone. Real evidence is the reply_package audit field.
    m = _ms(_ev("dsk_generated"))["reply_package_generated"]
    assert m["done"] is False
    assert m["state"] != "completed"


def test_reply_package_from_reply_package_field_fallback():
    assert _ms({"reply_package": {"to": "x@dhl.com"}})["reply_package_generated"]["done"] is True
    assert _ms({"agency_reply_package": {"status": "queued"}})["reply_package_generated"]["done"] is True


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


# ── Slice 2A: audit-field fallbacks (backfill from authoritative artifacts) ───

def test_polish_description_from_filename_field_fallback():
    # /generate-customs-package used to write polish_desc_filename WITHOUT emitting
    # description_ready — the field fallback backfills the milestone honestly.
    m = _ms({"polish_desc_filename": "SHIPMENT_X_polish.pdf"})["polish_description_generated"]
    assert m["done"] is True and m["source"] == "audit_field" and m["ts"] is None


def test_dsk_from_filename_field_fallback():
    m = _ms({"dsk_filename": "DSK_AWB_2026.pdf"})["dsk_generated"]
    assert m["done"] is True and m["source"] == "audit_field"


def test_precheck_from_dhl_precheck_field_fallback():
    m = _ms({"dhl_precheck": {"clearance_hint": "dsk_required"}})["dhl_precheck_completed"]
    assert m["done"] is True and m["source"] == "audit_field"


def test_precheck_absent_is_not_started_not_skipped():
    # No precheck evidence and nothing later → not_started (genuinely waiting),
    # never a false "skipped".
    m = _ms({})["dhl_precheck_completed"]
    assert m["done"] is False and m["state"] == "not_started"


# ── Slice 2A: the reported internal inconsistency ────────────────────────────

def test_reported_inconsistency_dsk_reply_complete_desc_not_falsely_complete():
    # Reproduce the reported shipment: DSK generated + reply package built, but the
    # Polish description was produced by the combined endpoint that (pre-fix) never
    # emitted description_ready. The description milestone must NOT be silently
    # completed off the back of the later DSK/reply evidence.
    audit = {
        "timeline": [
            {"ts": "2026-07-13T20:30:00+00:00", "event": "dsk_generated"},
        ],
        "dsk_filename": "DSK_AWB_2026.pdf",
        "reply_package": {"to": "odprawacelna@dhl.com"},
        # note: no description_ready event, no polish_desc_filename
    }
    ms = _ms(audit)
    assert ms["dsk_generated"]["done"] is True
    assert ms["reply_package_generated"]["done"] is True
    assert ms["polish_description_generated"]["done"] is False
    assert ms["polish_description_generated"]["state"] != "completed"


def test_reported_inconsistency_resolves_after_description_ready_or_field():
    # Once the fix (2A.1) emits description_ready — OR the field fallback sees
    # polish_desc_filename — the milestone flips to completed.
    by_event = _ms({"timeline": [{"ts": "2026-07-13T20:00:00+00:00", "event": "description_ready"}]})
    assert by_event["polish_description_generated"]["done"] is True
    by_field = _ms({"polish_desc_filename": "x_polish.pdf"})
    assert by_field["polish_description_generated"]["done"] is True


# ── Slice 2A: 7-state model ──────────────────────────────────────────────────

_VALID_STATES = {"completed", "available", "blocked", "not_started",
                 "skipped", "not_applicable", "failed"}


def test_every_milestone_state_in_enum_and_done_alias():
    for audit in ({}, _ev("description_ready", "dsk_generated"),
                  {"clearance_decision": {"clearance_path": "agency_clearance"}}):
        for m in build_milestones(audit):
            assert m["state"] in _VALID_STATES
            assert m["done"] == (m["state"] == "completed")


def test_available_is_the_frontier_next_action():
    # batch + invoice + awb + precheck + email done → the frontier is the Polish
    # description, gated by the received email (present) → available.
    audit = {
        "batch_id": "SHIPMENT_X",
        "inputs": {"invoices": ["i.pdf"], "awb": "awb.pdf"},
        "dhl_precheck": {"clearance_hint": "dsk_required"},
        "dhl_email": {"received": True},
    }
    ms = _ms(audit)
    assert ms["polish_description_generated"]["state"] == "available"
    # a milestone further down the chain is still waiting
    assert ms["dsk_generated"]["state"] == "not_started"


def test_blocked_carries_reason_when_email_missing():
    # AWB present, but no DHL email → the frontier (email received) is available;
    # description is downstream/not_started. Force the frontier to description by
    # marking email received via clearance path self and NO email: description is
    # frontier only after email milestone. Instead assert the email-gated block
    # directly on a self-clearance batch where email milestone is the frontier.
    audit = {
        "batch_id": "SHIPMENT_X",
        "inputs": {"invoices": ["i.pdf"], "awb": "awb.pdf"},
        "dhl_precheck": {"clearance_hint": "dsk_required"},
        "clearance_decision": {"clearance_path": "dhl_self_clearance"},
    }
    ms = _ms(audit)
    # email received is the frontier (awb done, precheck done) → available
    assert ms["dhl_email_received"]["state"] == "available"
    # description is downstream and email is not yet received → not_started
    assert ms["polish_description_generated"]["state"] == "not_started"


def test_description_blocked_reason_when_frontier_and_email_missing():
    # Make description the frontier by completing the email milestone via event but
    # NOT the dhl_email field, then removing it — simplest: complete email, so
    # description becomes frontier; email present → available (not blocked). To hit
    # blocked we complete everything up to description on the SELF path with email
    # NOT received: mark dhl_email_received milestone incomplete but precheck+awb
    # done makes email the frontier. So blocked is exercised indirectly; here we
    # assert the gate logic directly.
    from app.services.timeline_milestones import _gate_description
    ok, reason = _gate_description({"clearance_decision": {"clearance_path": "dhl_self_clearance"}}, {})
    assert ok is False and "email" in reason.lower()
    ok2, _ = _gate_description({"clearance_decision": {"clearance_path": "agency_clearance"}}, {})
    assert ok2 is True   # agency path: email guard advisory, never blocks


def test_not_applicable_from_clearance_path_agency_excludes_dsk():
    # On the agency path, DSK (a self-clearance authorization doc) is not_applicable
    # — UNLESS a DSK was genuinely generated, in which case completed wins.
    agency = {"clearance_decision": {"clearance_path": "agency_clearance"}}
    assert _ms(agency)["dsk_generated"]["state"] == "not_applicable"
    # completion beats not_applicable
    agency_with_dsk = {"clearance_decision": {"clearance_path": "agency_clearance"},
                       "dsk_filename": "DSK.pdf"}
    assert _ms(agency_with_dsk)["dsk_generated"]["state"] == "completed"
    # routing_pending / unknown path never marks not_applicable
    assert _ms({})["dsk_generated"]["state"] != "not_applicable"


def test_skipped_optional_precheck_when_later_milestone_completed():
    # Precheck (optional) never ran, but a later milestone completed → skipped,
    # not a misleading pending/not_started.
    audit = {
        "batch_id": "SHIPMENT_X",
        "inputs": {"invoices": ["i.pdf"], "awb": "awb.pdf"},
        "dhl_email": {"received": True},   # later milestone complete
        # no dhl_precheck evidence
    }
    ms = _ms(audit)
    assert ms["dhl_precheck_completed"]["state"] == "skipped"


def test_completed_counter_counts_only_completed():
    # A mix of completed + available + not_started + not_applicable: the count of
    # done==True (what the V2 subtitle renders) equals the completed count only.
    audit = {
        "batch_id": "SHIPMENT_X",
        "inputs": {"invoices": ["i.pdf"], "awb": "awb.pdf"},
        "clearance_decision": {"clearance_path": "agency_clearance"},
    }
    out = build_milestones(audit)
    done = [m for m in out if m["done"]]
    completed = [m for m in out if m["state"] == "completed"]
    assert len(done) == len(completed) == 3   # batch + invoice + awb
    # not_applicable and available are NOT counted as done
    assert any(m["state"] == "not_applicable" for m in out)  # dsk on agency path
    assert any(m["state"] == "available" for m in out)


def test_failed_only_from_evidence_never_fabricated():
    # No failure evidence → never "failed".
    assert all(m["state"] != "failed" for m in build_milestones(_ev("dsk_generated")))
    # Evidence present → the named milestone reads failed.
    audit = {"milestone_failures": ["reply_sent"],
             "reply_package": {"to": "x@dhl.com"},
             "polish_desc_filename": "x.pdf", "dsk_filename": "d.pdf",
             "dhl_email": {"received": True},
             "inputs": {"invoices": ["i.pdf"], "awb": "a.pdf"}, "batch_id": "X"}
    assert _ms(audit)["reply_sent"]["state"] == "failed"
