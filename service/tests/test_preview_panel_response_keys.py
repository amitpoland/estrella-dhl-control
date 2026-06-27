"""test_preview_panel_response_keys.py

The "Product preview result" panel in shipment-detail.html must read the CURRENT
auto-register-preview response shape:
    scanned, existing_mapped, pending_adoption, missing (int), created,
    blocked, failed, errors[], results[]

Previously it read mirrored_count / matched_count / missing_count / missing[]
— none of which the endpoint returns — so mapped/missing always rendered "—".

These are source-level assertions (shipment-detail.html is in-browser Babel
JSX; no DOM test runner), matching the existing C25A frontend test style.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_DETAIL_HTML = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"


@pytest.fixture(scope="module")
def panel() -> str:
    """The Product preview result panel block."""
    html = _DETAIL_HTML.read_text(encoding="utf-8")
    start = html.index('data-testid="setup-product-preview-result"')
    # Panel ends at the next sibling panel (pending adoption).
    end = html.index('data-testid="pending-adoption-panel"', start)
    return html[start:end]


def test_panel_reads_current_response_keys(panel):
    for key in ("existing_mapped", "pending_adoption", "p.missing",
                "p.created", "p.blocked", "p.failed", "p.errors", "p.results"):
        assert key in panel, f"preview panel must read response key {key!r}"


def test_existing_and_pending_shown_as_separate_rows(panel):
    # existing_mapped (done) and pending_adoption (needs Adopt) drive different
    # actions, so they must be distinct rows — not folded into one "mapped".
    assert 'data-testid="preview-existing-mapped"' in panel
    assert 'data-testid="preview-pending"' in panel
    assert "p.existing_mapped != null" in panel


def test_missing_handles_integer(panel):
    # missing is an int in the current response — must be read as a number,
    # not only as an array length.
    assert "typeof p.missing === 'number'" in panel


def test_failed_and_errors_and_buckets_surfaced(panel):
    assert 'data-testid="preview-failed"' in panel
    assert 'data-testid="preview-errors"' in panel
    assert 'data-testid="preview-result-buckets"' in panel
    # per-code buckets derived from results[]
    assert "buckets[s]" in panel


def test_numeric_testids_present(panel):
    for tid in ("preview-scanned", "preview-existing-mapped", "preview-pending",
                "preview-missing", "preview-created", "preview-blocked"):
        assert f'data-testid="{tid}"' in panel, f"missing data-testid {tid}"


def test_legacy_keys_kept_only_as_fallback(panel):
    # Legacy keys may remain as fallbacks, but the primary path must be the
    # current keys: existing_mapped must appear BEFORE any mirrored_count use.
    assert "existing_mapped" in panel
    if "mirrored_count" in panel:
        assert panel.index("existing_mapped") < panel.index("mirrored_count"), (
            "current keys must be the primary read; mirrored_count only a fallback"
        )
