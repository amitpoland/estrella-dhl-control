"""Wire-up tests — the wFirma PZ payload <description> field carries
the compact notes from `wfirma_pz_notes.build_wfirma_pz_notes`.

Source-grep tests + behavioural tests on the builder kwarg.
"""
from __future__ import annotations

from pathlib import Path

from service.app.services.import_pz_builder import (
    BatchRow,
    build_pz_request_from_batch,
)


ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_wfirma.py"
)


def _routes_body() -> str:
    return ROUTES.read_text(encoding="utf-8")


def test_routes_imports_build_wfirma_pz_notes():
    body = _routes_body()
    assert "from ..services.wfirma_pz_notes import build_wfirma_pz_notes" in body


def test_all_three_call_sites_pass_description_override():
    body = _routes_body()
    # Three callers — preview, products/resolve, pz_create — each must
    # pass `description_override=` to the builder, sourced from
    # build_wfirma_pz_notes(audit, batch_id) either inline or via a
    # local variable.
    count = body.count("description_override = ")
    assert count >= 3, (
        f"expected at least 3 description_override sites; found {count}"
    )
    # The notes helper is referenced (inline or via local variable).
    assert "build_wfirma_pz_notes(audit, batch_id)" in body


def test_preview_response_description_uses_notes_or_legacy_fallback():
    body = _routes_body()
    # The preview JSON response builds `description` from pz_notes
    # (preferred) with a legacy fallback. Pin both pieces.
    assert "description = pz_notes or" in body
    # The fallback shape (`batch=… | MRN …`) is preserved.
    assert 'f"batch={batch_id}"' in body or 'f"batch={batch_id}{mrn_part}"' in body


# ── Builder behaviour ─────────────────────────────────────────────────

def _row():
    return BatchRow(
        product_code   = "X-1",
        quantity       = 1.0,
        unit_netto_pln = 100.0,
        invoice_no     = "INV-1",
        description_en = "test",
        pl_desc        = "test PL",
        item_type      = "RING",
    )


def test_builder_uses_description_override_when_provided():
    result = build_pz_request_from_batch(
        rows           = [_row()],
        contractor_id  = "ctr",
        warehouse_id   = "wh",
        product_map    = {"X-1": "gid-1"},
        batch_id       = "BID",
        clearance_date = "2026-05-22",
        mrn            = "MRN-X",
        description_override = "INV:INV-1\nAWB:1234567890",
    )
    assert result.ready
    assert result.pz_request.description == "INV:INV-1\nAWB:1234567890"


def test_builder_falls_back_to_legacy_when_no_override():
    """Regression pin — Estrella + every existing caller continues to
    produce the `batch=… | MRN …` description when no override is
    supplied."""
    result = build_pz_request_from_batch(
        rows           = [_row()],
        contractor_id  = "ctr",
        warehouse_id   = "wh",
        product_map    = {"X-1": "gid-1"},
        batch_id       = "BID",
        clearance_date = "2026-05-22",
        mrn            = "MRN-X",
    )
    assert result.ready
    assert result.pz_request.description == "batch=BID | MRN MRN-X"


def test_builder_falls_back_when_override_empty_string():
    """Defensive — empty override string is treated as missing."""
    result = build_pz_request_from_batch(
        rows           = [_row()],
        contractor_id  = "ctr",
        warehouse_id   = "wh",
        product_map    = {"X-1": "gid-1"},
        batch_id       = "BID",
        clearance_date = "2026-05-22",
        mrn            = "MRN-X",
        description_override = "",
    )
    assert result.pz_request.description == "batch=BID | MRN MRN-X"


def test_builder_falls_back_when_override_whitespace_only():
    result = build_pz_request_from_batch(
        rows           = [_row()],
        contractor_id  = "ctr",
        warehouse_id   = "wh",
        product_map    = {"X-1": "gid-1"},
        batch_id       = "BID",
        clearance_date = "2026-05-22",
        mrn            = "",
        description_override = "   \n  \t  ",
    )
    assert result.pz_request.description == "batch=BID"


def test_pz_xml_carries_multiline_description():
    """Sanity — the wFirma XML builder accepts multi-line description
    content. wFirma's `<description>` element preserves newlines
    verbatim (they appear in the operator-visible Uwagi field)."""
    from service.app.services.wfirma_client import _build_pz_xml, PZRequest, PZLine
    req = PZRequest(
        contractor_id="ctr",
        warehouse_id="wh",
        date="2026-05-22",
        description="INV:088/2026-2027\nAWB:4789974092",
        lines=[PZLine(good_id="gid-1", count=1.0, price=100.0)],
    )
    xml = _build_pz_xml(req)
    # The newline-containing description body should appear verbatim
    # between <description>…</description>.
    assert "<description>INV:088/2026-2027\nAWB:4789974092</description>" in xml
    # XML structure invariants preserved.
    assert "<warehouse_document_contents>" in xml
    assert "<type>PZ</type>" in xml
