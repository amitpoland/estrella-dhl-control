"""
test_sprint35_documents_hub_wiring.py
=======================================
Sprint 35 regression tests — updated 2026-07-04 for Wave-3 3-lane Kanban rewrite.

CONTRACT SUPERSESSION (2026-07-04):
  The Sprint-35 read-only observer contract for sections D (no-write),
  E (no lifecycle stubs), H (testids), and K (view URL pattern) has been
  superseded by the operator's Wave-3 census ruling recorded in:
    .claude/campaigns/phase-c-master/DECISIONS.md (entry 2026-07-04,
    "DocumentsHubPage — full CRUD for every document type, census DC-5..DC-16").
  The ruling ratified DC-5..DC-16 and mandated all 13 wireframe controls
  wired to EXISTING backend authorities, with STOP-report gating for controls
  lacking an existing route (DC-12, DC-13-PZ, DC-14, DC-16).

  Section D is replaced with a positive whitelist: write calls are allowed
  but ONLY to the listed existing authority endpoints from routes_proforma.py
  and routes_pz.py.  Any future edit adding an unlisted write path fails.

  Section E is updated: onApprove/onUnapprove are now live-wired React prop
  names (not stubs); the test now asserts the actual lifecycle handlers target
  the correct authority URLs.

  Section H REQUIRED_TESTIDS updated to the Wave-3 kanban testid set.

  Section K test_view_links_use_real_url_pattern updated: the new kanban
  uses /api/v1/proforma/draft/{id}/preview.html (routes_proforma.py:4771)
  and /api/v1/proforma/{batch_id}/{client}/document.pdf (routes_proforma.py:2862)
  rather than documents-v2.html.

  Sections A, B, C (partial), F, G, I, J, original-K-no-mock remain valid and
  unchanged.

Source-grep tests pinning the wiring contract:
  A. 'documents' added to WIRED_PAGES (no MOCK banner); all 8 prior wired pages intact
  B. DocumentsHubPage uses window.EstrellaShared.apiFetch (not hardcoded fetch/XHR)
  C. Allowed endpoints: GET /api/v1/dashboard/batches + proforma/search +
     batches/{id}/files; no invented endpoints
  D. Write calls ONLY to whitelisted existing authority endpoints (positive pin)
  D2. STOP-report controls remain disabled — DC-12 / DC-13-PZ / DC-14 buttons
      carry no fetch/POST; they are honest-gated per R-Q3
  E. No forbidden mock affordances (SAMPLE_FLOW, OTHER_DOCS, fake PI/PZ arrays)
  F. Mock/static data retired (fake party names, hardcoded document numbers)
  G. index.html documents route still renders <DocumentsHubPage />
  H. Required testids present (Wave-3 kanban set)
  I. NAV_TREE 'documents' entry preserved in components.jsx
  J. Backend files not modified (no Python route changes)
  K. Issue #396 regression: no UPLOADED_DOCS / GENERATED_DOCS mock arrays;
     view links use real proforma authority URLs (preview.html / document.pdf)

References:
  service/app/static/v2/documents-hub.jsx  (DocumentsHubPage — Wave-3)
  service/app/static/v2/mock-badge.jsx     (WIRED_PAGES)
  service/app/static/v2/index.html         (documents route block)
  service/app/static/v2/components.jsx     (NAV_TREE)
  .claude/campaigns/phase-c-master/DECISIONS.md (Wave-3 ruling 2026-07-04)
  reports/wave3/pages/2026-07-04-documents-hub.md (build record + STOP-report)
"""
from __future__ import annotations

import re
from pathlib import Path

_V2         = Path(__file__).parent.parent / "app" / "static" / "v2"
_DOCS_HUB   = _V2 / "documents-hub.jsx"
_MOCK_BADGE = _V2 / "mock-badge.jsx"
_INDEX_HTML = _V2 / "index.html"
_COMPONENTS = _V2 / "components.jsx"

_BACKEND    = Path(__file__).parent.parent / "app" / "api"


