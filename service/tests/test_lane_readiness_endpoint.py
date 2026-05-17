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
                *, editable_lines_json: str = '[{"product_code":"X","qty":1}]',
                seed_master_and_wfirma: bool = True) -> None:
    """Seed a proforma_draft.  By default also seeds product_master +
    wfirma_products rows for any product_code present in the draft's
    editable_lines_json — so happy-path tests stay green under PR-5's
    new gates.  Set ``seed_master_and_wfirma=False`` to deliberately
    test missing-coverage scenarios."""
    from app.services import proforma_invoice_link_db as pildb
    from app.services import reservation_db as rdb
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

    # Optional coverage seeding so happy-path tests don't accidentally
    # trip the PR-5 product_master_missing / wfirma_products_missing
    # gates.  Tests that probe those gates explicitly pass
    # ``seed_master_and_wfirma=False``.
    if not seed_master_and_wfirma:
        return
    try:
        parsed = _json_for_seed_lines(editable_lines_json)
    except Exception:
        return
    pcs = sorted({
        str((ln or {}).get("product_code") or "").strip()
        for ln in (parsed or [])
        if isinstance(ln, dict) and str((ln or {}).get("product_code") or "").strip()
    })
    if not pcs:
        return
    rdb.init_reservation_db(tmp / "reservation_queue.db")
    for pc in pcs:
        rdb.upsert_product_master(
            tmp / "reservation_queue.db",
            product_code=pc, design_no="", source_batch_id=bid,
        )
    _seed_wfirma_ready(tmp, pcs)


def _json_for_seed_lines(s):
    import json as _json
    return _json.loads(s or "[]")


def _seed_wfirma_ready(tmp: Path, codes) -> None:
    """Seed wfirma_products rows with sync_status='created' for *codes*."""
    from app.services import wfirma_db as wfdb
    wfdb.init_wfirma_db(tmp / "wfirma.db")
    db = tmp / "wfirma.db"
    with _s.connect(str(db)) as conn:
        now = "2026-05-17T00:00:00Z"
        for i, code in enumerate(codes):
            conn.execute(
                "INSERT OR IGNORE INTO wfirma_products "
                "(id, product_code, wfirma_product_id, product_name_pl, "
                " sync_status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"wf-{code}-{i}", code, f"wfid-{i}", code,
                 "created", now, now),
            )
        conn.commit()


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


def _seed_product_master(tmp: Path, codes, *, batch_id: str = "") -> None:
    """Seed product_master rows so PR-5's product_master_missing gate
    does not trip happy-path tests.  Tests probing the gate explicitly
    skip this helper."""
    from app.services import reservation_db as rdb
    rdb.init_reservation_db(tmp / "reservation_queue.db")
    for c in codes:
        rdb.upsert_product_master(
            tmp / "reservation_queue.db",
            product_code=c, design_no="", source_batch_id=batch_id,
        )


def _seed_wfirma_products(tmp: Path, mapping: dict,
                           *, also_seed_master: bool = True,
                           batch_id: str = "") -> None:
    """mapping: {product_code: sync_status} for ready/missing simulation.

    By default also seeds matching product_master rows so happy-path
    tests stay green under PR-5's new product_master_missing gate.
    Tests that deliberately probe the gate pass
    ``also_seed_master=False``."""
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
    if also_seed_master:
        _seed_product_master(tmp, mapping.keys(), batch_id=batch_id)


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
    # PR-5: closed enum extended with product_master_missing.
    valid = {"no_packing_rows", "products_missing", "sad_missing",
             "product_master_missing"}
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


# ── PR-5: Product Master + wFirma coverage gates ──────────────────────────

