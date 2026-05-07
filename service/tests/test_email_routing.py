"""
test_email_routing.py — pin the public recipient-resolution helpers in
service/app/config/email_routing.py.

Phase 1.3.5 promoted resolve_dhl_to / resolve_dhl_cc from the proactive
builder to email_routing so both the builder-time preview and the
queue-time send path resolve via a single source of truth.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.config import email_routing as er


# ── resolve_dhl_to ─────────────────────────────────────────────────────────

def test_resolve_dhl_to_uses_constant_when_populated(monkeypatch):
    """DHL_TO populated → returns the formatted constant; env-var ignored."""
    monkeypatch.setattr(er, "DHL_TO", ["odprawacelna@dhl.com"])
    monkeypatch.setattr(er.settings, "dhl_customs_email",
                        "wrong-env-value@example.com", raising=False)
    assert er.resolve_dhl_to() == "odprawacelna@dhl.com"


def test_resolve_dhl_to_falls_back_when_constant_empty_list(monkeypatch):
    monkeypatch.setattr(er, "DHL_TO", [])
    monkeypatch.setattr(er.settings, "dhl_customs_email",
                        "fallback@dhl.example", raising=False)
    assert er.resolve_dhl_to() == "fallback@dhl.example"


def test_resolve_dhl_to_falls_back_when_constant_all_blank(monkeypatch):
    """`DHL_TO = [""]` is functionally empty — fallback fires."""
    monkeypatch.setattr(er, "DHL_TO", [""])
    monkeypatch.setattr(er.settings, "dhl_customs_email",
                        "fallback@dhl.example", raising=False)
    assert er.resolve_dhl_to() == "fallback@dhl.example"


def test_resolve_dhl_to_empty_when_both_empty(monkeypatch):
    monkeypatch.setattr(er, "DHL_TO", [])
    monkeypatch.setattr(er.settings, "dhl_customs_email", "", raising=False)
    assert er.resolve_dhl_to() == ""


# ── resolve_dhl_cc ─────────────────────────────────────────────────────────

def test_resolve_dhl_cc_uses_constant_when_populated(monkeypatch):
    monkeypatch.setattr(er, "INTERNAL_CC",
                        ["info@estrellajewels.eu",
                         "import@estrellajewels.eu",
                         "account@estrellajewels.eu"])
    monkeypatch.setattr(er.settings, "dhl_customs_cc",
                        "wrong-env-cc@example.com", raising=False)
    cc = er.resolve_dhl_cc()
    assert "info@estrellajewels.eu"    in cc
    assert "import@estrellajewels.eu"  in cc
    assert "account@estrellajewels.eu" in cc
    assert "wrong-env-cc@example.com" not in cc


def test_resolve_dhl_cc_falls_back_when_constant_empty_list(monkeypatch):
    monkeypatch.setattr(er, "INTERNAL_CC", [])
    monkeypatch.setattr(er.settings, "dhl_customs_cc",
                        "fallback-cc@example.com", raising=False)
    assert er.resolve_dhl_cc() == "fallback-cc@example.com"


def test_resolve_dhl_cc_empty_when_both_empty(monkeypatch):
    monkeypatch.setattr(er, "INTERNAL_CC", [])
    monkeypatch.setattr(er.settings, "dhl_customs_cc", "", raising=False)
    assert er.resolve_dhl_cc() == ""


# ── Single-source-of-truth invariant ───────────────────────────────────────

def test_builder_and_queue_path_share_resolution(monkeypatch):
    """The proactive builder and the queue-time _resolve_proactive_recipients
    must produce identical TO and CC strings when called with the same
    DHL_TO / INTERNAL_CC / settings state. Phase 1.3.5 invariant."""
    monkeypatch.setattr(er, "DHL_TO", ["odprawacelna@dhl.com"])
    monkeypatch.setattr(er, "INTERNAL_CC",
                        ["info@estrellajewels.eu",
                         "import@estrellajewels.eu",
                         "account@estrellajewels.eu"])

    builder_to = er.resolve_dhl_to()
    builder_cc = er.resolve_dhl_cc()

    from app.api.routes_action_proposals import _resolve_proactive_recipients
    monkeypatch.setattr(er.settings, "environment", "dev", raising=False)
    queue_to, queue_cc, err = _resolve_proactive_recipients()

    assert err is None
    assert builder_to == queue_to
    assert builder_cc == queue_cc
