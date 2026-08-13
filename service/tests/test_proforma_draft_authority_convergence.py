"""Permanent pins: new batch → draft converges commercial authorities.

Proves (without inventing values):
  * sales matcher product_codes persist before draft birth/reset
  * promote from audit.rows stamps when pz_rows.json is absent
  * intake enrich fills name_pl after birth / on stale blank drafts
  * readiness messages distinguish description vs price vs wFirma mapping
  * valid sales rows are not dropped when invoice-scoped lot pairing works
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.services import document_db as ddb
from app.services import packing_db as pdb
from app.services import proforma_invoice_link_db as pildb
from app.services.commercial_authority import (
    converge_batch_draft_authority,
    persist_matched_sales_product_codes,
    promote_and_enrich_batch_drafts,
)
from app.services.description_engine import promote_pz_rows_to_product_descriptions


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    return tmp_path


def _seed_purchase_lots(storage: Path, batch_id: str, lots: List[Dict[str, Any]]):
    with sqlite3.connect(str(storage / "packing.db")) as con:
        for lot in lots:
            con.execute(
                """INSERT INTO packing_lines
                   (id, packing_document_id, batch_id, product_code, design_no,
                    quantity, invoice_no, invoice_line_position,
                    unit_price, unit_price_eur, metal, karat, metal_color,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), "pdoc", batch_id,
                    lot["product_code"], lot["design_no"],
                    float(lot.get("quantity", 1)),
                    lot.get("invoice_no", "EJL/26-27/492"),
                    1,
                    float(lot["unit_price"]),
                    0.0,
                    lot.get("metal", "14KT/Y"),
                    lot.get("karat", "14KT"),
                    lot.get("metal_color", "Y"),
                    "2026-01-01T00:00:00",
                    "2026-01-01T00:00:00",
                ),
            )


def _seed_sales_rows(batch_id: str, rows: List[Dict[str, Any]]) -> str:
    sd = str(uuid.uuid4()).replace("-", "")[:32]
    ddb.ensure_sales_document_id(
        batch_id, sd, document_type="sales_packing_list",
        source_file_path="t.xlsx",
    )
    # ensure_sales_document_id may not set client — use replace path
    line_records = []
    for r in rows:
        line_records.append({
            "client_name": r.get("client_name", "Client A"),
            "product_code": r.get("product_code", ""),
            "design_no": r["design_no"],
            "quantity": float(r.get("quantity", 1)),
            "unit_price": float(r["unit_price"]),
            "currency": "USD",
            "total_value": float(r["unit_price"]),
            "invoice_no": r.get("invoice_no", "EJL/26-27/492"),
            "metal": r.get("metal", "14KT/Y"),
            "metal_color": r.get("metal_color", "Y"),
            "karat": "14KT",
            "client_po": r.get("client_po", "PO1"),
        })
    ddb.replace_sales_packing_lines(sd, batch_id, line_records)
    # stamp client_name on sales_documents
    with sqlite3.connect(str(ddb._db_path)) as con:
        con.execute(
            "UPDATE sales_documents SET client_name=? WHERE id=?",
            ("Client A", sd),
        )
    return sd


class TestPersistMatchedSalesProductCodes:
    def test_jr00819_class_multi_lot_persists(self, storage):
        bid = "B-JR-01"
        _seed_purchase_lots(storage, bid, [
            {"product_code": "EJL/26-27/492-2", "design_no": "JR00819",
             "unit_price": 221.0},
            {"product_code": "EJL/26-27/492-1", "design_no": "JR00819",
             "unit_price": 230.0},
            {"product_code": "EJL/26-27/492-1", "design_no": "JR00819",
             "unit_price": 228.0},
            {"product_code": "EJL/26-27/492-1", "design_no": "JR00819",
             "unit_price": 222.0},
        ])
        _seed_sales_rows(bid, [
            {"design_no": "JR00819", "unit_price": 243.0},
            {"design_no": "JR00819", "unit_price": 253.0},
            {"design_no": "JR00819", "unit_price": 250.0},
            {"design_no": "JR00819", "unit_price": 244.0},
        ])
        out = persist_matched_sales_product_codes(bid)
        assert out["updated"] == 4
        rows = ddb.get_sales_packing_lines(bid)
        assert all(str(r.get("product_code") or "").strip() for r in rows)
        assert {r["product_code"] for r in rows} == {
            "EJL/26-27/492-1", "EJL/26-27/492-2",
        }


