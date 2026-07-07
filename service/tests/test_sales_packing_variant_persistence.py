"""
test_sales_packing_variant_persistence.py — Product Master Slice 2.

Pins the sales-side variant-identity persistence: the sales packing file is
parsed by the SAME rich extractor as the purchase side
(invoice_packing_extractor.extract_packing), which already emits nine variant
fields — but they were dropped at the sales_packing_lines persistence boundary
(schema/store/intake never carried them). This slice mirrors the purchase
packing_lines columns EXACTLY so a sales row carries the full variant signature
for Slice-2 exact-matching against the Product Master.

Scope (operator-approved 2026-07-06, Path B only, new/re-uploaded rows only):
  columns: item_type, karat, metal, metal_color, quality_string, stone_type,
           size, diamond_weight, color_weight
  surfaces: sales_packing_lines schema, store_sales_packing_lines,
            replace_sales_packing_lines, routes_intake line_records (both
            store + reingest mappings).

Coverage:
  1. parse-shaped dict -> persist -> readback for all 9 (real document_db,
     temp DB, no stubs — Lesson A), on BOTH write paths.
  2. missing fields default '' / 0.0 (never None / KeyError).
  3. legacy pre-fix row (the 18-column client_po/invoice_no-era INSERT) reads
     back defaults for all 9 new columns via both SELECT * readers.
  4. init ALTER is idempotent (re-init same file, no raise, data intact).
  5. drop-can't-return source pins: both INSERTs name all 9 columns and each
     INSERT's placeholder count equals its column count; the ALTER tuple
     registers all 9 mirroring purchase types.
  6. GUARDRAIL: sales never invents product_code — a blank-pc row stays blank
     even when its variant identity is fully populated.
  7. intake forwards all 9 keys on BOTH mappings (store + reingest).
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from pathlib import Path

import pytest

from app.services import document_db as ddb

_DOC_DB_SRC = Path(ddb.__file__)

# The nine variant fields, with their expected default when unset.
_TEXT_FIELDS = (
    "item_type", "karat", "metal", "metal_color",
    "quality_string", "stone_type", "size",
)
_REAL_FIELDS = ("diamond_weight", "color_weight")


@pytest.fixture()
def db(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path / "documents.db"


def _line(n: int, **overrides) -> dict:
    """Real-shaped sales line dict — mirrors the routes_intake line_records
    record (the actual producer of these rows), now carrying the extractor's
    full variant set."""
    rec = {
        "batch_id":          "BATCH_V",
        "sales_document_id": "SDOC1",
        "client_name":       "Verhoeven BV",
        "client_ref":        "VER",
        "invoice_no":        "EJL/26-27/300",
        "design_no":         f"D-{n:03}",
        "bag_id":            f"BAG-{n}",
        "product_code":      f"EJL/26-27/300-{n}",
        "quantity":          1.0,
        "unit_price":        12.5,
        "currency":          "EUR",
        "total_value":       12.5,
        "price_source":      "excel_symbol",
        "client_po":         f"PO-{n:04}",
        "remarks":           "",
        # ── variant identity ──
        "item_type":         "RNG",
        "karat":             "14KT",
        "metal":             "14KT/W",
        "metal_color":       "W",
        "quality_string":    "GH-SI1",
        "stone_type":        "DIAMOND",
        "size":              "6.5",
        "diamond_weight":    0.75,
        "color_weight":      0.20,
    }
    rec.update(overrides)
    return rec


# ── 1. parse → persist → readback (all 9, both write paths) ─────────────────

def test_store_persists_all_variant_fields(db):
    ddb.store_sales_packing_lines("SDOC1", "BATCH_V", [_line(1)])
    rows = ddb.get_sales_packing_lines("BATCH_V")
    assert len(rows) == 1
    r = rows[0]
    assert r["item_type"]      == "RNG"
    assert r["karat"]          == "14KT"
    assert r["metal"]          == "14KT/W"
    assert r["metal_color"]    == "W"
    assert r["quality_string"] == "GH-SI1"
    assert r["stone_type"]     == "DIAMOND"
    assert r["size"]           == "6.5"
    assert r["diamond_weight"] == pytest.approx(0.75)
    assert r["color_weight"]   == pytest.approx(0.20)


def test_replace_path_persists_all_variant_fields(db):
    """replace_sales_packing_lines carries its OWN copy of the INSERT — the
    fix must cover both write paths (no Logic A / Logic B)."""
    ddb.store_sales_packing_lines("SDOC1", "BATCH_V", [_line(1)])
    ddb.replace_sales_packing_lines(
        "SDOC1", "BATCH_V",
        [_line(7, stone_type="RUBY", diamond_weight=1.10, size="7")],
    )
    rows = ddb.get_sales_packing_lines("BATCH_V")
    assert len(rows) == 1
    assert rows[0]["stone_type"]     == "RUBY"
    assert rows[0]["diamond_weight"] == pytest.approx(1.10)
    assert rows[0]["size"]           == "7"


# ── 2. missing fields default to ''/0.0 (never None) ────────────────────────

def test_missing_variant_fields_default_safe(db):
    ln = _line(3)
    for f in _TEXT_FIELDS + _REAL_FIELDS:
        del ln[f]
    ddb.store_sales_packing_lines("SDOC1", "BATCH_V", [ln])
    r = ddb.get_sales_packing_lines("BATCH_V")[0]
    for f in _TEXT_FIELDS:
        assert r[f] == "", f"{f} should default to '' not {r[f]!r}"
    for f in _REAL_FIELDS:
        assert r[f] == 0.0, f"{f} should default to 0.0 not {r[f]!r}"


# ── 3. legacy pre-fix row reads back defaults via both readers ──────────────

def test_legacy_rows_read_back_defaults_never_none(db):
    """A row written by the PRE-THIS-FIX 18-column INSERT (client_po/invoice_no
    era) must read back defaults for all 9 new columns — the ALTER DEFAULTs
    backfill legacy data; no None / KeyError."""
    con = sqlite3.connect(str(db))
    con.execute(
        """INSERT INTO sales_packing_lines
           (id, batch_id, sales_document_id, client_name, client_ref,
            product_code, design_no, bag_id, quantity, remarks,
            unit_price, currency, total_value, price_source,
            client_po, invoice_no,
            client_contractor_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), "BATCH_LEGACY", "SDOC_L", "Old Client", "OLD",
         "EJL/25-26/001-1", "D-OLD", "", 1.0, "",
         0.0, "", 0.0, "", "", "", "", "2026-01-01T00:00:00+00:00"),
    )
    con.commit()
    con.close()

    for reader_rows in (
        ddb.get_sales_packing_lines("BATCH_LEGACY"),
        ddb.get_sales_packing_lines_for_document("SDOC_L"),
    ):
        assert reader_rows, "reader returned no rows"
        r = reader_rows[0]
        for f in _TEXT_FIELDS:
            assert r[f] == ""
        for f in _REAL_FIELDS:
            assert r[f] == 0.0


