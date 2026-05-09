"""
test_proforma_drafts_lifecycle_phase25.py — Phase 2.5:
formalise editable Proforma Draft status/state compatibility.

Scope: validate the writer-side guards and the legacy ↔ lifecycle
mapping. No SQL CHECK constraint is added at this phase, so these
tests pin the writer-side contract instead.

Coverage:
  1. status='draft' is recognised AND maps to draft_state='draft'.
  2. _normalise_draft_status accepts the four known legacy values
     and raises ValueError on any unknown value.
  3. _normalise_draft_state accepts every lifecycle state and
     raises on unknown values.
  4. KNOWN_LEGACY_STATUSES extends DRAFT_STATUSES with 'draft' and
     leaves the original tuple unchanged (Phase 1 contract).
  5. _LEGACY_STATUS_TO_DRAFT_STATE has identity mapping for 'draft'.
  6. auto_create_draft_from_sales_packing writes a normalised
     status/state pair (defence-in-depth: corruption of
     _PHASE2_LEGACY_STATUS at module level would fail loudly).
  7. Existing 'issued' rows still read as 'posted'.
  8. Existing Phase 2 auto-created rows still read as 'draft'.
"""
from __future__ import annotations

import sqlite3

import pytest

from app.services import proforma_invoice_link_db as pildb


# ── 1. status='draft' compatibility ─────────────────────────────────────────

def test_draft_legacy_status_maps_to_draft_state():
    assert pildb._legacy_status_to_draft_state("draft") == "draft"
    # Whitespace tolerated.
    assert pildb._legacy_status_to_draft_state("  draft  ") == "draft"


def test_draft_in_known_legacy_statuses():
    assert "draft" in pildb.KNOWN_LEGACY_STATUSES


# ── 2. _normalise_draft_status ──────────────────────────────────────────────

@pytest.mark.parametrize("legacy", ["pending_local", "issued", "failed", "draft"])
def test_normalise_status_accepts_known(legacy):
    assert pildb._normalise_draft_status(legacy) == legacy


def test_normalise_status_strips_whitespace():
    assert pildb._normalise_draft_status("  draft  ") == "draft"


@pytest.mark.parametrize("bad", [
    "",
    None,
    "DRAFT",
    "Draft",
    "issued ",   # trailing space is stripped, but "issued" is valid
    "unknown",
    "posted",       # this is a draft_state, not a legacy status
    "post_failed",
])
def test_normalise_status_rejects_unknown(bad):
    if bad == "issued ":
        # Whitespace stripping means this is actually valid.
        assert pildb._normalise_draft_status(bad) == "issued"
        return
    with pytest.raises(ValueError) as exc:
        pildb._normalise_draft_status(bad)
    assert "unknown legacy draft status" in str(exc.value)


# ── 3. _normalise_draft_state ───────────────────────────────────────────────

@pytest.mark.parametrize("state", list(pildb.DRAFT_LIFECYCLE_STATES))
def test_normalise_state_accepts_every_lifecycle_state(state):
    assert pildb._normalise_draft_state(state) == state


@pytest.mark.parametrize("bad", [
    "",
    None,
    "Draft",
    "POSTED",
    "issued",          # legacy status, not a lifecycle state
    "pending_local",
    "unknown",
    "in_progress",
])
def test_normalise_state_rejects_unknown(bad):
    with pytest.raises(ValueError) as exc:
        pildb._normalise_draft_state(bad)
    assert "unknown draft_state" in str(exc.value)


def test_lifecycle_states_enumerated_in_full():
    """Pin the full lifecycle set so any future addition is intentional."""
    assert pildb.DRAFT_LIFECYCLE_STATES == (
        "draft", "editing", "approved",
        "posting", "posted", "post_failed",
        "cancelled", "superseded",
    )


# ── 4. KNOWN_LEGACY_STATUSES vs DRAFT_STATUSES ──────────────────────────────

def test_legacy_statuses_extension_is_additive():
    """Phase 1 freeze on DRAFT_STATUSES must hold; KNOWN_LEGACY_STATUSES
    extends it without mutating the original tuple."""
    assert pildb.DRAFT_STATUSES == ("pending_local", "issued", "failed")
    assert pildb.KNOWN_LEGACY_STATUSES == (
        "pending_local", "issued", "failed", "draft",
    )
    # The extension contains every original value.
    for s in pildb.DRAFT_STATUSES:
        assert s in pildb.KNOWN_LEGACY_STATUSES


