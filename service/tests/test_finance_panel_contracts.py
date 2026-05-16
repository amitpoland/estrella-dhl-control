"""Phase 6F.4 — read-only finance posting breakdown panel contract tests.

These contract tests pin the panel's read-only guarantees mechanically.
They run a source-grep over `service/app/static/dashboard.html` against
the `FinancePostingBreakdownPanel` component block and assert:

- The panel calls ONLY GET /api/v1/finance/postings/{id}/breakdown.
- No POST/PUT/PATCH/DELETE HTTP verbs reference any /api/v1/finance/ URL.
- No coupling-string appears inside the panel block (wfirma, proforma,
  settlement-mutation, charge-create, etc.).
- No auto-fetch on mount: there is no React.useEffect inside the panel
  that calls apiFetch.
- The single backend route file still exposes exactly one @router.get.

Hard rule: the panel must never be a write surface.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[2]
_DASHBOARD = _REPO / "service" / "app" / "static" / "dashboard.html"
_FINANCE_ROUTE = _REPO / "service" / "app" / "api" / "routes_finance_postings.py"


def _panel_block() -> str:
    """Return the exact JSX block for FinancePostingBreakdownPanel.

    The block starts at `function FinancePostingBreakdownPanel(` and
    ends at the matching close brace + closing `}` line (we accept the
    next top-level function declaration or end-of-file as terminator).
    """
    if not _DASHBOARD.exists():
        pytest.skip("dashboard.html missing")
    text = _DASHBOARD.read_text(encoding="utf-8")
    start = text.find("function FinancePostingBreakdownPanel(")
    assert start >= 0, "6F.4 panel function not found in dashboard.html"
    # Find the closing brace by scanning forward for the next top-level
    # `\nfunction ` declaration or `// ════` banner.
    after = text[start:]
    # Terminate at the next top-level function/banner or the script tag close.
    terminators = [
        "\nfunction ",
        "\n// ══",
        "\n</script>",
    ]
    end_rel = len(after)
    for term in terminators:
        # Skip the first character so we don't match our own signature.
        idx = after.find(term, 1)
        if idx >= 0 and idx < end_rel:
            end_rel = idx
    return after[:end_rel]


def test_panel_block_exists():
    block = _panel_block()
    assert "FinancePostingBreakdownPanel" in block


def test_panel_calls_only_breakdown_endpoint():
    """Every /api/v1/finance/ URL inside the panel must be the breakdown GET."""
    block = _panel_block()
    finance_urls = re.findall(r"/api/v1/finance/[^'\"\s)]+", block)
    assert finance_urls, "Expected at least one /api/v1/finance/ reference in the panel"
    for url in finance_urls:
        # Allow URL fragments built via string concatenation: the only
        # legal substring is `/api/v1/finance/postings/`.
        assert url.startswith("/api/v1/finance/postings/"), (
            f"Panel referenced non-breakdown finance URL: {url!r}"
        )


def test_panel_has_no_write_http_verbs_on_finance_urls():
    """No POST/PUT/PATCH/DELETE in the panel that targets a finance URL."""
    block = _panel_block()
    # Catch `method: 'POST'` style options on any fetch / apiFetch call.
    write_method = re.search(
        r"method\s*:\s*['\"](POST|PUT|PATCH|DELETE)['\"]",
        block,
        re.IGNORECASE,
    )
    assert write_method is None, (
        f"Panel contains write HTTP verb option: {write_method.group(0)!r}"
    )


def test_panel_has_no_forbidden_coupling_strings():
    """Forbid coupling URLs/imports to write subsystems.

    Read-only display of breakdown fields (e.g. `wfirma_invoice_id` rendered
    as a label) is allowed because the value originates server-side from the
    breakdown response. We forbid the *write* surfaces: URLs, imports, and
    mutation API tokens.
    """
    block = _panel_block().lower()
    forbidden = [
        # Write API surfaces.
        "/api/v1/wfirma",
        "/api/v1/proforma",
        "/api/v1/pz/",
        "/api/v1/dhl/",
        "/api/v1/carrier",
        # Settlement / charge / allocation mutation tokens.
        "settlement-close",
        "settlement_close",
        "charge-create",
        "charge_create",
        "allocation-create",
        "allocation_create",
        # Backfill execution surfaces.
        "backfill_run",
        "run-backfill",
        "run_backfill",
        # Imports / external client refs.
        "from wfirma",
        "import wfirma",
        "wfirma_client",
        "proforma_client",
    ]
    hits = [tok for tok in forbidden if tok in block]
    assert hits == [], (
        f"Panel contains forbidden coupling tokens: {hits}"
    )


def test_panel_has_no_auto_fetch_on_mount():
    """No useEffect that triggers apiFetch inside the panel block.

    The panel must wait for explicit user input + button click.
    """
    block = _panel_block()
    # Search for any `React.useEffect(` or `useEffect(` invocation.
    # If found, then within the same statement, apiFetch must NOT appear.
    use_effect_pattern = re.compile(r"\b(?:React\.)?useEffect\s*\(")
    for m in use_effect_pattern.finditer(block):
        # Take a window of ~400 chars after the useEffect call.
        window = block[m.start(): m.start() + 400]
        assert "apiFetch(" not in window, (
            "Panel contains useEffect that calls apiFetch — auto-fetch on mount is forbidden."
        )


def test_panel_has_explicit_fetch_handler():
    """The panel must wire fetch through an onClick handler, not useEffect."""
    block = _panel_block()
    assert "onClick={_doFetch}" in block or "onClick={() => _doFetch" in block, (
        "Panel must trigger fetch via an explicit click handler."
    )


def test_panel_uses_only_get_via_apifetch():
    """apiFetch calls inside the panel must NOT pass a write-method option."""
    block = _panel_block()
    # Find every apiFetch( call and inspect its arguments (best-effort regex).
    calls = re.findall(r"apiFetch\(([^)]*)\)", block)
    assert calls, "Panel must call apiFetch at least once"
    for call in calls:
        assert "POST" not in call and "PUT" not in call and "DELETE" not in call and "PATCH" not in call, (
            f"apiFetch call in panel contains write verb: {call!r}"
        )


def test_panel_has_readonly_badge():
    """A visible Read-only badge proves UX intent to the operator."""
    block = _panel_block()
    assert "diagnostics-finance-readonly-badge" in block, (
        "Panel must surface a visible Read-only badge."
    )


def test_panel_has_empty_state_copy():
    """Empty-state copy must explain dormant store, not look like an error."""
    block = _panel_block()
    assert "diagnostics-finance-posting-empty" in block, (
        "Panel must distinguish 404 (empty by design) from error."
    )


def test_panel_has_no_disabled_write_stub_buttons():
    """Even disabled-looking write stub buttons are forbidden in the panel."""
    block = _panel_block().lower()
    forbidden_button_labels = [
        "create posting",
        "post payment",
        "allocate payment",
        "run backfill",
        "close settlement",
        "create charge",
    ]
    hits = [tok for tok in forbidden_button_labels if tok in block]
    assert hits == [], (
        f"Panel contains forbidden write-stub button labels: {hits}"
    )


def test_finance_route_file_has_exactly_one_get():
    """Pin the backend surface: routes_finance_postings.py exposes only GET."""
    if not _FINANCE_ROUTE.exists():
        pytest.skip("routes_finance_postings.py missing")
    text = _FINANCE_ROUTE.read_text(encoding="utf-8")
    decorators = re.findall(r"@router\.(get|post|put|patch|delete)\b", text)
    assert decorators == ["get"], (
        f"routes_finance_postings.py must have exactly one @router.get decorator; got {decorators}"
    )


def test_diagnostics_page_renders_panel():
    """DiagnosticsPage must reference <FinancePostingBreakdownPanel /> exactly once."""
    if not _DASHBOARD.exists():
        pytest.skip("dashboard.html missing")
    text = _DASHBOARD.read_text(encoding="utf-8")
    # Locate the DiagnosticsPage function block.
    start = text.find("function DiagnosticsPage(")
    assert start >= 0
    # Take until the next top-level function/banner.
    after = text[start:]
    end = len(after)
    for term in ["\nfunction ", "\n// ══"]:
        idx = after.find(term, 1)
        if idx >= 0 and idx < end:
            end = idx
    diag_block = after[:end]
    count = diag_block.count("<FinancePostingBreakdownPanel")
    assert count == 1, (
        f"DiagnosticsPage must render <FinancePostingBreakdownPanel /> exactly once; got {count}"
    )
