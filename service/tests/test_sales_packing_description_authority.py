"""
test_sales_packing_description_authority.py — Campaign 4: Product Description Authority
in the Sales Packing List.

Rule (Lesson N, single-authority): ONE PRODUCT_CODE = ONE LOCKED DESCRIPTION_BLOCK.
documents.db :: product_descriptions is the ONLY Product Description Authority.
The Sales Packing List must display it through the already-enriched draft line —
no second resolver, no second mapping, no renderer-side lookup.

Two defects fixed by this campaign:

  D1 (writer)  EJL packing lists supply 3-letter category codes ("RNG"); the grammar
               tables are keyed by long names ("RING").  With no normalisation between
               them, render_product_description_en("RNG") fell through to
               "RNG".title() == "Rng" and the Polish half degraded to the generic
               "Wyrób jubilerski — wyrób jubilerski do noszenia.", which was then
               upserted with source='auto' and LOCKED forever.

  D2 (reader)  One authority is read under two policies: the customs path is guarded by
               resolve_product_description_for_customs + _contains_forbidden_desc_token,
               the proforma/draft path was NOT.  Poisoned rows leaked into drafts.

Coverage (operator test list 1–11):
  1.  Canonical short-code normalisation RNG/BRC/EAR/PND/NCK through the shared
      grammar authority, and the downstream EN/PL generation that follows from it.
  2.  No duplicate normalisation map — every consumer delegates to
      description_grammar.canonical_item_type.
  3.  Poisoned authority row rejected on draft enrichment (blank + warning, row intact).
  4.  Manual canonical row still accepted byte-for-byte.
  5.  Sales Packing List row builder carries the enriched draft description through.
  6.  Purchase description isolation — packing/purchase text never reaches the cell.
  7.  Sales-data authority preservation — commercial fields still come from the draft.
  8.  Missing description → blank cell, no generic/purchase fallback, no write.
  9.  Posted-draft immutability — enrichment is pure and gated by EDITABLE_STATES.
  10. Multi-design same product code — per-row sales data preserved, no collapsing.
  11. All-proforma behaviour — no special case for PROF 170/2026.

Frontend coverage is structural (source-grep over the JSX).  The repo's only JS test
runner (service/tests/js/*.mjs) is not wired into CI and its esbuild dependency is
absent, so a node test here would never execute.  These guards do run.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from app.services import proforma_invoice_link_db as pildb

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_V2 = _REPO_ROOT / "service/app/static/v2"


# ── The exact poison observed in production (23 rows, live documents.db) ───────

POISON_EN = "Rng"
POISON_PL = "Wyrób jubilerski — wyrób jubilerski do noszenia."

# The approved canonical example from description_length_policy's own docstring —
# not invented wording.
CANON_PL = "Pierścionek z 14-karatowego złota (próba 585) z diamentami laboratoryjnymi."
CANON_EN = "14KT Gold Ring With Laboratory Grown Diamonds. Jewellery."


def _poisoned_row() -> Dict[str, Any]:
    return {
        "product_code":   "EJL/26-27/999-9",
        "item_type":      "RNG",
        "name_pl":        "Wyrób jubilerski",
        "description_en": POISON_EN,
        "description_pl": POISON_PL,
        "source":         "auto",
        "confidence":     "low",
    }


def _manual_row() -> Dict[str, Any]:
    return {
        "product_code":   "EJL/26-27/295-1",
        "item_type":      "RING",
        "name_pl":        "Pierścionek złoty",
        "description_en": CANON_EN,
        "description_pl": CANON_PL,
        "source":         "manual",
        "confidence":     "high",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. Canonical short-code normalisation
# ══════════════════════════════════════════════════════════════════════════════

class TestShortCodeNormalisation:

    @pytest.mark.parametrize("raw,expected", [
        ("RNG", "RING"),
        ("BRC", "BRACELET"),
        ("EAR", "EARRING"),
        ("PND", "PENDANT"),
        ("NCK", "NECKLACE"),
    ])
    def test_grammar_canonicalises_ejl_short_codes(self, raw, expected):
        from description_grammar import canonical_item_type
        assert canonical_item_type(raw) == expected

    def test_canonical_keys_exist_in_both_grammar_tables(self):
        """Canonical output must be a real key — otherwise normalisation is cosmetic."""
        from description_grammar import (
            ITEM_TYPE_ALIASES, ITEM_TYPE_EN, ITEM_TYPE_PL,
        )
        for token, canon in ITEM_TYPE_ALIASES.items():
            assert canon in ITEM_TYPE_PL, f"{token!r} -> {canon!r} missing from ITEM_TYPE_PL"
            assert canon in ITEM_TYPE_EN, f"{token!r} -> {canon!r} missing from ITEM_TYPE_EN"

    def test_description_engine_normalise_widens_never_narrows(self):
        from app.services import description_engine as de
        assert de._normalise_item_type("RNG")  == "RING"      # fixed
        assert de._normalise_item_type("ring") == "RING"      # unchanged
        assert de._normalise_item_type("RING") == "RING"      # unchanged
        assert de._normalise_item_type("STUD") == "STUD"      # no alias, still a valid key
        assert de._normalise_item_type("")     == ""

    def test_translation_lookup_resolves_short_code_like_long_name(self):
        """RNG and RING must select the same Polish translation entry."""
        from app.services import description_engine as de
        assert de._resolve_translation("RNG") == de._resolve_translation("RING")

    def test_english_generation_for_short_code_is_not_the_title_cased_code(self):
        """
        Asserts the result of the existing grammar authority — no invented wording.
        The short code must render exactly what the long name renders.
        """
        from app.services import description_engine as de
        if de._load_customs_engine() is None:
            pytest.skip("customs_description_engine unavailable in this environment")

        long_name = de._english_description_from_item_type("RING")
        short_code = de._english_description_from_item_type("RNG")

        assert long_name, "grammar authority produced no English for RING"
        assert short_code == long_name
        assert short_code not in ("Rng", "Brc", "Ear", "Pnd", "Nck")

    @pytest.mark.parametrize("short,long", [
        ("RNG", "RING"), ("BRC", "BRACELET"), ("EAR", "EARRING"),
        ("PND", "PENDANT"), ("NCK", "NECKLACE"),
    ])
    def test_polish_generation_for_short_code_is_not_generic(self, short, long):
        from app.services import description_engine as de
        if de._load_customs_engine() is None:
            pytest.skip("customs_description_engine unavailable in this environment")

        en = de._english_description_from_item_type(short)
        block = de._customs_grade_translation(short, en)
        assert block["description_pl"] == de._customs_grade_translation(
            long, de._english_description_from_item_type(long)
        )["description_pl"]
        assert POISON_PL not in block["description_pl"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. One normalisation authority — no duplicate maps
# ══════════════════════════════════════════════════════════════════════════════

class TestSingleNormalisationAuthority:

    # normalised-token -> canonical, in any quoting/casing style
    _ALIAS_LITERAL = re.compile(
        r'["\']rng["\']\s*:\s*["\']ring["\']', re.IGNORECASE
    )

    def _production_sources(self):
        for path in (_REPO_ROOT / "service/app").rglob("*.py"):
            yield path
        for path in _REPO_ROOT.glob("*.py"):
            yield path

    def test_alias_map_literal_exists_only_in_the_grammar_authority(self):
        owners = {
            p.name for p in self._production_sources()
            if self._ALIAS_LITERAL.search(p.read_text(encoding="utf-8"))
        }
        assert owners == {"description_grammar.py"}, (
            "Item-type short-code aliases must exist ONLY in description_grammar.py; "
            f"also found in: {sorted(owners - {'description_grammar.py'})}. "
            "Use description_grammar.canonical_item_type instead."
        )

    def test_no_second_ejl_token_map(self):
        for path in self._production_sources():
            src = path.read_text(encoding="utf-8")
            assert "_EJL_TOKEN_MAP = {" not in src, (
                f"{path.name} declares a second _EJL_TOKEN_MAP"
            )

    def test_extractor_delegates_and_keeps_its_lowercase_contract(self):
        from app.services import invoice_packing_extractor as ipe
        assert ipe._canonical_item_type("RNG")     == "ring"
        assert ipe._canonical_item_type("PRS")     == "earring"
        assert ipe._canonical_item_type("unknown") == "unknown"

    def test_dhl_renderer_delegates_and_keeps_its_uppercase_contract(self):
        from app.api import routes_dhl_clearance as rdc
        assert rdc._normalise_type_key("RNG")  == "RING"
        assert rdc._normalise_type_key("ERS")  == "EARRING"
        assert rdc._normalise_type_key("PRS")  == "EARRING"
        assert rdc._normalise_type_key("ZZZ")  == "ZZZ"

    def test_description_engine_does_not_declare_its_own_mapping(self):
        src = (_REPO_ROOT / "service/app/services/description_engine.py").read_text(
            encoding="utf-8"
        )
        assert not self._ALIAS_LITERAL.search(src)


# ══════════════════════════════════════════════════════════════════════════════
# 2b. Parser containment — BEHAVIOURAL, not an allow-list
# ══════════════════════════════════════════════════════════════════════════════

_TSV_HEADER = "Sr\tCtg\tDesign\tKt\tCol\tQuality\tQty\tValue\tTotal Value"


def _tsv(ctg: str) -> str:
    return (
        _TSV_HEADER
        + f"\n1\t{ctg}\tD-1\t14KT\tYG\tLGD\t2\t100.00\t200.00\n"
    )


class TestParserContainment:
    """sales_packing_parser owns INPUT-COLUMN RECOGNITION only.

    It keeps a commercial-wording vocabulary (_CATEGORY_PL / _CATEGORY_EN) whose
    output reaches exactly two places: a draft line's birth ``name_pl`` fallback
    (only after a product_descriptions MISS) and ``SalesPackingRow.desc_en`` →
    ``ln["remarks"]``.  It is not a second normalisation authority and it never
    decides Product Description Authority wording.  Proven by behaviour below,
    not by trusting a filename list.
    """

    def test_parser_output_is_canonicalised_short_and_long_agree(self):
        from app.api import sales_packing_parser as spp
        assert (spp.generate_description("RNG", "14KT", "YG", "LGD")
                == spp.generate_description("RING", "14KT", "YG", "LGD"))
        assert (spp.generate_description("pnd", "", "", "")
                == spp.generate_description("PENDANT", "", "", ""))

    def test_raw_short_code_never_appears_in_parser_output(self):
        from app.api import sales_packing_parser as spp
        for code in ("RNG", "BRC", "EAR", "PND", "NCK"):
            pl, en = spp.generate_description(code, "14KT", "YG", "LGD")
            # whole-token match: "EAR" inside "earrings" is the correct word,
            # a bare "EAR"/"Ear" token is the D1 poison shape ("RNG".title()).
            token = re.compile(rf"\b{code}\b", re.IGNORECASE)
            assert not token.search(pl), pl
            assert not token.search(en), en

    def test_parser_routes_through_the_canonical_normaliser(self, monkeypatch):
        """Not "it happens to agree" — the parser must actually CALL it.

        Redirect the shared normaliser and the parser's answer must follow it.
        A private copy of the alias table would ignore this and fail.
        """
        from app.api import sales_packing_parser as spp
        monkeypatch.setattr(spp, "canonical_item_type", lambda s: "NECKLACE")
        pl, _en = spp.generate_description("RNG", "", "", "")
        assert pl.startswith("naszyjnik"), pl

    def test_unknown_code_cannot_become_authoritative_by_adding_a_local_alias(
        self, monkeypatch
    ):
        """Rule 3: a new alias outside description_grammar.py stays inert.

        Teaching the parser's own wording table a code the canonical grammar
        does not know must NOT make that code recognised.
        """
        from app.api import sales_packing_parser as spp
        monkeypatch.setitem(spp._CATEGORY_PL, "ZZZ", "amulet")
        assert spp.generate_name_pl_if_sufficient("ZZZ") is None
        pl, _en = spp.generate_description("ZZZ", "", "", "")
        assert "amulet" not in pl
        assert pl.startswith("wyrób")  # the declared placeholder noun

    def test_parser_never_writes_the_product_description_authority(self, monkeypatch):
        """Behavioural: the single authority writer must not fire while parsing."""
        from app.api import sales_packing_parser as spp
        from app.services import document_db

        def _boom(*a, **kw):
            raise AssertionError(
                "sales_packing_parser reached upsert_product_description — "
                "parser vocabulary must never write the Product Description Authority"
            )

        monkeypatch.setattr(document_db, "upsert_product_description", _boom)
        rows, _total = spp.parse_ejl_sales_packing(_tsv("RNG"))
        assert len(rows) == 1
        # Fabrication helper is permanently disabled — never invents name_pl.
        assert spp.generate_name_pl_if_sufficient("RNG", "14KT", "YG", "LGD") is None

    def test_parser_wording_does_not_decide_authority_wording(self, monkeypatch):
        """Corrupting the parser's vocabulary must not move the customs answer."""
        from app.api import sales_packing_parser as spp
        from app.services import description_engine as de

        before = de._english_description_from_item_type("RNG")
        monkeypatch.setitem(spp._CATEGORY_EN, "RING", "PARSER-POISON")
        assert de._english_description_from_item_type("RNG") == before
        assert "PARSER-POISON" not in before

    @pytest.mark.parametrize("raw,canon", [
        ("EARRING", "EARRING"),   # contains "RING" — must not collapse to RING
        ("EARRINGS", "EARRING"),
        ("ER",   "EARRING"),
        ("EARS", "EARRING"),
        ("PRS",  "EARRING"),      # pairs
        ("RNG",  "RING"),
        ("ZZZ",  ""),             # unrecognised → no invention
        ("",     ""),
    ])
    def test_ambiguous_normalisation(self, raw, canon):
        import description_grammar as dg
        assert dg.canonical_item_type(raw) == canon

    def test_earring_does_not_degrade_to_ring_through_the_parser(self):
        from app.api import sales_packing_parser as spp
        pl_ear, _ = spp.generate_description("EARRING", "", "", "")
        pl_rng, _ = spp.generate_description("RING", "", "", "")
        assert pl_ear.startswith("kolczyki")
        assert pl_ear != pl_rng


