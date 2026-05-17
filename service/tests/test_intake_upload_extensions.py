"""test_intake_upload_extensions.py — hotfix regression for the
2026-05-17 ".xlsx packing list rejected with Allowed: ['.pdf']" bug.

Per-slot extension matrix the modal + intake route must honor:

  purchase_invoice / sales_invoice / sales_proforma / awb  → .pdf only
  purchase_packing_list / sales_packing_list               → .pdf, .xlsx, .xls
  service_invoice                                          → .pdf, .xlsx, .xls
  carnet                                                   → .pdf only
  other_document (generic safe rule)                       → .pdf, .xlsx, .xls,
                                                             .jpg, .jpeg, .png
"""
from __future__ import annotations

import io
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="pz_ext_smoke_")
    monkeypatch.setenv("STORAGE_ROOT", tmp)
    monkeypatch.setenv("PZ_STORAGE_ROOT", tmp)
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root",
                        type(settings.storage_root)(tmp), raising=False)
    from app.main import app
    return TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────

def _pdf():  return io.BytesIO(b"%PDF-1.4\n%test\n")
def _xlsx(): return io.BytesIO(b"PK\x03\x04smoke-xlsx-data")
def _xls():  return io.BytesIO(b"\xD0\xCF\x11\xE0smoke-xls-data")
def _exe():  return io.BytesIO(b"MZ\x90\x00smoke-exe-data")
def _zip():  return io.BytesIO(b"PK\x03\x04smoke-zip-data")


def _post(client, tracking, files, meta=None):
    return client.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": tracking, "carrier": "DHL",
              "metadata": json.dumps(meta or {})},
        files=files,
    )


# ── Packing list: xlsx + xls + pdf ALL accepted ──────────────────────────

def test_purchase_packing_xlsx_accepted(client):
    files = [
        ("invoices",      ("inv.pdf",       _pdf(),  "application/pdf")),
        ("packing_lists", ("pack.xlsx",     _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    r = _post(client, "PXT-XLSX-1", files)
    assert r.status_code == 200, r.text


def test_purchase_packing_xls_accepted(client):
    files = [
        ("invoices",      ("inv.pdf",   _pdf(), "application/pdf")),
        ("packing_lists", ("pack.xls",  _xls(), "application/vnd.ms-excel")),
    ]
    r = _post(client, "PXT-XLS-1", files)
    assert r.status_code == 200, r.text


def test_sales_packing_xlsx_accepted(client):
    files = [
        ("invoices",            ("inv.pdf",   _pdf(),  "application/pdf")),
        ("sales_packing_lists", ("sp.xlsx",   _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    r = _post(client, "PXT-SXLSX-1", files)
    assert r.status_code == 200, r.text


def test_packing_pdf_still_accepted(client):
    files = [
        ("invoices",      ("inv.pdf",  _pdf(), "application/pdf")),
        ("packing_lists", ("pack.pdf", _pdf(), "application/pdf")),
    ]
    r = _post(client, "PXT-PDF-1", files)
    assert r.status_code == 200, r.text


# ── Purchase invoice + AWB stay PDF-only ─────────────────────────────────

def test_purchase_invoice_xlsx_rejected(client):
    """The exact failure mode from the 2026-05-17 production bug: a user
    drops an xlsx packing list into the default first slot (which is a
    purchase_invoice slot). Backend must reject with a clear error."""
    files = [("invoices", ("mislabeled.xlsx", _xlsx(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
    r = _post(client, "PXT-INV-1", files)
    assert r.status_code == 400
    assert "'.xlsx' not allowed" in r.text
    assert "'.pdf'" in r.text   # only PDF allowed for invoices


def test_awb_xlsx_rejected(client):
    files = [
        ("invoices", ("inv.pdf",  _pdf(),  "application/pdf")),
        ("awb",      ("awb.xlsx", _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    r = _post(client, "PXT-AWB-1", files)
    assert r.status_code == 400
    assert "'.xlsx' not allowed" in r.text


# ── Local-only slots: per-type matrix ────────────────────────────────────

def test_service_invoice_xlsx_accepted(client):
    files = [
        ("invoices",         ("inv.pdf",  _pdf(),  "application/pdf")),
        ("service_invoices", ("svc.xlsx", _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    r = _post(client, "PXT-SVC-1", files)
    assert r.status_code == 200, r.text


def test_service_invoice_xls_accepted(client):
    files = [
        ("invoices",         ("inv.pdf",  _pdf(), "application/pdf")),
        ("service_invoices", ("svc.xls",  _xls(), "application/vnd.ms-excel")),
    ]
    r = _post(client, "PXT-SVC-2", files)
    assert r.status_code == 200, r.text


def test_carnet_pdf_only(client):
    files = [
        ("invoices",    ("inv.pdf",     _pdf(),  "application/pdf")),
        ("carnet_docs", ("carnet.xlsx", _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    r = _post(client, "PXT-CARNET-1", files)
    assert r.status_code == 400
    assert "'.xlsx' not allowed" in r.text
    assert "'.pdf'" in r.text


def test_other_document_xlsx_accepted(client):
    files = [
        ("invoices",   ("inv.pdf",   _pdf(),  "application/pdf")),
        ("other_docs", ("misc.xlsx", _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    r = _post(client, "PXT-OTH-1", files)
    assert r.status_code == 200, r.text


def test_other_document_jpg_accepted(client):
    files = [
        ("invoices",   ("inv.pdf",   _pdf(),                 "application/pdf")),
        ("other_docs", ("photo.jpg", io.BytesIO(b"\xff\xd8\xff\xe0jpeg"), "image/jpeg")),
    ]
    r = _post(client, "PXT-OTH-2", files)
    assert r.status_code == 200, r.text


# ── Unsafe types rejected everywhere ─────────────────────────────────────

def test_exe_rejected_in_packing(client):
    files = [
        ("invoices",      ("inv.pdf", _pdf(), "application/pdf")),
        ("packing_lists", ("evil.exe", _exe(), "application/x-msdownload")),
    ]
    r = _post(client, "PXT-EXE-1", files)
    assert r.status_code == 400
    assert "'.exe' not allowed" in r.text


def test_zip_rejected_in_other(client):
    files = [
        ("invoices",   ("inv.pdf",  _pdf(), "application/pdf")),
        ("other_docs", ("evil.zip", _zip(), "application/zip")),
    ]
    r = _post(client, "PXT-ZIP-1", files)
    assert r.status_code == 400
    assert "'.zip' not allowed" in r.text


# ── Frontend source-grep: per-slot accept attribute + allowedExts ────────

def test_dashboard_modal_has_per_slot_accept():
    from pathlib import Path
    dash = (Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    # The single permissive `.pdf,.jpg,.png,.xlsx,.xls` literal must be gone
    # from the modal's <input>; replaced with per-type `accept={type.accept}`.
    assert "accept={type.accept" in dash
    # allowedExts list driving the preflight check:
    assert "allowedExts:" in dash
    # PDF-only types must list only .pdf in allowedExts:
    pi_section = dash[dash.index("id: 'purchase_invoice'"):dash.index("id: 'sales_proforma'")]
    assert "allowedExts: ['.pdf']" in pi_section
    # Packing types must include xlsx + xls:
    pp_section = dash[dash.index("id: 'purchase_packing'"):dash.index("id: 'sales_packing'")]
    assert "'.xlsx'" in pp_section and "'.xls'" in pp_section
