"""test_advance_packing_status.py — the operator status surface.

Requirement 5 of the Business Feature Completeness Standard: an operator must
be able to see, without a developer, what state Advance Packing is in, when it
last did something, what happened, and whether anything needs them.

These tests care about two things the status surface gets wrong easily:
  * fabricating a number it does not have (a run timestamp, an error count),
  * calling a business variance an "error" -- it is the answer, not a fault.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


_ROWS = [
    {"design_no": "D-100", "quantity": 10, "uom": "PCS", "item_type": "RING"},
    {"design_no": "D-200", "quantity": 5, "uom": "PCS", "item_type": "RING"},
]


@pytest.fixture()
def adv(tmp_path, monkeypatch):
    from app.services import advance_packing as adv_mod
    from app.services.packing_db import init_packing_db

    init_packing_db(tmp_path / "packing.db")
    monkeypatch.setattr(adv_mod, "_storage", lambda: tmp_path)
    monkeypatch.setattr(adv_mod, "extract_packing",
                        lambda p, **kw: (list(_ROWS), "stub", "1.0", {}))
    return adv_mod


@pytest.fixture()
def src(tmp_path):
    f = tmp_path / "advance.xlsx"
    f.write_bytes(b"stub-advance-packing-list")
    return f


def _shipment(batch_id, rows, storage):
    """A real (non-advance) shipment batch to link against.

    Uses the same packing authority the final purchase flow uses -- doc_stage
    defaults to "final", which is what makes it a legal link target -- and
    creates the ``outputs/<batch_id>`` directory, because link_to_batch
    deliberately refuses to link to a shipment that does not exist on disk.
    """
    from app.services import packing_db as pdb
    (storage / "outputs" / batch_id).mkdir(parents=True, exist_ok=True)
    doc_id = pdb.upsert_packing_document(
        batch_id=batch_id, source_file_path="inv.xlsx",
        source_file_hash="h-" + batch_id, extraction_status="ok")
    pdb.upsert_packing_lines([
        {"packing_document_id": doc_id, "batch_id": batch_id, "invoice_no": "",
         "product_code": None, "design_no": r["design_no"],
         "quantity": r["quantity"], "pack_sr": r["pack_sr"]}
        for r in rows
    ])
    return doc_id


# -- the four operator questions --------------------------------------------

def test_empty_module_is_healthy_and_says_nothing_happened(adv):
    """No documents is a legitimate state, not an error state."""
    st = adv.advance_status()
    assert st["healthy"] is True
    assert st["processed"] == 0
    assert st["last_completed_at"] is None
    assert st["attention"]["awaiting_link"] == 0
    assert st["attention"]["with_variance"] == 0


def test_counts_answer_what_happened(adv, src, tmp_path):
    a = adv.ingest_advance(src, operator="tester")

    st = adv.advance_status()
    assert st["processed"] == 1
    assert st["documents"] == {"total": 1, "awaiting_link": 0 + 1,
                               "linked": 0, "withdrawn": 0}
    assert st["last_completed_at"], "an ingest is the module doing something"
    # an announced-but-unlinked document is work the operator still owes
    assert st["attention"]["awaiting_link"] == 1
    assert a["document_id"] in [d["document_id"]
                                for d in st["attention"]["documents"]]


def test_withdrawn_documents_are_skipped_not_forgotten(adv, src):
    a = adv.ingest_advance(src)
    adv.withdraw(a["document_id"], "supplier sent the wrong file",
                 operator="tester")

    st = adv.advance_status()
    assert st["skipped"] == 1
    assert st["created"] == 0, "a retracted document is no longer standing"
    assert st["processed"] == 1, "but it still happened"
    assert st["documents"]["withdrawn"] == 1
    assert st["attention"]["awaiting_link"] == 0, \
        "a withdrawn document is not work to do"


# -- honesty: never invent a number -----------------------------------------

def test_run_shaped_fields_are_null_because_there_is_no_run(adv, src):
    """Advance Packing has no scheduler and cannot have one. The canonical
    keys stay present so consumers read one shape, but they must be null
    rather than filled with a fabricated timestamp."""
    adv.ingest_advance(src)
    st = adv.advance_status()
    assert st["running"] is False
    assert st["last_started_at"] is None
    assert st["duration_ms"] is None
    assert st["automation"]["mode"] == "operator_initiated"
    assert st["automation"]["reason"]


def test_a_variance_is_not_an_error(adv, src, tmp_path):
    """The supplier shipping less than announced is the business answer this
    module exists to produce. Reporting it as an error would send the operator
    hunting for a fault that is not there."""
    a = adv.ingest_advance(src, operator="tester")
    # shipped: D-100 short by 4, D-200 as announced
    _shipment("SHIPMENT_STATUS_1", [
        {"design_no": "D-100", "quantity": 6, "pack_sr": 1},
        {"design_no": "D-200", "quantity": 5, "pack_sr": 2},
    ], tmp_path)
    adv.link_to_batch(a["document_id"], "SHIPMENT_STATUS_1", operator="tester")

    st = adv.advance_status()
    assert st["errors"] == 0, "a quantity variance is not an exception count"
    assert st["last_error"] is None
    assert st["attention"]["with_variance"] == 1
    assert st["documents"]["linked"] == 1
    assert st["attention"]["awaiting_link"] == 0
    hit = [d for d in st["attention"]["documents"]
           if d["document_id"] == a["document_id"]]
    assert hit and hit[0]["batch_id"] == "SHIPMENT_STATUS_1"


def test_a_matching_shipment_needs_no_attention(adv, src, tmp_path):
    a = adv.ingest_advance(src, operator="tester")
    _shipment("SHIPMENT_STATUS_2", [
        {"design_no": "D-100", "quantity": 10, "pack_sr": 1},
        {"design_no": "D-200", "quantity": 5, "pack_sr": 2},
    ], tmp_path)
    adv.link_to_batch(a["document_id"], "SHIPMENT_STATUS_2", operator="tester")

    st = adv.advance_status()
    assert st["attention"]["with_variance"] == 0
    assert st["attention"]["documents"] == []
    assert st["updated"] == 1, "linking updates the document row"


# -- the route must not be swallowed by /{document_id} ----------------------

def test_status_route_is_registered_before_the_document_id_route():
    """``/{document_id}`` matches the literal segment ``status``. If the status
    route is ever moved below it, GET /status answers 404 for a document named
    'status' instead of returning the panel. Ordering is the contract."""
    src_text = (_ROOT / "app" / "api" / "routes_packing_advance.py").read_text(
        encoding="utf-8")
    assert src_text.index('"/status"') < src_text.index('"/{document_id}"')


def test_status_route_is_session_gated():
    """Same guard as every other route on this router -- the status panel
    exposes supplier document counts and must not be anonymous."""
    src_text = (_ROOT / "app" / "api" / "routes_packing_advance.py").read_text(
        encoding="utf-8")
    i = src_text.index('"/status"')
    assert "dependencies=[_auth]" in src_text[i:i + 120]
