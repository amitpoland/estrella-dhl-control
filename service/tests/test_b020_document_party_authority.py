"""B-020 — Document-party contractor authority (fail closed on multiparty).

Proves the pre-fix LIMIT-1 / row-order hazard, then locks the shared helper
and SAFE consumer wiring. No live MyDHL / wFirma / email / inventory writes.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services import document_db as ddb
from app.services.document_party_authority import (
    ROLE_CLIENT,
    ROLE_SUPPLIER,
    STATUS_AMBIGUOUS,
    STATUS_NONE,
    STATUS_SINGLE,
    list_distinct_party_ids,
    resolve_party_id,
)


BATCH = "B020_TEST_BATCH"


@pytest.fixture()
def docs_db(tmp_path: Path) -> Path:
    path = tmp_path / "documents.db"
    ddb.init_document_db(path)
    return path


def _reg(
    *,
    document_type: str,
    supplier: str = "",
    client: str = "",
    file_hash: str = "",
) -> str:
    did = ddb.register_document(
        batch_id=BATCH,
        document_type=document_type,
        file_name=f"{document_type}-{file_hash or supplier or client}.pdf",
        file_hash=file_hash or f"h-{document_type}-{supplier}-{client}",
        supplier_contractor_id=supplier,
        client_contractor_id=client,
    )
    assert did
    return did


# ── Helper unit pins ─────────────────────────────────────────────────────────


def test_single_party_supplier_control(docs_db: Path):
    _reg(document_type="purchase_invoice", supplier="SUP-A")
    _reg(document_type="awb", supplier="SUP-A")  # inherited — ignored for authority types
    r = resolve_party_id(docs_db, BATCH, ROLE_SUPPLIER)
    assert r.status == STATUS_SINGLE
    assert r.contractor_id == "SUP-A"
    assert r.ok


def test_two_suppliers_ambiguous(docs_db: Path):
    _reg(document_type="purchase_invoice", supplier="SUP-A", file_hash="s1")
    _reg(document_type="purchase_packing_list", supplier="SUP-B", file_hash="s2")
    r = resolve_party_id(docs_db, BATCH, ROLE_SUPPLIER)
    assert r.status == STATUS_AMBIGUOUS
    assert r.contractor_id is None
    assert r.candidates == ("SUP-A", "SUP-B")


def test_two_clients_ambiguous(docs_db: Path):
    _reg(document_type="sales_packing_list", client="CLI-A", file_hash="c1")
    _reg(document_type="sales_invoice", client="CLI-B", file_hash="c2")
    r = resolve_party_id(docs_db, BATCH, ROLE_CLIENT)
    assert r.status == STATUS_AMBIGUOUS
    assert set(r.candidates) == {"CLI-A", "CLI-B"}


def test_awb_inherited_identity_not_batch_authority(docs_db: Path):
    """AWB carrying supplier/client IDs must not invent a batch party alone."""
    _reg(document_type="awb", supplier="SUP-INHERITED", client="CLI-INHERITED")
    assert resolve_party_id(docs_db, BATCH, ROLE_SUPPLIER).status == STATUS_NONE
    assert resolve_party_id(docs_db, BATCH, ROLE_CLIENT).status == STATUS_NONE
    assert list_distinct_party_ids(docs_db, BATCH, ROLE_SUPPLIER) == []


def test_document_specific_context_overrides_batch_ambiguity(docs_db: Path):
    _reg(document_type="purchase_invoice", supplier="SUP-A", file_hash="a")
    did_b = _reg(document_type="purchase_invoice", supplier="SUP-B", file_hash="b")
    batch = resolve_party_id(docs_db, BATCH, ROLE_SUPPLIER)
    assert batch.status == STATUS_AMBIGUOUS
    one = resolve_party_id(docs_db, BATCH, ROLE_SUPPLIER, document_id=did_b)
    assert one.status == STATUS_SINGLE
    assert one.contractor_id == "SUP-B"


def test_legacy_limit1_picks_wrong_role_via_awb_row_order(docs_db: Path):
    """Reproduction of the pre-B-020 hazard: AWB inserted first wins LIMIT 1."""
    _reg(document_type="awb", supplier="SUP-WRONG", file_hash="awb")
    _reg(document_type="purchase_invoice", supplier="SUP-RIGHT", file_hash="inv")
    con = sqlite3.connect(str(docs_db))
    try:
        row = con.execute(
            "SELECT supplier_contractor_id FROM shipment_documents "
            "WHERE batch_id=? AND supplier_contractor_id != '' LIMIT 1",
            (BATCH,),
        ).fetchone()
    finally:
        con.close()
    assert row[0] == "SUP-WRONG"  # present failure: wrong party via row order
    # Authority helper must not follow that trap
    r = resolve_party_id(docs_db, BATCH, ROLE_SUPPLIER)
    assert r.status == STATUS_SINGLE
    assert r.contractor_id == "SUP-RIGHT"


# ── Consumer wiring ──────────────────────────────────────────────────────────


def test_customs_identity_uses_purchase_not_awb(tmp_path: Path, monkeypatch):
    from app.api import routes_dhl_clearance as rdc
    from app.core import config as cfg

    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(cfg.settings, "storage_root", storage)
    target = storage / "documents.db"
    ddb.init_document_db(target)
    _reg(document_type="awb", supplier="99", file_hash="awb2")
    _reg(document_type="purchase_invoice", supplier="42", file_hash="inv2")

    import sqlite3 as sq

    sdb = storage / "suppliers.sqlite"
    with sq.connect(str(sdb)) as con:
        con.execute(
            "CREATE TABLE suppliers (id TEXT PRIMARY KEY, name TEXT, wfirma_id TEXT)"
        )
        con.execute(
            "INSERT INTO suppliers (id, name) VALUES ('42', 'Right Supplier Ltd')"
        )
        con.execute(
            "INSERT INTO suppliers (id, name) VALUES ('99', 'Wrong AWB Co')"
        )

    _consignee, consignor = rdc._resolve_customs_identities(BATCH)
    assert consignor == "Right Supplier Ltd"


def test_customs_identity_ambiguous_fail_closed(tmp_path: Path, monkeypatch):
    from app.api import routes_dhl_clearance as rdc
    from app.core import config as cfg

    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(cfg.settings, "storage_root", storage)
    ddb.init_document_db(storage / "documents.db")
    _reg(document_type="purchase_invoice", supplier="S1", file_hash="a")
    _reg(document_type="purchase_packing_list", supplier="S2", file_hash="b")
    sentinel = rdc._get_unresolved_sentinel()
    _c, consignor = rdc._resolve_customs_identities(BATCH)
    assert consignor == sentinel


def test_ai_snapshot_skips_ambiguous_client(tmp_path: Path, monkeypatch):
    from app.services import ai_reverification as air

    storage = tmp_path / "storage"
    storage.mkdir()
    docs = storage / "documents.db"
    ddb.init_document_db(docs)
    _reg(document_type="sales_packing_list", client="C1", file_hash="c1")
    _reg(document_type="sales_invoice", client="C2", file_hash="c2")
    snap = air.build_masters_snapshot({"batch_id": BATCH}, storage)
    assert snap.client_row is None


def test_doc_package_prefers_party_id_over_name_and_fails_closed(
    tmp_path: Path, monkeypatch
):
    from app.services.carrier import doc_package as dp

    storage = tmp_path / "storage"
    storage.mkdir()
    docs = storage / "documents.db"
    ddb.init_document_db(docs)
    _reg(document_type="sales_packing_list", client="CID-RIGHT", file_hash="sp")
    _reg(document_type="awb", client="CID-WRONG", file_hash="awb")

    cm = storage / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as con:
        con.execute(
            "CREATE TABLE customer_master ("
            "bill_to_contractor_id TEXT PRIMARY KEY, bill_to_name TEXT, "
            "ship_to_name TEXT, ship_to_street TEXT, ship_to_city TEXT, "
            "ship_to_zip TEXT, ship_to_country TEXT, ship_to_phone TEXT, "
            "ship_to_email TEXT, ship_to_person TEXT, ship_to_use_alternate INTEGER)"
        )
        con.execute(
            "INSERT INTO customer_master (bill_to_contractor_id, bill_to_name) "
            "VALUES ('CID-RIGHT', 'Right Client')"
        )
        con.execute(
            "INSERT INTO customer_master (bill_to_contractor_id, bill_to_name) "
            "VALUES ('CID-WRONG', 'Wrong Client')"
        )

    view = dp._resolve_customer_from_batch(BATCH, client_name=None, storage_root=storage)
    assert view is not None
    assert view.bill_to_name == "Right Client"

    # Multiparty → None
    _reg(document_type="sales_invoice", client="CID-OTHER", file_hash="si")
    assert (
        dp._resolve_customer_from_batch(BATCH, client_name=None, storage_root=storage)
        is None
    )


def test_intelligence_graph_supplier_ambiguous_none(tmp_path: Path):
    from app.services import intelligence_graph as ig

    docs = tmp_path / "documents.db"
    ddb.init_document_db(docs)
    _reg(document_type="purchase_invoice", supplier="S1", file_hash="a")
    _reg(document_type="purchase_packing_list", supplier="S2", file_hash="b")
    assert ig._resolve_supplier_contractor_id(BATCH, docs) is None
