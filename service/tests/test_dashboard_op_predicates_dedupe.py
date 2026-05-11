"""tests/test_dashboard_op_predicates_dedupe.py — UI-3.3a

Source-grep tests proving that operational bucket predicate logic
is consolidated at DashboardPage scope and consumed by both the
per-card rendering (counts + attention table) and the active-table
filter (OP_PREDICATES).

The goal of UI-3.3a is single source of truth: card counts and table
filter must never drift apart. This file pins the consolidation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_HERE     = Path(__file__).resolve()
_SVC_ROOT = _HERE.parent.parent
_DASH     = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html not found")
    return _DASH.read_text(encoding="utf-8")


# ── Shared sets exist at DashboardPage scope ──────────────────────────────

@pytest.mark.parametrize(
    "set_name",
    [
        "PZ_DONE_LABELS",
        "PZ_PENDING_LABELS",
        "SAD_CLEARED_KEYS",
        "TRACK_ATTENTION",
        "DHL_FLOW_LIVE_KEYS",
    ],
)
def test_shared_label_set_declared_once(set_name):
    """Each shared label/key set must be declared exactly once.
    Duplicates indicate drift (the bug UI-3.3a fixes)."""
    src = _src()
    # Pattern for declarations.
    needle = f"const {set_name}"
    count = src.count(needle)
    assert count == 1, (
        f"{set_name!r} should be declared exactly once; found {count} "
        "(possible drift between card scope and shared scope)"
    )


# ── Shared warehouse derivation ───────────────────────────────────────────

def test_warehouse_lifecycle_keys_anchor_present():
    src = _src()
    assert "const WAREHOUSE_LIFECYCLE_KEYS" in src


def test_derive_warehouse_lifecycle_anchor_present():
    src = _src()
    assert "const deriveWarehouseLifecycle" in src


def test_warehouse_lifecycle_keys_array_enumerates_all_states():
    src = _src()
    idx = src.find("const WAREHOUSE_LIFECYCLE_KEYS")
    assert idx != -1
    snippet = src[idx : idx + 300]
    for key in ("unknown", "awaiting", "partial_received",
                "in_warehouse", "reserved"):
        assert f"'{key}'" in snippet, (
            f"WAREHOUSE_LIFECYCLE_KEYS must enumerate {key!r}"
        )


def test_derive_warehouse_lifecycle_consults_op_predicates():
    src = _src()
    idx = src.find("const deriveWarehouseLifecycle")
    snippet = src[idx : idx + 600]
    assert "OP_PREDICATES.warehouse[" in snippet, (
        "deriveWarehouseLifecycle must consult OP_PREDICATES.warehouse"
    )


# ── Shared attention predicates ───────────────────────────────────────────

def test_attention_predicates_anchor_present():
    src = _src()
    assert "const ATTENTION_PREDICATES" in src


@pytest.mark.parametrize(
    "card", ["warehouse", "sales_accounting", "dhl_customs"],
)
def test_attention_predicates_exposes_each_card(card):
    src = _src()
    idx = src.find("const ATTENTION_PREDICATES")
    snippet = src[idx : idx + 2000]
    assert f"{card}:" in snippet, (
        f"ATTENTION_PREDICATES must expose {card!r}"
    )


def test_attention_predicates_built_from_op_predicates():
    """Attention predicates must reference OP_PREDICATES so the bucket
    logic is the source of truth, not a parallel re-statement."""
    src = _src()
    idx = src.find("const ATTENTION_PREDICATES")
    snippet = src[idx : idx + 2500]
    # Each card's attention predicate must call into OP_PREDICATES.
    assert "OP_PREDICATES.warehouse.awaiting" in snippet
    assert "OP_PREDICATES.warehouse.partial_received" in snippet
    assert "OP_PREDICATES.sales_accounting.sales_missing" in snippet
    assert "OP_PREDICATES.sales_accounting.wfirma_pending" in snippet
    assert "OP_PREDICATES.sales_accounting.pz_pending" in snippet
    assert "OP_PREDICATES.dhl_customs.awaiting_customs_docs" in snippet


# ── Card-internal aliases point at shared helpers ─────────────────────────

def test_warehouse_card_aliases_shared_derivation():
    """xbatchDeriveLifecycle must alias deriveWarehouseLifecycle —
    a thin pass-through, not a duplicated implementation."""
    src = _src()
    # Find the per-card declaration.
    idx = src.find("const xbatchDeriveLifecycle")
    assert idx != -1
    snippet = src[idx : idx + 300]
    assert "deriveWarehouseLifecycle" in snippet, (
        "xbatchDeriveLifecycle must reference deriveWarehouseLifecycle"
    )


@pytest.mark.parametrize(
    "alias, target",
    [
        ("const acctSalesMissing",   "OP_PREDICATES.sales_accounting.sales_missing"),
        ("const acctWfirmaMissing",  "OP_PREDICATES.sales_accounting.wfirma_pending"),
        ("const acctPzPending",      "OP_PREDICATES.sales_accounting.pz_pending"),
        ("const acctNeedsAttention", "ATTENTION_PREDICATES.sales_accounting"),
    ],
)
def test_sales_card_aliases_point_at_shared(alias, target):
    src = _src()
    idx = src.find(alias)
    assert idx != -1, f"alias {alias!r} missing"
    snippet = src[idx : idx + 400]
    assert target in snippet, (
        f"{alias} must reference {target}"
    )


@pytest.mark.parametrize(
    "alias, target",
    [
        ("const dcSadCleared",      "OP_PREDICATES.dhl_customs.customs_cleared"),
        ("const dcAwaitingCustoms", "OP_PREDICATES.dhl_customs.awaiting_customs_docs"),
        ("const dcNeedsAttention",  "ATTENTION_PREDICATES.dhl_customs"),
    ],
)
def test_dhl_card_aliases_point_at_shared(alias, target):
    src = _src()
    idx = src.find(alias)
    assert idx != -1, f"alias {alias!r} missing"
    snippet = src[idx : idx + 400]
    assert target in snippet, (
        f"{alias} must reference {target}"
    )


# ── Card counts use shared OP_PREDICATES ──────────────────────────────────

@pytest.mark.parametrize(
    "card_counts_anchor",
    [
        # Warehouse card counts (UI-3.1b)
        "unknown:          batches.filter(OP_PREDICATES.warehouse.unknown).length",
        "awaiting:         batches.filter(OP_PREDICATES.warehouse.awaiting).length",
        "partial_received: batches.filter(OP_PREDICATES.warehouse.partial_received).length",
        "in_warehouse:     batches.filter(OP_PREDICATES.warehouse.in_warehouse).length",
        "reserved:         batches.filter(OP_PREDICATES.warehouse.reserved).length",
        # Sales card counts (UI-3.2a)
        "sales_ready:    batches.filter(OP_PREDICATES.sales_accounting.sales_ready).length",
        "sales_missing:  batches.filter(OP_PREDICATES.sales_accounting.sales_missing).length",
        "wfirma_preview: batches.filter(OP_PREDICATES.sales_accounting.wfirma_preview).length",
        "wfirma_pending: batches.filter(OP_PREDICATES.sales_accounting.wfirma_pending).length",
        "pz_done:        batches.filter(OP_PREDICATES.sales_accounting.pz_done).length",
        "pz_pending:     batches.filter(OP_PREDICATES.sales_accounting.pz_pending).length",
        # DHL card counts (UI-3.2b)
        "awaiting_customs_docs: batches.filter(OP_PREDICATES.dhl_customs.awaiting_customs_docs).length",
        "sad_present:           batches.filter(OP_PREDICATES.dhl_customs.sad_present).length",
        "sad_missing:           batches.filter(OP_PREDICATES.dhl_customs.sad_missing).length",
        "customs_cleared:       batches.filter(OP_PREDICATES.dhl_customs.customs_cleared).length",
        "dhl_in_transit:        batches.filter(OP_PREDICATES.dhl_customs.dhl_in_transit).length",
        "dhl_delivered:         batches.filter(OP_PREDICATES.dhl_customs.dhl_delivered).length",
    ],
)
def test_card_count_uses_op_predicates(card_counts_anchor):
    """Every cross-batch count must filter via OP_PREDICATES.
    Local re-statements would re-introduce drift."""
    src = _src()
    assert card_counts_anchor in src, (
        f"card count line {card_counts_anchor!r} missing — "
        "card may have drifted away from OP_PREDICATES"
    )


# ── No duplicate predicate definitions remain ─────────────────────────────

@pytest.mark.parametrize(
    "duplicated_pattern",
    [
        # Old warehouse local logic.
        "if (wh === 'n/a')     return 'unknown';",
        "if (wh === 'empty')   return 'awaiting';",
        "if (wh === 'partial') return 'partial_received';",
        # Old sales-card local predicate bodies.
        "const acctSalesMissing = (row) => {",
        "const acctWfirmaMissing = (row) => {",
        "const acctPzPending = (row) => {",
        # Old DHL-card local predicate bodies.
        "const dcSadCleared       = (row) => !!row.has_sad &&",
        "const dcAwaitingCustoms  = (row) => !row.has_sad &&",
    ],
)
def test_obsolete_local_predicate_body_removed(duplicated_pattern):
    """The original per-card predicate bodies must be gone after
    consolidation. If any reappear, drift can creep back in."""
    src = _src()
    assert duplicated_pattern not in src, (
        f"obsolete duplicated predicate body still present: "
        f"{duplicated_pattern!r}"
    )


# ── Behaviour preservation — UI-3.3 surfaces unaffected ───────────────────

def test_op_predicates_still_declared():
    src = _src()
    assert "const OP_PREDICATES" in src


def test_op_predicate_dispatch_still_declared():
    src = _src()
    assert "const opPredicate = (row) => {" in src


def test_isOpActive_still_declared():
    src = _src()
    assert "const isOpActive" in src


def test_toggle_op_filter_still_declared():
    src = _src()
    assert "const toggleOpFilter" in src


def test_clear_op_filter_still_declared():
    src = _src()
    assert "const clearOpFilter" in src


# ── Brace balance / file sanity ───────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
