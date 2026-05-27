"""
test_wfirma_pz_supplier_resolution.py
======================================
Verifies per-shipment supplier authority for wFirma PZ creation.

Tests
-----
1. Estrella supplier name resolves to wfirma_id=38142296 via supplier master
2. Global Jewellery supplier name resolves to wfirma_id=71554001 via supplier master
3. Unknown supplier falls back to env setting with risk flag
4. Unknown supplier + no env → SUPPLIER_NOT_RESOLVED
5. Unresolved supplier blocks pz_create with PZ_CREATE_SUPPLIER_NOT_RESOLVED
6. Resolved supplier contractor_id is used in PZ XML (not env global)
7. PZ preview returns supplier_resolution_source field
8. suppliers_db.find_by_name_normalized handles case/punctuation variants
9. PZ PDF download has X-PZ-PDF-Source=generated-from-api-data header
10. PZ PDF download filename includes _GENERATED_PREVIEW
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── suppliers_db helpers ──────────────────────────────────────────────────────

def _make_suppliers_db(tmp_path: Path) -> Path:
    """Create an in-memory suppliers.sqlite with two known suppliers."""
    from app.services import suppliers_db as sdb
    db = tmp_path / "suppliers.sqlite"
    sdb.init_db(db)
    with sqlite3.connect(str(db)) as conn:
        now = "2026-01-01T00:00:00+00:00"
        conn.execute("""
            INSERT INTO suppliers
                (supplier_code, name, country, vat_id, eori, address,
                 contact_email, contact_phone, active, notes, wfirma_id,
                 created_at, updated_at)
            VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, 1, NULL, ?, ?, ?)
        """, ("WF-38142296-ESTRELLA", "ESTRELLA JEWELS LLP.", "IN",
              "38142296", now, now))
        conn.execute("""
            INSERT INTO suppliers
                (supplier_code, name, country, vat_id, eori, address,
                 contact_email, contact_phone, active, notes, wfirma_id,
                 created_at, updated_at)
            VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, 1, NULL, ?, ?, ?)
        """, ("WF-71554001-GLOBAL", "Global Jewellery Pvt. Ltd.", "IN",
              "71554001", now, now))
        conn.commit()
    return db


# ── Test 1: Estrella resolves to 38142296 via master ─────────────────────────

def test_estrella_supplier_resolves_from_master(tmp_path):
    db = _make_suppliers_db(tmp_path)
    from app.services import suppliers_db as sdb

    result = sdb.find_by_name_normalized(db, "Estrella Jewels LLP")
    assert result is not None, "Supplier not found in master"
    assert result.wfirma_id == "38142296"
    assert result.name == "ESTRELLA JEWELS LLP."


# ── Test 2: Global Jewellery resolves to 71554001 via master ─────────────────

def test_global_jewellery_resolves_from_master(tmp_path):
    db = _make_suppliers_db(tmp_path)
    from app.services import suppliers_db as sdb

    # Various name forms that should all normalise to the same target
    for name in [
        "Global Jewellery Pvt. Ltd.",
        "GLOBAL JEWELLERY PVT. LTD.",
        "global jewellery pvt ltd",
        "Global Jewellery Pvt Ltd",
    ]:
        result = sdb.find_by_name_normalized(db, name)
        assert result is not None, f"Not found for name={name!r}"
        assert result.wfirma_id == "71554001", f"Wrong ID for name={name!r}"


# ── Test 3: _normalize_name handles case / punctuation ───────────────────────

def test_normalize_name_strips_punctuation_and_case():
    from app.services.suppliers_db import _normalize_name

    assert _normalize_name("ESTRELLA JEWELS LLP.") == "estrella jewels llp"
    assert _normalize_name("Estrella Jewels LLP")  == "estrella jewels llp"
    assert _normalize_name("estrella jewels llp.")  == "estrella jewels llp"
    # Punctuation is replaced with space then whitespace is collapsed
    assert _normalize_name("Global Jewellery Pvt. Ltd.") == "global jewellery pvt ltd"
    # Both forms normalise to the same string
    assert _normalize_name("Global Jewellery Pvt. Ltd.") == _normalize_name("Global Jewellery Pvt. Ltd")


# ── Test 4: find_by_name returns None for unknown name ───────────────────────

def test_find_by_name_returns_none_for_unknown(tmp_path):
    db = _make_suppliers_db(tmp_path)
    from app.services import suppliers_db as sdb

    result = sdb.find_by_name_normalized(db, "ACME Diamonds Unknown Corp.")
    assert result is None


# ── Test 5: resolve_supplier_contractor_id — master hit ──────────────────────

def test_resolve_supplier_uses_master(tmp_path):
    db = _make_suppliers_db(tmp_path)

    audit = {
        "verification": {"invoice_exporter_name": "Estrella Jewels LLP"},
    }

    mock_settings = MagicMock()
    mock_settings.storage_root   = str(tmp_path)
    mock_settings.wfirma_supplier_contractor_id = "71554001"  # wrong global — should be ignored

    with patch("app.api.routes_wfirma.settings", mock_settings):
        from app.api.routes_wfirma import resolve_supplier_contractor_id_for_batch
        cid, name, source, risks = resolve_supplier_contractor_id_for_batch(audit)

    assert cid    == "38142296",       f"Expected 38142296, got {cid!r}"
    assert source == "supplier_master"
    assert "supplier_from_env_fallback" not in risks


# ── Test 6: resolve_supplier — unknown → env fallback with risk flag ──────────

def test_resolve_supplier_falls_back_to_env_for_unknown(tmp_path):
    db = _make_suppliers_db(tmp_path)

    audit = {
        "verification": {"invoice_exporter_name": "ACME Diamonds Unknown Corp."},
    }

    mock_settings = MagicMock()
    mock_settings.storage_root   = str(tmp_path)
    mock_settings.wfirma_supplier_contractor_id = "71554001"

    with patch("app.api.routes_wfirma.settings", mock_settings):
        from app.api.routes_wfirma import resolve_supplier_contractor_id_for_batch
        cid, name, source, risks = resolve_supplier_contractor_id_for_batch(audit)

    assert cid    == "71554001"
    assert source == "env_fallback"
    assert "supplier_from_env_fallback" in risks


# ── Test 7: resolve_supplier — unknown + no env → SUPPLIER_NOT_RESOLVED ───────

def test_resolve_supplier_unresolved_when_no_master_and_no_env(tmp_path):
    db = _make_suppliers_db(tmp_path)

    audit = {
        "verification": {"invoice_exporter_name": "ACME Diamonds Unknown Corp."},
    }

    mock_settings = MagicMock()
    mock_settings.storage_root   = str(tmp_path)
    mock_settings.wfirma_supplier_contractor_id = ""   # env not configured

    with patch("app.api.routes_wfirma.settings", mock_settings):
        from app.api.routes_wfirma import resolve_supplier_contractor_id_for_batch
        cid, name, source, risks = resolve_supplier_contractor_id_for_batch(audit)

    assert cid    == ""
    assert source == "SUPPLIER_NOT_RESOLVED"
    assert "SUPPLIER_NOT_RESOLVED" in risks


# ── Test 8: pz_create blocks with PZ_CREATE_SUPPLIER_NOT_RESOLVED ─────────────

def test_pz_create_blocks_on_unresolved_supplier(tmp_path):
    db = _make_suppliers_db(tmp_path)

    audit = {
        "batch_id": "TEST_UNRESOLVED_001",
        "status":   "processed",
        "customs_declaration": {"mrn": "26PL999", "clearance_date": "2026-05-01"},
        "inputs":        {},
        "wfirma_export": {},
        "verification":  {"invoice_exporter_name": "ACME Diamonds Unknown Corp."},
    }

    def _mock_settings():
        m = MagicMock()
        m.wfirma_create_pz_allowed      = True
        m.wfirma_supplier_contractor_id = ""       # no env fallback
        m.wfirma_warehouse_id           = "347088"
        m.storage_root                  = str(tmp_path)
        return m

    import asyncio
    from fastapi import HTTPException
    from app.api.routes_wfirma import wfirma_pz_create

    with (
        patch("app.api.routes_wfirma.settings", _mock_settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz") as mock_create,
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(wfirma_pz_create("TEST_UNRESOLVED_001"))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "PZ_CREATE_SUPPLIER_NOT_RESOLVED"
    mock_create.assert_not_called()


# ── Test 9: pz_create uses resolved contractor_id (not global env) ────────────

def test_pz_create_uses_resolved_supplier_not_global_env(tmp_path):
    """PZ XML must use 38142296 (from master) not 71554001 (from env)."""
    db = _make_suppliers_db(tmp_path)

    audit = {
        "batch_id": "TEST_SUPPLIER_AUTH_001",
        "status":   "processed",
        "customs_declaration": {"mrn": "26PL9998", "clearance_date": "2026-05-01"},
        "inputs":        {},
        "wfirma_export": {},
        "verification":  {"invoice_exporter_name": "Estrella Jewels LLP"},
    }

    rows = [{"product_code": "EJL/26-27/001-1", "item_type": "wisiorek",
             "description_en": "Pendant", "pl_desc": "Wisiorek",
             "quantity": 1.0, "unit_netto_pln": 100.0, "invoice_no": "EJL/26-27/001"}]
    products = [{"product_code": "EJL/26-27/001-1", "wfirma_product_id": "99991111"}]

    def _mock_settings():
        m = MagicMock()
        m.wfirma_create_pz_allowed      = True
        m.wfirma_supplier_contractor_id = "71554001"  # WRONG global — master should win
        m.wfirma_warehouse_id           = "347088"
        m.storage_root                  = str(tmp_path)
        return m

    from app.services.wfirma_client import PZResult, PZRequest
    captured_requests: list[PZRequest] = []

    def _fake_create(req: PZRequest) -> PZResult:
        captured_requests.append(req)
        return PZResult(ok=True, wfirma_pz_doc_id="PZ_NEW_55555")

    import asyncio
    from app.api.routes_wfirma import wfirma_pz_create

    # Use a real tmp_path so _pz_write_lock can create a proper lockfile.
    # Pass x_operator=None directly to bypass FastAPI's Header() default.
    batch_output = tmp_path / "batch_output"
    batch_output.mkdir()

    with (
        patch("app.api.routes_wfirma.settings", _mock_settings()),
        patch("app.api.routes_wfirma.get_output_dir", return_value=batch_output),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma.wfirma_db.list_products", return_value=products),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz", side_effect=_fake_create),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=MagicMock(ok=False, error="test")),
        patch("app.api.routes_wfirma._patch_pz_doc_id", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        asyncio.get_event_loop().run_until_complete(
            wfirma_pz_create("TEST_SUPPLIER_AUTH_001", x_operator=None)
        )

    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.contractor_id == "38142296", (
        f"Expected contractor_id=38142296 (from supplier master), "
        f"got {req.contractor_id!r} (env fallback was used)"
    )


# ── Test 10: PZ preview returns supplier_resolution_source field ──────────────

def test_pz_preview_includes_supplier_resolution_source(tmp_path):
    db = _make_suppliers_db(tmp_path)

    audit = {
        "batch_id": "TEST_PREV_001",
        "status":   "partial",
        "customs_declaration": {"mrn": "26PL0001", "clearance_date": "2026-05-01"},
        "inputs":        {},
        "wfirma_export": {},
        "verification":  {"invoice_exporter_name": "Estrella Jewels LLP"},
    }

    rows = [{"product_code": "EJL/26-27/001-1", "item_type": "wisiorek",
             "description_en": "Pendant", "pl_desc": "Wisiorek",
             "quantity": 1.0, "unit_netto_pln": 100.0, "invoice_no": "EJL/26-27/001"}]
    products = [{"product_code": "EJL/26-27/001-1", "wfirma_product_id": "99991111"}]

    def _mock_settings():
        m = MagicMock()
        m.wfirma_create_pz_allowed      = True
        m.wfirma_supplier_contractor_id = "71554001"
        m.wfirma_warehouse_id           = "347088"
        m.storage_root                  = str(tmp_path)
        return m

    import asyncio
    from app.api.routes_wfirma import wfirma_pz_preview

    with (
        patch("app.api.routes_wfirma.settings", _mock_settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma._collect_pz_preview_blockers", return_value=[]),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma.wfirma_db.list_products", return_value=products),
    ):
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_pz_preview("TEST_PREV_001")
        )

    body = json.loads(result.body)
    assert "supplier_resolution_source" in body, "supplier_resolution_source missing from preview"
    assert body["supplier_resolution_source"] == "supplier_master"
    assert body["supplier_wfirma_id"] == "38142296"
    blocker_codes = [b.get("code") for b in body.get("blockers", [])]
    assert "SUPPLIER_NOT_RESOLVED" not in blocker_codes


# ── Test 11: PZ preview blocks when supplier not in master + no env ───────────

def test_pz_preview_blocker_when_supplier_unresolved(tmp_path):
    db = _make_suppliers_db(tmp_path)

    audit = {
        "batch_id": "TEST_PREV_UNRESOLVED",
        "status":   "partial",
        "customs_declaration": {"mrn": "26PL9999", "clearance_date": "2026-05-01"},
        "inputs":        {},
        "wfirma_export": {},
        "verification":  {"invoice_exporter_name": "ACME Unknown Corp."},
    }

    rows = [{"product_code": "EJL/26-27/001-1", "item_type": "wisiorek",
             "description_en": "Pendant", "pl_desc": "Wisiorek",
             "quantity": 1.0, "unit_netto_pln": 100.0, "invoice_no": "EJL/26-27/001"}]
    products = [{"product_code": "EJL/26-27/001-1", "wfirma_product_id": "99991111"}]

    def _mock_settings():
        m = MagicMock()
        m.wfirma_create_pz_allowed      = True
        m.wfirma_supplier_contractor_id = ""   # no env fallback
        m.wfirma_warehouse_id           = "347088"
        m.storage_root                  = str(tmp_path)
        return m

    import asyncio
    from app.api.routes_wfirma import wfirma_pz_preview

    with (
        patch("app.api.routes_wfirma.settings", _mock_settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma._collect_pz_preview_blockers", return_value=[]),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma.wfirma_db.list_products", return_value=products),
    ):
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_pz_preview("TEST_PREV_UNRESOLVED")
        )

    body = json.loads(result.body)
    blocker_codes = [b.get("code") for b in body.get("blockers", [])]
    assert "SUPPLIER_NOT_RESOLVED" in blocker_codes, f"Expected SUPPLIER_NOT_RESOLVED in blockers: {body.get('blockers')}"
    assert body.get("supplier_wfirma_id") == ""
    assert body.get("would_create_pz") is False


# ── Test 12: PZ PDF response has generated-preview header and filename ─────────

def test_pz_pdf_response_has_generated_source_header():
    """PDF endpoint must expose X-PZ-PDF-Source and _GENERATED_PREVIEW in filename."""
    import asyncio

    audit = {
        "wfirma_export": {"wfirma_pz_doc_id": "186437155"},
    }

    from app.services.wfirma_client import PZFetchResult
    fake_fetch = PZFetchResult(
        ok=True,
        pz_doc_id="186437155",
        pz_number="PZ 10/5/2026",
        raw_response="""<?xml version="1.0" encoding="UTF-8"?>
