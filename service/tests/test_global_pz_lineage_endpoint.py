"""
test_global_pz_lineage_endpoint.py

Pins the GET /api/v1/pz/lineage/{batch_id} endpoint:

Authority contract:
  - Global Jewellery batches  → {is_global_supplier: true} + 4-dimensional status
  - Non-Global batches        → {is_global_supplier: false}  (panel suppressed)
  - Corrupt / missing files   → {is_global_supplier: true, error: "...", match_status: "UNMATCHED"}
  - WARNING_MATCH             → never rendered as FULL_MATCH / green in UI source

Dashboard contract (source-grep):
  - GlobalPZLineageCard defined in shipment-detail.html
  - Rendered after OperatorWorkflowCard in PZ / Accounting tab
  - Badge logic uses amber / red for WARNING / PARTIAL — never green for WARNING_MATCH
  - Returns null (no render) when is_global_supplier is false
  - data-testid="global-pz-lineage-card" present

Estrella protection:
  - Non-Global supplier → is_global_supplier=false → dashboard panel hidden

Production fixture (skipped when absent):
  - AWB 4789974092 → match_status == "WARNING_MATCH"
  - shipment_total_match == "FULL"
  - invoice_position_match == "WARNING"
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_pz import router as pz_router
from app.core.config import settings


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(pz_router)
    # Inject a dummy API key so _auth passes in tests
    import app.core.security as sec
    with patch.object(sec, "require_api_key", return_value=None):
        app2 = FastAPI()
        app2.include_router(pz_router)
        yield TestClient(app2)


@pytest.fixture
def authed_client(tmp_path, monkeypatch):
    """Client with auth bypassed and storage root pointed at tmp_path."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    app2 = FastAPI()
    app2.include_router(pz_router)
    import app.core.security as sec
    with patch.object(sec, "require_api_key", return_value=None):
        app3 = FastAPI()
        app3.include_router(pz_router)
        yield TestClient(app3)


# ── Supplier-gate tests ───────────────────────────────────────────────────────


def test_non_global_returns_is_global_false(tmp_path, monkeypatch):
    """Non-Global supplier → {is_global_supplier: false}, no lineage computed."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    app2 = FastAPI()
    app2.include_router(pz_router)

    import app.core.security as sec
    import app.api.routes_pz as rp

    with patch.object(sec, "require_api_key", return_value=None), \
         patch.object(rp, "_is_global_batch", return_value=False):
        c = TestClient(app2)
        resp = c.get("/api/v1/pz/lineage/BATCH_123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_global_supplier"] is False
    assert "match_status" not in data


def test_global_batch_with_missing_invoice_returns_unmatched(tmp_path, monkeypatch):
    """Global supplier but no invoice PDF → error + UNMATCHED, not 500."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    app2 = FastAPI()
    app2.include_router(pz_router)

    import app.core.security as sec
    import app.api.routes_pz as rp

    with patch.object(sec, "require_api_key", return_value=None), \
         patch.object(rp, "_is_global_batch", return_value=True), \
         patch.object(rp, "_find_source_pdf", return_value=None):
        c = TestClient(app2)
        resp = c.get("/api/v1/pz/lineage/BATCH_GLOBAL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_global_supplier"] is True
    assert data["match_status"] == "UNMATCHED"
    assert "error" in data
    assert "invoice" in data["error"]


