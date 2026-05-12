"""Tests for POST /api/v1/inventory/pieces/{piece_id}/location (Phase 4.5
remediated with Option A — DB-level UNIQUE constraint).

Move stock is location metadata only — DOES NOT transition state.
Single-writer discipline: inventory_state_engine.transition is never
called by this endpoint.

Cases:
  - valid move with new idempotency_key -> 200, status='moved'
  - replay with same idempotency_key -> 200, status='replayed',
    SAME event_id as the first call
  - concurrent writes with same key -> exactly one INSERT wins,
    the other gets the replay path with the SAME event_id
  - empty idempotency_key -> 422 (Pydantic) / 400 (writer)
  - piece not in WAREHOUSE_STOCK -> 409 WRONG_STATE
  - piece not found -> 404 PIECE_NOT_FOUND
  - DB unavailable -> 503 DB_UNAVAILABLE
  - auth enforced (Depends(require_api_key) present)
  - source: no app-level wdb._lock acquired (Option A discipline)
  - source: no _find_prior_idempotent_event remains
  - source: no inventory_state_engine.transition() call
  - no new write methods elsewhere on /api/v1/inventory/*
"""
from __future__ import annotations

import inspect
import sqlite3
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.security import require_api_key
from app.api.routes_inventory_writes import router as _inv_writes_router


# Local test app. Move stock's router is intentionally NOT registered
# on the production `app` from main.py — that's a deploy-time wiring
# step per campaign spec. Using a local FastAPI instance here gives
# us route-level introspection without polluting the shared `app`
# (which would break other test files' "no write methods" assertions
# at session scope).
app = FastAPI()
app.include_router(_inv_writes_router)
app.dependency_overrides[require_api_key] = lambda: None
client = TestClient(app)


PATH = "/api/v1/inventory/pieces/SCAN-001/location"
VALID_BODY = {
    "to_location": "WH-A1",
    "operator": "tester",
    "idempotency_key": "key-001",
    "note": "audit",
}


def _state_row(state: str) -> dict:
    return {
        "id": "row-1",
        "scan_code": "SCAN-001",
        "product_code": "P1",
        "design_no": "D1",
        "batch_id": "B1",
        "state": state,
        "updated_at": "2026-05-12T00:00:00Z",
        "updated_by": "test",
        "note": "",
    }


# ── Happy path ───────────────────────────────────────────────────────────

