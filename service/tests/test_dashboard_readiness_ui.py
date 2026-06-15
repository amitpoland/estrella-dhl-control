"""
test_dashboard_readiness_ui.py — Source-grep tests for the Phase 2
dashboard readiness UI components.

Pattern: read dashboard.html as text and assert structural markers.
No JSX execution.  Endpoint behaviour is covered by
test_batch_readiness_endpoint.py and test_dhl_readiness_endpoint.py.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

DASHBOARD = _STATIC / "dashboard.html"
SHIPMENT_DETAIL = _STATIC / "shipment-detail.html"


def _src() -> str:
    """Dashboard shell source — owns the readiness component *definitions*."""
    return DASHBOARD.read_text(encoding="utf-8")


def _sd_src() -> str:
    """BatchDetailPage source — owns the readiness panel *usage* and the
    decision-panel wiring extracted from dashboard.html at commit 015d90d
    (feat(frontend): phase 2 — extract BatchDetailPage into shipment-detail.html)."""
    return SHIPMENT_DETAIL.read_text(encoding="utf-8")


# ── Component existence ───────────────────────────────────────────────────────

def test_readiness_banner_component_exists():
    """ReadinessBanner function component must be defined."""
    assert "function ReadinessBanner(" in _src()


def test_overall_readiness_card_component_exists():
    """OverallReadinessCard function component must be defined."""
    assert "function OverallReadinessCard(" in _src()


# ── Tab registration ──────────────────────────────────────────────────────────

def test_overview_tab_registered_in_detail_tabs():
    """'Overview' must appear in the DETAIL_TABS list."""
    src = _src()
    for line in src.splitlines():
        if "DETAIL_TABS" in line and "[" in line:
            assert "'Overview'" in line or '"Overview"' in line, (
                f"'Overview' not found in DETAIL_TABS line: {line!r}"
            )
            return
    raise AssertionError("DETAIL_TABS constant not found in dashboard.html")


def test_dhl_customs_tab_registered_in_detail_tabs():
    """'DHL / Customs' must appear in the DETAIL_TABS list."""
    src = _src()
    for line in src.splitlines():
        if "DETAIL_TABS" in line and "[" in line:
            assert "'DHL / Customs'" in line or '"DHL / Customs"' in line, (
                f"'DHL / Customs' not found in DETAIL_TABS line: {line!r}"
            )
            return
    raise AssertionError("DETAIL_TABS constant not found in dashboard.html")


def test_pz_wfirma_tab_registered_in_detail_tabs():
    """'PZ / Accounting' must appear in the DETAIL_TABS list."""
    src = _src()
    for line in src.splitlines():
        if "DETAIL_TABS" in line and "[" in line:
            assert "'PZ / Accounting'" in line or '"PZ / Accounting"' in line, (
                f"'PZ / Accounting' not found in DETAIL_TABS line: {line!r}"
            )
            return
    raise AssertionError("DETAIL_TABS constant not found in dashboard.html")


def test_pipeline_tab_not_in_detail_tabs():
    """'Pipeline' must NOT be in DETAIL_TABS — it was renamed to 'Overview'."""
    src = _src()
    for line in src.splitlines():
        if "DETAIL_TABS" in line and "[" in line:
            assert "'Pipeline'" not in line and '"Pipeline"' not in line, (
                f"Old 'Pipeline' tab still in DETAIL_TABS: {line!r}"
            )
            return
    raise AssertionError("DETAIL_TABS constant not found in dashboard.html")


def test_dhl_tab_registered_in_detail_tabs():
    """'DHL / Customs' must appear in the DETAIL_TABS list (renamed from 'DHL')."""
    src = _src()
    for line in src.splitlines():
        if "DETAIL_TABS" in line and "[" in line:
            assert "'DHL / Customs'" in line or '"DHL / Customs"' in line, (
                f"'DHL / Customs' not found in DETAIL_TABS line: {line!r}"
            )
            return
    raise AssertionError("DETAIL_TABS constant not found in dashboard.html")


# ── Endpoint wiring ───────────────────────────────────────────────────────────

def test_batch_readiness_endpoint_wired():
    """/api/v1/batch/.../readiness must be called somewhere in the source."""
    assert "/api/v1/batch/" in _src()
    assert "/readiness`" in _src() or "readiness/" in _src()


def test_batch_readiness_exact_endpoint_url():
    """Exact endpoint URL fragment must be present in a fetch call."""
    assert "/api/v1/batch/${encodeURIComponent(batchId)}/readiness" in _src()


def test_dhl_readiness_endpoint_wired():
    """/api/v1/dhl/readiness/... must be called somewhere in the source."""
    assert "/api/v1/dhl/readiness/" in _sd_src()


def test_dhl_readiness_exact_endpoint_url():
    """Exact DHL readiness endpoint URL fragment must be present."""
    assert "/api/v1/dhl/readiness/${encodeURIComponent(batchId)}" in _sd_src()


# ── State hooks ───────────────────────────────────────────────────────────────

def test_batch_readiness_state_hook_exists():
    assert "batchReadiness, setBatchReadiness" in _sd_src()


def test_batch_readiness_loading_state_hook_exists():
    assert "batchReadinessLoading, setBatchReadinessLoading" in _sd_src()


def test_batch_readiness_error_state_hook_exists():
    assert "batchReadinessError, setBatchReadinessError" in _sd_src()


def test_dhl_readiness_state_hook_exists():
    assert "dhlReadiness, setDhlReadiness" in _sd_src()


def test_dhl_readiness_loading_state_hook_exists():
    assert "dhlReadinessLoading, setDhlReadinessLoading" in _sd_src()


def test_dhl_readiness_error_state_hook_exists():
    assert "dhlReadinessError, setDhlReadinessError" in _sd_src()


# ── Banner testid markers ─────────────────────────────────────────────────────

def test_readiness_banner_testid_warehouse():
    assert 'readiness-banner-warehouse' in _sd_src()


def test_readiness_banner_testid_sales():
    assert 'readiness-banner-sales' in _sd_src()


def test_readiness_banner_testid_wfirma():
    """wFirma readiness surface.

    Retargeted after the BatchDetailPage extraction (015d90d): warehouse,
    sales and dhl render dedicated per-panel ``<ReadinessBanner>`` components
    with static ``readiness-banner-<domain>`` testids, but wFirma readiness is
    consolidated into the OverallReadinessCard ``DOMAINS`` chip list instead.
    The literal ``readiness-banner-wfirma`` never existed in this repo's
    history — assert the genuine current surface: ``'wfirma'`` is a tracked
    readiness domain in OverallReadinessCard.
    """
    assert "DOMAINS = ['warehouse', 'sales', 'wfirma', 'dhl']" in _sd_src(), (
        "wFirma must remain a tracked readiness domain in OverallReadinessCard"
    )


def test_readiness_banner_testid_dhl():
    assert 'readiness-banner-dhl' in _sd_src()


def test_overall_readiness_card_testid():
    assert 'overall-readiness-card' in _src()


def test_dhl_readiness_panel_testid():
    assert 'dhl-readiness-panel' in _sd_src()


# ── Banners are inserted in the correct panels ────────────────────────────────

def _find_nth(src: str, needle: str, n: int = 1) -> int:
    """Return start index of the nth occurrence of needle in src (1-based)."""
    start = 0
    for _ in range(n):
        pos = src.find(needle, start)
        if pos == -1:
            return -1
        start = pos + 1
    return pos


def test_readiness_banner_in_warehouse_panel():
    """The warehouse banner must appear inside the Warehouse tab block (the panel, not the useEffect)."""
    src = _sd_src()
    # The panel render block is the SECOND occurrence — first is in a useEffect
    wh_start = _find_nth(src, "activeTab === 'Warehouse'", 2)
    assert wh_start != -1, "Warehouse panel block (2nd occurrence) not found"
    wh_end = src.find("activeTab === 'Sales'", wh_start)
    assert wh_end != -1
    snippet = src[wh_start:wh_end]
    assert "readiness-banner-warehouse" in snippet, (
        "ReadinessBanner with testid 'readiness-banner-warehouse' not in Warehouse panel"
    )


def test_readiness_banner_in_sales_panel():
    """The sales banner must appear inside the Sales tab block (the panel, not the useEffect)."""
    src = _sd_src()
    # The panel render block is the SECOND occurrence — first is in a useEffect
    sa_start = _find_nth(src, "activeTab === 'Sales'", 2)
    assert sa_start != -1, "Sales panel block (2nd occurrence) not found"
    sa_end = src.find("activeTab === 'PZ / Accounting'", sa_start)
    assert sa_end != -1
    snippet = src[sa_start:sa_end]
    assert "readiness-banner-sales" in snippet, (
        "ReadinessBanner with testid 'readiness-banner-sales' not in Sales panel"
    )


def test_readiness_banner_in_wfirma_panel():
    """wFirma readiness must be rendered in the OverallReadinessCard DOMAINS map.

    Retargeted after the BatchDetailPage extraction (015d90d): unlike warehouse,
    sales and dhl — which each render a dedicated per-panel ``<ReadinessBanner>``
    — wFirma readiness is surfaced via the consolidated OverallReadinessCard
    ``DOMAINS.map`` chip list (the PZ / Accounting panel itself renders the
    legacy PZ details block, not a readiness banner). Assert the genuine
    surface: wFirma is iterated by the OverallReadinessCard readiness map.
    """
    src = _sd_src()
    card_start = src.find("function OverallReadinessCard(")
    assert card_start != -1, "OverallReadinessCard not found in shipment-detail.html"
    next_fn = src.find("\nfunction ", card_start + 1)
    card_body = src[card_start:next_fn]
    assert "DOMAINS.map" in card_body, "OverallReadinessCard must render a DOMAINS map"
    assert "'wfirma'" in card_body, (
        "wFirma must be a rendered readiness domain in OverallReadinessCard"
    )


def test_readiness_banner_in_dhl_panel():
    """The DHL banner must appear inside the DHL / Customs tab block (the panel, not the useEffect)."""
    src = _sd_src()
    # The panel block is the SECOND occurrence — first is in a useEffect
    dhl_start = _find_nth(src, "activeTab === 'DHL / Customs'", 2)
    assert dhl_start != -1, "DHL / Customs panel block (2nd occurrence) not found"
    # Banner testid must come after the panel open
    banner_pos = src.find("readiness-banner-dhl", dhl_start)
    assert banner_pos != -1, (
        "ReadinessBanner with testid 'readiness-banner-dhl' not in DHL / Customs panel"
    )


def test_overall_readiness_card_in_overview_tab():
    """OverallReadinessCard must be rendered inside the Overview tab block."""
    src = _sd_src()
    overview_start = src.find("activeTab === 'Overview'")
    assert overview_start != -1, "Overview tab block not found"
    # Next non-Overview activeTab check (Documents)
    overview_end = src.find("activeTab === 'Documents'", overview_start)
    assert overview_end != -1
    snippet = src[overview_start:overview_end]
    assert "OverallReadinessCard" in snippet, (
        "OverallReadinessCard not rendered inside Overview tab block"
    )


def test_batch_control_center_component_exists():
    """BatchControlCenter function component must be defined."""
    assert "function BatchControlCenter(" in _src()


def test_batch_control_center_testid():
    """BatchControlCenter must have data-testid='batch-control-center'."""
    src = _src()
    assert 'data-testid="batch-control-center"' in src or "data-testid='batch-control-center'" in src


def test_batch_control_center_in_overview_tab():
    """BatchControlCenter must be rendered inside the Overview tab block."""
    src = _sd_src()
    overview_start = src.find("activeTab === 'Overview'")
    assert overview_start != -1, "Overview tab block not found"
    overview_end = src.find("activeTab === 'Documents'", overview_start)
    assert overview_end != -1
    snippet = src[overview_start:overview_end]
    assert "BatchControlCenter" in snippet, (
        "BatchControlCenter not rendered inside Overview tab block"
    )


# ── Rendered content markers ──────────────────────────────────────────────────

def test_overall_next_step_rendered():
    """overall.next_step must be rendered with a testid."""
    assert 'data-testid="overall-next-step"' in _src() or "data-testid='overall-next-step'" in _src()


def test_dhl_next_required_action_rendered():
    """dhl.next_required_action must be rendered with a testid."""
    src = _sd_src()
    assert 'data-testid="dhl-next-required-action"' in src or "data-testid='dhl-next-required-action'" in src


def test_dhl_panel_shows_pipeline_stages():
    """DHL panel must render the 7-stage pipeline labels."""
    src = _sd_src()
    # Use the testid as anchor — it's inside the actual panel, not the useEffect
    panel_start = src.find("dhl-readiness-panel")
    assert panel_start != -1, "dhl-readiness-panel testid not found"
    snippet = src[panel_start:panel_start + 8000]
    for stage in ["Awaiting Start", "DHL Contacted", "DHL Replied", "Agency Forwarded", "Customs Cleared"]:
        assert stage in snippet, f"Stage '{stage}' not found in DHL panel"


def test_dhl_panel_shows_sla_breach_warning():
    """DHL panel must have an SLA breach warning block."""
    src = _sd_src()
    panel_start = src.find("dhl-readiness-panel")
    assert panel_start != -1
    snippet = src[panel_start:panel_start + 8000]
    assert "sla_breach" in snippet and ("SLA Breach" in snippet or "SLA breach" in snippet)


# ── Loading / error / empty states ───────────────────────────────────────────

def test_batch_readiness_loading_state_used():
    assert "batchReadinessLoading" in _src()


def test_batch_readiness_error_state_used():
    assert "batchReadinessError" in _src()


def test_dhl_readiness_loading_state_used():
    assert "dhlReadinessLoading" in _sd_src()


def test_dhl_readiness_error_state_used():
    assert "dhlReadinessError" in _sd_src()


def test_dhl_panel_has_empty_state():
    """DHL tab must show a message when dr is null (no data yet)."""
    src = _sd_src()
    panel_start = src.find("dhl-readiness-panel")
    assert panel_start != -1
    snippet = src[panel_start:panel_start + 5000]
    assert "No DHL readiness data available" in snippet


def test_dhl_panel_has_loading_state():
    """DHL tab must show a loading indicator while fetching."""
    src = _sd_src()
    panel_start = src.find("dhl-readiness-panel")
    assert panel_start != -1
    snippet = src[panel_start:panel_start + 5000]
    assert "Loading DHL pipeline" in snippet or "dhlReadinessLoading" in snippet


# ── No mutation POST added ────────────────────────────────────────────────────

def test_no_post_for_batch_readiness():
    """The batch readiness fetch must be GET-only — no POST method added."""
    src = _sd_src()
    # Find the loadBatchReadiness function and confirm no POST
    start = src.find("loadBatchReadiness")
    assert start != -1
    snippet = src[start:start + 300]
    assert "method: 'POST'" not in snippet and 'method:"POST"' not in snippet, (
        "loadBatchReadiness must not use POST"
    )


def test_no_post_for_dhl_readiness():
    """The DHL readiness fetch must be GET-only — no POST method added."""
    src = _sd_src()
    start = src.find("loadDhlReadiness")
    assert start != -1
    snippet = src[start:start + 300]
    assert "method: 'POST'" not in snippet and 'method:"POST"' not in snippet, (
        "loadDhlReadiness must not use POST"
    )


# ── Brace balance ─────────────────────────────────────────────────────────────

def test_brace_balance():
    """Curly braces in the JS/JSX portion must be balanced."""
    import re
    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("{")
    closes = jsx.count("}")
    assert opens == closes, f"Unbalanced curly braces: {{ {opens}  }} {closes}"


# ── Phase 3.6: decision integration state ────────────────────────────────────

def test_decision_data_state_hook_exists():
    """decisionData state hook must be declared at the BatchDetailPage level."""
    assert "decisionData, setDecisionData" in _sd_src()


def test_decision_loading_state_hook_exists():
    """decisionLoading state hook must exist alongside decisionData."""
    assert "decisionLoading, setDecisionLoading" in _sd_src()


def test_load_decision_function_defined():
    """loadDecision callback must be defined and call the decision endpoint."""
    src = _sd_src()
    assert "loadDecision" in src, "loadDecision callback not found"
    assert "/api/v1/agents/decision/" in src, "decision endpoint URL not found"


def test_decision_loaded_on_batch_mount():
    """loadDecision must be called in the same useEffect as loadBatchReadiness."""
    src = _sd_src()
    idx = src.find("loadBatchReadiness(); loadDecision();")
    assert idx != -1, (
        "loadDecision() must be invoked alongside loadBatchReadiness() in the mount effect"
    )


def test_is_primary_action_helper_defined():
    """isPrimaryAction helper must be defined for decision advisory integration."""
    assert "isPrimaryAction" in _sd_src()


def test_top_proposal_id_helper_defined():
    """topProposalId must be derived from decisionData.all_actions for proposal matching."""
    src = _sd_src()
    assert "topProposalId" in src, "topProposalId not found"
    assert "decisionData.all_actions" in src, "decisionData.all_actions not referenced"


def test_wfirma_primary_helper_defined():
    """wfirmaPrimary flag must be derived from decision advisory for create button highlight."""
    src = _sd_src()
    assert "wfirmaPrimary" in src, "wfirmaPrimary not found"
    assert "decisionData.status === 'action_required'" in src, (
        "wfirmaPrimary must check decisionData.status"
    )


def test_decision_is_read_only():
    """loadDecision must use GET, not POST."""
    src = _sd_src()
    idx = src.find("loadDecision")
    assert idx != -1
    snippet = src[idx:idx + 400]
    assert "method: 'POST'" not in snippet and 'method:"POST"' not in snippet, (
        "loadDecision must be GET-only"
    )


# ── Phase 3.6 dedup: DecisionBanner prop-based, no internal fetch ─────────────

def test_decision_banner_accepts_decision_data_prop():
    """DecisionBanner must accept decisionData as a prop, not batchId."""
    src = _src()
    idx = src.find("function DecisionBanner(")
    assert idx != -1
    sig_snippet = src[idx:idx + 80]
    assert "decisionData" in sig_snippet, "DecisionBanner signature must include decisionData"
    assert "batchId" not in sig_snippet, "DecisionBanner must not accept batchId after dedup"


def test_decision_banner_no_internal_fetch():
    """DecisionBanner must not contain an internal apiFetch call to the decision endpoint."""
    src = _src()
    banner_start = src.find("function DecisionBanner(")
    assert banner_start != -1
    # Find the next top-level function definition after DecisionBanner
    next_fn = src.find("\nfunction ", banner_start + 1)
    banner_body = src[banner_start:next_fn]
    assert "apiFetch" not in banner_body, (
        "DecisionBanner must not call apiFetch — decision data is passed via props"
    )
    assert "useEffect" not in banner_body, (
        "DecisionBanner must not contain useEffect — no internal fetch after dedup"
    )


def test_batch_detail_page_is_sole_decision_fetcher():
    """Only BatchDetailPage's loadDecision callback may call the decision endpoint."""
    src = _sd_src()
    # All occurrences of the decision endpoint URL
    endpoint = "/api/v1/agents/decision/"
    count = src.count(endpoint)
    assert count == 1, (
        f"Decision endpoint should appear exactly once (in loadDecision), found {count}"
    )


