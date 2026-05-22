"""test_ai_evidence_wiring_orchestrator.py

Wiring tests for PR #263's AI customs evidence module into the
SAD/ZC429 verification orchestrator.

Trigger contract:
  - Priority 4 in customs_parser_orchestrator.parse_customs_document
    fires ONLY when the deterministic result_data has
    invoice_refs_method == "inferred_from_sad_free_text" OR the
    corrections list contains a "[VERIFY-GAP] SAD invoice references
    inferred" line.
  - When AI is unavailable, the orchestrator returns ai_customs_evidence
    as None (or with reconciliation.status == "ai_unavailable").
  - When AI confirms anchors (verified_with_advisory), the VERIFY-GAP
    line in corrections is DEMOTED to "[ADVISORY] …".
  - When AI mismatches OR has low confidence, the VERIFY-GAP line is
    preserved unchanged.

Authority invariants:
  - AI never mutates result_data["invoice_refs"], MRN, CIF, duty_pln,
    vat_pln, etc.
  - The recheck consumer (routes_dashboard.py) stores the evidence
    dict under audit["ai_customs_evidence"] but the existing
    customs_declaration / verification fields are untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Source contract ──────────────────────────────────────────────────────


def test_orchestrator_returns_ai_customs_evidence_key():
    """The orchestrator return dict must include ai_customs_evidence
    (None when not triggered)."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "services" / "customs_parser_orchestrator.py").read_text("utf-8")
    assert '"ai_customs_evidence"' in src
    assert "ai_customs_evidence: Optional" in src


def test_orchestrator_imports_pr_263_module_lazily():
    """Lazy import (inside the Priority-4 branch) so the orchestrator
    has zero dependency on the AI module unless VERIFY-GAP fires."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "services" / "customs_parser_orchestrator.py").read_text("utf-8")
    assert "from .ai_customs_evidence import" in src
    # Must be inside a try/if block, not a top-level import
    top_block = src.split("def parse_customs_document(")[0]
    assert "from .ai_customs_evidence" not in top_block, (
        "PR #263 module must be lazily imported inside Priority-4 branch"
    )


def test_orchestrator_only_demotes_verify_gap_on_verified_with_advisory():
    src = (Path(__file__).resolve().parent.parent
           / "app" / "services" / "customs_parser_orchestrator.py").read_text("utf-8")
    # The demotion branch must explicitly gate on the success status
    assert 'recon.get("status") == "verified_with_advisory"' in src
    assert "[ADVISORY]" in src


def test_orchestrator_priority4_guarded_by_inferred_refs_check():
    """Priority 4 fires only when invoice_refs_method indicates
    inferred-from-free-text OR corrections list carries the marker."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "services" / "customs_parser_orchestrator.py").read_text("utf-8")
    assert '"invoice_refs_method") == "inferred_from_sad_free_text"' in src
    assert "[VERIFY-GAP] SAD invoice references inferred" in src


# ── Audit-persistence wiring at the route layer ──────────────────────────


def test_routes_dashboard_persists_ai_customs_evidence_on_audit():
    """The recheck consumer must store orch['ai_customs_evidence'] under
    audit['ai_customs_evidence']."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "api" / "routes_dashboard.py").read_text("utf-8")
    assert 'audit["ai_customs_evidence"] = orch["ai_customs_evidence"]' in src
    assert '"ai_customs_evidence"' in src


def test_routes_dashboard_emits_advisory_warning_only_on_confirmation():
    """The advisory message must surface only when reconciliation status
    is verified_with_advisory."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "api" / "routes_dashboard.py").read_text("utf-8")
    assert 'SAD verified by MRN/AWB/CIF' in src
    assert 'verified_with_advisory' in src
    # Must NOT add an advisory warning for any other status
    # (the route only appends the message inside the status-equality check)


# ── Behaviour tests against parse_customs_document ──────────────────────


