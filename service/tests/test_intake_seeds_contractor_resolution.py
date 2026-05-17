"""test_intake_seeds_contractor_resolution.py — regression for the
post-deploy Atlas gap where operator-picked client/supplier IDs were
captured on shipment_documents but never reflected in the
ContractorResolutionPanel (which reads packing_contractor_resolution).

Atlas intake now seeds packing_contractor_resolution with status='confirmed'
for each role whenever the corresponding contractor_id is present.

Hard rules verified:
  - No resolver algorithm runs.
  - No wFirma write.
  - No contractor record is created in master tables.
  - Intake remains successful even if the seed write fails.
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    from app.main import app
    # The route modules captured _DB_PATH at import time. Override those
    # module-level globals so each test sees its own tmp paths.
    from app.api import routes_packing_resolution as r_pr
    from app.api import routes_customer_master    as r_cm
    from app.api import routes_suppliers          as r_sup
    monkeypatch.setattr(r_pr,  "_DB_PATH", tmp_path / "packing_resolutions.sqlite", raising=False)
    monkeypatch.setattr(r_cm,  "_DB_PATH", tmp_path / "customer_master.sqlite",     raising=False)
    monkeypatch.setattr(r_sup, "_DB_PATH", tmp_path / "suppliers.sqlite",           raising=False)

    from app.services import customer_master_db as cmdb
    from app.services import suppliers_db as supdb
    from app.services.customer_master_db import CustomerMaster
    cm_path  = tmp_path / "customer_master.sqlite"
    sup_path = tmp_path / "suppliers.sqlite"
    cmdb.init_db(cm_path)
    cmdb.upsert_customer(cm_path, CustomerMaster(
        bill_to_contractor_id="CL-T-1",
        bill_to_name="Test Buyer GmbH",
        country="DE",
        nip="DE12345",
    ))
    supdb.init_db(sup_path)
    sup_id = supdb.create_supplier(sup_path, {
        "supplier_code": "SUP-T-1",
        "name":          "Test Atelier (IT)",
        "country":       "IT",
        "vat_id":        "IT98765",
    })
    return TestClient(app), tmp_path, str(sup_id)


def _pdf(): return io.BytesIO(b"%PDF-1.4\n%test\n")


def test_intake_with_supplier_id_seeds_supplier_resolution(client):
    cli, root, sup_id = client
    files = [("invoices", ("inv.pdf", _pdf(), "application/pdf"))]
    metadata = {
        "purchase_blocks": [{
            "invoice_index": 0, "packing_index": -1,
            "supplier_name": "", "supplier_contractor_id": sup_id,
        }],
        "sales_blocks": [],
    }
    r = cli.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "RS-SUP-1", "carrier": "DHL",
              "metadata": json.dumps(metadata)},
        files=files,
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    # Read back via the GET endpoint that the panel actually calls.
    g = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution/supplier")
    assert g.status_code == 200, g.text
    body = g.json()
    assert body["role"] == "supplier"
    assert body["status"] == "confirmed"
    assert str(body["matched_master_id"]) == sup_id
    assert body["matched_master_type"] == "suppliers"
    assert body["parsed_name"] == "Test Atelier (IT)"
    assert body["parsed_country"] == "IT"
    assert body["parsed_tax_id"] == "IT98765"
    assert body["tier"] == 1
    assert body["confidence"] == 1.0
    assert body["operator_user"] == "intake"
    assert body["operator_override"] is False


def test_intake_with_client_id_seeds_client_resolution(client):
    cli, root, _ = client
    files = [("invoices", ("inv.pdf", _pdf(), "application/pdf"))]
    metadata = {
        "purchase_blocks": [],
        "sales_blocks": [{
            "document_index": -1, "packing_index": -1,
            "client_name": "", "client_contractor_id": "CL-T-1",
        }],
    }
    r = cli.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "RS-CLI-1", "carrier": "DHL",
              "metadata": json.dumps(metadata)},
        files=files,
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    g = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution/client")
    assert g.status_code == 200, g.text
    body = g.json()
    assert body["role"] == "client"
    assert body["status"] == "confirmed"
    assert body["matched_master_id"] == "CL-T-1"
    assert body["matched_master_type"] == "customer_master"
    assert body["parsed_name"] == "Test Buyer GmbH"
    assert body["parsed_country"] == "DE"
    assert body["parsed_tax_id"] == "DE12345"
    assert body["operator_user"] == "intake"


def test_intake_without_contractor_ids_writes_no_resolution(client):
    cli, root, _ = client
    files = [("invoices", ("inv.pdf", _pdf(), "application/pdf"))]
    r = cli.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "RS-NONE-1", "carrier": "DHL", "metadata": "{}"},
        files=files,
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    g_sup = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution/supplier")
    g_cli = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution/client")
    assert g_sup.status_code == 404
    assert g_cli.status_code == 404


def test_intake_seeds_both_roles_when_both_ids_present(client):
    cli, root, sup_id = client
    files = [("invoices", ("inv.pdf", _pdf(), "application/pdf"))]
    metadata = {
        "purchase_blocks": [{"invoice_index": 0, "packing_index": -1,
                             "supplier_contractor_id": sup_id}],
        "sales_blocks":   [{"document_index": -1, "packing_index": -1,
                            "client_contractor_id": "CL-T-1"}],
    }
    r = cli.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "RS-BOTH-1", "carrier": "DHL",
              "metadata": json.dumps(metadata)},
        files=files,
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    listing = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution").json()
    roles = sorted(r["role"] for r in listing["resolutions"])
    assert roles == ["client", "supplier"]
    for row in listing["resolutions"]:
        assert row["status"] == "confirmed"
        assert row["tier"] == 1


def test_intake_seed_failure_is_nonfatal(client, monkeypatch):
    """Force the seeder to throw and confirm intake still returns 200."""
    cli, root, sup_id = client
    from app.services import packing_resolution_db as prdb
    def _boom(*a, **kw):
        raise RuntimeError("simulated seeder failure")
    monkeypatch.setattr(prdb, "upsert_resolution", _boom)

    files = [("invoices", ("inv.pdf", _pdf(), "application/pdf"))]
    metadata = {"purchase_blocks": [{
        "invoice_index": 0, "packing_index": -1,
        "supplier_contractor_id": sup_id,
    }], "sales_blocks": []}
    r = cli.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "RS-FAIL-1", "carrier": "DHL",
              "metadata": json.dumps(metadata)},
        files=files,
    )
    assert r.status_code == 200, r.text
    # No resolution row should be persisted.
    g = cli.get(f"/api/v1/packing/{r.json()['batch_id']}/contractor-resolution/supplier")
    assert g.status_code == 404


# ── Side-effect safety ───────────────────────────────────────────────────

def test_seed_block_does_not_reference_external_systems():
    """Source-grep the new seeder region for any DHL/wFirma/proforma/PZ/SAD
    write. The seed must be purely against packing_resolution_db."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes_intake.py").read_text(encoding="utf-8")
    start = src.index("# ── E3. Seed packing_contractor_resolution")
    end   = src.index("# ── F. Write draft audit", start)
    block = src[start:end]
    for forbidden in (
        "send_email", "queue_email", "smtp",
        "create_pz", "generate_pz",
        "wfirma_client", "wfirma_api",
        "proforma_create", "proforma_issue", "proforma_post",
        "process_sad", "trigger_clearance", "dhl_dispatch",
    ):
        assert forbidden not in block, f"seed block must not reference {forbidden!r}"
