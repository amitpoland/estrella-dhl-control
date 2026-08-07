"""Commercial authority propagation — future-proof + blank-only repair.

Pins:
  - manual sales allocation blank-fills variants from purchase packing
  - link_as_sales / matched sales lines carry purchase variants
  - sales_row_to_draft_input is the single birth/reset reshape
  - blank-fill never invents Client PO or overwrites Sales values
  - origin is never invented when Product Master lacks it
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@l"}

    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    from app.services import proforma_invoice_link_db as pildb
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def _seed_batch(storage: Path, batch_id: str) -> Path:
    out = storage / "outputs" / batch_id
    (out / "source" / "packing").mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(
        json.dumps({"batch_id": batch_id, "timeline": []}), encoding="utf-8",
    )
    return out


def _seed_purchase_with_variants(
    packing_db: Path, batch_id: str, rows: List[Dict[str, Any]],
) -> None:
    with sqlite3.connect(str(packing_db)) as con:
        for row in rows:
            con.execute(
                """INSERT OR REPLACE INTO packing_lines
                   (id, packing_document_id, batch_id, product_code, design_no,
                    quantity, invoice_no, invoice_line_position,
                    karat, metal, metal_color, quality_string, size,
                    diamond_weight, color_weight, item_type, stone_type,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), "fake-doc-id", batch_id,
                    row.get("product_code", ""),
                    row.get("design_no", ""),
                    float(row.get("quantity", 0)),
                    row.get("invoice_no", "INV/001"),
                    1,
                    row.get("karat", ""),
                    row.get("metal", ""),
                    row.get("metal_color", ""),
                    row.get("quality_string", ""),
                    row.get("size", ""),
                    float(row.get("diamond_weight", 0) or 0),
                    float(row.get("color_weight", 0) or 0),
                    row.get("item_type", ""),
                    row.get("stone_type", ""),
                    "2026-01-01T00:00:00",
                    "2026-01-01T00:00:00",
                ),
            )


_PURCHASE = [
    {
        "product_code": "EJL/26-27/001-1",
        "design_no": "D001",
        "quantity": 5.0,
        "karat": "14KT",
        "metal": "GOLD",
        "metal_color": "Y",
        "quality_string": "SI-GH",
        "size": "7",
        "diamond_weight": 0.12,
        "color_weight": 0.0,
        "item_type": "RING",
    },
]


class TestManualAllocationPropagatesVariants:
    def test_manual_allocation_fills_variants_from_purchase(self, client):
        cli, storage = client
        bid = "B-AUTH-01"
        _seed_batch(storage, bid)
        _seed_purchase_with_variants(storage / "packing.db", bid, _PURCHASE)

        with patch(
            "app.services.proforma_draft_sync.sync_draft_from_packing_upload",
            return_value={},
        ):
            r = cli.post(f"/api/v1/packing/{bid}/manual-sales-allocation", json={
                "client_name": "Verhoeven B.V.",
                "lines": [{
                    "product_code": "EJL/26-27/001-1",
                    "quantity": 2.0,
                    "unit_price": 150.0,
                }],
            })
        assert r.status_code == 200, r.text

        with sqlite3.connect(str(storage / "documents.db")) as con:
            row = con.execute(
                "SELECT karat, quality_string, metal_color, size, "
                "diamond_weight, client_po FROM sales_packing_lines "
                "WHERE batch_id=?",
                (bid,),
            ).fetchone()
        assert row is not None
        assert row[0] == "14KT"
        assert row[1] == "SI-GH"
        assert row[2] == "Y"
        assert row[3] == "7"
        assert float(row[4]) == pytest.approx(0.12)
        # Client PO must never be invented from purchase.
        assert (row[5] or "") == ""


class TestMatchedSalesLinesCarryVariants:
    def test_build_matched_sales_lines_carries_purchase_variants(self):
        from app.api.routes_packing import _build_matched_sales_lines

        packing_lines = [{
            "product_code": "EJL/26-27/001-1",
            "design_no": "D001",
            "quantity": 1,
            "unit_price_eur": 10,
            "karat": "18KT",
            "metal": "GOLD",
            "metal_color": "W",
            "quality_string": "VVS",
            "size": "54",
            "diamond_weight": 0.2,
            "color_weight": 0.05,
            "item_type": "BAND",
            "stone_type": "DIA",
        }]
        sales, skipped = _build_matched_sales_lines(packing_lines, "Client A")
        assert skipped == 0
        assert len(sales) == 1
        assert sales[0]["karat"] == "18KT"
        assert sales[0]["quality_string"] == "VVS"
        assert sales[0]["metal_color"] == "W"
        assert sales[0]["size"] == "54"
        assert float(sales[0]["diamond_weight"]) == pytest.approx(0.2)
        assert "client_po" not in sales[0] or sales[0].get("client_po") in ("", None)


class TestSalesRowToDraftInput:
    def test_single_reshape_carries_variants(self):
        from app.services.commercial_authority import sales_row_to_draft_input

        out = sales_row_to_draft_input({
            "product_code": "PC1",
            "design_no": "D1",
            "quantity": 2,
            "unit_price": 9.5,
            "currency": "eur",
            "client_po": "PO-99",
            "karat": "14KT",
            "quality_string": "SI",
            "metal_color": "Y",
            "size": "6",
            "diamond_weight": 0.1,
        })
        assert out["qty"] == 2.0
        assert out["currency"] == "EUR"
        assert out["client_po"] == "PO-99"
        assert out["karat"] == "14KT"
        assert out["quality_string"] == "SI"
        assert out["size"] == "6"


class TestBlankFillNeverOverwrites:
    def test_enrich_preserves_sales_values(self):
        from app.services.commercial_authority import (
            enrich_sales_line_blanks_from_purchase,
        )

        sales = {
            "product_code": "PC1",
            "karat": "10KT",  # sales wins
            "quality_string": "",
            "client_po": "KEEP-ME",
        }
        purchase_idx = {
            "PC1": {
                "karat": "14KT",
                "quality_string": "SI-GH",
                "metal": "GOLD",
                "metal_color": "Y",
                "size": "7",
                "diamond_weight": 0.1,
                "color_weight": 0,
                "item_type": "RING",
                "stone_type": "",
            },
        }
        out, filled = enrich_sales_line_blanks_from_purchase(sales, purchase_idx)
        assert out["karat"] == "10KT"
        assert out["quality_string"] == "SI-GH"
        assert out["client_po"] == "KEEP-ME"
        assert "karat" not in filled
        assert "quality_string" in filled


class TestOriginNeverInvented:
    def test_normalize_does_not_default_missing_sku(self):
        from app.services.master_data_db import normalize_origin_country

        assert normalize_origin_country("") is None
        assert normalize_origin_country(None) is None
        # India maps when present — blank stays None (no invent-IN).
        assert normalize_origin_country("India") == "IN"