class TestPromoteFromAuditWhenNoPzRows:
    def test_audit_authoritative_stamps_overwrite_auto_generic(self, storage):
        bid = "B-DESC-01"
        batch = storage / "outputs" / bid
        batch.mkdir(parents=True)
        # Poisoned auto generic (would be rejected at birth).
        ddb.upsert_product_description(
            product_code="EJL/26-27/492-1",
            item_type="RING",
            name_pl="Wyrób jubilerski",
            description_pl="Wyrób jubilerski — wyrób jubilerski do noszenia.",
            description_en="Jewellery",
            material_pl="",
            purpose_pl="",
            description_block="x",
            description_line="x",
            source="auto",
        )
        (batch / "audit.json").write_text(json.dumps({
            "batch_id": bid,
            "rows": [{
                "product_code": "EJL/26-27/492-1",
                "description": "PCS, 14KT Gold,Stud Jewelry DIA&CLS RING",
                "item_type": "RING",
                "_resolved_description_pl": (
                    "Pierścionek z 14-karatowego złota (próba 585) "
                    "wysadzany diamentami. Biżuteria do noszenia."
                ),
                "_resolved_name_pl": "Pierścionek",
                "_resolved_description_en": "",
                "_desc_authoritative": True,
            }],
        }), encoding="utf-8")
        # No pz_rows.json — promote must use audit stamps.
        result = promote_pz_rows_to_product_descriptions(batch, dry_run=False)
        assert result["written"] == 1
        assert result["source_file"] == "audit.json"
        row = ddb.get_product_description("EJL/26-27/492-1")
        assert row["source"] == "pz_rows"
        assert row["description_pl"].startswith("Pierścionek z 14-karatowego")


class TestConvergeEndToEnd:
    def test_new_batch_draft_gets_pc_and_name_pl(self, storage):
        bid = "B-CONV-01"
        _seed_purchase_lots(storage, bid, [
            {"product_code": "EJL/26-27/492-2", "design_no": "JR00819",
             "unit_price": 221.0},
            {"product_code": "EJL/26-27/492-1", "design_no": "JR00819",
             "unit_price": 230.0},
        ])
        _seed_sales_rows(bid, [
            {"design_no": "JR00819", "unit_price": 243.0},
            {"design_no": "JR00819", "unit_price": 253.0},
        ])
        batch = storage / "outputs" / bid
        batch.mkdir(parents=True)
        (batch / "audit.json").write_text(json.dumps({
            "rows": [
                {
                    "product_code": "EJL/26-27/492-1",
                    "description": "14KT Gold RING",
                    "_resolved_description_pl": (
                        "Pierścionek z 14-karatowego złota (próba 585)."
                    ),
                    "_resolved_name_pl": "Pierścionek",
                    "_desc_authoritative": True,
                    "item_type": "RING",
                },
                {
                    "product_code": "EJL/26-27/492-2",
                    "description": "14KT Gold LGD RING",
                    "_resolved_description_pl": (
                        "Pierścionek z 14-karatowego złota z diamentami "
                        "laboratoryjnymi."
                    ),
                    "_resolved_name_pl": "Pierścionek",
                    "_desc_authoritative": True,
                    "item_type": "RING",
                },
            ],
        }), encoding="utf-8")

        # Birth a thin draft (empty PC rows would be skipped — simulate
        # pre-converge birth with one resolved line, then converge).
        draft, _ = pildb.auto_create_draft_from_sales_packing(
            storage / "proforma_links.db",
            batch_id=bid,
            client_name="Client A",
            currency="USD",
            lines=[{
                "product_code": "EJL/26-27/492-1",
                "design_no": "JR00819",
                "qty": 1,
                "unit_price": 253.0,
                "currency": "USD",
            }],
            operator="test",
            name_pl_lookup=ddb.get_product_description,
        )
        assert draft is not None

        out = converge_batch_draft_authority(
            bid,
            proforma_db=storage / "proforma_links.db",
            operator="test",
            reset_editable=True,
        )
        assert out["product_codes"]["updated"] >= 1
        assert int(out["descriptions"]["promote"]["written"] or 0) >= 1

        d = pildb.get_draft_by_id(storage / "proforma_links.db", draft.id)
        lines = json.loads(d.editable_lines_json or "[]")
        assert len(lines) >= 2, "dropped JR00819 sales rows must re-enter"
        assert all(str(ln.get("product_code") or "").strip() for ln in lines)
        assert any(str(ln.get("name_pl") or "").strip() for ln in lines)