# ── 5. Legacy → state mapping completeness ──────────────────────────────────

def test_every_known_legacy_status_has_a_mapping():
    """Every value in KNOWN_LEGACY_STATUSES must produce a non-empty
    draft_state — otherwise a writer storing that legacy value would
    leave the row's projected state ambiguous."""
    for legacy in pildb.KNOWN_LEGACY_STATUSES:
        mapped = pildb._legacy_status_to_draft_state(legacy)
        assert mapped, f"no mapping for legacy status {legacy!r}"
        assert mapped in pildb.DRAFT_LIFECYCLE_STATES


def test_legacy_mapping_contents():
    """Pin the exact mapping so a future change is intentional."""
    assert pildb._LEGACY_STATUS_TO_DRAFT_STATE == {
        "issued":        "posted",
        "failed":        "post_failed",
        "pending_local": "posting",
        "draft":         "draft",
    }


# ── 6. auto_create_draft_from_sales_packing writes a valid pair ─────────────

def test_auto_create_writes_valid_status_state_pair(tmp_path):
    db = tmp_path / "p.db"
    pildb.init_db(db)
    draft, was_created = pildb.auto_create_draft_from_sales_packing(
        db,
        batch_id    = "B1",
        client_name = "ACME",
        currency    = "EUR",
        lines       = [{"product_code": "X", "design_no": "X",
                        "qty": 1, "unit_price": 5.0, "currency": "EUR"}],
    )
    assert was_created is True
    # Both columns must be present and individually valid.
    assert pildb._normalise_draft_status(draft.status) == "draft"
    assert pildb._normalise_draft_state(draft.draft_state) == "draft"


def test_auto_create_fails_loudly_if_phase2_status_corrupted(tmp_path, monkeypatch):
    """Defence-in-depth: if a future refactor accidentally sets
    _PHASE2_LEGACY_STATUS to an unknown value, the writer must raise
    a ValueError before touching the DB rather than silently inserting
    a row that the read shim cannot project."""
    db = tmp_path / "p.db"
    pildb.init_db(db)

    monkeypatch.setattr(pildb, "_PHASE2_LEGACY_STATUS", "garbage")
    with pytest.raises(ValueError) as exc:
        pildb.auto_create_draft_from_sales_packing(
            db, batch_id="B1", client_name="ACME",
            currency="EUR",
            lines=[{"product_code": "X", "design_no": "X", "qty": 1,
                    "unit_price": 5.0, "currency": "EUR"}],
        )
    assert "unknown legacy draft status" in str(exc.value)
    # Nothing was committed.
    assert pildb.list_drafts_for_batch(db, "B1") == []


# ── 7, 8. Read-side regressions ─────────────────────────────────────────────

def test_legacy_issued_row_still_reads_as_posted(tmp_path):
    db = tmp_path / "p.db"
    pildb.init_db(db)
    now = "2026-04-01T12:00:00Z"
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            """INSERT INTO proforma_drafts
               (batch_id, client_name, status, currency, source_lines_json,
                wfirma_proforma_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("LEGACY", "OLD", "issued", "EUR", "[]",
             "WF-1", now, now),
        )
        conn.commit()
    # init_db backfills draft_state for issued → posted.
    pildb.init_db(db)
    drafts = pildb.list_drafts_for_batch(db, "LEGACY")
    assert len(drafts) == 1
    assert drafts[0].status      == "issued"
    assert drafts[0].draft_state == "posted"


def test_phase2_auto_created_row_still_reads_as_draft(tmp_path):
    db = tmp_path / "p.db"
    pildb.init_db(db)
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B", client_name="ACME",
        currency="EUR",
        lines=[{"product_code": "X", "design_no": "X", "qty": 1,
                "unit_price": 1.0, "currency": "EUR"}],
    )
    # Re-running init_db must NOT clobber the explicit draft_state.
    pildb.init_db(db)
    refreshed = pildb.get_draft_by_id(db, draft.id)
    assert refreshed is not None
    assert refreshed.status      == "draft"
    assert refreshed.draft_state == "draft"


# ── 9. Public surface — __all__ exports ─────────────────────────────────────

def test_normalisers_exported():
    assert "_normalise_draft_status" in pildb.__all__
    assert "_normalise_draft_state"  in pildb.__all__
    assert "KNOWN_LEGACY_STATUSES"   in pildb.__all__
