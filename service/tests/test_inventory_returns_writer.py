"""End-to-end writer + route tests for Returns (Phase B.2).

Mirrors test_inventory_sample_writer.py. Covers:
  - mark_returned_from_client happy path + replay
  - mark_returned_to_producer happy path + replay
  - return_from_producer_to_stock happy path
  - Wrong state -> 409 WRONG_STATE
  - Piece not found -> 404
  - Missing migration -> 503 MIGRATION_PENDING (sanitized detail)
  - DB unavailable -> 503 DB_UNAVAILABLE
  - Bad evidence (future received_at, bad reason, missing producer
    name) -> 400 INVALID_EVIDENCE
  - No-direct-state-mutation source-check on writer
  - Returns routes registered on production main app
"""
from __future__ import annotations

import inspect
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.security import require_api_key
from app.api.routes_inventory_returns import router as _returns_router


# Local test app — same isolation pattern as Move stock + Sample-out.
app = FastAPI()
app.include_router(_returns_router)
app.dependency_overrides[require_api_key] = lambda: None
client = TestClient(app)


def _past(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _future(days: int = 14) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _state(state: str, scan: str = "S001") -> dict:
    return {
        "id": "row-1", "scan_code": scan,
        "product_code": "P1", "design_no": "D1",
        "batch_id": "B1", "state": state,
        "updated_at": "2026-05-12T00:00:00Z",
        "updated_by": "test", "note": "",
    }


VALID_FROM_CLIENT = {
    "operator": "alice",
    "return_reason": "warranty_claim",
    "origin_context": "RMA-9000",
    "received_at": _past(1),
    "idempotency_key": "rfc-001",
    "source_holder_name": "ACME Corp",
    "notes": "",
}

VALID_TO_PRODUCER = {
    "operator": "alice",
    "producer_name": "ProdCo",
    "return_reason": "defect",
    "idempotency_key": "rtp-001",
    "expected_resolution_date": _future(14),
    "notes": "",
}

VALID_FROM_PRODUCER = {
    "operator": "alice",
    "idempotency_key": "rfp-001",
    "notes": "",
}


@pytest.fixture(autouse=True)
def _stub_writer_deps():
    """Most tests assume schema OK + DB available. Failure-path tests
    override these patches in their own body."""
    with patch(
        "app.services.inventory_returns_writer.wdb._db_path", new="/fake/path"
    ), patch(
        "app.services.inventory_returns_writer.wdb.ensure_returns_schema",
        return_value=True,
    ):
        yield


# ── Happy paths ──────────────────────────────────────────────────────────

def test_return_from_client_happy_path():
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_returns_writer.wdb.record_returns_event",
        return_value={"id": "evt-rfc-1"},
    ), patch(
        "app.services.inventory_returns_writer.inventory_state_engine.transition"
    ) as mock_transition:
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-from-client",
            json=VALID_FROM_CLIENT,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "returned_from_client"
        assert body["event_id"] == "evt-rfc-1"
        assert body["direction"] == "from_client"
        # Critical: transition was called -> single-writer discipline.
        assert mock_transition.called


def test_return_from_client_from_sample_out_legal():
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("SAMPLE_OUT"),
    ), patch(
        "app.services.inventory_returns_writer.wdb.record_returns_event",
        return_value={"id": "evt-rfc-2"},
    ), patch(
        "app.services.inventory_returns_writer.inventory_state_engine.transition"
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-from-client",
            json=VALID_FROM_CLIENT,
        )
        assert r.status_code == 200, r.text


def test_return_to_producer_happy_path():
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_returns_writer.wdb.record_returns_event",
        return_value={"id": "evt-rtp-1"},
    ), patch(
        "app.services.inventory_returns_writer.inventory_state_engine.transition"
    ) as mock_transition:
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-to-producer",
            json=VALID_TO_PRODUCER,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "returned_to_producer"
        assert body["event_id"] == "evt-rtp-1"
        assert mock_transition.called


def test_return_to_producer_from_rfc_legal():
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("RETURNED_FROM_CLIENT"),
    ), patch(
        "app.services.inventory_returns_writer.wdb.record_returns_event",
        return_value={"id": "evt-rtp-2"},
    ), patch(
        "app.services.inventory_returns_writer.inventory_state_engine.transition"
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-to-producer",
            json=VALID_TO_PRODUCER,
        )
        assert r.status_code == 200, r.text


def test_return_from_producer_happy_path():
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("RETURNED_TO_PRODUCER"),
    ), patch(
        "app.services.inventory_returns_writer.wdb.record_returns_event",
        return_value={"id": "evt-rfp-1"},
    ), patch(
        "app.services.inventory_returns_writer.inventory_state_engine.transition"
    ) as mock_transition:
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-from-producer",
            json=VALID_FROM_PRODUCER,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "returned_from_producer_to_stock"
        assert mock_transition.called


# ── Replay (idempotency) ─────────────────────────────────────────────────

def test_replay_returns_prior_event_id():
    def _raise_unique(*a, **kw):
        raise sqlite3.IntegrityError(
            "UNIQUE constraint failed: idx_returns_idempotency"
        )
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_returns_writer.wdb.record_returns_event",
        side_effect=_raise_unique,
    ), patch(
        "app.services.inventory_returns_writer.wdb.find_returns_event_by_idempotency",
        return_value={"id": "evt-prior", "return_reason": "warranty_claim",
                       "received_at": _past(1)},
    ), patch(
        "app.services.inventory_returns_writer.inventory_state_engine.transition"
    ) as mock_transition:
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-from-client",
            json=VALID_FROM_CLIENT,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "replayed"
        assert body["event_id"] == "evt-prior"
        # CRITICAL: replay must NOT trigger a second state transition.
        assert not mock_transition.called


