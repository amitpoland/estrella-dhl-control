"""
test_product_identity_backfill.py — PR 2B: product identity backfill write mode.

Covers:
  1.  upsert inserts a new EJL row with correct source
  2.  upsert updates an existing backfill row (idempotent re-run)
  3.  upsert skips existing manual row — returns "skipped_manual"
  4.  ON CONFLICT WHERE guard: manual row unchanged after upsert attempt
  5.  upsert skips 417G code — returns "skipped_417g"
  6.  upsert skips generic description — returns "skipped_generic"
  7.  upsert dry_run=True returns "dry_run_insert" without writing
  8.  upsert dry_run=True returns "dry_run_update" for existing row
  9.  upsert updates existing source='auto' row
  10. all 9 identity columns written on insert
  11. source='pz_rows_backfill' set on written rows
  12. stub_cleanup dry-run: reports stubs, no deletes
  13. stub_cleanup write: 4 stubs deleted
  14. stub_cleanup preserves manual stub
  15. dedup: first-seen EJL code wins, second skipped
  16. end-to-end dry-run over synthetic outputs dir — no DB writes
  17. end-to-end write over synthetic outputs dir — rows inserted
  18. 417G rows produce no product_descriptions writes end-to-end
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> Path:
    """Init a minimal document.db with product_descriptions table."""
    from app.services.document_db import init_document_db
    db_path = tmp_path / "document.db"
    init_document_db(db_path)
    return db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def _make_identity(
    product_code: str = "EJL/26-27/100-1",
    *,
    supplier_prefix: str = "EJL",
    item_type: str = "RING",
    description_pl: str = "Pierścionek złoty z brylantami",
    description_en: str = "Gold ring with diamonds",
    karat: str = "18KT",
    metal_color: str = "W",
    quality_string: str = "G-VS LAB",
    stone_type: str = "LAB_DIAMOND",
    unit_price_eur: float = 125.0,
    unit_price_usd: float = 130.0,
    confidence: str = "HIGH",
    is_globally_unique: bool = True,
) -> Any:
    """Return a ProductIdentity via the engine (real object)."""
    from app.services.product_identity_engine import resolve_product_identity
    return resolve_product_identity(
        product_code,
        item_type=item_type,
        karat=karat,
        metal_color=metal_color,
        quality_string=quality_string,
        stone_type=stone_type,
        description_pl=description_pl,
        description_en=description_en,
        unit_price_eur=unit_price_eur,
        unit_price_usd=unit_price_usd,
        source="pz_rows_backfill",
    )


def _make_outputs_dir(
    tmp_path: Path,
    batches: Dict[str, list],
) -> Path:
    """
    Create a synthetic outputs directory.

    batches: {batch_id: [list of pz_rows dicts]}
    """
    outputs = tmp_path / "outputs"
    for batch_id, rows in batches.items():
        d = outputs / batch_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "pz_rows.json").write_text(
            json.dumps(rows), encoding="utf-8"
        )
    return outputs


def _pz_row(
    product_code: str = "EJL/26-27/100-1",
    item_type: str = "RING",
    pl_desc: str = "Pierścionek złoty",
    description_en: str = "Gold ring",
) -> Dict[str, Any]:
    return {
        "product_code":  product_code,
        "item_type":     item_type,
        "pl_desc":       pl_desc,
        "description_en": description_en,
    }


# ── 1. Insert new EJL row ─────────────────────────────────────────────────────

class TestUpsertInsert:
    def test_upsert_inserts_new_ejl_row(self, tmp_path):
        db_path = _make_db(tmp_path)
        identity = _make_identity()
        from app.services.document_db import upsert_product_identity_from_backfill
        con = _connect(db_path)
        result = upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=False
        )
        con.commit()
        con.close()
        assert result == "inserted"

    def test_inserted_row_readable(self, tmp_path):
        db_path = _make_db(tmp_path)
        identity = _make_identity()
        from app.services.document_db import (
            upsert_product_identity_from_backfill,
            get_product_description,
        )
        from app.services.document_db import init_document_db
        init_document_db(db_path)  # ensure path is set
        con = _connect(db_path)
        upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=False
        )
        con.commit()
        con.close()
        row = get_product_description("EJL/26-27/100-1")
        assert row is not None
        assert row["source"] == "pz_rows_backfill"


# ── 2. Update existing backfill row ──────────────────────────────────────────

class TestUpsertUpdate:
    def test_upsert_updates_existing_backfill_row(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import upsert_product_identity_from_backfill
        identity1 = _make_identity(description_pl="Pierścionek v1")
        identity2 = _make_identity(description_pl="Pierścionek v2")
        con = _connect(db_path)
        upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity1, dry_run=False
        )
        con.commit()
        result = upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity2, dry_run=False
        )
        con.commit()
        # Check row was updated
        row = con.execute(
            "SELECT name_pl FROM product_descriptions WHERE product_code=?",
            ("EJL/26-27/100-1",)
        ).fetchone()
        con.close()
        assert result == "updated"
        assert row["name_pl"] == "Pierścionek v2"


# ── 3–4. Manual row protection ────────────────────────────────────────────────

class TestManualProtection:
    def _insert_manual_row(self, con: sqlite3.Connection, product_code: str) -> None:
        now = "2026-01-01T00:00:00"
        con.execute(
            """INSERT INTO product_descriptions
               (product_code, item_type, name_pl, description_pl, description_en,
                material_pl, purpose_pl, description_block, description_line,
                source, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (product_code, "RING", "Manual name", "Manual desc", "",
             "", "", "", "", "manual", now, now),
        )
        con.commit()

    def test_upsert_skips_manual_row(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import upsert_product_identity_from_backfill
        con = _connect(db_path)
        self._insert_manual_row(con, "EJL/26-27/100-1")
        identity = _make_identity()
        result = upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=False
        )
        con.close()
        assert result == "skipped_manual"

    def test_manual_row_unchanged_after_upsert(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import upsert_product_identity_from_backfill
        con = _connect(db_path)
        self._insert_manual_row(con, "EJL/26-27/100-1")
        identity = _make_identity(description_pl="SHOULD NOT OVERWRITE")
        upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=False
        )
        row = con.execute(
            "SELECT name_pl, source FROM product_descriptions WHERE product_code=?",
            ("EJL/26-27/100-1",)
        ).fetchone()
        con.close()
        assert row["source"] == "manual"
        assert row["name_pl"] == "Manual name"


