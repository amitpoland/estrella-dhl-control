"""tests/test_c13d_transit_aware_inventory_ui.py — C13D

Source-grep tests verifying that PURCHASE_TRANSIT inventory is NOT
rendered as "Missing scan" in shipment-detail.html or dashboard.html.

C13D contract:
  - invState.synthetic === true + PURCHASE_TRANSIT count > 0
    → lifecycleState returns 'in_transit' (not 'awaiting')
  - displayMissing suppresses missing_scans list for transit batches
  - cleanGate uses displayMissing (not raw missing)
  - Warehouse tab shows transit note instead of red table
  - Sales tab statusBadge remaps 'missing_scan' → 'in_transit' when isTransit
  - Sales tab summary counter label switches to 'In transit' when isTransit
  - dashboard.html piece drawer renders 'In transit' label for PURCHASE_TRANSIT
  - No write actions added, no backend touched
"""
from __future__ import annotations

from pathlib import Path

import pytest

_HERE     = Path(__file__).resolve()
_SVC_ROOT = _HERE.parent.parent
_DETAIL   = _SVC_ROOT / "app" / "static" / "shipment-detail.html"
_DASH     = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _detail() -> str:
    if not _DETAIL.exists():
        pytest.skip("shipment-detail.html not found")
    return _DETAIL.read_text(encoding="utf-8")


def _dash() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html not found")
    return _DASH.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════
# CLASS 1: isTransit detection in Warehouse tab
# ══════════════════════════════════════════════════════════

class TestC13DIsTransitDetection:
    def test_is_transit_reads_invstate_synthetic(self):
        """isTransit must check invState.synthetic — the C13A field."""
        src = _detail()
        assert "invState.synthetic" in src, (
            "isTransit must check invState.synthetic"
        )

    def test_is_transit_reads_purchase_transit_count(self):
        """isTransit must check PURCHASE_TRANSIT count so it only fires
        when there are actual transit items."""
        src = _detail()
        assert "PURCHASE_TRANSIT" in src, (
            "isTransit must check counts.PURCHASE_TRANSIT"
        )

    def test_display_missing_defined(self):
        """displayMissing must be defined as the transit-filtered list."""
        src = _detail()
        assert "displayMissing" in src, (
            "displayMissing variable must be declared"
        )

    def test_display_missing_is_empty_when_transit(self):
        """displayMissing must resolve to [] when isTransit is true."""
        src = _detail()
        assert "isTransit ? [] : missing" in src, (
            "displayMissing must be [] when isTransit"
        )

    def test_clean_gate_uses_display_missing(self):
        """cleanGate must use displayMissing.length, not missing.length,
        so transit batches don't block the reservation gate."""
        src = _detail()
        idx = src.find("const cleanGate")
        assert idx != -1
        snippet = src[idx : idx + 250]
        assert "displayMissing.length" in snippet, (
            "cleanGate must use displayMissing.length"
        )
        assert "missing.length" not in snippet.replace("displayMissing.length", ""), (
            "cleanGate must not reference raw missing.length"
        )


# ══════════════════════════════════════════════════════════
# CLASS 2: in_transit lifecycle state — Warehouse tab
# ══════════════════════════════════════════════════════════

class TestC13DLifecycleState:
    def test_in_transit_state_key_exists(self):
        """'in_transit' must be a declared lifecycle state key."""
        src = _detail()
        assert "in_transit" in src, (
            "'in_transit' lifecycle key missing from shipment-detail.html"
        )

    def test_in_transit_returned_from_lifecycle_iife(self):
        """The lifecycleState IIFE must return 'in_transit' when
        isTransit is true, before the 'awaiting' branch."""
        src = _detail()
        idx = src.find("const lifecycleState")
        assert idx != -1
        body = src[idx : idx + 900]
        assert "return 'in_transit'" in body, (
            "lifecycleState IIFE must return 'in_transit'"
        )

    def test_in_transit_before_awaiting_in_iife(self):
        """The isTransit check must precede the scanned === 0 → awaiting
        check to correctly override the awaiting state."""
        src = _detail()
        idx = src.find("const lifecycleState")
        body = src[idx : idx + 900]
        transit_pos = body.find("in_transit")
        awaiting_pos = body.find("'awaiting'")
        assert transit_pos < awaiting_pos, (
            "isTransit → in_transit branch must come before awaiting branch"
        )

    def test_in_transit_label_declared(self):
        """lifecycleLabel must map 'in_transit' to a human-readable string."""
        src = _detail()
        assert "In transit / Awaiting warehouse receive" in src, (
            "in_transit lifecycle label not found"
        )

    def test_in_transit_tone_declared(self):
        """lifecycleTone must have an 'in_transit' entry (blue — expected state).
        Searches from isTransit declaration to find the right Warehouse-tab block."""
        src = _detail()
        # Use isTransit declaration as anchor since lifecycleTone appears multiple times.
        idx = src.find("C13D: synthetic PURCHASE_TRANSIT batches have no warehouse scans")
        assert idx != -1
        body = src[idx : idx + 3000]
        assert "in_transit" in body, (
            "lifecycleTone must include 'in_transit' entry (searched from isTransit anchor)"
        )


