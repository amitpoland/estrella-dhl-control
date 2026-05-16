"""Phase 6F.5 — Error swallowing contract.

The dual-write MUST NEVER raise. Any exception inside the helper is
logged at WARNING and the helper returns a result dict with ``ok=False``.
This guarantees the legacy /post commit cannot be rolled back by a bug
in the dual-write path.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.services import finance_dual_write as fdw


def test_create_charge_raises_does_not_propagate(monkeypatch, tmp_path: Path, caplog):
    """If finance_postings_db.create_charge raises, the helper swallows it."""
    db = tmp_path / "finance_postings.sqlite"

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB write failure")

    monkeypatch.setattr(fdw.fpdb, "create_charge", _boom)

    caplog.set_level(logging.WARNING)
    # Must NOT raise.
    res = fdw.dual_write_proforma_post(
        db_path=db,
        batch_id="B/err",
        client_name="Err Co",
        currency="EUR",
        full_number="FV/1/2026",
        service_charges_json='[{"charge_type":"freight","amount":1.00,"currency":"EUR"}]',
        enabled=True,
        shadow=False,
    )
    assert res["ok"] is False
    assert "RuntimeError" in res["reason"]
    # WARNING was logged.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("finance_dual_write_failed" in r.getMessage() for r in warnings)


def test_init_db_raises_does_not_propagate(monkeypatch, tmp_path: Path, caplog):
    db = tmp_path / "finance_postings.sqlite"
    monkeypatch.setattr(
        fdw.fpdb, "init_db",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
    )
    caplog.set_level(logging.WARNING)
    res = fdw.dual_write_proforma_post(
        db_path=db,
        batch_id="B/init",
        client_name="Init Co",
        currency="EUR",
        full_number="FV/1/2026",
        service_charges_json="[]",
        enabled=True,
        shadow=False,
    )
    assert res["ok"] is False
    assert "init_db_failed" in res["reason"]


def test_unexpected_exception_in_payload_build_does_not_propagate(
    monkeypatch, tmp_path: Path, caplog,
):
    """If _build_payload itself blows up, the outer guard catches it."""
    db = tmp_path / "finance_postings.sqlite"

    def _explode(*a, **kw):
        raise ValueError("payload exploded")

    monkeypatch.setattr(fdw, "_build_payload", _explode)
    caplog.set_level(logging.WARNING)
    res = fdw.dual_write_proforma_post(
        db_path=db,
        batch_id="B/x",
        client_name="X Co",
        currency="EUR",
        full_number="FV/1/2026",
        service_charges_json="[]",
        enabled=True,
        shadow=False,
    )
    assert res["ok"] is False
    assert "payload_build_failed" in res["reason"]


def test_helper_never_raises_with_garbage_input(tmp_path: Path):
    """Even pathological inputs must not raise to the caller."""
    db = tmp_path / "finance_postings.sqlite"
    # malformed json
    r1 = fdw.dual_write_proforma_post(
        db_path=db, batch_id="B", client_name="C", currency="EUR",
        full_number="FV/1", service_charges_json="not-json",
        enabled=True, shadow=False,
    )
    assert r1["ok"] is True  # malformed json → empty list → empty charges, posting created
    # None values
    r2 = fdw.dual_write_proforma_post(
        db_path=db, batch_id="", client_name="", currency="",
        full_number="", service_charges_json=None,
        enabled=True, shadow=False,
    )
    assert r2["ok"] is True
    assert r2.get("skipped") is True  # missing mandatory fields → graceful skip
