"""
routes_carrier_shadow.py — Read-only HTTP endpoints over the DHL
shadow-mode log store.

DL-F2.5 scope
-------------
* Two GET endpoints under ``/api/v1/carrier/shadow``.
* Router-level API-key dependency. Mirrors the auth pattern used by
  the cowork action-proposal pipeline. (Read-only carrier routes
  proper are auth-open by current convention; the shadow log
  exposes carrier traffic patterns and is admin-only.)
* No POST / PUT / PATCH / DELETE.
* No carrier-adapter imports. No coordinator imports. No outbound
  HTTP. No write-helper imports from the shadow-store module —
  ``record_call_outcome``, ``compute_request_hash``, ``init_db`` are
  deliberately absent.
* Response rows are projected through an explicit allowlist of
  documented column names — a future schema column does NOT
  auto-leak into the dashboard.

Endpoints
---------
  GET /api/v1/carrier/shadow/recent
  GET /api/v1/carrier/shadow/summary
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.security import require_api_key
from ..services.carrier.adapters.dhl_shadow_db import (
    _VALID_DIFF_OUTCOMES,
    count_total,
    list_recent,
    summarise_last_n_days,
)


# Router-level auth — every endpoint under /shadow is protected.
_auth = Depends(require_api_key)
router = APIRouter(
    prefix       = "/api/v1/carrier/shadow",
    tags         = ["carrier"],
    dependencies = [_auth],
)


# ── Validation sets ────────────────────────────────────────────────────────

#: The four method names recognised by the shadow adapter / DB writes.
#: Operator queries outside this set are rejected with HTTP 400.
_KNOWN_METHODS = frozenset({
    "create_shipment",
    "cancel_shipment",
    "fetch_label",
    "schedule_pickup",
})


#: Columns the dashboard receives. Anything in the DB row outside
#: this allowlist is dropped by ``_project_row``. A future schema
#: column (e.g. a hashed PII field) is therefore NOT auto-exposed
#: until DL-F2.5 is updated to include it.
_ROW_KEY_ALLOWLIST: Tuple[str, ...] = (
    "id",
    "method",
    "request_hash",
    "actor",
    "stub_status",
    "stub_awb",
    "stub_label_format",
    "stub_label_size",
    "stub_error_class",
    "stub_error_summary",
    "live_status",
    "live_awb",
    "live_label_format",
    "live_label_size",
    "live_http_status",
    "live_error_class",
    "live_error_summary",
    "live_duration_ms",
    "diff_outcome",
    "diff_notes",
    "created_at",
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _project_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Pin the response shape to the allowlisted column set."""
    return {k: row.get(k) for k in _ROW_KEY_ALLOWLIST}


def _validate_method(value: Optional[str]) -> Optional[str]:
    """Validate a ``method`` query param. Returns the canonical value
    or None when absent. Raises HTTPException 400 on unknown."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned not in _KNOWN_METHODS:
        raise HTTPException(status_code=400, detail={
            "code":  "invalid_method",
            "error": (
                f"method {cleaned!r} is not recognised; "
                f"valid values are {sorted(_KNOWN_METHODS)}"
            ),
        })
    return cleaned


def _validate_diff(value: Optional[str]) -> Optional[str]:
    """Validate a ``diff`` query param against the shadow-store's
    allowlist. Returns the canonical value or None when absent.
    Raises HTTPException 400 on unknown."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned not in _VALID_DIFF_OUTCOMES:
        raise HTTPException(status_code=400, detail={
            "code":  "invalid_diff",
            "error": (
                f"diff {cleaned!r} is not recognised; "
                f"valid values are {sorted(_VALID_DIFF_OUTCOMES)}"
            ),
        })
    return cleaned


def _safe_count_total() -> int:
    """``count_total`` raises if the shadow store has not been
    initialised (production main.py initialises in lifespan; tests
    initialise per fixture). Returning 0 in that uninit case keeps
    the endpoint useful in dev installs that have not configured
    the carrier path."""
    try:
        return int(count_total())
    except Exception:
        return 0


def _safe_list_recent(
    *,
    method:        Optional[str],
    diff_outcome:  Optional[str],
    limit:         int,
) -> List[Dict[str, Any]]:
    """Wrap the store call so an uninitialised DB does not 5xx the
    dashboard. Returns an empty list in that case."""
    try:
        return list_recent(
            method       = method,
            diff_outcome = diff_outcome,
            limit        = limit,
        )
    except Exception:
        return []


def _safe_summary(days: int) -> List[Dict[str, Any]]:
    try:
        return summarise_last_n_days(days)
    except Exception:
        return []


# ── 1. GET /recent ─────────────────────────────────────────────────────────

@router.get("/recent")
def recent_shadow_rows(
    method: Optional[str] = Query(default=None,
                                   description="Filter to one method"),
    diff:   Optional[str] = Query(default=None,
                                   description="Filter to one diff_outcome"),
    limit:  int = Query(default=100, ge=1, le=500),
) -> Dict[str, Any]:
    """Most-recent shadow-log rows, newest first.

    Empty store returns 200 with ``{"rows": [], "count": 0, ...}``.
    Filters are AND-combined; an unknown ``method`` or ``diff`` value
    returns HTTP 400 with ``code: "invalid_method"`` /
    ``code: "invalid_diff"``.
    """
    method_v = _validate_method(method)
    diff_v   = _validate_diff(diff)

    rows = _safe_list_recent(
        method       = method_v,
        diff_outcome = diff_v,
        limit        = limit,
    )
    projected = [_project_row(r) for r in rows]

    return {
        "filters": {
            "method": method_v,
            "diff":   diff_v,
            "limit":  limit,
        },
        "count": len(projected),
        "rows":  projected,
    }


# ── 2. GET /summary ────────────────────────────────────────────────────────

@router.get("/summary")
def shadow_summary(
    days: int = Query(default=7, ge=1, le=90),
) -> Dict[str, Any]:
    """Counts grouped by ``(method, diff_outcome)`` for the last
    ``days`` days. Buckets are pre-sorted by count desc by the store.

    Returns lifetime row count alongside the windowed total so the
    dashboard can show both.
    """
    buckets = _safe_summary(days)
    total_window = sum(int(b.get("count") or 0) for b in buckets)
    return {
        "days":                days,
        "total_rows_window":   total_window,
        "total_rows_lifetime": _safe_count_total(),
        "buckets":             list(buckets),
    }
