"""B-008: draft-birth blocks API advisory filter (include_advisory).

Read-side only. contractor_conflict remains open/advisory in the store;
include_advisory=false excludes it from list responses without mutation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import proforma_invoice_link_db as pildb


@pytest.fixture()
def blocks_db(tmp_path: Path) -> Path:
    db = tmp_path / "proforma_links.db"
    import sqlite3

    with sqlite3.connect(db) as con:
        pildb._ensure_drafts_table(con)
    return db


def _seed_mixed(db: Path, batch: str = "B008") -> None:
    pildb.record_draft_birth_block(
        db, batch, "sd-blocker",
        code="contractor_missing", reason="no identity", lines_count=2,
    )
    pildb.record_draft_birth_block(
        db, batch, "sd-conflict",
        code="contractor_conflict", reason="ambiguous cid",
        client_name="ACME", lines_count=3,
    )
    pildb.record_draft_birth_block(
        db, batch, "sd-conflict-2",
        code="contractor_conflict", reason="second ambiguity",
        client_name="BETA", lines_count=1,
    )
    pildb.record_draft_birth_block(
        db, batch, "sd-resolved",
        code="client_unresolved", reason="was blocked",
    )
    pildb.resolve_draft_birth_block(db, batch, "sd-resolved")


def test_default_list_preserves_mixed_open_blocks(blocks_db):
    _seed_mixed(blocks_db)
    rows = pildb.list_draft_birth_blocks(blocks_db, "B008")
    codes = sorted(r["code"] for r in rows)
    assert codes == ["contractor_conflict", "contractor_conflict", "contractor_missing"]
    assert all("is_advisory" in r for r in rows)
    by_sd = {r["sales_document_id"]: r for r in rows}
    assert by_sd["sd-blocker"]["is_advisory"] is False
    assert by_sd["sd-conflict"]["is_advisory"] is True


def test_include_advisory_false_drops_advisory_keeps_blocker(blocks_db):
    _seed_mixed(blocks_db)
    rows = pildb.list_draft_birth_blocks(
        blocks_db, "B008", include_advisory=False,
    )
    assert [r["code"] for r in rows] == ["contractor_missing"]
    assert rows[0]["sales_document_id"] == "sd-blocker"


def test_filtered_get_does_not_mutate_advisory_row(blocks_db):
    _seed_mixed(blocks_db)
    before = pildb.list_draft_birth_blocks(blocks_db, "B008", include_resolved=True)
    conflict = next(r for r in before if r["sales_document_id"] == "sd-conflict")
    assert conflict["blocked_state"] == "open"

    filtered = pildb.list_draft_birth_blocks(
        blocks_db, "B008", include_advisory=False,
    )
    assert all(r["code"] != "contractor_conflict" for r in filtered)

    after = pildb.list_draft_birth_blocks(blocks_db, "B008", include_resolved=True)
    conflict_after = next(r for r in after if r["sales_document_id"] == "sd-conflict")
    assert conflict_after["blocked_state"] == "open"
    assert conflict_after["code"] == "contractor_conflict"
    assert conflict_after["updated_at"] == conflict["updated_at"]


def test_resolved_semantics_unchanged(blocks_db):
    _seed_mixed(blocks_db)
    open_rows = pildb.list_draft_birth_blocks(blocks_db, "B008")
    assert not any(r["sales_document_id"] == "sd-resolved" for r in open_rows)
    all_rows = pildb.list_draft_birth_blocks(
        blocks_db, "B008", include_resolved=True, include_advisory=False,
    )
    resolved = [r for r in all_rows if r["sales_document_id"] == "sd-resolved"]
    assert len(resolved) == 1
    assert resolved[0]["blocked_state"] == "resolved"
    assert resolved[0]["is_advisory"] is False


def test_unknown_code_remains_visible_when_advisory_excluded(blocks_db):
    pildb.record_draft_birth_block(
        blocks_db, "B008", "sd-unknown",
        code="future_unknown_code", reason="new class",
    )
    pildb.record_draft_birth_block(
        blocks_db, "B008", "sd-conflict",
        code="contractor_conflict", reason="ambiguous",
    )
    rows = pildb.list_draft_birth_blocks(
        blocks_db, "B008", include_advisory=False,
    )
    codes = {r["code"] for r in rows}
    assert "future_unknown_code" in codes
    assert "contractor_conflict" not in codes


def test_multiple_advisory_do_not_change_blocker_count(blocks_db):
    _seed_mixed(blocks_db)
    rows = pildb.list_draft_birth_blocks(
        blocks_db, "B008", include_advisory=False,
    )
    assert len(rows) == 1
    assert rows[0]["code"] == "contractor_missing"


def test_blocks_route_include_advisory_filter(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.dependencies import require_admin
    from app.core.security import require_api_key
    from app.core.config import settings
    import app.api.routes_contractor_projection as rcp

    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(settings, "storage_root", storage)
    monkeypatch.setattr(settings, "environment", "dev")

    db = storage / "proforma_links.db"
    import sqlite3

    with sqlite3.connect(db) as con:
        pildb._ensure_drafts_table(con)
    _seed_mixed(db, "B008-API")
    monkeypatch.setattr(rcp, "_proforma_db_path", lambda: db)

    app.dependency_overrides[require_admin] = lambda: {
        "id": "test-admin", "username": "admin", "role": "admin",
    }
    app.dependency_overrides[require_api_key] = lambda: {"id": "test-admin"}
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            default = client.get(
                "/api/v1/admin/contractor-projection/blocks/B008-API"
            )
            assert default.status_code == 200
            body = default.json()
            assert body["include_advisory"] is True
            assert body["count"] == 3
            assert {b["code"] for b in body["blocks"]} == {
                "contractor_missing", "contractor_conflict",
            }

            filtered = client.get(
                "/api/v1/admin/contractor-projection/blocks/B008-API"
                "?include_advisory=false"
            )
            assert filtered.status_code == 200
            fbody = filtered.json()
            assert fbody["include_advisory"] is False
            assert fbody["count"] == 1
            assert fbody["blocks"][0]["code"] == "contractor_missing"

            # Persistence untouched after filtered GET.
            still = pildb.list_draft_birth_blocks(db, "B008-API")
            assert sum(1 for r in still if r["code"] == "contractor_conflict") == 2
    finally:
        app.dependency_overrides.clear()


def test_ui_wires_creation_panel_to_include_advisory_false():
    html = Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html"
    src = html.read_text(encoding="utf-8")
    assert "include_advisory=false" in src
    assert 'data-testid="proforma-advisory-blocks-panel"' in src
    assert 'data-testid="proforma-blocked-records-panel"' in src