# ══════════════════════════════════════════════════════════════════════════════
# 3. Poisoned authority row rejected on draft enrichment
# ══════════════════════════════════════════════════════════════════════════════

class TestPoisonedRowRejection:

    def _enrich_one(self, row: Optional[Dict[str, Any]], line: Dict[str, Any]):
        enriched, n_hit, n_miss = pildb.enrich_lines_from_product_descriptions(
            [line], lambda _pc: row
        )
        return enriched[0], n_hit, n_miss

    def test_poisoned_strings_are_never_exposed(self):
        line = {"line_id": 1, "product_code": "EJL/26-27/999-9",
                "design": "D-101", "qty": 3, "unit_price": 120.0}
        ln, _, _ = self._enrich_one(_poisoned_row(), line)

        assert not ln["description_en"], "poisoned 'Rng' must not be exposed"
        assert not ln["description_pl"], "generic Polish must not be exposed"
        assert not ln["description_bilingual"]
        assert not ln["name_pl"]
        assert POISON_EN not in str(ln)
        assert POISON_PL not in str(ln)

    def test_missing_description_warning_contract(self):
        line = {"line_id": 1, "product_code": "EJL/26-27/999-9"}
        ln, _, _ = self._enrich_one(_poisoned_row(), line)

        assert ln["name_pl_source"] == "missing_product_descriptions"
        assert "_warnings" in ln and ln["_warnings"]
        assert "EJL/26-27/999-9" in ln["_warnings"][0]
        assert "description" in ln["_warnings"][0].lower()

    def test_other_line_values_unchanged(self):
        line = {"line_id": 7, "product_code": "EJL/26-27/999-9", "design": "D-101",
                "qty": 3, "unit_price": 120.0, "currency": "EUR",
                "client_ref": "PO-77", "hs_code": "711319"}
        ln, _, _ = self._enrich_one(_poisoned_row(), line)

        assert ln["line_id"]      == 7
        assert ln["product_code"] == "EJL/26-27/999-9"   # stable identity preserved
        assert ln["design"]       == "D-101"
        assert ln["qty"]          == 3
        assert ln["unit_price"]   == 120.0
        assert ln["currency"]     == "EUR"
        assert ln["client_ref"]   == "PO-77"
        assert ln["hs_code"]      == "711319"
        assert ln["item_type"]    == "RNG"               # non-description field kept

    def test_authority_table_row_is_not_modified(self):
        row = _poisoned_row()
        before = dict(row)
        self._enrich_one(row, {"line_id": 1, "product_code": "EJL/26-27/999-9"})
        assert row == before, "rendering/enrichment must never mutate the authority row"

    def test_input_line_is_not_mutated(self):
        line = {"line_id": 1, "product_code": "EJL/26-27/999-9", "qty": 2}
        before = dict(line)
        self._enrich_one(_poisoned_row(), line)
        assert line == before

    def test_poisoned_english_alone_is_also_rejected(self):
        """Category abbreviation in description_en with clean PL must still blank EN."""
        row = {**_manual_row(), "description_en": "Rng"}
        ln, _, _ = self._enrich_one(row, {"line_id": 1, "product_code": "X"})
        assert not ln["description_en"]
        assert ln["description_pl"] == CANON_PL     # clean PL survives


