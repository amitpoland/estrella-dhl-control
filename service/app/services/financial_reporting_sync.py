"""financial_reporting_sync.py — scheduled AR/AP reporting projection sync.

ONE shared incremental capability per stream for local
``financial_reporting.sqlite``. Reuses ``app.tools.sync_financial_reporting``
(``sync_ar`` / ``sync_ap`` — same upsert paths as the CLI backfill). Callers:

  * ``wfirma_webhook_scheduler._run_ar_reporting_sync_tick`` (automation)
  * ``wfirma_webhook_scheduler._run_ap_reporting_sync_tick`` (automation)
  * operator CLI ``python -m app.tools.sync_financial_reporting``
    (full/backfill windows — unchanged)

Safety
------
  * wFirma is READ-ONLY (``expenses/find``).
  * Writes ONLY to ``financial_reporting.sqlite`` via existing upserts.
  * Never touches ``payment_state.db``, knock-off, or financial formulas.
  * Never triggered from CFO/MA page requests.
  * Idempotent: upsert by expense_id; duplicate runs do not duplicate rows.
  * Transient failures: status=error recorded; watermark not advanced; next
    due tick retries.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.logging import get_logger
from .financial_reporting_db import get_sync_state, reporting_db_path
from .local_fact_universe import FRESHNESS_MAX_AGE_HOURS

log = get_logger(__name__)

#: How often the scheduler may call wFirma for a portfolio expense window.
DEFAULT_COOLDOWN_SECONDS = 3600

#: After a failed tick, wait this long before retrying (avoids 30s hammering).
DEFAULT_ERROR_RETRY_SECONDS = 300

#: Re-fetch this many days before the last watermark so late-created documents
#: with earlier issue dates (the 2026-08-10 Estrella LLP lag class) are caught.
DEFAULT_OVERLAP_DAYS = 14

#: When no watermark exists yet, first automated tick uses a bounded lookback
#: (full historical backfill remains the CLI).
DEFAULT_LOOKBACK_DAYS = 30

STREAM_AP = "ap_expenses"
STREAM_AR = "ar_invoices"

#: ``last_reconcile_at`` on each stream = last attempt (success or failure).
#: Distinct from ``last_incremental_at`` (last successful sync).


def _parse_iso(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _today_utc(now: Optional[datetime] = None) -> date:
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.astimezone(timezone.utc).date()


def resolve_incremental_window(
    *,
    watermark: Optional[str],
    today: Optional[date] = None,
    overlap_days: int = DEFAULT_OVERLAP_DAYS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[str, str]:
    """Bounded fetch window from last watermark (with overlap) or lookback."""
    end = today or _today_utc()
    date_to = end.isoformat()
    wm = (watermark or "").strip()[:10]
    if len(wm) == 10 and wm[4] == "-" and wm[7] == "-":
        try:
            wm_d = date.fromisoformat(wm)
        except ValueError:
            wm_d = None
        if wm_d is not None:
            start = wm_d - timedelta(days=max(0, int(overlap_days)))
            if start > end:
                start = end
            return start.isoformat(), date_to
    start = end - timedelta(days=max(1, int(lookback_days)))
    return start.isoformat(), date_to


def is_sync_due(
    db_path: Path,
    stream: str,
    *,
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    error_retry_seconds: int = DEFAULT_ERROR_RETRY_SECONDS,
    now: Optional[datetime] = None,
) -> bool:
    """True when success-cooldown or error-retry window has elapsed."""
    st = get_sync_state(db_path, stream) or {}
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)

    if (st.get("status") or "").strip().lower() == "error":
        last_attempt = _parse_iso(st.get("last_reconcile_at")) or _parse_iso(
            st.get("last_incremental_at")
        )
        if last_attempt is None:
            return True
        return (n - last_attempt).total_seconds() >= float(error_retry_seconds)

    last = _parse_iso(st.get("last_incremental_at"))
    if last is None:
        return True
    return (n - last).total_seconds() >= float(cooldown_seconds)


def is_ap_sync_due(
    db_path: Path,
    *,
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    error_retry_seconds: int = DEFAULT_ERROR_RETRY_SECONDS,
    now: Optional[datetime] = None,
) -> bool:
    return is_sync_due(
        db_path,
        STREAM_AP,
        cooldown_seconds=cooldown_seconds,
        error_retry_seconds=error_retry_seconds,
        now=now,
    )


def is_ar_sync_due(
    db_path: Path,
    *,
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    error_retry_seconds: int = DEFAULT_ERROR_RETRY_SECONDS,
    now: Optional[datetime] = None,
) -> bool:
    return is_sync_due(
        db_path,
        STREAM_AR,
        cooldown_seconds=cooldown_seconds,
        error_retry_seconds=error_retry_seconds,
        now=now,
    )


def get_sync_status(
    stream: str,
    storage_root: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Observability: last_success / last_error / lag / stale watchdog."""
    from ..core.config import settings

    root = Path(storage_root) if storage_root else Path(settings.storage_root)
    db = reporting_db_path(root)
    st = get_sync_state(db, stream) or {}
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)

    last_ok = _parse_iso(st.get("last_incremental_at"))
    status = (st.get("status") or "").strip().lower() or "unknown"
    detail = st.get("detail") or ""
    last_error: Optional[str] = None
    if status == "error":
        last_error = detail or "unknown error"
    elif detail.startswith("error:"):
        last_error = detail[6:].strip() or detail

    lag_hours: Optional[float] = None
    if last_ok is not None:
        lag_hours = round((n - last_ok).total_seconds() / 3600.0, 3)

    stale_watchdog = bool(
        lag_hours is not None and lag_hours > float(FRESHNESS_MAX_AGE_HOURS)
    ) or (last_ok is None and status != "ok")

    return {
        "stream": stream,
        "status": status,
        "last_success": st.get("last_incremental_at"),
        "last_error": last_error,
        "last_source_watermark": st.get("last_source_watermark"),
        "row_count": st.get("row_count"),
        "detail": detail or None,
        "lag_hours": lag_hours,
        "freshness_max_age_hours": FRESHNESS_MAX_AGE_HOURS,
        "stale_watchdog": stale_watchdog,
        "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
        "error_retry_seconds": DEFAULT_ERROR_RETRY_SECONDS,
        "overlap_days": DEFAULT_OVERLAP_DAYS,
    }