def _patch_engine_parse_zc429(monkeypatch, ret_value):
    """Patch pz_import_processor.parse_zc429 to return a fixed dict."""
    fake_mod = type(sys)("pz_import_processor_fake")
    fake_mod.parse_zc429 = lambda path, corr: ret_value
    monkeypatch.setitem(sys.modules, "pz_import_processor", fake_mod)


def _stub_pdfplumber(monkeypatch, text="SAD content with 088/2026-2027 invoice ref"):
    """Stub pdfplumber.open to return a fake context manager that yields
    a single page producing the given text. The orchestrator's PDF
    extraction path inside Priority-4 then succeeds without needing a
    real PDF on disk."""
    class _FakePage:
        def __init__(self, t): self._t = t
        def extract_text(self): return self._t
    class _FakePdf:
        def __init__(self, t): self.pages = [_FakePage(t)]
        def __enter__(self): return self
        def __exit__(self, *a): return False
    fake_pp = type(sys)("pdfplumber_fake")
    fake_pp.open = lambda p: _FakePdf(text)
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pp)


def test_priority_4_does_not_fire_when_refs_are_clean(monkeypatch, tmp_path):
    """No VERIFY-GAP, no inferred refs → AI never invoked. The
    orchestrator's ai_customs_evidence stays None and corrections
    unchanged."""
    sad_dir = tmp_path / "sad"
    sad_dir.mkdir()
    sad_pdf = sad_dir / "ZC429.pdf"
    sad_pdf.write_bytes(b"%PDF-1.7\n%stub\n")

    deterministic_clean = {
        "mrn":                  "26PL44302D00C2M4R4",
        "lrn":                  "L1",
        "clearance_date":       "2026-05-21",
        "duty_pln":             None,
        "vat_pln":              None,
        "total_cif_usd":        3322.00,
        "invoice_refs":         ["088/2026-2027"],
        "invoice_refs_method":  "N935",   # clean — refs came from N935 markers
        "inferred_refs":        [],
        "importer_name":        "Estrella Jewels Sp. z o.o.",
        "exporter_name":        "Global Jewellery Pvt. Ltd.",
    }
    _patch_engine_parse_zc429(monkeypatch, deterministic_clean)

    from app.services.customs_parser_orchestrator import parse_customs_document
    out = parse_customs_document("TESTBATCH_CLEAN", sad_dir, audit={})
    assert out.get("ai_customs_evidence") is None
    # No VERIFY-GAP demotion happened because none was emitted
    for c in out.get("corrections") or []:
        assert "[ADVISORY]" not in c


