"""
accounting_documents.py — Read-only wFirma → professional accounting DTOs.

Normalization boundary (P0 Accounting Hub):
  wFirma XML response → top-level business documents only → DTO
  Nested ``<invoice><id>…</id></invoice>`` stubs MUST NOT become rows.

Never issues wFirma writes. Never invents payment or warehouse totals.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Warehouse types proven live against api2.wfirma.pl (2026-08-09).
WAREHOUSE_TYPES_SUPPORTED: Set[str] = {"WZ", "PZ", "PW", "RW"}
WAREHOUSE_TYPES_BLOCKED: Set[str] = {"MM"}

# Typed module map (optional direct find). Umbrella ``warehouse_documents``
# with ``type`` filter is preferred for list reads.
WAREHOUSE_MODULE_BY_TYPE: Dict[str, str] = {
    "WZ": "warehouse_document_w_z",
    "PZ": "warehouse_document_p_z",
    "PW": "warehouse_document_p_w",
    "RW": "warehouse_document_r_w",
}

_PAYMENT_STATE_LABEL = {
    "paid": "Paid",
    "unpaid": "Outstanding",
    "open": "Outstanding",
    "undefined": "Not specified",
}


def map_payment_state(raw: Optional[str]) -> str:
    """Map wFirma paymentstate to operator-readable label. Never echo raw enums."""
    s = (raw or "").strip().lower()
    if not s or s in ("—", "-", "null", "none"):
        return "Not specified"
    return _PAYMENT_STATE_LABEL.get(s, "Not specified" if s == "undefined" else s.title())


def _text(node: Optional[ET.Element], *tags: str, default: str = "") -> str:
    if node is None:
        return default
    for tag in tags:
        # ElementTree supports path segments in findtext.
        v = node.findtext(tag)
        if v is not None and str(v).strip():
            return str(v).strip()
    return default


def _accounting_currency_amount(
    node: ET.Element, currency: str, *tags: str
) -> str:
    """A ``<netto>`` / ``<tax>`` figure, withheld when it is not in ``currency``.

    wFirma returns these in the PLN accounting currency on EVERY document,
    while ``<currency>`` and the document-currency gross describe a foreign
    document — the same split ``ledger_aggregator._invoice_gross_raw``
    documents ("``<netto>`` may be PLN"). Emitting them in a row labelled USD
    or EUR stated a PLN amount as if it were foreign.

    No approved FX authority owns a netto conversion, so the figure is
    withheld on foreign documents rather than converted: truthful absence
    over an invented rate. Domestic documents are unaffected — there the
    accounting currency IS the document currency.
    """
    if (currency or "").strip().upper() not in ("", "PLN"):
        return "—"
    return _text(node, *tags) or "—"


def _first_child(parent: ET.Element, name: str) -> Optional[ET.Element]:
    return parent.find(name)


def iter_top_level_invoices(root: ET.Element) -> List[ET.Element]:
    """Direct children of ``<invoices>`` only — never ``.//invoice``."""
    invs = root.find("invoices")
    if invs is None:
        invs = root.find(".//invoices")
    if invs is None:
        return []
    return [c for c in list(invs) if c.tag == "invoice"]


def iter_top_level_warehouse_documents(root: ET.Element) -> List[ET.Element]:
    """Direct children of ``<warehouse_documents>`` only."""
    wds = root.find("warehouse_documents")
    if wds is None:
        wds = root.find(".//warehouse_documents")
    if wds is None:
        return []
    return [c for c in list(wds) if c.tag == "warehouse_document"]


def is_commercial_invoice_node(inv: ET.Element) -> bool:
    """True when the node is a real accounting document, not an id-only stub."""
    if inv is None or inv.tag != "invoice":
        return False
    fullnumber = _text(inv, "fullnumber", "full_number")
    if fullnumber:
        return True
    # Reject metadata stubs that only carry <id> (live prod shape).
    child_tags = {c.tag for c in list(inv)}
    if child_tags <= {"id"} or not child_tags:
        return False
    # Require at least one commercial signal besides id.
    if _text(inv, "date") and (_text(inv, "brutto", "total", "total_brutto") or _text(inv, "netto")):
        return True
    return False


