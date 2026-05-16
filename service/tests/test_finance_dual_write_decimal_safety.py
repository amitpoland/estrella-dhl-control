"""Phase 6F.5 — Monetary safety: Decimal conversion, no float-rounding bugs.

The classic pitfall: ``int(3.49 * 100)`` yields 348 (floating-point drift).
The dual-write must use ``Decimal(str(x)) * 100`` with ROUND_HALF_EVEN.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import finance_dual_write as fdw
from app.services import finance_postings_db as fpdb


def _run_with(amount, currency="EUR", charge_type="freight"):
    return (
        f'[{{"charge_type":"{charge_type}",'
        f'"amount":{amount},"currency":"{currency}"}}]'
    )


@pytest.mark.parametrize("amount,expected_minor", [
    (3.49,  349),
    (1.00,  100),
    (0.01,    1),
    (12.34,  1234),
    (99.99,  9999),
    (10,    1000),
    (0.025,    2),    # ROUND_HALF_EVEN: 2.5 → 2 (banker's rounding)
    (0.035,    4),    # ROUND_HALF_EVEN: 3.5 → 4 (banker's rounding)
    (0.005,    0),    # ROUND_HALF_EVEN: 0.5 → 0
    (0.015,    2),    # ROUND_HALF_EVEN: 1.5 → 2
])
def test_amount_to_minor_round_half_even(amount, expected_minor):
    assert fdw._amount_to_minor(amount) == expected_minor


def test_persisted_amount_minor_matches_decimal(tmp_path: Path):
    db = tmp_path / "finance_postings.sqlite"
    res = fdw.dual_write_proforma_post(
        db_path=db,
        batch_id="B/decimal-safety",
        client_name="Decimal Test Ltd",
        currency="EUR",
        full_number="FV/1/2026",
        service_charges_json=_run_with(3.49),
        enabled=True,
        shadow=False,
    )
    assert res["ok"] is True
    rows = fpdb.list_charges(db, batch_id="B/decimal-safety")
    assert len(rows) == 1
    assert rows[0].amount_minor == 349, (
        f"Float drift: expected 349 minor units for 3.49 EUR, got {rows[0].amount_minor}"
    )


def test_zero_amount_skipped(tmp_path: Path):
    db = tmp_path / "finance_postings.sqlite"
    res = fdw.dual_write_proforma_post(
        db_path=db,
        batch_id="B/zero",
        client_name="Zero Ltd",
        currency="EUR",
        full_number="FV/1/2026",
        service_charges_json=_run_with(0),
        enabled=True,
        shadow=False,
    )
    assert res["ok"] is True
    # Zero amount produces 0 charges (posting still created).
    assert res["created_charges"] == 0
    rows = fpdb.list_charges(db, batch_id="B/zero")
    assert rows == []


def test_source_grep_no_naive_int_times_100():
    """Defense in depth: the helper file must not use the unsafe int(x*100) pattern
    in executable code. Docstring/comment mentions (which describe the forbidden
    pattern) are stripped before checking.
    """
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "finance_dual_write.py"
    raw = src.read_text(encoding="utf-8")
    # Strip docstrings + comments — they may reference the forbidden pattern textually.
    code = re.sub(r'"""[\s\S]*?"""', '', raw)
    code = re.sub(r"'''[\s\S]*?'''", '', code)
    code = re.sub(r"(?m)#.*$", '', code)
    # In code-only text, forbid: int(<expr> * 100) without Decimal wrapping.
    bad = re.findall(r"int\s*\(\s*[^)]*\*\s*100", code)
    bad = [b for b in bad if "Decimal" not in b]
    assert bad == [], f"Forbidden naive int(x*100) in executable code: {bad}"
