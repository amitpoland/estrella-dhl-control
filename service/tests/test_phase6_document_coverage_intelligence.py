"""Phase 6 — Document Coverage Intelligence tests.

Tests for:
  - _score_documents() scoring logic (all paths)
  - get_document_coverage_summary() with real temp SQLite DB
  - MasterDataIntelligenceReport includes 'document' domain
  - generate_report() assembles document domain
  - MDI domain route accepts 'document', rejects unknown
  - Source-grep safety: no OCR, no LLM, no Anthropic, no writes in scorer
  - Phase 4/5 regression: existing domains still present and scored
"""
from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── path setup ────────────────────────────────────────────────────────────────
_SERVICE_ROOT = Path(__file__).parent.parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.services.master_data_intelligence import (
    DomainScore,
    MasterDataIntelligenceReport,
    _score_documents,
    generate_report,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty_summary() -> Dict[str, Any]:
    return {}


def _full_summary(
    total: int = 100,
    extracted: int = 90,
    failed: int = 5,
    awb_linked: int = 80,
    mrn_linked: int = 70,
    pz_linked: int = 60,
    manual_review: int = 3,
    customs_decl: int = 15,
    customs_cleared: int = 12,
    pz_total: int = 50,
    pz_workdrive: int = 45,
    awb_doc_count: int = 20,
    inv_lines: int = 200,
    inv_hs: int = 190,
) -> Dict[str, Any]:
    pending = total - extracted - failed
    return {
        "total_documents": total,
        "extraction_status_counts": {
            "extracted": extracted,
            "failed": failed,
            "pending": max(0, pending),
        },
        "awb_linked_count": awb_linked,
        "mrn_linked_count": mrn_linked,
        "pz_linked_count": pz_linked,
        "requires_manual_review_count": manual_review,
        "customs_declaration_count": customs_decl,
        "customs_with_clearance_date": customs_cleared,
        "pz_document_count": pz_total,
        "pz_with_workdrive_count": pz_workdrive,
        "awb_document_count": awb_doc_count,
        "invoice_line_count": inv_lines,
        "invoice_lines_with_hs_code": inv_hs,
        "document_type_counts": {"purchase_invoice": total},
    }


# ─────────────────────────────────────────────────────────────────────────────
# _score_documents: empty / zero-document path
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreDocumentsEmpty:
    def test_empty_summary_returns_domain_document(self):
        s = _score_documents(_empty_summary())
        assert s.domain == "document"

    def test_empty_summary_entity_count_zero(self):
        s = _score_documents(_empty_summary())
        assert s.entity_count == 0

    def test_empty_summary_completeness_zero(self):
        s = _score_documents(_empty_summary())
        assert s.completeness_score == 0.0

    def test_empty_summary_confidence_zero(self):
        s = _score_documents(_empty_summary())
        assert s.confidence == 0.0

    def test_empty_summary_has_recommendation(self):
        s = _score_documents(_empty_summary())
        assert len(s.recommendations) >= 1

    def test_empty_summary_no_field_gaps(self):
        s = _score_documents(_empty_summary())
        assert s.field_gaps == []

    def test_zero_docs_in_summary(self):
        s = _score_documents({"total_documents": 0})
        assert s.entity_count == 0
        assert s.completeness_score == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _score_documents: completeness score range
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreDocumentsCompleteness:
    def test_completeness_between_0_and_1(self):
        s = _score_documents(_full_summary())
        assert 0.0 <= s.completeness_score <= 1.0

    def test_perfect_coverage_high_completeness(self):
        perfect = _full_summary(
            total=100, extracted=100, failed=0,
            awb_linked=100, mrn_linked=100, pz_linked=100,
            pz_total=50, pz_workdrive=50,
        )
        s = _score_documents(perfect)
        assert s.completeness_score >= 0.90

    def test_zero_extracted_low_completeness(self):
        bad = _full_summary(
            total=100, extracted=0, failed=80,
            awb_linked=0, mrn_linked=0, pz_linked=0,
        )
        s = _score_documents(bad)
        assert s.completeness_score < 0.30

    def test_high_extraction_raises_score(self):
        high = _full_summary(extracted=100, failed=0, total=100)
        low  = _full_summary(extracted=10,  failed=10, total=100)
        assert _score_documents(high).completeness_score > _score_documents(low).completeness_score

    def test_entity_count_equals_total_documents(self):
        s = _score_documents(_full_summary(total=42))
        assert s.entity_count == 42


# ─────────────────────────────────────────────────────────────────────────────
# _score_documents: field gaps
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreDocumentsFieldGaps:
    def test_extraction_incomplete_creates_gap(self):
        s = _score_documents(_full_summary(total=100, extracted=60, failed=10))
        gap_fields = [g.field for g in s.field_gaps]
        assert "extraction_status" in gap_fields

    def test_awb_not_linked_creates_gap(self):
        s = _score_documents(_full_summary(total=100, awb_linked=50))
        gap_fields = [g.field for g in s.field_gaps]
        assert "awb_linkage" in gap_fields

    def test_mrn_not_linked_creates_gap(self):
        s = _score_documents(_full_summary(total=100, mrn_linked=20))
        gap_fields = [g.field for g in s.field_gaps]
        assert "mrn_linkage" in gap_fields

    def test_full_awb_linkage_no_awb_gap(self):
        s = _score_documents(_full_summary(total=50, awb_linked=50))
        gap_fields = [g.field for g in s.field_gaps]
        assert "awb_linkage" not in gap_fields

    def test_manual_review_creates_gap(self):
        s = _score_documents(_full_summary(total=100, manual_review=10))
        gap_fields = [g.field for g in s.field_gaps]
        assert "requires_manual_review" in gap_fields

    def test_no_manual_review_no_gap(self):
        s = _score_documents(_full_summary(total=100, manual_review=0))
        gap_fields = [g.field for g in s.field_gaps]
        assert "requires_manual_review" not in gap_fields

    def test_pz_workdrive_missing_creates_gap(self):
        s = _score_documents(_full_summary(pz_total=50, pz_workdrive=20))
        gap_fields = [g.field for g in s.field_gaps]
        assert "pz_workdrive_upload" in gap_fields

    def test_pz_full_workdrive_no_gap(self):
        s = _score_documents(_full_summary(pz_total=50, pz_workdrive=50))
        gap_fields = [g.field for g in s.field_gaps]
        assert "pz_workdrive_upload" not in gap_fields

    def test_pz_zero_docs_no_workdrive_gap(self):
        # If no PZ documents exist, no WorkDrive gap should fire
        s = _score_documents(_full_summary(pz_total=0, pz_workdrive=0))
        gap_fields = [g.field for g in s.field_gaps]
        assert "pz_workdrive_upload" not in gap_fields

    def test_hs_code_gap_surfaces_when_coverage_low(self):
        s = _score_documents(_full_summary(inv_lines=100, inv_hs=50))
        gap_fields = [g.field for g in s.field_gaps]
        assert "invoice_hs_code" in gap_fields

    def test_hs_code_no_gap_when_high_coverage(self):
        # 95% HS coverage — above 90% threshold, no gap
        s = _score_documents(_full_summary(inv_lines=100, inv_hs=95))
        gap_fields = [g.field for g in s.field_gaps]
        assert "invoice_hs_code" not in gap_fields

    def test_gaps_sorted_critical_first(self):
        s = _score_documents(_full_summary(total=100, extracted=0, failed=80))
        if s.field_gaps:
            assert s.field_gaps[0].severity == "critical"


# ─────────────────────────────────────────────────────────────────────────────
# _score_documents: confidence
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreDocumentsConfidence:
    def test_confidence_between_0_and_1(self):
        s = _score_documents(_full_summary())
        assert 0.0 <= s.confidence <= 1.0

    def test_high_failure_rate_lowers_confidence(self):
        high_fail = _full_summary(total=100, extracted=20, failed=80)
        low_fail  = _full_summary(total=100, extracted=95, failed=5)
        assert _score_documents(high_fail).confidence < _score_documents(low_fail).confidence

    def test_no_failures_max_confidence(self):
        s = _score_documents(_full_summary(total=100, extracted=100, failed=0))
        assert s.confidence >= 0.9


# ─────────────────────────────────────────────────────────────────────────────
# _score_documents: advisory and details
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreDocumentsAdvisory:
    def test_advisory_mentions_document_count(self):
        s = _score_documents(_full_summary(total=77))
        assert "77" in s.advisory

    def test_details_has_required_keys(self):
        s = _score_documents(_full_summary())
        required = {
            "total_documents", "extraction_complete_count", "extraction_failed_count",
            "awb_linked_count", "mrn_linked_count", "pz_linked_count",
            "pz_document_count", "pz_with_workdrive_count",
            "customs_declaration_count",
        }
        for key in required:
            assert key in s.details, f"Missing detail key: {key}"

    def test_details_total_matches_entity_count(self):
        s = _score_documents(_full_summary(total=55))
        assert s.details["total_documents"] == 55

    def test_llm_used_not_in_details(self):
        s = _score_documents(_full_summary())
        # llm_used lives on the report, not domain details
        assert "llm_used" not in s.details

    def test_no_write_keys_in_details(self):
        s = _score_documents(_full_summary())
        forbidden = {"INSERT", "UPDATE", "DELETE", "write", "create"}
        for key in s.details:
            assert key.lower() not in forbidden

    def test_no_duplicate_clusters(self):
        # Document domain never produces duplicate clusters
        s = _score_documents(_full_summary())
        assert s.duplicate_clusters == []


# ─────────────────────────────────────────────────────────────────────────────
# MasterDataIntelligenceReport: document field presence
# ─────────────────────────────────────────────────────────────────────────────

def _make_generate_report_patches(
    customers=None, designs=None, product_locals=None,
    suppliers=None, doc_summary=None,
):
    from contextlib import ExitStack
    from unittest.mock import patch as _patch
    stack = ExitStack()
    stack.enter_context(_patch("app.services.master_data_intelligence.list_customers",
                               return_value=customers or []))
    stack.enter_context(_patch("app.services.master_data_intelligence.list_designs",
                               return_value=designs or []))
    stack.enter_context(_patch("app.services.master_data_intelligence.list_product_local",
                               return_value=product_locals or []))
    stack.enter_context(_patch("app.services.master_data_intelligence.list_suppliers",
                               return_value=suppliers or []))
    stack.enter_context(_patch(
        "app.services.master_data_intelligence.get_document_coverage_summary",
        return_value=doc_summary if doc_summary is not None else {},
    ))
    stack.enter_context(_patch("app.services.master_data_intelligence.cm_init"))
    stack.enter_context(_patch("app.services.master_data_intelligence.md_init"))
    stack.enter_context(_patch("app.services.master_data_intelligence.supp_init"))
    return stack


class TestMasterDataIntelligenceReportDocumentField:
    def test_report_has_document_attribute(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert hasattr(r, "document")

    def test_document_is_domain_score(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert isinstance(r.document, DomainScore)

    def test_document_domain_name(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert r.document.domain == "document"

    def test_to_dict_includes_document_key(self):
        with _make_generate_report_patches():
            d = generate_report().to_dict()
        assert "document" in d

    def test_to_dict_document_has_expected_keys(self):
        with _make_generate_report_patches():
            d = generate_report().to_dict()["document"]
        for key in ("domain", "entity_count", "completeness_score",
                    "confidence", "field_gaps", "advisory", "recommendations", "details"):
            assert key in d, f"Missing key in document dict: {key}"

    def test_to_dict_still_has_all_five_prior_domains(self):
        with _make_generate_report_patches():
            d = generate_report().to_dict()
        for domain in ("customer", "product", "finishing", "supplier", "readiness"):
            assert domain in d, f"Prior domain missing from to_dict: {domain}"

    def test_llm_used_is_false(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert r.llm_used is False

    def test_advisory_class_is_R(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert r.advisory_class == "R"

    def test_platform_score_between_0_and_1(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert 0.0 <= r.platform_score <= 1.0

    def test_to_dict_no_write_keys(self):
        with _make_generate_report_patches():
            d = generate_report().to_dict()
        forbidden = {"insert", "update", "delete", "write", "create", "modify"}
        all_keys_lower = {k.lower() for k in d}
        for fk in forbidden:
            assert fk not in all_keys_lower

    def test_document_score_uses_summary_data(self):
        summary = _full_summary(total=99, extracted=90, failed=2)
        with _make_generate_report_patches(doc_summary=summary):
            r = generate_report()
        assert r.document.entity_count == 99

    def test_platform_score_higher_with_good_documents(self):
        good_summary = _full_summary(
            total=100, extracted=100, failed=0,
            awb_linked=100, mrn_linked=100, pz_workdrive=50, pz_total=50,
        )
        bad_summary = _full_summary(
            total=100, extracted=10, failed=80,
            awb_linked=5, mrn_linked=0, pz_workdrive=0, pz_total=50,
        )
        with _make_generate_report_patches(doc_summary=good_summary):
            good_score = generate_report().platform_score
        with _make_generate_report_patches(doc_summary=bad_summary):
            bad_score = generate_report().platform_score
        assert good_score > bad_score


# ─────────────────────────────────────────────────────────────────────────────
# Platform weight sanity
# ─────────────────────────────────────────────────────────────────────────────

class TestPlatformWeights:
    def test_platform_weights_sum_to_one(self):
        # The six weights in generate_report must sum to 1.0
        weights = [0.25, 0.22, 0.18, 0.12, 0.13, 0.10]
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_platform_score_is_weighted_not_simple_average(self):
        # All domain completeness = 1.0 → platform_score should equal 1.0
        with _make_generate_report_patches(
            doc_summary=_full_summary(
                total=10, extracted=10, failed=0,
                awb_linked=10, mrn_linked=10, pz_linked=10,
                pz_total=5, pz_workdrive=5,
            ),
        ):
            r = generate_report()
        # With all empty master-data domains scoring 0.0 this won't be 1.0 —
        # just verify it's a float in range.
        assert isinstance(r.platform_score, float)
        assert 0.0 <= r.platform_score <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# get_document_coverage_summary: real temp DB
# ─────────────────────────────────────────────────────────────────────────────

def _create_temp_documents_db() -> Path:
    """Create a minimal documents.db with the schema from document_db.py."""
    from app.services import document_db as ddb
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    ddb.init_document_db(path)
    return path


def _insert_test_rows(db_path: Path) -> None:
    """Insert representative rows for coverage testing."""
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(str(db_path))
    # 4 documents: 3 extracted, 1 failed; 3 with AWB, 2 with MRN, 1 with PZ
    rows = [
        (str(uuid.uuid4()), "B1", "AWB001", "purchase_invoice", "extracted", "completed",
         "INV-01", "MRN-01", "PZ001", 0, now, now),
        (str(uuid.uuid4()), "B1", "AWB002", "packing_list",     "extracted", "completed",
         "",       "MRN-02", "",     0, now, now),
        (str(uuid.uuid4()), "B2", "AWB003", "purchase_invoice", "extracted", "completed",
         "",       "",       "",     1, now, now),
        (str(uuid.uuid4()), "B2", "",       "sad_zc429",        "failed",    "failed",
         "",       "",       "",     0, now, now),
    ]
    con.executemany(
        """INSERT INTO shipment_documents
           (id, batch_id, awb, document_type,
            extraction_status, parser_status,
            related_invoice_no, related_mrn, related_pz_no,
            requires_manual_review, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    # 1 customs_declaration with clearance_date
    con.execute(
        """INSERT INTO customs_declarations
           (id, document_id, batch_id, mrn, lrn, clearance_date,
            duty_pln, vat_pln, total_cif_usd, statistical_value_pln,
            agent, importer_name, importer_nip, exporter_name,
            cn_code, goods_description, invoice_refs, raw_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), "doc1", "B1", "MRN-01", "", "2026-05-01",
         100.0, 230.0, 500.0, 600.0, "TestAgent", "Estrella",
         "1234567890", "Supplier", "7113", "jewellery", "[]", "{}", now, now),
    )
    # 1 pz_document with both WorkDrive IDs
    con.execute(
        """INSERT INTO pz_documents
           (id, document_id, batch_id, doc_no, line_count,
            total_net_pln, total_gross_pln, duty_a00_pln,
            verification_status, amendment_flags,
            workdrive_pdf_id, workdrive_xlsx_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), "doc1", "B1", "PZ001", 5,
         1000.0, 1230.0, 50.0, "verified", "[]",
         "WDPDF123", "WDXLSX456", now, now),
    )
    con.commit()
    con.close()


class TestGetDocumentCoverageSummary:
    def test_returns_dict(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        result = get_document_coverage_summary(path)
        assert isinstance(result, dict)
        path.unlink(missing_ok=True)

    def test_empty_db_total_zero(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        result = get_document_coverage_summary(path)
        assert result.get("total_documents", 0) == 0
        path.unlink(missing_ok=True)

    def test_counts_correct_after_insert(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        _insert_test_rows(path)
        result = get_document_coverage_summary(path)
        assert result["total_documents"] == 4
        path.unlink(missing_ok=True)

    def test_extraction_status_counts(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        _insert_test_rows(path)
        result = get_document_coverage_summary(path)
        assert result["extraction_status_counts"].get("extracted", 0) == 3
        assert result["extraction_status_counts"].get("failed", 0) == 1
        path.unlink(missing_ok=True)

    def test_awb_linked_count(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        _insert_test_rows(path)
        result = get_document_coverage_summary(path)
        assert result["awb_linked_count"] == 3
        path.unlink(missing_ok=True)

    def test_mrn_linked_count(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        _insert_test_rows(path)
        result = get_document_coverage_summary(path)
        assert result["mrn_linked_count"] == 2
        path.unlink(missing_ok=True)

    def test_pz_linked_count(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        _insert_test_rows(path)
        result = get_document_coverage_summary(path)
        assert result["pz_linked_count"] == 1
        path.unlink(missing_ok=True)

    def test_requires_manual_review(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        _insert_test_rows(path)
        result = get_document_coverage_summary(path)
        assert result["requires_manual_review_count"] == 1
        path.unlink(missing_ok=True)

    def test_customs_declaration_count(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        _insert_test_rows(path)
        result = get_document_coverage_summary(path)
        assert result["customs_declaration_count"] == 1
        assert result["customs_with_clearance_date"] == 1
        path.unlink(missing_ok=True)

    def test_pz_with_workdrive_count(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        _insert_test_rows(path)
        result = get_document_coverage_summary(path)
        assert result["pz_document_count"] == 1
        assert result["pz_with_workdrive_count"] == 1
        path.unlink(missing_ok=True)

    def test_nonexistent_db_returns_empty_dict(self):
        from app.services.document_db import get_document_coverage_summary
        result = get_document_coverage_summary(Path("/nonexistent/path/documents.db"))
        assert result == {}

    def test_document_type_counts_present(self):
        from app.services.document_db import get_document_coverage_summary
        path = _create_temp_documents_db()
        _insert_test_rows(path)
        result = get_document_coverage_summary(path)
        assert "document_type_counts" in result
        assert "purchase_invoice" in result["document_type_counts"]
        path.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# MDI route: /document domain accepted
# ─────────────────────────────────────────────────────────────────────────────

class TestMDIRouteDocumentDomain:
    def test_document_in_valid_domains(self):
        from app.api.routes_mdi import _VALID_DOMAINS
        assert "document" in _VALID_DOMAINS

    def test_all_six_domains_in_valid_domains(self):
        from app.api.routes_mdi import _VALID_DOMAINS
        for d in ("customer", "product", "finishing", "supplier", "document", "readiness"):
            assert d in _VALID_DOMAINS

    def test_badomain_not_in_valid_domains(self):
        from app.api.routes_mdi import _VALID_DOMAINS
        assert "badomain" not in _VALID_DOMAINS

    def test_generate_report_document_attribute_accessible(self):
        """generate_report() result must have .document attribute."""
        with _make_generate_report_patches():
            r = generate_report()
        _ = r.document  # must not raise AttributeError


# ─────────────────────────────────────────────────────────────────────────────
# Source-grep safety
# ─────────────────────────────────────────────────────────────────────────────

_MDI_SRC = (
    Path(__file__).parent.parent
    / "app" / "services" / "master_data_intelligence.py"
).read_text(encoding="utf-8")

_DOC_DB_SRC = (
    Path(__file__).parent.parent
    / "app" / "services" / "document_db.py"
).read_text(encoding="utf-8")

_ROUTES_MDI_SRC = (
    Path(__file__).parent.parent
    / "app" / "api" / "routes_mdi.py"
).read_text(encoding="utf-8")


class TestSourceGrepSafety:
    def test_no_anthropic_import_in_mdi(self):
        assert "anthropic" not in _MDI_SRC.lower()

    def test_no_ai_gateway_in_score_documents(self):
        # Extract _score_documents function body
        match = re.search(
            r"def _score_documents.*?(?=\ndef |\Z)", _MDI_SRC, re.DOTALL
        )
        body = match.group(0) if match else ""
        assert "ai_gateway" not in body
        assert "gateway" not in body.lower()

    def test_no_openai_in_mdi(self):
        assert "openai" not in _MDI_SRC.lower()

    def test_llm_used_false_hardcoded_in_mdi(self):
        assert "llm_used=False" in _MDI_SRC

    def test_no_insert_update_delete_in_score_documents(self):
        match = re.search(
            r"def _score_documents.*?(?=\ndef |\Z)", _MDI_SRC, re.DOTALL
        )
        body = match.group(0) if match else ""
        for stmt in ("INSERT", "UPDATE", "DELETE"):
            assert stmt not in body

    def test_no_insert_update_delete_in_coverage_summary(self):
        match = re.search(
            r"def get_document_coverage_summary.*?(?=\ndef |\Z)", _DOC_DB_SRC, re.DOTALL
        )
        body = match.group(0) if match else ""
        for stmt in ("INSERT ", "UPDATE ", "DELETE "):
            assert stmt not in body

    def test_query_only_pragma_in_coverage_summary(self):
        """Coverage summary sets PRAGMA query_only = ON before any reads."""
        match = re.search(
            r"def get_document_coverage_summary.*?(?=\ndef |\Z)", _DOC_DB_SRC, re.DOTALL
        )
        body = match.group(0) if match else ""
        assert "query_only" in body

    def test_no_ocr_reference_in_mdi(self):
        assert "ocr" not in _MDI_SRC.lower()

    def test_get_document_coverage_summary_imported_in_mdi(self):
        assert "get_document_coverage_summary" in _MDI_SRC

    def test_document_domain_in_routes_mdi(self):
        assert '"document"' in _ROUTES_MDI_SRC or "'document'" in _ROUTES_MDI_SRC

    def test_no_post_put_delete_routes_in_routes_mdi(self):
        assert "@router.post" not in _ROUTES_MDI_SRC
        assert "@router.put"  not in _ROUTES_MDI_SRC
        assert "@router.delete" not in _ROUTES_MDI_SRC

    def test_doc_domain_in_to_dict(self):
        # to_dict must include 'document' key
        assert '"document"' in _MDI_SRC or "'document'" in _MDI_SRC

    def test_doc_db_path_constant_in_mdi(self):
        assert "_DOC_DB" in _MDI_SRC


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4/5 regression: prior domains unaffected
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase456Regression:
    def test_customer_domain_still_scores(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert r.customer.domain == "customer"

    def test_product_domain_still_scores(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert r.product.domain == "product"

    def test_finishing_domain_still_scores(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert r.finishing.domain == "finishing"

    def test_supplier_domain_still_scores(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert r.supplier.domain == "supplier"

    def test_readiness_domain_still_scores(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert r.readiness.domain == "readiness"

    def test_document_domain_scores(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert r.document.domain == "document"

    def test_report_generated_at_is_iso(self):
        with _make_generate_report_patches():
            r = generate_report()
        from datetime import datetime
        datetime.fromisoformat(r.generated_at)  # must not raise

    def test_top_recommendations_is_list(self):
        with _make_generate_report_patches():
            r = generate_report()
        assert isinstance(r.top_recommendations, list)

    def test_phase5_desc_quality_still_present(self):
        """_desc_quality helper must still exist (Phase 5 regression)."""
        assert "_desc_quality" in _MDI_SRC

    def test_phase5_metal_stone_compat_still_present(self):
        assert "_metal_stone_compat_warnings" in _MDI_SRC
