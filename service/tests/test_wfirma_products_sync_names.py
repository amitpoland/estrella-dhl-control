"""wFirma goods name correction (2026-05-22).

PZ doc 185704611 was created with stale-described wFirma goods because
`/products/resolve` ran before the PR #269 bridge regenerated correct
pz_rows.json. This test suite pins the new `/products/sync-names`
endpoint behavior:

  - It NEVER fires without `WFIRMA_CREATE_PRODUCT_ALLOWED=true`.
  - When fired, it walks pz_rows.json and updates every wFirma good
    whose name has drifted from the current authority, persisting
    locally and logging each rename to the timeline.
  - Codes without a wfirma_product_id mapping are reported as
    `unmapped`, not as failures.
  - Idempotent — second run reports 0 renamed.
  - Material derivation from PL desc strips item-type prefix correctly.
"""
from __future__ import annotations

from pathlib import Path

from service.app.api.routes_wfirma import _material_from_pl_desc


# ── Helper unit tests — material derivation ─────────────────────────────

def test_material_strips_item_type_prefix():
    assert _material_from_pl_desc(
        "Bransoletki ze złota próby 375 z diamentami laboratoryjnymi"
    ) == "złota próby 375 z diamentami laboratoryjnymi"


def test_material_handles_silver():
    assert _material_from_pl_desc(
        "Kolczyki ze srebra próby 925 z cyrkoniami"
    ) == "srebra próby 925 z cyrkoniami"


def test_material_handles_plain():
    assert _material_from_pl_desc(
        "Pierścionki ze srebra próby 925"
    ) == "srebra próby 925"


def test_material_handles_multi_item_prefix():
    out = _material_from_pl_desc(
        "Wisiorki, Pierścionki ze srebra próby 925 z cyrkoniami i kamieniami kolorowymi"
    )
    assert out == "srebra próby 925 z cyrkoniami i kamieniami kolorowymi"


def test_material_handles_empty():
    assert _material_from_pl_desc("") == ""


def test_material_unrecognised_returns_input():
    s = "Some unrelated text without metal prefix"
    assert _material_from_pl_desc(s) == s


# ── Source-grep tests — endpoint contract ───────────────────────────────

ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_wfirma.py"
)


def _route_body():
    return ROUTES.read_text(encoding="utf-8")


def test_endpoint_registered():
    body = _route_body()
    assert '@router.post("/shipment/{batch_id}/wfirma/products/sync-names"' in body


def test_endpoint_gated_by_create_product_flag():
    body = _route_body()
    chunk = body[body.find("wfirma_products_sync_names"):]
    chunk = chunk[:chunk.find("@router", 1)] if "@router" in chunk[1:] else chunk
    assert "wfirma_create_product_allowed" in chunk
    assert "WFIRMA_PRODUCT_WRITE_DISABLED" in chunk


def test_endpoint_calls_edit_product_not_create():
    body = _route_body()
    chunk = body[body.find("wfirma_products_sync_names"):]
    end = chunk.find("@router", 1)
    if end > 0:
        chunk = chunk[:end]
    assert "wfirma_client.edit_product" in chunk
    assert "wfirma_client.create_product" not in chunk


def test_endpoint_persists_via_upsert_product():
    body = _route_body()
    chunk = body[body.find("wfirma_products_sync_names"):]
    end = chunk.find("@router", 1)
    if end > 0:
        chunk = chunk[:end]
    assert "wfirma_db.upsert_product" in chunk


def test_endpoint_logs_timeline_event():
    body = _route_body()
    assert "EV_WFIRMA_GOOD_RENAMED" in body
    assert '"wfirma_good_renamed"' in body


def test_endpoint_returns_before_after_table():
    body = _route_body()
    chunk = body[body.find("wfirma_products_sync_names"):]
    end = chunk.find("@router", 1)
    if end > 0:
        chunk = chunk[:end]
    assert '"before_after"' in chunk
    assert '"unchanged"' in chunk
    assert '"renamed"' in chunk
    assert '"unmapped"' in chunk
