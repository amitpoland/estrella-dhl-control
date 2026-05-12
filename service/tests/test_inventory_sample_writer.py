"""End-to-end writer + route tests for Sample-out / Sample-return.

Covers:
- Valid sample-out with all required fields → 200 sampled_out
- Idempotent replay → same event_id
- Missing migration → 503 MIGRATION_PENDING (sanitized detail)
- DB unavailable → 503 DB_UNAVAILABLE
- Piece not in WAREHOUSE_STOCK → 409 WRONG_STATE
- Piece not found → 404 PIECE_NOT_FOUND
- Bad evidence (past date, bad reason, missing recipient) → 400
- Recipient-overdue block → 409 RECIPIENT_OVERDUE_BLOCK
- Sample-return happy path → 200 returned
- Sample-return on non-sampled piece → 409 WRONG_STATE
- Move stock rejects a sampled piece (per §8.1) — natural state-gate
- No-direct-state-mutation source-check on writer
- Routes registered on production main app
"""
from __future__ import annotations

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
from app.api.routes_inventory_sample import router as _sample_router


# Local test app — keeps test isolation clean (same pattern as Move
# stock test file). Production main.py registration is verified
# separately by test_sample_routes_registered_on_main_app below.
app = FastAPI()
app.include_router(_sample_router)
app.dependency_overrides[require_api_key] = lambda: None
client = TestClient(app)


def _future(days: int = 7) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _state(state: str) -> dict:
    return {
        "id": "row-1", "scan_code": "S001",
        "product_code": "P1", "design_no": "D1",
        "batch_id": "B1", "state": state,
        "updated_at": "2026-05-12T00:00:00Z", "updated_by": "test", "note": "",
    }


VALID_OUT_BODY = {
    "operator": "alice",
    "recipient_client_name": "ACME Corp",
    "expected_return_date": _future(7),
    "sample_reason": "customer_review",
    "idempotency_key": "smoke-001",
    "notes": "happy path",
}


# Autouse: most tests assume schema OK + DB available + no overdue
# samples for the recipient. Tests that exercise a specific failure
# path override these patches in their body.
@pytest.fixture(autouse=True)
def _stub_writer_deps():
    with patch(
        "app.services.inventory_sample_writer.wdb._db_path", new="/fake/path"
    ), patch(
        "app.services.inventory_sample_writer.wdb.ensure_sample_out_schema",
        return_value=True,
    ), patch(
        "app.services.inventory_sample_writer.wdb.count_open_overdue_samples_for_recipient",
        return_value=0,
    ):
        yield


# ── Happy paths ──────────────────────────────────────────────────────────

def test_sample_out_happy_path():
    with patch(
        "app.services.inventory_sample_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_sample_writer.wdb.record_sample_out_event",
        return_value={"id": "evt-new-001"},
    ), patch(
        "app.services.inventory_sample_writer.inventory_state_engine.transition"
    ) as mock_transition:
        r = client.post("/api/v1/inventory/pieces/S001/sample-out", json=VALID_OUT_BODY)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "sampled_out"
        assert body["event_id"] == "evt-new-001"
        assert body["recipient_client_name"] == "ACME Corp"
        # transition() was called with SAMPLE_OUT + full evidence
        mock_transition.assert_called_once()
        kwargs = mock_transition.call_args.kwargs
        assert kwargs["to_state"] == "SAMPLE_OUT"
        assert kwargs["recipient_client_name"] == "ACME Corp"
        assert kwargs["sample_reason"] == "customer_review"


