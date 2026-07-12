"""
test_documents_identity_contract_wave3.py — EJ Dashboard Stabilization Wave 3.

Pins the document-identity authority the V2 Documents tab now consumes:

  * GET /upload/shipment/{id}/documents emits the identity contract per row
    (document_id, authority, mime_type, is_current, can_view/download/replace/
    delete, view_url, download_url) and NEVER leaks file_path.
  * Canonical content route serves inline (View) vs attachment (Download) with
    no-store, keyed by document_id through the registry authority.
  * Delete-by-id removes uploaded docs (registry row gone); generated fiscal /
    customs-evidence docs are non-deletable (409).
  * Replace supersedes the old row (is_current=0) instead of overwriting.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import document_db as ddb
from app.services import packing_db as pdb


@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("doc_identity_storage")


@pytest.fixture(scope="module")
def _dbs(tmp_storage):
    ddb.init_document_db(tmp_storage / "documents.db")
    pdb.init_packing_db(tmp_storage / "packing.db")
    return tmp_storage


@pytest.fixture(scope="module")
def client(tmp_storage, _dbs):
    with patch.object(settings, "storage_root", tmp_storage):
        with patch.object(settings, "max_upload_bytes", 20 * 1024 * 1024):
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _pdf(name):
    return (name, io.BytesIO(f"%PDF-1.4 {name}".encode()), "application/pdf")


def _seed_batch(client):
    """Create a real batch via intake (invoice + purchase packing + sales
    packing) so the registry has uploaded docs to exercise."""
    awb = patch("app.api.routes_intake.parse_awb_pdf", return_value={"awb_number": "", "carrier": "DHL", "confidence": 0.0})
    pack = patch("app.api.routes_intake.process_packing_upload", side_effect=Exception("no packing"))
    with awb, pack:
        r = client.post("/api/v1/shipment/intake",
            data={"tracking_no": "DOCID-1", "carrier": "DHL",
                  "metadata": json.dumps({"purchase_blocks": [{"invoice_index": 0, "packing_index": 0}],
                                          "sales_blocks": [{"document_index": -1, "packing_index": 0}]})},
            files=[("invoices", _pdf("INV.pdf")),
                   ("packing_lists", _pdf("PPACK.pdf")),
                   ("sales_packing_lists", _pdf("SPACK.pdf"))],
            headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()["batch_id"]


def _manifest(client, batch_id):
    r = client.get(f"/api/v1/upload/shipment/{batch_id}/documents", headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()["documents"]


# ── Identity contract ───────────────────────────────────────────────────────

def test_manifest_emits_identity_contract_and_hides_file_path(client):
    batch_id = _seed_batch(client)
    docs = _manifest(client, batch_id)
    assert docs, "expected registered documents"
    for row in docs:
        for field in ("document_id", "document_type", "authority", "mime_type",
                      "is_current", "can_view", "can_download", "can_replace",
                      "can_delete", "view_url", "download_url"):
            assert field in row, f"missing contract field {field} in {row.get('document_type')}"
        # file_path (absolute disk path) must NEVER cross the API boundary.
        assert "file_path" not in row, "file_path leaked in manifest row"
        assert row["view_url"] and "disposition=inline" in row["view_url"]
        assert row["download_url"] and "disposition=attachment" in row["download_url"]
        assert row["mime_type"] == "application/pdf"
        assert row["is_current"] is True


def test_uploaded_docs_deletable_generated_not(client):
    batch_id = _seed_batch(client)
    # register a generated fiscal artifact directly
    genf = Path(settings.storage_root) / "outputs" / batch_id / "PZ.pdf"
    genf.parent.mkdir(parents=True, exist_ok=True)
    genf.write_bytes(b"%PDF gen")
    ddb.register_document(batch_id=batch_id, document_type="pz_pdf",
                          file_name="PZ.pdf", file_path=str(genf),
                          file_hash=ddb.sha256_file(genf), source="generated")
    docs = _manifest(client, batch_id)
    by_type = {d["document_type"]: d for d in docs}
    assert by_type["purchase_invoice"]["can_delete"] is True
    assert by_type["pz_pdf"]["can_delete"] is False
    assert by_type["pz_pdf"]["can_replace"] is False
    assert by_type["pz_pdf"]["is_generated"] is True


def test_sad_is_non_deletable_and_non_replaceable_via_general_routes(client):
    """SAD is customs evidence: can_delete=false (never silently deleted) and
    can_replace=false via the GENERAL replace button (SAD is replaced through
    its own /sad route on the SAD card). Prevents a Replace button that 409s."""
    batch_id = _seed_batch(client)
    sadf = Path(settings.storage_root) / "outputs" / batch_id / "source" / "sad" / "SAD.pdf"
    sadf.parent.mkdir(parents=True, exist_ok=True)
    sadf.write_bytes(b"%PDF sad")
    ddb.register_document(batch_id=batch_id, document_type="sad_pdf",
                          file_name="SAD.pdf", file_path=str(sadf),
                          file_hash=ddb.sha256_file(sadf), source="upload")
    sad = next(d for d in _manifest(client, batch_id) if d["document_type"] == "sad_pdf")
    assert sad["can_delete"] is False
    assert sad["can_replace"] is False
    assert sad["can_view"] is True and sad["can_download"] is True


# ── Content serving (inline vs attachment) ──────────────────────────────────

def test_content_route_inline_and_attachment(client):
    batch_id = _seed_batch(client)
    inv = next(d for d in _manifest(client, batch_id) if d["document_type"] == "purchase_invoice")
    did = inv["document_id"]
    r_in = client.get(f"/api/v1/upload/shipment/{batch_id}/documents/{did}/content?disposition=inline", headers=_auth())
    assert r_in.status_code == 200
    assert "inline" in r_in.headers.get("content-disposition", "")
    assert "no-store" in r_in.headers.get("cache-control", "")
    r_at = client.get(f"/api/v1/upload/shipment/{batch_id}/documents/{did}/content?disposition=attachment", headers=_auth())
    assert r_at.status_code == 200
    assert "attachment" in r_at.headers.get("content-disposition", "")


def test_content_route_forces_attachment_for_unsafe_inline_types(client):
    """XSS defence: a non-browser-safe type (xlsx) must be served as ATTACHMENT
    even when inline is requested, and carry nosniff + a sandbox CSP. Only
    pdf/images render inline from the app origin."""
    batch_id = _seed_batch(client)
    xf = Path(settings.storage_root) / "outputs" / batch_id / "source" / "misc" / "pack.xlsx"
    xf.parent.mkdir(parents=True, exist_ok=True)
    xf.write_bytes(b"PK\x03\x04 fake xlsx")
    did = ddb.register_document(batch_id=batch_id, document_type="other",
                                file_name="pack.xlsx", file_path=str(xf),
                                file_hash=ddb.sha256_file(xf), source="upload")
    r = client.get(f"/api/v1/upload/shipment/{batch_id}/documents/{did}/content?disposition=inline", headers=_auth())
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", ""), "xlsx must not render inline"
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert "sandbox" in r.headers.get("content-security-policy", "")


def test_content_route_rejects_foreign_document(client):
    batch_id = _seed_batch(client)
    r = client.get(f"/api/v1/upload/shipment/{batch_id}/documents/does-not-exist/content", headers=_auth())
    assert r.status_code == 404


# ── Delete-by-id ────────────────────────────────────────────────────────────

def test_delete_requires_confirmation_header(client):
    batch_id = _seed_batch(client)
    inv = next(d for d in _manifest(client, batch_id) if d["document_type"] == "purchase_invoice")
    did = inv["document_id"]
    # Without X-Confirm-Delete → 428, and the row survives.
    r = client.delete(f"/api/v1/upload/shipment/{batch_id}/documents/{did}", headers=_auth())
    assert r.status_code == 428, r.text
    assert ddb.get_document(did) is not None


def test_delete_uploaded_document_removes_row(client):
    batch_id = _seed_batch(client)
    inv = next(d for d in _manifest(client, batch_id) if d["document_type"] == "purchase_invoice")
    did = inv["document_id"]
    r = client.delete(f"/api/v1/upload/shipment/{batch_id}/documents/{did}",
                      headers={**_auth(), "X-Operator": "tester", "X-Confirm-Delete": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["packing_db_cleaned"] is True
    # row gone from the registry
    assert ddb.get_document(did) is None
    assert not any(d["document_id"] == did for d in _manifest(client, batch_id))


def test_delete_generated_document_blocked_409(client):
    batch_id = _seed_batch(client)
    genf = Path(settings.storage_root) / "outputs" / batch_id / "PZ2.pdf"
    genf.parent.mkdir(parents=True, exist_ok=True)
    genf.write_bytes(b"%PDF gen2")
    gid = ddb.register_document(batch_id=batch_id, document_type="pz_pdf",
                                file_name="PZ2.pdf", file_path=str(genf),
                                file_hash=ddb.sha256_file(genf), source="generated")
    r = client.delete(f"/api/v1/upload/shipment/{batch_id}/documents/{gid}", headers=_auth())
    assert r.status_code == 409
    assert ddb.get_document(gid) is not None  # not deleted


# ── Replace (audited supersede) ─────────────────────────────────────────────

def test_replace_supersedes_old_row_and_preserves_original_file(client):
    batch_id = _seed_batch(client)
    inv = next(d for d in _manifest(client, batch_id) if d["document_type"] == "purchase_invoice")
    old_id = inv["document_id"]
    old_path = ddb.get_document(old_id)["file_path"]
    old_bytes = Path(old_path).read_bytes()
    # Replace using the SAME filename as the original — the original file must be
    # PRESERVED (written to a distinct path), never overwritten.
    r = client.post(f"/api/v1/upload/shipment/{batch_id}/documents/{old_id}/replace",
                    files={"file": ("INV.pdf", io.BytesIO(b"%PDF brand new invoice content"), "application/pdf")},
                    headers={**_auth(), "X-Operator": "tester"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["new_document_id"] != old_id and body["superseded"] is True
    old = ddb.get_document(old_id)
    assert old["is_current"] == 0 and old["superseded_by"] == body["new_document_id"]
    # Original file still exists at its original path with its ORIGINAL bytes.
    assert Path(old_path).exists() and Path(old_path).read_bytes() == old_bytes
    new = ddb.get_document(body["new_document_id"])
    assert new["file_path"] != old_path and new["is_current"] == 1


def test_replace_rejected_on_superseded_row(client):
    batch_id = _seed_batch(client)
    inv = next(d for d in _manifest(client, batch_id) if d["document_type"] == "purchase_invoice")
    old_id = inv["document_id"]
    r1 = client.post(f"/api/v1/upload/shipment/{batch_id}/documents/{old_id}/replace",
                     files={"file": ("INV.pdf", io.BytesIO(b"%PDF v2"), "application/pdf")}, headers=_auth())
    assert r1.status_code == 200
    # old_id is now superseded → replacing it again is a 409 (replace the current one)
    r2 = client.post(f"/api/v1/upload/shipment/{batch_id}/documents/{old_id}/replace",
                     files={"file": ("INV.pdf", io.BytesIO(b"%PDF v3"), "application/pdf")}, headers=_auth())
    assert r2.status_code == 409, r2.text
    # and the superseded row's manifest flag hides Replace
    sup = next(d for d in _manifest(client, batch_id) if d["document_id"] == old_id)
    assert sup["is_current"] is False and sup["can_replace"] is False


def test_replace_wrong_extension_rejected(client):
    batch_id = _seed_batch(client)
    inv = next(d for d in _manifest(client, batch_id) if d["document_type"] == "purchase_invoice")
    r = client.post(f"/api/v1/upload/shipment/{batch_id}/documents/{inv['document_id']}/replace",
                    files={"file": ("bad.txt", io.BytesIO(b"not pdf"), "text/plain")},
                    headers=_auth())
    assert r.status_code == 400


def test_replace_non_pdf_content_rejected(client):
    """A .pdf-named file whose bytes are not a PDF is rejected (magic-byte check
    via _save)."""
    batch_id = _seed_batch(client)
    inv = next(d for d in _manifest(client, batch_id) if d["document_type"] == "purchase_invoice")
    r = client.post(f"/api/v1/upload/shipment/{batch_id}/documents/{inv['document_id']}/replace",
                    files={"file": ("INV.pdf", io.BytesIO(b"GIF89a not a pdf"), "application/pdf")},
                    headers=_auth())
    assert r.status_code == 400