def test_overall_readiness_card_passes_decision_props():
    """OverallReadinessCard must pass decisionData and decisionLoading to DecisionBanner."""
    src = _src()
    card_start = src.find("function OverallReadinessCard(")
    assert card_start != -1
    next_fn = src.find("\nfunction ", card_start + 1)
    card_body = src[card_start:next_fn]
    assert "decisionData={decisionData}" in card_body, (
        "OverallReadinessCard must forward decisionData to DecisionBanner"
    )
    assert "decisionLoading={decisionLoading}" in card_body, (
        "OverallReadinessCard must forward decisionLoading to DecisionBanner"
    )


def test_batch_detail_page_passes_decision_to_overall_readiness_card():
    """BatchDetailPage must pass decisionData and decisionLoading to OverallReadinessCard."""
    src = _sd_src()
    # Find the OverallReadinessCard JSX call in BatchDetailPage
    idx = src.find("<OverallReadinessCard")
    assert idx != -1
    call_snippet = src[idx:idx + 300]
    assert "decisionData={decisionData}" in call_snippet, (
        "BatchDetailPage must pass decisionData to OverallReadinessCard"
    )
    assert "decisionLoading={decisionLoading}" in call_snippet, (
        "BatchDetailPage must pass decisionLoading to OverallReadinessCard"
    )
    assert "batchId={batchId}" not in call_snippet, (
        "OverallReadinessCard call must not pass batchId after dedup"
    )


