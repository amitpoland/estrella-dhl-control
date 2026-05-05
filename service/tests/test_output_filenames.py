"""
test_output_filenames.py — canonical filename helper + dashboard preference.

Covers:
  - canonical_filename() format
  - filenames_for_audit() — every output type
  - file_version_metadata() block
  - dashboard _build_files_detail prefers canonical files when present
  - dashboard falls back to legacy generic file with stale=True flag
  - audit.json carries canonical_filenames + file_metadata
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.output_filenames import (  # noqa: E402
    canonical_filename, filenames_for_audit, file_version_metadata,
    AUDIT_MEMO, AUDIT_EN_PDF, AUDIT_PL_PDF, PZ_PDF, PZ_CALC_XLSX, POLISH_DESC,
)
from app.api import routes_dashboard as rd  # noqa: E402


# ── Canonical filename helper ─────────────────────────────────────────────────

class TestCanonicalFilename:
    def test_full_format(self):
        assert canonical_filename(
            PZ_PDF, awb="2824221912", mrn="26PL44302D005LJ4R0",
            clearance_date="2026-03-12", extension="pdf",
        ) == "PZ_AWB_2824221912_MRN_26PL44302D005LJ4R0_2026-03-12.pdf"

    def test_audit_memo_format(self):
        assert canonical_filename(
            AUDIT_MEMO, awb="2824221912", mrn="26PL44302D005LJ4R0",
            clearance_date="2026-03-12", extension="pdf",
        ) == "AUDIT_MEMO_AWB_2824221912_MRN_26PL44302D005LJ4R0_2026-03-12.pdf"

    def test_unknown_slot_when_field_missing(self):
        n = canonical_filename(AUDIT_EN_PDF, awb=None, mrn="X", clearance_date="2026-01-01", extension="pdf")
        assert "_AWB_UNKNOWN_" in n

    def test_strips_unsafe_characters(self):
        n = canonical_filename(PZ_PDF, awb="123 / 456", mrn="X<>Y", clearance_date="2026-01-01", extension="pdf")
        assert "/" not in n and "<" not in n and ">" not in n


class TestFilenamesForAudit:
    def test_returns_all_expected_keys(self):
        audit = {
            "tracking_no": "2824221912",
            "customs_declaration": {"mrn": "26PL44302D005LJ4R0", "clearance_date": "2026-03-12"},
        }
        names = filenames_for_audit(audit)
        for k in ("pz_pdf", "calc_xlsx", "audit_memo", "audit_en", "audit_pl",
                  "audit_en_txt", "audit_pl_txt", "polish_desc", "corrections"):
            assert k in names
            assert "AWB_2824221912" in names[k]
            assert "MRN_26PL44302D005LJ4R0" in names[k]
            assert "2026-03-12" in names[k]

    def test_extensions_correct(self):
        names = filenames_for_audit({"tracking_no": "X", "customs_declaration": {"mrn": "M", "clearance_date": "D"}})
        assert names["pz_pdf"].endswith(".pdf")
        assert names["calc_xlsx"].endswith(".xlsx")
        assert names["audit_en_txt"].endswith(".txt")
        assert names["corrections"].endswith(".json")


class TestFileVersionMetadata:
    def test_metadata_has_required_fields(self):
        m = file_version_metadata(
            {"batch_id": "B", "tracking_no": "AWB",
             "customs_declaration": {"mrn": "MRN", "clearance_date": "DATE"}},
            row_schema_version="v2", generator_version="v1.4",
        )
        assert m["batch_id"] == "B"
        assert m["awb"] == "AWB"
        assert m["mrn"] == "MRN"
        assert m["clearance_date"] == "DATE"
        assert m["row_schema_version"] == "v2"
        assert m["generator_version"] == "v1.4"
        assert "T" in m["generated_at"]   # ISO 8601


# ── Dashboard preference ──────────────────────────────────────────────────────

@pytest.fixture
def outputs(tmp_path, monkeypatch):
    out = tmp_path / "outputs"; out.mkdir()
    monkeypatch.setattr(rd, "_OUTPUTS", out)
    return out


def _write_audit(bdir: Path, *, with_canonical: dict, with_metadata: bool = True):
    bdir.mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id":         bdir.name,
        "row_schema_version": "v2",
        "canonical_filenames": with_canonical,
    }
    if with_metadata:
        audit["file_metadata"] = {
            "batch_id": bdir.name, "awb": "X", "mrn": "Y",
            "clearance_date": "Z", "row_schema_version": "v2",
            "generator_version": "v1.4", "generated_at": "2026-05-02T00:00:00Z",
        }
    (bdir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")


class TestDashboardPrefersCanonical:
    def test_prefers_canonical_pdf_over_legacy_generic(self, outputs):
        bdir = outputs / "SHIPMENT_X"
        canon = "AUDIT_MEMO_AWB_111_MRN_AAA_2026-01-01.pdf"
        _write_audit(bdir, with_canonical={"audit_memo": canon, "audit_en": "AUDIT_REPORT_EN_AWB_111_MRN_AAA_2026-01-01.pdf"})
        # Both exist on disk: canonical + legacy generic
        (bdir / canon).write_bytes(b"%PDF-1.4 canonical")
        (bdir / "audit_memo.pdf").write_bytes(b"%PDF-1.4 legacy")

        files = rd._build_files_detail("SHIPMENT_X")["files"]
        assert files["audit_memo"]["exists"] is True
        assert files["audit_memo"]["name"] == canon
        assert files["audit_memo"]["stale"] is False

    def test_falls_back_to_legacy_with_stale_flag(self, outputs):
        bdir = outputs / "SHIPMENT_Y"
        # canonical referenced in audit.json but only legacy file on disk
        canon = "AUDIT_MEMO_AWB_222_MRN_BBB_2026-02-02.pdf"
        _write_audit(bdir, with_canonical={"audit_memo": canon})
        (bdir / "audit_memo.pdf").write_bytes(b"%PDF-1.4 legacy only")

        files = rd._build_files_detail("SHIPMENT_Y")["files"]
        assert files["audit_memo"]["exists"] is True
        assert files["audit_memo"]["name"] == "audit_memo.pdf"
        assert files["audit_memo"]["stale"] is True

    def test_neither_present_returns_disabled(self, outputs):
        bdir = outputs / "SHIPMENT_Z"
        _write_audit(bdir, with_canonical={"audit_memo": "AUDIT_MEMO_AWB_X.pdf"})
        files = rd._build_files_detail("SHIPMENT_Z")["files"]
        assert files["audit_memo"]["exists"] is False
        assert files["audit_memo"]["url"] == ""

    def test_canonical_pz_pdf_resolves_correctly(self, outputs):
        bdir = outputs / "SHIPMENT_PZ"
        canon = "PZ_AWB_333_MRN_CCC_2026-03-03.pdf"
        _write_audit(bdir, with_canonical={"pz_pdf": canon})
        (bdir / canon).write_bytes(b"%PDF-1.4 pz canonical")

        files = rd._build_files_detail("SHIPMENT_PZ")["files"]
        assert files["pz_pdf"]["name"] == canon
        assert files["pz_pdf"]["stale"] is False

    def test_legacy_pz_pdf_marked_stale(self, outputs):
        bdir = outputs / "SHIPMENT_LEGACY_PZ"
        # No canonical on disk — only an old PZ_<batch>.pdf
        _write_audit(bdir, with_canonical={"pz_pdf": "PZ_AWB_444_MRN_DDD_2026-04-04.pdf"})
        (bdir / "PZ_OLD_GENERIC.pdf").write_bytes(b"%PDF-1.4 old")

        files = rd._build_files_detail("SHIPMENT_LEGACY_PZ")["files"]
        assert files["pz_pdf"]["exists"] is True
        assert files["pz_pdf"]["stale"] is True
        assert files["pz_pdf"]["name"] == "PZ_OLD_GENERIC.pdf"