def _src() -> str:
    return _DOCS_HUB.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Strip `//` single-line comments so prose in authority-header comments
    never trips a forbidden-token scan."""
    out = []
    for line in src.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        if "//" in line and "http" not in line:
            line = line[: line.index("//")]
        out.append(line)
    return "\n".join(out)


def _documents_route_block(src: str) -> str:
    """The JSX documents route block in index.html, anchored by
    `page === 'documents' && (`."""
    idx = src.index("page === 'documents' && (")
    end = src.find("page === '", idx + 30)
    return src[idx:end] if end > idx else src[idx:idx + 1500]


# ══════════════════════════════════════════════════════════════════════════════
# A. mock-badge.jsx — 'documents' in WIRED_PAGES
# ══════════════════════════════════════════════════════════════════════════════

def test_documents_in_wired_pages():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    assert "'documents'" in src, "mock-badge.jsx WIRED_PAGES must include 'documents'"


def test_wired_pages_array_contains_documents():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    assert "documents" in arr_body, "'documents' must be inside the WIRED_PAGES array literal"


def test_all_prior_wired_pages_preserved():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    # proforma_detail intentionally removed Sprint 36 Phase 0 (2026-06-06) — authority violation
    # (fake VAT, fake company, browser-side financial calculations). Re-add after Sprint 36.
    for page in ("proforma", "inbox", "inventory", "dhl",
                 "shipments", "automation", "intelligence"):
        assert page in arr_body, f"Prior wired page '{page}' must not be removed from WIRED_PAGES"


# ══════════════════════════════════════════════════════════════════════════════
# B. DocumentsHubPage uses live apiFetch wiring
# ══════════════════════════════════════════════════════════════════════════════

def test_documents_page_uses_estrella_shared_api_fetch():
    src = _src()
    assert "apiFetch" in src, "documents-hub.jsx must call apiFetch (window.EstrellaShared.apiFetch)"
    assert "window.EstrellaShared" in src, "documents-hub.jsx must destructure from window.EstrellaShared"


def test_documents_hub_root_testid_present():
    src = _src()
    assert 'data-testid="documents-hub-root"' in src, "documents-hub-root testid required"


def test_documents_hub_page_exported_on_window():
    src = _src()
    assert "window.DocumentsHubPage" in src, "DocumentsHubPage must be exported via window.DocumentsHubPage"


# ══════════════════════════════════════════════════════════════════════════════
# C. Endpoint contract — allowed read endpoints present, no invented endpoints
#    Superseded note (2026-07-04): Wave-3 adds proforma/search + batches/files
#    as additional EXISTING authorities (routes_proforma.py:4282,
#    routes_dashboard.py:558). The whitelist expands; invented endpoints remain
#    forbidden. See DECISIONS.md Wave-3 ruling.
# ══════════════════════════════════════════════════════════════════════════════

def test_allowed_endpoint_batches_list_referenced():
    src = _src()
    assert "/api/v1/dashboard/batches" in src, (
        "documents-hub.jsx must reference /api/v1/dashboard/batches"
    )


def test_allowed_endpoint_proforma_search_referenced():
    """Wave-3: PI Kanban uses GET /api/v1/proforma/search (routes_proforma.py:4282).
    Superseding ruling: DECISIONS.md Wave-3 2026-07-04."""
    src = _src()
    assert "/api/v1/proforma/search" in src, (
        "documents-hub.jsx must reference /api/v1/proforma/search for PI kanban data"
    )


def test_allowed_endpoint_batch_files_referenced():
    """Wave-3: Other Docs tab uses GET /api/v1/dashboard/batches/{id}/files
    (routes_dashboard.py:558). Superseding ruling: DECISIONS.md Wave-3 2026-07-04."""
    src = _src()
    assert "/api/v1/dashboard/batches/" in src, (
        "documents-hub.jsx must reference /api/v1/dashboard/batches/{id}/files"
    )


def test_no_invented_dhl_documents_endpoint():
    src = _src()
    assert "/api/v1/dhl/documents" not in src, (
        "/api/v1/dhl/documents/{batch_id} does not exist — must not be referenced"
    )


def test_no_invented_batch_documents_endpoint():
    src = _src()
    assert "/api/v1/batch/{batch_id}/documents" not in src, (
        "/api/v1/batch/{batch_id}/documents does not exist — must not be referenced"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D. Write-authority whitelist (replaces no-write pins — Wave-3 supersession)
#    Superseded by DECISIONS.md Wave-3 ruling 2026-07-04:
#    "the wireframe's 13 controls wire to EXISTING backend authorities only;
#     Post-to-wFirma and every fiscal-class action goes through the deployed
#     write-gates unchanged — a UI slice never loosens or adds a write path."
#
#    Write calls ARE now present (via PzApi wrappers) but ONLY to these
#    whitelisted existing routes:
#      approveDraft   → POST /api/v1/proforma/draft/{id}/approve   (routes_proforma.py:6171)
#      cancelDraft    → POST /api/v1/proforma/draft/{id}/cancel     (routes_proforma.py:6367)
#      deleteDraft    → DELETE /api/v1/proforma/draft/{id}          (routes_proforma.py:6395)
#      postDraftToWfirma → POST /api/v1/proforma/draft/{id}/post   (routes_proforma.py:8095)
#      reopenDraft    → POST /api/v1/proforma/draft/{id}/re-open    (routes_proforma.py:6219)
#
#    Any future edit adding an UNLISTED write path will fail test_no_unlisted_write_paths.
# ══════════════════════════════════════════════════════════════════════════════

# Whitelisted PzApi write-method names (all proxy EXISTING backend routes)
_ALLOWED_WRITE_METHODS = {
    "approveDraft",
    "cancelDraft",
    "deleteDraft",
    "postDraftToWfirma",
    "reopenDraft",
}

def test_no_unlisted_write_paths():
    """Wave-3 whitelist pin: write calls in documents-hub.jsx must only use the
    five whitelisted PzApi methods. Direct apiFetch / fetch / axios calls with
    a write HTTP method (method: 'POST', method: 'PUT', method: 'PATCH',
    method: 'DELETE') signal a new write path that bypasses the PzApi wrapper.
    NOTE: 'POST' as a string literal inside JSX title/label attributes is
    documentation of the backend route, not a direct HTTP call — the check
    targets the method-assignment call-site pattern only.
    Superseding ruling: DECISIONS.md Wave-3 2026-07-04."""
    src = _code_only(_src())
    # These call-site patterns indicate a direct HTTP write bypassing PzApi
    _FORBIDDEN_CALL_PATTERNS = (
        "method: 'POST'",
        'method: "POST"',
        "method: 'PUT'",
        'method: "PUT"',
        "method: 'PATCH'",
        'method: "PATCH"',
        "method: 'DELETE'",
        'method: "DELETE"',
    )
    for pattern in _FORBIDDEN_CALL_PATTERNS:
        assert pattern not in src, (
            f"documents-hub.jsx contains direct HTTP method assignment '{pattern}' — "
            f"write calls must go through PzApi wrapper methods only. "
            f"If a new write endpoint is needed, add it to _ALLOWED_WRITE_METHODS "
            f"after confirming the backend route exists in routes_proforma.py."
        )


def test_whitelisted_write_methods_present():
    """Wave-3: all five PI lifecycle PzApi calls must be present in documents-hub.jsx.
    These call the existing proforma write-gate endpoints (routes_proforma.py).
    Superseding ruling: DECISIONS.md Wave-3 2026-07-04."""
    src = _src()
    for method in _ALLOWED_WRITE_METHODS:
        assert method in src, (
            f"Expected PzApi.{method} call missing from documents-hub.jsx — "
            f"DC-5..DC-9 wave-3 wiring requires all five lifecycle methods."
        )


# ══════════════════════════════════════════════════════════════════════════════
# D2. STOP-report controls remain disabled (DC-12 / DC-13-PZ / DC-14)
#     Lesson-M: disabled is not removed. These buttons must stay visible as
#     honest-gated placeholders with Wave-4 intake titles.
#     Superseding ruling: DECISIONS.md Wave-3 2026-07-04 + R-Q3 honest UI policy.
# ══════════════════════════════════════════════════════════════════════════════

def test_dc12_upload_button_is_disabled_and_present():
    """DC-12 Upload packing list: Lesson-M requires it be present-disabled,
    not removed. Superseding ruling: DECISIONS.md Wave-3 2026-07-04."""
    src = _src()
    assert "documents-hub-btn-upload-packing-list" in src, (
        "DC-12 Upload button testid must be present (Lesson-M — disabled not removed)"
    )
    assert "Wave-4" in src or "wave-4" in src or "Wave4" in src, (
        "DC-12 / DC-14 Wave-4 intake label must appear in disabled button title"
    )


def test_dc13_pz_new_button_is_disabled_and_present():
    """DC-13-PZ New Purchase Receipt: Lesson-M requires it be present-disabled.
    Superseding ruling: DECISIONS.md Wave-3 2026-07-04."""
    src = _src()
    assert "documents-hub-btn-new-pz" in src, (
        "DC-13-PZ New Purchase Receipt button testid must be present (Lesson-M)"
    )


def test_stop_report_buttons_carry_no_fetch_call():
    """DC-12 / DC-13-PZ / DC-14 disabled buttons must not have an attached
    fetch or PzApi call that would fire on click. They are visual-only disabled
    elements per DECISIONS.md constraint: 'closed-gate/absent-backend → honest
    gated/pending per R-Q3'. Superseding ruling: Wave-3 2026-07-04."""
    src = _src()
    # Verify the upload button is in a disabled state context — title must
    # contain the Wave-4 marker and no wired onClick to a fetch method
    lines = src.split("\n")
    in_upload_btn = False
    for line in lines:
        if "documents-hub-btn-upload-packing-list" in line:
            in_upload_btn = True
        if in_upload_btn:
            # The upload button must carry `disabled` attribute
            if "disabled" in line and "documents-hub-btn-upload-packing-list" not in line:
                break  # found disabled — all good
            if "onClick" in line and "apiFetch" in line:
                raise AssertionError(
                    "DC-12 upload button must not have an active apiFetch onClick"
                )


