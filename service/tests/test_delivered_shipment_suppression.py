"""test_delivered_shipment_suppression.py — PR-209.5 follow-up suppression.

Verifies the operator rule:
  "If shipment status is delivered, shipment is closed. Don't follow up."

Covered surfaces:
  1. shipment_delivered_guard pure helpers (is_audit_delivered,
     check_send_allowed, is_queue_entry_stale)
  2. email_sender.send_queued_email execution-time guard:
     - delivered shipment queued before delivery → suppressed at send time
     - replay of a now-suppressed queue entry stays suppressed
     - stale queue entry refused as expired
     - manual resend (any caller path) blocked the same way
  3. active_shipment_monitor._is_active scheduler-side skip
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest


# ── Fixture: per-test storage_root with email_queue + audit.json plumbing

@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    # Pre-create outputs/working dirs so guard lookup paths exist.
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "working").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_audit(tmp: pathlib.Path, batch_id: str, audit: dict,
                 sub: str = "outputs") -> None:
    d = tmp / sub / batch_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps(audit), encoding="utf-8")


def _write_queue(tmp: pathlib.Path, entries: list) -> None:
    (tmp / "email_queue.json").write_text(
        json.dumps(entries), encoding="utf-8",
    )


def _read_queue(tmp: pathlib.Path) -> list:
    p = tmp / "email_queue.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────
# Tier 1 — pure helpers
# ─────────────────────────────────────────────────────────────────────────

def test_is_audit_delivered_detects_tracking_status(fresh):
    from app.services.shipment_delivered_guard import is_audit_delivered
    assert is_audit_delivered({"tracking": {"status": "delivered"}}) is True
    assert is_audit_delivered({"tracking": {"status": "DELIVERED"}}) is True
    assert is_audit_delivered({"tracking": {"status": "in_transit"}}) is False


def test_is_audit_delivered_detects_audit_level_timestamp(fresh):
    from app.services.shipment_delivered_guard import is_audit_delivered
    assert is_audit_delivered({"delivered_at": "2026-05-18T10:00:00Z"}) is True
    assert is_audit_delivered({"delivered_at": ""}) is False
    assert is_audit_delivered({"delivered_at": "   "}) is False


def test_is_audit_delivered_detects_proactive_dispatch_slot(fresh):
    from app.services.shipment_delivered_guard import is_audit_delivered
    assert is_audit_delivered(
        {"proactive_dispatch_delivered_at": "2026-05-18T10:00:00Z"}
    ) is True


def test_is_audit_delivered_handles_malformed_input(fresh):
    from app.services.shipment_delivered_guard import is_audit_delivered
    assert is_audit_delivered(None) is False
    assert is_audit_delivered({}) is False
    assert is_audit_delivered({"tracking": "not-a-dict"}) is False
    assert is_audit_delivered({"tracking": None}) is False


def test_check_send_allowed_returns_allowed_when_audit_missing(fresh):
    from app.services.shipment_delivered_guard import check_send_allowed
    g = check_send_allowed("SHIPMENT_NOT_THERE")
    assert g["allowed"] is True
    assert g["audit_found"] is False
    assert g["delivered"] is False


def test_check_send_allowed_blocks_when_delivered(fresh):
    from app.services.shipment_delivered_guard import check_send_allowed
    _write_audit(fresh, "SHIPMENT_DEL_1",
                 {"tracking": {"status": "delivered"}})
    g = check_send_allowed("SHIPMENT_DEL_1")
    assert g["allowed"]   is False
    assert g["delivered"] is True
    assert g["reason"]    == "shipment_delivered"


def test_check_send_allowed_allows_when_not_delivered(fresh):
    from app.services.shipment_delivered_guard import check_send_allowed
    _write_audit(fresh, "SHIPMENT_ACTIVE_1",
                 {"tracking": {"status": "in_transit"}})
    g = check_send_allowed("SHIPMENT_ACTIVE_1")
    assert g["allowed"]   is True
    assert g["delivered"] is False
    assert g["reason"]    == "shipment_not_delivered"


def test_is_queue_entry_stale_threshold(fresh):
    from app.services.shipment_delivered_guard import is_queue_entry_stale
    now = "2026-05-18T12:00:00+00:00"
    # 15 days old → stale
    e_old = {"queued_at": "2026-05-03T12:00:00+00:00"}
    assert is_queue_entry_stale(e_old, now_iso=now) is True
    # 7 days old → not stale
    e_new = {"queued_at": "2026-05-11T12:00:00+00:00"}
    assert is_queue_entry_stale(e_new, now_iso=now) is False
    # malformed timestamp → not stale (safer default)
    assert is_queue_entry_stale({"queued_at": "not-a-date"}, now_iso=now) is False
    assert is_queue_entry_stale({}, now_iso=now) is False


# ─────────────────────────────────────────────────────────────────────────
# Tier 2 — email_sender execution-time guard
# ─────────────────────────────────────────────────────────────────────────

def test_send_blocked_for_delivered_shipment_queued_before_delivery(fresh):
    """The canonical operator scenario: a follow-up was queued while the
    shipment was still in transit, then DHL delivered it.  The next
    send_queued_email call MUST refuse the send and flip the entry to
    `suppressed_delivered`."""
    from app.services import email_sender as es
    _write_audit(fresh, "SHIPMENT_DEL_2",
                 {"tracking": {"status": "delivered"}})
    _write_queue(fresh, [{
        "id": "q-del-1", "batch_id": "SHIPMENT_DEL_2",
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "to": "dhl@example.com", "cc": "",
        "subject": "Follow-up", "body_text": "x",
    }])
    res = es.send_queued_email("q-del-1", method="smtp")
    assert res["ok"]            is False
    assert res["status"]        == "suppressed_delivered"
    assert res["guard"]         == "shipment_delivered"
    assert res["guard_reason"]  == "shipment_delivered"
    # Queue entry must now carry the terminal status so retries skip it.
    q = _read_queue(fresh)
    assert q[0]["status"]               == "suppressed_delivered"
    assert q[0]["suppression_reason"]   == "shipment_delivered"
    assert q[0]["suppressed_at"]


def test_retry_replay_skips_already_suppressed_entry(fresh):
    """Once an entry is marked `suppressed_delivered`, a second
    send_queued_email call must short-circuit at the
    already-suppressed check, NOT re-evaluate the guard and NOT send."""
    from app.services import email_sender as es
    _write_audit(fresh, "SHIPMENT_DEL_3",
                 {"tracking": {"status": "delivered"}})
    _write_queue(fresh, [{
        "id": "q-del-2", "batch_id": "SHIPMENT_DEL_3",
        "status": "suppressed_delivered",
        "suppression_reason": "shipment_delivered",
        "suppression_detail": "already-suppressed for test",
        "suppressed_at": "2026-05-18T08:00:00+00:00",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "to": "dhl@example.com",
        "subject": "Follow-up", "body_text": "x",
    }])
    res = es.send_queued_email("q-del-2", method="smtp")
    assert res["ok"]                is False
    assert res["status"]            == "suppressed_delivered"
    assert res["already_suppressed"] is True


def test_stale_queue_entry_refused_as_expired(fresh):
    """A queue entry older than STALE_QUEUE_DAYS must be refused with
    terminal `expired_stale_queue`, even if the shipment isn't delivered."""
    from app.services import email_sender as es
    _write_audit(fresh, "SHIPMENT_OLD_1",
                 {"tracking": {"status": "in_transit"}})
    old_iso = (datetime.now(timezone.utc)
               - timedelta(days=60)).isoformat()
    _write_queue(fresh, [{
        "id": "q-old-1", "batch_id": "SHIPMENT_OLD_1",
        "status": "pending",
        "queued_at": old_iso,
        "to": "dhl@example.com",
        "subject": "Old", "body_text": "x",
    }])
    res = es.send_queued_email("q-old-1", method="smtp")
    assert res["ok"]     is False
    assert res["status"] == "expired_stale_queue"
    assert res["guard"]  == "stale_queue"
    q = _read_queue(fresh)
    assert q[0]["status"] == "expired_stale_queue"


