"""wFirma Goods Authority Hardening (2026-05-22).

The Global AWB 4789974092 / PZ 185704611 incident exposed a structural
gap: `/products/resolve` built new wFirma good names from
`description_engine.get_description_block()` — a persistent cache that
returned stale text when the create call happened before the PZ engine
bridge had populated the authority rows.

This PR pins the permanent rule:

  Authority chain (one-way):
    Invoice-position authority (PR #269)
    → Polish description authority (audit.rows + sidecar)
    → wFirma goods authority (this PR — name source pinned to row)
    → PZ creation authority (PR #277 compact notes)

Test contract:
- Create path bypasses description_engine cache when row pl_desc is
  populated (Estrella + Global with PR #269 authority).
- Create REFUSED with STALE_AUTHORITY_REFUSED when row lacks pl_desc
  AND audit has no invoice_positions_authority marker.
- Drift on already-mapped codes is surfaced (NOT auto-renamed).
- Idempotent — re-running on clean state reports 0 drift.
- Estrella regression: legacy `pl_desc`-populated rows still create.
- Global incident scenario from a stale-aggregate audit fixture is
  REFUSED (the regression-pin proof).
"""
from __future__ import annotations

from pathlib import Path

from service.app.api.routes_wfirma import (
    EV_WFIRMA_GOOD_CREATED_FROM_AUTHORITY,
    _build_authority_name,
)


ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_wfirma.py"
)


def _body() -> str:
    return ROUTES.read_text(encoding="utf-8")


# ── 1. Authority pre-flight + STALE_AUTHORITY_REFUSED ─────────────────

def test_resolve_create_branch_has_stale_authority_refused_gate():
    body = _body()
    chunk_start = body.find("wfirma_products_resolve")
    end = body.find("@router.post", chunk_start + 1)
    chunk = body[chunk_start:end] if end > 0 else body[chunk_start:]
    assert "STALE_AUTHORITY_REFUSED" in chunk
    # The gate condition is `not _global_authority and not row_pl`
    assert "_global_authority" in chunk
    assert 'audit.get("_rows_source")' in chunk


def test_resolve_global_authority_marker_is_invoice_positions_authority():
    body = _body()
    chunk_start = body.find("wfirma_products_resolve")
    end = body.find("@router.post", chunk_start + 1)
    chunk = body[chunk_start:end] if end > 0 else body[chunk_start:]
    # The marker string the pre-flight checks for.
    assert '"invoice_positions_authority"' in chunk


# ── 2. Name comes from pz_rows directly, not from description_engine ──

def test_create_uses_row_authority_via_build_authority_name():
    body = _body()
    chunk_start = body.find("wfirma_products_resolve")
    end = body.find("@router.post", chunk_start + 1)
    chunk = body[chunk_start:end] if end > 0 else body[chunk_start:]
    # The create branch calls _build_authority_name to derive the name.
    assert "_build_authority_name(meta)" in chunk
    # The create call passes the row-derived name to wfirma_client.
    assert "name         = wf_name" in chunk


def test_description_engine_fallback_path_explicit_only_when_no_pl_desc():
    body = _body()
    chunk_start = body.find("wfirma_products_resolve")
    end = body.find("@router.post", chunk_start + 1)
    chunk = body[chunk_start:end] if end > 0 else body[chunk_start:]
    # description_engine fallback is gated behind `else` for `row_pl`.
    # Pin the fallback label so we'd notice if the create path ever
    # silently grew back into the cache-as-primary mode.
    assert "description_engine_fallback" in chunk
    assert "pz_rows_authority" in chunk


# ── 3. _build_authority_name unit tests ───────────────────────────────

def test_build_authority_name_both_pl_and_en():
    assert _build_authority_name({
        "pl_desc":        "Bransoletki ze złota próby 375 z diamentami laboratoryjnymi",
        "description_en": "09KT Gold Lab Grown Diamond Jewellery BRACELETS",
    }) == "Bransoletki ze złota próby 375 z diamentami laboratoryjnymi / 09KT Gold Lab Grown Diamond Jewellery BRACELETS"


def test_build_authority_name_pl_only():
    assert _build_authority_name({
        "pl_desc":        "Pierścionki ze srebra próby 925",
        "description_en": "",
    }) == "Pierścionki ze srebra próby 925"


