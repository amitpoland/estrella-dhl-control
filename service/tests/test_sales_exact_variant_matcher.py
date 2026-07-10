"""Slice 2 — batch-scoped exact variant matcher (Tier 2 of resolve_sales_lines_for_batch).

Covers the deterministic exact-signature tier that runs BEFORE the existing
reconciliation scorer:
  * _signature_specific_enough — sparse-signature guard
  * _match_clones_to_candidates — pure matcher (unique / shared / zero / sparse /
    all-or-nothing / never-invents)
  * _apply_exact_variant_match — DB-backed resolution against the Product Master
    (advisory signature source), incl. the no-op-when-empty safety property.

Guardrails pinned: batch-scoped (candidates only), never mints a product_code,
Master stays advisory, and the tier is a transparent no-op when Master
signatures are absent (existing scorer/scored-pending path unchanged).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services import reservation_db as rdb
from app.services.cpa_product_service import build_variant_signature
from app.services.proforma_draft_sync import (
    _signature_specific_enough,
    _match_clones_to_candidates,
    _apply_exact_variant_match,
)


def _clone(**kw):
    base = {"design_no": "CSTR001", "karat": "14KT", "metal_color": "W",
            "diamond_weight": 0.5, "quality_string": "G-VS", "color_weight": 0.0,
            "stone_type": "", "size": "7"}
    base.update(kw)
    return base


# ── _signature_specific_enough ────────────────────────────────────────────────

def test_specific_enough_true():
    assert _signature_specific_enough(build_variant_signature(_clone())) is True


def test_specific_enough_false_sparse():
    assert _signature_specific_enough("CSTR001|||||||") is False
    # only design_no + a single differentiating token → not specific enough
    assert _signature_specific_enough(
        build_variant_signature({"design_no": "D1", "karat": "14KT"})) is False


# ── _match_clones_to_candidates (pure) ────────────────────────────────────────

def test_match_unique():
    c14, c18 = _clone(), _clone(karat="18KT")
    cand = {"EJL/1-1": build_variant_signature(c14),
            "EJL/1-2": build_variant_signature(c18)}
    assert _match_clones_to_candidates([c14], cand) == {0: "EJL/1-1"}
    assert _match_clones_to_candidates([c18], cand) == {0: "EJL/1-2"}
    assert _match_clones_to_candidates([c14, c18], cand) == {0: "EJL/1-1", 1: "EJL/1-2"}


def test_match_shared_signature_none():
    c = _clone(); sig = build_variant_signature(c)
    assert _match_clones_to_candidates([c], {"EJL/1-1": sig, "EJL/1-2": sig}) is None


def test_match_zero_none():
    c = _clone()
    cand = {"EJL/1-1": build_variant_signature(_clone(karat="22KT"))}
    assert _match_clones_to_candidates([c], cand) is None


def test_match_sparse_none():
    c = {"design_no": "D1", "karat": "14KT"}  # 1 differentiating token
    assert _match_clones_to_candidates([c], {"EJL/1-1": build_variant_signature(c)}) is None


def test_match_all_or_nothing():
    c14, c_unmatched = _clone(), _clone(karat="22KT")
    cand = {"EJL/1-1": build_variant_signature(c14),
            "EJL/1-2": build_variant_signature(_clone(karat="18KT"))}
    # one clone can't be matched → the WHOLE design is handed to the scorer
    assert _match_clones_to_candidates([c14, c_unmatched], cand) is None


def test_match_never_invents():
    c = _clone()
    cand = {"EJL/1-1": build_variant_signature(c)}
    res = _match_clones_to_candidates([c], cand)
    assert res == {0: "EJL/1-1"}
    assert all(pc in cand for pc in res.values())


# ── _apply_exact_variant_match (DB-backed) ────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    return tmp_path / "reservation_queue.db"


def _seed_master(db: Path, code: str, design_no: str, sig: str) -> None:
    rdb.upsert_product_master(db, product_code=code, design_no=design_no,
                              source_batch_id="B1", normalized_design_attributes=sig)


def test_apply_resolves_ambiguous(env):
    c14, c18 = _clone(), _clone(karat="18KT")
    _seed_master(env, "EJL/1-1", "CSTR001", build_variant_signature(c14))
    _seed_master(env, "EJL/1-2", "CSTR001", build_variant_signature(c18))

    designs_ambiguous = {"CSTR001": ["EJL/1-1", "EJL/1-2"]}
    clones = {"CSTR001": [c14]}
    exact: dict = {}
    _apply_exact_variant_match("B1", designs_ambiguous, clones, exact)

    assert c14["product_code"] == "EJL/1-1"
    assert c14["resolution_source"] == "exact_variant_match"
    assert "CSTR001" not in designs_ambiguous            # removed from scorer input
    assert exact["CSTR001"]["assigned"] == ["EJL/1-1"]


def test_apply_no_match_leaves_ambiguous_for_scorer(env):
    _seed_master(env, "EJL/1-1", "CSTR001", build_variant_signature(_clone(karat="18KT")))
    _seed_master(env, "EJL/1-2", "CSTR001", build_variant_signature(_clone(karat="22KT")))
    c14 = _clone()  # matches neither candidate

    designs_ambiguous = {"CSTR001": ["EJL/1-1", "EJL/1-2"]}
    clones = {"CSTR001": [c14]}
    exact: dict = {}
    _apply_exact_variant_match("B1", designs_ambiguous, clones, exact)

    assert "product_code" not in c14                      # untouched
    assert "CSTR001" in designs_ambiguous                 # left for the scorer
    assert exact == {}


def test_apply_noop_when_master_signatures_empty(env):
    # Product Master rows exist but carry no signature (sync not yet run) → no-op.
    _seed_master(env, "EJL/1-1", "CSTR001", "")
    _seed_master(env, "EJL/1-2", "CSTR001", "")
    c14 = _clone()

    designs_ambiguous = {"CSTR001": ["EJL/1-1", "EJL/1-2"]}
    clones = {"CSTR001": [c14]}
    exact: dict = {}
    _apply_exact_variant_match("B1", designs_ambiguous, clones, exact)

    assert "CSTR001" in designs_ambiguous and exact == {}


# ── END-TO-END through resolve_sales_lines_for_batch (rebase addition) ───────
# The matcher was HELD as safe-but-inert because sales rows carried no variant
# fields. PFW Slice 1 (#870) now populates karat/metal_color/quality_string/
# size/diamond_weight/color_weight on every sales_packing line — this test
# drives the REAL resolver entry point with Slice-1-shaped rows over REAL
# packing_lines candidates + REAL Product Master signatures and proves the
# Tier-2 exact match resolves an ambiguous design deterministically.

def test_resolver_end_to_end_with_slice1_shaped_rows(env, tmp_path):
    from app.services import packing_db as pdb
    from app.services.proforma_draft_sync import resolve_sales_lines_for_batch

    # Real packing authority: one design, two candidate codes in this batch.
    pk_db = tmp_path / "packing.db"
    pdb.init_packing_db(pk_db)
    doc_id = pdb.upsert_packing_document(batch_id="B-E2E", source_file_path="pl.xlsx")
    pdb.upsert_packing_lines([
        {"packing_document_id": doc_id, "batch_id": "B-E2E", "invoice_no": "I1",
         "product_code": "EJL/1-1", "design_no": "CSTR001", "quantity": 1,
         "pack_sr": 1},
        {"packing_document_id": doc_id, "batch_id": "B-E2E", "invoice_no": "I1",
         "product_code": "EJL/1-2", "design_no": "CSTR001", "quantity": 1,
         "pack_sr": 2},
    ])

    # Real Master signatures (advisory identity) for both candidates.
    c14, c18 = _clone(), _clone(karat="18KT")
    _seed_master(env, "EJL/1-1", "CSTR001", build_variant_signature(c14))
    _seed_master(env, "EJL/1-2", "CSTR001", build_variant_signature(c18))

    # Slice-1-shaped sales row: variant fields populated, product_code empty.
    sales_row = {
        "client_name": "ACME", "design_no": "CSTR001", "product_code": "",
        "qty": 1, "unit_price": 300.0, "currency": "EUR",
        "karat": "14KT", "metal_color": "W", "quality_string": "G-VS",
        "stone_type": "", "size": "7", "diamond_weight": 0.5, "color_weight": 0.0,
    }
    resolved, summary = resolve_sales_lines_for_batch("B-E2E", [sales_row])

    assert len(resolved) == 1
    out = resolved[0]
    assert out["product_code"] == "EJL/1-1", \
        "Tier-2 exact variant match must resolve the 14KT row to its candidate"
    assert out["resolution_source"] == "exact_variant_match"
    assert "CSTR001" in summary["designs_exact_matched"]
    assert summary["designs_ambiguous"] == {}          # nothing left for the scorer
    assert summary["designs_scored_pending"] == {}     # no operator queue entry


def test_apply_only_assigns_candidate_codes(env):
    # even if a matching signature exists ONLY on a non-candidate code, the design
    # is not resolved (candidates are the batch authority; no cross-candidate leak)
    c14 = _clone()
    _seed_master(env, "EJL/1-1", "CSTR001", build_variant_signature(_clone(karat="18KT")))
    _seed_master(env, "EJL/1-2", "CSTR001", build_variant_signature(_clone(karat="22KT")))
    # a different code carries the matching sig but is NOT a candidate
    _seed_master(env, "EJL/9-9", "CSTR001", build_variant_signature(c14))

    designs_ambiguous = {"CSTR001": ["EJL/1-1", "EJL/1-2"]}
    clones = {"CSTR001": [c14]}
    exact: dict = {}
    _apply_exact_variant_match("B1", designs_ambiguous, clones, exact)

    assert "product_code" not in c14
    assert "CSTR001" in designs_ambiguous
