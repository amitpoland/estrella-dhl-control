"""
test_proforma_adopt_issued.py — unit + source-grep tests for routes_proforma_adopt.py.

Tests:
  Source checks (grep on source):
    1. draft_state = 'adopted_from_audit' is written
    2. status = 'created' is written
    3. posted_at column is written
    4. proforma_draft_events event = 'adopted_from_audit'
    5. Phase 2: wFirma guard present (503 path)
    6. Phase 2: fullnumber_enriched event present

  Adopt logic tests (in-memory SQLite):
    7.  confirmed=False → 400
    8.  confirmed=True, dry_run=True → preview, no DB rows
    9.  Normal insert → adopted row in proforma_drafts with correct columns
   10.  Normal insert → proforma_draft_events row written
   11.  Idempotency: same (batch_id, wfirma_proforma_id) → skipped, no duplicate
   12.  Conflict: same (batch_id, client_name) different ID → 409, zero rows written
   13.  Atomicity: conflict present alongside new entry → 409, still zero rows written
   14.  Missing proforma_issued → 422
   15.  posted_at / posted_by pulled from timeline
   16.  Entries with missing client_name or wfirma_proforma_id are silently skipped

  Enrich logic tests (in-memory SQLite + mocked wfirma_client):
   17.  confirmed=False → 400
   18.  wFirma not configured → 503
   19.  dry_run=True → preview with would_update, no DB writes
   20.  Successful enrich → fullnumber written, event inserted
   21.  Already-set rows are skipped (idempotent)
   22.  Fetch failure → reported in 'failed', other rows still processed
   23.  No blank rows → 200 with empty enriched list
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ── Helpers ───────────────────────────────────────────────────────────────────

_BATCH_ID = "TEST_BATCH_ADOPT_001"

_ISSUED = [
    {"client_name": "Client Alpha", "wfirma_proforma_id": "111", "currency": "EUR", "line_count": 5},
    {"client_name": "Client Beta",  "wfirma_proforma_id": "222", "currency": "USD", "line_count": 3},
]

_TIMELINE = [
    {
        "event":  "proforma_issued",
        "ts":     "2026-05-09T10:00:00+00:00",
        "actor":  "operatorA",
        "detail": {"wfirma_proforma_id": "111", "operator": "operatorA"},
    },
    {
        "event":  "proforma_issued",
        "ts":     "2026-05-09T10:01:00+00:00",
        "actor":  "operatorB",
        "detail": {"wfirma_proforma_id": "222", "operator": "operatorB"},
    },
]

_AUDIT = {
    "proforma_issued": _ISSUED,
    "timeline":        _TIMELINE,
}


def _make_db(tmp: Path) -> Path:
    db = tmp / "proforma_links.db"
    con = sqlite3.connect(str(db))
    con.executescript("""
        CREATE TABLE proforma_drafts (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id                TEXT NOT NULL,
            client_name             TEXT NOT NULL,
            status                  TEXT NOT NULL,
            currency                TEXT NOT NULL DEFAULT '',
            source_lines_json       TEXT NOT NULL DEFAULT '[]',
            wfirma_proforma_id      TEXT,
            notes                   TEXT,
            created_at              TEXT NOT NULL,
            updated_at              TEXT NOT NULL,
            draft_state             TEXT NOT NULL DEFAULT 'posted',
            draft_version           INTEGER NOT NULL DEFAULT 1,
            wfirma_proforma_fullnumber TEXT NOT NULL DEFAULT '',
            buyer_override_json     TEXT NOT NULL DEFAULT '{}',
            ship_to_override_json   TEXT NOT NULL DEFAULT '{}',
            payment_terms_json      TEXT NOT NULL DEFAULT '{}',
            remarks                 TEXT NOT NULL DEFAULT '',
            editable_lines_json     TEXT NOT NULL DEFAULT '[]',
            service_charges_json    TEXT NOT NULL DEFAULT '[]',
            posted_at               TEXT,
            posted_by               TEXT,
            UNIQUE(batch_id, client_name)
        );
        CREATE TABLE proforma_draft_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id    INTEGER NOT NULL,
            event       TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            operator    TEXT NOT NULL DEFAULT '',
            occurred_at TEXT NOT NULL
        );
    """)
    con.commit()
    con.close()
    return db


def _make_audit(tmp: Path, data: Dict[str, Any] | None = None) -> Path:
    batch_dir = tmp / "outputs" / _BATCH_ID
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(
        json.dumps(data if data is not None else _AUDIT),
        encoding="utf-8",
    )
    return audit_path


def _client_with_mocks(tmp: Path):
    """Return a TestClient with storage_root patched to tmp."""
    from service.app.main import app  # import here to avoid circular at module level

    with patch("service.app.api.routes_proforma_adopt.settings") as mock_settings:
        mock_settings.storage_root = tmp
        client = TestClient(app, raise_server_exceptions=True)
        yield client, tmp


def _make_env(tmp: Path):
    """Context manager: set up audit + db, yield (client, db_path, con)."""
    import contextlib

    @contextlib.contextmanager
    def _inner():
        _make_audit(tmp)
        db = _make_db(tmp)
        with patch("service.app.api.routes_proforma_adopt.settings") as ms:
            ms.storage_root = tmp
            from fastapi.testclient import TestClient
            from service.app.api.routes_proforma_adopt import router
            from fastapi import FastAPI
            from service.app.core.security import require_api_key

            mini = FastAPI()
            mini.include_router(router)
            # disable auth
            mini.dependency_overrides[require_api_key] = lambda: None
            client = TestClient(mini, raise_server_exceptions=False)
            yield client, db

    return _inner()


# ── Source-grep tests ─────────────────────────────────────────────────────────

_SRC_FILE = (
    Path(__file__).parents[1]
    / "app" / "api" / "routes_proforma_adopt.py"
)


def _src() -> str:
    return _SRC_FILE.read_text(encoding="utf-8")


class TestSourceChecks:
    def test_module_file_exists(self):
        assert _SRC_FILE.exists()

    def test_draft_state_adopted_from_audit(self):
        assert "'adopted_from_audit'" in _src()

    def test_status_created(self):
        assert "'created'" in _src()

    def test_posted_at_column_written(self):
        assert "posted_at" in _src()

    def test_event_adopted_from_audit(self):
        src = _src()
        assert "'adopted_from_audit'" in src
        assert "proforma_draft_events" in src

    def test_phase2_wfirma_guard_503_path(self):
        src = _src()
        assert "wfirma_not_configured" in src
        assert "503" in src

    def test_phase2_fullnumber_enriched_event(self):
        src = _src()
        assert "'fullnumber_enriched'" in src


# ── Logic tests ───────────────────────────────────────────────────────────────

class TestAdoptLogic:
    """Logic tests using a minimal FastAPI app + in-memory temp dir."""

    @pytest.fixture()
    def env(self, tmp_path):
        _make_audit(tmp_path)
        db = _make_db(tmp_path)
        with patch("service.app.api.routes_proforma_adopt.settings") as ms:
            ms.storage_root = tmp_path
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from service.app.api.routes_proforma_adopt import router
            from service.app.core.security import require_api_key

            mini = FastAPI()
            mini.include_router(router)
            mini.dependency_overrides[require_api_key] = lambda: None
            client = TestClient(mini, raise_server_exceptions=False)
            yield client, db

    def test_confirmed_false_returns_400(self, env):
        client, _ = env
        r = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                        json={"confirmed": False})
        assert r.status_code == 400

    def test_dry_run_no_db_writes(self, env):
        client, db = env
        r = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                        json={"confirmed": True, "dry_run": True})
        assert r.status_code == 200
        body = r.json()
        assert body["dry_run"] is True
        assert len(body["adopted"]) == 2
        assert all(e["action"] == "would_insert" for e in body["adopted"])
        # no rows in DB
        con = sqlite3.connect(str(db))
        count = con.execute("SELECT COUNT(*) FROM proforma_drafts").fetchone()[0]
        con.close()
        assert count == 0

    def test_normal_insert_creates_rows(self, env):
        client, db = env
        r = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                        json={"confirmed": True, "operator": "tester"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["adopted"]) == 2
        assert body["dry_run"] is False

        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=?", (_BATCH_ID,)
        ).fetchall()
        assert len(rows) == 2

        for row in rows:
            assert row["status"] == "created"
            assert row["draft_state"] == "adopted_from_audit"
            assert row["draft_version"] == 1
        con.close()

    def test_normal_insert_writes_event(self, env):
        client, db = env
        r = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                        json={"confirmed": True, "operator": "tester"})
        assert r.status_code == 200

        con = sqlite3.connect(str(db))
        events = con.execute("SELECT * FROM proforma_draft_events").fetchall()
        con.close()
        assert len(events) == 2
        for ev in events:
            assert ev[2] == "adopted_from_audit"  # event column

    def test_idempotency_skips_existing(self, env):
        client, db = env
        # first call
        r1 = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                         json={"confirmed": True})
        assert r1.status_code == 200
        # second call — same IDs
        r2 = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                         json={"confirmed": True})
        assert r2.status_code == 200
        body = r2.json()
        assert len(body["adopted"]) == 0
        assert len(body["skipped"]) == 2
        assert all(s["reason"] == "already_adopted" for s in body["skipped"])
        # still only 2 rows
        con = sqlite3.connect(str(db))
        count = con.execute("SELECT COUNT(*) FROM proforma_drafts").fetchone()[0]
        con.close()
        assert count == 2

    def test_conflict_returns_409_no_writes(self, env):
        client, db = env
        # pre-seed a row for Client Alpha with a DIFFERENT ID
        con = sqlite3.connect(str(db))
        con.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, created_at, updated_at) "
            "VALUES (?, 'Client Alpha', 'created', 'now', 'now')",
            (_BATCH_ID,),
        )
        con.commit()
        con.close()

        r = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                        json={"confirmed": True})
        assert r.status_code == 409

        # Client Beta must NOT have been inserted
        con = sqlite3.connect(str(db))
        count = con.execute("SELECT COUNT(*) FROM proforma_drafts").fetchone()[0]
        con.close()
        assert count == 1  # only the pre-seeded row

    def test_atomicity_conflict_blocks_all_inserts(self, env):
        client, db = env
        # pre-seed conflict only for Client Beta
        con = sqlite3.connect(str(db))
        con.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, created_at, updated_at) "
            "VALUES (?, 'Client Beta', 'created', 'now', 'now')",
            (_BATCH_ID,),
        )
        con.commit()
        con.close()

        r = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                        json={"confirmed": True})
        assert r.status_code == 409

        con = sqlite3.connect(str(db))
        count = con.execute("SELECT COUNT(*) FROM proforma_drafts").fetchone()[0]
        con.close()
        assert count == 1  # only the pre-seeded row — Client Alpha was NOT inserted

    def test_empty_proforma_issued_returns_422(self, tmp_path):
        _make_audit(tmp_path, {"proforma_issued": [], "timeline": []})
        _make_db(tmp_path)
        with patch("service.app.api.routes_proforma_adopt.settings") as ms:
            ms.storage_root = tmp_path
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from service.app.api.routes_proforma_adopt import router
            from service.app.core.security import require_api_key

            mini = FastAPI()
            mini.include_router(router)
            mini.dependency_overrides[require_api_key] = lambda: None
            client = TestClient(mini, raise_server_exceptions=False)
            r = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                            json={"confirmed": True})
            assert r.status_code == 422

    def test_posted_at_from_timeline(self, env):
        client, db = env
        r = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                        json={"confirmed": True, "operator": "tester"})
        assert r.status_code == 200

        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT posted_at, posted_by FROM proforma_drafts "
            "WHERE batch_id=? AND client_name='Client Alpha'",
            (_BATCH_ID,),
        ).fetchone()
        con.close()
        assert row["posted_at"] == "2026-05-09T10:00:00+00:00"
        assert row["posted_by"] == "operatorA"

    def test_entries_missing_fields_skipped(self, tmp_path):
        bad_audit = {
            "proforma_issued": [
                {"client_name": "", "wfirma_proforma_id": "999", "currency": "EUR", "line_count": 1},
                {"client_name": "Client X",  "wfirma_proforma_id": "",  "currency": "EUR", "line_count": 1},
                {"client_name": "Client OK", "wfirma_proforma_id": "333", "currency": "EUR", "line_count": 2},
            ],
            "timeline": [],
        }
        _make_audit(tmp_path, bad_audit)
        _make_db(tmp_path)
        with patch("service.app.api.routes_proforma_adopt.settings") as ms:
            ms.storage_root = tmp_path
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from service.app.api.routes_proforma_adopt import router
            from service.app.core.security import require_api_key

            mini = FastAPI()
            mini.include_router(router)
            mini.dependency_overrides[require_api_key] = lambda: None
            client = TestClient(mini, raise_server_exceptions=False)
            r = client.post(f"/api/v1/proforma/adopt-issued/{_BATCH_ID}",
                            json={"confirmed": True})
            assert r.status_code == 200
            body = r.json()
            assert len(body["adopted"]) == 1
            assert body["adopted"][0]["client_name"] == "Client OK"


# ── Phase 2: enrich-fullnumber tests ─────────────────────────────────────────

_ENRICH_BATCH = "TEST_BATCH_ENRICH_001"

# Minimal XML wFirma returns for a proforma fetch
_XML_ALPHA = """<?xml version="1.0"?>
<api><status><code>OK</code></status>
<invoices><invoice><id>111</id><fullnumber>PRO 1/05/2026</fullnumber></invoice></invoices>
</api>"""

_XML_BETA = """<?xml version="1.0"?>
<api><status><code>OK</code></status>
<invoices><invoice><id>222</id><fullnumber>PRO 2/05/2026</fullnumber></invoice></invoices>
</api>"""


def _make_db_with_adopted_rows(tmp: Path, batch_id: str = _ENRICH_BATCH) -> Path:
    """Create proforma_links.db with two adopted rows (fullnumber blank)."""
    db = tmp / "proforma_links.db"
    con = sqlite3.connect(str(db))
    con.executescript("""
        CREATE TABLE proforma_drafts (
            id                         INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id                   TEXT NOT NULL,
            client_name                TEXT NOT NULL,
            status                     TEXT NOT NULL,
            currency                   TEXT NOT NULL DEFAULT '',
            source_lines_json          TEXT NOT NULL DEFAULT '[]',
            wfirma_proforma_id         TEXT,
            notes                      TEXT,
            created_at                 TEXT NOT NULL,
            updated_at                 TEXT NOT NULL,
            draft_state                TEXT NOT NULL DEFAULT 'adopted_from_audit',
            draft_version              INTEGER NOT NULL DEFAULT 1,
            wfirma_proforma_fullnumber TEXT NOT NULL DEFAULT '',
            buyer_override_json        TEXT NOT NULL DEFAULT '{}',
            ship_to_override_json      TEXT NOT NULL DEFAULT '{}',
            payment_terms_json         TEXT NOT NULL DEFAULT '{}',
            remarks                    TEXT NOT NULL DEFAULT '',
            editable_lines_json        TEXT NOT NULL DEFAULT '[]',
            service_charges_json       TEXT NOT NULL DEFAULT '[]',
            posted_at                  TEXT,
            posted_by                  TEXT,
            UNIQUE(batch_id, client_name)
        );
        CREATE TABLE proforma_draft_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id    INTEGER NOT NULL,
            event       TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            operator    TEXT NOT NULL DEFAULT '',
            occurred_at TEXT NOT NULL
        );
    """)
    con.execute(
        "INSERT INTO proforma_drafts (batch_id, client_name, status, wfirma_proforma_id, "
        "wfirma_proforma_fullnumber, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (batch_id, "Client Alpha", "created", "111", "", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    con.execute(
        "INSERT INTO proforma_drafts (batch_id, client_name, status, wfirma_proforma_id, "
        "wfirma_proforma_fullnumber, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (batch_id, "Client Beta", "created", "222", "", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    con.commit()
    con.close()
    return db


def _enrich_env(tmp: Path, wfirma_configured: bool = True):
    """Context manager: set up DB with blank fullnumbers, patch settings + wfirma_client."""
    import contextlib

    @contextlib.contextmanager
    def _inner():
        db = _make_db_with_adopted_rows(tmp)

        def _fake_fetch(invoice_id: str) -> str:
            mapping = {"111": _XML_ALPHA, "222": _XML_BETA}
            if invoice_id in mapping:
                return mapping[invoice_id]
            raise RuntimeError(f"not found: {invoice_id}")

        with patch("service.app.api.routes_proforma_adopt.settings") as ms, \
             patch("service.app.api.routes_proforma_adopt._wfirma.fetch_invoice_xml",
                   side_effect=_fake_fetch):
            ms.storage_root = tmp
            ms.wfirma_access_key = "key" if wfirma_configured else ""
            ms.wfirma_secret_key = "sec" if wfirma_configured else ""
            ms.wfirma_app_key    = "app" if wfirma_configured else ""

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from service.app.api.routes_proforma_adopt import router
            from service.app.core.security import require_api_key

            mini = FastAPI()
            mini.include_router(router)
            mini.dependency_overrides[require_api_key] = lambda: None
            client = TestClient(mini, raise_server_exceptions=False)
            yield client, db

    return _inner()


class TestEnrichFullnumber:
    """Phase 2 enrichment endpoint tests."""

    @pytest.fixture()
    def env(self, tmp_path):
        with _enrich_env(tmp_path) as ctx:
            yield ctx

    @pytest.fixture()
    def env_unconfigured(self, tmp_path):
        with _enrich_env(tmp_path, wfirma_configured=False) as ctx:
            yield ctx

    def test_confirmed_false_returns_400(self, env):
        client, _ = env
        r = client.post(f"/api/v1/proforma/enrich-fullnumber/{_ENRICH_BATCH}",
                        json={"confirmed": False})
        assert r.status_code == 400

    def test_wfirma_not_configured_returns_503(self, env_unconfigured):
        client, _ = env_unconfigured
        r = client.post(f"/api/v1/proforma/enrich-fullnumber/{_ENRICH_BATCH}",
                        json={"confirmed": True})
        assert r.status_code == 503
        body = r.json()
        detail = body.get("detail", body)
        assert "wfirma_not_configured" in str(detail)

    def test_dry_run_no_db_writes(self, env):
        client, db = env
        r = client.post(f"/api/v1/proforma/enrich-fullnumber/{_ENRICH_BATCH}",
                        json={"confirmed": True, "dry_run": True})
        assert r.status_code == 200
        body = r.json()
        assert body["dry_run"] is True
        assert len(body["enriched"]) == 2
        assert all(e["action"] == "would_update" for e in body["enriched"])
        assert len(body["failed"]) == 0
        # DB must still have blank fullnumbers
        con = sqlite3.connect(str(db))
        blanks = con.execute(
            "SELECT COUNT(*) FROM proforma_drafts WHERE wfirma_proforma_fullnumber = ''"
        ).fetchone()[0]
        con.close()
        assert blanks == 2

    def test_successful_enrich_writes_fullnumber(self, env):
        client, db = env
        r = client.post(f"/api/v1/proforma/enrich-fullnumber/{_ENRICH_BATCH}",
                        json={"confirmed": True, "operator": "tester"})
        assert r.status_code == 200
        body = r.json()
        assert body["dry_run"] is False
        assert len(body["enriched"]) == 2
        assert len(body["failed"]) == 0
        assert all(e["action"] == "updated" for e in body["enriched"])

        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT client_name, wfirma_proforma_fullnumber FROM proforma_drafts "
            "WHERE batch_id=? ORDER BY client_name",
            (_ENRICH_BATCH,),
        ).fetchall()
        con.close()
        by_name = {r["client_name"]: r["wfirma_proforma_fullnumber"] for r in rows}
        assert by_name["Client Alpha"] == "PRO 1/05/2026"
        assert by_name["Client Beta"]  == "PRO 2/05/2026"

    def test_successful_enrich_writes_event(self, env):
        client, db = env
        r = client.post(f"/api/v1/proforma/enrich-fullnumber/{_ENRICH_BATCH}",
                        json={"confirmed": True, "operator": "tester"})
        assert r.status_code == 200

        con = sqlite3.connect(str(db))
        events = con.execute(
            "SELECT event, detail_json, operator FROM proforma_draft_events"
        ).fetchall()
        con.close()
        assert len(events) == 2
        for ev in events:
            assert ev[0] == "fullnumber_enriched"
            assert ev[2] == "tester"
            detail = json.loads(ev[1])
            assert "wfirma_proforma_fullnumber" in detail

    def test_already_set_rows_are_skipped(self, tmp_path):
        """Rows where fullnumber is already populated must not be overwritten."""
        db = _make_db_with_adopted_rows(tmp_path)
        # Pre-populate Alpha's fullnumber
        con = sqlite3.connect(str(db))
        con.execute(
            "UPDATE proforma_drafts SET wfirma_proforma_fullnumber='PRO EXISTING' "
            "WHERE client_name='Client Alpha'"
        )
        con.commit()
        con.close()

        def _fake_fetch(invoice_id: str) -> str:
            return _XML_BETA if invoice_id == "222" else _XML_ALPHA

        with patch("service.app.api.routes_proforma_adopt.settings") as ms, \
             patch("service.app.api.routes_proforma_adopt._wfirma.fetch_invoice_xml",
                   side_effect=_fake_fetch):
            ms.storage_root = tmp_path
            ms.wfirma_access_key = "k"
            ms.wfirma_secret_key = "s"
            ms.wfirma_app_key    = "a"

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from service.app.api.routes_proforma_adopt import router
            from service.app.core.security import require_api_key

            mini = FastAPI()
            mini.include_router(router)
            mini.dependency_overrides[require_api_key] = lambda: None
            client = TestClient(mini, raise_server_exceptions=False)

            r = client.post(f"/api/v1/proforma/enrich-fullnumber/{_ENRICH_BATCH}",
                            json={"confirmed": True})
            assert r.status_code == 200
            body = r.json()
            # Only Beta should be enriched — Alpha was already set
            assert len(body["enriched"]) == 1
            assert body["enriched"][0]["client_name"] == "Client Beta"

        # Alpha must still have the original value
        con = sqlite3.connect(str(db))
        val = con.execute(
            "SELECT wfirma_proforma_fullnumber FROM proforma_drafts WHERE client_name='Client Alpha'"
        ).fetchone()[0]
        con.close()
        assert val == "PRO EXISTING"

    def test_fetch_failure_reported_others_proceed(self, tmp_path):
        """If one row's wFirma fetch fails, it goes to 'failed'; others still write."""
        db = _make_db_with_adopted_rows(tmp_path)

        def _failing_fetch(invoice_id: str) -> str:
            if invoice_id == "111":
                raise RuntimeError("network timeout")
            return _XML_BETA  # Beta succeeds

        with patch("service.app.api.routes_proforma_adopt.settings") as ms, \
             patch("service.app.api.routes_proforma_adopt._wfirma.fetch_invoice_xml",
                   side_effect=_failing_fetch):
            ms.storage_root = tmp_path
            ms.wfirma_access_key = "k"
            ms.wfirma_secret_key = "s"
            ms.wfirma_app_key    = "a"

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from service.app.api.routes_proforma_adopt import router
            from service.app.core.security import require_api_key

            mini = FastAPI()
            mini.include_router(router)
            mini.dependency_overrides[require_api_key] = lambda: None
            client = TestClient(mini, raise_server_exceptions=False)

            r = client.post(f"/api/v1/proforma/enrich-fullnumber/{_ENRICH_BATCH}",
                            json={"confirmed": True})
            assert r.status_code == 200
            body = r.json()
            assert len(body["failed"])   == 1
            assert len(body["enriched"]) == 1
            assert body["failed"][0]["client_name"]   == "Client Alpha"
            assert body["enriched"][0]["client_name"] == "Client Beta"

        # Beta must be written, Alpha still blank
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        rows = {r["client_name"]: r["wfirma_proforma_fullnumber"]
                for r in con.execute(
                    "SELECT client_name, wfirma_proforma_fullnumber FROM proforma_drafts"
                ).fetchall()}
        con.close()
        assert rows["Client Beta"]  == "PRO 2/05/2026"
        assert rows["Client Alpha"] == ""

    def test_no_blank_rows_returns_empty(self, tmp_path):
        """If all rows already have fullnumbers, returns empty enriched list."""
        db = _make_db_with_adopted_rows(tmp_path)
        con = sqlite3.connect(str(db))
        con.execute("UPDATE proforma_drafts SET wfirma_proforma_fullnumber='PRO X'")
        con.commit()
        con.close()

        with patch("service.app.api.routes_proforma_adopt.settings") as ms, \
             patch("service.app.api.routes_proforma_adopt._wfirma.fetch_invoice_xml") as _mf:
            ms.storage_root = tmp_path
            ms.wfirma_access_key = "k"
            ms.wfirma_secret_key = "s"
            ms.wfirma_app_key    = "a"

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from service.app.api.routes_proforma_adopt import router
            from service.app.core.security import require_api_key

            mini = FastAPI()
            mini.include_router(router)
            mini.dependency_overrides[require_api_key] = lambda: None
            client = TestClient(mini, raise_server_exceptions=False)

            r = client.post(f"/api/v1/proforma/enrich-fullnumber/{_ENRICH_BATCH}",
                            json={"confirmed": True})
            assert r.status_code == 200
            body = r.json()
            assert body["enriched"] == []
            _mf.assert_not_called()  # no wFirma fetches needed