def normalize_invoice_node(inv: ET.Element) -> Optional[Dict[str, Any]]:
    """One professional Invoice/CN DTO, or None if the node is a nested stub."""
    if not is_commercial_invoice_node(inv):
        return None
    wfirma_id = _text(inv, "id")
    number = _text(inv, "fullnumber", "full_number")
    if not number:
        # Never fall back to raw id as the visible document number.
        return None
    party = _text(
        inv,
        "contractor_detail/name",
        "contractor/name",
        "contractor_detail/altname",
    )
    # contractor/id ONLY. contractor_detail is a per-invoice SNAPSHOT of the
    # contractor as it looked when that document was issued, and its id changes
    # from invoice to invoice for the same real party. Falling back to it does
    # not recover a missing id -- it invents a new party per document, which is
    # the mechanism that manufactures duplicate contractors.
    #
    # An absent contractor/id means the document was raised against a party with
    # no CRM record. That is a real condition worth seeing, so it stays empty
    # rather than being filled with a number that identifies nothing.
    contractor_id = _text(inv, "contractor/id")
    raw_state = _text(inv, "paymentstate", "state")
    paid = _text(inv, "alreadypaid")
    remaining = _text(inv, "remaining")
    ccy = _text(inv, "currency")
    return {
        "wfirma_id": wfirma_id,
        "number": number,
        "date": _text(inv, "date"),
        "party_name": party or "—",
        "party": party or "—",  # back-compat for AccDocGrid until UI cutover
        "contractor_id": contractor_id,
        "currency": ccy or "—",
        "net": _accounting_currency_amount(inv, ccy, "netto", "total_netto"),
        "tax": _accounting_currency_amount(inv, ccy, "tax", "vat"),
        "gross": _text(inv, "brutto", "total", "total_brutto") or "—",
        "payment_state_raw": raw_state or "undefined",
        "payment_state": map_payment_state(raw_state),
        "state": map_payment_state(raw_state),  # back-compat column
        "payment_due_date": _text(inv, "paymentdate") or None,
        "paid_amount": paid or None,
        "outstanding_amount": remaining or None,
        "pdf_available": bool(wfirma_id),
        "doc_kind": "credit_note" if _text(inv, "type") == "correction" else "invoice",
    }


def normalize_invoices_from_xml(response_text: str) -> List[Dict[str, Any]]:
    root = ET.fromstring(response_text)
    rows: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for inv in iter_top_level_invoices(root):
        dto = normalize_invoice_node(inv)
        if not dto:
            continue
        key = dto["wfirma_id"] or dto["number"]
        if key in seen:
            continue
        seen.add(key)
        rows.append(dto)
    return rows


def normalize_warehouse_node(
    wd: ET.Element,
    *,
    allowed_types: Optional[Set[str]] = None,
) -> Optional[Dict[str, Any]]:
    """One warehouse DTO from a top-level warehouse_document element."""
    if wd is None or wd.tag != "warehouse_document":
        return None
    number = _text(wd, "fullnumber", "full_number")
    wfirma_id = _text(wd, "id")
    if not number or not wfirma_id:
        return None
    # Reject id-only stubs
    child_tags = {c.tag for c in list(wd)}
    if child_tags <= {"id"}:
        return None
    doc_type = (_text(wd, "type") or "").strip().upper()
    allowed = allowed_types if allowed_types is not None else WAREHOUSE_TYPES_SUPPORTED
    if doc_type and doc_type not in allowed:
        return None
    if not doc_type:
        return None
    party = _text(
        wd,
        "contractor_detail/name",
        "contractor/name",
        "contractor_detail/altname",
    )
    wh_ccy = _text(wd, "currency")
    return {
        "wfirma_id": wfirma_id,
        "doc_type": doc_type,
        "number": number,
        "date": _text(wd, "date"),
        "party_name": party or "—",
        "party": party or "—",
        # contractor/id only -- see normalize_invoice_node above.
        "contractor_id": _text(wd, "contractor/id"),
        "currency": wh_ccy or "—",
        "net": _accounting_currency_amount(wd, wh_ccy, "netto"),
        "gross": _text(wd, "brutto") or "—",
        "qty_or_lines": None,  # filled only when contents count is projected
        "awb": None,  # secondary EJ correlation — filled by route when linked
        "pdf_available": False,  # warehouse PDF unproven — never claim true in P0
        "state": _text(wd, "status") or "—",
    }


def normalize_warehouse_documents_from_xml(
    response_text: str,
    *,
    allowed_types: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    root = ET.fromstring(response_text)
    rows: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for wd in iter_top_level_warehouse_documents(root):
        dto = normalize_warehouse_node(wd, allowed_types=allowed_types)
        if not dto:
            continue
        key = dto["wfirma_id"]
        if key in seen:
            continue
        seen.add(key)
        rows.append(dto)
    return rows


def expense_payment_outstanding(
    expense_gross: float,
    linked_payment_values: Sequence[float],
) -> Dict[str, Any]:
    """Reconciliation helper: expense − linked payments = outstanding.

    Pure arithmetic for the supplier proof fixture. Not a production AP engine.
    """
    paid = float(sum(linked_payment_values))
    outstanding = float(expense_gross) - paid
    return {
        "expense_gross": float(expense_gross),
        "payments_total": paid,
        "outstanding": outstanding,
    }
