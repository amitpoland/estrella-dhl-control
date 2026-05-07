"""
test_audit_merge.py — workflow overlay must survive regeneration.

Guards against the regression observed on SHIPMENT_2824221912 where
``regenerate_stale_batches --apply`` clobbered DHL/agency/Polish-desc
state by overwriting audit.json with a fresh engine-only dict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.audit_merge import (   # noqa: E402
    merge_regenerated_audit, PRESERVED_KEYS,
)


def _existing():
    """Snapshot of audit.json as it would look after a complete DHL workflow."""
    return {
        "batch_id": "SHIPMENT_2824221912_2026-04",
        "tracking_no": "2824221912",
        "polish_desc_filename": "POLISH_DESC_AWB_2824221912_20260428.pdf",
        "polish_desc_path":     "/storage/polish_descriptions/POLISH_DESC_AWB_2824221912_20260428.pdf",
        "polish_desc_file_exists": True,
        "dsk_received": True,
        "dsk_received_at": "2026-04-28T17:32:34Z",
        "dsk_source": "odprawacelna@dhl.com",
        "clearance_decision": {
            "clearance_path": "agency_clearance",
            "total_value_usd": 14169.0,
            "agency": "Agencja Celna Spedycja",
        },
        "dhl_reply_package": {"email_id": "drp-1", "status": "sent",
                              "to": "odprawacelna@dhl.com"},
        "agency_reply_package": {"queue_id": "arp-7", "status": "queued",
                                 "to": "biuro@acspedycja.pl"},
        "dhl_email": {"received": True, "sender": "odprawacelna@dhl.com"},
        "dhl_ticket": "T#1WA2603100000499",
        "email_scan_results": {"matched": 7},
        "email_evidence": {"threads": [{"id": 1}]},
        "tracking": {"status": "delivered", "available": True},
        "delivery_log": [{"action": "resend_to_cliq", "status": "success"}],
        "pz_confirmed": True,
        "pz_confirmed_at": "2026-04-25T11:54:33",
        "timeline": [
            {"ts": "2026-04-28T17:32:00Z", "event": "dhl_email_received"},
            {"ts": "2026-04-29T04:40:29Z", "event": "dhl_reply_sent_verified"},
        ],
        # Engine-output fields that WILL get overwritten:
        "row_schema_version": "v1",
        "verification": {"cif_match": True, "exporter_match": None},
        "rows": [{"product_code": ""}],   # legacy v1 row
    }


def _regenerated():
    """What the PZ engine produces in a fresh run — engine-only fields, no overlay."""
    return {
        "batch_id": "SHIPMENT_2824221912_2026-04",
        "tracking_no": "2824221912",
        "row_schema_version": "v2",
        "rows": [{"product_code": "EJL/25-26/1247-1", "nazwa": "x / y"}],
        "verification": {"cif_match": True, "exporter_match": True,
                         "qty_status": "partial_aggregated_sad"},
        "totals": {"net": 53632.46, "gross": 65967.92, "duty": 1261.0},
        "customs_declaration": {"mrn": "26PL44302D005LJ4R0",
                                "clearance_date": "2026-03-12"},
        "file_metadata": {"awb": "2824221912", "row_schema_version": "v2"},
        "canonical_filenames": {
            "pz_pdf": "PZ_AWB_2824221912_MRN_26PL44302D005LJ4R0_2026-03-12.pdf",
        },
        "engine_version": "v1.4",
        "timeline": [
            {"ts": "2026-05-02T10:59:00Z", "event": "pz_regenerated"},
            # Same timestamp+event as existing — must dedupe
            {"ts": "2026-04-29T04:40:29Z", "event": "dhl_reply_sent_verified"},
        ],
        # Engine writes empty overlay placeholders — must NOT clobber existing
        "polish_desc_filename": None,
        "dsk_received": None,
        "dhl_reply_package": {},
        "agency_reply_package": {},
        "clearance_decision": None,
    }


# ── Preservation rules ────────────────────────────────────────────────────────

class TestWorkflowPreservation:
    def test_polish_desc_filename_preserved(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["polish_desc_filename"] == "POLISH_DESC_AWB_2824221912_20260428.pdf"
        assert m["polish_desc_path"].startswith("/storage/polish_descriptions/")
        assert m["polish_desc_file_exists"] is True

    def test_dhl_reply_package_preserved(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["dhl_reply_package"]["status"] == "sent"
        assert m["dhl_reply_package"]["email_id"] == "drp-1"

    def test_agency_reply_package_preserved(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["agency_reply_package"]["status"] == "queued"
        assert m["agency_reply_package"]["queue_id"] == "arp-7"

    def test_clearance_decision_preserved(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["clearance_decision"]["clearance_path"] == "agency_clearance"
        assert m["clearance_decision"]["agency"] == "Agencja Celna Spedycja"

    def test_dsk_workflow_preserved(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["dsk_received"] is True
        assert m["dsk_source"] == "odprawacelna@dhl.com"
        assert m["dsk_received_at"] == "2026-04-28T17:32:34Z"

    def test_dhl_email_and_ticket_preserved(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["dhl_email"]["sender"] == "odprawacelna@dhl.com"
        assert m["dhl_ticket"] == "T#1WA2603100000499"

    def test_email_evidence_preserved(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["email_scan_results"]["matched"] == 7
        assert "threads" in m["email_evidence"]

    def test_tracking_state_preserved(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["tracking"]["status"] == "delivered"
        assert m["delivery_log"][0]["action"] == "resend_to_cliq"

    def test_pz_confirmed_preserved(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["pz_confirmed"] is True
        assert m["pz_confirmed_at"] == "2026-04-25T11:54:33"


# ── Engine-output replacement ─────────────────────────────────────────────────

class TestEngineOutputReplacement:
    def test_row_schema_version_advances_to_v2(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["row_schema_version"] == "v2"

    def test_rows_have_v2_fields(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["rows"][0]["product_code"] == "EJL/25-26/1247-1"
        assert m["rows"][0]["nazwa"] == "x / y"

    def test_verification_replaced_with_fresh(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        # Existing said exporter_match=None; fresh says True — fresh wins
        assert m["verification"]["exporter_match"] is True
        assert m["verification"]["qty_status"] == "partial_aggregated_sad"

    def test_canonical_filenames_replaced(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert "AWB_2824221912" in m["canonical_filenames"]["pz_pdf"]
        assert "MRN_26PL44302D005LJ4R0" in m["canonical_filenames"]["pz_pdf"]

    def test_file_metadata_replaced(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        assert m["file_metadata"]["row_schema_version"] == "v2"


# ── Timeline merging ──────────────────────────────────────────────────────────

class TestTimelineMerging:
    def test_timeline_appends_new_events(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        events = {(e["ts"], e["event"]) for e in m["timeline"]}
        # Existing events present
        assert ("2026-04-28T17:32:00Z", "dhl_email_received") in events
        # New regen event present
        assert ("2026-05-02T10:59:00Z", "pz_regenerated") in events

    def test_timeline_dedupes_overlap(self):
        m = merge_regenerated_audit(_existing(), _regenerated())
        keys = [(e["ts"], e["event"]) for e in m["timeline"]]
        # The shared event should appear exactly once
        assert keys.count(("2026-04-29T04:40:29Z", "dhl_reply_sent_verified")) == 1


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_no_existing_audit_returns_regenerated(self):
        m = merge_regenerated_audit({}, _regenerated())
        assert m["row_schema_version"] == "v2"
        # No overlay fields to preserve
        assert m.get("polish_desc_filename") is None

    def test_empty_regenerated_returns_existing(self):
        m = merge_regenerated_audit(_existing(), {})
        assert m["polish_desc_filename"] == "POLISH_DESC_AWB_2824221912_20260428.pdf"

    def test_regen_with_meaningful_value_wins_over_existing(self):
        """When the engine legitimately writes a new overlay value (e.g. it
        re-detected the polish_desc filename) the regen should win."""
        ex = _existing()
        rg = _regenerated()
        rg["polish_desc_filename"] = "POLISH_DESC_AWB_2824221912_20260502.pdf"   # fresher
        m = merge_regenerated_audit(ex, rg)
        assert m["polish_desc_filename"] == "POLISH_DESC_AWB_2824221912_20260502.pdf"

    def test_inputs_awb_preserved_when_engine_omits(self):
        ex = _existing()
        ex["inputs"] = {"awb": "2824221912 Tracking.pdf",
                        "invoices": ["a.pdf"]}
        rg = _regenerated()
        rg["inputs"] = {"invoices": ["a.pdf"], "zc429": "z.pdf"}   # no awb
        m = merge_regenerated_audit(ex, rg)
        assert m["inputs"]["awb"] == "2824221912 Tracking.pdf"
        assert m["inputs"]["zc429"] == "z.pdf"


# ── Preserved-keys contract ───────────────────────────────────────────────────

def test_preserved_keys_includes_all_required_workflow_fields():
    """The user's spec lists at minimum these fields to preserve.
    Lock the set so no future refactor silently drops one."""
    required = {
        "polish_desc_filename", "polish_desc_path",
        "dsk_filename", "dsk_path",
        "dsk_received", "dsk_received_at", "dsk_source",
        "clearance_decision",
        "dhl_reply_package", "agency_reply_package",
        "email_evidence", "email_timeline",
        "action_proposals",
        "queued_replies", "sent_replies",
        "manual_status_flags", "tracking_overrides", "operator_notes",
    }
    missing = required - set(PRESERVED_KEYS)
    assert not missing, f"Required workflow fields missing from PRESERVED_KEYS: {missing}"
