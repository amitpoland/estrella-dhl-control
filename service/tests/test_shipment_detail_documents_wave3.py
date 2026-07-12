"""
test_shipment_detail_documents_wave3.py — EJ Dashboard Stabilization Wave 3.

Source-contract tests for the V2 Shipment Detail Documents + SAD wiring. These
read the static JSX / pz-api.js (no HTTP) and pin the frontend contract:

  * DocumentsTab consumes the canonical manifest (getShipmentDocuments), NOT the
    retired /dashboard/batches/{id}/files filesystem scan.
  * The mismapping _WIREFRAME_DOC_CARDS is gone (no Packing List→AWB etc.).
  * Purchase vs sales packing render as distinct types.
  * View and Download use distinct inline/attachment URLs.
  * Buttons are gated by the backend capability flags (can_view/download/replace/
    delete) — the frontend never invents capability.
  * SAD upload uses multipart; recheck calls the canonical recheck route and
    surfaces the role gate; verification is read from the decision engine, never
    inferred from a SAD file existing.
  * DHL correspondence WRITE actions are not moved into V2.
  * No internal file_path is referenced by the frontend.
"""
from __future__ import annotations

from pathlib import Path

import pytest

V2 = Path(__file__).parents[1] / "app" / "static" / "v2"
DETAIL = V2 / "shipment-detail-page.jsx"
PZAPI = V2 / "pz-api.js"


def _read(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"{p} missing")
    return p.read_text(encoding="utf-8")


# ── pz-api wrappers ─────────────────────────────────────────────────────────

def test_pzapi_has_wave3_document_wrappers_once():
    src = _read(PZAPI)
    for w in ("getShipmentDocuments", "viewDocument", "downloadDocument",
              "uploadSad", "recheckSad", "deleteDocument", "replaceDocument",
              "getDhlClearanceStatus"):
        assert src.count(w + ":") == 1, f"{w} must be defined exactly once"


def test_uploadsad_and_replace_use_multipart():
    src = _read(PZAPI)
    # both file wrappers build FormData (multipart) — never JSON
    up = src[src.index("uploadSad:"): src.index("uploadSad:") + 400]
    assert "FormData" in up and "sad" in up, "uploadSad must post multipart with the sad field"
    rp = src[src.index("replaceDocument:"): src.index("replaceDocument:") + 500]
    assert "FormData" in rp and "X-Operator" in rp, "replaceDocument must be multipart + X-Operator"


def test_view_download_use_distinct_dispositions():
    src = _read(PZAPI)
    assert "disposition=inline" in src, "viewDocument must request inline disposition"
    assert "disposition=attachment" in src, "downloadDocument must request attachment disposition"


def test_recheck_uses_canonical_recheck_route_with_operator():
    src = _read(PZAPI)
    rc = src[src.index("recheckSad:"): src.index("recheckSad:") + 200]
    assert "/recheck" in rc and "mode" in rc and "_postM" in rc, (
        "recheckSad must call the recheck route with {mode:'sad'} via _postM (X-Operator)"
    )


# ── Documents tab ───────────────────────────────────────────────────────────

def test_documentstab_uses_manifest_not_filesystem_scan():
    src = _read(DETAIL)
    # the DocumentsTab body must load via the manifest wrapper …
    assert "getShipmentDocuments(batchId)" in src, "DocumentsTab must call PzApi.getShipmentDocuments"
    # … and must NOT fetch the retired filesystem-scan endpoint (comment mention ok,
    # but no live apiFetch to /files inside a documents context).
    assert "apiFetch('/api/v1/dashboard/batches/' + encodeURIComponent(batchId) + '/files')" not in src, (
        "DocumentsTab must not use the retired /dashboard/batches/{id}/files scan"
    )


def test_no_wireframe_doc_cards_mismap():
    src = _read(DETAIL)
    # the const definition + its mismapped rows must be gone (only the comment
    # explaining the retirement may mention the name).
    assert "const _WIREFRAME_DOC_CARDS" not in src, "_WIREFRAME_DOC_CARDS mismap must be removed"
    assert "sourceKey: 'awb'" not in src, "Packing List→AWB mismap must be gone"
    assert "generatedKey: 'calc_xlsx'" not in src, "CMR→calc_xlsx mismap must be gone"


def test_purchase_and_sales_packing_are_distinct_labels():
    src = _read(DETAIL)
    assert "purchase_packing_list:" in src and "Purchase Packing List" in src
    assert "sales_packing_list:" in src and "Sales Packing List" in src


def test_buttons_gated_by_capability_flags():
    src = _read(DETAIL)
    for flag in ("row.can_view", "row.can_download", "row.can_replace", "row.can_delete"):
        assert flag in src, f"document actions must be gated by {flag}"
    # non-deletable docs surface a protected marker rather than a delete button.
    assert "Protected" in src or "doc-locked" in src


def test_no_file_path_referenced_in_frontend():
    src = _read(DETAIL)
    # No CODE reference to the internal file_path (a comment explaining the
    # scrub is fine — strip // comment lines before checking).
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))
    for ref in ("row.file_path", ".file_path", '["file_path"]', "['file_path']"):
        assert ref not in code, f"frontend must never reference the internal {ref}"


# ── SAD verification honesty ────────────────────────────────────────────────

def test_sad_verification_read_from_decision_engine():
    src = _read(DETAIL)
    assert "sadDecision" in src, "SAD verdict must come from the decision engine (agency_sad_decision)"
    assert "safe_to_run_pz" in src, "the PZ gate verdict must be surfaced"
    # the stale 'run on the V1 page' SAD wording must be gone.
    assert "Upload on the V1 page" not in src, "stale SAD 'use V1' wording must be removed"


def test_dhl_correspondence_writes_not_in_v2():
    src = _read(DETAIL)
    # V2 must not call the DHL correspondence WRITE wrappers (they stay on the
    # standalone DHL Console). None of these should be invoked from the detail page.
    for write in ("sendReply", "matchAndHandle", "generateDescription",
                  "generateCustomsPackage", "markEmailReceived", "proactiveDispatch"):
        assert f"PzApi.{write}(" not in src, f"DHL correspondence write {write} must not be wired into V2"
