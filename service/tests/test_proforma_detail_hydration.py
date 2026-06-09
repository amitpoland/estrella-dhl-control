"""
test_proforma_detail_hydration.py
===================================
Regression tests for proforma_detail URL-param hydration.

Feature: direct URL / bookmark / browser-refresh navigation to
/v2/proforma_detail?draft=<id>  OR  /v2/proforma_detail?batch_id=<id>
must load the correct draft without requiring a React drill-down from
the proforma list.

Root cause (pre-fix): ProformaDetailPage required `proformaDraft` React
state to already be set; direct URLs left that state null → blank page.

Fix (service/app/static/v2/index.html):
  1. `proformaHydrating` + `proformaHydrateError` state variables added.
  2. `handleProformaDrill` updated to write `?draft=<id>` into the URL.
  3. Hydration useEffect reads `?draft=` or falls back to `?batch_id=`
     and fetches the draft via EstrellaShared.apiFetch (raw JSON, not
     the PzApi wrapper which would add a `data:` envelope).
  4. Three-state render: loading → error → ProformaDetailPage (was
     a single bare `proformaDraft && <ProformaDetailPage ...>`).

Scope: source-grep tests — no server required.
"""
from __future__ import annotations

import re
from pathlib import Path

_V2         = Path(__file__).parent.parent / "app" / "static" / "v2"
_INDEX_HTML = _V2 / "index.html"


def _src() -> str:
    return _INDEX_HTML.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# 1 — State declarations
# ══════════════════════════════════════════════════════════════════════════════

