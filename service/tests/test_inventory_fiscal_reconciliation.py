"""
WF-2 — Inventory Reconciliation (Dashboard operational vs wFirma fiscal).

Covers the pure comparison algorithm, difference classification, severity rules,
graceful degradation when the fiscal side is unavailable, server-side filters,
the audit-run store round-trip, the API envelope, and read-only authority pins.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import inventory_fiscal_reconciliation_service as svc  # noqa: E402
from app.services import inventory_reconciliation_audit_db as audit_db   # noqa: E402
from app.main import app                                                 # noqa: E402
from app.core.security import require_api_key                            # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────────

def _operational(on_hand=None, blank=0):
    return {"on_hand": dict(on_hand or {}), "states_by_code": {}, "blank_on_hand": blank}


def _fiscal(entries, available=True, unknown=None, warehouses=None, reason=None):
    return {
        "available": available,
        "unavailable_reason": reason,
        "warehouses": warehouses or [{"id": "1", "name": "Main"}],
        "unknown_warehouses": unknown or [],
        "entries": entries,
    }


def _e(product_code, count, wfirma_id="G1", warehouse_id="1", warehouse_name="Main", reserved=0.0):
    return {"warehouse_id": warehouse_id, "warehouse_name": warehouse_name,
            "product_code": product_code, "wfirma_id": wfirma_id,
            "count": count, "reserved": reserved}


def _mirror(*codes):
    return [{"product_code": c} for c in codes]


def _types(report):
    return {d["type"] for d in report["differences"]}


def _by_code(report, code):
    return [d for d in report["differences"] if d["product_code"] == code]


# ── classification ───────────────────────────────────────────────────────────

class TestClassification:

    def test_matching_counts_are_not_differences(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 5}), fiscal=_fiscal([_e("P1", 5)]),
            mirror_rows=_mirror("P1"))
        assert r["summary"]["matching"] == 1
        assert r["summary"]["mismatched"] == 0
        assert r["differences"] == []

    def test_missing_in_wfirma(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 3}), fiscal=_fiscal([]),
            mirror_rows=_mirror("P1"))
        d = _by_code(r, "P1")[0]
        assert d["type"] == svc.T_MISSING_WFIRMA
        assert d["severity"] == svc.SEV_HIGH
        assert d["dashboard_qty"] == 3 and d["wfirma_qty"] == 0

    def test_missing_in_dashboard(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({}), fiscal=_fiscal([_e("P9", 4)]),
            mirror_rows=_mirror("P9"))
        d = _by_code(r, "P9")[0]
        assert d["type"] == svc.T_MISSING_DASHBOARD
        assert d["severity"] == svc.SEV_MEDIUM

    def test_quantity_mismatch_high_when_large_delta(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 10}), fiscal=_fiscal([_e("P1", 3)]),
            mirror_rows=_mirror("P1"))
        d = _by_code(r, "P1")[0]
        assert d["type"] == svc.T_QTY_MISMATCH
        assert d["severity"] == svc.SEV_HIGH
        assert d["difference"] == 7

    def test_quantity_mismatch_medium_when_small_delta(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 10}), fiscal=_fiscal([_e("P1", 8)]),
            mirror_rows=_mirror("P1"))
        assert _by_code(r, "P1")[0]["severity"] == svc.SEV_MEDIUM

    def test_quantity_mismatch_critical_when_wfirma_zero(self):
        # code present in fiscal with count 0 → CRITICAL (stock in Dashboard,
        # wFirma says zero).
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 3}), fiscal=_fiscal([_e("P1", 0)]),
            mirror_rows=_mirror("P1"))
        d = _by_code(r, "P1")[0]
        assert d["type"] == svc.T_QTY_MISMATCH
        assert d["severity"] == svc.SEV_CRITICAL

    def test_product_mapping_missing_takes_precedence(self):
        # op stock but NO mirror mapping → mapping_missing, even if fiscal absent.
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 3}), fiscal=_fiscal([]),
            mirror_rows=_mirror())  # no mirror for P1
        d = _by_code(r, "P1")[0]
        assert d["type"] == svc.T_MAPPING_MISSING
        assert d["severity"] == svc.SEV_HIGH
        assert r["summary"]["unknown_mappings"] == 1

    def test_unknown_product_for_blank_code_good(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({}), fiscal=_fiscal([_e("", 2, wfirma_id="G7")]),
            mirror_rows=_mirror())
        assert svc.T_UNKNOWN_PRODUCT in _types(r)

    def test_duplicate_product_two_goods_same_code(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 1}),
            fiscal=_fiscal([_e("P1", 1, wfirma_id="G1"), _e("P1", 2, wfirma_id="G2")]),
            mirror_rows=_mirror("P1"))
        dups = [d for d in r["differences"] if d["type"] == svc.T_DUPLICATE_PRODUCT]
        assert dups and dups[0]["severity"] == svc.SEV_HIGH

    def test_duplicate_mapping_is_critical(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 1}), fiscal=_fiscal([_e("P1", 1)]),
            mirror_rows=_mirror("P1", "P1"))  # same code twice in mirror
        dups = [d for d in r["differences"] if d["type"] == svc.T_DUPLICATE_MAPPING]
        assert dups and dups[0]["severity"] == svc.SEV_CRITICAL

    def test_warehouse_split_is_low(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 2}),
            fiscal=_fiscal([_e("P1", 1, warehouse_id="1"), _e("P1", 1, warehouse_id="2")]),
            mirror_rows=_mirror("P1"))
        ws = [d for d in r["differences"] if d["type"] == svc.T_WAREHOUSE_MISMATCH]
        assert ws and ws[0]["severity"] == svc.SEV_LOW

    def test_unknown_warehouse_from_reader(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({}), fiscal=_fiscal([], unknown=["999"]),
            mirror_rows=_mirror())
        uw = [d for d in r["differences"] if d["type"] == svc.T_UNKNOWN_WAREHOUSE]
        assert uw and uw[0]["severity"] == svc.SEV_HIGH

    def test_differences_sorted_severity_first(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 10, "P2": 8}),
            fiscal=_fiscal([_e("P1", 0), _e("P2", 8)]),  # P1 critical, plus dup mapping
            mirror_rows=_mirror("P1", "P2", "P2"))
        sevs = [svc._SEV_ORDER[d["severity"]] for d in r["differences"]]
        assert sevs == sorted(sevs)


# ── degradation ──────────────────────────────────────────────────────────────

class TestDegradation:

    def test_fiscal_unavailable_reports_honestly(self):
        r = svc.compute_fiscal_reconciliation(
            operational=_operational({"P1": 3}),
            fiscal=_fiscal([], available=False, reason="wFirma API not configured"),
            mirror_rows=_mirror("P1"))
        assert r["fiscal_source"] == "unavailable"
        assert r["fiscal_unavailable_reason"] == "wFirma API not configured"
        assert r["differences"] == []                 # never invents differences
        assert r["summary"]["total_compared"] == 1


# ── filters ──────────────────────────────────────────────────────────────────

class TestFilters:

    def _report(self):
        return svc.compute_fiscal_reconciliation(
            operational=_operational({"AAA": 10, "BBB": 0}),
            fiscal=_fiscal([_e("AAA", 3), _e("BBB", 4)]),
            mirror_rows=_mirror("AAA", "BBB"))

    def test_filter_by_severity(self):
        rep = svc._apply_filters(self._report(), severity="high")
        assert rep["differences"]
        assert all(d["severity"] == "HIGH" for d in rep["differences"])

    def test_filter_by_product_substring(self):
        rep = svc._apply_filters(self._report(), product="aa")
        assert all("AA" in d["product_code"] for d in rep["differences"])

    def test_filter_by_type(self):
        rep = svc._apply_filters(self._report(), difference_type=svc.T_MISSING_DASHBOARD)
        assert all(d["type"] == svc.T_MISSING_DASHBOARD for d in rep["differences"])

    def test_search_free_text(self):
        rep = svc._apply_filters(self._report(), search="wFirma")
        assert isinstance(rep["differences"], list)


# ── audit store ──────────────────────────────────────────────────────────────

class TestAuditStore:

    def test_record_and_get_last_run(self, tmp_path):
        db = tmp_path / "inventory_reconciliation.db"
        rid = audit_db.record_run(db, {
            "warehouse_filter": "1", "fiscal_source": "wfirma",
            "duration_ms": 12, "objects_checked": 5, "matching": 3,
            "mismatched": 2, "by_severity": {"HIGH": 1, "LOW": 1},
        })
        assert rid
        last = audit_db.get_last_run(db)
        assert last["fiscal_source"] == "wfirma"
        assert last["objects_checked"] == 5
        assert last["by_severity"]["HIGH"] == 1

    def test_missing_audit_db_returns_none(self, tmp_path):
        assert audit_db.get_last_run(tmp_path / "nope.db") is None
        assert audit_db.list_runs(tmp_path / "nope.db") == []


# ── API envelope ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _bypass_auth():
    # app is the shared app.main singleton — a module-level override here
    # fires at collection and disables auth for every test collected after
    # it, silently breaking 401 assertions across the suite.
    app.dependency_overrides[require_api_key] = lambda: None
    yield
    app.dependency_overrides.pop(require_api_key, None)


client = TestClient(app)


class TestApi:

    def test_get_report_envelope_when_fiscal_unavailable(self):
        # Dev/verify env: wFirma not configured → honest unavailable report.
        with patch.object(svc.wfirma_fiscal_inventory, "read_fiscal_inventory",
                           return_value=_fiscal([], available=False,
                                                 reason="wFirma API not configured")), \
             patch.object(svc, "_read_operational",
                          return_value=_operational({"P1": 2})), \
             patch.object(svc.reservation_db, "list_mirror_products", return_value=_mirror("P1")):
            r = client.get("/api/v1/inventory/fiscal-reconciliation")
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("generated_at", "fiscal_source", "summary", "differences", "warehouses"):
            assert k in data
        assert data["fiscal_source"] == "unavailable"

    def test_run_now_records_and_returns_report(self):
        with patch.object(svc.wfirma_fiscal_inventory, "read_fiscal_inventory",
                           return_value=_fiscal([_e("P1", 1)])), \
             patch.object(svc, "_read_operational",
                          return_value=_operational({"P1": 1})), \
             patch.object(svc.reservation_db, "list_mirror_products", return_value=_mirror("P1")), \
             patch.object(svc.audit_db, "record_run", return_value="run-1") as rec:
            r = client.post("/api/v1/inventory/fiscal-reconciliation/run")
        assert r.status_code == 200, r.text
        assert r.json()["fiscal_source"] == "wfirma"
        rec.assert_called_once()

    def test_status_endpoint_shape(self):
        r = client.get("/api/v1/inventory/fiscal-reconciliation/status")
        assert r.status_code == 200
        data = r.json()
        for k in ("healthy", "running", "last_run", "fiscal_configured"):
            assert k in data

    def test_report_endpoint_is_read_only(self):
        for method in ("put", "patch", "delete"):
            rr = getattr(client, method)("/api/v1/inventory/fiscal-reconciliation")
            assert rr.status_code in (404, 405)


# ── authority pins (read-only) ───────────────────────────────────────────────

class TestAuthorityPins:

    def test_service_never_writes_business_tables(self):
        src = inspect.getsource(svc)
        for forbidden in (
            "INSERT INTO inventory_state", "UPDATE inventory_state",
            "DELETE FROM inventory_state",
            "INSERT INTO product_master", "UPDATE product_master",
            "INSERT INTO wfirma_product_mirror", "UPDATE wfirma_product_mirror",
        ):
            assert forbidden not in src, f"reconciliation service writes a business table: {forbidden}"

    def test_operational_read_uses_query_only(self):
        assert "PRAGMA query_only=ON" in inspect.getsource(svc)

    def test_fiscal_reader_has_no_wfirma_write_calls(self):
        from app.services import wfirma_fiscal_inventory as reader
        src = inspect.getsource(reader)
        for forbidden in (".create_product(", ".edit_product(", ".create_warehouse_pz(",
                          ".create_reservation(", ".create_proforma_draft(", ".create_customer(",
                          "/add", "/edit", "/delete"):
            assert forbidden not in src, f"fiscal reader contains a write call: {forbidden}"