def _seed_sales_packing_line(tmp: Path, bid: str, *, design_no: str,
                              product_code: str = "",
                              client_name: str = "ACME") -> None:
    """Seed one sales_packing_lines row directly (no FastAPI roundtrip)."""
    from app.services import document_db as ddb
    import uuid as _u
    ddb.init_document_db(tmp / "documents.db")
    # Need a sales_documents row too because of FK conventions.
    sales_doc_id = ddb.store_sales_document(
        batch_id=bid, document_id=str(_u.uuid4()),
        data={"client_name": client_name, "client_ref": "REF",
              "sales_doc_no": "SO"},
    )
    ddb.store_sales_packing_lines(
        sales_document_id=sales_doc_id, batch_id=bid,
        lines=[{"client_name": client_name, "client_ref": "REF",
                "product_code": product_code, "design_no": design_no,
                "bag_id": "", "quantity": 1.0, "remarks": "",
                "unit_price": 0.0, "currency": "USD", "total_value": 0.0}],
    )


def _seed_purchase_packing_row(tmp: Path, bid: str, *,
                                product_code: str = "",
                                design_no: str = "D") -> None:
    """Seed one packing.db row that may have empty product_code."""
    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp / "packing.db")
    doc_id = pdb.upsert_packing_document(
        batch_id=bid, document_id=f"pd-{bid}-{design_no}",
        source_file_path="/tmp/p.xlsx", invoice_no="INV",
        parser_name="t", parser_version="1",
        source_file_hash=f"h-{bid}-{design_no}",
    )
    pdb.upsert_packing_lines([{
        "packing_document_id": doc_id, "batch_id": bid,
        "invoice_no": "INV", "invoice_line_position": 1,
        "product_code": product_code, "design_no": design_no,
        "batch_no": "", "bag_id": "", "tray_id": "",
        "item_type": "", "uom": "PCS",
        "quantity": 1.0, "gross_weight": 0, "net_weight": 0,
        "metal": "", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": 1, "unit_price": 0.0, "total_value": 0.0,
    }])


# ── 1. purchase blocked by product_master_missing ────────────────────────

def test_pr5_purchase_blocked_by_product_master_missing(client):
    cli, tmp = client
    bid = "B-PR5-PMM"
    _make_batch(tmp, bid, sad=True)
    _seed_packing(tmp, bid, ["EJL/X-1"])
    _seed_wfirma_products(tmp, {"EJL/X-1": "created"},
                            also_seed_master=False)
    # Deliberately DO NOT seed product_master.
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    p = body["purchase"]
    assert "product_master_missing" in p["pz_blocked_by"]
    assert p["product_master_missing"] == ["EJL/X-1"]
    assert p["pz_ready"] is False


def test_pr5_purchase_unblocked_after_product_master_present(client):
    cli, tmp = client
    bid = "B-PR5-PMP"
    _make_batch(tmp, bid, sad=True)
    _seed_packing(tmp, bid, ["EJL/Y-1"])
    _seed_wfirma_products(tmp, {"EJL/Y-1": "created"})
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    p = body["purchase"]
    assert "product_master_missing" not in p["pz_blocked_by"]
    assert p["product_master_missing"] == []
    assert p["pz_ready"] is True


def test_pr5_product_master_missing_list_sorted(client):
    cli, tmp = client
    bid = "B-PR5-SORT"
    _make_batch(tmp, bid, sad=True)
    _seed_packing(tmp, bid, ["EJL/Z-1", "EJL/Z-2", "EJL/Z-3"])
    _seed_wfirma_products(tmp,
        {"EJL/Z-1": "created", "EJL/Z-2": "created", "EJL/Z-3": "created"},
        also_seed_master=False,
    )
    _seed_product_master(tmp, ["EJL/Z-2"])   # only 1 of 3 in master
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    p = body["purchase"]
    assert p["product_master_missing"] == ["EJL/Z-1", "EJL/Z-3"]


# ── 4. purchase wfirma_products_missing list ──────────────────────────────

