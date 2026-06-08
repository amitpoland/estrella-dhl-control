"""test_packing_parser_diagnostics.py — P1 parser observability.

Asserts the 4-tuple return contract of extract_packing, the
parser_diagnostic dict schema, and the artifact writer non-fatal
guarantees. NO parser logic change is tested here — that's P2.
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.services.invoice_packing_extractor import (
    extract_packing,
    _new_diagnostic,
    _PARSER_NAME,
    _PARSER_VERSION,
)


# ── Fixture helpers ──────────────────────────────────────────────────────

def _write(tmp_path: Path, name: str, content: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def _real_xlsx(tmp_path: Path, name: str, rows: list[list]) -> Path:
    """Build a real xlsx via openpyxl so the parser actually opens it."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for row in rows:
        ws.append(row)
    p = tmp_path / name
    wb.save(str(p))
    return p


# ── Schema + return-shape contract ───────────────────────────────────────

def test_extract_packing_returns_four_tuple(tmp_path):
    p = _real_xlsx(tmp_path, "empty.xlsx", [["only_one_col"]])
    result = extract_packing(p)
    assert isinstance(result, tuple)
    assert len(result) == 4
    rows, parser_name, parser_version, diag = result
    assert parser_name == _PARSER_NAME
    assert parser_version == _PARSER_VERSION
    assert isinstance(diag, dict)


def test_new_diagnostic_skeleton_has_all_keys():
    diag = _new_diagnostic(".xlsx")
    for k in (
        "parser_name", "parser_version", "file_type",
        "workbook_sheet_names", "sheet_count", "sheets_scanned",
        "candidate_header_rows", "chosen_header", "mapped_columns",
        "unmatched_columns", "alias_hits", "row_count",
        "failure_reason", "exception_class", "exception_message",
    ):
        assert k in diag, f"missing schema key {k}"


# ── Failure-reason taxonomy ──────────────────────────────────────────────

def test_corrupt_xlsx_yields_file_corrupt_or_parser_exception(tmp_path):
    """Bytes that look like a zip header but aren't a valid xlsx."""
    p = _write(tmp_path, "corrupt.xlsx", b"PK\x03\x04smoke-xlsx-data")
    rows, _, _, diag = extract_packing(p)
    assert rows == []
    # Either classification is acceptable here; both signal "file is broken".
    assert diag["failure_reason"] in ("parser_exception", "file_corrupt")
    assert diag["row_count"] == 0


def test_unsupported_extension_raises_value_error(tmp_path):
    p = _write(tmp_path, "x.docx", b"not-a-packing-list")
    with pytest.raises(ValueError):
        extract_packing(p)


def test_unknown_headers_yields_header_not_detected(tmp_path):
    """A valid xlsx where no header row matches the canonical aliases."""
    rows_in = [
        ["This is a totally non-standard header", "From a foreign vendor"],
        ["WeirdCol1", "WeirdCol2", "WeirdCol3"],
        ["data-a", "data-b", "data-c"],
    ]
    p = _real_xlsx(tmp_path, "unknown.xlsx", rows_in)
    rows, _, _, diag = extract_packing(p)
    assert rows == []
    assert diag["failure_reason"] == "header_not_detected"
    assert diag["chosen_header"] is None
    # Workbook readable → sheet name captured
    assert diag["workbook_sheet_names"] == ["Sheet1"]
    # Unmatched columns surfaced for the best-effort row (whichever scored
    # most alias hits — may be empty if no row had any alias hit).
    assert isinstance(diag["unmatched_columns"], list)


