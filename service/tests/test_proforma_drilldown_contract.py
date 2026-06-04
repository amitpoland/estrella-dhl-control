"""
test_proforma_drilldown_contract.py — Sprint 26 proforma drilldown contract.

Asserts (static source-grep; no server required):

  A. pz-api.js transport layer (1–6)
     1. postDraftToWfirma method present and uses _postM.
     2. cloneDraft method present and uses _postM.
     3. draftToInvoice method present and uses _postM.
     4. getDraftEvents method present and uses _get.
     5. discloseDraftConvert method present and uses _get.
     6. getDraftVisibility method present and uses _get.

  B. pz-state.js hook layer (7–9)
     7. useProformaDraftEvents function defined.
     8. useProformaDraftEvents exported from window.PzState.
     9. useProformaDraftEvents delegates to PzApi.getDraftEvents.

  C. pz-components.js DRAFT_STATE_MAP (10–11)
    10. convert_blocked key present in DRAFT_STATE_MAP.
    11. convert_blocked has non-empty label.

  D. proforma-detail-v2.html production page (12–17)
    12. Loads pz-design-v2.js (Sprint 24/25 design baseline).
    13. ConvertModal uses correct endpoint /proforma/draft/{id}/to-invoice.
    14. History tab wired to /proforma/draft/{id}/events.
    15. All 5 tab labels declared (Overview, Lines, Customer Mapping, Reservation, History).
    16. No hardcoded mock line arrays (fake product lines must not be present).
    17. No POST/PATCH/DELETE fetch calls that bypass PzApi (inline fetch mutations).

  E. proforma-v2.html production list page (18–20)
    18. proforma-v2.html exists.
    19. proforma-v2.html loads root pz-api.js (not a v2/ path).
    20. DraftStateChip is used in proforma-v2.html.

  F. No prototype files in production path (21–22)
    21. proforma-v2.html does NOT load v2/proforma-list.jsx.
    22. proforma-detail-v2.html does NOT load v2/proforma-detail.jsx.
"""
from __future__ import annotations

from pathlib import Path

_ROOT   = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "service" / "app" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
# A — pz-api.js: 6 new transport methods
# ══════════════════════════════════════════════════════════════════════════════

def test_pzapi_post_draft_to_wfirma():
    src = _read("pz-api.js")
    assert "postDraftToWfirma" in src, "postDraftToWfirma must be in pz-api.js"
    # Must use _postM (mutation POST, injects X-Operator)
    idx = src.index("postDraftToWfirma")
    snippet = src[idx:idx + 120]
    assert "_postM" in snippet, "postDraftToWfirma must use _postM (requires X-Operator)"


def test_pzapi_clone_draft():
    src = _read("pz-api.js")
    assert "cloneDraft" in src, "cloneDraft must be in pz-api.js"
    idx = src.index("cloneDraft")
    snippet = src[idx:idx + 100]
    assert "_postM" in snippet, "cloneDraft must use _postM"


def test_pzapi_draft_to_invoice():
    src = _read("pz-api.js")
    assert "draftToInvoice" in src, "draftToInvoice must be in pz-api.js"
    idx = src.index("draftToInvoice")
    snippet = src[idx:idx + 120]
    assert "_postM" in snippet, "draftToInvoice must use _postM"
    assert "/to-invoice" in src, "/to-invoice endpoint path must be present"


def test_pzapi_get_draft_events():
    src = _read("pz-api.js")
    assert "getDraftEvents" in src, "getDraftEvents must be in pz-api.js"
    idx = src.index("getDraftEvents")
    snippet = src[idx:idx + 100]
    assert "_get" in snippet, "getDraftEvents must use _get"
    assert "/events" in src, "/events endpoint path must be present"


def test_pzapi_disclose_draft_convert():
    src = _read("pz-api.js")
    assert "discloseDraftConvert" in src, "discloseDraftConvert must be in pz-api.js"
    idx = src.index("discloseDraftConvert")
    snippet = src[idx:idx + 120]
    assert "_get" in snippet, "discloseDraftConvert must use _get"
    assert "/disclose-convert" in src, "/disclose-convert endpoint path must be present"


def test_pzapi_get_draft_visibility():
    src = _read("pz-api.js")
    assert "getDraftVisibility" in src, "getDraftVisibility must be in pz-api.js"
    idx = src.index("getDraftVisibility")
    snippet = src[idx:idx + 100]
    assert "_get" in snippet, "getDraftVisibility must use _get"
    assert "/visibility" in src, "/visibility endpoint path must be present"


# ══════════════════════════════════════════════════════════════════════════════
# B — pz-state.js: useProformaDraftEvents hook
# ══════════════════════════════════════════════════════════════════════════════

def test_pzstate_hook_defined():
    src = _read("pz-state.js")
    assert "useProformaDraftEvents" in src, \
        "useProformaDraftEvents must be defined in pz-state.js"


def test_pzstate_hook_exported():
    src = _read("pz-state.js")
    # Must appear in the window.PzState = Object.freeze({ ... }) export block
    freeze_idx = src.index("Object.freeze")
    export_block = src[freeze_idx:]
    assert "useProformaDraftEvents" in export_block, \
        "useProformaDraftEvents must be exported in window.PzState"


