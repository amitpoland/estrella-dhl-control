"""
test_proforma_purchase_transit_bypass.py

Fix 1 regression tests: PURCHASE_TRANSIT stock state must NOT block proforma
when (a) PZ has been created in wFirma OR (b) DHL confirms delivery.

Fix 3 regression test: sales packing reprocess must write rich Polish/English
descriptions (with metal/color/quality) to product_descriptions so that
future ensure_products_for_batch finds them pre-populated.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import document_db  as ddb
from app.services import packing_db   as pdb
from app.services import warehouse_db as wdb
from app.services import wfirma_db    as wfdb
from app.services import wfirma_client as _wc
from app.services import inventory_state_engine as ise


BATCH  = "BATCH_TRANSIT_BYPASS"
CLIENT = "ACME_BYPASS"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _vat_cache():
    _wc._VAT_CODE_ID_CACHE["23"]  = "222"
    _wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    _wc._VAT_CODE_ID_CACHE["EXP"] = "229"
    yield
    for k in ("23", "WDT", "EXP"):
        _wc._VAT_CODE_ID_CACHE.pop(k, None)


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return tmp_path


@pytest.fixture()
def api_client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _batch_dir(storage: Path) -> Path:
    d = storage / "outputs" / BATCH
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_audit(storage: Path, *, pz_doc_id: str = "",
                 carrier_status: str = "") -> None:
    bd = _batch_dir(storage)
    audit: Dict[str, Any] = {
        "batch_id": BATCH,
        "timeline": [],
        "wfirma_export": {"wfirma_pz_doc_id": pz_doc_id},
    }
    if carrier_status:
        audit["carrier_status"] = carrier_status
    (bd / "audit.json").write_text(json.dumps(audit))


# Scan code computed by _compute_scan_code for
# product_code="EJL/BYP-1", pack_sr=1, design_no="JBP001"
# → priority 2: "EJL/BYP-1|sr1|JBP001"
_SCAN_CODE = "EJL/BYP-1|sr1|JBP001"


def _seed_transit_batch(storage: Path) -> None:
    """
    Seed minimum data for the proforma preview to run with one product
    EJL/BYP-1 in PURCHASE_TRANSIT inventory state.
    """
    # Purchase packing line — produces a scan_code via _compute_scan_code.
    pdb.upsert_packing_lines([{
        "batch_id":               BATCH,
        "invoice_no":             "EJL/BYP",
        "invoice_line_position":  1,
        "product_code":           "EJL/BYP-1",
        "design_no":              "JBP001",
        "bag_id":                 "",
        "tray_id":                "",
        "item_type":              "RNG",
        "uom":                    "PCS",
        "quantity":               1.0,
        "gross_weight":           0.0,
        "net_weight":             0.0,
        "metal":                  "",
        "karat":                  "",
        "stone_type":             "",
        "remarks":                "",
        "extracted_confidence":   1.0,
        "requires_manual_review": False,
        "pack_sr":                1.0,
        "unit_price":             0.0,
        "total_value":            0.0,
    }])

    # Transition scan_code to PURCHASE_TRANSIT so _state_codes returns it.
    ise.transition(
        scan_code=_SCAN_CODE,
        to_state=ise.PURCHASE_TRANSIT,
        trigger="pz_generated",
        product_code="EJL/BYP-1",
        design_no="JBP001",
        batch_id=BATCH,
        operator="test",
    )

    # Sales packing lines for CLIENT
    sd = ddb.store_sales_document(
        batch_id=BATCH,
        document_id=str(uuid.uuid4()),
        data={"client_name": CLIENT, "client_ref": "BYP-REF"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name":  CLIENT,
        "client_ref":   "BYP-REF",
        "product_code": "EJL/BYP-1",
        "design_no":    "JBP001",
        "bag_id":       "",
        "quantity":     1.0,
        "remarks":      "",
    }])

    # Invoice line
    ddb.store_invoice_lines("doc-byp", BATCH, [{
        "invoice_no":    "EJL/BYP",
        "line_position": 1,
        "product_code":  "EJL/BYP-1",
        "description":   "Bypass test ring",
        "quantity":      1.0,
        "unit_price":    100.0,
        "total_value":   100.0,
        "currency":      "USD",
        "rate_usd":      100.0,
        "amount_usd":    100.0,
    }])

    # pz_rows.json (batch dir already created by caller via _write_audit)
    _batch_dir(storage)
    (storage / "outputs" / BATCH / "pz_rows.json").write_text(json.dumps([{
        "product_code":   "EJL/BYP-1",
        "unit_netto_pln": 400.0,
        "invoice_no":     "EJL/BYP",
        "description_en": "Bypass test ring",
        "quantity":       1,
        "total_usd":      100.0,
    }]))

    # wFirma product + customer stubs
    wfdb.upsert_product("EJL/BYP-1", wfirma_product_id="88", sync_status="matched")
    wfdb.upsert_customer(CLIENT, wfirma_customer_id="9", country="PL",
                         vat_id="", match_status="matched")


# ── Fix 1 Tests: PURCHASE_TRANSIT bypass ──────────────────────────────────────

def test_purchase_transit_blocked_without_bypass(api_client, storage):
    """
    PURCHASE_TRANSIT with no PZ and no DHL delivery → blocking_reasons
    must contain a transit-related reason. ready=False.
    """
    _seed_transit_batch(storage)
    _write_audit(storage, pz_doc_id="", carrier_status="")

    r = api_client.post(
        f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready"] is False, (
        "Proforma must not be ready when goods are in PURCHASE_TRANSIT "
        "with no PZ and no DHL delivery"
    )
    reasons = body.get("blocking_reasons", [])
    assert any("transit" in reason.lower() or "purchase" in reason.lower()
               for reason in reasons), (
        f"blocking_reasons must mention transit/purchase, got: {reasons}"
    )


def test_purchase_transit_bypassed_when_pz_created(api_client, storage):
    """
    PURCHASE_TRANSIT + wFirma PZ created → NOT blocked by transit.
    The 'purchase_transit' reason must not appear in blocking_reasons.
    """
    _seed_transit_batch(storage)
    _write_audit(storage, pz_doc_id="183167843", carrier_status="")

    r = api_client.post(
        f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth(),
    )
    assert r.status_code == 200, r.text
    body = r.json()

    reasons = body.get("blocking_reasons", [])
    # "purchase_transit" reason specifically must not appear (PZ bypasses it)
    transit_only_reasons = [
        rr for rr in reasons
        if "purchase_transit" in rr.lower()
        and "pz" not in rr.lower()
        and "delivered" not in rr.lower()
    ]
    assert transit_only_reasons == [], (
        f"purchase_transit must not block when wFirma PZ exists; "
        f"blocking_reasons={reasons}"
    )


def test_purchase_transit_bypassed_when_dhl_delivered(api_client, storage):
    """
    PURCHASE_TRANSIT + DHL carrier_status='delivered' → NOT blocked by transit.
    """
    _seed_transit_batch(storage)
    _write_audit(storage, pz_doc_id="", carrier_status="delivered")

    r = api_client.post(
        f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth(),
    )
    assert r.status_code == 200, r.text
    body = r.json()

    reasons = body.get("blocking_reasons", [])
    transit_only_reasons = [
        rr for rr in reasons
        if "purchase_transit" in rr.lower()
        and "pz" not in rr.lower()
        and "delivered" not in rr.lower()
    ]
    assert transit_only_reasons == [], (
        f"purchase_transit must not block when DHL=delivered; "
        f"blocking_reasons={reasons}"
    )


# ── Fix 3 Tests: description pre-population at reprocess ─────────────────────

def _seed_packing_for_desc_test(
    tmp: Path, bid: str, pairs: List[Dict[str, Any]],
) -> None:
    """Seed packing.db with full metal/metal_color for description tests."""
    pdb.init_packing_db(tmp / "packing.db")
    doc_id = pdb.upsert_packing_document(
        batch_id=bid, document_id=f"pd-{bid}",
        source_file_path="/tmp/p.xlsx", invoice_no="INV",
        parser_name="t", parser_version="1",
        source_file_hash=f"h-{bid}",
    )
    pdb.upsert_packing_lines([{
        "packing_document_id": doc_id, "batch_id": bid,
        "invoice_no": "INV", "invoice_line_position": i,
        "product_code": r["product_code"], "design_no": r.get("design_no", ""),
        "metal": r.get("metal", ""), "metal_color": r.get("metal_color", ""),
        "quality_string": r.get("quality_string", ""),
        "batch_no": "", "bag_id": "", "tray_id": "",
        "item_type": r.get("item_type", ""), "uom": "PCS",
        "quantity": 1.0, "gross_weight": 0, "net_weight": 0,
        "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": i, "unit_price": 0.0, "total_value": 0.0,
    } for i, r in enumerate(pairs)])


@pytest.fixture()
def reprocess_client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(_s, "api_key", "", raising=False)
    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")

    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@local"}
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def test_sales_reprocess_writes_rich_description(reprocess_client, monkeypatch):
    """
    After sales packing reprocess, product_descriptions must contain
    a full rich Polish/English description (with metal/color/quality)
    for each resolved product_code — not a generic single-word name.
    """
    cli, tmp = reprocess_client
    bid = "B-DESC-PRE"

    # Seed purchase packing: design J9999 → product code PC-DESC with metal info
    _seed_packing_for_desc_test(tmp, bid, [{
        "product_code": "PC-DESC", "design_no": "J9999",
        "metal": "14KT", "metal_color": "W",
        "quality_string": "GH-SI1", "item_type": "RNG",
    }])

    # Batch output dir + audit.json
    out = tmp / "outputs" / bid
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(
        json.dumps({"batch_id": bid, "timeline": []}), encoding="utf-8",
    )

    # Register sales packing list document
    from app.services import document_db as _ddb
    sid = _ddb.register_document(
        batch_id=bid, document_type="sales_packing_list",
        file_name="sales.xlsx", file_path=str(out / "sales.xlsx"),
        file_hash="h-desc", source="intake",
    )
    _ddb.store_sales_document(
        batch_id=bid, document_id=sid,
        data={"client_name": "ACME", "client_ref": "",
              "document_type": "sales_packing_list",
              "source_file_path": str(out / "sales.xlsx"),
              "extraction_status": "extracted"},
    )
    (out / "sales.xlsx").write_bytes(b"stub")

    # Patch extractor to return a sales row with metal/color/quality fields
    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: (
            [{
                "design_no": "J9999", "quantity": 1.0,
                "unit_price": 50.0, "currency": "USD",
                "item_type": "RNG", "metal": "14KT",
                "metal_color": "W", "quality_string": "GH-SI1",
            }],
            "fake", "1.0", {"failure_reason": None},
        ),
    )

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200, r.text

    # product_descriptions must have a rich entry for PC-DESC
    row = _ddb.get_product_description("PC-DESC")
    assert row is not None, "product_descriptions entry must exist after reprocess"

    pl = row.get("description_pl") or row.get("name_pl") or ""
    # Rich description contains karat or metal info
    assert any(kw in pl.lower() for kw in ("14", "karatow", "gold", "złota")), (
        f"description_pl must contain metal/karat info, got: {pl!r}"
    )
    # Must be a full phrase (not a single word like "pierścionek")
    assert len(pl.split()) >= 3, (
        f"description_pl must be a full phrase, got: {pl!r}"
    )
    # English description must be populated
    en = row.get("description_en") or ""
    assert en, f"description_en must be populated after reprocess, row={row}"


def test_sales_reprocess_does_not_overwrite_manual_description(reprocess_client, monkeypatch):
    """
    product_descriptions entry with source='manual' must never be overwritten
    by the sales-packing pre-population (Fix 3).
    """
    cli, tmp = reprocess_client
    bid = "B-DESC-MANUAL"

    _seed_packing_for_desc_test(tmp, bid, [{
        "product_code": "PC-MAN", "design_no": "JM001",
        "metal": "18KT", "metal_color": "Y",
        "quality_string": "GH-VS", "item_type": "PND",
    }])

    out = tmp / "outputs" / bid
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(
        json.dumps({"batch_id": bid, "timeline": []}), encoding="utf-8",
    )

    from app.services import document_db as _ddb
    _ddb.init_document_db(tmp / "documents.db")

    # Pre-seed a MANUAL description — must not be overwritten
    from app.services.description_engine import set_manual_block
    set_manual_block(
        product_code="PC-MAN", item_type="PND",
        name_pl="Zawieszka ręcznie wpisana",
        description_pl="Zawieszka ręcznie wpisana",
        material_pl="Złoto",
        purpose_pl="Ozdoba",
        description_en="Manually entered pendant",
    )

    sid = _ddb.register_document(
        batch_id=bid, document_type="sales_packing_list",
        file_name="sales_m.xlsx", file_path=str(out / "sales_m.xlsx"),
        file_hash="h-man", source="intake",
    )
    _ddb.store_sales_document(
        batch_id=bid, document_id=sid,
        data={"client_name": "ACME", "client_ref": "",
              "document_type": "sales_packing_list",
              "source_file_path": str(out / "sales_m.xlsx"),
              "extraction_status": "extracted"},
    )
    (out / "sales_m.xlsx").write_bytes(b"stub")

    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: (
            [{
                "design_no": "JM001", "quantity": 1.0,
                "unit_price": 80.0, "currency": "USD",
                "item_type": "PND", "metal": "18KT",
                "metal_color": "Y", "quality_string": "GH-VS",
            }],
            "fake", "1.0", {"failure_reason": None},
        ),
    )

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200, r.text

    row = _ddb.get_product_description("PC-MAN")
    assert row is not None
    assert row["source"] == "manual", (
        f"Manual description source must remain 'manual', got: {row['source']!r}"
    )
    assert row["name_pl"] == "Zawieszka ręcznie wpisana", (
        f"Manual name_pl must not be overwritten, got: {row['name_pl']!r}"
    )
