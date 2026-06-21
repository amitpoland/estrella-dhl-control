"""
test_link_as_sales_contractor_authority.py

Backfill authority fix: ``POST /packing/{batch}/link-as-sales`` must capture the
operator-selected Customer-Master ``client_contractor_id`` (the customer
authority), not free-text ``client_name`` only. contractor_id outranks the
parsed/typed name (rules 1-2); when no contractor is selected the existing
name-fallback behaviour is preserved (rule 6); a prior selection is never
clobbered by a later name-only call (rule 5).

Layers:
  1. ``get_or_create_sales_document_for_packing`` writes the operator cid onto
     ``sales_documents`` and ``replace_sales_packing_lines`` projects it onto the
     sales lines (→ the proforma draft).
  2. ``derive_customer_authority_for_draft`` resolves Customer Master by that
     contractor_id even when the draft's display name conflicts.
  3. The endpoint persists the cid end-to-end and seeds the per-batch
     ``packing_contractor_resolution`` (single-contractor only).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services import document_db as ddb
from app.services import customer_resolution_authority as cra

CID       = "195596259"
OTHER_CID = "888777666"
BATCH     = "SHIPMENT_LAS_TEST_2026-06"


# ════════════════════════════════════════════════════════════════════════════
# Layer 1 — sales-chain persistence (get_or_create + replace projection)
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def docdb(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path / "documents.db"


def _sd_row(db, sd_id):
    with sqlite3.connect(str(db)) as c:
        c.row_factory = sqlite3.Row
        return c.execute(
            "SELECT client_contractor_id, client_name FROM sales_documents WHERE id=?",
            (sd_id,)).fetchone()


def test_explicit_contractor_id_written_and_projected_to_lines(docdb):
    sd = ddb.get_or_create_sales_document_for_packing(
        batch_id=BATCH, packing_document_id="PDOC1",
        client_name="Typed Name", client_contractor_id=CID)
    assert _sd_row(docdb, sd)["client_contractor_id"] == CID

    ddb.replace_sales_packing_lines(sales_document_id=sd, batch_id=BATCH, lines=[
        {"client_name": "Typed Name", "product_code": "EJL/1-1", "quantity": 1.0}])
    with sqlite3.connect(str(docdb)) as c:
        c.row_factory = sqlite3.Row
        line = c.execute(
            "SELECT client_contractor_id FROM sales_packing_lines "
            "WHERE sales_document_id=?", (sd,)).fetchone()
    assert line["client_contractor_id"] == CID   # projected onto the draft source


def test_explicit_reselection_wins_over_existing(docdb):
    sd1 = ddb.get_or_create_sales_document_for_packing(
        batch_id=BATCH, packing_document_id="PDOC2",
        client_name="N", client_contractor_id=OTHER_CID)
    sd2 = ddb.get_or_create_sales_document_for_packing(
        batch_id=BATCH, packing_document_id="PDOC2",
        client_name="N", client_contractor_id=CID)
    assert sd1 == sd2                                   # idempotent on packing doc
    assert _sd_row(docdb, sd2)["client_contractor_id"] == CID  # latest pick wins


def test_no_contractor_id_keeps_name_fallback(docdb):
    # rule 6: no operator selection → no cid written; name-based resolution
    # downstream is unchanged.
    sd = ddb.get_or_create_sales_document_for_packing(
        batch_id=BATCH, packing_document_id="PDOC3", client_name="Only Name")
    row = _sd_row(docdb, sd)
    assert (row["client_contractor_id"] or "") == ""
    assert row["client_name"] == "Only Name"


def test_name_only_call_does_not_clobber_prior_selection(docdb):
    # rule 5: a later name-only correction must NOT wipe a selected contractor.
    sd = ddb.get_or_create_sales_document_for_packing(
        batch_id=BATCH, packing_document_id="PDOC4",
        client_name="N", client_contractor_id=CID)
    ddb.get_or_create_sales_document_for_packing(
        batch_id=BATCH, packing_document_id="PDOC4", client_name="N corrected")
    row = _sd_row(docdb, sd)
    assert row["client_contractor_id"] == CID           # preserved
    assert row["client_name"] == "N corrected"          # name still editable


# ════════════════════════════════════════════════════════════════════════════
# Layer 2 — authority resolution: contractor_id beats conflicting name
# ════════════════════════════════════════════════════════════════════════════

def _make_cm(tmp_path, contractor_id=CID, name="REAL CLIENT LLC",
             country="SK", nip="SK123"):
    cm = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS customer_master ("
            "id INTEGER PRIMARY KEY, bill_to_contractor_id TEXT, "
            "bill_to_name TEXT, country TEXT, nip TEXT)")
        c.execute(
            "INSERT INTO customer_master "
            "(bill_to_contractor_id, bill_to_name, country, nip) VALUES (?,?,?,?)",
            (contractor_id, name, country, nip))
    return cm


def test_derive_authority_contractor_id_beats_conflicting_name(tmp_path):
    cm = _make_cm(tmp_path)
    ddb.init_document_db(tmp_path / "documents.db")
    res = cra.derive_customer_authority_for_draft(
        batch_id=BATCH, client_name="WRONG TYPED NAME",
        documents_db_path=tmp_path / "documents.db",
        customer_master_db_path=cm, client_contractor_id=CID)
    assert res is not None
    assert res["match_strategy"] == "draft_contractor_id"
    assert res["wfirma_customer_id"] == CID
    assert res["resolved_master_name"] == "REAL CLIENT LLC"
    assert "WRONG TYPED NAME" in (res["advisory"] or "")   # mismatch = advisory


def test_derive_authority_no_cid_no_doc_falls_through(tmp_path):
    # rule 3: no contractor selected and no sales doc → None (name fallback).
    cm = _make_cm(tmp_path)
    ddb.init_document_db(tmp_path / "documents.db")
    res = cra.derive_customer_authority_for_draft(
        batch_id=BATCH, client_name="Some Name",
        documents_db_path=tmp_path / "documents.db",
        customer_master_db_path=cm, client_contractor_id="")
    assert res is None


# ════════════════════════════════════════════════════════════════════════════
# Layer 3 — endpoint: persists cid end-to-end + seeds per-batch resolution
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def endpoint_env(tmp_path):
    from app.core.config import settings
    from app.services import packing_db as pdb
    from app.services import proforma_invoice_link_db as pildb

    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    cm = _make_cm(tmp_path, CID, "REAL CLIENT")

    out = tmp_path / "outputs" / BATCH
    (out / "source").mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(
        '{"batch_id":"%s","timeline":[]}' % BATCH, encoding="utf-8")

    def _seed_doc(pdoc_key, product_code):
        pdoc = pdb.upsert_packing_document(
            batch_id=BATCH, invoice_no=pdoc_key, extraction_status="extracted")
        pdb.upsert_packing_lines([{
            "batch_id": BATCH, "invoice_no": pdoc_key, "invoice_line_position": 1,
            "packing_document_id": pdoc, "product_code": product_code,
            "design_no": "D1", "bag_id": "", "quantity": 1.0,
            "unit_price": 100.0, "pack_sr": 1.0}])
        return pdoc

    with patch.object(settings, "storage_root", tmp_path):
        yield tmp_path, cm, _seed_doc


def _pr_row(storage):
    db = storage / "packing_resolutions.sqlite"
    if not db.is_file():
        return None                       # not seeded → no db file
    with sqlite3.connect(str(db)) as c:
        c.row_factory = sqlite3.Row
        try:
            return c.execute(
                "SELECT * FROM packing_contractor_resolution "
                "WHERE batch_id=? AND role='client'", (BATCH,)).fetchone()
        except sqlite3.OperationalError:
            return None                   # table never created → not seeded


def test_endpoint_persists_contractor_and_resolves_by_it(endpoint_env):
    from app.api.routes_packing import (
        link_packing_as_sales, _LinkAsSalesBody, _ClientMapping)
    storage, cm, seed_doc = endpoint_env
    pdoc = seed_doc("INV1", "EJL/1-1")

    res = link_packing_as_sales(BATCH, _LinkAsSalesBody(client_mappings=[
        _ClientMapping(packing_document_id=pdoc, client_name="WRONG TYPED NAME",
                       client_contractor_id=CID)]))
    assert res["ok"] is True
    assert res["results"][0]["client_contractor_id"] == CID

    # sales chain carries the operator cid (doc + projected onto the line)
    with sqlite3.connect(str(storage / "documents.db")) as c:
        c.row_factory = sqlite3.Row
        sd = c.execute("SELECT id, client_contractor_id FROM sales_documents "
                       "WHERE batch_id=?", (BATCH,)).fetchone()
        assert sd["client_contractor_id"] == CID
        line = c.execute("SELECT client_contractor_id FROM sales_packing_lines "
                         "WHERE sales_document_id=?", (sd["id"],)).fetchone()
        assert line["client_contractor_id"] == CID

    # per-batch resolution seeded as operator-confirmed
    pr = _pr_row(storage)
    assert pr is not None
    assert pr["status"] == "confirmed"
    # Lesson A: matched_master_id round-trips via SQLite affinity (int) — the
    # production reader normalises; assert on the normalised string.
    assert str(pr["matched_master_id"]) == CID
    assert pr["matched_master_type"] == "customer_master"
    assert pr["reason"] == "link_as_sales_operator_selected"

    # …and it resolves Customer Master BY the contractor_id
    resolved = cra.derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="WRONG TYPED NAME",
        customer_master_db_path=cm,
        packing_resolution_db_path=storage / "packing_resolutions.sqlite")
    assert resolved is not None
    assert resolved["wfirma_customer_id"] == CID
    assert resolved["resolved_master_name"] == "REAL CLIENT"


def test_endpoint_without_cid_seeds_no_resolution(endpoint_env):
    from app.api.routes_packing import (
        link_packing_as_sales, _LinkAsSalesBody, _ClientMapping)
    storage, cm, seed_doc = endpoint_env
    pdoc = seed_doc("INV1", "EJL/1-1")

    res = link_packing_as_sales(BATCH, _LinkAsSalesBody(client_mappings=[
        _ClientMapping(packing_document_id=pdoc, client_name="Only A Name")]))
    assert res["ok"] is True
    # rule 6: no cid → sales doc has blank contractor, no per-batch resolution
    with sqlite3.connect(str(storage / "documents.db")) as c:
        c.row_factory = sqlite3.Row
        sd = c.execute("SELECT client_contractor_id FROM sales_documents "
                       "WHERE batch_id=?", (BATCH,)).fetchone()
    assert (sd["client_contractor_id"] or "") == ""
    assert _pr_row(storage) is None


def test_endpoint_multi_client_skips_perbatch_resolution(endpoint_env):
    # UNIQUE(batch_id, role='client') can't represent two clients — the per-batch
    # resolution is skipped, but each sales_document still carries its own cid
    # (per-document authority resolves each draft correctly).
    from app.api.routes_packing import (
        link_packing_as_sales, _LinkAsSalesBody, _ClientMapping)
    storage, cm, seed_doc = endpoint_env
    p1 = seed_doc("INVA", "EJL/1-1")
    p2 = seed_doc("INVB", "EJL/2-1")

    res = link_packing_as_sales(BATCH, _LinkAsSalesBody(client_mappings=[
        _ClientMapping(packing_document_id=p1, client_name="Client A",
                       client_contractor_id=CID),
        _ClientMapping(packing_document_id=p2, client_name="Client B",
                       client_contractor_id=OTHER_CID)]))
    assert res["ok"] is True
    assert _pr_row(storage) is None    # multi-client → not seeded

    with sqlite3.connect(str(storage / "documents.db")) as c:
        c.row_factory = sqlite3.Row
        rows = {r["document_id"]: r["client_contractor_id"] for r in c.execute(
            "SELECT document_id, client_contractor_id FROM sales_documents "
            "WHERE batch_id=?", (BATCH,)).fetchall()}
    assert rows[f"packing:{p1}"] == CID
    assert rows[f"packing:{p2}"] == OTHER_CID
