"""test_invoice_line_diagnostics.py — generic line-description checks.

Covers:
  - pure evaluate_invoice_lines logic (warning codes + severities)
  - module purity (no DB / external / wFirma surfaces)
  - integration: routes_intake.py path persists the blob and flips
    requires_manual_review without blocking invoice_lines storage
"""
from __future__ import annotations

import json
import sqlite3 as _s
from pathlib import Path

import pytest


# ── Pure-function tests ────────────────────────────────────────────────────

def _line(pos: int, pc: str, desc: str) -> dict:
    return {"line_position": pos, "product_code": pc, "description": desc}


def test_clean_invoice_emits_no_warnings():
    from app.services import invoice_line_diagnostics as ild
    lines = [
        _line(1, "EJL/26-27/149-1", "PCS, 18KT Gold, Plain Jewellery RING"),
        _line(2, "EJL/26-27/149-2", "PCS, 18KT Gold, Stud With Diam Jewellery PENDANT"),
        _line(3, "EJL/26-27/149-3", "PCS, 14KT Gold, Stud With Diam Jewellery RING"),
        _line(4, "EJL/26-27/149-4", "PCS, 18KT Gold, Stud With Diam Jewellery RING"),
    ]
    out = ild.evaluate_invoice_lines(lines)
    assert out["any_warning"]            is False
    assert out["requires_manual_review"] is False
    assert out["line_warnings"]          == []
    assert out["doc_warnings"]           == []
    assert out["kind"]           == "invoice_line_description_diagnostics"
    assert out["schema_version"] == "1"
    assert isinstance(out["evaluated_at"], str)


def test_line_equals_customs_header_emits_error():
    from app.services import invoice_line_diagnostics as ild
    header = ("Diamond / Colour Stone / LGD Studded / Plain 09KT / 14KT / "
              "18 KT Gold & Platinum Jewellery")
    lines = [
        _line(1, "EJL/26-27/X-1", header),
        _line(2, "EJL/26-27/X-2", header),
        _line(3, "EJL/26-27/X-3", "PCS, 14KT Gold, Plain Jewellery RING"),
    ]
    out = ild.evaluate_invoice_lines(lines, customs_goods_description=header)
    assert out["any_warning"]            is True
    assert out["requires_manual_review"] is True
    errors = [w for w in out["line_warnings"] if w["severity"] == "error"]
    assert len(errors) == 2, f"expected 2 errors, got {errors!r}"
    for w in errors:
        assert "header_description_used_as_line" in w["codes"]


def test_no_customs_goods_description_skips_header_equality():
    """When the caller passes no customs header, the equality check
    must be quietly skipped (not itself a warning)."""
    from app.services import invoice_line_diagnostics as ild
    desc = ("Diamond / Colour Stone / LGD Studded / Plain 09KT / 14KT / "
            "18 KT Gold & Platinum Jewellery")
    out = ild.evaluate_invoice_lines([
        _line(1, "EJL/Y-1", desc),
    ], customs_goods_description="")
    # No 'header_description_used_as_line' fires without the cust source.
    for w in out["line_warnings"]:
        assert "header_description_used_as_line" not in w["codes"]


def test_repeated_long_description_across_positions_warns():
    from app.services import invoice_line_diagnostics as ild
    long_d = ("Same long description text appearing on multiple line "
              "positions which would be suspicious for parser collapse "
              "of header into per-line slots — needs operator review.")
    assert len(long_d) > 120
    lines = [
        _line(1, "EJL/Z-1", long_d),
        _line(2, "EJL/Z-2", long_d),
        _line(3, "EJL/Z-3", long_d),
    ]
    out = ild.evaluate_invoice_lines(lines)
    flagged = [w for w in out["line_warnings"]
                if "suspicious_repeated_line_description" in w["codes"]]
    assert len(flagged) == 3
    for w in flagged:
        assert w["severity"] == "warn"
    assert out["requires_manual_review"] is True


def test_mixed_category_description_warns():
    from app.services import invoice_line_diagnostics as ild
    desc = "PCS, 14KT Gold, Jewellery RING / PENDANT / EARRINGS"
    out = ild.evaluate_invoice_lines([
        _line(1, "EJL/MC-1", desc),
    ])
    assert any("mixed_category_description" in w["codes"]
               for w in out["line_warnings"])
    assert out["requires_manual_review"] is True


def test_looks_like_header_heuristic_positive():
    """4 slashes, multiple karat tokens, no trailing item-type → header."""
    from app.services import invoice_line_diagnostics as ild
    desc = ("Diamond / Colour Stone / LGD Studded / Plain 09KT / 14KT / "
            "18 KT Gold & Platinum Jewellery")
    out = ild.evaluate_invoice_lines([_line(1, "EJL/H-1", desc)])
    codes = out["line_warnings"][0]["codes"]
    assert "looks_like_header_description" in codes


