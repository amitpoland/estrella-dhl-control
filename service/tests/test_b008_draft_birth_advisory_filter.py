"""B-008 — draft-birth-block read-side advisory filter.

Pins the orthogonal severity dimension on list_draft_birth_blocks /
GET .../contractor-projection/blocks/{batch_id}:

  open/resolved  = lifecycle (unchanged)
  advisory/block = operational effect (new read filter)

Defaults stay backward-compatible. Filtering never mutates rows.
Unknown codes fail closed (remain visible under include_advisory=false).

Run: python -m pytest tests/test_b008_draft_birth_advisory_filter.py -q
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb


@pytest.fixture()
def storage(tmp_path: Path) -> Path:
    pildb.init_db(tmp_path / "proforma_links.db")
    with patch.object(settings, "storage_root", tmp_path):
        yield tmp_path


@pytest.fixture()
def db(storage: Path) -> Path:
    return storage / "proforma_links.db"


def _seed_mixed(db: Path, batch: str = "B-008-MIX") -> str:
    """Open advisory + open blocker + resolved blocker. Returns batch_id."""
    pildb.record_draft_birth_block(
        db, batch, "sd-conflict",
        code="contractor_conflict",
        reason="Same client_name maps to two contractor ids.",
        client_name="ACME", lines_count=2,
    )
    pildb.record_draft_birth_block(
        db, batch, "sd-missing",
        code="contractor_missing",
        reason="No client name and no contractor.",
        client_name="", lines_count=1,
    )
    pildb.record_draft_birth_block(
        db, batch, "sd-resolved",
        code="client_unresolved",
        reason="Contractor id present but no CM match.",
        client_contractor_id="999", client_name="", lines_count=1,
    )
    pildb.resolve_draft_birth_block(db, batch, "sd-resolved")
    return batch


class TestClassificationAuthority:
    def test_only_contractor_conflict_is_advisory(self):
        assert pildb.is_draft_birth_block_advisory("contractor_conflict") is True
        assert pildb.is_draft_birth_block_advisory("contractor_missing") is False
        assert pildb.is_draft_birth_block_advisory("client_unresolved") is False

    def test_unknown_code_fails_closed_not_advisory(self):
        assert pildb.is_draft_birth_block_advisory("future_mystery_code") is False
        assert pildb.is_draft_birth_block_advisory("") is False
        assert "contractor_conflict" in pildb.DRAFT_BIRTH_BLOCK_ADVISORY_CODES


class TestListFilter:
    def test_default_open_list_mixes_advisory_and_blocker(self, db):
        b = _seed_mixed(db)
        rows = pildb.list_draft_birth_blocks(db, b)
        codes = sorted(r["code"] for r in rows)
        assert codes == ["contractor_conflict", "contractor_missing"]
        by_code = {r["code"]: r for r in rows}
        assert by_code["contractor_conflict"]["is_advisory"] is True
        assert by_code["contractor_missing"]["is_advisory"] is False

    def test_include_advisory_false_hides_advisory_only(self, db):
        b = _seed_mixed(db)
        rows = pildb.list_draft_birth_blocks(db, b, include_advisory=False)
        assert [r["code"] for r in rows] == ["contractor_missing"]
        assert rows[0]["is_advisory"] is False

    def test_genuine_blocker_codes_remain(self, db):
        b = "B-008-BLOCKERS"
        for sid, code in (
            ("a", "contractor_missing"),
            ("b", "client_unresolved"),
            ("c", "contractor_conflict"),
        ):
            pildb.record_draft_birth_block(
                db, b, sid, code=code, reason=f"r-{code}", lines_count=1,
            )
        codes = {r["code"] for r in pildb.list_draft_birth_blocks(
            db, b, include_advisory=False)}
        assert codes == {"contractor_missing", "client_unresolved"}

    def test_resolved_semantics_unchanged(self, db):
        b = _seed_mixed(db)
        open_only = pildb.list_draft_birth_blocks(db, b)
        assert all(r["blocked_state"] == "open" for r in open_only)
        assert "sd-resolved" not in {r["sales_document_id"] for r in open_only}

        with_resolved = pildb.list_draft_birth_blocks(db, b, include_resolved=True)
        assert len(with_resolved) == 3
        resolved = [r for r in with_resolved if r["sales_document_id"] == "sd-resolved"]
        assert len(resolved) == 1
        assert resolved[0]["blocked_state"] == "resolved"
        assert resolved[0]["code"] == "client_unresolved"

    def test_filter_composes_with_include_resolved(self, db):
        b = _seed_mixed(db)
        rows = pildb.list_draft_birth_blocks(
            db, b, include_resolved=True, include_advisory=False,
        )
        codes = sorted(r["code"] for r in rows)
        # advisory conflict omitted; open missing + resolved unresolved remain
        assert codes == ["client_unresolved", "contractor_missing"]
        states = {r["code"]: r["blocked_state"] for r in rows}
        assert states["contractor_missing"] == "open"
        assert states["client_unresolved"] == "resolved"

    def test_filtered_get_does_not_mutate_db(self, db):
        b = _seed_mixed(db)
        before = pildb.list_draft_birth_blocks(db, b, include_resolved=True)
        before_states = {
            (r["sales_document_id"], r["code"], r["blocked_state"]) for r in before
        }
        assert len(before_states) == 3

        _ = pildb.list_draft_birth_blocks(db, b, include_advisory=False)

        after = pildb.list_draft_birth_blocks(db, b, include_resolved=True)
        after_states = {
            (r["sales_document_id"], r["code"], r["blocked_state"]) for r in after
        }
        assert after_states == before_states
        conflict = next(r for r in after if r["code"] == "contractor_conflict")
        assert conflict["blocked_state"] == "open"

        with sqlite3.connect(str(db)) as con:
            n_open_conflict = con.execute(
                "SELECT COUNT(*) FROM proforma_draft_birth_blocks "
                "WHERE batch_id=? AND code='contractor_conflict' "
                "AND blocked_state='open'",
                (b,),
            ).fetchone()[0]
        assert n_open_conflict == 1

    def test_unknown_code_stays_visible_when_advisory_filtered(self, db):
        b = "B-008-UNKNOWN"
        pildb.record_draft_birth_block(
            db, b, "sd-x",
            code="legacy_or_future_code",
            reason="Unknown to classifier — must remain actionable.",
            lines_count=1,
        )
        pildb.record_draft_birth_block(
            db, b, "sd-adv",
            code="contractor_conflict",
            reason="advisory",
            lines_count=1,
        )
        rows = pildb.list_draft_birth_blocks(db, b, include_advisory=False)
        codes = {r["code"] for r in rows}
        assert "legacy_or_future_code" in codes
        assert "contractor_conflict" not in codes
        assert rows[0]["is_advisory"] is False


class TestApiProjection:
    @pytest.fixture()
    def client(self, storage):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.security import require_api_key

        app.dependency_overrides[require_api_key] = lambda: {"id": "op"}
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
        app.dependency_overrides.clear()

    def test_default_get_includes_advisory(self, client, db):
        b = _seed_mixed(db)
        r = client.get(f"/api/v1/admin/contractor-projection/blocks/{b}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("include_advisory") is True
        codes = sorted(x["code"] for x in body["blocks"])
        assert codes == ["contractor_conflict", "contractor_missing"]
        conflict = next(x for x in body["blocks"] if x["code"] == "contractor_conflict")
        assert conflict["is_advisory"] is True

    def test_include_advisory_false_omits_advisory_only(self, client, db):
        b = _seed_mixed(db)
        r = client.get(
            f"/api/v1/admin/contractor-projection/blocks/{b}"
            f"?include_advisory=false",
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("include_advisory") is False
        assert body["count"] == 1
        assert body["blocks"][0]["code"] == "contractor_missing"
        assert body["blocks"][0]["is_advisory"] is False

        # Row still open in store after filtered GET
        still = pildb.list_draft_birth_blocks(db, b)
        assert any(x["code"] == "contractor_conflict" for x in still)

    def test_compose_include_resolved_and_advisory(self, client, db):
        b = _seed_mixed(db)
        r = client.get(
            f"/api/v1/admin/contractor-projection/blocks/{b}"
            f"?include_resolved=true&include_advisory=false",
        )
        assert r.status_code == 200, r.text
        codes = sorted(x["code"] for x in r.json()["blocks"])
        assert codes == ["client_unresolved", "contractor_missing"]


class TestUiCreationBlockerWiring:
    def test_creation_panel_fetches_include_advisory_false(self):
        src = Path("app/static/shipment-detail.html").read_text(encoding="utf-8")
        assert "include_advisory=false" in src
        assert 'data-testid="proforma-blocked-records-panel"' in src
        assert 'data-testid="proforma-advisory-birth-blocks-panel"' in src
        assert "birthAdvisory" in src