class TestReadinessMessageAuthority:
    def test_blank_name_pl_not_sales_price_hint(self):
        from app.api.routes_proforma import _repair_hint_for_blocker
        hint = _repair_hint_for_blocker(
            "Approval blocked: 3 line(s) have blank commercial description (name_pl)."
        )
        assert "sales price" not in hint.lower() or "not a sales-price" in hint.lower()
        assert "product_descriptions" in hint or "Promote" in hint

    def test_wfirma_hint_points_at_auto_register(self):
        from app.api.routes_proforma import _repair_hint_for_blocker
        hint = _repair_hint_for_blocker(
            "2 product(s) not matched in wfirma_products (missing wfirma_product_id): X"
        )
        assert "auto-register" in hint
        assert "invent" in hint.lower()

    def test_preflight_blank_desc_mentions_promote_not_prices(self, storage):
        from app.api import routes_proforma as rp
        draft, _ = pildb.auto_create_draft_from_sales_packing(
            storage / "proforma_links.db",
            batch_id="B-PF-01",
            client_name="Client A",
            currency="EUR",
            lines=[{
                "product_code": "EJL/X",
                "design_no": "D1",
                "qty": 1,
                "unit_price": 10.0,
                "currency": "EUR",
                "name_pl": "",
            }],
            operator="test",
        )
        err = rp._preflight_approve(storage / "proforma_links.db", draft.id)
        assert err is not None
        assert "name_pl" in err
        assert "Import sales prices first" not in err
        assert "product_descriptions" in err or "Promote" in err


# Canonical bilingual text used by the written==0 / stale-draft pins.
# Must be long enough to pass the generic/forbidden-token policy.
_CANON_PL = (
    "Pierścionek z 14-karatowego złota (próba 585) "
    "wysadzany diamentami laboratoryjnymi. Biżuteria do noszenia."
)
_CANON_EN = "Lab Grown Diamond Studded 14KT Gold Jewellery RING"
_CANON_PL_EAR = (
    "Kolczyki z 9-karatowego złota (próba 375) "
    "wysadzane diamentami laboratoryjnymi. Biżuteria do noszenia."
)
_CANON_EN_EAR = "Lab Grown Diamond Studded 9KT Gold Jewellery EARRINGS"


def _seed_pd(product_code: str, *, pl: str = _CANON_PL, en: str = _CANON_EN,
             source: str = "pz_rows", item_type: str = "RING"):
    ddb.upsert_product_description(
        product_code=product_code,
        item_type=item_type,
        name_pl=pl,
        description_pl=pl,
        description_en=en,
        material_pl="",
        purpose_pl="Ozdoba — biżuteria do noszenia.",
        description_block=f"{pl} / {en}",
        description_line=pl,
        source=source,
    )


