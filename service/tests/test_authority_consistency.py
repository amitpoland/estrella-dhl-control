"""Authority consistency: detect stale projections; repair only proven local ones.

Does not reopen #1205/#1206/#1208 algorithms. Pins the historical failures:
  * promote written=0 still converges blank editable drafts
  * create-and-adopt / adopt / update-and-adopt project Product Master mapped
  * pending/mismatch never maps Product Master
  * Product Master cannot claim mapped without canonical match
  * warehouse module enabled + missing warehouse id refuses create
  * goods/add XML never regrows <warehouse_type>simple
  * second repair/convergence is idempotent
"""
from __future__ import annotations

import inspect
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import document_db as ddb
from app.services import proforma_invoice_link_db as pildb
from app.services import reservation_db as rdb
from app.services import wfirma_db as wfdb
from app.services.authority_consistency import (
    BLOCKED,
    CONFLICT,
    KIND_DESC_INVALID,
    KIND_DESC_STALE,
    KIND_MAP_CONFLICT,
    KIND_MAP_STALE,
    KIND_WAREHOUSE,
    REPAIRABLE,
    evaluate_authority_consistency,
    repair_derived_projections,
)
from app.services.commercial_authority import promote_and_enrich_batch_drafts
from app.services.description_engine import promote_pz_rows_to_product_descriptions
from app.services.wfirma_client import _build_create_product_xml, create_product


CODE = "EJL/26-27/AC-1"
WFID = "51677283"
CANON_PL = (
    "Pierścionek z 18-karatowego złota (próba 750) z diamentem laboratoryjnym."
)
CANON_EN = "Lab Grown Diamond 18KT Gold RING"


@dataclass
class _WFStub:
    wfirma_id: str = WFID
    name: str = "Pierścionek"
    code: str = CODE
    unit: str = "szt."
    count: float = 0.0
    reserved: float = 0.0


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    monkeypatch.setattr(settings, "environment", "dev", raising=False)
    monkeypatch.setattr(settings, "wfirma_warehouse_module_enabled", True, raising=False)
    monkeypatch.setattr(settings, "wfirma_warehouse_id", "347088", raising=False)
    ddb.init_document_db(tmp_path / "documents.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return tmp_path


def _seed_pd(code=CODE, pl=CANON_PL, en=CANON_EN):
    ddb.upsert_product_description(
        product_code=code,
        item_type="RING",
        name_pl=pl,
        description_pl=pl,
        description_en=en,
        material_pl="",
        purpose_pl="Ozdoba — biżuteria do noszenia.",
        description_block=f"{pl} / {en}",
        description_line=pl,
        source="pz_rows",
    )


def _birth_blank(storage: Path, *, batch_id: str, client: str = "Kenny", code=CODE):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        storage / "proforma_links.db",
        batch_id=batch_id,
        client_name=client,
        currency="USD",
        lines=[{
            "product_code": code,
            "design_no": "JR08388-0.55",
            "qty": 1,
            "unit_price": 345.76,
            "currency": "USD",
            "name_pl": "",
        }],
        operator="test",
        name_pl_lookup=None,
        desc_generate=None,
    )
    return draft


def _register(db_path, *, wfirma_id, sync_status, cache_id=None, also=None, code=CODE):
    return rdb.register_product_identity(
        db_path,
        wfirma_id=wfirma_id,
        product_code=code,
        name="Pierścionek",
        also_set_master_status=also,
        cache_kwargs=dict(
            product_code=code,
            wfirma_product_id=cache_id if cache_id is not None else wfirma_id,
            product_name_pl="Pierścionek",
            unit="szt.",
            vat_rate="23",
            sync_status=sync_status,
        ),
    )


