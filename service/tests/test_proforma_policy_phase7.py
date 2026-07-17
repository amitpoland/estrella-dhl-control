"""test_proforma_policy_phase7.py — Phase 7 policy + snapshot integrity.

Coverage:
  - Language policy: name_sk never surfaced from proforma_intelligence module
  - Language policy: infer_missing_fields never returns field='name_sk'
  - Language policy: detect_line_anomalies never produces anomaly_type with 'sk'
  - Language policy: company_profile_completeness never references 'name_sk'
  - Snapshot integrity: proforma_intelligence.py source-grep checks
      * module docstring contains "PL + EN only"
      * no direct reference to "name_sk" in return paths
      * all public functions present
  - UI surface source-grep: btn-draft-visibility testid in shipment-detail.html
  - UI surface source-grep: btn-draft-intelligence testid in shipment-detail.html
  - UI surface source-grep: draft-visibility-panel testid present
  - UI surface source-grep: draft-intelligence-panel testid present
  - Backend source-grep: /visibility endpoint registered in routes_proforma.py
  - Backend source-grep: /intelligence endpoint registered in routes_proforma.py
  - Backend source-grep: _build_shipment_panel defined
  - Backend source-grep: _build_draft_readiness_panel defined
  - Backend source-grep: _build_document_status defined
  - Backend source-grep: _build_product_lines_panel defined
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# ── File paths ─────────────────────────────────────────────────────────────────

_INTEL  = Path(__file__).parent.parent / "app" / "services" / "proforma_intelligence.py"
_ROUTES = Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"
_HTML   = Path(__file__).parent.parent / "app" / "static" / "shipment-detail.html"

_intel_src  = _INTEL.read_text(encoding="utf-8")
_routes_src = _ROUTES.read_text(encoding="utf-8")
_html_src   = _HTML.read_text(encoding="utf-8")


# ── Language policy: module-level ─────────────────────────────────────────────

def test_language_policy_documented_in_module_docstring():
    """proforma_intelligence.py must declare PL + EN only in its docstring."""
    assert "PL + EN only" in _intel_src, (
        "Module docstring must contain 'PL + EN only' language policy declaration"
    )


def test_language_policy_name_sk_not_in_return_values():
    """name_sk must not appear in any returned field name or suggestion field."""
    # Acceptable to reference it in a 'never' / 'no name_sk' comment
    # but it MUST NOT appear in a dict key being returned.
    # Strategy: find all occurrences and check none are in a return dict key.
    matches = re.findall(r'"name_sk"', _intel_src)
    # Only acceptable: the language policy comment line
    for m in matches:
        # If it appears in a field= or as a returned dict key → fail
        # We check the full source for any FieldSuggestion(field="name_sk")
        pass
    assert 'field="name_sk"' not in _intel_src
    assert "field='name_sk'" not in _intel_src


def test_language_policy_infer_missing_fields_no_name_sk():
    """Runtime: infer_missing_fields must never produce a name_sk suggestion."""
    from app.services.proforma_intelligence import infer_missing_fields
    import app.services.document_db as _ddb_mod

    orig = _ddb_mod._db_path
    _ddb_mod._db_path = None
    try:
        lines = [{"product_code": "P001", "unit_price": 10}]
        result = infer_missing_fields(lines, master_db_path=None)
    finally:
        _ddb_mod._db_path = orig

    sk = [s for s in result if s.field == "name_sk"]
    assert sk == [], "infer_missing_fields must never produce name_sk suggestions"


def test_language_policy_detect_anomalies_no_sk_type():
    """detect_line_anomalies must not produce any anomaly_type containing 'sk'."""
    from app.services.proforma_intelligence import detect_line_anomalies
    lines = [{"product_code": "P001", "unit_price": 100}]
    result = detect_line_anomalies(lines)
    sk_anomalies = [a for a in result if "sk" in a.anomaly_type.lower()]
    assert sk_anomalies == []


def test_language_policy_company_completeness_no_name_sk():
    """company_profile_completeness must not surface 'name_sk' in any field."""
    from app.services.proforma_intelligence import company_profile_completeness
    result = company_profile_completeness(None)
    for key in result.get("fields", {}):
        assert "sk" not in key.lower(), f"Unexpected field with 'sk' in completeness: {key}"


# ── Module snapshot integrity ─────────────────────────────────────────────────

def test_module_has_detect_line_anomalies():
    assert "def detect_line_anomalies" in _intel_src


def test_module_has_infer_missing_fields():
    assert "def infer_missing_fields" in _intel_src


def test_module_has_build_corpus_stats():
    assert "def build_corpus_stats" in _intel_src


def test_module_has_score_draft_confidence():
    assert "def score_draft_confidence" in _intel_src


def test_module_has_company_profile_completeness():
    assert "def company_profile_completeness" in _intel_src


def test_module_has_line_anomaly_dataclass():
    assert "class LineAnomaly" in _intel_src


def test_module_has_field_suggestion_dataclass():
    assert "class FieldSuggestion" in _intel_src


def test_module_has_corpus_stats_dataclass():
    assert "class CorpusStats" in _intel_src


def test_module_has_draft_confidence_dataclass():
    assert "class DraftConfidence" in _intel_src


def test_module_read_only_no_wfirma_writes():
    """Module must not import or call wfirma_client (write-free zone)."""
    assert "wfirma_client" not in _intel_src


def test_module_read_only_no_audit_mutations():
    """Module must not write to audit.json."""
    assert "write_json_atomic" not in _intel_src
    # Must not open audit.json for writing — check for write mode open calls
    assert 'open(' not in _intel_src or all(
        '"w"' not in line and "'w'" not in line
        for line in _intel_src.splitlines()
        if "open(" in line
    )


# ── Backend routes source-grep ────────────────────────────────────────────────

def test_routes_has_visibility_endpoint():
    assert '"/draft/{draft_id}/visibility"' in _routes_src or \
           "draft/{draft_id}/visibility" in _routes_src


def test_routes_has_intelligence_endpoint():
    assert '"/draft/{draft_id}/intelligence"' in _routes_src or \
           "draft/{draft_id}/intelligence" in _routes_src


def test_routes_has_build_shipment_panel():
    assert "def _build_shipment_panel" in _routes_src


def test_routes_has_build_draft_readiness_panel():
    assert "def _build_draft_readiness_panel" in _routes_src


def test_routes_has_build_document_status():
    assert "def _build_document_status" in _routes_src


def test_routes_has_build_product_lines_panel():
    assert "def _build_product_lines_panel" in _routes_src


def test_routes_visibility_imports_intelligence():
    assert "proforma_intelligence" in _routes_src


def test_routes_shipment_panel_reads_audit_json():
    # _build_shipment_panel must read audit.json
    assert "audit.json" in _routes_src


def test_routes_shipment_panel_reads_carrier_shipments():
    # 2026-07-16 independent-review Condition 2: the shipment panel must
    # resolve through the per-client authority (get_shipment_for_draft),
    # NEVER the batch-scoped latest row (get_shipment_by_batch_id leaked the
    # most-recent client's service_product/dimensions to sibling drafts).
    assert "carrier_shipments" in _routes_src
    assert "get_shipment_for_draft" in _routes_src
    assert "get_shipment_by_batch_id as _get_carrier_shipment" not in _routes_src


# ── UI surface source-grep ────────────────────────────────────────────────────

def test_html_has_btn_draft_visibility():
    assert 'btn-draft-visibility' in _html_src


def test_html_has_btn_draft_intelligence():
    assert 'btn-draft-intelligence' in _html_src


def test_html_has_visibility_panel_testid():
    assert 'draft-visibility-panel' in _html_src


def test_html_has_intelligence_panel_testid():
    assert 'draft-intelligence-panel' in _html_src


def test_html_has_draft_shipment_panel_testid():
    assert 'draft-shipment-panel' in _html_src


def test_html_has_draft_commercial_state_testid():
    assert 'draft-commercial-state' in _html_src


def test_html_visibility_calls_visibility_endpoint():
    assert '/visibility' in _html_src


def test_html_intelligence_calls_intelligence_endpoint():
    assert '/intelligence' in _html_src


def test_html_anomaly_row_testid():
    assert 'draft-anomaly-row' in _html_src


def test_html_suggestion_row_testid():
    assert 'draft-suggestion-row' in _html_src


# ── Read-only contract ────────────────────────────────────────────────────────

def test_visibility_endpoint_is_get_only():
    """GET /visibility must only appear as @router.get."""
    vis_routes = re.findall(
        r'@router\.(get|post|put|patch|delete)\s*\(\s*["\'][^"\']*visibility',
        _routes_src,
    )
    assert vis_routes, "visibility endpoint must be registered"
    for method in vis_routes:
        assert method == "get", f"visibility endpoint must be GET-only, found: {method}"


def test_intelligence_endpoint_is_get_only():
    """GET /intelligence must only appear as @router.get."""
    intel_routes = re.findall(
        r'@router\.(get|post|put|patch|delete)\s*\(\s*["\'][^"\']*intelligence',
        _routes_src,
    )
    assert intel_routes, "intelligence endpoint must be registered"
    for method in intel_routes:
        assert method == "get", f"intelligence endpoint must be GET-only, found: {method}"
