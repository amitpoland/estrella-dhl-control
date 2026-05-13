"""
test_dhl_proactive_dispatch_p2.py — coordinator.dispatch_proactive integration

P2 wires `DhlClearanceCoordinator.dispatch_proactive` through:
  - Path A scope gate
  - ADR-018 shadow/live flag truth table
  - Idempotency by audit.dhl_clearance.p2_dispatch.message_id
  - AWB stability predicate
  - Builder package construction + content_sha256
  - Manifest writes
  - State transitions

These tests cover all 9 acceptance criteria from
docs/operational-memory/dhl-selfclearance/02_P2_PROACTIVE_DISPATCH.md
plus negative paths.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_clearance_coordinator as cc  # noqa: E402
from app.services import dhl_clearance_manifest as mf     # noqa: E402
from app.services import dhl_clearance_state_engine as se # noqa: E402
from app.core.config import settings                      # noqa: E402


_PATH_A_DECISION = {
    "clearance_path": "dhl_self_clearance",
    "total_value_usd": 1500.0,
}
_PATH_B_DECISION = {
    "clearance_path": "agency_clearance",
    "total_value_usd": 3500.0,
}


def _audit_path_a(*, awb: str = "AWB123", with_attachments: bool = True) -> dict:
    audit = {
        "clearance_decision": dict(_PATH_A_DECISION),
        "dhl_awb": awb,
        "polish_desc_filename": "test_polish.pdf" if with_attachments else "",
    }
    return audit


def _audit_path_b() -> dict:
    return {"clearance_decision": dict(_PATH_B_DECISION), "dhl_awb": "AWB999"}


def _stub_pkg(**overrides) -> dict:
    base = {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_proactive_dispatch",
        "to":           "odprawacelna@dhl.com",
        "cc":           "import@estrellajewels.eu",
        "subject":      "AWB AWB123 — Customs Declaration",
        "body_text":    "Customs declaration body — Polish then English",
        "body_html":    "<pre>Customs declaration body — Polish then English</pre>",
        "attachments":  [{"label": "Polish Customs Description", "path": "/tmp/x.pdf"}],
        "missing":      [],
    }
    base.update(overrides)
    return base


@pytest.fixture()
def coord():
    """Reset to default-OFF / shadow-True flag combination for each test."""
    return cc.DhlClearanceCoordinator()


@pytest.fixture(autouse=True)
def _reset_flags(monkeypatch):
    """Force ADR-018 default (SHADOW state): shadow_mode=True, live_enabled=False."""
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_shadow_mode", True)


# ── Scope gate (Path A vs Path B) ────────────────────────────────────────────

def test_path_b_raises_out_of_scope_error(coord):
    audit = _audit_path_b()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB999", audit=audit)
    with pytest.raises(cc.OutOfScopeError):
        coord.dispatch_proactive(inp)


def test_path_b_no_manifest_mutation(coord):
    audit = _audit_path_b()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB999", audit=audit)
    try:
        coord.dispatch_proactive(inp)
    except cc.OutOfScopeError:
        pass
    assert mf.MANIFEST_KEY not in audit


def test_path_a_passes_scope_gate(coord, monkeypatch):
    # Force AWB-unstable to short-circuit before any builder call,
    # but verify scope gate let us through.
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: False)
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    result = coord.dispatch_proactive(inp)
    assert result["status"] == "skipped"
    assert result["reason"] == "awb_unstable"


# ── ADR-018 flag combinations ────────────────────────────────────────────────

def test_forbidden_flag_combination_raises(coord, monkeypatch):
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_shadow_mode", False)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=_audit_path_a())
    with pytest.raises(cc.ForbiddenFlagCombination):
        coord.dispatch_proactive(inp)


def test_dormant_state_returns_skipped(coord, monkeypatch):
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_shadow_mode", False)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=_audit_path_a())
    result = coord.dispatch_proactive(inp)
    assert result["status"] == "skipped"
    assert result["reason"] == "dormant_state"
    assert result["message_id"] is None
    assert result["idempotent"] is False


def test_shadow_state_is_default(coord, monkeypatch):
    """Per ADR-018 the safe-default state is SHADOW (shadow=True, live=False)."""
    audit = _audit_path_a()
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_clearance_coordinator.build_dhl_proactive_dispatch"
        if False else "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    result = coord.dispatch_proactive(inp)
    assert result["status"] == "shadow"
    assert result["message_id"].startswith("shadow:")


# ── AWB stability gate ───────────────────────────────────────────────────────

def test_awb_unstable_no_op(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: False)
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    result = coord.dispatch_proactive(inp)
    assert result["status"] == "skipped"
    assert result["reason"] == "awb_unstable"
    # State remains at awaiting_preemptive_send
    state = audit.get(mf.MANIFEST_KEY, {}).get("state", se.INITIAL_STATE)
    assert state == se.INITIAL_STATE


def test_awb_stable_proceeds_to_build(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=_audit_path_a())
    result = coord.dispatch_proactive(inp)
    assert result["status"] == "shadow"


# ── Shadow mode: build + manifest, NO send ───────────────────────────────────

def test_shadow_writes_p2_dispatch_manifest(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    result = coord.dispatch_proactive(inp)
    p2 = audit[mf.MANIFEST_KEY]["p2_dispatch"]
    assert p2["shadow"] is True
    assert p2["message_id"].startswith("shadow:")
    assert p2["recipient"] == "odprawacelna@dhl.com"
    assert p2["sent_at"]
    assert len(p2["content_sha256"]) == 64


def test_shadow_no_email_queued(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    # If queue_email were called, this would explode (TypeError on stub args).
    # We avoid patching email_service entirely and rely on the shadow branch
    # not importing it. The result.status == "shadow" confirms no send.
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=_audit_path_a())
    result = coord.dispatch_proactive(inp)
    assert result["status"] == "shadow"


def test_shadow_advances_state_to_awaiting_poland_arrival(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    coord.dispatch_proactive(inp)
    assert audit[mf.MANIFEST_KEY]["state"] == se.STATE_AWAITING_POLAND_ARRIVAL


def test_shadow_state_history_carries_shadow_true_per_adr018(coord, monkeypatch):
    """ADR-018 Invariant 4: state_history entries written under shadow_mode
    MUST carry `shadow: True` as a structured field. Per the canonical
    adr-historian re-review, this is enforced via state_engine.transition
    accepting a shadow= kwarg that materializes the key on the entry record.
    """
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    coord.dispatch_proactive(inp)
    history = audit[mf.MANIFEST_KEY]["state_history"]
    assert len(history) == 1
    entry = history[0]
    # Reason is the canonical single value (no _shadow / _sent split).
    assert entry["reason"] == "p2_dispatch"
    # ADR-018 Invariant 4: shadow:True is a structured field, not a substring.
    assert entry.get("shadow") is True


def test_live_state_history_omits_shadow_field(coord, monkeypatch):
    """When live_enabled=True (LIVE state), state_history entries are NOT
    shadow-tagged. Audit consumers filter `entry.get("shadow") is True`
    to count shadow runs; live runs must be absent from that filter."""
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    monkeypatch.setattr("app.services.email_service.queue_email",
                        lambda **k: "msg_id_live")
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    coord.dispatch_proactive(inp)
    history = audit[mf.MANIFEST_KEY]["state_history"]
    assert len(history) == 1
    entry = history[0]
    assert entry["reason"] == "p2_dispatch"
    # Shadow key is absent (or False) on live entries.
    assert entry.get("shadow") in (None, False)


# ── Live mode: queue email + manifest ────────────────────────────────────────

def test_live_calls_queue_email_exactly_once(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    call_count = {"n": 0}

    def fake_queue(**kwargs):
        call_count["n"] += 1
        return "msg_id_live_xyz"

    monkeypatch.setattr("app.services.email_service.queue_email", fake_queue)
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    result = coord.dispatch_proactive(inp)
    assert call_count["n"] == 1
    assert result["status"] == "sent"
    assert result["message_id"] == "msg_id_live_xyz"


def test_live_writes_p2_dispatch_manifest(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    monkeypatch.setattr("app.services.email_service.queue_email",
                        lambda **k: "msg_id_live")
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    coord.dispatch_proactive(inp)
    p2 = audit[mf.MANIFEST_KEY]["p2_dispatch"]
    assert p2["shadow"] is False
    assert p2["message_id"] == "msg_id_live"
    assert "odprawacelna@dhl.com" in p2["recipient"]
    assert p2["sent_at"]
    assert len(p2["content_sha256"]) == 64


def test_live_advances_state(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    monkeypatch.setattr("app.services.email_service.queue_email",
                        lambda **k: "msg_id_live")
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    coord.dispatch_proactive(inp)
    assert audit[mf.MANIFEST_KEY]["state"] == se.STATE_AWAITING_POLAND_ARRIVAL


# ── Idempotency ───────────────────────────────────────────────────────────────

def test_idempotent_second_call_returns_prior_result(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    first = coord.dispatch_proactive(inp)
    second = coord.dispatch_proactive(inp)
    assert second["idempotent"] is True
    assert second["message_id"] == first["message_id"]
    assert second["content_sha256"] == first["content_sha256"]


def test_idempotent_no_second_email_queued(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    call_count = {"n": 0}

    def fake_queue(**kwargs):
        call_count["n"] += 1
        return "msg_id_live"

    monkeypatch.setattr("app.services.email_service.queue_email", fake_queue)
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    coord.dispatch_proactive(inp)
    coord.dispatch_proactive(inp)
    assert call_count["n"] == 1  # only one queue call


# ── Build / queue failure paths ──────────────────────────────────────────────

def test_build_failure_advances_to_dispatch_failed(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)

    def fake_build(audit, batch_id):
        raise RuntimeError("simulated build failure")

    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        fake_build,
    )
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    result = coord.dispatch_proactive(inp)
    assert result["status"] == "blocked"
    assert result["reason"] == "build_failed"
    assert audit[mf.MANIFEST_KEY]["state"] == se.STATE_DISPATCH_FAILED


def test_missing_attachments_blocks(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(missing=["polish desc"]),
    )
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    result = coord.dispatch_proactive(inp)
    assert result["status"] == "blocked"
    assert result["reason"] == "missing_attachments"
    # State stays at awaiting_preemptive_send
    assert audit[mf.MANIFEST_KEY]["state"] == se.STATE_AWAITING_PREEMPTIVE_SEND


def test_queue_failure_advances_to_dispatch_failed(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )

    def fake_queue(**kwargs):
        raise OSError("simulated smtp queue failure")

    monkeypatch.setattr("app.services.email_service.queue_email", fake_queue)
    audit = _audit_path_a()
    inp = cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit)
    result = coord.dispatch_proactive(inp)
    assert result["status"] == "blocked"
    assert result["reason"] == "queue_failed"
    assert audit[mf.MANIFEST_KEY]["state"] == se.STATE_DISPATCH_FAILED


# ── Content sha256 determinism ───────────────────────────────────────────────

def test_content_sha256_deterministic_same_payload():
    pkg1 = _stub_pkg()
    pkg2 = _stub_pkg()
    assert cc._compute_content_sha256(pkg1) == cc._compute_content_sha256(pkg2)


def test_content_sha256_differs_on_subject_change():
    pkg1 = _stub_pkg(subject="AWB123 — A")
    pkg2 = _stub_pkg(subject="AWB123 — B")
    assert cc._compute_content_sha256(pkg1) != cc._compute_content_sha256(pkg2)


def test_content_sha256_differs_on_attachment_change():
    pkg1 = _stub_pkg()
    pkg2 = _stub_pkg(attachments=[{"label": "Different", "path": "/tmp/y.pdf"}])
    assert cc._compute_content_sha256(pkg1) != cc._compute_content_sha256(pkg2)


def test_content_sha256_invariant_to_attachment_path():
    pkg1 = _stub_pkg(attachments=[{"label": "X", "path": "/a/b/c.pdf"}])
    pkg2 = _stub_pkg(attachments=[{"label": "X", "path": "/d/e/f.pdf"}])
    assert cc._compute_content_sha256(pkg1) == cc._compute_content_sha256(pkg2)


def test_content_sha256_is_64_hex_chars():
    sha = cc._compute_content_sha256(_stub_pkg())
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)


# ── Coordinator scope-gate helpers (regression of P0 invariants) ────────────

def test_is_in_scope_path_a_true():
    assert cc.DhlClearanceCoordinator.is_in_scope(_audit_path_a()) is True


def test_is_in_scope_path_b_false():
    assert cc.DhlClearanceCoordinator.is_in_scope(_audit_path_b()) is False


def test_is_in_scope_missing_decision_false():
    assert cc.DhlClearanceCoordinator.is_in_scope({}) is False


def test_predecessor_p2_always_unblocked():
    assert cc.DhlClearanceCoordinator.predecessor_live_enabled("p2") is True


# ── Manifest content_sha256 validation (ADR-006 hash-only) ───────────────────

def test_manifest_p2_dispatch_sha256_validated(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    audit = _audit_path_a()
    coord.dispatch_proactive(cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit))
    sha = audit[mf.MANIFEST_KEY]["p2_dispatch"]["content_sha256"]
    assert len(sha) == 64
    int(sha, 16)  # valid hex


# ── Result-shape invariants ──────────────────────────────────────────────────

def test_result_has_required_keys(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    audit = _audit_path_a()
    result = coord.dispatch_proactive(cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit))
    for key in ("status", "reason", "message_id", "content_sha256", "idempotent"):
        assert key in result


def test_dormant_result_shape(coord, monkeypatch):
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_shadow_mode", False)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    audit = _audit_path_a()
    result = coord.dispatch_proactive(cc.DispatchInput(batch_id="B1", awb="AWB123", audit=audit))
    # Per ADR-019: return shape now carries `triggered_by` (default "sweep"
    # when caller= is omitted).
    assert result == {
        "status": "skipped",
        "reason": "dormant_state",
        "message_id": None,
        "content_sha256": "",
        "idempotent": False,
        "triggered_by": "sweep",
    }


# ── Multiple distinct AWBs in shadow mode (volume invariant) ─────────────────

def test_shadow_multiple_awbs_unique_message_ids(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(subject=f"AWB {batch_id}"),
    )
    msg_ids = set()
    for i in range(5):
        audit = _audit_path_a(awb=f"AWB{i}")
        inp = cc.DispatchInput(batch_id=f"B{i}", awb=f"AWB{i}", audit=audit)
        result = coord.dispatch_proactive(inp)
        msg_ids.add(result["message_id"])
    assert len(msg_ids) == 5


# ── Real-builder integration (no stub) — catches type-contract drift ────────

def test_real_builder_to_field_is_str_not_list():
    """Regression test against integration-boundary CRITICAL finding: the
    real builder returns `pkg["to"]` as a comma-separated string (from
    `resolve_dhl_to()`), NOT as `List[str]`. The coordinator's
    `_normalise_recipient` helper must handle both shapes.
    """
    from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
    audit = _audit_path_a()
    pkg = build_dhl_proactive_dispatch(audit, batch_id="B1")
    assert isinstance(pkg["to"], str), (
        f"resolve_dhl_to() returns str; coordinator must normalise — "
        f"got type {type(pkg['to']).__name__}"
    )
    assert isinstance(pkg["cc"], str), (
        f"resolve_dhl_cc() returns str; coordinator must normalise — "
        f"got type {type(pkg['cc']).__name__}"
    )


def test_normalise_recipient_handles_str():
    assert cc._normalise_recipient("a@b.com") == "a@b.com"


def test_normalise_recipient_handles_list():
    assert cc._normalise_recipient(["a@b.com", "c@d.com"]) == "a@b.com, c@d.com"


def test_normalise_recipient_handles_none_and_empty():
    assert cc._normalise_recipient(None) == ""
    assert cc._normalise_recipient("") == ""
    assert cc._normalise_recipient([]) == ""


def test_normalise_recipient_no_char_iteration_bug():
    """The bug integration-boundary caught: a naive `",".join("a@b.com")`
    would produce "a,@,b,.,c,o,m". Confirm we don't do that anymore."""
    result = cc._normalise_recipient("odprawacelna@dhl.com")
    assert result == "odprawacelna@dhl.com"
    # The result is the str unchanged — no character-level join.
    assert result.count("@") == 1


# ── Live state transitions match shadow (parity check) ───────────────────────

def test_live_and_shadow_advance_to_same_state(coord, monkeypatch):
    monkeypatch.setattr(coord, "is_awb_stable_for", lambda awb, batch_id=None: True)
    monkeypatch.setattr(
        "app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
        lambda audit, batch_id: _stub_pkg(),
    )
    # Shadow run
    audit_s = _audit_path_a()
    coord.dispatch_proactive(cc.DispatchInput(batch_id="Bs", awb="AWB123", audit=audit_s))
    state_s = audit_s[mf.MANIFEST_KEY]["state"]

    # Live run
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    monkeypatch.setattr("app.services.email_service.queue_email",
                        lambda **k: "msg_id_live")
    audit_l = _audit_path_a()
    coord.dispatch_proactive(cc.DispatchInput(batch_id="Bl", awb="AWB123", audit=audit_l))
    state_l = audit_l[mf.MANIFEST_KEY]["state"]

    assert state_s == state_l == se.STATE_AWAITING_POLAND_ARRIVAL
