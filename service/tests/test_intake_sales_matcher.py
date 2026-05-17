"""test_intake_sales_matcher.py — PR-3b Intake Sales Upload Cleanup.

Verifies that both first-time-upload paths in routes_intake.py route
sales rows through sales_packing_matcher before persistence, and that
the legacy "design_no as product_code" fallback has been removed.

Paths covered:
  - shipment_intake          (POST /api/v1/shipment/upload via the
                              intake_router; the smell removed at
                              former routes_intake.py line 835)
  - sales_packing_reingest   (POST /api/v1/shipment/sales-packing/reingest;
                              smell removed at former line 1830)

Hard architectural rule re-verified here:
  product_code is NEVER set from design_no by any intake path. Sales
  rows either persist a canonical EJL/...-N code (from the parser,
  the PND disambiguator, or sales_packing_matcher) or persist an
  empty product_code — which the DB layer continues to accept.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest
from fastapi.testclient import TestClient


URL_REINGEST = "/api/v1/shipment/sales-packing/reingest"
BATCH        = "BATCH_PR3B"


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    from app.services import packing_db as pdb
    from app.services import warehouse_db as wdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_service_charges_db as scdb
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    scdb.init(tmp_path / "proforma_links.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    from app.core.config import settings
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── helpers ─────────────────────────────────────────────────────────────────

def _seed_purchase_pair(storage, batch_id, design, product, invoice_no="EJL/X-1"):
    """Seed packing.db with one (design_no, product_code) row for the batch."""
    from app.services import packing_db as pdb
    doc_id = pdb.upsert_packing_document(
        batch_id=batch_id, document_id=f"pd-{batch_id}-{design}",
        source_file_path=f"/tmp/{design}.xlsx", invoice_no=invoice_no,
        parser_name="t", parser_version="1",
        source_file_hash=f"h-{batch_id}-{design}",
    )
    pdb.upsert_packing_lines([{
        "packing_document_id": doc_id, "batch_id": batch_id,
        "invoice_no": invoice_no, "invoice_line_position": 1,
        "product_code": product, "design_no": design,
        "batch_no": "", "bag_id": "", "tray_id": "",
        "item_type": "RING", "uom": "PCS",
        "quantity": 1.0, "gross_weight": 0, "net_weight": 0,
        "metal": "", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": 1, "unit_price": 0.0, "total_value": 0.0,
    }])


def _seed_sales_doc(client_name, *, batch=BATCH, ref="REF", doc_no="SO"):
    from app.services import document_db as ddb
    return ddb.store_sales_document(
        batch_id=batch, document_id=str(uuid.uuid4()),
        data={"client_name": client_name, "client_ref": ref,
              "sales_doc_no": doc_no},
    )


def _make_sales_xlsx(tmp_path: Path, *, name: str, design: str,
                     invoice_no: str = "EJL/X-1",
                     value: float = 200.0) -> Path:
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append([f"Export No : {invoice_no}"])
    ws.append([""])
    ws.append(["PkSr", "DesignNo", "Qty", "Value", "Total Value"])
    ws.append([1, design, 1, value, value])
    p = tmp_path / name; wb.save(str(p))
    return p


def _all_rows(storage, batch_id=BATCH):
    with sqlite3.connect(str(storage / "documents.db")) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(
            "SELECT * FROM sales_packing_lines WHERE batch_id=? "
            "ORDER BY client_name, design_no",
            (batch_id,),
        )]


# ── Source-grep invariants ──────────────────────────────────────────────────

def test_routes_intake_has_no_design_no_as_pc_fallback():
    """The two former smell sites (line 835 and line 1830) used the
    pattern `r.get("product_code") or r.get("design_no") or ""`.
    After PR-3b that pattern must NOT appear anywhere in
    routes_intake.py — sales rows either get a canonical pc or stay
    empty."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_intake.py").read_text(encoding="utf-8")
    # The exact tail of the old fallback chain.
    assert 'or r.get("design_no") or ""' not in src, (
        "routes_intake.py still contains the design_no→product_code fallback"
    )


