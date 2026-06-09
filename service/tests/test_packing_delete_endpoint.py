"""
test_packing_delete_endpoint.py

Tests for the two new packing endpoints:
  GET  /api/v1/packing/{batch_id}/document/{document_id}/download
  DELETE /api/v1/packing/{batch_id}/document/{document_id}

Covers:
 - delete_packing_document_and_lines() DB function: atomic delete, KeyError on missing
 - Download endpoint: 404 on unknown doc, 404 on wrong batch, FileResponse on valid
 - Delete endpoint: 404 on unknown doc, 404 on wrong batch, 200 on success (disk + DB)
 - Delete SALES guard: 409 when active proforma draft exists
 - Delete SALES guard: passes when all drafts are cancelled/superseded
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services import packing_db as pdb
from app.core.config import settings


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    return tmp_path


@pytest.fixture()
def client(tmp_db):
    from app.main import app
    from app.auth.dependencies import get_current_user
    from fastapi.testclient import TestClient
    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@t"}
    with patch.object(settings, "storage_root", tmp_db):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    app.dependency_overrides.clear()


def _auth():
    return {}  # auth bypassed via dependency_override


def _insert_doc(tmp_db, batch_id: str, source_path: str = "", batch_id_field: str = None) -> str:
    """Insert a minimal packing document and return its ID."""
    doc_id = pdb.upsert_packing_document(
        batch_id=batch_id_field or batch_id,
        source_file_path=source_path,
        extraction_status="extracted",
    )
    return doc_id


def _insert_lines(batch_id: str, doc_id: str, count: int = 3):
    """Insert N dummy packing lines for a document."""
    import sqlite3, uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(pdb._db_path)) as con:
        for i in range(count):
            con.execute(
                """INSERT INTO packing_lines
                       (id, packing_document_id, batch_id, design_no, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (str(uuid.uuid4()), doc_id, batch_id, f"DESIGN-{i}", now, now),
            )


# ══════════════════════════════════════════════════════════════════════════════
# 1. packing_db.delete_packing_document_and_lines()
# ══════════════════════════════════════════════════════════════════════════════

class TestDeletePackingDocumentAndLines:
    def test_deletes_lines_and_document(self, tmp_db):
        doc_id = _insert_doc(tmp_db, "BATCH-DEL-01")
        _insert_lines("BATCH-DEL-01", doc_id, count=5)

        result = pdb.delete_packing_document_and_lines(doc_id)
        assert result["doc_id"] == doc_id
        assert result["deleted_lines"] == 5

        # Document gone
        assert pdb.get_packing_document(doc_id) is None
        # Lines gone
        remaining = pdb.get_packing_lines_for_document(doc_id)
        assert remaining == []

    def test_returns_source_file_path(self, tmp_db):
        doc_id = _insert_doc(tmp_db, "BATCH-DEL-02", source_path="/storage/some.xlsx")
        result = pdb.delete_packing_document_and_lines(doc_id)
        assert result["source_file_path"] == "/storage/some.xlsx"

    def test_raises_key_error_for_unknown_doc(self, tmp_db):
        with pytest.raises(KeyError):
            pdb.delete_packing_document_and_lines("nonexistent-uuid")

    def test_zero_lines_still_deletes_document(self, tmp_db):
        doc_id = _insert_doc(tmp_db, "BATCH-DEL-03")
        result = pdb.delete_packing_document_and_lines(doc_id)
        assert result["deleted_lines"] == 0
        assert pdb.get_packing_document(doc_id) is None

    def test_idempotent_raise_on_second_call(self, tmp_db):
        doc_id = _insert_doc(tmp_db, "BATCH-DEL-04")
        pdb.delete_packing_document_and_lines(doc_id)
        with pytest.raises(KeyError):
            pdb.delete_packing_document_and_lines(doc_id)


# ══════════════════════════════════════════════════════════════════════════════
# 2. GET /{batch_id}/document/{document_id}/download
# ══════════════════════════════════════════════════════════════════════════════

