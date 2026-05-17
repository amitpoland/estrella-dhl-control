"""test_cache_freshness_no_rows_not_stale.py — fix misleading
stale-audit banner on Atlas-style intake-draft batches that have not
yet been engine-processed.

Atlas intake writes an audit.json with metadata + timeline + inputs
but no `rows` array and no `row_schema_version` stamp.  Engine output
is what adds those fields. Before this fix, cache_freshness flagged
those audits as `schema (missing) → v2` and the dashboard surfaced a
banner reading "Cached audit is stale" on every fresh draft — false
positive.

The fix returns (False, '') when both `rows` and `row_schema_version`
are absent. Real cached rows with stale schema (v1, etc.) still
correctly report stale.
"""
from __future__ import annotations

from app.services.cache_freshness import is_audit_stale, stale_field_summary


# ── Intake-draft (not stale) ────────────────────────────────────────────

def test_audit_with_no_rows_and_no_schema_is_not_stale():
    """Atlas-style intake-draft audits have neither field; not stale."""
    audit = {"batch_id": "X", "timeline": []}
    stale, reason = is_audit_stale(audit)
    assert stale is False, f"expected not-stale; reason={reason!r}"
    assert reason == ""


def test_audit_with_empty_rows_array_and_no_schema_is_not_stale():
    """Empty rows list + no schema stamp = not yet generated."""
    audit = {"batch_id": "X", "rows": []}
    stale, reason = is_audit_stale(audit)
    assert stale is False
    assert reason == ""


def test_stale_field_summary_for_intake_draft_is_clean():
    """The structured summary surfaced via /dashboard/batches must
    reflect not-stale for intake drafts so the frontend banner stays
    hidden."""
    audit = {"batch_id": "X"}
    s = stale_field_summary(audit)
    assert s["stale"] is False
    assert s["regenerate_required"] is False
    assert s["row_count"] == 0


# ── Legacy stale still detected (regression guard) ─────────────────────

def test_v1_audit_with_rows_still_marked_stale():
    """Audit with rows but no v2 stamp must still be stale — fix must
    not relax the v2 check for real cached rows."""
    audit = {
        "batch_id": "X",
        "rows": [{"product_code": "A"}],
        "row_schema_version": "v1",
    }
    stale, reason = is_audit_stale(audit)
    assert stale is True
    assert "v1" in reason or "v2" in reason


def test_v2_audit_with_all_required_fields_is_fresh():
    """A properly engine-stamped v2 audit is fresh."""
    audit = {
        "batch_id": "X",
        "row_schema_version": "v2",
        "rows": [{
            "product_code": "A-1", "nazwa_pl": "Pl",
            "nazwa_en": "En", "nazwa": "Pl / En",
        }],
    }
    stale, reason = is_audit_stale(audit)
    assert stale is False
    assert reason == ""


def test_v2_audit_missing_required_row_field_is_stale():
    """Defensive guard — v2 audit with rows missing required fields
    must still report stale (existing behaviour preserved)."""
    audit = {
        "batch_id": "X",
        "row_schema_version": "v2",
        "rows": [{"product_code": "A"}],  # missing nazwa_pl/en/canonical
    }
    stale, reason = is_audit_stale(audit)
    assert stale is True
    assert "missing fields" in reason