def test_pr5_wfirma_products_missing_list_populated(client):
    cli, tmp = client
    bid = "B-PR5-WFM"
    _make_batch(tmp, bid, sad=True)
    _seed_packing(tmp, bid, ["EJL/W-1", "EJL/W-2", "EJL/W-3"])
    # Only 1 of 3 ready in wfirma; PM seeded for all 3 so PM gate is clean.
    _seed_wfirma_products(tmp, {"EJL/W-1": "created"})
    _seed_product_master(tmp, ["EJL/W-2", "EJL/W-3"])
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    p = body["purchase"]
    assert p["wfirma_products_missing"] == ["EJL/W-2", "EJL/W-3"]
    assert "products_missing" in p["pz_blocked_by"]


# ── 5. unresolved_purchase_product_codes ─────────────────────────────────

def test_pr5_unresolved_purchase_product_codes(client):
    cli, tmp = client
    bid = "B-PR5-UPC"
    _make_batch(tmp, bid, sad=True)
    _seed_purchase_packing_row(tmp, bid, product_code="",
                                design_no="D-PURCH-X")
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    assert body["purchase"]["unresolved_purchase_product_codes"] == \
        ["D-PURCH-X"]


# ── 6. sales blocked_by no_drafts ─────────────────────────────────────────

def test_pr5_sales_blocked_by_no_drafts(client):
    cli, tmp = client
    bid = "B-PR5-NOD"
    _make_batch(tmp, bid)
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    assert "no_drafts" in s["blocked_by"]
    assert s["ready"] is False


# ── 7. sales blocked_by drafts_have_no_lines ──────────────────────────────

def test_pr5_sales_blocked_by_drafts_have_no_lines(client):
    cli, tmp = client
    bid = "B-PR5-EMPTY"
    _make_batch(tmp, bid)
    _seed_draft(tmp, bid, "ACME", "editing",
                 editable_lines_json="[]",
                 seed_master_and_wfirma=False)
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    assert "drafts_have_no_lines" in s["blocked_by"]
    assert s["ready"] is False


# ── 8. sales blocked_by post_failed ───────────────────────────────────────

def test_pr5_sales_blocked_by_post_failed(client):
    cli, tmp = client
    bid = "B-PR5-PF"
    _make_batch(tmp, bid)
    _seed_draft(tmp, bid, "ACME", "post_failed")
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    assert "post_failed" in s["blocked_by"]
    assert s["ready"] is False


# ── 9. sales blocked_by wfirma_products_missing ──────────────────────────

def test_pr5_sales_blocked_by_wfirma_products_missing(client):
    cli, tmp = client
    bid = "B-PR5-SWFM"
    _make_batch(tmp, bid)
    # Draft with a real pc; seed PM but NOT wfirma → wfirma gate fires.
    _seed_draft(tmp, bid, "ACME", "editing",
                 editable_lines_json='[{"product_code":"EJL/SW-1","qty":1}]',
                 seed_master_and_wfirma=False)
    _seed_product_master(tmp, ["EJL/SW-1"])
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    assert "wfirma_products_missing" in s["blocked_by"]


# ── 10. sales blocked_by product_master_missing ──────────────────────────

def test_pr5_sales_blocked_by_product_master_missing(client):
    cli, tmp = client
    bid = "B-PR5-SPMM"
    _make_batch(tmp, bid)
    _seed_draft(tmp, bid, "ACME", "editing",
                 editable_lines_json='[{"product_code":"EJL/SP-1","qty":1}]',
                 seed_master_and_wfirma=False)
    # Seed wfirma but NOT PM → PM gate fires.
    _seed_wfirma_products(tmp, {"EJL/SP-1": "created"},
                            also_seed_master=False)
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    assert "product_master_missing" in s["blocked_by"]


# ── 11. unresolved_sales_product_codes ───────────────────────────────────

def test_pr5_unresolved_sales_product_codes(client):
    cli, tmp = client
    bid = "B-PR5-USC"
    _make_batch(tmp, bid)
    _seed_sales_packing_line(tmp, bid, design_no="D-SALES-X",
                              product_code="")
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    assert body["sales"]["unresolved_sales_product_codes"] == ["D-SALES-X"]


