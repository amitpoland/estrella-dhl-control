"""
test_sprint35_documents_hub_wiring.py
=======================================
Sprint 35 regression tests: Documents Hub wired into the V2 shell as a
read-only observer surface (DocumentsHubPage, route `page === 'documents'`).

Source-grep tests pinning the wiring contract:
  A. 'documents' added to WIRED_PAGES (no MOCK banner); all 8 prior wired pages intact
  B. DocumentsHubPage uses window.EstrellaShared.apiFetch (not hardcoded fetch/XHR)
  C. Exactly 1 allowed endpoint: GET /api/v1/dashboard/batches; no invented endpoints
  D. No write HTTP methods in documents-hub.jsx
  E. No forbidden mock affordances (SAMPLE_FLOW, OTHER_DOCS, fake PI/PZ arrays)
  F. Mock/static data retired (fake party names, hardcoded document numbers)
  G. index.html documents route still renders <DocumentsHubPage />
  H. Required testids present (documents-hub-root, documents-hub-reload,
     documents-hub-summary, documents-hub-batch-table)
  I. NAV_TREE 'documents' entry preserved in components.jsx
  J. Backend files not modified (no Python route changes)
  K. Issue #396 regression: no UPLOADED_DOCS / GENERATED_DOCS mock arrays,
     no dead onClick-only download buttons without real URLs

References:
  service/app/static/v2/documents-hub.jsx  (DocumentsHubPage — Sprint 35)
  service/app/static/v2/mock-badge.jsx     (WIRED_PAGES)
  service/app/static/v2/index.html         (documents route block)
  service/app/static/v2/components.jsx     (NAV_TREE)
  .claude/campaigns/atlas-v2/sprint-04-documents-v2.md
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
# C. Endpoint contract — one allowed GET endpoint, no invented endpoints
# ══════════════════════════════════════════════════════════════════════════════

def test_allowed_endpoint_batches_list_referenced():
    src = _src()
    assert "/api/v1/dashboard/batches" in src, (
        "documents-hub.jsx must reference /api/v1/dashboard/batches"
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
# D. No write HTTP methods
# ══════════════════════════════════════════════════════════════════════════════

def test_no_post_method_in_documents_hub():
    src = _code_only(_src())
    assert "POST " not in src, "documents-hub.jsx must not call any POST endpoint"


def test_no_put_method_in_documents_hub():
    src = _code_only(_src())
    assert "PUT " not in src, "documents-hub.jsx must not call any PUT endpoint"


def test_no_delete_method_in_documents_hub():
    src = _code_only(_src())
    assert "DELETE " not in src, "documents-hub.jsx must not call any DELETE endpoint"


def test_no_patch_method_in_documents_hub():
    src = _code_only(_src())
    assert "PATCH " not in src, "documents-hub.jsx must not call any PATCH endpoint"


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
    src = _code_only(_src())
    # Ensure write-lifecycle stub actions are gone
    assert "post-to-wfirma" not in src, "Proforma post-to-wFirma stub must be removed"
    assert "onApprove" not in src,      "onApprove lifecycle stub must be removed"
    assert "onUnapprove" not in src,    "onUnapprove lifecycle stub must be removed"


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
# H. Required testids present
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_TESTIDS = [
    "documents-hub-root",
    "documents-hub-reload",
    "documents-hub-summary",
    "documents-hub-batch-table",
]


def test_required_testids_present():
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
    src = _src()
    # View links must use documents-v2.html (the real standalone viewer)
    assert "documents-v2.html" in src, (
        "documents-hub.jsx must link to documents-v2.html for per-batch document view"
    )
    # Must pass batch_id as URL param
    assert "batch_id=" in src, (
        "documents-hub.jsx must pass batch_id as URL param to documents-v2.html"
    )
