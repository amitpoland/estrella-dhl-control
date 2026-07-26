"""
test_v2_components_rest_prop_forwarding.py — Source-grep tests pinning that
shared V2 primitives in components.jsx forward the DOM passthrough attrs
(data-testid, title, aria-label) to their underlying DOM elements.

Workflow class (Lesson I): shared V2 primitives that destructure a fixed prop
list silently swallow extra attributes. Confirmed production impact
2026-06-10: client-detail.jsx passed data-testid="cd-save" /
"cd-confirm-save" to Btn and neither attribute reached the DOM, breaking
browser-verification selectors and the frontend-design rule "Every interactive
element needs a data-testid". master-page.jsx additionally lost the Lesson M
disabled-reason `title` tooltips on Btn, plus data-testid on Input
("master-search") and Card ("error-state" / "loading-state").

MECHANISM CHANGE 2026-07-03 (PROJECT_STATE DECISIONS "V2-wide spread-rest
collision sweep"): the original fix used `...rest` + `{...rest}`, but
Babel-standalone hoists the compiled `_excluded` prop-list to GLOBAL scope
and a later-loaded V2 script overwrites it — leaking excluded props
(onChange) into the spread and crashing typing (the B2 render-check defect;
collider = TbBtn in proforma-detail.jsx). Spread-rest is now FORBIDDEN in V2
JSX (guarded by test_v2_no_spread_rest.py). The Lesson-I CONTRACT is
unchanged — the passthrough attrs still reach the DOM — only the mechanism
is now EXPLICIT named destructuring (census-complete):
  - Btn destructures 'data-testid'/title/'aria-label' and applies each on
    <button>; Card and Input destructure 'data-testid' and apply it.
  - style stays authoritative (computed style object last / destructured out).

Target: service/app/static/v2/components.jsx
"""
from __future__ import annotations

import pathlib
import re

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
V2_DIR = SERVICE_DIR / "app" / "static" / "v2"
COMPONENTS = V2_DIR / "components.jsx"


def _read() -> str:
    return COMPONENTS.read_text(encoding="utf-8")


def _strip_comments(block: str) -> str:
    """Drop // comment lines — a following function's leading comment can
    bleed into this block and legitimately mention `...rest` (DECISIONS
    citations), which must not trip the no-spread-rest asserts."""
    return "\n".join(l for l in block.splitlines() if not l.lstrip().startswith("//"))


def _function_block(src: str, name: str) -> str:
    """Return the source of `function <name>(...) { ... }` up to the next
    top-level `function` declaration (good enough for source-grep pinning)."""
    m = re.search(rf"^function {name}\(", src, flags=re.MULTILINE)
    assert m, f"function {name}( must exist in components.jsx"
    tail = src[m.start():]
    nxt = re.search(r"^function \w+\(", tail[1:], flags=re.MULTILINE)
    return tail[: nxt.start() + 1] if nxt else tail


# =============================================================================
# 1. Btn forwards rest props to <button>
# =============================================================================

class TestBtnForwardsRestProps:
    def test_btn_no_spread_rest(self):
        block = _function_block(_read(), "Btn")
        assert "...rest" not in _strip_comments(block), \
            "Btn must NOT use spread-rest (Babel _excluded global collision)"

    def test_btn_destructures_passthrough_attrs(self):
        block = _function_block(_read(), "Btn")
        head = block[:block.index("{", block.index("("))] if "{" in block else block
        sig = block.split(")", 1)[0]
        assert "'data-testid': testid" in sig, "Btn must destructure data-testid"
        assert "title" in sig, "Btn must destructure title"
        assert "'aria-label': ariaLabel" in sig, "Btn must destructure aria-label"

    def test_btn_applies_passthrough_on_button_before_style(self):
        block = _function_block(_read(), "Btn")
        btn_tag = block[block.index("<button"):]
        for attr in ("data-testid={testid}", "title={title}", "aria-label={ariaLabel}"):
            assert attr in btn_tag, f"Btn must apply {attr} on <button>"
            assert btn_tag.index(attr) < btn_tag.index("style="), \
                f"{attr} must precede style= so computed style stays last"


# =============================================================================
# 2. Card forwards rest props to its root <div>
# =============================================================================

class TestCardForwardsRestProps:
    def test_card_no_spread_rest(self):
        block = _function_block(_read(), "Card")
        assert "...rest" not in _strip_comments(block), \
            "Card must NOT use spread-rest (Babel _excluded global collision)"

    def test_card_applies_testid_on_div(self):
        block = _function_block(_read(), "Card")
        assert "'data-testid': testid" in block.split(")", 1)[0], \
            "Card must destructure data-testid"
        div_tag = block[block.index("<div"):]
        assert "data-testid={testid}" in div_tag[:div_tag.index(">")], \
            "Card must apply data-testid={testid} on its root <div>"


