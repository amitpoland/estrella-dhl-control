"""
Regression: email_evidence V2 dhl_request must flip audit.dhl_email.received
so Lane A B2 DSK auto-reply can fire.

Incident AWB 5831878861 (2026-08-10):
  odprawacelna@dhl.com T# email was ingested into email_evidence as
  event_type=dhl_request, but Lane A only read the empty email_intelligence
  cache — dhl_email.received stayed unset and B2 never triggered.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("API_KEY", "test-key")


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    (root / "outputs").mkdir(parents=True)
    (root / "email_evidence" / "by_awb").mkdir(parents=True)
    monkeypatch.setenv("STORAGE_ROOT", str(root))
    # Reset settings + evidence store module paths that cache storage_root
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", root)
    import app.services.email_evidence_store as evs
    monkeypatch.setattr(evs, "_ROOT", None, raising=False)
    return root


def _write_audit(storage: Path, batch_id: str, awb: str, **extra) -> Path:
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id": batch_id,
        "awb": awb,
        "status": "draft",
        "clearance_status": "draft",
        "clearance_decision": {"clearance_path": "agency_clearance"},
        "tracking": {"status": "in_customs"},
        **extra,
    }
    p = d / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def _seed_dhl_request(awb: str, ticket: str = "T#1WA2608100000162") -> None:
    from app.services import email_evidence_store as evs
    evs.save_message(awb, {
        "message_id": "msg-dhl-req-1",
        "thread_id": f"zoho:{ticket}",
        "direction": "incoming",
        "sender": "odprawacelna@dhl.com",
        "to": ["import@estrellajewels.eu"],
        "cc": [],
        "subject": f"{ticket} - Agencja Celna DHL - przesyłka numer: {awb}",
        "body_text": "W celu zachowania ciągłości… tłumaczenie zawartości…",
        "timestamp": "2026-08-10T05:52:09.451000+00:00",
        "event_type": "dhl_request",
        "matched_identifiers": {"awb": True},
        "attachments": [],
    }, source="zoho_rest")


def test_evidence_bridge_sets_dhl_email_received(storage):
    from app.services.active_shipment_monitor import (
        apply_dhl_email_received_from_evidence,
    )

    awb = "5831878861"
    ap = _write_audit(storage, "SHIPMENT_5831878861_test", awb)
    _seed_dhl_request(awb)
    audit = json.loads(ap.read_text(encoding="utf-8"))

    res = apply_dhl_email_received_from_evidence(ap, audit)

    assert res["wrote"] is True
    assert res["ticket"] == "T#1WA2608100000162"
    live = json.loads(ap.read_text(encoding="utf-8"))
    de = live["dhl_email"]
    assert de["received"] is True
    assert de["source"] == "email_evidence_v2"
    assert de["ticket"] == "T#1WA2608100000162"
    assert live["dhl_ticket"] == "T#1WA2608100000162"
    assert live["clearance_status"] == "dhl_email_received"


def test_evidence_bridge_does_not_downgrade_reply_queued(storage):
    from app.services.active_shipment_monitor import (
        apply_dhl_email_received_from_evidence,
    )

    awb = "5831878861"
    ap = _write_audit(
        storage, "SHIPMENT_5831878861_rq", awb,
        clearance_status="reply_queued",
    )
    _seed_dhl_request(awb)
    audit = json.loads(ap.read_text(encoding="utf-8"))

    res = apply_dhl_email_received_from_evidence(ap, audit)

    assert res["wrote"] is True
    live = json.loads(ap.read_text(encoding="utf-8"))
    assert live["dhl_email"]["received"] is True
    assert live["clearance_status"] == "reply_queued"


def test_evidence_bridge_idempotent(storage):
    from app.services.active_shipment_monitor import (
        apply_dhl_email_received_from_evidence,
    )

    awb = "1112223334"
    ap = _write_audit(storage, "SHIPMENT_111_test", awb)
    _seed_dhl_request(awb, ticket="T#1WA2608100000999")
    audit = json.loads(ap.read_text(encoding="utf-8"))

    assert apply_dhl_email_received_from_evidence(ap, audit)["wrote"] is True
    audit2 = json.loads(ap.read_text(encoding="utf-8"))
    assert apply_dhl_email_received_from_evidence(ap, audit2)["skipped"] == (
        "already_received"
    )


def test_evidence_bridge_skips_when_no_dhl_request(storage):
    from app.services.active_shipment_monitor import (
        apply_dhl_email_received_from_evidence,
    )

    awb = "9998887776"
    ap = _write_audit(storage, "SHIPMENT_999_test", awb)
    audit = json.loads(ap.read_text(encoding="utf-8"))

    res = apply_dhl_email_received_from_evidence(ap, audit)
    assert res["wrote"] is False
    assert res["skipped"] == "no_dhl_request"


def test_route_email_sets_dhl_email_received_for_dhl_request(storage):
    from app.services.event_trigger_engine import route_email

    awb = "5554443332"
    ap = _write_audit(storage, "SHIPMENT_555_test", awb)
    email = {
        "message_id": "zoho-1",
        "from": "odprawacelna@dhl.com",
        "sender_role": "dhl",
        "detected_type": "translation",
        "dhl_ticket": "T#1WA2608100000555",
        "subject": "T#1WA2608100000555 - Agencja Celna DHL - przesyłka numer: 5554443332",
        "received_at": "2026-08-10T05:52:09+00:00",
        "attachments": [],
    }

    res = route_email(ap, email, [])
    assert res.get("ok") is True
    live = json.loads(ap.read_text(encoding="utf-8"))
    assert live["dhl_email"]["received"] is True
    assert live["dhl_ticket"] == "T#1WA2608100000555"


def test_lane_a_source_mentions_evidence_bridge():
    """Source-grep: scheduled-inbox-check must call the evidence bridge."""
    src = (
        Path(__file__).parent.parent
        / "app" / "api" / "routes_dhl_clearance.py"
    ).read_text(encoding="utf-8", errors="replace")
    assert "apply_dhl_email_received_from_evidence" in src
    assert "evidence bridge set dhl_email.received" in src