def test_sample_return_happy_path():
    with patch(
        "app.services.inventory_sample_writer.inventory_state_engine.get_state",
        return_value=_state("SAMPLE_OUT"),
    ), patch(
        "app.services.inventory_sample_writer.wdb.find_origin_sample_out_event",
        return_value={"id": "evt-origin-001"},
    ), patch(
        "app.services.inventory_sample_writer.wdb.record_sample_out_event",
        return_value={"id": "evt-return-001"},
    ), patch(
        "app.services.inventory_sample_writer.inventory_state_engine.transition"
    ) as mock_transition:
        r = client.post(
            "/api/v1/inventory/pieces/S001/sample-return",
            json={"operator": "alice", "idempotency_key": "ret-001"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "returned"
        assert body["event_id"] == "evt-return-001"
        assert body["linked_origin_event_id"] == "evt-origin-001"
        kwargs = mock_transition.call_args.kwargs
        assert kwargs["to_state"] == "WAREHOUSE_STOCK"


# ── Idempotency replay ───────────────────────────────────────────────────

def test_sample_out_replay_returns_prior_event_id():
    prior = {
        "id": "evt-prior-XYZ",
        "scan_code": "S001",
        "recipient_client_name": "ACME Corp",
        "expected_return_date": VALID_OUT_BODY["expected_return_date"],
        "idempotency_key": "smoke-001",
    }
    integ = sqlite3.IntegrityError(
        "UNIQUE constraint failed: idx_sample_out_idempotency"
    )
    with patch(
        "app.services.inventory_sample_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_sample_writer.wdb.record_sample_out_event",
        side_effect=integ,
    ), patch(
        "app.services.inventory_sample_writer.wdb.find_sample_out_event_by_idempotency",
        return_value=prior,
    ), patch(
        "app.services.inventory_sample_writer.inventory_state_engine.transition"
    ) as mock_transition:
        r = client.post("/api/v1/inventory/pieces/S001/sample-out", json=VALID_OUT_BODY)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "replayed"
        assert body["event_id"] == "evt-prior-XYZ"
        # Replay must NOT call transition() — state was already changed
        # by the original (succeeded) request.
        mock_transition.assert_not_called()


# ── Validation / guard-rail rejections ───────────────────────────────────

def test_migration_pending_returns_503():
    with patch(
        "app.services.inventory_sample_writer.wdb.ensure_sample_out_schema",
        return_value=False,
    ):
        r = client.post("/api/v1/inventory/pieces/S001/sample-out", json=VALID_OUT_BODY)
        assert r.status_code == 503, r.text
        body = r.json()
        assert body["detail"]["code"] == "MIGRATION_PENDING"
        # Sanitize check: no SQL/traceback leakage
        for forbidden in ("Traceback", "sqlite3.", "no such column",
                          "OperationalError", "SELECT ", "INSERT "):
            assert forbidden not in body["detail"]["detail"], (
                f"MIGRATION_PENDING detail leaked {forbidden!r}: "
                f"{body['detail']['detail']}"
            )


def test_db_unavailable_returns_503():
    with patch(
        "app.services.inventory_sample_writer.wdb._db_path", new=None
    ):
        r = client.post("/api/v1/inventory/pieces/S001/sample-out", json=VALID_OUT_BODY)
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "DB_UNAVAILABLE"


def test_piece_not_found_returns_404():
    with patch(
        "app.services.inventory_sample_writer.inventory_state_engine.get_state",
        return_value=None,
    ):
        r = client.post("/api/v1/inventory/pieces/S001/sample-out", json=VALID_OUT_BODY)
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "PIECE_NOT_FOUND"


def test_wrong_state_returns_409():
    with patch(
        "app.services.inventory_sample_writer.inventory_state_engine.get_state",
        return_value=_state("PURCHASE_TRANSIT"),
    ):
        r = client.post("/api/v1/inventory/pieces/S001/sample-out", json=VALID_OUT_BODY)
        assert r.status_code == 409
        body = r.json()
        assert body["detail"]["code"] == "WRONG_STATE"
        assert "PURCHASE_TRANSIT" in body["detail"]["detail"]


def test_recipient_overdue_block_returns_409():
    with patch(
        "app.services.inventory_sample_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_sample_writer.wdb.count_open_overdue_samples_for_recipient",
        return_value=3,
    ):
        r = client.post("/api/v1/inventory/pieces/S001/sample-out", json=VALID_OUT_BODY)
        assert r.status_code == 409
        body = r.json()
        assert body["detail"]["code"] == "RECIPIENT_OVERDUE_BLOCK"
        assert "ACME Corp" in body["detail"]["detail"]
        assert "30" in body["detail"]["detail"]  # threshold days


def test_bad_evidence_past_date_returns_400():
    past_body = dict(VALID_OUT_BODY)
    past_body["expected_return_date"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat()
    with patch(
        "app.services.inventory_sample_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_sample_writer.wdb.record_sample_out_event",
        return_value={"id": "evt-tmp"},
    ), patch(
        "app.services.inventory_sample_writer.inventory_state_engine.transition",
        side_effect=ValueError("SAMPLE_OUT requires evidence; missing: expected_return_date in the future"),
    ):
        r = client.post("/api/v1/inventory/pieces/S001/sample-out", json=past_body)
        assert r.status_code == 400
        body = r.json()
        assert body["detail"]["code"] == "INVALID_EVIDENCE"
        assert "expected_return_date" in body["detail"]["detail"]


def test_missing_idempotency_key_pydantic_422():
    bad = dict(VALID_OUT_BODY)
    bad.pop("idempotency_key")
    r = client.post("/api/v1/inventory/pieces/S001/sample-out", json=bad)
    assert r.status_code == 422


def test_sample_return_wrong_state_returns_409():
    with patch(
        "app.services.inventory_sample_writer.inventory_state_engine.get_state",
        return_value=_state("WAREHOUSE_STOCK"),  # not SAMPLE_OUT
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/sample-return",
            json={"operator": "alice", "idempotency_key": "ret-001"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "WRONG_STATE"


def test_sample_return_no_open_sample_returns_409():
    """Piece is in SAMPLE_OUT but no open sample_out_events row —
    data-integrity inconsistency; refuse to return."""
    with patch(
        "app.services.inventory_sample_writer.inventory_state_engine.get_state",
        return_value=_state("SAMPLE_OUT"),
    ), patch(
        "app.services.inventory_sample_writer.wdb.find_origin_sample_out_event",
        return_value=None,
    ):
        r = client.post(
            "/api/v1/inventory/pieces/S001/sample-return",
            json={"operator": "alice", "idempotency_key": "ret-001"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "NO_OPEN_SAMPLE_OUT"


# ── Move stock + SAMPLE_OUT interaction (§8.1) ──────────────────────────

def test_move_stock_rejects_sampled_piece():
    """Move stock's state-gate (WAREHOUSE_STOCK only) naturally rejects
    a piece in SAMPLE_OUT. No code change to Move stock needed (per
    §8.1 operator decision) — this test confirms the existing behavior."""
    from app.services import inventory_location_writer as lw
    from app.services.inventory_location_writer import MoveStockError
    with patch(
        "app.services.inventory_location_writer.wdb._db_path", new="/fake/path"
    ), patch(
        "app.services.inventory_location_writer.wdb.ensure_idempotency_schema",
        return_value=True,
    ), patch(
        "app.services.inventory_location_writer.inventory_state_engine.get_state",
        return_value=_state("SAMPLE_OUT"),
    ):
        with pytest.raises(MoveStockError) as exc:
            lw.move_piece(
                scan_code="S001",
                to_location="WH-B2",
                operator="alice",
                idempotency_key="mv-001",
            )
        assert exc.value.code == "WRONG_STATE"
        assert "SAMPLE_OUT" in exc.value.detail


# ── Source / wiring checks ───────────────────────────────────────────────

def test_writer_does_not_directly_mutate_inventory_state():
    """Single-writer discipline: the Sample-out writer must NOT contain
    raw SQL that updates inventory_state. All state mutations go
    through inventory_state_engine.transition()."""
    import inspect
    from app.services import inventory_sample_writer as m
    src = inspect.getsource(m)
    for forbidden in (
        'UPDATE inventory_state',
        'INSERT INTO inventory_state ',  # space — not the events table
        '"UPDATE inventory_state',
        "'UPDATE inventory_state",
    ):
        assert forbidden not in src, (
            f"Sample-out writer must NOT contain {forbidden!r} — "
            "all state mutations via transition()"
        )


def test_writer_calls_transition_for_state_changes():
    """transition() must be referenced by the writer (both directions)."""
    import inspect
    from app.services import inventory_sample_writer as m
    src = inspect.getsource(m)
    assert "inventory_state_engine.transition(" in src


def test_sample_routes_registered_on_main_app():
    """Production main.py wires both sample-out and sample-return."""
    from app.main import app as prod
    paths = [getattr(r, "path", "") for r in prod.routes]
    assert "/api/v1/inventory/pieces/{piece_id}/sample-out" in paths
    assert "/api/v1/inventory/pieces/{piece_id}/sample-return" in paths


def test_main_app_inventory_writes_are_only_three():
    """Move stock + sample-out + sample-return = exactly 3 writes under
    /api/v1/inventory/*. Any addition requires new SECURITY review."""
    from app.main import app as prod
    writes = []
    for r in prod.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/v1/inventory/"):
            continue
        methods = set(getattr(r, "methods", set()) or set())
        if methods & {"POST", "PUT", "PATCH", "DELETE"}:
            writes.append((path, methods))
    expected = {
        "/api/v1/inventory/pieces/{piece_id}/location",
        "/api/v1/inventory/pieces/{piece_id}/sample-out",
        "/api/v1/inventory/pieces/{piece_id}/sample-return",
    }
    actual = {p for p, _ in writes}
    assert actual == expected, (
        f"Expected exactly {sorted(expected)} write paths; got {sorted(actual)}"
    )
    for _, methods in writes:
        assert methods == {"POST"}
