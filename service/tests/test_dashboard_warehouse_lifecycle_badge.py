"""tests/test_dashboard_warehouse_lifecycle_badge.py — UI-3.1a

Source-grep tests for the read-only inventory lifecycle badge added
near the warehouse readiness banner.

The badge:
  - is derived purely from existing backend payload
    (warehouseAudit.summary.* + audit.wfirma_export.wfirma_pz_doc_id);
  - exposes a stable technical key via data-lifecycle-state;
  - renders an operator-readable label via a label map;
  - is read-only — there is no button, no form, no write surface;
  - is DHL-Express scope — no FedEx / UPS / multi-carrier copy.
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


# ── Badge landmark ────────────────────────────────────────────────────────

def test_lifecycle_badge_testid_present():
    """The badge container exposes a stable data-testid landmark."""
    src = _src()
    assert 'data-testid="warehouse-inventory-lifecycle-badge"' in src


def test_lifecycle_pill_testid_present():
    """The inner pill exposes its own data-testid so the rendered
    label is independently locatable."""
    src = _src()
    assert 'data-testid="warehouse-inventory-lifecycle-pill"' in src


def test_lifecycle_badge_carries_state_data_attribute():
    """The badge carries data-lifecycle-state with the technical key
    so tests and filters can read the raw state value without
    parsing the operator-readable label."""
    src = _src()
    idx = src.find('data-testid="warehouse-inventory-lifecycle-badge"')
    assert idx != -1
    snippet = src[idx : idx + 600]
    assert "data-lifecycle-state={lifecycleState}" in snippet, (
        "badge must expose data-lifecycle-state={lifecycleState}"
    )


def test_lifecycle_badge_renders_after_readiness_banner():
    """The badge must sit immediately after the warehouse readiness
    banner, not buried in the audit details section."""
    src = _src()
    banner_idx = src.find('data-testid="readiness-banner-warehouse"')
    badge_idx  = src.find('data-testid="warehouse-inventory-lifecycle-badge"')
    assert banner_idx != -1 and badge_idx != -1
    assert badge_idx > banner_idx, "badge must render after the readiness banner"
    # Within 2.5 KB of the banner — i.e. in the same warehouse-tab block.
    assert badge_idx - banner_idx < 2500, (
        "badge appears too far from the warehouse readiness banner; "
        "likely rendered in the wrong tab"
    )


# ── Lifecycle key map ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "key",
    [
        "unknown",
        "awaiting",
        "partial_received",
        "in_warehouse",
        "reserved",
        "partial_dispatch",
        "dispatched",
    ],
)
def test_lifecycle_state_key_declared(key):
    """All seven technical lifecycle keys must appear in the source —
    they are the union of states the derivation function can produce."""
    src = _src()
    assert f"{key}:" in src or f"'{key}'" in src or f'"{key}"' in src, (
        f"lifecycle state key {key!r} missing from dashboard.html"
    )


@pytest.mark.parametrize(
    "label",
    [
        "No packing list",
        "Awaiting receipt",
        "Partially received",
        "In warehouse",
        "Reserved (PZ created)",
        "Partial dispatch",
        "Dispatched",
    ],
)
def test_lifecycle_operator_label_present(label):
    """Every state must have an operator-readable label string."""
    src = _src()
    assert label in src, f"operator-readable lifecycle label {label!r} missing"


def test_lifecycle_label_map_anchor_present():
    """The label-map declaration anchor (`lifecycleLabel = {`) exists
    so it can be located by reviewers and downstream tests."""
    src = _src()
    assert "const lifecycleLabel" in src, "lifecycleLabel declaration missing"


def test_lifecycle_state_anchor_present():
    """The state-derivation anchor exists."""
    src = _src()
    assert "const lifecycleState" in src, "lifecycleState declaration missing"


# ── Derivation: backend-payload source only ───────────────────────────────

def test_lifecycle_uses_warehouse_summary_fields():
    """Derivation must read from existing warehouse audit summary,
    not from invented or hardcoded values."""
    src = _src()
    idx = src.find("const lifecycleState")
    assert idx != -1
    body = src[idx : idx + 1200]
    for field in ("total_items", "scanned_items", "dispatched_items"):
        assert f"summary.{field}" in body or f"summary.{field}" in src, (
            f"derivation must reference summary.{field}"
        )


def test_lifecycle_uses_wfirma_pz_doc_id_for_reserved():
    """The 'reserved' state must be gated on the existing wFirma PZ
    doc id field. No new backend signal is invented."""
    src = _src()
    idx = src.find("const lifecycleState")
    body = src[idx : idx + 1200]
    assert "hasPzDocId" in body or "wfirma_pz_doc_id" in body, (
        "reserved state must derive from existing wfirma_pz_doc_id"
    )


# ── Read-only discipline ──────────────────────────────────────────────────

def test_lifecycle_badge_has_no_button():
    """The badge block must be purely read-only — no <Btn>, no
    <button>, no onClick handler on the badge container."""
    src = _src()
    idx = src.find('data-testid="warehouse-inventory-lifecycle-badge"')
    end = src.find("📦 Warehouse Audit", idx)
    assert idx != -1 and end != -1 and end > idx
    block = src[idx:end]
    assert "<Btn"     not in block, "lifecycle badge block must not contain a Btn"
    assert "<button"  not in block, "lifecycle badge block must not contain a button"
    assert "onClick"  not in block, "lifecycle badge block must not bind onClick"


def test_lifecycle_badge_has_no_form_or_input():
    """No form inputs allowed inside the badge block."""
    src = _src()
    idx = src.find('data-testid="warehouse-inventory-lifecycle-badge"')
    end = src.find("📦 Warehouse Audit", idx)
    block = src[idx:end]
    for forbidden in ("<input", "<form", "<select", "<textarea"):
        assert forbidden not in block, (
            f"lifecycle badge block must not contain {forbidden!r}"
        )


def test_lifecycle_badge_does_not_call_apiFetch():
    """The badge does not perform any API calls of its own."""
    src = _src()
    idx = src.find('data-testid="warehouse-inventory-lifecycle-badge"')
    end = src.find("📦 Warehouse Audit", idx)
    block = src[idx:end]
    assert "apiFetch" not in block
    assert "fetch("   not in block


def test_lifecycle_badge_carries_derivation_disclaimer():
    """Operator must see that the badge is derived (not a manual
    override) — disclaimer copy must be present near the badge."""
    src = _src()
    idx = src.find('data-testid="warehouse-inventory-lifecycle-badge"')
    end = src.find("📦 Warehouse Audit", idx)
    block = src[idx:end]
    assert "no manual control" in block.lower(), (
        "badge must disclose that it is derived / read-only"
    )


# ── Scope discipline — DHL Express only, no multi-carrier leakage ────────

@pytest.mark.parametrize(
    "forbidden",
    ["FedEx IP", "FedEx Priority", "UPS Worldwide", "Estrella Atlas"],
)
def test_lifecycle_badge_block_no_out_of_scope_carriers(forbidden):
    src = _src()
    idx = src.find('data-testid="warehouse-inventory-lifecycle-badge"')
    end = src.find("📦 Warehouse Audit", idx)
    block = src[idx:end]
    assert forbidden not in block, (
        f"out-of-scope carrier copy {forbidden!r} leaked into "
        "lifecycle badge block"
    )


# ── Hard preservation invariants — warehouse tab logic untouched ─────────

@pytest.mark.parametrize(
    "preserved",
    [
        '📦 Warehouse Audit',
        'data-testid="readiness-banner-warehouse"',
        "loadWarehouseAudit",
        "warehouseAudit",
        # Completion summary card field labels (must keep rendering):
        "Total:",
        "Scanned:",
        "Dispatched:",
        "Missing:",
        "Completion:",
    ],
)
def test_warehouse_tab_landmarks_preserved(preserved):
    src = _src()
    assert preserved in src, (
        f"warehouse-tab landmark {preserved!r} no longer present"
    )


# ── Brace balance / file sanity ───────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
