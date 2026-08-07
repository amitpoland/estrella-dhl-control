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


# ── GATE-4 follow-ups (PR #1119 gate, QA flags A/B/C) ────────────────────────
def _release_events(tmp_path) -> list:
    audit = json.loads((tmp_path / "outputs" / BID / "audit.json").read_text("utf-8"))
    return [e for e in audit["timeline"]
            if e.get("event") == "packing_confirmation_released"]


def test_release_without_reason_defaults_to_empty_string(env):
    """The reason field is optional; omitting it must not 422, and the audit
    event must carry the schema default "" — not null, not a missing key."""
    client, tmp_path, pdb = env
    ids = _seed(tmp_path, pdb)
    r = client.post(f"/api/v1/packing/{BID}/release-confirmation",
                    json={"row_ids": ids[:1]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["released"] == 1
    assert _status_by_id(pdb)[ids[0]] in (None, "")

    evs = _release_events(tmp_path)
    assert len(evs) == 1
    assert evs[0]["detail"]["reason"] == ""


def test_release_event_designs_match_released_rows(env):
    """detail.designs must name the released rows' design_no values, aligned
    index-for-index with detail.row_ids — the timeline entry is how an operator
    recognises WHICH pieces were reopened without resolving opaque row ids."""
    client, tmp_path, pdb = env
    ids = _seed(tmp_path, pdb)
    by_id = {str(r["id"]): r for r in pdb.get_packing_lines_for_batch(BID)}

    r = client.post(f"/api/v1/packing/{BID}/release-confirmation",
                    json={"row_ids": ids[:2], "reason": "legacy confirmations"})
    assert r.status_code == 200, r.text

    evs = _release_events(tmp_path)
    assert len(evs) == 1
    detail = evs[0]["detail"]
    assert detail["designs"] == [by_id[rid]["design_no"] for rid in detail["row_ids"]]
    assert detail["designs"] == [by_id[rid]["design_no"] for rid in ids[:2]]


def test_released_rows_become_rematch_eligible(env):
    """The intended sequence end-to-end: release → rematch dry-run.

    A confirmed mis-assigned row is preserved by the rematch planner (and, in
    this seed shape, blocks the plan — see
    test_packing_rematch_endpoint.test_operator_confirmed_row_survives_an_apply).
    After the governed release, the SAME dry run must propose the correction:
    the row moves from operator_confirmed_preserved into row_changes and the
    plan stops blocking. Seed reused from the rematch suite so the two
    endpoints are exercised against one identical batch shape.
    """
    client, tmp_path, pdb = env
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")
    from test_packing_rematch_endpoint import BID as R_BID
    from test_packing_rematch_endpoint import INV as R_INV
    from test_packing_rematch_endpoint import _seed as _seed_rematch
    _seed_rematch(tmp_path, ddb, pdb)  # wrong=True: sr1 mis-assigned to line 2

    rows = {r["pack_sr"]: r for r in pdb.get_packing_lines_for_batch(R_BID)}
    # Confirm sr1 by id — confirm_product_review keys on product_code, which
    # sr1 shares with sr2 in this deliberately-wrong seed shape.
    import sqlite3
    with sqlite3.connect(tmp_path / "packing.db") as con:
        con.execute(
            "UPDATE packing_lines SET operator_review_status='confirmed' WHERE id=?",
            (rows[1]["id"],))
        con.commit()

    before = client.post(f"/api/v1/packing/{R_BID}/rematch").json()["plan"]
    assert {e["pack_sr"] for e in before["operator_confirmed_preserved"]} == {1}
    assert 1 not in {c["pack_sr"] for c in before["row_changes"]}
    assert before["blocking"] is False
    assert [a for a in before["advisories"]
            if a["code"] == "line_over_authority_preexisting"]

    r = client.post(f"/api/v1/packing/{R_BID}/release-confirmation",
                    json={"row_ids": [str(rows[1]["id"])],
                          "reason": "defective-matcher legacy confirmation"})
    assert r.status_code == 200, r.text
    assert r.json()["released"] == 1

    after = client.post(f"/api/v1/packing/{R_BID}/rematch").json()
    assert after["dry_run"] is True and after["applied"] is False
    plan = after["plan"]
    assert plan["operator_confirmed_preserved"] == []
    changed = {c["pack_sr"]: c for c in plan["row_changes"]}
    assert 1 in changed, "the released row must be rematch-eligible again"
    assert changed[1]["new"]["invoice_line_position"] == 1
    assert changed[1]["new"]["product_code"] == f"{R_INV}-1"
    assert plan["blocking"] is False
