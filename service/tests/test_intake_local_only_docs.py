"""test_intake_local_only_docs.py — Atlas local-only doc types.

Confirms /api/v1/shipment/intake now persists service_invoice / carnet /
other_document uploads as shipment_documents rows with correct
contractor IDs, and that the operator note is captured in audit.json.

Hard rules verified:
- No parser is invoked for these types (they are not in invoice/packing
  extraction paths).
- No DHL/PZ/SAD/wFirma/proforma side-effect (asserted by absence of
  related document rows / by source-grep of the route).
"""
from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("STORAGE_ROOT",    str(tmp_path))
    # Ensure all storage roots inside settings resolve to tmp_path.
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    from app.main import app
    from app.services import document_db as ddb
    from app.services import wfirma_db   as wfdb
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    yield TestClient(app), tmp_path


def _auth():
    from app.core.config import settings
    return {"X-API-Key": getattr(settings, "api_key", None) or "test-key"}


def _pdf_bytes(label: str = b"%PDF-1.4\n%test\n") -> bytes:
    return label


def test_service_invoice_carnet_other_persist_with_contractor_ids(client):
    cli, root = client
    files = [
        ("invoices",         ("inv1.pdf",    io.BytesIO(_pdf_bytes()), "application/pdf")),
        ("service_invoices", ("dhl_fee.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")),
        ("carnet_docs",      ("ata.pdf",     io.BytesIO(_pdf_bytes()), "application/pdf")),
        ("other_docs",       ("misc.pdf",    io.BytesIO(_pdf_bytes()), "application/pdf")),
    ]
    metadata = {
        "purchase_blocks": [{
            "invoice_index": 0, "packing_index": -1,
            "supplier_name": "", "supplier_contractor_id": "SUP-100",
        }],
        "sales_blocks":   [],
        "service_blocks": [{"supplier_contractor_id": "SUP-100", "client_contractor_id": ""}],
        "carnet_blocks":  [{"supplier_contractor_id": "SUP-100", "client_contractor_id": "CLI-200"}],
        "other_blocks":   [{"supplier_contractor_id": "SUP-100", "client_contractor_id": "CLI-200"}],
        "note":           "Test note — preserve me",
    }
    form = {"tracking_no": "TST-AWB-1", "carrier": "DHL",
            "metadata": json.dumps(metadata)}

    r = cli.post("/api/v1/shipment/intake", data=form, files=files, headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["local_documents"]["service_invoice"] == 1
    assert body["local_documents"]["carnet"]          == 1
    assert body["local_documents"]["other_document"]  == 1
    assert body["operator_note"] == "Test note — preserve me"

    # Confirm rows + contractor IDs in document_db
    with sqlite3.connect(str(root / "documents.db")) as conn:
        conn.row_factory = sqlite3.Row
        rows = {r["document_type"]: r for r in conn.execute(
            "SELECT document_type, supplier_contractor_id, client_contractor_id, file_name "
            "FROM shipment_documents WHERE batch_id=?", (body["batch_id"],)
        ).fetchall()}
    assert "service_invoice" in rows
    assert rows["service_invoice"]["supplier_contractor_id"] == "SUP-100"
    assert rows["service_invoice"]["client_contractor_id"]   == ""
    assert "carnet" in rows
    assert rows["carnet"]["supplier_contractor_id"] == "SUP-100"
    assert rows["carnet"]["client_contractor_id"]   == "CLI-200"
    assert "other_document" in rows
    assert rows["other_document"]["supplier_contractor_id"] == "SUP-100"
    assert rows["other_document"]["client_contractor_id"]   == "CLI-200"


def test_operator_note_persisted_in_audit_json(client):
    cli, root = client
    files = [
        ("invoices", ("inv.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")),
    ]
    form = {"tracking_no": "TST-AWB-2", "carrier": "DHL",
            "metadata": json.dumps({"note": "audit-note-roundtrip"})}
    r = cli.post("/api/v1/shipment/intake", data=form, files=files, headers=_auth())
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    # audit.json lives under the batch output folder.
    matches = list(root.rglob("audit.json"))
    found = [p for p in matches if batch_id in str(p)]
    assert found, "audit.json for batch missing"
    audit = json.loads(found[0].read_text(encoding="utf-8"))
    assert audit.get("operator_note") == "audit-note-roundtrip"


def test_no_dhl_pz_sad_wfirma_proforma_side_effect_for_local_docs(client):
    """Source-grep: the local-doc persistence block must not import any
    DHL / PZ / SAD / wFirma / proforma module symbol at runtime."""
    src = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_intake.py"
    text = src.read_text(encoding="utf-8")
    start = text.index("# ── E2. Local-only Atlas document types")
    end   = text.index("# ── F. Write draft audit", start)
    block = text[start:end]
    for forbidden in (
        "dhl_", "pz_", "sad_", "wfirma_", "proforma_",
        "trigger_clearance", "issue_proforma", "create_pz",
        "process_packing_upload", "parse_invoice_pdf",
    ):
        assert forbidden not in block, \
            f"local-doc persistence must not reference {forbidden!r}"