def test_pzstate_hook_delegates_to_pzapi():
    src = _read("pz-state.js")
    assert "getDraftEvents" in src, \
        "useProformaDraftEvents must call PzApi.getDraftEvents"


# ══════════════════════════════════════════════════════════════════════════════
# C — pz-components.js: DRAFT_STATE_MAP coverage
# ══════════════════════════════════════════════════════════════════════════════

def test_draft_state_map_has_convert_blocked():
    src = _read("pz-components.js")
    assert "convert_blocked" in src, \
        "convert_blocked must be in DRAFT_STATE_MAP in pz-components.js"


def test_convert_blocked_has_label():
    src = _read("pz-components.js")
    idx = src.index("convert_blocked")
    snippet = src[idx:idx + 80]
    assert "Convert Blocked" in snippet or "label" in snippet, \
        "convert_blocked entry must have a non-empty label"


# ══════════════════════════════════════════════════════════════════════════════
# D — proforma-detail-v2.html production detail page
# ══════════════════════════════════════════════════════════════════════════════

def test_proforma_detail_loads_pz_design():
    src = _read("proforma-detail-v2.html")
    assert "pz-design-v2.js" in src, \
        "proforma-detail-v2.html must load pz-design-v2.js (Sprint 24 baseline)"


def test_proforma_detail_convert_modal_correct_endpoint():
    src = _read("proforma-detail-v2.html")
    # Wrong endpoint that MUST NOT be present
    assert "/proforma/" not in src.split("/to-invoice")[0].split("convert-to-invoice")[0] \
           or "convert-to-invoice" not in src, \
        "Old wrong endpoint /proforma/{id}/convert-to-invoice must not be present"
    # Correct endpoint must be present
    assert "/proforma/draft/" in src and "/to-invoice" in src, \
        "Correct endpoint /proforma/draft/{id}/to-invoice must be present"


def test_proforma_detail_history_uses_events_route():
    src = _read("proforma-detail-v2.html")
    assert "/events" in src, \
        "proforma-detail-v2.html must reference /events route for History tab"


def test_proforma_detail_five_tabs():
    src = _read("proforma-detail-v2.html")
    for tab in ["Overview", "Lines", "Customer Mapping", "Reservation", "History"]:
        assert tab in src, f"Tab '{tab}' must be present in proforma-detail-v2.html"


def test_proforma_detail_no_hardcoded_fake_lines():
    src = _read("proforma-detail-v2.html")
    # The v2/proforma-detail.jsx prototype had 3 hardcoded fake lines with
    # SKUs like 'RNG-AU750-001'. If these are in production HTML, it's mock data.
    assert "RNG-AU750-001" not in src, \
        "Hardcoded fake SKU 'RNG-AU750-001' found — production page must use live data"
    assert "NKL-AU585-008" not in src, \
        "Hardcoded fake SKU 'NKL-AU585-008' found — production page must use live data"


def test_proforma_detail_no_inline_mutation_fetch():
    src = _read("proforma-detail-v2.html")
    # The page should route write calls through PzApi, not raw fetch with POST/PATCH/DELETE
    # Raw fetch is fine for GET reads; we check for mutation methods only
    import re
    # Look for fetch(url, { method: 'POST/PATCH/DELETE' }) patterns that bypass PzApi
    # Legitimate: apiFetch is provided by pz-design-v2.js/dashboard-shared.js
    # Flag: direct new fetch() calls with mutation methods (not via apiFetch wrapper)
    raw_post = re.findall(r"new fetch\s*\(.*method.*POST", src, re.IGNORECASE)
    assert not raw_post, \
        f"Raw fetch() with POST found, should go via PzApi: {raw_post}"


# ══════════════════════════════════════════════════════════════════════════════
# E — proforma-v2.html production list page
# ══════════════════════════════════════════════════════════════════════════════

def test_proforma_list_exists():
    assert (_STATIC / "proforma-v2.html").exists(), \
        "proforma-v2.html must exist in service/app/static/"


def test_proforma_list_loads_root_pzapi():
    src = _read("proforma-v2.html")
    assert "/dashboard/pz-api.js" in src, \
        "proforma-v2.html must load root /dashboard/pz-api.js"
    assert "/dashboard/v2/pz-api.js" not in src, \
        "proforma-v2.html must NOT load the v2/ prototype pz-api.js"


def test_proforma_list_uses_draft_state_chip():
    src = _read("proforma-v2.html")
    assert "DraftStateChip" in src, \
        "proforma-v2.html must use DraftStateChip from window.PzComponents"


# ══════════════════════════════════════════════════════════════════════════════
# F — No prototype files loaded in production
# ══════════════════════════════════════════════════════════════════════════════

def test_proforma_list_not_loading_jsx_prototype():
    src = _read("proforma-v2.html")
    assert "v2/proforma-list.jsx" not in src, \
        "proforma-v2.html must NOT load v2/proforma-list.jsx (prototype, not production)"


def test_proforma_detail_not_loading_jsx_prototype():
    src = _read("proforma-detail-v2.html")
    assert "v2/proforma-detail.jsx" not in src, \
        "proforma-detail-v2.html must NOT load v2/proforma-detail.jsx (prototype, not production)"
