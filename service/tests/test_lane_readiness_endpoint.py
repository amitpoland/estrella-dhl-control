"""test_lane_readiness_endpoint.py — 2026-05-17.

Contract + read-only behaviour for GET /api/v1/packing/{bid}/lane-readiness.

Sales counts come from proforma_drafts state buckets. Purchase counts
come from packing_lines × wfirma_products cache + audit.json SAD
presence. pz_blocked_by uses a closed enum:
  no_packing_rows | products_missing | sad_missing
"""
from __future__ import annotations

import json
import sqlite3 as _s
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "test", "email": "test@local"}
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def _make_batch(tmp: Path, bid: str, *, sad: bool = False) -> Path:
    out = tmp / "outputs" / bid
    out.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": bid, "timeline": []}
    if sad:
        audit["importer"] = "Estrella Jewels Sp. z o.o."
        audit["sad_number"] = "PL/MF/AC429/2026/0001"
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out


_LEGACY_STATUS_FOR_STATE = {
    # Reverse the read-side shim so seeded rows stay in the target state.
    # If we left status='draft' for a row with draft_state='posted', the
    # shim would override draft_state back to 'draft' (see _row_to_draft).
    "draft":       "draft",
    "editing":     "draft",
    "approved":    "draft",
    "posted":      "issued",
    "post_failed": "failed",
    "posting":     "pending_local",
}


def _seed_draft(tmp: Path, bid: str, client_name: str, state: str,
                *, editable_lines_json: str = '[{"product_code":"X","qty":1}]') -> None:
    from app.services import proforma_invoice_link_db as pildb
    db = tmp / "proforma_links.db"
    pildb.init_db(db)
    legacy = _LEGACY_STATUS_FOR_STATE.get(state, "draft")
    with _s.connect(str(db)) as conn:
        conn.row_factory = _s.Row
        pildb._ensure_drafts_table(conn)
        now = pildb._now_utc_iso()
        conn.execute(
            "INSERT INTO proforma_drafts (batch_id, client_name, status, "
            "currency, draft_state, draft_version, source_lines_json, "
            "editable_lines_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (bid, client_name, legacy, "USD", state, 1, "[]",
             editable_lines_json, now, now),
        )


def _seed_packing(tmp: Path, bid: str, codes: list) -> None:
    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp / "packing.db")
    doc_id = pdb.upsert_packing_document(
        batch_id=bid, document_id=f"pd-{bid}",
        source_file_path="/tmp/p.xlsx", invoice_no="INV",
        parser_name="t", parser_version="1", source_file_hash=f"h-{bid}",
    )
    lines = [{
        "packing_document_id": doc_id, "batch_id": bid,
        "invoice_no": "INV", "invoice_line_position": i,
        "product_code": c, "design_no": c, "batch_no": "", "bag_id": "",
        "tray_id": "", "item_type": "", "uom": "PCS",
        "quantity": 1.0, "gross_weight": 0, "net_weight": 0,
        "metal": "", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": i, "unit_price": 0.0, "total_value": 0.0,
    } for i, c in enumerate(codes)]
    pdb.upsert_packing_lines(lines)


def _seed_wfirma_products(tmp: Path, mapping: dict) -> None:
    """mapping: {product_code: sync_status} for ready/missing simulation."""
    from app.services import wfirma_db as wfdb
    wfdb.init_wfirma_db(tmp / "wfirma.db")
    db = tmp / "wfirma.db"
    with _s.connect(str(db)) as conn:
        for i, (code, status) in enumerate(mapping.items()):
            conn.execute(
                "INSERT INTO wfirma_products (id, product_code, "
                "wfirma_product_id, product_name_pl, sync_status, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (f"id-{i}", code, "wfid-" + str(i), code, status,
                 "2026-05-17T00:00:00Z", "2026-05-17T00:00:00Z"),
            )
        conn.commit()


# ── Shape + read-only ─────────────────────────────────────────────────────

def test_response_shape_matches_contract(client):
    cli, tmp = client
    _make_batch(tmp, "B-SHAPE")
    r = cli.get("/api/v1/packing/B-SHAPE/lane-readiness")
    assert r.status_code == 200
    body = r.json()
    assert body["batch_id"] == "B-SHAPE"
    for k in ("drafts_total", "drafts_needs_review", "drafts_approved",
              "drafts_posted", "drafts_post_failed", "ready"):
        assert k in body["sales"], f"sales.{k} missing"
    for k in ("packing_rows", "distinct_product_codes", "products_ready",
              "products_missing", "sad_present", "pz_ready", "pz_blocked_by"):
        assert k in body["purchase"], f"purchase.{k} missing"
    assert isinstance(body["purchase"]["pz_blocked_by"], list)


