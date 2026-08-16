"""india_official_fx.py — India Official Reference FX Authority.

ONE business authority: *the official India reference rate for FCY/INR*.

RBI and FBIL are **publication surfaces of the same authority**, not two
competing authorities:

* Until 2018-07-09 the Reserve Bank of India computed and published the
  reference rate itself.
* Effective **2018-07-10** FBIL (Financial Benchmarks India Pvt. Ltd.) took
  over computation and publication of the USD/INR, EUR/INR, GBP/INR and
  JPY/INR reference rates (AED and IDR were added later), published on Mumbai
  business days at ~13:30 IST.
* RBI continues to publish the *same* FBIL-computed numbers in its Reference
  Rate Archive, and that archive is the surface that carries the full history
  across the 2018 handover.

Transport decision (measured 2026-08-16, this host)
---------------------------------------------------
Two official surfaces were probed live:

* ``https://www.fbil.org.in/wasdm/refrates/fetchfiltered`` — official JSON,
  unauthenticated, history from 2018-07-10. **Lags**: on 2026-08-16 its most
  recent publication was 2026-08-07, i.e. five business days behind.
* ``https://www.rbi.org.in/scripts/referenceratearchive.aspx`` — official RBI
  archive. Current (carried 2026-08-14 on 2026-08-16), covers the pre-2018
  RBI era, and declares the quotation unit in its own table header
  (``USD (INR / 1 USD)``, ``JPY (INR / 100 JPY)``, ``IDR (INR / 10000 IDR)``).

The RBI archive is therefore the transport: it is the only official surface
that is both current and historically complete. Where the two overlap they
agree exactly (2026-08-07 USD 95.2135 on both). FBIL is **not** wired in as a
runtime fallback — there is exactly one transport, so no report-time
dual-source fallback can exist.

Orientation
-----------
Rates are stored and returned as **INR per 1 unit of the foreign currency**.
The quotation unit is never hardcoded: it is parsed out of the RBI table
header for every fetch, and a header that cannot be parsed fails closed with
``rate_orientation_invalid``.

Date rule (operator-approved)
-----------------------------
``requested_rate_date = invoice_issue_date - 1 calendar day``, then the latest
official publication **on or before** that date. Never forward, never a
publication dated on or after the invoice date, never today's rate for a
historical invoice. The weekend / Mumbai-holiday backward walk lives here, in
the authority — never in a caller and never in the UI.

Currencies
----------
Only currencies the authority actually publishes are supported. **PLN is not
published by RBI/FBIL, so PLN→INR fails closed** (``unsupported_currency``).
No cross-rate is invented, and NBP — the Polish accounting authority — is
never consulted here.

That refusal is scoped to *this* module and is unchanged. Since the operator
ruling of 2026-08-16 the PLN cross rate is assembled one layer up, at the FX
boundary (``insurance_fx_provider``), out of this authority's **USD** quote and
NBP's Table A PLN-per-USD mid. This module still answers only for what RBI
publishes, and no rate is ever combined here.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..core.config import settings

logger = logging.getLogger("pz.india_official_fx")

SOURCE_RBI_ARCHIVE = "rbi_reference_rate_archive"

RBI_ARCHIVE_URL = "https://www.rbi.org.in/scripts/referenceratearchive.aspx"

# Widest window verified complete against the live archive (a full calendar
# year returns every published business day: 2015 → 241 rows, 2025 → 243).
# Wider spans are silently truncated by the archive, so never exceed this.
MAX_FETCH_WINDOW_DAYS = 365

# Backward walk budget. 45 days comfortably clears the longest Mumbai bank
# holiday cluster; beyond it the rate is treated as unpublished, not stale.
LOOKBACK_DAYS = 45

_HTTP_TIMEOUT = 90

# "USD (INR / 1 USD)" / "JPY (INR / 100 JPY)" / "IDR (INR / 10000 IDR)"
_HEADER_RE = re.compile(
    r"<b>\s*([A-Z]{3})\s*\(\s*INR\s*/\s*(\d+)\s*([A-Z]{3})\s*\)\s*</b>",
    re.IGNORECASE,
)
_ROW_RE = re.compile(
    r"<tr>\s*<td[^>]*>\s*(\d{2}/\d{2}/\d{4})\s*</td>(.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)
_CELL_RE = re.compile(r"<td[^>]*>\s*([^<]*?)\s*</td>", re.IGNORECASE)
_HIDDEN_RE = re.compile(
    r'<input type="hidden" name="(__[A-Z]+)"[^>]*value="([^"]*)"'
)


class OfficialFxError(Exception):
    """Controlled failure of the India Official Reference FX Authority.

    ``kind`` is the structured taxonomy the caller maps to a row-level
    NEEDS REVIEW state — never a 500, never a substituted rate:

    ``unsupported_currency``     — the authority does not publish this currency
    ``historical_rate_unavailable`` — requested date precedes published history
    ``official_rate_not_published`` — no publication on or before the date
    ``provider_transport_error`` — network / HTTP failure reaching the source
    ``provider_payload_invalid`` — response was not the expected archive table
    ``rate_orientation_invalid`` — quotation unit could not be established
    ``official_rate_conflict``   — source contradicts an already-stored rate
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


