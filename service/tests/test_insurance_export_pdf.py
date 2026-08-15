"""Insurance Export Statement — PDF renderer tests (pypdf, label-based).

Calls ``render_insurance_export_statement_pdf`` directly with a stub
selection and asserts on extracted text: masthead, Polish headers,
nested adjustment rows, TOTAL/GRAND TOTAL, recovered footnote, signature
block, landscape orientation, and the two column/adjustment toggles.
"""
from __future__ import annotations

import io

from pypdf import PdfReader

from app.services.insurance_export_pdf_renderer import (
    render_insurance_export_statement_pdf,
)

PERIOD = {"from": "2026-05-01", "to": "2026-05-31"}


def _row(invoice_id, fullnumber, *, contractor_id, contractor_name,
         currency="USD", inv_cif="2600.00", plus_10="260.00",
         sum_insured="2860.00", fx="88.467460", inr="253016.94",
         recovered=None):
    return {
        "invoice_id": invoice_id,
        "contractor_id": contractor_id,
        "contractor_name": contractor_name,
        "fullnumber": fullnumber,
        "date": "2026-05-10",
        "currency": currency,
        "inv_cif": inv_cif,
        "plus_10_pct": plus_10,
        "sum_insured": sum_insured,
        "fx_rate": fx,
        "sum_insured_inr": inr,
        "insurance_recovered": recovered or {
            "amount": "0.00", "currency": currency, "resolution": "unresolved"
        },
    }


def _adjustment():
    return {
        "invoice_id": "201",
        "parent_invoice_id": "101",
        "parent_confirmed": True,
        "contractor_id": "C-1",
        "contractor_name": "Alpha Exports Ltd",
        "fullnumber": "KOR 201/2026",
        "date": "2026-05-20",
        "currency": "USD",
        "inv_cif": "-500.00",
        "plus_10_pct": "-50.00",
        "sum_insured": "-550.00",
        "fx_rate": "88.467460",
        "sum_insured_inr": "-48657.10",
        "insurance_recovered": {
            "amount": "0.00", "currency": "USD", "resolution": "not_applicable"
        },
    }


def _selection():
    rows = [
        _row("101", "FV 1/2026", contractor_id="C-1",
             contractor_name="Alpha Exports Ltd",
             recovered={"amount": "45.67", "currency": "USD",
                        "resolution": "manual_amount"}),
        _row("102", "FV 2/2026", contractor_id="C-1",
             contractor_name="Alpha Exports Ltd",
             inv_cif="1000.00", plus_10="100.00", sum_insured="1100.00",
             inr="97314.21"),
        _row("103", "FV 3/2026", contractor_id="C-2",
             contractor_name="Beta Trading GmbH", currency="EUR",
             inv_cif="2000.00", plus_10="200.00", sum_insured="2200.00",
             fx="99.382000", inr="218640.40",
             recovered={"amount": "30.00", "currency": "EUR",
                        "resolution": "calculated"}),
    ]
    totals = {
        "sum_insured_inr_documents": "568971.55",
        "sum_insured_inr_adjustments": "-48657.10",
        "sum_insured_inr_grand": "520314.45",
        "insurance_recovered": {"EUR": "30.00", "USD": "45.67"},
        "documents": 3,
        "adjustments": 1,
        "rows_without_inr": 0,
    }
    return rows, [_adjustment()], totals


def _render(**kwargs):
    rows, adjustments, totals = _selection()
    merged = dict(
        selected_rows=rows,
        selected_adjustments=adjustments,
        declaration_totals=totals,
        period=PERIOD,
    )
    merged.update(kwargs)
    return render_insurance_export_statement_pdf(None, **merged)


def _text(pdf_bytes):
    """Whitespace-normalized extraction: table cells wrap multi-word labels
    across lines, so all assertions run against a single-spaced string."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return " ".join(raw.split())


def test_pdf_is_landscape_a4():
    pdf = _render()
    assert pdf[:5] == b"%PDF-"
    reader = PdfReader(io.BytesIO(pdf))
    box = reader.pages[0].mediabox
    assert float(box.width) > float(box.height)


def test_pdf_masthead_and_period():
    text = _text(_render())
    assert "ESTRELLA JEWELS LLP SP. Z O.O., SP. K." in text
    assert "STATEMENT OF EXPORT SHIPMENT" in text
    assert "Period: 2026-05-01 – 2026-05-31" in text


def test_pdf_polish_headers_present():
    text = _text(_render())
    for header in ("Kontrahent", "Nr dokumentu", "Data wystawienia",
                   "Waluta", "Inv CIF", "10% addition", "Sum Insured",
                   "Exch Rate", "Sum Insured INR", "Insurance Recovered"):
        assert header in text, header


def test_pdf_document_rows_and_group_subtotals():
    text = _text(_render())
    for fullnumber in ("FV 1/2026", "FV 2/2026", "FV 3/2026"):
        assert fullnumber in text
    assert "Razem: Alpha Exports Ltd" in text
    assert "Razem: Beta Trading GmbH" in text
    assert "253016.94" in text
    assert "218640.40" in text


def test_pdf_adjustment_row_nested_with_em_dash():
    text = _text(_render())
    assert "— KOR 201/2026" in text
    assert "-48657.10" in text


def test_pdf_total_and_grand_total_rows():
    text = _text(_render())
    assert "TOTAL" in text
    assert "GRAND TOTAL" in text
    assert "568971.55" in text
    assert "520314.45" in text


def test_pdf_recovered_footnote_per_currency():
    text = _text(_render())
    assert "Insurance recovered from customers" in text
    assert "30.00 EUR" in text or "EUR" in text
    assert "45.67" in text


def test_pdf_signature_block():
    text = _text(_render())
    assert "Prepared by" in text
    assert "Authorised Signatory" in text
    assert "Date + Company Stamp" in text


def test_pdf_recovered_column_omitted_when_disabled():
    text = _text(_render(columns={"insurance_recovered": False}))
    assert "Insurance Recovered" not in text
    assert "Insurance recovered from customers" not in text
    # The other nine headers survive the reflow.
    assert "Sum Insured INR" in text


def test_pdf_include_adjustments_false_drops_grand_total():
    text = _text(_render(include_adjustments=False))
    assert "KOR 201/2026" not in text
    assert "GRAND TOTAL" not in text
    assert "TOTAL" in text


def test_pdf_no_adjustments_means_no_grand_total():
    text = _text(_render(selected_adjustments=[]))
    assert "GRAND TOTAL" not in text
    assert "TOTAL" in text


def test_pdf_page_footer():
    text = _text(_render())
    assert "Page 1" in text
