"""test_proforma_529_price_source_authority.py

Campaign 04 — PR1 (#529): sales-price provenance hardening.

Defect: ``import_draft_sales_prices`` repriced a draft line with the SALES
figure but left the cost-basis ``price_source`` label
(``packing_xlsx_value`` / ``packing_promote``) originally written by
``routes_packing.py:2327``. At invoice the priced line then read as having
cost-price provenance, masking Estrella's sales margin (the EUR 3,608 gap on
EJL/26-27/244: sales 78,636 vs cost 75,028).

Fix (two parts — both exercised through the REAL builders here, Lesson A):

  1. ``import_draft_sales_prices`` stamps ``price_source="sales_packing_list"``
     on every matched line at the write site.

  2. ``_preflight_approve`` — THE readiness gate composed into
     approve / post / convert by ``_derive_draft_readiness`` — blocks approval
     when any PRICED line still carries a cost-basis ``price_source``
     (the margin-mask guard). Only the two cost labels are rejected;
     ``sales_packing_list``, ``bulk_recovery`` and unlabelled manual lines pass.

Frozen-valuation invariant: the guard asserts provenance only. It never
computes, derives, or alters a financial value — MDC-071 FX override into
landed cost stays permanently forbidden and is untouched here.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_engine_candidates = [
    Path(__file__).parent.parent.parent / "engine",
    Path(__file__).parent.parent.parent.parent / "engine",
]
for _p in _engine_candidates:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break


BATCH  = "BATCH_529_PRICE_SOURCE"
CLIENT = "PRICE_SOURCE_CLIENT"

# Matches the known-good TSV row in test_sales_packing_parser.py.
DESIGN      = "JP01823-0.20"
COST_LABEL_A = "packing_xlsx_value"
COST_LABEL_B = "packing_promote"
SALES_LABEL  = "sales_packing_list"
COST_BASIS_MSG = "cost-basis price_source"


# ── fixtures (mirror test_proforma_readiness_single_authority.py) ─────────────

@pytest.fixture()
def storage(tmp_path):
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb

    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")

    out = tmp_path / "outputs" / BATCH
    (out / "source").mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": BATCH, "tracking_no": BATCH,
             "awb": BATCH, "carrier": "DHL", "timeline": []}
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    return tmp_path


@pytest.fixture()
def client(storage):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, storage


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def _op_headers():
    return {"X-Operator": "test-op", **_auth()}


# ── seed helpers ──────────────────────────────────────────────────────────────

def _line(product_code: str = DESIGN, name_pl: str = "Pierścionek złoty",
          unit_price: float = 100.0, price_source=None,
          line_id=None) -> dict:
    ln = {
        "line_id":      line_id if line_id is not None else str(uuid.uuid4()),
        "product_code": product_code,
        "name_pl":      name_pl,
        "unit_price":   unit_price,
        "total_eur":    unit_price,
        "quantity":     1.0,
        "currency":     "EUR",
    }
    if price_source is not None:
        ln["price_source"] = price_source
    return ln


def _seed_draft(storage: Path, editable_lines: list,
                status: str = "draft", draft_state: str = "draft") -> int:
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """
            INSERT INTO proforma_drafts
              (batch_id, client_name, status, currency, draft_state,
               wfirma_proforma_id, wfirma_proforma_fullnumber,
               source_lines_json, editable_lines_json, service_charges_json,
               clone_generation, draft_version,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
            """,
            (BATCH, CLIENT, status, "EUR", draft_state, None, "",
             "[]", json.dumps(editable_lines), "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _editable_lines(storage: Path, draft_id: int) -> list:
    """Read the persisted editable_lines back from the real draft row."""
    from app.services import proforma_invoice_link_db as pildb
    draft = pildb.get_draft_by_id(storage / "proforma_links.db", draft_id)
    return json.loads(draft.editable_lines_json or "[]")


def _updated_at(storage: Path, draft_id: int) -> str:
    """Current optimistic-lock token for the seeded draft."""
    from app.services import proforma_invoice_link_db as pildb
    draft = pildb.get_draft_by_id(storage / "proforma_links.db", draft_id)
    return draft.updated_at or ""


def _preflight(storage: Path, draft_id: int):
    """Call the REAL gate directly (the one composed into approve/post/convert)."""
    from app.api.routes_proforma import _preflight_approve
    return _preflight_approve(storage / "proforma_links.db", draft_id)


# Known-good EJL sales packing TSV (one row, grand total matches the row).
_TSV = "\n".join([
    "Sr\tCtg\tDesign\tDesign Description\tKt\tCol\tQuality\tQty\tValue (EUR)\tTotal Value (EUR)",
    f"1\tPND\t{DESIGN}\tTest\t14KT\tW\tGH-SI1\t3\t211\t633",
    "Grand Total\t\t\t\t\t\t\t\t\t633",
])


# ── 1. Write site stamps sales_packing_list (real endpoint) ──────────────────

def test_import_sales_prices_stamps_sales_packing_list(client):
    c, storage = client
    # Seed a line still carrying the cost-basis label + the cost unit_price.
    # Real draft lines carry 1-based integer line_ids (_ensure_line_ids), so
    # the line matches TSV Sr=1 via the precise 1:1 Sr path.
    draft_id = _seed_draft(storage, [
        _line(product_code=DESIGN, unit_price=50.0,
              price_source=COST_LABEL_A, line_id=1),
    ])

    r = c.post(
        f"/api/v1/proforma/draft/{draft_id}/import-sales-prices",
        json={"expected_updated_at": _updated_at(storage, draft_id),
              "tsv_text": _TSV, "invoice_ref": "EJL/26-27/244"},
        headers=_op_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["lines_matched"] == 1, body

    lines = _editable_lines(storage, draft_id)
    assert len(lines) == 1, lines
    # Provenance flipped from cost-basis to sales authority…
    assert lines[0]["price_source"] == SALES_LABEL, lines[0]
    # …and the sales figure replaced the cost figure (211 from the TSV).
    assert float(lines[0]["unit_price"]) == 211.0, lines[0]


# ── 2. Gate blocks a priced line that still carries packing_xlsx_value ───────

def test_preflight_blocks_stale_packing_xlsx_value(storage):
    draft_id = _seed_draft(storage, [
        _line(unit_price=100.0, price_source=COST_LABEL_A),
    ])
    err = _preflight(storage, draft_id)
    assert err is not None, "stale cost label must block approval"
    assert COST_BASIS_MSG in err, err
    assert COST_LABEL_A in err, err


# ── 3. Gate blocks packing_promote too ───────────────────────────────────────

def test_preflight_blocks_stale_packing_promote(storage):
    draft_id = _seed_draft(storage, [
        _line(unit_price=100.0, price_source=COST_LABEL_B),
    ])
    err = _preflight(storage, draft_id)
    assert err is not None and COST_BASIS_MSG in err, err


# ── 4. Gate passes the correct sales label ───────────────────────────────────

def test_preflight_passes_sales_packing_list(storage):
    draft_id = _seed_draft(storage, [
        _line(unit_price=100.0, price_source=SALES_LABEL),
    ])
    err = _preflight(storage, draft_id)
    assert err is None, f"sales_packing_list must pass the margin-mask gate: {err}"


# ── 5. Gate does NOT false-block bulk_recovery / unlabelled manual lines ─────

def test_preflight_does_not_false_block_other_sources(storage):
    # bulk_recovery (a legitimate non-cost source) + an unlabelled manual line.
    draft_id = _seed_draft(storage, [
        _line(product_code="MANUAL-1", unit_price=100.0,
              price_source="bulk_recovery"),
        _line(product_code="MANUAL-2", unit_price=100.0, price_source=None),
    ])
    err = _preflight(storage, draft_id)
    assert err is None, f"non-cost sources must not be blocked: {err}"


# ── 6. Margin-mask guard targets PRICED lines only ───────────────────────────

def test_preflight_zero_price_caught_by_zero_guard_not_cost_guard(storage):
    # A zero-price line carrying a cost label is caught by the pre-existing
    # zero_price guard (different message) — the cost-basis guard only fires
    # on PRICED lines, so the two messages must not collide.
    draft_id = _seed_draft(storage, [
        _line(unit_price=0.0, price_source=COST_LABEL_B),
    ])
    err = _preflight(storage, draft_id)
    assert err is not None, err
    assert "zero/missing unit_price" in err, err
    assert COST_BASIS_MSG not in err, err