def test_replay_to_producer_returns_prior_event_id():
    def _raise_unique(*a, **kw):
        raise sqlite3.IntegrityError(
            "UNIQUE constraint failed: idx_returns_idempotency"
        )
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_returns_writer.wdb.record_returns_event",
        side_effect=_raise_unique,
    ), patch(
        "app.services.inventory_returns_writer.wdb.find_returns_event_by_idempotency",
        return_value={"id": "evt-prior-rtp", "producer_name": "ProdCo"},
    ), patch(
        "app.services.inventory_returns_writer.inventory_state_engine.transition"
    ) as mock_transition:
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-to-producer",
            json=VALID_TO_PRODUCER,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "replayed"
        assert not mock_transition.called


# ── State-gate failures ──────────────────────────────────────────────────

def test_return_from_client_rejects_purchase_transit():
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("PURCHASE_TRANSIT"),
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-from-client",
            json=VALID_FROM_CLIENT,
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "WRONG_STATE"


def test_return_to_producer_rejects_closed():
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("CLOSED"),
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-to-producer",
            json=VALID_TO_PRODUCER,
        )
        assert r.status_code == 409


def test_return_from_producer_only_from_rtp():
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-from-producer",
            json=VALID_FROM_PRODUCER,
        )
        assert r.status_code == 409


def test_piece_not_found_returns_404():
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=None,
    ):
        r = client.post(
            "/api/v1/inventory/pieces/NOPE/return-from-client",
            json=VALID_FROM_CLIENT,
        )
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "PIECE_NOT_FOUND"


# ── DB/migration failure paths ───────────────────────────────────────────

def test_missing_migration_returns_503():
    with patch(
        "app.services.inventory_returns_writer.wdb.ensure_returns_schema",
        return_value=False,
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-from-client",
            json=VALID_FROM_CLIENT,
        )
        assert r.status_code == 503
        body = r.json()
        assert body["detail"]["code"] == "MIGRATION_PENDING"
        # No SQL traceback leaked.
        assert "Traceback" not in body["detail"]["detail"]
        assert "no column named" not in body["detail"]["detail"].lower()


def test_db_unavailable_returns_503():
    with patch(
        "app.services.inventory_returns_writer.wdb._db_path", new=None
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-from-client",
            json=VALID_FROM_CLIENT,
        )
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "DB_UNAVAILABLE"


# ── Engine-level evidence rejection -> 400 INVALID_EVIDENCE ──────────────

def test_invalid_evidence_returns_400_on_future_received_at():
    def _raise(*a, **kw):
        raise ValueError(
            "RETURNED_FROM_CLIENT requires evidence; missing: "
            "received_at not in the future"
        )
    body = dict(VALID_FROM_CLIENT)
    body["received_at"] = _future(7)
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_returns_writer.wdb.record_returns_event",
        return_value={"id": "evt-1"},
    ), patch(
        "app.services.inventory_returns_writer.inventory_state_engine.transition",
        side_effect=_raise,
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-from-client",
            json=body,
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_EVIDENCE"


def test_invalid_evidence_returns_400_on_bad_reason_for_producer():
    def _raise(*a, **kw):
        raise ValueError(
            "RETURNED_TO_PRODUCER requires evidence; missing: return_reason"
        )
    body = dict(VALID_TO_PRODUCER)
    body["return_reason"] = "not_in_enum"
    with patch(
        "app.services.inventory_returns_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_returns_writer.wdb.record_returns_event",
        return_value={"id": "evt-2"},
    ), patch(
        "app.services.inventory_returns_writer.inventory_state_engine.transition",
        side_effect=_raise,
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/return-to-producer",
            json=body,
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_EVIDENCE"


# ── Route schema (Pydantic) validation ───────────────────────────────────

def test_return_from_client_missing_required_field_returns_422():
    body = dict(VALID_FROM_CLIENT)
    del body["received_at"]
    r = client.post(
        "/api/v1/inventory/pieces/S001/return-from-client", json=body,
    )
    assert r.status_code == 422


def test_return_to_producer_missing_producer_name_returns_422():
    body = dict(VALID_TO_PRODUCER)
    del body["producer_name"]
    r = client.post(
        "/api/v1/inventory/pieces/S001/return-to-producer", json=body,
    )
    assert r.status_code == 422


# ── Single-writer discipline (source-grep invariant) ─────────────────────

def test_returns_writer_does_not_directly_mutate_inventory_state():
    """The writer must NOT contain INSERT/UPDATE/DELETE against
    inventory_state or inventory_state_events. All state mutation
    routes through inventory_state_engine.transition()."""
    from app.services import inventory_returns_writer as m
    src = inspect.getsource(m)
    for forbidden in (
        "INSERT INTO inventory_state", "UPDATE inventory_state",
        "DELETE FROM inventory_state",
        "INSERT INTO inventory_state_events",
    ):
        assert forbidden not in src, (
            f"Returns writer must not contain {forbidden!r}"
        )


# ── Production main-app registration ─────────────────────────────────────

def test_returns_routes_registered_on_main_app():
    from app.main import app as prod
    paths = {getattr(r, "path", "") for r in prod.routes}
    for p in (
        "/api/v1/inventory/pieces/{piece_id}/return-from-client",
        "/api/v1/inventory/pieces/{piece_id}/return-to-producer",
        "/api/v1/inventory/pieces/{piece_id}/return-from-producer",
    ):
        assert p in paths, f"Missing returns route on main app: {p}"
