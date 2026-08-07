"""Permanent pins: new batch → draft converges commercial authorities.

Proves (without inventing values):
  * sales matcher product_codes persist before draft birth/reset
  * promote from audit.rows stamps when pz_rows.json is absent
  * intake enrich fills name_pl after birth / on stale blank drafts
  * readiness messages distinguish description vs price vs wFirma mapping
  * valid sales rows are not dropped when invoice-scoped lot pairing works
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.services import document_db as ddb
from app.services import packing_db as pdb
from app.services import proforma_invoice_link_db as pildb
from app.services.commercial_authority import (
    converge_batch_draft_authority,
    persist_matched_sales_product_codes,
    promote_and_enrich_batch_drafts,
)
from app.services.description_engine import promote_pz_rows_to_product_descriptions


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    return tmp_path


def _seed_purchase_lots(storage: Path, batch_id: str, lots: List[Dict[str, Any]]):
    with sqlite3.connect(str(storage / "packing.db")) as con:
        for lot in lots:
            con.execute(
                """INSERT INTO packing_lines
                   (id, packing_document_id, batch_id, product_code, design_no,
                    quantity, invoice_no, invoice_line_position,
                    unit_price, unit_price_eur, metal, karat, metal_color,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), "pdoc", batch_id,
                    lot["product_code"], lot["design_no"],
                    float(lot.get("quantity", 1)),
                    lot.get("invoice_no", "EJL/26-27/492"),
                    1,
                    float(lot["unit_price"]),
                    0.0,
                    lot.get("metal", "14KT/Y"),
                    lot.get("karat", "14KT"),
                    lot.get("metal_color", "Y"),
                    "2026-01-01T00:00:00",
                    "2026-01-01T00:00:00",
                ),
            )


def _seed_sales_rows(batch_id: str, rows: List[Dict[str, Any]]) -> str:
    sd = str(uuid.uuid4()).replace("-", "")[:32]
    ddb.ensure_sales_document_id(
        batch_id, sd, document_type="sales_packing_list",
        source_file_path="t.xlsx",
    )
    # ensure_sales_document_id may not set client — use replace path
    line_records = []
    for r in rows:
        line_records.append({
            "client_name": r.get("client_name", "Client A"),
            "product_code": r.get("product_code", ""),
            "design_no": r["design_no"],
            "quantity": float(r.get("quantity", 1)),
            "unit_price": float(r["unit_price"]),
            "currency": "USD",
            "total_value": float(r["unit_price"]),
            "invoice_no": r.get("invoice_no", "EJL/26-27/492"),
            "metal": r.get("metal", "14KT/Y"),
            "metal_color": r.get("metal_color", "Y"),
            "karat": "14KT",
            "client_po": r.get("client_po", "PO1"),
        })
    ddb.replace_sales_packing_lines(sd, batch_id, line_records)
    # stamp client_name on sales_documents
    with sqlite3.connect(str(ddb._db_path)) as con:
        con.execute(
            "UPDATE sales_documents SET client_name=? WHERE id=?",
            ("Client A", sd),
        )
    return sd


class TestPersistMatchedSalesProductCodes:
    def test_jr00819_class_multi_lot_persists(self, storage):
        bid = "B-JR-01"
        _seed_purchase_lots(storage, bid, [
            {"product_code": "EJL/26-27/492-2", "design_no": "JR00819",
             "unit_price": 221.0},
            {"product_code": "EJL/26-27/492-1", "design_no": "JR00819",
             "unit_price": 230.0},
            {"product_code": "EJL/26-27/492-1", "design_no": "JR00819",
             "unit_price": 228.0},
            {"product_code": "EJL/26-27/492-1", "design_no": "JR00819",
             "unit_price": 222.0},
        ])
        _seed_sales_rows(bid, [
            {"design_no": "JR00819", "unit_price": 243.0},
            {"design_no": "JR00819", "unit_price": 253.0},
            {"design_no": "JR00819", "unit_price": 250.0},
            {"design_no": "JR00819", "unit_price": 244.0},
        ])
        out = persist_matched_sales_product_codes(bid)
        assert out["updated"] == 4
        rows = ddb.get_sales_packing_lines(bid)
        assert all(str(r.get("product_code") or "").strip() for r in rows)
        assert {r["product_code"] for r in rows} == {
            "EJL/26-27/492-1", "EJL/26-27/492-2",
        }