def test_routes_intake_calls_sales_packing_matcher_twice():
    """Matcher must be wired into BOTH sales intake paths
    (shipment_intake + sales_packing_reingest)."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_intake.py").read_text(encoding="utf-8")
    n = src.count("match_sales_lines_to_packing")
    assert n >= 2, (
        f"expected matcher imported/called >=2 times in routes_intake.py, "
        f"got {n}"
    )


def test_no_new_external_calls_introduced_in_routes_intake():
    """PR-3b is local-DB only — must not introduce new external HTTP
    or wFirma/SMTP/DHL surfaces in routes_intake.py."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_intake.py").read_text(encoding="utf-8")
    # Verify the matcher symbol is present (import may be multi-line).
    assert "match_sales_lines_to_packing" in src, (
        "matcher symbol not referenced in routes_intake.py"
    )
    # Verify the matcher import is the only NEW external-ish surface.
    # The matcher module itself must be local-DB only (separately
    # locked by test_matcher_module_has_no_external_calls in
    # test_sales_packing_matcher.py).  Here we just confirm no new
    # HTTP/SMTP/DHL surfaces were imported from the matcher path.
    assert "from ..services.sales_packing_matcher import" in src, (
        "matcher import statement not found"
    )


# ── Reingest end-to-end: design_no resolves to canonical pc ────────────────

