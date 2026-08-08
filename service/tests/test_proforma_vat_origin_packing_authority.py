"""Proforma + Commercial Packing shared authority — VAT / origin / weights.

Regression pins for Draft #82 class defects:
  - PL domestic → 23% (not hardcoded WDT 0%)
  - EU B2B → WDT 0%; non-EU → EXP 0%
  - Origin from Product Master ISO (India → IN); missing stays explicit
  - Gross/net from packing else invoice_lines; colour stone from Sales Packing
  - Editable repair normalizes vat_mode 222 → 23/domestic; posted untouched
  - Preview/PDF JSX consume docData VAT (no hardcoded WDT)
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

BATCH = "BATCH_VAT_ORIGIN_AUTH"
CID = "90000001"
CLIENT = "VAT Origin Client"
NOW = "2026-08-08T00:00:00Z"

_DOC = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "estrella-doc-proforma.jsx"
_DETAIL = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)

    from app.services import customer_master_db as cmdb
    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    from app.services import proforma_invoice_link_db as pildb

    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    cmdb.init_db(tmp_path / "customer_master.sqlite")
    return tmp_path


def _insert_draft(
    db: Path,
    *,
    draft_state: str = "draft",
    vat_code: str | None = None,
    vat_context: str | None = None,
    client_name: str = CLIENT,
) -> int:
    from app.services import proforma_invoice_link_db as pildb

    pildb.init_db(db)
    with sqlite3.connect(str(db)) as con:
        pildb._ensure_drafts_table(con)
        cur = con.execute(
            """
            INSERT INTO proforma_drafts
                (batch_id, client_name, status, currency, exchange_rate,
                 source_lines_json, editable_lines_json, service_charges_json,
                 buyer_override_json, ship_to_override_json, payment_terms_json,
                 remarks, draft_state, draft_version, created_at, updated_at,
                 client_contractor_id, vat_code, vat_context)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                BATCH, client_name, draft_state, "EUR", None,
                "[]", "[]", "[]", "{}", "{}", "{}",
                "", draft_state, 1, NOW, NOW, CID,
                vat_code, vat_context,
            ),
        )
        con.commit()
        return int(cur.lastrowid)


def _upsert_cm(storage: Path, *, country: str = "PL", vat_mode: int = 222) -> None:
    from app.services import customer_master_db as cmdb
    from app.services.customer_master_db import CustomerMaster

    cmdb.upsert_customer(
        storage / "customer_master.sqlite",
        CustomerMaster(
            bill_to_contractor_id=CID,
            bill_to_name=CLIENT,
            country=country,
            vat_mode=vat_mode,
        ),
    )


def _insert_invoice_line(
    storage: Path,
    *,
    product_code: str,
    gross_weight: float,
    net_weight: float,
    quantity: float = 2.0,
) -> None:
    doc_id = str(uuid.uuid4())
    line_id = str(uuid.uuid4())
    with sqlite3.connect(str(storage / "documents.db")) as con:
        con.execute(
            """
            INSERT INTO shipment_documents
                (id, batch_id, document_type, file_name, created_at, updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (doc_id, BATCH, "invoice", "inv.pdf", NOW, NOW),
        )
        con.execute(
            """
            INSERT INTO invoice_lines
                (id, document_id, batch_id, invoice_no, line_position,
                 product_code, description, quantity, unit_price, total_value,
                 currency, hs_code, gross_weight, net_weight, rate_usd, amount_usd,
                 hsn_code, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                line_id, doc_id, BATCH, "INV/1", 1,
                product_code, "desc", quantity, 10.0, 20.0,
                "EUR", "", gross_weight, net_weight, 0.0, 0.0,
                "", NOW,
            ),
        )
        con.commit()


def test_decide_proforma_vat_context_pl_eu_export_blocked():
    from app.services import wfirma_client as wfc

    pl = wfc.decide_proforma_vat_context("PL", "")
    assert pl["context"] == "domestic" and pl["vat_code"] == "23"
    eu = wfc.decide_proforma_vat_context("DE", "DE123456789")
    assert eu["context"] == "wdt" and eu["vat_code"] == "WDT"
    exp = wfc.decide_proforma_vat_context("US", "")
    assert exp["context"] == "export" and exp["vat_code"] == "EXP"
    blocked = wfc.decide_proforma_vat_context("DE", "")
    assert blocked["context"] == "blocked"


def test_normalize_stored_vat_mode_ids():
    from app.services.wfirma_client import normalize_stored_vat

    n = normalize_stored_vat(222)
    assert n["ok"] and n["vat_code"] == "23" and n["vat_context"] == "domestic"
    assert n["rate"] == pytest.approx(0.23)
    w = normalize_stored_vat("228")
    assert w["vat_code"] == "WDT" and w["rate"] == 0.0


