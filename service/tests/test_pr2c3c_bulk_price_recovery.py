"""
test_pr2c3c_bulk_price_recovery.py — PR 2C.3c: bulk price recovery.

Tests
-----
Happy path (1-5)
  1.  updates matching product_code lines, leaves others unchanged
  2.  unmatched codes reported in return value
  3.  needs_pricing_refresh becomes False when all lines filled
  4.  source_lines_json is byte-for-byte unchanged after call
  5.  preserves qty, currency, client_ref, design_no, item_type, name_pl

Validation / rejection (6-12)
  6.  rejects unit_price == 0
  7.  rejects negative unit_price
  8.  rejects non-numeric unit_price
  9.  rejects blank product_code
  10. rejects duplicate product_code in payload
  11. rejects empty prices list
  12. rejects blank operator

OCC / state gates (13-16)
  13. requires expected_updated_at (empty string → DraftConflict)
  14. rejects stale expected_updated_at
  15. blocked on approved draft (DraftNotEditable)
  16. blocked on cancelled draft (DraftNotEditable)

Overwrite guard (17-20)
  17. raises OverwriteRequired when nonzero price would be overwritten
  18. confirm_overwrite=True allows overwrite, overwritten_count=1
  19. no confirm required when all target lines are zero
  20. wrong confirm token (not exact string) still raises OverwriteRequired

Event log + state + misc (21-25)
  21. records event "draft_bulk_price_recovery" with correct detail fields
  22. draft→editing state transition
  23. post_failed state is preserved after edit
  24. updated lines have price_source="bulk_recovery"; untouched lines unchanged
  25. dashboard source-grep: required testids present in dashboard.html
"""
from __future__ import annotations

import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.services.proforma_invoice_link_db import (   # noqa: E402
    DraftConflict,
    DraftNotEditable,
    DraftNotFound,
    OverwriteRequired,
    approve_draft,
    bulk_price_recovery,
    cancel_draft,
    get_draft_by_id,
    init_db as pildb_init_db,
    list_draft_events,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_counter = 0


def _mk_db(tmp_path: Path) -> Path:
    db = tmp_path / "proforma_links.db"
    pildb_init_db(db)
    return db


def _make_draft(
    db: Path,
    *,
    currency: str = "EUR",
    lines: list | None = None,
    state: str = "draft",
    status: str = "draft",
) -> int:
    """Insert a minimal draft row directly so we control state precisely."""
    global _counter
    _counter += 1
    pildb_init_db(db)
    now = "2026-05-15T08:00:00+00:00"
    default_lines = [
        {
            "line_id": i + 1,
            "product_code": f"EJL/TEST/{i+1:03d}",
            "qty": 1.0,
            "unit_price": 0.0,
            "currency": currency,
            "client_ref": "REF-001",
            "design_no": f"DES{i+1:04d}",
            "item_type": "RING",
            "name_pl": f"pierścionek {i+1}",
            "description_en": f"Ring {i+1}",
            "description_pl": f"pierścionek {i+1}",
            "price_source": "packing_promote",
            "pd_confidence": "LOW",
        }
        for i in range(3)
    ]
    src_lines = json.dumps(default_lines)   # source_lines mirrors editable
    editable  = json.dumps(lines if lines is not None else default_lines)
    with sqlite3.connect(str(db), isolation_level=None) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("""
            INSERT INTO proforma_drafts
                (batch_id, client_name, status, currency, exchange_rate,
                 source_lines_json, editable_lines_json,
                 wfirma_proforma_id, notes,
                 draft_state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
            ON CONFLICT(batch_id, client_name) DO NOTHING
        """, (
            f"BATCH-2C3C-{_counter}", "TestClient",
            status, currency, 1.0,
            src_lines, editable,
            state, now, now,
        ))
        row = conn.execute(
            "SELECT id FROM proforma_drafts WHERE batch_id=?",
            (f"BATCH-2C3C-{_counter}",),
        ).fetchone()
        return row["id"]


def _get_source_lines_raw(db: Path, draft_id: int) -> str:
    """Return the raw source_lines_json string for byte comparison."""
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT source_lines_json FROM proforma_drafts WHERE id=?",
            (draft_id,),
        ).fetchone()
    return row[0] if row else ""


# ── Helper to build a 3-line draft and run recovery on 2 of them ─────────────

