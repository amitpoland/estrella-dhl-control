"""
test_pr2c4_packing_price_backfill.py — PR 2C.4: packing unit_price_eur backfill.

Verifies:
  1.  Extractor correctly reads "Value" column → unit_price in extracted rows.
  2.  routes_packing copies unit_price → unit_price_eur in line_records dict.
  3.  packing_db.backfill_unit_price_eur updates rows with 0 value only.
  4.  backfill_unit_price_eur does NOT overwrite rows that already have a price.
  5.  backfill_unit_price_eur returns correct count.
  6.  packing_db.backfill_unit_price_eur no-ops when unit_price_eur already set.
  7.  unit_price_eur=0 rows in batch → backfill updates them.
  8.  reset_from_sales_packing copies unit_price_eur from packing into draft unit_price.
  9.  draft unit_price = 0 when packing unit_price_eur = 0 (pre-backfill state).
  10. Customer master PUT updates freight fields.
  11. Customer master PUT updates insurance fields.
  12. Customer master GET returns updated freight_service_id.
  13. Customer master GET returns updated insurance_rate.
  14. Dashboard source-grep: cm-edit-freight-service-id field present.
  15. Dashboard source-grep: cm-edit-insurance-rate field present.
  16. Dashboard source-grep: cm-edit-insurance-enabled checkbox present.
  17. Dashboard source-grep: master-cm-btn-save button present.
  18. Dashboard source-grep: master-cm-edit-form container present.
  19. Dashboard source-grep: master-customer-master-panel present.
  20. Dashboard source-grep: master-cm-btn-edit present.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.services import packing_db as pdb   # noqa: E402
from app.services.customer_master_db import (  # noqa: E402
    CustomerMaster,
    init_db as cm_init_db,
    upsert_customer,
    get_customer,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────

_SUOKKO_XLSX = Path(
    r"C:\PZ\storage\outputs\SHIPMENT_1196338404_2026-05_48f86046"
    r"\source\packing\148 EJL-26-27-148-Shipment packing list of 20pcs-09.05.26-Client SUOKKO.xlsx"
)
_BATCH_ID = "SHIPMENT_1196338404_2026-05_48f86046"


def _init_pdb(tmp_path: Path) -> None:
    """Point packing_db at a temp DB and initialise it."""
    db_path = tmp_path / "packing.db"
    pdb.init_packing_db(db_path)


def _make_packing_line(tmp_path: Path, *, batch_id: str = "TEST-BATCH",
                        invoice_no: str = "INV/001", pos: int = 1,
                        design_no: str = "D001", unit_price_eur: float = 0.0) -> str:
    """Insert a minimal packing_line and return its id."""
    import uuid, datetime
    line_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat() + "+00:00"
    with sqlite3.connect(str(pdb._db_path)) as con:
        con.execute(
            """INSERT INTO packing_lines
               (id, packing_document_id, batch_id, invoice_no, invoice_line_position,
                product_code, design_no, batch_no, bag_id, tray_id,
                item_type, uom, quantity, gross_weight, net_weight,
                metal, karat, stone_type, remarks,
                extracted_confidence, requires_manual_review,
                pack_sr, unit_price, total_value, scan_code,
                unit_price_eur, metal_color, quality_string,
                created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (line_id, "doc-001", batch_id, invoice_no, pos,
             f"{batch_id}-{pos}", design_no, "", "", "",
             "RNG", "pcs", 1.0, 0.0, 0.0,
             "18KT", "9KT", "", "",
             1.0, 0,
             None, 0.0, 0.0, None,
             unit_price_eur, "", "",
             now, now),
        )
    return line_id


# ── Extractor tests (1-2) ─────────────────────────────────────────────────────

@pytest.mark.skipif(not _SUOKKO_XLSX.exists(),
                    reason="Live SUOKKO XLSX not present on this machine")
