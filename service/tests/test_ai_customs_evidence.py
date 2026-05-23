"""test_ai_customs_evidence.py

Phase 2 of the Global Jewellery campaign — AI-assisted customs evidence
recovery layer. Validates:

  1. The trigger gate (should_invoke_ai) fires only on deterministic gaps.
  2. The provider abstraction is a safe no-op when unconfigured.
  3. Strict JSON normalisation rejects numeric noise + unknown keys.
  4. Reconciliation classifies outcomes correctly:
       - verified_with_advisory  (AI matches deterministic anchors)
       - operator_review_required (any mismatch)
       - ai_unavailable          (provider missing)
       - ai_low_confidence       (AI returned 'low')
  5. Estrella protection — no Estrella module imported or referenced;
     deterministic path is unchanged.

The provider call itself is stubbed in every test (no live API key
required to run the suite).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


_MOD_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "services" / "ai_customs_evidence.py"
)


# ── Module + schema contract ──────────────────────────────────────────────


def test_module_loads_and_exposes_public_api():
    from app.services.ai_customs_evidence import (
        should_invoke_ai, extract_customs_evidence, reconcile_evidence,
        build_audit_entry, EVIDENCE_SCHEMA,
    )
    assert callable(should_invoke_ai)
    assert callable(extract_customs_evidence)
    assert callable(reconcile_evidence)
    assert callable(build_audit_entry)


def test_schema_lists_all_required_fields():
    from app.services.ai_customs_evidence import EVIDENCE_SCHEMA
    required = {"invoice_refs", "awb", "mrn", "cif_usd", "exporter",
                "importer", "cn_codes", "confidence", "evidence"}
    assert set(EVIDENCE_SCHEMA.keys()) == required


# ── Trigger gate (should_invoke_ai) ──────────────────────────────────────


def test_gate_fires_on_verify_gap_warning():
    from app.services.ai_customs_evidence import should_invoke_ai
    anchors = {"invoice_refs": ["088/2026-2027"], "mrn": "X", "awb": "Y"}
    assert should_invoke_ai(anchors, warnings=["VERIFY-GAP: refs noisy"]) is True


def test_gate_fires_on_inferred_refs_warning():
    from app.services.ai_customs_evidence import should_invoke_ai
    assert should_invoke_ai(
        {"invoice_refs": ["088"], "mrn": "X", "awb": "Y"},
        warnings=["SAD invoice refs inferred from free text: ['3322','088']"],
    ) is True


def test_gate_fires_on_empty_invoice_refs():
    from app.services.ai_customs_evidence import should_invoke_ai
    assert should_invoke_ai({"invoice_refs": [], "mrn": "X", "awb": "Y"}) is True


def test_gate_fires_on_numeric_noise_only_refs():
    """The operator's exact production case: SAD parser produced refs
    like ['3322','121','1000','088','2026','2027','585'] — all digit
    runs, no structured invoice references."""
    from app.services.ai_customs_evidence import should_invoke_ai
    noisy = ["3322", "121", "1000", "088", "2026", "2027", "585"]
    assert should_invoke_ai({"invoice_refs": noisy, "mrn": "X", "awb": "Y"}) is True


def test_gate_fires_on_anchor_partner_missing():
    from app.services.ai_customs_evidence import should_invoke_ai
    # MRN present, AWB missing
    assert should_invoke_ai({"invoice_refs": ["088/2026-2027"],
                             "mrn": "26PL44302D00C2M4R4", "awb": ""}) is True
    # AWB present, MRN missing
    assert should_invoke_ai({"invoice_refs": ["088/2026-2027"],
                             "mrn": "", "awb": "4789974092"}) is True


def test_gate_fires_on_low_confidence_flag():
    from app.services.ai_customs_evidence import should_invoke_ai
    assert should_invoke_ai({
        "invoice_refs": ["088/2026-2027"], "mrn": "X", "awb": "Y",
        "confidence": "low",
    }) is True


def test_gate_does_not_fire_for_clean_deterministic_result():
    """When the deterministic parser produces a confident, complete
    result, the AI MUST NOT be invoked — preserves the authority chain."""
    from app.services.ai_customs_evidence import should_invoke_ai
    clean = {
        "invoice_refs": ["088/2026-2027"],
        "mrn":  "26PL44302D00C2M4R4",
        "awb":  "4789974092",
        "confidence": "high",
    }
    assert should_invoke_ai(clean, warnings=[]) is False


def test_gate_does_not_fire_on_empty_warnings_list():
    from app.services.ai_customs_evidence import should_invoke_ai
    assert should_invoke_ai({
        "invoice_refs": ["EJL/26-27/180"], "mrn": "X", "awb": "Y",
    }, warnings=[]) is False


# ── Provider abstraction — safe no-op ────────────────────────────────────


def test_extract_returns_none_when_provider_unconfigured(monkeypatch):
    """No API key configured → extract returns None without calling
    any network. Deterministic path continues unchanged."""
    import app.services.ai_customs_evidence as _mod
    monkeypatch.setattr(_mod, "_provider_available", lambda: False)
    out = _mod.extract_customs_evidence("any text", document_hint="SAD")
    assert out is None


def test_extract_returns_none_on_empty_text(monkeypatch):
    import app.services.ai_customs_evidence as _mod
    monkeypatch.setattr(_mod, "_provider_available", lambda: True)
    assert _mod.extract_customs_evidence("") is None
    assert _mod.extract_customs_evidence("   ") is None


def test_extract_handles_provider_call_failure(monkeypatch):
    """Anthropic API raises → returns None, deterministic path runs."""
    import app.services.ai_customs_evidence as _mod
    monkeypatch.setattr(_mod, "_provider_available", lambda: True)

    # Stub the import + client to raise
    import sys
    fake_anthropic = type(sys)("anthropic_fake")
    class _FakeClient:
        def __init__(self, api_key): pass
        @property
        def messages(self_inner):
            class _M:
                def create(self_inner, **kw):
                    raise RuntimeError("network blip")
            return _M()
    fake_anthropic.Anthropic = _FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    out = _mod.extract_customs_evidence("text", document_hint="SAD")
    assert out is None


def test_extract_handles_non_json_response(monkeypatch):
    """Provider returned text that doesn't parse as JSON → None."""
    import app.services.ai_customs_evidence as _mod
    monkeypatch.setattr(_mod, "_provider_available", lambda: True)

    import sys
    class _Resp:
        def __init__(self, text):
            self.content = [type("X", (), {"text": text})()]
    fake = type(sys)("anthropic_fake2")
    class _FakeClient:
        def __init__(self, api_key): pass
        class messages:
            @staticmethod
            def create(**kw):
                return _Resp("not json — sorry")
    fake.Anthropic = _FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    out = _mod.extract_customs_evidence("text", document_hint="SAD")
    assert out is None


