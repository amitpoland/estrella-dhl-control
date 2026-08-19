r"""Item 3/6/7: the advance workflow against the authorities it must not become.

An advance packing list is a supplier's ANNOUNCEMENT. Goods do not exist yet.
Every authority below owns a fact that only becomes true later, and the point
of these tests is that an advance batch reaches none of them -- not by policy
in a docstring, but by calling the real functions with a real advance batch and
showing they come back empty.

  Product Master   product_code is minted from the purchase invoice (ADR-024).
  wFirma           registration works off invoice_lines; an advance batch has
                   none, so the sanctioned proposal mechanism never sees it.
  Inventory        seeding keys on scan_code; advance rows carry NULL.
  Shipment list    enumerated by scanning storage/outputs/; advance batches get
                   no outputs directory, so no phantom shipment appears.
  Warehouse        accepted/shortage/overage stay with warehouse_receipt.
                   Reconciliation here compares two COMMERCIAL documents.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.core.config import settings              # noqa: E402
from app.services import advance_packing as adv   # noqa: E402
from app.services import packing_db as pdb        # noqa: E402

_ROWS = [
    {"design_no": "D-100", "quantity": 4, "bag_id": "B1"},
    {"design_no": "D-200", "quantity": 6, "bag_id": "B1"},
]


@pytest.fixture()
def advance(tmp_path, monkeypatch):
    """An ingested advance batch, plus the storage root it lives in."""
    pdb.init_packing_db(tmp_path / "packing.db")
    monkeypatch.setattr(adv, "_storage", lambda: tmp_path)
    monkeypatch.setattr(adv, "extract_packing",
                        lambda p, **kw: (list(_ROWS), "stub", "1", {}))
    src = tmp_path / "advance.xlsx"
    src.write_bytes(b"x" * 32)
    result = adv.ingest_advance(src, operator="t")
    return result, tmp_path


def test_advance_lines_carry_no_product_or_piece_identity(advance):
    """The two columns every downstream authority keys on are NULL."""
    result, root = advance
    con = sqlite3.connect(str(root / "packing.db"))
    try:
        rows = con.execute(
            "SELECT product_code, scan_code FROM packing_lines WHERE batch_id=?",
            (result["batch_id"],)).fetchall()
    finally:
        con.close()
    assert len(rows) == 2
    assert all(pc in (None, "") for pc, _ in rows), "product_code is minted at invoice"
    assert all(sc is None for _, sc in rows), "a scan_code would let a scan resolve it"


def test_product_master_sync_finds_nothing_to_sync(advance):
    """Product Master stays the single authority; an advance batch adds to it
    exactly nothing."""
    from app.services import product_master_sync as pms

    result, root = advance
    with patch.object(settings, "storage_root", root):
        summary = pms.run_product_master_sync(result["batch_id"], dry_run=True)
    assert summary.get("codes", summary.get("total_codes", 0)) in (0, None, [])
    assert not summary.get("created") and not summary.get("updated")


def test_wfirma_registration_never_sees_an_advance_batch(advance):
    """Item 7: convergence runs through the existing sanctioned proposal
    mechanism, which reads invoice_lines. An advance batch has none, so it is
    excluded structurally rather than by a second rule."""
    from app.services import wfirma_product_registration as wpr

    result, root = advance
    assert wpr.find_unsynced_product_codes(result["batch_id"], root) == []

    audit = {"batch_id": result["batch_id"], "action_proposals": []}
    assert wpr.create_registration_proposal(audit, result["batch_id"], []) is None
    assert audit["action_proposals"] == []


def test_an_advance_batch_is_not_a_shipment(advance):
    """The shipment list is a directory scan of storage/outputs/. An advance
    batch must never create a directory there."""
    result, root = advance
    assert not (root / "outputs").exists(), (
        "ingesting an advance list must not create anything under outputs/")
    assert adv.advance_source_dir(result["batch_id"]).parent.name == "advance_packing"


def test_reconciliation_does_not_touch_physical_receipt(advance, tmp_path):
    """Item 6: expected-vs-shipped compares two commercial documents. The
    physical numbers (accepted / shortage / overage) belong to
    warehouse_receipt and must be untouched by an advance reconciliation."""
    result, root = advance
    batch = "SHIPMENT_777_2026-08_abcd1234"
    (root / "outputs" / batch).mkdir(parents=True)

    doc = pdb.upsert_packing_document(batch_id=batch, invoice_no="INV-1",
                                      source_file_path="real.xlsx",
                                      extraction_status="extracted")
    pdb.upsert_packing_lines([
        {"packing_document_id": doc, "batch_id": batch, "invoice_no": "INV-1",
         "design_no": "D-100", "quantity": 4, "pack_sr": 1},
    ])
    adv.link_to_batch(result["document_id"], batch, operator="t")
    report = adv.reconcile(result["document_id"])

    assert {ln["design_no"] for ln in report["lines"]} == {"D-100", "D-200"}
    # Announced-vs-shipped vocabulary only. No physical fields are invented.
    for ln in report["lines"]:
        assert set(ln) == {"design_no", "expected_qty", "actual_qty",
                           "variance_qty", "status"}
        assert "accepted_qty" not in ln and "shortage_qty" not in ln

    con = sqlite3.connect(str(root / "packing.db"))
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "warehouse_receipt_confirmations" in tables:
            n = con.execute(
                "SELECT COUNT(*) FROM warehouse_receipt_confirmations").fetchone()[0]
            assert n == 0, "reconciliation must not assert physical receipt"
    finally:
        con.close()


def test_linking_rewrites_neither_document(advance):
    """Historical and posted documents are not silently rewritten: the link is
    the only field that changes, and the final packing document is untouched."""
    result, root = advance
    batch = "SHIPMENT_777_2026-08_abcd1234"
    (root / "outputs" / batch).mkdir(parents=True)
    doc = pdb.upsert_packing_document(batch_id=batch, invoice_no="INV-1",
                                      source_file_path="real.xlsx",
                                      extraction_status="extracted")
    before = dict(pdb.get_packing_document(doc))

    adv.link_to_batch(result["document_id"], batch, operator="t")

    after = dict(pdb.get_packing_document(doc))
    assert after == before, "the shipment's own packing document must not change"

    # And the advance document keeps its own batch and stage.
    a = pdb.get_packing_document(result["document_id"])
    assert a["batch_id"] == result["batch_id"] and a["doc_stage"] == "advance"


def test_a_second_link_to_a_different_shipment_is_refused(advance):
    result, root = advance
    for name in ("SHIPMENT_A_2026-08_aaaaaaaa", "SHIPMENT_B_2026-08_bbbbbbbb"):
        (root / "outputs" / name).mkdir(parents=True)
    adv.link_to_batch(result["document_id"], "SHIPMENT_A_2026-08_aaaaaaaa")
    with pytest.raises(ValueError, match="already linked"):
        adv.link_to_batch(result["document_id"], "SHIPMENT_B_2026-08_bbbbbbbb")
