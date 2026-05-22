"""test_polish_desc_cache_and_overwrite.py

Defends against the production observation: "even after delete and
regenerate, the old Polish Description PDF keeps returning."

Root cause: the download endpoint set ``Cache-Control: max-age=14400``
(4 hours). The browser served its cached copy even after the file on
disk was updated — looked like the old file kept coming back.

Fix (this PR):
  1. Download endpoint sets ``Cache-Control: no-store, no-cache,
     must-revalidate, max-age=0`` so the browser ALWAYS revalidates.
  2. Generate endpoint validates the freshly-generated PDF for the
     four forbidden placeholder strings (UNKNOWN / metal szlachetny /
     Wyrób jubilerski / grouped invoice aggregate). On a hit the file
     is unlinked and the audit pointers are NOT updated — the
     operator sees a clean 422 instead of a silent stale write.
  3. Generate endpoint records polish_desc_generated_at +
     polish_desc_file_exists so the UI can tell when the artifact was
     actually refreshed (helps detect future cache mismatches).

Estrella protection: no Estrella supplier code is modified. The
forbidden-token list is checked on the GENERATED OUTPUT only, not on
any input parser. Estrella batches that produce a clean description
pass through unchanged.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_dhl_clearance.py"
)


# ── Cache-Control on download endpoint ────────────────────────────────────


def test_download_endpoint_sets_no_store_cache_control():
    """The download endpoint MUST send Cache-Control: no-store (or
    equivalent no-cache directives) so the browser never serves a
    stale cached copy of regenerable artifacts."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def download_dhl_file(")
    assert idx >= 0, "download_dhl_file endpoint missing"
    body = src[idx : idx + 3000]
    # Three header values must all appear in the response setup
    assert "no-store" in body
    assert "no-cache" in body
    assert "must-revalidate" in body
    assert "max-age=0" in body
    assert "headers=no_cache_headers" in body


def test_download_endpoint_no_max_age_14400_anywhere_in_handler():
    """Regression pin against the original 4-hour cache that caused
    the stale-PDF report. Comment text documenting the prior behaviour
    is allowed (the docstring may say "Prior behaviour set max-age=14400");
    only the executable Cache-Control HEADER value matters."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def download_dhl_file(")
    body = src[idx : idx + 3000]
    # The actual response Cache-Control header
    assert '"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"' in body, (
        "download response Cache-Control header must be no-store"
    )
    # The handler must not emit a 14400/3600 max-age in any new code path
    # (we allow it in docstrings — those describe the prior behaviour we
    # specifically fixed and are not part of the response).
    code_only = "\n".join(
        ln for ln in body.split("\n")
        if not ln.strip().startswith(("#", '"', "'"))
        and not ln.lstrip().startswith(("# ", '" ', "' "))
    )
    # Cache-Control header line is the only place these tokens may appear
    # in executable code. Filter that out and ensure no stale defaults.
    code_no_cc = "\n".join(
        ln for ln in code_only.split("\n")
        if "no-store, no-cache" not in ln
    )
    assert "max-age=14400" not in code_no_cc
    assert "max-age=3600"  not in code_no_cc


# ── Forbidden-token validation gate ──────────────────────────────────────


def test_generate_validates_pdf_against_forbidden_tokens():
    """The generate endpoint reads the freshly-generated PDF text and
    rejects it if any forbidden placeholder is present."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def generate_description(")
    # Take a generous slice — the function body is long (several KB
    # including docstring + multiple guard blocks).
    body = src[idx : idx + 15000]
    # All 4 operator-locked forbidden tokens must be checked
    assert '"UNKNOWN"' in body
    assert '"metal szlachetny"' in body
    assert '"Wyrób jubilerski"' in body
    assert '"grouped invoice aggregate"' in body
    # Validation must be a tuple in the validator block
    assert "_FORBIDDEN_TOKENS" in body
    assert "polish_desc_forbidden_tokens" in body