def get_ap_sync_status(
    storage_root: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    return get_sync_status(STREAM_AP, storage_root, now=now)


def get_ar_sync_status(
    storage_root: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    return get_sync_status(STREAM_AR, storage_root, now=now)


def _attempt_iso(now: datetime) -> str:
    return now.replace(microsecond=0).isoformat()


def _run_incremental_tick(
    stream: str,
    sync_fn_name: str,
    log_prefix: str,
    storage_root: Optional[Path] = None,
    *,
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    error_retry_seconds: int = DEFAULT_ERROR_RETRY_SECONDS,
    overlap_days: int = DEFAULT_OVERLAP_DAYS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    force: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Automation entry — same CLI sync authority, cooldown-gated."""
    from ..core.config import settings
    from .financial_reporting_db import set_sync_state

    root = Path(storage_root) if storage_root else Path(settings.storage_root)
    db = reporting_db_path(root)
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)

    if not force and not is_sync_due(
        db,
        stream,
        cooldown_seconds=cooldown_seconds,
        error_retry_seconds=error_retry_seconds,
        now=n,
    ):
        return None

    st = get_sync_state(db, stream) or {}
    date_from, date_to = resolve_incremental_window(
        watermark=st.get("last_source_watermark"),
        today=_today_utc(n),
        overlap_days=overlap_days,
        lookback_days=lookback_days,
    )
    attempt_at = _attempt_iso(n)

    summary: Dict[str, Any] = {
        "date_from": date_from,
        "date_to": date_to,
        "fetched": 0,
        "upserted": 0,
        "errors": [],
        "ok": False,
    }

    try:
        from app.tools import sync_financial_reporting as sfr

        sync_fn = getattr(sfr, sync_fn_name)
        fetched, upserted, errors = sync_fn(db, date_from, date_to, dry_run=False)
        summary["fetched"] = int(fetched)
        summary["upserted"] = int(upserted)
        summary["errors"] = list(errors or [])
        set_sync_state(db, stream, last_reconcile_at=attempt_at)
        if errors:
            msg = "; ".join(str(e) for e in errors[:5])
            set_sync_state(
                db,
                stream,
                status="error",
                detail=f"error: partial upsert; {msg}"[:500],
                last_reconcile_at=attempt_at,
            )
            summary["ok"] = False
            summary["last_error"] = msg
            log.warning(
                "%s: partial window=%s..%s upserted=%s errors=%s",
                log_prefix,
                date_from,
                date_to,
                upserted,
                len(errors),
            )
        else:
            summary["ok"] = True
            log.info(
                "%s: ok window=%s..%s fetched=%s upserted=%s",
                log_prefix,
                date_from,
                date_to,
                fetched,
                upserted,
            )
    except Exception as exc:  # noqa: BLE001 — scheduler must never die
        err = f"{type(exc).__name__}: {exc}"
        summary["errors"] = [err]
        summary["last_error"] = err
        try:
            set_sync_state(
                db,
                stream,
                status="error",
                detail=f"error: {err}"[:500],
                last_reconcile_at=attempt_at,
            )
        except Exception as stamp_exc:  # noqa: BLE001
            log.warning("%s: failed to stamp error state: %s", log_prefix, stamp_exc)
        log.warning(
            "%s: failed window=%s..%s err=%s",
            log_prefix,
            date_from,
            date_to,
            err,
        )

    summary["status"] = get_sync_status(stream, root, now=n)
    return summary


def run_ap_incremental_tick(
    storage_root: Optional[Path] = None,
    *,
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    error_retry_seconds: int = DEFAULT_ERROR_RETRY_SECONDS,
    overlap_days: int = DEFAULT_OVERLAP_DAYS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    force: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Automation entry — same ``sync_ap`` as the CLI, cooldown-gated."""
    return _run_incremental_tick(
        STREAM_AP,
        "sync_ap",
        "ap_reporting_sync",
        storage_root,
        cooldown_seconds=cooldown_seconds,
        error_retry_seconds=error_retry_seconds,
        overlap_days=overlap_days,
        lookback_days=lookback_days,
        force=force,
        now=now,
    )


def run_ar_incremental_tick(
    storage_root: Optional[Path] = None,
    *,
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    error_retry_seconds: int = DEFAULT_ERROR_RETRY_SECONDS,
    overlap_days: int = DEFAULT_OVERLAP_DAYS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    force: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Automation entry — same ``sync_ar`` as the CLI, cooldown-gated."""
    return _run_incremental_tick(
        STREAM_AR,
        "sync_ar",
        "ar_reporting_sync",
        storage_root,
        cooldown_seconds=cooldown_seconds,
        error_retry_seconds=error_retry_seconds,
        overlap_days=overlap_days,
        lookback_days=lookback_days,
        force=force,
        now=now,
    )


__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_ERROR_RETRY_SECONDS",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_OVERLAP_DAYS",
    "STREAM_AP",
    "STREAM_AR",
    "get_ap_sync_status",
    "get_ar_sync_status",
    "get_sync_status",
    "is_ap_sync_due",
    "is_ar_sync_due",
    "is_sync_due",
    "resolve_incremental_window",
    "run_ap_incremental_tick",
    "run_ar_incremental_tick",
]
