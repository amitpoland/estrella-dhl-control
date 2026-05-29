"""
test_documents_v2_contract.py — Source-grep contract tests for Documents V2 frontend.

Atlas-V2 Sprint 04. These tests never make HTTP requests — they read the static
file content and ensure the implementation meets the sprint contract:

  1. File exists at expected path
  2. CDN load order: react@18, react-dom@18, @babel/standalone, then the
     shared layer (dashboard-shared.js → pz-api.js → pz-state.js → pz-components.js)
  3. All required section + row testids present
  4. READ-ONLY authority: zero write-capable API calls, zero PZ/wFirma/DHL mutation,
     zero generation triggers
  5. Document links open in a new tab (target="_blank") — no inline render
  6. ?batch_id= URL param read via URLSearchParams
  7. Auth error handled (401/403 path present)
  8. Empty/error state present for missing batch_id and for empty sections
  9. Stack compliance: no TypeScript, no Tailwind, no Vite, no ES modules
 10. CSS custom properties used (--bg, --text); no raw hex inside the React component
 11. Binds to the REAL data source: GET /api/v1/dashboard/batches/{id}
 12. Binds to the REAL files_detail shape (source_files invoices/sad/awb + generated files)
 13. V1 freeze: this is the only new file; V1 files untouched
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "app" / "static"
DOC = STATIC / "documents-v2.html"


def _src() -> str:
    if not DOC.exists():
        pytest.skip(f"documents-v2.html not found at {DOC}")
    return DOC.read_text(encoding="utf-8")


def _component_block(src: str) -> str:
    """Return the inline page <script> body (the React component code only)."""
    m = re.search(r"<!-- Documents V2 page -->\s*<script[^>]*>(.+?)</script>", src, re.DOTALL)
    assert m, "Documents V2 page script block not found"
    return m.group(1)


# ── Contract 1: File exists ──────────────────────────────────────────────────

def test_file_exists():
    assert DOC.exists(), f"documents-v2.html must exist at {DOC}"


# ── Contract 2: CDN + shared-layer load order ────────────────────────────────

def test_cdn_and_shared_load_order():
    src = _src()
    positions = [
        src.find("react@18/umd/react.production.min.js"),
        src.find("react-dom@18/umd/react-dom.production.min.js"),
        src.find("@babel/standalone/babel.min.js"),
        src.find("/dashboard/dashboard-shared.js"),
        src.find("/dashboard/pz-api.js"),
        src.find("/dashboard/pz-state.js"),
        src.find("/dashboard/pz-components.js"),
    ]
    for p in positions:
        assert p != -1, "A required CDN / shared-layer script is missing"
    assert positions == sorted(positions), "Scripts must load in dependency order"


# ── Contract 3: Required testids present (real DOM nodes) ─────────────────────

def test_root_and_section_testids():
    src = _src()
    for tid in (
        "documents-v2-root",
        "batch-header",
        "customs-documents-section",
        "commercial-documents-section",
        "generated-documents-section",
        "audit-trail-section",
    ):
        assert f'data-testid="{tid}"' in src, f"missing testid {tid}"


def test_dynamic_row_testids_present():
    block = _component_block(_src())
    # Row + open-link testids are template-literal driven
    for frag in (
        "customs-doc-sad-",
        "customs-doc-awb-",
        "commercial-doc-invoice-",
        "generated-doc-",
        "-open",
        "-unavailable",
    ):
        assert frag in block, f"missing dynamic testid fragment {frag}"


# ── Contract 4: READ-ONLY authority ───────────────────────────────────────────

def test_no_write_methods():
    block = _component_block(_src())
    # No mutating HTTP verbs anywhere in the page logic
    for verb in ("method: 'POST'", "method: 'PUT'", "method: 'DELETE'", "method: 'PATCH'",
                 'method:"POST"', 'method:"PUT"', 'method:"DELETE"', 'method:"PATCH"'):
        assert verb not in block, f"write verb {verb} found — page must be read-only"


def test_no_write_endpoints():
    block = _component_block(_src())
    # No PZ creation / wFirma / SAD approval / generation endpoints
    forbidden = (
        "/pz/process", "/pz/create", "/wfirma", "/generate", "/approve",
        "/sad/", "/zc429/process", "/mrn", "/clearance/decide", "/process",
    )
    for ep in forbidden:
        assert ep not in block, f"forbidden write/mutation endpoint {ep} present"


def test_no_generation_or_save_handlers():
    block = _component_block(_src())
    for token in ("onGenerate", "handleGenerate", "onSave", "handleSave",
                  "onApprove", "onCreate", "onSubmit"):
        assert token not in block, f"write handler {token} present — page must be read-only"


# ── Contract 5: Document links open new tab (no inline render) ────────────────

def test_doc_links_open_new_tab():
    block = _component_block(_src())
    assert 'target="_blank"' in block
    assert 'rel="noopener noreferrer"' in block
    # The link href is the backend-provided url field — page invents no download path
    assert "href={file.url}" in block


def test_no_invented_download_endpoint():
    block = _component_block(_src())
    # Must NOT construct file URLs by hand — only consume server-provided url fields
    assert "/api/v1/files/" not in block, (
        "page must use server-provided file.url, not hand-built /api/v1/files/ paths"
    )


# ── Contract 6: batch_id via URLSearchParams ──────────────────────────────────

def test_batch_id_url_param():
    block = _component_block(_src())
    assert "URLSearchParams" in block
    assert "get('batch_id')" in block


# ── Contract 7: Auth error handled ─────────────────────────────────────────────

def test_auth_error_handled():
    block = _component_block(_src())
    assert "401" in block and "403" in block
    assert "SessionBanner" in block


# ── Contract 8: Empty / error states present ──────────────────────────────────

def test_missing_batch_id_state():
    block = _component_block(_src())
    assert 'state="error"' in block
    assert "Missing batch_id" in block


def test_empty_states_per_section():
    block = _component_block(_src())
    # Each section renders an EmptyState when its data is empty
    assert block.count('EmptyState state="empty"') >= 4 or block.count('state="empty"') >= 4


# ── Contract 9: Stack compliance ───────────────────────────────────────────────

def test_no_forbidden_stack():
    src = _src()
    for bad in ("import React", "from 'react'", 'from "react"',
                "tailwind", "Tailwind", "vite", "Vite", ": React.FC", "interface ",
                "tsx", "<script type=\"module\""):
        assert bad not in src, f"forbidden stack token {bad!r} present"


# ── Contract 10: CSS custom properties, no raw hex in component ───────────────

def test_css_custom_properties_used():
    src = _src()
    assert "--bg:" in src and "--text:" in src
    assert "@media (prefers-color-scheme: dark)" in src


def test_no_raw_hex_in_component():
    block = _component_block(_src())
    # Strip JS comments first — issue/PR refs like "#395" are not colours.
    no_line_comments = re.sub(r"//[^\n]*", "", block)
    no_comments = re.sub(r"/\*.*?\*/", "", no_line_comments, flags=re.DOTALL)
    # The React component body must not hardcode hex colours — uses var(--*)
    hexes = re.findall(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b", no_comments)
    assert not hexes, f"raw hex colours in component body: {hexes[:5]}"


# ── Contract 11: Real primary data source ─────────────────────────────────────

def test_primary_data_source():
    block = _component_block(_src())
    assert "/api/v1/dashboard/batches/" in block, (
        "must read from the real batch-detail endpoint (PR #395 alias-mount)"
    )


# ── Contract 12: Real files_detail shape binding ──────────────────────────────

def test_binds_real_files_detail_shape():
    block = _component_block(_src())
    assert "files_detail" in block
    assert "source_files" in block
    # source taxonomy that the backend actually returns
    for field in ("sf.invoices", "sf.sad", "sf.awb"):
        assert field in block, f"missing real source field {field}"
    # generated files block
    for gen in ("files.pz_pdf", "files.calc_xlsx", "files.audit_en",
                "files.audit_pl", "files.audit_memo", "files.corrections"):
        assert gen in block, f"missing generated file binding {gen}"


def test_audit_trail_binds_timeline():
    block = _component_block(_src())
    assert "batch.timeline" in block or "timeline" in block
    # event shape fields actually present in audit.json timeline events
    for f in ("e.event", "e.ts", "e.actor"):
        assert f in block, f"missing timeline event field {f}"


# ── Contract 13: V1 freeze ─────────────────────────────────────────────────────

def test_v1_files_not_modified_by_this_sprint():
    # documents-v2.html is a new file; V1 dashboard.html / shipment-detail.html
    # must still exist and remain the V1 surfaces (sanity guard, not a diff check).
    assert (STATIC / "dashboard.html").exists()
    assert (STATIC / "shipment-detail.html").exists()
    # The new page must not reference the V1 detail page as its own implementation.
    block = _component_block(_src())
    assert "shipment-detail.html" not in block