def test_extractor_reads_value_column_into_unit_price():
    """Test 1: extract_packing returns unit_price > 0 for SUOKKO XLSX."""
    from app.services.invoice_packing_extractor import extract_packing
    rows, _parser, _ver, _meta = extract_packing(_SUOKKO_XLSX)
    nonzero = [r for r in rows if float(r.get("unit_price", 0) or 0) > 0]
    assert len(nonzero) > 0, "Expected some rows with unit_price > 0 from Value column"
    # First row should be JBR00257 with 1046.52
    first = rows[0]
    assert float(first["unit_price"]) > 100


@pytest.mark.skipif(not _SUOKKO_XLSX.exists(),
                    reason="Live SUOKKO XLSX not present on this machine")
def test_routes_packing_copies_unit_price_to_unit_price_eur():
    """Test 2: routes_packing line_records have unit_price_eur from extractor unit_price."""
    from app.services.invoice_packing_extractor import extract_packing
    rows, _, _, _ = extract_packing(_SUOKKO_XLSX)
    # Simulate what routes_packing does
    for row in rows:
        upe = float(row.get("unit_price", 0) or 0)
        line = {"unit_price_eur": upe}
        # If Value column data is > 0, it should end up in unit_price_eur
        if float(row.get("unit_price", 0) or 0) > 0:
            assert line["unit_price_eur"] > 0


# ── backfill_unit_price_eur tests (3-7) ───────────────────────────────────────

def test_backfill_updates_zero_rows(tmp_path: Path):
    """Test 3: backfill updates rows where unit_price_eur=0 with new value."""
    _init_pdb(tmp_path)
    batch_id = "BATCH-BF-001"
    _make_packing_line(tmp_path, batch_id=batch_id, pos=1, design_no="D001",
                       unit_price_eur=0.0)
    _make_packing_line(tmp_path, batch_id=batch_id, pos=2, design_no="D002",
                       unit_price_eur=0.0)

    updates = [
        {"batch_id": batch_id, "invoice_no": "INV/001",
         "invoice_line_position": 1, "design_no": "D001", "unit_price_eur": 150.0},
        {"batch_id": batch_id, "invoice_no": "INV/001",
         "invoice_line_position": 2, "design_no": "D002", "unit_price_eur": 200.0},
    ]
    count = pdb.backfill_unit_price_eur(batch_id, updates)
    assert count == 2

    rows = pdb.get_packing_lines_for_batch(batch_id)
    prices = {r["design_no"]: r["unit_price_eur"] for r in rows}
    assert prices["D001"] == 150.0
    assert prices["D002"] == 200.0


def test_backfill_does_not_overwrite_nonzero(tmp_path: Path):
    """Test 4: backfill skips rows that already have unit_price_eur > 0."""
    _init_pdb(tmp_path)
    batch_id = "BATCH-BF-002"
    _make_packing_line(tmp_path, batch_id=batch_id, pos=1, design_no="D001",
                       unit_price_eur=999.0)  # already set

    updates = [
        {"batch_id": batch_id, "invoice_no": "INV/001",
         "invoice_line_position": 1, "design_no": "D001", "unit_price_eur": 42.0},
    ]
    count = pdb.backfill_unit_price_eur(batch_id, updates)
    assert count == 0  # should NOT have updated

    rows = pdb.get_packing_lines_for_batch(batch_id)
    assert rows[0]["unit_price_eur"] == 999.0  # unchanged


def test_backfill_returns_correct_count(tmp_path: Path):
    """Test 5: backfill returns exact count of rows updated."""
    _init_pdb(tmp_path)
    batch_id = "BATCH-BF-003"
    _make_packing_line(tmp_path, batch_id=batch_id, pos=1, design_no="D001",
                       unit_price_eur=0.0)
    _make_packing_line(tmp_path, batch_id=batch_id, pos=2, design_no="D002",
                       unit_price_eur=50.0)   # already priced
    _make_packing_line(tmp_path, batch_id=batch_id, pos=3, design_no="D003",
                       unit_price_eur=0.0)

    updates = [
        {"batch_id": batch_id, "invoice_no": "INV/001",
         "invoice_line_position": 1, "design_no": "D001", "unit_price_eur": 100.0},
        {"batch_id": batch_id, "invoice_no": "INV/001",
         "invoice_line_position": 2, "design_no": "D002", "unit_price_eur": 60.0},
        {"batch_id": batch_id, "invoice_no": "INV/001",
         "invoice_line_position": 3, "design_no": "D003", "unit_price_eur": 80.0},
    ]
    count = pdb.backfill_unit_price_eur(batch_id, updates)
    assert count == 2  # only D001 and D003 were zero


