"""Insurance Export — Declaration PDF composer UX contract pins (Slice 2).

Frontend convention here is source-grep against the JSX (there is no JS test
runner in this repo).

Pins:
  • The composer renders through the ONE canonical Modal primitive — no second
    modal/drawer framework, no hand-rolled fixed-position panel.
  • The action row (Cancel + Download PDF) is the Modal footer, so it never
    scrolls out of reach however long the body gets.
  • The canonical Modal keeps its previous rendering when no footer is given.
  • Selection summary is counts + the server preview total only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
JSX = APP / "static" / "v2" / "insurance-export-tab.jsx"
COMPONENTS = APP / "static" / "v2" / "components.jsx"


@pytest.fixture(scope="module")
def jsx() -> str:
    return JSX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def components() -> str:
    return COMPONENTS.read_text(encoding="utf-8")


def _composer(jsx: str) -> str:
    return jsx.split("{drawerOpen && (", 1)[1]


def test_composer_uses_the_canonical_modal(jsx):
    body = _composer(jsx)
    assert "<Modal" in body
    assert 'data-testid="ins-export-drawer"' in body


def test_no_second_modal_framework(jsx):
    """No hand-rolled fixed overlay/panel anywhere in the tab."""
    code = "\n".join(
        ln for ln in jsx.splitlines() if not ln.strip().startswith("//")
    )
    assert "position: 'fixed'" not in code
    assert "zIndex" not in code


def test_actions_live_in_the_modal_footer(jsx):
    footer = _composer(jsx).split("footer={", 1)[1].split("}\n        >", 1)[0]
    assert 'data-testid="ins-export-download"' in footer
    assert 'data-testid="ins-export-drawer-close"' in footer
    assert "Download PDF" in footer
    assert "Cancel" in footer


def test_download_still_blocked_without_a_selection(jsx):
    footer = _composer(jsx).split("footer={", 1)[1].split("}\n        >", 1)[0]
    assert "disabled={downloading || selectedCount === 0}" in footer


def test_output_options_preserved(jsx):
    for testid in (
        "ins-export-opt-documents",
        "ins-export-opt-adjustments",
        "ins-export-opt-recovered",
        "ins-export-download-error",
    ):
        assert 'data-testid="%s"' % testid in jsx, testid


def test_selection_summary_is_counts_and_server_total(jsx):
    summary = _composer(jsx).split('data-testid="ins-export-drawer-selection"', 1)[1]
    summary = summary.split("Output options", 1)[0]
    assert "{selectedCount}" in summary
    assert "reportRowCount - selectedCount" in summary
    # The money figure comes from the declaration-preview response, never math.
    assert "declarationTotal" in summary
    assert not re.search(r"declarationTotal\s*[*+/-]", summary)


def test_modal_footer_body_scrolls_and_actions_stay_put(components):
    modal = components.split("function Modal(", 1)[1].split("\nfunction ", 1)[0]
    assert "footer" in modal.split(")", 1)[0]  # accepted as a prop
    # Body scrolls, header and footer do not.
    assert "overflowY: 'auto', flex: 1, minHeight: 0" in modal
    assert modal.count("flexShrink: 0") == 2
    # Backdrop + viewport containment are unchanged canonical behaviour.
    assert "position: 'fixed', inset: 0" in modal
    assert "maxWidth: '100%'" in modal
    assert "maxHeight: '90vh'" in modal


def test_modal_without_footer_renders_as_before(components):
    modal = components.split("function Modal(", 1)[1].split("\nfunction ", 1)[0]
    assert "overflow: footer ? 'hidden' : 'auto'" in modal
    assert "display: footer ? 'flex' : 'block'" in modal
    assert "{ padding: 24 }" in modal
    assert "footer ? (" in modal