def test_written_zero_stale_draft_converges_and_checker_clears(storage):
    _seed_pd()
    batch = storage / "outputs" / "B-AC-W0"
    batch.mkdir(parents=True)
    draft = _birth_blank(storage, batch_id="B-AC-W0")
    first = promote_pz_rows_to_product_descriptions(batch, dry_run=False)
    assert int(first.get("written") or 0) == 0
    before = evaluate_authority_consistency(storage)
    assert before["counts"][KIND_DESC_STALE] == 1
    out = promote_and_enrich_batch_drafts(
        "B-AC-W0", proforma_db=storage / "proforma_links.db",
        batch_dir=batch, operator="test",
    )
    assert int(out["promote"].get("written") or 0) == 0
    assert out["incomplete_convergence"] is False
    d = pildb.get_draft_by_id(storage / "proforma_links.db", draft.id)
    ln = json.loads(d.editable_lines_json)[0]
    assert ln["name_pl"] == CANON_PL
    assert float(ln["unit_price"]) == 345.76
    after = evaluate_authority_consistency(storage)
    assert after["counts"][KIND_DESC_STALE] == 0
    out2 = promote_and_enrich_batch_drafts(
        "B-AC-W0", proforma_db=storage / "proforma_links.db",
        batch_dir=batch, operator="test",
    )
    assert out2["incomplete_convergence"] is False
    d2 = pildb.get_draft_by_id(storage / "proforma_links.db", draft.id)
    ln2 = json.loads(d2.editable_lines_json)[0]
    assert ln2["name_pl"] == CANON_PL
    assert float(ln2["unit_price"]) == 345.76


def test_repair_fills_blank_editable_draft_not_posted(storage):
    _seed_pd()
    draft = _birth_blank(storage, batch_id="B-AC-REP", client="Kenny")
    posted, _ = pildb.auto_create_draft_from_sales_packing(
        storage / "proforma_links.db",
        batch_id="B-AC-REP",
        client_name="PostedCo",
        currency="USD",
        lines=[{
            "product_code": CODE,
            "design_no": "JR08388-0.55",
            "qty": 1,
            "unit_price": 100.0,
            "currency": "USD",
            "name_pl": "",
        }],
        operator="test",
        name_pl_lookup=None,
        desc_generate=None,
    )
    with sqlite3.connect(str(storage / "proforma_links.db")) as con:
        con.execute(
            "UPDATE proforma_drafts SET draft_state='posted' WHERE id=?",
            (posted.id,),
        )
    report = evaluate_authority_consistency(storage)
    assert report["counts"][KIND_DESC_STALE] == 1
    repaired = repair_derived_projections(storage)
    assert CODE in repaired["repaired_description_codes"]
    d = pildb.get_draft_by_id(storage / "proforma_links.db", draft.id)
    assert json.loads(d.editable_lines_json)[0]["name_pl"] == CANON_PL
    p = pildb.get_draft_by_id(storage / "proforma_links.db", posted.id)
    assert not str(json.loads(p.editable_lines_json)[0].get("name_pl") or "").strip()
    again = repair_derived_projections(storage)
    assert again["after"][KIND_DESC_STALE] == 0
    assert again["repaired_description_codes"] == []


GENERIC_PL = "Wyrób jubilerski z 14-karatowego złota (próba 585). Biżuteria do noszenia."
GENERIC_EN = "14kt gold nose pin"


def test_generic_canonical_is_invalid_authority_not_stale_and_not_repaired(storage):
    """Checker must reuse description_engine usability, not 'any non-empty text'."""
    _seed_pd(pl=GENERIC_PL, en=GENERIC_EN)
    draft = _birth_blank(storage, batch_id="B-AC-GENERIC")
    before_lines = json.loads(
        pildb.get_draft_by_id(storage / "proforma_links.db", draft.id).editable_lines_json
    )
    report = evaluate_authority_consistency(storage)
    assert report["counts"][KIND_DESC_INVALID] == 1
    assert report["counts"][KIND_DESC_STALE] == 0
    finding = next(f for f in report["findings"] if f["kind"] == KIND_DESC_INVALID)
    assert finding["class"] == BLOCKED
    assert finding["product_code"] == CODE
    repaired = repair_derived_projections(storage, product_codes=[CODE], draft_ids=[draft.id])
    assert repaired["repaired_description_codes"] == []
    assert any(
        s.get("kind") == KIND_DESC_INVALID
        or s.get("reason") == "not repairable_projection"
        for s in repaired["skipped"]
    )
    after_lines = json.loads(
        pildb.get_draft_by_id(storage / "proforma_links.db", draft.id).editable_lines_json
    )
    assert after_lines[0]["name_pl"] == before_lines[0]["name_pl"]
    assert float(after_lines[0]["qty"]) == 1
    assert float(after_lines[0]["unit_price"]) == 345.76
    assert after_lines[0]["product_code"] == CODE
    assert after_lines[0]["currency"] == "USD"
    again = evaluate_authority_consistency(storage)
    assert again["counts"][KIND_DESC_INVALID] == 1
    assert again["counts"][KIND_DESC_STALE] == 0