# ── 5. 417G skip ──────────────────────────────────────────────────────────────

class TestSkip417G:
    def test_upsert_skips_417g_code(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import upsert_product_identity_from_backfill
        from app.services.product_identity_engine import resolve_product_identity
        identity = resolve_product_identity(
            "417 Global Invoice-1",
            item_type="RING",
            description_pl="Gold ring",
            source="pz_rows_backfill",
        )
        con = _connect(db_path)
        result = upsert_product_identity_from_backfill(
            con, "417 Global Invoice-1", identity, dry_run=False
        )
        count = con.execute(
            "SELECT COUNT(*) FROM product_descriptions WHERE product_code=?",
            ("417 Global Invoice-1",)
        ).fetchone()[0]
        con.close()
        assert result == "skipped_417g"
        assert count == 0


# ── 6. Generic description skip ───────────────────────────────────────────────

class TestSkipGeneric:
    def test_upsert_skips_generic_description(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import upsert_product_identity_from_backfill
        from app.services.product_identity_engine import resolve_product_identity
        identity = resolve_product_identity(
            "EJL/26-27/100-1",
            description_pl="Biżuteria złota",
            source="pz_rows_backfill",
        )
        con = _connect(db_path)
        result = upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=False
        )
        con.close()
        assert result == "skipped_generic"


# ── 7–8. Dry-run mode ─────────────────────────────────────────────────────────

class TestDryRun:
    def test_dry_run_returns_dry_run_insert(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import upsert_product_identity_from_backfill
        identity = _make_identity()
        con = _connect(db_path)
        result = upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=True
        )
        count = con.execute(
            "SELECT COUNT(*) FROM product_descriptions WHERE product_code=?",
            ("EJL/26-27/100-1",)
        ).fetchone()[0]
        con.close()
        assert result == "dry_run_insert"
        assert count == 0, "dry-run must not write to DB"

    def test_dry_run_returns_dry_run_update_for_existing(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import upsert_product_identity_from_backfill
        identity = _make_identity()
        con = _connect(db_path)
        # Write once for real
        upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=False
        )
        con.commit()
        # Now dry-run
        result = upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=True
        )
        con.close()
        assert result == "dry_run_update"


# ── 9. Updates source='auto' row ──────────────────────────────────────────────