<api><status><code>OK</code></status><warehouse_documents>
  <warehouse_document>
    <id>186437155</id>
    <fullnumber>PZ 10/5/2026</fullnumber>
    <date>2026-05-27</date>
    <netto>219741.79</netto>
    <brutto>270282.40</brutto>
    <currency>PLN</currency>
    <contractor><id>38142296</id><altname>ESTRELLA JEWELS LLP.</altname></contractor>
    <warehouse><id>347088</id></warehouse>
    <description>AWB:9198333502</description>
    <warehouse_document_contents></warehouse_document_contents>
  </warehouse_document>
</warehouse_documents></api>""",
    )

    from app.api.routes_wfirma import wfirma_pz_document_pdf

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz", return_value=fake_fetch),
    ):
        try:
            response = asyncio.get_event_loop().run_until_complete(
                wfirma_pz_document_pdf("TEST_PDF_BATCH")
            )
        except Exception as exc:
            # reportlab may not be installed in test env — skip PDF content check
            if "reportlab" in str(exc).lower() or "pdf" in str(exc).lower():
                pytest.skip(f"reportlab not available: {exc}")
            raise

    assert response.status_code == 200
    headers = dict(response.headers)
    assert headers.get("x-pz-pdf-source") == "generated-from-api-data", (
        f"Missing or wrong X-PZ-PDF-Source header: {headers}"
    )
    content_disposition = headers.get("content-disposition", "")
    assert "_GENERATED_PREVIEW" in content_disposition, (
        f"Filename should contain _GENERATED_PREVIEW: {content_disposition!r}"
    )
    assert headers.get("cache-control", "").startswith("no-store"), (
        f"Cache-Control should be no-store: {headers.get('cache-control')!r}"
    )
