"""POST /api/v1/packing/{batch_id}/release-confirmation — governed confirmation release.

A confirmation recorded under an earlier, defective matcher is otherwise permanent:
rematch preserves confirmed rows by design and re-upload never reopens them (#1102).
This endpoint is the deliberate, admin-only, audited exit. These tests pin its
load-bearing properties: exact row_ids only, all-or-nothing refusal, confirmation
fields cleared while product_code stays untouched, audit event written, auth enforced.

All fixtures synthetic — the repository is public. No client name, real AWB, real
supplier invoice number, or real design number appears here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

INV = "TEST/00-00/002"
BID = "B-RELEASE-1"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    from app.auth.dependencies import get_current_user, require_admin
    # Admin session by default (Lesson O: session override, popped in teardown).
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "t", "email": "t@l", "role": "admin"}
    app.dependency_overrides[require_admin] = lambda: {
        "id": "t", "email": "t@l", "role": "admin"}

    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp_path / "packing.db")
    try:
        yield TestClient(app), tmp_path, pdb
    finally:
        app.dependency_overrides.clear()


def _seed(tmp_path, pdb, *, confirm_sr=(1, 2)) -> list[str]:
    """Batch dir + three persisted rows; sr in confirm_sr get confirmed.

    Returns the row ids in pack_sr order.
    """
    out = tmp_path / "outputs" / BID
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(
        {"batch_id": BID, "tracking_no": BID, "awb": BID,
         "carrier": "DHL", "timeline": []}), encoding="utf-8")

    doc_id = pdb.upsert_packing_document(
        batch_id=BID, invoice_no=INV,
        source_file_path=str(out / "p.xlsx"), source_file_hash="synthetic-hash",
        parser_name="test", parser_version="1", extraction_status="complete")
    pdb.upsert_packing_lines([
        {"batch_id": BID, "packing_document_id": doc_id, "invoice_no": INV,
         "invoice_line_position": pos, "product_code": f"{INV}-{pos}",
         "design_no": f"SYN-10{pos}", "item_type": "RNG", "quantity": 1,
         "unit_price": 100.0 + pos, "pack_sr": pos}
        for pos in (1, 2, 3)
    ])
    rows = sorted(pdb.get_packing_lines_for_batch(BID), key=lambda r: r["pack_sr"])
    for r in rows:
        if r["pack_sr"] in confirm_sr:
            pdb.confirm_product_review(BID, r["product_code"], "legacy-op")
    return [str(r["id"]) for r in rows]


def _status_by_id(pdb):
    return {str(r["id"]): r.get("operator_review_status")
            for r in pdb.get_packing_lines_for_batch(BID)}


# ── Happy path ───────────────────────────────────────────────────────────────
def test_release_clears_confirmation_fields_and_writes_audit(env):
    client, tmp_path, pdb = env
    ids = _seed(tmp_path, pdb)
    r = client.post(f"/api/v1/packing/{BID}/release-confirmation",
                    json={"row_ids": ids[:2], "reason": "pre-fix legacy confirmations"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["released"] == 2
    assert {x["row_id"] for x in body["rows"]} == set(ids[:2])

    rows = {str(x["id"]): x for x in pdb.get_packing_lines_for_batch(BID)}
    for rid in ids[:2]:
        assert rows[rid]["operator_review_status"] in (None, "")
        assert not rows[rid].get("operator_confirmed_by")
        assert not rows[rid].get("operator_source_revision")
        # Released, not reassigned: the stored mapping is untouched.
        assert rows[rid]["product_code"].startswith(INV)

    audit = json.loads((tmp_path / "outputs" / BID / "audit.json").read_text("utf-8"))
    evs = [e for e in audit["timeline"]
           if e.get("event") == "packing_confirmation_released"]
    assert len(evs) == 1, "the release must land in the operator-visible timeline"
    assert set(evs[0]["detail"]["row_ids"]) == set(ids[:2])
    assert evs[0]["detail"]["reason"] == "pre-fix legacy confirmations"


# ── All-or-nothing refusals ──────────────────────────────────────────────────
def test_unknown_row_id_refuses_everything(env):
    client, tmp_path, pdb = env
    ids = _seed(tmp_path, pdb)
    r = client.post(f"/api/v1/packing/{BID}/release-confirmation",
                    json={"row_ids": [ids[0], "does-not-exist"]})
    assert r.status_code == 422
    assert "not found" in r.json()["detail"]
    assert _status_by_id(pdb)[ids[0]] == "confirmed", \
        "a refused release must change nothing — including the valid rows named"


def test_unconfirmed_row_refuses_everything(env):
    client, tmp_path, pdb = env
    ids = _seed(tmp_path, pdb)          # sr3 is never confirmed
    r = client.post(f"/api/v1/packing/{BID}/release-confirmation",
                    json={"row_ids": [ids[0], ids[2]]})
    assert r.status_code == 422
    assert "not confirmed" in r.json()["detail"]
    assert _status_by_id(pdb)[ids[0]] == "confirmed"


def test_wrong_batch_empty_and_duplicate_ids_refused(env):
    client, tmp_path, pdb = env
    ids = _seed(tmp_path, pdb)
    assert client.post(f"/api/v1/packing/{BID}/release-confirmation",
                       json={"row_ids": []}).status_code == 422
    assert client.post(f"/api/v1/packing/{BID}/release-confirmation",
                       json={"row_ids": [ids[0], ids[0]]}).status_code == 422
    from app.services import packing_db as pdb2
    with pytest.raises(ValueError, match="different batch"):
        pdb2.release_product_confirmation("B-OTHER", [ids[0]], "op")


# ── Auth (Lesson O: real dependency, overrides removed) ──────────────────────
def test_release_rejects_unauthenticated_and_non_admin(env):
    client, tmp_path, pdb = env
    ids = _seed(tmp_path, pdb)
    from app.main import app
    from app.auth.dependencies import get_current_user, require_admin
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_current_user, None)
    try:
        r = client.post(f"/api/v1/packing/{BID}/release-confirmation",
                        json={"row_ids": ids[:1]})
        assert r.status_code == 401
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "v", "email": "v@l", "role": "viewer"}
        r = client.post(f"/api/v1/packing/{BID}/release-confirmation",
                        json={"row_ids": ids[:1]})
        assert r.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "t", "email": "t@l", "role": "admin"}
        app.dependency_overrides[require_admin] = lambda: {
            "id": "t", "email": "t@l", "role": "admin"}
    assert _status_by_id(pdb)[ids[0]] == "confirmed", "denied calls must write nothing"
