"""The commercial line needs an identity that does not change shape.

Root cause pinned here. A supplier sends the same goods twice, in two forms:

    EJL-26-27-178-Packing list of shipment-1pc-16-05-26-Poland.xls   pack_sr = 1.0
    EJL-26-27-178-Packing list of shipment-1pc-16-05-26-Client.xlsx  pack_sr = None

``pack_sr`` is our pack sequence. The supplier's per-client form does not carry
it, because it is not a property of the goods. Both the barcode function and the
dedup key in ``upsert_packing_lines`` branched on its presence, so the two forms
produced different keys, never matched each other, and one commercial line became
two rows. Three such pairs are in production.

The fix is not a better ladder. It is that an identity function must be TOTAL over
required fields and INVARIANT under optional ones -- every part always present,
empty when unknown. ``scan_code`` keeps its ladder: it is the printed barcode and
labels already exist on boxes. This is a second, separate concern.
"""
from __future__ import annotations

import pytest

from app.services.packing_db import (
    line_key_is_incomplete,
    line_ordinals,
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
    poland, client = _poland_form(), _client_form()
    assert packing_line_key(poland, 1) == packing_line_key(client, 1)


def test_the_old_barcode_key_still_partitions_them():
    """Why a second function was needed rather than reusing scan_code.

    Not a complaint about scan_code -- it is the printed barcode and must stay
    as it is. It simply cannot answer 'is this the same commercial line'.
    """
    assert _compute_scan_code(_poland_form()) != _compute_scan_code(_client_form())


@pytest.mark.parametrize("missing", ["invoice_no", "product_code", "design_no",
                                     "pack_sr", "bag_id"])
def test_the_key_shape_never_varies_with_a_missing_field(missing):
    """Five segments, always. A key that gains or loses one partitions."""
    line = _poland_form()
    line[missing] = None
    assert len(packing_line_key(line, 1).split("|")) == 5


@pytest.mark.parametrize("qty", [1, 1.0, "1", "1.00", " 1.0 "])
def test_quantity_spellings_are_one_quantity(qty):
    line = _poland_form()
    line["quantity"] = qty
    assert packing_line_key(line, 1) == packing_line_key(_poland_form(), 1)


def test_case_and_whitespace_do_not_create_a_second_line():
    line = _poland_form()
    line["design_no"] = "  jr08007 "
    assert packing_line_key(line, 1) == packing_line_key(_poland_form(), 1)


def test_genuinely_repeated_rows_stay_distinct():
    """A lot of three identical rings is three lines, not one.

    The ordinal is what separates them, and it is computed from source row
    order -- never read from pack_sr, which is the field that broke the old key.
    """
    lot = [_poland_form(), _poland_form(), _poland_form()]
    assert line_ordinals(lot) == [1, 2, 3]
    keys = {packing_line_key(l, o) for l, o in zip(lot, line_ordinals(lot))}
    assert len(keys) == 3


def test_ordinals_correspond_across_the_two_forms():
    """The property the whole design rests on, verified on production data:
    within a group, row order matches between the Poland and Client forms."""
    poland = [_poland_form(), _poland_form()]
    client = [_client_form(), _client_form()]
    assert line_ordinals(poland) == line_ordinals(client)
    assert [packing_line_key(l, o) for l, o in zip(poland, line_ordinals(poland))] \
        == [packing_line_key(l, o) for l, o in zip(client, line_ordinals(client))]


def test_ordinal_ignores_pack_sr_entirely():
    """ADVERSARY: the obvious 'improvement' is to seed the ordinal from pack_sr
    when it happens to be there. That reintroduces the bug exactly."""
    poland = [dict(_poland_form(), pack_sr=7.0), dict(_poland_form(), pack_sr=99.0)]
    assert line_ordinals(poland) == [1, 2]


def test_a_line_with_neither_invoice_nor_product_code_is_incomplete():
    """123 live rows are in this state. The key still works; it is just too weak
    to bind money to, so allocation must refuse rather than guess."""
    thin = {"invoice_no": "", "product_code": None,
            "design_no": "JE01868", "quantity": 1.0}
    assert line_key_is_incomplete(thin)
    assert packing_line_key(thin, 1) == "||JE01868|1|1"
    assert not line_key_is_incomplete(_poland_form())


def test_a_line_with_only_one_of_the_two_is_not_incomplete():
    assert not line_key_is_incomplete(
        {"invoice_no": "EJL/26-27/178", "product_code": "", "design_no": "X",
         "quantity": 1})
    assert not line_key_is_incomplete(
        {"invoice_no": "", "product_code": "EJL/26-27/178-1", "design_no": "X",
         "quantity": 1})