def test_valid_packing_xlsx_yields_chosen_header(tmp_path):
    """xlsx with EJL-style headers must parse rows AND populate
    chosen_header in the diagnostic."""
    rows_in = [
        ["Invoice #", "EJL/TEST/001"],
        [],
        ["PkSr", "Ctg", "DesignNo", "Kt/Color", "Quality",
         "Dia Wt", "Col Wt", "Qty", "Value", "Total Value", "Size"],
        [1, "PND", "PND-001", "14KT/W", "G-VS",
         0.50, 0.10, 5, 100.0, 500.0, "7"],
    ]
    p = _real_xlsx(tmp_path, "valid_ejl.xlsx", rows_in)
    rows, _, _, diag = extract_packing(p)
    assert diag["chosen_header"] is not None
    assert diag["chosen_header"]["row_index"] == 2
    assert diag["failure_reason"] is None
    assert diag["row_count"] >= 1
    assert len(diag["mapped_columns"]) > 0
    canonical_fields = {m["canonical_field"] for m in diag["mapped_columns"]}
    assert "quantity" in canonical_fields
    assert "design_no" in canonical_fields


# ── Artifact writer ──────────────────────────────────────────────────────

def test_artifact_writer_creates_file(tmp_path):
    from app.services.parser_diagnostic_writer import write_packing_diagnostic_artifact

    diag = _new_diagnostic(".xlsx")
    diag["failure_reason"] = "header_not_detected"
    diag["workbook_sheet_names"] = ["Sheet1"]
    # Source file the writer will sniff:
    src = _real_xlsx(tmp_path, "src.xlsx", [["foo", "bar"]])

    out = write_packing_diagnostic_artifact(
        storage_root=tmp_path,
        batch_id="B-DIAG-1",
        document_id="doc-1",
        filename="src.xlsx",
        document_type="purchase_packing_list",
        source_path=src,
        parser_diagnostic=diag,
    )
    assert out is not None
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    for k in (
        "schema_version", "batch_id", "document_id", "filename",
        "document_type", "upload_timestamp", "workbook_sheet_names",
        "raw_header_rows", "first_20_rows_preview", "parser_diagnostic",
    ):
        assert k in payload, f"artifact missing key {k}"
    assert payload["batch_id"] == "B-DIAG-1"
    assert payload["parser_diagnostic"]["failure_reason"] == "header_not_detected"


def test_artifact_writer_unwritable_dir_returns_none(tmp_path, monkeypatch):
    """Forcing an OSError in the writer must NOT raise — returns None."""
    from app.services import parser_diagnostic_writer as pdw

    def _boom(*a, **kw):
        raise OSError("simulated disk failure")
    monkeypatch.setattr(pdw.Path, "mkdir", _boom)

    diag = _new_diagnostic(".xlsx")
    src = _real_xlsx(tmp_path, "src.xlsx", [["foo"]])
    out = pdw.write_packing_diagnostic_artifact(
        storage_root=tmp_path,
        batch_id="B-FAIL",
        document_id="doc-1",
        filename="src.xlsx",
        document_type="purchase_packing_list",
        source_path=src,
        parser_diagnostic=diag,
    )
    assert out is None


# ── DB: ALTER idempotence + parser_diagnostic_json roundtrip ─────────────

def test_packing_db_alter_is_idempotent_on_legacy_schema(tmp_path):
    """Create a packing.db with the OLD schema (no parser_diagnostic_json),
    then re-init via init_packing_db: ALTER adds the column without error."""
    db = tmp_path / "packing.db"
    with sqlite3.connect(str(db)) as conn:
        conn.executescript("""
            CREATE TABLE packing_documents (
                id                  TEXT PRIMARY KEY,
                batch_id            TEXT NOT NULL,
                invoice_no          TEXT NOT NULL DEFAULT '',
                source_file_path    TEXT NOT NULL DEFAULT '',
                source_file_hash    TEXT NOT NULL DEFAULT '',
                parser_name         TEXT NOT NULL DEFAULT '',
                parser_version      TEXT NOT NULL DEFAULT '',
                extraction_status   TEXT NOT NULL DEFAULT 'pending',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );
            CREATE TABLE packing_lines (
                id                      TEXT PRIMARY KEY,
                packing_document_id     TEXT NOT NULL,
                batch_id                TEXT NOT NULL,
                product_code            TEXT DEFAULT NULL,
                design_no               TEXT NOT NULL DEFAULT '',
                created_at              TEXT NOT NULL,
                updated_at              TEXT NOT NULL,
                FOREIGN KEY (packing_document_id) REFERENCES packing_documents(id)
            );
        """)

    from app.services import packing_db as pdb
    pdb.init_packing_db(db)

    with sqlite3.connect(str(db)) as conn:
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info(packing_documents)"
        ).fetchall()}
    assert "parser_diagnostic_json" in cols