def test_compute_document_vat_totals_regimes():
    from app.services.wfirma_client import compute_document_vat_totals

    d = compute_document_vat_totals(100.0, vat_code="23")
    assert d["net"] == 100.0 and d["vat_amount"] == 23.0 and d["gross"] == 123.0
    w = compute_document_vat_totals(100.0, vat_code="WDT")
    assert w["vat_amount"] == 0.0 and w["gross"] == 100.0
    e = compute_document_vat_totals(50.5, vat_code="EXP")
    assert e["vat_amount"] == 0.0 and e["gross"] == 50.5


def test_normalize_origin_india_and_missing():
    from app.services.master_data_db import normalize_origin_country

    assert normalize_origin_country("India") == "IN"
    assert normalize_origin_country("IN") == "IN"
    assert normalize_origin_country(None) is None
    assert normalize_origin_country("") is None


def test_physical_weight_index_invoice_fallback(storage):
    from app.services.commercial_authority import (
        attach_physical_weights_to_lines,
        physical_weight_index,
    )

    # Empty packing weights — invoice must supply.
    with sqlite3.connect(str(storage / "packing.db")) as con:
        con.execute(
            """INSERT INTO packing_lines
               (id, packing_document_id, batch_id, product_code, design_no,
                quantity, invoice_no, invoice_line_position,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), "doc1", BATCH, "JR00001", "D1",
                2.0, "INV/1", 1, NOW, NOW,
            ),
        )
        con.commit()
    _insert_invoice_line(
        storage, product_code="JR00001",
        gross_weight=6.0, net_weight=4.0, quantity=2.0,
    )
    idx = physical_weight_index(BATCH)
    assert idx["JR00001"]["unit_gross"] == pytest.approx(3.0)
    lines = [{"product_code": "JR00001", "qty": 2}]
    out = attach_physical_weights_to_lines(BATCH, lines)
    assert out[0]["gross_weight"] == pytest.approx(6.0)
    assert out[0]["net_weight"] == pytest.approx(4.0)


def test_repair_editable_drafts_vat_222_to_23_posted_untouched(storage):
    from app.services import proforma_invoice_link_db as pildb
    from app.services.commercial_authority import (
        repair_editable_drafts_vat,
        seed_draft_vat_from_customer,
    )

    db = storage / "proforma_links.db"
    cm = storage / "customer_master.sqlite"
    _upsert_cm(storage, country="PL", vat_mode=222)
    editable_id = _insert_draft(
        db, draft_state="draft", vat_code="222", vat_context=None,
    )
    posted_id = _insert_draft(
        db, draft_state="posted", vat_code="WDT", vat_context="wdt",
        client_name="Posted VAT Client",
    )

    soft = seed_draft_vat_from_customer(
        db, editable_id, customer_master_db=cm, force=False,
    )
    assert soft.get("ok") is True
    assert soft.get("vat_code") == "23"

    out = repair_editable_drafts_vat(db, customer_master_db=cm)
    assert out["repaired"] >= 1

    d_ed = pildb.get_draft_by_id(db, editable_id)
    assert d_ed.vat_code == "23"
    assert d_ed.vat_context == "domestic"

    d_post = pildb.get_draft_by_id(db, posted_id)
    assert d_post.vat_code == "WDT"
    assert d_post.vat_context == "wdt"


def test_apply_customer_commercial_stores_normalized_vat(storage):
    from app.services import proforma_invoice_link_db as pildb

    db = storage / "proforma_links.db"
    draft_id = _insert_draft(db)
    d0 = pildb.get_draft_by_id(db, draft_id)
    refreshed = pildb.apply_customer_commercial_to_draft(
        db, draft_id,
        cm_name=CLIENT, cm_contractor_id=CID,
        updates={"vat_mode": 222},
        operator="test", expected_updated_at=d0.updated_at,
    )
    assert refreshed.vat_code == "23"
    assert refreshed.vat_context == "domestic"


@pytest.fixture(scope="module")
def proforma_jsx():
    return _DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail_jsx():
    return _DETAIL.read_text(encoding="utf-8")


def test_jsx_no_hardcoded_wdt_pill(proforma_jsx):
    assert "function _ejVatBlock(" in proforma_jsx
    assert '<span className="ej-pill">WDT 0%</span>' not in proforma_jsx
    assert "0% WDT</td>" not in proforma_jsx
    assert "WDT 0% intra-EU" not in proforma_jsx


def test_preview_doc_data_carries_vat_totals(detail_jsx):
    assert "net_taxable: _previewVat.net" in detail_jsx
    assert "vat_amount: _previewVat.vatAmount" in detail_jsx
    assert "gross_total: _previewVat.gross" in detail_jsx


def test_packing_colour_stone_and_weights_and_origin(detail_jsx):
    pack = detail_jsx.split("const packingListData")[1].split("const draftState")[0]
    assert "ln.color_weight" in pack
    assert "Number(ln.gross_weight)" in pack
    assert "Number(ln.net_weight)" in pack
    assert "origin:       (ln.origin || '').trim() || '—'," in pack
    assert "'India'" not in pack


def test_converge_seeds_vat_step():
    from app.services import commercial_authority as ca

    src = Path(ca.__file__).read_text(encoding="utf-8")
    assert "seed_draft_vat_from_customer" in src
    assert "vat_seeds" in src
