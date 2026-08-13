"""B-002: sales-document identity must be sole-authority via ensure_sales_document_id.

store_sales_document must not mint a second UUID-backed identity for the same
shipment_documents.id (document_id). Same logical document → same persistent id
across retry and alternate intake writers.
"""
from __future__ import annotations

import uuid

import pytest

from app.services import document_db as ddb


@pytest.fixture()
def docdb(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _count_for_document(batch_id: str, document_id: str) -> int:
    rows = [
        r for r in ddb.get_sales_documents(batch_id)
        if r.get("document_id") == document_id
    ]
    return len(rows)


def test_store_sales_document_twice_same_document_one_row(docdb):
    """Same logical sales document submitted twice → one persisted identity."""
    B = "B002_DUP"
    doc_id = str(uuid.uuid4())  # shipment_documents.id from register_document
    data = {
        "client_name": "ACME",
        "client_ref": "PO-1",
        "document_type": "sales_invoice",
        "source_file_path": "/tmp/a.pdf",
        "extraction_status": "pending",
        "client_contractor_id": "CL-1",
    }
    a = ddb.store_sales_document(B, doc_id, data)
    b = ddb.store_sales_document(B, doc_id, data)
    assert a == b == doc_id
    assert _count_for_document(B, doc_id) == 1
    row = next(r for r in ddb.get_sales_documents(B) if r["document_id"] == doc_id)
    assert row["id"] == doc_id
    assert row["client_name"] == "ACME"
    assert row["client_contractor_id"] == "CL-1"


def test_ensure_and_store_same_document_converge(docdb):
    """Both live intake authority paths (ensure vs store wrapper) → same ID."""
    B = "B002_BOTH"
    doc_id = str(uuid.uuid4())
    e = ddb.ensure_sales_document_id(
        B, doc_id,
        client_name="X",
        document_type="sales_invoice",
        source_file_path="/tmp/x.pdf",
        client_contractor_id="CL-X",
    )
    s = ddb.store_sales_document(
        B, doc_id,
        {
            "client_name": "X",
            "document_type": "sales_invoice",
            "source_file_path": "/tmp/x.pdf",
            "extraction_status": "pending",
            "client_contractor_id": "CL-X",
        },
    )
    assert e == s == doc_id
    assert _count_for_document(B, doc_id) == 1


def test_distinct_documents_keep_distinct_ids(docdb):
    B = "B002_DISTINCT"
    d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
    a = ddb.store_sales_document(B, d1, {"document_type": "sales_invoice", "client_name": "A"})
    b = ddb.store_sales_document(B, d2, {"document_type": "sales_invoice", "client_name": "B"})
    assert a == d1 and b == d2 and a != b
    assert _count_for_document(B, d1) == 1
    assert _count_for_document(B, d2) == 1


def test_multi_file_sales_docs_stable_per_document(docdb):
    """Multi-file sales-document slot: each logical document_id gets one row."""
    B = "B002_MULTI"
    docs = [str(uuid.uuid4()) for _ in range(3)]
    for doc_id in docs:
        ddb.store_sales_document(
            B, doc_id,
            {"document_type": "sales_invoice", "client_name": "M", "extraction_status": "pending"},
        )
        ddb.store_sales_document(
            B, doc_id,
            {"document_type": "sales_invoice", "client_name": "M", "extraction_status": "pending"},
        )
    all_rows = ddb.get_sales_documents(B)
    assert len(all_rows) == 3
    assert {r["id"] for r in all_rows} == set(docs)


def test_store_does_not_silently_merge_distinct_clients_on_different_docs(docdb):
    B = "B002_NOMERGE"
    d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
    ddb.store_sales_document(B, d1, {"client_name": "Alpha", "document_type": "sales_invoice"})
    ddb.store_sales_document(B, d2, {"client_name": "Beta", "document_type": "sales_invoice"})
    by_id = {r["id"]: r for r in ddb.get_sales_documents(B)}
    assert by_id[d1]["client_name"] == "Alpha"
    assert by_id[d2]["client_name"] == "Beta"
