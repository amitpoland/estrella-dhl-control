"""PM4 (MASTER-EXEC-1 Phase 4) — Product Master auto-sync on purchase-packing ingest.

The Product Master sync (product_master_sync.run_product_master_sync), its Run-Now
POST, status endpoint, and UI panel already exist. The ONLY missing Business-Feature-
Completeness layer is automation. PM4 adds an event-driven trigger: after purchase-
packing rows are STORED for a batch, schedule run_product_master_sync as a
fire-and-forget FastAPI BackgroundTask.

These tests pin:
  * the helper schedules ONLY the canonical sync boundary, and only when rows > 0;
  * it is failure-isolated (never raises into the intake response);
  * shipment_intake + add_packing_list are wired, gated on stored (status=="extracted") rows;
  * add_document_to_batch is NOT wired (its packing branch extracts but never persists
    packing_lines — the 'rows stored' precondition is not met, so scheduling there would
    violate the safety gate);
  * routes_intake introduces no direct product_master write, no product_code mint, and
    no wFirma product create — Master writes route through run_product_master_sync only.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

from fastapi import BackgroundTasks

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_intake as ri            # noqa: E402
from app.services import product_master_sync as pms  # noqa: E402


class TestSchedulerHelper:
    """Behavioural: the helper drives a REAL BackgroundTasks object."""

    def test_schedules_sync_when_rows_stored(self):
        bg = BackgroundTasks()
        ok = ri.schedule_product_master_sync(bg, "SHIPMENT_X", 3)
        assert ok is True
        assert len(bg.tasks) == 1
        task = bg.tasks[0]
        assert task.func is pms.run_product_master_sync   # the ONE sync boundary
        assert task.args == ("SHIPMENT_X",)               # batch_id passed positionally
        assert task.kwargs == {}                          # dry_run default False → live sync

    def test_no_task_when_zero_rows(self):
        bg = BackgroundTasks()
        assert ri.schedule_product_master_sync(bg, "SHIPMENT_X", 0) is False
        assert len(bg.tasks) == 0

    def test_no_task_when_negative_rows(self):
        bg = BackgroundTasks()
        assert ri.schedule_product_master_sync(bg, "SHIPMENT_X", -5) is False
        assert len(bg.tasks) == 0

    def test_no_task_when_blank_batch(self):
        bg = BackgroundTasks()
        assert ri.schedule_product_master_sync(bg, "", 3) is False
        assert len(bg.tasks) == 0

    def test_scheduling_failure_is_isolated(self):
        # A broken background object must NOT raise out of the helper — the intake
        # response must be unaffected by a scheduling failure.
        class _Boom:
            def add_task(self, *a, **k):
                raise RuntimeError("bg down")
        assert ri.schedule_product_master_sync(_Boom(), "SHIPMENT_X", 3) is False


class TestWiring:
    def test_shipment_intake_schedules_on_stored_purchase_packing(self):
        src = inspect.getsource(ri.shipment_intake)
        assert "schedule_product_master_sync(background, batch_id" in src
        # gated on rows that were actually STORED (status == 'extracted')
        assert 'pr.get("status") == "extracted"' in src
        # shipment_intake already receives the BackgroundTasks dependency
        assert "background" in inspect.signature(ri.shipment_intake).parameters

    def test_add_packing_list_has_background_param_and_schedules(self):
        assert "background" in inspect.signature(ri.add_packing_list).parameters
        src = inspect.getsource(ri.add_packing_list)
        assert "schedule_product_master_sync(" in src
        assert 'result_summary.get("status") == "extracted"' in src

    def test_add_document_to_batch_not_wired_because_no_rows_persisted(self):
        # add_document_to_batch's packing branch calls process_packing_upload (which
        # does NOT persist) and never calls upsert_packing_lines — so no purchase-
        # packing rows are stored on that path. Per the 'rows stored' safety gate,
        # PM4 must NOT schedule there.
        src = inspect.getsource(ri.add_document_to_batch)
        assert "schedule_product_master_sync(" not in src
        assert "upsert_packing_lines(" not in src


class TestAuthoritySafety:
    def test_helper_uses_only_the_sync_boundary(self):
        src = inspect.getsource(ri.schedule_product_master_sync)
        assert "run_product_master_sync" in src
        for forbidden in ("upsert_product_master", "store_invoice_lines",
                          "create_product", "goods/add",
                          "upsert_product_master_from_packing"):
            assert forbidden not in src

    def test_routes_intake_does_not_write_product_master_directly(self):
        src = inspect.getsource(ri)
        # PM4 routes ALL Master writes through run_product_master_sync (→ the CPA
        # boundary). routes_intake must not call the write boundary itself, nor
        # raw-SQL the table.
        assert "upsert_product_master_from_packing" not in src
        assert "INSERT INTO product_master" not in src
        assert "upsert_product_master(" not in src

    def test_routes_intake_adds_no_wfirma_product_create(self):
        src = inspect.getsource(ri)
        for forbidden in (".create_product(", "wfirma_create_product", "goods/add"):
            assert forbidden not in src

    def test_run_product_master_sync_is_the_only_sync_boundary_referenced(self):
        src = inspect.getsource(ri)
        assert "run_product_master_sync" in src            # referenced via the helper
        assert "def run_product_master_sync" not in src    # never re-implemented here
