"""
test_v2_components_rest_prop_forwarding.py — Source-grep tests pinning that
shared V2 primitives in components.jsx forward rest props (data-testid, title,
aria-*) to their underlying DOM elements.

Workflow class (Lesson I): shared V2 primitives that destructure a fixed prop
list silently swallow every extra attribute. Confirmed production impact
2026-06-10: client-detail.jsx passed data-testid="cd-save" /
"cd-confirm-save" to Btn and neither attribute reached the DOM, breaking
browser-verification selectors and the frontend-design rule "Every interactive
element needs a data-testid". master-page.jsx additionally lost the Lesson M
disabled-reason `title` tooltips on Btn, plus data-testid on Input
("master-search") and Card ("error-state" / "loading-state").

Contract pinned here (mirrors the Btn in v2/dashboard-shared.js):
  - Btn, Card and Input accept `...rest` in their parameter destructuring
  - each spreads `{...rest}` onto its root DOM element
  - the spread sits BEFORE the style prop so the computed style object stays
    authoritative (style itself is destructured out and can never be in rest)

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
    def test_btn_accepts_rest(self):
        block = _function_block(_read(), "Btn")
        assert "...rest" in block.split("{", 2)[1], \
            "Btn must accept ...rest in its destructured props"

    def test_btn_spreads_rest_on_button(self):
        block = _function_block(_read(), "Btn")
        m = re.search(r"<button[^>]*\{\.\.\.rest\}", block, flags=re.DOTALL)
        assert m, "Btn must spread {...rest} onto the <button> element"

    def test_btn_spread_before_style(self):
        """{...rest} must come before style= so computed style stays last."""
        block = _function_block(_read(), "Btn")
        btn_tag = block[block.index("<button"):]
        assert btn_tag.index("{...rest}") < btn_tag.index("style="), \
            "Btn must spread {...rest} before the style prop"


# =============================================================================
# 2. Card forwards rest props to its root <div>
# =============================================================================

class TestCardForwardsRestProps:
    def test_card_accepts_rest(self):
        block = _function_block(_read(), "Card")
        assert "...rest" in block.split("{", 2)[1], \
            "Card must accept ...rest in its destructured props"

    def test_card_spreads_rest(self):
        block = _function_block(_read(), "Card")
        m = re.search(r"<div[^>]*\{\.\.\.rest\}", block, flags=re.DOTALL)
        assert m, "Card must spread {...rest} onto its root <div>"


# =============================================================================
# 3. Input forwards rest props to <input>
# =============================================================================

class TestInputForwardsRestProps:
    def test_input_accepts_rest(self):
        block = _function_block(_read(), "Input")
        assert "...rest" in block.split("{", 2)[1], \
            "Input must accept ...rest in its destructured props"

    def test_input_spreads_rest(self):
        block = _function_block(_read(), "Input")
        m = re.search(r"<input[^>]*\{\.\.\.rest\}", block, flags=re.DOTALL)
        assert m, "Input must spread {...rest} onto the <input> element"


# =============================================================================
# 4. Known caller testids still present (regression canary)
# =============================================================================

class TestKnownCallerTestids:
    """The callers whose selectors vanished in production 2026-06-10.
    If these move or get renamed, browser-verification selectors break."""

    def test_client_detail_btn_testids(self):
        src = (SERVICE_DIR / "app" / "static" / "v2" / "client-detail.jsx").read_text(encoding="utf-8")
        for tid in ("cd-save", "cd-confirm-save", "cd-confirm-cancel", "cd-cancel", "cd-close"):
            assert f'data-testid="{tid}"' in src, \
                f"client-detail.jsx must keep data-testid=\"{tid}\" on its Btn"

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
