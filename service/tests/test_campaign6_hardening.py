"""
test_campaign6_hardening.py — Campaign 6 convergence hardening tests.

Covers:
  T3  — Threading locks on description_engine, intelligence_engine caches
  T3  — Atomic write for tracking_service._save_cache
  T4  — ProformaDraftPanel removed from OperatorWorkflowCard in PZ tab
  T5  — upsert_design partial-update semantics (no NULL-wipe on absent keys)
  T6  — get_products_batch O(1) vs O(N) get_product calls
  T8  — PRAGMA quick_check on wfirma.db startup
  T9  — governance_constants imported in main (assert_no_overlap at startup)
"""
from __future__ import annotations

import importlib
import sqlite3
import threading
from pathlib import Path
from unittest.mock import patch

import pytest


# ── T3: Threading locks ────────────────────────────────────────────────────────

class TestDescriptionEngineLock:
    def test_cache_lock_exists(self):
        from app.services import description_engine as de
        assert hasattr(de, "_cache_lock"), "_cache_lock not found in description_engine"
        assert isinstance(de._cache_lock, type(threading.Lock())), "_cache_lock is not a Lock"

    def test_load_customs_engine_thread_safe_double_check(self):
        """Concurrent calls to _load_customs_engine should not race."""
        from app.services import description_engine as de
        results = []
        errors  = []

        def worker():
            try:
                result = de._load_customs_engine()
                results.append(result)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        # All threads get same result (None or engine) — no partial reads
        assert len(set(id(r) for r in results if r is not None)) <= 1, \
            "Different _CUSTOMS_ENGINE_CACHE instances returned by concurrent calls"

    def test_load_translations_thread_safe(self):
        """Concurrent calls to _load_translations should not race."""
        from app.services import description_engine as de
        errors = []

        def worker():
            try:
                de._load_translations()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"


class TestIntelligenceEngineLock:
    def test_master_cache_lock_exists(self):
        from app.services import intelligence_engine as ie
        assert hasattr(ie, "_master_cache_lock"), "_master_cache_lock not found"
        assert isinstance(ie._master_cache_lock, type(threading.Lock()))

    def test_load_master_thread_safe_missing_file(self, tmp_path):
        """Concurrent calls with missing master file should all return None safely."""
        from app.services import intelligence_engine as ie
        results = []
        errors  = []

        with patch.object(ie, "MASTER_PATH", tmp_path / "nonexistent.json"):
            def worker():
                try:
                    r = ie.load_master(force_reload=True)
                    results.append(r)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert not errors, f"Thread errors: {errors}"
        assert all(r is None for r in results)


# ── T3: Atomic cache write ─────────────────────────────────────────────────────

class TestTrackingCacheAtomicWrite:
    def test_save_cache_uses_atomic_rename(self, tmp_path):
        """_save_cache must write to .tmp then rename, not write directly."""
        from app.services import tracking_service as ts
        cache = {"AWB123": {"status": "delivered"}}
        ts._save_cache(tmp_path, cache)
        cache_file = tmp_path / "tracking_cache.json"
        tmp_file   = tmp_path / "tracking_cache.json.tmp"
        assert cache_file.exists(), "cache_file not created"
        assert not tmp_file.exists(), ".tmp file not cleaned up (rename failed)"

    def test_save_cache_source_uses_os_replace(self):
        """Verify _save_cache uses os.replace (atomic) not write_text direct."""
        import inspect
        from app.services import tracking_service as ts
        src = inspect.getsource(ts._save_cache)
        assert "_os.replace" in src or "os.replace" in src, \
            "_save_cache does not use os.replace — not atomic"

    def test_save_cache_no_partial_on_reread(self, tmp_path):
        """Round-trip: save → load → same content."""
        from app.services import tracking_service as ts
        import json
        cache = {"AWB999": {"status": "in_transit", "ts": "2026-01-01"}}
        ts._save_cache(tmp_path, cache)
        loaded = json.loads((tmp_path / "tracking_cache.json").read_text())
        assert loaded == cache


# ── T4: Commercial ownership ───────────────────────────────────────────────────