# ── JSON normalisation ────────────────────────────────────────────────────


def test_normalise_strips_numeric_noise_invoice_refs():
    from app.services.ai_customs_evidence import _normalise_response
    out = _normalise_response({
        "invoice_refs": ["088/2026-2027", "3322", "088", "2026", "EJL/26-27/180"],
    })
    # Pure-digit-noise tokens dropped; structured refs kept
    assert "3322" not in out["invoice_refs"]
    assert "2026" not in out["invoice_refs"]
    assert "088/2026-2027" in out["invoice_refs"]
    assert "EJL/26-27/180" in out["invoice_refs"]


def test_normalise_drops_unknown_keys():
    from app.services.ai_customs_evidence import _normalise_response
    out = _normalise_response({
        "invoice_refs": ["088/2026-2027"],
        "this_is_not_in_schema": "garbage",
        "also_unknown":          42,
    })
    assert "this_is_not_in_schema" not in out
    assert "also_unknown" not in out


def test_normalise_fills_missing_keys_with_safe_defaults():
    from app.services.ai_customs_evidence import _normalise_response
    out = _normalise_response({})
    assert out["invoice_refs"] == []
    assert out["awb"] is None
    assert out["mrn"] is None
    assert out["cif_usd"] is None
    assert out["cn_codes"] == []
    assert out["confidence"] == "low"
    assert out["evidence"] == []


def test_normalise_coerces_cif_to_float():
    from app.services.ai_customs_evidence import _normalise_response
    assert _normalise_response({"cif_usd": "3322.00"})["cif_usd"] == 3322.00
    assert _normalise_response({"cif_usd": 3172})["cif_usd"] == 3172.0
    assert _normalise_response({"cif_usd": "not-a-number"})["cif_usd"] is None


def test_normalise_clamps_confidence_to_allowed_values():
    from app.services.ai_customs_evidence import _normalise_response
    assert _normalise_response({"confidence": "HIGH"})["confidence"] == "high"
    assert _normalise_response({"confidence": "garbage"})["confidence"] == "low"
    assert _normalise_response({"confidence": None})["confidence"] == "low"