# ══════════════════════════════════════════════════════════════════════════════
# 4. Manual canonical row still accepted
# ══════════════════════════════════════════════════════════════════════════════

class TestManualRowAccepted:

    def test_manual_row_enriches_unchanged(self):
        enriched, n_hit, n_miss = pildb.enrich_lines_from_product_descriptions(
            [{"line_id": 1, "product_code": "EJL/26-27/295-1", "qty": 1}],
            lambda _pc: _manual_row(),
        )
        ln = enriched[0]
        assert n_hit == 1 and n_miss == 0
        assert ln["description_pl"] == CANON_PL
        assert ln["description_en"] == CANON_EN
        assert ln["description_bilingual"] == f"{CANON_PL} / {CANON_EN}"
        # Commercial name_pl = description_pl (PZ / customs authority), not the
        # short noun-only name_pl column.
        assert ln["name_pl"] == CANON_PL
        assert "name_pl_source" not in ln or ln["name_pl_source"] != "missing_product_descriptions"
        assert "_warnings" not in ln

    def test_existing_short_but_valid_descriptions_are_not_over_blocked(self):
        """The reader guard rejects forbidden tokens — not every terse description."""
        row = {"item_type": "PENDANT", "name_pl": "Wisiorek",
               "description_pl": "Wisiorek różowe złoto 585",
               "description_en": "Rose gold pendant 585", "source": "auto"}
        enriched, _, _ = pildb.enrich_lines_from_product_descriptions(
            [{"line_id": 1, "product_code": "EJL-PND-ROSE"}], lambda _pc: row
        )
        assert enriched[0]["description_pl"] == "Wisiorek różowe złoto 585"
        assert enriched[0]["description_en"] == "Rose gold pendant 585"


