"""Shared AR/AP wFirma fact-universe loader with in-flight coalesce + short TTL.

Read-only. Never a second accounting authority — only caches the same bulk
invoice/payment/expense XML→fact projections already used by Management
Analysis and Client/Supplier ledgers.

Process-local only (no cross-user disk, no auth principal in the value).
``force=True`` (Refresh) bypasses TTL and starts a new load; in-flight
callers for the same key still coalesce onto the newest load after eviction.

Timing fields on the payload (also surfaced via route ``query_stats``):
  wfirma_wait_ms   — sum of upstream HTTP round-trips (paginator)
  ej_normalize_ms  — Python date-filter + XML→fact parse
  ej_ms            — EJ work inside the loader (normalize only at this layer)
  duration_ms      — wall for the loader run (wfirma + normalize)
  *_page_wait_ms   — per-page upstream timings (capped)
On cache hit, this-request wait fields are zeroed; originals kept as
``cached_wfirma_wait_ms`` / ``cached_duration_ms``.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from . import wfirma_client
from .ledger_aggregator import (
    _parse_expense_fact,
    _parse_invoice_fact,
    _parse_payment_fact,
)

# Tens of seconds — bridges hub navigations; Refresh always bypasses.
DEFAULT_TTL_S = 30.0

# Fiscal AR document types for Client Ledger / Client Balance / Management
# Analysis. Proforma is commercial only — never part of this universe.
FISCAL_AR_INVOICE_TYPES: tuple = ("normal", "correction")
# Commercial override for rare non-fiscal registers (not Balance/Ledger/MA).
COMMERCIAL_AR_INVOICE_TYPES: tuple = ("normal", "correction", "proforma")

_lock = threading.Lock()
# key -> {"event": Event, "result": dict|None, "error": BaseException|None, "at": float}
_inflight: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
# key -> {"at": float, "payload": dict}
_cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}


def _python_filter_by_date(nodes, df: str, dt: str, date_tag: str = "date"):
    if not (df or dt):
        return list(nodes or [])
    out = []
    for n in nodes or []:
        d = (n.findtext(date_tag) or "").strip()
        if not d:
            out.append(n)
            continue
        if df and d < df:
            continue
        if dt and d > dt:
            continue
        out.append(n)
    return out


def clear_fact_universe_cache() -> None:
    """Test helper — drop settled cache entries (inflight left alone)."""
    with _lock:
        _cache.clear()


def _cache_get(key: Tuple[Any, ...], ttl_s: float) -> Optional[Dict[str, Any]]:
    hit = _cache.get(key)
    if not hit:
        return None
    if (time.monotonic() - float(hit["at"])) > ttl_s:
        _cache.pop(key, None)
        return None
    return hit["payload"]


def _mark_cache_hit(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Zero this-request wait; preserve original load cost under cached_*."""
    out = dict(payload)
    out["cache_hit"] = True
    out["coalesced"] = False
    out["cached_wfirma_wait_ms"] = int(out.get("wfirma_wait_ms") or 0)
    out["cached_duration_ms"] = int(out.get("duration_ms") or 0)
    out["wfirma_wait_ms"] = 0
    out["ej_normalize_ms"] = 0
    out["ej_ms"] = 0
    out["duration_ms"] = 0
    return out


def _sum_wait(stats: Dict[str, Any]) -> int:
    return int(stats.get("wfirma_wait_ms") or 0)


def _page_waits(stats: Dict[str, Any]) -> list:
    raw = stats.get("page_wait_ms") or []
    if not isinstance(raw, list):
        return []
    return [int(x) for x in raw[:40]]


def _load_or_coalesce(
    key: Tuple[Any, ...],
    loader: Callable[[], Dict[str, Any]],
    *,
    force: bool,
    ttl_s: float,
) -> Dict[str, Any]:
    """Return payload; coalesce concurrent identical keys onto one loader run."""
    with _lock:
        if force:
            _cache.pop(key, None)
        else:
            cached = _cache_get(key, ttl_s)
            if cached is not None:
                return _mark_cache_hit(cached)
        existing = _inflight.get(key)
        if existing is not None:
            waiter = existing
            is_leader = False
        else:
            waiter = {
                "event": threading.Event(),
                "result": None,
                "error": None,
                "at": time.monotonic(),
            }
            _inflight[key] = waiter
            is_leader = True

    if not is_leader:
        waiter["event"].wait(timeout=180)
        if waiter["error"] is not None:
            raise waiter["error"]
        if waiter["result"] is None:
            raise RuntimeError("fact-universe coalesce wait returned empty")
        out = dict(waiter["result"])
        out["cache_hit"] = False
        out["coalesced"] = True
        return out

    try:
        payload = loader()
        payload = dict(payload)
        payload["cache_hit"] = False
        payload["coalesced"] = False
        with _lock:
            _cache[key] = {"at": time.monotonic(), "payload": payload}
            waiter["result"] = payload
    except BaseException as exc:
        with _lock:
            waiter["error"] = exc
        raise
    finally:
        with _lock:
            _inflight.pop(key, None)
            waiter["event"].set()

    return dict(payload)