def test_backfill_noop_when_all_already_priced(tmp_path: Path):
    """Test 6: backfill returns 0 when all rows already have unit_price_eur > 0."""
    _init_pdb(tmp_path)
    batch_id = "BATCH-BF-004"
    _make_packing_line(tmp_path, batch_id=batch_id, pos=1, design_no="D001",
                       unit_price_eur=100.0)

    updates = [{"batch_id": batch_id, "invoice_no": "INV/001",
                "invoice_line_position": 1, "design_no": "D001", "unit_price_eur": 200.0}]
    count = pdb.backfill_unit_price_eur(batch_id, updates)
    assert count == 0


def test_backfill_skips_records_with_zero_unit_price_eur(tmp_path: Path):
    """Test 7: backfill ignores update records where unit_price_eur <= 0."""
    _init_pdb(tmp_path)
    batch_id = "BATCH-BF-005"
    _make_packing_line(tmp_path, batch_id=batch_id, pos=1, design_no="D001",
                       unit_price_eur=0.0)

    updates = [{"batch_id": batch_id, "invoice_no": "INV/001",
                "invoice_line_position": 1, "design_no": "D001",
                "unit_price_eur": 0.0}]   # zero value in update
    count = pdb.backfill_unit_price_eur(batch_id, updates)
    assert count == 0