# ── 12. sales ready true only when all gates pass ────────────────────────

def test_pr5_sales_ready_true_when_all_gates_pass(client):
    cli, tmp = client
    bid = "B-PR5-ALLOK"
    _make_batch(tmp, bid)
    # Default _seed_draft seeds PM + wfirma for the pc in the draft line.
    _seed_draft(tmp, bid, "ACME", "editing")
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    assert s["blocked_by"] == []
    assert s["ready"] is True


# ── 13. blocked_by lists sorted and deduped ───────────────────────────────

def test_pr5_blocked_by_lists_sorted_dedup(client):
    cli, tmp = client
    bid = "B-PR5-SORT2"
    _make_batch(tmp, bid)
    # Multiple sales-side causes: no drafts (will fire) — and that's
    # enough alone.  Add a sales row with empty pc to populate the
    # unresolved field too.
    _seed_sales_packing_line(tmp, bid, design_no="D-A")
    _seed_sales_packing_line(tmp, bid, design_no="D-B")
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    s = body["sales"]
    # blocked_by is sorted ascending; no duplicates.
    assert s["blocked_by"] == sorted(set(s["blocked_by"]))
    assert s["unresolved_sales_product_codes"] == ["D-A", "D-B"]


# ── 14. endpoint stays read-only with new fields ─────────────────────────

def test_pr5_endpoint_read_only_with_new_fields(client):
    cli, tmp = client
    bid = "B-PR5-RO"
    _make_batch(tmp, bid, sad=True)
    _seed_packing(tmp, bid, ["EJL/R-1"])
    _seed_wfirma_products(tmp, {"EJL/R-1": "created"})

    def _snap():
        out = {}
        for fname, tables in (
            ("packing.db",            ["packing_documents", "packing_lines"]),
            ("wfirma.db",             ["wfirma_products"]),
            ("reservation_queue.db",  ["product_master"]),
            ("proforma_links.db",     ["proforma_drafts"]),
            ("documents.db",          ["sales_packing_lines", "sales_documents"]),
        ):
            p = tmp / fname
            if not p.exists(): continue
            with _s.connect(str(p)) as c:
                for t in tables:
                    try:
                        out[t] = c.execute(
                            f"SELECT COUNT(*) FROM {t}"
                        ).fetchone()[0]
                    except Exception:
                        pass
        return out

    before = _snap()
    cli.get(f"/api/v1/packing/{bid}/lane-readiness")
    cli.get(f"/api/v1/packing/{bid}/lane-readiness")
    after = _snap()
    assert before == after, f"row counts changed: before={before} after={after}"


# ── 15. new fields default to empty lists on empty batch ─────────────────

def test_pr5_new_fields_default_to_empty_lists(client):
    cli, tmp = client
    bid = "B-PR5-DEF"
    _make_batch(tmp, bid)
    body = cli.get(f"/api/v1/packing/{bid}/lane-readiness").json()
    p, s = body["purchase"], body["sales"]
    assert p["product_master_missing"] == []
    assert p["wfirma_products_missing"] == []
    assert p["unresolved_purchase_product_codes"] == []
    assert s["unresolved_sales_product_codes"] == []
    assert isinstance(s["blocked_by"], list)


# ── 16. source-grep no external calls in lane_readiness body ─────────────

def test_pr5_source_grep_no_external_calls():
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_packing.py").read_text(encoding="utf-8")
    start = src.index("def get_lane_readiness(")
    end   = src.index("# ── GET /api/v1/packing/{batch_id}/lines", start)
    body  = src[start:end]
    for forbidden in ("requests.", "httpx.", "wfirma_client",
                      "smtp", "send_email", "dhl_dispatch",
                      "process_sad", "queue_email"):
        assert forbidden not in body, (
            f"lane-readiness body must not reference {forbidden!r}"
        )