def test_send_allowed_when_shipment_not_delivered_and_fresh(fresh):
    """Sanity check: a fresh queue entry for an in-transit shipment is
    NOT suppressed by either guard.  (SMTP isn't configured in test env,
    so we expect the next gate's response — not an early suppression.)"""
    from app.services import email_sender as es
    _write_audit(fresh, "SHIPMENT_ACT_2",
                 {"tracking": {"status": "in_transit"}})
    _write_queue(fresh, [{
        "id": "q-act-1", "batch_id": "SHIPMENT_ACT_2",
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "to": "dhl@example.com",
        "subject": "Hi", "body_text": "x",
    }])
    res = es.send_queued_email("q-act-1", method="smtp")
    assert res["status"] not in (
        "suppressed_delivered", "expired_stale_queue",
    ), f"unexpected guard fire: {res!r}"


def test_send_allowed_when_audit_file_missing(fresh):
    """When the batch's audit.json doesn't exist, the guard must NOT
    fire — refusing every send because of a metadata gap would cause
    more harm than the rule it enforces.  Caller observes audit_found
    via the guard return contract."""
    from app.services import email_sender as es
    # No audit file written
    _write_queue(fresh, [{
        "id": "q-noaudit-1", "batch_id": "SHIPMENT_GONE",
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "to": "dhl@example.com",
        "subject": "Hi", "body_text": "x",
    }])
    res = es.send_queued_email("q-noaudit-1", method="smtp")
    assert res["status"] not in (
        "suppressed_delivered", "expired_stale_queue",
    ), f"guard wrongly fired without audit: {res!r}"