# ── cache (this module owns india_official_fx.db) ─────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS official_reference_rate (
    effective_date     TEXT NOT NULL,   -- YYYY-MM-DD, the publication date
    currency           TEXT NOT NULL,   -- ISO 4217
    rate_inr_per_unit  TEXT NOT NULL,   -- Decimal as text — never a float
    quote_unit         INTEGER NOT NULL,-- as published (1 / 100 / 10000)
    rate_as_published  TEXT NOT NULL,   -- untouched source value
    source             TEXT NOT NULL,
    fetched_at         TEXT NOT NULL,
    PRIMARY KEY (effective_date, currency)
);
CREATE TABLE IF NOT EXISTS official_reference_coverage (
    from_date  TEXT NOT NULL,
    to_date    TEXT NOT NULL,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""


def db_path() -> Path:
    return Path(settings.storage_root) / "india_official_fx.db"


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_DDL)
    return conn


def _iso(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _parse_iso(value: str) -> date:
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise OfficialFxError(
            "provider_payload_invalid", "Invalid ISO date %r" % value
        )


def _covered(conn: sqlite3.Connection, day: date) -> bool:
    iso = _iso(day)
    row = conn.execute(
        "SELECT 1 FROM official_reference_coverage "
        "WHERE from_date <= ? AND to_date >= ? LIMIT 1",
        (iso, iso),
    ).fetchone()
    return row is not None


def _lookup(
    conn: sqlite3.Connection, currency: str, not_after: date, not_before: date
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM official_reference_rate "
        "WHERE currency = ? AND effective_date <= ? AND effective_date >= ? "
        "ORDER BY effective_date DESC LIMIT 1",
        (currency, _iso(not_after), _iso(not_before)),
    ).fetchone()


def _store(conn: sqlite3.Connection, rows: List[Dict[str, object]]) -> Tuple[int, int]:
    """Insert published rates idempotently.

    An already-stored rate is never overwritten. A source value that
    contradicts a stored one is a hard conflict — issued financial evidence is
    not silently rewritten.
    """
    fetched_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    inserted = 0
    unchanged = 0
    for row in rows:
        existing = conn.execute(
            "SELECT rate_inr_per_unit FROM official_reference_rate "
            "WHERE effective_date = ? AND currency = ?",
            (row["effective_date"], row["currency"]),
        ).fetchone()
        if existing is not None:
            if Decimal(existing["rate_inr_per_unit"]) != row["rate_inr_per_unit"]:
                raise OfficialFxError(
                    "official_rate_conflict",
                    "Official %s rate for %s changed: stored %s, source now %s "
                    "— refusing to overwrite stored financial evidence"
                    % (
                        row["currency"],
                        row["effective_date"],
                        existing["rate_inr_per_unit"],
                        row["rate_inr_per_unit"],
                    ),
                )
            unchanged += 1
            continue
        conn.execute(
            "INSERT INTO official_reference_rate "
            "(effective_date, currency, rate_inr_per_unit, quote_unit, "
            " rate_as_published, source, fetched_at) VALUES (?,?,?,?,?,?,?)",
            (
                row["effective_date"],
                row["currency"],
                str(row["rate_inr_per_unit"]),
                int(row["quote_unit"]),
                str(row["rate_as_published"]),
                SOURCE_RBI_ARCHIVE,
                fetched_at,
            ),
        )
        inserted += 1
    return inserted, unchanged


def _record_coverage(conn: sqlite3.Connection, start: date, end: date) -> None:
    conn.execute(
        "INSERT INTO official_reference_coverage "
        "(from_date, to_date, source, fetched_at) VALUES (?,?,?,?)",
        (
            _iso(start),
            _iso(end),
            SOURCE_RBI_ARCHIVE,
            datetime.utcnow().isoformat(timespec="seconds") + "Z",
        ),
    )


# ── transport (RBI Reference Rate Archive) ────────────────────────────────────


def _parse_archive(html: str) -> List[Dict[str, object]]:
    """Parse the RBI archive table into per-currency published rates.

    The quotation unit comes from the table header, never from a hardcoded
    table — a header that cannot be read fails closed.
    """
    headers = _HEADER_RE.findall(html or "")
    if not headers:
        raise OfficialFxError(
            "provider_payload_invalid",
            "RBI reference rate archive returned no recognisable rate table",
        )

    columns: List[Tuple[str, int]] = []
    for code, unit, unit_code in headers:
        if code.upper() != unit_code.upper():
            raise OfficialFxError(
                "rate_orientation_invalid",
                "RBI header column %r declares quotation in %r — orientation "
                "could not be established" % (code, unit_code),
            )
        try:
            quote_unit = int(unit)
        except ValueError:
            raise OfficialFxError(
                "rate_orientation_invalid",
                "RBI header column %r has a non-numeric quotation unit %r"
                % (code, unit),
            )
        if quote_unit <= 0:
            raise OfficialFxError(
                "rate_orientation_invalid",
                "RBI header column %r declares quotation unit %d" % (code, quote_unit),
            )
        columns.append((code.upper(), quote_unit))

    out: List[Dict[str, object]] = []
    for match in _ROW_RE.finditer(html):
        try:
            day = datetime.strptime(match.group(1), "%d/%m/%Y").date()
        except ValueError:
            continue
        cells = [c.strip() for c in _CELL_RE.findall(match.group(2))]
        if len(cells) < len(columns):
            continue
        for (code, quote_unit), raw in zip(columns, cells):
            if not raw or raw in {"-", "--", "NA", "N.A."}:
                continue
            try:
                published = Decimal(raw.replace(",", ""))
            except InvalidOperation:
                continue
            if published <= 0:
                continue
            out.append(
                {
                    "effective_date": _iso(day),
                    "currency": code,
                    "rate_inr_per_unit": published / Decimal(quote_unit),
                    "quote_unit": quote_unit,
                    "rate_as_published": raw,
                }
            )
    return out


def _fetch_window(start: date, end: date) -> List[Dict[str, object]]:
    """Fetch one published window from the RBI archive (read-only)."""
    if (end - start).days > MAX_FETCH_WINDOW_DAYS:
        raise OfficialFxError(
            "provider_payload_invalid",
            "Fetch window %s..%s exceeds the %d-day limit the archive returns "
            "completely" % (_iso(start), _iso(end), MAX_FETCH_WINDOW_DAYS),
        )
    import requests  # local import: keeps module import side-effect free

    try:
        session = requests.Session()
        page = session.get(RBI_ARCHIVE_URL, timeout=_HTTP_TIMEOUT)
        page.raise_for_status()
        form = {name: value for name, value in _HIDDEN_RE.findall(page.text)}
        form.update(
            {
                "txtFromDate": start.strftime("%d/%m/%Y"),
                "txtToDate": end.strftime("%d/%m/%Y"),
                "chkAll": "on",
                "btnSubmit": " GO ",
            }
        )
        result = session.post(RBI_ARCHIVE_URL, data=form, timeout=_HTTP_TIMEOUT)
        result.raise_for_status()
    except OfficialFxError:
        raise
    except Exception as exc:  # noqa: BLE001 — any transport failure
        raise OfficialFxError(
            "provider_transport_error",
            "RBI reference rate archive unreachable: %s" % exc,
        )
    return _parse_archive(result.text)


# ── authority ─────────────────────────────────────────────────────────────────


def published_currencies() -> List[str]:
    """Currencies present in the local cache (what the authority publishes)."""
    with closing(_connect()) as conn:
        return [
            r["currency"]
            for r in conn.execute(
                "SELECT DISTINCT currency FROM official_reference_rate "
                "ORDER BY currency"
            )
        ]


def resolve_for_invoice_date(currency: str, invoice_date: str) -> Dict[str, object]:
    """Official INR rate for ``currency`` applicable to ``invoice_date``.

    Applies the approved date rule: invoice date minus one calendar day, then
    the latest official publication on or before that date. Returns::

        {"currency", "rate" (Decimal, INR per 1 unit), "requested_date",
         "effective_date", "staleness_days", "quote_unit",
         "rate_as_published", "source"}

    Raises :class:`OfficialFxError` — never returns a substituted or invented
    rate.
    """
    ccy = (currency or "").strip().upper()
    if not ccy:
        raise OfficialFxError("unsupported_currency", "Currency missing")
    if ccy == "INR":
        raise OfficialFxError(
            "unsupported_currency",
            "INR is the target currency — no reference rate applies",
        )

    invoice_day = _parse_iso(invoice_date)
    requested = invoice_day - timedelta(days=1)
    floor = requested - timedelta(days=LOOKBACK_DAYS)

    with closing(_connect()) as conn:
        if not _covered(conn, requested):
            window_start = max(floor, requested - timedelta(days=MAX_FETCH_WINDOW_DAYS))
            fetched = _fetch_window(window_start, requested)
            if not fetched:
                raise OfficialFxError(
                    "official_rate_not_published",
                    "No official India reference rate published between %s and "
                    "%s" % (_iso(window_start), _iso(requested)),
                )
            _store(conn, fetched)
            _record_coverage(conn, window_start, requested)
            conn.commit()

        row = _lookup(conn, ccy, requested, floor)
        if row is None:
            available = {
                r["currency"]
                for r in conn.execute(
                    "SELECT DISTINCT currency FROM official_reference_rate"
                )
            }
            if available and ccy not in available:
                raise OfficialFxError(
                    "unsupported_currency",
                    "The India official reference rate authority does not "
                    "publish %s (published: %s) — no cross-rate is invented"
                    % (ccy, ", ".join(sorted(available))),
                )
            oldest = conn.execute(
                "SELECT MIN(effective_date) AS d FROM official_reference_rate "
                "WHERE currency = ?",
                (ccy,),
            ).fetchone()
            if oldest and oldest["d"] and _iso(requested) < oldest["d"]:
                raise OfficialFxError(
                    "historical_rate_unavailable",
                    "Official %s rate for %s precedes published history "
                    "(earliest %s)" % (ccy, _iso(requested), oldest["d"]),
                )
            raise OfficialFxError(
                "official_rate_not_published",
                "No official %s reference rate published on or before %s "
                "(searched back to %s)" % (ccy, _iso(requested), _iso(floor)),
            )

    effective = _parse_iso(row["effective_date"])
    return {
        "currency": ccy,
        "rate": Decimal(row["rate_inr_per_unit"]),
        "requested_date": _iso(requested),
        "effective_date": row["effective_date"],
        "staleness_days": (requested - effective).days,
        "quote_unit": int(row["quote_unit"]),
        "rate_as_published": row["rate_as_published"],
        "source": row["source"],
    }


def backfill(from_date: str, to_date: str) -> Dict[str, object]:
    """Populate the cache for a date range, one <=365-day window at a time.

    Read-only against the source, idempotent against the cache: re-running
    inserts nothing and raises ``official_rate_conflict`` if the source ever
    contradicts a stored rate. Never invoked at startup.
    """
    start = _parse_iso(from_date)
    end = _parse_iso(to_date)
    if start > end:
        raise OfficialFxError(
            "provider_payload_invalid", "from_date %s is after to_date %s" % (start, end)
        )

    windows = 0
    inserted = 0
    unchanged = 0
    with closing(_connect()) as conn:
        cursor = start
        while cursor <= end:
            window_end = min(end, cursor + timedelta(days=MAX_FETCH_WINDOW_DAYS))
            rows = _fetch_window(cursor, window_end)
            added, kept = _store(conn, rows)
            _record_coverage(conn, cursor, window_end)
            conn.commit()
            windows += 1
            inserted += added
            unchanged += kept
            cursor = window_end + timedelta(days=1)
        currencies = [
            r["currency"]
            for r in conn.execute(
                "SELECT DISTINCT currency FROM official_reference_rate ORDER BY currency"
            )
        ]
        span = conn.execute(
            "SELECT MIN(effective_date) AS lo, MAX(effective_date) AS hi "
            "FROM official_reference_rate"
        ).fetchone()

    return {
        "from_date": _iso(start),
        "to_date": _iso(end),
        "windows": windows,
        "inserted": inserted,
        "already_present": unchanged,
        "currencies": currencies,
        "cached_from": span["lo"] if span else None,
        "cached_to": span["hi"] if span else None,
        "source": SOURCE_RBI_ARCHIVE,
    }


__all__ = [
    "OfficialFxError",
    "SOURCE_RBI_ARCHIVE",
    "backfill",
    "db_path",
    "published_currencies",
    "resolve_for_invoice_date",
]