def test_valid_replacement_makes_blank_drafts_repairable_without_mutating_qty_price(storage):
    _seed_pd(pl=GENERIC_PL, en=GENERIC_EN)
    d1 = _birth_blank(storage, batch_id="B-AC-56", client="Monodija A")
    d2 = _birth_blank(storage, batch_id="B-AC-58", client="Monodija B")
    blocked = evaluate_authority_consistency(storage)
    assert blocked["counts"][KIND_DESC_INVALID] == 1
    assert blocked["counts"][KIND_DESC_STALE] == 0
    assert repair_derived_projections(
        storage, product_codes=[CODE], draft_ids=[d1.id, d2.id],
    )["repaired_description_codes"] == []

    _seed_pd(pl=CANON_PL, en=CANON_EN)
    eligible = evaluate_authority_consistency(storage)
    assert eligible["counts"][KIND_DESC_INVALID] == 0
    assert eligible["counts"][KIND_DESC_STALE] == 2
    repaired = repair_derived_projections(
        storage, product_codes=[CODE], draft_ids=[d1.id, d2.id],
    )
    assert CODE in repaired["repaired_description_codes"]
    for draft in (d1, d2):
        ln = json.loads(
            pildb.get_draft_by_id(storage / "proforma_links.db", draft.id).editable_lines_json
        )[0]
        assert ln["name_pl"] == CANON_PL
        assert float(ln["qty"]) == 1
        assert float(ln["unit_price"]) == 345.76
        assert ln["product_code"] == CODE
        assert ln["currency"] == "USD"
    after = evaluate_authority_consistency(storage)
    assert after["counts"][KIND_DESC_STALE] == 0
    assert after["counts"][KIND_DESC_INVALID] == 0


def test_mapping_stale_repair_and_idempotent(storage):
    db = storage / "reservation_queue.db"
    rdb.upsert_product_master(db, CODE, "D-AC")
    rdb.set_product_master_status(db, CODE, "mapping_required")
    _register(db, wfirma_id=WFID, sync_status="matched")
    rdb.set_product_master_status(db, CODE, "mapping_required")
    report = evaluate_authority_consistency(storage)
    assert report["counts"][KIND_MAP_STALE] == 1
    assert report["findings"][0]["class"] == REPAIRABLE
    repaired = repair_derived_projections(storage)
    assert CODE in repaired["repaired_mapping_codes"]
    assert rdb.get_product_master(db, CODE)["status"] == "mapped"
    again = repair_derived_projections(storage)
    assert again["after"][KIND_MAP_STALE] == 0
    assert again["repaired_mapping_codes"] == []
    assert rdb.get_product_master(db, CODE)["status"] == "mapped"