def test_send_guard_does_not_send_when_blocked(fresh, monkeypatch):
    """Hard belt-and-braces check: monkey-patch the actual SMTP send path
    to raise.  A delivered-suppressed call must NOT reach it."""
    from app.services import email_sender as es
    _write_audit(fresh, "SHIPMENT_DEL_4",
                 {"tracking": {"status": "delivered"}})
    _write_queue(fresh, [{
        "id": "q-del-4", "batch_id": "SHIPMENT_DEL_4",
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "to": "dhl@example.com",
        "subject": "x", "body_text": "x",
    }])
    # Poison the MIME build (any later step would call this); never reached.
    monkeypatch.setattr(
        es, "_build_mime",
        lambda *_a, **_kw: pytest.fail(
            "guard failed to suppress — _build_mime was reached"
        ),
        raising=True,
    )
    res = es.send_queued_email("q-del-4", method="smtp")
    assert res["status"] == "suppressed_delivered"


# ─────────────────────────────────────────────────────────────────────────
# Tier 3 — scheduler-side skip via _is_active
# ─────────────────────────────────────────────────────────────────────────

def test_is_active_returns_false_for_delivered_shipment(fresh):
    from app.services import active_shipment_monitor as asm
    # Delivered, regardless of clearance status
    assert asm._is_active({
        "tracking": {"status": "delivered"},
        "clearance_status": "",
    }) is False
    # delivered_at slot alone is also sufficient
    assert asm._is_active({
        "delivered_at": "2026-05-18T10:00:00Z",
        "clearance_status": "polish_description_generated",
    }) is False


def test_is_active_returns_true_for_in_transit(fresh):
    from app.services import active_shipment_monitor as asm
    assert asm._is_active({
        "tracking": {"status": "in_transit"},
        "clearance_status": "polish_description_generated",
    }) is True


def test_is_active_skips_delivered_even_with_open_clearance(fresh):
    """The pre-PR-209.5 behaviour required BOTH tracking-delivered AND
    a terminal clearance to mark inactive.  After this PR, tracking-
    delivered alone is enough — a stuck clearance with a delivered
    shipment must NOT be followed up."""
    from app.services import active_shipment_monitor as asm
    audit = {
        "tracking": {"status": "delivered"},
        "clearance_status": "awaiting_dhl_customs_email",   # non-terminal
    }
    assert asm._is_active(audit) is False


# ─────────────────────────────────────────────────────────────────────────
# Tier 4 — invariants (no auto-resend, no fake status, no DB writes)
# ─────────────────────────────────────────────────────────────────────────

def test_guard_module_has_no_external_or_write_paths():
    """Source-grep: the guard module must be pure.  No HTTP, no wFirma,
    no PZ, no DHL email send, no DB writes."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "app"
           / "services" / "shipment_delivered_guard.py").read_text(
               encoding="utf-8"
           )
    for bad in (
        "wfirma_client", "requests.post", "requests.put",
        "requests.delete", "httpx.post", "httpx.patch", "httpx.delete",
        "create_proforma", "create_customer", "create_product",
        "send_email(", "dhl_dispatch", "smtplib", "smtp.send",
        "INSERT INTO", "UPDATE ", "DELETE FROM",
        "con.execute(",   # no sqlite calls
    ):
        assert bad not in src, (
            f"shipment_delivered_guard must not reference {bad!r}"
        )


def test_email_sender_guard_does_not_invent_status_for_unknown_batches(fresh):
    """When batch_id is empty / unknown, the guard must NOT manufacture
    a delivered status — the missing-audit branch returns allowed=True
    so the caller proceeds normally to other validations."""
    from app.services import email_sender as es
    _write_queue(fresh, [{
        "id": "q-empty-bid", "batch_id": "",
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "to": "dhl@example.com",
        "subject": "x", "body_text": "x",
    }])
    res = es.send_queued_email("q-empty-bid", method="smtp")
    assert res["status"] not in (
        "suppressed_delivered", "expired_stale_queue",
    )