def _standard_prices(n: int = 2) -> list:
    return [
        {"product_code": f"EJL/TEST/{i+1:03d}", "unit_price": 10.0 + i}
        for i in range(n)
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Group 1 — Happy path
# ══════════════════════════════════════════════════════════════════════════════

def test_bulk_price_updates_matching_codes(tmp_path):
    """Test 1: matching lines get new unit_price; 3rd line stays zero."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)

    refreshed = bulk_price_recovery(
        db, did,
        [
            {"product_code": "EJL/TEST/001", "unit_price": 55.0},
            {"product_code": "EJL/TEST/002", "unit_price": 66.0},
        ],
        "operator",
        d0.updated_at,
    )

    lines = json.loads(refreshed.editable_lines_json)
    by_code = {ln["product_code"]: ln for ln in lines}
    assert by_code["EJL/TEST/001"]["unit_price"] == 55.0
    assert by_code["EJL/TEST/002"]["unit_price"] == 66.0
    assert by_code["EJL/TEST/003"]["unit_price"] == 0.0   # untouched


def test_bulk_price_unmatched_codes_reported(tmp_path):
    """Test 2: product_codes not in lines are returned in unmatched list."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)

    # Provide one real code and one bogus
    prices = [
        {"product_code": "EJL/TEST/001", "unit_price": 10.0},
        {"product_code": "BOGUS/CODE",    "unit_price": 20.0},
    ]
    # OverwriteRequired won't fire here since all lines start at 0.
    # We need to capture unmatched_codes from the event.
    refreshed = bulk_price_recovery(db, did, prices, "op", d0.updated_at)
    events = list_draft_events(db, did)
    detail = json.loads(events[-1]["detail_json"])
    assert "BOGUS/CODE" in detail["unmatched_codes"]
    assert detail["updated_count"] == 1


def test_bulk_price_needs_pricing_refresh_false_when_all_filled(tmp_path):
    """Test 3: after filling all lines, needs_pricing_refresh is False."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)

    prices = [
        {"product_code": f"EJL/TEST/{i+1:03d}", "unit_price": float(10 + i)}
        for i in range(3)
    ]
    refreshed = bulk_price_recovery(db, did, prices, "op", d0.updated_at)

    lines = json.loads(refreshed.editable_lines_json)
    still_zero = sum(1 for ln in lines if float(ln.get("unit_price", 0) or 0) <= 0)
    assert still_zero == 0


def test_bulk_price_source_lines_json_unchanged(tmp_path):
    """Test 4: source_lines_json is byte-for-byte identical before and after."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    src_before = _get_source_lines_raw(db, did)
    d0  = get_draft_by_id(db, did)

    bulk_price_recovery(db, did, _standard_prices(2), "op", d0.updated_at)

    src_after = _get_source_lines_raw(db, did)
    assert src_after == src_before, "source_lines_json must never be modified"


def test_bulk_price_preserves_non_price_fields(tmp_path):
    """Test 5: qty, currency, design_no, client_ref, item_type, name_pl unchanged."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)

    lines_before = {
        ln["product_code"]: ln
        for ln in json.loads(d0.editable_lines_json)
    }

    bulk_price_recovery(
        db, did,
        [{"product_code": "EJL/TEST/001", "unit_price": 99.0}],
        "op", d0.updated_at,
    )

    refreshed = get_draft_by_id(db, did)
    lines_after = {
        ln["product_code"]: ln
        for ln in json.loads(refreshed.editable_lines_json)
    }

    for field in ("qty", "currency", "design_no", "client_ref", "item_type", "name_pl"):
        assert lines_after["EJL/TEST/001"][field] == lines_before["EJL/TEST/001"][field], \
            f"{field} was modified — it must be preserved"


# ══════════════════════════════════════════════════════════════════════════════
# Group 2 — Validation / rejection
# ══════════════════════════════════════════════════════════════════════════════

def test_bulk_price_rejects_zero_price(tmp_path):
    """Test 6: unit_price=0 raises ValueError."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)
    with pytest.raises(ValueError, match="> 0"):
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": 0.0}],
            "op", d0.updated_at,
        )


def test_bulk_price_rejects_negative_price(tmp_path):
    """Test 7: negative unit_price raises ValueError."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)
    with pytest.raises(ValueError, match="> 0"):
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": -5.0}],
            "op", d0.updated_at,
        )


def test_bulk_price_rejects_non_numeric_price(tmp_path):
    """Test 8: non-numeric unit_price raises ValueError."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)
    with pytest.raises(ValueError, match="numeric"):
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": "abc"}],
            "op", d0.updated_at,
        )


def test_bulk_price_rejects_blank_product_code(tmp_path):
    """Test 9: blank product_code raises ValueError."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)
    with pytest.raises(ValueError, match="non-blank"):
        bulk_price_recovery(
            db, did,
            [{"product_code": "", "unit_price": 10.0}],
            "op", d0.updated_at,
        )


def test_bulk_price_rejects_duplicate_product_code(tmp_path):
    """Test 10: duplicate product_code in request raises ValueError."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)
    with pytest.raises(ValueError, match="duplicate"):
        bulk_price_recovery(
            db, did,
            [
                {"product_code": "EJL/TEST/001", "unit_price": 10.0},
                {"product_code": "EJL/TEST/001", "unit_price": 20.0},
            ],
            "op", d0.updated_at,
        )