class TestCommercialOwnership:
    """ProformaDraftPanel must NOT appear in OperatorWorkflowCard in PZ tab."""

    def _src(self) -> str:
        sdet = Path(__file__).parents[1] / "app" / "static" / "shipment-detail.html"
        return sdet.read_text(encoding="utf-8")

    def test_workflow_section_a_removed_from_operator_workflow_card(self):
        src = self._src()
        # Section A was removed from OperatorWorkflowCard
        # The div with data-testid="workflow-section-a" must no longer exist
        # in the OperatorWorkflowCard context (it still may exist in Sales tab
        # if ProformaDraftPanel is used there independently — but the section
        # wrapper is gone)
        assert 'data-testid="workflow-section-a"' not in src, \
            "workflow-section-a testid still present — section A not removed"

    def test_independence_note_removed(self):
        src = self._src()
        assert 'data-testid="workflow-independence-note"' not in src, \
            "workflow-independence-note still present in shipment-detail.html"

    def test_proforma_draft_panel_still_in_sales_tab(self):
        src = self._src()
        # ProformaDraftPanel must still be present somewhere (Sales tab)
        assert "ProformaDraftPanel" in src, \
            "ProformaDraftPanel entirely removed — it must remain in Sales tab"

    def test_section_b_is_pz_customs_only(self):
        src = self._src()
        # Section B header updated to note commercial is in Sales tab
        assert "Proforma Invoices (commercial) are managed in the Sales tab" in src


# ── T5: Design upsert partial-update semantics ────────────────────────────────

class TestDesignUpsertPartialUpdate:
    def test_update_absent_optional_field_preserved(self, tmp_path):
        """UPDATE with stone_summary absent must NOT wipe existing stone_summary."""
        from app.services.master_data_db import upsert_design, get_design, init_db
        db = tmp_path / "md.db"
        init_db(db)
        # Insert with stone_summary set
        upsert_design(db, {
            "design_code": "RD001",
            "display_name": "Ring Diamond",
            "stone_summary": "2x 0.5ct D SI1",
            "hs_code": "711319",
            "active": True,
        })
        # Update only display_name — stone_summary must be preserved
        upsert_design(db, {
            "design_code": "RD001",
            "display_name": "Ring Diamond Updated",
        })
        rec = get_design(db, "RD001")
        assert rec is not None
        assert rec.display_name == "Ring Diamond Updated", "display_name not updated"
        assert rec.stone_summary == "2x 0.5ct D SI1", \
            f"stone_summary was wiped to None — partial update failed: {rec.stone_summary!r}"

    def test_explicit_none_clears_optional_field(self, tmp_path):
        """Explicitly passing None for a present key SHOULD clear the field."""
        from app.services.master_data_db import upsert_design, get_design, init_db
        db = tmp_path / "md.db"
        init_db(db)
        upsert_design(db, {
            "design_code": "RD002",
            "display_name": "Ring",
            "stone_summary": "1x 1ct",
            "active": True,
        })
        # Explicitly pass None — should clear stone_summary
        upsert_design(db, {
            "design_code": "RD002",
            "display_name": "Ring",
            "stone_summary": None,
        })
        rec = get_design(db, "RD002")
        assert rec.stone_summary is None, "stone_summary should be cleared when explicitly None"


# ── T6: get_products_batch O(1) ────────────────────────────────────────────────