# =============================================================================
# 3. Input forwards rest props to <input>
# =============================================================================

class TestInputForwardsRestProps:
    def test_input_no_spread_rest(self):
        block = _function_block(_read(), "Input")
        assert "...rest" not in _strip_comments(block), \
            "Input must NOT use spread-rest (Babel _excluded global collision)"

    def test_input_applies_testid_on_input(self):
        block = _function_block(_read(), "Input")
        assert "'data-testid': testid" in block.split(")", 1)[0], \
            "Input must destructure data-testid"
        input_tag = block[block.index("<input"):]
        assert "data-testid={testid}" in input_tag[:input_tag.index("/>")], \
            "Input must apply data-testid={testid} on the <input> element"


# =============================================================================
# 4. Known caller testids still present (regression canary)
# =============================================================================

class TestKnownCallerTestids:
    """The callers whose selectors vanished in production 2026-06-10.
    If these move or get renamed, browser-verification selectors break."""

    def test_client_detail_btn_testids(self):
        """cd-confirm-save / cd-confirm-cancel were dropped 2026-07-20 together
        with the confirmation dialog itself (operator ruling: V1 saves
        immediately; a Customer Master edit is not an irreversible financial
        operation). The remaining three selectors still guard the 2026-06-10
        regression. The forwarding mechanism itself stays covered by
        TestBtn / TestInput above."""
        src = (SERVICE_DIR / "app" / "static" / "v2" / "client-detail.jsx").read_text(encoding="utf-8")
        for tid in ("cd-save", "cd-cancel", "cd-close"):
            assert f'data-testid="{tid}"' in src, \
                f"client-detail.jsx must keep data-testid=\"{tid}\""
        assert "cd-confirm-dialog" not in src, \
            "the Save confirmation dialog must stay removed (V1 parity)"

    def test_master_page_input_and_card_testids(self):
        src = (SERVICE_DIR / "app" / "static" / "v2" / "master-page.jsx").read_text(encoding="utf-8")
        for tid in ("master-search", "error-state", "loading-state"):
            assert f'data-testid="{tid}"' in src, \
                f"master-page.jsx must keep data-testid=\"{tid}\""


# =============================================================================
# 5. Btn variants map — `primary` declared, and every used literal resolves
# =============================================================================

def _btn_variant_keys() -> set:
    """Keys declared in the `const variants = {...}` map inside Btn."""
    block = _function_block(_read(), "Btn")
    m = re.search(r"const variants = \{(.*?)\n\s*\};", block, flags=re.DOTALL)
    assert m, "Btn must declare a `const variants = {...}` map"
    return set(re.findall(r"^\s*(\w+):\s*\{", m.group(1), flags=re.MULTILINE))


class TestBtnVariantCoverage:
    """C20A parity: the Btn in v2/dashboard-shared.js gained a `primary`
    variant (alias for gold/accent — the intended CTA style) because unknown
    variants silently fall back to `default` (dark navy). The V2 shell
    (v2/index.html) loads components.jsx ONLY — dashboard-shared.js is
    intentionally excluded — so the same key must exist here or every
    variant="primary" CTA (e.g. proforma-detail.jsx send-proforma submit)
    renders unstyled."""

    def test_primary_variant_declared(self):
        assert "primary" in _btn_variant_keys(), \
            "Btn variants map must declare `primary` (C20A parity with dashboard-shared.js)"

    def test_primary_uses_accent_tokens(self):
        block = _function_block(_read(), "Btn")
        m = re.search(r"primary:\s*\{([^}]*)\}", block)
        assert m, "primary variant must be declared inline in the variants map"
        assert "var(--accent)" in m.group(1) and "var(--accent-text)" in m.group(1), \
            "primary must render the gold/accent CTA style"

    def test_every_used_variant_literal_is_declared(self):
        """Workflow-class guard (Lesson I): an undeclared variant string in any
        V2 page falls back to `default` with no error or console warning.
        Every variant=\"x\" literal in v2/*.jsx must be a declared Btn key."""
        keys = _btn_variant_keys()
        undeclared = {}
        for page in sorted(V2_DIR.glob("*.jsx")):
            src = page.read_text(encoding="utf-8")
            for m in re.finditer(r"variant=[\"'](\w+)[\"']", src):
                if m.group(1) not in keys:
                    undeclared.setdefault(m.group(1), set()).add(page.name)
        assert not undeclared, (
            "variant literals used in v2/*.jsx but not declared in the "
            f"components.jsx Btn variants map (silent navy fallback): {undeclared}"
        )
