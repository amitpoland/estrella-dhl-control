"""
test_proforma_birth_name_pl_authority.py — Campaign 04 PR3:
birth-pipeline authority fix for proforma drafts.

Root cause being pinned: drafts born from sales packing silently lost
commercial-description authority (``name_pl``) because the birth caller +
normaliser carried only the 7 sales columns and never name_pl, and the
product_descriptions enrichment helper — though it existed — was only ever
invoked by an operator-triggered endpoint, never at birth. Zero/missing
unit_price was likewise accepted with no visibility surface.

The fix:
  * birth (``auto_create_draft_from_sales_packing``) and reset
    (``reset_draft_from_sales_packing``) now normalise a ``name_pl`` key and,
    when a ``name_pl_lookup`` is supplied, fill BLANK name_pl from the
    product_descriptions authority — never fabricating, never overwriting an
    operator-confirmed value;
  * a NON-AUTHORITATIVE birth advisory (``birth_unresolved``) is recorded in
    the ``created_from_sales_packing`` / ``draft_reset_from_sales_packing``
    event detail for any line born with a blank name_pl (after enrichment) or
    a zero/missing unit_price. It is visibility only — never stored on the
    draft row, never blocks creation, never readiness truth.

These tests exercise the DB layer directly with a dict-backed lookup_fn so no
real document_db / product_descriptions table is required.

Coverage (the 10 contract tests):
  1. birth enriches name_pl from product_descriptions authority
  2. birth leaves name_pl blank when there is no product_descriptions authority
  3. birth records advisory for a zero-price line
  4. birth records advisory for a blank name_pl after an enrichment miss
  5. birth does NOT store ready/blocked truth anywhere
  6. birth preserves unit_price and price_source untouched
  7. birth does NOT overwrite an operator-confirmed name_pl
  8. reset preserves the prior operator-confirmed name_pl (no strip-to-blank)
  9. reset enriches a blank name_pl from the product_descriptions authority
 10. reset records the same non-authoritative advisory as birth
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import proforma_invoice_link_db as pildb


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


# A dict-backed product_descriptions authority. Mirrors the shape returned by
# document_db.get_product_description: a row dict (or None on a miss).
_PD_AUTHORITY = {
    "RNG-100": {"name_pl": "Pierścionek złoty", "item_type": "ring",
                "description_pl": "Pierścionek", "description_en": "Ring",
                "confidence": "high"},
    "NCK-200": {"name_pl": "Naszyjnik srebrny", "item_type": "necklace"},
}


def _lookup(product_code):
    """name_pl_lookup Callable: returns the PD row dict or None on a miss."""
    return _PD_AUTHORITY.get(str(product_code or "").strip())


def _line(product_code, *, name_pl="", unit_price=10.0, price_source="excel_symbol",
          design_no="D1", currency="EUR", client_ref="REF1"):
    return {
        "product_code": product_code,
        "design_no":    design_no,
        "quantity":     2,
        "unit_price":   unit_price,
        "currency":     currency,
        "price_source": price_source,
        "client_ref":   client_ref,
        "name_pl":      name_pl,
    }


def _editable(draft) -> list:
    return json.loads(draft.editable_lines_json or "[]")


def _birth_event_detail(db_path, draft_id) -> dict:
    for ev in pildb.list_draft_events(db_path, draft_id):
        if ev["event"] == "created_from_sales_packing":
            return json.loads(ev["detail_json"] or "{}")
    raise AssertionError("created_from_sales_packing event not found")


def _reset_event_detail(db_path, draft_id) -> dict:
    # last reset event wins
    detail = None
    for ev in pildb.list_draft_events(db_path, draft_id):
        if ev["event"] == "draft_reset_from_sales_packing":
            detail = json.loads(ev["detail_json"] or "{}")
    if detail is None:
        raise AssertionError("draft_reset_from_sales_packing event not found")
    return detail


# ── 1. birth enriches name_pl from product_descriptions ──────────────────────

def test_birth_enriches_name_pl_from_product_descriptions(db_path):
    draft, created = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME", currency="EUR",
        lines=[_line("RNG-100", name_pl="")],
        name_pl_lookup=_lookup,
    )
    assert created is True
    lines = _editable(draft)
    assert len(lines) == 1
    assert lines[0]["name_pl"] == "Pierścionek złoty"


# ── 2. birth leaves name_pl blank when no PD authority ───────────────────────

def test_birth_leaves_name_pl_blank_on_enrichment_miss(db_path):
    draft, created = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B2", client_name="ACME", currency="EUR",
        lines=[_line("UNKNOWN-999", name_pl="")],
        name_pl_lookup=_lookup,
    )
    assert created is True
    lines = _editable(draft)
    # A PD miss must NOT fabricate a name — blank stays blank.
    assert lines[0]["name_pl"] == ""


# ── 3. birth records advisory for a zero-price line ──────────────────────────

def test_birth_records_advisory_for_zero_price_line(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B3", client_name="ACME", currency="EUR",
        lines=[_line("RNG-100", name_pl="X", unit_price=0.0)],
        name_pl_lookup=_lookup,
    )
    detail = _birth_event_detail(db_path, draft.id)
    unresolved = detail["birth_unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0]["product_code"] == "RNG-100"
    assert "zero_unit_price" in unresolved[0]["reasons"]
    # name_pl was provided, so it is NOT flagged blank.
    assert "blank_name_pl" not in unresolved[0]["reasons"]


# ── 4. birth records advisory for blank name_pl after enrichment miss ────────

def test_birth_records_advisory_for_blank_name_pl(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B4", client_name="ACME", currency="EUR",
        lines=[_line("UNKNOWN-999", name_pl="", unit_price=25.0)],
        name_pl_lookup=_lookup,
    )
    detail = _birth_event_detail(db_path, draft.id)
    unresolved = detail["birth_unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0]["product_code"] == "UNKNOWN-999"
    assert "blank_name_pl" in unresolved[0]["reasons"]
    # unit_price was positive, so zero_unit_price is NOT flagged.
    assert "zero_unit_price" not in unresolved[0]["reasons"]


def test_birth_advisory_empty_when_all_lines_resolved(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B4b", client_name="ACME", currency="EUR",
        lines=[_line("RNG-100", name_pl="", unit_price=12.0)],  # enriched + priced
        name_pl_lookup=_lookup,
    )
    detail = _birth_event_detail(db_path, draft.id)
    assert detail["birth_unresolved"] == []


# ── 5. birth does NOT store ready/blocked truth ──────────────────────────────

def test_birth_does_not_store_readiness_truth(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B5", client_name="ACME", currency="EUR",
        lines=[_line("UNKNOWN-999", name_pl="", unit_price=0.0)],  # worst case
        name_pl_lookup=_lookup,
    )
    # No readiness field smuggled onto the draft row / dataclass.
    for forbidden in ("ready", "blocked", "is_ready", "readiness"):
        assert not hasattr(draft, forbidden), f"draft exposes {forbidden}"
    # No readiness key smuggled into the persisted editable line shape.
    for ln in _editable(draft):
        for forbidden in ("ready", "blocked", "is_ready", "readiness"):
            assert forbidden not in ln, f"editable line carries {forbidden}"
    # The advisory lives in the EVENT detail, not on the draft.
    detail = _birth_event_detail(db_path, draft.id)
    assert "birth_unresolved" in detail
    for forbidden in ("ready", "blocked", "readiness"):
        assert forbidden not in detail


# ── 6. birth preserves unit_price and price_source ───────────────────────────

def test_birth_preserves_unit_price_and_price_source(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B6", client_name="ACME", currency="EUR",
        lines=[_line("RNG-100", name_pl="", unit_price=37.5,
                     price_source="packing_xlsx_value")],
        name_pl_lookup=_lookup,
    )
    ln = _editable(draft)[0]
    assert ln["unit_price"] == 37.5
    assert ln["price_source"] == "packing_xlsx_value"
    assert ln["currency"] == "EUR"


# ── 7. birth does NOT overwrite operator-confirmed name_pl ───────────────────

def test_birth_does_not_overwrite_confirmed_name_pl(db_path):
    # RNG-100 has a PD authority value "Pierścionek złoty", but the caller
    # supplies an already-confirmed name_pl. Enrichment must not clobber it.
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B7", client_name="ACME", currency="EUR",
        lines=[_line("RNG-100", name_pl="Operator Curated Name")],
        name_pl_lookup=_lookup,
    )
    assert _editable(draft)[0]["name_pl"] == "Operator Curated Name"


# ── 8. reset preserves prior operator-confirmed name_pl ──────────────────────

def test_reset_preserves_prior_name_pl(db_path):
    # Birth with a confirmed name_pl for a code with NO PD authority, so the
    # only way name_pl survives reset is the prior-name re-inheritance path.
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B8", client_name="ACME", currency="EUR",
        lines=[_line("UNKNOWN-999", name_pl="Curated Survivor")],
        name_pl_lookup=_lookup,
    )
    fresh = pildb.get_draft_by_id(db_path, draft.id)
    # Reset feeds sales lines that DO NOT carry name_pl (the lossy birth shape).
    reset_lines = [_line("UNKNOWN-999", name_pl="", unit_price=10.0)]
    refreshed = pildb.reset_draft_from_sales_packing(
        db_path, draft.id, operator="tester",
        expected_updated_at=fresh.updated_at,
        sales_lines=reset_lines, name_pl_lookup=_lookup,
    )
    ln = _editable(refreshed)[0]
    assert ln["name_pl"] == "Curated Survivor", "reset stripped name_pl to blank"


# ── 9. reset enriches a blank name_pl from product_descriptions ──────────────

def test_reset_enriches_blank_name_pl(db_path):
    # Birth a line with no name_pl and no PD hit so it is born blank.
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B9", client_name="ACME", currency="EUR",
        lines=[_line("UNKNOWN-999", name_pl="")],
        name_pl_lookup=_lookup,
    )
    fresh = pildb.get_draft_by_id(db_path, draft.id)
    # Reset now feeds a code that HAS PD authority — enrichment must fill it.
    refreshed = pildb.reset_draft_from_sales_packing(
        db_path, draft.id, operator="tester",
        expected_updated_at=fresh.updated_at,
        sales_lines=[_line("NCK-200", name_pl="", unit_price=15.0)],
        name_pl_lookup=_lookup,
    )
    ln = _editable(refreshed)[0]
    assert ln["product_code"] == "NCK-200"
    assert ln["name_pl"] == "Naszyjnik srebrny"


# ── 10. reset records the same non-authoritative advisory ────────────────────

def test_reset_records_birth_unresolved_advisory(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B10", client_name="ACME", currency="EUR",
        lines=[_line("RNG-100", name_pl="X", unit_price=5.0)],
        name_pl_lookup=_lookup,
    )
    fresh = pildb.get_draft_by_id(db_path, draft.id)
    # Reset to a worst-case line: blank name_pl (PD miss) + zero price.
    pildb.reset_draft_from_sales_packing(
        db_path, draft.id, operator="tester",
        expected_updated_at=fresh.updated_at,
        sales_lines=[_line("UNKNOWN-999", name_pl="", unit_price=0.0)],
        name_pl_lookup=_lookup,
    )
    detail = _reset_event_detail(db_path, draft.id)
    unresolved = detail["birth_unresolved"]
    assert len(unresolved) == 1
    assert set(unresolved[0]["reasons"]) == {"blank_name_pl", "zero_unit_price"}


# ── invariant: lookup_fn=None is a pure no-op (no enrichment, blank stays) ────

def test_birth_without_lookup_is_noop(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B11", client_name="ACME", currency="EUR",
        lines=[_line("RNG-100", name_pl="")],  # PD authority exists...
        name_pl_lookup=None,                    # ...but no lookup wired
    )
    # Without a lookup, name_pl must remain blank (no DB I/O, no fabrication).
    assert _editable(draft)[0]["name_pl"] == ""
    # And the blank is still surfaced in the advisory.
    detail = _birth_event_detail(db_path, draft.id)
    assert any("blank_name_pl" in u["reasons"] for u in detail["birth_unresolved"])
