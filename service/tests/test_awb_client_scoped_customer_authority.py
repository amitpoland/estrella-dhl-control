"""AWB customer authority — an outbound booking is scoped by its commercial document.

Regression: an import batch may carry several commercial customers.  The AWB
booking path resolved the recipient through batch-level document-party
resolution only, which fails closed as AMBIGUOUS on such a batch — so
``POST /api/v1/carrier/{batch_id}/shipment`` answered 422 CUSTOMER_NOT_FOUND
even though the operator had already named the client and that client's own
proforma draft carried ``client_contractor_id``.

Fixed at the owning authority (``doc_package._resolve_customer_from_batch``),
so every consumer — AWB address, CMR, packing list, shipping information,
label package, return draft — gains the same client scope.  Unscoped callers
still fail closed: the ambiguity guard is not weakened, it is bypassed only by
a stronger, explicit document identifier.

Synthetic fixtures only. No live MyDHL / wFirma / email writes.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services import document_db as ddb
from app.services import proforma_invoice_link_db as pildb
from app.services.carrier import doc_package as dp

BATCH = "SHIPMENT_1234567890_2026-08_abcdef01"

CLIENT_A, CID_A = "Alpha Trading BV", "CID-ALPHA"
CLIENT_B, CID_B = "Beta Handels GmbH", "CID-BETA"


def _register(document_type: str, client: str, file_hash: str) -> None:
    ddb.register_document(
        batch_id=BATCH,
        document_type=document_type,
        file_name=f"{document_type}-{file_hash}.pdf",
        file_hash=file_hash,
        supplier_contractor_id="",
        client_contractor_id=client,
    )


def _draft(storage: Path, client_name: str, contractor_id: str) -> None:
    pf = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        pf,
        batch_id=BATCH,
        client_name=client_name,
        currency="EUR",
        exchange_rate=None,
        source_lines_json="[]",
    )
    with sqlite3.connect(str(pf)) as con:
        con.execute(
            "UPDATE proforma_drafts SET client_contractor_id=? "
            "WHERE batch_id=? AND client_name=?",
            (contractor_id, BATCH, client_name),
        )


@pytest.fixture()
def storage(tmp_path: Path) -> Path:
    root = tmp_path / "storage"
    root.mkdir()
    ddb.init_document_db(root / "documents.db")
    # Two commercial customers on one import batch → party authority AMBIGUOUS.
    _register("sales_packing_list", CID_A, "spl-a")
    _register("sales_invoice", CID_B, "si-b")

    cm = root / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as con:
        con.execute(
            "CREATE TABLE customer_master ("
            "bill_to_contractor_id TEXT PRIMARY KEY, bill_to_name TEXT, "
            "bill_to_street TEXT, bill_to_city TEXT, bill_to_postal_code TEXT, "
            "country TEXT, ship_to_name TEXT, ship_to_street TEXT, "
            "ship_to_city TEXT, ship_to_zip TEXT, ship_to_country TEXT, "
            "ship_to_phone TEXT, ship_to_email TEXT, ship_to_person TEXT, "
            "ship_to_use_alternate INTEGER)"
        )
        con.executemany(
            "INSERT INTO customer_master (bill_to_contractor_id, bill_to_name, "
            "bill_to_street, bill_to_city, bill_to_postal_code, country) "
            "VALUES (?,?,?,?,?,?)",
            [
                (CID_A, CLIENT_A, "1 Alpha Street", "Antwerp", "2000", "BE"),
                (CID_B, CLIENT_B, "2 Beta Weg", "Bonn", "53111", "DE"),
            ],
        )

    _draft(root, CLIENT_A, CID_A)
    _draft(root, CLIENT_B, CID_B)
    return root


def _resolved_name(storage: Path, client_name):
    view = dp._resolve_customer_from_batch(BATCH, client_name, storage)
    return None if view is None else view.bill_to_name


# ── The ambiguity guard is preserved ─────────────────────────────────────────


def test_unscoped_caller_still_fails_closed_on_ambiguous_batch(storage: Path):
    """No client scope → no batch-level guess. Unchanged pre-existing behaviour."""
    assert _resolved_name(storage, None) is None


def test_unknown_client_ref_fails_closed(storage: Path):
    """A client scope that names no draft resolves nothing — never a first row."""
    assert _resolved_name(storage, "Client With No Draft") is None


# ── The client-scoped commercial document is the stronger authority ──────────


def test_client_scoped_draft_resolves_on_ambiguous_batch(storage: Path):
    """Pre-fix this returned None → 422 CUSTOMER_NOT_FOUND on booking."""
    assert _resolved_name(storage, CLIENT_A) == CLIENT_A


def test_client_scope_does_not_leak_across_clients(storage: Path):
    """Each client on the same batch resolves to its OWN contractor."""
    assert _resolved_name(storage, CLIENT_A) == CLIENT_A
    assert _resolved_name(storage, CLIENT_B) == CLIENT_B


def test_draft_contractor_id_helper_is_scoped(storage: Path):
    assert dp._draft_client_contractor_id(BATCH, CLIENT_A, storage) == CID_A
    assert dp._draft_client_contractor_id(BATCH, CLIENT_B, storage) == CID_B
    assert dp._draft_client_contractor_id(BATCH, "Nobody", storage) is None


# ── AWB address authority consumes the same scope ────────────────────────────


def test_awb_address_authority_requires_client_scope(storage: Path):
    from app.services.awb_address_authority import (
        CustomerNotFoundError,
        derive_awb_address_authority,
    )

    with pytest.raises(CustomerNotFoundError):
        derive_awb_address_authority(BATCH, storage)


def test_awb_address_authority_client_scoped_resolves_per_client(storage: Path):
    from app.services.awb_address_authority import derive_awb_address_authority

    a = derive_awb_address_authority(BATCH, storage, client_ref=CLIENT_A)
    b = derive_awb_address_authority(BATCH, storage, client_ref=CLIENT_B)
    assert (a["name"], a["city"], a["country"]) == (CLIENT_A, "Antwerp", "BE")
    assert (b["name"], b["city"], b["country"]) == (CLIENT_B, "Bonn", "DE")


def test_awb_address_fallback_passes_client_scope_through(storage: Path):
    from app.services.awb_address_authority import (
        derive_awb_address_authority_with_fallback,
    )

    # Recent batch: the raw fallback must NOT be reachable, and the client
    # scope alone is what makes the authority path succeed.
    out = derive_awb_address_authority_with_fallback(
        BATCH, storage, raw_fallback={"name": "RAW", "street": "x",
                                      "city": "y", "country": "PL"},
        client_ref=CLIENT_A,
    )
    assert out["name"] == CLIENT_A
    assert out.get("source") != "raw_fallback_historical"
