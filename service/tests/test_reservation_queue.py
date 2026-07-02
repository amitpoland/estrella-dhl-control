"""
test_reservation_queue.py — Comprehensive tests for the reservation queue.

Covers (20 tests):
 1.  init_reservation_db creates all 5 tables
 2.  upsert_product_master + get_product_master roundtrip
 3.  upsert_design_mapping + get_product_code_by_design_no roundtrip
 4.  import_purchase_packing creates master + mapping rows
 5.  import_sales_packing with known mapping → status=pending
 6.  import_sales_packing with unknown design_no → status=blocked
 7.  sync_wfirma_products_by_codes with mock client returning a product
 8.  sync_wfirma_products_by_codes with mock client returning None
 9.  refresh_queue_readiness promotes pending → ready when both mappings present
10.  refresh_queue_readiness keeps pending when customer missing
11.  process_ready_reservations dry_run → returns would_create, no API call
12.  process_ready_reservations live mode with mock success → status=created
13.  process_ready_reservations live mode with mock failure → status=failed
14.  POST /api/v1/products/import-purchase-packing returns 200 with created count
15.  POST /api/v1/reservations/import-sales-packing returns 200 with row statuses
16.  GET /api/v1/reservations/queue returns correct rows
17.  POST /api/v1/wfirma/products/sync-by-codes returns matched/missing
18.  POST /api/v1/reservations/process-pending dry_run returns would_create
19.  POST /api/v1/reservations/{queue_id}/reset resets failed → pending
20.  Duplicate queue_key is idempotent (upsert, not error)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import reservation_db as rdb
from app.services import reservation_worker as rworker


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_path(tmp_path):
    """Fresh isolated DB for each test."""
    p = tmp_path / "reservation_queue.db"
    rdb.init_reservation_db(p)
    return p


@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("reservation_storage")


@pytest.fixture(scope="module")
def client(tmp_storage):
    # Initialise all DBs that the app lifespan touches
    from app.services.packing_db import init_packing_db
    from app.services.document_db import init_document_db
    from app.services.warehouse_db import init_warehouse_db
    from app.services.wfirma_db import init_wfirma_db
    from app.services.tracking_db import init_tracking_db
    init_packing_db(tmp_storage / "packing.db")
    init_document_db(tmp_storage / "documents.db")
    init_warehouse_db(tmp_storage / "warehouse.db")
    init_wfirma_db(tmp_storage / "wfirma.db")
    init_tracking_db(tmp_storage / "tracking_events.db")

    with patch.object(settings, "storage_root", tmp_storage):
        # Point reservation routes at the same tmp_storage
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── Helper: mock wFirma client ────────────────────────────────────────────────

def _mock_client_with_product(product_code: str = "EJL/TEST/001"):
    """Return a mock client whose get_product_by_code returns a WFirmaProduct."""
    from app.services.wfirma_client import WFirmaProduct
    mock = MagicMock()
    mock.get_product_by_code.return_value = WFirmaProduct(
        wfirma_id="WF-P-001",
        name="Test Ring",
        code=product_code,
        unit="szt.",
        count=100.0,
        reserved=0.0,
    )
    return mock


def _mock_client_no_product():
    mock = MagicMock()
    mock.get_product_by_code.return_value = None
    return mock


def _mock_client_reservation_ok():
    from app.services.wfirma_client import ReservationResult
    mock = MagicMock()
    mock.get_product_by_code.return_value = None
    mock.create_reservation.return_value = ReservationResult(
        ok=True,
        wfirma_reservation_id="WF-R-001",
    )
    return mock


def _mock_client_reservation_fail():
    from app.services.wfirma_client import ReservationResult
    mock = MagicMock()
    mock.create_reservation.return_value = ReservationResult(
        ok=False,
        error="wFirma API error: insufficient stock",
    )
    return mock


# ── Test 1: init creates all 5 tables ────────────────────────────────────────

def test_init_creates_all_tables(tmp_path):
    import sqlite3
    db = tmp_path / "init_test.db"
    rdb.init_reservation_db(db)
    with sqlite3.connect(str(db)) as con:
        tables = {
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    expected = {
        "product_master",
        "design_product_mapping",
        "wfirma_product_mapping",
        "wfirma_customer_mapping",
        "reservation_queue",
    }
    assert expected.issubset(tables)


# ── Test 2: upsert_product_master + get_product_master roundtrip ──────────────

def test_upsert_and_get_product_master(db_path):
    row_id = rdb.upsert_product_master(
        db_path,
        product_code="EJL/26-27/001",
        design_no="D-001",
        description="Gold Ring",
        metal="yellow_gold",
        category="rings",
        source_invoice_no="INV-2026-001",
        source_batch_id="BATCH-A",
    )
    assert isinstance(row_id, int) and row_id > 0

    rec = rdb.get_product_master(db_path, "EJL/26-27/001")
    assert rec is not None
    assert rec["design_no"] == "D-001"
    assert rec["metal"] == "yellow_gold"
    assert rec["source_invoice_no"] == "INV-2026-001"


# ── Test 3: upsert_design_mapping + get_product_code_by_design_no ─────────────

def test_upsert_and_get_design_mapping(db_path):
    # Need product_master first (FK)
    rdb.upsert_product_master(db_path, "EJL/26-27/002", "D-002")
    row_id = rdb.upsert_design_mapping(
        db_path, design_no="D-002", product_code="EJL/26-27/002",
        confidence="locked", source="purchase_packing",
    )
    assert isinstance(row_id, int) and row_id > 0

    mapping = rdb.get_product_code_by_design_no(db_path, "D-002")
    assert mapping is not None
    assert mapping["product_code"] == "EJL/26-27/002"
    assert mapping["confidence"] == "locked"


# ── Test 4: import_purchase_packing creates master + mapping rows ──────────────

def test_import_purchase_packing(db_path):
    payload = {
        "batch_id":   "BATCH-PP-001",
        "invoice_no": "INV-001",
        "lines": [
            {"design_no": "D-101", "product_code": "EJL/TEST/101",
             "description": "Silver Necklace", "metal": "silver", "category": "necklaces"},
            {"design_no": "D-102", "product_code": "EJL/TEST/102",
             "description": "Gold Bracelet",  "metal": "gold",   "category": "bracelets"},
        ],
    }
    result = rworker.import_purchase_packing(db_path, payload)
    assert result["created"] == 2
    assert result["skipped"] == 0
    assert result["errors"] == []

    # Verify DB state
    pm = rdb.get_product_master(db_path, "EJL/TEST/101")
    assert pm is not None and pm["design_no"] == "D-101"

    dm = rdb.get_product_code_by_design_no(db_path, "D-101")
    assert dm is not None and dm["product_code"] == "EJL/TEST/101"


# ── Test 5: import_sales_packing with known mapping → status=pending ──────────

def test_import_sales_packing_known_design(db_path):
    # Setup purchase packing first
    rworker.import_purchase_packing(db_path, {
        "batch_id": "BATCH-PP-002", "invoice_no": "INV-002",
        "lines": [{"design_no": "D-200", "product_code": "EJL/SALE/200"}],
    })

    result = rworker.import_sales_packing(db_path, {
        "batch_id":    "BATCH-SP-002",
        "client_name": "Dream Rings",
        "lines": [{"design_no": "D-200", "qty": 5, "unit_price": 100.0}],
    })
    assert result["created"] == 1
    assert result["blocked"] == 0
    assert result["rows"][0]["status"] == "pending"
    assert result["rows"][0]["product_code"] == "EJL/SALE/200"


# ── Test 6: import_sales_packing with unknown design_no → status=blocked ──────

def test_import_sales_packing_unknown_design(db_path):
    result = rworker.import_sales_packing(db_path, {
        "batch_id":    "BATCH-SP-003",
        "client_name": "Mystery Client",
        "lines": [{"design_no": "D-UNKNOWN-999", "qty": 2}],
    })
    assert result["blocked"] == 1
    assert result["created"] == 0
    assert result["rows"][0]["status"] == "blocked"
    assert "UNMAPPED" in result["rows"][0]["product_code"]


# ── Test 7: sync_wfirma_products_by_codes — product found ────────────────────

def test_sync_wfirma_products_found(db_path):
    # Need product_master entry
    rdb.upsert_product_master(db_path, "EJL/SYNC/001", "D-SYNC-001")
    mc = _mock_client_with_product("EJL/SYNC/001")

    result = rworker.sync_wfirma_products_by_codes(db_path, mc, ["EJL/SYNC/001"])
    assert "EJL/SYNC/001" in result["matched"]
    assert result["missing"] == []

    mapping = rdb.get_wfirma_product_mapping(db_path, "EJL/SYNC/001")
    assert mapping is not None
    assert mapping["sync_status"] == "matched"
    assert mapping["wfirma_product_id"] == "WF-P-001"


# ── Test 8: sync_wfirma_products_by_codes — product not found ────────────────

def test_sync_wfirma_products_not_found(db_path):
    rdb.upsert_product_master(db_path, "EJL/MISSING/001", "D-MISSING-001")
    mc = _mock_client_no_product()

    result = rworker.sync_wfirma_products_by_codes(db_path, mc, ["EJL/MISSING/001"])
    assert result["matched"] == []
    assert "EJL/MISSING/001" in result["missing"]

    mapping = rdb.get_wfirma_product_mapping(db_path, "EJL/MISSING/001")
    assert mapping is not None
    assert mapping["sync_status"] == "not_found"


# ── Test 9: refresh_queue_readiness promotes pending → ready ──────────────────

def test_refresh_queue_readiness_promotes(db_path):
    product_code = "EJL/READY/001"
    client_name  = "Promo Client"

    # Setup product master + mappings
    rdb.upsert_product_master(db_path, product_code, "D-READY-001")
    rdb.upsert_wfirma_product_mapping(
        db_path, product_code,
        wfirma_product_id="WF-P-READY",
        sync_status="matched",
    )
    rdb.upsert_wfirma_customer_mapping(
        db_path, client_name,
        wfirma_customer_id="WF-C-READY",
        match_status="matched",
    )

    # Create a pending queue row
    key = "test-ready-key-001"
    rdb.upsert_reservation_queue(
        db_path, queue_key=key,
        batch_id="BATCH-RDY", client_name=client_name,
        design_no="D-READY-001", product_code=product_code,
        qty=3, status="pending",
    )

    result = rworker.refresh_queue_readiness(db_path)
    assert result["promoted"] >= 1

    rows = rdb.list_reservation_queue(db_path, status="ready")
    ready_keys = [r["queue_key"] for r in rows]
    assert key in ready_keys


# ── Test 10: refresh_queue_readiness keeps pending if customer missing ─────────

def test_refresh_queue_readiness_no_customer(db_path):
    product_code = "EJL/READY/002"
    client_name  = "No Customer Client"

    rdb.upsert_product_master(db_path, product_code, "D-READY-002")
    rdb.upsert_wfirma_product_mapping(
        db_path, product_code,
        wfirma_product_id="WF-P-002",
        sync_status="matched",
    )
    # No wfirma_customer_mapping for client_name

    key = "test-no-cust-key-001"
    rdb.upsert_reservation_queue(
        db_path, queue_key=key,
        batch_id="BATCH-NOCUST", client_name=client_name,
        design_no="D-READY-002", product_code=product_code,
        qty=1, status="pending",
    )

    rworker.refresh_queue_readiness(db_path)

    row = rdb.list_reservation_queue(db_path, batch_id="BATCH-NOCUST")
    assert row[0]["status"] == "pending"


# ── Test 11: process_ready_reservations dry_run ───────────────────────────────

def test_process_ready_dry_run(db_path):
    product_code = "EJL/DRY/001"
    client_name  = "Dry Run Client"

    rdb.upsert_product_master(db_path, product_code, "D-DRY-001")
    rdb.upsert_wfirma_product_mapping(
        db_path, product_code, wfirma_product_id="WF-DRY-P",
        sync_status="matched",
    )
    rdb.upsert_wfirma_customer_mapping(
        db_path, client_name, wfirma_customer_id="WF-DRY-C",
        match_status="matched",
    )
    rdb.upsert_reservation_queue(
        db_path, queue_key="dry-key-001",
        batch_id="BATCH-DRY", client_name=client_name,
        sales_doc_no="SD-DRY",
        design_no="D-DRY-001", product_code=product_code,
        qty=2, status="ready",
        wfirma_product_id="WF-DRY-P", wfirma_customer_id="WF-DRY-C",
    )

    mc = MagicMock()
    result = rworker.process_ready_reservations(
        db_path, mc, batch_id="BATCH-DRY", mode="dry_run",
    )
    assert result["mode"] == "dry_run"
    assert result["groups"] == 1
    assert result["results"][0]["status"] == "would_create"
    mc.create_reservation.assert_not_called()


# ── Test 12: process_ready_reservations live mode success ─────────────────────

def test_process_ready_live_success(db_path):
    product_code = "EJL/LIVE/001"
    client_name  = "Live Client"

    rdb.upsert_product_master(db_path, product_code, "D-LIVE-001")
    rdb.upsert_wfirma_product_mapping(
        db_path, product_code, wfirma_product_id="WF-LIVE-P",
        sync_status="matched",
    )
    rdb.upsert_wfirma_customer_mapping(
        db_path, client_name, wfirma_customer_id="WF-LIVE-C",
        match_status="matched",
    )
    rdb.upsert_reservation_queue(
        db_path, queue_key="live-key-001",
        batch_id="BATCH-LIVE", client_name=client_name,
        sales_doc_no="SD-LIVE",
        design_no="D-LIVE-001", product_code=product_code,
        qty=1, status="ready",
        wfirma_product_id="WF-LIVE-P", wfirma_customer_id="WF-LIVE-C",
    )

    mc = _mock_client_reservation_ok()
    result = rworker.process_ready_reservations(
        db_path, mc, batch_id="BATCH-LIVE", mode="live",
    )
    assert result["mode"] == "live"
    assert result["results"][0]["status"] == "created"
    assert result["results"][0]["wfirma_reservation_id"] == "WF-R-001"
    mc.create_reservation.assert_called_once()


# ── Test 13: process_ready_reservations live mode failure ─────────────────────

def test_process_ready_live_failure(db_path):
    product_code = "EJL/FAIL/001"
    client_name  = "Fail Client"

    rdb.upsert_product_master(db_path, product_code, "D-FAIL-001")
    rdb.upsert_wfirma_product_mapping(
        db_path, product_code, wfirma_product_id="WF-FAIL-P",
        sync_status="matched",
    )
    rdb.upsert_wfirma_customer_mapping(
        db_path, client_name, wfirma_customer_id="WF-FAIL-C",
        match_status="matched",
    )
    rdb.upsert_reservation_queue(
        db_path, queue_key="fail-key-001",
        batch_id="BATCH-FAIL", client_name=client_name,
        sales_doc_no="SD-FAIL",
        design_no="D-FAIL-001", product_code=product_code,
        qty=1, status="ready",
        wfirma_product_id="WF-FAIL-P", wfirma_customer_id="WF-FAIL-C",
    )

    mc = _mock_client_reservation_fail()
    result = rworker.process_ready_reservations(
        db_path, mc, batch_id="BATCH-FAIL", mode="live",
    )
    assert result["results"][0]["status"] == "failed"
    assert "stock" in result["results"][0]["error"].lower()

    # Verify queue row is now failed
    rows = rdb.list_reservation_queue(db_path, batch_id="BATCH-FAIL")
    assert rows[0]["status"] == "failed"


# ── Test 14: POST /api/v1/products/import-purchase-packing ────────────────────

def test_api_import_purchase_packing(client, tmp_storage):
    db = tmp_storage / "reservation_queue.db"
    rdb.init_reservation_db(db)

    r = client.post(
        "/api/v1/products/import-purchase-packing",
        json={
            "batch_id":   "API-BATCH-001",
            "invoice_no": "API-INV-001",
            "lines": [
                {"design_no": "D-API-001", "product_code": "EJL/API/001",
                 "description": "API Ring", "metal": "gold", "category": "rings"},
            ],
        },
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1
    assert body["skipped"] == 0


# ── Test 15: POST /api/v1/reservations/import-sales-packing ──────────────────

def test_api_import_sales_packing(client, tmp_storage):
    db = tmp_storage / "reservation_queue.db"
    rdb.init_reservation_db(db)

    # First add the purchase packing so design_no resolves
    client.post(
        "/api/v1/products/import-purchase-packing",
        json={
            "batch_id": "API-BATCH-SP",
            "invoice_no": "API-INV-SP",
            "lines": [
                {"design_no": "D-API-SP-001", "product_code": "EJL/API/SP001"},
            ],
        },
        headers=_auth(),
    )

    r = client.post(
        "/api/v1/reservations/import-sales-packing",
        json={
            "batch_id":    "API-BATCH-SP2",
            "client_name": "API Test Client",
            "lines": [
                {"design_no": "D-API-SP-001", "qty": 3, "unit_price": 200.0},
                {"design_no": "D-UNKNOWN-API", "qty": 1},
            ],
        },
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1
    assert body["blocked"] == 1
    statuses = {row["design_no"]: row["status"] for row in body["rows"]}
    assert statuses["D-API-SP-001"] == "pending"
    assert statuses["D-UNKNOWN-API"] == "blocked"


# ── Test 16: GET /api/v1/reservations/queue ───────────────────────────────────

def test_api_get_reservation_queue(client, tmp_storage):
    db = tmp_storage / "reservation_queue.db"
    rdb.init_reservation_db(db)

    # Insert a known row
    rdb.upsert_reservation_queue(
        db, queue_key="api-queue-test-key",
        batch_id="API-QUEUE-BATCH", client_name="Queue Test",
        design_no="D-QT-001", product_code="EJL/QT/001",
        qty=1, status="pending",
    )

    r = client.get(
        "/api/v1/reservations/queue",
        params={"batch_id": "API-QUEUE-BATCH"},
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    keys = [row["queue_key"] for row in body["rows"]]
    assert "api-queue-test-key" in keys


# ── Test 17: POST /api/v1/wfirma/products/sync-by-codes ──────────────────────

def test_api_sync_by_codes(client, tmp_storage):
    db = tmp_storage / "reservation_queue.db"
    rdb.init_reservation_db(db)
    # Add a product master so FK will be satisfied when upsert_wfirma_product_mapping runs
    rdb.upsert_product_master(db, "EJL/SYNC/API/001", "D-SYNC-API-001")

    from app.services.wfirma_client import WFirmaProduct
    mock_product = WFirmaProduct(
        wfirma_id="WF-SYNC-API-001",
        name="Test",
        code="EJL/SYNC/API/001",
    )

    with patch("app.api.routes_reservations.rdb.init_reservation_db"):
        with patch("app.api.routes_reservations._ensure_db", return_value=db):
            with patch(
                "app.services.wfirma_client.get_product_by_code",
                return_value=mock_product,
            ):
                r = client.post(
                    "/api/v1/wfirma/products/sync-by-codes",
                    json={"product_codes": ["EJL/SYNC/API/001", "EJL/MISSING/API/999"]},
                    headers=_auth(),
                )

    assert r.status_code == 200
    body = r.json()
    assert "matched" in body
    assert "missing" in body


# ── Test 18: POST /api/v1/reservations/process-pending dry_run ───────────────

def test_api_process_pending_dry_run(client, tmp_storage):
    db = tmp_storage / "reservation_queue.db"
    rdb.init_reservation_db(db)

    # Insert a ready row
    rdb.upsert_reservation_queue(
        db, queue_key="api-proc-key-001",
        batch_id="API-PROC-BATCH", client_name="Proc Client",
        sales_doc_no="SD-PROC",
        design_no="D-PROC-001", product_code="EJL/PROC/001",
        qty=2, status="ready",
        wfirma_product_id="WF-PROC-P", wfirma_customer_id="WF-PROC-C",
    )

    with patch("app.api.routes_reservations._ensure_db", return_value=db):
        r = client.post(
            "/api/v1/reservations/process-pending",
            json={"batch_id": "API-PROC-BATCH", "mode": "dry_run"},
            headers=_auth(),
        )

    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "dry_run"
    assert body["groups"] >= 1
    statuses = [res["status"] for res in body["results"]]
    assert "would_create" in statuses


# ── Test 19: POST /api/v1/reservations/{queue_id}/reset ──────────────────────

def test_api_reset_queue_row(client, tmp_storage):
    db = tmp_storage / "reservation_queue.db"
    rdb.init_reservation_db(db)

    row_id = rdb.upsert_reservation_queue(
        db, queue_key="api-reset-key-001",
        batch_id="API-RESET-BATCH", client_name="Reset Client",
        design_no="D-RESET-001", product_code="EJL/RESET/001",
        qty=1, status="failed",
    )
    # Record a last_error so we can verify it gets cleared
    rdb.update_queue_status(db, row_id, "failed", last_error="previous error")

    with patch("app.api.routes_reservations._ensure_db", return_value=db):
        r = client.post(
            f"/api/v1/reservations/{row_id}/reset",
            json={"target_status": "pending", "reason": "manual retry"},
            headers=_auth(),
        )

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["new_status"] == "pending"
    assert body["queue_id"] == row_id

    # Verify DB updated
    row = rdb.get_reservation_queue_row(db, row_id)
    assert row["status"] == "pending"


# ── Test 20: Duplicate queue_key is idempotent ────────────────────────────────

def test_duplicate_queue_key_is_idempotent(db_path):
    kwargs = dict(
        queue_key="idempotent-key-001",
        batch_id="BATCH-IDEM", client_name="Idem Client",
        design_no="D-IDEM-001", product_code="EJL/IDEM/001",
        qty=5, status="pending",
    )

    id1 = rdb.upsert_reservation_queue(db_path, **kwargs)
    id2 = rdb.upsert_reservation_queue(db_path, **{**kwargs, "qty": 10})

    # Same id returned — row was updated, not duplicated
    assert id1 == id2

    rows = rdb.list_reservation_queue(db_path, batch_id="BATCH-IDEM")
    # Filter to just our row
    our_rows = [r for r in rows if r["queue_key"] == "idempotent-key-001"]
    assert len(our_rows) == 1
    # qty updated
    assert our_rows[0]["qty"] == 10.0


# ── C-1b.1 regression: the reservations router MUST be registered in main.py ──
# Guards against the router being dropped from app.include_router (the original
# defect: every reservation endpoint 404/405 in production — task_d6fdfca9). It
# also pins the ordering fix — the concrete POST route must resolve and NOT be
# shadowed by the wfirma_capabilities catch-all PUT /wfirma/products/{code:path}.

def test_reservations_router_is_registered_and_http_reachable(client, tmp_storage):
    db = tmp_storage / "reservation_queue.db"
    rdb.init_reservation_db(db)
    rdb.upsert_product_master(db, "EJL/REG/SMOKE/001", "D-REG-SMOKE-001")

    from app.services.wfirma_client import WFirmaProduct
    mock_product = WFirmaProduct(
        wfirma_id="WF-REG-001", name="Test", code="EJL/REG/SMOKE/001",
    )
    with patch("app.api.routes_reservations._ensure_db", return_value=db):
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=mock_product):
            r = client.post(
                "/api/v1/wfirma/products/sync-by-codes",
                json={"product_codes": ["EJL/REG/SMOKE/001"]},
                headers=_auth(),
            )
    # The regression manifested as 405 (catch-all shadow) or 404 (unregistered).
    assert r.status_code == 200, (
        f"reservations router not reachable ({r.status_code}) — is it registered "
        f"in main.py BEFORE wfirma_capabilities_router?"
    )
    # And the concrete POST route is present in the app route table.
    from app.main import app as _app
    registered = any(
        getattr(rt, "path", "") == "/api/v1/wfirma/products/sync-by-codes"
        and "POST" in (getattr(rt, "methods", None) or set())
        for rt in _app.routes
    )
    assert registered, \
        "POST /api/v1/wfirma/products/sync-by-codes missing from app.routes"