def test_paren_balance():
    """Parentheses in the JS/JSX portion must be balanced."""
    import re
    content = SHIPMENT_DETAIL.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("(")
    closes = jsx.count(")")
    assert opens == closes, f"Unbalanced parentheses: ( {opens}  ) {closes}"


# ── JSX comment syntax regression (Babel 'expected ,') ───────────────────────
#
# Root cause (fixed 2026-05-04):
#
#   {!isTrackingLookup && (isPending || isApproved) && (
#     <div ...>
#       ...
#     </div>{/* /flex row */}
#     </div>{/* /column */}   ← ROOT CAUSE
#   )}
#
# `{/* /column */}` appeared after `</div>` but OUTSIDE all JSX elements —
# it was still inside the JavaScript `&&(...)` expression.  Babel's parser
# treated `{/* /column */}` as an empty object literal `{}` and then expected
# a comma separator before the next token, producing:
#
#   SyntaxError: Unexpected token, expected "," (line N, col 26)
#
# The `>` of the next `</div>` (at column 26) was misread as a greater-than
# operator, not a JSX closing tag, so the whole dashboard failed to render.
#
# Fix: removed inline comments on closing `</div>` tags inside &&() blocks.
# ─────────────────────────────────────────────────────────────────────────────


def test_no_jsx_column_comment_string():
    """The exact string '{/* /column */}' must not appear anywhere in dashboard.html.

    This was the root cause of the Babel parse error: a JSX block comment
    placed after </div> but OUTSIDE all JSX elements, inside a JavaScript
    &&(...) expression.  Babel parsed it as an empty object literal and then
    expected a comma, breaking the entire dashboard render.
    """
    src = DASHBOARD.read_text(encoding="utf-8")
    assert "{/* /column */}" not in src, (
        "'{/* /column */}' found in dashboard.html — this was the root cause of "
        "the Babel SyntaxError ('Unexpected token, expected \\',\\'').  "
        "JSX block comments must not appear after the last closing </div> inside "
        "a JavaScript &&(...) expression."
    )


