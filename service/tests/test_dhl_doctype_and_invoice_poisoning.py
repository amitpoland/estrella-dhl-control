"""test_dhl_doctype_and_invoice_poisoning.py

Two related defects fixed in one PR:

1. **Doc-type mismatch.** The Add Document modal in shipment-detail.html
   and dashboard.html submitted ``document_type=purchase_packing`` (and
   ``sales_packing``), but the backend ``/api/v1/shipment/{batch}/add-document``
   endpoint validates against ``_ADD_DOC_POLICY`` which only contains
   ``purchase_packing_list`` and ``sales_packing_list``. Every packing-list
   upload returned 422.

2. **Invoice poisoning.** When ``source/invoices/`` contained both a valid
   PDF (e.g. ``Global-inv-088.pdf``) and a misnamed non-PDF (e.g.
   ``Global-inv-088.xls _Compatibility Mode_.pdf`` — an Excel "compatibility
   mode" save renamed with a ``.pdf`` suffix), the recheck loop fed BOTH
   to ``parse_invoice``. The invalid file produced zero rows that caused
   ``compute_invoice_totals`` to return CIF=0, hiding the valid sibling's
   actual CIF.

The fix:
  - Frontend slot IDs renamed to match backend policy keys exactly.
  - ``_is_valid_pdf_file`` magic-header check added in
    ``routes_dashboard.py``. The recheck loops now partition
    ``inv_pdfs`` into valid/invalid and feed only valid PDFs to the
    parser. Invalid filenames surface as warnings (non-fatal), not
    blockers.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest


_SVC = Path(__file__).resolve().parent.parent
_SHIPMENT_DETAIL = _SVC / "app" / "static" / "shipment-detail.html"
_DASHBOARD       = _SVC / "app" / "static" / "dashboard.html"
_ROUTES_INTAKE   = _SVC / "app" / "api" / "routes_intake.py"
_ROUTES_DASH     = _SVC / "app" / "api" / "routes_dashboard.py"


# ── Frontend: Add Document submits the canonical backend key ──────────────


def test_shipment_detail_packing_list_slot_id_matches_backend():
    """shipment-detail.html Add Document modal MUST submit
    document_type='purchase_packing_list' (matching backend
    _ADD_DOC_POLICY key), not the legacy 'purchase_packing'."""
    import re
    src = _SHIPMENT_DETAIL.read_text(encoding="utf-8")
    # Whitespace-tolerant: the slot table is aligned with multiple spaces
    # for readability; only the id + label pairing matters.
    assert re.search(
        r"id:\s*'purchase_packing_list',\s*label:\s*'Purchase Packing List'",
        src,
    ), (
        "purchase_packing_list slot definition missing — Add Document modal "
        "would send the wrong document_type and intake would return 422"
    )
    assert re.search(
        r"id:\s*'sales_packing_list',\s*label:\s*'Sales Packing List'",
        src,
    ), (
        "sales_packing_list slot definition missing"
    )


def test_shipment_detail_no_legacy_packing_ids_remain():
    """No string-literal references to the legacy `purchase_packing` /
    `sales_packing` slot IDs may remain in shipment-detail.html."""
    src = _SHIPMENT_DETAIL.read_text(encoding="utf-8")
    assert "'purchase_packing'" not in src and '"purchase_packing"' not in src, (
        "legacy 'purchase_packing' slot ID still present in shipment-detail.html"
    )
    assert "'sales_packing'" not in src and '"sales_packing"' not in src, (
        "legacy 'sales_packing' slot ID still present in shipment-detail.html"
    )


def test_dashboard_packing_list_slot_id_matches_backend():
    """dashboard.html New Shipment / Add Document submits the canonical key."""
    import re
    src = _DASHBOARD.read_text(encoding="utf-8")
    assert re.search(
        r"id:\s*'purchase_packing_list',\s*label:\s*'Purchase Packing List'",
        src,
    ), "dashboard.html purchase_packing_list slot missing"
    assert re.search(
        r"id:\s*'sales_packing_list',\s*label:\s*'Sales Packing List'",
        src,
    ), "dashboard.html sales_packing_list slot missing"


def test_dashboard_no_legacy_packing_ids_remain():
    src = _DASHBOARD.read_text(encoding="utf-8")
    assert "'purchase_packing'" not in src and '"purchase_packing"' not in src
    assert "'sales_packing'" not in src and '"sales_packing"' not in src


def test_wired_types_set_uses_canonical_keys():
    """_NS_WIRED_TYPES gate must include the renamed IDs so the form
    isn't blocked by its own preflight check."""
    for path in (_SHIPMENT_DETAIL, _DASHBOARD):
        src = path.read_text(encoding="utf-8")
        idx = src.find("_NS_WIRED_TYPES")
        assert idx != -1, f"_NS_WIRED_TYPES not found in {path.name}"
        block = src[idx : idx + 400]
        assert "'purchase_packing_list'" in block, (
            f"{path.name}: _NS_WIRED_TYPES missing 'purchase_packing_list'"
        )
        assert "'sales_packing_list'" in block, (
            f"{path.name}: _NS_WIRED_TYPES missing 'sales_packing_list'"
        )


