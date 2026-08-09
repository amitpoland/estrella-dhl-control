"""Shared Accounting Hub register paging contract.

Authority: backend query contract for year + page + limit + sort=date_desc.
Frontend consumes only — must not slice a full-history payload.

Defaults:
  page=1 (1-indexed), limit=15, sort=date_desc, year=current calendar year
  year="" / "all" → All Years (no date window)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_PAGE_LIMIT = 15
MAX_PAGE_LIMIT = 200
SORT_DATE_DESC = "date_desc"


def current_default_year(today: Optional[date] = None) -> int:
    return (today or date.today()).year


def parse_register_paging(
    *,
    page: Optional[int] = None,
    limit: Optional[int] = None,
    year: Optional[str] = None,
    sort: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Normalize query params into a paging DTO.

    *year*:
      - omitted / None → default current calendar year
      - "all" / "" / "0" → All Years (no year window)
      - "2026" → that calendar year
    Explicit date_from/date_to override year window when both provided.
    """
    today_d = today or date.today()
    try:
        page_i = max(1, int(page) if page is not None else 1)
    except (TypeError, ValueError):
        page_i = 1
    try:
        limit_i = int(limit) if limit is not None else DEFAULT_PAGE_LIMIT
    except (TypeError, ValueError):
        limit_i = DEFAULT_PAGE_LIMIT
    limit_i = max(1, min(limit_i, MAX_PAGE_LIMIT))

    sort_s = (sort or SORT_DATE_DESC).strip().lower()
    if sort_s not in (SORT_DATE_DESC,):
        sort_s = SORT_DATE_DESC

    y_raw = None if year is None else str(year).strip().lower()
    all_years = y_raw in ("all", "", "0", "*")
    year_i: Optional[int] = None
    if not all_years:
        if y_raw is None:
            year_i = today_d.year
        else:
            try:
                year_i = int(y_raw)
            except ValueError:
                year_i = today_d.year
            if year_i < 1990 or year_i > today_d.year + 1:
                year_i = today_d.year

    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if df and dt and df <= dt:
        # explicit range wins
        pass
    elif year_i is not None:
        df = f"{year_i:04d}-01-01"
        dt = f"{year_i:04d}-12-31"
    else:
        df, dt = "", ""

    start = (page_i - 1) * limit_i
    years_available = list(range(today_d.year, today_d.year - 11, -1))
    return {
        "page": page_i,
        "limit": limit_i,
        "start": start,
        "sort": sort_s,
        "year": year_i,  # None ⇒ All Years
        "date_from": df or None,
        "date_to": dt or None,
        "years_available": years_available,
        "all_years": year_i is None,
    }


def order_xml_date_desc() -> str:
    """wFirma find order fragment — newest document date first."""
    return "<order><desc>date</desc></order>"


def date_window_conditions_xml(date_from: Optional[str], date_to: Optional[str]) -> str:
    parts: List[str] = []
    if date_from:
        parts.append(
            f"<condition><field>date</field>"
            f"<operator>ge</operator><value>{_esc(date_from)}</value></condition>"
        )
    if date_to:
        parts.append(
            f"<condition><field>date</field>"
            f"<operator>le</operator><value>{_esc(date_to)}</value></condition>"
        )
    return "".join(parts)


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _parse_date_key(value: Any) -> Tuple[int, str]:
    """Sort key: dated rows first (desc), undated last.

    Returns (tier, key) where tier 0 = valid date, tier 1 = missing/invalid.
    Within tier 0, lexicographic ISO date DESC via reverse sort on key.
    """
    s = (str(value) if value is not None else "").strip()
    if len(s) >= 10:
        chunk = s[:10]
        try:
            datetime.strptime(chunk, "%Y-%m-%d")
            return (0, chunk)
        except ValueError:
            pass
    return (1, "")


def sort_rows_date_desc(rows: Sequence[Dict[str, Any]], date_field: str = "date") -> List[Dict[str, Any]]:
    """Stable latest-first sort; null/invalid dates last."""
    dated = [r for r in rows if _parse_date_key(r.get(date_field))[0] == 0]
    undated = [r for r in rows if _parse_date_key(r.get(date_field))[0] == 1]
    dated.sort(key=lambda r: _parse_date_key(r.get(date_field))[1], reverse=True)
    return dated + undated


def paginate_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    page: int,
    limit: int,
) -> Dict[str, Any]:
    """Slice an already-sorted list. Totals stay with the caller."""
    page_i = max(1, int(page))
    limit_i = max(1, int(limit))
    start = (page_i - 1) * limit_i
    total = len(rows)
    slice_rows = list(rows[start : start + limit_i])
    total_pages = max(1, (total + limit_i - 1) // limit_i) if total else 1
    return {
        "rows": slice_rows,
        "count": len(slice_rows),
        "page": page_i,
        "limit": limit_i,
        "total_count": total,
        "total_pages": total_pages,
        "has_more": start + limit_i < total,
    }


def enrich_years_available(
    base_years: Sequence[int], rows: Sequence[Dict[str, Any]], date_field: str = "date"
) -> List[int]:
    seen = set(int(y) for y in base_years)
    for r in rows:
        key = _parse_date_key(r.get(date_field))
        if key[0] == 0 and len(key[1]) >= 4:
            try:
                seen.add(int(key[1][:4]))
            except ValueError:
                pass
    return sorted(seen, reverse=True)
