"""
Source-grep guard tests for the InboxPage Open-button dead-button fix.

Background
----------
The Inbox table renders rows from heterogeneous sources (DSK, proposals,
emails). Only rows whose `open_target.type === "batch"` actually have a
navigation target (the shipment detail view). Earlier the Open button was
rendered for every row with any `open_target`, even ones the click handler
silently no-op'd on — a classic dead-button UX bug.

This file pins the corrected render contract in source so a regression is
caught at test time, not in production.

Invariants
----------
1. The active `inbox-open-btn` JSX is gated by `row.open_target.type === 'batch'`.
2. Non-batch rows render a dedicated disabled placeholder with
   `data-testid="inbox-open-disabled"` and a tooltip explaining why.
3. The Open button block does NOT issue writes (no apiFetch / fetch / POST/PUT/DELETE).
4. No other `open_target.type` literal is treated as navigable in the same block.
5. The dashboard.html brace count is balanced (cheap whole-file integrity guard).
"""

from pathlib import Path

DASHBOARD = (
    Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"
)


def _read() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def _inbox_open_block(src: str) -> str:
    """Return the slice of dashboard.html that contains the Inbox Open cell.

    We anchor on the `inbox-open-btn` testid and walk a small window around it
    so the assertions are local to the cell rather than global to the file.
    """
    marker = 'data-testid="inbox-open-btn"'
    idx = src.find(marker)
    assert idx != -1, "inbox-open-btn testid not found in dashboard.html"
    # 400 chars of context before + 900 after is enough to cover the
    # ternary guard + button onClick body + fallback span, but tight enough
    # to avoid bleeding into unrelated InboxPage blocks.
    start = max(0, idx - 400)
    end = min(len(src), idx + 900)
    return src[start:end]


def test_inbox_open_btn_is_guarded_by_batch_type():
    """The active Open button must require open_target.type === 'batch'."""
    block = _inbox_open_block(_read())
    assert "row.open_target && row.open_target.type === 'batch'" in block, (
        "Open button render guard must be "
        "`row.open_target && row.open_target.type === 'batch'` — "
        "rendering for any truthy open_target reintroduces the dead-button bug."
    )


def test_inbox_open_disabled_placeholder_present():
    """Non-batch rows must show an explicit disabled placeholder with tooltip."""
    block = _inbox_open_block(_read())
    assert 'data-testid="inbox-open-disabled"' in block, (
        "Fallback em-dash span must carry data-testid='inbox-open-disabled' "
        "so QA and design-preview tests can target it."
    )
    assert 'title="No navigation target for this row type"' in block, (
        "Disabled placeholder must include a tooltip explaining why the row "
        "is not navigable. Operator-facing affordances are not silent."
    )


def test_inbox_open_block_has_no_writes():
    """The Open cell never issues backend writes — navigation only."""
    block = _inbox_open_block(_read())
    forbidden = ("apiFetch(", "fetch(", "'POST'", '"POST"', "'PUT'", '"PUT"',
                 "'DELETE'", '"DELETE"')
    for token in forbidden:
        assert token not in block, (
            f"Inbox Open cell must not perform writes — found `{token}`. "
            "Send / approve / reject actions remain on each item's detail page."
        )


def test_no_non_batch_open_target_type_navigable():
    """Only 'batch' is a navigable open_target.type inside this cell."""
    block = _inbox_open_block(_read())
    # Any other literal `open_target.type === '<x>'` inside this cell would
    # imply a second navigation path we haven't sanctioned. Scan for the
    # pattern and assert the only allowed value is 'batch'.
    import re
    matches = re.findall(r"open_target\.type\s*===\s*'([^']+)'", block)
    assert matches, "Expected at least one open_target.type comparison in the cell."
    assert set(matches) == {"batch"}, (
        f"Only 'batch' may be treated as navigable inside the Inbox Open cell; "
        f"found {sorted(set(matches))}. Add explicit handlers in a follow-up "
        f"PR before introducing new navigation targets."
    )


def test_dashboard_html_braces_balanced():
    """Cheap structural guard: opening/closing braces must match.

    Catches the most common kind of breakage from a botched JSX edit
    (stray `{` or `}`) without needing a real JS parser.
    """
    src = _read()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, (
        f"dashboard.html brace imbalance: {opens} `{{` vs {closes} `}}`. "
        "An edit to the Inbox cell likely dropped or added a brace."
    )