def test_looks_like_header_heuristic_negative_for_normal_line():
    """Real per-line text ending in a singular item-type token must NOT
    trigger the header heuristic — even when it mentions one karat."""
    from app.services import invoice_line_diagnostics as ild
    desc = "PCS, 18KT Gold, Plain Jewellery RING"
    out = ild.evaluate_invoice_lines([_line(1, "EJL/N-1", desc)])
    # No line_warning at all is the strongest assertion.
    assert out["any_warning"] is False, out["line_warnings"]


def test_missing_line_description_warns():
    from app.services import invoice_line_diagnostics as ild
    out = ild.evaluate_invoice_lines([_line(1, "EJL/MISS-1", "")])
    codes = out["line_warnings"][0]["codes"]
    assert "missing_line_description" in codes
    assert out["line_warnings"][0]["severity"] == "warn"
    assert out["requires_manual_review"] is True


def test_unusually_long_line_is_info_only():
    """A 240-char description alone (no slashes, no karat patterns)
    must surface only the info-level code — no review flip."""
    from app.services import invoice_line_diagnostics as ild
    desc = "X" * 240
    out = ild.evaluate_invoice_lines([_line(1, "EJL/L-1", desc)])
    assert len(out["line_warnings"]) == 1
    w = out["line_warnings"][0]
    assert "line_description_unusually_long" in w["codes"]
    assert w["severity"] == "info"
    assert out["requires_manual_review"] is False


def test_function_is_pure_and_deterministic():
    from app.services import invoice_line_diagnostics as ild
    lines = [
        _line(1, "EJL/PUR-1", "PCS, 14KT Gold, Plain Jewellery RING"),
        _line(2, "EJL/PUR-2", "PCS, 18KT Gold, Stud With Diam Jewellery PENDANT"),
    ]
    snapshot = json.dumps(lines, sort_keys=True)
    a = ild.evaluate_invoice_lines(lines)
    b = ild.evaluate_invoice_lines(lines)
    # Caller list unchanged
    assert json.dumps(lines, sort_keys=True) == snapshot
    # Outputs equal modulo the timestamp field
    a.pop("evaluated_at"); b.pop("evaluated_at")
    assert a == b


def test_module_source_has_no_external_or_db_calls():
    """Source-grep guard: the diagnostics module must never reach
    wfirma_client / requests / httpx / sqlite / posting paths."""
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "invoice_line_diagnostics.py").read_text(encoding="utf-8")
    for bad in (
        "wfirma_client", "requests.", "httpx.", "sqlite3",
        "create_proforma", "create_customer", "create_product",
        "send_email", "dhl_dispatch", "con.execute", "cursor.execute",
        "ddb.", "document_db",
    ):
        assert bad not in src, f"diagnostics module must not reference {bad!r}"


def test_module_source_does_not_invent_product_code_or_design_no_alias():
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "invoice_line_diagnostics.py").read_text(encoding="utf-8")
    # No outbound product_code or design_no assignments to draft lines.
    assert "product_code =" not in src or "product_code = (" not in src
    assert "design_no" not in src, (
        "diagnostics must not touch design_no at all — line is a "
        "read-only diagnostic surface"
    )


# ── Integration: routes_intake.py wire-up ──────────────────────────────────

