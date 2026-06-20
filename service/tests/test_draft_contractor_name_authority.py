"""test_draft_contractor_name_authority.py — PR-3 Dropdown selection wins
==========================================================================

Real-builder tests (no mocked success paths) pinning the operator decision that
the Customer-Master dropdown selection (client_contractor_id) is the
AUTHORITATIVE draft identity and OVERRIDES a parsed/stored client_name — with a
safe, DISCLOSED migration of freight/insurance + reservation keyed by the old
name (operator chose "canonical always wins"; dropped non-zero amounts are
reported, never silent).

Contracts pinned:
  Forward  — a line carrying a resolvable contractor is grouped/born under the
             canonical CM bill_to_name (overrides the parsed name); the sales
             chain (sales_documents + sales_packing_lines) is canonicalized so a
             re-upload never spawns a duplicate parsed-name draft.
  Migrate  — existing EDITABLE draft renamed in place when no canonical draft
             exists (charges MOVED, preserved); superseded + charges DROPPED +
             DISCLOSED when a canonical draft already exists.
  Frozen   — posted/approved drafts are never renamed.
  Resolver — derive_customer_authority_for_draft resolves by client_contractor_id
             directly (match_strategy='draft_contractor_id'), independent of name.
  Idempot. — a second migration run is a no-op.
  Regress. — a no-contractor line keeps its parsed name (PR-2 behaviour).

Run: python -m pytest tests/test_draft_contractor_name_authority.py -q
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
from app.services import proforma_service_charges_db as psc
from app.services.customer_master_db import CustomerMaster
from app.services.proforma_draft_sync import sync_draft_from_packing_upload

CID = "182241571"
CANON = "ACME CORP"
PARSED = "Acme"


@pytest.fixture()
def storage(tmp_path) -> Path:
    ddb.init_document_db(tmp_path / "documents.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    psc.init(tmp_path / "proforma_links.db")
    cmdb.init_db(tmp_path / "customer_master.sqlite")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    cmdb.upsert_customer(
        tmp_path / "customer_master.sqlite",
        CustomerMaster(bill_to_contractor_id=CID, bill_to_name=CANON, country="PL"),
    )
    with patch.object(settings, "storage_root", tmp_path):
        yield tmp_path


@pytest.fixture()
def pf_db(storage) -> Path:
    return storage / "proforma_links.db"


def _seed_sales(batch: str, *, client_name: str, cid: str) -> str:
    ship = ddb.register_document(
        batch_id=batch, document_type="sales_packing_list",
        file_name="s.xlsx", source="intake", client_contractor_id=cid,
    ) or ""
    sd = ddb.store_sales_document(
        batch_id=batch, document_id=ship,
        data={"client_name": client_name, "document_type": "sales_packing_list",
              "client_contractor_id": cid},
    )
    ddb.store_sales_packing_lines(sd, batch, [{
        "client_name": client_name, "product_code": "PC-1", "design_no": "D1",
        "quantity": 1.0, "unit_price": 10.0, "total_value": 10.0, "currency": "EUR",
    }])
    return sd


def _drafts(pf_db, batch):
    return pildb.list_drafts_for_batch(pf_db, batch)


def _migrators():
    return dict(
        charge_move=psc.move_charges_client_name,
        charge_drop=psc.drop_charges_client_name,
        reservation_migrate=wfdb.rename_reservation_draft_client,
    )


# ── Forward: dropdown wins at birth + no duplicate on re-upload ───────────────

class TestForwardOverride:
    def test_draft_born_under_canonical_name(self, storage, pf_db):
        b = "B-FWD-1"
        _seed_sales(b, client_name=PARSED, cid=CID)
        r = sync_draft_from_packing_upload(batch_id=b, operator="t", db_path=pf_db)
        assert r["created"] == 1
        drafts = _drafts(pf_db, b)
        assert len(drafts) == 1
        assert drafts[0].client_name == CANON          # canonical overrides parsed
        # sales chain canonicalized (no split-brain)
        sd = ddb.get_sales_documents(b)[0]
        assert sd["client_name"] == CANON
        assert all(l["client_name"] == CANON for l in ddb.get_sales_packing_lines(b))

    def test_reupload_does_not_duplicate(self, storage, pf_db):
        b = "B-FWD-2"
        _seed_sales(b, client_name=PARSED, cid=CID)
        sync_draft_from_packing_upload(batch_id=b, operator="t", db_path=pf_db)
        # second sync (re-upload) must reuse the same canonical draft
        sync_draft_from_packing_upload(batch_id=b, operator="t", db_path=pf_db)
        assert len(_drafts(pf_db, b)) == 1

    def test_no_contractor_keeps_parsed_name(self, storage, pf_db):
        b = "B-FWD-3"
        _seed_sales(b, client_name="FOO LTD", cid="")  # no contractor
        r = sync_draft_from_packing_upload(batch_id=b, operator="t", db_path=pf_db)
        assert r["created"] == 1
        assert _drafts(pf_db, b)[0].client_name == "FOO LTD"  # PR-2 behaviour


# ── Migration of EXISTING drafts ──────────────────────────────────────────────

class TestMigration:
    def test_rename_in_place_moves_charges(self, storage, pf_db):
        b = "B-MIG-1"
        # Existing parsed-name draft with operator freight + reservation.
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=PARSED, currency="EUR",
            lines=[{"product_code": "PC-1", "qty": 1, "unit_price": 10}],
            client_contractor_id=CID,
        )
        psc.upsert_charge(batch_id=b, client_name=PARSED, charge_type="freight",
                          amount=1500.0, currency="EUR")
        wfdb.upsert_reservation_draft(b, PARSED, currency="EUR", client_contractor_id=CID)

        rep = pildb.migrate_draft_to_canonical_name(pf_db, b, PARSED, CANON, **_migrators())
        assert rep["action"] == "renamed"
        assert _drafts(pf_db, b)[0].client_name == CANON
        # charges MOVED, amount preserved exactly
        assert psc.list_charges(b, PARSED) == []
        moved = psc.list_charges(b, CANON)
        assert len(moved) == 1 and moved[0]["amount"] == 1500.0
        assert rep["dropped_charges"] == []
        # reservation renamed
        assert wfdb.get_reservation_draft(b, CANON) is not None
        assert wfdb.get_reservation_draft(b, PARSED) is None

    def test_collision_supersedes_and_discloses_dropped_charge(self, storage, pf_db):
        b = "B-MIG-2"
        # Both a parsed-name draft (with freight) AND a canonical draft (empty) exist.
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=PARSED, currency="EUR",
            lines=[{"product_code": "PC-1", "qty": 1, "unit_price": 10}],
            client_contractor_id=CID)
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=CANON, currency="EUR",
            lines=[{"product_code": "PC-2", "qty": 1, "unit_price": 20}],
            client_contractor_id=CID)
        psc.upsert_charge(batch_id=b, client_name=PARSED, charge_type="freight",
                          amount=1500.0, currency="EUR")

        rep = pildb.migrate_draft_to_canonical_name(pf_db, b, PARSED, CANON, **_migrators())
        assert rep["action"] == "superseded"
        # canonical-wins: the dropped freight is DISCLOSED, not silent
        assert any(d["amount"] == 1500.0 and d["charge_type"] == "freight"
                   for d in rep["dropped_charges"])
        assert psc.list_charges(b, PARSED) == []
        # old draft superseded; canonical remains. Verify states directly.
        with sqlite3.connect(str(pf_db)) as con:
            con.row_factory = sqlite3.Row
            rows = {r["client_name"]: r["draft_state"] for r in con.execute(
                "SELECT client_name, draft_state FROM proforma_drafts WHERE batch_id=?",
                (b,))}
        assert rows.get(PARSED) == "superseded"
        assert rows.get(CANON) in ("draft", "editing", "post_failed")

    def test_posted_draft_not_renamed(self, storage, pf_db):
        b = "B-MIG-3"
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=PARSED, currency="EUR",
            lines=[{"product_code": "PC-1", "qty": 1, "unit_price": 10}],
            client_contractor_id=CID)
        with sqlite3.connect(str(pf_db)) as con:
            con.execute("UPDATE proforma_drafts SET draft_state='posted' "
                        "WHERE batch_id=? AND client_name=?", (b, PARSED))
        rep = pildb.migrate_draft_to_canonical_name(pf_db, b, PARSED, CANON, **_migrators())
        assert len(rep["skipped_frozen"]) == 1
        # name unchanged — frozen identity protected
        with sqlite3.connect(str(pf_db)) as con:
            names = [r[0] for r in con.execute(
                "SELECT client_name FROM proforma_drafts WHERE batch_id=?", (b,))]
        assert PARSED in names and CANON not in names

    def test_idempotent_second_run_noop(self, storage, pf_db):
        b = "B-MIG-4"
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=PARSED, currency="EUR",
            lines=[{"product_code": "PC-1", "qty": 1, "unit_price": 10}],
            client_contractor_id=CID)
        pildb.migrate_draft_to_canonical_name(pf_db, b, PARSED, CANON, **_migrators())
        # second run: old name no longer present → noop
        rep2 = pildb.migrate_draft_to_canonical_name(pf_db, b, PARSED, CANON, **_migrators())
        assert rep2["action"] == "noop"
        assert len(_drafts(pf_db, b)) == 1


# ── Resolver contractor-id-first ──────────────────────────────────────────────

class TestResolverContractorIdFirst:
    def test_resolves_by_contractor_id_regardless_of_name(self, storage):
        from app.services.customer_resolution_authority import (
            derive_customer_authority_for_draft,
        )
        res = derive_customer_authority_for_draft(
            batch_id="B-RES",
            client_name="totally-different-name",
            documents_db_path=storage / "documents.db",
            customer_master_db_path=storage / "customer_master.sqlite",
            client_contractor_id=CID,
        )
        assert res is not None
        assert res["match_strategy"] == "draft_contractor_id"
        assert res["resolved_master_name"] == CANON
        assert res["wfirma_customer_id"] == CID

    def test_cm_miss_falls_through_to_name_chain(self, storage):
        from app.services.customer_resolution_authority import (
            derive_customer_authority_for_draft,
        )
        # contractor id with NO Customer Master row → must not assert; fall
        # through (returns None here because no sales doc under that name).
        res = derive_customer_authority_for_draft(
            batch_id="B-RES-MISS", client_name="Nobody",
            documents_db_path=storage / "documents.db",
            customer_master_db_path=storage / "customer_master.sqlite",
            client_contractor_id="000-no-master",
        )
        assert res is None


# ── Review-driven hardening: frozen canonical, collisions, clones, ambiguity ──

class TestMigrationHardening:
    def test_frozen_canonical_preserves_charges_not_dropped(self, storage, pf_db):
        """CRITICAL fix: superseding into a FROZEN/posted canonical must MOVE
        (preserve) charges, never DROP — a posted draft can never receive a
        re-entered amount, so dropping would be unrecoverable money loss."""
        b = "B-FZ-1"
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=PARSED, currency="EUR",
            lines=[{"product_code": "PC-1", "qty": 1, "unit_price": 10}],
            client_contractor_id=CID)
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=CANON, currency="EUR",
            lines=[{"product_code": "PC-2", "qty": 1, "unit_price": 20}],
            client_contractor_id=CID)
        with sqlite3.connect(str(pf_db)) as con:
            con.execute("UPDATE proforma_drafts SET draft_state='posted' "
                        "WHERE batch_id=? AND client_name=?", (b, CANON))
        psc.upsert_charge(batch_id=b, client_name=PARSED, charge_type="freight",
                          amount=1500.0, currency="EUR")
        rep = pildb.migrate_draft_to_canonical_name(pf_db, b, PARSED, CANON, **_migrators())
        assert rep["charge_mode"] == "move"   # frozen canonical → preserve
        assert any(c["amount"] == 1500.0 for c in psc.list_charges(b, CANON))
        assert psc.list_charges(b, PARSED) == []

    def test_move_collision_subpath_discloses(self, storage, pf_db):
        """Pure-rename path where canonical name already holds the same
        charge_type → that slot is dropped + DISCLOSED; canonical value kept."""
        b = "B-FZ-2"
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=PARSED, currency="EUR",
            lines=[{"product_code": "PC-1", "qty": 1, "unit_price": 10}],
            client_contractor_id=CID)
        psc.upsert_charge(batch_id=b, client_name=PARSED, charge_type="freight",
                          amount=100.0, currency="EUR")
        psc.upsert_charge(batch_id=b, client_name=CANON, charge_type="freight",
                          amount=999.0, currency="EUR")
        rep = pildb.migrate_draft_to_canonical_name(pf_db, b, PARSED, CANON, **_migrators())
        assert rep["action"] == "renamed"
        assert any(d["amount"] == 100.0 and
                   d["reason"] == "canonical_already_has_charge_type"
                   for d in rep["dropped_charges"])
        assert [c["amount"] for c in psc.list_charges(b, CANON)] == [999.0]

    def test_clone_generation_handled(self, storage, pf_db):
        """A cloned draft (gen>0) under the old name is migrated without an
        IntegrityError; the old name is no longer an EDITABLE draft."""
        b = "B-FZ-3"
        d0, _ = pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=PARSED, currency="EUR",
            lines=[{"product_code": "PC-1", "qty": 1, "unit_price": 10}],
            client_contractor_id=CID)
        pildb.clone_draft(pf_db, d0.id)  # gen1 under PARSED
        rep = pildb.migrate_draft_to_canonical_name(pf_db, b, PARSED, CANON, **_migrators())
        # both generations handled (renamed, since no canonical pre-existed)
        assert len(rep["renamed"]) >= 2
        with sqlite3.connect(str(pf_db)) as con:
            parsed_left = con.execute(
                "SELECT COUNT(*) FROM proforma_drafts WHERE batch_id=? "
                "AND client_name=? AND draft_state IN ('draft','editing','post_failed')",
                (b, PARSED)).fetchone()[0]
        assert parsed_left == 0

    def test_reservation_collision_drops_old(self, storage, pf_db):
        b = "B-FZ-4"
        wfdb.upsert_reservation_draft(b, PARSED, currency="EUR", client_contractor_id=CID)
        wfdb.upsert_reservation_draft(b, CANON, currency="EUR", client_contractor_id=CID)
        out = wfdb.rename_reservation_draft_client(b, PARSED, CANON)
        assert out["action"] == "dropped_old"
        assert wfdb.get_reservation_draft(b, PARSED) is None
        assert wfdb.get_reservation_draft(b, CANON) is not None

    def test_defensive_branches_log_not_nameerror(self, storage, pf_db):
        """The migration's defensive except branches call log.warning — pin that
        `log` is bound (a raising migrator must be swallowed, never NameError)."""
        import logging as _logging
        assert isinstance(pildb.log, _logging.Logger)
        b = "B-LOG-1"
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=PARSED, currency="EUR",
            lines=[{"product_code": "PC-1", "qty": 1, "unit_price": 10}],
            client_contractor_id=CID)

        def _raiser(*a, **k):
            raise RuntimeError("boom")

        rep = pildb.migrate_draft_to_canonical_name(
            pf_db, b, PARSED, CANON,
            charge_move=_raiser, charge_drop=_raiser, reservation_migrate=_raiser)
        # rename still committed; the raising callables were swallowed via log.warning
        assert rep["action"] == "renamed"


# ── HTTP route end-to-end (migration via the backfill endpoint) ───────────────

class TestBackfillRouteMigration:
    @pytest.fixture()
    def client(self, storage):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth.dependencies import require_admin
        from app.core.security import require_api_key
        app.dependency_overrides[require_admin] = lambda: {
            "id": "admin", "username": "admin", "role": "admin"}
        app.dependency_overrides[require_api_key] = lambda: {"id": "admin"}
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
        app.dependency_overrides.clear()

    def test_route_renames_draft_and_moves_charges(self, client, storage, pf_db):
        b = "B-RT-1"
        _seed_sales(b, client_name=PARSED, cid=CID)
        pildb.auto_create_draft_from_sales_packing(
            pf_db, batch_id=b, client_name=PARSED, currency="EUR",
            lines=[{"product_code": "PC-1", "qty": 1, "unit_price": 10}],
            client_contractor_id=CID)
        psc.upsert_charge(batch_id=b, client_name=PARSED, charge_type="freight",
                          amount=1500.0, currency="EUR")

        r = client.post(f"/api/v1/admin/contractor-projection/backfill/{b}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["canonical_renames"], "expected a canonical rename"
        # draft renamed to canonical; freight moved (preserved)
        assert any(d.client_name == CANON for d in _drafts(pf_db, b))
        assert any(c["amount"] == 1500.0 for c in psc.list_charges(b, CANON))

    def test_route_skips_ambiguous_same_name_two_contractors(self, client, storage, pf_db):
        b = "B-RT-2"
        # second Customer-Master contractor with a different canonical name
        cmdb.upsert_customer(
            storage / "customer_master.sqlite",
            CustomerMaster(bill_to_contractor_id="333", bill_to_name="BETA LTD",
                           country="PL"))
        # two sales docs, SAME parsed name "DUP", DIFFERENT contractors
        _seed_sales(b, client_name="DUP", cid=CID)
        _seed_sales(b, client_name="DUP", cid="333")
        r = client.post(f"/api/v1/admin/contractor-projection/backfill/{b}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert any(a["old"] == "DUP" for a in body["ambiguous_renames"])
        # DUP was NOT migrated to either canonical
        assert not any(m.get("old_client_name") == "DUP"
                       for m in body["canonical_renames"])