def test_alter_on_init_is_idempotent(db, tmp_path):
    ddb.store_sales_packing_lines("SDOC1", "BATCH_V", [_line(1)])
    ddb.init_document_db(tmp_path / "documents.db")  # re-init same file
    r = ddb.get_sales_packing_lines("BATCH_V")[0]
    assert r["stone_type"] == "DIAMOND"
    assert r["diamond_weight"] == pytest.approx(0.75)


# ── 4. GUARDRAIL: sales never invents product_code ──────────────────────────

def test_blank_product_code_stays_blank_even_with_full_variant(db):
    """Variant identity is additive — it must NEVER cause product_code to be
    minted. A row that arrives with product_code='' (matcher unresolved) stays
    '' after persistence, regardless of how complete its variant fields are."""
    ln = _line(9, product_code="")
    ddb.store_sales_packing_lines("SDOC1", "BATCH_V", [ln])
    r = ddb.get_sales_packing_lines("BATCH_V")[0]
    assert r["product_code"] == ""          # never invented
    assert r["design_no"]    == "D-009"     # design preserved
    assert r["stone_type"]   == "DIAMOND"   # variant persisted


# ── 5. drop-can't-return source pins (both INSERTs) ─────────────────────────

_VARIANT_COLS = list(_TEXT_FIELDS) + list(_REAL_FIELDS)


def test_both_inserts_carry_all_variant_columns_with_matching_placeholders():
    src = _DOC_DB_SRC.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(
        r"INSERT INTO sales_packing_lines\s*\((.*?)\)\s*VALUES\s*\((.*?)\)",
        src, flags=re.DOTALL,
    )
    assert len(blocks) == 2, (
        f"expected exactly the two known sales_packing_lines INSERTs "
        f"(store_ + replace_), found {len(blocks)} — a new write path must "
        f"also persist the variant columns and be added to this pin"
    )
    for cols_raw, vals_raw in blocks:
        cols = [c.strip() for c in cols_raw.replace("\n", " ").split(",")]
        for vc in _VARIANT_COLS:
            assert vc in cols, f"INSERT dropped {vc} — silent-drop returned"
        placeholders = vals_raw.count("?")
        assert placeholders == len(cols), (
            f"INSERT placeholder/column mismatch: {placeholders} vs {len(cols)}"
        )


def test_alter_tuple_registers_all_variant_columns_mirroring_purchase():
    src = _DOC_DB_SRC.read_text(encoding="utf-8", errors="replace")
    # TEXT fields mirror purchase packing_lines TEXT NOT NULL DEFAULT ''.
    for f in _TEXT_FIELDS:
        assert re.search(
            rf'\("{f}",\s*"TEXT NOT NULL DEFAULT \'\'"\)', src
        ), f"ALTER tuple missing TEXT column {f}"
    # REAL weights mirror purchase REAL NOT NULL DEFAULT 0.0.
    for f in _REAL_FIELDS:
        assert re.search(
            rf'\("{f}",\s*"REAL NOT NULL DEFAULT 0\.0"\)', src
        ), f"ALTER tuple missing REAL column {f}"


# ── 6. intake forwards all 9 keys on BOTH mappings ──────────────────────────

def test_intake_mappings_forward_all_variant_keys():
    # Variant forwarding is now CENTRALIZED in the canonical sales-packing
    # authority (document_db._reshape_sales_line), which every write flow
    # (intake / re-ingest / reprocess) routes through — so the keys are pinned at
    # that single location instead of duplicated in each route mapping.
    from app.services import document_db as ddb
    canonical = set(ddb._SALES_LINE_TEXT) | set(ddb._SALES_LINE_NUM)
    for f in _TEXT_FIELDS + _REAL_FIELDS:
        assert f in canonical, (
            f"variant key {f} not forwarded by document_db._reshape_sales_line — "
            f"the canonical sales-packing persistence authority"
        )
