"""The commercial line needs an identity that does not change shape.

Root cause pinned here. A supplier sends the same goods twice, in two forms:

    EJL-26-27-178-Packing list of shipment-1pc-16-05-26-Poland.xls   pack_sr = 1.0
    EJL-26-27-178-Packing list of shipment-1pc-16-05-26-Client.xlsx  pack_sr = None

``pack_sr`` is our pack sequence. The supplier's per-client form does not carry
it, because it is not a property of the goods. Both the barcode function and the
dedup key in ``upsert_packing_lines`` branched on its presence, so the two forms
produced different keys, never matched each other, and one commercial line became
two rows. 38 duplicate groups reached production that way.

The key identifies a GROUP, and deliberately carries NO ordinal. Two independent
failures proved an ordinal cannot exist here: computed within the incoming list
it collapses when callers upsert one line at a time, and ranked against stored
rows it makes the key a function of ingestion history. A pure function of the
row cannot separate two lines of a lot — they are identical in every non-barred
field — so how many rows share a key is a COUNT, the same shape the allocation
ruling (R8) chose.

``scan_code`` keeps its ladder: it is the printed barcode and labels already
exist on boxes. This is a second, separate concern.
"""
from __future__ import annotations

import pytest

from app.services.packing_db import (
    line_key_is_incomplete,
    packing_line_key,
    _compute_scan_code,
)


def _poland_form():
    """Per-invoice form: carries our pack sequence."""
    return {"invoice_no": "EJL/26-27/178", "product_code": "EJL/26-27/178-1",
            "design_no": "JR08007", "quantity": 1.0, "pack_sr": 1.0, "bag_id": ""}


def _client_form():
    """Per-client form: same goods, no pack sequence. Not a different line."""
    return {"invoice_no": "EJL/26-27/178", "product_code": "EJL/26-27/178-1",
            "design_no": "JR08007", "quantity": 1.0, "pack_sr": None, "bag_id": ""}


def test_the_two_supplier_forms_of_one_line_produce_one_key():
    """THE regression. Both forms describe the same commercial line."""
    assert packing_line_key(_poland_form()) == packing_line_key(_client_form())


def test_the_old_barcode_key_still_partitions_them():
    """Why a second function was needed rather than reusing scan_code.

    Not a complaint about scan_code -- it is the printed barcode and must stay
    as it is. It simply cannot answer 'is this the same commercial line'.
    """
    assert _compute_scan_code(_poland_form()) != _compute_scan_code(_client_form())


@pytest.mark.parametrize("missing", ["invoice_no", "product_code", "design_no",
                                     "pack_sr", "bag_id"])
def test_the_key_shape_never_varies_with_a_missing_field(missing):
    """Four segments, always. A key that gains or loses one partitions."""
    line = _poland_form()
    line[missing] = None
    assert len(packing_line_key(line).split("|")) == 4


@pytest.mark.parametrize("qty", [1, 1.0, "1", "1.00", " 1.0 "])
def test_quantity_spellings_are_one_quantity(qty):
    line = _poland_form()
    line["quantity"] = qty
    assert packing_line_key(line) == packing_line_key(_poland_form())


def test_case_and_whitespace_do_not_create_a_second_line():
    line = _poland_form()
    line["design_no"] = "  jr08007 "
    assert packing_line_key(line) == packing_line_key(_poland_form())


def test_the_key_is_a_pure_function_of_the_row():
    """ADVERSARY: both dead designs, pinned so neither returns.

    The first ordinal was computed from list position -- so batching the calls
    changed the key. The second ranked against stored rows -- so ingestion
    history changed the key. A key that answers differently for the same row is
    not an identity. The group key must depend on NOTHING but the row.
    """
    line = _poland_form()
    k1 = packing_line_key(line)
    k2 = packing_line_key(dict(line))            # a copy
    k3 = packing_line_key(dict(line, pack_sr=99.0))   # optional field changed
    k4 = packing_line_key(dict(line, bag_id="B7"))    # optional field changed
    assert k1 == k2 == k3 == k4


def test_two_lines_of_a_lot_share_the_key_by_design():
    """Not a defect: a lot of identical rings IS one commercial group.
    Multiplicity is a count, never a key segment."""
    assert packing_line_key(_poland_form()) == packing_line_key(
        dict(_poland_form(), pack_sr=2.0))


def test_a_line_with_neither_invoice_nor_product_code_is_incomplete():
    """123 live rows are in this state. The key still works; it is just too weak
    to bind money to, so allocation and write-time absorb must refuse it."""
    thin = {"invoice_no": "", "product_code": None,
            "design_no": "JE01868", "quantity": 1.0}
    assert line_key_is_incomplete(thin)
    assert packing_line_key(thin) == "||JE01868|1"
    assert not line_key_is_incomplete(_poland_form())


def test_a_line_with_only_one_of_the_two_is_not_incomplete():
    assert not line_key_is_incomplete(
        {"invoice_no": "EJL/26-27/178", "product_code": "", "design_no": "X",
         "quantity": 1})
    assert not line_key_is_incomplete(
        {"invoice_no": "", "product_code": "EJL/26-27/178-1", "design_no": "X",
         "quantity": 1})
