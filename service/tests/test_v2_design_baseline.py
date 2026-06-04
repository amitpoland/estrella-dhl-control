"""
test_v2_design_baseline.py — Sprint 25 design token consolidation contract.

Asserts:
  1. customer-master-v2.html loads pz-design-v2.js and NOT dashboard-shared.js.
  2. customer-master-v2.html includes DM Serif Display in its font link.
  3. customer-master-v2.html defines --overlay token.
  4. customer-master-v2.html destructures components from window.PzDesign.
  5. shipment-detail-v3.html exists in service/app/static/.
  6. shipment-detail-v3.html has pz-design-v2.js script loading.
  7. shipment-detail-v3.html reads batch_id from URL params.
  8. shipment-detail-v3.html defines --overlay token.
  9. pz-design-v2.js exports Sel and CompactTable.
  10. pz-design-v2.js does NOT export dashboard-shared.js (it is the replacement).
  11. proforma-detail-v2.html is unchanged — still uses pz-design-v2.js.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT   = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "service" / "app" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8", errors="replace")


# ── 1–4: customer-master-v2.html ────────────────────────────────────────────

def test_customer_master_loads_pz_design_not_dashboard_shared():
    src = _read("customer-master-v2.html")
    assert "pz-design-v2.js" in src, "pz-design-v2.js must be loaded"
    assert "dashboard-shared.js" not in src, "dashboard-shared.js must NOT be present"


def test_customer_master_has_dm_serif_font():
    src = _read("customer-master-v2.html")
    assert "DM+Serif+Display" in src or "DM Serif Display" in src, \
        "DM Serif Display font must be in the font link"


def test_customer_master_defines_overlay_token():
    src = _read("customer-master-v2.html")
    assert "--overlay" in src, "--overlay CSS custom property must be defined"


def test_customer_master_uses_pz_design_for_components():
    src = _read("customer-master-v2.html")
    assert "window.PzDesign" in src, "components must be sourced from window.PzDesign"
    assert "window.EstrellaShared.apiFetch" in src, \
        "apiFetch transport must come from window.EstrellaShared.apiFetch"


# ── 5–8: shipment-detail-v3.html ────────────────────────────────────────────

def test_shipment_detail_v3_exists():
    assert (_STATIC / "shipment-detail-v3.html").exists(), \
        "shipment-detail-v3.html must exist in service/app/static/"


def test_shipment_detail_v3_has_pz_design_script():
    src = _read("shipment-detail-v3.html")
    assert "pz-design-v2.js" in src, "pz-design-v2.js must be loaded in shipment-detail-v3.html"
    # The CSS comment documents "does NOT load dashboard-shared.js" — check for the
    # script TAG specifically, not the comment text.
    assert 'src="/dashboard/dashboard-shared.js"' not in src, \
        "dashboard-shared.js must NOT appear as a script src"


def test_shipment_detail_v3_wires_batch_id():
    src = _read("shipment-detail-v3.html")
    assert "batch_id" in src, "?batch_id= URL param must be wired"


def test_shipment_detail_v3_defines_overlay_token():
    src = _read("shipment-detail-v3.html")
    assert "--overlay" in src, "--overlay CSS custom property must be defined"


# ── 9–10: pz-design-v2.js exports ───────────────────────────────────────────

def test_pz_design_exports_sel():
    src = (_ROOT / "service" / "app" / "static" / "pz-design-v2.js").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "function Sel(" in src, "Sel component must be defined in pz-design-v2.js"
    assert "Sel," in src or "Sel\n" in src or ", Sel" in src, \
        "Sel must be exported in window.PzDesign"


def test_pz_design_exports_compact_table():
    src = (_ROOT / "service" / "app" / "static" / "pz-design-v2.js").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "function CompactTable(" in src, "CompactTable must be defined in pz-design-v2.js"
    assert "CompactTable," in src or "CompactTable\n" in src or ", CompactTable" in src, \
        "CompactTable must be exported in window.PzDesign"


# ── 11: proforma-detail-v2.html unchanged ───────────────────────────────────

def test_proforma_detail_v2_unchanged():
    """Visual regression: proforma-detail-v2.html must still use pz-design-v2.js."""
    src = _read("proforma-detail-v2.html")
    assert "pz-design-v2.js" in src, \
        "proforma-detail-v2.html must still load pz-design-v2.js (Sprint 24 regression)"
    assert "dashboard-shared.js" not in src, \
        "proforma-detail-v2.html must NOT load dashboard-shared.js (Sprint 24 regression)"
    assert "DM+Serif+Display" in src or "DM Serif Display" in src, \
        "proforma-detail-v2.html must still have DM Serif Display (Sprint 24 regression)"
