"""
test_proforma_search.py — M6 Prior Proforma Search: DB layer tests.

PR 1 of 3: Verifies search_drafts() function, index creation,
filtering, pagination, and edge cases.

Authority: proforma_drafts table in proforma_links.db is the SOLE
authority for cross-batch proforma search. No other data source.

Sprint: M6 Prior Proforma Search (PR 1 — DB Layer)
Target: proforma_invoice_link_db.py (search_drafts + indexes)
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.proforma_invoice_link_db import (
    ProformaDraft,
    _ensure_drafts_table,
    list_drafts_for_batch,
    search_drafts,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db_path(tmp_path):
    """Create a fresh proforma_links.db with tables initialised."""
    p = tmp_path / "proforma_links.db"
    with sqlite3.connect(str(p)) as conn:
        _ensure_drafts_table(conn)
    return p


def _insert_draft(
    db_path: Path,
    *,
    batch_id: str = "BATCH-001",
    client_name: str = "Estrella Jewels",
    draft_state: str = "draft",
    currency: str = "EUR",
    wfirma_proforma_id: str = "",
    wfirma_proforma_fullnumber: str = "",
    created_at: str = "2026-06-01T10:00:00Z",
    clone_generation: int = 0,
) -> int:
    """Insert a test draft row and return its id.

    Sets legacy ``status`` column to match ``draft_state`` so the
    read-side legacy shim in _row_to_draft does not override.
    Mapping: posted->issued, post_failed->failed, posting->pending_local,
    everything else->'draft'.
    """
    # Legacy status must match draft_state to avoid read-shim override
    _STATE_TO_LEGACY = {
        "posted": "issued",
        "post_failed": "failed",
        "posting": "pending_local",
    }
    legacy_status = _STATE_TO_LEGACY.get(draft_state, "draft")

    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            """
            INSERT INTO proforma_drafts (
                batch_id, client_name, status, currency, exchange_rate,
                source_lines_json, wfirma_proforma_id, notes,
                created_at, updated_at, draft_state,
                wfirma_proforma_fullnumber, clone_generation
            ) VALUES (?, ?, ?, ?, 1.0, '[]', ?, '',
                      ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                client_name,
                legacy_status,
                currency,
                wfirma_proforma_id,
                created_at,
                now,
                draft_state,
                wfirma_proforma_fullnumber,
                clone_generation,
            ),
        )
        return cur.lastrowid


# =============================================================================
# 1. Index creation
# =============================================================================


class TestIndexCreation:
    """M6 search indexes must be created by _ensure_drafts_table."""

    def test_idx_pd_client_name_exists(self, db_path):
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_pd_client_name'"
            ).fetchone()
        assert row is not None, "idx_pd_client_name must exist"

    def test_idx_pd_fullnumber_exists(self, db_path):
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_pd_fullnumber'"
            ).fetchone()
        assert row is not None, "idx_pd_fullnumber must exist"

    def test_idx_pd_created_at_exists(self, db_path):
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_pd_created_at'"
            ).fetchone()
        assert row is not None, "idx_pd_created_at must exist"

    def test_idx_pd_currency_exists(self, db_path):
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_pd_currency'"
            ).fetchone()
        assert row is not None, "idx_pd_currency must exist"

    def test_idx_pd_draft_state_exists(self, db_path):
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_pd_draft_state'"
            ).fetchone()
        assert row is not None, "idx_pd_draft_state must exist"

    def test_idx_pd_batch_id_exists(self, db_path):
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_pd_batch_id'"
            ).fetchone()
        assert row is not None, "idx_pd_batch_id must exist"

    def test_idx_pd_wfirma_proforma_id_exists(self, db_path):
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_pd_wfirma_proforma_id'"
            ).fetchone()
        assert row is not None, "idx_pd_wfirma_proforma_id must exist"

    def test_indexes_are_idempotent(self, db_path):
        """Running _ensure_drafts_table twice must not fail."""
        with sqlite3.connect(str(db_path)) as conn:
            _ensure_drafts_table(conn)
            _ensure_drafts_table(conn)
        # No exception = pass


# =============================================================================
# 2. Basic search — no filters
# =============================================================================


