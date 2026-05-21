"""Bridge Persistence (2026-05-21).

PR #269 invoice-position authority must survive the PZ engine's audit
rewrite so the bridge can fire on subsequent /process retries. This test
suite pins:

- audit_merge.PRESERVED_KEYS includes the new sidecar keys.
- _try_invoice_from_authority_rows prefers the sidecar over audit.rows.
- _try_invoice_from_authority_rows logs explicit [bridge_miss] reasons.
- merge_regenerated_audit preserves the sidecar when the engine result
  lacks it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import pz_import_processor as p
from service.app.services.audit_merge import (
    PRESERVED_KEYS,
    merge_regenerated_audit,
)


# ── Shared fixture helpers ────────────────────────────────────────────────

def _rows_10():
    """Same 10-position fixture as test_global_engine_authority_bridge."""
    return [
        {"line_position": i, "quantity": 1.0, "uom": "PCS", "line_total_usd": 100.0,
         "unit_price": 100.0, "item_type": "RING", "invoice_number": "088/2026-2027",
         "description_en": "925 Silver Plain Jewellery RINGS",
         "description_pl": "Pierścionki ze srebra próby 925", "hsn_code": ""}
        for i in range(1, 11)
    ]


def _audit_with_sidecar(rows):
    return {
        # Note: _rows_source NOT set — proves the sidecar wins on its own.
        "_pz_engine_authority_rows": rows,
        "_pz_engine_authority_meta": {
            "source":            "invoice_positions_authority",
            "captured_at":       "2026-05-21T20:00:00Z",
            "fob_sum_preserved": 1000.0,
            "row_count":         len(rows),
        },
        "invoice_totals": {
            "total_fob_usd":       1000.0,
            "total_freight_usd":   50.0,
            "total_insurance_usd": 10.0,
            "total_cif_usd":       1060.0,
        },
        # audit.rows deliberately empty — only sidecar provides authority.
        "rows": [],
    }


def _audit_with_fresh_regen(rows):
    return {
        "_rows_source": "invoice_positions_authority",
        "_customs_aggregation": {"fob_sum_preserved": 1000.0,
                                  "source": "commercial_invoice_lines",
                                  "position_count": len(rows)},
        "invoice_totals": {
            "total_fob_usd":       1000.0,
            "total_freight_usd":   50.0,
            "total_insurance_usd": 10.0,
            "total_cif_usd":       1060.0,
        },
        "rows": rows,
    }


def _layout(tmp_path: Path, audit: dict) -> Path:
    batch = tmp_path / "BATCH_X"
    inv_dir = batch / "source" / "invoices"
    inv_dir.mkdir(parents=True)
    pdf = inv_dir / "inv.pdf"
    pdf.write_bytes(b"%PDF stub")
    (batch / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return pdf


# ── 1. Sidecar is preferred over audit.rows ───────────────────────────────
def test_bridge_prefers_sidecar_over_audit_rows(tmp_path):
    rows = _rows_10()
    audit = _audit_with_sidecar(rows)
    # Add a competing audit.rows that should be IGNORED. The legacy regex
    # path would have used these; the sidecar must win.
    audit["rows"] = [
        {"line_position": 1, "quantity": 999.0, "uom": "PCS",
         "line_total_usd": 99999.0, "invoice_number": "WRONG"},
    ]
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert res is not None
    assert len(res["items"]) == 10
    # Sidecar invoice_number wins; the competing single row is ignored.
    assert res["invoice_no"] == "088/2026-2027"
    # bridge_hit log emitted with source label
    assert any("[bridge_hit]" in l and "sidecar:_pz_engine_authority_rows" in l for l in log)


# ── 2. Falls back to audit.rows when sidecar absent ───────────────────────
def test_bridge_falls_back_to_audit_rows_when_sidecar_absent(tmp_path):
    rows = _rows_10()
    audit = _audit_with_fresh_regen(rows)
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert res is not None
    assert len(res["items"]) == 10
    assert any("[bridge_hit]" in l and "audit.rows (fresh regen)" in l for l in log)


# ── 3. Explicit bridge_miss reason when audit missing ─────────────────────
def test_bridge_miss_reason_audit_file_absent(tmp_path):
    pdf = tmp_path / "BATCH_X" / "source" / "invoices" / "inv.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"stub")
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None
    assert any("[bridge_miss]" in l and "reason=audit_file_absent" in l for l in log)


# ── 4. Explicit bridge_miss reason when no authority source ───────────────
def test_bridge_miss_reason_no_authority_source(tmp_path):
    # audit present but neither sidecar nor _rows_source authority set
    audit = {"rows": [{"quantity": 1, "line_total_usd": 1}], "invoice_totals": {}}
    pdf = _layout(tmp_path, audit)
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None
    assert any("[bridge_miss]" in l and "reason=no_authority_source" in l for l in log)


# ── 5. PRESERVED_KEYS contract ────────────────────────────────────────────
def test_preserved_keys_includes_sidecar_entries():
    assert "_pz_engine_authority_rows" in PRESERVED_KEYS
    assert "_pz_engine_authority_meta" in PRESERVED_KEYS


# ── 6. merge_regenerated_audit preserves sidecar across engine writes ────
def test_merge_preserves_sidecar_when_engine_result_lacks_it():
    rows = _rows_10()
    meta = {"source": "invoice_positions_authority",
            "captured_at": "2026-05-21T20:00:00Z",
            "fob_sum_preserved": 1000.0, "row_count": len(rows)}
    existing = {
        "_pz_engine_authority_rows": rows,
        "_pz_engine_authority_meta": meta,
        "rows": rows,
        "polish_desc_filename": "POLISH_DESC_X.pdf",
    }
    # Engine regenerated output — has its own rows + no awareness of sidecar
    regenerated = {
        "rows": [{"quantity": 5, "engine_pipeline": True}],
        "totals": {"net": 100},
        "status": "success",
    }
    merged = merge_regenerated_audit(existing, regenerated)
    # Sidecar preserved verbatim
    assert merged["_pz_engine_authority_rows"] == rows
    assert merged["_pz_engine_authority_meta"] == meta
    # audit.rows replaced by engine output (REGENERATED_KEYS behaviour)
    assert merged["rows"] != rows


# ── 7. Sidecar with malformed data falls through cleanly ──────────────────
def test_bridge_miss_when_sidecar_present_but_invalid(tmp_path):
    audit = _audit_with_sidecar(_rows_10())
    # Corrupt sidecar with a zero-qty row
    audit["_pz_engine_authority_rows"][0]["quantity"] = 0
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert res is None
    assert any("validation_failed" in l for l in log)