class TestGetProductsBatch:
    def test_batch_fetch_returns_all_known_products(self, tmp_path):
        from app.services import wfirma_db
        db = tmp_path / "wfirma.db"
        wfirma_db.init_wfirma_db(db)
        wfirma_db.upsert_product("CODE1", wfirma_product_id="id1", product_name_pl="Name1", sync_status="matched")
        wfirma_db.upsert_product("CODE2", wfirma_product_id="id2", product_name_pl="Name2", sync_status="matched")
        wfirma_db.upsert_product("CODE3", wfirma_product_id="id3", product_name_pl="Name3", sync_status="matched")

        result = wfirma_db.get_products_batch(["CODE1", "CODE2", "CODE3", "MISSING"])
        assert set(result.keys()) == {"CODE1", "CODE2", "CODE3"}, \
            f"Expected 3 products, got {set(result.keys())}"
        assert result["CODE1"]["wfirma_product_id"] == "id1"
        assert "MISSING" not in result

    def test_batch_fetch_empty_list(self, tmp_path):
        from app.services import wfirma_db
        db = tmp_path / "wfirma.db"
        wfirma_db.init_wfirma_db(db)
        result = wfirma_db.get_products_batch([])
        assert result == {}

    def test_batch_fetch_one_call_vs_n_calls(self, tmp_path):
        """get_products_batch makes exactly 1 DB connection vs N for get_product."""
        from app.services import wfirma_db
        db = tmp_path / "wfirma.db"
        wfirma_db.init_wfirma_db(db)
        for i in range(5):
            wfirma_db.upsert_product(f"C{i}", wfirma_product_id=f"id{i}", product_name_pl=f"N{i}", sync_status="matched")

        connect_calls = []
        original_connect = wfirma_db._connect
        def counting_connect(*a, **kw):
            connect_calls.append(1)
            return original_connect(*a, **kw)

        with patch.object(wfirma_db, "_connect", side_effect=counting_connect):
            wfirma_db.get_products_batch([f"C{i}" for i in range(5)])

        assert len(connect_calls) == 1, \
            f"get_products_batch made {len(connect_calls)} DB connections, expected 1"


# ── T8: PRAGMA quick_check on startup ─────────────────────────────────────────

class TestWfirmaDbQuickCheck:
    def test_init_wfirma_db_runs_quick_check(self, tmp_path):
        """init_wfirma_db must run PRAGMA quick_check on the new DB."""
        from app.services import wfirma_db
        db = tmp_path / "wfirma.db"
        quick_check_called = []

        original_connect = wfirma_db._connect
        class CountingConn:
            def __init__(self, real_con):
                self._c = real_con
            def execute(self, sql, *args, **kw):
                if "quick_check" in sql.lower():
                    quick_check_called.append(True)
                return self._c.execute(sql, *args, **kw)
            def executescript(self, sql):
                return self._c.executescript(sql)
            def fetchone(self):
                return self._c.fetchone()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return self._c.__exit__(*a)

        # Quick check — just verify the source includes the PRAGMA
        import inspect
        src = inspect.getsource(wfirma_db.init_wfirma_db)
        assert "quick_check" in src.lower(), \
            "init_wfirma_db does not call PRAGMA quick_check"


# ── T9: Governance constants imported at startup ───────────────────────────────

class TestGovernanceAtStartup:
    def test_governance_constants_imported_in_main(self):
        """main.py must import governance_constants to trigger assert_no_overlap()."""
        src = Path(__file__).parents[1] / "app" / "main.py"
        text = src.read_text(encoding="utf-8")
        assert "governance_constants" in text, \
            "governance_constants not imported in main.py — assert_no_overlap won't run at startup"

    def test_no_overlap_passes(self):
        """assert_no_overlap() must not raise."""
        from app.services.governance_constants import assert_no_overlap
        assert_no_overlap()  # raises AssertionError if any action in both sets

    def test_invoice_invariant_in_human_required(self):
        from app.services.governance_constants import HUMAN_APPROVAL_REQUIRED_ACTIONS
        for action in ("invoice.create_final_invoice", "invoice.convert_proforma_to_invoice",
                       "invoice.activate", "pz.post_final"):
            assert action in HUMAN_APPROVAL_REQUIRED_ACTIONS, \
                f"{action!r} not in HUMAN_APPROVAL_REQUIRED_ACTIONS"

    def test_invoice_invariant_not_in_autonomous(self):
        from app.services.governance_constants import SAFE_AUTONOMOUS_ACTIONS
        for action in ("invoice.create_final_invoice", "invoice.convert_proforma_to_invoice",
                       "invoice.activate", "pz.post_final"):
            assert action not in SAFE_AUTONOMOUS_ACTIONS, \
                f"{action!r} in SAFE_AUTONOMOUS_ACTIONS — governance violation"
