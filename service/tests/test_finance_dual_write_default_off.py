"""Phase 6F.5 — Dual-write defaults OFF.

The first and most important contract: when the feature flag is not set
(or explicitly False), the dual-write helper returns immediately. No DB
file is touched. No log line is emitted that suggests persistence.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import finance_dual_write as fdw


def test_default_flag_is_false_in_settings():
    """If the env vars are unset, the Settings defaults must be False."""
    from app.core import config as cfg
    s = cfg.Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.finance_dual_write_enabled is False
    assert s.finance_dual_write_shadow is False


def test_dual_write_returns_immediately_when_disabled(tmp_path: Path):
    db = tmp_path / "finance_postings.sqlite"
    res = fdw.dual_write_proforma_post(
        db_path=db,
        batch_id="B1",
        client_name="Acme",
        currency="EUR",
        full_number="FV/1/2026",
        service_charges_json='[{"charge_type":"freight","amount":10.0,"currency":"EUR"}]',
        enabled=False,
        shadow=False,
    )
    assert res["ok"] is True
    assert res["skipped"] is True
    assert res["reason"] == "flag_off"
    # Critical: the DB file must NOT have been created.
    assert not db.exists(), (
        "Default-OFF behaviour must not touch the finance_postings.sqlite file"
    )


def test_shadow_alone_without_enabled_is_still_off(tmp_path: Path):
    """shadow=True with enabled=False is still off (enabled is the master switch)."""
    db = tmp_path / "finance_postings.sqlite"
    res = fdw.dual_write_proforma_post(
        db_path=db,
        batch_id="B1",
        client_name="Acme",
        currency="EUR",
        full_number="FV/1/2026",
        service_charges_json="[]",
        enabled=False,
        shadow=True,
    )
    assert res == {"ok": True, "skipped": True, "reason": "flag_off"}
    assert not db.exists()
