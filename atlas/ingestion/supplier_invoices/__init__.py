"""
atlas/ingestion/supplier_invoices/
====================================
Reusable supplier invoice ingestion authority.

Exports:
    parse_invoice_line(description)  -> dict of extracted fields
    classify_product_type(description) -> product type string (last-noun authority)
    InvoiceLine                      -> typed dict / dataclass for a parsed line
    InvoiceBatch                     -> typed dict for a batch of invoices
"""
from .parser import parse_invoice_line, parse_invoice_batch, InvoiceLine
from .classifier import classify_product_type, ITEM_TYPE_ORDER

__all__ = [
    "parse_invoice_line",
    "parse_invoice_batch",
    "InvoiceLine",
    "classify_product_type",
    "ITEM_TYPE_ORDER",
]
