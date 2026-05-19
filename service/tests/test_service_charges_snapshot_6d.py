"""
test_service_charges_snapshot_6d.py — Phase 6D snapshot timing contracts.

Pins:
  1. upsert_pending_draft accepts service_charges_json and persists it.
  2. A draft created with charges has service_charges_json populated.
  3. Replay (ON CONFLICT DO NOTHING) returns the original snapshot unchanged.
  4. Retry path (failed draft) updates service_charges_json.
  5. Source-grep: routes_proforma no longer has the old hard block.
  6. Source-grep: _service_charges_json_snapshot is built and passed to
     upsert_pending_draft at create time.
  7. finance_dual_write reads service_charges_json from the draft row
     and produces charge_count > 0 when charges are present.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest


# ── Path bootstrap ────────────────────────────────────────────────────────────

def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)

_ensure_path()

from app.services.proforma_invoice_link_db import (  # noqa: E402
    upsert_pending_draft, get_draft, init_db, _commit_draft_update,
)

_ROUTES   = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_proforma.py"
_HELPER   = Path(__file__).resolve().parents[1] / "app" / "services" / "finance_dual_write.py"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test_pildb.db"
    init_db(p)
    return p


SAMPLE_CHARGES = [
    {"charge_type": "freight",   "amount": 90.0,  "currency": "USD", "note": "test"},
    {"charge_type": "insurance", "amount": 60.0,  "currency": "USD", "note": "test"},
]


# ── 1. upsert_pending_draft persists service_charges_json ────────────────────

def test_upsert_persists_service_charges(db):
    sc_json = json.dumps(SAMPLE_CHARGES, sort_keys=True)
    draft, created = upsert_pending_draft(
        db,
        batch_id              = "BATCH-SC-001",
        client_name           = "TestClient",
        currency              = "USD",
        exchange_rate         = None,
        source_lines_json     = "[]",
        service_charges_json  = sc_json,
    )
    assert created is True
    stored = json.loads(draft.service_charges_json or "[]")
    assert len(stored) == 2
    types = {c["charge_type"] for c in stored}
    assert types == {"freight", "insurance"}


# ── 2. Default (no arg) produces empty list ───────────────────────────────────

def test_upsert_default_service_charges_is_empty(db):
    draft, created = upsert_pending_draft(
        db,
        batch_id          = "BATCH-SC-002",
        client_name       = "TestClient2",
        currency          = "USD",
        exchange_rate     = None,
        source_lines_json = "[]",
    )
    assert created is True
    stored = json.loads(draft.service_charges_json or "[]")
    assert stored == []


# ── 3. Replay returns original snapshot unchanged ─────────────────────────────

def test_upsert_replay_does_not_overwrite(db):
    sc_first  = json.dumps([{"charge_type": "freight", "amount": 90.0, "currency": "USD", "note": ""}], sort_keys=True)
    sc_second = json.dumps([{"charge_type": "insurance", "amount": 60.0, "currency": "USD", "note": ""}], sort_keys=True)

    draft1, c1 = upsert_pending_draft(
        db, batch_id="BATCH-SC-003", client_name="C3",
        currency="USD", exchange_rate=None, source_lines_json="[]",
        service_charges_json=sc_first,
    )
    draft2, c2 = upsert_pending_draft(
        db, batch_id="BATCH-SC-003", client_name="C3",
        currency="USD", exchange_rate=None, source_lines_json="[]",
        service_charges_json=sc_second,
    )
    assert c1 is True
    assert c2 is False  # ON CONFLICT DO NOTHING
    # Original snapshot must survive
    stored = json.loads(draft2.service_charges_json or "[]")
    assert len(stored) == 1
    assert stored[0]["charge_type"] == "freight"


# ── 4. Retry path: _commit_draft_update can refresh charges ──────────────────

def test_retry_path_updates_service_charges(db):
    draft, _ = upsert_pending_draft(
        db, batch_id="BATCH-SC-004", client_name="C4",
        currency="USD", exchange_rate=None, source_lines_json="[]",
        service_charges_json="[]",
    )
    assert json.loads(draft.service_charges_json) == []

    refreshed = _commit_draft_update(
        db, draft.id,
        new_state           = "post_failed",   # failed draft retry state
        new_service_charges = SAMPLE_CHARGES,
    )
    stored = json.loads(refreshed.service_charges_json or "[]")
    assert len(stored) == 2


# ── 5. Source-grep: old hard block REMOVED from routes_proforma ───────────────

def test_old_hard_block_removed():
    text = _ROUTES.read_text(encoding="utf-8")
    assert "service charges present but wFirma service product mapping" \
        not in text, (
        "Old hard block must be removed — service charges no longer block "
        "proforma create (Phase 6D snapshot fix)"
    )


# ── 6. Source-grep: snapshot is built and passed at create time ───────────────

def test_snapshot_built_and_passed_to_upsert():
    text = _ROUTES.read_text(encoding="utf-8")
    assert "_service_charges_json_snapshot" in text, (
        "_service_charges_json_snapshot must be defined in routes_proforma"
    )
    assert "service_charges_json  = _service_charges_json_snapshot" in text or \
           "service_charges_json=_service_charges_json_snapshot" in text, (
        "service_charges_json snapshot must be passed to upsert_pending_draft"
    )


# ── 7. finance_dual_write: charge_count > 0 when draft has charges ────────────

def test_dual_write_reads_charges_from_snapshot(tmp_path):
    import os
    os.environ.setdefault("STORAGE_ROOT", str(tmp_path))
    os.environ.setdefault("ENGINE_DIR", str(Path(__file__).resolve().parents[2]))

    from app.services.finance_dual_write import dual_write_proforma_post

    sc_json = json.dumps(SAMPLE_CHARGES, sort_keys=True)
    result = dual_write_proforma_post(
        db_path              = tmp_path / "finance_postings.sqlite",
        batch_id             = "BATCH-SC-DW-001",
        client_name          = "TestClient",
        currency             = "USD",
        full_number          = "PRO 1/2026-TEST",
        service_charges_json = sc_json,
        enabled              = True,
        shadow               = True,
    )
    assert result["ok"] is True
    assert result["mode"] == "shadow"
    assert result["charge_count"] == 2
    # Shadow mode: no DB writes
    live_db = tmp_path / "finance_postings.sqlite"
    assert not live_db.exists(), "finance_postings.sqlite must not be created in shadow mode"
