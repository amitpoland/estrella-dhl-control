"""Local AR/AP fact universe — fast CFO/MA path from reporting projections.

wFirma remains originating fiscal authority. This module projects:
  financial_reporting.sqlite  (invoices / expenses)
  payment_state.db            (settlements)

into the same fact dicts consumed by ``build_portfolio_from_facts`` /
``build_payables_portfolio_from_facts``.

Never invents remaining math — callers still use match_payments_* +
remaining_after_payments.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .financial_reporting_db import (
    count_ap,
    count_ar,
    get_sync_state,
    list_ap_expenses_as_of,
    list_ar_invoices_as_of,
    reporting_db_path,
)
from .wfirma_payment_db import get_snapshot_count, list_payments_as_of


# Projection older than this is marked stale (still served, never as "fresh").
FRESHNESS_MAX_AGE_HOURS = 24


def _dec(raw: Any) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw).replace(",", ".").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _freshness_block(
    *,
    stream_states: Dict[str, Optional[Dict[str, Any]]],
    payment_count: int,
    ar_count: int,
    ap_count: int,
) -> Dict[str, Any]:
    """Build source/freshness/reconciliation_status for CFO responses."""
    now = datetime.now(timezone.utc)
    stamps: List[datetime] = []
    detail: Dict[str, Any] = {}
    for stream, st in stream_states.items():
        if not st:
            detail[stream] = {"status": "missing"}
            continue
        ts = (
            _parse_iso(st.get("last_reconcile_at"))
            or _parse_iso(st.get("last_incremental_at"))
            or _parse_iso(st.get("last_full_sync_at"))
        )
        detail[stream] = {
            "status": st.get("status") or "unknown",
            "row_count": st.get("row_count"),
            "last_full_sync_at": st.get("last_full_sync_at"),
            "last_incremental_at": st.get("last_incremental_at"),
            "last_reconcile_at": st.get("last_reconcile_at"),
        }
        if ts:
            stamps.append(ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))

    if ar_count <= 0 and ap_count <= 0:
        level = "empty"
        recon = "unavailable"
    elif not stamps:
        level = "unknown"
        recon = "unverified"
    else:
        newest = max(stamps)
        age_h = (now - newest).total_seconds() / 3600.0
        if age_h <= FRESHNESS_MAX_AGE_HOURS:
            level = "fresh"
            recon = "projection_ok"
        else:
            level = "stale"
            recon = "stale_projection"

    return {
        "as_of_generated_at": _iso_now(),
        "source": "local",
        "freshness": level,
        "freshness_max_age_hours": FRESHNESS_MAX_AGE_HOURS,
        "reconciliation_status": recon,
        "projection": {
            "ar_invoice_rows": ar_count,
            "ap_expense_rows": ap_count,
            "payment_snapshot_rows": payment_count,
            "streams": detail,
        },
    }


def reporting_row_to_invoice_fact(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row.get("invoice_id") or "").strip(),
        "fullnumber": (row.get("invoice_number") or "").strip(),
        "type": (row.get("document_type") or "").strip(),
        "date": (row.get("issue_date") or "").strip(),
        "paymentdate": (row.get("due_date") or "").strip(),
        "currency": (row.get("currency") or "").strip().upper(),
        "netto": _dec(row.get("net")),
        "brutto": _dec(row.get("gross")),
        "contractor_id": str(row.get("contractor_id") or "").strip(),
        "contractor_name": (row.get("contractor_name") or "").strip(),
    }


def reporting_row_to_expense_fact(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row.get("expense_id") or "").strip(),
        "fullnumber": (row.get("document_number") or "").strip(),
        "type": (row.get("document_type") or "").strip(),
        "date": (row.get("issue_date") or "").strip(),
        "payment_date": (row.get("due_date") or "").strip(),
        "currency": (row.get("currency") or "").strip().upper(),
        "netto": _dec(row.get("net")),
        "brutto": _dec(row.get("gross")),
        "contractor_id": str(row.get("supplier_id") or "").strip(),
        "contractor_name": (row.get("supplier_name") or "").strip(),
        "correction": "1" if (row.get("correction_of_id") or "") else "0",
    }


def payment_row_to_fact(row: Dict[str, Any]) -> Dict[str, Any]:
    inv = str(row.get("invoice_id") or "").strip()
    exp = str(row.get("expense_id") or "").strip()
    if inv in ("0", "None"):
        inv = ""
    if exp in ("0", "None"):
        exp = ""
    return {
        "id": str(row.get("payment_id") or "").strip(),
        "linked_invoice": inv,
        "linked_expense": exp,
        "value": _dec(row.get("value")),
        "value_pln": _dec(row.get("value_pln")),
        "date": (row.get("payment_date") or "").strip(),
        "currency_label": (row.get("currency_label") or "").strip(),
        "currency": "",
        "contractor_id": str(row.get("contractor_id") or "").strip(),
    }


def _in_activity_window(issue_date: str, date_from: str, date_to: str) -> bool:
    d = (issue_date or "").strip()
    if not d:
        return True  # unknown issue date — keep (same as live Python filter)
    if date_from and d < date_from:
        return False
    if date_to and d > date_to:
        return False
    return True


def local_projection_available(storage_root: Path) -> Tuple[bool, str]:
    """True when AR reporting has rows (minimum for CFO local path)."""
    db = reporting_db_path(Path(storage_root))
    if not db.exists():
        return False, "financial_reporting.sqlite missing"
    n = count_ar(db)
    if n <= 0:
        return False, "ar_invoice_reporting empty — run sync_financial_reporting"
    return True, f"ar_rows={n}"


def load_ar_fact_universe_local(
    storage_root: Path,
    date_from: str,
    date_to: str,
    *,
    types: Sequence[str] = ("normal", "correction"),
) -> Dict[str, Any]:
    """POSITION payments + ACTIVITY invoices from local projection."""
    t0 = time.perf_counter()
    root = Path(storage_root)
    rep = reporting_db_path(root)
    pay_db = root / "payment_state.db"

    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if not df or not dt:
        raise ValueError("date_from and date_to are required")

    t_n0 = time.perf_counter()
    rows = list_ar_invoices_as_of(
        rep, as_of=dt, document_types=tuple(types) or ("normal", "correction"),
    )
    invoice_facts = [
        reporting_row_to_invoice_fact(r)
        for r in rows
        if _in_activity_window(r.get("issue_date") or "", df, dt)
    ]
    invoice_facts = [f for f in invoice_facts if f.get("id")]

    inv_ids = [f["id"] for f in invoice_facts]
    pay_rows: List[Dict[str, Any]] = []
    if pay_db.exists() and inv_ids:
        # POSITION: all payments <= as_of (date_to). Prefer invoice-linked set
        # plus contractor-wide payments for unmatched/credit application.
        pay_rows = list_payments_as_of(pay_db, dt)
    payment_facts = [payment_row_to_fact(r) for r in pay_rows]
    payment_facts = [p for p in payment_facts if p.get("id")]
    ej_ms = int((time.perf_counter() - t_n0) * 1000)

    ar_count = count_ar(rep)
    pay_count = get_snapshot_count(pay_db) if pay_db.exists() else 0
    meta = _freshness_block(
        stream_states={
            "ar_invoices": get_sync_state(rep, "ar_invoices"),
            "ap_expenses": get_sync_state(rep, "ap_expenses"),
        },
        payment_count=pay_count,
        ar_count=ar_count,
        ap_count=count_ap(rep) if rep.exists() else 0,
    )

    duration_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "kind": "ar",
        "period": (df, dt),
        "invoice_facts": invoice_facts,
        "payment_facts": payment_facts,
        "inv_stats": {"api_calls": 0, "pages": 0, "source": "local"},
        "pay_stats": {"api_calls": 0, "pages": 0, "source": "local"},
        "duration_ms": duration_ms,
        "wfirma_wait_ms": 0,
        "ej_normalize_ms": ej_ms,
        "ej_ms": ej_ms,
        "inv_page_wait_ms": [],
        "pay_page_wait_ms": [],
        "per_customer_wfirma_calls": 0,
        "cache_hit": False,
        "coalesced": False,
        "source": "local",
        "provenance": meta,
    }


def load_ap_fact_universe_local(
    storage_root: Path,
    date_from: str,
    date_to: str,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    root = Path(storage_root)
    rep = reporting_db_path(root)
    pay_db = root / "payment_state.db"

    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if not df or not dt:
        raise ValueError("date_from and date_to are required")

    t_n0 = time.perf_counter()
    rows = list_ap_expenses_as_of(rep, as_of=dt)
    expense_facts = [
        reporting_row_to_expense_fact(r)
        for r in rows
        if _in_activity_window(r.get("issue_date") or "", df, dt)
    ]
    expense_facts = [f for f in expense_facts if f.get("id")]

    pay_rows: List[Dict[str, Any]] = []
    if pay_db.exists():
        pay_rows = list_payments_as_of(pay_db, dt)
    payment_facts = [payment_row_to_fact(r) for r in pay_rows]
    payment_facts = [p for p in payment_facts if p.get("id")]
    ej_ms = int((time.perf_counter() - t_n0) * 1000)

    meta = _freshness_block(
        stream_states={
            "ar_invoices": get_sync_state(rep, "ar_invoices"),
            "ap_expenses": get_sync_state(rep, "ap_expenses"),
        },
        payment_count=get_snapshot_count(pay_db) if pay_db.exists() else 0,
        ar_count=count_ar(rep) if rep.exists() else 0,
        ap_count=count_ap(rep),
    )
    duration_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "kind": "ap",
        "period": (df, dt),
        "expense_facts": expense_facts,
        "payment_facts": payment_facts,
        "exp_stats": {"api_calls": 0, "pages": 0, "source": "local"},
        "pay_stats": {"api_calls": 0, "pages": 0, "source": "local"},
        "duration_ms": duration_ms,
        "wfirma_wait_ms": 0,
        "ej_normalize_ms": ej_ms,
        "ej_ms": ej_ms,
        "exp_page_wait_ms": [],
        "pay_page_wait_ms": [],
        "per_supplier_wfirma_calls": 0,
        "cache_hit": False,
        "coalesced": False,
        "source": "local",
        "provenance": meta,
    }
