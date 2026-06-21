"""
test_v2_proforma_list_retry_btn.py — frontend-design compliance for the
Pro Forma List (Atlas V2 shell) drafts load-error Retry control.

Flagged during the PR #697 frontend-flow review as a pre-existing bare
`<button>` (out of scope for that PR). Per .claude/skills/frontend-design.md
§4 (shared components) + §8 (every interactive control carries a data-testid),
the Retry control in the drafts load-error block must use the shared `Btn`
component (defined in v2/components.jsx, forwards data-testid via ...rest) and
carry a stable data-testid — not a bare, untestable `<button>`.

Static-contract (source-grep; no server required):

  1. The drafts load-error Retry control uses the shared `Btn` component.
  2. It carries data-testid="btn-proforma-list-retry".
  3. No bare `<button>...Retry...</button>` remains in the file.
  4. The reload action is preserved (onClick={draftsHook.reload}).
  5. V1 frozen pages are untouched (Lesson F).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_LIST = _V2 / "proforma-list.jsx"


@pytest.fixture(scope="module")
def list_src() -> str:
    return _LIST.read_text(encoding="utf-8")


# ── §4: the Retry control uses the shared Btn component ──────────────────────

def test_retry_uses_shared_btn(list_src):
    assert ">Retry</Btn>" in list_src, \
        "drafts load-error Retry control must render via the shared <Btn> component"


def test_no_bare_retry_button(list_src):
    # the pre-existing bare <button ...>Retry</button> must be gone — a bare
    # button bypasses the shared component contract and is untestable.
    assert ">Retry</button>" not in list_src, \
        "bare <button>Retry</button> must be replaced by the shared <Btn> component"


# ── §8: stable data-testid on the interactive control ────────────────────────

def test_retry_has_testid(list_src):
    assert 'data-testid="btn-proforma-list-retry"' in list_src, \
        "Retry control must carry a stable data-testid for verification"


# ── the reload action is preserved (no behavioural regression) ───────────────

def test_retry_preserves_reload_action(list_src):
    # the testid'd Btn must wire onClick to the drafts reload (one element)
    assert "onClick={draftsHook.reload}" in list_src
    idx = list_src.index('data-testid="btn-proforma-list-retry"')
    region = list_src[idx - 80: idx + 120]
    assert "onClick={draftsHook.reload}" in region, \
        "the Retry Btn must reload the drafts hook"


# ── Lesson F: V1 frozen pages are not touched by this cleanup ─────────────────

def test_v1_pages_untouched():
    for v1 in ("dashboard.html", "shipment-detail.html"):
        p = _V2.parent / v1
        if p.is_file():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            assert "btn-proforma-list-retry" not in txt