class TestSearchNoFilters:
    """search_drafts with no filters returns all drafts paginated."""

    def test_returns_all_drafts(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="Client A")
        _insert_draft(db_path, batch_id="B2", client_name="Client B")
        result = search_drafts(db_path)
        assert result["total"] == 2
        assert len(result["results"]) == 2

    def test_empty_db_returns_empty(self, db_path):
        result = search_drafts(db_path)
        assert result["total"] == 0
        assert result["results"] == []
        assert result["page"] == 1
        assert result["page_size"] == 25

    def test_nonexistent_db_returns_empty(self, tmp_path):
        fake_path = tmp_path / "does_not_exist.db"
        result = search_drafts(fake_path)
        assert result["total"] == 0
        assert result["results"] == []

    def test_returns_proforma_draft_objects(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="Client A")
        result = search_drafts(db_path)
        assert len(result["results"]) == 1
        assert isinstance(result["results"][0], ProformaDraft)

    def test_results_ordered_newest_first(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="Old",
                      created_at="2026-01-01T00:00:00Z")
        _insert_draft(db_path, batch_id="B2", client_name="New",
                      created_at="2026-06-01T00:00:00Z")
        result = search_drafts(db_path)
        assert result["results"][0].client_name == "New"
        assert result["results"][1].client_name == "Old"


# =============================================================================
# 3. Filter by batch_id (exact match)
# =============================================================================


class TestFilterBatchId:
    """Filter by batch_id — exact match."""

    def test_exact_match(self, db_path):
        _insert_draft(db_path, batch_id="BATCH-A", client_name="C1")
        _insert_draft(db_path, batch_id="BATCH-B", client_name="C2")
        result = search_drafts(db_path, filters={"batch_id": "BATCH-A"})
        assert result["total"] == 1
        assert result["results"][0].batch_id == "BATCH-A"

    def test_no_match_returns_empty(self, db_path):
        _insert_draft(db_path, batch_id="BATCH-A", client_name="C1")
        result = search_drafts(db_path, filters={"batch_id": "NONEXIST"})
        assert result["total"] == 0


# =============================================================================
# 4. Filter by client_name (partial / LIKE match)
# =============================================================================


class TestFilterClientName:
    """Filter by client_name — partial match (LIKE %value%)."""

    def test_partial_match(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="Estrella Jewels Ltd")
        _insert_draft(db_path, batch_id="B2", client_name="Other Company")
        result = search_drafts(db_path, filters={"client_name": "Estrella"})
        assert result["total"] == 1
        assert "Estrella" in result["results"][0].client_name

    def test_case_insensitive_sqlite_default(self, db_path):
        """SQLite LIKE is case-insensitive for ASCII by default."""
        _insert_draft(db_path, batch_id="B1", client_name="ESTRELLA JEWELS")
        result = search_drafts(db_path, filters={"client_name": "estrella"})
        assert result["total"] == 1

    def test_matches_anywhere_in_name(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="ABC Jewels XYZ")
        result = search_drafts(db_path, filters={"client_name": "Jewels"})
        assert result["total"] == 1


# =============================================================================
# 5. Filter by wfirma_proforma_id (exact match)
# =============================================================================


class TestFilterWfirmaProformaId:
    """Filter by wfirma_proforma_id — exact match."""

    def test_exact_match(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1",
                      wfirma_proforma_id="12345")
        _insert_draft(db_path, batch_id="B2", client_name="C2",
                      wfirma_proforma_id="67890")
        result = search_drafts(db_path, filters={"wfirma_proforma_id": "12345"})
        assert result["total"] == 1
        assert result["results"][0].wfirma_proforma_id == "12345"


# =============================================================================
# 6. Filter by wfirma_proforma_fullnumber (prefix match)
# =============================================================================


class TestFilterFullnumber:
    """Filter by wfirma_proforma_fullnumber — prefix match (LIKE value%)."""

    def test_prefix_match(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1",
                      wfirma_proforma_fullnumber="PROF 90/2026")
        _insert_draft(db_path, batch_id="B2", client_name="C2",
                      wfirma_proforma_fullnumber="PROF 91/2026")
        result = search_drafts(
            db_path, filters={"wfirma_proforma_fullnumber": "PROF 90"}
        )
        assert result["total"] == 1
        assert result["results"][0].wfirma_proforma_fullnumber == "PROF 90/2026"

    def test_exact_full_number(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1",
                      wfirma_proforma_fullnumber="PROF 90/2026")
        result = search_drafts(
            db_path, filters={"wfirma_proforma_fullnumber": "PROF 90/2026"}
        )
        assert result["total"] == 1


# =============================================================================
# 7. Filter by draft_state (exact match)
# =============================================================================


class TestFilterDraftState:
    """Filter by draft_state — exact match."""

    def test_filter_posted(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1",
                      draft_state="posted")
        _insert_draft(db_path, batch_id="B2", client_name="C2",
                      draft_state="draft")
        result = search_drafts(db_path, filters={"draft_state": "posted"})
        assert result["total"] == 1
        assert result["results"][0].draft_state == "posted"

    def test_filter_draft(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1",
                      draft_state="posted")
        _insert_draft(db_path, batch_id="B2", client_name="C2",
                      draft_state="draft")
        result = search_drafts(db_path, filters={"draft_state": "draft"})
        assert result["total"] == 1
        assert result["results"][0].draft_state == "draft"

    def test_filter_cancelled(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1",
                      draft_state="cancelled")
        result = search_drafts(db_path, filters={"draft_state": "cancelled"})
        assert result["total"] == 1


