"""
test_dhl_readiness_pz_suppression.py — Downstream-evidence overrides.

Pins the new gating rules in get_dhl_readiness / batch_readiness:
  • SAD received  → suppress sla_breach
  • PZ generated  → suppress sla_breach AND clear stale "Process customs
                    documents and generate PZ" next-action
  • SAD missing + outbound > SLA + no inbound → sla_breach still fires
  • Batch readiness: PZ-generated path treats DHL domain as ready, with
    a clarifying message when customs_cleared isn't yet recorded.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import tracking_db as tdb
from app.services import dhl_readiness as dr
from app.services import batch_readiness as br
from app.core import timeline as tl


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    tdb.init_tracking_db(tmp_path / "tracking_events.db")
    return tmp_path


@pytest.fixture()
def with_storage(storage):
    """Patch settings.storage_root for the duration of one test."""
    with patch.object(settings, "storage_root", storage):
        yield storage


# ── helpers ─────────────────────────────────────────────────────────────────

def _ev(event: str, ts: str, **detail) -> dict:
    return {"event": event, "ts": ts, "trigger_source": "test",
            "actor": "system", "detail": detail or {}}


def _write_audit(storage_root: Path, batch_id: str, *,
                  timeline: list, audit_extras: dict | None = None) -> None:
    out = storage_root / "outputs" / batch_id
    out.mkdir(parents=True, exist_ok=True)
    audit = {"timeline": timeline}
    if audit_extras:
        audit.update(audit_extras)
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")


def _now_iso(offset_hours: float = 0) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(hours=offset_hours)).isoformat()


# Outbound > SLA window (4 days ago), no inbound after — would normally
# trip sla_breach.
_OLD_OUTBOUND = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()


# ── 1. SAD received suppresses DHL SLA breach ─────────────────────────────

def test_sad_received_suppresses_sla_breach(with_storage):
    storage = with_storage
    B = "BATCH_SAD_SUPPRESS"
    # Outbound 4d ago, no later inbound on the email timeline (would
    # normally trip SLA). SAD received via customs_declaration.received
    # — a NON-timeline signal path that the dhl_readiness compatibility
    # belt promotes to sad_received without altering the SLA outbound/
    # inbound calculation.
    timeline = [_ev(tl.EV_DSK_TRANSFER_SENT, _OLD_OUTBOUND)]
    _write_audit(storage, B, timeline=timeline, audit_extras={
        "customs_declaration": {"received": True,
                                  "received_at": _now_iso(-1)},
    })
    r = dr.get_dhl_readiness(B)
    assert r["dhl_status"]    == "sad_received"
    assert r["sad_received"]   is not None
    assert r["sla_breach"]     is False
    assert "suppressed: SAD received" in (r["sla_breach_reason"] or "")


# ── 2. PZ generated suppresses "generate PZ" next-action + SLA breach ─────

def test_pz_generated_suppresses_generate_pz_next_action(with_storage):
    storage = with_storage
    B = "BATCH_PZ_GENERATED"
    timeline = [
        _ev(tl.EV_DSK_TRANSFER_SENT, _OLD_OUTBOUND),
        _ev(tl.EV_ZC429_RECEIVED,    _now_iso(-2)),
    ]
    _write_audit(storage, B, timeline=timeline, audit_extras={
        "wfirma_export": {
            "wfirma_pz_doc_id":     "183484963",
            "wfirma_pz_fullnumber": "PZ 4/5/2026",
        },
    })
    r = dr.get_dhl_readiness(B)
    assert r["dhl_status"]            == "sad_received"
    assert r["pz_generated"]          is True
    assert r["next_required_action"]  is None         # ← stale hint cleared
    # ZC429_RECEIVED inbound after outbound → no SLA breach to suppress
    # in this fixture; the next-action override is the operative fix here.
    assert r["sla_breach"]            is False


# ── 3. customs_docs.received without timeline event still suppresses ──────

def test_customs_declaration_received_suppresses_sla_breach(with_storage):
    storage = with_storage
    B = "BATCH_CD_RECEIVED"
    # Outbound > SLA, NO timeline SAD event, but customs_declaration.received=True.
    timeline = [_ev(tl.EV_DSK_TRANSFER_SENT, _OLD_OUTBOUND)]
    _write_audit(storage, B, timeline=timeline, audit_extras={
        "customs_declaration": {"received": True,
                                  "received_at": _now_iso(-1)},
    })
    r = dr.get_dhl_readiness(B)
    # Compatibility belt at lines 342-353 advances state to sad_received
    # via customs_declaration.received → sla_breach must suppress.
    assert r["dhl_status"]  == "sad_received"
    assert r["sla_breach"]  is False


# ── 4. No SAD/PZ + overdue outbound → SLA breach still fires ──────────────

def test_no_sad_no_pz_overdue_outbound_still_breaches(with_storage):
    storage = with_storage
    B = "BATCH_NO_DOCS_OVERDUE"
    timeline = [_ev(tl.EV_DSK_TRANSFER_SENT, _OLD_OUTBOUND)]
    _write_audit(storage, B, timeline=timeline)
    r = dr.get_dhl_readiness(B)
    assert r["dhl_status"]    == "dhl_replied"
    assert r["sad_received"]   is None
    assert r["sla_breach"]     is True
    assert r["sla_breach_reason"] is not None
    assert "suppressed" not in (r["sla_breach_reason"] or "")


# ── 5. AWB 6049349806 fixture (sad + PZ) returns no DHL/PZ next action ────

def test_awb_6049349806_fixture_no_dhl_or_pz_next_action(with_storage):
    """Mirrors the live AWB 6049349806 audit shape: outbound queued
    recently, ZC429/SAD received, wFirma PZ already generated."""
    storage = with_storage
    B = "BATCH_AWB_6049349806_FIXTURE"
    timeline = [
        _ev("email_queued",          _now_iso(-3)),    # outbound 3h ago
        _ev(tl.EV_ZC429_RECEIVED,    _now_iso(-1)),
        _ev("wfirma_pz_created", _now_iso(-0.5),
             batch_id=B, wfirma_pz_doc_id="183484963", line_count=9),
    ]
    _write_audit(storage, B, timeline=timeline, audit_extras={
        "wfirma_export": {
            "wfirma_pz_doc_id":     "183484963",
            "wfirma_pz_fullnumber": "PZ 4/5/2026",
        },
        "customs_declaration": {"mrn": "26PL44302D00AUCWR3"},
    })
    r = dr.get_dhl_readiness(B)
    assert r["pz_generated"]         is True
    assert r["sla_breach"]           is False
    assert r["next_required_action"] is None
    # The next_step picker in batch_readiness must NOT mention DHL or
    # "generate PZ" for this batch.
    bb = br.get_batch_readiness(B)
    next_step = (bb.get("overall") or {}).get("next_step", "") or ""
    assert "DHL" not in next_step or "Process customs" not in next_step
    assert "generate PZ" not in next_step
    # And dhl domain reports ready=true with the PZ-generated message.
    dhl = bb.get("dhl") or {}
    assert dhl.get("ready") is True
    assert dhl.get("pz_generated") is True
    assert "wFirma PZ generated" in (dhl.get("message") or "")


# ── 6. Batch readiness: PZ-generated still surfaces real remaining work ───

def test_batch_readiness_advances_past_dhl_when_pz_generated(with_storage):
    """When DHL is satisfied (PZ generated) but warehouse is still empty,
    next_step must be the warehouse blocker — not the stale DHL hint."""
    storage = with_storage
    B = "BATCH_PZ_DONE_WH_EMPTY"
    timeline = [
        _ev(tl.EV_ZC429_RECEIVED,   _now_iso(-2)),
        _ev("wfirma_pz_created", _now_iso(-1),
             wfirma_pz_doc_id="X", line_count=1),
    ]
    _write_audit(storage, B, timeline=timeline, audit_extras={
        "wfirma_export": {"wfirma_pz_doc_id": "X",
                            "wfirma_pz_fullnumber": "PZ 1/1/2026"},
    })
    bb = br.get_batch_readiness(B)
    next_step = (bb.get("overall") or {}).get("next_step", "") or ""
    # Either ready-for-closure (no other blockers) or a non-DHL blocker.
    assert "Process customs documents and generate PZ" not in next_step
    assert "no DHL response" not in next_step


# ── 7. SLA breach reason is informative when SAD is suppressing ───────────

def test_sla_breach_reason_explains_suppression_when_sad_received(with_storage):
    storage = with_storage
    B = "BATCH_SUPPRESS_REASON"
    # Outbound 4d ago, no later timeline inbound → SLA would normally trip.
    # SAD signalled via customs_declaration.received (non-timeline path).
    timeline = [_ev(tl.EV_DSK_TRANSFER_SENT, _OLD_OUTBOUND)]
    _write_audit(storage, B, timeline=timeline, audit_extras={
        "customs_declaration": {"received": True,
                                  "received_at": _now_iso(-1)},
    })
    r = dr.get_dhl_readiness(B)
    assert r["sla_breach"]   is False
    assert "SAD received"    in (r["sla_breach_reason"] or "")


def test_sla_breach_reason_distinguishes_pz_from_sad(with_storage):
    storage = with_storage
    B = "BATCH_SUPPRESS_PZ_REASON"
    timeline = [_ev(tl.EV_DSK_TRANSFER_SENT, _OLD_OUTBOUND)]
    _write_audit(storage, B, timeline=timeline, audit_extras={
        "wfirma_export": {"wfirma_pz_doc_id":     "X",
                            "wfirma_pz_fullnumber": "PZ 1/1/2026"},
    })
    # No SAD timeline event, no customs_declaration — only the wFirma
    # PZ stamp triggers suppression. NB best_state stays 'dhl_replied'
    # because the timeline doesn't carry a SAD event, but the breach is
    # suppressed by PZ-generated evidence.
    r = dr.get_dhl_readiness(B)
    assert r["pz_generated"] is True
    assert r["sla_breach"]   is False
    assert "wFirma PZ generated" in (r["sla_breach_reason"] or "")
