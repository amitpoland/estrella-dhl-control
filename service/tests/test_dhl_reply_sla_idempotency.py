"""
test_dhl_reply_sla_idempotency.py — Surgical regressions for two cosmetic bugs:

  1. _evaluate_sla() must clear dhl_reply_overdue when:
        - dhl_reply_package.status == "sent", OR
        - timeline contains dhl_reply_sent_verified
  2. _apply_cache_to_audit() must NOT append a duplicate
     dhl_customs_email_received timeline event when the same ticket is
     already applied; a different ticket still records normally.

Financial / PZ fields must remain untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import active_shipment_monitor as asm
from app.services.active_shipment_monitor import (
    _evaluate_sla, _apply_cache_to_audit,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _seed(tmp_path: Path, overrides: dict | None = None) -> Path:
    bdir = tmp_path / "outputs" / "B_TEST"
    bdir.mkdir(parents=True, exist_ok=True)
    base = {
        "batch_id":         "B_TEST",
        "tracking_no":      "1012178215",
        "clearance_status": "dhl_email_received",
        "clearance_decision": {
            "total_value_usd": 10366.0,
            "clearance_path":  "agency_clearance",
        },
        "dhl_email": {
            "received":    True,
            "ticket":      "T#1WA2604290000028",
            "received_at": "2026-04-29T02:46:18Z",
        },
        # Sentinels for "do not touch" assertions
        "totals":          {"netto": 12345.67, "brutto": 14999.99},
        "invoice_totals":  {"net": 12345.67},
        "engine_version":  "v1.0.0",
    }
    if overrides:
        base.update(overrides)
    (bdir / "audit.json").write_text(json.dumps(base))
    return bdir / "audit.json"


# ── 1. _evaluate_sla: dhl_reply_overdue must clear on sent ───────────────────

def test_dhl_reply_overdue_cleared_when_package_status_sent(tmp_path):
    p = _seed(tmp_path, {
        "dhl_reply_package": {
            "email_id":            "36b7492b",
            "status":              "sent",
            "provider_message_id": "<msg@host>",
        },
    })
    audit = json.loads(p.read_text())
    sla = _evaluate_sla(audit)
    assert sla["dhl_reply_overdue"] is False


def test_dhl_reply_overdue_cleared_via_timeline_event(tmp_path):
    p = _seed(tmp_path, {
        # Package status missing/queued, but timeline event proves it was sent
        "dhl_reply_package": {"status": "queued"},
        "timeline": [
            {"ts": "2026-04-29T04:40:08Z",
             "event": "dhl_reply_sent_verified",
             "detail": {"queue_id": "36b7492b"}},
        ],
    })
    audit = json.loads(p.read_text())
    sla = _evaluate_sla(audit)
    assert sla["dhl_reply_overdue"] is False


def test_dhl_reply_overdue_true_when_neither_signal_present(tmp_path):
    # Force time-overdue state: dhl_email received >> 10 minutes ago,
    # high-value, no sent package, no timeline event.
    p = _seed(tmp_path, {
        "dhl_reply_package": {"status": "queued"},
        "timeline":          [],
        "clearance_status":  "dhl_email_received",
    })
    audit = json.loads(p.read_text())
    sla = _evaluate_sla(audit)
    assert sla["dhl_reply_overdue"] is True


def test_evaluate_sla_does_not_mutate_financial_fields(tmp_path):
    p = _seed(tmp_path, {
        "dhl_reply_package": {"status": "sent"},
    })
    before = json.loads(p.read_text())
    _evaluate_sla(json.loads(p.read_text()))
    after = json.loads(p.read_text())
    # File on disk untouched (read-only function)
    assert before == after
    # Sentinel financial fields preserved
    assert after["totals"]["netto"]    == 12345.67
    assert after["totals"]["brutto"]   == 14999.99
    assert after["invoice_totals"]["net"] == 12345.67


# ── 2. _apply_cache_to_audit: duplicate ticket must not re-append ────────────

def _cached_email(ticket: str, subject: str = "DHL email") -> dict:
    return {
        "derived_events": [{
            "event":               "dhl_customs_email_received",
            "ticket":              ticket,
            "source_email_from":   "odprawacelna@dhl.com",
            "source_email_subject": subject,
            "request_type":        "translation",
            "confidence":          "high",
            "timestamp":           "2026-04-29T02:46:18Z",
        }],
    }


def test_duplicate_dhl_event_not_appended_for_same_ticket(tmp_path):
    # Seed WITHOUT dhl_email so first apply is fresh
    p = _seed(tmp_path, {"dhl_email": None})
    audit = json.loads(p.read_text())
    audit.pop("dhl_email", None)
    p.write_text(json.dumps(audit))
    # First apply — fresh ticket; expect timeline append
    res1 = _apply_cache_to_audit(
        p, json.loads(p.read_text()),
        _cached_email("T#1WA2604290000028"),
    )
    assert res1["applied"] is True
    assert "dhl_customs_email_received" in res1["timeline_events_added"]
    assert res1.get("dhl_duplicate", False) is False

    # Second apply — SAME ticket; must NOT append
    res2 = _apply_cache_to_audit(
        p, json.loads(p.read_text()),
        _cached_email("T#1WA2604290000028"),
    )
    assert res2["dhl_duplicate"] is True
    assert "dhl_customs_email_received" not in res2["timeline_events_added"]
    assert res2["applied"] is False


def test_different_ticket_appends_new_event(tmp_path):
    p = _seed(tmp_path, {"dhl_email": None})
    audit = json.loads(p.read_text()); audit.pop("dhl_email", None)
    p.write_text(json.dumps(audit))
    _apply_cache_to_audit(p, json.loads(p.read_text()),
                          _cached_email("T#OLDTICKET"))
    res = _apply_cache_to_audit(p, json.loads(p.read_text()),
                                _cached_email("T#NEWTICKET"))
    assert res["dhl_duplicate"] is False
    assert "dhl_customs_email_received" in res["timeline_events_added"]


def test_apply_cache_does_not_touch_financial_fields(tmp_path):
    p = _seed(tmp_path)
    before = json.loads(p.read_text())
    _apply_cache_to_audit(p, json.loads(p.read_text()),
                          _cached_email("T#1WA2604290000028"))
    after = json.loads(p.read_text())
    assert after["totals"]    == before["totals"]
    assert after["invoice_totals"] == before["invoice_totals"]
    assert after["engine_version"] == before["engine_version"]


# ── AWB 1012178215 live shape regression ─────────────────────────────────────

def test_awb_1012178215_live_shape_overdue_false(tmp_path):
    """Reproduce the real audit shape: package has email_id + status=sent."""
    p = _seed(tmp_path, {
        "dhl_reply_package": {
            "email_id":            "36b7492b-9102-4b9f-8ec5-52f675fca106",
            "status":              "sent",
            "sent_at":             "2026-04-29T04:40:08Z",
            "provider_message_id": "<177743760343...@1.0.0.127.in-addr.arpa>",
            "send_verified":       True,
        },
        "timeline": [
            {"event": "dhl_reply_package_auto_built",
             "detail": {"email_id": "36b7492b-9102-4b9f-8ec5-52f675fca106"}},
            {"event": "dhl_reply_sent_verified",
             "detail": {"queue_id": "36b7492b-9102-4b9f-8ec5-52f675fca106"}},
        ],
    })
    audit = json.loads(p.read_text())
    sla = _evaluate_sla(audit)
    assert sla["dhl_reply_overdue"] is False
    assert sla["high_value"]        is True