class TestDownloadPackingDocument:
    def test_404_unknown_doc(self, client, tmp_db):
        r = client.get(
            "/api/v1/packing/BATCH-DL-01/document/does-not-exist/download",
            headers=_auth(),
        )
        assert r.status_code == 404

    def test_404_wrong_batch(self, client, tmp_db):
        doc_id = _insert_doc(tmp_db, "BATCH-DL-02")
        r = client.get(
            f"/api/v1/packing/WRONG-BATCH/document/{doc_id}/download",
            headers=_auth(),
        )
        assert r.status_code == 404

    def test_404_file_missing_on_disk(self, client, tmp_db):
        doc_id = _insert_doc(tmp_db, "BATCH-DL-03", source_path="/nonexistent/file.xlsx")
        r = client.get(
            f"/api/v1/packing/BATCH-DL-03/document/{doc_id}/download",
            headers=_auth(),
        )
        assert r.status_code == 404

    def test_200_returns_file(self, client, tmp_db):
        """Happy path: file exists on disk → 200 with file content."""
        disk_file = tmp_db / "test_pack.xlsx"
        disk_file.write_bytes(b"fake-xlsx-content")
        doc_id = _insert_doc(tmp_db, "BATCH-DL-04", source_path=str(disk_file))
        r = client.get(
            f"/api/v1/packing/BATCH-DL-04/document/{doc_id}/download",
            headers=_auth(),
        )
        assert r.status_code == 200
        assert r.content == b"fake-xlsx-content"
        # Cache-Control must be no-store (Lesson G compliance)
        assert "no-store" in r.headers.get("cache-control", "").lower()

    def test_endpoint_has_auth_dependency(self):
        """Auth guard is declared at the router level (source-grep check)."""
        import app.api.routes_packing as rp
        with open(rp.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
            src = f.read()
        # Both endpoints must use dependencies=[_auth]
        assert src.count("dependencies=[_auth]") >= 6  # existing + 2 new


# ══════════════════════════════════════════════════════════════════════════════
# 3. DELETE /{batch_id}/document/{document_id}
# ══════════════════════════════════════════════════════════════════════════════

class TestDeletePackingDocumentEndpoint:
    def test_404_unknown_doc(self, client, tmp_db):
        r = client.delete(
            "/api/v1/packing/BATCH-RM-01/document/does-not-exist",
            headers=_auth(),
        )
        assert r.status_code == 404

    def test_404_wrong_batch(self, client, tmp_db):
        doc_id = _insert_doc(tmp_db, "BATCH-RM-02")
        r = client.delete(
            f"/api/v1/packing/WRONG-BATCH/document/{doc_id}",
            headers=_auth(),
        )
        assert r.status_code == 404

    def test_200_deletes_purchase_doc_no_disk_file(self, client, tmp_db):
        """PURCHASE doc with no disk file: 200, lines deleted, disk_deleted=False."""
        doc_id = _insert_doc(tmp_db, "BATCH-RM-03", source_path="")
        _insert_lines("BATCH-RM-03", doc_id, count=4)
        r = client.delete(
            f"/api/v1/packing/BATCH-RM-03/document/{doc_id}",
            headers={**_auth(), "X-Operator": "test_op"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["deleted_lines"] == 4
        assert body["disk_deleted"] is False
        # Verify DB is empty
        assert pdb.get_packing_document(doc_id) is None

    def test_200_deletes_disk_file(self, client, tmp_db):
        """Disk file exists: should be deleted and disk_deleted=True."""
        disk_file = tmp_db / "source" / "packing" / "pack.xlsx"
        disk_file.parent.mkdir(parents=True)
        disk_file.write_bytes(b"content")
        doc_id = _insert_doc(tmp_db, "BATCH-RM-04", source_path=str(disk_file))
        r = client.delete(
            f"/api/v1/packing/BATCH-RM-04/document/{doc_id}",
            headers=_auth(),
        )
        assert r.status_code == 200
        assert r.json()["disk_deleted"] is True
        assert not disk_file.exists()

    def test_endpoint_has_auth_dependency(self):
        """Auth guard declared via source-grep (see download test for full coverage)."""
        import app.api.routes_packing as rp
        with open(rp.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
            src = f.read()
        assert "@router.delete" in src
        assert "dependencies=[_auth]" in src

    def test_409_sales_blocked_by_active_draft(self, client, tmp_db):
        """SALES file delete blocked when active proforma draft exists."""
        # SALES path contains '/source/sales/'
        sales_path = "/storage/outputs/BATCH-RM-06/source/sales/sales.xlsx"
        doc_id = _insert_doc(tmp_db, "BATCH-RM-06", source_path=sales_path)

        mock_draft = MagicMock()
        mock_draft.draft_state = "draft"
        mock_draft.wfirma_proforma_fullnumber = "PROF 55/2026"
        mock_draft.id = 55

        with patch(
            "app.api.routes_packing.pdb.get_packing_document",
            return_value={"id": doc_id, "batch_id": "BATCH-RM-06",
                          "source_file_path": sales_path},
        ), patch(
            "app.api.routes_packing.settings.storage_root",
            tmp_db,
        ), patch(
            "app.services.proforma_invoice_link_db.list_drafts_for_batch",
            return_value=[mock_draft],
        ):
            r = client.delete(
                f"/api/v1/packing/BATCH-RM-06/document/{doc_id}",
                headers=_auth(),
            )
        assert r.status_code == 409
        body = r.json()
        assert body["detail"]["code"] == "PACKING_SALES_DELETE_BLOCKED_BY_PROFORMA"
        assert "PROF 55/2026" in str(body["detail"]["active_drafts"])

    def test_200_sales_allowed_when_all_drafts_cancelled(self, client, tmp_db):
        """SALES file delete succeeds when all drafts are cancelled/superseded."""
        sales_path = str(tmp_db / "source" / "sales" / "sales.xlsx")
        Path(sales_path).parent.mkdir(parents=True, exist_ok=True)
        Path(sales_path).write_bytes(b"content")
        doc_id = _insert_doc(tmp_db, "BATCH-RM-07", source_path=sales_path)

        mock_draft = MagicMock()
        mock_draft.draft_state = "cancelled"
        mock_draft.wfirma_proforma_fullnumber = ""
        mock_draft.id = 99

        with patch(
            "app.services.proforma_invoice_link_db.list_drafts_for_batch",
            return_value=[mock_draft],
        ):
            r = client.delete(
                f"/api/v1/packing/BATCH-RM-07/document/{doc_id}",
                headers=_auth(),
            )
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 4. Source grep: new endpoints registered in routes_packing.py
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceGrep:
    def _src(self):
        import app.api.routes_packing as rp
        with open(rp.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
            return f.read()

    def test_download_endpoint_registered(self):
        assert "download_packing_document" in self._src()
        assert "document/{document_id}/download" in self._src()

    def test_delete_endpoint_registered(self):
        assert "delete_packing_document" in self._src()
        assert "@router.delete" in self._src()

    def test_proforma_guard_present(self):
        assert "PACKING_SALES_DELETE_BLOCKED_BY_PROFORMA" in self._src()

    def test_lesson_g_cache_control(self):
        """Download endpoint must set no-store (Lesson G compliance)."""
        assert "no-store" in self._src()

    def test_db_delete_function_exists(self):
        import app.services.packing_db as pdb_mod
        with open(pdb_mod.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
            src = f.read()
        assert "delete_packing_document_and_lines" in src

    def test_html_has_download_testid(self):
        html_path = Path(__file__).parent.parent / "app" / "static" / "shipment-detail.html"
        src = html_path.read_text(encoding="utf-8")
        assert "packing-list-download-" in src

    def test_html_has_delete_testid(self):
        html_path = Path(__file__).parent.parent / "app" / "static" / "shipment-detail.html"
        src = html_path.read_text(encoding="utf-8")
        assert "packing-list-delete-" in src

    def test_html_has_handle_packing_delete(self):
        html_path = Path(__file__).parent.parent / "app" / "static" / "shipment-detail.html"
        src = html_path.read_text(encoding="utf-8")
        assert "handlePackingDelete" in src
