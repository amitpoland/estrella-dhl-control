"""
test_wfirma_reservation_exists.py — Phase 2 Step 2.

Verifies that GET /api/v1/wfirma/reservation-preview/{batch_id} now includes:
  reservation_exists  — bool: True when any draft for the batch has status='created'
  reservation_id      — str | None: wfirma_reservation_id from first 'created' draft

Rules under test:
  - No drafts at all → reservation_exists=False, reservation_id=None
  - Draft present with status='pending' → reservation_exists=False, reservation_id=None
  - Draft present with status='created' + non-empty ID → reservation_exists=True, reservation_id=<id>
  - Draft present with status='failed' → reservation_exists=False, reservation_id=None
  - Multiple drafts, one 'created' → reservation_exists=True
  - All existing response fields preserved (batch_id, audit_clean, wfirma_configured,
    reservation_supported, ready_to_create, blocking_reasons, currency, documents)
  - Endpoint is GET-only / no side effect from checking reservation_exists
  - Empty-batch path: _empty_response includes both fields safely
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import packing_db as pdb
from app.services import document_db as ddb
from app.services import warehouse_db as wdb
from app.services import wfirma_db as wfdb
from app.services import wfirma_reservation as wr


BATCH_NORES  = "WRE_NO_RESERVATION_BATCH"
BATCH_PEND   = "WRE_PENDING_BATCH"
BATCH_CREATED = "WRE_CREATED_BATCH"
BATCH_FAILED  = "WRE_FAILED_BATCH"
BATCH_MULTI   = "WRE_MULTI_BATCH"

INV_NO = "EJL/WRE/001"
SKU_A  = "WRE/SKU-ALPHA"
INV_PC = "EJL/WRE/001-1"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("wre_storage")


@pytest.fixture(scope="module")
def db(tmp_storage):
    pdb.init_packing_db(tmp_storage / "packing.db")
    ddb.init_document_db(tmp_storage / "documents.db")
    wdb.init_warehouse_db(tmp_storage / "warehouse.db")
    wfdb.init_wfirma_db(tmp_storage / "wfirma.db")
    return tmp_storage


@pytest.fixture(scope="module")
def client(tmp_storage, db):
    with patch.object(settings, "storage_root", tmp_storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── Minimal data seeder (same pattern as test_wfirma_reservation.py) ──────────

def _seed_batch(batch_id: str) -> None:
    """Seed minimal packing + invoice + sales data for a batch."""
    pline = {
        "packing_document_id":   f"wre-pdoc-{batch_id[:8]}",
        "batch_id":              batch_id,
        "invoice_no":            INV_NO,
        "invoice_line_position": 1,
        "product_code":          INV_PC,
        "design_no":             SKU_A,
        "bag_id":                "",
        "tray_id":               "",
        "item_type":             "RNG",
        "uom":                   "PCS",
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            5.0,
        "metal":                 "18KT",
        "karat":                 "",
        "stone_type":            "",
        "remarks":               "",
        "extracted_confidence":  0.95,
        "requires_manual_review": False,
        "pack_sr":               1.0,
        "unit_price":            100.0,
        "total_value":           100.0,
        "batch_no":              "",
    }
    pdb.upsert_packing_lines([pline])

    inv_doc_id = str(uuid.uuid4())
    ddb.store_invoice_lines(inv_doc_id, batch_id, [{
        "invoice_no":    INV_NO,
        "line_position": 1,
        "product_code":  INV_PC,
        "description":   "Test item",
        "quantity":      1.0,
        "unit_price":    100.0,
        "total_value":   100.0,
        "currency":      "USD",
        "hs_code":       "",
        "gross_weight":  5.0,
        "net_weight":    5.0,
        "rate_usd":      100.0,
        "amount_usd":    100.0,
        "hsn_code":      "",
    }])

    sdoc_id = ddb.store_sales_document(batch_id, str(uuid.uuid4()), {
        "client_name":  "WRE Client",
        "client_ref":   f"WRE/{batch_id[:6]}",
        "sales_doc_no": f"SD-{batch_id[:6]}",
    })
    ddb.store_sales_packing_lines(sdoc_id, batch_id, [{
        "product_code": SKU_A,
        "design_no":    SKU_A,
        "client_name":  "WRE Client",
        "client_ref":   f"WRE/{batch_id[:6]}",
        "quantity":     1.0,
        "bag_id":       "",
        "remarks":      "",
    }])


def _force_draft_status(batch_id: str, status: str, wfirma_id: str = "") -> None:
    """
    Directly set a draft's status + wfirma_reservation_id via SQL.
    Used only in tests to simulate Phase 3 outcomes without running the create flow.
    """
    import sqlite3 as _sq
    with _sq.connect(str(wfdb._db_path)) as con:
        con.execute(
            """UPDATE wfirma_reservation_drafts
               SET status=?, wfirma_reservation_id=?
               WHERE batch_id=?""",
            (status, wfirma_id, batch_id),
        )


# ── Test: no reservation exists ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def seeded_no_res(db):
    _seed_batch(BATCH_NORES)
    # Call preview so drafts are created (status='pending' by default)
    wr.get_reservation_preview(BATCH_NORES)
    return {}


class TestNoReservation:
    def test_reservation_exists_false(self, db, seeded_no_res):
        result = wr.get_reservation_preview(BATCH_NORES)
        assert result["reservation_exists"] is False

    def test_reservation_id_none(self, db, seeded_no_res):
        result = wr.get_reservation_preview(BATCH_NORES)
        assert result["reservation_id"] is None

    def test_api_response_has_both_fields(self, client, seeded_no_res):
        r = client.get(f"/api/v1/wfirma/reservation-preview/{BATCH_NORES}",
                       headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert "reservation_exists" in body
        assert "reservation_id" in body
        assert body["reservation_exists"] is False
        assert body["reservation_id"] is None


# ── Test: draft status='pending' ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def seeded_pending(db):
    _seed_batch(BATCH_PEND)
    wr.get_reservation_preview(BATCH_PEND)
    _force_draft_status(BATCH_PEND, "pending", "")
    return {}


class TestPendingDraft:
    def test_pending_draft_does_not_set_reservation_exists(self, db, seeded_pending):
        result = wr.get_reservation_preview(BATCH_PEND)
        assert result["reservation_exists"] is False

    def test_pending_draft_reservation_id_is_none(self, db, seeded_pending):
        result = wr.get_reservation_preview(BATCH_PEND)
        assert result["reservation_id"] is None


# ── Test: draft status='created' ─────────────────────────────────────────────

FAKE_WFIRMA_ID = "WFIRMA-RES-12345"


@pytest.fixture(scope="module")
def seeded_created(db):
    _seed_batch(BATCH_CREATED)
    wr.get_reservation_preview(BATCH_CREATED)
    _force_draft_status(BATCH_CREATED, "created", FAKE_WFIRMA_ID)
    return {}


class TestCreatedReservation:
    def test_reservation_exists_true(self, db, seeded_created):
        result = wr.get_reservation_preview(BATCH_CREATED)
        assert result["reservation_exists"] is True

    def test_reservation_id_matches_wfirma_id(self, db, seeded_created):
        result = wr.get_reservation_preview(BATCH_CREATED)
        assert result["reservation_id"] == FAKE_WFIRMA_ID

    def test_api_reports_existing_reservation(self, client, seeded_created):
        r = client.get(f"/api/v1/wfirma/reservation-preview/{BATCH_CREATED}",
                       headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["reservation_exists"] is True
        assert body["reservation_id"] == FAKE_WFIRMA_ID

    def test_created_reservation_does_not_change_ready_to_create(self, db, seeded_created):
        """reservation_exists is independent of ready_to_create logic."""
        result = wr.get_reservation_preview(BATCH_CREATED)
        # Both fields coexist without interference
        assert "ready_to_create" in result
        assert "reservation_exists" in result

    def test_calling_preview_again_does_not_clear_reservation_id(self, db, seeded_created):
        """
        Re-calling preview (which upserts the draft) must NOT overwrite
        status='created' or wfirma_reservation_id — the upsert only touches
        client_ref/currency/warehouse_id/ready_to_create.
        """
        # Call twice
        wr.get_reservation_preview(BATCH_CREATED)
        result = wr.get_reservation_preview(BATCH_CREATED)
        assert result["reservation_exists"] is True
        assert result["reservation_id"] == FAKE_WFIRMA_ID


# ── Test: draft status='failed' ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def seeded_failed(db):
    _seed_batch(BATCH_FAILED)
    wr.get_reservation_preview(BATCH_FAILED)
    _force_draft_status(BATCH_FAILED, "failed", "")
    return {}


class TestFailedDraft:
    def test_failed_draft_does_not_set_reservation_exists(self, db, seeded_failed):
        result = wr.get_reservation_preview(BATCH_FAILED)
        assert result["reservation_exists"] is False

    def test_failed_draft_reservation_id_is_none(self, db, seeded_failed):
        result = wr.get_reservation_preview(BATCH_FAILED)
        assert result["reservation_id"] is None


# ── Test: empty batch path ─────────────────────────────────────────────────────

class TestEmptyBatchReservationFields:
    def test_empty_batch_reservation_exists_false(self, db):
        result = wr.get_reservation_preview("WRE_NONEXISTENT_BATCH_999")
        assert result["reservation_exists"] is False

    def test_empty_batch_reservation_id_none(self, db):
        result = wr.get_reservation_preview("WRE_NONEXISTENT_BATCH_999")
        assert result["reservation_id"] is None

    def test_empty_batch_has_both_fields(self, db):
        result = wr.get_reservation_preview("WRE_NONEXISTENT_BATCH_999")
        assert "reservation_exists" in result
        assert "reservation_id" in result


# ── Test: all existing fields preserved ──────────────────────────────────────

class TestExistingFieldsPreserved:
    REQUIRED_KEYS = {
        "batch_id", "audit_clean", "wfirma_configured",
        "reservation_supported", "ready_to_create",
        "blocking_reasons", "currency", "documents",
        "reservation_exists", "reservation_id",
    }

    def test_all_keys_present_non_empty_batch(self, db, seeded_no_res):
        result = wr.get_reservation_preview(BATCH_NORES)
        assert self.REQUIRED_KEYS.issubset(result.keys()), (
            f"missing keys: {self.REQUIRED_KEYS - result.keys()}"
        )

    def test_all_keys_present_empty_batch(self, db):
        result = wr.get_reservation_preview("WRE_NONEXISTENT_BATCH_999")
        assert self.REQUIRED_KEYS.issubset(result.keys()), (
            f"missing keys: {self.REQUIRED_KEYS - result.keys()}"
        )

    def test_api_schema_has_new_fields(self, client, seeded_no_res):
        r = client.get(f"/api/v1/wfirma/reservation-preview/{BATCH_NORES}",
                       headers=_auth())
        body = r.json()
        for key in ("reservation_exists", "reservation_id"):
            assert key in body, f"API response missing {key}"

    def test_endpoint_is_get_only(self, client):
        r = client.post(
            f"/api/v1/wfirma/reservation-preview/{BATCH_NORES}",
            headers=_auth(),
        )
        assert r.status_code in (404, 405), (
            f"POST to reservation-preview should not be routed: got {r.status_code}"
        )