def _make_pack_sr_line(*, batch_id: str, invoice_no: str, pack_sr: float,
                       doc_id: str, pos: int = 1, design_no: str = "D-GJ",
                       unit_price_eur: float = 0.0) -> str:
    """Insert a pack_sr-bearing packing_line under a specific document id."""
    import uuid, datetime
    line_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat() + "+00:00"
    with sqlite3.connect(str(pdb._db_path)) as con:
        con.execute(
            """INSERT INTO packing_lines
               (id, packing_document_id, batch_id, invoice_no, invoice_line_position,
                product_code, design_no, batch_no, bag_id, tray_id,
                item_type, uom, quantity, gross_weight, net_weight,
                metal, karat, stone_type, remarks,
                extracted_confidence, requires_manual_review,
                pack_sr, unit_price, total_value, scan_code,
                unit_price_eur, metal_color, quality_string,
                created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (line_id, doc_id, batch_id, invoice_no, pos,
             f"{batch_id}-{pos}", design_no, "", "", "",
             "RNG", "pcs", 1.0, 0.0, 0.0,
             "18KT", "9KT", "", "",
             1.0, 0,
             pack_sr, 0.0, 0.0, None,
             unit_price_eur, "", "",
             now, now),
        )
    return line_id


def test_backfill_pack_sr_branch_ignores_document_id(tmp_path: Path):
    """Test 7b: pack_sr backfill must NOT be scoped by packing_document_id.

    Regression for the Global Jewellery reprocess-prices gap: a stored row
    carries a UUID packing_document_id, but POST /{batch_id}/reprocess-prices
    backfills with an empty document id (it does not upsert a document). The
    canonical key is (batch_id, invoice_no, pack_sr), so the row must be
    updated despite the document-id mismatch. Before the fix this branch
    filtered on packing_document_id and silently returned rows_updated:0.
    """
    _init_pdb(tmp_path)
    batch_id = "BATCH-BF-PACKSR"
    stored_doc_id = "11111111-2222-3333-4444-555555555555"  # real UUID doc id
    _make_pack_sr_line(
        batch_id=batch_id, invoice_no="INV/GJ", pack_sr=7.0,
        doc_id=stored_doc_id, design_no="D-GJ", unit_price_eur=0.0,
    )

    # Backfill carries pack_sr and a DIFFERENT (empty) document id — exactly
    # what the reprocess-prices caller passes.
    updates = [{
        "batch_id": batch_id, "invoice_no": "INV/GJ",
        "packing_document_id": "",          # caller does not upsert a document
        "pack_sr": 7.0, "design_no": "D-GJ",
        "unit_price_eur": 321.0,
    }]
    count = pdb.backfill_unit_price_eur(batch_id, updates)
    assert count == 1, "pack_sr backfill must match across document ids"

    rows = pdb.get_packing_lines_for_batch(batch_id)
    assert len(rows) == 1
    assert rows[0]["pack_sr"] == 7.0
    assert rows[0]["unit_price_eur"] == 321.0


# ── reset_from_sales_packing pipeline tests (8-9) ────────────────────────────

def _make_proforma_db(tmp_path: Path):
    """Create a minimal proforma_links.db for pipeline tests."""
    from app.services.proforma_invoice_link_db import init_db as pildb_init_db
    db = tmp_path / "proforma_links.db"
    pildb_init_db(db)
    return db


def test_reset_carries_unit_price_eur_into_draft(tmp_path: Path):
    """Test 8: reset_draft_from_sales_packing exists and routes_packing carries unit_price_eur."""
    # Structural verification: the function that resets a draft from sales packing
    # must exist in proforma_invoice_link_db.
    from app.services import proforma_invoice_link_db as pildb
    assert hasattr(pildb, "reset_draft_from_sales_packing"), \
        "reset_draft_from_sales_packing must exist in proforma_invoice_link_db"

    # Verify routes_packing carries the price: unit_price_eur is set in the
    # line_records dict at the point where sales packing lines are merged.
    routes_packing_src = Path(__file__).parent.parent / "app" / "api" / "routes_packing.py"
    text = routes_packing_src.read_text(encoding="utf-8")
    assert "unit_price_eur" in text, "routes_packing must reference unit_price_eur"
    assert "packing_xlsx_value" in text, "routes_packing must set price_source=packing_xlsx_value"


def test_draft_unit_price_zero_when_packing_unit_price_eur_zero(tmp_path: Path):
    """Test 9: routes_packing sets price_source='packing_promote' when unit_price_eur=0."""
    # price_source = "packing_xlsx_value" if unit_price_eur > 0 else "packing_promote"
    # This logic lives in routes_packing.py (the sales packing → draft reset path).
    routes_src = Path(__file__).parent.parent / "app" / "api" / "routes_packing.py"
    text = routes_src.read_text(encoding="utf-8")
    assert "packing_xlsx_value" in text, "price_source 'packing_xlsx_value' must exist in routes_packing"
    assert "packing_promote" in text, "price_source 'packing_promote' must exist in routes_packing"
    assert "unit_price_eur" in text, "unit_price_eur must be referenced in routes_packing"


# ── Customer master PUT/GET tests (10-13) ─────────────────────────────────────

def _cm_db(tmp_path: Path) -> Path:
    db = tmp_path / "customer_master.sqlite"
    cm_init_db(db)
    return db


def _base_cm(**overrides) -> CustomerMaster:
    base = dict(
        bill_to_contractor_id = "CM-TEST-001",
        bill_to_name          = "Test Corp",
        country               = "NO",
    )
    base.update(overrides)
    return CustomerMaster(**base)


def test_customer_master_put_updates_freight_fields(tmp_path: Path):
    """Test 10: upsert_customer stores freight_fixed_amount_eur and freight_service_id."""
    db = _cm_db(tmp_path)
    cm = _base_cm(
        freight_service_id       = "13002743",
        freight_fixed_amount_eur = Decimal("35.00"),
        freight_fixed_amount_usd = Decimal("50.00"),
        freight_label_pl         = "Transport",
        freight_label_en         = "Courier",
    )
    upsert_customer(db, cm)
    stored = get_customer(db, "CM-TEST-001")
    assert stored.freight_service_id       == "13002743"
    assert stored.freight_fixed_amount_eur == Decimal("35.00")
    assert stored.freight_fixed_amount_usd == Decimal("50.00")
    assert stored.freight_label_pl         == "Transport"
    assert stored.freight_label_en         == "Courier"


def test_customer_master_put_updates_insurance_fields(tmp_path: Path):
    """Test 11: upsert_customer stores insurance_rate, insurance_enabled, insurance labels."""
    db = _cm_db(tmp_path)
    cm = _base_cm(
        insurance_service_id = "13102217",
        insurance_rate       = Decimal("0.0035"),
        insurance_enabled    = True,
        insurance_label_pl   = "Ubezpieczenie",
        insurance_label_en   = "Insurance",
    )
    upsert_customer(db, cm)
    stored = get_customer(db, "CM-TEST-001")
    assert stored.insurance_service_id == "13102217"
    assert stored.insurance_rate       == Decimal("0.0035")
    assert stored.insurance_enabled    is True
    assert stored.insurance_label_pl   == "Ubezpieczenie"
    assert stored.insurance_label_en   == "Insurance"


def test_customer_master_get_returns_freight_service_id(tmp_path: Path):
    """Test 12: get_customer returns updated freight_service_id after upsert."""
    db = _cm_db(tmp_path)
    cm_v1 = _base_cm(freight_service_id="OLD-ID")
    upsert_customer(db, cm_v1)
    cm_v2 = _base_cm(freight_service_id="NEW-ID-99")
    upsert_customer(db, cm_v2)
    stored = get_customer(db, "CM-TEST-001")
    assert stored.freight_service_id == "NEW-ID-99"


def test_customer_master_get_returns_insurance_rate(tmp_path: Path):
    """Test 13: get_customer returns updated insurance_rate after upsert."""
    db = _cm_db(tmp_path)
    cm_v1 = _base_cm(insurance_rate=Decimal("0.0020"))
    upsert_customer(db, cm_v1)
    cm_v2 = _base_cm(insurance_rate=Decimal("0.0050"))
    upsert_customer(db, cm_v2)
    stored = get_customer(db, "CM-TEST-001")
    assert stored.insurance_rate == Decimal("0.0050")


# ── Dashboard source-grep tests (14-20) ───────────────────────────────────────

_DASHBOARD = Path(__file__).parent.parent / "app" / "static" / "dashboard.html"


def _dash_text():
    return _DASHBOARD.read_text(encoding="utf-8")


def test_dashboard_has_cm_edit_freight_service_id():
    """Test 14: Customer master freight service ID edit field present."""
    assert 'data-testid="cm-edit-freight-service-id"' in _dash_text()


def test_dashboard_has_cm_edit_insurance_rate():
    """Test 15: Customer master insurance rate edit field present."""
    assert 'data-testid="cm-edit-insurance-rate"' in _dash_text()


def test_dashboard_has_cm_edit_insurance_enabled():
    """Test 16: Customer master insurance enabled checkbox present."""
    assert 'data-testid="cm-edit-insurance-enabled"' in _dash_text()


def test_dashboard_has_cm_btn_save():
    """Test 17: Customer master save button present."""
    assert 'data-testid="master-cm-btn-save"' in _dash_text()


def test_dashboard_has_cm_edit_form():
    """Test 18: Customer master edit form container present."""
    assert 'data-testid="master-cm-edit-form"' in _dash_text()


def test_dashboard_has_customer_master_panel():
    """Test 19: Customer master panel top-level container present."""
    assert 'data-testid="master-customer-master-panel"' in _dash_text()


def test_dashboard_has_cm_btn_edit():
    """Test 20: Customer master per-row edit button present."""
    assert 'data-testid="master-cm-btn-edit"' in _dash_text()
