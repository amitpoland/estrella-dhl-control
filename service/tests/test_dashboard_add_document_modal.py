"""test_dashboard_add_document_modal.py — Batch 2/2 frontend for the
post-draft add-document flow.

Source-grep tests against the dashboard JSX for the new "+ Add Document"
button + AddDocumentModal component. Backend endpoint (PR #173) is
already deployed; this batch wires the UI button to it.
"""
from __future__ import annotations

from pathlib import Path


def _src() -> str:
    return (Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")


# ── Button presence in Uploaded Source Files header ─────────────────────

def test_add_document_button_testid_present():
    src = _src()
    assert 'data-testid="source-files-add-doc"' in src


def test_add_document_button_label_present():
    """'+ Add Document' string appears in the Uploaded Source Files header."""
    src = _src()
    header_idx = src.index("Uploaded Source Files")
    snippet = src[header_idx: header_idx + 1200]
    assert "+ Add Document" in snippet
    assert "source-files-add-doc" in snippet


def test_button_toggles_state_setter():
    src = _src()
    btn_idx = src.index('data-testid="source-files-add-doc"')
    snippet = src[btn_idx: btn_idx + 400]
    assert "setAddDocOpen(true)" in snippet


# ── Modal component presence ────────────────────────────────────────────

def test_add_document_modal_function_defined():
    src = _src()
    assert "function AddDocumentModal(" in src


def test_modal_mounted_from_batch_detail():
    """BatchDetailPage must mount the modal conditionally on addDocOpen."""
    src = _src()
    assert "addDocOpen &&" in src
    assert "<AddDocumentModal" in src
    assert "setAddDocOpen(false)" in src


def test_addDocOpen_state_in_batch_detail():
    src = _src()
    assert "const [addDocOpen, setAddDocOpen] = React.useState(false);" in src


# ── Required testids inside the modal ───────────────────────────────────

def test_modal_testids_present():
    src = _src()
    for tid in (
        'add-doc-type-select',
        'add-doc-file',
        'add-doc-cancel',
        'add-doc-save',
        'add-doc-client-override',
        'add-doc-supplier-override',
    ):
        assert f'data-testid="{tid}"' in src, f"missing testid {tid}"


# ── Doc-type filter (SAD excluded) ──────────────────────────────────────

def test_modal_filters_out_sad():
    src = _src()
    start = src.index("function AddDocumentModal(")
    end   = src.index("// ══", start + 100)
    body  = src[start:end]
    # The filter is explicit:
    assert "filter(t => t.id !== 'sad')" in body


# ── Per-type accept + allowedExts preflight ─────────────────────────────

def test_file_input_uses_per_type_accept():
    src = _src()
    start = src.index("function AddDocumentModal(")
    end   = src.index("// ══", start + 100)
    body  = src[start:end]
    assert "accept={type.accept" in body


def test_preflight_references_allowedExts():
    src = _src()
    start = src.index("function AddDocumentModal(")
    end   = src.index("// ══", start + 100)
    body  = src[start:end]
    assert "type.allowedExts" in body


# ── Submit + refresh wiring ─────────────────────────────────────────────

def test_submit_posts_to_add_document_endpoint():
    src = _src()
    start = src.index("function AddDocumentModal(")
    end   = src.index("// ══", start + 100)
    body  = src[start:end]
    assert "/api/v1/shipment/${encodeURIComponent(batchId)}/add-document" in body
    assert "credentials: 'include'" in body


def test_submit_carries_document_type_field():
    src = _src()
    start = src.index("function AddDocumentModal(")
    end   = src.index("// ══", start + 100)
    body  = src[start:end]
    assert "fd.append('document_type'" in body
    assert "fd.append('file'" in body


def test_on_uploaded_handler_calls_load_and_doc_registry():
    src = _src()
    # Look at the mount site in BatchDetailPage, where onUploaded is wired:
    mount_idx = src.index("<AddDocumentModal")
    snippet = src[mount_idx: mount_idx + 800]
    assert "load()" in snippet
    assert "loadDocRegistry()" in snippet


def test_packing_types_also_trigger_loadPackingInfo():
    src = _src()
    mount_idx = src.index("<AddDocumentModal")
    snippet = src[mount_idx: mount_idx + 800]
    assert "purchase_packing_list" in snippet
    assert "sales_packing_list"    in snippet
    assert "loadPackingInfo()"     in snippet


# ── Side-effect guard ───────────────────────────────────────────────────

def test_modal_body_has_no_external_system_triggers():
    src = _src()
    start = src.index("function AddDocumentModal(")
    end   = src.index("// ══", start + 100)
    body  = src[start:end]
    for forbidden in (
        "/api/v1/dhl/",
        "/api/v1/pz/",
        "/api/v1/wfirma/",
        "/api/v1/proforma/",
        "/api/v1/customs/",
        "/api/v1/finance/",
        "trigger_clearance",
        "create_pz",
        "generate_pz",
        "issue_proforma",
        "send_email",
        "queue_email",
    ):
        assert forbidden not in body, f"modal must not reference {forbidden!r}"


# ── Packing-list-card legacy tests must still work (brace balance) ──────

def test_jsx_brace_balance_unchanged():
    """The modal insertion must not break the brace balance the existing
    test_dashboard_packing_list_card::test_brace_balance asserts."""
    import re
    src = _src()
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", src, re.DOTALL)
    jsx = max(scripts, key=len)
    assert jsx.count("{") == jsx.count("}")