def load_ar_fact_universe(
    date_from: str,
    date_to: str,
    *,
    types: tuple = FISCAL_AR_INVOICE_TYPES,
    force: bool = False,
    ttl_s: float = DEFAULT_TTL_S,
) -> Dict[str, Any]:
    """Bulk fiscal invoices + payments for a window. Zero per-customer wFirma calls.

    Default ``types`` is :data:`FISCAL_AR_INVOICE_TYPES` (normal + correction).
    Proforma is excluded so Client Balance and Management Analysis cannot
    diverge into commercial AR. Pass ``COMMERCIAL_AR_INVOICE_TYPES`` only for
    an explicitly non-fiscal register.
    """
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if not df or not dt:
        raise ValueError("date_from and date_to are required")
    if df > dt:
        raise ValueError(f"date_from {df!r} is after date_to {dt!r}")
    if not isinstance(types, tuple) or not types:
        raise ValueError("types must be a non-empty tuple")

    key = ("ar", df, dt, types)

    def _loader() -> Dict[str, Any]:
        t0 = time.perf_counter()
        inv_stats: Dict[str, Any] = {}
        pay_stats: Dict[str, Any] = {}
        inv_nodes = wfirma_client.fetch_invoices_for_period(
            df, dt, types=types, stats=inv_stats
        )
        pay_nodes = wfirma_client.fetch_payments_for_period(df, dt, stats=pay_stats)
        wfirma_wait_ms = _sum_wait(inv_stats) + _sum_wait(pay_stats)
        t_n0 = time.perf_counter()
        inv_nodes = _python_filter_by_date(inv_nodes, df, dt, "date")
        pay_nodes = _python_filter_by_date(pay_nodes, df, dt, "date")
        invoice_facts = [_parse_invoice_fact(n) for n in inv_nodes]
        payment_facts = [_parse_payment_fact(n) for n in pay_nodes]
        ej_normalize_ms = int((time.perf_counter() - t_n0) * 1000)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "kind": "ar",
            "period": (df, dt),
            "invoice_facts": invoice_facts,
            "payment_facts": payment_facts,
            "inv_stats": inv_stats,
            "pay_stats": pay_stats,
            "duration_ms": duration_ms,
            "wfirma_wait_ms": wfirma_wait_ms,
            "ej_normalize_ms": ej_normalize_ms,
            "ej_ms": ej_normalize_ms,
            "inv_page_wait_ms": _page_waits(inv_stats),
            "pay_page_wait_ms": _page_waits(pay_stats),
            "per_customer_wfirma_calls": 0,
        }

    return _load_or_coalesce(key, _loader, force=force, ttl_s=ttl_s)


def load_ap_fact_universe(
    date_from: str,
    date_to: str,
    *,
    force: bool = False,
    ttl_s: float = DEFAULT_TTL_S,
) -> Dict[str, Any]:
    """Bulk expenses + payments for a window. Zero per-supplier wFirma calls."""
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if not df or not dt:
        raise ValueError("date_from and date_to are required")
    if df > dt:
        raise ValueError(f"date_from {df!r} is after date_to {dt!r}")

    key = ("ap", df, dt)

    def _loader() -> Dict[str, Any]:
        t0 = time.perf_counter()
        exp_stats: Dict[str, Any] = {}
        pay_stats: Dict[str, Any] = {}
        exp_nodes = wfirma_client.fetch_expenses_for_period(df, dt, stats=exp_stats)
        pay_nodes = wfirma_client.fetch_payments_for_period(df, dt, stats=pay_stats)
        wfirma_wait_ms = _sum_wait(exp_stats) + _sum_wait(pay_stats)
        t_n0 = time.perf_counter()
        exp_nodes = _python_filter_by_date(exp_nodes, df, dt, "date")
        pay_nodes = _python_filter_by_date(pay_nodes, df, dt, "date")
        expense_facts = [_parse_expense_fact(n) for n in exp_nodes]
        payment_facts = [_parse_payment_fact(n) for n in pay_nodes]
        ej_normalize_ms = int((time.perf_counter() - t_n0) * 1000)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "kind": "ap",
            "period": (df, dt),
            "expense_facts": expense_facts,
            "payment_facts": payment_facts,
            "exp_stats": exp_stats,
            "pay_stats": pay_stats,
            "duration_ms": duration_ms,
            "wfirma_wait_ms": wfirma_wait_ms,
            "ej_normalize_ms": ej_normalize_ms,
            "ej_ms": ej_normalize_ms,
            "exp_page_wait_ms": _page_waits(exp_stats),
            "pay_page_wait_ms": _page_waits(pay_stats),
            "per_supplier_wfirma_calls": 0,
        }

    return _load_or_coalesce(key, _loader, force=force, ttl_s=ttl_s)


def timing_fields_from_universe(uni: Dict[str, Any]) -> Dict[str, Any]:
    """Compact timing block for route/analytics ``query_stats``."""
    out: Dict[str, Any] = {
        "wfirma_wait_ms": int(uni.get("wfirma_wait_ms") or 0),
        "ej_normalize_ms": int(uni.get("ej_normalize_ms") or 0),
        "ej_ms": int(uni.get("ej_ms") or 0),
        "duration_ms": int(uni.get("duration_ms") or 0),
    }
    if uni.get("inv_page_wait_ms") is not None:
        out["inv_page_wait_ms"] = list(uni.get("inv_page_wait_ms") or [])
    if uni.get("exp_page_wait_ms") is not None:
        out["exp_page_wait_ms"] = list(uni.get("exp_page_wait_ms") or [])
    if uni.get("pay_page_wait_ms") is not None:
        out["pay_page_wait_ms"] = list(uni.get("pay_page_wait_ms") or [])
    if "cached_wfirma_wait_ms" in uni:
        out["cached_wfirma_wait_ms"] = int(uni.get("cached_wfirma_wait_ms") or 0)
    if "cached_duration_ms" in uni:
        out["cached_duration_ms"] = int(uni.get("cached_duration_ms") or 0)
    return out


__all__ = [
    "DEFAULT_TTL_S",
    "FISCAL_AR_INVOICE_TYPES",
    "COMMERCIAL_AR_INVOICE_TYPES",
    "clear_fact_universe_cache",
    "load_ar_fact_universe",
    "load_ap_fact_universe",
    "timing_fields_from_universe",
]