# ── Reconciliation ────────────────────────────────────────────────────────


def test_reconcile_returns_ai_unavailable_when_block_is_none():
    from app.services.ai_customs_evidence import reconcile_evidence
    r = reconcile_evidence(None, anchors={"mrn": "X", "awb": "Y"})
    assert r["status"] == "ai_unavailable"
    assert r["matches"] == []
    assert r["mismatches"] == []


def test_reconcile_returns_low_confidence_when_ai_says_low():
    from app.services.ai_customs_evidence import reconcile_evidence
    block = {"confidence": "low", "mrn": "X", "awb": "Y", "evidence": ["q1"]}
    r = reconcile_evidence(block, anchors={"mrn": "X", "awb": "Y"})
    assert r["status"] == "ai_low_confidence"


def test_reconcile_verified_with_advisory_on_full_match():
    """AI confirms MRN + AWB + CIF + invoice_refs → verified_with_advisory."""
    from app.services.ai_customs_evidence import reconcile_evidence
    block = {
        "confidence":   "high",
        "mrn":          "26PL44302D00C2M4R4",
        "awb":          "4789974092",
        "cif_usd":      3322.00,
        "invoice_refs": ["088/2026-2027"],
        "evidence":     ["MRN: 26PL44302D00C2M4R4 (page 1)"],
    }
    anchors = {
        "mrn":          "26PL44302D00C2M4R4",
        "awb":          "4789974092",
        "cif_usd":      3322.00,
        "invoice_refs": ["088/2026-2027"],
    }
    r = reconcile_evidence(block, anchors)
    assert r["status"] == "verified_with_advisory"
    for m in ("mrn", "awb", "cif_usd", "invoice_refs"):
        assert m in r["matches"], f"expected {m} in matches"
    assert r["mismatches"] == []
    assert "SAD verified by" in r["advisory"]


def test_reconcile_operator_review_on_mrn_mismatch():
    """AI reports a different MRN than the deterministic anchor →
    blocker remains."""
    from app.services.ai_customs_evidence import reconcile_evidence
    block = {
        "confidence":   "high",
        "mrn":          "26PL44302D00A1J5R7",  # wrong
        "awb":          "4789974092",
        "cif_usd":      3322.00,
        "invoice_refs": ["088/2026-2027"],
    }
    anchors = {
        "mrn":          "26PL44302D00C2M4R4",  # different
        "awb":          "4789974092",
        "cif_usd":      3322.00,
        "invoice_refs": ["088/2026-2027"],
    }
    r = reconcile_evidence(block, anchors)
    assert r["status"] == "operator_review_required"
    assert any(m["field"] == "mrn" for m in r["mismatches"])
    assert "operator review required" in r["advisory"]


def test_reconcile_cif_tolerance_passes_within_one_dollar():
    """CIF drift within tolerance → match (no mismatch raised)."""
    from app.services.ai_customs_evidence import reconcile_evidence
    block = {
        "confidence": "high",
        "mrn": "X", "awb": "Y",
        "cif_usd": 3322.50,
        "invoice_refs": ["088/2026-2027"],
    }
    anchors = {"mrn": "X", "awb": "Y", "cif_usd": 3322.00,
               "invoice_refs": ["088/2026-2027"]}
    r = reconcile_evidence(block, anchors, cif_tolerance=1.00)
    assert r["status"] == "verified_with_advisory"
    assert "cif_usd" in r["matches"]


def test_reconcile_cif_drift_above_tolerance_blocks():
    from app.services.ai_customs_evidence import reconcile_evidence
    block = {
        "confidence": "high",
        "mrn": "X", "awb": "Y", "cif_usd": 3500.00,
        "invoice_refs": ["088/2026-2027"],
    }
    anchors = {"mrn": "X", "awb": "Y", "cif_usd": 3322.00,
               "invoice_refs": ["088/2026-2027"]}
    r = reconcile_evidence(block, anchors)
    assert r["status"] == "operator_review_required"
    assert any(m["field"] == "cif_usd" for m in r["mismatches"])


