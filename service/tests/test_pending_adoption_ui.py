"""test_pending_adoption_ui.py — pin PR 4 of 4 frontend UI invariants
for the pending_adoption operator decision surface in shipment-detail.html.

Tests are source-grep-only — they verify the HTML/JSX contains the
required testids, endpoint paths, and cancel-is-noop guarantees without
needing a browser. The deployed PR #300 + PR #302 + PR #303 backend
guarantees behavioral correctness; this suite pins the wiring.

V1-freeze exception (Lesson F): this is the only V1 page change for the
search-first product authority arc. The tests below pin that the
exception stayed narrow — no dashboard.html / dashboard-shared.js touched,
no business logic re-derived in the frontend, no silent adoption paths.
"""
from __future__ import annotations

from pathlib import Path

SHIPMENT_DETAIL = (
    Path(__file__).parents[1] / "app" / "static" / "shipment-detail.html"
)


def _read() -> str:
    return SHIPMENT_DETAIL.read_text(encoding="utf-8", errors="ignore")


# ── A. Required data-testids present ───────────────────────────────────


class TestRequiredTestIds:

    REQUIRED = [
        "pending-adoption-panel",
        "pending-adoption-open-modal",
        "pending-adoption-modal-body",
        "pending-adoption-list",
        "pending-adoption-empty",
        "pending-adoption-error",
        "pending-adoption-close",
    ]

    def test_all_required_testids_present(self):
        html = _read()
        missing = [tid for tid in self.REQUIRED if f'"{tid}"' not in html]
        assert not missing, f"missing data-testids: {missing}"

    def test_per_row_testid_templates_present(self):
        """Per-row testids are template literals; pin the prefixes."""
        html = _read()
        for prefix in (
            "pending-row-",
            "pending-compare-",
            "pending-comparison-",
            "pending-action-adopt-",
            "pending-action-update-",
            "pending-action-create-",
            "pending-message-",
        ):
            assert prefix in html, f"missing per-row testid template: {prefix}"


# ── B. Deployed endpoints are the sole wFirma write surface ────────────


class TestEndpointPaths:

    def test_read_endpoint_wired(self):
        """Pending list MUST be fetched from the deployed read endpoint."""
        html = _read()
        assert (
            "/api/v1/wfirma/products?sync_status=pending_adoption" in html
        ), "pending list endpoint not wired"

    def test_compare_endpoint_wired(self):
        """Per-row comparison MUST hit the deployed PR #300 read endpoint."""
        html = _read()
        assert (
            "/api/v1/wfirma/goods/search-and-compare?product_code=" in html
        ), "search-and-compare endpoint not wired"

    def test_three_write_endpoints_wired(self):
        """All 3 deployed PR #302 write endpoints MUST be called."""
        html = _read()
        # The handlers compose the URL via template; pin the URL fragment
        # and each endpoint suffix the dispatcher passes.
        assert "/api/v1/wfirma/goods/${endpoint}/${encodeURIComponent(productCode)}" in html, (
            "shared POST dispatcher URL template missing"
        )
        for endpoint in ("adopt", "update-and-adopt", "create-and-adopt"):
            assert f"'{endpoint}'" in html, f"endpoint label not passed: {endpoint}"


# ── C. No silent adoption / no client-side authority re-derivation ─────


class TestNoSilentAdoption:

    def test_no_client_side_matched_status_advance(self):
        """The frontend MUST NEVER write sync_status='matched' itself.
        Only the deployed backend endpoints advance state. If this assertion
        ever fails, the UI has started faking authority and must be reverted."""
        html = _read()
        # Search for the exact pattern that would indicate frontend
        # advancing pending → matched without an endpoint call.
        # Frontend code never writes sync_status; the backend endpoints do.
        forbidden_patterns = [
            "sync_status: 'matched'",
            'sync_status: "matched"',
            "sync_status='matched'",
            'sync_status="matched"',
        ]
        for pat in forbidden_patterns:
            assert pat not in html, (
                f"forbidden client-side authority pattern found: {pat!r}"
            )

    def test_cancel_close_is_noop(self):
        """closePendingModal MUST only reset local UI state. No fetch,
        no setSyncStatus, no backend call."""
        html = _read()
        # Locate the close handler block and verify it only sets state.
        close_block_idx = html.find("closePendingModal = React.useCallback")
        assert close_block_idx > 0, "closePendingModal handler missing"
        # Read ~200 chars after the marker — should contain
        # setPendingModalOpen(false) and nothing else substantive.
        close_block = html[close_block_idx:close_block_idx + 400]
        assert "setPendingModalOpen(false)" in close_block, (
            "close handler must reset modal state"
        )
        assert "fetch(" not in close_block, (
            "close handler must NEVER call fetch — would violate "
            "cancel-is-noop guarantee"
        )
        assert "apiFetch(" not in close_block, (
            "close handler must NEVER call apiFetch"
        )

    def test_close_button_label_signals_no_mutation(self):
        """The close button copy must explicitly tell the operator that
        cancelling causes no side effect."""
        html = _read()
        assert "Close (no mutation)" in html, (
            "close button must label itself as no-mutation"
        )


