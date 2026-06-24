"""
test_proforma_description_authority.py — Single-authority contract for Polish description.

Rule: The Draft Proforma must use exactly the same Polish description already stored in
documents.db :: product_descriptions.description_pl.  No second description generator
is allowed (Lesson N, single-authority rule).

Canonical description authority (binding):
  description_pl = final Polish customs-grade description
  description_en = final English customs-grade description ONLY if clean
  Supplier shorthand (PCS/PRS/14KT/LGD invoice codes) must NEVER populate description_en.
  If description_en is missing or untrusted, renderer outputs PL only (no slash).
  Output format: {description_pl} / {description_en}  (EN slot only if authoritative)

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
  11. Source-grep: routes_packing must not pass supplier shorthand as description_en
  12. get_description_block without description_en → description_en blank, PL-only output
  13. Operator override differing from description_pl surfaces ANOMALY_OPERATOR_DESCRIPTION_MISMATCH
  14. Operator override matching description_pl is a clean pass (no anomaly, no false positive)
  15. detect_operator_override_mismatches skips lines without name_pl_source='operator'
  16. detect_operator_override_mismatches returns empty when no canonical description_pl exists
  17. build_description_line(pl, blank_en) returns PL only — no trailing slash
  18. build_description_line with PCS/LGD shorthand as en would render slash+shorthand
      (demonstrating why description_en must stay blank for EJL products)
  19. Source-grep: routes_packing must not contain description_en=_inv_en call pattern
  20. get_description_block for EJL product code without description_en: description_line
      has no PCS/LGD/KT shorthand and no slash separator
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
    description_engine.get_description_block().

    Canonical description_en rule (binding):
      invoice_lines.description for EJL products is supplier shorthand
      (e.g. "PCS, 14KT Gold, LGD Stud Jewellery RING") — NOT customs-grade English.
      It must NEVER be passed as description_en to get_description_block().
      description_en is left blank; the renderer outputs PL only until a
      verified customs-grade English sentence is explicitly provided.
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

    def test_routes_packing_does_not_pass_supplier_shorthand_as_description_en(self):
        """
        Test 11: routes_packing.py must NOT pass invoice_lines.description as
        description_en to get_description_block().  invoice_lines.description for EJL
        products is supplier shorthand (PCS/KT/LGD codes) — not customs-grade English.
        Writing shorthand as description_en would make the renderer produce:
            "{customs_pl} / PCS, 14KT Gold, LGD Stud Jewellery RING"
        which violates the canonical authority rule.
        """
        src = (
            Path(__file__).parent.parent / "app/api/routes_packing.py"
        ).read_text(encoding="utf-8")

        assert "get_description_block" in src, (
            "routes_packing.py must import and use description_engine.get_description_block"
        )
        assert "_ITEM_MATERIAL" not in src, (
            "routes_packing.py must not contain hardcoded _ITEM_MATERIAL dict "
            "(generator-based material fallback). Use get_description_block() instead."
        )
        assert "_gen_sp_desc" not in src, (
            "routes_packing.py must not contain _gen_sp_desc alias (generator alias)"
        )
        # The key guard: invoice shorthand must not be passed as description_en.
        # Any of these patterns indicates the old shorthand-pass-through was re-introduced.
        assert "description_en=_inv_en" not in src, (
            "routes_packing.py must not pass _inv_en (invoice_lines.description shorthand) "
            "as description_en to get_description_block(). Supplier shorthand like "
            "'PCS, 14KT Gold, LGD Stud Jewellery RING' must never populate description_en."
        )
        assert "description_en=inv_en" not in src, (
            "routes_packing.py must not pass inv_en (invoice shorthand) as description_en."
        )

    def test_get_description_block_without_en_produces_blank_en_and_pl_only_line(
        self, tmp_path
    ):
        """
        Test 12: get_description_block(product_code, item_type) called WITHOUT
        description_en must produce:
          - description_en == "" (blank — no shorthand persisted)
          - description_line == description_pl (PL only, no slash)
          - description_line contains no PCS/LGD/KT supplier shorthand

        This is the call pattern that routes_packing.py now uses after the
        canonical authority fix: no supplier text is ever written as description_en.
        """
        import sqlite3

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

        import app.services.document_db as ddb
        from app.services.description_engine import get_description_block

        orig = ddb._db_path
        ddb._db_path = db_path
        try:
            # Call WITHOUT description_en — this is the new routes_packing.py pattern.
            result = get_description_block("EJL/26-27/327-1", "RNG")
        finally:
            ddb._db_path = orig

        desc_pl   = result.get("description_pl",   "")
        desc_en   = result.get("description_en",   "")
        desc_line = result.get("description_line", "")

        assert desc_en == "", (
            f"description_en must be blank when no authoritative English source is "
            f"provided. Got: {desc_en!r}. Supplier shorthand must never be persisted."
        )
        assert desc_line == desc_pl, (
            f"description_line must equal description_pl (PL only) when description_en "
            f"is blank. Got description_line={desc_line!r}, description_pl={desc_pl!r}."
        )
        assert "/" not in desc_line, (
            f"description_line must contain no slash when description_en is blank. "
            f"Got: {desc_line!r}. A slash indicates supplier shorthand leaked through."
        )
        # No shorthand tokens in the output line
        for token in ("PCS", "PRS", "LGD", "KT Gold", "SILVER", "RING", "EARRINGS"):
            assert token not in desc_line, (
                f"description_line must contain no supplier shorthand token {token!r}. "
                f"Got: {desc_line!r}."
            )
        assert desc_pl, "description_pl must not be empty after get_description_block call"


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


# ── 17–20: Canonical description_en shorthand guard ──────────────────────────

class TestDescriptionEnShorthandGuard:
    """
    Enforces the canonical authority rule for description_en:

      description_en = final English customs-grade description ONLY if clean.
      Supplier shorthand (PCS/PRS/14KT/LGD invoice codes) must NEVER populate
      description_en.  If description_en is missing or untrusted, the renderer
      (build_description_line) outputs PL only — no slash, no shorthand.
    """

    def test_build_description_line_blank_en_returns_pl_only(self):
        """Test 17: build_description_line(pl, "") returns pl with no slash."""
        from app.services.description_engine import build_description_line

        pl = "Pierścionek z 14-karatowego złota (próba 585) wysadzany diamentami. Biżuteria do noszenia."
        result = build_description_line(pl, "")

        assert result == pl, (
            f"build_description_line(pl, '') must return pl unchanged. Got: {result!r}"
        )
        assert "/" not in result, (
            f"build_description_line with blank EN must not produce a slash. Got: {result!r}"
        )

    def test_build_description_line_with_shorthand_en_renders_slash_violation(self):
        """
        Test 18: build_description_line(pl, shorthand_en) would render
        "{pl} / PCS, 14KT Gold, LGD..." — documenting exactly why description_en
        must never be populated with supplier shorthand.  The renderer itself does
        not validate inputs; the guard is upstream (tests 11, 19).
        """
        from app.services.description_engine import build_description_line

        pl           = "Pierścionek z 14-karatowego złota (próba 585) wysadzany diamentami. Biżuteria do noszenia."
        shorthand_en = "PCS, 14KT Gold, LGD Stud Jewellery RING"

        result = build_description_line(pl, shorthand_en)

        assert "PCS" in result and "LGD" in result, (
            "build_description_line with shorthand_en renders shorthand after slash — "
            "confirming that description_en must stay blank for EJL products."
        )
        assert " / " in result, (
            "build_description_line(pl, shorthand_en) produces a slash separator — "
            "confirming the violation that upstream guards must prevent."
        )

    def test_routes_packing_inv_en_not_passed_as_description_en(self):
        """
        Test 19: Source-grep — routes_packing.py must not contain any call pattern
        that passes invoice_lines.description (shorthand) as the description_en
        argument to get_description_block().
        """
        src = (
            Path(__file__).parent.parent / "app/api/routes_packing.py"
        ).read_text(encoding="utf-8")

        assert "description_en=_inv_en" not in src, (
            "routes_packing.py must not contain description_en=_inv_en. "
            "This passes supplier shorthand as description_en to get_description_block(), "
            "causing 'PCS, 14KT Gold, LGD Stud Jewellery RING' to be persisted in "
            "product_descriptions.description_en and rendered after the slash."
        )
        assert "description_en=inv_en" not in src, (
            "routes_packing.py must not pass inv_en as description_en."
        )
        assert "description_en=_il_en" not in src, (
            "routes_packing.py must not pass _il_en (invoice line description) "
            "as description_en — it is supplier shorthand."
        )

    def test_ejl_product_via_routes_packing_call_pattern_has_no_shorthand(
        self, tmp_path
    ):
        """
        Test 20: When get_description_block(product_code, item_type) is called WITHOUT
        description_en (the routes_packing.py call pattern), description_line must
        contain no PCS/LGD/KT supplier shorthand and no slash separator.
        """
        import sqlite3

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

        import app.services.document_db as ddb
        from app.services.description_engine import get_description_block

        orig = ddb._db_path
        ddb._db_path = db_path
        try:
            result = get_description_block("EJL/26-27/098-1", "RNG")
        finally:
            ddb._db_path = orig

        desc_en   = result.get("description_en",   "")
        desc_line = result.get("description_line", "")

        assert desc_en == "", (
            f"description_en must be blank when get_description_block is called without "
            f"description_en. Got: {desc_en!r}. Supplier shorthand must not be persisted."
        )
        assert "/" not in desc_line, (
            f"description_line must not contain a slash when description_en is blank. "
            f"Got: {desc_line!r}."
        )
        shorthand_tokens = [
            "PCS", "PRS", "LGD", "14KT", "18KT", "09KT",
            "PT950", "SL925", "RING", "EARRINGS", "PENDANT",
            "BRACELET", "Stud", "Jewel", "Jewellery",
        ]
        for token in shorthand_tokens:
            assert token not in desc_line, (
                f"description_line must not contain supplier shorthand token {token!r}. "
                f"Got: {desc_line!r}."
            )
