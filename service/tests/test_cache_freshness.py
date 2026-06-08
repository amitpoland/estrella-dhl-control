"""
test_cache_freshness.py — Stale audit.json / pz_rows.json detection.

The 2026-05 row-schema bump (v2) added product_code, line_position,
nazwa_pl, nazwa_en, nazwa to every PZ row. Audits stamped before the bump
do not carry these fields; consumers must treat them as stale and
regenerate from source.
"""
from __future__ import annotations

import pytest

from app.services.cache_freshness import (
    CURRENT_ROW_SCHEMA_VERSION,
    is_audit_stale,
    stale_field_summary,
)


def _row_v2():
    return {
        "invoice_no":      "EJL/25-26/1247",
        "product_code":    "EJL/25-26/1247-1",
        "line_position":   1,
        "nazwa_pl":        "pierścionek",
        "nazwa_en":        "Plain 9KT Gold Jewellery RING",
        "nazwa":           "pierścionek / Plain 9KT Gold Jewellery RING",
        "quantity":        2,
    }


def test_v2_audit_with_complete_rows_is_fresh():
    audit = {
        "row_schema_version": CURRENT_ROW_SCHEMA_VERSION,
        "rows": [_row_v2()],
    }
    stale, reason = is_audit_stale(audit)
    assert stale is False, reason


def test_missing_row_schema_version_is_stale():
    audit = {"rows": [_row_v2()]}
    stale, reason = is_audit_stale(audit)
    assert stale is True
    assert "row_schema_version" in reason


def test_old_row_schema_version_is_stale():
    audit = {"row_schema_version": "v1", "rows": [_row_v2()]}
    stale, _ = is_audit_stale(audit)
    assert stale is True


def test_row_missing_product_code_is_stale():
    row = _row_v2()
    row.pop("product_code")
    audit = {"row_schema_version": CURRENT_ROW_SCHEMA_VERSION, "rows": [row]}
    stale, reason = is_audit_stale(audit)
    assert stale is True
    assert "product_code" in reason


def test_row_missing_bilingual_nazwa_is_stale():
    row = _row_v2()
    row.pop("nazwa")
    audit = {"row_schema_version": CURRENT_ROW_SCHEMA_VERSION, "rows": [row]}
    stale, _ = is_audit_stale(audit)
    assert stale is True


def test_summary_lists_per_row_missing_fields():
    rows = [
        _row_v2(),                                                        # OK
        {**_row_v2(), "product_code": ""},                                # missing PC
        {**_row_v2(), "nazwa": "", "nazwa_pl": "", "nazwa_en": ""},       # missing names
    ]
    audit = {"row_schema_version": CURRENT_ROW_SCHEMA_VERSION, "rows": rows}
    summary = stale_field_summary(audit)
    assert summary["stale"] is True
    assert summary["row_count"] == 3
    missing_idx = {entry["row_index"] for entry in summary["rows_missing_fields"]}
    assert missing_idx == {1, 2}


def test_empty_audit_not_yet_generated():
    # {} has no rows and no stamp → "not-yet-engine-generated", not stale
    stale, reason = is_audit_stale({})
    assert stale is False, reason

def test_none_audit_is_invalid():
    # None is not a dict → always treated as stale (invalid input)
    assert is_audit_stale(None)[0] is True


def test_invoice_intake_rows_not_flagged_stale():
    """Audits with _rows_source='db_invoice_lines' and no row_schema_version
    are invoice-intake preview rows written before the PZ engine runs.
    SAD/ZC429 customs data is not yet available, so nazwa_pl/en/nazwa are
    absent by design — not a cache staleness problem.  Regression for
    AWB 9938632830 where the stale banner fired on a pre-clearance draft."""
    audit = {
        "_rows_source": "db_invoice_lines",
        "rows": [
            {"invoice_no": "EJL/25-26/1337", "product_code": "EJL/25-26/1337-1",
             "quantity": 5, "item_type": ""},
            {"invoice_no": "EJL/25-26/1337", "product_code": "EJL/25-26/1337-2",
             "quantity": 3, "item_type": ""},
        ],
        # no row_schema_version — engine has not run yet
    }
    stale, reason = is_audit_stale(audit)
    assert stale is False, f"expected not-stale for db_invoice_lines draft, got: {reason!r}"

    summary = stale_field_summary(audit)
    assert summary["stale"] is False
    # rows_missing_fields is always computed from raw rows regardless of stale flag;
    # intake rows lack nazwa_pl/en/nazwa by design — the stale=False gate is what matters


def test_invoice_intake_escape_requires_exact_source_value():
    """Only _rows_source='db_invoice_lines' escapes the stale check.
    Any other value (or missing) still triggers the schema version gate."""
    # Missing _rows_source — rows exist, no stamp → stale
    audit_no_source = {"rows": [{"product_code": "X-1"}]}
    stale, _ = is_audit_stale(audit_no_source)
    assert stale is True

    # Wrong _rows_source value → stale
    audit_wrong_source = {
        "_rows_source": "pz_engine_output",
        "rows": [{"product_code": "X-1"}],
    }
    stale2, _ = is_audit_stale(audit_wrong_source)
    assert stale2 is True


def test_legacy_v1_batch_2824221912_audit_is_flagged_stale():
    """Mimic the cached v1 audit.json shape from production storage —
    rows entry exists but lacks product_code / nazwa* fields."""
    legacy_rows = [
        {"invoice_number": "EJL/25-26/1247", "description": "Plain 9KT",
         "item_type": "RING", "quantity": 2, "unit_price": 313.0,
         "line_total": 626.0},
    ]
    audit = {"rows": legacy_rows}   # no row_schema_version → stale
    stale, _ = is_audit_stale(audit)
    assert stale is True