# ── D. V1-freeze discipline — change is narrowly scoped ────────────────


class TestV1FreezeDiscipline:

    def test_only_shipment_detail_html_touched(self):
        """The V1-freeze exception applies ONLY to shipment-detail.html.
        dashboard.html and dashboard-shared.js MUST NOT be touched."""
        dashboard = (
            Path(__file__).parents[1] / "app" / "static" / "dashboard.html"
        ).read_text(encoding="utf-8", errors="ignore")
        shared = (
            Path(__file__).parents[1] / "app" / "static" / "dashboard-shared.js"
        ).read_text(encoding="utf-8", errors="ignore")
        # The new code introduces these tokens; verify they are NOT in
        # the V1-frozen files we promised not to touch.
        for forbidden_token in (
            "pending-adoption-panel",
            "pending-adoption-open-modal",
            "pending-adoption-modal-body",
        ):
            assert forbidden_token not in dashboard, (
                f"V1-freeze violation: dashboard.html contains {forbidden_token}"
            )
            assert forbidden_token not in shared, (
                f"V1-freeze violation: dashboard-shared.js contains "
                f"{forbidden_token} — shared layer must remain "
                f"domain-agnostic per Lesson F Rule 5"
            )

    def test_one_time_exception_documented_in_source(self):
        """The code MUST self-document this as a one-time, non-precedent
        V1-freeze exception. Future authors reading the source will see
        the explicit non-precedent language."""
        html = _read()
        # The block comment in source MUST contain the discipline language
        assert "V1-freeze exception" in html, (
            "V1-freeze exception comment missing"
        )
        assert "NON-PRECEDENT" in html.upper(), (
            "exception must explicitly disclaim precedent setting"
        )

    def test_reviewer_challenge_scale_concern_addressed(self):
        """reviewer-challenge raised modal-scale concern (50+ pending
        rows). The implementation MUST use a scroll container."""
        html = _read()
        assert "maxHeight: 480" in html, (
            "scrollable container missing — modal would be unmanageable "
            "for batches with many pending rows"
        )
        assert "overflowY: 'auto'" in html, (
            "scroll behavior missing"
        )


# ── E. Authority discipline — frontend is a thin caller ────────────────


class TestThinCaller:

    def test_advisory_text_rendered_verbatim(self):
        """Advisory text comes from the backend comparator. UI MUST
        display it verbatim, not re-interpret. The render path uses
        the raw cmp.advisory value."""
        html = _read()
        # The JSX renders {cmp.advisory} unmodified — verify the literal
        assert "cmp.advisory" in html, (
            "advisory must be rendered via cmp.advisory (verbatim)"
        )

    def test_recommendation_rendered_verbatim(self):
        """Comparator recommendation is rendered as-is — no UI mapping
        from raw enum values to operator-friendly labels (that would be
        UI-side business logic)."""
        html = _read()
        assert "cmp.recommendation" in html, (
            "recommendation must be rendered via cmp.recommendation"
        )

    def test_three_explicit_buttons_for_three_endpoints(self):
        """Each operator decision corresponds to exactly one POST endpoint.
        UI MUST present three distinct buttons — no UI-side decision logic
        that picks the endpoint automatically."""
        html = _read()
        for label in ("Adopt as-is", "Update then adopt", "Create new"):
            assert label in html, f"missing explicit operator-choice button: {label}"

    def test_state_refresh_after_action(self):
        """reviewer-challenge raised race concern. After any successful
        action the list MUST be re-fetched so other open modals see the
        updated state on next render."""
        html = _read()
        # The action handler must call refreshPendingList after success
        action_handler_idx = html.find("_postPendingAction = React.useCallback")
        assert action_handler_idx > 0
        body = html[action_handler_idx:action_handler_idx + 2000]
        assert "await refreshPendingList()" in body, (
            "post-action state refresh missing — would leave other open "
            "modals with stale state"
        )
