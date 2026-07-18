"""
test_packing_reextract_v2_parity.py — Source-grep contract for the V2 packing
re-extract action (V1/V2 extraction parity).

V1 (shipment-detail.html) already has a working batch-level re-extract
("Reparse all" → POST /api/v1/packing/{batch_id}/reprocess). These tests pin
the equivalent V2 wiring that closes the parity gap:

  1. pz-api.js exposes a transport-only reprocessPacking(batchId) that POSTs the
     CANONICAL existing endpoint (no new/duplicate endpoint, no business logic).
  2. proforma-detail.jsx SourceExtractionTab exposes a Re-extract action wired to
     it, refreshes rows/status after completion, and surfaces honest state.
  3. No technical metadata (paths/hashes/model names/prompts/tokens) is added to
     the operator-facing wiring.

Source-grep only — no HTTP, no browser. Matches the V2-contract test convention.
"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).parents[1] / "app" / "static"
PZ_API = STATIC / "v2" / "pz-api.js"
PROFORMA = STATIC / "v2" / "proforma-detail.jsx"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    return p.read_text(encoding="utf-8")


def _handler_body(src: str) -> str:
    """The reextractPacking handler body (const … up to its closing '\\n  };')."""
    i = src.index("const reextractPacking")
    j = src.index("\n  };", i)
    return src[i:j]


def _reextract_button_block(src: str) -> str:
    i = src.index('data-testid="pf-source-reextract"')
    return src[i:src.index("</button>", i)]


def _region(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


# ── Named regions of the reextractPacking handler (branch-scoped assertions) ──
def _warn_consts(src):      return _region(src, "const refreshWarn", "setReextract({ busy: true")
def _result_failure(src):   return _region(src, "[A] mutation RESULT failure", "[C] interpret")
def _interp_catch(src):     return _region(src, "catch (_interp)", "[FINAL] mutation outcome")
def _final_success(src):    return _region(src, "[FINAL] mutation outcome", "[BLOCK A] notify parent")
def _block_a_onsaved(src):  return _region(src, "[BLOCK A] notify parent", "[BLOCK B] refresh")
def _block_b_refresh(src):  return _region(src, "[BLOCK B] refresh", "[B] TRANSPORT/mutation rejection ONLY")
def _rejection_B(src):
    body = _handler_body(src)
    return body[body.index("[B] TRANSPORT/mutation rejection ONLY"):]


def test_pz_api_exposes_reprocess_transport():
    src = _read(PZ_API)
    assert "reprocessPacking" in src, "pz-api.js must expose reprocessPacking"
    # Canonical existing endpoint — reuse, not a new/duplicate route.
    assert "/packing/" in src and "/reprocess" in src
    # Mutation transport (X-Operator via _postM), not a read-like POST.
    assert "reprocessPacking:" in src
    idx = src.index("reprocessPacking:")
    body = src[idx:idx + 260]
    assert "_postM(" in body, "re-extract is a mutation → must use _postM"
    assert "/reprocess" in body


def test_pz_api_reprocess_invents_no_new_endpoint():
    src = _read(PZ_API)
    idx = src.index("reprocessPacking:")
    body = src[idx:idx + 260]
    # Only the canonical reprocess path; no reprocess-v2/new variants.
    assert "reprocess-v2" not in body and "reextract" not in body.lower().replace(
        "reprocesspacking", "")


def test_proforma_detail_has_reextract_action():
    src = _read(PROFORMA)
    assert 'data-testid="pf-source-reextract"' in src, "Re-extract button testid missing"
    assert "reextractPacking" in src, "re-extract handler missing"
    assert "window.PzApi.reprocessPacking(batchId)" in src, \
        "must call the canonical batch-level reprocess transport"


def test_no_chained_catch_writes_mutation_failure():
    # (1) No `.catch(...)` of ANY form is chained on the reprocessPacking promise,
    # so a success-handler throw can never be caught as red mutation failure.
    # Transport rejection uses the 2nd arg of .then. (Form-agnostic — counts every
    # `.catch(` so a future `.catch(err =>` / `.catch(function` cannot slip in.)
    src = _read(PROFORMA)
    body = _handler_body(src)
    assert "reprocessPacking(batchId).then(" in body
    assert "[B] TRANSPORT/mutation rejection ONLY" in body   # rejection = 2nd arg
    # The ONLY .catch in the whole handler is the inner apiFetch refresh catch.
    assert body.count(".catch(") == 1
    assert ".catch(" in _block_b_refresh(src)


def test_transport_rejection_uses_then_rejection_arg():
    # (2)(5) Transport/original-promise rejection is the 2nd arg of .then and writes
    # red mutation failure. It cannot catch success-handler exceptions.
    rej = _rejection_B(_read(PROFORMA))
    assert "ok: false" in rej and "'Re-extract failed'" in rej and "busy: false" in rej


def test_only_result_or_transport_paths_write_mutation_failure():
    # (5) Red mutation failure ONLY on a failed /reprocess RESULT ([A]) or a
    # transport rejection ([B]); NO post-success branch writes err/ok:false.
    src = _read(PROFORMA)
    assert "'Re-extract failed'" in _result_failure(src) and "ok: false" in _result_failure(src)
    for region in (_interp_catch(src), _final_success(src),
                   _block_a_onsaved(src), _block_b_refresh(src)):
        assert "Re-extract failed" not in region
        assert "ok: false" not in region


def test_response_interpretation_throw_is_advisory_not_red():
    # (3) A synchronous throw while interpreting a SUCCESSFUL response preserves
    # success (ok:true) and shows an amber advisory — never red, never fake counts.
    c = _interp_catch(_read(PROFORMA))
    assert "ok: true" in c and "warn: resultWarn" in c and "err: null" in c
    assert "Re-extract failed" not in c and "ok: false" not in c
    assert "Re-extraction completed." in c          # no fabricated row/file counts


def test_malformed_files_cannot_throw_through_filter():
    # (4) data.files is normalised to an array before .filter, so a malformed
    # payload cannot throw.
    body = _handler_body(_read(PROFORMA))
    assert "Array.isArray(d.files) ? d.files : []" in body
    assert "resultFiles.filter(" in body
    assert "(d.files || []).filter" not in body     # old unsafe form is gone


def test_mutation_success_is_final_and_carries_no_error():
    # (6) Success committed with busy:false BEFORE any presentation step; no err.
    fs = _final_success(_read(PROFORMA))
    assert "busy: false" in fs and "ok, err: null" in fs and "msg" in fs
    assert "ok: false" not in fs


def test_onsaved_failure_is_advisory_not_mutation_failure():
    # (6) A throwing onSaved is caught locally, preserves ok+msg, sets warn.
    a = _block_a_onsaved(_read(PROFORMA))
    assert "try {" in a and "catch" in a and "if (onSaved) onSaved();" in a
    assert "warn: onSavedWarn" in a and "ok, msg" in a and "err: null" in a
    assert "Re-extract failed" not in a and "ok: false" not in a


def test_refresh_failure_is_advisory_not_mutation_failure():
    # (6) Refresh failure preserves ok+msg, sets warn; guarded sync + async.
    b = _block_b_refresh(_read(PROFORMA))
    assert "/extraction" in b and "setData(" in b   # explicit refresh, not reload()
    assert "warn: refreshWarn" in b and "ok, msg" in b
    assert "Re-extract failed" not in b and "ok: false" not in b
    assert ".catch(" in b and "try {" in b and "catch (" in b
    # Refresh SUCCESS clears a refresh advisory but PRESERVES an onSaved advisory
    # (the parent notify failed even though this tab refreshed) — not a blanket wipe.
    assert "warn: onSavedFailed ? onSavedWarn : null" in b


def test_onsaved_advisory_persists_through_successful_refresh():
    # M2: a throwing onSaved sets a flag; a subsequent SUCCESSFUL refresh must not
    # silently erase that advisory (the parent stayed stale).
    src = _read(PROFORMA)
    a = _block_a_onsaved(src)
    b = _block_b_refresh(src)
    assert "onSavedFailed = true" in a                       # flag set on onSaved throw
    assert "onSavedFailed ? onSavedWarn : null" in b         # preserved on refresh success


def test_warn_wording_is_honest_and_distinct():
    # All three advisories say the extraction COMPLETED; none claims failure or an
    # unverified preservation guarantee.
    w = _warn_consts(_read(PROFORMA))
    assert "could not be loaded" in w                        # refresh
    assert "part of the page could not be refreshed" in w    # onSaved
    assert "could not be displayed" in w                     # result-interpretation
    assert w.count("Re-extraction completed") >= 3
    assert "Re-extract failed" not in w and "preserved" not in w


def test_busy_always_clears_on_every_branch():
    # (7) busy:true set once (initial); every terminal branch clears it.
    src = _read(PROFORMA)
    assert _handler_body(src).count("busy: true") == 1
    for region in (_result_failure(src), _interp_catch(src), _final_success(src),
                   _block_a_onsaved(src), _block_b_refresh(src), _rejection_B(src)):
        assert "busy: false" in region


def test_reextract_honesty_and_no_metadata_intact():
    # per-file partial + zero-row honesty; explicit refresh; no metadata leak.
    body = _handler_body(_read(PROFORMA))
    assert "did not extract" in body and "d.files" in body
    assert "no rows extracted" in body
    assert "/extraction" in body and "setData(" in body
    for forbidden in ("file_path", "sha256", "claude-", "prompt", "token"):
        assert forbidden not in body, f"technical metadata leaked: {forbidden}"


def test_no_operator_facing_preservation_claim():
    # BLOCKER 1: the UNVERIFIED "rows preserved" guarantee must not appear in the
    # re-extract handler or the button tooltip. (Scoped — an unrelated pre-existing
    # action legitimately uses the phrase.)
    src = _read(PROFORMA)
    for region in (_handler_body(src), _reextract_button_block(src)):
        assert "confirmed rows preserved" not in region
        assert "are preserved" not in region
        assert "rows preserved" not in region


def test_distinct_render_targets():
    # Three mutually exclusive render testids for the three states.
    src = _read(PROFORMA)
    for tid in ("pf-source-reextract-msg", "pf-source-reextract-warn", "pf-source-reextract-err"):
        assert f'data-testid="{tid}"' in src


def test_v1_reextract_authority_unchanged():
    # Parity does not touch V1 — the working "Reparse all" reprocess call stays.
    v1 = _read(STATIC / "shipment-detail.html")
    assert "/reprocess" in v1 and "packing-list-reparse-all" in v1
