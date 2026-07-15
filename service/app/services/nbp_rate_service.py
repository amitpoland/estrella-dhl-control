"""nbp_rate_service.py — server-safe Proforma adapter over the PZ NBP service.

The ONE rate-fetch authority remains ``pz_import_processor.get_nbp_rate`` (the PZ
engine). This adapter does NOT reimplement it and adds NO second NBP client or
rate calculator — it CALLS the engine function and makes it safe to invoke from a
FastAPI request:

  * The engine falls back to ``input()`` when the live api.nbp.pl fetch fails; in
    a worker with an attached TTY that call would BLOCK the request. The adapter
    neutralises stdin for the duration so the fallback raises immediately, and
    converts it — together with RuntimeError / SystemExit / network / malformed
    response / missing rate — into a controlled :class:`NbpRateError`.
  * It NEVER returns a fabricated fallback rate. For a USD/EUR upstream failure it
    raises; it never silently returns 1.0.

Currency scope (PR-4): USD, EUR, PLN.
  * PLN is the identity rate (1.0, source "identity", no table).
  * USD / EUR are fetched from the engine.
  * Any other currency is a controlled unsupported-currency error.
"""
from __future__ import annotations

import io
import sys
import threading
from typing import Any, Dict

# Currencies the engine returns a live NBP rate for. PLN is handled as identity.
FETCH_CURRENCIES = ("USD", "EUR")
SUPPORTED_CURRENCIES = ("USD", "EUR", "PLN")


# Serialises the stdin swap in ``_call_engine``. Sync FastAPI endpoints run in a
# threadpool, so without this two concurrent fetches could interleave the
# save/restore and leave the process stdin pointing at another call's stream.
_STDIN_LOCK = threading.Lock()


class NbpRateError(Exception):
    """Controlled adapter failure.

    ``kind`` ∈ {"unsupported_currency", "upstream", "missing_rate"} — the route
    maps it to the appropriate HTTP status (422 / 502).
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


def _call_engine(accounting_date: str) -> Dict[str, Any]:
    """Invoke the sole PZ NBP authority with stdin neutralised, so its
    interactive fallback can never block or read a live terminal."""
    from pz_import_processor import get_nbp_rate  # the ONE authority — not reimplemented
    # Serialised: the stdin swap is a process-global side effect, so concurrent
    # fetches must not interleave the save/restore.
    with _STDIN_LOCK:
        saved_stdin = sys.stdin
        try:
            # An empty stream makes input() raise EOFError immediately, which the
            # engine converts to RuntimeError — caught below. No blocking, no prompt.
            sys.stdin = io.StringIO("")
            return get_nbp_rate(accounting_date)
        finally:
            sys.stdin = saved_stdin


def fetch_rate(currency: str, accounting_date: str) -> Dict[str, Any]:
    """Resolve the NBP (or identity) rate for *currency* keyed to *accounting_date*.

    Parameters
    ----------
    currency : str
        Draft currency (USD / EUR / PLN). Case-insensitive.
    accounting_date : str
        The accounting date the operator's proforma is keyed to ("YYYY-MM-DD" or
        "DD-MM-YYYY"). The engine selects the applicable prior NBP working-day
        table by its own rules; the returned ``table_date`` may differ from this.

    Returns
    -------
    dict
        ``{"rate": float, "source": "NBP"|"identity", "table_number": str|None,
           "table_date": str|None, "accounting_date": str, "currency": str}``

    Raises
    ------
    NbpRateError
        unsupported_currency — currency outside USD/EUR/PLN.
        upstream            — engine unavailable / malformed / no live table.
        missing_rate        — the live table has no rate for this currency.
    """
    ccy = str(currency or "").strip().upper()

    if ccy == "PLN":
        # Identity — an honest 1.0, NOT a failure fallback.
        return {
            "rate": 1.0, "source": "identity", "table_number": None,
            "table_date": None, "accounting_date": accounting_date, "currency": "PLN",
        }

    if ccy not in FETCH_CURRENCIES:
        raise NbpRateError(
            "unsupported_currency",
            f"NBP fetch supports USD, EUR and PLN only; {ccy or '(blank)'} is not supported",
        )

    try:
        res = _call_engine(accounting_date)
    except (RuntimeError, SystemExit) as exc:
        raise NbpRateError("upstream", f"NBP rate service unavailable: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — network / JSON / any engine error
        raise NbpRateError("upstream", f"NBP rate fetch failed: {exc}") from exc

    if not isinstance(res, dict):
        raise NbpRateError("upstream", "NBP service returned a malformed response")
    table_no = res.get("table_no")
    if table_no in (None, "", "MANUAL"):
        raise NbpRateError("upstream", "NBP service did not return a live table")

    raw = res.get("usd_rate") if ccy == "USD" else res.get("eur_rate")
    try:
        rate = float(raw or 0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate <= 0:
        # Never substitute 1.0 for a USD/EUR miss — surface it.
        raise NbpRateError("missing_rate", f"NBP table {table_no} has no {ccy} rate")

    return {
        "rate": rate,
        "source": "NBP",
        "table_number": str(table_no),
        "table_date": res.get("table_date"),
        "accounting_date": accounting_date,
        "currency": ccy,
    }
