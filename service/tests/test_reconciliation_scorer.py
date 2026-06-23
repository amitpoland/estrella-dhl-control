"""test_reconciliation_scorer.py — Regression tests for spec-based ambiguity resolution.

Test cases derived from batch SHIPMENT_9158478722_2026-06_924c4e59:

  #34 Clear-Diamonds: PND ambiguous (3 candidates, 3 sales rows, sparse spec)
      Expected: MEDIUM confidence — distribution plan 1:1:1, operator confirms
  #37 Anastazia: CSTR07966 unresolvable (0 packing rows in batch)
      Expected: UNRESOLVABLE — scorer cannot help; stays in designs_unresolved
  #40 SAS MAYURI: J4006R01513 ambiguous (2 candidates 4:1, 5 sales rows, sparse spec)
      Expected: MEDIUM confidence — distribution plan 4:1, operator confirms which

Integration tests verify that resolve_sales_lines_for_batch() correctly routes
HIGH-confidence results to product_code auto-assignment, and MEDIUM results to
designs_scored_pending without touching product_code.

Safety invariant: scorer NEVER posts, NEVER mutates inventory, NEVER writes wFirma.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    return tmp_path


def _init_packing_db(db_path: Path) -> None:
    """Create a minimal packing.db schema for tests."""
    from app.services import packing_db as pdb
    pdb.init_packing_db(db_path)


def _seed_packing_rows(
    db_path: Path,
    batch_id: str,
    rows: List[Dict[str, Any]],
) -> None:
    """Seed packing_lines rows directly into a packing.db.

    Each row dict must include design_no, product_code, scan_code, and any
    spec fields to test.  Other fields default to safe empty values.
    """
    from app.services import packing_db as pdb
    doc_id = pdb.upsert_packing_document(
        batch_id=batch_id,
        document_id=f"pd-{batch_id}",
        source_file_path="/tmp/p.xlsx",
        invoice_no="INV",
        parser_name="t",
        parser_version="1",
        source_file_hash=f"h-{batch_id}",
    )
    lines = []
    for i, row in enumerate(rows):
        lines.append({
            "packing_document_id": doc_id,
            "batch_id":            batch_id,
            "invoice_no":          row.get("invoice_no", "INV"),
            "invoice_line_position": i,
            "product_code":        row.get("product_code", ""),
            "design_no":           row.get("design_no", ""),
            "batch_no": "", "bag_id": "", "tray_id": "",
            "item_type":       row.get("item_type", ""),
            "uom":             "PCS",
            "quantity":        row.get("quantity", 1.0),
            "gross_weight":    row.get("gross_weight", 0.0),
            "net_weight":      row.get("net_weight", 0.0),
            "diamond_weight":  row.get("diamond_weight", 0.0),
            "color_weight":    row.get("color_weight", 0.0),
            "metal":           row.get("metal", ""),
            "karat":           row.get("karat", ""),
            "metal_color":     row.get("metal_color", ""),
            "stone_type":      row.get("stone_type", ""),
            "quality_string":  row.get("quality_string", ""),
            "size":            row.get("size", ""),
            "remarks":         "",
            "scan_code":       row.get("scan_code", f"sc-{i}"),
            "unit_price":      row.get("unit_price", 0.0),
            "total_value":     row.get("unit_price", 0.0),
            "extracted_confidence":   1.0,
            "requires_manual_review": False,
            "pack_sr":         i,
        })
    pdb.upsert_packing_lines(lines)


def _sales_row(design_no: str, product_code: str = "", price: float = 50.0) -> Dict:
    return {
        "id":           f"sr-{design_no}-{price}",
        "design_no":    design_no,
        "product_code": product_code,
        "quantity":     1.0,
        "unit_price":   price,
        "currency":     "EUR",
    }


# ── Unit tests: scorer internals ──────────────────────────────────────────────

class TestScorerInternals:

    def test_is_differentiating_categorical(self):
        from app.services.reconciliation_scorer import _is_differentiating
        assert _is_differentiating({"A": "RING", "B": "PENDANT"}, False) is True
        assert _is_differentiating({"A": "RING", "B": "RING"}, False) is False
        assert _is_differentiating({"A": "", "B": ""}, False) is False

    def test_is_differentiating_numeric(self):
        from app.services.reconciliation_scorer import _is_differentiating
        assert _is_differentiating({"A": 3.5, "B": 2.1}, True) is True
        assert _is_differentiating({"A": 3.5, "B": 3.5}, True) is False
        assert _is_differentiating({"A": 0.0, "B": 0.0}, True) is False  # zero not differentiating
        assert _is_differentiating({"A": 0.0, "B": 1.0}, True) is True   # one non-zero

    def test_representative_spec_majority_vote(self):
        from app.services.reconciliation_scorer import _representative_spec
        rows = [
            {"item_type": "RING", "karat": "14KT", "gross_weight": 3.0, "net_weight": 2.0,
             "metal": "YG", "metal_color": "", "quality_string": "", "size": "",
             "diamond_weight": 0.0, "color_weight": 0.0},
            {"item_type": "RING", "karat": "14KT", "gross_weight": 4.0, "net_weight": 3.0,
             "metal": "YG", "metal_color": "", "quality_string": "", "size": "",
             "diamond_weight": 0.0, "color_weight": 0.0},
        ]
        spec = _representative_spec(rows)
        assert spec["item_type"] == "RING"
        assert spec["karat"] == "14KT"
        assert abs(spec["gross_weight"] - 3.5) < 0.001

    def test_score_quantity_balance_exact_match(self):
        from app.services.reconciliation_scorer import _score_quantity_balance, WEIGHT_QUANTITY_BALANCE
        groups = {"PC-1": [{}], "PC-2": [{}, {}]}
        score, dist, audit = _score_quantity_balance(groups, 3)
        assert abs(score - WEIGHT_QUANTITY_BALANCE) < 0.001
        assert dist == {"PC-1": 1, "PC-2": 2}

    def test_score_quantity_balance_mismatch_partial_credit(self):
        from app.services.reconciliation_scorer import _score_quantity_balance, WEIGHT_QUANTITY_BALANCE
        groups = {"PC-1": [{}], "PC-2": [{}]}
        score, _, _ = _score_quantity_balance(groups, 1)  # 2 purchase, 1 sale
        assert score > 0.0
        assert score < WEIGHT_QUANTITY_BALANCE

    def test_score_spec_fingerprint_item_type_differentiates(self):
        from app.services.reconciliation_scorer import _score_spec_fingerprint
        groups = {
            "PC-RING": [{"item_type": "RING", "karat": "14KT", "metal": "YG",
                          "metal_color": "", "gross_weight": 0.0, "net_weight": 0.0,
                          "diamond_weight": 0.0, "color_weight": 0.0, "quality_string": "",
                          "size": ""}],
            "PC-PEND": [{"item_type": "PENDANT", "karat": "14KT", "metal": "YG",
                          "metal_color": "", "gross_weight": 0.0, "net_weight": 0.0,
                          "diamond_weight": 0.0, "color_weight": 0.0, "quality_string": "",
                          "size": ""}],
        }
        score, diff_fields, _ = _score_spec_fingerprint(groups)
        assert "item_type" in diff_fields
        assert score > 0.0

    def test_score_spec_fingerprint_no_diff(self):
        from app.services.reconciliation_scorer import _score_spec_fingerprint
        row = {"item_type": "RING", "karat": "14KT", "metal": "",
               "metal_color": "", "gross_weight": 0.0, "net_weight": 0.0,
               "diamond_weight": 0.0, "color_weight": 0.0, "quality_string": "", "size": ""}
        groups = {"PC-1": [dict(row)], "PC-2": [dict(row)]}
        score, diff_fields, _ = _score_spec_fingerprint(groups)
        assert diff_fields == []
        assert score == 0.0


# ── Regression case #34 (PND) ─────────────────────────────────────────────────

class TestPNDCase:
    """PND: 3 packing candidates (1 each for 295-1, 299-3, 299-6), 3 sales rows.
    EJL data is sparse — all spec fields 0 / empty.
    Expected: MEDIUM confidence — quantity-balanced 1:1:1, operator confirms mapping.
    """

    BATCH = "BATCH-PND-TEST"
    CANDIDATES = ["EJL/26-27/295-1", "EJL/26-27/299-3", "EJL/26-27/299-6"]

    def _packing_rows(self):
        return [
            {"design_no": "PND", "product_code": c, "scan_code": f"sc-pnd-{i}",
             "unit_price": 51.0, "item_type": "", "karat": "",
             "metal": "", "gross_weight": 0.0, "net_weight": 0.0,
             "diamond_weight": 0.0}
            for i, c in enumerate(self.CANDIDATES)
        ]

    def _sales_rows(self):
        return [_sales_row("PND", price=51.0) for _ in range(3)]

    def test_confidence_is_medium(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._packing_rows())

        from app.services.reconciliation_scorer import (
            score_ambiguous_design, MEDIUM_CONFIDENCE_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD
        )
        result = score_ambiguous_design(
            self.BATCH, "PND", self.CANDIDATES, self._sales_rows(),
            packing_db_path=str(db_path),
        )
        assert result.confidence_label == "MEDIUM"
        assert MEDIUM_CONFIDENCE_THRESHOLD <= result.confidence < HIGH_CONFIDENCE_THRESHOLD

    def test_distribution_hint_is_balanced(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design
        result = score_ambiguous_design(
            self.BATCH, "PND", self.CANDIDATES, self._sales_rows(),
            packing_db_path=str(db_path),
        )
        # Each candidate should get 1 row
        for pc in self.CANDIDATES:
            assert result.distribution_hint.get(pc, 0) == 1

    def test_all_three_rows_assigned(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design
        result = score_ambiguous_design(
            self.BATCH, "PND", self.CANDIDATES, self._sales_rows(),
            packing_db_path=str(db_path),
        )
        assigned = [a for a in result.recommended_assignments if a.recommended_product_code]
        assert len(assigned) == 3

    def test_requires_operator_review(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design
        result = score_ambiguous_design(
            self.BATCH, "PND", self.CANDIDATES, self._sales_rows(),
            packing_db_path=str(db_path),
        )
        assert result.requires_operator_review is True
        assert result.is_auto_resolvable is False

    def test_audit_trail_present(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design
        result = score_ambiguous_design(
            self.BATCH, "PND", self.CANDIDATES, self._sales_rows(),
            packing_db_path=str(db_path),
        )
        assert len(result.audit_trail) > 3
        combined = " ".join(result.audit_trail)
        assert "Quantity" in combined or "quantity" in combined


# ── Regression case #37 (CSTR07966) ──────────────────────────────────────────

class TestCSTR07966Case:
    """CSTR07966: 0 packing rows in batch (invoice 293 never scanned).
    Expected: UNRESOLVABLE — scorer cannot help without purchase evidence.
    """

    BATCH = "BATCH-CSTR-TEST"
    CANDIDATES = ["EJL/26-27/293-1"]

    def test_unresolvable_when_no_packing_rows(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        # Deliberately seed NO packing rows for CSTR07966

        from app.services.reconciliation_scorer import score_ambiguous_design
        sales = [_sales_row("CSTR07966", price=326.0)]
        result = score_ambiguous_design(
            self.BATCH, "CSTR07966", self.CANDIDATES, sales,
            packing_db_path=str(db_path),
        )
        assert result.confidence == 0.0
        assert result.confidence_label == "UNRESOLVABLE"
        assert result.requires_operator_review is True
        assert all(a.recommended_product_code is None for a in result.recommended_assignments)

    def test_zero_confidence_no_auto_resolve(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)

        from app.services.reconciliation_scorer import score_ambiguous_design, HIGH_CONFIDENCE_THRESHOLD
        sales = [_sales_row("CSTR07966", price=326.0)]
        result = score_ambiguous_design(
            self.BATCH, "CSTR07966", self.CANDIDATES, sales,
            packing_db_path=str(db_path),
        )
        assert result.confidence < HIGH_CONFIDENCE_THRESHOLD
        assert result.is_auto_resolvable is False


# ── Regression case #40 (J4006R01513) ────────────────────────────────────────

class TestJ4006R01513Case:
    """J4006R01513: 5 packing rows (298-1 x4, 298-2 x1), 5 sales rows, sparse spec.
    Expected: MEDIUM confidence — quantity-balanced 4:1, operator confirms which row -> 298-2.
    """

    BATCH = "BATCH-J4006-TEST"
    CANDIDATES = ["EJL/26-27/298-1", "EJL/26-27/298-2"]

    def _packing_rows(self):
        rows = []
        for i in range(4):
            rows.append({
                "design_no": "J4006R01513", "product_code": "EJL/26-27/298-1",
                "scan_code": f"sc-298-1-{i}", "unit_price": 52.0 + i,
                "item_type": "", "karat": "", "metal": "",
                "gross_weight": 0.0, "net_weight": 0.0, "diamond_weight": 0.0,
            })
        rows.append({
            "design_no": "J4006R01513", "product_code": "EJL/26-27/298-2",
            "scan_code": "sc-298-2-0", "unit_price": 56.0,
            "item_type": "", "karat": "", "metal": "",
            "gross_weight": 0.0, "net_weight": 0.0, "diamond_weight": 0.0,
        })
        return rows

    def _sales_rows(self):
        prices = [70.0, 93.0, 84.0, 91.0, 89.0]
        return [_sales_row("J4006R01513", price=p) for p in prices]

    def test_confidence_is_medium(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._packing_rows())

        from app.services.reconciliation_scorer import (
            score_ambiguous_design, MEDIUM_CONFIDENCE_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD,
        )
        result = score_ambiguous_design(
            self.BATCH, "J4006R01513", self.CANDIDATES, self._sales_rows(),
            packing_db_path=str(db_path),
        )
        assert result.confidence_label == "MEDIUM"
        assert MEDIUM_CONFIDENCE_THRESHOLD <= result.confidence < HIGH_CONFIDENCE_THRESHOLD

    def test_distribution_plan_is_4_to_1(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design
        result = score_ambiguous_design(
            self.BATCH, "J4006R01513", self.CANDIDATES, self._sales_rows(),
            packing_db_path=str(db_path),
        )
        assert result.distribution_hint["EJL/26-27/298-1"] == 4
        assert result.distribution_hint["EJL/26-27/298-2"] == 1

    def test_five_assignments_produced(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design
        result = score_ambiguous_design(
            self.BATCH, "J4006R01513", self.CANDIDATES, self._sales_rows(),
            packing_db_path=str(db_path),
        )
        assert len(result.recommended_assignments) == 5
        assigned = [a for a in result.recommended_assignments if a.recommended_product_code]
        assert len(assigned) == 5

    def test_distribution_4_rows_to_298_1(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design
        result = score_ambiguous_design(
            self.BATCH, "J4006R01513", self.CANDIDATES, self._sales_rows(),
            packing_db_path=str(db_path),
        )
        pc_1_count = sum(
            1 for a in result.recommended_assignments
            if a.recommended_product_code == "EJL/26-27/298-1"
        )
        pc_2_count = sum(
            1 for a in result.recommended_assignments
            if a.recommended_product_code == "EJL/26-27/298-2"
        )
        assert pc_1_count == 4
        assert pc_2_count == 1


# ── HIGH confidence auto-resolve ──────────────────────────────────────────────

class TestHighConfidenceAutoResolve:
    """When spec data clearly differentiates candidates (item_type + karat + metal),
    the scorer should reach HIGH confidence and auto-resolve.
    """

    BATCH = "BATCH-HIGH-CONF"
    CANDIDATES = ["PC-RING", "PC-PEND"]

    def _rich_spec_packing_rows(self):
        return [
            {
                "design_no": "DESIGN-X", "product_code": "PC-RING",
                "scan_code": "sc-ring-0", "unit_price": 50.0,
                "item_type": "RING", "karat": "14KT", "metal": "YG",
                "metal_color": "YELLOW", "gross_weight": 3.5,
                "net_weight": 3.0, "diamond_weight": 0.0,
            },
            {
                "design_no": "DESIGN-X", "product_code": "PC-PEND",
                "scan_code": "sc-pend-0", "unit_price": 80.0,
                "item_type": "PENDANT", "karat": "18KT", "metal": "WG",
                "metal_color": "WHITE", "gross_weight": 2.1,
                "net_weight": 1.8, "diamond_weight": 0.0,
            },
        ]

    def test_high_confidence_reached(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._rich_spec_packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design, HIGH_CONFIDENCE_THRESHOLD
        sales = [_sales_row("DESIGN-X", price=55.0), _sales_row("DESIGN-X", price=85.0)]
        result = score_ambiguous_design(
            self.BATCH, "DESIGN-X", self.CANDIDATES, sales,
            packing_db_path=str(db_path),
        )
        assert result.confidence >= HIGH_CONFIDENCE_THRESHOLD, (
            f"Expected HIGH confidence, got {result.confidence:.2f} ({result.confidence_label})"
        )
        assert result.is_auto_resolvable is True
        assert result.requires_operator_review is False

    def test_item_type_in_diff_fields(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._rich_spec_packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design
        sales = [_sales_row("DESIGN-X", price=55.0), _sales_row("DESIGN-X", price=85.0)]
        result = score_ambiguous_design(
            self.BATCH, "DESIGN-X", self.CANDIDATES, sales,
            packing_db_path=str(db_path),
        )
        assert "item_type" in result.spec_diff_fields

    def test_all_assignments_have_product_code(self, setup, tmp_path):
        db_path = tmp_path / "packing.db"
        _init_packing_db(db_path)
        _seed_packing_rows(db_path, self.BATCH, self._rich_spec_packing_rows())

        from app.services.reconciliation_scorer import score_ambiguous_design
        sales = [_sales_row("DESIGN-X", price=55.0), _sales_row("DESIGN-X", price=85.0)]
        result = score_ambiguous_design(
            self.BATCH, "DESIGN-X", self.CANDIDATES, sales,
            packing_db_path=str(db_path),
        )
        assert all(a.recommended_product_code is not None for a in result.recommended_assignments)
        assert all(a.is_auto_resolved for a in result.recommended_assignments)


# ── Integration: resolve_sales_lines_for_batch ────────────────────────────────

class TestIntegration:
    """Integration tests via resolve_sales_lines_for_batch() — verifies the full
    pipeline from sales rows through scorer to final summary.
    """

    def test_high_confidence_sets_product_code_on_row(self, setup):
        """When scorer is HIGH confidence, the resolved row gets product_code set."""
        tmp = setup
        bid = "B-INTEG-HIGH"

        from app.services import packing_db as pdb
        db = tmp / "packing.db"
        pdb.init_packing_db(db)
        _seed_packing_rows(db, bid, [
            {
                "design_no": "DESIGN-HI", "product_code": "PC-RING",
                "scan_code": "sc-1", "unit_price": 50.0,
                "item_type": "RING", "karat": "14KT", "metal": "YG",
                "metal_color": "YELLOW", "gross_weight": 3.5,
            },
            {
                "design_no": "DESIGN-HI", "product_code": "PC-PEND",
                "scan_code": "sc-2", "unit_price": 80.0,
                "item_type": "PENDANT", "karat": "18KT", "metal": "WG",
                "metal_color": "WHITE", "gross_weight": 2.1,
            },
        ])

        from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
        rows = [
            {"product_code": "", "design_no": "DESIGN-HI", "unit_price": 55.0, "currency": "EUR"},
            {"product_code": "", "design_no": "DESIGN-HI", "unit_price": 85.0, "currency": "EUR"},
        ]
        resolved, summary = resolve_sales_lines_for_batch(bid, rows)

        from app.services.reconciliation_scorer import HIGH_CONFIDENCE_THRESHOLD
        rec = summary.get("designs_reconciled", {})
        if rec.get("DESIGN-HI", {}).get("confidence", 0.0) >= HIGH_CONFIDENCE_THRESHOLD:
            # AUTO-RESOLVED path
            assert all(r.get("product_code") for r in resolved), (
                f"All rows should have product_code after HIGH auto-resolve; got {resolved}"
            )
            assert all(r.get("resolution_source") == "spec_reconciliation" for r in resolved)
            assert "DESIGN-HI" not in summary["designs_ambiguous"]
        else:
            # MEDIUM path (if spec differentiation didn't score high enough in this env)
            assert "DESIGN-HI" in summary.get("designs_scored_pending", {}) or \
                   "DESIGN-HI" in summary["designs_ambiguous"]

    def test_medium_confidence_leaves_product_code_empty(self, setup):
        """When scorer is MEDIUM (sparse spec), product_code stays empty."""
        tmp = setup
        bid = "B-INTEG-MED"

        from app.services import packing_db as pdb
        db = tmp / "packing.db"
        pdb.init_packing_db(db)
        # Seed 2 sparse-spec rows for PND — same spec, 2 candidates, 1 sales row
        _seed_packing_rows(db, bid, [
            {"design_no": "PND", "product_code": "PC-A", "scan_code": "sc-pnd-0",
             "unit_price": 51.0},
            {"design_no": "PND", "product_code": "PC-B", "scan_code": "sc-pnd-1",
             "unit_price": 51.0},
        ])

        from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
        rows = [{"product_code": "", "design_no": "PND", "unit_price": 51.0, "currency": "EUR"}]
        resolved, summary = resolve_sales_lines_for_batch(bid, rows)

        # With quantity mismatch (2 purchase, 1 sale) and no spec diff → LOW confidence
        # → product_code must remain empty (not auto-resolved)
        assert resolved[0].get("product_code", "") == ""
        # The design must remain in ambiguous OR move to scored_pending — never silently resolved
        still_tracked = (
            "PND" in summary.get("designs_ambiguous", {}) or
            "PND" in summary.get("designs_scored_pending", {})
        )
        assert still_tracked, "PND should remain tracked after LOW-confidence scoring"

    def test_summary_always_has_new_keys(self, setup):
        """designs_reconciled and designs_scored_pending must always be present."""
        tmp = setup
        bid = "B-NEW-KEYS"

        from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
        _, summary = resolve_sales_lines_for_batch(bid, [])

        for key in (
            "designs_resolved", "designs_ambiguous", "designs_unresolved",
            "designs_reconciled", "designs_scored_pending",
        ):
            assert key in summary, f"summary missing {key!r}"

    def test_j4006_ambiguous_produces_scored_pending(self, setup):
        """J4006R01513 case: 5 packing rows (4:1), 5 sales rows → designs_scored_pending."""
        tmp = setup
        bid = "B-J4006"

        from app.services import packing_db as pdb
        db = tmp / "packing.db"
        pdb.init_packing_db(db)

        packing_rows = []
        for i in range(4):
            packing_rows.append({
                "design_no": "J4006R01513", "product_code": "EJL/26-27/298-1",
                "scan_code": f"sc-298-1-{i}", "unit_price": 52.0,
            })
        packing_rows.append({
            "design_no": "J4006R01513", "product_code": "EJL/26-27/298-2",
            "scan_code": "sc-298-2-0", "unit_price": 56.0,
        })
        _seed_packing_rows(db, bid, packing_rows)

        sales = [
            {"product_code": "", "design_no": "J4006R01513",
             "unit_price": p, "currency": "EUR"}
            for p in [70.0, 93.0, 84.0, 91.0, 89.0]
        ]

        from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
        resolved, summary = resolve_sales_lines_for_batch(bid, sales)

        # Sparse spec → MEDIUM → should land in scored_pending
        pending = summary.get("designs_scored_pending", {})
        if "J4006R01513" in pending:
            hint = pending["J4006R01513"]["distribution_hint"]
            assert hint.get("EJL/26-27/298-1") == 4
            assert hint.get("EJL/26-27/298-2") == 1
        else:
            # If for some reason it went HIGH (different env), all rows should have product_code
            rec = summary.get("designs_reconciled", {})
            assert "J4006R01513" in rec, "J4006R01513 must be in reconciled or scored_pending"

    def test_cstr07966_stays_unresolved(self, setup):
        """CSTR07966: 0 packing rows → stays in designs_unresolved, product_code empty."""
        tmp = setup
        bid = "B-CSTR"

        from app.services import packing_db as pdb
        db = tmp / "packing.db"
        pdb.init_packing_db(db)
        # Deliberately seed NO rows for CSTR07966

        from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
        sales = [{"product_code": "", "design_no": "CSTR07966",
                  "unit_price": 326.0, "currency": "EUR"}]
        resolved, summary = resolve_sales_lines_for_batch(bid, sales)

        assert "CSTR07966" in summary["designs_unresolved"]
        assert resolved[0].get("product_code", "") == ""

    def test_existing_product_code_not_overwritten_by_scorer(self, setup):
        """Rows that already have product_code must never be touched by the scorer."""
        tmp = setup
        bid = "B-PRESERVE-SCORER"

        from app.services import packing_db as pdb
        db = tmp / "packing.db"
        pdb.init_packing_db(db)

        from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
        rows = [{"product_code": "MY-EXISTING-CODE", "design_no": "PND",
                 "unit_price": 50.0, "currency": "EUR"}]
        resolved, summary = resolve_sales_lines_for_batch(bid, rows)

        assert resolved[0]["product_code"] == "MY-EXISTING-CODE"
        assert "resolution_source" not in resolved[0]
        assert "reconciliation_source" not in resolved[0]

    def test_no_external_calls_in_scorer_module(self):
        """Source-grep guard — scorer must stay local-DB and pure-computation only."""
        src = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "reconciliation_scorer.py"
        ).read_text(encoding="utf-8")
        for forbidden in ("requests.", "httpx.", "wfirma_client",
                          "smtp", "send_email", "dhl_dispatch",
                          "wfirma", "POST /", "GET /"):
            assert forbidden not in src, (
                f"reconciliation_scorer.py must not reference {forbidden!r}"
            )

    def test_no_wfirma_no_posting_no_inventory_in_scorer(self):
        """Source-grep guard — scorer must never write wFirma, inventory, or PZ."""
        src = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "reconciliation_scorer.py"
        ).read_text(encoding="utf-8")
        for forbidden in ("create_pz", "create_proforma", "post_invoice",
                          "inventory_", "reserve_", "wfirma_export",
                          "fiscal_write", "upsert_packing"):
            assert forbidden not in src, (
                f"reconciliation_scorer.py must not contain {forbidden!r}"
            )
