"""
reservation_worker.py — Worker logic for the reservation queue.

All functions are pure: they take db_path + optional wfirma_client,
no global state. Caller provides the client instance.

Flow
----
1. import_purchase_packing  → product_master + design_product_mapping rows
2. import_sales_packing     → reservation_queue rows (pending or blocked)
3. sync_wfirma_products_by_codes → wfirma_product_mapping (read-only from wFirma)
4. refresh_queue_readiness  → promote pending → ready when both mappings present
5. process_ready_reservations → groups by (batch_id, client_name, sales_doc_no),
                                 one reservation per group
6. worker_tick              → safe background tick combining 3+4+5

Constraints
-----------
- product_code is the ONLY bridge to wFirma goods (no name matching).
- No automatic product creation in wFirma.
- No live reservation unless mode='live' or AUTO_CREATE_WFIRMA_RESERVATIONS=true.
"""
from __future__ import annotations

import hashlib
from datetime import date, timezone, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger
from . import reservation_db as rdb

log = get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _queue_key(batch_id: str, client_name: str, design_no: str, product_code: str) -> str:
    """Stable unique key for a queue row."""
    raw = f"{batch_id}::{client_name}::{design_no}::{product_code}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── 1. import_purchase_packing ────────────────────────────────────────────────

def import_purchase_packing(db_path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create product_master + design_product_mapping rows from a purchase packing list.

    Payload shape:
        {
          "batch_id": str,
          "invoice_no": str,
          "lines": [
            {"design_no": str, "product_code": str, "description": str,
             "metal": str, "category": str}
          ]
        }

    Returns {"created": int, "skipped": int, "errors": list[str]}
    """
    batch_id   = payload.get("batch_id", "")
    invoice_no = payload.get("invoice_no", "")
    lines      = payload.get("lines") or []

    created = 0
    skipped = 0
    errors: List[str] = []

    for idx, line in enumerate(lines):
        design_no    = (line.get("design_no") or "").strip()
        product_code = (line.get("product_code") or "").strip()
        if not design_no or not product_code:
            errors.append(f"line[{idx}]: design_no and product_code required")
            skipped += 1
            continue
        try:
            rdb.upsert_product_master(
                db_path,
                product_code=product_code,
                design_no=design_no,
                description=line.get("description", ""),
                metal=line.get("metal", ""),
                category=line.get("category", ""),
                source_invoice_no=invoice_no,
                source_batch_id=batch_id,
            )
            rdb.upsert_design_mapping(
                db_path,
                design_no=design_no,
                product_code=product_code,
                confidence="locked",
                source="purchase_packing",
            )
            created += 1
        except Exception as exc:
            errors.append(f"line[{idx}] {product_code}: {exc}")
            skipped += 1

    return {"created": created, "skipped": skipped, "errors": errors}


# ── 2. import_sales_packing ───────────────────────────────────────────────────

def import_sales_packing(db_path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create reservation_queue rows from a sales packing list.

    Looks up product_code via design_product_mapping.
    If design_no is not known → status=blocked.

    Payload shape:
        {
          "batch_id": str,
          "client_name": str,
          "client_ref": str,          # optional
          "sales_doc_no": str,        # optional
          "lines": [
            {"design_no": str, "qty": float, "unit_price": float, "currency": str}
          ]
        }

    Returns {"created": int, "blocked": int, "rows": [...]}
    """
    batch_id     = payload.get("batch_id", "")
    client_name  = (payload.get("client_name") or "").strip()
    client_ref   = payload.get("client_ref", "") or ""
    sales_doc_no = payload.get("sales_doc_no", "") or ""
    lines        = payload.get("lines") or []

    rows_out: List[Dict[str, Any]] = []
    created = 0
    blocked = 0

    for line in lines:
        design_no  = (line.get("design_no") or "").strip()
        qty        = float(line.get("qty") or 0)
        unit_price = float(line.get("unit_price") or 0)
        currency   = (line.get("currency") or "USD").strip()

        # Resolve product_code from design_no
        mapping = rdb.get_product_code_by_design_no(db_path, design_no)
        if mapping:
            product_code    = mapping["product_code"]
            status          = "pending"
            blocking_reason = ""
        else:
            product_code    = "UNMAPPED"
            status          = "blocked"
            blocking_reason = f"design_no '{design_no}' not found in product_master"

        key = _queue_key(batch_id, client_name, design_no, product_code)

        try:
            row_id = rdb.upsert_reservation_queue(
                db_path,
                queue_key=key,
                batch_id=batch_id,
                client_name=client_name,
                client_ref=client_ref,
                sales_doc_no=sales_doc_no,
                design_no=design_no,
                product_code=product_code,
                qty=qty,
                unit_price=unit_price,
                currency=currency,
                status=status,
                blocking_reason=blocking_reason,
            )
        except Exception as exc:
            log.warning("import_sales_packing row error %s: %s", design_no, exc)
            blocked += 1
            continue

        if status == "blocked":
            blocked += 1
        else:
            created += 1

        rows_out.append({
            "queue_key":    key,
            "queue_id":     row_id,
            "design_no":    design_no,
            "product_code": product_code,
            "status":       status,
            "blocking_reason": blocking_reason,
        })

    return {"created": created, "blocked": blocked, "rows": rows_out}


# ── 3. sync_wfirma_products_by_codes ─────────────────────────────────────────

def sync_wfirma_products_by_codes(
    db_path: Path,
    wfirma_client: Any,
    product_codes: List[str],
) -> Dict[str, Any]:
    """
    Exact-code search in wFirma for each product_code. Updates wfirma_product_mapping.
    Read-only: never creates products in wFirma.

    wfirma_client must have:  get_product_by_code(product_code) → WFirmaProduct | None

    Returns {"matched": [...], "missing": [...]}
    """
    matched: List[str] = []
    missing: List[str] = []
    now = _now()

    for code in product_codes:
        if not code or code == "UNMAPPED":
            missing.append(code)
            continue
        try:
            product = wfirma_client.get_product_by_code(code)
        except Exception as exc:
            log.warning("sync_wfirma_products_by_codes error for %s: %s", code, exc)
            rdb.upsert_wfirma_product_mapping(
                db_path,
                product_code=code,
                sync_status="error",
                last_checked_at=now,
                last_error=str(exc)[:500],
            )
            missing.append(code)
            continue

        if product is None:
            rdb.upsert_wfirma_product_mapping(
                db_path,
                product_code=code,
                sync_status="not_found",
                last_checked_at=now,
                last_error="",
            )
            missing.append(code)
        else:
            warehouse_id = getattr(product, "warehouse_id", "") or ""
            rdb.upsert_wfirma_product_mapping(
                db_path,
                product_code=code,
                wfirma_product_id=str(product.wfirma_id),
                wfirma_code=str(product.code),
                wfirma_name=str(product.name),
                warehouse_id=warehouse_id,
                sync_status="matched",
                last_checked_at=now,
                last_error="",
            )
            matched.append(code)

    return {"matched": matched, "missing": missing}


# ── 4. refresh_queue_readiness ────────────────────────────────────────────────

def refresh_queue_readiness(db_path: Path) -> Dict[str, Any]:
    """
    Promote pending → ready for each row where both
    wfirma_product_mapping (matched) and wfirma_customer_mapping (matched)
    exist.

    Returns {"promoted": int, "still_pending": int}
    """
    pending_rows = rdb.list_reservation_queue(db_path, status="pending")
    promoted = 0
    still_pending = 0
    now = _now()

    for row in pending_rows:
        product_code = row["product_code"]
        client_name  = row["client_name"]

        prod_mapping = rdb.get_wfirma_product_mapping(db_path, product_code)
        cust_mapping = rdb.get_wfirma_customer_mapping(db_path, client_name)

        prod_ok = (
            prod_mapping is not None
            and prod_mapping.get("sync_status") == "matched"
            and prod_mapping.get("wfirma_product_id")
        )
        cust_ok = (
            cust_mapping is not None
            and cust_mapping.get("match_status") == "matched"
            and cust_mapping.get("wfirma_customer_id")
        )

        if prod_ok and cust_ok:
            rdb.update_queue_ready(
                db_path,
                row_id=row["id"],
                wfirma_product_id=prod_mapping["wfirma_product_id"],
                wfirma_customer_id=cust_mapping["wfirma_customer_id"],
                ready_at=now,
                updated_at=now,
            )
            promoted += 1
        else:
            still_pending += 1

    return {"promoted": promoted, "still_pending": still_pending}


# ── 5. process_ready_reservations ─────────────────────────────────────────────

def process_ready_reservations(
    db_path: Path,
    wfirma_client: Any,
    *,
    batch_id: Optional[str] = None,
    mode: str = "dry_run",
) -> Dict[str, Any]:
    """
    Groups ready rows by (batch_id, client_name, sales_doc_no) and creates
    one reservation per group.

    mode='dry_run'  → returns would_create count, no API calls.
    mode='live'     → calls wfirma_client.create_reservation() for each group.

    wfirma_client must have: create_reservation(req) → ReservationResult

    Returns {
        "mode": str,
        "groups": int,
        "results": [{
            "group_key": str, "batch_id": str, "client_name": str,
            "sales_doc_no": str, "lines": int, "status": str,
            "wfirma_reservation_id": str, "error": str
        }]
    }
    """
    ready_rows = rdb.list_reservation_queue(db_path, status="ready", batch_id=batch_id)

    # Group by (batch_id, client_name, sales_doc_no)
    groups: Dict[tuple, List[Dict]] = {}
    for row in ready_rows:
        key = (row["batch_id"], row["client_name"], row["sales_doc_no"])
        groups.setdefault(key, []).append(row)

    results: List[Dict[str, Any]] = []
    now = _now()

    for (gd_batch_id, client_name, sales_doc_no), rows in groups.items():
        group_key = f"{gd_batch_id}::{client_name}::{sales_doc_no}"

        if mode == "dry_run":
            results.append({
                "group_key":            group_key,
                "batch_id":             gd_batch_id,
                "client_name":          client_name,
                "sales_doc_no":         sales_doc_no,
                "lines":                len(rows),
                "status":               "would_create",
                "wfirma_reservation_id": "",
                "error":                "",
            })
            continue

        # mode == "live"
        locked = rdb.mark_queue_group_submitting(
            db_path, gd_batch_id, client_name, sales_doc_no, updated_at=now,
        )
        if not locked:
            results.append({
                "group_key":            group_key,
                "batch_id":             gd_batch_id,
                "client_name":          client_name,
                "sales_doc_no":         sales_doc_no,
                "lines":                len(rows),
                "status":               "skipped_already_locked",
                "wfirma_reservation_id": "",
                "error":                "concurrent lock",
            })
            continue

        try:
            from .wfirma_client import ReservationRequest, ReservationLine

            first_row = rows[0]
            wfirma_customer_id = first_row["wfirma_customer_id"]

            # Resolve warehouse_id from product mapping of first matched row
            warehouse_id = ""
            for row in rows:
                pm = rdb.get_wfirma_product_mapping(db_path, row["product_code"])
                if pm and pm.get("warehouse_id"):
                    warehouse_id = pm["warehouse_id"]
                    break

            lines = []
            for row in rows:
                pm = rdb.get_wfirma_product_mapping(db_path, row["product_code"])
                wfirma_good_id = pm["wfirma_product_id"] if pm else row["wfirma_product_id"]
                lines.append(ReservationLine(
                    product_code=row["product_code"],
                    wfirma_good_id=wfirma_good_id,
                    product_name=row["design_no"],
                    qty=float(row["qty"]),
                    unit_price=float(row["unit_price"]),
                    currency=row["currency"],
                ))

            req = ReservationRequest(
                batch_id=gd_batch_id,
                client_name=client_name,
                wfirma_contractor_id=wfirma_customer_id,
                wfirma_warehouse_id=warehouse_id,
                date=date.today().isoformat(),
                lines=lines,
                currency=rows[0]["currency"],
                description=sales_doc_no or f"{gd_batch_id} / {client_name}",
            )

            result = wfirma_client.create_reservation(req)

            if result.ok:
                rdb.mark_queue_group_created(
                    db_path, gd_batch_id, client_name, sales_doc_no,
                    wfirma_reservation_id=result.wfirma_reservation_id,
                    completed_at=_now(),
                    updated_at=_now(),
                )
                results.append({
                    "group_key":            group_key,
                    "batch_id":             gd_batch_id,
                    "client_name":          client_name,
                    "sales_doc_no":         sales_doc_no,
                    "lines":                len(rows),
                    "status":               "created",
                    "wfirma_reservation_id": result.wfirma_reservation_id,
                    "error":                "",
                })
            else:
                error_msg = result.error or "unknown error"
                rdb.mark_queue_group_failed(
                    db_path, gd_batch_id, client_name, sales_doc_no,
                    error=error_msg,
                    updated_at=_now(),
                )
                results.append({
                    "group_key":            group_key,
                    "batch_id":             gd_batch_id,
                    "client_name":          client_name,
                    "sales_doc_no":         sales_doc_no,
                    "lines":                len(rows),
                    "status":               "failed",
                    "wfirma_reservation_id": "",
                    "error":                error_msg,
                })

        except Exception as exc:
            error_msg = str(exc)[:500]
            rdb.mark_queue_group_failed(
                db_path, gd_batch_id, client_name, sales_doc_no,
                error=error_msg,
                updated_at=_now(),
            )
            results.append({
                "group_key":            group_key,
                "batch_id":             gd_batch_id,
                "client_name":          client_name,
                "sales_doc_no":         sales_doc_no,
                "lines":                len(rows),
                "status":               "failed",
                "wfirma_reservation_id": "",
                "error":                error_msg,
            })

    return {
        "mode":    mode,
        "groups":  len(groups),
        "results": results,
    }


# ── 6. worker_tick ────────────────────────────────────────────────────────────

def worker_tick(db_path: Path, wfirma_client: Any) -> Dict[str, Any]:
    """
    Safe background tick:
    1. sync_wfirma_products_by_codes for all pending product codes
    2. refresh_queue_readiness
    3. process_ready_reservations (live only if AUTO_CREATE_WFIRMA_RESERVATIONS=true)

    Returns combined summary dict.
    """
    try:
        from ..core.config import settings
        auto_live = getattr(settings, "auto_create_wfirma_reservations", False)
    except Exception:
        auto_live = False

    mode = "live" if auto_live else "dry_run"

    # Step 1: sync products
    pending_codes = rdb.list_product_codes_from_queue(db_path, status="pending")
    sync_result = sync_wfirma_products_by_codes(db_path, wfirma_client, pending_codes)

    # Step 2: refresh readiness
    readiness = refresh_queue_readiness(db_path)

    # Step 3: process
    process_result = process_ready_reservations(
        db_path, wfirma_client, mode=mode,
    )

    return {
        "mode":            mode,
        "sync":            sync_result,
        "readiness":       readiness,
        "process":         process_result,
    }