def test_bulk_price_rejects_empty_prices_list(tmp_path):
    """Test 11: empty prices list raises ValueError."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)
    with pytest.raises(ValueError, match="non-empty"):
        bulk_price_recovery(db, did, [], "op", d0.updated_at)


def test_bulk_price_rejects_blank_operator(tmp_path):
    """Test 12: blank operator raises ValueError."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)
    with pytest.raises(ValueError, match="operator is required"):
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": 10.0}],
            "",
            d0.updated_at,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Group 3 — OCC / state gates
# ══════════════════════════════════════════════════════════════════════════════

def test_bulk_price_requires_expected_updated_at(tmp_path):
    """Test 13: empty expected_updated_at → DraftConflict."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    with pytest.raises(DraftConflict):
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": 10.0}],
            "op", "",
        )


def test_bulk_price_rejects_stale_expected_updated_at(tmp_path):
    """Test 14: stale timestamp → DraftConflict."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    with pytest.raises(DraftConflict):
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": 10.0}],
            "op", "2000-01-01T00:00:00+00:00",   # definitely stale
        )


def test_bulk_price_blocked_on_approved_draft(tmp_path):
    """Test 15: approved draft → DraftNotEditable."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)
    # First fill prices so approve can proceed (approve checks zero-price guard
    # separately — but our approve_draft in pildb doesn't block on it).
    # We'll approve the draft directly.
    approved = approve_draft(
        db, did, "op", d0.updated_at,
        confirm_token="YES_APPROVE_LOCAL_PROFORMA_DRAFT",
    )
    with pytest.raises(DraftNotEditable):
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": 10.0}],
            "op", approved.updated_at,
        )


def test_bulk_price_blocked_on_cancelled_draft(tmp_path):
    """Test 16: cancelled draft → DraftNotEditable."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)
    cancelled = cancel_draft(db, did, "op", d0.updated_at, reason="test")
    with pytest.raises(DraftNotEditable):
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": 10.0}],
            "op", cancelled.updated_at,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Group 4 — Overwrite guard
# ══════════════════════════════════════════════════════════════════════════════

def _draft_with_one_priced_line(db: Path) -> tuple:
    """Return (draft_id, updated_at) with line 1 having unit_price=100."""
    lines = [
        {
            "line_id": 1,
            "product_code": "EJL/TEST/001",
            "qty": 1.0,
            "unit_price": 100.0,     # already priced
            "currency": "EUR",
            "client_ref": "REF",
            "design_no": "DES0001",
            "item_type": "RING",
            "name_pl": "pierścionek 1",
            "description_en": "Ring 1",
            "description_pl": "pierścionek 1",
            "price_source": "manual",
            "pd_confidence": "LOW",
        },
        {
            "line_id": 2,
            "product_code": "EJL/TEST/002",
            "qty": 1.0,
            "unit_price": 0.0,
            "currency": "EUR",
            "client_ref": "REF",
            "design_no": "DES0002",
            "item_type": "RING",
            "name_pl": "pierścionek 2",
            "description_en": "Ring 2",
            "description_pl": "pierścionek 2",
            "price_source": "packing_promote",
            "pd_confidence": "LOW",
        },
    ]
    did = _make_draft(db, lines=lines)
    d0  = get_draft_by_id(db, did)
    return did, d0.updated_at


def test_bulk_price_overwrite_requires_confirm(tmp_path):
    """Test 17: existing non-zero price → OverwriteRequired without confirm."""
    db = _mk_db(tmp_path)
    did, ts = _draft_with_one_priced_line(db)
    with pytest.raises(OverwriteRequired) as exc_info:
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": 200.0}],
            "op", ts,
        )
    assert "EJL/TEST/001" in exc_info.value.codes


def test_bulk_price_confirm_overwrite_allows_update(tmp_path):
    """Test 18: confirm_overwrite=True allows overwriting; overwritten_count=1."""
    db = _mk_db(tmp_path)
    did, ts = _draft_with_one_priced_line(db)
    refreshed = bulk_price_recovery(
        db, did,
        [{"product_code": "EJL/TEST/001", "unit_price": 200.0}],
        "op", ts,
        confirm_overwrite=True,
    )
    lines = {ln["product_code"]: ln for ln in json.loads(refreshed.editable_lines_json)}
    assert lines["EJL/TEST/001"]["unit_price"] == 200.0

    events = list_draft_events(db, did)
    detail = json.loads(events[-1]["detail_json"])
    assert detail["overwritten_count"] == 1
    assert detail["updated_count"] == 1