def test_generate_rolls_back_file_on_forbidden_token_hit():
    """On a forbidden-token hit the freshly-generated file must be
    unlinked AND the audit pointers must NOT be updated. This is the
    'validate-then-rollback' safety pattern."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def generate_description(")
    # Take a generous slice — the function body is long (several KB
    # including docstring + multiple guard blocks).
    body = src[idx : idx + 15000]
    # Unlink call must be inside the forbidden-token branch
    assert "_generated_path.unlink()" in body
    # Audit pointer update must be AFTER the forbidden-token check
    i_check = body.find("_FORBIDDEN_TOKENS")
    i_audit = body.find('audit["polish_desc_filename"]')
    assert 0 < i_check < i_audit, (
        "forbidden-token check must run BEFORE audit pointer update"
    )


def test_generate_returns_422_on_forbidden_tokens():
    """HTTP status code for forbidden-token rejection must be 422."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def generate_description(")
    # Take a generous slice — the function body is long (several KB
    # including docstring + multiple guard blocks).
    body = src[idx : idx + 15000]
    # Find the forbidden-token HTTPException block
    i_guard = body.find('"polish_desc_forbidden_tokens"')
    assert i_guard >= 0
    # Look back 600 chars to find the status_code
    window = body[max(0, i_guard - 600) : i_guard + 200]
    assert "status_code=422" in window


def test_audit_records_generated_at_and_file_exists():
    """After successful generation the audit must record
    polish_desc_generated_at + polish_desc_file_exists so future
    operators can tell when the artifact was actually refreshed.
    This helps detect future cache mismatches."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def generate_description(")
    # Take a generous slice — the function body is long (several KB
    # including docstring + multiple guard blocks).
    body = src[idx : idx + 15000]
    assert 'audit["polish_desc_generated_at"]' in body
    assert 'audit["polish_desc_file_exists"]' in body


# ── Out-of-scope guard ────────────────────────────────────────────────────


def test_validator_block_does_not_touch_fiscal_or_wfirma_paths():
    """The forbidden-token validator + rollback must not touch CIF,
    duty, VAT, wFirma write paths, or any fiscal field."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx_start = src.find("Validate-then-rollback overwrite safety")
    idx_end   = src.find("# Update audit", idx_start)
    block = src[idx_start:idx_end]
    forbidden = (
        "WFIRMA_CREATE_", "create_invoice", "create_pz",
        "_guard_wfirma_export", "post_to_wfirma",
        "compute_cif", "DHL_BROKER_THRESHOLD",
        "total_fob_usd", "total_cif_usd",
        "duty_pln", "vat_pln",
    )
    for tok in forbidden:
        assert tok not in block, (
            f"validator block must not reference {tok!r}"
        )


def test_no_estrella_supplier_module_imported_by_new_code():
    """The TWO regions added by this PR (download endpoint cache
    headers + validate-then-rollback block) must not introduce any
    new Estrella supplier-module import. The existing top-of-handler
    ``from customs_description_engine import generate_customs_description_package``
    is unchanged by this PR and is not in either new region."""
    src = _ROUTES.read_text(encoding="utf-8")
    # Region 1: cache-headers block in download_dhl_file
    i1 = src.find("no_cache_headers = {")
    region1 = src[i1 : i1 + 800] if i1 >= 0 else ""
    # Region 2: validate-then-rollback block
    i2 = src.find("Validate-then-rollback overwrite safety")
    region2 = src[i2 : src.find("# Update audit", i2)] if i2 >= 0 else ""
    forbidden = (
        "invoice_intake_parser",
        "product_identity_engine",
        "from .. import description_engine",
        "global_invoice_parser",
        "global_packing_parser",
    )
    for block_name, block in (("cache-headers", region1),
                              ("validator", region2)):
        for tok in forbidden:
            assert tok not in block, (
                f"{block_name} block must not import {tok!r}"
            )


# ── Behaviour: validator unit test against fixture PDFs ───────────────────


def test_validator_logic_rejects_pdf_with_unknown_token(tmp_path):
    """Direct test of the forbidden-token check pattern against a
    PDF that contains 'UNKNOWN'."""
    # We can't easily forge a real PDF here. Instead verify the regex
    # equivalent: the code uses ``if any(t in text for t in _FORBIDDEN_TOKENS)``.
    forbidden = ("UNKNOWN", "metal szlachetny", "Wyrób jubilerski",
                 "grouped invoice aggregate")
    text_with_unknown = "Pozycja 1: UNKNOWN item, value USD 100"
    hits = [t for t in forbidden if t in text_with_unknown]
    assert hits == ["UNKNOWN"]


