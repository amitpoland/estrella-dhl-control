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


def test_empty_audit_is_stale():
    assert is_audit_stale({})[0] is True
    assert is_audit_stale(None)[0] is True


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
