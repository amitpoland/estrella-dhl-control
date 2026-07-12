"""
test_v2_no_spread_rest.py — V2-wide spread-rest collision guard.

PROJECT_STATE DECISIONS "V2-wide spread-rest collision sweep" (2026-07-03):
Babel-standalone compiles JSX object-REST destructuring
(`function C({ a, ...rest })`) by hoisting `var _excluded = [...]` to the
transformed script's top level. V2 loads each *.jsx as an un-wrapped classic
<script>, so those `_excluded` vars collide in global scope and the
last-loaded file wins — leaking excluded props (onChange) into `{...rest}`
and crashing the tree on first keystroke (the B2 render-check defect; the
collider was TbBtn in proforma-detail.jsx).

RULE (pinned here, drop-can't-return): spread-rest destructuring is
FORBIDDEN in V2 JSX. A future PR reintroducing `...rest`/`...props` in a
destructuring pattern fails this pin.

NB: object-LITERAL spreads (`{ ...prev }`, inline `...style`) are SAFE
(they compile to idempotent _extends, no `_excluded`) and are NOT flagged —
the pattern below matches only rest inside a destructuring `{ … }` that
closes a function/arrow parameter list.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"

# Rest element that terminates a destructuring PARAM LIST: `...name })` where the
# `)` closes the params and is itself followed by an arrow `=>` or a function
# body `{`. That param-list rest is exactly what emits a hoisted `_excluded`.
#
# Why the trailing `\)\s*(?:=>|\{)` matters: the earlier `\}\s*(?:\)|=>)` form
# also matched object-LITERAL spreads whose `}` closes an object that is the last
# thing inside a call/return paren — e.g. `prev => ({ ...prev, ...payload })` or
# `dispatch({ ...payload })`. Those are safe idempotent `_extends` spreads (no
# `_excluded`), yet `...payload })` tripped the guard (false positive on
# proforma-detail.jsx). A real destructuring-rest param is ALWAYS followed by
# `) =>` (arrow) or `) {` (function body); an object literal used as a value is
# not. Anchoring on that suffix flags only the dangerous form.
_REST_DESTRUCTURE = re.compile(r"\.\.\.[A-Za-z_$][\w$]*\s*\}\s*\)\s*(?:=>|\{)")


def _jsx_files():
    return sorted(_V2.glob("*.jsx"))


def test_v2_files_exist():
    assert _jsx_files(), "no v2 JSX files found — path wrong?"


@pytest.mark.parametrize("path", _jsx_files(), ids=lambda p: p.name)
def test_no_spread_rest_destructure_in_v2_file(path):
    src = path.read_text(encoding="utf-8", errors="replace")
    # Strip line comments so the DECISIONS citations mentioning `...rest`
    # don't trip the guard.
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("//")
    )
    hits = _REST_DESTRUCTURE.findall(code)
    assert not hits, (
        f"{path.name} contains spread-rest destructuring {hits} — FORBIDDEN "
        f"in V2 JSX (Babel _excluded global-hoist collision; PROJECT_STATE "
        f"DECISIONS 'V2-wide spread-rest collision sweep'). Use explicit "
        f"named destructuring of the forwarded attrs instead."
    )


def test_index_html_inline_jsx_has_no_spread_rest():
    src = (_V2 / "index.html").read_text(encoding="utf-8", errors="replace")
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("//")
    )
    assert not _REST_DESTRUCTURE.findall(code), \
        "index.html inline JSX contains spread-rest destructuring (forbidden)"


def test_swept_components_kept_their_testid_forwarding():
    """The fix must preserve data-testid forwarding on the swept shared
    primitives (explicit destructuring, not dropped)."""
    comp = (_V2 / "components.jsx").read_text(encoding="utf-8", errors="replace")
    for sig_marker in ("function Card(", "function Btn(", "function Input("):
        k = comp.index(sig_marker)
        head = comp[k:k + 260]
        assert "'data-testid': testid" in head, \
            f"{sig_marker} must destructure data-testid explicitly after the sweep"
    # Btn also forwards title + aria-label per the census
    kb = comp.index("function Btn(")
    assert "title" in comp[kb:kb + 260] and "'aria-label': ariaLabel" in comp[kb:kb + 260]
    # TbBtn (the collider) swept in proforma-detail.jsx
    pd = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8", errors="replace")
    kt = pd.index("function TbBtn(")
    assert "'data-testid': testid" in pd[kt:kt + 200]
    assert "...rest" not in pd[kt:kt + 400]