def test_pending_and_mismatch_never_project_mapped(storage):
    db = storage / "reservation_queue.db"
    rdb.upsert_product_master(db, CODE, "D-AC")
    rdb.set_product_master_status(db, CODE, "mapping_required")
    _register(db, wfirma_id=WFID, sync_status="pending")
    assert rdb.get_product_master(db, CODE)["status"] == "mapping_required"
    report = evaluate_authority_consistency(storage)
    assert report["counts"][KIND_MAP_STALE] == 0
    assert report["counts"][KIND_MAP_CONFLICT] == 0

    code2 = "EJL/26-27/AC-2"
    rdb.upsert_product_master(db, code2, "D-AC2")
    rdb.set_product_master_status(db, code2, "mapping_required")
    _register(db, wfirma_id="51677347", sync_status="matched", cache_id="999", code=code2)
    assert rdb.get_product_master(db, code2)["status"] == "mapping_required"

    # Checker must not treat mirror/cache disagreement as repairable projection.
    rdb.upsert_product_mirror(db, wfirma_id="51677411", product_code="EJL/26-27/AC-3")
    rdb.upsert_product_master(db, "EJL/26-27/AC-3", "D-AC3")
    rdb.set_product_master_status(db, "EJL/26-27/AC-3", "mapping_required")
    wfdb.upsert_product(
        product_code="EJL/26-27/AC-3",
        wfirma_product_id="999",
        product_name_pl="x",
        unit="szt.",
        vat_rate="23",
        sync_status="matched",
    )
    report2 = evaluate_authority_consistency(storage)
    stale = {
        f["product_code"] for f in report2["findings"] if f["kind"] == KIND_MAP_STALE
    }
    assert "EJL/26-27/AC-3" not in stale
    assert CODE not in stale
    repaired = repair_derived_projections(storage)
    assert "EJL/26-27/AC-3" not in repaired["repaired_mapping_codes"]
    assert rdb.get_product_master(db, "EJL/26-27/AC-3")["status"] == "mapping_required"


def test_missing_master_row_is_not_inserted_by_repair(storage):
    db = storage / "reservation_queue.db"
    rdb.upsert_product_mirror(db, wfirma_id=WFID, product_code=CODE)
    wfdb.upsert_product(
        product_code=CODE,
        wfirma_product_id=WFID,
        product_name_pl="Pierścionek",
        unit="szt.",
        vat_rate="23",
        sync_status="matched",
    )
    assert rdb.get_product_master(db, CODE) is None
    report = evaluate_authority_consistency(storage)
    assert report["counts"][KIND_MAP_STALE] == 1
    repaired = repair_derived_projections(storage)
    assert repaired["repaired_mapping_codes"] == []
    assert rdb.get_product_master(db, CODE) is None
    assert any(
        s.get("class") == "blocked_authority_missing"
        or str(s.get("reason") or "").startswith("product_master row missing")
        or s.get("reason") == "not repairable_projection"
        for s in repaired["skipped"]
    )


