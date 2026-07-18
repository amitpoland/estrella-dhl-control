"""test_document_comparator_golden.py — Campaign-2 A1.1 · GOLDEN CORPUS.

Runs the comparator against a static corpus of wFirma invoice XML snapshots
(tests/golden/comparator/*.xml) with a fixed reference plan and pins the
expected gap outcome for each. Guards against future XML-parsing changes
silently altering what the comparison observes.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.services.document_comparator import compare_invoice_plan
from app.services.proforma_to_invoice import FinalInvoicePlan, LineItem

_GOLDEN = Path(__file__).resolve().parent / "golden" / "comparator"


def _ref_plan() -> FinalInvoicePlan:
    """Reference plan A — matches 01_match.xml exactly."""
    return FinalInvoicePlan(
        type="normal", contractor_id="9001", currency="EUR",
        price_currency_exchange=None, paymentmethod="przelew",
        paymentdate="2026-05-15", date="2026-06-08", description="x",
        series_id="15827921", company_account_id="194483",
        translation_language_id=None, contractor_receiver_id=None,
        contents=[LineItem(name="RING", good_id="42", unit="szt.",
                           unit_count="1.0000", price="306.00", vat_code_id="228")],
        source_proforma_id="1", source_proforma_number="P/1",
        expected_total=Decimal("306.00"),
    )


# filename -> (expected gap fields in order, expected first-blocking message substring)
_MANIFEST = {
    "01_match.xml":             ([], None),
    "02_wrong_type.xml":        (["type"], "expected type='normal' or 'vat'"),
    "03_contractor_mismatch.xml": (["contractor_id"], "contractor mismatch"),
    "04_line_dropped.xml":      (["line_count"], "line count mismatch"),
    "05_line_field.xml":        (["line[1]"], "line 1 field mismatch"),
    "06_currency.xml":          (["currency"], "currency mismatch"),
    "07_total_drift.xml":       (["total"], "total mismatch"),
    "08_multi_gap.xml":         (["contractor_id", "currency", "total"], "contractor mismatch"),
}


@pytest.mark.parametrize("fname,expected", _MANIFEST.items())
def test_golden_corpus(fname, expected):
    expected_fields, expected_msg = expected
    xml = (_GOLDEN / fname).read_text(encoding="utf-8")
    res = compare_invoice_plan(_ref_plan(), xml)

    assert [g.field for g in res.gaps] == expected_fields, (
        f"{fname}: gap fields {[g.field for g in res.gaps]} != {expected_fields}"
    )
    if expected_msg is None:
        assert res.first_blocking_gap() is None
    else:
        assert expected_msg in res.first_blocking_gap().message


def test_golden_corpus_is_present():
    files = sorted(p.name for p in _GOLDEN.glob("*.xml"))
    assert files == sorted(_MANIFEST), (
        f"golden corpus drift: on disk {files} vs manifest {sorted(_MANIFEST)}"
    )