def test_no_closing_div_with_jsx_comment_before_expression_close():
    """Regression: '</div>{/* ... */}' immediately followed by ')}' is a Babel parse error.

    When a JSX block comment {/* */} appears after </div> but before the closing
    ')' of a &&(expression), the parser is in JavaScript context — not JSX context.
    Babel treats {/* */} as an empty object literal and then expects a comma,
    causing 'Unexpected token, expected ',''.

    This test scans the main JS/JSX script for any line containing '</div>{/*'
    where the next non-blank line starts with ')}', which would close the
    JavaScript &&(...) expression and confirm the comment is in the wrong context.
    """
    import re

    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    lines = jsx.splitlines()

    violations: list[str] = []
    for i, line in enumerate(lines):
        if "</div>{/*" not in line:
            continue
        # Scan ahead up to 3 lines for the expression-close pattern ')}' or ')}'
        for j in range(i + 1, min(i + 4, len(lines))):
            nxt = lines[j].strip()
            if not nxt:
                continue          # skip blank lines
            if nxt.startswith(")}"):
                violations.append(
                    f"  script line {i + 1}: {line.rstrip()!r}\n"
                    f"  followed by ')}}' at script line {j + 1}: {lines[j].rstrip()!r}"
                )
            break  # stop at first non-blank line (we only care about immediate context)

    assert not violations, (
        "Found '</div>{{/* ... */}}' immediately before ')}' — the JSX block comment "
        "is in JavaScript expression context, not JSX content.  "
        "Babel parses it as an empty object literal and raises 'expected ,'.\n"
        + "\n".join(violations)
    )