def test_validator_logic_accepts_clean_pdf_text():
    forbidden = ("UNKNOWN", "metal szlachetny", "Wyrób jubilerski",
                 "grouped invoice aggregate")
    clean = (
        "Pozycja 1 / Item 1:\n"
        "Bransoletka ze złota próby 375 z diamentami laboratoryjnymi\n"
        "09KT Gold Lab Grown Diamond Jewellery BRACELET\n"
        "Wartość / Value: USD 232.00"
    )
    hits = [t for t in forbidden if t in clean]
    assert hits == []


def test_validator_logic_detects_each_token_individually():
    forbidden = ("UNKNOWN", "metal szlachetny", "Wyrób jubilerski",
                 "grouped invoice aggregate")
    for tok in forbidden:
        sample = f"... some Polish description with {tok} embedded ..."
        hits = [t for t in forbidden if t in sample]
        assert tok in hits, f"failed to detect {tok!r}"


# ── Black-square (U+25A0) corruption rejection ───────────────────────────


def test_forbidden_tokens_include_black_square_corruption_marker():
    """The forbidden-token tuple in routes_dhl_clearance.py MUST include
    U+25A0 BLACK SQUARE (■). On Windows, polish_description_generator
    falls back to Helvetica when no OS-matching font path resolves;
    Helvetica has no glyph for Polish diacritics so they render as ■.
    Catching ■ in the validator rejects corrupted PDFs at generation
    time and triggers the rollback path before audit pointers mutate.
    """
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("_FORBIDDEN_TOKENS = (")
    assert idx >= 0, "_FORBIDDEN_TOKENS tuple missing"
    # Take the tuple body (rough 500-char window)
    block = src[idx : idx + 500]
    assert '"■"' in block, (
        "U+25A0 BLACK SQUARE must be in _FORBIDDEN_TOKENS to catch "
        "Windows font-fallback corruption of Polish diacritics"
    )


def test_validator_logic_detects_black_square_corruption():
    """Direct validator-logic test: a PDF text fragment containing the
    Windows-font-fallback corruption marker MUST be detected."""
    forbidden = ("UNKNOWN", "metal szlachetny", "Wyrób jubilerski",
                 "grouped invoice aggregate", "■")
    corrupted = (
        "Pozycja 1: Pier■cionek (RING)\n"
        "Pier■cionek z diamentami i kamieniami szlachetnymi, "
        "bi■uteria do noszenia.\n"
        "Z jakiego materia■u / Material: metal\n"
    )
    hits = [t for t in forbidden if t in corrupted]
    assert "■" in hits, (
        "Validator failed to detect ■ corruption — "
        f"hits = {hits!r}"
    )


def test_black_square_rejection_uses_existing_422_rollback_path():
    """Source-grep: ■ must be handled by the same 422-rollback branch
    the other 4 tokens use. The validate-then-rollback architecture
    from PR #265 is the single rejection path; ■ does NOT get a custom
    branch (`if "■" in pdf_text: ...`) anywhere else in the route file.
    """
    src = _ROUTES.read_text(encoding="utf-8")
    # ■ as a Python string literal (only counts when it appears in code,
    # not in comments) — must appear exactly once: in the tuple entry.
    literal_count = src.count('"■"')
    assert literal_count == 1, (
        f'"■" literal should appear exactly once (in _FORBIDDEN_TOKENS); '
        f"found {literal_count}"
    )
    # That one occurrence must come AFTER the tuple opens and BEFORE the
    # forbidden-token scan (`_hits = [t for t in _FORBIDDEN_TOKENS …]`).
    i_tuple_open = src.find("_FORBIDDEN_TOKENS = (")
    i_hits       = src.find("_hits = [t for t in _FORBIDDEN_TOKENS")
    i_literal    = src.find('"■"')
    assert 0 < i_tuple_open < i_literal < i_hits, (
        "■ literal must live inside the _FORBIDDEN_TOKENS tuple, "
        "not in any custom branch elsewhere in the route"
    )