def test_reconcile_invoice_refs_substring_match():
    """AI may return prefix like 'N935-088/2026-2027' for the same
    invoice — substring match handles the supplier prefix variant."""
    from app.services.ai_customs_evidence import reconcile_evidence
    block = {
        "confidence":   "high",
        "mrn": "X", "awb": "Y", "cif_usd": 3322.00,
        "invoice_refs": ["N935-088/2026-2027"],
    }
    anchors = {"mrn": "X", "awb": "Y", "cif_usd": 3322.00,
               "invoice_refs": ["088/2026-2027"]}
    r = reconcile_evidence(block, anchors)
    assert r["status"] == "verified_with_advisory"
    assert "invoice_refs" in r["matches"]


def test_reconcile_invoice_refs_noise_anchors_ignored():
    """If the anchor refs are all numeric noise (production scenario:
    deterministic parser found '3322','121','1000','088'), the AI's
    real refs should still count as a recovery — not a mismatch."""
    from app.services.ai_customs_evidence import reconcile_evidence
    block = {
        "confidence":   "high",
        "mrn": "X", "awb": "Y", "cif_usd": 3322.00,
        "invoice_refs": ["088/2026-2027"],
    }
    # All-noise anchors
    anchors = {"mrn": "X", "awb": "Y", "cif_usd": 3322.00,
               "invoice_refs": ["3322", "121", "1000", "088", "585"]}
    r = reconcile_evidence(block, anchors)
    # No real anchor to compare → no mismatch raised → verified_with_advisory
    assert r["status"] == "verified_with_advisory"


def test_reconcile_invoice_refs_recovered_when_anchor_empty():
    """Anchor refs empty + AI recovered structured ref → counted as
    recovery match (informational)."""
    from app.services.ai_customs_evidence import reconcile_evidence
    block = {
        "confidence":   "high",
        "mrn": "X", "awb": "Y", "cif_usd": 3322.00,
        "invoice_refs": ["088/2026-2027"],
    }
    anchors = {"mrn": "X", "awb": "Y", "cif_usd": 3322.00, "invoice_refs": []}
    r = reconcile_evidence(block, anchors)
    assert r["status"] == "verified_with_advisory"
    assert "invoice_refs_recovered" in r["matches"]


# ── Audit storage shape ──────────────────────────────────────────────────


def test_build_audit_entry_shape():
    from app.services.ai_customs_evidence import build_audit_entry
    ai = {"mrn": "X", "confidence": "high", "evidence": ["q1"]}
    recon = {"status": "verified_with_advisory", "matches": ["mrn"],
             "mismatches": [], "advisory": "ok", "evidence": ["q1"]}
    e = build_audit_entry(ai, recon)
    assert e["schema_version"] == 1
    assert e["ai_block"] == ai
    assert e["reconciliation"] == recon
    assert "stored_at" in e and isinstance(e["stored_at"], str)


def test_build_audit_entry_with_none_ai_block():
    """When extract_customs_evidence returned None, build_audit_entry
    still produces a valid record (with empty ai_block) so the audit
    has a trace of the attempt."""
    from app.services.ai_customs_evidence import build_audit_entry
    recon = {"status": "ai_unavailable", "matches": [], "mismatches": [],
             "advisory": "AI unavailable", "evidence": []}
    e = build_audit_entry(None, recon)
    assert e["ai_block"] == {}
    assert e["reconciliation"]["status"] == "ai_unavailable"


# ── Safety / Estrella protection invariants ──────────────────────────────


def test_module_does_not_import_estrella_supplier_modules():
    body = _MOD_PATH.read_text(encoding="utf-8")
    forbidden_imports = (
        "invoice_intake_parser",
        "customs_description_engine",
        "product_identity_engine",
        "description_engine",
        "global_invoice_parser",
        "global_packing_parser",
    )
    for tok in forbidden_imports:
        assert tok not in body, (
            f"AI evidence module must not import {tok!r} — keeps the "
            "deterministic supplier path isolated from the AI layer"
        )


def test_module_does_not_reference_forbidden_write_paths():
    body = _MOD_PATH.read_text(encoding="utf-8")
    forbidden = (
        "WFIRMA_CREATE_", "create_invoice", "create_pz",
        "_guard_wfirma_export", "post_to_wfirma",
        "compute_cif", "DHL_BROKER_THRESHOLD",
        "duty_pln", "vat_pln",  # AI may not name these fields
    )
    for tok in forbidden:
        assert tok not in body, (
            f"AI evidence module must not reference {tok!r}"
        )