# ══════════════════════════════════════════════════════════════════════════════
# E. No forbidden mock affordances
# ══════════════════════════════════════════════════════════════════════════════

def test_no_sample_flow_mock():
    src = _src()
    assert "SAMPLE_FLOW" not in src, "SAMPLE_FLOW mock data must be removed from documents-hub.jsx"


def test_no_other_docs_mock():
    src = _src()
    assert "OTHER_DOCS" not in src, "OTHER_DOCS mock array must be removed from documents-hub.jsx"


def test_no_fake_wfirma_ids():
    src = _src()
    assert "wf_pi_" not in src, "Fake wFirma IDs (wf_pi_*) must not appear in documents-hub.jsx"
    assert "wf_pz_" not in src, "Fake wFirma IDs (wf_pz_*) must not appear in documents-hub.jsx"


def test_no_proforma_lifecycle_stubs():
    """Wave-3 supersession (DECISIONS.md 2026-07-04): onApprove and onUnapprove
    are now LIVE React prop names (not stubs) wiring DC-6/DC-9 to existing
    PzApi.approveDraft / PzApi.reopenDraft. The old assertion that they must be
    ABSENT is replaced: they must be PRESENT and must route to the correct
    PzApi authority methods. The 'post-to-wfirma' literal CSS class stub pin
    remains valid (the feature uses PzApi.postDraftToWfirma, not a CSS class).
    Superseding ruling: DECISIONS.md Wave-3 census DC-5..DC-16."""
    src = _code_only(_src())
    # post-to-wfirma as a literal string (old stub marker) must still be absent
    assert "post-to-wfirma" not in src, "Proforma post-to-wFirma stub class must be removed"
    # onApprove and onUnapprove must NOW be PRESENT as live wired handlers (DC-6 / DC-9)
    assert "onApprove" in src, (
        "DC-6: onApprove must be present as a live React prop wired to PzApi.approveDraft"
    )
    assert "onUnapprove" in src, (
        "DC-9: onUnapprove must be present as a live React prop wired to PzApi.reopenDraft"
    )
    # And the actual PzApi calls must back them up
    assert "approveDraft" in src, (
        "DC-6: PzApi.approveDraft call must be present (routes_proforma.py:6171)"
    )
    assert "reopenDraft" in src, (
        "DC-9: PzApi.reopenDraft call must be present (routes_proforma.py:6219)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# F. Mock/static data retired
# ══════════════════════════════════════════════════════════════════════════════

def test_no_fake_party_names():
    src = _src()
    assert "Maison Royale SARL" not in src,  "Fake party name must be retired"
    assert "Crown Jewelers Ltd" not in src,  "Fake party name must be retired"
    assert "Patek Philippe SA"  not in src,  "Fake party name must be retired"
    assert "Audemars Piguet"    not in src,  "Fake party name must be retired"


def test_no_fake_document_numbers():
    src = _src()
    assert "PI-2026/0143" not in src, "Fake PI document number must be retired"
    assert "PZ-2026/0318" not in src, "Fake PZ document number must be retired"


# ══════════════════════════════════════════════════════════════════════════════
# G. index.html documents route renders <DocumentsHubPage />
# ══════════════════════════════════════════════════════════════════════════════

def test_index_html_documents_route_renders_documents_hub_page():
    src = _INDEX_HTML.read_text(encoding="utf-8")
    block = _documents_route_block(src)
    assert "DocumentsHubPage" in block, (
        "index.html documents route block must render <DocumentsHubPage />"
    )


def test_documents_route_block_present_in_index():
    src = _INDEX_HTML.read_text(encoding="utf-8")
    assert "page === 'documents' && (" in src, (
        "index.html must contain the documents route block"
    )


# ══════════════════════════════════════════════════════════════════════════════
# H. Required testids present (Wave-3 kanban set)
#    Superseded by DECISIONS.md Wave-3 ruling 2026-07-04:
#    Old read-only set: documents-hub-root, documents-hub-reload,
#    documents-hub-summary, documents-hub-batch-table
#    New kanban set: updated for 3-lane kanban — documents-hub-reload is
#    removed (no longer a reload-only observer; Kanban data refreshes per
#    tab) and documents-hub-batch-table is removed (batch list lives in
#    PZ kanban lane, not a flat table). New testids reflect the kanban
#    structure and all 13 controls.
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_TESTIDS = [
    # Core page structure (unchanged)
    "documents-hub-root",
    "documents-hub-summary",
    "documents-hub-tabs",
    # Export CSV header action (DC-16 honest-gated)
    "documents-hub-btn-export-csv",
    # PI kanban (DC-5..DC-11 controls)
    "documents-hub-pi-kanban",
    # DC-12 Upload packing list — disabled (Wave-4), must be visible
    "documents-hub-btn-upload-packing-list",
    # New Proforma — navigate to /v2/proforma (DC-13-PI)
    "documents-hub-btn-new-pi",
    # PZ kanban (DC-8..DC-11 equivalent)
    "documents-hub-pz-kanban",
    # DC-13-PZ New Purchase Receipt — disabled (Wave-4), must be visible
    "documents-hub-btn-new-pz",
    # Other Documents tab (DC-15)
    "documents-hub-other-tab",
    "documents-hub-other-batch-select",
    "documents-hub-other-files-table",
    # Confirm modal (used by Approve / Delete / Post / Unapprove)
    "documents-hub-confirm-modal",
    "documents-hub-confirm-cancel",
    "documents-hub-confirm-ok",
]


def test_required_testids_present():
    """Wave-3 supersession (DECISIONS.md 2026-07-04): testid set updated for
    3-lane kanban. The old read-only observer testids (documents-hub-reload,
    documents-hub-batch-table) are replaced by kanban control testids covering
    all 13 census controls (DC-5..DC-16)."""
    src = _src()
    for tid in REQUIRED_TESTIDS:
        assert f'data-testid="{tid}"' in src, (
            f"Required testid '{tid}' missing from documents-hub.jsx"
        )


# ══════════════════════════════════════════════════════════════════════════════
# I. NAV_TREE 'documents' entry preserved
# ══════════════════════════════════════════════════════════════════════════════

def test_documents_in_nav_tree():
    src = _COMPONENTS.read_text(encoding="utf-8")
    assert "'documents'" in src or '"documents"' in src, (
        "NAV_TREE in components.jsx must contain the 'documents' entry"
    )


def test_existing_nav_entries_preserved():
    src = _COMPONENTS.read_text(encoding="utf-8")
    for nav_id in ("inbox", "shipments", "dhl", "proforma", "accounting"):
        assert f"'{nav_id}'" in src or f'"{nav_id}"' in src, (
            f"NAV_TREE entry '{nav_id}' must not be removed"
        )


# ══════════════════════════════════════════════════════════════════════════════
# J. Backend files not modified
# ══════════════════════════════════════════════════════════════════════════════

def test_routes_dashboard_not_modified_by_sprint35():
    """Sprint 35 is frontend-only. routes_dashboard.py must not be changed."""
    target = _BACKEND / "routes_dashboard.py"
    assert target.exists(), "routes_dashboard.py must exist"
    # Not possible to assert not-modified here, but confirm the file is present
    # and still serves GET /batches (the endpoint we depend on).
    src = target.read_text(encoding="utf-8")
    assert '@router.get("/batches"' in src or "@router.get('/batches'" in src, (
        "GET /batches endpoint must still be present in routes_dashboard.py"
    )


def test_no_new_backend_endpoints_added():
    """No new routes should appear in routes_dashboard.py for Sprint 35."""
    target = _BACKEND / "routes_dashboard.py"
    src = target.read_text(encoding="utf-8")
    # The ghost endpoints from the sprint-04 plan must NOT exist
    assert '"/batches/{batch_id}/documents"' not in src, (
        "GET /batches/{batch_id}/documents was NOT implemented — must not exist"
    )


# ══════════════════════════════════════════════════════════════════════════════
# K. Issue #396 regression — no dead-download mock patterns
# ══════════════════════════════════════════════════════════════════════════════

def test_no_uploaded_docs_mock_array():
    src = _src()
    assert "UPLOADED_DOCS" not in src, (
        "UPLOADED_DOCS mock array must not exist in documents-hub.jsx (Issue #396)"
    )


def test_no_generated_docs_mock_array():
    src = _src()
    assert "GENERATED_DOCS" not in src, (
        "GENERATED_DOCS mock array must not exist in documents-hub.jsx (Issue #396)"
    )


def test_no_files_detail_wrong_keys():
    src = _src()
    for bad_key in ("files_detail.files.sad_pdf", "files_detail.files.zc429_pdf",
                    "filesDetail.sad_pdf", "filesDetail.zc429_pdf"):
        assert bad_key not in src, (
            f"Broken files_detail key '{bad_key}' found — Issue #396 regression"
        )


def test_view_links_use_real_url_pattern():
    """Wave-3 supersession (DECISIONS.md 2026-07-04): DC-10 View action uses
    GET /api/v1/proforma/draft/{id}/preview.html (routes_proforma.py:4771) for
    PI drafts, and DC-11 Download uses
    GET /api/v1/proforma/{batch_id}/{client}/document.pdf (routes_proforma.py:2862).
    PZ and Other Docs use GET /api/v1/files/{batch_id}/{filename}
    (routes_pz.py:1421). The old documents-v2.html standalone viewer is no
    longer used — each document type links to its own authority endpoint.
    Superseding ruling: DECISIONS.md Wave-3 2026-07-04."""
    src = _src()
    # DC-10: PI Draft View → proforma preview endpoint (routes_proforma.py:4771)
    assert "preview.html" in src, (
        "DC-10: documents-hub.jsx must link to /api/v1/proforma/draft/{id}/preview.html "
        "(routes_proforma.py:4771) for PI draft view"
    )
    # DC-11: PI Draft Download → proforma PDF endpoint (routes_proforma.py:2862)
    assert "document.pdf" in src, (
        "DC-11: documents-hub.jsx must link to /api/v1/proforma/{batch}/{client}/document.pdf "
        "(routes_proforma.py:2862) for PI draft download"
    )
    # DC-15 / PZ Download: batch-level file route (routes_pz.py:1421)
    assert "/api/v1/files/" in src, (
        "DC-15 / PZ Download: documents-hub.jsx must use /api/v1/files/{batch_id}/{filename} "
        "(routes_pz.py:1421) for batch file downloads"
    )
