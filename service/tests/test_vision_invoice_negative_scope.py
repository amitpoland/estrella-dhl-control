"""
test_vision_invoice_negative_scope.py — authority-isolation guard for the
advisory ``vision_invoice`` block (vision_extractor image-only invoice layer).

Why this module exists (Lesson F — strict authority isolation)
--------------------------------------------------------------
``run_image_only_invoice_extraction`` recovers supplier / FOB / goods lines from
an image-only commercial invoice into an ADVISORY ``audit["vision_invoice"]``
proposal. That block is operator-confirmable input, NOT booked authority. The
one way this layer could do real damage is *authority bleed*: if any customs /
clearance / monitor consumer ever read ``vision_invoice`` as a CIF source, a
low-confidence OCR guess would silently become a customs value — exactly the
fake-zero / poisoned-authority class ``cif_resolver`` was built to kill.

These tests are the negative-scope guard. They are failing-first by
construction: the day someone adds ``vision_invoice`` to the CIF ladder (or any
clearance/monitor consumer starts reading it), one of these assertions breaks.

What is pinned
--------------
1. resolve_cif IGNORES vision_invoice — a CIF-shaped value buried in
   vision_invoice never changes the tri-state outcome (stays UNKNOWN when no
   real ladder layer produced a value; an unrelated vision_invoice never
   perturbs a genuinely RESOLVED value).
2. build_clearance_decision IGNORES vision_invoice — its resolved CIF/source is
   identical with and without a vision_invoice block present.
3. SOURCE CONTRACT — cif_resolver.py does not name ``vision_invoice`` at all,
   and the CIF authority ladder layer-labels do not include it.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.cif_resolver import resolve_cif, CIF_RESOLVED, CIF_UNKNOWN


# A deliberately loud, high-value CIF-shaped proposal. If ANY consumer wrongly
# read vision_invoice as a customs value, this 99999 would leak into the result.
_POISON_VISION_INVOICE = {
    "operator_confirmed": False,
    "source": "vision_llm",
    "confidence": 0.95,
    "supplier": "ACME EXPORTS",
    "fob_usd": 99999.0,
    "currency": "USD",
    "line_items": [
        {"description": "GOLD RING", "quantity": 1, "unit_price_usd": 99999.0, "total_usd": 99999.0},
    ],
    "itemization_unavailable": False,
    # CIF-shaped keys an over-eager future consumer might grab:
    "cif_usd": 99999.0,
    "total_cif_usd": 99999.0,
    "invoice_cif_total_usd": 99999.0,
}


def test_resolve_cif_ignores_vision_invoice_when_unknown():
    """No real ladder layer → UNKNOWN, even with a CIF-shaped vision_invoice."""
    audit = {
        "inputs": {"invoices": ["inv_122.pdf"]},
        "invoice_totals": {},          # nothing parsed
        "vision_invoice": dict(_POISON_VISION_INVOICE),
    }
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_UNKNOWN, res
    assert res["cif_usd"] is None, "vision_invoice must NEVER become a CIF value"
    assert res["cif_source"] == "unavailable"
    # And the 99999 poison must not appear anywhere in the resolver trace.
    assert all(a.get("value") != 99999.0 for a in res["attempts"]), res["attempts"]


def test_resolve_cif_unchanged_by_vision_invoice_when_resolved():
    """A genuinely RESOLVED CIF (AWB Custom Val) is identical with/without the
    vision_invoice block — the proposal never perturbs real authority."""
    base = {
        "inputs": {"invoices": ["inv_122.pdf"]},
        "invoice_totals": {},
        "awb_customs": {"value_usd": 732.0, "currency": "USD", "gap": False},
    }
    without = resolve_cif(dict(base))
    with_vi = dict(base)
    with_vi["vision_invoice"] = dict(_POISON_VISION_INVOICE)
    got = resolve_cif(with_vi)

    assert without["cif_state"] == CIF_RESOLVED and without["cif_usd"] == 732.0
    assert got["cif_state"] == without["cif_state"]
    assert got["cif_usd"] == without["cif_usd"] == 732.0
    assert got["cif_source"] == without["cif_source"] == "awb_customs.value_usd"


def test_build_clearance_decision_ignores_vision_invoice():
    """clearance_decision delegates CIF to resolve_cif and never reads
    vision_invoice — its resolved value/source is invariant to the block."""
    from app.services.clearance_decision import build_clearance_decision

    base = {
        "inputs": {"invoices": ["inv_122.pdf"]},
        "invoice_totals": {},
        "awb_customs": {"value_usd": 732.0, "currency": "USD", "gap": False},
    }
    dec_without = build_clearance_decision(dict(base))
    with_vi = dict(base)
    with_vi["vision_invoice"] = dict(_POISON_VISION_INVOICE)
    dec_with = build_clearance_decision(with_vi)

    # Whatever CIF-bearing fields the decision exposes, they must match exactly.
    for k in ("cif_usd", "cif_state", "cif_source", "total_value_usd"):
        assert dec_with.get(k) == dec_without.get(k), (
            f"clearance_decision.{k} changed when vision_invoice was added — "
            f"authority bleed: {dec_without.get(k)!r} -> {dec_with.get(k)!r}"
        )
    # And the poison value must not surface as the routing value.
    assert dec_with.get("total_value_usd") != 99999.0


def test_source_contract_cif_resolver_does_not_name_vision_invoice():
    """Static guard: the CIF resolver source must not reference vision_invoice."""
    src = (Path(_SVC) / "app" / "services" / "cif_resolver.py").read_text(encoding="utf-8")
    assert "vision_invoice" not in src, (
        "cif_resolver.py references vision_invoice — the advisory invoice "
        "proposal must never be a CIF authority source (authority isolation)."
    )


def test_source_contract_clearance_decision_does_not_name_vision_invoice():
    """Static guard: the clearance decision builder must not read vision_invoice.

    clearance_decision delegates CIF entirely to resolve_cif. If this source ever
    started naming vision_invoice, a low-confidence OCR proposal could leak into a
    customs routing decision — the exact authority bleed this module guards."""
    src = (Path(_SVC) / "app" / "services" / "clearance_decision.py").read_text(encoding="utf-8")
    assert "vision_invoice" not in src, (
        "clearance_decision.py references vision_invoice — the advisory invoice "
        "proposal must never influence a clearance/customs decision."
    )


def test_source_contract_active_shipment_monitor_does_not_name_vision_invoice():
    """Static guard: the active-shipment monitor must not read vision_invoice.

    The monitor surfaces CIF/value state via resolve_cif. Reading the advisory
    proposal here would let an unconfirmed OCR guess drive monitor status —
    authority bleed into the operator-facing shipment view."""
    src = (Path(_SVC) / "app" / "services" / "active_shipment_monitor.py").read_text(encoding="utf-8")
    assert "vision_invoice" not in src, (
        "active_shipment_monitor.py references vision_invoice — the advisory "
        "invoice proposal must never drive monitor/shipment status."
    )
