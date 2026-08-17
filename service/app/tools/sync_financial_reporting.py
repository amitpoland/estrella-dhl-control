"""
sync_financial_reporting.py — backfill AR/AP reporting projection (read-only wFirma).

Loads fiscal invoices (normal + correction) and expenses via existing
``wfirma_client.fetch_*_for_period`` helpers and upserts into
``financial_reporting_db``. NEVER writes to wFirma.

Scheduled incremental AR/AP automation reuses ``sync_ar`` / ``sync_ap`` via
``app.services.financial_reporting_sync.run_ar_incremental_tick`` /
``run_ap_incremental_tick`` (wired into ``wfirma_webhook_scheduler``). This CLI
remains the full / historical backfill path.

Usage:
    python -m app.tools.sync_financial_reporting --from 2024-01-01 --to 2026-08-17
    python -m app.tools.sync_financial_reporting --from 2024-01-01 --to 2026-08-17 --ar-only
    python -m app.tools.sync_financial_reporting --from 2024-01-01 --to 2026-08-17 --ap-only
    python -m app.tools.sync_financial_reporting --from 2024-01-01 --to 2026-08-17 --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional, Tuple


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()

from app.services.financial_reporting_db import (  # noqa: E402
    ApExpenseReportingRow,
    ArInvoiceReportingRow,
    count_ap,
    count_ar,
    reporting_db_path,
    set_sync_state,
    upsert_ap_expense,
    upsert_ar_invoice,
)
from app.services.ledger_aggregator import (  # noqa: E402
    EXPENSE_CLASS_REJECTED,
    classify_expense_lifecycle,
)
from app.services.ledger_fact_universe import FISCAL_AR_INVOICE_TYPES  # noqa: E402


def _dec(raw: Optional[str]) -> Optional[Decimal]:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _t(node: ET.Element, *tags: str) -> str:
    for tag in tags:
        v = (node.findtext(tag) or "").strip()
        if v:
            return v
    return ""


def _invoice_gross(inv: ET.Element) -> Optional[Decimal]:
    for tag in ("brutto", "total", "total_brutto"):
        d = _dec(inv.findtext(tag))
        if d is not None:
            return d
    return None


def _expense_gross(exp: ET.Element) -> Optional[Decimal]:
    for tag in ("brutto", "total", "total_brutto"):
        d = _dec(exp.findtext(tag))
        if d is not None:
            return d
    return None


def _hash_node(node: ET.Element) -> str:
    blob = ET.tostring(node, encoding="utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def map_invoice_node(inv: ET.Element) -> Optional[ArInvoiceReportingRow]:
    iid = _t(inv, "id")
    cid = _t(inv, "contractor/id")
    dtype = _t(inv, "type") or "normal"
    if not iid or not cid:
        return None
    if dtype not in FISCAL_AR_INVOICE_TYPES:
        return None
    name = (
        _t(inv, "contractor_detail/name")
        or _t(inv, "contractor/name")
    )
    return ArInvoiceReportingRow(
        invoice_id=iid,
        contractor_id=cid,
        document_type=dtype,
        contractor_name=name or None,
        invoice_number=_t(inv, "fullnumber", "full_number", "number") or None,
        issue_date=_t(inv, "date") or None,
        due_date=_t(inv, "paymentdate", "payment_date") or None,
        currency=(_t(inv, "currency") or "").upper() or None,
        net=_dec(inv.findtext("netto")),
        tax=_dec(_t(inv, "vat", "vat_sum", "tax") or None),
        gross=_invoice_gross(inv),
        payment_state=_t(inv, "paymentstate") or None,
        document_status=_t(inv, "status") or None,
        correction_of_id=_t(inv, "parent/id") or None,
        open_relevant=True,
        source_modified=_t(inv, "modified", "modificationdate") or None,
        source_version=_t(inv, "version") or None,
        raw_hash=_hash_node(inv),
    )


def map_expense_node(exp: ET.Element) -> Optional[ApExpenseReportingRow]:
    eid = _t(exp, "id")
    sid = _t(exp, "contractor/id")
    if not eid or not sid:
        return None
    name = (
        _t(exp, "contractor_detail/name")
        or _t(exp, "contractor/name")
    )
    # The expenses module never emits <status>; lifecycle lives in
    # <draft>/<is_rejected>. Rejected inbox documents are not liabilities and
    # are excluded from the open-payable universe via open_relevant.
    lifecycle = classify_expense_lifecycle(
        _t(exp, "draft"), _t(exp, "is_rejected")
    )
    return ApExpenseReportingRow(
        expense_id=eid,
        supplier_id=sid,
        document_type=_t(exp, "type") or None,
        supplier_name=name or None,
        document_number=_t(exp, "fullnumber", "number") or None,
        issue_date=_t(exp, "date") or None,
        due_date=_t(exp, "payment_date", "paymentdate") or None,
        currency=(_t(exp, "currency") or "").upper() or None,
        net=_dec(exp.findtext("netto")),
        tax=_dec(_t(exp, "vat", "vat_sum", "tax") or None),
        gross=_expense_gross(exp),
        payment_state=_t(exp, "paymentstate") or None,
        document_status=lifecycle,
        correction_of_id=_t(exp, "parent/id") or None,
        open_relevant=lifecycle != EXPENSE_CLASS_REJECTED,
        source_modified=_t(exp, "modified", "modificationdate") or None,
        source_version=_t(exp, "version") or None,
        raw_hash=_hash_node(exp),
    )


@dataclass
class SyncResult:
    ar_fetched: int = 0
    ar_upserted: int = 0
    ap_fetched: int = 0
    ap_upserted: int = 0
    dry_run: bool = False
    errors: List[str] = field(default_factory=list)


def sync_ar(
    db_path: Path,
    date_from: str,
    date_to: str,
    *,
    dry_run: bool = False,
) -> Tuple[int, int, List[str]]:
    from app.services import wfirma_client

    errors: List[str] = []
    nodes = wfirma_client.fetch_invoices_for_period(
        date_from, date_to, types=FISCAL_AR_INVOICE_TYPES
    )
    kept: List[ET.Element] = []
    for n in nodes or []:
        d = (n.findtext("date") or "").strip()
        if d and date_from and d < date_from:
            continue
        if d and date_to and d > date_to:
            continue
        kept.append(n)

    upserted = 0
    for n in kept:
        row = map_invoice_node(n)
        if row is None:
            continue
        if not dry_run:
            try:
                upsert_ar_invoice(db_path, row)
                upserted += 1
            except Exception as exc:  # noqa: BLE001 — tool continues on row errors
                errors.append(f"ar {row.invoice_id}: {exc}")
        else:
            upserted += 1
    if not dry_run:
        set_sync_state(
            db_path,
            "ar_invoices",
            last_incremental_at=datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            row_count=count_ar(db_path),
            status="ok" if not errors else "partial",
            detail=f"window={date_from}..{date_to}; upserted={upserted}",
            last_source_watermark=date_to,
        )
    return len(kept), upserted, errors


def sync_ap(
    db_path: Path,
    date_from: str,
    date_to: str,
    *,
    dry_run: bool = False,
) -> Tuple[int, int, List[str]]:
    from app.services import wfirma_client

    errors: List[str] = []
    nodes = wfirma_client.fetch_expenses_for_period(date_from, date_to)
    kept: List[ET.Element] = []
    for n in nodes or []:
        d = (n.findtext("date") or "").strip()
        if d and date_from and d < date_from:
            continue
        if d and date_to and d > date_to:
            continue
        kept.append(n)

    upserted = 0
    for n in kept:
        row = map_expense_node(n)
        if row is None:
            continue
        if not dry_run:
            try:
                upsert_ap_expense(db_path, row)
                upserted += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"ap {row.expense_id}: {exc}")
        else:
            upserted += 1
    if not dry_run:
        set_sync_state(
            db_path,
            "ap_expenses",
            last_incremental_at=datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            row_count=count_ap(db_path),
            status="ok" if not errors else "partial",
            detail=f"window={date_from}..{date_to}; upserted={upserted}",
            last_source_watermark=date_to,
        )
    return len(kept), upserted, errors


def run(
    *,
    date_from: str,
    date_to: str,
    ar_only: bool = False,
    ap_only: bool = False,
    dry_run: bool = False,
    db: Optional[Path] = None,
) -> SyncResult:
    from app.core.config import settings

    if ar_only and ap_only:
        raise ValueError("choose at most one of --ar-only / --ap-only")
    db_path = Path(db) if db else reporting_db_path(Path(settings.storage_root))
    result = SyncResult(dry_run=dry_run)

    do_ar = not ap_only
    do_ap = not ar_only
    if do_ar:
        fetched, upserted, errs = sync_ar(
            db_path, date_from, date_to, dry_run=dry_run
        )
        result.ar_fetched = fetched
        result.ar_upserted = upserted
        result.errors.extend(errs)
    if do_ap:
        fetched, upserted, errs = sync_ap(
            db_path, date_from, date_to, dry_run=dry_run
        )
        result.ap_fetched = fetched
        result.ap_upserted = upserted
        result.errors.extend(errs)
    return result


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Sync wFirma AR/AP into local financial_reporting.sqlite (read-only upstream)."
    )
    p.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    p.add_argument("--ar-only", action="store_true")
    p.add_argument("--ap-only", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--db", default="", help="Override reporting sqlite path")
    args = p.parse_args(argv)

    result = run(
        date_from=args.date_from,
        date_to=args.date_to,
        ar_only=args.ar_only,
        ap_only=args.ap_only,
        dry_run=args.dry_run,
        db=Path(args.db) if args.db else None,
    )
    mode = "DRY-RUN" if result.dry_run else "WRITE"
    print(
        f"[{mode}] AR fetched={result.ar_fetched} upserted={result.ar_upserted} | "
        f"AP fetched={result.ap_fetched} upserted={result.ap_upserted} | "
        f"errors={len(result.errors)}"
    )
    for e in result.errors[:20]:
        print(f"  ! {e}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
