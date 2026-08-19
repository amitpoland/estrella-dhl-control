"""
test_proforma_line_enrichment.py — PR 2C: product-description enrichment.

Coverage:
  1. test_enrich_lines_pure_all_found        — all lines matched, 5 fields set
  2. test_enrich_lines_pure_missing_code     — blank code → None fields, no crash
  3. test_enrich_lines_preserves_pricing     — qty/unit_price/currency/price_source
                                               left untouched by enrichment
  4. test_enrich_lines_low_confidence_accepted — confidence "low" accepted (no filter)
  5. test_enrich_draft_persists_to_db        — enriched fields are in DB after call
  6. test_enrich_draft_source_lines_json_untouched — source_lines_json never mutated
  7. test_enrich_draft_records_event         — event row written with correct detail
  8. test_enrich_draft_blocked_approved_state — approved draft raises DraftNotEditable
  9. test_enrich_idempotent                  — calling twice, same data → same result
 10. test_enrich_state_unchanged             — draft stays 'draft', not 'editing'
 11. test_route_requires_expected_updated_at — missing field → HTTP 400
 12. test_dashboard_has_enrich_button_and_columns — HTML assertions
 13. test_enrich_clears_stale_description_warning — PD now present → own stale
                                               warning dropped, key removed
 14. test_enrich_description_warning_not_duplicated — repeated passes emit ONE
 15. test_enrich_preserves_foreign_warning  — another producer's _warnings kept
 16. test_recompute_line_warning_is_per_producer — the shared helper both
                                               producers route through
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb


# ── Fixtures & helpers ────────────────────────────────────────────────────────

def _auth_headers(operator: str = "alice"):
    return {
        "X-API-KEY":  settings.api_key or "test-key",
        "X-Operator": operator,
    }


@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


@pytest.fixture()
def client(tmp_path) -> TestClient:
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _seed_draft(db: Path, batch: str = "B1", client_name: str = "ACME",
                currency: str = "EUR"):
    """Create a draft with two lines and return it."""
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db,
        batch_id    = batch,
        client_name = client_name,
        currency    = currency,
        lines       = [
            {
                "product_code": "EJL-RNG-417G",
                "design_no":    "D100",
                "qty":           2,
                "unit_price":    25.50,
                "currency":      currency,
                "price_source":  "packing_list",
                "client_ref":    "PO-9001",
            },
            {
                "product_code": "EJL-PND-ROSE",
                "design_no":    "D200",
                "qty":           1,
                "unit_price":    100.0,
                "currency":      currency,
                "price_source":  "packing_list",
                "client_ref":    "",
            },
        ],
        operator = "intake",
    )
    return draft


_PD_ROW_417G: Dict[str, Any] = {
    "product_code":         "EJL-RNG-417G",
    "item_type":            "RING",
    "name_pl":              "Pierścionek złoty",
    "description_pl":       "Pierścionek złoty 585",
    "description_en":       "Gold ring 585",
    "description_bilingual": "Pierścionek złoty 585 / Gold ring 585",
    "confidence":           "high",
}

_PD_ROW_ROSE: Dict[str, Any] = {
    "product_code":         "EJL-PND-ROSE",
    "item_type":            "PENDANT",
    "name_pl":              "Wisiorek różowe złoto",
    "description_pl":       "Wisiorek różowe złoto 585",
    "description_en":       "Rose gold pendant 585",
    "description_bilingual": "Wisiorek różowe złoto 585 / Rose gold pendant 585",
    "confidence":           "medium",
}


def _lookup_both(pc: str) -> Optional[Dict[str, Any]]:
    data = {"EJL-RNG-417G": _PD_ROW_417G, "EJL-PND-ROSE": _PD_ROW_ROSE}
    return data.get(pc)


def _lookup_none(_pc: str) -> Optional[Dict[str, Any]]:
    return None


# ── 1. Pure function — all found ──────────────────────────────────────────────

def test_enrich_lines_pure_all_found():
    lines = [
        {"line_id": 1, "product_code": "EJL-RNG-417G",
         "qty": 2, "unit_price": 25.50, "currency": "EUR"},
        {"line_id": 2, "product_code": "EJL-PND-ROSE",
         "qty": 1, "unit_price": 100.0, "currency": "EUR"},
    ]
    enriched, n_hit, n_miss = pildb.enrich_lines_from_product_descriptions(
        lines, _lookup_both
    )
    assert n_hit  == 2
    assert n_miss == 0
    assert len(enriched) == 2

    r = enriched[0]
    assert r["item_type"]             == "RING"
    # Commercial name_pl is the usable description_pl (preferred over PD name_pl).
    assert r["name_pl"]               == "Pierścionek złoty 585"
    assert r["description_pl"]        == "Pierścionek złoty 585"
    assert r["description_en"]        == "Gold ring 585"
    assert r["description_bilingual"] == "Pierścionek złoty 585 / Gold ring 585"
    assert r["pd_confidence"]         == "high"

    r2 = enriched[1]
    assert r2["item_type"] == "PENDANT"
    assert r2["pd_confidence"] == "medium"


# ── 2. Pure function — missing code → None fields, no crash ──────────────────

def test_enrich_lines_pure_missing_code():
    lines = [
        {"line_id": 1, "product_code": "",
         "qty": 1, "unit_price": 10.0, "currency": "EUR"},
        {"line_id": 2, "product_code": "UNKNOWN-XYZ",
         "qty": 1, "unit_price": 10.0, "currency": "EUR"},
    ]
    enriched, n_hit, n_miss = pildb.enrich_lines_from_product_descriptions(
        lines, _lookup_none
    )
    assert n_hit  == 0
    assert n_miss == 2
    for ln in enriched:
        assert ln["item_type"]             is None
        assert ln["name_pl"]               is None
        assert ln["description_pl"]        is None
        assert ln["description_en"]        is None
        assert ln["description_bilingual"] is None
        assert ln["pd_confidence"]         is None


# ── 3. Pricing fields never mutated ──────────────────────────────────────────

def test_enrich_lines_preserves_pricing():
    lines = [
        {
            "line_id":      99,
            "product_code": "EJL-RNG-417G",
            "qty":           3,
            "unit_price":    99.99,
            "currency":      "USD",
            "price_source":  "manual",
            "client_ref":    "PO-X",
        }
    ]
    enriched, _, _ = pildb.enrich_lines_from_product_descriptions(
        lines, _lookup_both
    )
    r = enriched[0]
    # Pricing fields must be identical.
    assert r["qty"]          == 3
    assert r["unit_price"]   == 99.99
    assert r["currency"]     == "USD"
    assert r["price_source"] == "manual"
    assert r["client_ref"]   == "PO-X"
    # Annotation fields must be set.
    assert r["item_type"] == "RING"
    assert r["name_pl"]   == "Pierścionek złoty 585"


# ── 4. Low-confidence accepted (no confidence filter) ─────────────────────────

def test_enrich_lines_low_confidence_accepted():
    low_row = {**_PD_ROW_417G, "confidence": "low"}
    enriched, n_hit, _ = pildb.enrich_lines_from_product_descriptions(
        [{"line_id": 1, "product_code": "EJL-RNG-417G",
          "qty": 1, "unit_price": 10.0}],
        lambda pc: low_row if pc == "EJL-RNG-417G" else None,
    )
    assert n_hit == 1
    assert enriched[0]["pd_confidence"] == "low"
    assert enriched[0]["name_pl"]       == "Pierścionek złoty 585"


# ── 5. Enrichment persists to DB ─────────────────────────────────────────────

def test_enrich_draft_persists_to_db(db_path):
    d = _seed_draft(db_path)
    refreshed = pildb.enrich_draft_lines(
        db_path, d.id, "alice", d.updated_at, _lookup_both
    )
    lines = json.loads(refreshed.editable_lines_json)
    by_code = {ln["product_code"]: ln for ln in lines}
    assert by_code["EJL-RNG-417G"]["name_pl"]   == "Pierścionek złoty 585"
    assert by_code["EJL-PND-ROSE"]["item_type"] == "PENDANT"

    # Verify the data really is in the DB, not just in the returned object.
    stored = pildb.get_draft_by_id(db_path, d.id)
    stored_lines = json.loads(stored.editable_lines_json)
    by_code2 = {ln["product_code"]: ln for ln in stored_lines}
    assert by_code2["EJL-RNG-417G"]["item_type"]             == "RING"
    assert by_code2["EJL-RNG-417G"]["description_bilingual"] == \
        "Pierścionek złoty 585 / Gold ring 585"


# ── 6. source_lines_json never touched ───────────────────────────────────────

def test_enrich_draft_source_lines_json_untouched(db_path):
    d = _seed_draft(db_path)
    original_source = d.source_lines_json

    pildb.enrich_draft_lines(
        db_path, d.id, "alice", d.updated_at, _lookup_both
    )

    stored = pildb.get_draft_by_id(db_path, d.id)
    assert stored.source_lines_json == original_source, (
        "source_lines_json was mutated — enrichment must NEVER touch it"
    )
    # Confirm source lines do NOT have annotation fields.
    source_lines = json.loads(stored.source_lines_json)
    for ln in source_lines:
        assert "name_pl"   not in ln
        assert "item_type" not in ln


# ── 6b. Birth INSERT writes raw source, not the editable shape (#593 Cluster A) ─

def test_birth_source_lines_json_is_raw_only(db_path):
    """#593 Cluster A — auto_create_draft_from_sales_packing must snapshot
    source_lines_json as the RAW sales-packing record only. The bug it guards
    against: the birth INSERT wrote the same name_pl-annotated editable blob
    into BOTH source_lines_json and editable_lines_json, polluting the
    immutable source record at birth (before any enrichment ever runs).

    This asserts the contract directly at birth — it does NOT depend on the
    enrichment code path, so it pins the fix at its true root cause.
    """
    d = _seed_draft(db_path)

    source = json.loads(d.source_lines_json)
    assert len(source) == 2, "both seeded lines must be present in source"
    for ln in source:
        # Annotation / transient fields must NEVER be in source.
        assert "name_pl"    not in ln
        assert "item_type"  not in ln
        assert "_gen_attrs" not in ln
        # Source carries the raw sales_packing columns — and only those.
        # 2026-07-10 (wireframe Slice 1): the raw set now includes the
        # variant-identity sales_packing columns (client_po, karat, metal,
        # metal_color, quality_string, size, diamond_weight, color_weight)
        # that were previously silently dropped at the birth boundary.
        # These are RAW caller-supplied columns, not annotations — the
        # guarded invariant (no name_pl / item_type / _gen_attrs pollution)
        # is unchanged and still asserted above.
        assert set(ln.keys()) == {
            "product_code", "design_no", "qty", "unit_price",
            "currency", "price_source", "client_ref",
            "client_po", "karat", "metal", "metal_color",
            "quality_string", "stone_type", "size",
            "diamond_weight", "color_weight",
        }

    # The editable copy IS the annotated working shape and carries name_pl
    # (blank at birth here, since _seed_draft supplies no name_pl_lookup).
    editable = json.loads(d.editable_lines_json)
    assert len(editable) == 2
    assert all("name_pl" in ln for ln in editable), (
        "editable_lines_json must keep the name_pl annotation"
    )
    # _gen_attrs is transient and must not persist on either side.
    assert all("_gen_attrs" not in ln for ln in editable)


# ── 7. Event recorded ────────────────────────────────────────────────────────

def test_enrich_draft_records_event(db_path):
    d = _seed_draft(db_path)
    pildb.enrich_draft_lines(
        db_path, d.id, "alice", d.updated_at, _lookup_both
    )
    events = pildb.list_draft_events(db_path, d.id)
    enriched_events = [
        e for e in events
        if e.get("event") == "lines_enriched_from_product_descriptions"
    ]
    assert len(enriched_events) == 1
    detail = json.loads(enriched_events[0]["detail_json"])
    assert detail["enriched_count"] == 2
    assert detail["missing_count"]  == 0
    assert detail["line_count"]     == 2
    assert enriched_events[0].get("operator") == "alice"


# ── 8. Blocked in approved state ─────────────────────────────────────────────

def test_enrich_draft_blocked_approved_state(db_path):
    d = _seed_draft(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        # Leave status='draft' (the Phase-2 legacy value) — setting
        # status='issued' would cause _ensure_drafts_table's migration loop
        # to snap draft_state back to 'posted' on every connection open.
        conn.execute(
            "UPDATE proforma_drafts SET draft_state='approved' WHERE id=?",
            (d.id,),
        )
        conn.commit()
    fresh = pildb.get_draft_by_id(db_path, d.id)
    assert fresh.draft_state == "approved"

    with pytest.raises(pildb.DraftNotEditable):
        pildb.enrich_draft_lines(
            db_path, fresh.id, "alice", fresh.updated_at, _lookup_both
        )


# ── 9. Idempotent ─────────────────────────────────────────────────────────────

def test_enrich_idempotent(db_path):
    d = _seed_draft(db_path)
    r1 = pildb.enrich_draft_lines(
        db_path, d.id, "alice", d.updated_at, _lookup_both
    )
    r2 = pildb.enrich_draft_lines(
        db_path, r1.id, "alice", r1.updated_at, _lookup_both
    )
    lines1 = json.loads(r1.editable_lines_json)
    lines2 = json.loads(r2.editable_lines_json)
    # Same annotation values after second enrichment.
    by1 = {ln["product_code"]: ln for ln in lines1}
    by2 = {ln["product_code"]: ln for ln in lines2}
    for pc in by1:
        assert by1[pc]["name_pl"]   == by2[pc]["name_pl"]
        assert by1[pc]["item_type"] == by2[pc]["item_type"]


# ── 10. Draft state unchanged after enrichment ────────────────────────────────

def test_enrich_state_unchanged(db_path):
    d = _seed_draft(db_path)
    assert d.draft_state == "draft"

    refreshed = pildb.enrich_draft_lines(
        db_path, d.id, "alice", d.updated_at, _lookup_both
    )
    # Must stay 'draft', NOT transition to 'editing'.
    assert refreshed.draft_state == "draft", (
        f"enrichment must not change draft_state; got {refreshed.draft_state!r}"
    )
    stored = pildb.get_draft_by_id(db_path, d.id)
    assert stored.draft_state == "draft"


# ── 11. Route requires expected_updated_at ────────────────────────────────────

def test_route_requires_expected_updated_at(client, tmp_path):
    # Seed a draft so we have a real draft_id.
    db = tmp_path / "proforma" / "proforma_links.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    pildb.init_db(db)
    d = _seed_draft(db)

    # Missing expected_updated_at → 400.
    resp = client.post(
        f"/api/v1/proforma/draft/{d.id}/enrich-from-product-descriptions",
        json={},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert "expected_updated_at" in resp.text

    # Empty string expected_updated_at → 400.
    resp2 = client.post(
        f"/api/v1/proforma/draft/{d.id}/enrich-from-product-descriptions",
        json={"expected_updated_at": ""},
        headers=_auth_headers(),
    )
    assert resp2.status_code == 400


# ── 12. Dashboard HTML — button and columns present ──────────────────────────

def test_dashboard_has_enrich_button_and_columns():
    html_path = (
        Path(__file__).resolve().parents[1]
        / "app" / "static" / "dashboard.html"
    )
    assert html_path.exists(), f"dashboard.html not found at {html_path}"
    html = html_path.read_text(encoding="utf-8", errors="replace")

    assert 'data-testid="btn-enrich-product-names"' in html, \
        "Enrich product names button missing from dashboard.html"
    assert "Enrich product names" in html, \
        "'Enrich product names' label missing"
    assert "enrich-from-product-descriptions" in html, \
        "Route path 'enrich-from-product-descriptions' missing from dashboard.html"
    assert 'data-testid="draft-line-name-pl-' in html or \
           "draft-line-name-pl-" in html, \
        "data-testid for name_pl column missing"
    assert "item_type" in html, \
        "'item_type' column reference missing from dashboard.html"
    assert "name_pl" in html, \
        "'name_pl' column reference missing from dashboard.html"


# ── PR 2C.1 regression tests ─────────────────────────────────────────────────
#
# These tests assert the AND→OR guard fix in auto_create_draft_from_sales_packing
# and reset_draft_from_sales_packing.  A row with product_code='' but a non-empty
# design_no must NOT appear in editable_lines_json.

def test_auto_create_draft_skips_blank_product_code_with_design_no(db_path):
    """Regression: blank product_code + non-empty design_no must be skipped.

    Before the fix the guard was ``if not product_code and not design_no: continue``
    which let these rows slip through.  After the fix it is ``if not product_code:
    continue``.
    """
    lines = [
        {
            "product_code": "",           # blank — must be skipped
            "design_no":    "J3609R01707",  # non-empty design_no (the old guard let this pass)
            "qty":           1,
            "unit_price":    50.0,
            "currency":      "EUR",
            "price_source":  "packing_promote",
        },
        {
            "product_code": "EJL-RNG-417G",  # valid — must be kept
            "design_no":    "D100",
            "qty":           2,
            "unit_price":    25.50,
            "currency":      "EUR",
            "price_source":  "packing_promote",
        },
    ]
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path,
        batch_id    = "B_REGRESSION_AUTO",
        client_name = "SUOKKO",
        currency    = "EUR",
        lines       = lines,
        operator    = "intake",
    )
    editable = json.loads(draft.editable_lines_json)
    codes = [ln["product_code"] for ln in editable]
    assert "" not in codes, (
        "blank product_code row appeared in editable_lines_json — AND guard not fixed"
    )
    assert "EJL-RNG-417G" in codes
    assert len(editable) == 1


def test_reset_draft_skips_blank_product_code_with_design_no(db_path):
    """Regression: reset_draft_from_sales_packing must apply the same guard."""
    # Seed a valid draft first.
    draft = _seed_draft(db_path)

    lines_with_blank = [
        {
            "product_code": "",            # blank — must be skipped
            "design_no":    "J3609R01707",
            "qty":           1,
            "unit_price":    50.0,
            "currency":      "EUR",
            "price_source":  "packing_promote",
        },
        {
            "product_code": "EJL-RNG-417G",  # valid
            "design_no":    "D100",
            "qty":           3,
            "unit_price":    30.0,
            "currency":      "EUR",
            "price_source":  "packing_promote",
        },
    ]
    reset = pildb.reset_draft_from_sales_packing(
        db_path,
        draft_id           = draft.id,
        operator           = "intake",
        sales_lines        = lines_with_blank,
        expected_updated_at = draft.updated_at,
    )
    editable = json.loads(reset.editable_lines_json)
    codes = [ln["product_code"] for ln in editable]
    assert "" not in codes, (
        "blank product_code row appeared after reset — AND guard not fixed in reset path"
    )
    assert "EJL-RNG-417G" in codes
    assert len(editable) == 1


def test_existing_blank_draft_line_enrichment_still_safe(db_path):
    """Grandfathered blank-product_code line in editable_lines_json must not crash enrichment.

    Historical drafts created before the fix may contain rows with product_code=''.
    enrich_lines_from_product_descriptions must handle them gracefully: no exception,
    and all annotation fields set to None for that row.
    """
    # Seed a normal draft then manually inject a blank-code line into editable_lines_json.
    draft = _seed_draft(db_path)
    existing = json.loads(draft.editable_lines_json)
    blank_line = {
        "product_code": "",
        "design_no":    "J3609R01707",
        "qty":           1.0,
        "unit_price":    50.0,
        "currency":      "EUR",
        "price_source":  "packing_promote",
        "line_id":       999,
    }
    existing.append(blank_line)
    with __import__("sqlite3").connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET editable_lines_json=? WHERE id=?",
            (json.dumps(existing), draft.id),
        )
        conn.commit()

    # Re-load so updated_at is fresh.
    fresh = pildb.get_draft_by_id(db_path, draft.id)

    # Must not raise.
    enriched_lines, n_hit, n_miss = pildb.enrich_lines_from_product_descriptions(
        json.loads(fresh.editable_lines_json),
        _lookup_none,  # returns None for every code
    )

    # All annotation fields for the blank-code row must be None, no crash.
    blank_enriched = next(
        (ln for ln in enriched_lines if ln.get("product_code") == ""), None
    )
    assert blank_enriched is not None, "blank-code line disappeared unexpectedly"
    assert blank_enriched["item_type"]    is None
    assert blank_enriched["name_pl"]      is None
    assert blank_enriched["description_pl"] is None


# ── 13. Enrichment 100% when unmatched rows already filtered out ──────────────

def test_enrich_100pct_after_unmatched_filter(db_path):
    """
    A draft built exclusively from matched lines (no blank product_code) must
    reach 100% enrichment — n_miss == 0.
    """
    # Seed a draft whose lines ALL have a known product_code (no unmatched rows).
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path,
        batch_id    = "B_FILTERED",
        client_name = "SUOKKO",
        currency    = "EUR",
        lines       = [
            {
                "product_code": "EJL-RNG-417G",
                "design_no":    "D100",
                "qty":           2,
                "unit_price":    25.50,
                "currency":      "EUR",
                "price_source":  "packing_promote",
                "client_ref":    "",
            },
            {
                "product_code": "EJL-PND-ROSE",
                "design_no":    "D200",
                "qty":           1,
                "unit_price":    100.0,
                "currency":      "EUR",
                "price_source":  "packing_promote",
                "client_ref":    "",
            },
        ],
        operator = "intake",
    )
    refreshed = pildb.enrich_draft_lines(
        db_path, draft.id, "alice", draft.updated_at, _lookup_both
    )
    events = pildb.list_draft_events(db_path, draft.id)
    enriched_events = [
        e for e in events
        if e.get("event") == "lines_enriched_from_product_descriptions"
    ]
    detail = json.loads(enriched_events[-1]["detail_json"])
    assert detail["missing_count"] == 0, (
        f"expected 0 missing after unmatched rows filtered; got {detail['missing_count']}"
    )
    assert detail["enriched_count"] == 2


# ── 13-15. `_warnings` is DERIVED — recomputed, never accumulated ─────────────
# Regression: `_warnings` rides along on the line dict via `{**ln, ...}`, so a
# "Product description missing" warning emitted on an earlier pass (before the
# product_descriptions row existed) survived every later pass and gained one
# duplicate per enrichment — a false, un-actionable operator blocker on the
# outbound proforma. Production draft 90 carried it twice while both PD rows
# were present and usable.

_STALE_PD_WARNING = (
    "Product description missing for product_code='EJL-RNG-417G'. "
    "The canonical product_descriptions row is absent or contains "
    "generic/forbidden text. Promote the PZ bilingual description "
    "(pz_rows.json) into product_descriptions first — no description "
    "may be fabricated."
)

# Emitted by routes_proforma (a DIFFERENT producer) — must never be eaten here.
_FOREIGN_WARNING = (
    "Polish customs description missing for product_code='EJL-RNG-417G'. "
    "Generate customs description package first. "
    "Proforma must not fabricate Polish description."
)


def test_enrich_clears_stale_description_warning():
    """PD resolves now → this module's own earlier warning is dropped entirely."""
    lines = [{
        "line_id": 1, "product_code": "EJL-RNG-417G",
        "qty": 2, "unit_price": 25.50, "currency": "EUR",
        "_warnings": [_STALE_PD_WARNING],
    }]
    enriched, n_hit, n_miss = pildb.enrich_lines_from_product_descriptions(
        lines, _lookup_both
    )
    assert (n_hit, n_miss) == (1, 0)
    assert enriched[0]["description_pl"] == "Pierścionek złoty 585"
    # No empty-list residue either — the key is gone, same shape as never-warned.
    assert "_warnings" not in enriched[0]
    # Input line untouched (documented pure function).
    assert lines[0]["_warnings"] == [_STALE_PD_WARNING]


