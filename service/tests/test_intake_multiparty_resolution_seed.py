"""test_intake_multiparty_resolution_seed.py — cross-document contractor
contamination via the intake per-batch resolution seed.

``packing_contractor_resolution`` is UNIQUE(batch_id, role): it can hold
exactly ONE client and ONE supplier per batch. ``link_as_sales``
(routes_packing.py) already refuses to seed it when a batch resolves to
more than one operator-selected contractor, because a multi-party batch
"cannot be represented there without misrouting".

Atlas intake seeds the same store from the FIRST non-empty contractor id
found across ``purchase_blocks`` / ``sales_blocks``. On a multi-party
intake that silently records document #1's contractor as the batch-level
``status='confirmed'`` / ``confidence=1.0`` authority — an identity the
operator never confirmed at batch level — which ``_resolve_customer``
step 0b then hands to EVERY proforma draft on the batch that does not
resolve per-document.

These tests assert the ``link_as_sales`` invariant at the intake boundary.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    from app.main import app
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
    for cid, name in (("CL-A", "Alpha Buyer GmbH"), ("CL-B", "Beta Buyer SARL")):
        cmdb.upsert_customer(cm_path, CustomerMaster(
            bill_to_contractor_id=cid, bill_to_name=name,
            country="DE", nip="DE" + cid,
        ))
    supdb.init_db(sup_path)
    sup_a = supdb.create_supplier(sup_path, {
        "supplier_code": "SUP-A", "name": "Alpha Atelier", "country": "IT"})
    sup_b = supdb.create_supplier(sup_path, {
        "supplier_code": "SUP-B", "name": "Beta Atelier", "country": "IT"})
    return TestClient(app), str(sup_a), str(sup_b)


def _pdf(): return io.BytesIO(b"%PDF-1.4\n%test\n")


def test_two_clients_do_not_seed_a_batch_level_client(client):
    """Two sales documents, two different operator-picked clients.

    Neither is the batch's client, so no per-batch row may be written.
    """
    cli, _, _ = client
    r = cli.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "RS-MULTI-CLI", "carrier": "DHL",
              "metadata": json.dumps({
                  "purchase_blocks": [],
                  "sales_blocks": [
                      {"document_index": 0, "packing_index": -1,
                       "client_name": "", "client_contractor_id": "CL-A"},
                      {"document_index": 1, "packing_index": -1,
                       "client_name": "", "client_contractor_id": "CL-B"},
                  ],
              })},
        files=[("invoices", ("i1.pdf", _pdf(), "application/pdf")),
               ("sales_documents", ("s1.pdf", _pdf(), "application/pdf")),
               ("sales_documents", ("s2.pdf", _pdf(), "application/pdf"))],
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    g = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution/client")
    assert g.status_code == 404, (
        "multi-client intake seeded a batch-level client authority "
        f"= {g.json().get('matched_master_id')!r}; every proforma draft on "
        "this batch that falls through to resolver step 0b now resolves to "
        "that one contractor. link_as_sales refuses to seed this case."
    )


def test_two_suppliers_do_not_seed_a_batch_level_supplier(client):
    """Same invariant on the purchase side."""
    cli, sup_a, sup_b = client
    r = cli.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "RS-MULTI-SUP", "carrier": "DHL",
              "metadata": json.dumps({
                  "purchase_blocks": [
                      {"invoice_index": 0, "packing_index": -1,
                       "supplier_name": "", "supplier_contractor_id": sup_a},
                      {"invoice_index": 1, "packing_index": -1,
                       "supplier_name": "", "supplier_contractor_id": sup_b},
                  ],
                  "sales_blocks": [],
              })},
        files=[("invoices", ("i1.pdf", _pdf(), "application/pdf")),
               ("invoices", ("i2.pdf", _pdf(), "application/pdf"))],
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    g = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution/supplier")
    assert g.status_code == 404, (
        "multi-supplier intake seeded a batch-level supplier authority "
        f"= {g.json().get('matched_master_id')!r}"
    )


def test_single_party_intake_still_seeds(client):
    """Guard against over-correction: the single-party case must keep working.

    ``{A,A}`` across two purchase blocks is still one distinct contractor —
    a legitimate batch-level seed (same as ``{A}``).
    """
    cli, sup_a, _ = client
    r = cli.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "RS-SINGLE", "carrier": "DHL",
              "metadata": json.dumps({
                  "purchase_blocks": [
                      {"invoice_index": 0, "packing_index": -1,
                       "supplier_name": "", "supplier_contractor_id": sup_a},
                      {"invoice_index": 1, "packing_index": -1,
                       "supplier_name": "", "supplier_contractor_id": sup_a},
                  ],
                  "sales_blocks": [
                      {"document_index": 0, "packing_index": -1,
                       "client_name": "", "client_contractor_id": "CL-A"},
                  ],
              })},
        files=[("invoices", ("i1.pdf", _pdf(), "application/pdf")),
               ("invoices", ("i2.pdf", _pdf(), "application/pdf")),
               ("sales_documents", ("s1.pdf", _pdf(), "application/pdf"))],
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    gs = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution/supplier")
    assert gs.status_code == 200, gs.text
    assert str(gs.json()["matched_master_id"]) == sup_a
    gc = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution/client")
    assert gc.status_code == 200, gc.text
    assert str(gc.json()["matched_master_id"]) == "CL-A"


def test_multiparty_falls_through_to_per_document_not_step_0b(client, tmp_path):
    """Multi-client intake must not feed Pro Forma resolver step 0b.

    After intake: no batch-level packing_contractor_resolution row.
    Per-document authority (draft contractor id → Customer Master) still
    resolves each party independently. Step 0b
    (``derive_customer_resolution_via_packing``) must return None so it
    cannot wrong-route every draft on the batch.
    """
    cli, _, _ = client
    r = cli.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "RS-MULTI-0B", "carrier": "DHL",
              "metadata": json.dumps({
                  "purchase_blocks": [],
                  "sales_blocks": [
                      {"document_index": 0, "packing_index": -1,
                       "client_name": "Alpha Buyer GmbH",
                       "client_contractor_id": "CL-A"},
                      {"document_index": 1, "packing_index": -1,
                       "client_name": "Beta Buyer SARL",
                       "client_contractor_id": "CL-B"},
                  ],
              })},
        files=[("invoices", ("i1.pdf", _pdf(), "application/pdf")),
               ("sales_documents", ("s1.pdf", _pdf(), "application/pdf")),
               ("sales_documents", ("s2.pdf", _pdf(), "application/pdf"))],
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    g = cli.get(f"/api/v1/packing/{batch_id}/contractor-resolution/client")
    assert g.status_code == 404, g.text

    from app.core.config import settings
    from app.services.customer_resolution_authority import (
        derive_customer_authority_for_draft,
        derive_customer_resolution_via_packing,
    )

    packing_db = settings.storage_root / "packing_resolutions.sqlite"
    cm_db = settings.storage_root / "customer_master.sqlite"
    docs_db = settings.storage_root / "documents.db"

    step_0b = derive_customer_resolution_via_packing(
        batch_id=batch_id,
        client_name="Alpha Buyer GmbH",
        customer_master_db_path=cm_db,
        packing_resolution_db_path=packing_db,
    )
    assert step_0b is None, (
        "step 0b must not resolve on a multi-party batch with no seeded "
        f"batch-level row; got {step_0b!r}"
    )

    per_a = derive_customer_authority_for_draft(
        batch_id=batch_id,
        client_name="Alpha Buyer GmbH",
        documents_db_path=docs_db,
        customer_master_db_path=cm_db,
        client_contractor_id="CL-A",
    )
    assert per_a is not None
    assert per_a["wfirma_customer_id"] == "CL-A"
    assert per_a["match_strategy"] in ("draft_contractor_id", "per_document_upload")

    per_b = derive_customer_authority_for_draft(
        batch_id=batch_id,
        client_name="Beta Buyer SARL",
        documents_db_path=docs_db,
        customer_master_db_path=cm_db,
        client_contractor_id="CL-B",
    )
    assert per_b is not None
    assert per_b["wfirma_customer_id"] == "CL-B"
    assert per_a["wfirma_customer_id"] != per_b["wfirma_customer_id"]
