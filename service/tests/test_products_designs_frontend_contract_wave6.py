"""
test_products_designs_frontend_contract_wave6.py — EJ Dashboard Wave 6.

Source-contract pins for the Products + Designs V2 consolidation. Guards the
Product Master authority constitution at the frontend layer: the Products tab
must read the product_master REGISTRY (not the product_local overlay), product
edits must go to the overlay or the gated wFirma create-and-adopt path (never a
product_master writer), designs use the real design CRUD, and no forbidden
authority (design_product_mapping writer / wFirma mirror) is touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

V2 = Path(__file__).parents[1] / "app" / "static" / "v2"
MASTER = V2 / "master-page.jsx"
DESIGN = V2 / "design-detail.jsx"
PZAPI = V2 / "pz-api.js"


def _read(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"{p.name} missing")
    return p.read_text(encoding="utf-8")


# ── Products: 0-vs-149 consolidation ─────────────────────────────────────────

def test_products_tab_reads_product_master_registry():
    src = _read(MASTER)
    # The products entity api must resolve to the REGISTRY read (product_master),
    # not the overlay (product_local) that was showing 0.
    assert "case 'products'" in src
    # find the products entity-api line and assert it uses listProductMaster
    idx = src.index("case 'products'")
    window = src[idx:idx + 200]
    assert "listProductMaster" in window, "products tab must read the product_master registry"
    assert "listProductLocal()" not in window, "products primary read must not be the overlay"


def test_product_local_surfaced_as_overlay_not_primary():
    src = _read(MASTER)
    # product_local is still consumed — but as an overlay cross-ref, not the count.
    assert "listProductLocal" in src, "overlay must still be surfaced as enrichment"


def test_mapping_required_status_is_rendered():
    src = _read(MASTER)
    assert "mapping_required" in src and "statusBadge" in src, \
        "mapping_required must be visible via a status badge"


# ── Legal write paths only (authority constitution) ──────────────────────────

def test_product_edit_writes_overlay_only():
    src = _read(MASTER)
    assert "saveProductLocal" in src, "product edit must write the local overlay"
    # There is no product_master writer wrapper — assert none is invented here.
    assert "saveProductMaster" not in src
    assert "updateProductMaster" not in src


def test_product_create_uses_gated_create_and_adopt():
    src = _read(MASTER)
    assert "wfirmaGoodsCreateAndAdopt" in src, "product create must use the canonical gated path"
    # Honest fiscal-gate + already-in-wfirma handling present.
    assert "WFIRMA_CREATE_PRODUCT_ALLOWED" in src
    assert "wfirmaGoodsAdopt" in src, "409 already_in_wfirma must offer Adopt"


def test_no_forbidden_authority_touched():
    src = _read(MASTER)
    # No design_product_mapping writer, no wFirma mirror read from the UI.
    assert "design_product_mapping" not in src
    assert "wfirma_product_mirror" not in src


def test_new_product_is_not_a_manual_mint():
    src = _read(MASTER)
    # There must be no minting helper; creation always supplies an existing code.
    assert "mintProductCode" not in src and "generateProductCode" not in src


# ── Designs: real design authority CRUD ──────────────────────────────────────

def test_design_modal_uses_real_design_writers():
    src = _read(DESIGN)
    assert "SupplierDetailModal" not in src  # sanity: this is the design modal
    assert "saveDesign" in src, "design create/edit must call the real designs writer"
    assert "getDesign" in src, "edit mode must load via getDesign"
    assert "DesignDetailModal" in src


def test_master_page_wires_design_crud():
    src = _read(MASTER)
    assert "DesignDetailModal" in src
    assert "deleteDesign" in src, "designs must wire soft-delete"


def test_design_wrappers_exist_in_pzapi():
    src = _read(PZAPI)
    for m in ("saveDesign", "getDesign", "deleteDesign",
              "wfirmaGoodsCreateAndAdopt", "saveProductLocal"):
        assert m in src, f"pz-api must expose {m}"