def test_enrich_description_warning_not_duplicated():
    """A genuine miss warns exactly once, no matter how many passes run."""
    lines = [{"line_id": 1, "product_code": "EJL-RNG-417G",
              "qty": 2, "unit_price": 25.50, "currency": "EUR"}]

    for _ in range(3):
        lines, _hit, n_miss = pildb.enrich_lines_from_product_descriptions(
            lines, _lookup_none
        )
        assert n_miss == 1
        warnings = lines[0]["_warnings"]
        assert len(warnings) == 1, warnings
        assert warnings[0].startswith(pildb.PD_MISSING_WARNING_PREFIX)


def test_enrich_preserves_foreign_warning():
    """Only OUR prefix is recomputed; another producer's warning survives."""
    lines = [{
        "line_id": 1, "product_code": "EJL-RNG-417G",
        "qty": 2, "unit_price": 25.50, "currency": "EUR",
        "_warnings": [_FOREIGN_WARNING, _STALE_PD_WARNING],
    }]
    enriched, _hit, _miss = pildb.enrich_lines_from_product_descriptions(
        lines, _lookup_both
    )
    assert enriched[0]["_warnings"] == [_FOREIGN_WARNING]


# ── 16. the shared `_warnings` recompute helper ──────────────────────────────
def test_recompute_line_warning_is_per_producer():
    """Each producer replaces only its OWN entries and never accumulates.

    Both `_warnings` producers (this module's PD-missing warning and
    routes_proforma's customs warning) route through this helper, so the
    per-producer isolation is pinned once here rather than twice downstream.
    """
    a, b = pildb.PD_MISSING_WARNING_PREFIX, pildb.CUSTOMS_PL_MISSING_WARNING_PREFIX

    line = {"_warnings": [a + "'X'. old", b + "'X'. old"]}

    # producer A re-emits: its own entry is replaced, B's survives untouched
    pildb.recompute_line_warning(line, a, a + "'X'. new")
    assert line["_warnings"] == [b + "'X'. old", a + "'X'. new"]

    # idempotent — a second identical pass does not duplicate
    pildb.recompute_line_warning(line, a, a + "'X'. new")
    assert line["_warnings"] == [b + "'X'. old", a + "'X'. new"]

    # producer A resolves: only its entry is dropped
    pildb.recompute_line_warning(line, a)
    assert line["_warnings"] == [b + "'X'. old"]

    # last producer resolves: the key disappears entirely
    pildb.recompute_line_warning(line, b)
    assert "_warnings" not in line

    # a line that never warned stays clean
    empty = {}
    pildb.recompute_line_warning(empty, a)
    assert empty == {}