# ══════════════════════════════════════════════════════════
# CLASS 3: Missing scans section — transit suppression
# ══════════════════════════════════════════════════════════

class TestC13DMissingScanSection:
    def test_missing_scans_badge_uses_display_missing(self):
        """The Missing scans badge count must use displayMissing.length,
        not missing.length, so transit items don't show a red count."""
        src = _detail()
        idx = src.find("Missing scans")
        assert idx != -1
        snippet = src[idx : idx + 400]
        assert "displayMissing.length" in snippet, (
            "Missing scans badge must count displayMissing not missing"
        )

    def test_transit_note_testid_present(self):
        """A transit-specific note with data-testid must replace the
        red table when isTransit."""
        src = _detail()
        assert 'data-testid="warehouse-transit-note"' in src, (
            "transit note element must have data-testid='warehouse-transit-note'"
        )

    def test_transit_note_shown_when_is_transit(self):
        """The transit note is conditional on isTransit."""
        src = _detail()
        idx = src.find('data-testid="warehouse-transit-note"')
        assert idx != -1
        # Look back 500 chars to cover the long style attribute before data-testid.
        prefix = src[max(0, idx - 500) : idx]
        assert "isTransit" in prefix, (
            "transit note must be conditional on isTransit"
        )

    def test_transit_note_says_no_action_required(self):
        """Transit note must tell the operator no action is needed."""
        src = _detail()
        assert "No action required" in src or "no action required" in src, (
            "transit note must explain no action is required"
        )

    def test_missing_table_uses_display_missing_slice(self):
        """The missing scans table must iterate displayMissing, not missing."""
        src = _detail()
        assert "displayMissing.slice" in src, (
            "missing scans table must use displayMissing.slice()"
        )


# ══════════════════════════════════════════════════════════
# CLASS 4: Sales tab — missing_scan → in_transit remapping
# ══════════════════════════════════════════════════════════

class TestC13DSalesTabRemap:
    def test_sales_tab_has_is_transit(self):
        """Sales tab must compute isTransit for context banner and summary counter.
        C14A superseded per-line remap with a banner; isTransit detection remains.
        Verified via C14A comment anchor unique to the Sales tab isTransit block."""
        src = _detail()
        # C14A comment anchor replaces the old C13D anchor.
        assert "C14A: transit detection" in src, (
            "Sales tab must have isTransit detection (C14A comment anchor missing)"
        )

    def test_status_badge_has_in_transit_entry(self):
        """STATUS_BADGE must have an 'in_transit' entry for in_transit-state items."""
        src = _detail()
        assert "in_transit:" in src, (
            "STATUS_BADGE must include in_transit entry"
        )

    def test_status_badge_uses_pending_arrival_for_missing_scan(self):
        """C14A: statusBadge no longer remaps missing_scan → in_transit per line.
        Instead, missing_scan shows 'Pending arrival' (amber) and the transit
        context banner above the groups explains the inventory location."""
        src = _detail()
        # C14A deliberate change: per-line remap removed; banner added instead.
        assert "Pending arrival" in src, (
            "missing_scan status must show 'Pending arrival' label (C14A)"
        )
        # Confirm the old inline remap is gone (it was confusing Sales status
        # with inventory location).
        assert "isTransit && s === 'missing_scan'" not in src and \
               "isTransit && s==='missing_scan'" not in src, (
            "per-line missing_scan→in_transit remap must be absent (C14A removed it)"
        )

    def test_sales_summary_counter_switches_label_when_transit(self):
        """Summary counter label must show 'In transit:' instead of
        'Missing scan:' when the batch is in transit."""
        src = _detail()
        assert "isTransit ? 'In transit:'" in src or \
               "isTransit?'In transit:'" in src, (
            "summary counter label must switch to 'In transit:' when isTransit"
        )

    def test_sales_summary_counter_uses_blue_color_when_transit(self):
        """Missing scan counter must use blue (not red) color when isTransit."""
        src = _detail()
        assert "isTransit ? 'var(--badge-blue-text)'" in src or \
               "isTransit?'var(--badge-blue-text)'" in src, (
            "transit items must use blue color in summary counter, not red"
        )