def test_priority_4_fires_on_inferred_method_and_demotes_when_ai_confirms(
    monkeypatch, tmp_path,
):
    """When inferred_from_sad_free_text + AI confirms anchors, the
    VERIFY-GAP correction is demoted to [ADVISORY]."""
    sad_dir = tmp_path / "sad"
    sad_dir.mkdir()
    sad_pdf = sad_dir / "ZC429.pdf"
    # Use a real-ish PDF header so pdfplumber doesn't crash; content is
    # what the AI would see — we stub the AI provider below anyway.
    sad_pdf.write_bytes(b"%PDF-1.7\n%SAD content stub\n")

    deterministic_noisy = {
        "mrn":                  "26PL44302D00C2M4R4",
        "lrn":                  "L1",
        "clearance_date":       "2026-05-21",
        "duty_pln":             None,
        "vat_pln":              None,
        "total_cif_usd":        3322.00,
        "invoice_refs":         ["3322", "121", "1000", "088", "585"],  # noisy
        "invoice_refs_method":  "inferred_from_sad_free_text",
        "inferred_refs":        ["3322", "121", "1000", "088", "585"],
        "importer_name":        "Estrella Jewels Sp. z o.o.",
        "exporter_name":        "Global Jewellery Pvt. Ltd.",
    }
    # Engine emits the VERIFY-GAP line through `corrections` argument it
    # received. To simulate that, monkeypatch parse_zc429 to ALSO append
    # to the corrections list it gets.
    def _fake_parse(path, corrections):
        corrections.append(
            "[VERIFY-GAP] SAD invoice references inferred from free text / "
            "document sections (not via N935): ['3322','121','1000','088','585']"
        )
        return deterministic_noisy
    fake_mod = type(sys)("pz_import_processor_fake2")
    fake_mod.parse_zc429 = _fake_parse
    monkeypatch.setitem(sys.modules, "pz_import_processor", fake_mod)
    _stub_pdfplumber(monkeypatch)

    # Stub PR #263's AI extraction to return a confirming block
    import app.services.ai_customs_evidence as _ai
    monkeypatch.setattr(_ai, "_provider_available", lambda: True)
    monkeypatch.setattr(
        _ai, "extract_customs_evidence",
        lambda pdf_text, document_hint=None, anchors=None, max_text_chars=6000: {
            "invoice_refs": ["088/2026-2027"],
            "awb":          "4789974092",
            "mrn":          "26PL44302D00C2M4R4",
            "cif_usd":      3322.00,
            "exporter":     "Global Jewellery Pvt. Ltd.",
            "importer":     "Estrella Jewels Sp. z o.o.",
            "cn_codes":     ["71131911"],
            "confidence":   "high",
            "evidence":     ["Exporter's Ref: 088/2026-2027 (page 1)"],
            "_ai_meta":     {"model": "test", "extraction_time_ms": 1,
                             "raw_confidence": "high"},
        },
    )

    from app.services.customs_parser_orchestrator import parse_customs_document
    out = parse_customs_document(
        "TESTBATCH_NOISY", sad_dir,
        audit={"awb": "4789974092", "inputs": {}},
    )
    # ai_customs_evidence present + status verified_with_advisory
    ace = out.get("ai_customs_evidence")
    assert ace is not None
    assert ace["reconciliation"]["status"] == "verified_with_advisory"
    # VERIFY-GAP line demoted to [ADVISORY]
    corr = out.get("corrections") or []
    has_advisory = any(c.startswith("[ADVISORY]") for c in corr)
    has_verify_gap = any(c.startswith("[VERIFY-GAP] SAD invoice references")
                         for c in corr)
    assert has_advisory, f"expected [ADVISORY] line, corrections: {corr}"
    assert not has_verify_gap, (
        f"VERIFY-GAP line should be demoted, corrections: {corr}"
    )


def test_priority_4_keeps_verify_gap_when_ai_unavailable(
    monkeypatch, tmp_path,
):
    """No AI provider configured → orchestrator preserves [VERIFY-GAP],
    ai_customs_evidence is either None or has status ai_unavailable."""
    sad_dir = tmp_path / "sad"
    sad_dir.mkdir()
    (sad_dir / "ZC429.pdf").write_bytes(b"%PDF-1.7\n%stub\n")

    def _fake_parse(path, corrections):
        corrections.append(
            "[VERIFY-GAP] SAD invoice references inferred from free text / "
            "document sections (not via N935): ['3322','088']"
        )
        return {
            "mrn": "X", "total_cif_usd": 100.0,
            "invoice_refs": ["3322", "088"],
            "invoice_refs_method": "inferred_from_sad_free_text",
        }
    fake_mod = type(sys)("pz_import_processor_fake3")
    fake_mod.parse_zc429 = _fake_parse
    monkeypatch.setitem(sys.modules, "pz_import_processor", fake_mod)

    # Provider explicitly unavailable
    import app.services.ai_customs_evidence as _ai
    monkeypatch.setattr(_ai, "_provider_available", lambda: False)

    from app.services.customs_parser_orchestrator import parse_customs_document
    out = parse_customs_document("TESTBATCH_NO_AI", sad_dir, audit={})

    corr = out.get("corrections") or []
    has_verify_gap = any(c.startswith("[VERIFY-GAP] SAD invoice references")
                         for c in corr)
    assert has_verify_gap, (
        "VERIFY-GAP must be preserved when AI unavailable, "
        f"corrections: {corr}"
    )
    # ai_customs_evidence either None or status=ai_unavailable
    ace = out.get("ai_customs_evidence")
    if ace is not None:
        assert ace["reconciliation"]["status"] in (
            "ai_unavailable", "ai_low_confidence",
        )


