"""
test_proforma_wireframe_slice1_fields.py — Proforma wireframe rebuild Slice 1.

Additive backend fields for the wireframe Proforma Detail page:

  A. Variant-identity passthrough (client_po, karat, metal, metal_color,
     quality_string, size, diamond_weight, color_weight) from
     sales_packing_lines into editable_lines at draft birth AND reset —
     previously silently dropped at the pildb boundary.
  B. _draft_to_full additive header keys: vat_code, vat_context,
     wfirma_payment_method, nbp_table_number.
  C. nbp_table_number = best-effort display-only lookup of
     fx_rates.table_number (master_data.sqlite) by (fx_rate_date, currency).

Coverage:
  1. test_birth_carries_variant_fields
  2. test_birth_variant_fields_default_safely
  3. test_reset_carries_variant_fields
  4. test_enrichment_preserves_variant_fields
  5. test_draft_get_surfaces_variant_fields
  6. test_draft_get_has_additive_header_keys
  7. test_draft_get_surfaces_frozen_vat
  8. test_nbp_table_number_resolves_from_fx_rates
  9. test_nbp_table_number_none_when_no_match
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb

VARIANT_LINE: Dict[str, Any] = {
    "product_code":   "EJL-RNG-0001",
    "design_no":      "JR02075",
    "qty":            1,
    "unit_price":     300.0,
    "currency":       "EUR",
    "price_source":   "packing_xlsx_value",
    "client_ref":     "PO-1",
    # Variant identity — sales_packing_lines columns
    "client_po":      "Adagia new order",
    "karat":          "14KT",
    "metal":          "GOLD/P",
    "metal_color":    "P",
    "quality_string": "FG-VS (LAB",
    "size":           "17.0M",
    "diamond_weight": 0.51,
    "color_weight":   0.0,
}

VARIANT_KEYS = (
    "client_po", "karat", "metal", "metal_color",
    "quality_string", "size", "diamond_weight", "color_weight",
)


def _auth_headers(operator: str = "alice"):
    return {
        "X-API-KEY":  settings.api_key or "test-key",
        "X-Operator": operator,
    }


@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


@pytest.fixture()
def client(tmp_path) -> TestClient:
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _seed(db: Path, lines=None, batch="B1", client_name="ACME"):
    draft, created = pildb.auto_create_draft_from_sales_packing(
        db,
        batch_id=batch,
        client_name=client_name,
        currency="EUR",
        lines=lines if lines is not None else [dict(VARIANT_LINE)],
        operator="intake",
    )
    assert created
    return draft


# ── A. Variant passthrough at birth / reset ──────────────────────────────────

def test_birth_carries_variant_fields(db_path):
    draft = _seed(db_path)
    lines = json.loads(draft.editable_lines_json)
    assert len(lines) == 1
    ln = lines[0]
    assert ln["client_po"] == "Adagia new order"
    assert ln["karat"] == "14KT"
    assert ln["metal"] == "GOLD/P"
    assert ln["metal_color"] == "P"
    assert ln["quality_string"] == "FG-VS (LAB"
    assert ln["size"] == "17.0M"
    assert ln["diamond_weight"] == pytest.approx(0.51)
    assert ln["color_weight"] == pytest.approx(0.0)
    # Source projection carries the same sales_packing columns.
    src = json.loads(draft.source_lines_json)[0]
    for k in VARIANT_KEYS:
        assert k in src, f"source_lines missing {k}"


def test_birth_variant_fields_default_safely(db_path):
    """Rows without variant columns (legacy callers) get ''/0.0 — no crash."""
    draft = _seed(db_path, lines=[{
        "product_code": "EJL-PND-1", "design_no": "D2",
        "qty": 1, "unit_price": 10.0, "currency": "EUR",
        "price_source": "", "client_ref": "",
        "diamond_weight": "not-a-number",   # defensive coercion
    }])
    ln = json.loads(draft.editable_lines_json)[0]
    assert ln["client_po"] == ""
    assert ln["karat"] == ""
    assert ln["size"] == ""
    assert ln["diamond_weight"] == 0.0
    assert ln["color_weight"] == 0.0


def test_reset_carries_variant_fields(db_path):
    draft = _seed(db_path, lines=[{
        "product_code": "EJL-RNG-0001", "design_no": "JR02075",
        "qty": 1, "unit_price": 300.0, "currency": "EUR",
        "price_source": "", "client_ref": "",
    }])
    # Reset with variant-rich rows — the rebuild must carry them through.
    updated = pildb.reset_draft_from_sales_packing(
        db_path, draft.id, "alice", draft.updated_at,
        sales_lines=[dict(VARIANT_LINE)],
    )
    ln = json.loads(updated.editable_lines_json)[0]
    assert ln["client_po"] == "Adagia new order"
    assert ln["karat"] == "14KT"
    assert ln["quality_string"] == "FG-VS (LAB"
    assert ln["size"] == "17.0M"
    assert ln["diamond_weight"] == pytest.approx(0.51)


def test_enrichment_preserves_variant_fields(db_path):
    """Product-description enrichment must not clobber variant identity."""
    draft = _seed(db_path)
    pd_row = {
        "product_code": "EJL-RNG-0001", "item_type": "RING",
        "name_pl": "Pierścionek", "description_pl": "Pierścionek złoty",
        "description_en": "Gold ring", "confidence": "high",
    }
    pildb.enrich_draft_lines(
        db_path, draft.id, "alice", draft.updated_at,
        lambda pc: pd_row if pc == "EJL-RNG-0001" else None,
    )
    refreshed = pildb.get_draft(db_path, "B1", "ACME")
    ln = json.loads(refreshed.editable_lines_json)[0]
    assert ln["karat"] == "14KT"
    assert ln["client_po"] == "Adagia new order"
    assert ln["diamond_weight"] == pytest.approx(0.51)
    assert ln["item_type"] == "RING"   # enrichment still owns item_type


# ── B. GET /draft/{id} additive keys ─────────────────────────────────────────

def test_draft_get_surfaces_variant_fields(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    pildb.init_db(db)
    draft = _seed(db)
    r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_auth_headers())
    assert r.status_code == 200
    ln = r.json()["draft"]["editable_lines"][0]
    for k in VARIANT_KEYS:
        assert k in ln, f"editable_lines missing {k} in GET response"
    assert ln["karat"] == "14KT"
    assert ln["size"] == "17.0M"


def test_draft_get_has_additive_header_keys(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    pildb.init_db(db)
    draft = _seed(db)
    r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()["draft"]
    for k in ("vat_code", "vat_context", "wfirma_payment_method",
              "nbp_table_number"):
        assert k in body, f"draft GET missing additive key {k}"
    # Fresh draft: stored-but-unset values surface as None, never crash.
    assert body["vat_code"] is None
    assert body["nbp_table_number"] is None
    # Pre-existing keys unchanged (regression guard).
    assert "nbp_table" in body
    assert "incoterm" in body


def test_draft_get_surfaces_frozen_vat(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    pildb.init_db(db)
    draft = _seed(db)
    pildb.freeze_draft_vat_context(db, draft.id, "wdt", "WDT", "derived")
    r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()["draft"]
    assert body["vat_code"] == "WDT"
    assert body["vat_context"] == "wdt"


# ── C. nbp_table_number lookup ───────────────────────────────────────────────

def _set_fx(db: Path, draft_id: int, rate_date: str):
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET exchange_rate=4.2650, fx_rate_date=? "
            "WHERE id=?", (rate_date, draft_id))
        conn.commit()


def test_nbp_table_number_resolves_from_fx_rates(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    pildb.init_db(db)
    draft = _seed(db)
    _set_fx(db, draft.id, "2026-05-10")
    from app.services import master_data_db as mdb
    mdb.create_fx_rate(tmp_path / "master_data.sqlite", {
        "rate_date": "2026-05-10", "from_currency": "EUR",
        "to_currency": "PLN", "rate": 4.2650,
        "source": "NBP", "table_number": "A 089/2026",
    })
    r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["draft"]["nbp_table_number"] == "A 089/2026"
    # Display-only: the stored exchange_rate is untouched by the lookup.
    assert r.json()["draft"]["exchange_rate"] == pytest.approx(4.2650)


def test_nbp_table_number_none_when_no_match(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    pildb.init_db(db)
    draft = _seed(db)
    _set_fx(db, draft.id, "2026-05-11")   # no fx_rates row for this date
    r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["draft"]["nbp_table_number"] is None