# ══════════════════════════════════════════════════════════
# CLASS 5: dashboard.html — piece drawer label
# ══════════════════════════════════════════════════════════

class TestC13DDashboardPieceDrawer:
    def test_purchase_transit_maps_to_in_transit_label(self):
        """dashboard.html must map PURCHASE_TRANSIT state to
        'In transit' human-readable label."""
        src = _dash()
        assert "PURCHASE_TRANSIT" in src and "'In transit'" in src, (
            "dashboard.html must declare PURCHASE_TRANSIT → 'In transit' mapping"
        )

    def test_piece_state_pill_uses_st_label(self):
        """The piece state pill must render stLabel not raw st code.
        data-state={st} attribute is allowed; only the child text must use stLabel."""
        src = _dash()
        idx = src.find('data-testid="inventory-piece-state-pill"')
        assert idx != -1
        snippet = src[idx : idx + 500]
        assert "{stLabel}" in snippet, (
            "piece state pill must render {stLabel} not {st}"
        )
        # The pill child text must be stLabel. Strip data-state={st} from check.
        child_text = snippet.split("}}>{")[-1]  # content after the closing style brace
        assert child_text.startswith("stLabel}"), (
            "piece state pill child text must be {stLabel}, not {st}"
        )

    def test_warehouse_lifecycle_label_has_in_transit(self):
        """WAREHOUSE_LIFECYCLE_LABEL must include 'in_transit' key
        so if the backend adds transit hint, the UI handles it."""
        src = _dash()
        # Find the const declaration (not the comment that references the name).
        idx = src.find("const WAREHOUSE_LIFECYCLE_LABEL")
        assert idx != -1, "WAREHOUSE_LIFECYCLE_LABEL declaration not found"
        body = src[idx : idx + 400]
        assert "in_transit" in body, (
            "WAREHOUSE_LIFECYCLE_LABEL must include in_transit entry"
        )

    def test_xbatch_lifecycle_tone_has_in_transit(self):
        """xbatchLifecycleTone must include 'in_transit' entry."""
        src = _dash()
        idx = src.find("xbatchLifecycleTone")
        assert idx != -1
        body = src[idx : idx + 500]
        assert "in_transit" in body, (
            "xbatchLifecycleTone must include in_transit entry"
        )


# ══════════════════════════════════════════════════════════
# CLASS 6: Safety invariants — no forbidden mutations
# ══════════════════════════════════════════════════════════

class TestC13DSafetyInvariants:
    def test_no_wfirma_write_flag_touched(self):
        """C13D must not touch WFIRMA_CREATE_PZ_ALLOWED flag."""
        src = _detail()
        assert "WFIRMA_CREATE_PZ_ALLOWED" not in src, (
            "shipment-detail.html must not reference WFIRMA_CREATE_PZ_ALLOWED"
        )

    def test_no_fake_ready_state(self):
        """C13D must not fake warehouse readiness — cleanGate must still
        block on stuck/invalid/orphan issues even in transit mode."""
        src = _detail()
        idx = src.find("const cleanGate")
        snippet = src[idx : idx + 250]
        assert "stuck.length" in snippet, (
            "cleanGate must still check stuck inventory"
        )
        assert "invalid.length" in snippet, (
            "cleanGate must still check invalid flows"
        )
        assert "orphans.length" in snippet, (
            "cleanGate must still check orphan scans"
        )

    def test_transit_note_is_read_only(self):
        """Transit note must be informational — no button, no form."""
        src = _detail()
        idx = src.find('data-testid="warehouse-transit-note"')
        assert idx != -1
        snippet = src[idx : idx + 300]
        assert "<Btn" not in snippet, "transit note must not contain a Btn"
        assert "<button" not in snippet, "transit note must not contain a button"
        assert "onClick" not in snippet, "transit note must not bind onClick"

    def test_shipment_detail_braces_balanced(self):
        """shipment-detail.html must have balanced braces after C13D edits."""
        src = _detail()
        opens  = src.count("{")
        closes = src.count("}")
        assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"

    def test_dashboard_html_braces_balanced(self):
        """dashboard.html must have balanced braces after C13D edits."""
        src = _dash()
        opens  = src.count("{")
        closes = src.count("}")
        assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
