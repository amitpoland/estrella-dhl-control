"""Shared Accounting Hub register paging contract tests."""
from app.services.accounting_register_paging import (
    enrich_years_available,
    paginate_rows,
    parse_register_paging,
    sort_rows_date_desc,
)


def test_default_year_is_current_and_limit_15():
    p = parse_register_paging(today=__import__("datetime").date(2026, 8, 10))
    assert p["page"] == 1
    assert p["limit"] == 15
    assert p["year"] == 2026
    assert p["date_from"] == "2026-01-01"
    assert p["date_to"] == "2026-12-31"
    assert p["sort"] == "date_desc"
    assert p["all_years"] is False


def test_all_years_clears_window():
    p = parse_register_paging(year="all", today=__import__("datetime").date(2026, 8, 10))
    assert p["year"] is None
    assert p["all_years"] is True
    assert p["date_from"] is None
    assert p["date_to"] is None


def test_year_2025_window():
    p = parse_register_paging(year="2025", page=2, limit=15)
    assert p["year"] == 2025
    assert p["date_from"] == "2025-01-01"
    assert p["date_to"] == "2025-12-31"
    assert p["page"] == 2
    assert p["start"] == 15


def test_sort_null_dates_last_and_latest_first():
    rows = [
        {"id": "1", "date": "2024-01-01"},
        {"id": "2", "date": ""},
        {"id": "3", "date": "2026-07-01"},
        {"id": "4", "date": None},
        {"id": "5", "date": "2026-08-01"},
    ]
    out = sort_rows_date_desc(rows)
    assert [r["id"] for r in out] == ["5", "3", "1", "2", "4"]


def test_paginate_no_duplicate_across_pages():
    rows = [{"id": str(i), "date": f"2026-01-{(i % 28) + 1:02d}"} for i in range(40)]
    sorted_rows = sort_rows_date_desc(rows)
    p1 = paginate_rows(sorted_rows, page=1, limit=15)
    p2 = paginate_rows(sorted_rows, page=2, limit=15)
    assert p1["count"] == 15
    assert p2["count"] == 15
    ids1 = {r["id"] for r in p1["rows"]}
    ids2 = {r["id"] for r in p2["rows"]}
    assert not (ids1 & ids2)
    assert p1["has_more"] is True
    assert p1["total_pages"] == 3


def test_enrich_years_merges_row_years():
    years = enrich_years_available([2026, 2025], [{"date": "2023-04-01"}, {"date": "bad"}])
    assert years[0] == 2026
    assert 2023 in years
