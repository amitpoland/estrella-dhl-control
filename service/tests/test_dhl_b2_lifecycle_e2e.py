"""
E2E synthetic: evidence-only DHL request → received → 10m delay → B2 same-thread
DSK reply → follow-up schedule → DHL response suppresses chase.

Mirrors AWB 5831878861 shape where noted. No real SMTP / DHL email.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

os.environ.setdefault("API_KEY", "test-key")

AWB = "5831878861"
TICKET = "T#1WA2608100000162"
RFC822_MID = "<T1WA2608100000162.customs@dhl.com>"
RECEIVED_AT = "2026-08-10T05:52:09.451000+00:00"
ALT_REPLY = "customs.poland@dhl.com"


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    (root / "outputs").mkdir(parents=True)
    (root / "dsk_outputs").mkdir(parents=True)
    monkeypatch.setenv("STORAGE_ROOT", str(root))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", root)
    monkeypatch.setattr(settings, "dhl_dsk_auto_reply_delay_minutes", 10)
    return root


def _write_audit(storage: Path, **extra) -> Path:
    batch = f"SHIPMENT_{AWB}_2026-08_test"
    d = storage / "outputs" / batch
    d.mkdir(parents=True, exist_ok=True)
    dsk = storage / "dsk_outputs" / f"DSK_{AWB}_05-08-2026.pdf"
    dsk.write_bytes(b"%PDF-1.4 dsk")
    audit = {
        "batch_id": batch,
        "awb": AWB,
        "status": "draft",
        "clearance_status": "draft",
        "clearance_decision": {"clearance_path": "agency_clearance"},
        "tracking": {"status": "in_customs"},
        "dsk_filename": dsk.name,
        "dsk_path": str(dsk),
        "agency_reply_package": {
            "status": "queued",
            "to": "biuro@acspedycja.pl",
            "queued_at": "2026-08-09T00:50:24.751439+00:00",
        },
        **extra,
    }
    p = d / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def _seed_evidence(
    awb: str = AWB,
    *,
    rfc822: bool = True,
    reply_to: str = "odprawacelna@dhl.com",
    sender: str = "odprawacelna@dhl.com",
) -> None:
    from app.services import email_evidence_store as evs
    msg = {
        "message_id": "1786341129449110100",
        "thread_id": f"zoho:{TICKET.lower()} - agencja celna dhl",
        "direction": "incoming",
        "sender": sender,
        "to": ["import@estrellajewels.eu"],
        "cc": [],
        "subject": f"{TICKET} - Agencja Celna DHL - przesyłka numer: {awb}",
        "body_text": "tłumaczenie zawartości…",
        "timestamp": RECEIVED_AT,
        "event_type": "dhl_request",
        "matched_identifiers": {"awb": True},
        "attachments": [],
        "reply_to": reply_to,
        "from_header": sender,
    }
    if rfc822:
        msg["rfc822_message_id"] = RFC822_MID
        msg["Message-ID"] = RFC822_MID
        msg["references"] = RFC822_MID
    evs.save_message(awb, msg, source="zoho_rest")


def _dhl_email(**extra):
    # Default receipt far enough in the past that the 10m delay is always due
    # in unit tests (independent of wall-clock).
    base = {
        "received": True,
        "ticket": TICKET,
        "subject": f"{TICKET} - Agencja Celna DHL - przesyłka numer: {AWB}",
        "received_at": "2026-08-01T05:52:09+00:00",
        "rfc822_message_id": RFC822_MID,
        "source_message_id": "1786341129449110100",
        "source_thread_id": "thr-1",
        "reply_to": "odprawacelna@dhl.com",
        "from_header": "odprawacelna@dhl.com",
        "reply_to_address": "odprawacelna@dhl.com",
        "reply_recipient_source": "reply_to",
        "sender": "odprawacelna@dhl.com",
    }
    base.update(extra)
    return base


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_bridge_preserves_evidence_received_at_and_recipient(storage):
    from app.services.active_shipment_monitor import (
        apply_dhl_email_received_from_evidence,
    )
    ap = _write_audit(storage)
    _seed_evidence(reply_to=ALT_REPLY)
    audit = json.loads(ap.read_text(encoding="utf-8"))
    with patch(
        "app.services.active_shipment_monitor._maybe_recover_rfc822_headers",
        side_effect=lambda awb, best: best,
    ):
        res = apply_dhl_email_received_from_evidence(ap, audit)
    assert res["wrote"] is True
    live = json.loads(ap.read_text(encoding="utf-8"))
    de = live["dhl_email"]
    assert de["received"] is True
    assert de["received_at"] == RECEIVED_AT
    assert de["ticket"] == TICKET
    assert de["source_message_id"] == "1786341129449110100"
    assert de["rfc822_message_id"] == RFC822_MID
    assert de["reply_to_address"] == ALT_REPLY
    assert de["reply_recipient_source"] == "reply_to"


def test_agency_clearance_path_routes_to_b2(storage):
    from app.services.clearance_path_alias import (
        PATH_AGENCY_CLEARANCE, normalize_path,
    )
    assert normalize_path("agency_clearance") == PATH_AGENCY_CLEARANCE
    assert normalize_path("external_agency_clearance") == PATH_AGENCY_CLEARANCE


def test_b2_holds_without_rfc822_thread_identity(storage):
    from app.services.active_shipment_monitor import _ensure_dhl_dsk_transfer_reply
    from app.utils import proposal_lock as pl

    ap = _write_audit(
        storage,
        dhl_email=_dhl_email(
            rfc822_message_id="",
            source_message_id="1786341129449110100",
        ),
    )
    audit = json.loads(ap.read_text(encoding="utf-8"))
    with patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
         patch("app.services.email_service.queue_email") as q:
        out = _ensure_dhl_dsk_transfer_reply(ap, audit)
    assert out.get("built") is False
    assert out.get("error") == "missing_rfc822_thread_identity"
    q.assert_not_called()


def test_b2_holds_when_dsk_missing(storage):
    from app.services.active_shipment_monitor import _ensure_dhl_dsk_transfer_reply
    ap = _write_audit(
        storage,
        dhl_email=_dhl_email(),
        dsk_filename="",
        dsk_path="",
    )
    audit = json.loads(ap.read_text(encoding="utf-8"))
    with patch("app.services.email_service.queue_email") as q:
        out = _ensure_dhl_dsk_transfer_reply(ap, audit)
    assert out.get("error") == "dsk_not_yet_generated"
    q.assert_not_called()


def test_b2_holds_before_due_at(storage):
    from app.services import active_shipment_monitor as asm
    from app.utils import proposal_lock as pl

    recv = datetime(2026, 8, 10, 5, 52, 9, tzinfo=timezone.utc)
    due = recv + timedelta(minutes=10)
    ap = _write_audit(
        storage,
        dhl_email=_dhl_email(received_at=recv.isoformat()),
    )
    audit = json.loads(ap.read_text(encoding="utf-8"))

    with patch.object(
        asm, "_b2_delay_gate",
        return_value={
            "eligible": False,
            "due_at": due.isoformat(),
            "received_at": recv.isoformat(),
            "reason": "before_due_at",
        },
    ), patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
       patch("app.services.email_service.queue_email") as q:
        out = asm._ensure_dhl_dsk_transfer_reply(ap, audit)
    assert out.get("error") == "before_due_at"
    assert out.get("due_at") == due.isoformat()
    q.assert_not_called()


def test_b2_delay_gate_unit():
    from app.services.active_shipment_monitor import _b2_delay_gate, _b2_due_at
    recv = "2026-08-10T05:52:09+00:00"
    due = _b2_due_at(recv, 10)
    assert due == datetime(2026, 8, 10, 6, 2, 9, tzinfo=timezone.utc)
    before = _b2_delay_gate(
        {"dhl_email": {"received_at": recv}},
        now=due - timedelta(seconds=1),
    )
    assert before["eligible"] is False
    assert before["reason"] == "before_due_at"
    at = _b2_delay_gate({"dhl_email": {"received_at": recv}}, now=due)
    assert at["eligible"] is True
    missing = _b2_delay_gate({"dhl_email": {"received": True}}, now=due)
    assert missing["reason"] == "missing_received_at"


def test_agency_reply_package_does_not_satisfy_b2(storage):
    import inspect
    from app.services.active_shipment_monitor import _ensure_dhl_dsk_transfer_reply
    from app.utils import proposal_lock as pl

    src = inspect.getsource(_ensure_dhl_dsk_transfer_reply)
    assert "dhl_reply_package" in src
    assert 'agency_reply_package") or {}).get("status")' not in src

    ap = _write_audit(storage, dhl_email=_dhl_email())
    audit = json.loads(ap.read_text(encoding="utf-8"))
    assert audit["agency_reply_package"]["status"] == "queued"

    queued = []

    def _spy(**kwargs):
        queued.append(kwargs)
        return "qid-agency-split"

    with patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
         patch("app.services.email_service.queue_email", side_effect=_spy):
        out = _ensure_dhl_dsk_transfer_reply(ap, audit)

    assert out.get("built") is True, out
    assert len(queued) == 1
    assert "odprawacelna@dhl.com" in queued[0]["to"]
    assert "acspedycja" not in queued[0]["to"]
    live = json.loads(ap.read_text(encoding="utf-8"))
    assert live["dhl_reply_package"]["status"] == "queued"
    assert live["agency_reply_package"]["status"] == "queued"


def test_b2_respects_alternate_inbound_reply_to(storage):
    from app.services.active_shipment_monitor import _ensure_dhl_dsk_transfer_reply
    from app.utils import proposal_lock as pl

    ap = _write_audit(
        storage,
        dhl_email=_dhl_email(
            reply_to=ALT_REPLY,
            reply_to_address=ALT_REPLY,
            from_header="odprawacelna@dhl.com",
            reply_recipient_source="reply_to",
        ),
    )
    audit = json.loads(ap.read_text(encoding="utf-8"))
    queued = []

    def _spy(**kwargs):
        queued.append(kwargs)
        return "qid-alt"

    with patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
         patch("app.services.email_service.queue_email", side_effect=_spy):
        out = _ensure_dhl_dsk_transfer_reply(ap, audit)
    assert out.get("built") is True, out
    assert queued[0]["to"] == ALT_REPLY


def test_b2_holds_without_valid_recipient(storage):
    from app.services.active_shipment_monitor import _ensure_dhl_dsk_transfer_reply
    from app.utils import proposal_lock as pl

    ap = _write_audit(
        storage,
        dhl_email=_dhl_email(
            reply_to="",
            reply_to_address="",
            from_header="someone@example.com",
            sender="someone@example.com",
            reply_recipient_source="missing",
        ),
    )
    audit = json.loads(ap.read_text(encoding="utf-8"))
    with patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
         patch("app.services.email_service.queue_email") as q:
        out = _ensure_dhl_dsk_transfer_reply(ap, audit)
    assert out.get("error") == "missing_reply_recipient"
    q.assert_not_called()


def test_e2e_lifecycle_delay_thread_exactly_once(storage):
    """inbound → bridge → t+9m59 no → t+10m one → restart still one."""
    from app.services import active_shipment_monitor as asm
    from app.utils import proposal_lock as pl

    ap = _write_audit(storage)
    _seed_evidence(rfc822=True, reply_to=ALT_REPLY)
    audit = json.loads(ap.read_text(encoding="utf-8"))

    with patch.object(
        asm, "_maybe_recover_rfc822_headers", side_effect=lambda a, b: b,
    ):
        br = asm.apply_dhl_email_received_from_evidence(ap, audit)
    assert br["wrote"] is True
    audit = json.loads(ap.read_text(encoding="utf-8"))
    assert audit["dhl_email"]["reply_to_address"] == ALT_REPLY

    recv = datetime.fromisoformat(RECEIVED_AT)
    due = recv + timedelta(minutes=10)
    queued = []
    _real_gate = asm._b2_delay_gate

    def _spy(**kwargs):
        queued.append(kwargs)
        return "qid-e2e-1"

    with patch.object(
        asm, "_b2_delay_gate",
        return_value={
            "eligible": False,
            "due_at": due.isoformat(),
            "received_at": RECEIVED_AT,
            "reason": "before_due_at",
        },
    ), patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
       patch("app.services.email_service.queue_email", side_effect=_spy):
        out0 = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text(encoding="utf-8")),
        )
    assert out0.get("error") == "before_due_at"
    assert len(queued) == 0

    with patch.object(
        asm, "_b2_delay_gate",
        side_effect=lambda a, now=None, _gate=_real_gate: _gate(a, now=due),
    ), patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
       patch("app.services.email_service.queue_email", side_effect=_spy):
        out1 = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text(encoding="utf-8")),
        )
    assert out1.get("built") is True, out1
    assert len(queued) == 1
    call = queued[0]
    assert call["to"] == ALT_REPLY
    assert TICKET in call["subject"]
    assert call["in_reply_to"] == RFC822_MID
    assert RFC822_MID in (call.get("references") or "")
    assert call["attachments"] and "DSK_" in Path(call["attachments"][0]["path"]).name

    live = json.loads(ap.read_text(encoding="utf-8"))
    assert live["dhl_reply_package"]["status"] == "queued"
    assert live["dhl_reply_package"]["due_at"]
    assert live["dhl_reply_package"]["queued_at"]
    assert live["dhl_reply_package"]["in_reply_to"] == RFC822_MID
    assert live["dhl_reply_package"]["ticket"] == TICKET

    with patch.object(
        asm, "_b2_delay_gate",
        side_effect=lambda a, now=None, _gate=_real_gate: _gate(
            a, now=due + timedelta(minutes=1),
        ),
    ), patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
       patch("app.services.email_service.queue_email", side_effect=_spy):
        out2 = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text(encoding="utf-8")),
        )
        out3 = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text(encoding="utf-8")),
        )
    assert out2.get("error") == "already_started_or_sent"
    assert out3.get("error") == "already_started_or_sent"
    assert len(queued) == 1


def test_b2_queue_failure_is_retryable_not_sent(storage):
    from app.services.active_shipment_monitor import _ensure_dhl_dsk_transfer_reply
    from app.utils import proposal_lock as pl

    ap = _write_audit(storage, dhl_email=_dhl_email())
    audit = json.loads(ap.read_text(encoding="utf-8"))

    with patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
         patch(
             "app.services.email_service.queue_email",
             side_effect=RuntimeError("smtp_down"),
         ):
        out1 = _ensure_dhl_dsk_transfer_reply(ap, audit)
    assert out1.get("built") is False
    live = json.loads(ap.read_text(encoding="utf-8"))
    assert live["dhl_reply_package"]["status"] == "failed"
    assert "build_started_at" not in live["dhl_reply_package"]

    queued = []

    def _spy(**kwargs):
        queued.append(kwargs)
        return "qid-retry"

    with patch.object(pl, "proposal_write_lock", return_value=_Lock()), \
         patch("app.services.email_service.queue_email", side_effect=_spy):
        out2 = _ensure_dhl_dsk_transfer_reply(ap, json.loads(ap.read_text()))
    assert out2.get("built") is True, out2
    assert len(queued) == 1
    assert json.loads(ap.read_text())["dhl_reply_package"]["status"] == "queued"


def test_smtp_mime_sets_in_reply_to_when_rfc822_present():
    from app.services.email_sender import _build_mime
    msg = _build_mime(
        sender="import@estrellajewels.eu",
        to_list=["odprawacelna@dhl.com"],
        cc_list=[],
        subject=f"Re: {TICKET} – Request",
        body_text="body",
        body_html="",
        attachments=[],
        in_reply_to=RFC822_MID,
        references=RFC822_MID,
    )
    assert msg["In-Reply-To"] == RFC822_MID
    assert msg["References"] == RFC822_MID


def test_smtp_mime_skips_non_rfc822_in_reply_to():
    from app.services.email_sender import _build_mime
    msg = _build_mime(
        sender="import@estrellajewels.eu",
        to_list=["odprawacelna@dhl.com"],
        cc_list=[],
        subject="Re: ticket",
        body_text="body",
        body_html="",
        attachments=[],
        in_reply_to="1786341129449110100",
        references="",
    )
    assert msg.get("In-Reply-To") is None


def test_delay_setting_separate_from_sla():
    import inspect
    from app.services import active_shipment_monitor as asm
    from app.core.config import settings
    src = inspect.getsource(asm._ensure_dhl_dsk_transfer_reply)
    assert "DHL_REPLY_AFTER_EMAIL_SLA_MINUTES" not in src
    assert "_b2_delay_gate" in src
    assert asm.DHL_REPLY_AFTER_EMAIL_SLA_MINUTES == 10
    assert getattr(settings, "dhl_dsk_auto_reply_delay_minutes") == 10


def test_followup_first_due_and_suppression():
    from app.services.dhl_dsk_chase_sla import (
        dhl_replied_after_dsk_reply,
        start_dsk_chase,
    )
    sent_at = datetime(2026, 8, 10, 6, 10, 0, tzinfo=timezone.utc)
    audit = {
        "dhl_reply_package": {
            "status": "sent",
            "sent_at": sent_at.isoformat(),
        },
    }
    state = start_dsk_chase(audit, sent_at, "dsk_reply_sent")
    first = datetime.fromisoformat(state["first_followup_at"])
    assert first >= sent_at

    audit_replied = {
        "dhl_reply_package": {
            "status": "sent",
            "sent_at": sent_at.isoformat(),
        },
        "dhl_inbox_flags": {
            "translation": {
                "received_at": (sent_at + timedelta(hours=1)).isoformat(),
            }
        },
    }
    assert dhl_replied_after_dsk_reply(audit_replied) is True


def test_never_synthesize_rfc822_from_zoho_id():
    from app.services.active_shipment_monitor import (
        _b2_thread_identity,
        _is_rfc822_message_id,
    )
    assert not _is_rfc822_message_id("1786341129449110100")
    ident = _b2_thread_identity({
        "dhl_email": {
            "source_message_id": "1786341129449110100",
            "rfc822_message_id": "",
        }
    })
    assert not ident["has_smtp_thread"]


def test_rfc822_header_parser_unit():
    from dhl_email_monitor import _parse_rfc822_header_block, extract_email_address
    raw = (
        "Message-Id: <abc@dhl.com>\r\n"
        "From: DHL <odprawacelna@dhl.com>\r\n"
        "Reply-To: customs.poland@dhl.com\r\n"
        "References: <abc@dhl.com>\r\n"
        "\r\n"
        "body"
    )
    parsed = _parse_rfc822_header_block(raw)
    assert parsed["rfc822_message_id"] == "<abc@dhl.com>"
    assert "customs.poland@dhl.com" in parsed["reply_to"]
    assert extract_email_address(parsed["from_header"]) == "odprawacelna@dhl.com"