def _birth_blank(storage: Path, *, batch_id: str, client: str, lines: List[Dict[str, Any]]):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        storage / "proforma_links.db",
        batch_id=batch_id,
        client_name=client,
        currency="USD",
        lines=lines,
        operator="test",
        name_pl_lookup=None,
        desc_generate=None,
    )
    return draft


def _lines(draft) -> List[Dict[str, Any]]:
    return json.loads(draft.editable_lines_json or "[]") or []


class TestWrittenZeroStillEnrichesStaleDraft:
    """PD already present + blank editable draft + promote written==0 must still fill."""

    def test_written_zero_fills_blank_name_pl_and_is_idempotent(self, storage):
        bid = "B-W0-01"
        pc = "EJL/26-27/522-1"
        _seed_pd(pc)
        batch = storage / "outputs" / bid
        batch.mkdir(parents=True)
        # No pz_rows / audit stamps: promote writes 0, PD already holds authority.

        draft = _birth_blank(storage, batch_id=bid, client="Kenny", lines=[{
            "product_code": pc,
            "design_no": "JR08388-0.55",
            "qty": 1,
            "unit_price": 345.76,
            "currency": "USD",
            "name_pl": "",
        }])
        assert not str(_lines(draft)[0].get("name_pl") or "").strip()

        first = promote_pz_rows_to_product_descriptions(batch, dry_run=False)
        assert int(first.get("written") or 0) == 0

        out = promote_and_enrich_batch_drafts(
            bid, proforma_db=storage / "proforma_links.db",
            batch_dir=batch, operator="test",
        )
        assert int(out["promote"].get("written") or 0) == 0
        assert out["drafts_enriched"] == 1
        assert out["incomplete_convergence"] is False

        d1 = pildb.get_draft_by_id(storage / "proforma_links.db", draft.id)
        ln = _lines(d1)[0]
        assert ln["name_pl"] == _CANON_PL
        assert ln["qty"] == 1
        assert float(ln["unit_price"]) == 345.76
        assert ln["currency"] == "USD"
        assert ln["product_code"] == pc
        assert "Wyrób jubilerski" not in (ln["name_pl"] or "")

        snap = d1.editable_lines_json
        out2 = promote_and_enrich_batch_drafts(
            bid, proforma_db=storage / "proforma_links.db",
            batch_dir=batch, operator="test",
        )
        assert int(out2["promote"].get("written") or 0) == 0
        d2 = pildb.get_draft_by_id(storage / "proforma_links.db", draft.id)
        ln2 = _lines(d2)[0]
        assert ln2["name_pl"] == _CANON_PL
        assert float(ln2["unit_price"]) == 345.76
        assert ln2["qty"] == 1
        assert json.loads(d2.editable_lines_json)[0]["product_code"] == pc
        # Second pass must not rewrite commercial values.
        assert _lines(d2)[0]["name_pl"] == json.loads(snap)[0]["name_pl"]

    def test_multi_draft_same_pc_locked_and_manual_protected(self, storage):
        bid = "B-W0-MULTI"
        pc_ring = "EJL/26-27/522-1"
        pc_ear = "EJL/26-27/522-3"
        pc_manual = "EJL/26-27/522-2"
        _seed_pd(pc_ring)
        _seed_pd(pc_ear, pl=_CANON_PL_EAR, en=_CANON_EN_EAR, item_type="EARRINGS")
        _seed_pd(
            pc_manual,
            pl="Operator-locked pierścionek z 18-karatowego złota (próba 750).",
            en="Operator EN RING",
            source="manual",
        )
        batch = storage / "outputs" / bid
        batch.mkdir(parents=True)
        # Conflicting pz_rows must not clobber the manual PD row.
        (batch / "pz_rows.json").write_text(json.dumps([
            {"product_code": pc_manual,
             "nazwa_pl": "MUST-NOT-REPLACE pierścionek ze złota próby 14 karatów",
             "nazwa_en": "MUST-NOT-REPLACE EN", "item_type": "RING"},
        ]), encoding="utf-8")

        editable_a = _birth_blank(storage, batch_id=bid, client="Omara", lines=[{
            "product_code": pc_ring, "design_no": "JR08388-0.55",
            "qty": 1, "unit_price": 100.0, "currency": "USD", "name_pl": "",
        }])
        # Draft-87 shape: one draft, same purchase code on distinct sales designs.
        editable_b = _birth_blank(storage, batch_id=bid, client="Kenny", lines=[
            {"product_code": pc_ear, "design_no": "JE02058-0.50",
             "qty": 1, "unit_price": 99.52, "currency": "USD", "name_pl": ""},
            {"product_code": pc_ear, "design_no": "JE02058-1.00",
             "qty": 3, "unit_price": 140.56, "currency": "USD", "name_pl": ""},
            {"product_code": pc_ear, "design_no": "J4506E00545-1.0",
             "qty": 2, "unit_price": 176.47, "currency": "USD", "name_pl": ""},
        ])
        manual_draft = _birth_blank(storage, batch_id=bid, client="Verhoeven", lines=[{
            "product_code": pc_manual, "design_no": "J3403R02044",
            "qty": 1, "unit_price": 1285.58, "currency": "USD", "name_pl": "",
        }])
        posted, _ = pildb.auto_create_draft_from_sales_packing(
            storage / "proforma_links.db",
            batch_id=bid, client_name="Posted Client", currency="USD",
            lines=[{"product_code": pc_ring, "design_no": "LOCKED",
                    "qty": 1, "unit_price": 10.0, "currency": "USD",
                    "name_pl": "STALE_POSTED"}],
            operator="test", name_pl_lookup=None, desc_generate=None,
        )
        with sqlite3.connect(str(storage / "proforma_links.db")) as con:
            con.execute(
                "UPDATE proforma_drafts SET draft_state='posted', status='issued' "
                "WHERE id=?",
                (posted.id,),
            )

        promo = promote_pz_rows_to_product_descriptions(batch, dry_run=False)
        assert int(promo.get("written") or 0) == 0
        assert int(promo.get("skipped_manual") or 0) >= 1
        assert ddb.get_product_description(pc_manual)["source"] == "manual"
        assert ddb.get_product_description(pc_manual)["description_pl"].startswith(
            "Operator-locked"
        )

        out = promote_and_enrich_batch_drafts(
            bid, proforma_db=storage / "proforma_links.db",
            batch_dir=batch, operator="test",
        )
        assert out["drafts_locked_skipped"] >= 1

        a = _lines(pildb.get_draft_by_id(storage / "proforma_links.db", editable_a.id))
        assert a[0]["name_pl"] == _CANON_PL
        assert float(a[0]["unit_price"]) == 100.0

        b = _lines(pildb.get_draft_by_id(storage / "proforma_links.db", editable_b.id))
        assert len(b) == 3
        assert [ln["design_no"] for ln in b] == [
            "JE02058-0.50", "JE02058-1.00", "J4506E00545-1.0",
        ]
        assert [ln["qty"] for ln in b] == [1, 3, 2]
        assert [float(ln["unit_price"]) for ln in b] == [99.52, 140.56, 176.47]
        assert all(ln["name_pl"] == _CANON_PL_EAR for ln in b)
        assert all(ln["product_code"] == pc_ear for ln in b)

        m = _lines(pildb.get_draft_by_id(storage / "proforma_links.db", manual_draft.id))
        assert m[0]["name_pl"].startswith("Operator-locked")
        assert "MUST-NOT-REPLACE" not in (m[0]["name_pl"] or "")

        p = _lines(pildb.get_draft_by_id(storage / "proforma_links.db", posted.id))
        assert p[0]["name_pl"] == "STALE_POSTED"

    def test_audit_stamps_after_blank_birth_converge(self, storage):
        """84–88 lifecycle: drafts born before PD; later audit stamps must fill."""
        bid = "B-LIFECYCLE-01"
        pc = "EJL/26-27/519-1"
        draft = _birth_blank(storage, batch_id=bid, client="Omara", lines=[{
            "product_code": pc, "design_no": "CSTR08282",
            "qty": 1, "unit_price": 374.0, "currency": "EUR", "name_pl": "",
        }])
        assert not str(_lines(draft)[0].get("name_pl") or "").strip()
        assert ddb.get_product_description(pc) is None

        batch = storage / "outputs" / bid
        batch.mkdir(parents=True)
        (batch / "audit.json").write_text(json.dumps({
            "batch_id": bid,
            "rows": [{
                "product_code": pc,
                "description": "PCS, 14KT Gold,LGD Gold Stud Jewell RING",
                "item_type": "RING",
                "_resolved_description_pl": _CANON_PL,
                "_resolved_name_pl": "Pierścionek",
                "_resolved_description_en": _CANON_EN,
                "_desc_authoritative": True,
            }],
        }), encoding="utf-8")

        out = promote_and_enrich_batch_drafts(
            bid, proforma_db=storage / "proforma_links.db",
            batch_dir=batch, operator="description-ready",
        )
        assert int(out["promote"].get("written") or 0) == 1
        d = pildb.get_draft_by_id(storage / "proforma_links.db", draft.id)
        ln = _lines(d)[0]
        assert ln["name_pl"] == _CANON_PL
        assert float(ln["unit_price"]) == 374.0
        assert ln["design_no"] == "CSTR08282"


