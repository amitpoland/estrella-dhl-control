"""
test_proforma_wireframe_primitives.py — Proforma wireframe rebuild Slice 2.

Source-grep pins for the Pf* visual primitives added to proforma-detail.jsx
(wireframe rebuild Slice 2). The primitives are PASSIVE display widgets ported
1:1 from the operator-approved wireframe; this pin asserts they exist, follow
the V2 governance rules (explicit destructuring, CSS custom properties only),
and that Slice 2 changed no behavior surface (toolbar testids, modals, tabs).

Coverage:
  1. test_pf_primitives_defined            — all Pf* components present
  2. test_pf_status_chip_uses_live_states  — PF_STATUS_CHIP keyed by live draft_state values
  3. test_pf_primitives_no_rest_destructure— no spread-rest in the new components
  4. test_pf_primitives_css_vars_only      — no hardcoded hex colors in the new block
  5. test_slice2_behavior_surface_unchanged— pinned toolbar testids + modals intact
"""
from __future__ import annotations

import re
from pathlib import Path

JSX = (Path(__file__).resolve().parent.parent
       / "app" / "static" / "v2" / "proforma-detail.jsx")

PF_COMPONENTS = (
    "function PfSectionLabel(",
    "function PfPanelCard(",
    "function PfStatTile(",
    "function PfProformaStatusChip(",
    "function PfFieldRow(",
    "function PfTextEdit(",
    "function PfSelectEdit(",
    "function PfEditField(",
    "function PfAutocomplete(",
    "const PF_STATUS_CHIP = {",
)

# Live proforma_drafts.draft_state values the chip must map (lifecycle
# display only — readiness stays with the ProformaStatusHeader pill).
LIVE_STATES = ("draft", "editing", "approved", "posting", "posted",
               "issued", "post_failed", "cancelled", "superseded")

TOOLBAR_TESTIDS = (
    "tb-edit", "tb-edit-save", "tb-edit-cancel", "tb-delete", "tb-purge",
    "tb-duplicate", "tb-approve", "tb-post", "tb-convert", "tb-preview",
    "proforma-detail-download-pdf", "tb-send", "tb-generate",
    "tb-awb-generate", "tb-invoice-history", "tb-more", "tb-back",
)

MODALS = (
    "function AwbGenerateModal(",
    "function ProformaPreviewModal(",
    "function PostToWFirmaModal(",
)


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def _pf_block(src: str) -> str:
    """The contiguous source region holding the Pf* primitives.

    Boundary = the next top-level function/const that is NOT part of the
    block. Gate finding (Slice 2 → Slice 3 precondition): the original
    lookahead `(?!Pf)` was case-sensitive, so `const PF_STATUS_CHIP` (PF,
    not Pf) terminated the scan after only 3 of 10 components — the
    spread-rest and hex pins silently covered a fraction of the block.
    `PF_`-named consts (PF_STATUS_CHIP, PF_EDIT_INPUT) belong to the block
    and must not end it.
    """
    start = src.index("function PfSectionLabel(")
    m = re.search(r"\n(?:function|const) (?!Pf[A-Z]|PF_)", src[start:])
    block = src[start:start + (m.start() if m else len(src) - start)]
    # Self-check: every named component must be inside the scanned block so
    # the downstream pins can never silently under-cover again.
    missing = [c for c in PF_COMPONENTS if c not in block]
    assert not missing, f"_pf_block boundary regressed — missing: {missing}"
    return block


def test_pf_primitives_defined():
    src = _src()
    missing = [c for c in PF_COMPONENTS if c not in src]
    assert not missing, f"proforma-detail.jsx missing Slice 2 primitives: {missing}"


def test_pf_status_chip_uses_live_states():
    src = _src()
    chip = src[src.index("const PF_STATUS_CHIP"):]
    chip = chip[:chip.index("};") + 2]
    missing = [s for s in LIVE_STATES if f"{s}:" not in chip]
    assert not missing, f"PF_STATUS_CHIP missing live draft states: {missing}"


def test_pf_primitives_no_rest_destructure():
    # Same pattern as test_v2_no_spread_rest — scoped to the new block so a
    # regression in Slice 2 code fails HERE with a precise message.
    block = _pf_block(_src())
    hits = re.findall(r"\.\.\.[A-Za-z_$][\w$]*\s*\}\s*(?:\)|=>)", block)
    assert not hits, f"Pf* primitives contain spread-rest destructuring: {hits}"


def test_pf_primitives_css_vars_only():
    block = _pf_block(_src())
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", block)
    assert not hexes, f"Pf* primitives hardcode hex colors: {hexes} — use CSS vars"


def test_slice2_behavior_surface_unchanged():
    src = _src()
    for tid in TOOLBAR_TESTIDS:
        assert f'"{tid}"' in src, f"pinned toolbar data-testid {tid} missing"
    for m in MODALS:
        assert m in src, f"modal signature changed or removed: {m}"