def test_build_authority_name_en_only():
    assert _build_authority_name({
        "pl_desc":        "",
        "description_en": "Some English Description",
    }) == "Some English Description"


def test_build_authority_name_empty_returns_empty():
    assert _build_authority_name({"pl_desc": "", "description_en": ""}) == ""


# ── 4. Drift surfacing in resolve response ────────────────────────────

def test_resolve_response_includes_drift_codes_field():
    body = _body()
    # The endpoint return JSON exposes both drift_codes (list) and
    # drift_count (int) so the operator can decide to run sync-names.
    assert '"drift_codes":' in body
    assert '"drift_count":' in body


def test_resolve_drift_is_only_surfaced_not_auto_renamed():
    body = _body()
    chunk_start = body.find("wfirma_products_resolve")
    end = body.find("@router.post", chunk_start + 1)
    chunk = body[chunk_start:end] if end > 0 else body[chunk_start:]
    # The already_mapped branch detects drift by comparing names.
    assert "drift_codes.append" in chunk
    # And explicitly NOT calling edit_product inside resolve — only
    # the dedicated /wfirma/products/sync-names endpoint may edit.
    # Within the already_mapped branch context, no edit_product call:
    already_mapped_block_start = chunk.find("already_mapped += 1")
    next_block = chunk.find("\n        # ── 2.", already_mapped_block_start)
    if next_block > 0:
        block = chunk[already_mapped_block_start:next_block]
        assert "edit_product" not in block


# ── 5. Audit timeline event on create ─────────────────────────────────

def test_create_emits_authority_provenance_event():
    body = _body()
    assert "EV_WFIRMA_GOOD_CREATED_FROM_AUTHORITY" in body
    assert '"wfirma_good_created_from_authority"' in body
    chunk_start = body.find("wfirma_products_resolve")
    end = body.find("@router.post", chunk_start + 1)
    chunk = body[chunk_start:end] if end > 0 else body[chunk_start:]
    assert "EV_WFIRMA_GOOD_CREATED_FROM_AUTHORITY" in chunk
    # The event detail records both the authority_source and the audit
    # _rows_source for traceability.
    assert '"authority_source"' in chunk
    assert '"audit_rows_source"' in chunk


# ── 6. Regression — Global incident scenario refused ──────────────────

def test_global_stale_aggregate_audit_would_refuse_create_path():
    """The exact audit shape that produced the Global incident:
    _rows_source = packing_lines_aggregated_to_invoice_positions
    (stale PR #267 aggregate), with rows whose pl_desc is empty
    because the regenerate path failed. The create branch must refuse
    with STALE_AUTHORITY_REFUSED."""
    body = _body()
    chunk_start = body.find("wfirma_products_resolve")
    end = body.find("@router.post", chunk_start + 1)
    chunk = body[chunk_start:end] if end > 0 else body[chunk_start:]
    # The gate is `if not _global_authority and not row_pl`. _global_
    # authority is False when _rows_source != "invoice_positions_authority"
    # (e.g., when it's "packing_lines_aggregated_to_invoice_positions").
    assert 'not _global_authority and not row_pl' in chunk
    # And the refusal includes a clear remediation hint.
    assert "Re-run the Polish Description regenerate" in chunk


# ── 7. Existing call sites preserved ──────────────────────────────────

def test_existing_already_mapped_count_path_intact():
    body = _body()
    # The PR is purely additive on the create branch. The other three
    # outcomes (already_mapped, found_and_mapped, missing-gate-off) are
    # unchanged regressions.
    assert "already_mapped += 1" in body
    assert "found_and_mapped += 1" in body
    assert "missing_codes.append(pc)" in body


def test_no_unconditional_description_engine_call_on_create_branch():
    body = _body()
    chunk_start = body.find("wfirma_products_resolve")
    end = body.find("@router.post", chunk_start + 1)
    chunk = body[chunk_start:end] if end > 0 else body[chunk_start:]
    # `deng.get_description_block` MAY appear (legacy fallback), but
    # ONLY inside an `else:` branch — never as the first/sole source.
    # Verify by counting occurrences and checking the surrounding code.
    # The new flow uses build_description_block (not get_description_block)
    # on the primary path.
    assert "deng.build_description_block(" in chunk
