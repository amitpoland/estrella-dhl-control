"""
test_master_csv_wave5.py — EJ Dashboard Stabilization Wave 5.

Pins the shared Master-Data CSV import/export contract (Clients + Suppliers):
formula-injection safety, column policy (system columns never writable), the
dry-run/commit import semantics, upsert-by-key, validation rejects, empty-cell
no-blank, and the duplicate-VAT advisory (never a blocker — Lesson N).
"""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.services import master_csv


# ── Pure helper unit tests ───────────────────────────────────────────────────

def test_formula_injection_is_neutralised():
    rows = [{"name": "=cmd|calc", "code": "+1", "c": "-2", "d": "@x", "ok": "Acme"}]
    out = master_csv.rows_to_csv(rows, ["name", "code", "c", "d", "ok"]).decode("utf-8-sig")
    body = out.splitlines()[1]
    assert body.startswith("'=cmd|calc") or "\"'=cmd|calc\"" in body
    assert "'+1" in body and "'-2" in body and "'@x" in body
    assert "Acme" in body and "'Acme" not in body


def test_export_has_bom_and_key_first():
    assert master_csv.rows_to_csv([], master_csv.supplier_columns()).startswith(b"\xef\xbb\xbf")
    assert master_csv.supplier_columns()[0] == "supplier_code"
    assert master_csv.customer_columns()[0] == "bill_to_contractor_id"


def test_system_columns_never_writable():
    for banned in ("id", "created_at", "updated_at", "deleted_at",
                   "last_wfirma_sync_at", "wfirma_sync_source", "active"):
        assert banned not in master_csv.supplier_import_writable()
        assert banned not in master_csv.customer_import_writable()
    # VIES results are customer-only system columns
    assert "vat_eu_valid" not in master_csv.customer_import_writable()


def test_parse_strips_bom_and_numbers_rows_from_two():
    raw = b"\xef\xbb\xbfsupplier_code,name\r\nS1,Acme\r\nS2,Beta\r\n"
    parsed = master_csv.parse_csv(raw)
    assert [ln for ln, _ in parsed] == [2, 3]
    assert parsed[0][1] == {"supplier_code": "S1", "name": "Acme"}


def test_project_writable_drops_empty_and_unknown():
    row = {"supplier_code": "S1", "name": "", "bogus": "x", "id": "9"}
    out = master_csv.project_writable(row, master_csv.supplier_import_writable())
    assert out == {"supplier_code": "S1"}  # empty name dropped, unknown/system dropped


# ── Endpoint wiring (suppliers) ──────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    from app.main import app
    from app.core.config import settings
    from app.services import suppliers_db, customer_master_db
    sup_db = tmp_path / "suppliers.sqlite"
    cus_db = tmp_path / "customer_master.sqlite"
    suppliers_db.init_db(sup_db)
    customer_master_db.init_db(cus_db)
    with patch("app.api.routes_suppliers._DB_PATH", sup_db), \
         patch("app.api.routes_customer_master._DB_PATH", cus_db):
        with TestClient(app) as c:
            c.headers.update({"X-API-KEY": settings.api_key or "test-key"})
            yield c


def _supplier_csv(rows):
    buf = io.StringIO()
    buf.write("supplier_code,name,country,vat_id\r\n")
    for r in rows:
        buf.write(",".join(r) + "\r\n")
    return buf.getvalue().encode("utf-8-sig")


def test_supplier_import_preview_then_commit_upserts_by_code(client):
    csv_bytes = _supplier_csv([["WF-1", "Acme", "PL", "PL123"],
                               ["WF-2", "Beta", "DE", "DE9"]])
    # preview — nothing written
    r = client.post("/api/v1/suppliers/import/csv",
                    files={"file": ("s.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["mode"] == "preview" and p["committed"] is False
    assert p["created"] == 2 and p["updated"] == 0
    assert client.get("/api/v1/suppliers/").json()["count"] == 0  # dry-run wrote nothing

    # commit — creates
    r = client.post("/api/v1/suppliers/import/csv?commit=true",
                    files={"file": ("s.csv", csv_bytes, "text/csv")})
    body = r.json()
    assert body["committed"] is True and body["created"] == 2
    assert client.get("/api/v1/suppliers/").json()["count"] == 2

    # re-import same codes → updates, not duplicates
    r = client.post("/api/v1/suppliers/import/csv?commit=true",
                    files={"file": ("s.csv", csv_bytes, "text/csv")})
    b2 = r.json()
    assert b2["updated"] == 2 and b2["created"] == 0
    assert client.get("/api/v1/suppliers/").json()["count"] == 2


def test_supplier_import_rejects_missing_required(client):
    bad = b"supplier_code,name,country\r\n,NoCode,PL\r\nWF-9,,PL\r\n"
    r = client.post("/api/v1/suppliers/import/csv?commit=true",
                    files={"file": ("s.csv", bad, "text/csv")})
    body = r.json()
    assert body["created"] == 0
    assert len(body["rejected"]) == 2
    assert body["rejected"][0]["row"] == 2  # 1-based incl header


def test_supplier_export_roundtrips(client):
    client.post("/api/v1/suppliers/import/csv?commit=true",
                files={"file": ("s.csv", _supplier_csv([["WF-7", "Gamma", "PL", "PL7"]]), "text/csv")})
    r = client.get("/api/v1/suppliers/export/csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "no-store" in r.headers.get("cache-control", "")
    assert "WF-7" in r.text and "Gamma" in r.text


def test_bad_upload_rejected(client):
    r = client.post("/api/v1/suppliers/import/csv",
                    files={"file": ("evil.exe", b"MZ...", "application/x-msdownload")})
    assert r.status_code == 422


# ── Endpoint wiring (customers) — upsert by contractor id + dup-VAT advisory ──

def test_customer_import_upsert_and_dup_vat_advisory(client):
    csv_bytes = ("bill_to_contractor_id,bill_to_name,country,nip\r\n"
                 "C1,Alpha,PL,PL555\r\n"
                 "C2,Beta,PL,PL555\r\n").encode("utf-8-sig")
    # commit both (same NIP, different contractor ids — allowed, advisory only)
    r = client.post("/api/v1/customer-master/import/csv?commit=true",
                    files={"file": ("c.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2 and body["updated"] == 0
    # C2 shares NIP with C1 → advisory present, but row still committed
    assert any(a["nip"] == "PL555" for a in body["duplicate_vat_advisories"])
    assert body["skipped"] == 0
    assert client.get("/api/v1/customer-master/").json()["count"] == 2
