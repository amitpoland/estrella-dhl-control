"""test_document_db_contractor_ids.py — shipment_documents now carries
client_contractor_id and supplier_contractor_id columns.

The two columns are nullable (DEFAULT ''), additive, no FK. Existing rows
are unaffected. Existing register_document callers without the new kwargs
keep working (defaults to empty string).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def test_shipment_documents_has_contractor_id_columns(tmp_path):
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")

    with sqlite3.connect(str(tmp_path / "documents.db")) as conn:
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info(shipment_documents)"
        ).fetchall()}
    assert "client_contractor_id"   in cols
    assert "supplier_contractor_id" in cols


def test_register_document_default_blank_contractor_ids(tmp_path):
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")

    doc_id = ddb.register_document(
        batch_id="B1", document_type="purchase_invoice",
        file_name="x.pdf", file_path="/tmp/x.pdf",
        file_hash="h1",
    )
    assert doc_id

    with sqlite3.connect(str(tmp_path / "documents.db")) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM shipment_documents WHERE id=?", (doc_id,)
        ).fetchone()
    assert row["client_contractor_id"]   == ""
    assert row["supplier_contractor_id"] == ""


def test_register_document_persists_supplier_contractor_id(tmp_path):
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")

    doc_id = ddb.register_document(
        batch_id="B1", document_type="purchase_packing_list",
        file_name="p.pdf", file_path="/tmp/p.pdf",
        file_hash="h2",
        supplier_contractor_id="SUP-42",
    )
    with sqlite3.connect(str(tmp_path / "documents.db")) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM shipment_documents WHERE id=?", (doc_id,)
        ).fetchone()
    assert row["supplier_contractor_id"] == "SUP-42"
    assert row["client_contractor_id"]   == ""


def test_register_document_persists_client_contractor_id(tmp_path):
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")

    doc_id = ddb.register_document(
        batch_id="B1", document_type="sales_packing_list",
        file_name="s.pdf", file_path="/tmp/s.pdf",
        file_hash="h3",
        client_contractor_id="CLI-7",
    )
    with sqlite3.connect(str(tmp_path / "documents.db")) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM shipment_documents WHERE id=?", (doc_id,)
        ).fetchone()
    assert row["client_contractor_id"]   == "CLI-7"
    assert row["supplier_contractor_id"] == ""


def test_alter_column_idempotent_on_existing_db(tmp_path):
    """Init a DB with the OLD schema (no new columns), then re-init: the
    forward-compat ALTER must add the columns without error."""
    db = tmp_path / "documents.db"
    # Create an older-style table missing the new columns.
    with sqlite3.connect(str(db)) as conn:
        conn.executescript("""
            CREATE TABLE shipment_documents (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                awb TEXT NOT NULL DEFAULT '',
                document_type TEXT NOT NULL,
                file_name TEXT NOT NULL DEFAULT '',
                canonical_file_name TEXT NOT NULL DEFAULT '',
                file_path TEXT NOT NULL DEFAULT '',
                file_hash TEXT NOT NULL DEFAULT '',
                parser_name TEXT NOT NULL DEFAULT '',
                parser_version TEXT NOT NULL DEFAULT '',
                parser_status TEXT NOT NULL DEFAULT 'pending',
                extraction_status TEXT NOT NULL DEFAULT 'pending',
                requires_manual_review INTEGER NOT NULL DEFAULT 0,
                related_invoice_no TEXT NOT NULL DEFAULT '',
                related_mrn TEXT NOT NULL DEFAULT '',
                related_pz_no TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'upload',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

    from app.services import document_db as ddb
    ddb.init_document_db(db)
    with sqlite3.connect(str(db)) as conn:
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info(shipment_documents)"
        ).fetchall()}
    assert "client_contractor_id"   in cols
    assert "supplier_contractor_id" in cols