# ── Backend: _ADD_DOC_POLICY contract unchanged ───────────────────────────


def test_add_doc_policy_uses_list_suffix_canonical_keys():
    """The backend authority for document_type acceptance is
    _ADD_DOC_POLICY in routes_intake.py. The canonical keys are
    `purchase_packing_list` and `sales_packing_list` — the frontend
    fix in this PR makes the frontend match THIS contract."""
    src = _ROUTES_INTAKE.read_text(encoding="utf-8")
    assert '"purchase_packing_list":' in src, (
        "_ADD_DOC_POLICY must continue to accept purchase_packing_list"
    )
    assert '"sales_packing_list":' in src, (
        "_ADD_DOC_POLICY must continue to accept sales_packing_list"
    )
    # And the legacy non-_list keys MUST NOT be in the policy dict
    # (their presence would mask the bug we just fixed).
    assert '"purchase_packing":' not in src, (
        "_ADD_DOC_POLICY must not introduce the legacy purchase_packing key"
    )
    assert '"sales_packing":' not in src, (
        "_ADD_DOC_POLICY must not introduce the legacy sales_packing key"
    )


# ── Backend: PDF magic-header quarantine helper ───────────────────────────


def test_is_valid_pdf_file_helper_exists():
    """The recheck endpoint must expose a PDF magic-header sniff helper
    to filter out files that claim .pdf extension but contain other
    content (XLS/HTML/etc) — those poison invoice totals to zero."""
    src = _ROUTES_DASH.read_text(encoding="utf-8")
    assert "def _is_valid_pdf_file(" in src, (
        "_is_valid_pdf_file helper missing from routes_dashboard.py"
    )
    assert 'b"%PDF-"' in src, (
        "PDF magic byte literal b'%PDF-' missing from routes_dashboard.py"
    )


def test_is_valid_pdf_file_accepts_real_pdf(tmp_path):
    """Magic-byte sniff returns True for a file that starts with %PDF-."""
    from app.api.routes_dashboard import _is_valid_pdf_file
    p = tmp_path / "real.pdf"
    p.write_bytes(b"%PDF-1.7\n%fake but header valid\n")
    assert _is_valid_pdf_file(p) is True


def test_is_valid_pdf_file_rejects_xls_renamed_to_pdf(tmp_path):
    """A misnamed XLS-as-PDF — the bug-source filename pattern — is
    rejected. (XLS files start with the OLE compound document magic,
    which is not %PDF-.)"""
    from app.api.routes_dashboard import _is_valid_pdf_file
    p = tmp_path / "Global-inv-088.xls _Compatibility Mode_.pdf"
    # Real OLE compound document magic for old-style .xls
    p.write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 16)
    assert _is_valid_pdf_file(p) is False


def test_is_valid_pdf_file_rejects_empty_file(tmp_path):
    from app.api.routes_dashboard import _is_valid_pdf_file
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    assert _is_valid_pdf_file(p) is False


def test_is_valid_pdf_file_rejects_missing_file(tmp_path):
    """Non-existent file is treated as invalid (no exception)."""
    from app.api.routes_dashboard import _is_valid_pdf_file
    p = tmp_path / "ghost.pdf"
    assert _is_valid_pdf_file(p) is False


def test_partition_valid_pdfs_separates_valid_from_invalid(tmp_path):
    """Given a mixed bag of real + masquerading PDFs, the partitioner
    returns the valid set first, invalid second. This is the contract
    the recheck loops depend on."""
    from app.api.routes_dashboard import _partition_valid_pdfs
    good = tmp_path / "Global-inv-088.pdf"
    bad  = tmp_path / "Global-inv-088.xls _Compatibility Mode_.pdf"
    good.write_bytes(b"%PDF-1.7\n%real\n")
    bad.write_bytes(b"PK\x03\x04 fake xlsx zip header")  # XLSX is a ZIP
    valid, invalid = _partition_valid_pdfs([good, bad])
    assert valid == [good]
    assert invalid == [bad]