class TestUpdateAutoRow:
    def test_upsert_overwrites_auto_row(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import (
            upsert_product_description,
            upsert_product_identity_from_backfill,
            init_document_db,
        )
        init_document_db(db_path)
        # Insert an auto row via the legacy function
        upsert_product_description(
            product_code="EJL/26-27/100-1",
            item_type="RING",
            name_pl="Auto name",
            description_pl="Auto desc",
            material_pl="",
            purpose_pl="",
            description_block="",
            source="auto",
        )
        identity = _make_identity(description_pl="Backfill desc")
        con = _connect(db_path)
        result = upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=False
        )
        row = con.execute(
            "SELECT source, name_pl FROM product_descriptions WHERE product_code=?",
            ("EJL/26-27/100-1",)
        ).fetchone()
        con.close()
        assert result == "updated"
        assert row["source"] == "pz_rows_backfill"
        assert row["name_pl"] == "Backfill desc"


# ── 10. All 9 identity columns written ───────────────────────────────────────

class TestIdentityColumns:
    def test_all_9_identity_columns_written(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import upsert_product_identity_from_backfill
        identity = _make_identity(
            karat="18KT",
            metal_color="W",
            quality_string="G-VS LAB",
            stone_type="LAB_DIAMOND",
            unit_price_eur=125.0,
            unit_price_usd=130.0,
            confidence="HIGH",
        )
        con = _connect(db_path)
        upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=False
        )
        con.commit()
        row = dict(con.execute(
            "SELECT * FROM product_descriptions WHERE product_code=?",
            ("EJL/26-27/100-1",)
        ).fetchone())
        con.close()
        assert row["karat"]              == "18KT"
        assert row["metal_color"]        == "W"
        assert row["quality_string"]     == "G-VS LAB"
        assert row["stone_type"]         == "LAB_DIAMOND"
        assert abs(row["unit_price_eur"] - 125.0) < 0.001
        assert abs(row["unit_price_usd"] - 130.0) < 0.001
        assert row["confidence"]         == "HIGH"
        assert row["supplier_prefix"]    == "EJL"
        assert row["is_globally_unique"] == 1


# ── 11. Source provenance ────────────────────────────────────────────────────

class TestSourceProvenance:
    def test_source_is_pz_rows_backfill(self, tmp_path):
        db_path = _make_db(tmp_path)
        from app.services.document_db import upsert_product_identity_from_backfill
        identity = _make_identity()
        con = _connect(db_path)
        upsert_product_identity_from_backfill(
            con, "EJL/26-27/100-1", identity, dry_run=False
        )
        con.commit()
        row = con.execute(
            "SELECT source FROM product_descriptions WHERE product_code=?",
            ("EJL/26-27/100-1",)
        ).fetchone()
        con.close()
        assert row["source"] == "pz_rows_backfill"


# ── 12–14. Stub cleanup ───────────────────────────────────────────────────────