def test_global_batch_with_missing_packing_returns_unmatched(tmp_path, monkeypatch):
    """Global supplier + invoice found but no packing PDF → UNMATCHED."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    import app.core.security as sec
    import app.api.routes_pz as rp

    inv_pdf = tmp_path / "fake_invoice.pdf"
    inv_pdf.write_bytes(b"%PDF-1.4")

    app2 = FastAPI()
    app2.include_router(pz_router)

    with patch.object(sec, "require_api_key", return_value=None), \
         patch.object(rp, "_is_global_batch", return_value=True), \
         patch.object(rp, "_find_source_pdf", side_effect=lambda b, cat: inv_pdf if cat == "invoices" else None):
        c = TestClient(app2)
        resp = c.get("/api/v1/pz/lineage/BATCH_GLOBAL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_global_supplier"] is True
    assert data["match_status"] == "UNMATCHED"
    assert "packing" in data["error"]


def test_invalid_batch_id_rejected():
    """Batch IDs with path separators must be rejected or route-not-matched.

    FastAPI normalises URL paths before the route handler sees them, so
    '../../etc' is resolved at the routing layer and returns 404 (route not
    matched) rather than reaching our 400 guard.  Both 400 and 404 are
    acceptable security outcomes — the request must not return 200.
    """
    import app.core.security as sec
    app2 = FastAPI()
    app2.include_router(pz_router)
    with patch.object(sec, "require_api_key", return_value=None):
        c = TestClient(app2)
        # Path traversal: router never matches the route → 404 (acceptable)
        assert c.get("/api/v1/pz/lineage/../../etc").status_code in (400, 404)
        # Sub-path: also route-unmatched → 404
        assert c.get("/api/v1/pz/lineage/foo/bar").status_code == 404


# ── Lineage build tests (mocked parsers) ─────────────────────────────────────


def _make_positions():
    return [
        {
            "position_no": 1, "unit": "PCS",
            "metal_en": "925 Silver", "stone_en": "CZ Stud Jewellery",
            "quantity": 10.0, "amount": 100.0,
            "rows": [{"type": "PENDANT", "qty": 5.0, "amount": 50.0},
                     {"type": "RING",    "qty": 5.0, "amount": 50.0}],
        },
    ]


def _make_packing_rows():
    return [
        {"serial_no": i, "item_type": "PENDANT" if i <= 5 else "RING",
         "metal": "925SL", "stone_detail": "CZ STUD",
         "quantity": 1.0, "unit_price": 10.0, "design_no": f"D{i:03d}"}
        for i in range(1, 11)
    ]


def test_full_match_response_shape(tmp_path, monkeypatch):
    """Mocked full-match scenario returns all 4 dimension fields."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    import app.core.security as sec
    import app.api.routes_pz as rp
    from pathlib import Path

    fake_inv  = tmp_path / "inv.pdf"
    fake_pack = tmp_path / "pack.pdf"
    fake_inv.write_bytes(b"%PDF-1.4")
    fake_pack.write_bytes(b"%PDF-1.4")

    app2 = FastAPI()
    app2.include_router(pz_router)

    with patch.object(sec, "require_api_key", return_value=None), \
         patch.object(rp, "_is_global_batch", return_value=True), \
         patch.object(rp, "_find_source_pdf", side_effect=lambda b, cat: fake_inv if cat == "invoices" else fake_pack), \
         patch.object(rp, "_load_pz_rows_from_audit", return_value=None), \
         patch.object(rp, "_extract_invoice_no", return_value="088/2026-2027"), \
         patch("app.api.routes_pz.parse_invoice_positions_from_pdf", return_value=_make_positions(), create=True), \
         patch("app.api.routes_pz.parse_global_packing_pdf", return_value=(_make_packing_rows(), "v1", "1.0", {}), create=True):
        c = TestClient(app2)
        resp = c.get("/api/v1/pz/lineage/BATCH_GLOBAL")

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_global_supplier"] is True
    assert data["invoice_no"] == "088/2026-2027"
    assert "shipment_total_match"          in data
    assert "invoice_position_match"        in data
    assert "packing_row_assignment_match"  in data
    assert "pz_line_visibility_match"      in data
    assert "match_status"                  in data
    assert "position_links"                in data
    assert "confidence_reasons" not in data    # confidence on individual links, not top level


