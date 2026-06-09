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


# ── LLM operator-triggered reprocess (Task 5) ────────────────────────────────

_ROUTES_PACKING = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_packing.py"
_EXTRACTOR      = Path(__file__).resolve().parents[1] / "app" / "services" / "invoice_packing_extractor.py"
_PACKING_DB     = Path(__file__).resolve().parents[1] / "app" / "services" / "packing_db.py"


def test_extract_packing_accepts_llm_fallback_false(tmp_path):
    """extract_packing(path, llm_fallback=False) must not raise — default upload path."""
    rows_in = [[], ["PkSr", "Ctg", "DesignNo", "Qty"], [1, "PND", "D-001", 3]]
    p = _real_xlsx(tmp_path, "t_llm_false.xlsx", rows_in)
    result = extract_packing(p, llm_fallback=False)
    assert len(result) == 4


def test_extract_packing_accepts_llm_fallback_true(tmp_path, monkeypatch):
    """extract_packing(path, llm_fallback=True) must not raise; LLM is mocked."""
    import app.services.excel_column_mapper as _ecm
    monkeypatch.setattr(
        _ecm, "_llm_suggest_header",
        lambda header, candidates: {"suggested_field": None, "confidence": 0.0, "reason": "mocked"},
    )
    rows_in = [[], ["PkSr", "Ctg", "DesignNo", "UnknownCol99", "Qty"],
               [1, "PND", "D-001", "X", 3]]
    p = _real_xlsx(tmp_path, "t_llm_true.xlsx", rows_in)
    result = extract_packing(p, llm_fallback=True)
    assert len(result) == 4
    _, _, _, diag = result
    assert "column_mapping_audit" in diag


def test_llm_fallback_does_not_enter_col_map(tmp_path, monkeypatch):
    """With llm_fallback=True, LLM suggestions carry method='llm' and are
    excluded from build_col_map (only alias + fuzzy≥90 enter the col map)."""
    import app.services.excel_column_mapper as _ecm
    from app.services.excel_column_mapper import build_col_map, map_all_headers, CANONICAL_FIELDS

    # Return a valid canonical field from the LLM so it passes the guard.
    _some_canonical = next(iter(CANONICAL_FIELDS))
    monkeypatch.setattr(
        _ecm, "_llm_suggest_header",
        lambda header, candidates: {
            "suggested_field": _some_canonical,
            "confidence": 0.55,
            "reason": "mocked-llm",
        },
    )
    # Header that won't alias or fuzzy-match anything.
    mappings = map_all_headers(
        ["XYZZY_unrecognised_9999"],
        # Use real extractor aliases
        __import__("app.services.invoice_packing_extractor", fromlist=["_FIELD_ALIASES"])._FIELD_ALIASES,
        llm_fallback=True,
    )
    assert any(m.method == "llm" for m in mappings), "LLM suggestion must be present in audit"
    col_map = build_col_map(mappings)
    # The LLM-suggested column must NOT be in the col_map
    llm_canonical = next(m.canonical_field for m in mappings if m.method == "llm")
    assert llm_canonical not in col_map.values(), (
        "LLM-suggested field must NOT enter build_col_map"
    )


def test_normal_upload_does_not_pass_llm_fallback_true():
    """The standard upload route must never pass llm_fallback=True to extract_packing."""
    src = _ROUTES_PACKING.read_text(encoding="utf-8")
    # The upload route calls process_packing_upload, not extract_packing directly.
    # Guard: llm_fallback=True must only appear inside suggest_column_mapping handler.
    # Collect all lines with llm_fallback=True and assert they're in the suggest handler.
    lines = src.splitlines()
    in_suggest = False
    for line in lines:
        if "suggest_column_mapping" in line and "def " in line:
            in_suggest = True
        if in_suggest and "llm_fallback=True" in line:
            break  # found it where it belongs
        if not in_suggest and "llm_fallback=True" in line:
            raise AssertionError(
                f"llm_fallback=True found outside suggest_column_mapping handler: {line.strip()!r}"
            )


def test_suggest_column_mapping_endpoint_exists():
    """The suggest-column-mapping endpoint must be registered in routes_packing.py."""
    src = _ROUTES_PACKING.read_text(encoding="utf-8")
    assert "suggest-column-mapping" in src, (
        "routes_packing.py must define the suggest-column-mapping endpoint"
    )
    assert "_SuggestColumnMappingRequest" in src, (
        "routes_packing.py must define _SuggestColumnMappingRequest model"
    )
    assert "suggest_column_mapping" in src, (
        "routes_packing.py must define suggest_column_mapping handler"
    )