class TestSinglePromoteEnrichAuthority:
    """Architecture pins: one production promote/enrich algorithm."""

    def _src(self, rel: str) -> str:
        return (
            Path(__file__).resolve().parent.parent / "app" / rel
        ).read_text(encoding="utf-8")

    def test_export_service_delegates_and_has_no_written_gt_zero_gate(self):
        src = self._src("services/export_service.py")
        assert "promote_and_enrich_batch_drafts" in src
        assert 'int(_promo_summary.get("written") or 0) > 0' not in src
        assert "enrich_draft_lines" not in src
        write_i = src.index("_write_pz_rows_json(output_dir, result)")
        promo_i = src.index("promote_and_enrich_batch_drafts")
        assert promo_i > write_i

    def test_intake_and_polish_desc_call_promote_and_enrich(self):
        intake = self._src("api/routes_intake.py")
        clearance = self._src("api/routes_dhl_clearance.py")
        packing_sync = self._src("services/proforma_draft_sync.py")
        assert "promote_and_enrich_batch_drafts" in intake
        assert "promote_and_enrich_batch_drafts" in clearance
        assert "promote_and_enrich_batch_drafts" in packing_sync

    def test_export_service_does_not_import_promote_primitive(self):
        src = self._src("services/export_service.py")
        assert "promote_pz_rows_to_product_descriptions" not in src
        assert "patch_audit_pz_description_promote" in src
        assert 'result["pz_description_promote"]' in src

    def test_no_second_production_promote_enrich_algorithm(self):
        """Only commercial_authority.py may pair promote primitive + draft enrich."""
        services = Path(__file__).resolve().parent.parent / "app" / "services"
        offenders = []
        for path in services.glob("*.py"):
            if path.name == "commercial_authority.py":
                continue
            src = path.read_text(encoding="utf-8")
            if (
                "promote_pz_rows_to_product_descriptions" in src
                and "enrich_draft_lines(" in src
            ):
                offenders.append(path.name)
        assert offenders == [], offenders

    def test_authority_consistency_is_the_only_derived_repair_entry(self):
        src = self._src("services/authority_consistency.py")
        assert "def evaluate_authority_consistency" in src
        assert "def repair_derived_projections" in src
        assert "create_product(" not in src
        debug = self._src("api/routes_debug.py")
        assert "/authority-consistency" in debug
        assert "/repair-derived-projections" in debug

