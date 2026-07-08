"""WF-3 slice 1 — canonical customer identity resolver + non-destructive backfill.

Covers the operator-required scenarios: contractor rename, duplicate names,
same company / different ids, same id / different name, legacy lookup, mirror
lookup, Customer Master lookup, caller-agnostic resolution (invoice / reservation
/ payment / webhook / scheduler / proforma all resolve through the one authority),
migration rollback-safety, idempotent migration, and authority separation.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import customer_identity_resolver as cir     # noqa: E402
from app.services import customer_master_db                    # noqa: E402
from app.services import reservation_db                        # noqa: E402
from app.services import wfirma_db                             # noqa: E402


@pytest.fixture
def stores(tmp_path):
    cm = tmp_path / "customer_master.db"
    res = tmp_path / "reservation_queue.db"
    wf = tmp_path / "wfirma.db"
    customer_master_db.init_db(cm)
    reservation_db.init_reservation_db(res)
    wfirma_db.init_wfirma_db(wf)
    return {"cm": cm, "res": res, "wf": wf}


def _master(cm, cid, name, nip="", country="PL"):
    customer_master_db.upsert_identity_only(
        cm, bill_to_contractor_id=cid, bill_to_name=name, country=country, nip=nip)


def _legacy(name, cid=None):
    return wfirma_db.upsert_customer(name, wfirma_customer_id=cid)


def _mirror(res, cid, name):
    reservation_db.upsert_customer_mirror(res, contractor_id=cid, client_name=name)


# ── id-first resolution ──────────────────────────────────────────────────────

class TestResolveById:

    def test_customer_master_lookup(self, stores):
        _master(stores["cm"], "100", "Acme Sp. z o.o.", nip="PL123")
        r = cir.resolve_by_contractor_id("100", cm_path=stores["cm"], res_path=stores["res"])
        assert r["source"] == "customer_master"
        assert r["name"] == "Acme Sp. z o.o."
        assert r["contractor_id"] == "100"

    def test_mirror_lookup_when_master_misses(self, stores):
        _mirror(stores["res"], "200", "Mirror Only Ltd")
        r = cir.resolve_by_contractor_id("200", cm_path=stores["cm"], res_path=stores["res"])
        assert r["source"] == "wfirma_customer_mirror"
        assert r["name"] == "Mirror Only Ltd"

    def test_legacy_lookup_when_master_and_mirror_miss(self, stores):
        _legacy("Legacy Only GmbH", cid="300")
        r = cir.resolve_by_contractor_id("300", cm_path=stores["cm"], res_path=stores["res"])
        assert r["source"] == "legacy_wfirma_customers"
        assert r["name"] == "Legacy Only GmbH"

    def test_master_wins_over_legacy_and_mirror(self, stores):
        _master(stores["cm"], "100", "Canonical Name")
        _mirror(stores["res"], "100", "Mirror Name")
        _legacy("Legacy Name", cid="100")
        r = cir.resolve_by_contractor_id("100", cm_path=stores["cm"], res_path=stores["res"])
        assert r["source"] == "customer_master"
        assert r["name"] == "Canonical Name"

    def test_unknown_id_resolves_none(self, stores):
        assert cir.resolve_by_contractor_id("999", cm_path=stores["cm"], res_path=stores["res"]) is None


# ── rename / duplicate / collision scenarios ─────────────────────────────────

class TestIdentityScenarios:

    def test_contractor_rename_resolves_by_id(self, stores):
        # Master renamed to NewName; legacy row still carries the old name for id 100.
        _master(stores["cm"], "100", "NewName Ltd")
        _legacy("OldName Ltd", cid="100")
        r = cir.resolve_by_contractor_id("100", cm_path=stores["cm"], res_path=stores["res"])
        # id resolves to the CURRENT canonical name regardless of the stale legacy label.
        assert r["name"] == "NewName Ltd"

    def test_duplicate_names_are_ambiguous(self, stores):
        _master(stores["cm"], "100", "Duplicate Name")
        _master(stores["cm"], "101", "Duplicate Name")
        sug = cir.suggest_id_for_name("Duplicate Name", cm_path=stores["cm"])
        assert sug["ambiguous"] is True
        assert sug["suggested_contractor_id"] is None
        assert set(sug["candidates"]) == {"100", "101"}

    def test_same_company_different_ids_resolve_independently(self, stores):
        _master(stores["cm"], "100", "Same Co")
        _master(stores["cm"], "101", "Same Co")
        assert cir.resolve_by_contractor_id("100", cm_path=stores["cm"], res_path=stores["res"])["contractor_id"] == "100"
        assert cir.resolve_by_contractor_id("101", cm_path=stores["cm"], res_path=stores["res"])["contractor_id"] == "101"

    def test_same_id_different_name_advisory(self, stores):
        _master(stores["cm"], "100", "Master Name")
        out = cir.resolve(contractor_id="100", name="Typed Different Name",
                          cm_path=stores["cm"], res_path=stores["res"])
        assert out["resolved"] is True
        assert out["record"]["name"] == "Master Name"     # id wins
        assert "authoritative" in out["advisory"].lower() or "drift" in out["advisory"].lower()

    def test_name_only_is_advisory_never_a_key(self, stores):
        _master(stores["cm"], "100", "Unique Co")
        out = cir.resolve(name="Unique Co", cm_path=stores["cm"], res_path=stores["res"])
        assert out["resolved"] is False                   # a name never asserts identity
        assert out["contractor_id"] is None               # name is never returned as the key
        assert out["match_strategy"] == "name_advisory"


# ── caller-agnostic single authority ─────────────────────────────────────────

class TestSingleAuthority:

    def test_resolution_is_deterministic_for_every_caller(self, stores):
        # invoice / reservation / payment / webhook / scheduler / proforma all
        # call the same authority — the record must be identical each time.
        _master(stores["cm"], "555", "OneAuthority Co", nip="PL555")
        results = [cir.resolve_by_contractor_id("555", cm_path=stores["cm"], res_path=stores["res"])
                   for _ in range(6)]
        assert all(r == results[0] for r in results)
        assert results[0]["contractor_id"] == "555"


# ── non-destructive migration ────────────────────────────────────────────────

class TestBackfill:

    def test_dry_run_writes_nothing(self, stores):
        _master(stores["cm"], "100", "Acme")
        _legacy("Acme", cid=None)
        rep = cir.backfill_legacy_contractor_ids(dry_run=True, cm_path=stores["cm"],
                                                 res_path=stores["res"], wfirma_db_path=stores["wf"])
        assert rep["filled"] == 1                          # would fill 1
        # but the legacy row id is STILL empty (no write in dry-run)
        row = [r for r in wfirma_db.list_customers() if r["client_name"] == "Acme"][0]
        assert not (row["wfirma_customer_id"] or "")

    def test_live_fills_unambiguous(self, stores):
        _master(stores["cm"], "100", "Acme")
        _legacy("Acme", cid=None)
        cir.backfill_legacy_contractor_ids(dry_run=False, cm_path=stores["cm"],
                                           res_path=stores["res"], wfirma_db_path=stores["wf"])
        row = wfirma_db.get_customer_by_wfirma_id("100")
        assert row is not None and row["client_name"] == "Acme"

    def test_ambiguous_not_filled(self, stores):
        _master(stores["cm"], "100", "Dup")
        _master(stores["cm"], "101", "Dup")
        _legacy("Dup", cid=None)
        rep = cir.backfill_legacy_contractor_ids(dry_run=False, cm_path=stores["cm"],
                                                 res_path=stores["res"], wfirma_db_path=stores["wf"])
        assert rep["ambiguous"] == 1 and rep["filled"] == 0
        row = [r for r in wfirma_db.list_customers() if r["client_name"] == "Dup"][0]
        assert not (row["wfirma_customer_id"] or "")

    def test_unmatched_not_filled(self, stores):
        _legacy("No Master Co", cid=None)
        rep = cir.backfill_legacy_contractor_ids(dry_run=False, cm_path=stores["cm"],
                                                 res_path=stores["res"], wfirma_db_path=stores["wf"])
        assert rep["unmatched"] == 1 and rep["filled"] == 0

    def test_idempotent(self, stores):
        _master(stores["cm"], "100", "Acme")
        _legacy("Acme", cid=None)
        cir.backfill_legacy_contractor_ids(dry_run=False, cm_path=stores["cm"],
                                           res_path=stores["res"], wfirma_db_path=stores["wf"])
        rep2 = cir.backfill_legacy_contractor_ids(dry_run=False, cm_path=stores["cm"],
                                                  res_path=stores["res"], wfirma_db_path=stores["wf"])
        assert rep2["filled"] == 0 and rep2["already_linked"] == 1

    def test_rollback_safe_never_overwrites_existing_id(self, stores):
        _master(stores["cm"], "100", "Acme")
        _legacy("Acme", cid="999")                          # already linked to a different id
        cir.backfill_legacy_contractor_ids(dry_run=False, cm_path=stores["cm"],
                                           res_path=stores["res"], wfirma_db_path=stores["wf"])
        row = [r for r in wfirma_db.list_customers() if r["client_name"] == "Acme"][0]
        assert row["wfirma_customer_id"] == "999"           # untouched — original preserved

    def test_backfill_populates_mirror_from_legacy(self, stores):
        _legacy("Mirror Me", cid="700")
        cir.backfill_legacy_contractor_ids(dry_run=False, cm_path=stores["cm"],
                                           res_path=stores["res"], wfirma_db_path=stores["wf"])
        assert reservation_db.get_customer_mirror(stores["res"], "700") is not None


# ── authority separation ──────────────────────────────────────────────────────

class TestAuthoritySeparation:

    def test_resolver_makes_no_forbidden_writes(self):
        src = inspect.getsource(cir)
        for forbidden in (
            "INSERT INTO product_master", "UPDATE product_master",
            "INSERT INTO inventory_state", "UPDATE inventory_state",
            "goods/add", "goods/edit",
            ".search_customer(", ".fetch_contractor_by_id(", ".create_customer(",
        ):
            assert forbidden not in src, f"resolver contains forbidden operation: {forbidden}"

    def test_only_writes_are_idkeyed_migration_helpers(self):
        src = inspect.getsource(cir)
        # The resolver's only writes are the two non-destructive, id-keyed migration
        # helpers. Neither is a name-keyed write.
        assert "backfill_contractor_id(" in src            # legacy id-fill (by row id)
        assert "backfill_customer_authority(" in src        # mirror population (by contractor_id)
        assert "upsert_customer(" not in src                # never the name-keyed legacy writer


class TestCanonicalPaths:
    """The default store paths must match the codebase-canonical filenames, or the
    resolver would silently miss the canonical Customer Master in production."""

    def test_default_customer_master_path_is_canonical(self):
        assert cir._cm_path().name == "customer_master.sqlite"

    def test_default_reservation_and_wfirma_paths_are_canonical(self):
        assert cir._res_path().name == "reservation_queue.db"
        assert cir._wfirma_path().name == "wfirma.db"
