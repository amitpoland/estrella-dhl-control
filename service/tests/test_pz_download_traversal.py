"""test_pz_download_traversal.py — path-traversal containment for GET /api/v1/files/*.

Regression pin for R-1 (file-download containment). Before the fix, the
generic download route

    GET /api/v1/files/{batch_id}/{filename}   (routes_pz.download_file)

validated ``filename`` but NOT ``batch_id``. A percent-encoded request
``GET /api/v1/files/%2e%2e/users.db`` decoded server-side to batch_id="..",
built ``storage_root/outputs/../users.db`` == ``storage_root/users.db`` and
served it (HTTP 200) — an authenticated read of any file directly under the
storage root, including the auth DB.

The fix applies resolved-path containment (mirrors
routes_upload._safe_document_path): the request-controlled batch_id + filename
must resolve strictly inside their authorized batch directory.

These tests drive the REAL Starlette routing stack (app.main.app via TestClient)
so the server-side percent-decoding that enables the exploit is exercised — a
direct call to the handler function would bypass it. All I/O is confined to the
per-test tmp_path (settings.storage_root is redirected there); no production
storage, auth DB, or secret is touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)  # dev-mode: auth open
    from app.main import app
    return TestClient(app), tmp_path


def _seed(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    (outputs / "BATCH123").mkdir(parents=True)
    (outputs / "BATCH123" / "report.pdf").write_bytes(b"%PDF-1.4 valid-report")
    # A file directly in outputs/ (target of the batch_id="." collapse case).
    (outputs / "loose.txt").write_text("OUTPUTS-ROOT-FILE")
    # Sensitive files one level ABOVE outputs/, i.e. directly in storage_root —
    # the escape target the exploit reached.
    (tmp_path / "users.db").write_text("SENSITIVE-AUTH-DB")
    (tmp_path / "secret_root.txt").write_text("STORAGE-ROOT-SECRET")


# ── Baseline behaviour preserved ──────────────────────────────────────────────

def test_valid_download_succeeds(client):
    c, tmp_path = client
    _seed(tmp_path)
    r = c.get("/api/v1/files/BATCH123/report.pdf")
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 valid-report"
    # Lesson G — generated-artifact download must be no-store.
    assert "no-store" in r.headers.get("cache-control", "")


def test_missing_file_returns_404(client):
    c, tmp_path = client
    _seed(tmp_path)
    r = c.get("/api/v1/files/BATCH123/does-not-exist.pdf")
    assert r.status_code == 404
    assert "SENSITIVE" not in r.text and "SECRET" not in r.text


# ── Traversal is contained ────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/v1/files/%2e%2e/users.db",         # encoded '..' -> parent escape (the R-1 exploit)
    "/api/v1/files/%2e%2e/secret_root.txt",  # encoded '..' -> other storage-root file
    "/api/v1/files/%2E%2E/users.db",         # case-variant encoding
])
def test_encoded_parent_escape_rejected(client, path):
    c, tmp_path = client
    _seed(tmp_path)
    r = c.get(path)
    assert r.status_code == 400, f"{path} -> {r.status_code}"
    assert "SENSITIVE-AUTH-DB" not in r.text
    assert "STORAGE-ROOT-SECRET" not in r.text


def test_dot_batch_id_collapse_rejected(client):
    # batch_id="." collapses batch_dir to outputs_root -> must be rejected so a
    # caller cannot read files sitting directly in outputs/ outside any batch.
    c, tmp_path = client
    _seed(tmp_path)
    r = c.get("/api/v1/files/%2e/loose.txt")
    assert r.status_code == 400
    assert "OUTPUTS-ROOT-FILE" not in r.text


def test_filename_dotdot_rejected(client):
    # filename=".." (single encoded segment, no slash) must not escape the batch dir.
    c, tmp_path = client
    _seed(tmp_path)
    r = c.get("/api/v1/files/BATCH123/%2e%2e")
    assert r.status_code in (400, 404)
    assert "SENSITIVE" not in r.text


# ── Sibling guarded route unchanged ───────────────────────────────────────────

def test_source_route_batch_id_guard_still_rejects(client):
    # download_source_file already guarded batch_id; confirm no regression.
    c, tmp_path = client
    _seed(tmp_path)
    r = c.get("/api/v1/files/%2e%2e/source/invoices/inv.pdf")
    assert r.status_code == 400
    assert "SENSITIVE" not in r.text


def test_source_route_valid_download(client):
    c, tmp_path = client
    _seed(tmp_path)
    src = tmp_path / "outputs" / "BATCH123" / "source" / "invoices"
    src.mkdir(parents=True)
    (src / "inv.pdf").write_bytes(b"%PDF-1.4 inv")
    r = c.get("/api/v1/files/BATCH123/source/invoices/inv.pdf")
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 inv"


# ── Item-6 gate: empty + Windows trailing-dot/space batch_id ──────────────────

def test_empty_batch_id_rejected(client):
    # batch_id="" is expressed as a double slash. Starlette's {batch_id}=[^/]+ never
    # matches an empty segment, so the 2-param route MISSES -> 404 (rejected at the
    # routing layer, before the handler). Were it to reach the handler, batch_dir would
    # collapse to outputs_root and the equality guard would return 400. Either path:
    # no pass-through, no leak.
    c, tmp_path = client
    _seed(tmp_path)
    r = c.get("/api/v1/files//report.pdf")
    assert r.status_code in (400, 404), r.status_code
    assert "SENSITIVE-AUTH-DB" not in r.text
    assert "STORAGE-ROOT-SECRET" not in r.text


@pytest.mark.parametrize("path", [
    "/api/v1/files/%2e%2e%2e/users.db",   # batch_id="..." (Windows strips trailing dots)
    "/api/v1/files/%2e%2e%20/users.db",   # batch_id=".. " (Windows strips trailing space -> "..")
    "/api/v1/files/..%20/users.db",       # same escape, literal '..' + encoded trailing space
])
def test_windows_trailing_dot_space_batch_id_rejected(client, path):
    # Windows strips trailing dots and spaces from a path component, so ".. " / "..."
    # collapse to ".." at the filesystem layer. Path.resolve() performs that OS-level
    # normalization, so the relative_to() containment check sees the parent escape and
    # rejects with 400 -- a substring ".." guard on the raw string would NOT catch
    # "%2e%2e%20". No sensitive content is served.
    c, tmp_path = client
    _seed(tmp_path)
    r = c.get(path)
    assert r.status_code == 400, f"{path} -> {r.status_code}"
    assert "SENSITIVE-AUTH-DB" not in r.text
    assert "STORAGE-ROOT-SECRET" not in r.text
