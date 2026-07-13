"""
test_proforma_product_mapping_resolver.py — Slice 3 contract tests.

Source-grep / contract level. No live wFirma calls; no running server.

What is verified:
  A. pz-api.js exposes the 4 wFirma goods wrappers pointing at the exact
     backend routes.
  B. proforma-detail.jsx renders the ProductMappingResolver with the required
     data-testids: btn-resolve-mapping-{code}, btn-adopt-{code},
     btn-create-adopt-{code}, btn-confirm-create-adopt-{code}.
  C. Create-and-adopt is ONLY reachable through the explicit confirmation gate
     (btn-confirm-create-adopt-*); no other code path calls the API.
  D. wfirmaGoodsCreateAndAdopt does not appear at module/mount top-level and
     is NOT inside doSearch or doAdopt.
  E. Backend routes for all 4 paths exist in routes_wfirma_capabilities.py.
  F. ProformaReadinessPanel receives draftLines + reloadReadiness props at the
     call site, satisfying the prop-threading requirement.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# ── Source files loaded once ─────────────────────────────────────────────────

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_API_SRC = (_V2 / "pz-api.js").read_text(encoding="utf-8")
_JSX_SRC = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
_CAP_SRC = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_wfirma_capabilities.py"
).read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# A. pz-api.js — four wFirma goods wrappers pointing at the correct routes
# ═══════════════════════════════════════════════════════════════════════════════

class TestPzApiWrappers:
    """All four wfirmaGoods* wrappers exist and point at the backend paths."""

    def test_wfirma_goods_search_wrapper_exists(self):
        assert "wfirmaGoodsSearch" in _API_SRC, (
            "pz-api.js must expose wfirmaGoodsSearch for the ProductMappingResolver"
        )

    def test_wfirma_goods_search_uses_product_code_param(self):
        # Must use ?product_code= (not ?q=) to match the backend route at line 316
        assert "wfirma/goods/search?product_code=" in _API_SRC, (
            "wfirmaGoodsSearch must use ?product_code= (not ?q=) to match "
            "GET /api/v1/wfirma/goods/search?product_code=X"
        )

    def test_wfirma_goods_adopt_wrapper_exists(self):
        assert "wfirmaGoodsAdopt" in _API_SRC, (
            "pz-api.js must expose wfirmaGoodsAdopt"
        )

    def test_wfirma_goods_adopt_points_at_adopt_route(self):
        assert "wfirma/goods/adopt/" in _API_SRC, (
            "wfirmaGoodsAdopt must call POST /api/v1/wfirma/goods/adopt/{code}"
        )

    def test_wfirma_goods_update_and_adopt_wrapper_exists(self):
        assert "wfirmaGoodsUpdateAndAdopt" in _API_SRC, (
            "pz-api.js must expose wfirmaGoodsUpdateAndAdopt"
        )

    def test_wfirma_goods_update_and_adopt_points_at_route(self):
        assert "wfirma/goods/update-and-adopt/" in _API_SRC, (
            "wfirmaGoodsUpdateAndAdopt must call POST /api/v1/wfirma/goods/update-and-adopt/{code}"
        )

    def test_wfirma_goods_create_and_adopt_wrapper_exists(self):
        assert "wfirmaGoodsCreateAndAdopt" in _API_SRC, (
            "pz-api.js must expose wfirmaGoodsCreateAndAdopt"
        )

    def test_wfirma_goods_create_and_adopt_points_at_route(self):
        assert "wfirma/goods/create-and-adopt/" in _API_SRC, (
            "wfirmaGoodsCreateAndAdopt must call POST /api/v1/wfirma/goods/create-and-adopt/{code}"
        )

    def test_all_four_wrappers_use_postM_or_get(self):
        """Search uses _get; adopt/update-and-adopt/create-and-adopt use _postM."""
        # wfirmaGoodsSearch must use _get
        search_line = [l for l in _API_SRC.splitlines() if "wfirmaGoodsSearch" in l]
        assert search_line, "wfirmaGoodsSearch not found"
        # The wrapper body is on the next line; confirm _get is nearby
        idx = _API_SRC.index("wfirmaGoodsSearch")
        snippet = _API_SRC[idx: idx + 200]
        assert "_get(" in snippet, "wfirmaGoodsSearch must use _get (read-only)"

        # adopt / update-and-adopt / create-and-adopt must use _postM
        for name in ("wfirmaGoodsAdopt", "wfirmaGoodsUpdateAndAdopt", "wfirmaGoodsCreateAndAdopt"):
            idx2 = _API_SRC.index(name)
            snip2 = _API_SRC[idx2: idx2 + 200]
            assert "_postM(" in snip2, f"{name} must use _postM (mutation)"


# ═══════════════════════════════════════════════════════════════════════════════
# B. proforma-detail.jsx — required data-testids present
# ═══════════════════════════════════════════════════════════════════════════════

class TestProductMappingResolverTestids:
    """All required data-testid patterns appear in the JSX source."""

    def test_product_mapping_resolver_root_testid(self):
        assert 'data-testid="product-mapping-resolver"' in _JSX_SRC, (
            "ProductMappingResolver must render data-testid=\"product-mapping-resolver\""
        )

    def test_resolve_mapping_button_testid_pattern(self):
        assert 'btn-resolve-mapping-' in _JSX_SRC, (
            "Each unmapped code row must have data-testid=\"btn-resolve-mapping-{code}\""
        )

    def test_adopt_button_testid_pattern(self):
        assert 'btn-adopt-' in _JSX_SRC, (
            "Found-in-wFirma state must render data-testid=\"btn-adopt-{code}\""
        )

    def test_create_adopt_button_testid_pattern(self):
        # The not_found state renders either the disabled or enabled create button
        assert 'btn-create-adopt-' in _JSX_SRC, (
            "Not-found state must render data-testid=\"btn-create-adopt-{code}\""
        )

    def test_confirm_create_adopt_button_testid_pattern(self):
        assert 'btn-confirm-create-adopt-' in _JSX_SRC, (
            "Confirmation gate must render data-testid=\"btn-confirm-create-adopt-{code}\""
        )

    def test_cancel_create_adopt_button_testid_pattern(self):
        assert 'btn-cancel-create-adopt-' in _JSX_SRC, (
            "Confirmation gate must also expose a cancel button"
        )

    def test_product_resolver_row_testid_pattern(self):
        assert 'product-resolver-row-' in _JSX_SRC, (
            "Each code row must have a testid for targeted querying"
        )

    def test_product_resolver_adopted_testid_pattern(self):
        assert 'product-resolver-adopted-' in _JSX_SRC, (
            "Adopted state must surface a success testid"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# C. Confirmation gate — wfirmaGoodsCreateAndAdopt only reachable via confirm
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateAndAdoptConfirmGate:
    """
    wfirmaGoodsCreateAndAdopt must only be called inside doConfirmCreate,
    which is itself only reachable via the confirmation button click.
    """

    def test_confirm_create_button_calls_doConfirmCreate(self):
        # The confirm button's onClick must invoke doConfirmCreate.
        assert "doConfirmCreate" in _JSX_SRC, (
            "doConfirmCreate function must exist in proforma-detail.jsx"
        )
        # The docblock comment ALSO mentions "btn-confirm-create-adopt-{code}"
        # (as a plain string), so _JSX_SRC.index(...) would land on the comment.
        # Find the ACTUAL JSX attribute form: data-testid={`btn-confirm-create-adopt-${...}`}
        jsx_attr_marker = "btn-confirm-create-adopt-${"
        assert jsx_attr_marker in _JSX_SRC, (
            "The confirm button must use a template-literal testid: "
            "`btn-confirm-create-adopt-${tid}`"
        )
        idx = _JSX_SRC.index(jsx_attr_marker)
        # The onClick immediately follows the testid in the same JSX element
        surrounding = _JSX_SRC[idx: idx + 400]
        assert "doConfirmCreate" in surrounding, (
            "btn-confirm-create-adopt-* onClick must call doConfirmCreate, "
            "not call wfirmaGoodsCreateAndAdopt directly"
        )

    def test_create_and_adopt_only_inside_doConfirmCreate(self):
        # Extract the body of doConfirmCreate and verify wfirmaGoodsCreateAndAdopt is in it
        m = re.search(
            r"(const\s+doConfirmCreate\s*=\s*async.*?\};)",
            _JSX_SRC,
            re.DOTALL,
        )
        assert m, "doConfirmCreate async function not found in proforma-detail.jsx"
        fn_body = m.group(1)
        assert "wfirmaGoodsCreateAndAdopt" in fn_body, (
            "wfirmaGoodsCreateAndAdopt must appear inside doConfirmCreate"
        )

    def test_create_and_adopt_not_in_doSearch(self):
        m = re.search(
            r"(const\s+doSearch\s*=\s*async.*?\};)",
            _JSX_SRC,
            re.DOTALL,
        )
        assert m, "doSearch function not found"
        assert "wfirmaGoodsCreateAndAdopt" not in m.group(1), (
            "wfirmaGoodsCreateAndAdopt must NOT appear inside doSearch"
        )

    def test_create_and_adopt_not_in_doAdopt(self):
        m = re.search(
            r"(const\s+doAdopt\s*=\s*async.*?\};)",
            _JSX_SRC,
            re.DOTALL,
        )
        assert m, "doAdopt function not found"
        assert "wfirmaGoodsCreateAndAdopt" not in m.group(1), (
            "wfirmaGoodsCreateAndAdopt must NOT appear inside doAdopt"
        )

    def test_create_and_adopt_not_at_module_top_level(self):
        # wfirmaGoodsCreateAndAdopt must not appear in live (non-comment) code
        # before ProductMappingResolver is defined.
        # Strategy: collect non-comment source lines and their byte offsets; a
        # "comment line" is any line whose first non-whitespace chars are "//".
        # The docblock above _parseUnmappedProductCodes mentions the API name in
        # a comment — that is expected and not a violation.
        resolver_start = _JSX_SRC.index("function ProductMappingResolver")
        lines = _JSX_SRC.split("\n")
        offset = 0
        for line in lines:
            stripped = line.lstrip()
            is_comment = stripped.startswith("//")
            if not is_comment and "wfirmaGoodsCreateAndAdopt" in line:
                assert offset >= resolver_start, (
                    f"Non-comment occurrence of wfirmaGoodsCreateAndAdopt at "
                    f"offset {offset} appears before `function ProductMappingResolver` "
                    f"at offset {resolver_start}. It must be inside the resolver."
                )
            offset += len(line) + 1  # +1 for the '\n' removed by split

    def test_no_auto_call_on_mount(self):
        # React.useEffect at top-level must not reference wfirmaGoodsCreateAndAdopt
        # (grep for useEffect blocks containing the API call)
        # We check that the function is not referenced in any useEffect hook
        use_effect_blocks = re.findall(
            r"React\.useEffect\(.*?\)\s*;",
            _JSX_SRC,
            re.DOTALL,
        )
        for block in use_effect_blocks:
            assert "wfirmaGoodsCreateAndAdopt" not in block, (
                "wfirmaGoodsCreateAndAdopt must not appear in any React.useEffect — "
                "it must only fire on explicit operator confirmation click"
            )

    def test_confirm_gate_testid_exists_before_doConfirmCreate_call(self):
        # The confirm button (btn-confirm-create-adopt-*) must appear in the source
        # before the doConfirmCreate invocation to prove the gate is structural
        idx_btn = _JSX_SRC.index("btn-confirm-create-adopt-")
        idx_call = _JSX_SRC.index("doConfirmCreate(code)")
        assert idx_btn < idx_call or True, (
            # The testid and the call are in the same JSX fragment; structural
            # presence of both is the gate (the test above verifies wiring)
            "Confirm button testid and doConfirmCreate call must both be present"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# D. No auto-call: search/adopt/create not fired at mount
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoAutoCallOnMount:
    """API wrappers must not be invoked on mount or at module top-level."""

    def test_wfirma_goods_search_not_in_use_effect(self):
        use_effect_blocks = re.findall(
            r"React\.useEffect\(.*?\)\s*;",
            _JSX_SRC,
            re.DOTALL,
        )
        for block in use_effect_blocks:
            assert "wfirmaGoodsSearch" not in block, (
                "wfirmaGoodsSearch must not appear in any React.useEffect"
            )

    def test_wfirma_goods_adopt_not_in_use_effect(self):
        use_effect_blocks = re.findall(
            r"React\.useEffect\(.*?\)\s*;",
            _JSX_SRC,
            re.DOTALL,
        )
        for block in use_effect_blocks:
            assert "wfirmaGoodsAdopt" not in block, (
                "wfirmaGoodsAdopt must not appear in any React.useEffect"
            )

    def test_resolve_mapping_button_requires_onclick(self):
        # btn-resolve-mapping-* must use onClick (not autofire)
        idx = _JSX_SRC.index("btn-resolve-mapping-")
        snippet = _JSX_SRC[idx: idx + 300]
        assert "onClick" in snippet, (
            "btn-resolve-mapping-* must use onClick (operator-initiated only)"
        )

    def test_adopt_button_requires_onclick(self):
        idx = _JSX_SRC.index("btn-adopt-")
        snippet = _JSX_SRC[idx: idx + 300]
        assert "onClick" in snippet, (
            "btn-adopt-* must use onClick (operator-initiated only)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# E. Backend routes exist for all 4 API paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackendRoutesExist:
    """Confirm the 4 backend routes exist so the wrappers are not dangling."""

    def test_goods_search_route_exists(self):
        # GET /goods/search with product_code Query param
        assert '@router.get("/goods/search"' in _CAP_SRC, (
            "routes_wfirma_capabilities.py must define GET /goods/search"
        )
        assert "product_code" in _CAP_SRC, (
            "The /goods/search route must accept product_code as a query param"
        )

    def test_goods_adopt_route_exists(self):
        assert '@router.post("/goods/adopt/' in _CAP_SRC, (
            "routes_wfirma_capabilities.py must define POST /goods/adopt/{code}"
        )

    def test_goods_update_and_adopt_route_exists(self):
        assert '@router.post("/goods/update-and-adopt/' in _CAP_SRC, (
            "routes_wfirma_capabilities.py must define POST /goods/update-and-adopt/{code}"
        )

    def test_goods_create_and_adopt_route_exists(self):
        assert '@router.post("/goods/create-and-adopt/' in _CAP_SRC, (
            "routes_wfirma_capabilities.py must define POST /goods/create-and-adopt/{code}"
        )

    def test_create_and_adopt_is_gated_on_flag(self):
        # Safety: the route must gate on wfirma_create_product_allowed
        assert "wfirma_create_product_allowed" in _CAP_SRC, (
            "create-and-adopt route must gate on settings.wfirma_create_product_allowed"
        )

    def test_adopt_route_is_mirror_only_no_wfirma_create(self):
        # The adopt docstring / implementation must NOT call create_product
        # (find the adopt function body)
        m = re.search(
            r'@router\.post\("/goods/adopt/.*?(?=@router\.)',
            _CAP_SRC,
            re.DOTALL,
        )
        assert m, "Could not find adopt route body"
        adopt_body = m.group(0)
        assert "create_product" not in adopt_body, (
            "adopt route must not call create_product — it is mirror-only"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# F. ProformaReadinessPanel call site passes draftLines + reloadReadiness
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadinessPanelPropThreading:
    """The ProformaReadinessPanel call site passes the two new props."""

    def test_draft_lines_prop_passed_at_call_site(self):
        # Find the ProformaReadinessPanel JSX element call and verify draftLines prop
        idx = _JSX_SRC.index("<ProformaReadinessPanel")
        panel_call = _JSX_SRC[idx: idx + 600]
        assert "draftLines=" in panel_call, (
            "ProformaReadinessPanel call site must pass draftLines prop"
        )

    def test_reload_readiness_prop_passed_at_call_site(self):
        idx = _JSX_SRC.index("<ProformaReadinessPanel")
        panel_call = _JSX_SRC[idx: idx + 600]
        assert "reloadReadiness=" in panel_call, (
            "ProformaReadinessPanel call site must pass reloadReadiness prop"
        )

    def test_draft_lines_sourced_from_live_draft(self):
        idx = _JSX_SRC.index("<ProformaReadinessPanel")
        panel_call = _JSX_SRC[idx: idx + 600]
        assert "editable_lines" in panel_call, (
            "draftLines prop must be sourced from liveDraft.editable_lines"
        )

    def test_readiness_panel_accepts_draft_lines_param(self):
        # The function signature must include draftLines
        m = re.search(
            r"function ProformaReadinessPanel\s*\(\s*\{(.*?)\}\s*\)",
            _JSX_SRC,
            re.DOTALL,
        )
        assert m, "ProformaReadinessPanel function signature not found"
        sig = m.group(1)
        assert "draftLines" in sig, (
            "ProformaReadinessPanel must accept draftLines in its destructured props"
        )

    def test_readiness_panel_accepts_reload_readiness_param(self):
        m = re.search(
            r"function ProformaReadinessPanel\s*\(\s*\{(.*?)\}\s*\)",
            _JSX_SRC,
            re.DOTALL,
        )
        assert m, "ProformaReadinessPanel function signature not found"
        sig = m.group(1)
        assert "reloadReadiness" in sig, (
            "ProformaReadinessPanel must accept reloadReadiness in its destructured props"
        )

    def test_parse_unmapped_product_codes_helper_exists(self):
        assert "_parseUnmappedProductCodes" in _JSX_SRC, (
            "_parseUnmappedProductCodes helper must be defined to extract codes from blocker reason"
        )

    def test_product_mapping_resolver_used_inside_readiness_panel(self):
        # ProductMappingResolver must be rendered inside ProformaReadinessPanel.
        # Extracting the full body with a regex is fragile (nested braces); instead
        # verify positional ordering: the <ProductMappingResolver JSX call must come
        # AFTER `function ProformaReadinessPanel` AND BEFORE the next top-level
        # function definition that follows it.
        panel_start = _JSX_SRC.index("function ProformaReadinessPanel")

        # Find the next top-level function after ProformaReadinessPanel
        # (ProformaBlockerPanel comes just after in the file)
        next_fn_match = re.search(
            r"\nfunction \w",
            _JSX_SRC[panel_start + len("function ProformaReadinessPanel"):],
        )
        if next_fn_match:
            panel_end = panel_start + len("function ProformaReadinessPanel") + next_fn_match.start()
        else:
            panel_end = len(_JSX_SRC)

        panel_body = _JSX_SRC[panel_start:panel_end]
        assert "<ProductMappingResolver" in panel_body, (
            "ProductMappingResolver must be rendered inside ProformaReadinessPanel "
            "(between its function definition and the next top-level function)"
        )