def test_suggest_column_mapping_writes_only_diagnostic():
    """The endpoint must write ONLY parser_diagnostic_json — no business writes."""
    src = _ROUTES_PACKING.read_text(encoding="utf-8")
    # Find the suggest_column_mapping function body (between its def and the next top-level def).
    start = src.find("async def suggest_column_mapping(")
    assert start != -1, "suggest_column_mapping not found"
    # Take a generous window (2000 chars) covering the function body.
    body = src[start: start + 2500]
    # MUST call update_packing_document_diagnostic.
    assert "update_packing_document_diagnostic" in body, (
        "suggest_column_mapping must call update_packing_document_diagnostic"
    )
    # Must NOT call write-path helpers that mutate business records.
    for forbidden in (
        "upsert_packing_lines",
        "upsert_packing_document",
        "seed_purchase_transit",
        "sync_draft_from_packing_upload",
        "wfirma",
        "queue_email",
        "create_pz",
    ):
        assert forbidden not in body, (
            f"suggest_column_mapping must NOT call '{forbidden}' (write surface)"
        )


def test_update_packing_document_diagnostic_function_exists():
    """packing_db must expose update_packing_document_diagnostic."""
    src = _PACKING_DB.read_text(encoding="utf-8")
    assert "def update_packing_document_diagnostic" in src, (
        "packing_db.py must define update_packing_document_diagnostic"
    )
    # Must write ONLY parser_diagnostic_json (not packing_lines, not extraction_status).
    start = src.find("def update_packing_document_diagnostic")
    body = src[start: start + 800]
    assert "parser_diagnostic_json" in body
    assert "upsert_packing_lines" not in body
    # UPDATE statement must not SET extraction_status (docstring may mention it).
    assert "SET extraction_status" not in body
    assert "SET parser_name" not in body


def test_extractor_llm_fallback_param_threaded():
    """_extract_packing_excel and extract_packing must both accept llm_fallback."""
    src = _EXTRACTOR.read_text(encoding="utf-8")
    assert "def _extract_packing_excel" in src
    assert "def extract_packing" in src
    # Both functions must carry llm_fallback parameter.
    import re as _re
    for fn in ("_extract_packing_excel", "extract_packing"):
        # Find from function def to next blank line or next def.
        m = _re.search(rf"def {fn}\b.*?\) ->", src, _re.DOTALL)
        if not m:
            m = _re.search(rf"def {fn}\b.*?\):", src, _re.DOTALL)
        assert m, f"Function {fn} not found"
        snippet = src[m.start(): m.start() + 400]
        assert "llm_fallback" in snippet, (
            f"{fn} must declare llm_fallback parameter"
        )


# ── Frontend button source-grep ───────────────────────────────────────────────

def test_frontend_suggest_button_testid_present():
    src = _SD.read_text(encoding="utf-8")
    assert "suggest-column-mapping-btn" in src, (
        "shipment-detail.html must have suggest-column-mapping-btn testid"
    )


def test_frontend_suggest_button_condition():
    """Button must only appear when unresolved or fuzzy_warning columns exist."""
    src = _SD.read_text(encoding="utf-8")
    # The condition must check for unresolved OR fuzzy_warning.
    assert ("method === 'unresolved' || m.method === 'fuzzy_warning'" in src or
            "m.method === 'fuzzy_warning' || m.method === 'unresolved'" in src), (
        "Suggest AI button condition must check for unresolved or fuzzy_warning"
    )
    # The button label must match the spec.
    assert "Suggest column mapping with AI" in src, (
        "Button label must be 'Suggest column mapping with AI'"
    )


def test_frontend_llm_suggest_advisory_note():
    """Advisory note must be rendered next to the AI button."""
    src = _SD.read_text(encoding="utf-8")
    assert "suggest-column-mapping-advisory-note" in src, (
        "shipment-detail.html must render suggest-column-mapping-advisory-note"
    )
    assert "Advisory only" in src or "advisory only" in src, (
        "Advisory note must state 'Advisory only'"
    )


def test_frontend_llm_mapping_meta_display():
    """llm_mapping_meta block must be conditionally rendered."""
    src = _SD.read_text(encoding="utf-8")
    assert "llm_mapping_meta" in src, (
        "shipment-detail.html must render the llm_mapping_meta audit block"
    )
    assert "llm-mapping-meta" in src, (
        "shipment-detail.html must set data-testid='llm-mapping-meta'"
    )


def test_frontend_suggest_button_never_fires_on_upload():
    """The fetch to suggest-column-mapping must require an explicit onClick — not fired on mount."""
    src = _SD.read_text(encoding="utf-8")
    # The endpoint call must only appear inside an onClick handler, not in a useEffect or
    # on-mount fetch block.
    idx = src.find("suggest-column-mapping")
    assert idx != -1
    # Walk 500 chars before the first occurrence — must not be inside useEffect.
    window = src[max(0, idx - 500): idx]
    assert "useEffect" not in window, (
        "suggest-column-mapping call must not appear inside useEffect (auto-trigger forbidden)"
    )