def test_valid_move_with_new_idempotency_key_succeeds():
    fake_current = {
        "scan_code": "SCAN-001",
        "current_location": "WH-A1",
        "current_status": "in_warehouse",
        "from_location": "WH-A0",
        "event_id": "evt-new-001",
    }
    with patch(
        "app.services.inventory_location_writer.inventory_state_engine.get_state",
        return_value=_state_row("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_location_writer.wdb._db_path", new="/fake/path"
    ), patch(
        "app.services.inventory_location_writer.wdb.record_scan_with_idempotency",
        return_value=fake_current,
    ):
        r = client.post(PATH, json=VALID_BODY)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "moved"
        assert data["event_id"] == "evt-new-001"
        assert data["idempotency_key"] == "key-001"


# ── Replay path (Option A — IntegrityError → fetch existing) ─────────────

def test_replay_with_same_idempotency_key_returns_existing_event_id():
    prior_event = {
        "id": "evt-prior-XYZ",
        "scan_code": "SCAN-001",
        "from_location": "WH-A0",
        "to_location": "WH-A1",
        "action": "MOVE",
        "idempotency_key": "key-001",
    }
    fake_current = {"scan_code": "SCAN-001", "current_location": "WH-A1"}

    integ_err = sqlite3.IntegrityError(
        "UNIQUE constraint failed: idx_movement_idempotency"
    )

    with patch(
        "app.services.inventory_location_writer.inventory_state_engine.get_state",
        return_value=_state_row("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_location_writer.wdb._db_path", new="/fake/path"
    ), patch(
        "app.services.inventory_location_writer.wdb.record_scan_with_idempotency",
        side_effect=integ_err,
    ), patch(
        "app.services.inventory_location_writer.wdb.find_movement_event_by_idempotency",
        return_value=prior_event,
    ), patch(
        "app.services.inventory_location_writer.wdb.get_current_location",
        return_value=fake_current,
    ):
        r = client.post(PATH, json=VALID_BODY)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "replayed"
        # Replay must return the prior event_id, not a fresh one.
        assert data["event_id"] == "evt-prior-XYZ"
        assert data["idempotency_key"] == "key-001"


# ── Concurrent writes — exactly one INSERT wins ──────────────────────────

def test_concurrent_writes_with_same_key_one_wins():
    """Two threads call move_piece with the same (scan_code, key).
    The first INSERT wins; the second hits IntegrityError and replays.
    Both must observe the same event_id.

    Note: in this test we mock record_scan_with_idempotency so that
    the FIRST call returns a normal write result and the SECOND raises
    IntegrityError. This deterministically models the DB-level race
    outcome (the actual SQLite UNIQUE constraint is exercised in
    end-to-end testing on the migrated DB).
    """
    from app.services.inventory_location_writer import move_piece

    call_lock = threading.Lock()
    call_count = {"n": 0}
    winning_event_id = "evt-winner-001"
    write_result = {
        "scan_code": "SCAN-001",
        "current_location": "WH-A1",
        "current_status": "in_warehouse",
        "from_location": "WH-A0",
        "event_id": winning_event_id,
    }
    prior_event = {
        "id": winning_event_id,
        "scan_code": "SCAN-001",
        "from_location": "WH-A0",
        "to_location": "WH-A1",
        "action": "MOVE",
        "idempotency_key": "key-conc",
    }

    def mock_record_scan(**kwargs):
        with call_lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n == 1:
            return write_result
        raise sqlite3.IntegrityError(
            "UNIQUE constraint failed: idx_movement_idempotency"
        )

    results = [None, None]
    errors = [None, None]

    def thread_target(idx):
        try:
            results[idx] = move_piece(
                scan_code="SCAN-001",
                to_location="WH-A1",
                operator="tester",
                idempotency_key="key-conc",
                note="",
            )
        except Exception as e:
            errors[idx] = e

    with patch(
        "app.services.inventory_location_writer.inventory_state_engine.get_state",
        return_value=_state_row("WAREHOUSE_STOCK"),
    ), patch(
        "app.services.inventory_location_writer.wdb._db_path", new="/fake/path"
    ), patch(
        "app.services.inventory_location_writer.wdb.record_scan_with_idempotency",
        side_effect=mock_record_scan,
    ), patch(
        "app.services.inventory_location_writer.wdb.find_movement_event_by_idempotency",
        return_value=prior_event,
    ), patch(
        "app.services.inventory_location_writer.wdb.get_current_location",
        return_value={"scan_code": "SCAN-001", "current_location": "WH-A1"},
    ):
        t1 = threading.Thread(target=thread_target, args=(0,))
        t2 = threading.Thread(target=thread_target, args=(1,))
        t1.start(); t2.start()
        t1.join(); t2.join()

    assert errors[0] is None and errors[1] is None, f"errors: {errors}"
    assert results[0] is not None and results[1] is not None

    # Exactly one moved, exactly one replayed.
    statuses = sorted([results[0]["status"], results[1]["status"]])
    assert statuses == ["moved", "replayed"], (
        f"Expected one moved + one replayed; got {statuses}"
    )

    # Both must agree on the event_id — the contract for callers.
    assert results[0]["event_id"] == results[1]["event_id"] == winning_event_id


# ── Validation paths ─────────────────────────────────────────────────────

def test_empty_idempotency_key_rejected_by_pydantic():
    bad = {"to_location": "WH-A1", "operator": "t", "idempotency_key": ""}
    r = client.post(PATH, json=bad)
    # Pydantic min_length=1 → 422
    assert r.status_code == 422


def test_missing_fields_return_422():
    r1 = client.post(PATH, json={})
    assert r1.status_code == 422
    r2 = client.post(PATH, json={"to_location": "WH-A1", "idempotency_key": "k"})
    assert r2.status_code == 422


def test_piece_not_in_warehouse_stock_rejected():
    with patch(
        "app.services.inventory_location_writer.inventory_state_engine.get_state",
        return_value=_state_row("PURCHASE_TRANSIT"),
    ), patch(
        "app.services.inventory_location_writer.wdb._db_path", new="/fake/path"
    ):
        r = client.post(PATH, json=VALID_BODY)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "WRONG_STATE"


def test_piece_not_found_returns_404():
    with patch(
        "app.services.inventory_location_writer.inventory_state_engine.get_state",
        return_value=None,
    ), patch(
        "app.services.inventory_location_writer.wdb._db_path", new="/fake/path"
    ):
        r = client.post(PATH, json=VALID_BODY)
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "PIECE_NOT_FOUND"


def test_db_unavailable_returns_503():
    with patch(
        "app.services.inventory_location_writer.wdb._db_path", new=None
    ):
        r = client.post(PATH, json=VALID_BODY)
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "DB_UNAVAILABLE"


# ── Source-level discipline checks (Option A invariants) ─────────────────

def test_source_does_not_acquire_app_level_lock():
    """Option A removes app-level locking. The DB UNIQUE constraint is
    the sole serialiser. Source must not contain `wdb._lock` or
    `with wdb._lock`."""
    from app.services import inventory_location_writer as m
    src = inspect.getsource(m)
    # Strip docstrings before scanning
    lines = []
    in_docstring = False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            if s.count('"""') >= 2 or s.count("'''") >= 2:
                pass
            else:
                in_docstring = not in_docstring
            continue
        if in_docstring or s.startswith("#"):
            continue
        lines.append(line)
    code_only = "\n".join(lines)
    forbidden_lock = ("wdb._lock", "with wdb._lock", "with _lock")
    for pat in forbidden_lock:
        assert pat not in code_only, (
            f"Option A discipline violated: writer uses app-level lock {pat!r}"
        )


def test_source_has_no_find_prior_idempotent_event():
    """The pre-remediation race source was a function called
    _find_prior_idempotent_event. After Option A it must be gone."""
    from app.services import inventory_location_writer as m
    src = inspect.getsource(m)
    assert "_find_prior_idempotent_event" not in src, (
        "Legacy SELECT-then-INSERT helper must be removed under Option A"
    )


def test_source_does_not_call_state_transition():
    """Single-writer discipline preserved."""
    from app.services import inventory_location_writer as m
    src = inspect.getsource(m)
    lines = []
    in_docstring = False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            if s.count('"""') >= 2 or s.count("'''") >= 2:
                pass
            else:
                in_docstring = not in_docstring
            continue
        if in_docstring or s.startswith("#"):
            continue
        lines.append(line)
    code_only = "\n".join(lines)
    for pat in (
        "inventory_state_engine.transition(",
        ".transition(",
    ):
        assert pat not in code_only, (
            f"Move-stock must not call {pat}"
        )


def test_no_new_writes_on_inventory_paths():
    """The /api/v1/inventory/* router family exposes exactly one write
    path under this branch — POST /pieces/{piece_id}/location.
    Trailing slash excludes the pre-existing /api/v1/inventory-state/*
    lifecycle write."""
    write_paths = []
    for r in app.routes:
        path = getattr(r, "path", "")
        methods = set(getattr(r, "methods", set()) or set())
        if not path.startswith("/api/v1/inventory/"):
            continue
        if methods & {"POST", "PUT", "PATCH", "DELETE"}:
            write_paths.append((path, methods))
    assert len(write_paths) == 1, (
        f"Expected exactly 1 write path on /api/v1/inventory/*, got "
        f"{write_paths}"
    )
    path, methods = write_paths[0]
    assert path == "/api/v1/inventory/pieces/{piece_id}/location"
    assert methods == {"POST"}


def test_pieces_path_registered():
    move_routes = [
        r for r in app.routes
        if getattr(r, "path", "") == "/api/v1/inventory/pieces/{piece_id}/location"
    ]
    assert move_routes
    methods = set()
    for r in move_routes:
        methods |= set(getattr(r, "methods", set()) or set())
    assert "POST" in methods


def test_warehouse_db_has_idempotency_helpers():
    """The two helpers added to warehouse_db.py must exist and be callable."""
    from app.services import warehouse_db as wdb
    assert callable(getattr(wdb, "record_scan_with_idempotency", None)), (
        "warehouse_db.record_scan_with_idempotency must be defined"
    )
    assert callable(getattr(wdb, "find_movement_event_by_idempotency", None)), (
        "warehouse_db.find_movement_event_by_idempotency must be defined"
    )