class TestPromoteFromAuditWhenNoPzRows:
    def test_audit_authoritative_stamps_overwrite_auto_generic(self, storage):
        bid = "B-DESC-01"
        batch = storage / "outputs" / bid
        batch.mkdir(parents=True)
        # Poisoned auto generic (would be rejected at birth).
        ddb.upsert_product_description(
            product_code="EJL/26-27/492-1",
            item_type="RING",
            name_pl="Wyrób jubilerski",
            description_pl="Wyrób jubilerski — wyrób jubilerski do noszenia.",
            description_en="Jewellery",
            material_pl="",
            purpose_pl="",
            description_block="x",
            description_line="x",
            source="auto",
        )
        (batch / "audit.json").write_text(json.dumps({
            "batch_id": bid,
            "rows": [{
                "product_code": "EJL/26-27/492-1",
                "description": "PCS, 14KT Gold,Stud Jewelry DIA&CLS RING",
                "item_type": "RING",
                "_resolved_description_pl": (
                    "Pierścionek z 14-karatowego złota (próba 585) "
                    "wysadzany diamentami. Biżuteria do noszenia."
                ),
                "_resolved_name_pl": "Pierścionek",
                "_resolved_description_en": "",
                "_desc_authoritative": True,
            }],
        }), encoding="utf-8")
        # No pz_rows.json — promote must use audit stamps.
        result = promote_pz_rows_to_product_descriptions(batch, dry_run=False)
        assert result["written"] == 1
        assert result["source_file"] == "audit.json"
        row = ddb.get_product_description("EJL/26-27/492-1")
        assert row["source"] == "pz_rows"
        assert row["description_pl"].startswith("Pierścionek z 14-karatowego")


class TestConvergeEndToEnd:
    def test_new_batch_draft_gets_pc_and_name_pl(self, storage):
        bid = "B-CONV-01"
        _seed_purchase_lots(storage, bid, [
            {"product_code": "EJL/26-27/492-2", "design_no": "JR00819",
             "unit_price": 221.0},
            {"product_code": "EJL/26-27/492-1", "design_no": "JR00819",
             "unit_price": 230.0},
        ])
        _seed_sales_rows(bid, [
            {"design_no": "JR00819", "unit_price": 243.0},
            {"design_no": "JR00819", "unit_price": 253.0},
        ])
        batch = storage / "outputs" / bid
        batch.mkdir(parents=True)
        (batch / "audit.json").write_text(json.dumps({
            "rows": [
                {
                    "product_code": "EJL/26-27/492-1",
                    "description": "14KT Gold RING",
                    "_resolved_description_pl": (
                        "Pierścionek z 14-karatowego złota (próba 585)."
                    ),
                    "_resolved_name_pl": "Pierścionek",
                    "_desc_authoritative": True,
                    "item_type": "RING",
                },
                {
                    "product_code": "EJL/26-27/492-2",
                    "description": "14KT Gold LGD RING",
                    "_resolved_description_pl": (
                        "Pierścionek z 14-karatowego złota z diamentami "
                        "laboratoryjnymi."
                    ),
                    "_resolved_name_pl": "Pierścionek",
                    "_desc_authoritative": True,
                    "item_type": "RING",
                },
            ],
        }), encoding="utf-8")

        # Birth a thin draft (empty PC rows would be skipped — simulate
        # pre-converge birth with one resolved line, then converge).
        draft, _ = pildb.auto_create_draft_from_sales_packing(
            storage / "proforma_links.db",
            batch_id=bid,
            client_name="Client A",
            currency="USD",
            lines=[{
                "product_code": "EJL/26-27/492-1",
                "design_no": "JR00819",
                "qty": 1,
                "unit_price": 253.0,
                "currency": "USD",
            }],
            operator="test",
            name_pl_lookup=ddb.get_product_description,
        )
        assert draft is not None

        out = converge_batch_draft_authority(
            bid,
            proforma_db=storage / "proforma_links.db",
            operator="test",
            reset_editable=True,
        )
        assert out["product_codes"]["updated"] >= 1
        assert int(out["descriptions"]["promote"]["written"] or 0) >= 1

        d = pildb.get_draft_by_id(storage / "proforma_links.db", draft.id)
        lines = json.loads(d.editable_lines_json or "[]")
        assert len(lines) >= 2, "dropped JR00819 sales rows must re-enter"
        assert all(str(ln.get("product_code") or "").strip() for ln in lines)
        assert any(str(ln.get("name_pl") or "").strip() for ln in lines)


class TestReadinessMessageAuthority:
    def test_blank_name_pl_not_sales_price_hint(self):
        from app.api.routes_proforma import _repair_hint_for_blocker
        hint = _repair_hint_for_blocker(
            "Approval blocked: 3 line(s) have blank commercial description (name_pl)."
        )
        assert "sales price" not in hint.lower() or "not a sales-price" in hint.lower()
        assert "product_descriptions" in hint or "Promote" in hint

    def test_wfirma_hint_points_at_auto_register(self):
        from app.api.routes_proforma import _repair_hint_for_blocker
        hint = _repair_hint_for_blocker(
            "2 product(s) not matched in wfirma_products (missing wfirma_product_id): X"
        )
        assert "auto-register" in hint
        assert "invent" in hint.lower()

    def test_preflight_blank_desc_mentions_promote_not_prices(self, storage):
        from app.api import routes_proforma as rp
        draft, _ = pildb.auto_create_draft_from_sales_packing(
            storage / "proforma_links.db",
            batch_id="B-PF-01",
            client_name="Client A",
            currency="EUR",
            lines=[{
                "product_code": "EJL/X",
                "design_no": "D1",
                "qty": 1,
                "unit_price": 10.0,
                "currency": "EUR",
                "name_pl": "",
            }],
            operator="test",
        )
        err = rp._preflight_approve(storage / "proforma_links.db", draft.id)
        assert err is not None
        assert "name_pl" in err
        assert "Import sales prices first" not in err
        assert "product_descriptions" in err or "Promote" in err