def test_no_jsx_block_comment_closes_expression_div():
    """Narrowed check: a line that is ONLY </div>{/* ... */} is dangerous only when
    the &&(...) expression closes on the very next non-blank line (i.e. that line
    starts with ')}').  In JSX content (where more sibling elements follow) the
    same pattern is harmless.

    This catches the original bug:
        </div>{/* /column */}
        )}                       ← outer &&(...) closes here → Babel sees {} literal
    and does NOT flag:
        </div>{/* /wfirma-confirm-modal */}
        <SomeChild ... />        ← still inside JSX parent → safe
    """
    import re

    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    lines = jsx.splitlines()

    violations: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Line whose visible content is ONLY a closing </div> + an inline JSX comment
        if not re.match(r"^</div>\s*\{/\*.*\*/\}\s*$", stripped):
            continue
        # Only dangerous if the &&(...) expression closes within the next 3 lines
        for j in range(i + 1, min(i + 4, len(lines))):
            nxt = lines[j].strip()
            if not nxt:
                continue
            if nxt.startswith(")}"):
                violations.append(
                    f"  script line {i + 1}: {line.rstrip()!r}\n"
                    "  followed by ')}' at script line "
                    f"{j + 1}: {lines[j].rstrip()!r}"
                )
            break  # only look at the first non-blank successor

    assert not violations, (
        "Found </div>{/* ... */} immediately before ')}' — the JSX block comment "
        "is in JavaScript expression context (inside &&(...)), not JSX content.  "
        "Babel parses {/* */} as an empty object literal and raises "
        "'Unexpected token, expected \",\"'.\n"
        "Move the comment to its own line above the closing </div>:\n"
        "  {/* label */}\n"
        "  </div>\n"
        "  )}\n"
        "Violations:\n" + "\n".join(violations)
    )


