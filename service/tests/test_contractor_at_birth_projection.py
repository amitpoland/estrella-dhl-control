"""test_contractor_at_birth_projection.py — PR-2 Contractor-at-Birth Projection
================================================================================

Real-builder tests (no mocked success paths) pinning the contractor-at-birth
projection: the Customer-Master contractor authority resolved at intake
(``shipment_documents.client_contractor_id``) must survive through
sales_documents → sales_packing_lines → proforma draft grouping → reservation
draft, and unresolved contractor cases must become VISIBLE blocked draft-birth
records instead of silent drops.

Contracts pinned:
  Schema      — client_contractor_id present + idempotent on sales_documents,
                sales_packing_lines, proforma_drafts, wfirma_reservation_drafts.
  Projection  — store_sales_document / store_sales_packing_lines /
                ensure_sales_document_id / get_or_create_sales_document_for_packing
                derive the contractor from the authoritative shipment_documents
                row when not explicitly supplied (self-healing every call site).
  Grouping    — empty client_name + resolvable contractor → draft recovered
                (client_name from Customer Master); contractor is the authority,
                client_name stays the storage key.
  Blocked     — empty name + (no contractor OR contractor with no CM row) →
                visible blocked record (blocked_state/reason/code); resolves
                once a draft is later created.
  Backfill    — idempotent reconciliation repairs legacy rows.
  Reservation — reservation draft carries the contractor reference (readiness).
  Regression  — existing client_name happy path unchanged; draft count never
                decreases; same client_name under two contractors → conflict
                surfaced but draft still created.

Run: python -m pytest tests/test_contractor_at_birth_projection.py -q
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import document_db as ddb
from app.services import proforma_invoice_link_db as pildb
from app.services import customer_master_db as cmdb
from app.services import wfirma_db as wfdb
from app.services.customer_master_db import CustomerMaster
from app.services.proforma_draft_sync import sync_draft_from_packing_upload

CID_ACME = "182241571"
CID_NO_MASTER = "999000111"
CID_OTHER = "445566778"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path) -> Path:
    ddb.init_document_db(tmp_path / "documents.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    cmdb.init_db(tmp_path / "customer_master.sqlite")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    with patch.object(settings, "storage_root", tmp_path):
        yield tmp_path


@pytest.fixture()
def proforma_db(storage) -> Path:
    return storage / "proforma_links.db"


def _add_customer(storage: Path, cid: str, name: str) -> None:
    cmdb.upsert_customer(
        storage / "customer_master.sqlite",
        CustomerMaster(bill_to_contractor_id=cid, bill_to_name=name, country="PL"),
    )


def _register_sales_packing_doc(batch_id: str, *, cid: str = "") -> str:
    return ddb.register_document(
        batch_id=batch_id,
        document_type="sales_packing_list",
        file_name="sales_pl.xlsx",
        source="intake",
        client_contractor_id=cid,
    ) or ""


def _store_sales_doc(batch_id: str, ship_doc_id: str, *, client_name: str = "",
                     cid: str = "") -> str:
    return ddb.store_sales_document(
        batch_id=batch_id, document_id=ship_doc_id,
        data={
            "client_name":          client_name,
            "document_type":        "sales_packing_list",
            "client_contractor_id": cid,
        },
    )


def _line(product_code: str = "PC-1", client_name: str = "", **kw) -> dict:
    row = {
        "client_name":  client_name,
        "product_code": product_code,
        "design_no":    "D1",
        "quantity":     1.0,
        "unit_price":   10.0,
        "total_value":  10.0,
        "currency":     "EUR",
    }
    row.update(kw)
    return row


def _cols(db_path: Path, table: str) -> set:
    with sqlite3.connect(str(db_path)) as con:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


# ── Schema ──────────────────────────────────────────────────────────────────

class TestSchema:
    def test_columns_present_on_all_four_tables(self, storage, proforma_db):
        assert "client_contractor_id" in _cols(storage / "documents.db", "sales_documents")
        assert "client_contractor_id" in _cols(storage / "documents.db", "sales_packing_lines")
        assert "client_contractor_id" in _cols(proforma_db, "proforma_drafts")
        assert "client_contractor_id" in _cols(storage / "wfirma.db", "wfirma_reservation_drafts")

    def test_reinit_is_idempotent(self, storage, proforma_db):
        # Re-running init must not raise (additive ALTER swallows duplicate col)
        ddb.init_document_db(storage / "documents.db")
        pildb.init_db(proforma_db)
        wfdb.init_wfirma_db(storage / "wfirma.db")
        assert "client_contractor_id" in _cols(proforma_db, "proforma_drafts")

    def test_draft_birth_blocks_table_present(self, proforma_db):
        assert _cols(proforma_db, "proforma_draft_birth_blocks") >= {
            "batch_id", "sales_document_id", "client_contractor_id",
            "blocked_state", "reason", "code",
        }


# ── Projection at birth ───────────────────────────────────────────────────────

class TestProjectionAtBirth:
    def test_store_sales_document_derives_from_shipment_doc(self, storage):
        b = "B-PROJ-1"
        ship = _register_sales_packing_doc(b, cid=CID_ACME)
        # No explicit cid in data → derived from shipment_documents.
        sd_id = _store_sales_doc(b, ship, client_name="ACME")
        rows = ddb.get_sales_documents(b)
        row = next(r for r in rows if r["id"] == sd_id)
        assert row["client_contractor_id"] == CID_ACME

    def test_explicit_cid_wins(self, storage):
        b = "B-PROJ-2"
        ship = _register_sales_packing_doc(b, cid="")  # shipment doc has none
        sd_id = _store_sales_doc(b, ship, client_name="ACME", cid=CID_OTHER)
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == sd_id)
        assert row["client_contractor_id"] == CID_OTHER

    def test_lines_inherit_parent_contractor(self, storage):
        b = "B-PROJ-3"
        ship = _register_sales_packing_doc(b, cid=CID_ACME)
        sd_id = _store_sales_doc(b, ship, client_name="ACME")
        ddb.store_sales_packing_lines(sd_id, b, [_line(), _line(product_code="PC-2")])
        lines = ddb.get_sales_packing_lines(b)
        assert lines, "lines must persist"
        assert all(ln["client_contractor_id"] == CID_ACME for ln in lines)

    def test_ensure_sales_document_id_derives(self, storage):
        b = "B-PROJ-4"
        ship = _register_sales_packing_doc(b, cid=CID_ACME)
        # reprocess path: id == shipment_documents.id
        returned = ddb.ensure_sales_document_id(b, ship, document_type="sales_packing_list")
        assert returned == ship
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == ship)
        assert row["client_contractor_id"] == CID_ACME

    def test_get_or_create_for_packing_derives(self, storage):
        b = "B-PROJ-5"
        ship = _register_sales_packing_doc(b, cid=CID_ACME)
        sd_id = ddb.get_or_create_sales_document_for_packing(b, ship, "ACME")
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == sd_id)
        assert row["client_contractor_id"] == CID_ACME


# ── Backfill (idempotent reconciliation of legacy rows) ───────────────────────

class TestBackfill:
    def test_backfill_repairs_legacy_empty_rows(self, storage):
        b = "B-BF-1"
        # Legacy: shipment_documents bound the contractor AFTER the sales rows
        # were already created with empty client_contractor_id.
        ship = _register_sales_packing_doc(b, cid="")
        sd_id = _store_sales_doc(b, ship, client_name="ACME")
        ddb.store_sales_packing_lines(sd_id, b, [_line()])
        # Operator's intake pick lands on the shipment doc later.
        with sqlite3.connect(str(storage / "documents.db")) as con:
            con.execute(
                "UPDATE shipment_documents SET client_contractor_id=? WHERE id=?",
                (CID_ACME, ship),
            )
        # Pre-backfill the sales rows are unprojected.
        assert next(r for r in ddb.get_sales_documents(b)
                    if r["id"] == sd_id)["client_contractor_id"] == ""

        result = ddb.backfill_contractor_ids(b)
        assert result["sales_documents_updated"] == 1
        assert result["sales_lines_updated"] == 1
        assert next(r for r in ddb.get_sales_documents(b)
                    if r["id"] == sd_id)["client_contractor_id"] == CID_ACME
        assert all(ln["client_contractor_id"] == CID_ACME
                   for ln in ddb.get_sales_packing_lines(b))

    def test_backfill_is_idempotent(self, storage):
        b = "B-BF-2"
        ship = _register_sales_packing_doc(b, cid=CID_ACME)
        sd_id = _store_sales_doc(b, ship, client_name="ACME")
        ddb.store_sales_packing_lines(sd_id, b, [_line()])
        # Rows already projected at birth → backfill is a no-op.
        result = ddb.backfill_contractor_ids(b)
        assert result == {"sales_documents_updated": 0, "sales_lines_updated": 0}


# ── Grouping authority + recovery + blocked records ───────────────────────────

class TestGroupingAndBlocks:
    def _seed_doc(self, b: str, *, client_name: str, cid: str) -> str:
        ship = _register_sales_packing_doc(b, cid=cid)
        sd_id = _store_sales_doc(b, ship, client_name=client_name, cid=cid)
        ddb.store_sales_packing_lines(sd_id, b, [_line(client_name=client_name)])
        return sd_id

    def test_empty_name_recovered_via_contractor(self, storage, proforma_db):
        b = "B-GRP-1"
        _add_customer(storage, CID_ACME, "ACME CORP")
        self._seed_doc(b, client_name="", cid=CID_ACME)

        result = sync_draft_from_packing_upload(
            batch_id=b, operator="test", db_path=proforma_db,
            master_db_path=storage / "master_data.sqlite",
        )
        assert result["created"] == 1
        assert result["birth_blocked"] == 0
        drafts = pildb.list_drafts_for_batch(proforma_db, b)
        assert len(drafts) == 1
        assert drafts[0].client_name == "ACME CORP"          # recovered name
        assert drafts[0].client_contractor_id == CID_ACME    # projected authority

    def test_unresolved_contractor_becomes_blocked(self, storage, proforma_db):
        b = "B-GRP-2"
        # contractor present at the line, but NO Customer Master record exists.
        self._seed_doc(b, client_name="", cid=CID_NO_MASTER)
        result = sync_draft_from_packing_upload(
            batch_id=b, operator="test", db_path=proforma_db,
        )
        assert result["created"] == 0
        assert result["birth_blocked"] == 1
        blocks = pildb.list_draft_birth_blocks(proforma_db, b)
        assert len(blocks) == 1
        assert blocks[0]["code"] == "client_unresolved"
        assert blocks[0]["client_contractor_id"] == CID_NO_MASTER
        assert blocks[0]["blocked_state"] == "open"

    def test_no_name_no_contractor_blocked_and_skip_event(self, storage, proforma_db):
        b = "B-GRP-3"
        self._seed_doc(b, client_name="", cid="")  # nothing to resolve
        result = sync_draft_from_packing_upload(
            batch_id=b, operator="test", db_path=proforma_db,
        )
        assert result["created"] == 0
        assert result["birth_blocked"] == 1
        # PR-1 invariant preserved: `blocked` is the VAT/finalized counter.
        assert result["blocked"] == 0
        blocks = pildb.list_draft_birth_blocks(proforma_db, b)
        assert blocks[0]["code"] == "contractor_missing"

    def test_blocked_resolves_after_master_added(self, storage, proforma_db):
        b = "B-GRP-4"
        self._seed_doc(b, client_name="", cid=CID_ACME)
        # First sync: no CM record → blocked.
        r1 = sync_draft_from_packing_upload(
            batch_id=b, operator="test", db_path=proforma_db,
            master_db_path=storage / "master_data.sqlite",
        )
        assert r1["birth_blocked"] == 1
        assert len(pildb.list_draft_birth_blocks(proforma_db, b)) == 1

        # Operator adds the Customer Master record, then re-syncs.
        _add_customer(storage, CID_ACME, "ACME CORP")
        r2 = sync_draft_from_packing_upload(
            batch_id=b, operator="test", db_path=proforma_db,
            master_db_path=storage / "master_data.sqlite",
        )
        assert r2["created"] == 1
        # Block auto-resolves — no stale red flag.
        assert pildb.list_draft_birth_blocks(proforma_db, b) == []
        resolved = pildb.list_draft_birth_blocks(proforma_db, b, include_resolved=True)
        assert resolved and resolved[0]["blocked_state"] == "resolved"


# ── Regression: client_name path + conflict + non-decreasing draft count ──────

class TestRegression:
    def test_client_name_happy_path_unchanged(self, storage, proforma_db):
        b = "B-REG-1"
        ship = _register_sales_packing_doc(b, cid="")
        sd_id = _store_sales_doc(b, ship, client_name="FOO LTD")
        ddb.store_sales_packing_lines(sd_id, b, [_line(client_name="FOO LTD")])
        result = sync_draft_from_packing_upload(
            batch_id=b, operator="test", db_path=proforma_db,
        )
        assert result["created"] == 1
        assert result["birth_blocked"] == 0
        assert result["blocked"] == 0
        drafts = pildb.list_drafts_for_batch(proforma_db, b)
        assert drafts[0].client_name == "FOO LTD"  # storage key unchanged

    def test_same_name_two_contractors_conflict_but_draft_created(self, storage, proforma_db):
        b = "B-REG-2"
        # Two docs, same client_name "DUP CO", different contractor ids.
        for cid in (CID_ACME, CID_OTHER):
            ship = _register_sales_packing_doc(b, cid=cid)
            sd_id = _store_sales_doc(b, ship, client_name="DUP CO", cid=cid)
            ddb.store_sales_packing_lines(sd_id, b, [_line(client_name="DUP CO")])

        result = sync_draft_from_packing_upload(
            batch_id=b, operator="test", db_path=proforma_db,
        )
        # Draft is STILL created by name (no silent split/merge, no regression).
        drafts = pildb.list_drafts_for_batch(proforma_db, b)
        assert len(drafts) == 1
        assert drafts[0].client_name == "DUP CO"
        # Conflict surfaced as a visible advisory.
        assert result["contractor_conflict"] == 1
        codes = {bk["code"] for bk in pildb.list_draft_birth_blocks(proforma_db, b)}
        assert "contractor_conflict" in codes


# ── Reservation readiness reference chain ─────────────────────────────────────

class TestReservationContractorReference:
    def test_reservation_draft_carries_contractor(self, storage):
        b = "B-RES-1"
        draft_id = wfdb.upsert_reservation_draft(
            b, "ACME CORP", currency="EUR", client_contractor_id=CID_ACME,
        )
        assert draft_id
        rec = wfdb.get_reservation_draft(b, "ACME CORP")
        assert rec["client_contractor_id"] == CID_ACME

    def test_reservation_merge_does_not_clear_contractor(self, storage):
        b = "B-RES-2"
        wfdb.upsert_reservation_draft(
            b, "ACME CORP", currency="EUR", client_contractor_id=CID_ACME,
        )
        # A later upsert with empty contractor (e.g. a readiness refresh that
        # didn't carry it) must NOT clear the stored reference.
        wfdb.upsert_reservation_draft(
            b, "ACME CORP", currency="EUR", ready_to_create=True,
        )
        rec = wfdb.get_reservation_draft(b, "ACME CORP")
        assert rec["client_contractor_id"] == CID_ACME
        assert rec["ready_to_create"] == 1


# ── Merge-not-replace + arg precedence (no #570-class clobber) ────────────────

class TestMergeAndPrecedence:
    def test_get_or_create_does_not_clobber_existing_contractor(self, storage):
        b = "B-MRG-1"
        ship = _register_sales_packing_doc(b, cid=CID_ACME)
        sd_id = ddb.get_or_create_sales_document_for_packing(b, ship, "ACME")
        # The shipment doc loses its contractor (simulated drift); a second
        # get-or-create with no resolvable contractor must NOT clear the stored.
        with sqlite3.connect(str(storage / "documents.db")) as con:
            con.execute("UPDATE shipment_documents SET client_contractor_id='' WHERE id=?",
                        (ship,))
        sd_id2 = ddb.get_or_create_sales_document_for_packing(b, ship, "ACME")
        assert sd_id2 == sd_id
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == sd_id)
        assert row["client_contractor_id"] == CID_ACME  # preserved

    def test_ensure_explicit_cid_precedence_and_merge(self, storage):
        b = "B-MRG-2"
        ship = _register_sales_packing_doc(b, cid=CID_ACME)
        # Explicit arg wins over the shipment-doc derived value.
        ddb.ensure_sales_document_id(
            b, ship, document_type="sales_packing_list",
            client_contractor_id=CID_OTHER,
        )
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == ship)
        assert row["client_contractor_id"] == CID_OTHER
        # Re-run with empty arg must NOT clear the stored reference.
        ddb.ensure_sales_document_id(b, ship, document_type="sales_packing_list")
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == ship)
        assert row["client_contractor_id"] == CID_OTHER

    def test_store_sales_document_explicit_overrides_shipment_doc(self, storage):
        b = "B-MRG-3"
        ship = _register_sales_packing_doc(b, cid=CID_ACME)
        sd_id = _store_sales_doc(b, ship, client_name="ACME", cid=CID_OTHER)
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == sd_id)
        assert row["client_contractor_id"] == CID_OTHER  # explicit wins


# ── Backfill through synthetic link-as-sales document_id ──────────────────────

class TestBackfillSyntheticPackingRef:
    def test_backfill_resolves_packing_prefixed_doc(self, storage):
        b = "B-BF-3"
        # link-as-sales creates sales_documents.document_id == "packing:<ship_id>".
        ship = _register_sales_packing_doc(b, cid="")  # contractor bound later
        sd_id = ddb.get_or_create_sales_document_for_packing(b, ship, "ACME")
        ddb.store_sales_packing_lines(sd_id, b, [_line(client_name="ACME")])
        # Operator binds the contractor on the real packing shipment doc.
        with sqlite3.connect(str(storage / "documents.db")) as con:
            con.execute("UPDATE shipment_documents SET client_contractor_id=? WHERE id=?",
                        (CID_ACME, ship))
        result = ddb.backfill_contractor_ids(b)
        assert result["sales_documents_updated"] == 1
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == sd_id)
        assert row["client_contractor_id"] == CID_ACME  # resolved via packing: prefix


# ── Edge: contractor exists but Customer Master name is blank ─────────────────

class TestEmptyMasterName:
    def test_blank_bill_to_name_falls_through_to_block(self, storage, proforma_db):
        b = "B-EDGE-1"
        # CustomerMaster requires a non-empty bill_to_name at write time, so we
        # write a row then blank the name to simulate a corrupt/incomplete master.
        _add_customer(storage, CID_ACME, "PLACEHOLDER")
        with sqlite3.connect(str(storage / "customer_master.sqlite")) as con:
            con.execute("UPDATE customer_master SET bill_to_name='' WHERE bill_to_contractor_id=?",
                        (CID_ACME,))
        ship = _register_sales_packing_doc(b, cid=CID_ACME)
        sd_id = _store_sales_doc(b, ship, client_name="", cid=CID_ACME)
        ddb.store_sales_packing_lines(sd_id, b, [_line(client_name="")])
        result = sync_draft_from_packing_upload(
            batch_id=b, operator="test", db_path=proforma_db,
        )
        assert result["created"] == 0
        assert result["birth_blocked"] == 1
        blocks = pildb.list_draft_birth_blocks(proforma_db, b)
        assert blocks[0]["code"] == "client_unresolved"


# ── HTTP route end-to-end (execution path: API → projection → DB → blocks) ────

class TestBackfillRoute:
    @pytest.fixture()
    def client(self, storage):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth.dependencies import require_admin
        from app.core.security import require_api_key
        app.dependency_overrides[require_admin] = lambda: {
            "id": "test-admin", "username": "admin", "role": "admin",
        }
        app.dependency_overrides[require_api_key] = lambda: {"id": "test-admin"}
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
        app.dependency_overrides.clear()

    def test_backfill_route_projects_and_lists_blocks(self, client, storage, proforma_db):
        b = "B-ROUTE-1"
        # Legacy batch: contractor bound on shipment_documents AFTER sales rows.
        ship = _register_sales_packing_doc(b, cid="")
        sd_id = ddb.store_sales_document(
            batch_id=b, document_id=ship,
            data={"client_name": "ACME", "document_type": "sales_packing_list"},
        )
        ddb.store_sales_packing_lines(sd_id, b, [_line(client_name="ACME")])
        with sqlite3.connect(str(storage / "documents.db")) as con:
            con.execute("UPDATE shipment_documents SET client_contractor_id=? WHERE id=?",
                        (CID_ACME, ship))

        r = client.post(f"/api/v1/admin/contractor-projection/backfill/{b}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["projection"]["sales_documents_updated"] == 1
        # Contractor now projected on the sales row.
        row = next(rr for rr in ddb.get_sales_documents(b) if rr["id"] == sd_id)
        assert row["client_contractor_id"] == CID_ACME

        g = client.get(f"/api/v1/admin/contractor-projection/blocks/{b}")
        assert g.status_code == 200
        assert "blocks" in g.json()

    def test_backfill_route_rejects_path_traversal(self, client):
        # A single path segment that reaches the handler and trips the guard
        # (contains "..": parent-dir traversal attempt). Encoded-slash forms are
        # already rejected by the framework with 404 — this pins OUR 400 guard.
        r = client.post("/api/v1/admin/contractor-projection/backfill/evil..seg")
        assert r.status_code == 400, r.text
        # Backslash (Windows path separator) in a value that reaches the handler.
        r2 = client.get("/api/v1/admin/contractor-projection/blocks/bad%5Cseg")
        assert r2.status_code == 400, r2.text

    def test_blocks_route_surfaces_open_block(self, client, storage, proforma_db):
        b = "B-ROUTE-2"
        # Unresolvable contractor (no Customer Master row) → blocked on sync.
        ship = _register_sales_packing_doc(b, cid=CID_NO_MASTER)
        sd_id = _store_sales_doc(b, ship, client_name="", cid=CID_NO_MASTER)
        ddb.store_sales_packing_lines(sd_id, b, [_line(client_name="")])
        client.post(f"/api/v1/admin/contractor-projection/backfill/{b}")
        g = client.get(f"/api/v1/admin/contractor-projection/blocks/{b}")
        assert g.status_code == 200
        body = g.json()
        assert body["count"] >= 1
        assert body["blocks"][0]["code"] == "client_unresolved"