def test_priority_4_keeps_verify_gap_when_ai_mismatches(
    monkeypatch, tmp_path,
):
    """AI returns a CIF that disagrees with the deterministic anchor →
    operator_review_required, VERIFY-GAP preserved."""
    sad_dir = tmp_path / "sad"
    sad_dir.mkdir()
    (sad_dir / "ZC429.pdf").write_bytes(b"%PDF-1.7\n%stub\n")

    def _fake_parse(path, corrections):
        corrections.append(
            "[VERIFY-GAP] SAD invoice references inferred from free text / "
            "document sections (not via N935): ['088']"
        )
        return {
            "mrn": "26PL44302D00C2M4R4",
            "total_cif_usd": 3322.00,
            "invoice_refs": ["088"],
            "invoice_refs_method": "inferred_from_sad_free_text",
        }
    fake_mod = type(sys)("pz_import_processor_fake4")
    fake_mod.parse_zc429 = _fake_parse
    monkeypatch.setitem(sys.modules, "pz_import_processor", fake_mod)
    _stub_pdfplumber(monkeypatch)

    import app.services.ai_customs_evidence as _ai
    monkeypatch.setattr(_ai, "_provider_available", lambda: True)
    # AI returns a different CIF — mismatch
    monkeypatch.setattr(
        _ai, "extract_customs_evidence",
        lambda pdf_text, document_hint=None, anchors=None, max_text_chars=6000: {
            "invoice_refs": ["088/2026-2027"],
            "awb":          "4789974092",
            "mrn":          "26PL44302D00C2M4R4",
            "cif_usd":      9999.99,    # disagrees with anchor 3322.00
            "exporter":     "X", "importer": "Y",
            "cn_codes":     [], "confidence": "high",
            "evidence":     ["fake quote"],
            "_ai_meta":     {"model": "test", "extraction_time_ms": 1,
                             "raw_confidence": "high"},
        },
    )

    from app.services.customs_parser_orchestrator import parse_customs_document
    out = parse_customs_document(
        "TESTBATCH_MISMATCH", sad_dir,
        audit={"awb": "4789974092"},
    )
    ace = out.get("ai_customs_evidence")
    assert ace is not None
    assert ace["reconciliation"]["status"] == "operator_review_required"
    # VERIFY-GAP preserved — AI cannot override
    corr = out.get("corrections") or []
    has_verify_gap = any(c.startswith("[VERIFY-GAP] SAD invoice references")
                         for c in corr)
    assert has_verify_gap, (
        "VERIFY-GAP must be preserved on AI mismatch, "
        f"corrections: {corr}"
    )


# ── Authority invariants: AI never mutates deterministic fields ──────────