class TestStubCleanup:
    def _insert_stubs(self, con: sqlite3.Connection) -> None:
        now = "2026-01-01T00:00:00"
        for stub in ("RING", "PENDANT", "BRACELET", "EARRINGS"):
            con.execute(
                """INSERT OR IGNORE INTO product_descriptions
                   (product_code, item_type, name_pl, description_pl,
                    description_en, material_pl, purpose_pl, description_block,
                    description_line, source, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (stub, stub, stub, stub, "", "", "", "", "", "auto", now, now),
            )
        con.commit()

    def test_stub_cleanup_dry_run_reports_but_no_delete(self, tmp_path):
        db_path = _make_db(tmp_path)
        from service.scripts.backfill_product_identity import _run_stub_cleanup
        con = _connect(db_path)
        self._insert_stubs(con)
        result = _run_stub_cleanup(con, dry_run=True, verbose=False)
        count_after = con.execute(
            "SELECT COUNT(*) FROM product_descriptions"
        ).fetchone()[0]
        con.close()
        assert result["would_delete"] == 4
        assert count_after == 4, "dry-run must not delete rows"

    def test_stub_cleanup_write_deletes_4_stubs(self, tmp_path):
        db_path = _make_db(tmp_path)
        from service.scripts.backfill_product_identity import _run_stub_cleanup
        con = _connect(db_path)
        self._insert_stubs(con)
        result = _run_stub_cleanup(con, dry_run=False, verbose=False)
        con.commit()
        count_after = con.execute(
            "SELECT COUNT(*) FROM product_descriptions"
        ).fetchone()[0]
        con.close()
        assert result["deleted"] == 4
        assert count_after == 0

    def test_stub_cleanup_preserves_manual_stub(self, tmp_path):
        db_path = _make_db(tmp_path)
        from service.scripts.backfill_product_identity import _run_stub_cleanup
        con = _connect(db_path)
        now = "2026-01-01T00:00:00"
        # Insert RING as manual
        con.execute(
            """INSERT INTO product_descriptions
               (product_code, item_type, name_pl, description_pl,
                description_en, material_pl, purpose_pl, description_block,
                description_line, source, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("RING", "RING", "Manual ring", "Manual ring", "",
             "", "", "", "", "manual", now, now),
        )
        con.commit()
        result = _run_stub_cleanup(con, dry_run=False, verbose=False)
        con.commit()
        row = con.execute(
            "SELECT source FROM product_descriptions WHERE product_code='RING'"
        ).fetchone()
        con.close()
        assert result["manual_protected"] == 1
        assert result["deleted"] == 0
        assert row is not None and row["source"] == "manual"


# ── 15. First-seen dedup ──────────────────────────────────────────────────────

class TestDedup:
    def test_first_seen_wins_second_skipped(self, tmp_path):
        db_path = _make_db(tmp_path)
        outputs = _make_outputs_dir(tmp_path, {
            "SHIPMENT_001": [_pz_row("EJL/26-27/100-1", "RING", "Pierścionek złoty", "Gold ring")],
            "SHIPMENT_002": [_pz_row("EJL/26-27/100-1", "RING", "Pierścionek złoty v2", "Gold ring v2")],
        })
        from service.scripts.backfill_product_identity import run_backfill
        summary = run_backfill(
            outputs_root=outputs,
            db_path=db_path,
            dry_run=False,
            verbose=False,
        )
        assert summary["inserted"] == 1
        assert summary["skipped_duplicate"] == 1


# ── 16–18. End-to-end ─────────────────────────────────────────────────────────

class TestEndToEnd:
    def test_dry_run_end_to_end_no_db_writes(self, tmp_path):
        db_path = _make_db(tmp_path)
        outputs = _make_outputs_dir(tmp_path, {
            "SHIPMENT_001": [
                _pz_row("EJL/26-27/100-1", "RING",    "Pierścionek złoty",    "Gold ring"),
                _pz_row("EJL/26-27/100-2", "PENDANT", "Zawieszka złota",      "Gold pendant"),
            ],
        })
        from service.scripts.backfill_product_identity import run_backfill
        summary = run_backfill(
            outputs_root=outputs,
            db_path=db_path,
            dry_run=True,
            verbose=False,
        )
        # Dry-run: inserted count is rows that WOULD be inserted
        assert summary["mode"] == "dry_run"
        assert summary["inserted"] == 2
        # DB must be untouched
        con = _connect(db_path)
        count = con.execute(
            "SELECT COUNT(*) FROM product_descriptions"
        ).fetchone()[0]
        con.close()
        assert count == 0, "dry-run must not write to DB"

    def test_write_end_to_end_rows_inserted(self, tmp_path):
        db_path = _make_db(tmp_path)
        outputs = _make_outputs_dir(tmp_path, {
            "SHIPMENT_001": [
                _pz_row("EJL/26-27/100-1", "RING",    "Pierścionek złoty",  "Gold ring"),
                _pz_row("EJL/26-27/100-2", "PENDANT", "Zawieszka złota",    "Gold pendant"),
                _pz_row("EJL/26-27/100-3", "EARRING", "Kolczyki złote",     "Gold earrings"),
            ],
        })
        from service.scripts.backfill_product_identity import run_backfill
        summary = run_backfill(
            outputs_root=outputs,
            db_path=db_path,
            dry_run=False,
            verbose=False,
        )
        assert summary["mode"] == "write"
        assert summary["inserted"] == 3
        assert summary["errors"] == 0
        con = _connect(db_path)
        count = con.execute(
            "SELECT COUNT(*) FROM product_descriptions "
            "WHERE source='pz_rows_backfill'"
        ).fetchone()[0]
        con.close()
        assert count == 3

    def test_417g_rows_not_written_end_to_end(self, tmp_path):
        db_path = _make_db(tmp_path)
        outputs = _make_outputs_dir(tmp_path, {
            "SHIPMENT_001": [
                _pz_row("417 Global Invoice-1", "RING",    "Gold ring",     "Gold ring"),
                _pz_row("417 Global Invoice-2", "PENDANT", "Gold pendant",  "Gold pendant"),
            ],
        })
        from service.scripts.backfill_product_identity import run_backfill
        summary = run_backfill(
            outputs_root=outputs,
            db_path=db_path,
            dry_run=False,
            verbose=False,
        )
        assert summary["skipped_417g"] == 2
        assert summary["inserted"] == 0
        con = _connect(db_path)
        count = con.execute(
            "SELECT COUNT(*) FROM product_descriptions"
        ).fetchone()[0]
        con.close()
        assert count == 0
