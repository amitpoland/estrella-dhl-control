"""test_generated_output_dsk_row.py — 2026-05-17 hotfix.

Generated Output Files section was missing the DSK document row even
though DHL Clearance Values showed DSK File: Generated. This test asserts
the new DSK block renders parallel to Polish Description, with stable
testids and the same download endpoint pattern.
"""
from __future__ import annotations

from pathlib import Path


def _src() -> str:
    return (Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html").read_text(encoding="utf-8")


# ── Presence ─────────────────────────────────────────────────────────────

def test_generated_output_dsk_row_testid_present():
    src = _src()
    assert 'data-testid="generated-output-dsk"' in src


def test_generated_output_dsk_status_testid_present():
    src = _src()
    assert 'data-testid="generated-output-dsk-status"' in src


def test_generated_output_dsk_download_testid_present():
    src = _src()
    assert 'data-testid="generated-output-dsk-download"' in src


# ── Behavior ─────────────────────────────────────────────────────────────

def test_dsk_row_reads_audit_dsk_filename():
    """The new block must source from audit.dsk_filename (not regenerated
    or invented)."""
    src = _src()
    # Widen back to the IIFE start so `const fn = audit.dsk_filename;`
    # (above the data-testid) is included in the block.
    testid_idx  = src.index('data-testid="generated-output-dsk"')
    block_start = src.rindex('{(() => {', 0, testid_idx)
    block_end   = src.index('})()}', testid_idx)
    block = src[block_start:block_end]
    assert "audit.dsk_filename" in block


def test_dsk_row_reuses_existing_dhl_download_endpoint():
    """Same download endpoint pattern as the Polish Description row."""
    src = _src()
    # Widen back to the IIFE start so `const fn = audit.dsk_filename;`
    # (above the data-testid) is included in the block.
    testid_idx  = src.index('data-testid="generated-output-dsk"')
    block_start = src.rindex('{(() => {', 0, testid_idx)
    block_end   = src.index('})()}', testid_idx)
    block = src[block_start:block_end]
    assert "/api/v1/dhl/download/${encodeURIComponent(fn)}" in block


def test_dsk_row_renders_generated_or_not_generated_text():
    src = _src()
    # Widen back to the IIFE start so `const fn = audit.dsk_filename;`
    # (above the data-testid) is included in the block.
    testid_idx  = src.index('data-testid="generated-output-dsk"')
    block_start = src.rindex('{(() => {', 0, testid_idx)
    block_end   = src.index('})()}', testid_idx)
    block = src[block_start:block_end]
    assert "✓ Generated" in block
    assert "Not generated" in block


# ── Co-existence ─────────────────────────────────────────────────────────

def test_polish_description_row_still_present():
    """The hotfix must NOT remove or modify the Polish Description row."""
    src = _src()
    assert 'data-testid="generated-output-polish-desc"' in src
    assert "Polish Customs Description (DHL)" in src


def test_dsk_row_is_sibling_of_polish_desc_row():
    """DSK row must appear after Polish Description, both inside the
    Generated Output Files block."""
    src = _src()
    pd_idx  = src.index('data-testid="generated-output-polish-desc"')
    dsk_idx = src.index('data-testid="generated-output-dsk"')
    assert dsk_idx > pd_idx, "DSK row must appear after Polish Description row"
    # Find the Generated Output Files header that precedes both:
    header_idx = src.index("Generated Output Files")
    assert header_idx < pd_idx < dsk_idx


def test_dsk_row_does_not_trigger_external_systems():
    """Source-grep guard: the new DSK row must be display-only. No
    references to generation triggers / external integrations."""
    src = _src()
    # Widen back to the IIFE start so `const fn = audit.dsk_filename;`
    # (above the data-testid) is included in the block.
    testid_idx  = src.index('data-testid="generated-output-dsk"')
    block_start = src.rindex('{(() => {', 0, testid_idx)
    block_end   = src.index('})()}', testid_idx)
    block = src[block_start:block_end]
    for forbidden in (
        "send_email", "queue_email", "smtp",
        "create_pz", "generate_pz", "generate_dsk",
        "wfirma_client", "wfirma_api",
        "proforma_create", "proforma_issue", "proforma_post",
        "process_sad", "trigger_clearance", "dhl_dispatch",
        "regenerateDsk", "regenerate_dsk",
    ):
        assert forbidden not in block, f"DSK row must not reference {forbidden!r}"
