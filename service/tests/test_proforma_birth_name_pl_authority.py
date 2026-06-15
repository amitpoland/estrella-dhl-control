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


# ════════════════════════════════════════════════════════════════════════════
# Campaign 04 PR4 — generated name_pl fallback + name_pl_source provenance +
# missing-product-mapping birth advisory.
#
# These use the REAL generate_name_pl_if_sufficient (no stub — Lesson A: the
# function under contract is exercised directly) and a dict-backed mapping
# authority that is read-only by construction (it cannot write wFirma).
# ════════════════════════════════════════════════════════════════════════════

from app.api.sales_packing_parser import generate_name_pl_if_sufficient


# A read-only wFirma product-mapping authority. Mirrors wfirma_db.get_product:
# a row dict carrying wfirma_product_id (truthy ⇒ mapped) or None on a miss.
_MAPPING_AUTHORITY = {
    "RNG-100": {"wfirma_product_id": 555},   # mapped
    "NCK-200": {"wfirma_product_id": 0},     # row exists but unmapped (falsy)
    # UNKNOWN-999 → absent ⇒ unmapped
}


def _mapping_lookup(product_code):
    return _MAPPING_AUTHORITY.get(str(product_code or "").strip())


def _attr_line(product_code, *, name_pl="", unit_price=10.0,
               ctg="", kt="", col="", quality="", price_source="excel_symbol"):
    """A sales line carrying the optional generate-fallback attributes."""
    return {
        "product_code": product_code,
        "design_no":    "D1",
        "quantity":     2,
        "unit_price":   unit_price,
        "currency":     "EUR",
        "price_source": price_source,
        "client_ref":   "REF1",
        "name_pl":      name_pl,
        "ctg":          ctg,
        "kt":           kt,
        "col":          col,
        "quality":      quality,
    }


def _reasons_for(detail, product_code) -> set:
    for u in detail.get("birth_unresolved", []):
        if u["product_code"] == product_code:
            return set(u["reasons"])
    return set()


# ── PR4-1. generated fallback fills name_pl when PD misses + attrs sufficient ─

def test_birth_generated_fallback_when_pd_misses(db_path):
    # UNKNOWN-999 has NO product_descriptions authority, but the line carries a
    # recognised category (RNG) ⇒ the generator supplies a real Polish name.
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="P1", client_name="ACME", currency="EUR",
        lines=[_attr_line("UNKNOWN-999", name_pl="", ctg="RNG",
                          kt="14KT", col="W", quality="GH-SI1")],
        name_pl_lookup=_lookup,
        desc_generate=generate_name_pl_if_sufficient,
    )
    ln = _editable(draft)[0]
    assert ln["name_pl"], "generator should have produced a non-blank name_pl"
    assert "pierścionek" in ln["name_pl"].lower()
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_GENERATED
    # transient attrs must not persist
    assert "_gen_attrs" not in ln


# ── PR4-2. anti-fabrication: generator declines for an unknown category ──────

def test_birth_generated_declines_for_unknown_category(db_path):
    # ctg "ZZZ" is not a recognised category ⇒ generate_name_pl_if_sufficient
    # returns None ⇒ name_pl stays blank, source=blank (never the generic
    # "wyrób" placeholder).
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="P2", client_name="ACME", currency="EUR",
        lines=[_attr_line("UNKNOWN-999", name_pl="", ctg="ZZZ",
                          kt="14KT", col="W", quality="GH-SI1")],
        name_pl_lookup=_lookup,
        desc_generate=generate_name_pl_if_sufficient,
    )
    ln = _editable(draft)[0]
    assert ln["name_pl"] == ""
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_BLANK


# ── PR4-3. name_pl_source stamped correctly for all four provenance values ───

def test_birth_name_pl_source_all_four_values(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="P3", client_name="ACME", currency="EUR",
        lines=[
            _attr_line("RNG-100",     name_pl="Operator Curated"),  # operator
            _attr_line("NCK-200",     name_pl=""),                  # product_descriptions
            _attr_line("UNKNOWN-999", name_pl="", ctg="EAR"),       # generated
            _attr_line("BLANK-000",   name_pl="", ctg=""),          # blank
        ],
        name_pl_lookup=_lookup,
        desc_generate=generate_name_pl_if_sufficient,
    )
    by_code = {ln["product_code"]: ln for ln in _editable(draft)}
    assert by_code["RNG-100"]["name_pl_source"]     == pildb.NAME_PL_SOURCE_OPERATOR
    assert by_code["RNG-100"]["name_pl"]            == "Operator Curated"
    assert by_code["NCK-200"]["name_pl_source"]     == pildb.NAME_PL_SOURCE_PD
    assert by_code["NCK-200"]["name_pl"]            == "Naszyjnik srebrny"
    assert by_code["UNKNOWN-999"]["name_pl_source"] == pildb.NAME_PL_SOURCE_GENERATED
    assert by_code["UNKNOWN-999"]["name_pl"]
    assert by_code["BLANK-000"]["name_pl_source"]   == pildb.NAME_PL_SOURCE_BLANK
    assert by_code["BLANK-000"]["name_pl"]          == ""