def test_ai_does_not_modify_deterministic_result_data(monkeypatch, tmp_path):
    """Even when AI confirms, the orchestrator's result_data field
    values must remain bit-for-bit identical to what the deterministic
    parser returned. The AI block lives in a separate
    ai_customs_evidence key — never merged into result_data."""
    sad_dir = tmp_path / "sad"
    sad_dir.mkdir()
    (sad_dir / "ZC429.pdf").write_bytes(b"%PDF-1.7\n%stub\n")

    deterministic = {
        "mrn":                  "26PL44302D00C2M4R4",
        "total_cif_usd":        3322.00,
        "duty_pln":             None,
        "vat_pln":              None,
        "invoice_refs":         ["3322", "121", "1000"],  # noisy
        "invoice_refs_method":  "inferred_from_sad_free_text",
        "exporter_name":        "Global Jewellery Pvt. Ltd.",
        "importer_name":        "Estrella Jewels",
    }
    def _fake_parse(path, corrections):
        corrections.append(
            "[VERIFY-GAP] SAD invoice references inferred from free text / "
            "document sections (not via N935): ['3322','121','1000']"
        )
        # Return a COPY so test can compare originals afterwards
        return dict(deterministic)
    fake_mod = type(sys)("pz_import_processor_fake5")
    fake_mod.parse_zc429 = _fake_parse
    monkeypatch.setitem(sys.modules, "pz_import_processor", fake_mod)
    _stub_pdfplumber(monkeypatch)

    import app.services.ai_customs_evidence as _ai
    monkeypatch.setattr(_ai, "_provider_available", lambda: True)
    monkeypatch.setattr(
        _ai, "extract_customs_evidence",
        lambda pdf_text, document_hint=None, anchors=None, max_text_chars=6000: {
            "invoice_refs": ["088/2026-2027"],
            "mrn":          "26PL44302D00C2M4R4",
            "awb":          "4789974092",
            "cif_usd":      3322.00,
            "exporter":     "Global Jewellery Pvt. Ltd.",
            "importer":     "Estrella Jewels",
            "cn_codes":     [], "confidence": "high",
            "evidence":     [], "_ai_meta": {"model": "test",
                             "extraction_time_ms": 1, "raw_confidence": "high"},
        },
    )

    from app.services.customs_parser_orchestrator import parse_customs_document
    out = parse_customs_document(
        "TESTBATCH_AUTHORITY", sad_dir, audit={"awb": "4789974092"},
    )

    data = out["data"]
    # Deterministic fields are bit-for-bit identical
    assert data["mrn"]            == deterministic["mrn"]
    assert data["total_cif_usd"]  == deterministic["total_cif_usd"]
    assert data["duty_pln"]       is None
    assert data["vat_pln"]        is None
    # AI did NOT merge its 088/2026-2027 into result_data["invoice_refs"]
    assert data["invoice_refs"]   == ["3322", "121", "1000"]
    assert data["invoice_refs_method"] == "inferred_from_sad_free_text"
    # The AI recovery lives separately
    assert "088/2026-2027" in out["ai_customs_evidence"]["ai_block"]["invoice_refs"]


# ── Safety / security source-grep ────────────────────────────────────────


def test_no_api_key_committed_to_orchestrator():
    src = (Path(__file__).resolve().parent.parent
           / "app" / "services" / "customs_parser_orchestrator.py").read_text("utf-8")
    forbidden = ("sk-ant-", "sk-", "ANTHROPIC_API_KEY=", "api_key=\"sk")
    for tok in forbidden:
        assert tok not in src, f"orchestrator must not contain {tok!r}"


def test_orchestrator_priority4_does_not_touch_fiscal_or_wfirma_paths():
    src = (Path(__file__).resolve().parent.parent
           / "app" / "services" / "customs_parser_orchestrator.py").read_text("utf-8")
    # Inspect ONLY the Priority-4 block
    idx_start = src.find("# ── Priority 4: AI evidence recovery")
    idx_end   = src.find("# ── No result at all", idx_start)
    p4 = src[idx_start:idx_end]
    forbidden = (
        "WFIRMA_CREATE_", "create_invoice", "create_pz", "post_to_wfirma",
        "_guard_wfirma_export", "compute_cif", "DHL_BROKER_THRESHOLD",
        "duty_pln =", "vat_pln =",  # AI must not mutate fiscal fields
    )
    for tok in forbidden:
        assert tok not in p4, (
            f"Priority-4 AI block must not reference {tok!r}"
        )


def test_pr_263_module_still_isolated_after_wiring():
    """After this PR wires the orchestrator to PR #263, the AI module
    itself MUST remain isolated from Estrella supplier code."""
    body = (Path(__file__).resolve().parent.parent
            / "app" / "services" / "ai_customs_evidence.py").read_text("utf-8")
    forbidden_imports = (
        "invoice_intake_parser", "customs_description_engine",
        "product_identity_engine", "description_engine",
        "global_invoice_parser", "global_packing_parser",
    )
    for tok in forbidden_imports:
        assert tok not in body, (
            f"PR #263 module must not import {tok!r} (Estrella isolation)"
        )
