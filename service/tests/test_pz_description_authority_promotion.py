"""
test_pz_description_authority_promotion.py — PZ pz_rows is the single
commercial-description authority for proforma drafts.

Pins:
  1. promote_pz_rows_to_product_descriptions writes nazwa_pl/nazwa_en
  2. promote refuses generic placeholders
  3. promote never overwrites source='manual'
  4. birth + enrich consume promoted description_pl as name_pl
  5. drafts modelled on #76/#79/#80/#81 clear blank-name_pl after promote+enrich
  6. intake no longer wires generate_name_pl_if_sufficient
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import document_db as ddb
from app.services import proforma_invoice_link_db as pildb
from app.services.description_engine import (
    promote_pz_rows_to_product_descriptions,
    validate_product_description_row,
)


@pytest.fixture()
def docs_db(tmp_path: Path) -> Path:
    db = tmp_path / "documents.db"
    ddb.init_document_db(db)
    return db


@pytest.fixture()
def proc_db(tmp_path: Path) -> Path:
    db = tmp_path / "proforma_links.db"
    pildb.init_db(db)
    return db


def _write_pz_rows(batch_dir: Path, rows: list) -> Path:
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "pz_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )
    return batch_dir


def test_promote_writes_pz_bilingual_authority(docs_db, tmp_path):
    batch = _write_pz_rows(tmp_path / "batch", [{
        "product_code": "EJL/26-27/485-1",
        "item_type": "RING",
        "nazwa_pl": "pierścionek ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie",
        "nazwa_en": "Lab Grown Diamond Studded 14KT Gold Jewellery RING",
        "pl_desc": "pierścionek ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie",
        "description_en": "Lab Grown Diamond Studded 14KT Gold Jewellery RING",
    }])
    # Seed poisoned auto row — must be overwritten.
    ddb.upsert_product_description(
        product_code="EJL/26-27/485-1",
        item_type="RNG",
        name_pl="Wyrób jubilerski",
        description_pl="Wyrób jubilerski — wyrób jubilerski do noszenia.",
        description_en="Rng",
        material_pl="metal szlachetny",
        purpose_pl="Ozdoba",
        description_block="x",
        description_line="x",
        source="auto",
    )
    result = promote_pz_rows_to_product_descriptions(batch, dry_run=False)
    assert result["written"] == 1
    assert result["errors"] == []
    row = ddb.get_product_description("EJL/26-27/485-1")
    assert row["source"] == "pz_rows"
    assert row["description_pl"].startswith("pierścionek ze złota")
    assert "Lab Grown" in row["description_en"]
    assert "Wyrób jubilerski" not in row["description_pl"]
    v = validate_product_description_row(row)
    assert v.is_usable
    assert v.description_pl.startswith("pierścionek")


def test_promote_skips_generic_and_manual(docs_db, tmp_path):
    batch = _write_pz_rows(tmp_path / "batch", [
        {
            "product_code": "EJL/GEN",
            "nazwa_pl": "Wyrób jubilerski — wyrób jubilerski do noszenia.",
            "nazwa_en": "Jewellery",
        },
        {
            "product_code": "EJL/MAN",
            "nazwa_pl": "pierścionek srebrny próby 925",
            "nazwa_en": "Silver SL925 Jewellery RING",
        },
    ])
    ddb.upsert_product_description(
        product_code="EJL/MAN",
        item_type="RING",
        name_pl="Operator Pierścionek",
        description_pl="Operator Pierścionek srebrny",
        description_en="Operator silver ring",
        material_pl="",
        purpose_pl="",
        description_block="x",
        description_line="x",
        source="manual",
    )
    result = promote_pz_rows_to_product_descriptions(batch, dry_run=False)
    assert result["skipped_generic"] == 1
    assert result["skipped_manual"] == 1
    man = ddb.get_product_description("EJL/MAN")
    assert man["source"] == "manual"
    assert man["name_pl"] == "Operator Pierścionek"
    assert ddb.get_product_description("EJL/GEN") is None or (
        ddb.get_product_description("EJL/GEN") or {}
    ).get("source") != "pz_rows"


def test_enrich_uses_promoted_description_pl_as_name_pl(docs_db, tmp_path):
    batch = _write_pz_rows(tmp_path / "batch", [{
        "product_code": "EJL/26-27/491-3",
        "item_type": "RING",
        "nazwa_pl": "pierścionek ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie",
        "nazwa_en": "Lab Grown Diamond Studded 14KT Gold Jewellery RING",
    }])
    promote_pz_rows_to_product_descriptions(batch, dry_run=False)
    lines = [{
        "product_code": "EJL/26-27/491-3",
        "design_no": "JR08157",
        "name_pl": "",
        "name_pl_source": "missing_product_descriptions",
        "unit_price": 280.1,
    }]
    out, hit, miss = pildb.enrich_lines_from_product_descriptions(
        lines, ddb.get_product_description,
    )
    assert hit == 1 and miss == 0
    assert out[0]["name_pl"].startswith("pierścionek ze złota")
    assert out[0]["description_en"].startswith("Lab Grown")
    assert out[0]["name_pl_source"] == pildb.NAME_PL_SOURCE_PD


def test_operator_confirmed_short_name_pl_preserved_over_pz_enrich(docs_db, tmp_path):
    """Draft #76 precedence: operator short name_pl beats full PZ text on enrich.

    Blank lines receive full ``nazwa_pl``; operator-confirmed non-generic
    ``name_pl`` (``name_pl_source=operator``) must not be silently overwritten.
    """
    pc = "EJL/26-27/485-1"
    pz_pl = "pierścionek ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie"
    pz_en = "Lab Grown Diamond Studded 14KT Gold Jewellery RING"
    batch = _write_pz_rows(tmp_path / "op76", [{
        "product_code": pc,
        "item_type": "RING",
        "nazwa_pl": pz_pl,
        "nazwa_en": pz_en,
    }])
    promote_pz_rows_to_product_descriptions(batch, dry_run=False)

    operator_short = "Pierścionek"
    blank_pc = "EJL/26-27/485-3"
    blank_pl = "bransoletka srebrna próby 925"
    blank_en = "Silver SL925 Jewellery BRACELET"
    promote_pz_rows_to_product_descriptions(
        _write_pz_rows(tmp_path / "op76b", [{
            "product_code": blank_pc,
            "item_type": "BRACELET",
            "nazwa_pl": blank_pl,
            "nazwa_en": blank_en,
        }]),
        dry_run=False,
    )

    lines = [
        {
            "product_code": pc,
            "design_no": "D-OP",
            "name_pl": operator_short,
            "name_pl_source": pildb.NAME_PL_SOURCE_OPERATOR,
            "unit_price": 100.0,
        },
        {
            "product_code": blank_pc,
            "design_no": "D-BLANK",
            "name_pl": "",
            "name_pl_source": pildb.NAME_PL_SOURCE_MISSING_PD,
            "unit_price": 50.0,
        },
    ]
    out, hit, miss = pildb.enrich_lines_from_product_descriptions(
        lines, ddb.get_product_description,
    )
    by_pc = {ln["product_code"]: ln for ln in out}
    assert by_pc[pc]["name_pl"] == operator_short
    assert by_pc[pc]["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR
    assert by_pc[blank_pc]["name_pl"] == blank_pl
    assert by_pc[blank_pc]["description_en"] == blank_en
    assert by_pc[blank_pc]["name_pl_source"] == pildb.NAME_PL_SOURCE_PD
    assert hit >= 1


def test_pz_rows_equals_pd_equals_draft_and_wfirma_pl_payload(docs_db, tmp_path):
    """Chain equality: pz_rows → PD → draft name_pl; wFirma PL reads same text."""
    pc = "EJL/26-27/491-3"
    pl = "pierścionek ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie"
    en = "Lab Grown Diamond Studded 14KT Gold Jewellery RING"
    batch = _write_pz_rows(tmp_path / "chain", [{
        "product_code": pc, "item_type": "RING",
        "nazwa_pl": pl, "nazwa_en": en, "pl_desc": pl, "description_en": en,
    }])
    promote_pz_rows_to_product_descriptions(batch, dry_run=False)
    pd = ddb.get_product_description(pc)
    assert pd["source"] == "pz_rows"
    assert pd["description_pl"] == pl
    assert pd["description_en"] == en
    assert pd["name_pl"] == pl

    out, _, _ = pildb.enrich_lines_from_product_descriptions(
        [{"product_code": pc, "name_pl": "", "unit_price": 1.0}],
        ddb.get_product_description,
    )
    assert out[0]["name_pl"] == pl
    assert out[0]["description_en"] == en

    # wFirma product-create / PZ row consumers use pl_desc / description_en
    # from pz_rows (same strings promoted into PD). Equality is the contract.
    import json
    raw = json.loads((batch / "pz_rows.json").read_text(encoding="utf-8"))
    row = raw[0]
    assert row["nazwa_pl"] == pl == out[0]["name_pl"] == pd["description_pl"]
    assert row["nazwa_en"] == en == out[0]["description_en"] == pd["description_en"]


@pytest.mark.parametrize("draft_key,pcs", [
    ("76", ["EJL/26-27/485-3", "EJL/26-27/485-1", "EJL/26-27/485-10"]),
    ("79", ["EJL/26-27/488-3"]),
    ("80", ["EJL/26-27/489-1", "EJL/26-27/489-2", "EJL/26-27/489-3", "EJL/26-27/489-4"]),
    ("81", ["EJL/26-27/491-1", "EJL/26-27/491-2", "EJL/26-27/491-3", "EJL/26-27/491-4"]),
])
def test_draft_family_blank_name_pl_clears_after_promote(docs_db, proc_db, tmp_path, draft_key, pcs):
    """Model drafts #76/#79/#80/#81: blank name_pl clears once PZ authority is promoted."""
    pz_map = {
        "EJL/26-27/485-1": ("pierścionek ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie",
                            "Lab Grown Diamond Studded 14KT Gold Jewellery RING"),
        "EJL/26-27/485-3": ("bransoletka srebrna próby 925", "Silver SL925 Jewellery BRACELET"),
        "EJL/26-27/485-10": ("kolczyki ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie",
                             "Lab Grown Diamond Studded 14KT Gold Jewellery EARRINGS"),
        "EJL/26-27/488-3": ("kolczyki ze złota próby 14 karatów wysadzane diamentami",
                            "Diamond Studded 14KT Gold Jewellery EARRINGS"),
        "EJL/26-27/489-1": ("pierścionek z platyny próby 950 z diamentami hodowanymi laboratoryjnie",
                            "Lab Grown Diamond Studded PT950 Platinum Jewellery RING"),
        "EJL/26-27/489-2": ("pierścionek ze złota próby 9 karatów z diamentami hodowanymi laboratoryjnie",
                            "Lab Grown Diamond Studded 9KT Gold Jewellery RING"),
        "EJL/26-27/489-3": ("pierścionek ze złota próby 18 karatów z diamentami hodowanymi laboratoryjnie",
                            "Lab Grown Diamond Studded 18KT Gold Jewellery RING"),
        "EJL/26-27/489-4": ("pierścionek srebrny próby 925", "Silver SL925 Jewellery RING"),
        "EJL/26-27/491-1": ("pierścionek ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie",
                            "Lab Grown Diamond Studded 14KT Gold Jewellery RING"),
        "EJL/26-27/491-2": ("bransoletka ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie",
                            "Lab Grown Diamond Studded 14KT Gold Jewellery BRACELET"),
        "EJL/26-27/491-3": ("pierścionek ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie",
                            "Lab Grown Diamond Studded 14KT Gold Jewellery RING"),
        "EJL/26-27/491-4": ("kolczyki ze złota próby 14 karatów z diamentami hodowanymi laboratoryjnie",
                            "Lab Grown Diamond Studded 14KT Gold Jewellery EARRINGS"),
    }
    rows = []
    for pc in pcs:
        pl, en = pz_map[pc]
        rows.append({"product_code": pc, "nazwa_pl": pl, "nazwa_en": en, "item_type": "RING"})
        ddb.upsert_product_description(
            product_code=pc, item_type="RNG",
            name_pl="Wyrób jubilerski",
            description_pl="Wyrób jubilerski — wyrób jubilerski do noszenia.",
            description_en="Rng", material_pl="metal szlachetny", purpose_pl="x",
            description_block="x", description_line="x", source="auto",
        )
    promote_pz_rows_to_product_descriptions(
        _write_pz_rows(tmp_path / f"d{draft_key}", rows), dry_run=False,
    )

    lines = [
        {"product_code": pc, "design_no": f"D-{i}", "name_pl": "",
         "name_pl_source": "missing_product_descriptions", "unit_price": 10.0 + i}
        for i, pc in enumerate(pcs)
    ]
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        proc_db,
        batch_id=f"BATCH_DRAFT_{draft_key}",
        client_name=f"Client {draft_key}",
        currency="USD",
        lines=lines,
        operator="test",
        name_pl_lookup=ddb.get_product_description,
        desc_generate=None,
    )
    refreshed = pildb.enrich_draft_lines(
        proc_db, draft.id, "test", draft.updated_at, ddb.get_product_description,
    )
    out_lines = json.loads(refreshed.editable_lines_json or "[]")
    assert out_lines, f"draft {draft_key} has no lines"
    blank = [ln for ln in out_lines if not (ln.get("name_pl") or "").strip()]
    assert blank == [], f"draft {draft_key} still blank: {blank}"
    for ln in out_lines:
        assert "Wyrób jubilerski" not in (ln.get("name_pl") or "")
        assert ln.get("name_pl_source") == pildb.NAME_PL_SOURCE_PD


def test_intake_does_not_wire_name_pl_generator():
    src = (
        Path(__file__).resolve().parent.parent
        / "app" / "api" / "routes_intake.py"
    ).read_text(encoding="utf-8")
    assert "generate_name_pl_if_sufficient" not in src
    assert "desc_generate  = None" in src or "desc_generate=None" in src


def test_export_service_promotes_pz_rows_after_write():
    """PZ process must promote nazwa_pl/nazwa_en into product_descriptions."""
    src = (
        Path(__file__).resolve().parent.parent
        / "app" / "services" / "export_service.py"
    ).read_text(encoding="utf-8")
    assert "promote_pz_rows_to_product_descriptions" in src
    assert "_write_pz_rows_json(output_dir, result)" in src
    # promote must follow the pz_rows write in source order
    write_i = src.index("_write_pz_rows_json(output_dir, result)")
    promo_i = src.index("promote_pz_rows_to_product_descriptions")
    assert promo_i > write_i


def test_name_pl_generator_is_disabled():
    from app.api.sales_packing_parser import generate_name_pl_if_sufficient
    assert generate_name_pl_if_sufficient("RNG", "14KT", "YG", "LGD") is None
    assert generate_name_pl_if_sufficient("RING") is None