def test_freight_insurance_missing_master_never_created_via_endpoint(storage):
    """Hard pin: freight/insurance-style cache matches must not mint Product Master."""
    db = storage / "reservation_queue.db"
    for code, wid in (("freight", "13002743"), ("insurance", "13102217")):
        rdb.upsert_product_mirror(db, wfirma_id=wid, product_code=code)
        wfdb.upsert_product(
            product_code=code,
            wfirma_product_id=wid,
            product_name_pl=code,
            unit="szt.",
            vat_rate="23",
            sync_status="matched",
        )
        assert rdb.get_product_master(db, code) is None
    client = TestClient(app)
    before_count = client.get("/api/v1/debug/authority-consistency").json()["counts"]
    assert before_count["mapping_master_missing"] >= 2
    r = client.post(
        "/api/v1/debug/repair-derived-projections",
        json={"product_codes": ["freight", "insurance"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repaired_mapping_codes"] == []
    assert body["wfirma_writes"] is False
    assert rdb.get_product_master(db, "freight") is None
    assert rdb.get_product_master(db, "insurance") is None
    after_count = client.get("/api/v1/debug/authority-consistency").json()["counts"]
    assert after_count["mapping_master_missing"] == before_count["mapping_master_missing"]


def test_scoped_repair_touches_only_named_existing_master(storage):
    db = storage / "reservation_queue.db"
    keep = "EJL/26-27/AC-KEEP"
    for code, wid in ((CODE, WFID), (keep, "51677347")):
        rdb.upsert_product_master(db, code, "D")
        rdb.set_product_master_status(db, code, "mapping_required")
        _register(db, wfirma_id=wid, sync_status="matched", code=code)
        rdb.set_product_master_status(db, code, "mapping_required")
    out = repair_derived_projections(storage, product_codes=[CODE])
    assert CODE in out["repaired_mapping_codes"]
    assert keep not in out["repaired_mapping_codes"]
    assert rdb.get_product_master(db, CODE)["status"] == "mapped"
    assert rdb.get_product_master(db, keep)["status"] == "mapping_required"


def test_mapped_without_canonical_match_is_conflict_not_repaired(storage):
    db = storage / "reservation_queue.db"
    rdb.upsert_product_master(db, CODE, "D-AC")
    rdb.set_product_master_status(db, CODE, "mapped")
    report = evaluate_authority_consistency(storage)
    assert report["counts"][KIND_MAP_CONFLICT] == 1
    assert report["findings"][0]["class"] == CONFLICT
    repaired = repair_derived_projections(storage)
    assert repaired["repaired_mapping_codes"] == []
    assert rdb.get_product_master(db, CODE)["status"] == "mapped"
    assert repaired["after"][KIND_MAP_CONFLICT] == 1


def test_register_matched_sets_incomplete_convergence_false(storage):
    db = storage / "reservation_queue.db"
    rdb.upsert_product_master(db, CODE, "D-AC")
    rdb.set_product_master_status(db, CODE, "mapping_required")
    out = _register(db, wfirma_id=WFID, sync_status="matched")
    assert out.get("incomplete_convergence") is False
    assert out.get("master_status") == "mapped"
    assert rdb.get_product_master(db, CODE)["status"] == "mapped"


def test_create_and_adopt_http_projects_mapped(storage, monkeypatch):
    db = storage / "reservation_queue.db"
    rdb.upsert_product_master(db, CODE, "D-AC")
    rdb.set_product_master_status(db, CODE, "mapping_required")
    monkeypatch.setattr(settings, "wfirma_create_product_allowed", True, raising=False)
    from app.services import description_engine as deng
    from app.services import wfirma_client as wc

    monkeypatch.setattr(wc, "get_product_by_code", lambda code: None)
    monkeypatch.setattr(wc, "find_vat_code_id", lambda rate: "222")
    monkeypatch.setattr(
        deng, "get_description_block",
        lambda **kw: {
            "name_pl": "Pierścionek",
            "description_line": "Pierścionek / RING",
            "description_block": "block",
        },
    )
    monkeypatch.setattr(
        wc, "create_product",
        lambda **kw: _WFStub(wfirma_id=WFID, code=CODE),
    )
    r = TestClient(app).post(
        f"/api/v1/wfirma/goods/create-and-adopt/{CODE}",
        json={"item_type": "", "description_en": "RING"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("incomplete_convergence") is False
    assert rdb.get_product_master(db, CODE)["status"] == "mapped"


def test_adopt_http_projects_mapped(storage, monkeypatch):
    db = storage / "reservation_queue.db"
    rdb.upsert_product_master(db, CODE, "D-AC")
    rdb.set_product_master_status(db, CODE, "mapping_required")
    from app.services import wfirma_client as wc

    monkeypatch.setattr(
        wc, "get_product_by_code",
        lambda code: _WFStub(wfirma_id=WFID, code=CODE),
    )
    r = TestClient(app).post(f"/api/v1/wfirma/goods/adopt/{CODE}")
    assert r.status_code == 200, r.text
    assert r.json().get("incomplete_convergence") is False
    assert rdb.get_product_master(db, CODE)["status"] == "mapped"


def test_update_and_adopt_http_projects_mapped(storage, monkeypatch):
    db = storage / "reservation_queue.db"
    rdb.upsert_product_master(db, CODE, "D-AC")
    rdb.set_product_master_status(db, CODE, "mapping_required")
    monkeypatch.setattr(settings, "wfirma_edit_product_allowed", True, raising=False)
    from app.services import wfirma_client as wc

    monkeypatch.setattr(
        wc, "get_product_by_code",
        lambda code: _WFStub(wfirma_id=WFID, name="Old", code=CODE),
    )
    monkeypatch.setattr(
        wc, "edit_product",
        lambda wfirma_product_id, **kw: {
            "wfirma_id": wfirma_product_id,
            "name": kw.get("name") or "Old",
            "code": CODE,
            "unit": "szt.",
        },
    )
    r = TestClient(app).post(
        f"/api/v1/wfirma/goods/update-and-adopt/{CODE}",
        json={"name": "Updated name"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("incomplete_convergence") is False
    assert rdb.get_product_master(db, CODE)["status"] == "mapped"


def test_warehouse_module_enabled_missing_id_is_blocked_finding(storage, monkeypatch):
    monkeypatch.setattr(settings, "wfirma_warehouse_id", "", raising=False)
    monkeypatch.setattr(settings, "wfirma_warehouse_module_enabled", True, raising=False)
    report = evaluate_authority_consistency(storage)
    assert report["counts"][KIND_WAREHOUSE] == 1
    assert report["findings"][-1]["class"] == "blocked_authority_missing"
    with pytest.raises(ValueError, match="warehouse"):
        create_product(CODE, "Name")
    repaired = repair_derived_projections(storage)
    assert repaired["after"][KIND_WAREHOUSE] == 1
    assert all(s["kind"] == KIND_WAREHOUSE for s in repaired["skipped"])


def test_create_xml_never_regrows_warehouse_type_simple():
    xml = _build_create_product_xml(
        product_code=CODE,
        name="Pierścionek",
        unit="szt.",
        netto=0.0,
        vat_code_id="222",
        description="locked",
        warehouse_id="347088",
    )
    assert "<warehouse_type>" not in xml
    assert "simple" not in xml
    emitted = inspect.getsource(_build_create_product_xml).split("return f", 1)[1]
    assert "<warehouse_type>" not in emitted


def test_debug_consistency_endpoint_and_repair(storage):
    _seed_pd()
    _birth_blank(storage, batch_id="B-AC-HTTP")
    client = TestClient(app)
    g = client.get("/api/v1/debug/authority-consistency")
    assert g.status_code == 200, g.text
    body = g.json()
    assert "findings" not in body
    assert body["counts"][KIND_DESC_STALE] == 1
    p = client.post("/api/v1/debug/repair-derived-projections")
    assert p.status_code == 200, p.text
    repaired = p.json()
    assert repaired["wfirma_writes"] is False
    assert repaired["descriptions_mutated"] is False
    assert repaired["posted_drafts_touched"] is False
    assert CODE in repaired["repaired_description_codes"]
    g2 = client.get("/api/v1/debug/authority-consistency")
    assert g2.json()["counts"][KIND_DESC_STALE] == 0


def test_repair_source_never_writes_wfirma_or_descriptions():
    src = (
        Path(__file__).resolve().parent.parent
        / "app" / "services" / "authority_consistency.py"
    ).read_text(encoding="utf-8")
    assert "create_product(" not in src
    assert "edit_product(" not in src
    assert "upsert_product_description" not in src
    assert "goods/add" not in src


def test_checker_and_projection_share_validate_product_description_row():
    """Checker must not fork a second generic-token rule; projection already uses this."""
    root = Path(__file__).resolve().parent.parent / "app" / "services"
    checker = (root / "authority_consistency.py").read_text(encoding="utf-8")
    projection = (root / "proforma_invoice_link_db.py").read_text(encoding="utf-8")
    engine = (root / "description_engine.py").read_text(encoding="utf-8")
    assert "from .description_engine import validate_product_description_row" in checker
    assert checker.count("validate_product_description_row") >= 3
    assert "FORBIDDEN_DESC_TOKENS" not in checker
    assert "Wyrób jubilerski" not in checker
    assert "def validate_product_description_row(" in engine
    assert "validate_product_description_row" in projection