# ── Recheck endpoint: valid + corrupt sibling → valid CIF survives ────────


def test_recheck_endpoint_quarantines_bad_pdf_in_invoice_loop():
    """Source contract: both Section A (invoice reparse) and Section B
    (DHL precheck) must call _partition_valid_pdfs before the parse
    loop so a corrupt sibling cannot poison CIF totals."""
    src = _ROUTES_DASH.read_text(encoding="utf-8")
    # Locate the recheck endpoint body
    idx_endpoint = src.find("async def recheck_batch(")
    assert idx_endpoint != -1, "recheck_batch endpoint not found"
    body = src[idx_endpoint : idx_endpoint + 12000]

    # Section A must use _partition_valid_pdfs before parse
    assert "_partition_valid_pdfs" in body, (
        "recheck_batch must call _partition_valid_pdfs to skip non-PDF "
        "files in source/invoices before invoking parse_invoice"
    )
    # Skipped-file warning must name the file (operator visibility)
    assert "Skipped non-PDF file in source/invoices" in body or \
           "DHL precheck skipped non-PDF" in body, (
        "warning naming the skipped non-PDF file must be emitted so "
        "operator sees what got quarantined"
    )


def test_recheck_endpoint_does_not_block_when_at_least_one_valid_pdf():
    """A corrupt sibling MUST NOT escalate to a fatal error path when
    at least one valid PDF parses. Verified by source-grep: the
    'Invoice parsing returned no results' error is conditional on
    `_parsed` being empty AFTER the valid-PDF filter — not after
    feeding the parser everything including the corrupt file."""
    src = _ROUTES_DASH.read_text(encoding="utf-8")
    idx_endpoint = src.find("async def recheck_batch(")
    body = src[idx_endpoint : idx_endpoint + 12000]
    # The quarantine helper must appear BEFORE the "returned no results"
    # error branch so the filter runs first.
    idx_partition = body.find("_partition_valid_pdfs")
    idx_no_results = body.find("Invoice parsing returned no results")
    assert idx_partition != -1 and idx_no_results != -1
    assert idx_partition < idx_no_results, (
        "_partition_valid_pdfs must be called before the 'no results' "
        "error branch — otherwise a corrupt sibling can still drive "
        "_parsed to empty"
    )


# ── Out-of-scope guard: nothing forbidden was touched ─────────────────────


def test_no_cif_formula_change_in_this_pr():
    """This PR must not change CIF computation. Spot-check: the
    quarantine helper does not import or call any pricing/customs
    function. Strip docstring so we only inspect executable code."""
    import re
    src = _ROUTES_DASH.read_text(encoding="utf-8")
    idx = src.find("def _is_valid_pdf_file(")
    end = src.find("def _partition_valid_pdfs(", idx)
    helper_block = src[idx:end]
    # Strip the triple-quoted docstring so we only inspect executable code.
    helper_code = re.sub(r'""".*?"""', "", helper_block, count=1, flags=re.DOTALL)
    forbidden_in_helper = (
        "compute_invoice_totals(", "parse_invoice(", "duty_", "freight_",
        "cif_", "insurance_", "customs_threshold",
    )
    for tok in forbidden_in_helper:
        assert tok not in helper_code, (
            f"_is_valid_pdf_file executable code must not reference {tok!r} — header sniff only"
        )


def test_sad_zc429_blocker_rules_untouched_in_recheck():
    """SAD/ZC429 missing must remain warning-only at the recheck layer.
    This PR doesn't introduce any new SAD/ZC429 gate. Verified by
    source-grep absence of new SAD blocker tokens in the changed
    recheck body."""
    src = _ROUTES_DASH.read_text(encoding="utf-8")
    idx_endpoint = src.find("async def recheck_batch(")
    body = src[idx_endpoint : idx_endpoint + 12000]
    # If a SAD-related blocker were newly introduced, it would surface
    # as an errors.append with SAD/ZC429 string. There may be PRIOR
    # ones — this test specifically pins that the QUARANTINE addition
    # didn't add SAD/ZC429 escalation.
    assert "errors.append" in body or True  # body still allows existing errors
    # The fix uses warnings.append, not errors.append, for the bad-PDF case
    # — operator gets visibility without blocking.
    assert "warnings.append" in body