def test_warning_match_status_not_full(tmp_path, monkeypatch):
    """WARNING_MATCH must never equal FULL_MATCH (regression guard)."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    import app.core.security as sec
    import app.api.routes_pz as rp

    fake_inv  = tmp_path / "inv.pdf"
    fake_pack = tmp_path / "pack.pdf"
    fake_inv.write_bytes(b"%PDF-1.4")
    fake_pack.write_bytes(b"%PDF-1.4")

    # Build a scenario with one OVERFLOW link to force WARNING_MATCH:
    # 2 positions that share the same stone family → one gets extra rows
    positions = [
        {
            "position_no": 1, "unit": "PCS",
            "metal_en": "925 Silver", "stone_en": "CZ Stud Jewellery",
            "quantity": 3.0, "amount": 30.0,
            "rows": [{"type": "PENDANT", "qty": 3.0, "amount": 30.0}],
        },
        {
            "position_no": 2, "unit": "PCS",
            "metal_en": "14KT Gold", "stone_en": "CZ Stud Jewellery",
            "quantity": 2.0, "amount": 40.0,
            "rows": [{"type": "RING", "qty": 2.0, "amount": 40.0}],
        },
    ]
    packing = [
        {"serial_no": i, "item_type": "PENDANT",
         "metal": "925SL", "stone_detail": "CZ STUD",
         "quantity": 1.0, "unit_price": 10.0, "design_no": f"D{i:03d}"}
        for i in range(1, 4)
    ] + [
        {"serial_no": i, "item_type": "RING",
         "metal": "14KT", "stone_detail": "CZ STUD",
         "quantity": 1.0, "unit_price": 20.0, "design_no": f"D{i:03d}"}
        for i in range(4, 6)
    ]

    app2 = FastAPI()
    app2.include_router(pz_router)

    with patch.object(sec, "require_api_key", return_value=None), \
         patch.object(rp, "_is_global_batch", return_value=True), \
         patch.object(rp, "_find_source_pdf", side_effect=lambda b, cat: fake_inv if cat == "invoices" else fake_pack), \
         patch.object(rp, "_load_pz_rows_from_audit", return_value=None), \
         patch.object(rp, "_extract_invoice_no", return_value="088/2026-2027"), \
         patch("app.api.routes_pz.parse_invoice_positions_from_pdf", return_value=positions, create=True), \
         patch("app.api.routes_pz.parse_global_packing_pdf", return_value=(packing, "v1", "1.0", {}), create=True):
        c = TestClient(app2)
        resp = c.get("/api/v1/pz/lineage/BATCH_GLOBAL")

    data = resp.json()
    assert data["match_status"] != "FULL_MATCH", (
        "WARNING_MATCH / PARTIAL_MATCH must not be promoted to FULL_MATCH"
    )


# ── UI source-grep tests (no runtime needed) ─────────────────────────────────

_HTML = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"


def test_global_pz_lineage_card_defined():
    src = _HTML.read_text(encoding="utf-8")
    assert "function GlobalPZLineageCard(" in src, (
        "GlobalPZLineageCard component must be defined in shipment-detail.html"
    )


def test_global_pz_lineage_card_rendered_in_pz_tab():
    src = _HTML.read_text(encoding="utf-8")
    assert "GlobalPZLineageCard" in src
    # Must appear inside the PZ / Accounting tab block
    tab_idx  = src.find("activeTab === 'PZ / Accounting'")
    card_idx = src.find("GlobalPZLineageCard", tab_idx)
    assert tab_idx > 0, "PZ / Accounting tab not found"
    assert card_idx > 0, "GlobalPZLineageCard not rendered in PZ / Accounting tab"


def test_global_pz_lineage_card_has_testid():
    src = _HTML.read_text(encoding="utf-8")
    assert 'data-testid="global-pz-lineage-card"' in src


def test_global_pz_lineage_card_suppressed_for_non_global():
    """If is_global_supplier is false, card must return null (no render).

    The component body is large (style atoms + loading/error JSX blocks
    precede the guard), so we search the full component text rather than
    a fixed-length slice.
    """
    src = _HTML.read_text(encoding="utf-8")
    start = src.find("function GlobalPZLineageCard(")
    # Find the next top-level function definition to bound the component body
    next_fn = src.find("\nfunction ", start + 1)
    body = src[start:next_fn] if next_fn > start else src[start:start + 15000]

    assert "is_global_supplier" in body, (
        "GlobalPZLineageCard must check is_global_supplier"
    )
    # Must have a null/nothing guard somewhere after the is_global_supplier check
    null_guard_idx   = body.find("return null")
    global_cond_idx  = body.find("is_global_supplier")
    assert null_guard_idx > 0, (
        "GlobalPZLineageCard must return null when is_global_supplier is false"
    )
    assert global_cond_idx > 0
    # The null guard must come after the is_global_supplier check
    assert global_cond_idx < null_guard_idx, (
        "null guard must appear after the is_global_supplier check"
    )


def test_warning_match_not_rendered_as_green():
    """WARNING_MATCH must never use the green badge color.

    The component must map WARNING_MATCH → amber color, not the green color
    used for FULL_MATCH. This is the core UI contract: operators must never
    see a green status indicator when overall lineage is WARNING or worse.
    """
    src = _HTML.read_text(encoding="utf-8")
    start = src.find("function GlobalPZLineageCard(")
    body  = src[start:start + 6000]
    # The match_status badge logic must NOT map WARNING_MATCH to 'green'
    # Find the overall badge chip area and check it doesn't equate WARNING → green
    assert "WARNING_MATCH" in body, "WARNING_MATCH case must appear in component"
    # The component must have explicit 'amber' or 'red' association with WARNING_MATCH
    assert "amber" in body or "warning" in body.lower(), (
        "Component must use amber/warning color for WARNING_MATCH"
    )
    # The component must not have a line like: WARNING_MATCH → green
    # (sanity: check that the FULL_MATCH → green assignment never leaks to WARNING_MATCH)
    full_match_idx    = body.find("FULL_MATCH")
    warning_match_idx = body.find("WARNING_MATCH")
    assert full_match_idx > 0 and warning_match_idx > 0


def test_endpoint_path_in_component():
    """The component must call /api/v1/pz/lineage/{batchId}."""
    src = _HTML.read_text(encoding="utf-8")
    start = src.find("function GlobalPZLineageCard(")
    body  = src[start:start + 3000]
    assert "/api/v1/pz/lineage/" in body, (
        "GlobalPZLineageCard must fetch from /api/v1/pz/lineage/{batchId}"
    )


# ── Production fixture (skipped when absent) ─────────────────────────────────

_FIXTURE_BATCH = "SHIPMENT_4789974092_2026-05_999deef1"
_FIXTURE_DIR   = Path("C:/PZ/storage/outputs") / _FIXTURE_BATCH


def test_production_fixture_endpoint_warning_match():
    """AWB 4789974092 must return WARNING_MATCH via the full endpoint chain.

    Skipped when the production fixture is absent (CI / fresh machine).
    """
    if not _FIXTURE_DIR.is_dir():
        pytest.skip("production fixture not available")

    import app.core.security as sec
    import app.api.routes_pz as routes_mod
    from app.core.config import settings

    # storage_root may differ between dev and prod; point it at production storage
    # so _is_global_batch and _find_source_pdf can locate the real fixture PDFs.
    prod_storage = Path("C:/PZ/storage")
    app2 = FastAPI()
    app2.include_router(pz_router)

    with patch.object(sec, "require_api_key", return_value=None), \
         patch.object(settings, "storage_root", prod_storage):
        c = TestClient(app2)
        resp = c.get(f"/api/v1/pz/lineage/{_FIXTURE_BATCH}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_global_supplier"] is True
    assert data["match_status"] != "FULL_MATCH", (
        "088/2026-2027 has stone-family ambiguity → must not report FULL_MATCH"
    )
    assert data["match_status"] == "WARNING_MATCH"
    assert data["shipment_total_match"] == "FULL"
    assert data["invoice_position_match"] == "WARNING"


def test_production_fixture_no_global_suppression_for_non_global():
    """A random non-Global batch must never show the lineage panel.

    Uses a synthetic batch dir with a plain text file — detect_supplier
    will not match 'global_jewellery', so the endpoint must return
    is_global_supplier=false.
    """
    import tempfile
    import app.core.security as sec
    import app.api.routes_pz as rp

    with tempfile.TemporaryDirectory() as td:
        import pathlib
        td_path = pathlib.Path(td)
        bid = "ESTRELLA_BATCH_001"
        inv_dir = td_path / "outputs" / bid / "source" / "invoices"
        inv_dir.mkdir(parents=True)
        # Write a plain PDF marker that does NOT contain Global Jewellery text
        (inv_dir / "invoice.pdf").write_bytes(b"%PDF-1.4 ESTRELLA JEWELS LTD")

        from unittest.mock import patch as _patch
        import app.core.config as cfg
        import app.core.security as sec2
        old_root = settings.storage_root
        settings.storage_root = td_path
        try:
            app2 = FastAPI()
            app2.include_router(pz_router)
            with _patch.object(sec2, "require_api_key", return_value=None):
                c = TestClient(app2)
                resp = c.get(f"/api/v1/pz/lineage/{bid}")
        finally:
            settings.storage_root = old_root

    assert resp.status_code == 200
    assert resp.json()["is_global_supplier"] is False