# =============================================================================
# 8. Filter by currency (exact match)
# =============================================================================


class TestFilterCurrency:
    """Filter by currency — exact match."""

    def test_filter_eur(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1", currency="EUR")
        _insert_draft(db_path, batch_id="B2", client_name="C2", currency="USD")
        result = search_drafts(db_path, filters={"currency": "EUR"})
        assert result["total"] == 1
        assert result["results"][0].currency == "EUR"

    def test_filter_usd(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1", currency="EUR")
        _insert_draft(db_path, batch_id="B2", client_name="C2", currency="USD")
        result = search_drafts(db_path, filters={"currency": "USD"})
        assert result["total"] == 1
        assert result["results"][0].currency == "USD"


# =============================================================================
# 9. Filter by date range (created_at)
# =============================================================================


class TestFilterDateRange:
    """Filter by date_from / date_to on created_at."""

    def test_date_from(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="Old",
                      created_at="2026-01-15T00:00:00Z")
        _insert_draft(db_path, batch_id="B2", client_name="New",
                      created_at="2026-06-15T00:00:00Z")
        result = search_drafts(
            db_path, filters={"date_from": "2026-06-01T00:00:00Z"}
        )
        assert result["total"] == 1
        assert result["results"][0].client_name == "New"

    def test_date_to(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="Old",
                      created_at="2026-01-15T00:00:00Z")
        _insert_draft(db_path, batch_id="B2", client_name="New",
                      created_at="2026-06-15T00:00:00Z")
        result = search_drafts(
            db_path, filters={"date_to": "2026-03-01T00:00:00Z"}
        )
        assert result["total"] == 1
        assert result["results"][0].client_name == "Old"

    def test_date_range_both(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="Jan",
                      created_at="2026-01-15T00:00:00Z")
        _insert_draft(db_path, batch_id="B2", client_name="Mar",
                      created_at="2026-03-15T00:00:00Z")
        _insert_draft(db_path, batch_id="B3", client_name="Jun",
                      created_at="2026-06-15T00:00:00Z")
        result = search_drafts(db_path, filters={
            "date_from": "2026-02-01T00:00:00Z",
            "date_to": "2026-04-01T00:00:00Z",
        })
        assert result["total"] == 1
        assert result["results"][0].client_name == "Mar"


# =============================================================================
# 10. Combined filters
# =============================================================================


class TestCombinedFilters:
    """Multiple filters combine with AND logic."""

    def test_client_and_state(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="Estrella",
                      draft_state="posted")
        _insert_draft(db_path, batch_id="B2", client_name="Estrella",
                      draft_state="draft", clone_generation=1)
        _insert_draft(db_path, batch_id="B3", client_name="Other",
                      draft_state="posted")
        result = search_drafts(db_path, filters={
            "client_name": "Estrella",
            "draft_state": "posted",
        })
        assert result["total"] == 1
        assert result["results"][0].batch_id == "B1"

    def test_currency_and_date(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1",
                      currency="EUR", created_at="2026-01-01T00:00:00Z")
        _insert_draft(db_path, batch_id="B2", client_name="C2",
                      currency="EUR", created_at="2026-06-01T00:00:00Z")
        _insert_draft(db_path, batch_id="B3", client_name="C3",
                      currency="USD", created_at="2026-06-01T00:00:00Z")
        result = search_drafts(db_path, filters={
            "currency": "EUR",
            "date_from": "2026-05-01T00:00:00Z",
        })
        assert result["total"] == 1
        assert result["results"][0].client_name == "C2"

    def test_all_filters_together(self, db_path):
        """Apply every filter simultaneously — only exact match survives."""
        _insert_draft(
            db_path, batch_id="B-TARGET", client_name="Estrella Jewels",
            draft_state="posted", currency="EUR",
            wfirma_proforma_id="WF123",
            wfirma_proforma_fullnumber="PROF 99/2026",
            created_at="2026-03-15T10:00:00Z",
        )
        # Decoy rows
        _insert_draft(db_path, batch_id="B-DECOY1", client_name="Other Co",
                      draft_state="draft", currency="USD",
                      created_at="2026-01-01T00:00:00Z")
        _insert_draft(db_path, batch_id="B-DECOY2", client_name="Estrella Jewels",
                      draft_state="draft", currency="EUR",
                      created_at="2026-03-15T10:00:00Z",
                      clone_generation=1)

        result = search_drafts(db_path, filters={
            "batch_id": "B-TARGET",
            "client_name": "Estrella",
            "wfirma_proforma_id": "WF123",
            "wfirma_proforma_fullnumber": "PROF 99",
            "draft_state": "posted",
            "currency": "EUR",
            "date_from": "2026-03-01T00:00:00Z",
            "date_to": "2026-04-01T00:00:00Z",
        })
        assert result["total"] == 1
        assert result["results"][0].batch_id == "B-TARGET"


# =============================================================================
# 11. Pagination
# =============================================================================


class TestPagination:
    """Pagination must respect page and page_size."""

    def test_default_page_size_25(self, db_path):
        result = search_drafts(db_path)
        assert result["page_size"] == 25

    def test_page_1_returns_first_batch(self, db_path):
        for i in range(5):
            _insert_draft(db_path, batch_id=f"B{i}", client_name=f"C{i}",
                          created_at=f"2026-01-{i+1:02d}T00:00:00Z")
        result = search_drafts(db_path, page=1, page_size=3)
        assert len(result["results"]) == 3
        assert result["total"] == 5
        assert result["page"] == 1
        assert result["page_size"] == 3

    def test_page_2_returns_remainder(self, db_path):
        for i in range(5):
            _insert_draft(db_path, batch_id=f"B{i}", client_name=f"C{i}",
                          created_at=f"2026-01-{i+1:02d}T00:00:00Z")
        result = search_drafts(db_path, page=2, page_size=3)
        assert len(result["results"]) == 2
        assert result["total"] == 5
        assert result["page"] == 2

    def test_page_beyond_results_returns_empty(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1")
        result = search_drafts(db_path, page=99, page_size=25)
        assert result["results"] == []
        assert result["total"] == 1

    def test_page_size_clamped_to_100(self, db_path):
        result = search_drafts(db_path, page_size=500)
        assert result["page_size"] == 100

    def test_page_size_minimum_1(self, db_path):
        result = search_drafts(db_path, page_size=0)
        assert result["page_size"] == 1

    def test_page_minimum_1(self, db_path):
        result = search_drafts(db_path, page=-5)
        assert result["page"] == 1


# =============================================================================
# 12. Empty/falsy filters are ignored
# =============================================================================


class TestEmptyFiltersIgnored:
    """Falsy filter values (empty string, None) must not narrow results."""

    def test_empty_string_client_name_ignored(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1")
        result = search_drafts(db_path, filters={"client_name": ""})
        assert result["total"] == 1

    def test_none_batch_id_ignored(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1")
        result = search_drafts(db_path, filters={"batch_id": None})
        assert result["total"] == 1

    def test_empty_filters_dict(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1")
        result = search_drafts(db_path, filters={})
        assert result["total"] == 1

    def test_none_filters(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1")
        result = search_drafts(db_path, filters=None)
        assert result["total"] == 1


# =============================================================================
# 13. Existing functionality unchanged
# =============================================================================


class TestExistingFunctionalityUnchanged:
    """search_drafts must not break existing list_drafts_for_batch."""

    def test_list_drafts_for_batch_still_works(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1")
        _insert_draft(db_path, batch_id="B1", client_name="C2",
                      clone_generation=1)
        _insert_draft(db_path, batch_id="B2", client_name="C3")
        drafts = list_drafts_for_batch(db_path, "B1")
        assert len(drafts) == 2
        assert all(d.batch_id == "B1" for d in drafts)

    def test_search_and_list_see_same_data(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1")
        # list_drafts_for_batch returns batch-scoped results
        listed = list_drafts_for_batch(db_path, "B1")
        # search_drafts with batch_id filter returns same records
        searched = search_drafts(db_path, filters={"batch_id": "B1"})
        assert len(listed) == searched["total"]
        assert listed[0].id == searched["results"][0].id


# =============================================================================
# 14. Response structure
# =============================================================================


class TestResponseStructure:
    """Verify the response dict has all required keys."""

    def test_has_results_key(self, db_path):
        result = search_drafts(db_path)
        assert "results" in result

    def test_has_total_key(self, db_path):
        result = search_drafts(db_path)
        assert "total" in result

    def test_has_page_key(self, db_path):
        result = search_drafts(db_path)
        assert "page" in result

    def test_has_page_size_key(self, db_path):
        result = search_drafts(db_path)
        assert "page_size" in result

    def test_total_is_int(self, db_path):
        _insert_draft(db_path, batch_id="B1", client_name="C1")
        result = search_drafts(db_path)
        assert isinstance(result["total"], int)

    def test_results_is_list(self, db_path):
        result = search_drafts(db_path)
        assert isinstance(result["results"], list)
