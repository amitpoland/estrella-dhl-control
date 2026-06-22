"""
test_authority_separation.py — Permanent authority-model separation (2026-06-22).

Pins the rule that import, product master, proforma, warehouse receipt, barcode
traceability, and sales linkage are SEPARATE authorities. Specifically:

  - product creation/adoption is NOT gated on PZ state / SAD (PRODUCT authority)
  - warehouse scan completeness is ADVISORY, not a blocker, for sales linkage
  - reservation readiness is NOT gated on whole-batch warehouse scan completeness
  - warehouse receipt = operator quantity confirmation (new WAREHOUSE authority),
    with derived shortage/overage, audit trail, idempotency, and serial_controlled
  - import PZ surfaces unconfirmed received qty as an ADVISORY, never a blocker

These are regression guards: a warning may not be promoted back into a hard blocker
without an explicit business rule + a new test.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import document_db as ddb
from app.services import wfirma_db as wfdb
from app.services import warehouse_receipt_db as wrdb
from app.services import warehouse_receipt as wrcpt
from app.services import sales_linkage as slink
from app.services import wfirma_reservation as wres


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path, monkeypatch):
    from app.core.config import settings
    root = tmp_path / "authsep"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "storage_root", root, raising=False)
    pdb.init_packing_db(root / "packing.db")
    wdb.init_warehouse_db(root / "warehouse.db")
    ddb.init_document_db(root / "documents.db")
    wfdb.init_wfirma_db(root / "wfirma.db")
    wrdb.init_warehouse_receipt_db(root / "warehouse_receipt.db")
    try:
        from app.services.reservation_db import init_reservation_db
        init_reservation_db(root / "reservation_queue.db")
    except Exception:
        pass
    return root


def _packing_line(batch_id: str, n: int) -> dict:
    return {
        "packing_document_id":   f"pdoc-{batch_id[:6]}-{n}",
        "batch_id":              batch_id,
        "invoice_no":            f"INV/{n:03d}",
        "invoice_line_position": n,
        "product_code":          f"EJL/{n:03d}-1",
        "design_no":             f"SKU-{n}",
        "bag_id": "", "tray_id": "",
        "item_type": "RNG", "uom": "PCS",
        "quantity": 3.0, "gross_weight": 5.0, "net_weight": 5.0,
        "metal": "18KT", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 0.95, "requires_manual_review": False,
        "pack_sr": float(n), "unit_price": 100.0, "total_value": 300.0,
        "batch_no": "",
    }


# ── PRODUCT authority: resolve must not be gated on SAD / PZ-done ────────────

def test_product_resolve_not_guarded_by_sad_or_pz(monkeypatch, storage):
    """
    The product-resolve route must NOT raise WFIRMA_NO_SAD / WFIRMA_PZ_NOT_GENERATED.
    Product creation/adoption is the first authority and runs before customs/PZ.
    """
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", storage, raising=False)

    batch_id = f"PRODTEST_{uuid.uuid4().hex[:8]}"
    out = storage / "outputs" / batch_id
    out.mkdir(parents=True, exist_ok=True)
    # audit WITHOUT zc429 (no SAD) and WITHOUT a completed PZ status.
    (out / "audit.json").write_text(json.dumps({"status": "processing", "inputs": {}}),
                                    encoding="utf-8")
    # pz_rows.json provides the product source (derived from the invoice).
    (out / "pz_rows.json").write_text(json.dumps([
        {"product_code": "EJL/001-1", "quantity": 3, "unit_netto_pln": 10.0,
         "invoice_no": "INV/001", "pl_desc": "Pierścionek złoty", "description_en": "Gold ring"},
    ]), encoding="utf-8")

    import asyncio
    from app.api import routes_wfirma
    # Must complete without raising the customs/PZ guard HTTPException.
    resp = asyncio.get_event_loop().run_until_complete(
        routes_wfirma.wfirma_products_resolve(batch_id)
    )
    body = json.loads(resp.body)
    assert "considered" in body
    assert body["considered"] == 1  # the product source was read despite no SAD/PZ


# ── SALES authority: warehouse scan is advisory, not a blocker ──────────────

def test_sales_linkage_missing_scan_is_advisory_not_blocker(storage):
    batch_id = f"SALES_{uuid.uuid4().hex[:8]}"
    pdb.upsert_packing_lines([_packing_line(batch_id, 1)])
    # sales doc referencing the same SKU, no warehouse scans at all.
    inv_doc = str(uuid.uuid4())
    ddb.store_invoice_lines(inv_doc, batch_id, [{
        "invoice_no": "INV/001", "line_position": 1, "product_code": "EJL/001-1",
        "description": "ring", "quantity": 3.0, "unit_price": 100.0, "total_value": 300.0,
        "currency": "USD", "hs_code": "", "gross_weight": 5.0, "net_weight": 5.0,
        "rate_usd": 100.0, "amount_usd": 300.0, "hsn_code": "",
    }])
    sdoc = ddb.store_sales_document(batch_id, str(uuid.uuid4()),
                                    {"client_name": "C", "client_ref": "R", "sales_doc_no": "SD1"})
    ddb.store_sales_packing_lines(sdoc, batch_id, [{
        "product_code": "SKU-1", "design_no": "SKU-1", "client_name": "C",
        "client_ref": "R", "quantity": 3.0, "bag_id": "", "remarks": "",
    }])

    res = slink.get_sales_linkage(batch_id, mode="final")
    # Scan completeness must NOT block sales invoice readiness…
    joined_blockers = " ".join(res.get("blocking_reasons") or [])
    assert "not yet scanned" not in joined_blockers
    assert "awaiting warehouse confirmation" not in joined_blockers
    # …it is surfaced as an advisory warning instead.
    assert any("awaiting warehouse confirmation" in w for w in res.get("audit_warnings", []))


# ── SALES reservation: not gated on whole-batch scan completeness ───────────

def test_reservation_ready_not_gated_by_missing_scans(monkeypatch, storage):
    batch_id = f"RESV_{uuid.uuid4().hex[:8]}"
    # Two packing lines; NONE scanned → get_missing_scans() non-empty (the
    # recurring "N packing line(s) not yet scanned" signal).
    pdb.upsert_packing_lines([_packing_line(batch_id, 1), _packing_line(batch_id, 2)])
    # A sales doc is required for the preview to exercise the audit gate (no sales
    # doc → empty response).
    inv_doc = str(uuid.uuid4())
    ddb.store_invoice_lines(inv_doc, batch_id, [{
        "invoice_no": "INV/001", "line_position": 1, "product_code": "EJL/001-1",
        "description": "ring", "quantity": 3.0, "unit_price": 100.0, "total_value": 300.0,
        "currency": "USD", "hs_code": "", "gross_weight": 5.0, "net_weight": 5.0,
        "rate_usd": 100.0, "amount_usd": 300.0, "hsn_code": "",
    }])
    sdoc = ddb.store_sales_document(batch_id, str(uuid.uuid4()),
                                    {"client_name": "C", "client_ref": "R", "sales_doc_no": "SD1"})
    ddb.store_sales_packing_lines(sdoc, batch_id, [{
        "product_code": "SKU-1", "design_no": "SKU-1", "client_name": "C",
        "client_ref": "R", "quantity": 3.0, "bag_id": "", "remarks": "",
    }])

    res = wres.get_reservation_preview(batch_id)
    # The scan signal must be an advisory, never a hard batch blocker.
    blockers = (res.get("blocking_reasons") or []) + (res.get("batch_blocking_reasons") or [])
    assert not any("not yet scanned" in b for b in blockers)
    assert any("awaiting warehouse confirmation" in a for a in res.get("batch_advisories", []))
    # audit_clean is retained but is now informational only — it must not be the
    # reason a configured batch cannot be created (proved by the absence of the
    # scan string in any blocker list above).


# ── WAREHOUSE authority: receipt quantity confirmation ──────────────────────

def test_receipt_confirm_persists_shortage_and_overage(storage):
    batch_id = f"RCPT_{uuid.uuid4().hex[:8]}"
    pdb.upsert_packing_lines([_packing_line(batch_id, 1), _packing_line(batch_id, 2)])

    # expected qty per line is 3.0 (from packing). Confirm line 1 short, line 2 over.
    status = wrcpt.confirm_receipt(batch_id, [
        {"invoice_no": "INV/001", "invoice_line_position": "1", "accepted_qty": 2.0},
        {"invoice_no": "INV/002", "invoice_line_position": "2", "accepted_qty": 5.0},
    ], operator="alice", source_documents=["packing.pdf"])

    assert status["confirmed_now"] == 2
    assert status["shortage_lines"] == 1
    assert status["overage_lines"] == 1
    line1 = next(l for l in status["lines"] if l["line_key"] == "INV/001|1")
    assert line1["expected_qty"] == 3.0 and line1["accepted_qty"] == 2.0
    assert line1["shortage_qty"] == 1.0 and line1["overage_qty"] == 0.0
    # audit trail recorded.
    assert len(wrdb.get_events(batch_id)) == 2


def test_receipt_status_summary_and_fully_confirmed(storage):
    batch_id = f"RCPT2_{uuid.uuid4().hex[:8]}"
    pdb.upsert_packing_lines([_packing_line(batch_id, 1), _packing_line(batch_id, 2)])

    s0 = wrcpt.get_receipt_status(batch_id)
    assert s0["total_lines"] == 2 and s0["unconfirmed_lines"] == 2
    assert s0["fully_confirmed"] is False

    wrcpt.confirm_receipt(batch_id, [
        {"invoice_no": "INV/001", "invoice_line_position": "1", "accepted_qty": 3.0},
        {"invoice_no": "INV/002", "invoice_line_position": "2", "accepted_qty": 3.0},
    ], operator="bob")
    s1 = wrcpt.get_receipt_status(batch_id)
    assert s1["unconfirmed_lines"] == 0 and s1["fully_confirmed"] is True


def test_receipt_confirm_is_idempotent(storage):
    batch_id = f"RCPT3_{uuid.uuid4().hex[:8]}"
    pdb.upsert_packing_lines([_packing_line(batch_id, 1)])
    wrcpt.confirm_receipt(batch_id, [
        {"invoice_no": "INV/001", "invoice_line_position": "1", "accepted_qty": 1.0}],
        operator="x")
    wrcpt.confirm_receipt(batch_id, [
        {"invoice_no": "INV/001", "invoice_line_position": "1", "accepted_qty": 3.0}],
        operator="x")
    confs = wrdb.get_confirmations(batch_id)
    assert len(confs) == 1                       # upsert, not duplicate
    assert confs[0]["accepted_qty"] == 3.0       # latest wins
    assert confs[0]["shortage_qty"] == 0.0


def test_serial_controlled_read_from_audit(monkeypatch, storage):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", storage, raising=False)
    batch_id = f"SER_{uuid.uuid4().hex[:8]}"
    out = storage / "outputs" / batch_id
    out.mkdir(parents=True, exist_ok=True)

    (out / "audit.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    assert wrcpt.is_serial_controlled(batch_id) is False

    (out / "audit.json").write_text(json.dumps({"serial_controlled": True}), encoding="utf-8")
    assert wrcpt.is_serial_controlled(batch_id) is True
    assert wrcpt.get_receipt_status(batch_id)["serial_controlled"] is True
