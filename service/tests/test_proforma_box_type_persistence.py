"""Box Master selection survives closing the modal.

Box Master (master_data_db.box_types) stays the only authority for which boxes
exist and what they measure. The draft persists the operator's CHOICE as a code
reference — no dimension columns, no second catalogue.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_ROOT = pathlib.Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BATCH = "BATCH_BOXTYPE"
CLIENT = "BOX_CLIENT"


@pytest.fixture()
def storage(tmp_path):
    from app.services import document_db as ddb
    from app.services import master_data_db as mdb
    from app.services import packing_db as pdb
    from app.services import proforma_invoice_link_db as pildb
    from app.services import wfirma_db as wfdb
    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    mdb.init_db(tmp_path / "master_data.sqlite")
    mdb.upsert_box_type(tmp_path / "master_data.sqlite", {
        "code": "BOX-A", "name": "Small carton", "length_cm": 20.0,
        "width_cm": 15.0, "height_cm": 10.0, "tare_weight_kg": 0.3,
    })
    out = tmp_path / "outputs" / BATCH
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(
        {"batch_id": BATCH, "awb": BATCH, "carrier": "DHL", "timeline": []}),
        encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, storage


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def _op():
    return {"X-Operator": "test-op", **_auth()}


def _seed_draft(storage):
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, status, currency, draft_state,
                  wfirma_proforma_id, wfirma_proforma_fullnumber,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (BATCH, CLIENT, "draft", "EUR", "draft", None, "", "[]",
             json.dumps([{"line_id": "L1", "product_code": "EJL/1", "qty": 1.0,
                          "unit_price": 100.0, "currency": "EUR"}]),
             "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _get(c, did):
    r = c.get(f"/api/v1/proforma/draft/{did}", headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def _set(c, did, body):
    return c.post(f"/api/v1/proforma/draft/{did}/box-type", json=body, headers=_op())


def _events(storage, did):
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        return [r[0] for r in conn.execute(
            "SELECT event FROM proforma_draft_events WHERE draft_id=?", (did,)).fetchall()]


def test_selection_persists_and_reloads(client):
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    assert d["box_type_code"] is None
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "box_type_code": "BOX-A"})
    assert r.status_code == 200, r.text
    assert _get(c, did)["box_type_code"] == "BOX-A"
    assert "box_type_set" in _events(storage, did)


def test_selection_can_be_cleared(client):
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    _set(c, did, {"expected_updated_at": d["updated_at"], "box_type_code": "BOX-A"})
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "box_type_code": ""})
    assert r.status_code == 200, r.text
    assert _get(c, did)["box_type_code"] is None


def test_unknown_code_is_rejected_by_box_master(client):
    """Box Master decides which codes exist — the request body never does."""
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "box_type_code": "NOPE"})
    assert r.status_code == 422, r.text
    assert _get(c, did)["box_type_code"] is None


def test_stale_lock_conflicts(client):
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    assert _set(c, did, {"expected_updated_at": d["updated_at"],
                         "box_type_code": "BOX-A"}).status_code == 200
    # second write still holding the pre-write timestamp
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "box_type_code": "BOX-A"})
    assert r.status_code == 409, r.text


def test_draft_stores_the_code_only_never_dimensions(client):
    """No second box catalogue: dimensions stay in Box Master."""
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    _set(c, did, {"expected_updated_at": d["updated_at"], "box_type_code": "BOX-A"})
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(proforma_drafts)")}
    assert "box_type_code" in cols
    assert not {"box_length_cm", "box_width_cm", "box_height_cm"} & cols


# ── Frontend contract pins (source-grep) ─────────────────────────────────────

_V2 = pathlib.Path(__file__).resolve().parents[1] / "app" / "static" / "v2"


def test_modal_persists_and_prefills_the_selection():
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "persistBoxSelection(code, boxUpdatedAt, false)" in src, "selection is not persisted on change"
    assert "box_type_code: prefill.box_type_code || ''" in src, "modal does not prefill"
    assert "PzApi.setDraftBoxType" in src
    api = (_V2 / "pz-api.js").read_text(encoding="utf-8")
    assert "setDraftBoxType:" in api
    assert "/box-type`" in api


def test_modal_never_persists_dimensions_on_the_draft():
    """Box Master owns the measurements — the draft holds the code alone."""
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    start = src.index("const persistBoxSelection")
    body = src[start:src.index("const handleBoxSelect", start)]
    for field in ("length_cm", "width_cm", "height_cm", "tare_weight_kg"):
        assert field not in body, field


# ── OCC conflict recovery (production incident, draft id=90, 2026-08-20) ─────
#
# The modal owns a snapshot of draft.updated_at. Any other legitimate draft edit
# advances the canonical token while the modal stays open, so the box write
# arrives stale and the server correctly refuses it. The OCC contract is NOT
# weakened anywhere below: every successful write still presents the CANONICAL
# token. What these pin is the recovery — refresh, then retry once, then stop.

_STALE     = "2026-08-20T02:20:20Z"   # token the modal opened with
_CANONICAL = "2026-08-20T02:26:19Z"   # after another legitimate draft mutation


def _force_updated_at(storage, did, when, remarks=None):
    """Stand in for an interleaving draft mutation with a controlled timestamp.

    updated_at has one-second resolution, so a same-second sibling write cannot
    be made deterministically distinct through the API.
    """
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        if remarks is None:
            conn.execute("UPDATE proforma_drafts SET updated_at=? WHERE id=?", (when, did))
        else:
            conn.execute(
                "UPDATE proforma_drafts SET updated_at=?, remarks=? WHERE id=?",
                (when, remarks, did))
        conn.commit()


def test_stale_box_write_recovers_through_one_refresh_and_retry(client):
    """The exact production failure, end to end, without weakening the lock."""
    c, storage = client
    did = _seed_draft(storage)
    _force_updated_at(storage, did, _STALE)
    # Another legitimate mutation lands while the modal is open.
    _force_updated_at(storage, did, _CANONICAL, remarks="edited elsewhere")

    # 1. The modal's stale token is refused — the server keeps its authority.
    r = _set(c, did, {"expected_updated_at": _STALE, "box_type_code": "BOX-A"})
    assert r.status_code == 409, r.text
    assert _get(c, did)["box_type_code"] is None

    # 2. The client re-reads the CANONICAL draft.
    d = _get(c, did)
    assert d["updated_at"] == _CANONICAL

    # 3. One retry against the canonical token succeeds.
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "box_type_code": "BOX-A"})
    assert r.status_code == 200, r.text

    # 4. Reopening the modal reads the persisted selection, and the unrelated
    #    edit made by the other session was never discarded.
    after = _get(c, did)
    assert after["box_type_code"] == "BOX-A"
    assert after["remarks"] == "edited elsewhere"
    assert after["updated_at"] != _CANONICAL     # the write advanced the token


def test_response_carries_the_new_token_so_the_next_write_is_not_stale(client):
    """A successful save must hand back the token the next write has to use.

    The client read it from the wrong level of the response envelope, so its
    snapshot never advanced and the SECOND box change in one modal session
    conflicted with no other editor involved.
    """
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "box_type_code": "BOX-A"})
    assert r.status_code == 200, r.text
    returned = r.json()["draft"]["updated_at"]
    assert returned == _get(c, did)["updated_at"]
    # Reusing the returned token immediately is accepted; the pre-write one is not.
    assert _set(c, did, {"expected_updated_at": returned,
                         "box_type_code": ""}).status_code == 200


def test_recovery_needs_no_second_write_when_the_value_is_already_canonical(client):
    """Another session stored the same code — the refresh alone resolves it."""
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    assert _set(c, did, {"expected_updated_at": d["updated_at"],
                         "box_type_code": "BOX-A"}).status_code == 200
    _force_updated_at(storage, did, _CANONICAL)

    assert _set(c, did, {"expected_updated_at": _STALE,
                         "box_type_code": "BOX-A"}).status_code == 409
    # The refreshed draft already holds the requested code, so the client has
    # nothing left to write — one box_type_set event, not two.
    assert _get(c, did)["box_type_code"] == "BOX-A"
    assert _events(storage, did).count("box_type_set") == 1


def test_a_second_conflict_stops_instead_of_looping(client):
    """Retry number two never happens — and nothing is lost when it doesn't."""
    c, storage = client
    did = _seed_draft(storage)
    _force_updated_at(storage, did, _CANONICAL, remarks="concurrent edit")

    assert _set(c, did, {"expected_updated_at": _STALE,
                         "box_type_code": "BOX-A"}).status_code == 409
    # The retry token is stale too (a third writer moved again): still refused,
    # still no partial write, still the other session's data intact.
    _force_updated_at(storage, did, "2026-08-20T02:31:00Z", remarks="concurrent edit")
    assert _set(c, did, {"expected_updated_at": _CANONICAL,
                         "box_type_code": "BOX-A"}).status_code == 409
    after = _get(c, did)
    assert after["box_type_code"] is None
    assert after["remarks"] == "concurrent edit"
    assert "box_type_set" not in _events(storage, did)


def test_client_recovery_is_bounded_and_reads_the_right_envelope():
    """Source pins for the browser half of the recovery."""
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    start = src.index("const adoptSavedDraft")
    body = src[start:src.index("// When a box profile is selected", start)]
    # The draft is at r.data.draft — reading r.draft silently never refreshed.
    assert "(r.data && r.data.draft)" in body
    # Exactly one retry, gated on the 409 and on not already being the retry.
    assert "r.status === 409 && !isRetry" in body
    assert "persistBoxSelection(code, d.updated_at, true)" in body
    # Already-canonical value resolves without a second write.
    assert "(d.box_type_code || '') === (code || '')" in body
    # No unbounded recovery loop (Lesson S).
    for banned in ("while (", "for (", "setInterval", "setTimeout"):
        assert banned not in body, banned


def test_successful_save_converges_the_parent_draft_token():
    """The page must learn the canonical draft, not just the modal."""
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "onDraftChanged" in src
    assert "onDraftChanged={() => draftHook && draftHook.reload && draftHook.reload()}" in src
    assert "if (typeof onDraftChanged === 'function') onDraftChanged();" in src