def test_upsert_packing_document_persists_parser_diagnostic(tmp_path):
    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp_path / "packing.db")

    diag = _new_diagnostic(".xlsx")
    diag["failure_reason"] = "header_not_detected"
    diag["workbook_sheet_names"] = ["Sheet1", "Summary"]

    doc_id = pdb.upsert_packing_document(
        batch_id="B-1", invoice_no="INV-1",
        source_file_path="/tmp/p.xlsx", source_file_hash="h-1",
        parser_name=_PARSER_NAME, parser_version=_PARSER_VERSION,
        extraction_status="empty",
        parser_diagnostic=diag,
    )
    assert doc_id

    docs = pdb.get_packing_documents_for_batch("B-1")
    assert len(docs) == 1
    raw = docs[0].get("parser_diagnostic_json")
    assert raw  # serialised
    decoded = json.loads(raw)
    assert decoded["failure_reason"] == "header_not_detected"
    assert decoded["workbook_sheet_names"] == ["Sheet1", "Summary"]


def test_upsert_without_diagnostic_preserves_existing_on_update(tmp_path):
    """Passing parser_diagnostic=None on UPDATE keeps the prior value."""
    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp_path / "packing.db")

    diag = _new_diagnostic(".xlsx")
    diag["failure_reason"] = "header_not_detected"
    doc_id = pdb.upsert_packing_document(
        batch_id="B-2", source_file_hash="h-2",
        parser_diagnostic=diag,
    )
    # Update with no diagnostic — prior value should remain.
    pdb.upsert_packing_document(
        batch_id="B-2", invoice_no="INV-2",
        source_file_hash="h-2",
        parser_diagnostic=None,
        document_id=doc_id,
    )
    docs = pdb.get_packing_documents_for_batch("B-2")
    decoded = json.loads(docs[0]["parser_diagnostic_json"])
    assert decoded["failure_reason"] == "header_not_detected"


# ── API exposure ─────────────────────────────────────────────────────────

