"""C1 — Customer Master usage projection regression pins."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402
from app.services.customer_usage import project_customer_usage  # noqa: E402
from app.services.customer_master_db import (  # noqa: E402
    CustomerMaster,
    init_db as cm_init,
    upsert_customer,
)


def _init_docs(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE shipment_documents (
          id TEXT PRIMARY KEY,
          batch_id TEXT,
          document_type TEXT,
          original_filename TEXT,
          client_contractor_id TEXT NOT NULL DEFAULT '',
          supplier_contractor_id TEXT NOT NULL DEFAULT '',
          created_at TEXT
        );
        CREATE TABLE sales_documents (
          id TEXT PRIMARY KEY,
          batch_id TEXT,
          sales_doc_no TEXT,
          client_name TEXT,
          client_contractor_id TEXT NOT NULL DEFAULT '',
          created_at TEXT,
          updated_at TEXT
        );
        """
    )
    con.commit()
    con.close()


def _init_links(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE proforma_drafts (
          id INTEGER PRIMARY KEY,
          batch_id TEXT,
          client_name TEXT,
          status TEXT,
          draft_state TEXT,
          client_contractor_id TEXT NOT NULL DEFAULT '',
          wfirma_proforma_id TEXT,
          wfirma_proforma_fullnumber TEXT,
          created_at TEXT,
          updated_at TEXT
        );
        CREATE TABLE proforma_invoice_links (
          id INTEGER PRIMARY KEY,
          proforma_id TEXT NOT NULL UNIQUE,
          proforma_number TEXT,
          invoice_id TEXT,
          invoice_number TEXT,
          converted_at TEXT,
          operator TEXT,
          source_total TEXT,
          currency TEXT,
          status TEXT,
          notes TEXT
        );
        """
    )
    con.commit()
    con.close()


def _init_carrier(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE carrier_shipments (
          id INTEGER PRIMARY KEY,
          batch_id TEXT,
          client_ref TEXT,
          tracking_ref TEXT,
          state TEXT,
          created_at TEXT,
          updated_at TEXT
        );
        """
    )
    con.commit()
    con.close()


@pytest.fixture()
def usage_root(tmp_path):
    docs = tmp_path / "documents.db"
    links = tmp_path / "proforma_links.db"
    carrier = tmp_path / "carrier" / "carrier_shipments.db"
    _init_docs(docs)
    _init_links(links)
    _init_carrier(carrier)
    return tmp_path


def test_empty_usage_is_zero(usage_root):
    out = project_customer_usage(usage_root, "203763363")
    assert out["sales_packing"]["count"] == 0
    assert out["purchase_packing"]["count"] == 0
    assert out["proformas"]["count"] == 0
    assert out["invoices"]["count"] == 0
    assert out["shipments"]["count"] == 0


def test_counts_use_exact_contractor_id(usage_root):
    docs = usage_root / "documents.db"
    con = sqlite3.connect(docs)
    con.execute(
        "INSERT INTO sales_documents VALUES (?,?,?,?,?,?,?)",
        ("sd1", "BATCH_A", "PL-1", "Eldoradoo", "203763363", "2026-08-01", "2026-08-01"),
    )
    con.execute(
        "INSERT INTO sales_documents VALUES (?,?,?,?,?,?,?)",
        ("sd2", "BATCH_B", "PL-2", "Other", "999", "2026-08-01", "2026-08-01"),
    )
    con.execute(
        "INSERT INTO shipment_documents VALUES (?,?,?,?,?,?,?)",
        ("pk1", "BATCH_A", "purchase_packing_list", "pack.pdf", "203763363", "sup1", "2026-08-01"),
    )
    con.commit()
    con.close()

    links = usage_root / "proforma_links.db"
    con = sqlite3.connect(links)
    con.execute(
        "INSERT INTO proforma_drafts VALUES (?,?,?,?,?,?,?,?,?,?)",
        (1, "BATCH_A", "Eldoradoo", "issued", "posted", "203763363", "WF1", "PF/1", "2026-08-01", "2026-08-01"),
    )
    con.execute(
        """INSERT INTO proforma_invoice_links
           (id, proforma_id, proforma_number, invoice_id, invoice_number,
            converted_at, operator, source_total, currency, status, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (1, "WF1", "PF/1", "INV1", "FV/1", "2026-08-02", "op", "10", "PLN", "issued", None),
    )
    con.commit()
    con.close()

    carrier = usage_root / "carrier" / "carrier_shipments.db"
    con = sqlite3.connect(carrier)
    con.execute(
        "INSERT INTO carrier_shipments VALUES (?,?,?,?,?,?,?)",
        (1, "BATCH_A", "Eldoradoo", "1234567890", "booked", "2026-08-01", "2026-08-01"),
    )
    # Name-similar but wrong batch — must NOT count via name
    con.execute(
        "INSERT INTO carrier_shipments VALUES (?,?,?,?,?,?,?)",
        (2, "BATCH_OTHER", "Eldoradoo", "9999999999", "booked", "2026-08-01", "2026-08-01"),
    )
    con.commit()
    con.close()

    out = project_customer_usage(usage_root, "203763363")
    assert out["sales_packing"]["count"] == 1
    assert out["purchase_packing"]["count"] == 1
    assert out["proformas"]["count"] == 1
    assert out["invoices"]["count"] == 1
    assert out["shipments"]["count"] == 1
    assert out["shipments"]["recent_refs"][0]["awb"] == "1234567890"

    other = project_customer_usage(usage_root, "999")
    assert other["sales_packing"]["count"] == 1
    assert other["proformas"]["count"] == 0
    assert other["shipments"]["count"] == 0


def test_no_usage_db_module_created():
    svc = Path(__file__).resolve().parent.parent / "app" / "services"
    assert not (svc / "usage_db.py").exists()
    assert (svc / "customer_usage.py").exists()


def test_route_usage_endpoint(tmp_path, monkeypatch):
    cm = tmp_path / "customer_master.sqlite"
    cm_init(cm)
    upsert_customer(
        cm,
        CustomerMaster(
            bill_to_contractor_id="203763363",
            bill_to_name="Eldoradoo",
            country="PL",
            nip="7010326020",
        ),
    )
    # Leave documents/proforma/carrier absent — projection returns zero with db_missing notes.
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key")
    import app.api.routes_customer_master as rcm
    monkeypatch.setattr(rcm, "_DB_PATH", cm)

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get(
            "/api/v1/customer-master/203763363/usage",
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 200, r.text[:500]
        body = r.json()
        assert body["customer_identity"]["bill_to_contractor_id"] == "203763363"
        assert body["sales_packing"]["count"] == 0
        assert "source_health" in body

        missing = client.get(
            "/api/v1/customer-master/no-such/usage",
            headers={"X-API-Key": "test-key"},
        )
        assert missing.status_code == 404


def test_master_page_no_client_usage_pending():
    src = (
        Path(__file__).resolve().parent.parent
        / "app/static/v2/master-page.jsx"
    ).read_text(encoding="utf-8")
    # clients pending list must be empty; usage panel + getCustomerUsage wired
    assert "ClientUsagePanel" in src
    assert "getCustomerUsage" in (
        Path(__file__).resolve().parent.parent / "app/static/v2/pz-api.js"
    ).read_text(encoding="utf-8")
    assert "Purchase packing list usage — no endpoint" not in src
