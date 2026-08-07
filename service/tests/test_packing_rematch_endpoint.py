"""POST /api/v1/packing/{batch_id}/rematch — governed re-extraction endpoint.

End-to-end against a real temp DB and a real xlsx: persist rows under a
deliberately WRONG assignment, then verify the dry run proposes the correction
without writing, and that apply is triple-gated (admin session, confirmation
token, non-blocking plan) before the same computation persists.

All fixtures synthetic — the repository is public.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

INV = "TEST/00-00/001"
BID = "B-REMATCH-1"


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _build_purchase_xlsx(path: Path) -> None:
    """Two-row EJL-style purchase packing list.

    Row 1: silver pendant  $5   → belongs to invoice line 1 (925, $5)
    Row 2: gold pendant  $106   → belongs to invoice line 2 (14KT, $106)
    """
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    # Preamble: the parser reads the invoice reference from here and stamps it
    # onto every row — without it every matcher tier vetoes on invoice_no.
    ws.append(["Invoice #", INV])
    ws.append([])
    ws.append(["PkSr", "Ctg", "DesignNo", "Kt/Color", "Quality",
               "Dia Wt", "Col Wt", "Qty", "Value", "Total Value", "Size"])
    ws.append([1, "PND", "SYN-001", "925/W", "PLAIN", 0, 0, 1, 5.0, 5.0, ""])
    ws.append([2, "PND", "SYN-002", "14KT/Y", "G-VS", 0.5, 0, 1, 106.0, 106.0, ""])
    wb.save(str(path))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    from app.auth.dependencies import get_current_user, require_admin
    # Admin session by default (Lesson O: session override, popped in teardown).
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "t", "email": "t@l", "role": "admin"}
    app.dependency_overrides[require_admin] = lambda: {
        "id": "t", "email": "t@l", "role": "admin"}

    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    try:
        yield TestClient(app), tmp_path, ddb, pdb
    finally:
        app.dependency_overrides.clear()


def _seed(tmp_path, ddb, pdb, *, wrong: bool = True) -> Path:
    """Batch with invoice authority + a packing file + persisted rows.

    ``wrong=True`` persists the historical mis-assignment: both rows on line 2,
    which over-fills a qty-1 line and leaves line 1 starved.
    """
    out = tmp_path / "outputs" / BID
    (out / "source" / "packing").mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(
        {"batch_id": BID, "tracking_no": BID, "awb": BID,
         "carrier": "DHL", "timeline": []}), encoding="utf-8")

    # Purchase authority: 2 one-piece lines the two rows discriminate on metal.
    inv_doc = ddb.register_document(
        batch_id=BID, document_type="purchase_invoice",
        file_name="invoice.pdf", file_path=str(out / "invoice.pdf"),
        file_hash="synthetic-invoice-hash", source="intake") or ""
    ddb.store_invoice_lines(inv_doc, BID, [
        {"invoice_no": INV, "line_position": 1, "product_code": f"{INV}-1",
         "description": "PCS, SL925 SILVER Plain Jewellery PENDANT",
         "quantity": 1, "unit_price": 5.0, "total_value": 5.0,
         "rate_usd": 5.0, "amount_usd": 5.0},
        {"invoice_no": INV, "line_position": 2, "product_code": f"{INV}-2",
         "description": "PCS, 14KT Gold Studded PENDANT",
         "quantity": 1, "unit_price": 106.0, "total_value": 106.0,
         "rate_usd": 106.0, "amount_usd": 106.0},
    ])

    # The stored packing source file + its content-addressed document record.
    pf = out / "source" / "packing" / "purchase_syn.xlsx"
    _build_purchase_xlsx(pf)
    from app.services.invoice_packing_extractor import file_sha256
    doc_id = pdb.upsert_packing_document(
        batch_id=BID, invoice_no=INV,
        source_file_path=str(pf), source_file_hash=file_sha256(pf),
        parser_name="test", parser_version="1", extraction_status="complete")

    # Persisted rows: sr1 (the silver $5 pendant) sits on the WRONG line when
    # wrong=True — the exact incident shape this endpoint exists to repair.
    pdb.upsert_packing_lines([
        {"batch_id": BID, "packing_document_id": doc_id, "invoice_no": INV,
         "pack_sr": 1, "invoice_line_position": 2 if wrong else 1,
         "product_code": f"{INV}-2" if wrong else f"{INV}-1",
         "design_no": "SYN-001", "item_type": "PENDANT", "quantity": 1,
         "unit_price": 5.0, "total_value": 5.0, "metal": "925",
         "match_strategy": "type+qty", "extracted_confidence": 0.80,
         "requires_manual_review": False},
        {"batch_id": BID, "packing_document_id": doc_id, "invoice_no": INV,
         "pack_sr": 2, "invoice_line_position": 2,
         "product_code": f"{INV}-2",
         "design_no": "SYN-002", "item_type": "PENDANT", "quantity": 1,
         "unit_price": 106.0, "total_value": 106.0, "metal": "14KT",
         "match_strategy": "type+qty+rate+metal", "extracted_confidence": 0.95,
         "requires_manual_review": False},
    ])
    return pf


def _rows_by_sr(pdb):
    return {r["pack_sr"]: r for r in pdb.get_packing_lines_for_batch(BID)}


# ── Dry run ──────────────────────────────────────────────────────────────────

def test_dry_run_proposes_the_correction_and_writes_nothing(env):
    cli, tmp, ddb, pdb = env
    _seed(tmp, ddb, pdb)
    before = _rows_by_sr(pdb)

    r = cli.post(f"/api/v1/packing/{BID}/rematch")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True and body["applied"] is False

    plan = body["plan"]
    assert plan["blocking"] is False
    changed = {c["pack_sr"]: c for c in plan["row_changes"]}
    # The mis-placed silver pendant moves to its metal-matching line.
    assert changed[1]["old"]["product_code"] == f"{INV}-2"
    assert changed[1]["new"]["product_code"] == f"{INV}-1"
    # The line reconciliation shows the over/starve pair resolving.
    recon = {l["product_code"]: l for l in plan["line_reconciliation"]}
    assert recon[f"{INV}-2"]["before"]["qty_status"] == "over"
    assert recon[f"{INV}-2"]["after"]["qty_status"] == "ok"
    assert recon[f"{INV}-1"]["before"]["qty_status"] == "short"
    assert recon[f"{INV}-1"]["after"]["qty_status"] == "ok"

    # And nothing was written.
    assert _rows_by_sr(pdb) == before


def test_dry_run_on_batch_with_no_stored_rows_is_404_not_an_empty_write(env):
    cli, tmp, ddb, pdb = env
    out = tmp / "outputs" / "B-NOROWS"
    (out / "source" / "packing").mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(
        {"batch_id": "B-NOROWS", "timeline": []}), encoding="utf-8")
    _build_purchase_xlsx(out / "source" / "packing" / "p.xlsx")
    r = cli.post("/api/v1/packing/B-NOROWS/rematch")
    assert r.status_code == 404


def test_unregistered_source_file_blocks_instead_of_guessing_a_document(env):
    """Content hash is the authority: an unregistered (or edited) file must not
    resolve by filename and must render the plan blocking."""
    cli, tmp, ddb, pdb = env
    pf = _seed(tmp, ddb, pdb)
    # Edit the file after registration → its hash no longer matches the record.
    _build_purchase_xlsx(pf)  # rebuild alone keeps content identical…
    import openpyxl
    wb = openpyxl.load_workbook(pf)
    wb.active.append([3, "RNG", "SYN-003", "14KT/Y", "G-VS", 0, 0, 1, 50.0, 50.0, ""])
    wb.save(str(pf))

    r = cli.post(f"/api/v1/packing/{BID}/rematch")
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert plan["blocking"] is True
    assert "no_unique_document_for_file" in {b["code"] for b in plan["blockers"]}


# ── Apply gating ─────────────────────────────────────────────────────────────

def test_apply_without_confirmation_token_refuses_and_writes_nothing(env):
    cli, tmp, ddb, pdb = env
    _seed(tmp, ddb, pdb)
    before = _rows_by_sr(pdb)

    for confirm in ("", "yes", "true", BID.lower() + "x"):
        r = cli.post(f"/api/v1/packing/{BID}/rematch",
                     params={"apply": "true", "confirm": confirm})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["applied"] is False
        assert body["refused"] == "confirmation_token_missing_or_mismatched"

    assert _rows_by_sr(pdb) == before


def test_apply_with_blocking_plan_refuses_and_writes_nothing(env):
    cli, tmp, ddb, pdb = env
    pf = _seed(tmp, ddb, pdb)
    import openpyxl
    wb = openpyxl.load_workbook(pf)
    wb.active.append([3, "RNG", "SYN-003", "14KT/Y", "G-VS", 0, 0, 1, 50.0, 50.0, ""])
    wb.save(str(pf))  # hash mismatch → blocking plan
    before = _rows_by_sr(pdb)

    r = cli.post(f"/api/v1/packing/{BID}/rematch",
                 params={"apply": "true", "confirm": BID})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is False
    assert body["refused"] == "plan_is_blocking"
    assert _rows_by_sr(pdb) == before


def test_apply_with_confirmation_persists_exactly_the_dry_run_plan(env):
    cli, tmp, ddb, pdb = env
    _seed(tmp, ddb, pdb)

    dry = cli.post(f"/api/v1/packing/{BID}/rematch").json()["plan"]
    r = cli.post(f"/api/v1/packing/{BID}/rematch",
                 params={"apply": "true", "confirm": BID})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is True
    assert body["rows_written"] == len(dry["row_changes"])

    after = _rows_by_sr(pdb)
    # sr1 landed on its metal-matching line; sr2 untouched.
    assert after[1]["product_code"] == f"{INV}-1"
    assert after[1]["invoice_line_position"] == 1
    assert after[2]["product_code"] == f"{INV}-2"
    assert after[2]["invoice_line_position"] == 2
    # After the write, a fresh plan projects zero changes.
    assert body["plan_after"]["rows_changed"] == 0


def test_apply_is_idempotent(env):
    cli, tmp, ddb, pdb = env
    _seed(tmp, ddb, pdb)
    cli.post(f"/api/v1/packing/{BID}/rematch",
             params={"apply": "true", "confirm": BID})
    snap = _rows_by_sr(pdb)

    r = cli.post(f"/api/v1/packing/{BID}/rematch",
                 params={"apply": "true", "confirm": BID})
    body = r.json()
    assert body["applied"] is False or body.get("rows_written", 0) == 0
    assert _rows_by_sr(pdb) == snap


def test_operator_confirmed_row_survives_an_apply(env):
    cli, tmp, ddb, pdb = env
    _seed(tmp, ddb, pdb)
    # Operator confirms the (wrong) mapping on sr1. The machine may disagree;
    # it must not overwrite a human decision.
    rows = _rows_by_sr(pdb)
    import sqlite3
    with sqlite3.connect(tmp / "packing.db") as con:
        con.execute(
            "UPDATE packing_lines SET operator_review_status='confirmed' WHERE id=?",
            (rows[1]["id"],))
        con.commit()

    dry = cli.post(f"/api/v1/packing/{BID}/rematch").json()["plan"]
    preserved = {e["pack_sr"] for e in dry["operator_confirmed_preserved"]}
    assert preserved == {1}
    # With sr1 pinned to line 2, the projected "after" keeps line 2 over
    # authority — so the plan blocks rather than promising a fix it can't make.
    assert dry["blocking"] is True

    before = _rows_by_sr(pdb)
    r = cli.post(f"/api/v1/packing/{BID}/rematch",
                 params={"apply": "true", "confirm": BID})
    assert r.json()["applied"] is False
    assert _rows_by_sr(pdb) == before


# ── Auth (Lesson O: session-guarded route, tests migrate with it) ────────────

def test_rematch_requires_admin_not_just_a_session(env):
    cli, tmp, ddb, pdb = env
    _seed(tmp, ddb, pdb)
    from app.main import app
    from app.auth.dependencies import get_current_user, require_admin
    # Non-admin session: restore the real require_admin so the role check runs.
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u", "email": "u@l", "role": "viewer"}
    app.dependency_overrides.pop(require_admin, None)
    try:
        r = cli.post(f"/api/v1/packing/{BID}/rematch")
        assert r.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "t", "email": "t@l", "role": "admin"}
        app.dependency_overrides[require_admin] = lambda: {
            "id": "t", "email": "t@l", "role": "admin"}


def test_rematch_rejects_unauthenticated(env):
    cli, tmp, ddb, pdb = env
    _seed(tmp, ddb, pdb)
    from app.main import app
    from app.auth.dependencies import get_current_user, require_admin
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_admin, None)
    try:
        r = cli.post(f"/api/v1/packing/{BID}/rematch")
        assert r.status_code == 401
    finally:
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "t", "email": "t@l", "role": "admin"}
        app.dependency_overrides[require_admin] = lambda: {
            "id": "t", "email": "t@l", "role": "admin"}
