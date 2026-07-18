# Golden comparator corpus (Campaign-2 A1.1)

Static wFirma invoice XML snapshots pinning `document_comparator.compare_invoice_plan`
against a fixed reference plan (see test_document_comparator_golden.py `_ref_plan`).
Each file has a known expected gap outcome. If a future XML-parse change alters
what the comparator observes, these break — which is the intent.

Reference plan A: contractor=9001, currency=EUR, 1 line (RING, good=42,
unit_count=1.0000, price=306.00, vat=228), total=306.00, no receiver.
