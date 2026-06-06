"""
test_pz_api_proforma_bridge.py
==============================
Regression tests: the 4 proforma lifecycle functions added to static/v2/pz-api.js
must exist and wire to the correct backend routes.

These are source-grep tests — no server required.

Roots the contract between:
  service/app/static/v2/pz-api.js          (transport layer)
  service/app/static/v2/proforma-detail.jsx (caller)
  service/app/api/routes_proforma.py         (backend)
"""
from __future__ import annotations

import re
from pathlib import Path

_V2_DIR    = Path(__file__).parent.parent / "app" / "static" / "v2"
_PZ_API_V2 = _V2_DIR / "pz-api.js"
_DETAIL    = _V2_DIR / "proforma-detail.jsx"
_ROUTES    = Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"


def _api() -> str:
    return _PZ_API_V2.read_text(encoding="utf-8")


def _detail() -> str:
    return _DETAIL.read_text(encoding="utf-8")


def _routes() -> str:
    return _ROUTES.read_text(encoding="utf-8")


# ── 1. Functions exist in V2 pz-api.js ───────────────────────────────────────

def test_v2_pz_api_has_post_draft_to_wfirma():
    assert "postDraftToWfirma:" in _api(), \
        "static/v2/pz-api.js must expose postDraftToWfirma"


def test_v2_pz_api_has_clone_draft():
    assert "cloneDraft:" in _api(), \
        "static/v2/pz-api.js must expose cloneDraft"


def test_v2_pz_api_has_draft_to_invoice():
    assert "draftToInvoice:" in _api(), \
        "static/v2/pz-api.js must expose draftToInvoice"


def test_v2_pz_api_has_get_draft_events():
    assert "getDraftEvents:" in _api(), \
        "static/v2/pz-api.js must expose getDraftEvents"


# ── 2. Endpoint paths in V2 pz-api.js match backend routes ───────────────────

def test_post_draft_to_wfirma_endpoint():
    src = _api()
    assert "/proforma/draft/${draftId}/post" in src, \
        "postDraftToWfirma must call /proforma/draft/{id}/post"


def test_clone_draft_endpoint():
    src = _api()
    assert "/proforma/draft/${draftId}/clone" in src, \
        "cloneDraft must call /proforma/draft/{id}/clone"


def test_draft_to_invoice_endpoint():
    src = _api()
    assert "/proforma/draft/${draftId}/to-invoice" in src, \
        "draftToInvoice must call /proforma/draft/{id}/to-invoice"


def test_get_draft_events_endpoint():
    src = _api()
    assert "/proforma/draft/${draftId}/events" in src, \
        "getDraftEvents must call /proforma/draft/{id}/events"


# ── 3. Transport helpers: mutations use _postM, reads use _get ────────────────

def test_post_draft_to_wfirma_uses_postM():
    src = _api()
    block = re.search(
        r"postDraftToWfirma:.*?(?=\n\s+//|\n\s+\w+:|\Z)", src, re.DOTALL
    )
    assert block and "_postM(" in block.group(), \
        "postDraftToWfirma must use _postM (requires X-Operator)"


def test_clone_draft_uses_postM():
    src = _api()
    block = re.search(
        r"cloneDraft:.*?(?=\n\s+//|\n\s+\w+:|\Z)", src, re.DOTALL
    )
    assert block and "_postM(" in block.group(), \
        "cloneDraft must use _postM (mutation — creates resource)"


def test_draft_to_invoice_uses_postM():
    src = _api()
    block = re.search(
        r"draftToInvoice:.*?(?=\n\s+//|\n\s+\w+:|\Z)", src, re.DOTALL
    )
    assert block and "_postM(" in block.group(), \
        "draftToInvoice must use _postM"


def test_get_draft_events_uses_get():
    src = _api()
    block = re.search(
        r"getDraftEvents:.*?(?=\n\s+//|\n\s+\w+:|\Z)", src, re.DOTALL
    )
    assert block and "_get(" in block.group(), \
        "getDraftEvents must use _get (read-only)"


# ── 4. Backend routes exist for all 4 endpoints ──────────────────────────────

def test_backend_route_post_exists():
    assert '"/draft/{draft_id}/post"' in _routes(), \
        "routes_proforma.py must define POST /draft/{draft_id}/post"


def test_backend_route_clone_exists():
    assert '"/draft/{draft_id}/clone"' in _routes(), \
        "routes_proforma.py must define POST /draft/{draft_id}/clone"


def test_backend_route_to_invoice_exists():
    assert '"/draft/{draft_id}/to-invoice"' in _routes(), \
        "routes_proforma.py must define POST /draft/{draft_id}/to-invoice"


def test_backend_route_events_exists():
    assert '"/draft/{draft_id}/events"' in _routes(), \
        "routes_proforma.py must define GET /draft/{draft_id}/events"


# ── 5. proforma-detail.jsx calls all 4 functions ─────────────────────────────

def test_detail_calls_clone_draft():
    assert "PzApi.cloneDraft(" in _detail(), \
        "proforma-detail.jsx must call PzApi.cloneDraft"


def test_detail_calls_get_draft_events():
    assert "PzApi.getDraftEvents(" in _detail(), \
        "proforma-detail.jsx must call PzApi.getDraftEvents"


def test_detail_calls_post_draft_to_wfirma():
    assert "PzApi.postDraftToWfirma(" in _detail(), \
        "proforma-detail.jsx must call PzApi.postDraftToWfirma"


def test_detail_calls_draft_to_invoice():
    assert "PzApi.draftToInvoice(" in _detail(), \
        "proforma-detail.jsx must call PzApi.draftToInvoice"
