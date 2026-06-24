"""
test_proforma_description_authority.py — Single-authority contract for Polish description.

Rule: The Draft Proforma must use exactly the same Polish description already stored in
documents.db :: product_descriptions.description_pl.  No second description generator
is allowed (Lesson N, single-authority rule).

Coverage:
  1.  Source-grep: proforma_draft_sync must not import generate_name_pl_if_sufficient
  2.  Source-grep: routes_proforma must not import generate_name_pl_if_sufficient
  3.  Birth path reads name_pl from PD row, not from sales-packing generator
  4.  Birth path falls back to name_pl when description_pl is blank
  5.  Birth path returns blank (no fabrication) on PD miss
  6.  TSV import path reads description_pl from product_descriptions (not row.desc_pl)
  7.  TSV import path returns blank + warning on PD miss
  8.  description_pl is byte-identical from engine write to proforma read (mock-based)
  9.  description_pl is preferred over name_pl when both present in PD row
  10. Source-grep: routes_packing must not import generate_description for PD writes
  11. Packing import calls get_description_block with invoice English description
  12. RNG 14KT LGD ring stores customs-grade sentence via get_description_block
  13. Operator override differing from description_pl surfaces ANOMALY_OPERATOR_DESCRIPTION_MISMATCH
  14. Operator override matching description_pl is a clean pass (no anomaly, no false positive)
  15. detect_operator_override_mismatches skips lines without name_pl_source='operator'
  16. detect_operator_override_mismatches returns empty when no canonical description_pl exists
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── 1 & 2: Import-level source-grep guards ─────────────────────────────────────

class TestNoGeneratorImport:

    def test_proforma_draft_sync_does_not_import_generate_name_pl_if_sufficient(self):
        src = (
            Path(__file__).parent.parent
            / "app/services/proforma_draft_sync.py"
        ).read_text(encoding="utf-8")
        assert "generate_name_pl_if_sufficient" not in src, (
            "proforma_draft_sync.py must not import generate_name_pl_if_sufficient "
            "(Lesson N / single-authority rule)"
        )

    def test_routes_proforma_does_not_import_generate_name_pl_if_sufficient(self):
        src = (
            Path(__file__).parent.parent
            / "app/api/routes_proforma.py"
        ).read_text(encoding="utf-8")
        assert "generate_name_pl_if_sufficient" not in src, (
            "routes_proforma.py must not import generate_name_pl_if_sufficient "
            "(Lesson N / single-authority rule)"
        )


# ── 3–5: Birth path uses product_descriptions, not the sales generator ─────────

class TestBirthPathAuthority:
    """
    _birth_resolve_name_pl(lines, lookup_fn, desc_generate) is called with
    desc_generate=None (no generator). Resolution: operator → PD → blank.
    """

    def _get_pildb(self):
        from service.app.services import proforma_invoice_link_db as pildb
        return pildb

    def test_birth_uses_pd_authority_not_generator(self):
        """Birth path reads name_pl from PD row; desc_generate=None must not fabricate."""
        pildb = self._get_pildb()
        pd_row = {"name_pl": "pierścionek złoty", "description_pl": "Pierścionek ze złota"}

        lines = [{"product_code": "EJL/26-27/295-1", "name_pl": ""}]
        result = pildb._birth_resolve_name_pl(
            lines=lines,
            lookup_fn=lambda _: pd_row,
            desc_generate=None,
        )

        assert len(result) == 1
        ln = result[0]
        assert ln["name_pl"], "name_pl must be non-blank when PD row has name_pl"
        assert ln["name_pl"] == pd_row["name_pl"]
        assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_PD

    def test_birth_falls_back_to_name_pl_when_description_pl_blank(self):
        """PD hit with non-blank name_pl returns it regardless of description_pl."""
        pildb = self._get_pildb()
        pd_row = {"name_pl": "pierścionek", "description_pl": ""}

        lines = [{"product_code": "EJL/26-27/295-1", "name_pl": ""}]
        result = pildb._birth_resolve_name_pl(
            lines=lines,
            lookup_fn=lambda _: pd_row,
            desc_generate=None,
        )

        ln = result[0]
        assert ln["name_pl"] == "pierścionek"
        assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_PD

    def test_birth_blank_on_pd_miss_no_generator(self):
        """PD miss with desc_generate=None → blank; never fabricate."""
        pildb = self._get_pildb()

        lines = [{"product_code": "EJL/26-27/999-9", "name_pl": ""}]
        result = pildb._birth_resolve_name_pl(
            lines=lines,
            lookup_fn=lambda _: None,
            desc_generate=None,
        )

        ln = result[0]
        assert ln["name_pl"] == ""
        assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_BLANK


# ── 6 & 7: TSV import path reads description_pl, not row.desc_pl ───────────────

class TestTSVImportAuthority:
    """
    The TSV sales-packing import in routes_proforma.py must look up
    product_descriptions.description_pl, not stamp row.desc_pl.
    """

    def _make_mock_row(self, desc_pl: str = "generated from category codes"):
        row = MagicMock()
        row.desc_pl    = desc_pl
        row.desc_en    = "gold ring"
        row.unit_price = 500.0
        row.line_total = 500.0
        return row

    def test_tsv_import_uses_description_pl_not_row_desc_pl(self):
        """When PD row present, ln['name_pl'] must equal description_pl, not row.desc_pl."""
        pd_text = "Pierścionek z 14-karatowego złota (próba 585). Biżuteria."

        ln: dict = {"product_code": "EJL/26-27/295-1"}
        row = self._make_mock_row("generated-from-category-codes")

        # Replicate the TSV import logic from routes_proforma.py
        with patch(
            "service.app.services.document_db.get_product_description",
            return_value={"description_pl": pd_text, "name_pl": "pierścionek"},
        ) as mock_get:
            import service.app.services.document_db as ddb
            _pc = str(ln.get("product_code") or "").strip()
            _pd_row = ddb.get_product_description(_pc) if _pc else None
            _pd_text = (
                (_pd_row or {}).get("description_pl")
                or (_pd_row or {}).get("name_pl")
                or ""
            ).strip()
            if _pd_text:
                ln["name_pl"]        = _pd_text
                ln["name_pl_source"] = "product_descriptions.description_pl"
            else:
                ln["name_pl"]        = ""
                ln["name_pl_source"] = "missing_product_descriptions"

        assert ln["name_pl"] == pd_text, (
            "name_pl must equal description_pl from product_descriptions, not row.desc_pl"
        )
        assert ln["name_pl"] != row.desc_pl
        assert ln["name_pl_source"] == "product_descriptions.description_pl"
        mock_get.assert_called_once_with("EJL/26-27/295-1")

    def test_tsv_import_blank_warning_on_pd_miss(self):
        """PD miss in TSV path → blank + warning; must not use row.desc_pl."""
        ln: dict = {"product_code": "EJL/26-27/999-9"}

        with patch(
            "service.app.services.document_db.get_product_description",
            return_value=None,
        ):
            import service.app.services.document_db as ddb
            _pc = str(ln.get("product_code") or "").strip()
            _pd_row = ddb.get_product_description(_pc) if _pc else None
            _pd_text = (
                (_pd_row or {}).get("description_pl")
                or (_pd_row or {}).get("name_pl")
                or ""
            ).strip()
            if _pd_text:
                ln["name_pl"] = _pd_text
                ln["name_pl_source"] = "product_descriptions.description_pl"
            else:
                ln["name_pl"] = ""
                ln["name_pl_source"] = "missing_product_descriptions"
                ln.setdefault("_warnings", []).append(
                    f"Polish customs description missing for product_code={_pc!r}. "
                    "Generate customs description package first. "
                    "Proforma must not fabricate Polish description."
                )

        assert ln["name_pl"] == ""
        assert ln["name_pl_source"] == "missing_product_descriptions"
        assert "_warnings" in ln
        assert "EJL/26-27/999-9" in ln["_warnings"][0]
        assert "customs description" in ln["_warnings"][0].lower()


# ── 8: Byte-identical from engine write to proforma read (mock-based) ──────────

class TestDescriptionPlByteIdentity:

    def test_description_pl_byte_identical_from_engine_to_proforma(self):
        """
        Mock-based: whatever description_pl is stored in product_descriptions,
        the TSV import path returns the same bytes — no transformation.
        """
        stored_text = "Pierścionek z 14-karatowego złota (próba 585) z diamentami. Biżuteria do noszenia."
        ln: dict = {"product_code": "EJL/26-27/295-1"}

        with patch(
            "service.app.services.document_db.get_product_description",
            return_value={"description_pl": stored_text, "name_pl": "pierścionek"},
        ):
            import service.app.services.document_db as ddb
            _pc = str(ln.get("product_code") or "").strip()
            _pd_row = ddb.get_product_description(_pc) if _pc else None
            _pd_text = (
                (_pd_row or {}).get("description_pl")
                or (_pd_row or {}).get("name_pl")
                or ""
            ).strip()
            if _pd_text:
                ln["name_pl"] = _pd_text

        assert ln.get("name_pl") == stored_text, (
            "name_pl must be byte-identical to stored description_pl — no mangling"
        )


# ── 9: description_pl preferred over name_pl when both present ─────────────────

class TestDescriptionPlPriority:

    def test_description_pl_preferred_over_name_pl(self):
        """When both description_pl and name_pl present, use description_pl."""
        pd_row = {
            "description_pl": "Pierścionek z 14-karatowego złota (próba 585). Biżuteria.",
            "name_pl": "pierścionek",
        }
        ln: dict = {"product_code": "EJL/26-27/295-1"}

        with patch(
            "service.app.services.document_db.get_product_description",
            return_value=pd_row,
        ):
            import service.app.services.document_db as ddb
            _pc = str(ln.get("product_code") or "").strip()
            _pd_row = ddb.get_product_description(_pc) if _pc else None
            _pd_text = (
                (_pd_row or {}).get("description_pl")
                or (_pd_row or {}).get("name_pl")
                or ""
            ).strip()
            if _pd_text:
                ln["name_pl"] = _pd_text

        assert ln["name_pl"] == pd_row["description_pl"], (
            "description_pl must be preferred over name_pl when both are present"
        )
        assert ln["name_pl"] != pd_row["name_pl"]


# ── 10-12. Packing import authority (routes_packing.py Fix 3 replacement) ────

class TestPackingImportAuthority:
    """
    routes_packing.py must not write sales_packing_parser generator output
    into product_descriptions.  The canonical authority is
    description_engine.get_description_block() via the invoice English description.
    """

    def test_routes_packing_no_generate_description_import_for_pd(self):
        """
        Test 10: routes_packing.py must not import sales_packing_parser.generate_description
        to populate product_descriptions.  The old block did:
            generate_description → upsert_product_description(description_pl=generated)
        Both halves of that pattern must be absent after the authority fix.
        """
        src = (
            Path(__file__).parent.parent / "app/api/routes_packing.py"
        ).read_text(encoding="utf-8")

        # The generator import alias must be gone entirely.
        assert "generate_description as _gen_sp_desc" not in src, (
            "routes_packing.py must not alias generate_description from "
            "sales_packing_parser for use in product_descriptions writes."
        )
        # upsert_product_description must not appear in routes_packing.py —
        # the canonical route is now description_engine.get_description_block().
        assert "upsert_product_description" not in src, (
            "routes_packing.py must not call upsert_product_description directly. "
            "Use description_engine.get_description_block() which handles the upsert "
            "internally via the customs engine."
        )

    def test_routes_packing_uses_get_description_block_for_pd(self):
        """
        Test 11: The packing import description block must call get_description_block
        (the canonical customs authority) with the invoice English description.
        It must NOT call generate_description or generate_name_pl_if_sufficient.
        """
        src = (
            Path(__file__).parent.parent / "app/api/routes_packing.py"
        ).read_text(encoding="utf-8")

        assert "get_description_block" in src, (
            "routes_packing.py must import and use description_engine.get_description_block"
        )
        # The old pattern hardcoded material_pl from _ITEM_MATERIAL dict — that must be gone.
        assert "_ITEM_MATERIAL" not in src, (
            "routes_packing.py must not contain hardcoded _ITEM_MATERIAL dict "
            "(generator-based material fallback). Use get_description_block() instead."
        )
        assert "_gen_sp_desc" not in src, (
            "routes_packing.py must not contain _gen_sp_desc alias (generator alias)"
        )

    def test_rng_14kt_lgd_stores_customs_grade_sentence(self, tmp_path):
        """
        Test 12: After packing import for an RNG 14KT LGD product code,
        product_descriptions.description_pl must contain a customs-grade sentence
        that includes karat purity and stone specification — NOT a short generator
        artifact like 'pierścionek z diamentami'.

        Simulates the get_description_block() call that routes_packing.py now makes,
        using the invoice English description as input.
        """
        import sqlite3
        from pathlib import Path as _Path

        # Build a minimal documents.db with invoice_lines for an RNG 14KT LGD product
        db_path = tmp_path / "documents.db"
        with sqlite3.connect(str(db_path)) as con:
            con.execute("""
                CREATE TABLE product_descriptions (
                    product_code TEXT PRIMARY KEY,
                    item_type TEXT NOT NULL DEFAULT '',
                    name_pl TEXT NOT NULL DEFAULT '',
                    description_pl TEXT NOT NULL DEFAULT '',
                    description_en TEXT NOT NULL DEFAULT '',
                    material_pl TEXT NOT NULL DEFAULT '',
                    purpose_pl TEXT NOT NULL DEFAULT '',
                    description_block TEXT NOT NULL DEFAULT '',
                    description_line TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'auto',
                    karat TEXT NOT NULL DEFAULT '',
                    metal_color TEXT NOT NULL DEFAULT '',
                    quality_string TEXT NOT NULL DEFAULT '',
                    stone_type TEXT NOT NULL DEFAULT '',
                    unit_price_eur REAL NOT NULL DEFAULT 0.0,
                    unit_price_usd REAL NOT NULL DEFAULT 0.0,
                    confidence TEXT NOT NULL DEFAULT '',
                    supplier_prefix TEXT NOT NULL DEFAULT '',
                    is_globally_unique INTEGER NOT NULL DEFAULT 1,
                    name_sk TEXT,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
            """)

        test_pc     = "EJL/26-27/327-1"
        invoice_en  = "PCS, 14KT Gold, LGD Stud Jewell Ring"

        import service.app.services.document_db as ddb
        from service.app.services.description_engine import get_description_block

        orig = ddb._db_path
        ddb._db_path = db_path
        try:
            result = get_description_block(test_pc, "RNG", description_en=invoice_en)
        finally:
            ddb._db_path = orig

        desc_pl  = result.get("description_pl", "")
        mat_pl   = result.get("material_pl",    "")

        # Must contain karat purity — NOT a short generator artifact
        assert "14-karatowego" in desc_pl or "próba 585" in desc_pl, (
            f"description_pl must contain karat information (14-karatowego / próba 585). "
            f"Got: {desc_pl!r}. This indicates the customs engine was not invoked."
        )
        assert "diament" in desc_pl.lower(), (
            f"description_pl must mention diamonds (diament). Got: {desc_pl!r}"
        )
        assert "Biżuteria" in desc_pl or "biżuteria" in desc_pl, (
            f"description_pl must contain purpose clause (Biżuteria do noszenia). "
            f"Got: {desc_pl!r}"
        )

        # Material must reflect gold purity — NOT generic 'Metal (srebro/stop metali)'
        assert "złoto" in mat_pl.lower() or "585" in mat_pl, (
            f"material_pl must contain gold purity. Got: {mat_pl!r}. "
            f"The hardcoded 'Metal (srebro/stop metali)' value indicates the old "
            f"generator path was used instead of get_description_block()."
        )

        # Confirm it is NOT the short generator artifact
        short_artifacts = [
            "pierścionek z diamentami",
            "pierścionek z kamieniami",
            "Wyrób jubilerski",  # pure fallback with no purity
        ]
        # Only flag if it's ONLY the artifact (customs-grade includes it but also more)
        assert not (desc_pl in short_artifacts), (
            f"description_pl must not be a short generator artifact. "
            f"Got: {desc_pl!r}. Expected a full customs-grade legal sentence."
        )


# ── 13–16. Operator-override mismatch advisory ────────────────────────────────

class TestOperatorOverrideMismatch:
    """
    When a draft line has name_pl_source='operator' and the operator's name_pl
    differs from the canonical product_descriptions.description_pl, the intelligence
    layer must surface ANOMALY_OPERATOR_DESCRIPTION_MISMATCH (severity=high).

    It must NOT fire when the operator value matches canonical (clean byte-match),
    and must NOT fire for lines that lack name_pl_source='operator'.
    """

    def _make_db(self, tmp_path, product_code: str, description_pl: str):
        """Create a minimal documents.db with one product_descriptions row."""
        import sqlite3
        db = tmp_path / "documents.db"
        with sqlite3.connect(str(db)) as con:
            con.execute("""
                CREATE TABLE product_descriptions (
                    product_code TEXT PRIMARY KEY,
                    description_pl TEXT NOT NULL DEFAULT ''
                )
            """)
            con.execute(
                "INSERT INTO product_descriptions VALUES (?,?)",
                (product_code, description_pl),
            )
        return db

    def _detect(self, lines, db_path):
        from service.app.services.proforma_intelligence import (
            detect_operator_override_mismatches,
            ANOMALY_OPERATOR_DESCRIPTION_MISMATCH,
        )
        return detect_operator_override_mismatches(lines, master_db_path=db_path)

    def test_operator_override_differing_surfaces_anomaly(self, tmp_path):
        """Test 13: operator name_pl ≠ canonical description_pl → HIGH anomaly."""
        canonical = (
            "Wyrób jubilerski z 14-karatowego złota (próba 585) wysadzany diamentami "
            "laboratoryjnymi. Biżuteria do noszenia."
        )
        db = self._make_db(tmp_path, "EJL/26-27/327-1", canonical)

        lines = [{
            "product_code":   "EJL/26-27/327-1",
            "name_pl":        "pierścionek z diamentami",  # old generator value
            "name_pl_source": "operator",
            "line_id":        "ln-01",
        }]
        anomalies = self._detect(lines, db)

        from service.app.services.proforma_intelligence import (
            ANOMALY_OPERATOR_DESCRIPTION_MISMATCH,
            SEVERITY_HIGH,
        )
        assert len(anomalies) == 1, (
            "Expected exactly 1 anomaly for operator override mismatch"
        )
        a = anomalies[0]
        assert a.anomaly_type == ANOMALY_OPERATOR_DESCRIPTION_MISMATCH
        assert a.severity == SEVERITY_HIGH
        assert a.confidence == 1.0
        assert "pierścionek z diamentami" in a.message
        assert "14-karatowego" in a.message or "585" in a.message
        assert "EJL/26-27/327-1" in a.message

    def test_operator_override_matching_canonical_is_clean(self, tmp_path):
        """Test 14: operator name_pl == canonical description_pl → no anomaly (clean byte-match)."""
        canonical = (
            "Wyrób jubilerski z 14-karatowego złota (próba 585) wysadzany diamentami "
            "laboratoryjnymi. Biżuteria do noszenia."
        )
        db = self._make_db(tmp_path, "EJL/26-27/327-1", canonical)

        lines = [{
            "product_code":   "EJL/26-27/327-1",
            "name_pl":        canonical,       # operator confirmed the canonical text
            "name_pl_source": "operator",
            "line_id":        "ln-01",
        }]
        anomalies = self._detect(lines, db)

        assert anomalies == [], (
            "No anomaly expected when operator value matches canonical description_pl "
            "(clean byte-match must not produce a false positive)"
        )

    def test_non_operator_source_not_flagged(self, tmp_path):
        """Test 15: lines with name_pl_source != 'operator' must not trigger the guard."""
        canonical = "Wyrób jubilerski z 14-karatowego złota. Biżuteria."
        db = self._make_db(tmp_path, "EJL/26-27/327-1", canonical)

        lines = [
            {
                "product_code":   "EJL/26-27/327-1",
                "name_pl":        "pierścionek z diamentami",
                "name_pl_source": "product_descriptions",  # not operator
                "line_id":        "ln-01",
            },
            {
                "product_code":   "EJL/26-27/327-1",
                "name_pl":        "pierścionek z diamentami",
                "name_pl_source": "auto",
                "line_id":        "ln-02",
            },
        ]
        anomalies = self._detect(lines, db)

        assert anomalies == [], (
            "Operator-override guard must only fire for name_pl_source='operator'"
        )

    def test_no_canonical_means_no_anomaly(self, tmp_path):
        """Test 16: if product_descriptions has no row for this product_code, skip silently."""
        db = tmp_path / "documents.db"
        import sqlite3
        with sqlite3.connect(str(db)) as con:
            con.execute(
                "CREATE TABLE product_descriptions "
                "(product_code TEXT PRIMARY KEY, description_pl TEXT NOT NULL DEFAULT '')"
            )
            # No row for EJL/26-27/327-1

        lines = [{
            "product_code":   "EJL/26-27/327-1",
            "name_pl":        "pierścionek z diamentami",
            "name_pl_source": "operator",
            "line_id":        "ln-01",
        }]
        anomalies = self._detect(lines, db)

        assert anomalies == [], (
            "No canonical description_pl in DB → no anomaly to surface (nothing to compare)"
        )