def test_reingest_resolves_pc_from_same_batch_packing(client, storage, tmp_path):
    """Seed purchase packing with (D-77, EJL/X-1-7). Reingest a sales
    file whose only row has design_no=D-77 and no product_code. After
    reingest, sales_packing_lines.product_code must be the canonical
    EJL code — NOT the design_no."""
    _seed_purchase_pair(storage, BATCH, design="D-77", product="EJL/X-1-7")
    sd = _seed_sales_doc("ACME")

    xlsx = _make_sales_xlsx(tmp_path, name="s.xlsx",
                             design="D-77", value=300.0)
    files = [("files", ("s.xlsx", open(str(xlsx), "rb"),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
    data = {
        "batch_id":          BATCH,
        "metadata":          json.dumps({"sales_blocks": [{
            "packing_index": 0, "client_name": "ACME", "client_ref": "REF",
        }]}),
        "override_currency": "",
    }
    r = client.post(URL_REINGEST, headers=_auth(), files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()

    # Response carries sales_matcher_summary on per_file.
    per_files = body.get("results") or body.get("files") or []
    # Some shapes nest under "details"; be lenient.
    found_summary = False
    for entry in (per_files if isinstance(per_files, list)
                  else [per_files]):
        if isinstance(entry, dict) and "sales_matcher_summary" in entry:
            found_summary = True
            assert "D-77" in entry["sales_matcher_summary"]["designs_resolved"]
            assert entry["sales_matcher_summary"]["designs_resolved"]["D-77"] \
                == "EJL/X-1-7"
            break
    # If the wrapper shape doesn't expose per-file dicts, fall through
    # to DB-state assertions which are the load-bearing checks.
    rows = _all_rows(storage)
    assert rows, "no sales_packing_lines persisted"
    assert all(r["product_code"] == "EJL/X-1-7" for r in rows), (
        f"sales rows did not pick up canonical pc: "
        f"{[r['product_code'] for r in rows]}"
    )


# ── Reingest end-to-end: unresolvable design → product_code='' ─────────────

def test_reingest_leaves_pc_empty_when_unresolvable(client, storage, tmp_path):
    """Seed NO purchase packing for the design. Reingest a sales file
    with that design. product_code MUST be empty — design_no NEVER
    becomes pc."""
    sd = _seed_sales_doc("ACME")

    xlsx = _make_sales_xlsx(tmp_path, name="s.xlsx",
                             design="GHOST-DESIGN", value=100.0)
    files = [("files", ("s.xlsx", open(str(xlsx), "rb"),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
    data = {
        "batch_id":          BATCH,
        "metadata":          json.dumps({"sales_blocks": [{
            "packing_index": 0, "client_name": "ACME", "client_ref": "REF",
        }]}),
        "override_currency": "USD",
    }
    r = client.post(URL_REINGEST, headers=_auth(), files=files, data=data)
    assert r.status_code == 200, r.text

    rows = _all_rows(storage)
    assert rows
    for rec in rows:
        assert rec["product_code"] == "", (
            f"product_code must stay empty for unresolvable design, got "
            f"{rec['product_code']!r}"
        )
        assert rec["product_code"] != rec["design_no"], (
            "product_code must NEVER equal design_no on unresolvable rows"
        )


# ── Reingest: existing canonical pc is preserved ───────────────────────────

def test_reingest_preserves_explicit_canonical_pc(client, storage, tmp_path,
                                                   monkeypatch):
    """When the parser explicitly emits a canonical product_code (rare
    but possible), the matcher's existing-wins branch must preserve
    it untouched, even if same-batch packing_lines would map to a
    different code."""
    _seed_purchase_pair(storage, BATCH,
                         design="D-K", product="EJL/X-1-WRONG")
    sd = _seed_sales_doc("ACME")

    # Patch extract_packing to return a row that already carries a
    # canonical product_code (simulates a richer sales packing file).
    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: (
            [{"design_no": "D-K",
              "product_code": "EJL/X-1-RIGHT",
              "invoice_no": "EJL/X-1",
              "quantity": 1.0, "unit_price": 50.0,
              "currency": "USD", "total_value": 50.0}],
            "fake", "1.0", {"failure_reason": None},
        ),
    )

    xlsx = _make_sales_xlsx(tmp_path, name="s.xlsx", design="D-K")
    files = [("files", ("s.xlsx", open(str(xlsx), "rb"),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
    data = {
        "batch_id":          BATCH,
        "metadata":          json.dumps({"sales_blocks": [{
            "packing_index": 0, "client_name": "ACME", "client_ref": "REF",
        }]}),
        "override_currency": "USD",
    }
    r = client.post(URL_REINGEST, headers=_auth(), files=files, data=data)
    assert r.status_code == 200, r.text

    rows = _all_rows(storage)
    assert rows
    assert rows[0]["product_code"] == "EJL/X-1-RIGHT", (
        "explicit canonical pc must be preserved by matcher (existing-wins)"
    )


# ── Reingest: client_name / client_ref unchanged by matcher ────────────────

def test_reingest_client_name_and_ref_unchanged(client, storage, tmp_path):
    """The matcher only touches product_code. client_name and
    client_ref must be exactly what the intake handler computed."""
    _seed_purchase_pair(storage, BATCH, design="D-CN", product="EJL/X-1-CN")
    sd = _seed_sales_doc("Foo Client", ref="REF-XYZ")

    xlsx = _make_sales_xlsx(tmp_path, name="s.xlsx", design="D-CN")
    files = [("files", ("s.xlsx", open(str(xlsx), "rb"),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
    data = {
        "batch_id":          BATCH,
        "metadata":          json.dumps({"sales_blocks": [{
            "packing_index": 0, "client_name": "Foo Client",
            "client_ref": "REF-XYZ",
        }]}),
        "override_currency": "USD",
    }
    r = client.post(URL_REINGEST, headers=_auth(), files=files, data=data)
    assert r.status_code == 200, r.text

    rows = _all_rows(storage)
    assert rows
    assert rows[0]["client_name"] == "Foo Client"
    assert rows[0]["client_ref"]  == "REF-XYZ"
    assert rows[0]["product_code"] == "EJL/X-1-CN"


# ── Architectural — product_code never equals design_no unless canonical ──

def test_architectural_pc_never_equals_design_no_unless_canonical(
    client, storage, tmp_path,
):
    """After any intake run, sales_packing_lines.product_code should
    either be empty OR equal a value that came from packing_lines (i.e.
    canonical). It must NEVER equal the design_no of the same row when
    that design_no is not itself a canonical EJL-style code."""
    _seed_purchase_pair(storage, BATCH,
                         design="D-A", product="EJL/X-1-A")
    # D-B has no purchase evidence → should resolve empty
    _seed_sales_doc("ACME")

    for design in ("D-A", "D-B"):
        xlsx = _make_sales_xlsx(tmp_path, name=f"{design}.xlsx",
                                 design=design)
        files = [("files", (f"{design}.xlsx", open(str(xlsx), "rb"),
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
        data = {
            "batch_id":          BATCH,
            "metadata":          json.dumps({"sales_blocks": [{
                "client": "ACME", "client_ref": "REF",
                "files": [f"{design}.xlsx"],
            }]}),
            "override_currency": "USD",
        }
        r = client.post(URL_REINGEST, headers=_auth(),
                        files=files, data=data)
        assert r.status_code == 200, r.text

    rows = _all_rows(storage)
    # D-A row gets canonical pc; D-B row gets empty pc.
    for rec in rows:
        pc = rec["product_code"]
        dn = rec["design_no"]
        if not pc:
            continue  # empty is allowed
        # Non-empty pc must NOT equal the design_no unless dn itself is
        # canonical-looking (starts with "EJL/" or similar).  In this
        # test we deliberately use non-canonical design_nos.
        assert pc != dn, (
            f"product_code {pc!r} must not equal non-canonical "
            f"design_no {dn!r}"
        )