# ── PR4-4. missing_product_mapping advisory — only when lookup supplied ───────

def test_birth_missing_product_mapping_advisory(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="P4", client_name="ACME", currency="EUR",
        lines=[
            _attr_line("RNG-100",     name_pl="Has Name", unit_price=10.0),  # mapped
            _attr_line("NCK-200",     name_pl="Has Name", unit_price=10.0),  # unmapped (id=0)
            _attr_line("UNKNOWN-999", name_pl="Has Name", unit_price=10.0),  # unmapped (absent)
        ],
        name_pl_lookup=_lookup,
        desc_generate=generate_name_pl_if_sufficient,
        product_mapping_lookup=_mapping_lookup,
    )
    detail = _birth_event_detail(db_path, draft.id)
    # mapped product carries NO missing_product_mapping
    assert "missing_product_mapping" not in _reasons_for(detail, "RNG-100")
    # unmapped products are flagged (read-only mapping check; never writes wFirma)
    assert "missing_product_mapping" in _reasons_for(detail, "NCK-200")
    assert "missing_product_mapping" in _reasons_for(detail, "UNKNOWN-999")


def test_birth_no_mapping_advisory_without_lookup(db_path):
    # Backward-compat: with no product_mapping_lookup, the mapping is simply
    # not assessed — no missing_product_mapping reason is ever emitted.
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="P5", client_name="ACME", currency="EUR",
        lines=[_attr_line("UNKNOWN-999", name_pl="Has Name", unit_price=10.0)],
        name_pl_lookup=_lookup,
        desc_generate=generate_name_pl_if_sufficient,
        # product_mapping_lookup omitted
    )
    detail = _birth_event_detail(db_path, draft.id)
    assert "missing_product_mapping" not in _reasons_for(detail, "UNKNOWN-999")


# ── PR4-5. reset uses the same generated fallback + mapping advisory ─────────

def test_reset_generated_fallback_and_mapping_advisory(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="P6", client_name="ACME", currency="EUR",
        lines=[_attr_line("RNG-100", name_pl="Seed", unit_price=10.0)],
        name_pl_lookup=_lookup,
        desc_generate=generate_name_pl_if_sufficient,
        product_mapping_lookup=_mapping_lookup,
    )
    fresh = pildb.get_draft_by_id(db_path, draft.id)
    refreshed = pildb.reset_draft_from_sales_packing(
        db_path, draft.id, operator="tester",
        expected_updated_at=fresh.updated_at,
        sales_lines=[_attr_line("UNKNOWN-999", name_pl="", ctg="BRC",
                                unit_price=10.0)],
        name_pl_lookup=_lookup,
        desc_generate=generate_name_pl_if_sufficient,
        product_mapping_lookup=_mapping_lookup,
    )
    ln = _editable(refreshed)[0]
    # generated fallback applied in reset path
    assert ln["name_pl"], "reset generator produced no name_pl"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_GENERATED
    assert "_gen_attrs" not in ln
    # mapping advisory applied in reset path
    detail = _reset_event_detail(db_path, draft.id)
    assert "missing_product_mapping" in _reasons_for(detail, "UNKNOWN-999")


# ── PR4-6. reset name_pl_source = product_descriptions on a PD hit ───────────

def test_reset_stamps_pd_source(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="P7", client_name="ACME", currency="EUR",
        lines=[_attr_line("UNKNOWN-999", name_pl="", unit_price=10.0)],
        name_pl_lookup=_lookup,
        desc_generate=generate_name_pl_if_sufficient,
    )
    fresh = pildb.get_draft_by_id(db_path, draft.id)
    refreshed = pildb.reset_draft_from_sales_packing(
        db_path, draft.id, operator="tester",
        expected_updated_at=fresh.updated_at,
        sales_lines=[_attr_line("RNG-100", name_pl="", unit_price=10.0)],
        name_pl_lookup=_lookup,
        desc_generate=generate_name_pl_if_sufficient,
    )
    ln = _editable(refreshed)[0]
    assert ln["name_pl"] == "Pierścionek złoty"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_PD