class TestStateDeclarations:
    """proformaHydrating and proformaHydrateError must be declared in App()."""

    def test_proforma_hydrating_state_exists(self):
        src = _src()
        assert "proformaHydrating" in src, (
            "index.html must declare proformaHydrating state "
            "(needed for loading-spinner while draft is fetched)"
        )

    def test_proforma_hydrate_error_state_exists(self):
        src = _src()
        assert "proformaHydrateError" in src, (
            "index.html must declare proformaHydrateError state "
            "(needed to show an error message when fetch fails)"
        )

    def test_hydrating_initial_true_on_direct_url(self):
        """proformaHydrating must be true on initial load when page=proforma_detail.

        This prevents a flash of blank content before the API call completes.
        """
        src = _src()
        # The pattern: useState(_initialLocation.page === 'proforma_detail')
        assert "proformaHydrating" in src
        assert "_initialLocation.page === 'proforma_detail'" in src, (
            "proformaHydrating initial value must be "
            "`_initialLocation.page === 'proforma_detail'` so that "
            "a direct-URL navigation starts in loading state, not blank"
        )

    def test_hydrate_error_initial_null(self):
        """proformaHydrateError must start as null (no error on mount)."""
        src = _src()
        assert "proformaHydrateError" in src
        assert "React.useState(null)" in src or "useState(null)" in src, (
            "proformaHydrateError must be initialized to null"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2 — Hydration useEffect
# ══════════════════════════════════════════════════════════════════════════════

class TestHydrationEffect:
    """The hydration useEffect must exist with correct guard, paths, and deps."""

    def _effect_block(self) -> str:
        src = _src()
        marker = "proforma_detail URL-param hydration"
        idx = src.find(marker)
        assert idx != -1, (
            f"index.html must contain the hydration comment block "
            f"'{marker}' so it is unambiguous to locate"
        )
        return src[idx: idx + 3000]

    def test_guard_page_and_draft(self):
        """Effect must bail out when page!=proforma_detail or draft already set."""
        block = self._effect_block()
        assert "page !== 'proforma_detail'" in block, (
            "Hydration effect must check page !== 'proforma_detail'"
        )
        assert "proformaDraft" in block, (
            "Hydration effect must check proformaDraft to avoid double-fetch"
        )

    def test_reads_draft_url_param(self):
        """Effect must read ?draft= from window.location.search."""
        block = self._effect_block()
        assert "sp.get('draft')" in block or 'sp.get("draft")' in block, (
            "Hydration effect must read ?draft= URL param"
        )

    def test_reads_batch_id_url_param(self):
        """Effect must read ?batch_id= as fallback."""
        block = self._effect_block()
        assert "sp.get('batch_id')" in block or 'sp.get("batch_id")' in block, (
            "Hydration effect must read ?batch_id= URL param as fallback"
        )

    def test_missing_params_sets_error(self):
        """When neither param is present, setProformaHydrateError must be called."""
        block = self._effect_block()
        assert "setProformaHydrateError" in block, (
            "Hydration effect must call setProformaHydrateError when params are missing"
        )

    def test_draft_path_uses_draft_endpoint(self):
        """?draft=<id> path must fetch /api/v1/proforma/draft/<id>."""
        block = self._effect_block()
        assert "/api/v1/proforma/draft/" in block, (
            "Hydration effect must fetch /api/v1/proforma/draft/<id> for ?draft= param"
        )

    def test_batch_path_uses_batch_endpoint(self):
        """?batch_id= path must fetch /api/v1/proforma/drafts/<batch_id>."""
        block = self._effect_block()
        assert "/api/v1/proforma/drafts/" in block, (
            "Hydration effect must fetch /api/v1/proforma/drafts/<batch_id> for ?batch_id= param"
        )

    def test_uses_raw_api_fetch_not_pz_api(self):
        """Must use EstrellaShared.apiFetch (raw JSON) not PzApi (adds data: wrapper).

        The endpoint returns {ok, draft: {...}} — PzApi would wrap it further
        as {ok, data: {ok, draft: {...}}} breaking the !r.draft check.
        """
        block = self._effect_block()
        assert "EstrellaShared.apiFetch" in block or "apiFetch" in block, (
            "Hydration effect must use EstrellaShared.apiFetch, not PzApi"
        )
        # Must NOT use PzApi.getDraft (which wraps in {ok, data:...})
        assert "PzApi.getDraft" not in block, (
            "Hydration effect must NOT use PzApi.getDraft — use apiFetch directly "
            "so the response shape matches the !r.draft check"
        )

    def test_checks_draft_key_in_response(self):
        """Response check must test !r.draft (not !r.data.draft or !r.ok)."""
        block = self._effect_block()
        assert "!r.draft" in block or "r.draft" in block, (
            "Hydration effect must check `r.draft` in the API response "
            "(endpoint returns {ok, draft: {...}}, not {data: {draft: {...}}})"
        )

    def test_sets_proforma_draft_on_success(self):
        """Effect must call setProformaDraft on successful fetch."""
        block = self._effect_block()
        assert "setProformaDraft(r.draft)" in block or "setProformaDraft(r.draft)" in block, (
            "Hydration effect must call setProformaDraft(r.draft) on success"
        )

    def test_sets_hydrating_false_on_complete(self):
        """Effect must call setProformaHydrating(false) when done (success or error)."""
        block = self._effect_block()
        assert "setProformaHydrating(false)" in block, (
            "Hydration effect must call setProformaHydrating(false) on both "
            "success and error paths"
        )

    def test_dep_array_is_page(self):
        """Effect dependency array must include [page] so it re-fires on navigation."""
        block = self._effect_block()
        assert "}, [page])" in block or "}, [page]); " in block or "], // eslint" in block or "[page])" in block, (
            "Hydration effect dependency array must be [page] so it re-fires "
            "when page changes (e.g. back to list and then to detail again)"
        )

    def test_batch_path_uses_first_draft_id(self):
        """Batch fallback must use r.drafts[0].id to fetch the first draft."""
        block = self._effect_block()
        assert "r.drafts[0].id" in block, (
            "Batch fallback path must use r.drafts[0].id to fetch the first draft "
            "(_draft_to_summary returns an 'id' field for each draft in the list)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3 — Three-state render
# ══════════════════════════════════════════════════════════════════════════════

class TestThreeStateRender:
    """Render block must show loading / error / ProformaDetailPage states."""

    def _render_block(self) -> str:
        src = _src()
        # Locate the render block by the data-testid anchor
        idx = src.find("proforma-detail-loading")
        assert idx != -1, (
            "index.html must contain data-testid='proforma-detail-loading' "
            "for the loading state shown while hydration API call is in flight"
        )
        # Use a 2000-char window: the three-state block spans ~700 chars after the anchor
        return src[max(0, idx - 800): idx + 1200]

    def test_loading_testid_exists(self):
        """Loading state must have data-testid='proforma-detail-loading'."""
        src = _src()
        assert "proforma-detail-loading" in src, (
            "Render must include data-testid='proforma-detail-loading' "
            "for browser-verifier to detect loading state"
        )

    def test_error_testid_exists(self):
        """Error state must have data-testid='proforma-detail-error'."""
        src = _src()
        assert "proforma-detail-error" in src, (
            "Render must include data-testid='proforma-detail-error' "
            "for browser-verifier to detect error state"
        )

    def test_error_has_back_button(self):
        """Error state must include a Back to Proforma list button."""
        src = _src()
        idx = src.find("proforma-detail-error")
        assert idx != -1
        surrounding = src[idx: idx + 400]
        assert "handleProformaBack" in surrounding or "Back" in surrounding, (
            "Error state must include a Back button so operator can recover"
        )

    def test_three_states_are_conditional_branches(self):
        """The three states must be in a single conditional block (not scattered)."""
        block = self._render_block()
        assert "proformaHydrating" in block, "Loading branch missing"
        assert "proformaHydrateError" in block, "Error branch missing"
        assert "ProformaDetailPage" in block, "Detail page branch missing"

    def test_blank_page_regression_guard(self):
        """The old bare `proformaDraft && <ProformaDetailPage` pattern must not exist.

        The old render condition `page === 'proforma_detail' && proformaDraft && (`
        caused a blank page on direct URL because proformaDraft starts null.
        The new render omits the bare `&& proformaDraft` guard (the three-state
        render handles this via the `proformaDraft ? ... : null` branch).
        """
        src = _src()
        # Old pattern that causes blank page: page === 'proforma_detail' && proformaDraft && (
        old_pattern = re.compile(
            r"page\s*===\s*['\"]proforma_detail['\"]\s*&&\s*proformaDraft\s*&&"
        )
        assert not old_pattern.search(src), (
            "The old render pattern `page === 'proforma_detail' && proformaDraft && (` "
            "must be removed — it causes blank page on direct URL navigation. "
            "The new three-state render uses proformaHydrating/proformaHydrateError/proformaDraft."
        )

    def test_proforma_detail_page_still_rendered(self):
        """ProformaDetailPage must still be rendered (three-state doesn't remove it)."""
        src = _src()
        assert "ProformaDetailPage" in src, (
            "ProformaDetailPage must still appear in index.html — "
            "the three-state render wraps it, not removes it"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4 — handleProformaDrill writes draft id to URL
# ══════════════════════════════════════════════════════════════════════════════

class TestDrillHandlerUrlWrite:
    """handleProformaDrill must persist ?draft=<id> in the URL for bookmarking."""

    def _drill_block(self) -> str:
        src = _src()
        idx = src.find("handleProformaDrill")
        assert idx != -1, "handleProformaDrill not found in index.html"
        return src[idx: idx + 600]

    def test_drill_writes_draft_param(self):
        """Drill handler must set 'draft' param on the URLSearchParams."""
        block = self._drill_block()
        assert "sp.set('draft'" in block or 'sp.set("draft"' in block, (
            "handleProformaDrill must call sp.set('draft', ...) so that "
            "the URL becomes /v2/proforma_detail?batch_id=X&draft=24 "
            "enabling bookmarks and browser refresh to work"
        )

    def test_drill_uses_draft_id(self):
        """Drill handler must use draft.id when setting the URL param."""
        block = self._drill_block()
        assert "draft.id" in block, (
            "handleProformaDrill must use draft.id to set ?draft= param"
        )

    def test_drill_updates_current_search(self):
        """Drill handler must update currentSearch state before pushState."""
        block = self._drill_block()
        assert "setCurrentSearch" in block, (
            "handleProformaDrill must call setCurrentSearch so that "
            "pageToUrl uses the fresh search string when computing href"
        )
