"""test_add_document_route.py — POST /api/v1/shipment/{batch_id}/add-document.

Verifies the post-draft add-document endpoint:
  * per-doc-type file extension policy
  * shipment_documents row creation
  * contractor_id inheritance order (explicit > packing_contractor_resolution > '')
  * parser-failure non-fatal
  * SAD / unknown document_type rejected with 422
  * missing batch returns 404
  * no DHL / wFirma / proforma / PZ / SAD trigger from this code path
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    # Module-level _db_path globals may be cached from a prior test
    # using a different tmp dir. Re-init so the route writes to THIS
    # test's tmp dir.
    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    from app.services import wfirma_db as wfdb
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return TestClient(app), tmp_path


def _pdf(): return io.BytesIO(b"%PDF-1.4\n%test\n%EOF\n")
def _xlsx(): return io.BytesIO(b"PK\x03\x04smoke-xlsx-data")
def _xls():  return io.BytesIO(b"\xD0\xCF\x11\xE0smoke-xls-data")


def _seed_batch(tmp_path: Path, batch_id: str = "B-ADD-1") -> str:
    """Create the batch output folder + a minimal audit.json so the route
    finds the batch."""
    out = tmp_path / "outputs" / batch_id
    (out / "source").mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "tracking_no": batch_id,
             "awb": batch_id, "carrier": "DHL", "timeline": []}
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_id


def _seed_resolution(tmp_path: Path, batch_id: str, role: str,
                     matched_id: str, parsed_name: str = "Inherited Co.") -> None:
    """Seed a packing_contractor_resolution row so the route can inherit
    IDs from it (mirrors what intake's E3 seeder writes)."""
    from app.services import packing_resolution_db as prdb
    p = tmp_path / "packing_resolutions.sqlite"
    prdb.upsert_resolution(
        p,
        batch_id=batch_id, role=role,
        verdict={
            "parsed_name":         parsed_name,
            "matched_master_type": "customer_master" if role == "client" else "suppliers",
            "matched_master_id":   matched_id,
            "tier":                1, "confidence": 1.0,
            "reason":              "test_seeded",
            "evidence":            {}, "candidates": [],
            "status":              "confirmed",
        },
        operator_user="test", operator_override=False,
        status_override="confirmed",
    )


def _post(client, batch_id: str, document_type: str, filename: str,
          file_obj, ctype: str, **form_extra):
    fields = {"document_type": document_type, **form_extra}
    return client.post(
        f"/api/v1/shipment/{batch_id}/add-document",
        data=fields,
        files=[("file", (filename, file_obj, ctype))],
    )


# ── Happy paths ──────────────────────────────────────────────────────────

def test_purchase_invoice_pdf_accepted(client):
    cli, root = client
    bid = _seed_batch(root)
    r = _post(cli, bid, "purchase_invoice", "inv.pdf", _pdf(), "application/pdf")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["document_type"] == "purchase_invoice"
    assert body["document_id"]
    assert body["file_name"] == "inv.pdf"
    # Stub PDF parses as filename_only or extraction_failed (non-fatal):
    assert body["parser_status"] in ("placeholder", "extracted", "extraction_failed")


def test_purchase_packing_list_xlsx_accepted(client):
    cli, root = client
    bid = _seed_batch(root)
    r = _post(cli, bid, "purchase_packing_list", "pack.xlsx", _xlsx(),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 200, r.text
    body = r.json()
    # Parser fails on a stub xlsx — must be non-fatal:
    assert body["parser_status"] in ("extracted", "placeholder", "extraction_failed")
    assert body["document_id"]


def test_sales_packing_list_xlsx_accepted(client):
    cli, root = client
    bid = _seed_batch(root)
    r = _post(cli, bid, "sales_packing_list", "sp.xlsx", _xlsx(),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 200, r.text


def test_service_invoice_xlsx_accepted_local_only(client):
    cli, root = client
    bid = _seed_batch(root)
    r = _post(cli, bid, "service_invoice", "svc.xlsx", _xlsx(),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parser_status"] == "local_only"


# ── Rejection paths ──────────────────────────────────────────────────────

def test_carnet_rejects_xlsx(client):
    cli, root = client
    bid = _seed_batch(root)
    r = _post(cli, bid, "carnet", "ata.xlsx", _xlsx(),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 400
    assert "'.xlsx' not allowed" in r.text


def test_purchase_invoice_rejects_xlsx(client):
    cli, root = client
    bid = _seed_batch(root)
    r = _post(cli, bid, "purchase_invoice", "inv.xlsx", _xlsx(),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 400
    assert "'.xlsx' not allowed" in r.text


def test_sad_rejected_with_pointer_to_dedicated_route(client):
    cli, root = client
    bid = _seed_batch(root)
    r = _post(cli, bid, "sad", "sad.pdf", _pdf(), "application/pdf")
    assert r.status_code == 422
    assert "SAD" in r.text and "route" in r.text


def test_unknown_document_type_rejected(client):
    cli, root = client
    bid = _seed_batch(root)
    r = _post(cli, bid, "made_up_type", "x.pdf", _pdf(), "application/pdf")
    assert r.status_code == 422
    assert "Unknown document_type" in r.text


def test_missing_batch_returns_404(client):
    cli, _ = client
    r = _post(cli, "NO-SUCH-BATCH", "purchase_invoice", "inv.pdf",
              _pdf(), "application/pdf")
    assert r.status_code == 404


# ── Contractor inheritance ───────────────────────────────────────────────

def test_explicit_contractor_id_wins_over_inherited(client):
    cli, root = client
    bid = _seed_batch(root)
    _seed_resolution(root, bid, "supplier", "INHERITED-SUP")

    r = _post(cli, bid, "purchase_invoice", "inv.pdf", _pdf(),
              "application/pdf", supplier_contractor_id="EXPLICIT-SUP")
    assert r.status_code == 200
    assert r.json()["contractor"]["supplier_contractor_id"] == "EXPLICIT-SUP"


def test_inherited_supplier_from_packing_contractor_resolution(client):
    cli, root = client
    bid = _seed_batch(root)
    _seed_resolution(root, bid, "supplier", "RES-SUP-7")

    r = _post(cli, bid, "purchase_packing_list", "p.xlsx", _xlsx(),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 200
    body = r.json()
    assert body["contractor"]["supplier_contractor_id"] == "RES-SUP-7"
    assert body["contractor"]["client_contractor_id"]   == ""


def test_inherited_client_from_packing_contractor_resolution(client):
    cli, root = client
    bid = _seed_batch(root)
    _seed_resolution(root, bid, "client", "RES-CLI-9")

    r = _post(cli, bid, "sales_packing_list", "sp.xlsx", _xlsx(),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    body = r.json()
    assert body["contractor"]["client_contractor_id"]   == "RES-CLI-9"
    assert body["contractor"]["supplier_contractor_id"] == ""


def test_neutral_type_inherits_both_sides(client):
    """carnet / other_document / awb inherit BOTH ids when explicit
    values are missing."""
    cli, root = client
    bid = _seed_batch(root)
    _seed_resolution(root, bid, "supplier", "S-1")
    _seed_resolution(root, bid, "client",   "C-1")

    r = _post(cli, bid, "carnet", "ata.pdf", _pdf(), "application/pdf")
    body = r.json()
    assert body["contractor"]["supplier_contractor_id"] == "S-1"
    assert body["contractor"]["client_contractor_id"]   == "C-1"


# ── Parser failure is non-fatal ──────────────────────────────────────────

def test_parser_failure_does_not_break_endpoint(client, monkeypatch):
    """Force the packing parser to throw and confirm the endpoint still
    returns 200 with parser_status='extraction_failed'."""
    cli, root = client
    bid = _seed_batch(root)

    from app.api import routes_intake
    def _boom(*a, **kw):
        raise RuntimeError("simulated parser failure")
    monkeypatch.setattr(routes_intake, "process_packing_upload", _boom)

    r = _post(cli, bid, "purchase_packing_list", "p.xlsx", _xlsx(),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 200
    body = r.json()
    assert body["parser_status"] == "extraction_failed"
    assert body["document_id"]              # row still registered


# ── Side-effect safety: source-grep guard ────────────────────────────────

def test_endpoint_block_does_not_reference_external_systems():
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes_intake.py").read_text(encoding="utf-8")
    start = src.index("# ── Generic add-document endpoint (post-draft)")
    # Block ends at the next top-level marker (sales-packing/reingest or
    # module EOF).
    try:
        end = src.index("@router.post(\"/sales-packing/reingest\"", start)
    except ValueError:
        end = len(src)
    block = src[start:end]
    for forbidden in (
        "send_email", "queue_email", "smtp",
        "create_pz", "generate_pz",
        "wfirma_client", "wfirma_api",
        "proforma_create", "proforma_issue", "proforma_post",
        "process_sad", "trigger_clearance", "dhl_dispatch",
        "dhl_express", "regenerateDsk", "regenerate_dsk",
    ):
        assert forbidden not in block, f"add-document must not reference {forbidden!r}"


def test_endpoint_registered_with_documented_path():
    """Quick wiring check — main app must expose the new route."""
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/api/v1/shipment/{batch_id}/add-document" in paths
