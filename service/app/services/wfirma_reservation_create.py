"""
wfirma_reservation_create.py — Single-client live reservation create orchestrator.

Phase 3.A: this module is the ONLY place that issues a real
POST warehouse_document_r/add call to wFirma. It enforces every gate
required before a live submission:

  1. caps.ready_to_reserve must be True (config-only check)
  2. Live diagnostic re-probe must succeed:
       contractors/find reachable
       goods/find reachable
       warehouses/find returns the configured WFIRMA_WAREHOUSE_ID
       vat_codes/find resolves rate=23 to a wFirma vat_code_id
  3. Local draft (batch_id, client_name) must exist with ready_to_create=True
  4. Draft status must be in {pending, failed} (idempotency)
  5. Customer mapping (wfirma_customers) must have non-empty wfirma_customer_id
  6. Every line's product_code must have a non-empty wfirma_product_id
  7. Every line.stock_ok must be True (preview already verified dispatch)
  8. WFIRMA_WAREHOUSE_ID must appear in list_warehouses()

Submission flow:
  - mark_draft_submitting (atomic; rejects concurrent submitters)
  - build ReservationRequest
  - wfirma_client.create_reservation (Basic Auth POST)
  - mark_draft_created OR mark_draft_failed
  - return structured result

Never raises — every failure mode returns a dict the route handler
turns into the appropriate HTTP status.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from ..core.config import settings
from ..core.logging import get_logger
from . import wfirma_capabilities as wfc
from . import wfirma_client as wfcli
from . import wfirma_db as wfdb

log = get_logger(__name__)


# ── Result codes (human-readable, machine-parseable) ─────────────────────────
GATE_OK                       = "OK"
GATE_NOT_READY                = "WFIRMA_NOT_READY"
GATE_DIAGNOSTIC_FAILED        = "DIAGNOSTIC_FAILED"
GATE_DRAFT_NOT_FOUND          = "DRAFT_NOT_FOUND"
GATE_DRAFT_NOT_READY          = "DRAFT_NOT_READY"
GATE_DRAFT_ALREADY_PROCESSED  = "DRAFT_ALREADY_PROCESSED"
GATE_DRAFT_ALREADY_SUBMITTING = "DRAFT_ALREADY_SUBMITTING"
GATE_NO_LINES                 = "NO_LINES"
GATE_CUSTOMER_NOT_MAPPED      = "CUSTOMER_NOT_MAPPED"
GATE_PRODUCTS_NOT_MAPPED      = "PRODUCTS_NOT_MAPPED"
GATE_STOCK_INSUFFICIENT       = "STOCK_INSUFFICIENT"
GATE_WAREHOUSE_NOT_FOUND      = "WAREHOUSE_NOT_FOUND"
GATE_VAT_CODE_NOT_FOUND       = "VAT_CODE_NOT_FOUND"
SUBMIT_RACE_LOST              = "SUBMIT_RACE_LOST"
SUBMIT_UPSTREAM_ERROR         = "UPSTREAM_ERROR"


def create_one_reservation(batch_id: str, client_name: str) -> Dict[str, Any]:
    """
    Run all gates and (if all pass) submit a single reservation to wFirma.

    Returns a dict with at minimum:
      ok            : bool
      code          : one of the GATE_* / SUBMIT_* constants above
      error         : human-readable message (empty on success)
      draft_id      : str (if a draft was located, even on gate failure)
      wfirma_reservation_id : str (only on success)
      details       : dict with extra context for the caller / UI
    """
    # ── Gate 1: capability ───────────────────────────────────────────────────
    caps = wfc.get_capabilities()
    if not caps.get("ready_to_reserve"):
        return _fail(
            GATE_NOT_READY,
            "wFirma not ready to reserve. See blocking_reasons.",
            details={"blocking_reasons": caps.get("blocking_reasons", [])},
        )

    # ── Gate 2: live diagnostic re-probe ─────────────────────────────────────
    diag = _run_live_diagnostic()
    if not diag["ok"]:
        return _fail(
            GATE_DIAGNOSTIC_FAILED,
            "Live wFirma diagnostic failed. Run check_wfirma_config.",
            details=diag,
        )

    # ── Gate 3: draft exists ─────────────────────────────────────────────────
    draft = wfdb.get_reservation_draft(batch_id, client_name)
    if not draft:
        return _fail(
            GATE_DRAFT_NOT_FOUND,
            f"No draft for batch_id={batch_id} client_name={client_name}",
        )

    draft_id = draft["id"]

    # ── Gate 4: draft state ──────────────────────────────────────────────────
    if not draft.get("ready_to_create"):
        return _fail(GATE_DRAFT_NOT_READY,
                     "Draft is not marked ready_to_create.",
                     draft_id=draft_id)
    status = (draft.get("status") or "pending").lower()
    if status == "created":
        return _fail(
            GATE_DRAFT_ALREADY_PROCESSED,
            f"Reservation already created in wFirma (id={draft.get('wfirma_reservation_id')}).",
            draft_id=draft_id,
            details={"wfirma_reservation_id": draft.get("wfirma_reservation_id", "")},
        )
    if status == "submitting":
        return _fail(
            GATE_DRAFT_ALREADY_SUBMITTING,
            "Another submission is already in progress for this draft.",
            draft_id=draft_id,
            details={"submitted_at": draft.get("submitted_at", "")},
        )
    # status in {pending, failed} → eligible

    # ── Gate 5: lines exist ──────────────────────────────────────────────────
    lines = wfdb.list_reservation_lines(draft_id)
    if not lines:
        return _fail(GATE_NO_LINES, "Draft has no lines.", draft_id=draft_id)

    # ── Gate 6: customer mapping ─────────────────────────────────────────────
    customer = wfdb.get_customer(client_name)
    wfirma_customer_id = (customer or {}).get("wfirma_customer_id") or ""
    if not wfirma_customer_id:
        return _fail(
            GATE_CUSTOMER_NOT_MAPPED,
            f"No wfirma_customer_id mapped for client '{client_name}'.",
            draft_id=draft_id,
        )

    # ── Gate 7: per-line product mapping ─────────────────────────────────────
    unmapped: List[str] = []
    line_payload: List[Dict[str, Any]] = []
    for ln in lines:
        pc = ln["product_code"]
        prod = wfdb.get_product(pc) or {}
        wfirma_product_id = prod.get("wfirma_product_id") or ""
        if not wfirma_product_id:
            unmapped.append(pc)
            continue
        line_payload.append({
            "product_code":     pc,
            "wfirma_good_id":   wfirma_product_id,
            "product_name":     prod.get("product_name_pl") or ln.get("product_name_pl") or pc,
            "qty":              float(ln.get("qty") or 0),
            "unit_price":       float(ln.get("unit_price") or 0),
            "currency":         ln.get("currency") or draft.get("currency") or "USD",
            "unit":             prod.get("unit") or "szt.",
            "stock_ok":         bool(ln.get("stock_ok")),
        })
    if unmapped:
        return _fail(
            GATE_PRODUCTS_NOT_MAPPED,
            f"{len(unmapped)} product(s) have no wfirma_product_id.",
            draft_id=draft_id,
            details={"unmapped_product_codes": unmapped},
        )

    # ── Gate 8: stock for every line ─────────────────────────────────────────
    stock_failures = [p["product_code"] for p in line_payload if not p["stock_ok"]]
    if stock_failures:
        return _fail(
            GATE_STOCK_INSUFFICIENT,
            f"{len(stock_failures)} line(s) do not have stock_ok=True.",
            draft_id=draft_id,
            details={"products_without_stock": stock_failures},
        )

    # ── Gate 9: warehouse_id present in live warehouses ──────────────────────
    warehouse_id = (
        draft.get("warehouse_id")
        or settings.wfirma_warehouse_id
        or ""
    )
    if not warehouse_id:
        return _fail(
            GATE_WAREHOUSE_NOT_FOUND,
            "WFIRMA_WAREHOUSE_ID is not set.",
            draft_id=draft_id,
        )
    if not any(w.get("id") == warehouse_id for w in diag.get("warehouses", [])):
        return _fail(
            GATE_WAREHOUSE_NOT_FOUND,
            f"WFIRMA_WAREHOUSE_ID={warehouse_id} not found in live warehouses.",
            draft_id=draft_id,
            details={"available_warehouse_ids": [w.get("id") for w in diag.get("warehouses", [])]},
        )

    # ── Gate 10: VAT code 23 resolved ────────────────────────────────────────
    if not diag.get("vat_code_23_id"):
        return _fail(
            GATE_VAT_CODE_NOT_FOUND,
            "Could not resolve VAT code 23 in wFirma.",
            draft_id=draft_id,
        )

    # ── All gates passed — atomic transition pending|failed → submitting ────
    if not wfdb.mark_draft_submitting(draft_id):
        # Race: another worker just took it
        return _fail(
            SUBMIT_RACE_LOST,
            "Another submission claimed this draft just now.",
            draft_id=draft_id,
        )

    # Build ReservationRequest — uses wfcli's dataclasses
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    req = wfcli.ReservationRequest(
        batch_id=batch_id,
        client_name=client_name,
        wfirma_contractor_id=wfirma_customer_id,
        wfirma_warehouse_id=warehouse_id,
        date=today,
        currency=draft.get("currency") or "USD",
        description=f"Batch {batch_id} · {client_name}"[:200],
        lines=[
            wfcli.ReservationLine(
                product_code=p["product_code"],
                wfirma_good_id=p["wfirma_good_id"],
                product_name=p["product_name"],
                qty=p["qty"],
                unit_price=p["unit_price"],
                unit=p["unit"],
                currency=p["currency"],
            ) for p in line_payload
        ],
    )

    # ── Submit ───────────────────────────────────────────────────────────────
    result = wfcli.create_reservation(req)
    if result.ok and result.wfirma_reservation_id:
        wfdb.mark_draft_created(draft_id, result.wfirma_reservation_id)
        log.info(
            "wfirma reservation created: batch=%s client=%s wfirma_id=%s",
            batch_id, client_name, result.wfirma_reservation_id,
        )
        return {
            "ok": True,
            "code": GATE_OK,
            "error": "",
            "draft_id": draft_id,
            "wfirma_reservation_id": result.wfirma_reservation_id,
            "details": {},
        }

    # Submission failed at upstream — record + return
    err = result.error or "wFirma create_reservation returned ok=False"
    wfdb.mark_draft_failed(draft_id, err)
    log.warning(
        "wfirma reservation failed: batch=%s client=%s error=%s",
        batch_id, client_name, err,
    )
    return _fail(
        SUBMIT_UPSTREAM_ERROR,
        err,
        draft_id=draft_id,
        details={"raw_response_excerpt": (result.raw_response or "")[:500]},
    )


# ── Stuck-draft reset (admin) ────────────────────────────────────────────────

# Default safety threshold — a draft stuck in submitting longer than this is
# considered abandoned. Operator may override via ?force=true.
STUCK_THRESHOLD_MINUTES = 30


def reset_stuck_draft(draft_id: str, force: bool = False) -> Dict[str, Any]:
    """
    Reset a draft stuck in 'submitting'. Allowed only when:
      - force=True (explicit operator override), OR
      - submitted_at is older than STUCK_THRESHOLD_MINUTES.

    Returns {ok, code, error, draft_id, details}.
    """
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    if not draft:
        return _fail(GATE_DRAFT_NOT_FOUND, f"Draft {draft_id} not found", draft_id=draft_id)

    status = (draft.get("status") or "pending").lower()
    if status != "submitting":
        return _fail(
            "NOT_STUCK",
            f"Draft is in status='{status}', not 'submitting' — nothing to reset.",
            draft_id=draft_id,
            details={"current_status": status},
        )

    if not force:
        ts = draft.get("submitted_at") or ""
        age_min = _age_minutes_iso(ts)
        if age_min is None or age_min < STUCK_THRESHOLD_MINUTES:
            return _fail(
                "TOO_RECENT",
                f"Draft submitted_at age={age_min} min < threshold {STUCK_THRESHOLD_MINUTES} min. "
                "Pass force=true to override.",
                draft_id=draft_id,
                details={"age_minutes": age_min, "threshold_minutes": STUCK_THRESHOLD_MINUTES},
            )

    if not wfdb.reset_stuck_draft(draft_id, reason="forced" if force else "timeout"):
        return _fail(
            "RESET_FAILED",
            "Reset SQL did not affect any row (concurrent transition).",
            draft_id=draft_id,
        )

    return {
        "ok": True,
        "code": GATE_OK,
        "error": "",
        "draft_id": draft_id,
        "details": {"forced": force, "previous_status": status},
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run_live_diagnostic() -> Dict[str, Any]:
    """Re-probe wFirma read endpoints. Returns aggregate result."""
    out: Dict[str, Any] = {
        "ok": False,
        "contractors_ok": False,
        "goods_ok": False,
        "warehouses": [],
        "vat_code_23_id": None,
        "errors": [],
    }
    # contractors/find probe
    try:
        r = wfcli.probe_endpoint("contractors", "find")
        out["contractors_ok"] = bool(r.get("ok"))
        if not r.get("ok"):
            out["errors"].append(f"contractors/find: {r.get('error')}")
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"contractors/find: {exc}")

    # goods/find probe
    try:
        r = wfcli.probe_endpoint("goods", "find")
        out["goods_ok"] = bool(r.get("ok"))
        if not r.get("ok"):
            out["errors"].append(f"goods/find: {r.get('error')}")
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"goods/find: {exc}")

    # warehouses
    try:
        out["warehouses"] = wfcli.list_warehouses()
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"warehouses/find: {exc}")

    # vat 23
    try:
        out["vat_code_23_id"] = wfcli.find_vat_code_id_live(23)
        if not out["vat_code_23_id"]:
            out["errors"].append("vat_code_23_id not resolved")
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"vat_codes/find: {exc}")

    out["ok"] = (
        out["contractors_ok"]
        and out["goods_ok"]
        and bool(out["warehouses"])
        and bool(out["vat_code_23_id"])
    )
    return out


def _age_minutes_iso(iso_ts: str) -> "float | None":
    """Return age in minutes for an ISO-8601 timestamp; None on parse error."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return round(delta.total_seconds() / 60.0, 1)
    except Exception:  # noqa: BLE001
        return None


def _fail(code: str, error: str, *, draft_id: str = "", details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "ok": False,
        "code": code,
        "error": error,
        "draft_id": draft_id,
        "wfirma_reservation_id": "",
        "details": details or {},
    }