def test_system_prompt_locks_extraction_only_rule():
    """The prompt MUST instruct the AI to never calculate / derive /
    infer values — extraction only. Without that rule the AI could
    silently change customs facts."""
    from app.services.ai_customs_evidence import _SYSTEM_PROMPT
    assert "NEVER calculate" in _SYSTEM_PROMPT
    assert "infer" in _SYSTEM_PROMPT.lower() or "never" in _SYSTEM_PROMPT.lower()
    assert "verbatim" in _SYSTEM_PROMPT.lower()
    assert "ONLY the JSON object" in _SYSTEM_PROMPT \
           or "Return ONLY the JSON" in _SYSTEM_PROMPT


def test_provider_unavailable_when_settings_key_absent(monkeypatch):
    """Removing the anthropic_api_key must make _provider_available
    return False — the foundation of the safe no-op contract."""
    import app.services.ai_customs_evidence as _mod
    from app.core.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    assert _mod._provider_available() is False


# ── End-to-end: noisy SAD → AI recovers 088/2026-2027 ────────────────────


def test_end_to_end_global_noisy_sad_refs_recovered(monkeypatch):
    """Production scenario: deterministic SAD parser extracted noisy
    refs ['3322','121','1000','088','2026','2027','585']. The gate
    fires, AI returns '088/2026-2027', reconciler classifies as
    verified_with_advisory."""
    import app.services.ai_customs_evidence as _mod
    from unittest.mock import MagicMock, patch

    # Stub provider as available, with a canned response
    monkeypatch.setattr(_mod, "_provider_available", lambda: True)

    canned = json.dumps({
        "invoice_refs": ["088/2026-2027"],
        "awb":          "4789974092",
        "mrn":          "26PL44302D00C2M4R4",
        "cif_usd":      3322.00,
        "exporter":     "Global Jewellery Pvt. Ltd.",
        "importer":     "Estrella Jewels Sp. z o.o., Sp. k.",
        "cn_codes":     ["71131911"],
        "confidence":   "high",
        "evidence":     ["Exporter's Ref: 088/2026-2027 (page 1)",
                         "MRN: 26PL44302D00C2M4R4"],
    })
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = canned
    monkeypatch.setattr("app.services.ai_gateway", mock_gateway, raising=False)

    # Gate check
    noisy_anchors = {
        "invoice_refs": ["3322", "121", "1000", "088", "2026", "2027", "585"],
        "mrn":          "26PL44302D00C2M4R4",
        "awb":          "4789974092",
        "cif_usd":      3322.00,
    }
    assert _mod.should_invoke_ai(noisy_anchors) is True

    # AI extracts
    ai_block = _mod.extract_customs_evidence(
        pdf_text="…SAD text content…",
        document_hint="SAD/ZC429",
    )
    assert ai_block is not None
    assert "088/2026-2027" in ai_block["invoice_refs"]
    assert ai_block["mrn"] == "26PL44302D00C2M4R4"
    assert ai_block["confidence"] == "high"

    # Reconcile
    recon = _mod.reconcile_evidence(ai_block, noisy_anchors)
    assert recon["status"] == "verified_with_advisory"
    # MRN + AWB + CIF + invoice_refs all confirmed
    for m in ("mrn", "awb", "cif_usd"):
        assert m in recon["matches"]


def test_end_to_end_ai_disagreement_remains_blocker(monkeypatch):
    """Even if the AI is confident, a real value disagreement with the
    deterministic anchor MUST classify as operator_review_required —
    the AI cannot override deterministic facts."""
    import app.services.ai_customs_evidence as _mod
    from unittest.mock import MagicMock
    monkeypatch.setattr(_mod, "_provider_available", lambda: True)

    bad = json.dumps({
        "invoice_refs": ["088/2026-2027"],
        "awb":          "4789974092",
        "mrn":          "26PL44302D00C2M4R4",
        "cif_usd":      9999.99,  # AI says a different value
        "confidence":   "high",
        "evidence":     ["fake quote"],
    })
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = bad
    monkeypatch.setattr("app.services.ai_gateway", mock_gateway, raising=False)

    ai_block = _mod.extract_customs_evidence(pdf_text="X")
    anchors = {
        "invoice_refs": [], "mrn": "26PL44302D00C2M4R4",
        "awb": "4789974092", "cif_usd": 3322.00,
    }
    recon = _mod.reconcile_evidence(ai_block, anchors)
    assert recon["status"] == "operator_review_required"
    assert any(m["field"] == "cif_usd" for m in recon["mismatches"])
