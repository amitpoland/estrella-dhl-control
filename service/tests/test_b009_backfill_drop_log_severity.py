"""B-009 — backfill dropped-charge log severity split by reason.

Rename-path collisions (canonical_already_has_charge_type) log at INFO.
Canonical-wins drops (canonical_wins_collision) stay WARNING.
Unknown reasons stay WARNING (fail-visible). Response payload unchanged.

Run: python -m pytest tests/test_b009_backfill_drop_log_severity.py -q
"""
from __future__ import annotations

import logging

from app.api.routes_contractor_projection import _log_backfill_dropped_charges


def test_rename_path_collision_logs_info_not_warning(caplog):
    rows = [{
        "charge_type": "freight", "amount": 10.0, "currency": "PLN",
        "old_client_name": "OLD", "reason": "canonical_already_has_charge_type",
    }]
    with caplog.at_level(logging.INFO):
        _log_backfill_dropped_charges("B-009", rows)
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("rename-path charge collision" in r.getMessage() for r in infos)
    assert any("canonical_already_has_charge_type" in r.getMessage() for r in infos)
    assert not any("DROPPED" in r.getMessage() for r in warns)


def test_canonical_wins_logs_warning(caplog):
    rows = [{
        "charge_type": "freight", "amount": 25.0, "currency": "PLN",
        "old_client_name": "OLD", "reason": "canonical_wins_collision",
    }]
    with caplog.at_level(logging.INFO):
        _log_backfill_dropped_charges("B-009", rows)
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "DROPPED" in r.getMessage() and "canonical_wins_collision" in r.getMessage()
        for r in warns
    )


def test_mixed_reasons_split_severity(caplog):
    rows = [
        {"charge_type": "a", "amount": 1.0, "reason": "canonical_already_has_charge_type"},
        {"charge_type": "b", "amount": 2.0, "reason": "canonical_wins_collision"},
        {"charge_type": "c", "amount": 3.0, "reason": "future_unknown"},
    ]
    with caplog.at_level(logging.INFO):
        _log_backfill_dropped_charges("B-009-MIX", rows)
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("rename-path" in m for m in infos)
    assert any("canonical_wins_collision" in m for m in warns)
    assert any("unclassified reason" in m for m in warns)


def test_empty_noop(caplog):
    with caplog.at_level(logging.INFO):
        _log_backfill_dropped_charges("B-009", [])
    assert caplog.records == []


def test_source_no_longer_has_single_conflated_warning():
    from pathlib import Path
    src = Path("app/api/routes_contractor_projection.py").read_text(encoding="utf-8")
    # Old single conflated line must be gone; helper owns the split.
    assert "_log_backfill_dropped_charges" in src
    assert 'names (canonical-wins, operator-chosen): %s"' not in src
    assert "rename-path charge collision" in src