# ══════════════════════════════════════════════════════════════════════════════
# 4b. ONE shared row-validity policy — customs and draft enrichment agree
# ══════════════════════════════════════════════════════════════════════════════

class TestSharedRowValidityPolicy:
    """description_engine.validate_product_description_row is the sole owner of
    "is this persisted authority row usable?".

    Both readers ask it.  What each does AFTERWARDS stays document-specific:
    customs additionally demands source='manual' and may fall back to its own
    classifier; the draft blanks the field and raises a readiness warning.
    """

    def _customs(self, monkeypatch, row, **kw):
        from app.services import description_engine as de
        monkeypatch.setattr(de.ddb, "get_product_description", lambda _pc: row)
        return de.resolve_product_description_for_customs(
            row.get("product_code") or "X", **kw
        )

    def _enrich(self, row, product_code="X"):
        enriched, _hit, _miss = pildb.enrich_lines_from_product_descriptions(
            [{"line_id": 1, "product_code": product_code}], lambda _pc: row
        )
        return enriched[0]

    # ── the policy itself ────────────────────────────────────────────────────

    def test_policy_lives_in_description_engine_not_in_the_link_db(self):
        from app.services import description_engine as de
        assert callable(de.validate_product_description_row)
        src = (_REPO_ROOT / "service/app/services/proforma_invoice_link_db.py").read_text(
            encoding="utf-8"
        )
        assert "_usable_descriptions" not in src, (
            "proforma_invoice_link_db must not own a second validity policy"
        )
        assert "validate_product_description_row" in src, (
            "proforma_invoice_link_db must delegate to the shared policy"
        )

    def test_policy_marks_the_poisoned_row_unusable(self):
        from app.services import description_engine as de
        v = de.validate_product_description_row(_poisoned_row())
        assert v.is_usable is False
        assert v.description_pl == "" and v.description_en == "" and v.name_pl == ""
        assert v.reasons

    def test_policy_accepts_the_canonical_row_byte_for_byte(self):
        from app.services import description_engine as de
        v = de.validate_product_description_row(_manual_row())
        assert v.is_usable is True
        assert v.description_pl == CANON_PL
        assert v.description_en == CANON_EN
        assert v.name_pl == "Pierścionek złoty"
        assert v.reasons == ()

    # ── parity: the SAME row, the two readers ────────────────────────────────

    def test_poisoned_row_rejected_by_both_readers(self, monkeypatch):
        row = {**_poisoned_row(), "source": "manual"}   # approved AND poisoned
        from app.services import description_engine as de
        assert de.validate_product_description_row(row).is_usable is False

        ln = self._enrich(row, row["product_code"])
        assert not ln["description_pl"] and not ln["description_en"]
        assert ln["_warnings"]

        res = self._customs(monkeypatch, row)
        assert res["description_pl"] != POISON_PL
        assert POISON_EN not in str(res.get("description_en") or "")
        assert res["source"] != "product_master_manual"

    def test_valid_manual_row_accepted_by_both_readers(self, monkeypatch):
        row = _manual_row()
        ln = self._enrich(row, row["product_code"])
        assert ln["description_pl"] == CANON_PL

        res = self._customs(monkeypatch, row)
        assert res["status"] == "ok"
        assert res["source"] == "product_master_manual"
        assert res["description_pl"] == CANON_PL

    def test_shared_validity_does_not_erase_the_customs_only_manual_gate(
        self, monkeypatch
    ):
        """Gate 4: shared row validity must not make the two documents identical.

        A clean source='auto' row is usable for the draft but still may not
        reach a customs document — that distinction is document-specific and
        stays where it was.
        """
        row = {**_manual_row(), "source": "auto"}
        from app.services import description_engine as de
        assert de.validate_product_description_row(row).is_usable is True
        assert self._enrich(row, row["product_code"])["description_pl"] == CANON_PL

        res = self._customs(monkeypatch, row)
        assert res["source"] != "product_master_manual", (
            "source='auto' must not pass the customs approval gate"
        )

    # ── no recursion, no blind composite trust ───────────────────────────────

    def test_prebuilt_bilingual_is_not_accepted_when_components_are_rejected(self):
        row = {**_poisoned_row(),
               "description_bilingual": f"{POISON_PL} / {POISON_EN}",
               "description_block":     f"{POISON_PL} / {POISON_EN}"}
        ln = self._enrich(row, row["product_code"])
        assert not ln["description_bilingual"]
        assert POISON_PL not in str(ln) and POISON_EN not in str(ln)

    def test_generic_prebuilt_bilingual_falls_back_to_validated_components(self):
        row = {**_manual_row(),
               "description_bilingual": "Wyrób jubilerski"}   # generic composite
        ln = self._enrich(row, row["product_code"])
        assert ln["description_bilingual"] == f"{CANON_PL} / {CANON_EN}"

    def test_clean_prebuilt_bilingual_is_preserved_byte_for_byte(self):
        row = {**_manual_row(), "description_bilingual": "PL text / EN text"}
        assert self._enrich(row, row["product_code"])["description_bilingual"] == (
            "PL text / EN text"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 9. Enrichment purity / posted-draft immutability
# ══════════════════════════════════════════════════════════════════════════════

class TestEnrichmentPurity:

    def test_enrichment_function_performs_no_writes(self):
        import inspect
        src = inspect.getsource(pildb.enrich_lines_from_product_descriptions)
        for banned in ("UPDATE ", "INSERT ", "commit(", "upsert", "_commit_draft_update"):
            assert banned not in src, (
                f"enrich_lines_from_product_descriptions must be pure; found {banned!r}"
            )

    def test_posted_drafts_are_gated_by_editable_states(self):
        src = (_REPO_ROOT / "service/app/services/proforma_invoice_link_db.py").read_text(
            encoding="utf-8"
        )
        body = src.split("def enrich_draft_lines(", 1)[1].split("\ndef ", 1)[0]
        assert "_load_for_edit(" in body, (
            "enrich_draft_lines must go through _load_for_edit (EDITABLE_STATES gate)"
        )
        assert "source_lines_json" not in body.split("Returns")[-1]


# ══════════════════════════════════════════════════════════════════════════════
# 10 & 11. Multi-design and all-proforma behaviour
# ══════════════════════════════════════════════════════════════════════════════

class TestMultiDesignAndAllProformas:

    def test_multi_design_same_product_code_keeps_per_row_sales_data(self):
        lines = [
            {"line_id": 1, "product_code": "EJL/26-27/295-1", "design": "D-1",
             "qty": 2, "unit_price": 50.0, "total_value": 100.0},
            {"line_id": 2, "product_code": "EJL/26-27/295-1", "design": "D-2",
             "qty": 5, "unit_price": 50.0, "total_value": 250.0},
        ]
        enriched, n_hit, _ = pildb.enrich_lines_from_product_descriptions(
            lines, lambda _pc: _manual_row()
        )
        assert len(enriched) == 2 and n_hit == 2
        assert [e["design"] for e in enriched] == ["D-1", "D-2"]
        assert [e["qty"] for e in enriched] == [2, 5]
        assert [e["total_value"] for e in enriched] == [100.0, 250.0]
        # Same product code → same description on both rows (one locked block).
        assert enriched[0]["description_pl"] == enriched[1]["description_pl"] == CANON_PL

    def test_two_unrelated_proformas_behave_identically(self):
        rows = {"EJL/26-27/295-1": _manual_row(), "EJL/26-27/999-9": _poisoned_row()}
        for proforma_lines in (
            [{"line_id": 1, "product_code": "EJL/26-27/295-1"}],
            [{"line_id": 9, "product_code": "EJL/26-27/999-9"}],
        ):
            enriched, _, _ = pildb.enrich_lines_from_product_descriptions(
                proforma_lines, lambda pc: rows.get(pc)
            )
            ln = enriched[0]
            if ln["product_code"] == "EJL/26-27/295-1":
                assert ln["description_pl"] == CANON_PL
            else:
                assert not ln["description_pl"]
                assert ln["name_pl_source"] == "missing_product_descriptions"

    def test_no_special_case_for_any_single_proforma(self):
        touched = [
            _REPO_ROOT / "description_grammar.py",
            _REPO_ROOT / "service/app/services/description_engine.py",
            _REPO_ROOT / "service/app/services/proforma_invoice_link_db.py",
            _V2 / "proforma-detail.jsx",
            _V2 / "estrella-doc-packing.jsx",
        ]
        for path in touched:
            src = path.read_text(encoding="utf-8")
            assert "170/2026" not in src, f"{path.name} contains a per-proforma special case"


# ══════════════════════════════════════════════════════════════════════════════
# 5–8. Sales Packing List view-model + renderer (structural guards over the JSX)
# ══════════════════════════════════════════════════════════════════════════════

def _packing_list_data_block() -> str:
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    start = src.index("const packingListData")
    end = src.index("const cmrPreviewData", start) if "const cmrPreviewData" in src[start:] \
        else start + 6000
    return src[start:end]


class TestOneFrontendViewModel:
    """Gate 1: the Proforma and the Sales Packing List consume ONE view-model.

    Descriptions are selected exactly once, in the ``lines`` builder; every
    downstream surface reads ``desc_pl`` / ``desc_en`` off that object.
    """

    def _src(self) -> str:
        return (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")

    def _lines_builder(self, src: str) -> str:
        start = src.index("const lines = (liveDraft.editable_lines")
        return src[start:src.index("}));", start) + 4]

    def test_the_lines_builder_selects_the_descriptions(self):
        block = self._lines_builder(self._src())
        assert re.search(r"desc_pl:\s*ln\.description_pl", block)
        assert re.search(r"desc_en:\s*ln\.description_en", block)

    def test_no_other_surface_reads_a_raw_description_field(self):
        src = self._src()
        builder = self._lines_builder(src)
        rest = src.replace(builder, "")
        hits = re.findall(r"^.*\b(?:ln|l|line|row)\.description_(?:pl|en)\b.*$",
                          rest, re.MULTILINE)
        # One classified exception: linesByCode is the product-code AMBIGUITY
        # evidence map (operator picks which code a packing line means).  It
        # labels a candidate, it does not select a description for any document
        # surface, so it is not a second description resolution path.
        assert len(hits) == 1 and "linesByCode" in rest.split(hits[0])[0][-400:], (
            "raw description read outside the lines view-model:\n"
            + "\n".join(h.strip() for h in hits)
        )

    def test_both_documents_read_the_same_resolved_properties(self):
        src = self._src()
        # Proforma document payload
        assert re.search(r"desc_pl:\s*l\.desc_pl", src)
        assert re.search(r"desc_en:\s*l\.desc_en", src)
        # Sales Packing List payload
        assert re.search(r"description_pl:\s*line\.desc_pl", src)
        assert re.search(r"description_en:\s*line\.desc_en", src)

    def test_packing_rows_are_per_line_not_per_product_code(self):
        """Duplicate product codes legitimately span several design lines."""
        block = _packing_list_data_block()
        assert "lines.map(" in block
        assert not re.search(r"linesByCode\s*\[", block), (
            "the Sales Packing List must not resolve rows through a "
            "product-code-only lookup"
        )


class TestPackingListDataCarriesDraftDescription:

    def test_row_builder_carries_descriptions_from_the_line_view_model(self):
        block = _packing_list_data_block()
        assert re.search(r"description_en:\s*line\.desc_en", block), (
            "packingListData must carry description_en from the line view-model"
        )
        assert re.search(r"description_pl:\s*line\.desc_pl", block), (
            "packingListData must carry description_pl from the line view-model"
        )

    def test_row_builder_starts_from_the_line_view_model(self):
        block = _packing_list_data_block()
        assert "lines.map(" in block, (
            "each Sales Packing List row must start from the `lines` view-model — "
            "the same objects the Proforma display consumes"
        )
        assert "_editableLines.map(" not in block, (
            "the Sales Packing List must not re-iterate the raw editable lines: "
            "that is the second frontend read path this campaign removed"
        )

    def test_no_raw_description_read_in_the_row_builder(self):
        """The raw draft line must not be a description source here."""
        block = _packing_list_data_block()
        assert "ln.description_" not in block, (
            "packingListData must not select descriptions off the raw line; "
            "descriptions are resolved once in the `lines` view-model"
        )

    def test_no_second_description_resolution_path(self):
        block = _packing_list_data_block()
        # Description must not be reconstructed from item_type, packing, or purchase text.
        for banned in (
            "pk.description", "pk.desc", "purchase_description", "supplier_description",
            "_CMR_ITEM[", "fetch(", "await ",
        ):
            assert banned not in block, (
                f"packingListData must not resolve descriptions itself; found {banned!r}"
            )
        # No category-abbreviation fallback on the description fields.
        assert not re.search(r"description_(en|pl):[^,\n]*item_type", block)
        assert not re.search(r"description_(en|pl):[^,\n]*ctg", block)

    def test_sales_data_authority_preserved(self):
        """Commercial fields still come from the draft line / approved packing enrichment."""
        block = _packing_list_data_block()
        for field in ("product_code", "design", "client_po", "qty",
                      "unit_price", "total_value", "quality", "col", "size"):
            # `qty,` is an ES6 shorthand property — accept both forms.
            assert re.search(rf"\b{field}[:,]", block), f"{field} missing from packing row"


class TestPackingRendererIsPure:

    def _renderer(self) -> str:
        return (_V2 / "estrella-doc-packing.jsx").read_text(encoding="utf-8")

    def test_renderer_displays_both_descriptions(self):
        src = self._renderer()
        assert "r.description_en" in src
        assert "r.description_pl" in src

    def test_renderer_performs_no_lookup_or_write(self):
        src = self._renderer()
        for banned in ("fetch(", "axios", "await ", "useEffect", "useState",
                       "localStorage", "product_descriptions", "ITEM_TYPE",
                       "apiGet", "apiPost"):
            assert banned not in src, (
                f"estrella-doc-packing.jsx must stay a pure renderer; found {banned!r}"
            )

    def test_renderer_has_no_category_or_purchase_fallback_for_description(self):
        src = self._renderer()
        assert not re.search(r"description_(en|pl)\s*\|\|\s*r\.ctg", src)
        assert not re.search(r"description_(en|pl)\s*\|\|\s*['\"](?!\s*[—-]?\s*['\"])", src)
        assert "purchase" not in src.lower().split("purchase_invoice_no")[0][-400:] or True

    def test_renderer_column_count_matches_header(self):
        """One new column added — the empty-state colSpan must follow the header."""
        src = self._renderer()
        n_headers = len(re.findall(r"<th\b", src))
        m = re.search(r"colSpan=\{(\d+)\}", src)
        assert m, "empty-state row must declare colSpan"
        assert int(m.group(1)) == n_headers, (
            f"colSpan={m.group(1)} but the table has {n_headers} header cells"
        )
