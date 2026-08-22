"""An allocation warning is a warning. The operator holds the better information.

We never open the box: QC happens in India and parcels are reshipped sealed, so
every quantity here is derived from the same documents the operator can see, and
the operator additionally knows things no table holds. Refusing on that basis is
the less-informed party vetoing the better-informed one.

What the system may do is say what it noticed and keep the answer — and that
record is worth more than the block, because a block leaves no trace.
"""
from __future__ import annotations

import pytest

import app.services.packing_db as pdb


@pytest.fixture
def db(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    monkeypatch.setattr(pdb, "_customer_master_exists", lambda cid: cid == "4321")
    return tmp_path


def _doc(doc_id, stage="final"):
    with pdb._connect() as con:
        con.execute(
            "INSERT INTO packing_documents (id, batch_id, invoice_no, source_file_path,"
            " source_file_hash, parser_name, parser_version, extraction_status,"
            " created_at, updated_at, doc_stage) "
            "VALUES (?,?,'INV','p','h','x','1','complete','2026-01-01','2026-01-01',?)",
            (doc_id, "B1", stage))


def _line(doc_id, *, inv="INV", code="P1"):
    pdb.upsert_packing_lines([{
        "packing_document_id": doc_id, "batch_id": "B1", "invoice_no": inv,
        "product_code": code, "design_no": "D1", "quantity": 1.0, "pack_sr": 1.0,
        "invoice_line_position": 1,
    }])
    with pdb._connect() as con:
        return con.execute("SELECT id FROM packing_lines WHERE packing_document_id=?",
                           (doc_id,)).fetchone()[0]


def test_an_advance_line_can_be_allocated_with_a_reason(db):
    _doc("dA", stage="advance")
    lid = _line("dA")
    out = pdb.confirm_allocation(lid, "4321", "amit",
                                 reason="customer confirmed by email, goods ship next week")
    assert out["allocated_customer_id"] == "4321"
    assert out["weak_identity"] is True
    assert out["override_warning"] == pdb.ADVANCE_WARNING
    assert out["override_reason"].startswith("customer confirmed")


def test_the_reason_is_mandatory_and_the_message_says_it_is_allowed(db):
    _doc("dA", stage="advance")
    lid = _line("dA")
    with pytest.raises(ValueError) as e:
        pdb.confirm_allocation(lid, "4321", "amit")
    msg = str(e.value)
    assert "allocation is allowed" in msg
    assert "reason" in msg
    assert "cannot be allocated" not in msg      # the old refusal, gone


def test_the_override_is_recorded_on_the_row_not_only_returned(db):
    """A block leaves no trace. This is the trace, and it must survive the call."""
    _doc("dA", stage="advance")
    lid = _line("dA")
    pdb.confirm_allocation(lid, "4321", "amit", reason="operator knows the buyer")
    with pdb._connect() as con:
        r = con.execute("SELECT allocation_override_warning, allocation_override_reason,"
                        " allocation_weak_identity, allocation_confirmed_by"
                        " FROM packing_lines WHERE id=?", (lid,)).fetchone()
    assert r["allocation_override_warning"] == pdb.ADVANCE_WARNING
    assert r["allocation_override_reason"] == "operator knows the buyer"
    assert r["allocation_weak_identity"] == 1
    assert r["allocation_confirmed_by"] == "amit"


def test_an_incomplete_identity_warns_too(db):
    """Neither an invoice number nor a product code: allocatable, tagged."""
    _doc("dF")
    lid = _line("dF", inv="", code="")
    out = pdb.confirm_allocation(lid, "4321", "amit", reason="matched by hand from the bag")
    assert out["override_warning"] == pdb.WEAK_IDENTITY_WARNING
    assert out["weak_identity"] is True


def test_an_ordinary_line_needs_no_reason_and_is_not_flagged(db):
    """A rule that warns on everything is a rule nobody reads."""
    _doc("dF")
    lid = _line("dF")
    out = pdb.confirm_allocation(lid, "4321", "amit")
    assert out["weak_identity"] is False
    assert out["override_warning"] == ""
    with pdb._connect() as con:
        r = con.execute("SELECT allocation_weak_identity, allocation_override_reason"
                        " FROM packing_lines WHERE id=?", (lid,)).fetchone()
    assert r["allocation_weak_identity"] == 0
    assert r["allocation_override_reason"] == ""


def test_a_customer_outside_customer_master_is_still_refused(db):
    """This one STAYS hard: the system does know its own Master, and
    MASTER-FIRST binds. Override posture is about goods, not about authority."""
    _doc("dF")
    lid = _line("dF")
    with pytest.raises(ValueError) as e:
        pdb.confirm_allocation(lid, "9999", "amit", reason="just this once")
    assert "Customer Master" in str(e.value)