# ── Default active tab regression (Pipeline → Overview) ──────────────────────

def test_default_active_tab_is_overview():
    """
    useState for activeTab must default to 'Overview', not 'Pipeline'.

    Regression: dashboard was blank because useState('Pipeline') was the default
    but 'Pipeline' no longer exists in DETAIL_TABS, so no tab content ever rendered.
    """
    src = _sd_src()
    assert "useState('Pipeline')" not in src and 'useState("Pipeline")' not in src, (
        "useState('Pipeline') found — default active tab must be 'Overview', "
        "not 'Pipeline' which no longer exists in DETAIL_TABS"
    )
    assert "useState('Overview')" in src or 'useState("Overview")' in src, (
        "useState('Overview') not found — default active tab must be 'Overview'"
    )


def test_no_pipeline_usestate_anywhere():
    """No useState call in the dashboard may reference 'Pipeline'."""
    src = _src()
    assert "useState('Pipeline')" not in src and 'useState("Pipeline")' not in src, (
        "useState('Pipeline') must not exist anywhere in dashboard — "
        "'Pipeline' was removed from DETAIL_TABS"
    )


def test_overview_content_block_exists():
    """
    There must be a content block guarded by activeTab === 'Overview'.

    This ensures the Overview tab has renderable content and won't
    silently blank the panel if the default active tab is 'Overview'.
    """
    src = _sd_src()
    assert (
        "activeTab === 'Overview'" in src or 'activeTab === "Overview"' in src
    ), (
        "No content block guarded by activeTab === 'Overview' found in dashboard — "
        "Overview tab has no content to render"
    )