def test_get_batch_packing_decodes_parser_diagnostic(tmp_path, monkeypatch):
    """GET /api/v1/packing/{batch} returns parser_diagnostic on each
    packing_documents row."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "t"}

    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp_path / "packing.db")
    diag = _new_diagnostic(".xlsx")
    diag["failure_reason"] = "header_not_detected"
    diag["workbook_sheet_names"] = ["Vendor Sheet"]
    pdb.upsert_packing_document(
        batch_id="B-API-1", source_file_hash="h-api-1",
        parser_diagnostic=diag,
    )

    # Make the batch folder so _validate_batch passes:
    (tmp_path / "outputs" / "B-API-1").mkdir(parents=True, exist_ok=True)

    from fastapi.testclient import TestClient
    cli = TestClient(app)
    r = cli.get("/api/v1/packing/B-API-1")
    assert r.status_code == 200, r.text
    docs = r.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["parser_diagnostic"]["failure_reason"] == "header_not_detected"
    assert docs[0]["parser_diagnostic"]["workbook_sheet_names"] == ["Vendor Sheet"]
    app.dependency_overrides.clear()


# ── Source-grep guard ────────────────────────────────────────────────────

def test_diagnostic_block_has_no_external_system_triggers():
    """The new diagnostic / artifact / endpoint blocks must not reference
    DHL / wFirma / proforma / PZ / SAD / email write surfaces."""
    files = [
        Path(__file__).resolve().parents[1] / "app" / "services" / "parser_diagnostic_writer.py",
        Path(__file__).resolve().parents[1] / "app" / "services" / "invoice_packing_extractor.py",
    ]
    for f in files:
        src = f.read_text(encoding="utf-8")
        for forbidden in (
            "send_email", "queue_email", "smtp",
            "create_pz", "generate_pz",
            "wfirma_client", "wfirma_api",
            "proforma_create", "proforma_issue", "proforma_post",
            "trigger_clearance", "dhl_dispatch", "dhl_express",
        ):
            assert forbidden not in src, \
                f"{f.name} must not reference {forbidden!r}"


def test_dashboard_renders_diagnostic_block():
    src = (Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    assert "packing-list-diagnostic-" in src
    assert "packing-list-diagnostic-toggle-" in src
    assert "Header detected:" in src
    assert "Raw columns seen" in src
    assert "Matched aliases" in src
    assert "expandedDiagDocId" in src


# ── Column mapping audit — backend contract ──────────────────────────────

def test_column_mapping_audit_present_for_ejl_xlsx(tmp_path):
    """extract_packing on an EJL-style xlsx with recognisable headers must
    include column_mapping_audit in the diagnostic dict."""
    rows_in = [
        ["Invoice #", "EJL/TEST/001"],
        [],
        ["PkSr", "Ctg", "DesignNo", "Kt/Color", "Quality",
         "Dia Wt", "Col Wt", "Qty", "Value", "Total Value", "Size"],
        [1, "PND", "PND-001", "14KT/W", "G-VS", 0.50, 0.10, 5, 100.0, 500.0, "7"],
    ]
    p = _real_xlsx(tmp_path, "ejl_audit.xlsx", rows_in)
    _, _, _, diag = extract_packing(p)
    assert "column_mapping_audit" in diag, (
        "column_mapping_audit key must be present in diagnostic for xlsx files"
    )


def test_column_mapping_audit_entries_have_required_keys(tmp_path):
    """Every entry in column_mapping_audit must carry the seven required fields."""
    rows_in = [
        [],
        ["PkSr", "Ctg", "DesignNo", "Qty", "Value"],
        [1, "PND", "PND-001", 3, 90.0],
    ]
    p = _real_xlsx(tmp_path, "ejl_keys.xlsx", rows_in)
    _, _, _, diag = extract_packing(p)
    audit = diag.get("column_mapping_audit", [])
    assert audit, "Expected at least one audit entry"
    for entry in audit:
        for field in ("col_index", "original_header", "normalised",
                      "canonical_field", "method", "confidence", "reason"):
            assert field in entry, f"Audit entry missing key '{field}'"


def test_column_mapping_audit_known_headers_have_alias_method(tmp_path):
    """Exact alias headers must be recorded with method='alias' and confidence=1.0."""
    rows_in = [
        [],
        ["PkSr", "Ctg", "DesignNo", "Qty", "Value"],
        [1, "PND", "PND-001", 3, 90.0],
    ]
    p = _real_xlsx(tmp_path, "ejl_alias.xlsx", rows_in)
    _, _, _, diag = extract_packing(p)
    audit = diag.get("column_mapping_audit", [])
    alias_entries = [e for e in audit if e["method"] == "alias"]
    assert alias_entries, "Expected at least one alias-method entry for known headers"
    for e in alias_entries:
        assert e["confidence"] == 1.0, f"alias entry must have confidence=1.0, got {e['confidence']}"


def test_column_mapping_audit_no_unrecognised_methods(tmp_path):
    """All method values in audit must be one of the five recognised strings."""
    rows_in = [
        [],
        ["PkSr", "Ctg", "DesignNo", "Qty", "Value", "WeirdColumn99"],
        [1, "PND", "PND-001", 3, 90.0, "X"],
    ]
    p = _real_xlsx(tmp_path, "ejl_methods.xlsx", rows_in)
    _, _, _, diag = extract_packing(p)
    audit = diag.get("column_mapping_audit", [])
    allowed = {"alias", "fuzzy", "fuzzy_warning", "llm", "unresolved"}
    for e in audit:
        assert e["method"] in allowed, (
            f"Unexpected method value '{e['method']}' — must be one of {allowed}"
        )


def test_column_mapping_audit_serialisable_as_json(tmp_path):
    """The diagnostic dict (including column_mapping_audit) must be
    JSON-serialisable so it can be stored in packing_documents.parser_diagnostic_json."""
    import json as _json
    rows_in = [
        [],
        ["PkSr", "Ctg", "DesignNo", "Qty", "Value"],
        [1, "PND", "PND-001", 3, 90.0],
    ]
    p = _real_xlsx(tmp_path, "ejl_serial.xlsx", rows_in)
    _, _, _, diag = extract_packing(p)
    # Must not raise
    serialised = _json.dumps(diag, ensure_ascii=False)
    decoded = _json.loads(serialised)
    assert "column_mapping_audit" in decoded


# ── Column mapping audit — frontend source-grep ──────────────────────────

_SD = Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html"


def test_shipment_detail_renders_column_mapping_audit_block():
    src = _SD.read_text(encoding="utf-8")
    assert "column_mapping_audit" in src, (
        "shipment-detail.html must render the column_mapping_audit block"
    )
    assert "packing-list-mapping-audit-" in src, (
        "shipment-detail.html must set data-testid for the audit block"
    )
    assert "mapping-audit-row-" in src, (
        "shipment-detail.html must set data-testid per audit row (includes method)"
    )
    assert "Excel column mapping" in src, (
        "shipment-detail.html must label the column mapping section"
    )


def test_shipment_detail_hides_audit_when_absent():
    src = _SD.read_text(encoding="utf-8")
    # The guard `Array.isArray(diag.column_mapping_audit) && diag.column_mapping_audit.length > 0`
    # must be present so the block is hidden when the audit key is absent.
    assert "Array.isArray(diag.column_mapping_audit)" in src, (
        "shipment-detail.html must guard the audit block so it is hidden when absent"
    )


def test_shipment_detail_marks_llm_as_advisory():
    src = _SD.read_text(encoding="utf-8")
    assert "mapping-llm-advisory-copy" in src, (
        "shipment-detail.html must include the LLM advisory disclaimer testid"
    )
    assert "advisory only" in src, (
        "shipment-detail.html must include the advisory-only disclaimer text"
    )
    assert "do not create products" in src or "do not create products, customers, PZ" in src, (
        "Advisory copy must explicitly state AI/LLM does not create business entities"
    )


def test_shipment_detail_marks_unresolved_as_review_required():
    src = _SD.read_text(encoding="utf-8")
    assert "mapping-unresolved-notice" in src, (
        "shipment-detail.html must include the unresolved notice testid"
    )
    assert "mapping-advisory-flag" in src, (
        "shipment-detail.html must flag advisory/unresolved rows per-row"
    )
    assert "review" in src, (
        "shipment-detail.html must include operator review language for non-authoritative mappings"
    )


def test_column_mapping_audit_no_write_surface_references():
    """The column mapper and extractor must not reference any write surfaces."""
    files = [
        Path(__file__).resolve().parents[1] / "app" / "services" / "excel_column_mapper.py",
    ]
    for f in files:
        src = f.read_text(encoding="utf-8")
        for forbidden in (
            "send_email", "queue_email", "smtp",
            "create_pz", "generate_pz",
            "wfirma_client", "wfirma_api",
            "proforma_create", "upsert_packing", "insert_packing",
        ):
            assert forbidden not in src, (
                f"{f.name} must not reference write surface '{forbidden}'"
            )