@pytest.fixture()
def fresh_intake(tmp_path, monkeypatch):
    """Per-test storage with documents.db initialised + module-level
    _db_path saved/restored so other suites aren't polluted."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    from app.services import document_db as ddb
    saved = ddb._db_path
    ddb.init_document_db(tmp_path / "documents.db")
    try:
        yield tmp_path
    finally:
        ddb._db_path = saved


def _register_test_invoice_doc(tmp: Path) -> tuple:
    """Insert a shipment_documents row directly + return (doc_id, batch_id)."""
    from app.services import document_db as ddb
    batch_id = "SHIPMENT_TEST_DIAG"
    # Touch a fake file path that exists so sha256_file works.
    fpath = tmp / "fake-invoice.pdf"
    fpath.write_bytes(b"fake")
    doc_id = ddb.register_document(
        batch_id=batch_id, document_type="purchase_invoice",
        file_name="fake-invoice.pdf", file_path=str(fpath),
        file_hash=ddb.sha256_file(fpath),
        awb="", source="test",
    )
    return doc_id or "", batch_id


def test_integration_writes_diagnostics_blob_when_warning_fires(fresh_intake):
    """Drive the helper directly (matches what routes_intake.py does
    after invoice parse).  Asserts the blob lands in
    document_extraction_json.normalized_json and the review flag flips."""
    tmp = fresh_intake
    from app.services import document_db as ddb
    from app.services import invoice_line_diagnostics as ild
    doc_id, batch_id = _register_test_invoice_doc(tmp)
    assert doc_id

    # Lines that DEFINITELY trip a warn-level code:
    long_d = "A" * 130 + " repeated description across multiple positions"
    lines = [
        {"line_position": 1, "product_code": "EJL/IT-1", "description": long_d},
        {"line_position": 2, "product_code": "EJL/IT-2", "description": long_d},
    ]
    diag = ild.evaluate_invoice_lines(lines)
    assert diag["any_warning"] is True
    assert diag["requires_manual_review"] is True

    ddb.merge_document_normalized_json(
        document_id=doc_id, batch_id=batch_id, blob=diag,
        document_type="purchase_invoice",
    )
    ddb.update_document_status(document_id=doc_id, requires_manual_review=True)

    # Blob persisted under normalized_json
    db = tmp / "documents.db"
    with _s.connect(str(db)) as con:
        row = con.execute(
            "SELECT normalized_json FROM document_extraction_json "
            "WHERE document_id=?", (doc_id,)
        ).fetchone()
        assert row is not None, "diagnostics row not persisted"
        blob = json.loads(row[0])
        assert blob.get("kind") == "invoice_line_description_diagnostics"
        assert blob.get("any_warning") is True
        assert any("suspicious_repeated_line_description" in (w.get("codes") or [])
                   for w in blob.get("line_warnings") or [])
        # And the document's requires_manual_review is flipped.
        flag = con.execute(
            "SELECT requires_manual_review FROM shipment_documents "
            "WHERE id=?", (doc_id,)
        ).fetchone()
        assert flag is not None and int(flag[0]) == 1


def test_integration_does_not_block_invoice_lines_storage(fresh_intake):
    """The diagnostics step must never throw or block the surrounding
    intake flow.  Storing invoice_lines must succeed even when the
    diagnostics blob also writes."""
    tmp = fresh_intake
    from app.services import document_db as ddb
    from app.services import invoice_line_diagnostics as ild
    doc_id, batch_id = _register_test_invoice_doc(tmp)

    bad_lines = [
        {"invoice_no": "EJL/IT/A", "line_position": 1,
         "product_code": "EJL/IT/A-1", "description": "",   # missing_line_description
         "quantity": 1.0, "unit_price": 100.0, "currency": "USD"},
    ]
    n = ddb.store_invoice_lines(doc_id, batch_id, bad_lines)
    assert n == 1

    diag = ild.evaluate_invoice_lines(bad_lines)
    ddb.merge_document_normalized_json(
        document_id=doc_id, batch_id=batch_id, blob=diag,
        document_type="purchase_invoice",
    )
    # invoice_lines row is still there — diagnostics did not block.
    with _s.connect(str(tmp / "documents.db")) as con:
        cnt = con.execute(
            "SELECT COUNT(*) FROM invoice_lines WHERE document_id=?",
            (doc_id,),
        ).fetchone()[0]
        assert cnt == 1


def test_integration_does_not_mutate_invoice_lines_description(fresh_intake):
    """The diagnostics step must not rewrite the stored
    invoice_lines.description column."""
    tmp = fresh_intake
    from app.services import document_db as ddb
    from app.services import invoice_line_diagnostics as ild
    doc_id, batch_id = _register_test_invoice_doc(tmp)
    original = "PCS, 14KT Gold, Stud With Diam Jewellery RING"
    ddb.store_invoice_lines(doc_id, batch_id, [{
        "invoice_no": "EJL/IT/B", "line_position": 1,
        "product_code": "EJL/IT/B-1", "description": original,
        "quantity": 1.0, "unit_price": 100.0, "currency": "USD",
    }])
    diag = ild.evaluate_invoice_lines([
        {"line_position": 1, "product_code": "EJL/IT/B-1",
         "description": original}
    ])
    ddb.merge_document_normalized_json(
        document_id=doc_id, batch_id=batch_id, blob=diag,
        document_type="purchase_invoice",
    )
    with _s.connect(str(tmp / "documents.db")) as con:
        row = con.execute(
            "SELECT description FROM invoice_lines WHERE document_id=?",
            (doc_id,),
        ).fetchone()
        assert row is not None and row[0] == original


def test_integration_intake_routes_call_diagnostics_helper():
    """Source-grep guard: routes_intake.py must invoke the new helper
    at both invoice-parse call sites without altering store_invoice_lines."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_intake.py").read_text(encoding="utf-8")
    # Helper imported lazily inside both branches
    assert src.count("from app.services import invoice_line_diagnostics") >= 2
    assert src.count("ild.evaluate_invoice_lines(lines)") >= 2
    assert src.count("ddb.merge_document_normalized_json(") >= 2
    assert src.count("requires_manual_review=True") >= 2
    # store_invoice_lines is still called BEFORE diagnostics (so a
    # diagnostics failure can never block storage).
    inv = src.index("ddb.store_invoice_lines(doc_id, batch_id, lines)")
    diag = src.index("ild.evaluate_invoice_lines(lines)")
    assert inv < diag, (
        "store_invoice_lines must run BEFORE diagnostics at the first "
        "intake site"
    )
