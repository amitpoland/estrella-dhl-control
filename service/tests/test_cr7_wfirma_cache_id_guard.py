"""CR7 (MASTER-EXEC-1 Campaign Run 7, governance gap G1) — cache id guard.

Root cause: wfirma_db.upsert_product updated wfirma_product_id UNCONDITIONALLY
on the existing-row branch — a None incoming value erased a stored id, and a
different incoming value silently replaced a confirmed id without consulting
the canonical wfirma_product_mirror (reservation_queue.db, UNIQUE(wfirma_id),
collision-refused). PM4 background sync widened the exposure by auto-running
the dry-run discovery path (pending_adoption write) after every intake.

Pins: never-erase for wfirma_product_id; a stored id changes ONLY when the
mirror confirms the incoming id for the same product_code (fail-closed);
a refused write leaves the whole row untouched (no sync_status demotion);
refusals surface as structured warnings; inserts and same-id updates are
unchanged; the auto-register discovery path reports a refusal as failed
instead of silently diverging; the cache module never writes the mirror.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import wfirma_db as wfdb            # noqa: E402
from app.services import reservation_db as rdb        # noqa: E402


CODE = "EJL/G1/001"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "storage_root", tmp_path)
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    return tmp_path


def _seed(code=CODE, wid="X-100", status="matched", **kw):
    return wfdb.upsert_product(code, wfirma_product_id=wid,
                               product_name_pl="Ring", sync_status=status, **kw)


class TestNeverErase:
    def test_none_incoming_preserves_stored_id(self, db):
        _seed()
        wfdb.upsert_product(CODE, product_name_pl="Ring v2")   # id defaults to None
        row = wfdb.get_product(CODE)
        assert row["wfirma_product_id"] == "X-100"
        assert row["product_name_pl"] == "Ring v2"             # non-identity fields update

    def test_empty_incoming_preserves_stored_id(self, db):
        _seed()
        wfdb.upsert_product(CODE, wfirma_product_id="", sync_status="matched")
        assert wfdb.get_product(CODE)["wfirma_product_id"] == "X-100"


class TestDivergentOverwrite:
    def test_refused_without_mirror_confirmation(self, db):
        row_id = _seed()
        refusals: list = []
        ret = wfdb.upsert_product(CODE, wfirma_product_id="Y-200",
                                  product_name_pl="Other good",
                                  sync_status="pending_adoption",
                                  refusals=refusals)
        row = wfdb.get_product(CODE)
        assert row["wfirma_product_id"] == "X-100"          # id untouched
        assert row["sync_status"] == "matched"              # no demotion
        assert row["product_name_pl"] == "Ring"             # whole write refused
        assert ret == row_id                                # contract: row id returned
        assert len(refusals) == 1
        ref = refusals[0]
        assert ref["refused"] is True
        assert ref["current_id"] == "X-100"
        assert ref["attempted_id"] == "Y-200"
        assert ref["product_code"] == CODE
        assert "mirror" in ref["reason"]

    def test_allowed_when_mirror_confirms(self, db):
        _seed()
        res = rdb.upsert_product_mirror(db / "reservation_queue.db",
                                        wfirma_id="Y-200", product_code=CODE)
        assert res["collision"] is False
        refusals: list = []
        wfdb.upsert_product(CODE, wfirma_product_id="Y-200",
                            sync_status="matched", refusals=refusals)
        assert refusals == []
        assert wfdb.get_product(CODE)["wfirma_product_id"] == "Y-200"

    def test_refused_when_mirror_maps_code_to_other_id(self, db):
        _seed()
        rdb.upsert_product_mirror(db / "reservation_queue.db",
                                  wfirma_id="X-100", product_code=CODE)
        refusals: list = []
        wfdb.upsert_product(CODE, wfirma_product_id="Z-999", refusals=refusals)
        assert len(refusals) == 1
        assert wfdb.get_product(CODE)["wfirma_product_id"] == "X-100"

    def test_fail_closed_when_mirror_db_absent(self, db):
        (db / "reservation_queue.db").unlink()              # no mirror at all
        _seed()
        refusals: list = []
        wfdb.upsert_product(CODE, wfirma_product_id="Y-200", refusals=refusals)
        assert len(refusals) == 1
        assert wfdb.get_product(CODE)["wfirma_product_id"] == "X-100"


class TestUnchangedPaths:
    def test_same_id_update_idempotent(self, db):
        _seed()
        refusals: list = []
        wfdb.upsert_product(CODE, wfirma_product_id="X-100",
                            product_name_pl="Ring v3", sync_status="matched",
                            refusals=refusals)
        row = wfdb.get_product(CODE)
        assert refusals == []
        assert row["wfirma_product_id"] == "X-100"
        assert row["product_name_pl"] == "Ring v3"

    def test_insert_new_row_unchanged(self, db):
        rid = wfdb.upsert_product("EJL/G1/NEW", wfirma_product_id="N-1")
        assert rid
        assert wfdb.get_product("EJL/G1/NEW")["wfirma_product_id"] == "N-1"

    def test_insert_without_id_unchanged(self, db):
        wfdb.upsert_product("EJL/G1/NOID", sync_status="pending")
        assert not (wfdb.get_product("EJL/G1/NOID")["wfirma_product_id"] or "")

    def test_fill_empty_id_needs_no_mirror(self, db):
        # pending_adoption discovery flow: unmirrored by design; filling an
        # EMPTY stored id must keep working without a mirror row.
        wfdb.upsert_product(CODE, sync_status="pending")
        refusals: list = []
        wfdb.upsert_product(CODE, wfirma_product_id="D-1",
                            sync_status="pending_adoption", refusals=refusals)
        row = wfdb.get_product(CODE)
        assert refusals == []
        assert row["wfirma_product_id"] == "D-1"
        assert row["sync_status"] == "pending_adoption"


class TestAutoRegisterDiscoveryPath:
    """The PM4 background path: ensure_products_for_batch(dry_run=True) →
    _register_one → discovery write. A divergent discovered id must be
    refused and reported, never silently overwrite the cache."""

    def test_divergent_discovery_reports_failed_and_preserves_row(self, db):
        from app.services import wfirma_product_auto_register as wfar
        # Local row NOT matched (matched+id short-circuits before search) but
        # carrying a confirmed-divergent id — the legacy state G1 protects.
        wfdb.upsert_product(CODE, wfirma_product_id="X-100", sync_status="pending")
        found = SimpleNamespace(wfirma_id="Y-200", name="wFirma good", unit="szt.")
        with patch.object(wfar.wfirma_client, "get_product_by_code",
                          return_value=found):
            out = wfar._register_one(product_code=CODE, item_type="RING",
                                     description_en="Gold ring", dry_run=True)
        assert out["status"] == "failed"
        assert "cache id guard refused" in out["error"]
        assert out["wfirma_product_id"] == "X-100"          # reports DB truth
        row = wfdb.get_product(CODE)
        assert row["wfirma_product_id"] == "X-100"
        assert row["sync_status"] == "pending"              # no state mutation

    def test_clean_discovery_still_becomes_pending_adoption(self, db):
        from app.services import wfirma_product_auto_register as wfar
        found = SimpleNamespace(wfirma_id="Y-200", name="wFirma good", unit="szt.")
        with patch.object(wfar.wfirma_client, "get_product_by_code",
                          return_value=found):
            out = wfar._register_one(product_code="EJL/G1/CLEAN", item_type="RING",
                                     description_en="Gold ring", dry_run=True)
        assert out["status"] == "pending_adoption"
        assert wfdb.get_product("EJL/G1/CLEAN")["wfirma_product_id"] == "Y-200"


class TestCacheNeverAuthority:
    def test_guard_wired_in_upsert_product(self):
        # NB: read the module FILE — conftest wraps wfdb.upsert_product with a
        # mirror-seeding shim, so getsource(upsert_product) shows the wrapper.
        import inspect
        src = inspect.getsource(wfdb)
        assert "def _mirror_confirms_identity" in src
        assert "not _mirror_confirms_identity(product_code, incoming_id)" in src
        assert "refusals.append(refusal)" in src

    def test_cache_module_never_writes_mirror(self):
        import inspect
        src = inspect.getsource(wfdb)
        assert "UPDATE wfirma_product_mirror" not in src
        assert "INSERT INTO wfirma_product_mirror" not in src

    def test_both_auto_register_writers_pass_refusals(self):
        import inspect
        from app.services import wfirma_product_auto_register as wfar
        src = inspect.getsource(wfar)
        assert src.count("refusals          = _id_refusals") == 2
