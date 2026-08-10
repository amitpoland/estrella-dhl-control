"""
test_row_material_persistence.py — material identity at production shape.

`test_multi_metal_descriptions.py` pins the parser and the two renderers as
units.  This file pins the thing an operator actually receives: the **persisted
row**.  It drives two real production functions, not helpers written for the
test —

  * `_try_invoice_from_authority_rows()` — a production parse site, reading a
    real batch layout off disk; and
  * `calculate_landed()` — the persistence boundary, where `nazwa_pl` /
    `nazwa_en` are RECOMPUTED from the item dict and the row is frozen.

That second point is the reason this file exists.  A repair that fixed only
`build_item_meta` would look green in every unit test and still ship the old
wording, because the names that reach `pz_rows.json` are not the ones the
parse site computed — they are rebuilt here, from whatever survived on the
item.  So the material handle has to reach this line, and the proof has to be
taken at this line.

Generic strings only: no draft id, no invoice number, no product code from any
real shipment is asserted anywhere (Lesson I — the defect is a workflow class).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import description_grammar as dg
import pz_import_processor as pz


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures — raw supplier grammar, no real identity
# ═══════════════════════════════════════════════════════════════════════════

RAW_GOLD_ONLY   = "PCS, 18KT Gold,LGD Gold Stud Jewell RING"
RAW_GOLD_PLAT   = "PCS, 18KT Gold,LGD Stud PT950 Com Jewell RING"
RAW_SILVER_GOLD = "PCS, SILVER Plain 10kt Gold Com Jewell RING"
RAW_SILVER_BARE = "PCS, SILVER Plain Jewell RING"
RAW_AMBIGUOUS   = "PCS, Fancy Jewell RING"

# What the OLD lossy chain wrote for these rows.  Kept as literal strings so a
# regression back to single-metal wording fails loudly rather than quietly.
LEGACY_DESC_EN  = "925 Silver Plain Jewellery RING"


def _row(pos: int, raw: str | None, *, desc_en: str = "", qty: float = 2.0,
         price: float = 50.0, item_type: str = "RING") -> dict:
    """One authority row as the customs-description chain persists it."""
    r = {
        "line_position":  pos,
        "quantity":       qty,
        "uom":            "PCS",
        "unit_price":     price,
        "line_total_usd": qty * price,
        "item_type":      item_type,
        "invoice_number": "TEST/2026-27/001",
        "description_en": desc_en or "Jewellery RING",
        "description_pl": "",
        "hsn_code":       "",
    }
    if raw is not None:
        r["source_description_raw"] = raw
    return r


def _batch(tmp_path: Path, rows: list) -> Path:
    """A minimal on-disk batch the authority bridge will accept."""
    fob = sum(r["line_total_usd"] for r in rows)
    audit = {
        "_pz_engine_authority_rows": rows,
        "_pz_engine_authority_meta": {
            "source":            "invoice_positions_authority",
            "captured_at":       "2026-08-10T00:00:00Z",
            "fob_sum_preserved": fob,
            "row_count":         len(rows),
        },
        "invoice_totals": {
            "total_fob_usd":       fob,
            "total_freight_usd":   fob * 0.02,
            "total_insurance_usd": 0.0,
            "total_cif_usd":       fob * 1.02,
        },
        "rows": [],
    }
    batch = tmp_path / "BATCH_MATERIAL"
    inv_dir = batch / "source" / "invoices"
    inv_dir.mkdir(parents=True)
    pdf = inv_dir / "inv.pdf"
    pdf.write_bytes(b"%PDF stub")
    (batch / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return pdf


# Duty is deliberately small against the smallest fixture invoice (one row,
# 100 USD): `calculate_landed` refuses a duty rate above 20% as a parser error,
# and a fixture must not stand on the wrong side of a production sanity guard.
_ZC429 = {"duty_pln": 5.0, "lrn": "TEST-LRN", "total_cif_usd": None}
_NBP   = {"usd_rate": 4.0}


def _persist(tmp_path: Path, rows: list):
    """Raw source text → parse site → persistence boundary → persisted rows.

    Returns `(persisted_rows, corrections_log)`.  Every assertion in this file
    is taken on the far side of this call, because that is where the operator's
    document is actually decided.
    """
    log: list = []
    pdf = _batch(tmp_path, rows)
    invoice = pz._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert invoice is not None, "authority bridge refused the fixture batch"
    persisted, _totals = pz.calculate_landed([invoice], _ZC429, _NBP, log)
    return persisted, log


# ═══════════════════════════════════════════════════════════════════════════
# 1. Provenance survives to the persisted row
# ═══════════════════════════════════════════════════════════════════════════

class TestProvenanceIsPersisted:

    def test_source_description_raw_reaches_every_row(self, tmp_path):
        rows, _ = _persist(tmp_path, [
            _row(1, RAW_GOLD_ONLY),
            _row(2, RAW_GOLD_PLAT),
            _row(3, RAW_SILVER_GOLD),
        ])
        assert [r["source_description_raw"] for r in rows] == [
            RAW_GOLD_ONLY, RAW_GOLD_PLAT, RAW_SILVER_GOLD,
        ]

    def test_persisted_raw_reproduces_the_same_components(self, tmp_path):
        """The point of persisting raw text: a later reader re-derives, never re-guesses.

        Re-parsing `source_description_raw` must give back exactly what the
        parse site saw.  Re-parsing `nazwa_en` — the generated field — is the
        lossy round-trip this campaign removes, and is deliberately not what
        any consumer is asked to do.
        """
        rows, _ = _persist(tmp_path, [_row(1, RAW_SILVER_GOLD)])
        again = dg.parse_material_components(rows[0]["source_description_raw"])
        assert [c.purity_key for c in again.components] == ["SILVER", "10KT"]
        assert again.construction == "combination"

    def test_construction_and_review_flag_are_persisted(self, tmp_path):
        rows, _ = _persist(tmp_path, [
            _row(1, RAW_GOLD_ONLY),
            _row(2, RAW_SILVER_GOLD),
            _row(3, RAW_AMBIGUOUS),
        ])
        assert [r["construction"] for r in rows] == [
            "single", "combination", "single",
        ]
        assert [r["description_review_required"] for r in rows] == [
            False, False, True,
        ]


class TestPersistedRowStaysSerialisable:
    """`parsed_material` is an in-memory handle. It must not leave the engine."""

    def test_handle_is_absent_from_persisted_rows(self, tmp_path):
        rows, _ = _persist(tmp_path, [_row(1, RAW_GOLD_PLAT)])
        assert "parsed_material" not in rows[0]

    def test_persisted_rows_are_json_serialisable(self, tmp_path):
        rows, _ = _persist(tmp_path, [
            _row(1, RAW_GOLD_ONLY), _row(2, RAW_SILVER_GOLD),
        ])
        json.dumps(rows)   # audit.json / the process route do exactly this

    def test_returned_invoice_items_are_json_serialisable(self, tmp_path):
        """`invoices` is part of the engine result and is serialised by callers."""
        log: list = []
        pdf = _batch(tmp_path, [_row(1, RAW_GOLD_PLAT)])
        invoice = pz._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
        pz.calculate_landed([invoice], _ZC429, _NBP, log)
        json.dumps(invoice)


# ═══════════════════════════════════════════════════════════════════════════
# 2. The persisted names keep every material the source stated
# ═══════════════════════════════════════════════════════════════════════════

class TestPersistedNamesKeepEveryMaterial:

    def test_gold_plus_platinum(self, tmp_path):
        rows, _ = _persist(tmp_path, [_row(1, RAW_GOLD_PLAT)])
        pl, en = rows[0]["nazwa_pl"], rows[0]["nazwa_en"]
        assert "złot" in pl and "platyn" in pl
        assert "18KT Gold" in en and "Platinum" in en
        assert rows[0]["nazwa"] == f"{pl} / {en}"

    def test_silver_plus_gold(self, tmp_path):
        rows, _ = _persist(tmp_path, [_row(1, RAW_SILVER_GOLD)])
        pl, en = rows[0]["nazwa_pl"], rows[0]["nazwa_en"]
        assert "srebr" in pl and "złot" in pl
        assert "Silver" in en and "10KT Gold" in en

    @pytest.mark.parametrize("raw", [RAW_GOLD_PLAT, RAW_SILVER_GOLD])
    def test_persisted_names_satisfy_the_completeness_invariant(self, tmp_path, raw):
        rows, _ = _persist(tmp_path, [_row(1, raw)])
        parsed = dg.parse_material_components(rows[0]["source_description_raw"])
        ok, reason = dg.check_material_completeness(
            parsed, rows[0]["nazwa_pl"], rows[0]["nazwa_en"]
        )
        assert ok is True, reason


class TestPersistedRowInventsNoPurity:
    """The source said SILVER. A persisted customs/accounting row may not say 925."""

    def test_bare_silver_alone(self, tmp_path):
        rows, _ = _persist(tmp_path, [_row(1, RAW_SILVER_BARE)])
        assert "925" not in rows[0]["nazwa"]
        assert "srebr" in rows[0]["nazwa_pl"]

    def test_bare_silver_beside_gold(self, tmp_path):
        rows, _ = _persist(tmp_path, [_row(1, RAW_SILVER_GOLD)])
        assert "925" not in rows[0]["nazwa"]

    def test_legacy_generated_text_does_not_reintroduce_purity(self, tmp_path):
        """A row whose RAW text says SILVER keeps its raw text as the authority.

        The generated `description_en` on the same row still carries the old
        "925" wording.  Raw source wins; the derived field is not consulted.
        """
        rows, _ = _persist(
            tmp_path, [_row(1, RAW_SILVER_BARE, desc_en=LEGACY_DESC_EN)]
        )
        assert "925" not in rows[0]["nazwa"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. One row may not contaminate another
# ═══════════════════════════════════════════════════════════════════════════

class TestNoCrossRowContamination:

    def test_neighbours_render_identically_alone_and_in_a_mixed_batch(self, tmp_path):
        mixed, _ = _persist(tmp_path / "mixed", [
            _row(1, RAW_GOLD_ONLY),
            _row(2, RAW_GOLD_PLAT),
            _row(3, RAW_SILVER_GOLD),
            _row(4, RAW_SILVER_BARE),
        ])
        for idx, raw in enumerate(
            [RAW_GOLD_ONLY, RAW_GOLD_PLAT, RAW_SILVER_GOLD, RAW_SILVER_BARE]
        ):
            alone, _ = _persist(tmp_path / f"alone{idx}", [_row(1, raw)])
            assert mixed[idx]["nazwa"] == alone[0]["nazwa"], (
                f"row {idx + 1} rendered differently beside its neighbours"
            )

    def test_reversing_row_order_reverses_output_and_changes_nothing_else(self, tmp_path):
        order = [RAW_GOLD_ONLY, RAW_GOLD_PLAT, RAW_SILVER_GOLD]
        fwd, _ = _persist(tmp_path / "f",
                          [_row(i, r) for i, r in enumerate(order, 1)])
        rev, _ = _persist(tmp_path / "r",
                          [_row(i, r) for i, r in enumerate(reversed(order), 1)])
        assert [r["nazwa"] for r in fwd] == [r["nazwa"] for r in rev][::-1]

    def test_every_row_keeps_its_own_raw_text(self, tmp_path):
        raws = [RAW_GOLD_ONLY, RAW_GOLD_PLAT, RAW_SILVER_GOLD, RAW_SILVER_BARE]
        rows, _ = _persist(tmp_path, [_row(i, r) for i, r in enumerate(raws, 1)])
        assert [r["source_description_raw"] for r in rows] == raws


# ═══════════════════════════════════════════════════════════════════════════
# 4. Rows written before this repair
# ═══════════════════════════════════════════════════════════════════════════

class TestLegacyRowsWithoutRawText:
    """No raw field exists on older authority rows. The fallback is named, not hidden."""

    def test_row_without_raw_still_renders_from_its_generated_text(self, tmp_path):
        rows, _ = _persist(tmp_path, [_row(1, None, desc_en=LEGACY_DESC_EN)])
        assert rows[0]["nazwa_pl"]
        assert rows[0]["nazwa_en"]

    def test_row_without_raw_records_the_text_it_fell_back_to(self, tmp_path):
        rows, _ = _persist(tmp_path, [_row(1, None, desc_en=LEGACY_DESC_EN)])
        assert rows[0]["source_description_raw"] == LEGACY_DESC_EN

    def test_legacy_stated_925_is_preserved_not_stripped(self, tmp_path):
        """Anti-over-correction: the row states SL925, so 925 is source-supported.

        This repair removes INVENTED purity.  It does not remove purity the
        text actually carries — that would be the same defect facing the other
        way.
        """
        rows, _ = _persist(tmp_path, [_row(1, "PCS, SL925 Silver Plain Jewell RING")])
        assert "925" in rows[0]["nazwa"]


# ═══════════════════════════════════════════════════════════════════════════
# 5. Operator breadcrumbs
# ═══════════════════════════════════════════════════════════════════════════

class TestCorrectionsLogBreadcrumbs:

    def test_combination_row_is_recorded_with_both_materials(self, tmp_path):
        _, log = _persist(tmp_path, [_row(1, RAW_SILVER_GOLD)])
        hits = [l for l in log if "Combination row" in l]
        assert hits, log
        assert "SILVER" in hits[0] and "10KT" in hits[0]

    def test_unreadable_material_is_surfaced_as_a_verify_gap(self, tmp_path):
        _, log = _persist(tmp_path, [_row(1, RAW_AMBIGUOUS)])
        assert any("[VERIFY-GAP]" in l and "Material composition" in l for l in log)

    def test_plain_single_metal_row_adds_no_noise(self, tmp_path):
        _, log = _persist(tmp_path, [_row(1, RAW_GOLD_ONLY)])
        assert not [l for l in log if "Combination row" in l or "[VERIFY-GAP]" in l]

    def test_no_row_is_reported_as_auto_corrected(self, tmp_path):
        """The deleted silver override logged a "correction" that WAS the defect."""
        _, log = _persist(tmp_path, [
            _row(1, RAW_SILVER_GOLD), _row(2, RAW_SILVER_BARE),
        ])
        assert not [l for l in log if "Auto-corrected silver" in l]