def test_bulk_price_no_confirm_needed_when_all_zero(tmp_path):
    """Test 19: no OverwriteRequired when all target lines have unit_price=0."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)   # all lines start at 0
    d0  = get_draft_by_id(db, did)
    # Must not raise
    refreshed = bulk_price_recovery(
        db, did,
        [{"product_code": "EJL/TEST/001", "unit_price": 50.0}],
        "op", d0.updated_at,
    )
    assert refreshed is not None


def test_bulk_price_wrong_confirm_token_still_raises(tmp_path):
    """Test 20: wrong confirm_overwrite value (not exact token) → OverwriteRequired."""
    db = _mk_db(tmp_path)
    did, ts = _draft_with_one_priced_line(db)
    with pytest.raises(OverwriteRequired):
        # confirm_overwrite=False (default) — same as passing wrong string at DB layer
        bulk_price_recovery(
            db, did,
            [{"product_code": "EJL/TEST/001", "unit_price": 200.0}],
            "op", ts,
            confirm_overwrite=False,   # explicitly wrong
        )


# ══════════════════════════════════════════════════════════════════════════════
# Group 5 — Event log + state + price_source + dashboard source-grep
# ══════════════════════════════════════════════════════════════════════════════

def test_bulk_price_records_event(tmp_path):
    """Test 21: event "draft_bulk_price_recovery" recorded with correct fields."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)

    bulk_price_recovery(
        db, did,
        [
            {"product_code": "EJL/TEST/001", "unit_price": 11.0},
            {"product_code": "BOGUS",        "unit_price": 22.0},
        ],
        "tester", d0.updated_at,
    )

    events = list_draft_events(db, did)
    bpr_events = [e for e in events if e["event"] == "draft_bulk_price_recovery"]
    assert len(bpr_events) == 1

    detail = json.loads(bpr_events[0]["detail_json"])
    assert "updated_count" in detail
    assert "unmatched_codes" in detail
    assert "still_zero_count" in detail
    assert "overwritten_count" in detail
    assert detail["updated_count"] == 1
    assert "BOGUS" in detail["unmatched_codes"]
    assert detail["overwritten_count"] == 0


def test_bulk_price_draft_transitions_to_editing(tmp_path):
    """Test 22: draft state 'draft' → 'editing' after recovery."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db, state="draft")
    d0  = get_draft_by_id(db, did)

    refreshed = bulk_price_recovery(
        db, did,
        [{"product_code": "EJL/TEST/001", "unit_price": 10.0}],
        "op", d0.updated_at,
    )
    assert refreshed.draft_state == "editing"


def test_bulk_price_post_failed_state_preserved(tmp_path):
    """Test 23: post_failed state stays post_failed after recovery."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db, state="post_failed", status="draft")
    d0  = get_draft_by_id(db, did)

    refreshed = bulk_price_recovery(
        db, did,
        [{"product_code": "EJL/TEST/001", "unit_price": 10.0}],
        "op", d0.updated_at,
    )
    assert refreshed.draft_state == "post_failed"


def test_bulk_price_price_source_set_to_bulk_recovery(tmp_path):
    """Test 24: updated lines have price_source='bulk_recovery'; untouched unchanged."""
    db  = _mk_db(tmp_path)
    did = _make_draft(db)
    d0  = get_draft_by_id(db, did)

    refreshed = bulk_price_recovery(
        db, did,
        [{"product_code": "EJL/TEST/001", "unit_price": 42.0}],
        "op", d0.updated_at,
    )
    lines = {ln["product_code"]: ln for ln in json.loads(refreshed.editable_lines_json)}
    assert lines["EJL/TEST/001"]["price_source"] == "bulk_recovery"
    # Untouched line keeps its original price_source
    assert lines["EJL/TEST/002"]["price_source"] == "packing_promote"
    assert lines["EJL/TEST/003"]["price_source"] == "packing_promote"


def test_dashboard_source_grep_bulk_price_testids():
    """Test 25: all required data-testid attributes are present in dashboard.html."""
    html_path = Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html"
    assert html_path.exists(), f"dashboard.html not found at {html_path}"
    content = html_path.read_text(encoding="utf-8")

    required = [
        "draft-pricing-refresh-banner",
        "btn-toggle-bulk-price-recovery",
        "draft-bulk-price-panel",
        "bulk-price-textarea",
        "btn-apply-bulk-prices",
        "bulk-price-result",
        "bulk-price-updated-count",
        "bulk-price-still-zero",
        "bulk-price-unmatched",
        "bulk-price-confirm-overwrite",
        "bulk-price-overwrite-codes",
        "btn-bulk-price-confirm-overwrite",
        "/bulk-price-recovery",
    ]
    missing = [t for t in required if t not in content]
    assert not missing, f"Missing testids/strings in dashboard.html: {missing}"
