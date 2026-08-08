"""Customer Master Incoterm operator workflow — authority + API pins."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    settings.storage_root = tmp_path
    return tmp_path


def _seed_catalogue(storage: Path):
    from app.services.master_data_db import init_db, seed_default_incoterms
    md = storage / "master_data.sqlite"
    init_db(md)
    seed_default_incoterms(md)


def _mk_cm(storage: Path, cid: str, name: str, country: str = "LT", default=None):
    from app.services import customer_master_db as cmdb
    db = storage / "customer_master.sqlite"
    cmdb.init_db(db)
    c = cmdb.CustomerMaster(
        bill_to_contractor_id=cid,
        bill_to_name=name,
        country=country,
        default_incoterm=default,
        active=True,
    )
    cmdb.upsert_customer(db, c)


def _mk_draft(storage: Path, *, cid="", name="X", incoterm=None, state="editing"):
    from app.services import proforma_invoice_link_db as pildb
    db = storage / "proforma_links.db"
    pildb.init_db(db)
    d, created = pildb.auto_create_draft_from_sales_packing(
        db,
        batch_id=f"BATCH_{cid or 'orphan'}_{state}",
        client_name=name,
        currency="EUR",
        lines=[{"product_code": "P1", "qty": 1, "unit_price": 1.0, "currency": "EUR"}],
        operator="test",
        client_contractor_id=cid or None,
    )
    with pildb._connect(db) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET draft_state=?, incoterm=?, client_name=?, client_contractor_id=? WHERE id=?",
            (state, incoterm, name, cid or "", d.id),
        )
        conn.commit()
    return d.id


def test_classify_uab_orphan_is_review_not_preselected(storage):
    from app.services.customer_incoterm_authority import build_incoterm_review

    _mk_cm(storage, "45722450", "UAB Tomas Gold", "LT")
    _mk_cm(storage, "134920664", "UAB MONODIJA IR KO", "LT")
    _mk_cm(storage, "144938465", "ORKNIS UAB", "LT")
    _mk_draft(storage, cid="", name="UAB", incoterm="DAP", state="posted")

    payload = build_incoterm_review(storage=storage, missing_incoterm=True)
    by_cid = {r["contractor_id"]: r for r in payload["customers"]}
    for cid in ("45722450", "134920664", "144938465"):
        row = by_cid[cid]
        assert row["classification"] == "REVIEW"
        assert row["recommended_incoterm"] is None
        assert row["preselect_incoterm"] is None
        assert row["orphan_name_hints"]
        assert row["orphan_name_hints"][0]["hint_incoterm"] == "DAP"


def test_never_infer_from_country(storage):
    from app.services.customer_incoterm_authority import build_incoterm_review

    _mk_cm(storage, "1", "Polish Client", "PL")
    payload = build_incoterm_review(storage=storage)
    row = payload["customers"][0]
    assert row["classification"] == "NO EVIDENCE"
    assert row["recommended_incoterm"] is None


def test_apply_and_reseed_editable_only(storage):
    from app.services.customer_incoterm_authority import apply_customer_incoterms
    from app.services import proforma_invoice_link_db as pildb

    _seed_catalogue(storage)
    _mk_cm(storage, "C-1", "Client One", "DE")
    editable_id = _mk_draft(storage, cid="C-1", name="Client One", incoterm=None, state="editing")
    posted_id = _mk_draft(storage, cid="C-1", name="Client One", incoterm=None, state="posted")

    db = storage / "proforma_links.db"
    with pildb._connect(db) as conn:
        conn.execute("UPDATE proforma_drafts SET incoterm=NULL WHERE id IN (?,?)", (editable_id, posted_id))
        conn.commit()

    res = apply_customer_incoterms({"C-1": "EXW"}, storage=storage, reseed_editable=True)
    assert any(u.get("changed") for u in res["updated"])
    assert res["draft_reseed"]["seeded_count"] == 1
    assert res["draft_reseed"]["seeded"][0]["draft_id"] == editable_id

    d_edit = pildb.get_draft_by_id(db, editable_id)
    d_post = pildb.get_draft_by_id(db, posted_id)
    assert d_edit.incoterm == "EXW"
    assert not (d_post.incoterm or "").strip()


def test_api_incoterm_review_and_bulk(storage, monkeypatch):
    from app.core.config import settings
    from app.main import app
    import app.api.routes_customer_master as rcm

    # routes_customer_master binds _DB_PATH at import — re-point for this test
    monkeypatch.setattr(rcm, "_DB_PATH", storage / "customer_master.sqlite", raising=False)

    _seed_catalogue(storage)
    _mk_cm(storage, "C-10", "Bulk Client", "FR")
    editable_id = _mk_draft(storage, cid="C-10", name="Bulk Client", state="editing")
    db = storage / "proforma_links.db"
    from app.services import proforma_invoice_link_db as pildb
    with pildb._connect(db) as conn:
        conn.execute("UPDATE proforma_drafts SET incoterm=NULL WHERE id=?", (editable_id,))
        conn.commit()

    headers = {"X-API-KEY": settings.api_key or "test-key"}
    with TestClient(app) as client:
        r = client.get("/api/v1/customer-master/incoterm-review", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 1
        assert body["authority"]["never_infer_from_country"] is True

        bad = client.post(
            "/api/v1/customer-master/incoterm-bulk",
            headers=headers,
            json={"contractor_ids": ["C-10"], "default_incoterm": "DAP", "confirm": False},
        )
        assert bad.status_code == 422

        ok = client.post(
            "/api/v1/customer-master/incoterm-bulk",
            headers=headers,
            json={"contractor_ids": ["C-10"], "default_incoterm": "DAP", "confirm": True},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["draft_reseed"]["seeded_count"] == 1

        g = client.get("/api/v1/customer-master/C-10", headers=headers)
        assert g.json()["default_incoterm"] == "DAP"


def test_ui_pins_incoterm_panel_and_api_wrappers():
    root = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
    panel = (root / "customer-incoterm-panel.jsx").read_text(encoding="utf-8")
    assert "cm-incoterm-panel" in panel
    assert "country" in panel.lower()
    assert "confirm" in panel
    idx = (root / "index.html").read_text(encoding="utf-8")
    assert "customer-incoterm-panel.jsx" in idx
    api = (root / "pz-api.js").read_text(encoding="utf-8")
    assert "listCustomerIncotermReview" in api
    assert "bulkAssignCustomerIncoterm" in api
    master = (root / "master-page.jsx").read_text(encoding="utf-8")
    assert "CustomerIncotermPanel" in master
    assert "default_incoterm" in master
    detail = (root / "client-detail.jsx").read_text(encoding="utf-8")
    assert "cd-default_incoterm" in detail