# ── 17-19. producer 2 — the customs warning, driven over HTTP ────────────────
# Tests 13-16 pin the shared helper and THIS module's producer. The SECOND
# producer lives in `routes_proforma.import_draft_sales_prices` and was covered
# at helper level only. These three drive the real endpoint and assert what is
# actually PERSISTED into `editable_lines_json` — the surface a stale or
# duplicated warning is read back from on the outbound proforma.

_HTTP_PC    = "EJL-RNG-417G"
_HTTP_BATCH = "BATCH_WARN_HTTP"

# One row, Sr=1, grand total equal to the row total (the import validates it).
_HTTP_TSV = "\n".join([
    "Sr\tCtg\tDesign\tDesign Description\tKt\tCol\tQuality\tQty\t"
    "Value (EUR)\tTotal Value (EUR)",
    f"1\tPND\t{_HTTP_PC}\tTest\t14KT\tW\tGH-SI1\t3\t211\t633",
    "Grand Total\t\t\t\t\t\t\t\t\t633",
])


@pytest.fixture()
def http_draft(tmp_path):
    """Real endpoint over real storage — yields (client, storage, draft_id)."""
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.main import app

    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")

    out = tmp_path / "outputs" / _HTTP_BATCH
    (out / "source").mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(
        json.dumps({"batch_id": _HTTP_BATCH, "tracking_no": _HTTP_BATCH,
                    "awb": _HTTP_BATCH, "carrier": "DHL", "timeline": []}),
        encoding="utf-8",
    )

    # 1-based integer line_id matches TSV Sr=1 on the precise 1:1 path.
    seed = [{"line_id": 1, "product_code": _HTTP_PC, "quantity": 1.0,
             "unit_price": 50.0, "total_eur": 50.0, "currency": "EUR"}]
    with sqlite3.connect(str(tmp_path / "proforma_links.db")) as conn:
        draft_id = conn.execute(
            """
            INSERT INTO proforma_drafts
              (batch_id, client_name, status, currency, draft_state,
               wfirma_proforma_id, wfirma_proforma_fullnumber,
               source_lines_json, editable_lines_json, service_charges_json,
               clone_generation, draft_version, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
            """,
            (_HTTP_BATCH, "ACME", "draft", "EUR", "draft", None, "", "[]",
             json.dumps(seed), "[]", 0, 1),
        ).lastrowid
        conn.commit()

    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, tmp_path, draft_id