def test_endpoint_is_read_only(client):
    cli, tmp = client
    bid = "B-RO"
    _make_batch(tmp, bid)
    _seed_packing(tmp, bid, ["X1", "X2"])
    _seed_draft(tmp, bid, "ACME", "draft")

    # Snapshot row counts.
    def snap():
        out = {}
        for fname, tables in (
            ("proforma_links.db", ["proforma_drafts"]),
            ("packing.db",        ["packing_documents", "packing_lines"]),
        ):
            p = tmp / fname
            if not p.exists(): continue
            with _s.connect(str(p)) as c:
                for t in tables:
                    try:
                        out[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    except Exception:
                        pass
        return out

    before = snap()
    cli.get(f"/api/v1/packing/{bid}/lane-readiness")
    cli.get(f"/api/v1/packing/{bid}/lane-readiness")
    after = snap()
    assert before == after, f"row counts changed: before={before} after={after}"


# ── Sales counts ──────────────────────────────────────────────────────────

def test_sales_counts_match_drafts_states(client):
    cli, tmp = client
    bid = "B-SALES"
    _make_batch(tmp, bid)
    _seed_draft(tmp, bid, "ACME",   "draft")
    _seed_draft(tmp, bid, "BETA",   "editing")
    _seed_draft(tmp, bid, "GAMMA",  "approved")
    _seed_draft(tmp, bid, "DELTA",  "posted")

    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    assert s["drafts_total"] == 4
    assert s["drafts_needs_review"] == 2
    assert s["drafts_approved"] == 1
    assert s["drafts_posted"] == 1
    assert s["drafts_post_failed"] == 0
    assert s["ready"] is True


def test_sales_ready_false_on_post_failed(client):
    cli, tmp = client
    bid = "B-SALES-FAIL"
    _make_batch(tmp, bid)
    _seed_draft(tmp, bid, "ACME", "post_failed")
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    assert body["sales"]["drafts_post_failed"] == 1
    assert body["sales"]["ready"] is False


def test_sales_ready_false_when_drafts_have_no_lines(client):
    """Regression guard for the false-positive 'sales ready' banner: a
    draft created with editable_lines_json='[]' (e.g. all sales rows
    were skipped because product_code couldn't be resolved) must NOT
    count toward sales_ready, even though draft_state is editable."""
    cli, tmp = client
    bid = "B-SALES-EMPTY"
    _make_batch(tmp, bid)
    _seed_draft(tmp, bid, "ACME", "editing", editable_lines_json="[]")
    _seed_draft(tmp, bid, "BETA", "draft",   editable_lines_json="[]")
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    assert s["drafts_total"] == 2
    assert s["drafts_with_lines"] == 0
    assert s["ready"] is False, (
        "sales_ready must be False when every draft has empty "
        "editable_lines_json — drafts_total alone is not enough."
    )


def test_sales_ready_true_when_at_least_one_draft_has_lines(client):
    cli, tmp = client
    bid = "B-SALES-MIXED"
    _make_batch(tmp, bid)
    _seed_draft(tmp, bid, "EMPTY", "editing", editable_lines_json="[]")
    _seed_draft(tmp, bid, "REAL",  "editing")  # default seeds 1 line
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    assert s["drafts_total"] == 2
    assert s["drafts_with_lines"] == 1
    assert s["ready"] is True


# ── Purchase counts ───────────────────────────────────────────────────────

def test_purchase_products_ready_count_matches_wfirma_cache(client):
    cli, tmp = client
    bid = "B-PROD"
    _make_batch(tmp, bid)
    _seed_packing(tmp, bid, ["A", "B", "C", "D"])
    _seed_wfirma_products(tmp, {"A": "created", "B": "ready",
                                "C": "pending", "D": "failed"})
    p = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()["purchase"]
    assert p["distinct_product_codes"] == 4
    assert p["products_ready"] == 2  # only created + ready
    assert p["products_missing"] == 2


def test_pz_blocked_by_uses_enumerated_reasons_only(client):
    cli, tmp = client
    # No packing → no_packing_rows, no products_missing (since 0),
    # sad_missing
    _make_batch(tmp, "B-EMPTY")
    body = cli.get("/api/v1/packing/B-EMPTY/lane-readiness").json()
    blocked = body["purchase"]["pz_blocked_by"]
    valid = {"no_packing_rows", "products_missing", "sad_missing"}
    assert set(blocked).issubset(valid), f"unexpected reasons: {blocked}"
    assert "no_packing_rows" in blocked
    assert "sad_missing" in blocked


def test_pz_ready_requires_all_three_conditions(client):
    cli, tmp = client
    bid = "B-READY"
    _make_batch(tmp, bid, sad=True)
    _seed_packing(tmp, bid, ["A", "B"])
    _seed_wfirma_products(tmp, {"A": "ready", "B": "created"})
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    p = body["purchase"]
    assert p["sad_present"] is True
    assert p["products_missing"] == 0
    assert p["pz_ready"] is True
    assert p["pz_blocked_by"] == []


# ── Source-grep guards ────────────────────────────────────────────────────

def test_lane_readiness_source_has_no_write_keywords():
    src = (Path(__file__).resolve().parents[1] / "app" / "api" /
           "routes_packing.py").read_text(encoding="utf-8")
    # Slice the lane-readiness endpoint body.
    start_marker = "def get_lane_readiness("
    end_marker   = "# ── GET /api/v1/packing/{batch_id}/lines"
    assert start_marker in src
    body = src[src.index(start_marker):src.index(end_marker)]
    for kw in ("INSERT ", "UPDATE ", "DELETE ",
               "register_document(", "store_", "replace_",
               "upsert_", "update_sales_document",
               "send_email", "queue_email", "smtp",
               "wfirma_client", "dhl_dispatch", "process_sad"):
        assert kw not in body, f"lane-readiness must not call {kw!r}"


def test_dashboard_renders_lane_readiness_testids():
    # Phase 2 — Lane Readiness banners live in shipment-detail.html.
    dash = (Path(__file__).resolve().parents[1] / "app" / "static" /
            "shipment-detail.html").read_text(encoding="utf-8")
    assert 'data-testid="lane-readiness-sales"' in dash
    assert 'data-testid="lane-readiness-purchase"' in dash
    assert 'data-testid="lane-readiness-sales-open-accounting"' in dash
    assert "SALES LANE" in dash
    assert "PURCHASE LANE" in dash
