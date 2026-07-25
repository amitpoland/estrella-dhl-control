"""
test_proforma_packing_authority_failclosed.py — OQ-PR689-OVERBILL-FAILCLOSED.

Billing safety: if packing_lines (the per-piece product authority) cannot be
READ, proforma readiness must FAIL CLOSED. The system must never let an over-bill
pass ``ready=true`` merely because it could not read the authority to prove
product_code validity / available quantity / over-bill status.

Two layers proven here:
  * resolver — a read FAILURE returns a structured ``authority_available=False``
    snapshot (distinct from a successful read of an empty batch).
  * readiness — ``_derive_draft_readiness`` adds a HARD blocker (not a warning)
    when the authority is unavailable; approve/post stay blocked. Proven by an
    ISOLATED test DB, never by breaking the production database.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import product_authority_resolver as par

_engine_candidates = [
    Path(__file__).parent.parent.parent / "engine",
    Path(__file__).parent.parent.parent.parent / "engine",
]
for _p in _engine_candidates:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break


# ════════════════════════════════════════════════════════════════════════════
# Layer 1 — resolver returns a STRUCTURED FAILURE on a packing read error
# ════════════════════════════════════════════════════════════════════════════

def _row(design="D1", pc="EJL/26-27/299-2", qty=1):
    return {"design_no": design, "product_code": pc, "quantity": qty,
            "invoice_no": "EJL/26-27/299"}


def test_packing_rows_raises_on_unreadable_db(tmp_path):
    bad = tmp_path / "no_packing_table.db"
    sqlite3.connect(str(bad)).close()             # exists, but NO packing_lines table
    with pytest.raises(par.PackingAuthorityUnavailable):
        par._packing_rows("B", packing_db_path=bad)


def test_resolver_read_failure_returns_structured_failure(tmp_path):
    bad = tmp_path / "no_packing_table.db"
    sqlite3.connect(str(bad)).close()
    snap = par.resolve_batch_product_authority("B", packing_db_path=bad)
    assert snap["authority_available"] is False
    assert snap["authority_error"]                # carries the reason
    # maps are empty — the failure is NOT silently treated as "no over-bill"
    assert snap["available_by_product_code"] == {}
    assert snap["design_to_product_codes"] == {}
    assert snap["product_codes"] == set()


def test_valid_packing_db_path_is_authority_available(tmp_path):
    db = tmp_path / "packing.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE packing_lines (design_no TEXT, product_code TEXT, "
                "quantity REAL, invoice_no TEXT, invoice_line_position INTEGER, "
                "batch_id TEXT)")
    con.execute("INSERT INTO packing_lines VALUES ('D1','EJL/26-27/299-2',2,"
                "'EJL/26-27/299',2,'B')")
    con.commit(); con.close()
    snap = par.resolve_batch_product_authority("B", packing_db_path=db)
    assert snap["authority_available"] is True
    assert snap["authority_error"] == ""
    assert snap["available_by_product_code"]["EJL/26-27/299-2"] == 2


def test_injected_rows_are_authority_available_even_when_empty():
    # An injected packing_rows list (incl. empty) is a SUCCESSFUL read.
    assert par.resolve_batch_product_authority("B", packing_rows=[])["authority_available"] is True
    snap = par.resolve_batch_product_authority("B", packing_rows=[_row()])
    assert snap["authority_available"] is True
    assert snap["available_by_product_code"]["EJL/26-27/299-2"] == 1


def test_slice_helpers_degrade_empty_on_read_failure(tmp_path):
    bad = tmp_path / "x.db"; sqlite3.connect(str(bad)).close()
    assert par.design_to_product_codes("B", packing_db_path=bad) == {}
    assert par.available_quantity_by_product_code("B", packing_db_path=bad) == {}
    # validate is conservative: unprovable → False (never True on a failed read)
    assert par.validate_billed_product_code("B", "EJL/26-27/299-2", packing_db_path=bad) is False


def test_resolver_never_reads_product_master_as_authority():
    """Rule 5: no fallback to product_master as a hard authority. The resolver
    must never SELECT from / read product_master."""
    src = Path(par.__file__).read_text(encoding="utf-8")
    # docstring may MENTION product_master (advisory), but it must never READ it.
    assert "FROM product_master" not in src
    assert "get_product_master" not in src
    assert "product_master WHERE" not in src


# ════════════════════════════════════════════════════════════════════════════
# Layer 2 — readiness gate FAILS CLOSED (direct _derive_draft_readiness call;
# no TestClient/auth so there is no users.db storage-leak — isolated test DB)
# ════════════════════════════════════════════════════════════════════════════

BATCH  = "BATCH_FAILCLOSED_TEST"
CLIENT = "FAILCLOSED_CLIENT"
CODE_A = "EJL/26-27/299-2"
FAILCLOSED_TEXT = "packing authority unavailable"


@pytest.fixture()
def seeded(tmp_path):
    """Isolated storage with a clean, billable draft (1 matched product)."""
    from app.core.config import settings
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb
    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")

    pdb.upsert_packing_lines([{
        "batch_id": BATCH, "invoice_no": "EJL/26-27/299",
        "invoice_line_position": 2, "product_code": CODE_A, "design_no": "D1",
        "bag_id": "", "tray_id": "", "item_type": "RNG", "uom": "PCS",
        "quantity": 1.0, "gross_weight": 0.0, "net_weight": 0.0, "metal": "",
        "karat": "", "stone_type": "", "remarks": "", "extracted_confidence": 1.0,
        "requires_manual_review": False, "pack_sr": 2.0, "unit_price": 50.0,
        "total_value": 50.0}])
    sd = ddb.store_sales_document(batch_id=BATCH, document_id=str(uuid.uuid4()),
                                  data={"client_name": CLIENT, "client_ref": "R",
                                        "sales_doc_no": "SO"})
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name": CLIENT, "client_ref": "R", "product_code": CODE_A,
        "design_no": "D1", "bag_id": "", "quantity": 1.0, "remarks": "",
        "unit_price": 100.0, "total_value": 100.0, "currency": "EUR",
        "price_source": "packing_list"}])
    wfdb.upsert_product(product_code=CODE_A, wfirma_product_id="99",
                        sync_status="matched")

    line = {"line_id": str(uuid.uuid4()), "product_code": CODE_A,
            "name_pl": "Pierścionek", "unit_price": 100.0, "quantity": 1.0,
            "currency": "EUR", "design_no": "D1"}
    with sqlite3.connect(str(tmp_path / "proforma_links.db")) as conn:
        cur = conn.execute(
            "INSERT INTO proforma_drafts (batch_id, client_name, status, currency,"
            " draft_state, wfirma_proforma_id, wfirma_proforma_fullnumber,"
            " source_lines_json, editable_lines_json, service_charges_json,"
            " clone_generation, draft_version, created_at, updated_at) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
            (BATCH, CLIENT, "draft", "EUR", "draft", None, "", "[]",
             json.dumps([line]), "[]", 0, 1))
        conn.commit()
        draft_id = cur.lastrowid

    with patch.object(settings, "storage_root", tmp_path):
        draft = pildb.get_draft_by_id(tmp_path / "proforma_links.db", draft_id)
        yield draft


# Faithful stand-in for "packing authority cannot be read": the resolver's real
# structured-failure snapshot. Patched at the module the readiness gate imports.
def _unavailable_snapshot(batch_id, **kw):
    return {
        "batch_id": batch_id, "design_to_product_codes": {},
        "available_by_product_code": {}, "invoice_by_product_code": {},
        "product_codes": set(), "rows_scanned": 0, "rows_skipped": 0,
        "authority_available": False,
        "authority_error": "packing_db is not initialised — cannot read product authority",
    }


def test_packing_authority_unavailable_blocks_readiness(seeded, tmp_path):
    from app.core.config import settings
    from app.api import routes_proforma as rp
    with patch.object(settings, "storage_root", tmp_path), \
         patch("app.services.cpa_product_service.authority_snapshot",
               side_effect=_unavailable_snapshot):
        ready = rp._derive_draft_readiness(seeded, intent="post")
    assert ready["ready"] is False, ready
    assert ready.get("product_authority_available") is False, ready
    assert any(FAILCLOSED_TEXT in br for br in ready["blocking_reasons"]), ready
    # the blocker carries an exact repair action (Lesson M)
    fc = [b for b in ready["blockers"] if FAILCLOSED_TEXT in b["reason"]]
    assert fc and (fc[0].get("repair_action") or "").strip()


def test_approve_post_convert_all_blocked_when_authority_unavailable(seeded, tmp_path):
    """ready=False on every lifecycle intent → approve/post/convert all gated
    (the routes refuse a write whenever readiness is not ready)."""
    from app.core.config import settings
    from app.api import routes_proforma as rp
    for intent in ("approve", "post", "convert"):
        with patch.object(settings, "storage_root", tmp_path), \
             patch("app.services.cpa_product_service.authority_snapshot",
                   side_effect=_unavailable_snapshot):
            ready = rp._derive_draft_readiness(seeded, intent=intent)
        assert ready["ready"] is False, (intent, ready)
        assert any(FAILCLOSED_TEXT in br for br in ready["blocking_reasons"]), (intent, ready)


def test_normal_context_authority_available_no_failclosed_blocker(seeded, tmp_path):
    """The fail-closed blocker must NOT appear when packing reads fine — the
    normal over-bill guard runs and product identity is provable."""
    from app.core.config import settings
    from app.api import routes_proforma as rp
    with patch.object(settings, "storage_root", tmp_path):
        ready = rp._derive_draft_readiness(seeded, intent="post")
    assert ready.get("product_authority_available") is True, ready
    assert not any(FAILCLOSED_TEXT in br for br in ready["blocking_reasons"]), ready