def _persisted_line(storage: Path, draft_id: int) -> Dict[str, Any]:
    draft = pildb.get_draft_by_id(storage / "proforma_links.db", draft_id)
    return json.loads(draft.editable_lines_json or "[]")[0]


def _http_import(c, storage: Path, draft_id: int) -> Dict[str, Any]:
    """POST the sales-price import; return the line as PERSISTED."""
    draft = pildb.get_draft_by_id(storage / "proforma_links.db", draft_id)
    r = c.post(
        f"/api/v1/proforma/draft/{draft_id}/import-sales-prices",
        json={"expected_updated_at": draft.updated_at or "",
              "tsv_text": _HTTP_TSV},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["lines_matched"] == 1, r.text
    return _persisted_line(storage, draft_id)


def test_http_import_raises_customs_warning_when_pd_missing(http_draft):
    """No product_descriptions row → exactly one customs warning persisted."""
    c, storage, draft_id = http_draft
    line = _http_import(c, storage, draft_id)

    assert line["name_pl"] == "", "no PD row must never yield a fabricated name_pl"
    warnings = line["_warnings"]
    assert len(warnings) == 1, warnings
    assert warnings[0].startswith(pildb.CUSTOMS_PL_MISSING_WARNING_PREFIX)


def test_http_import_customs_warning_not_duplicated(http_draft):
    """Root cause: append-only added one copy per import pass. Now exactly one."""
    c, storage, draft_id = http_draft
    for _ in range(3):
        warnings = _http_import(c, storage, draft_id)["_warnings"]
        assert len(warnings) == 1, warnings
        assert warnings[0].startswith(pildb.CUSTOMS_PL_MISSING_WARNING_PREFIX)


def test_http_import_clears_customs_warning_and_keeps_foreign(http_draft):
    """PD exists now → own warning dropped; the other producer's survives."""
    from app.services import document_db as ddb
    c, storage, draft_id = http_draft

    assert len(_http_import(c, storage, draft_id)["_warnings"]) == 1

    # Persist a foreign entry from the OTHER producer alongside ours.
    line = _persisted_line(storage, draft_id)
    line["_warnings"] = [_STALE_PD_WARNING] + line["_warnings"]
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        conn.execute("UPDATE proforma_drafts SET editable_lines_json=? WHERE id=?",
                     (json.dumps([line]), draft_id))
        conn.commit()

    # The canonical description authority now answers for this product_code.
    ddb.upsert_product_description(
        product_code      = _HTTP_PC,
        item_type         = "RING",
        name_pl           = "Pierscionek zloty",
        description_pl    = "Pierscionek zloty 585",
        material_pl       = "zloto 585",
        purpose_pl        = "bizuteria",
        description_block = "Pierscionek zloty 585",
        source            = "manual",
    )

    line = _http_import(c, storage, draft_id)
    assert line["name_pl"] == "Pierscionek zloty 585", line
    # Ours is gone; the foreign producer's entry is untouched.
    assert line["_warnings"] == [_STALE_PD_WARNING], line["_warnings"]
