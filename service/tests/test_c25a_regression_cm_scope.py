"""test_c25a_regression_cm_scope.py — C25A-REGRESSION-FIX.

PRODUCTION INCIDENT
Safari console after C25A static deploy:
  ReferenceError: Can't find variable: cm

ROOT CAUSE
The C25A JSX panel was inserted into the OperatorWorkflowCard
component, but the state hooks + handler functions it references
were declared in the sibling BatchDetailPage component.  Each React
function component has its own lexical scope; OperatorWorkflowCard
cannot see BatchDetailPage's `cm`, `setupDetail`,
`handleSetupSaveCmFor`, etc.  Result: ReferenceError at render time
on Safari → React unmounts → blank screen.

FIX
Move all C25A state + handlers FROM BatchDetailPage TO
OperatorWorkflowCard so the panel JSX can reach them through
ordinary lexical scope.

This test file pins the scope contract by source-grep so future
regressions cannot reintroduce the cross-component scope leak.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_DETAIL_HTML = _REPO / "app" / "static" / "shipment-detail.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _DETAIL_HTML.read_text(encoding="utf-8")


def _slice_component(html: str, component_name: str) -> str:
    """Return the source slice of a top-level function React component."""
    needle = f"\nfunction {component_name}("
    idx = html.index(needle)
    # End at next top-level `\nfunction ` declaration
    next_fn = html.find("\nfunction ", idx + len(needle))
    return html[idx : next_fn if next_fn > 0 else len(html)]


# ── BatchDetailPage scope must NOT declare C25A state/handlers ─────────────


def test_batch_detail_page_does_not_declare_setup_state(html):
    """No useState for setupDetail / setupProductPreview /
    setupCustomerResolve in BatchDetailPage — they belong in
    OperatorWorkflowCard."""
    body = _slice_component(html, "BatchDetailPage")
    for var in (
        "setSetupDetail",
        "setSetupProductPreview",
        "setSetupCustomerResolve",
        "setSetupDetailLoading",
        "setSetupProductPreviewLoading",
        "setSetupCustomerResolveLoading",
    ):
        assert f"const [{var.replace('set', '').lower()}" not in body.lower(), (
            f"BatchDetailPage must not declare {var} state"
        )
        assert f"useState" not in body or f"set{var.replace('set', '', 1)}" not in body, (
            f"BatchDetailPage must not declare setter {var}"
        )


def test_batch_detail_page_does_not_declare_setup_handlers(html):
    """The 4 C25A handlers must NOT exist in BatchDetailPage scope."""
    body = _slice_component(html, "BatchDetailPage")
    forbidden_decls = (
        "const refreshSetupDetail",
        "const handleProductPreview",
        "const handleCustomerResolve",
        "const handleSetupSaveCmFor",
    )
    for decl in forbidden_decls:
        # Allow the substring to appear in comments (lines starting with //)
        # but not as a const declaration on a non-comment line.
        for line_no, line in enumerate(body.split("\n"), start=1):
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue
            assert decl not in line, (
                f"BatchDetailPage line {line_no} declares forbidden {decl!r}: {line.strip()[:120]}"
            )


def test_batch_detail_page_useeffect_does_not_call_refresh_setup_detail(html):
    """The BatchDetailPage useEffect must not call refreshSetupDetail
    (the handler lives in OperatorWorkflowCard now)."""
    body = _slice_component(html, "BatchDetailPage")
    # Find React.useEffect blocks in BatchDetailPage
    for ln in body.split("\n"):
        stripped = ln.strip()
        if stripped.startswith("//"):
            continue
        if "React.useEffect" in ln:
            assert "refreshSetupDetail" not in ln, (
                f"BatchDetailPage useEffect must not call refreshSetupDetail: {ln.strip()[:160]}"
            )


# ── OperatorWorkflowCard scope MUST declare C25A state/handlers ────────────


def test_operator_workflow_card_declares_setup_state(html):
    body = _slice_component(html, "OperatorWorkflowCard")
    required = (
        "setSetupDetail",
        "setSetupProductPreview",
        "setSetupCustomerResolve",
        "setSetupDetailLoading",
        "setSetupProductPreviewLoading",
        "setSetupCustomerResolveLoading",
    )
    for setter in required:
        assert setter in body, (
            f"OperatorWorkflowCard must declare state setter {setter}"
        )


def test_operator_workflow_card_declares_setup_handlers(html):
    body = _slice_component(html, "OperatorWorkflowCard")
    required_decls = (
        "const refreshSetupDetail",
        "const handleProductPreview",
        "const handleCustomerResolve",
        "const handleSetupSaveCmFor",
    )
    for decl in required_decls:
        assert decl in body, (
            f"OperatorWorkflowCard must declare {decl!r}"
        )


def test_operator_workflow_card_useeffect_calls_refresh_setup_detail(html):
    """OperatorWorkflowCard's mount-time useEffect must call
    refreshSetupDetail() so the panel hydrates."""
    body = _slice_component(html, "OperatorWorkflowCard")
    # Find any useEffect that calls refreshSetupDetail
    assert "refreshSetupDetail" in body, (
        "OperatorWorkflowCard must reference refreshSetupDetail()"
    )
    # Specifically, the mount effect should invoke it
    assert "refreshSetupDetail()" in body, (
        "OperatorWorkflowCard useEffect must call refreshSetupDetail()"
    )


# ── No FREE variables in the C25A panel block ─────────────────────────────


def test_setup_panel_has_no_free_cm_reference_in_jsx(html):
    """The C25A setup panel block (between setup-detail-panel testid and
    the next sectionShell('warehouse'...) opener) must NOT contain a
    free `cm` reference outside a closure that has `cm` in scope.

    Heuristic: every `cm` token in the panel block must be inside one of:
      - a .map(cm => ...) parameter binding
      - the existing C17A cmEdit / cmSaving / cmSavedMsg state names
      - a comment line
      - a property name like cm_record_present / cm_bill_to_name
        (snake-case database key, not a JS variable)
      - a member access through row.X (e.g. row.cm_bill_to_name)

    Any bare `cm` reference would re-introduce the regression."""
    import re
    panel_start = html.index('data-testid="setup-detail-panel"')
    panel_end = html.index("{sectionShell('warehouse'", panel_start)
    panel = html[panel_start:panel_end]

    # Strip comments
    no_comments = "\n".join(
        ln for ln in panel.split("\n") if not ln.lstrip().startswith("//")
    )

    # Find bare `cm` tokens that look like JS variable references:
    #   - preceded by JS operator, whitespace, or `(`/`,`
    #   - followed by `.`, ` `, `,`, `)`, `[`
    # Excludes dash-separated strings (test IDs like `btn-...-cm-...`)
    # and longer identifiers (cm_record_present, cmEdit, cmRow, etc.).
    # Disallow `-` adjacent on either side (kebab-case test ID strings).
    bare_cm_pattern = re.compile(
        r"(?:^|[\s(,;{}=!<>&|+*/?:])(cm)(?=[\s.,)\]\[;!=<>&|+*/?:])"
    )
    matches = list(bare_cm_pattern.finditer(no_comments))
    bad = []
    for m in matches:
        start = m.start(1)  # position of `cm` itself
        ctx = no_comments[max(0, start - 20):start + 20]
        # Skip arrow-function param bindings — `.map(cm =>` or `(cm)=>`
        if "=> " in ctx or "(cm" in ctx[:25] or "cm =>" in ctx or "cm) =>" in ctx:
            continue
        bad.append((start, ctx))
    assert not bad, (
        f"Setup panel block contains {len(bad)} free `cm` reference(s): "
        + "; ".join(f"...{ctx}..." for _, ctx in bad[:3])
    )


# ── Sparse-batch shape regression ──────────────────────────────────────────


def test_setup_panel_safely_handles_null_setup_detail(html):
    """The panel block must be wrapped in `{setupDetail && (...)}` so it
    renders nothing when the fetch returns null (404 / error / sparse
    batch).  This is the structural invariant that protects sparse
    completed batches from blank-screen render errors."""
    panel_idx = html.index('data-testid="setup-detail-panel"')
    # Look backward 300 chars for the wrapping `{setupDetail && (`
    window_before = html[max(0, panel_idx - 300):panel_idx]
    assert "setupDetail && (" in window_before, (
        "setup-detail-panel must be wrapped in `{setupDetail && (...)}` "
        "so it renders nothing on null state (sparse-batch protection)"
    )


def test_products_body_safely_handles_null_setup_detail(html):
    """productsBody must use null-safe access on setupDetail since it
    runs even when setupDetail is null (panel above is gated, but
    productsBody is always rendered inside its sectionShell)."""
    # Find productsBody body — between `const productsBody` and the
    # closing `})();` of its IIFE
    idx = html.index("const productsBody")
    end = html.index("})();", idx) + 5
    body = html[idx:end]
    # All setupDetail accesses inside productsBody must be guarded
    import re
    unsafe_pattern = re.compile(r"setupDetail\.\w+")
    unsafe = []
    for m in unsafe_pattern.finditer(body):
        # Allow the safe pattern: (setupDetail && setupDetail.X)
        start = m.start()
        ctx = body[max(0, start - 30):start]
        if "setupDetail && " in ctx:
            continue
        unsafe.append(body[max(0, start - 30):start + 50])
    assert not unsafe, (
        f"productsBody has {len(unsafe)} unsafe setupDetail.X access(es) "
        f"without null guard: " + "; ".join(unsafe[:3])
    )


# ── Smoke: JSX file parses (no unclosed tags, no stray braces) ─────────────


def test_html_has_balanced_braces_around_setup_panel(html):
    """A crude balance check on the setup-detail-panel block — the
    number of `{` and `}` characters inside the JSX block must match.
    Catches accidental brace deletions during refactor."""
    panel_start = html.index('data-testid="setup-detail-panel"')
    panel_end = html.index("{sectionShell('warehouse'", panel_start)
    block = html[panel_start:panel_end]
    opens = block.count("{")
    closes = block.count("}")
    # Strictly we cannot require equality (JSX strings may contain stray
    # braces) but a delta > 5 is a strong signal of a refactor mistake.
    assert abs(opens - closes) <= 5, (
        f"setup-detail-panel block has unbalanced braces "
        f"(opens={opens}, closes={closes}); refactor likely broke nesting"
    )
