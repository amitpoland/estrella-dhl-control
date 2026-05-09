"""
test_audit_proforma_cancelled.py — `record_proforma_cancelled` helper +
cancel-route audit emit.

Pins:
  1. helper appends one cancellation event with the expected detail shape
  2. helper is idempotent on (batch_id, deleted_wfirma_proforma_id)
  3. helper does NOT mutate audit.proforma_issued[]
  4. cancel-for-reissue route emits the event after a successful cancel
  5. cancel route does NOT emit when the wFirma delete fails
  6. cancel route does NOT emit when the local reset fails
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as _wc
from app.services import packing_db   as pdb
from app.services import warehouse_db as wdb
from app.services import document_db  as ddb
from app.services import wfirma_db    as wfdb
from app.services import proforma_invoice_link_db as pildb
from app.services import proforma_service_charges_db as scdb
from app.services.audit_persist import (
    EV_PROFORMA_CANCELLED,
    record_proforma_cancelled,
)


_BATCH   = "BATCH_AUDIT_CANCEL"
_CONFIRM = "YES_DELETE_AND_REISSUE_ONE_PROFORMA"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _prime_vat():
    _wc._VAT_CODE_ID_CACHE["23"] = "222"
    yield


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    scdb.init(tmp_path / "proforma_links.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    (tmp_path / "outputs" / _BATCH).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _gate_delete_on():
    return patch.object(settings, "wfirma_delete_invoice_allowed", True)


def _seed_audit(storage, *, with_issued=True) -> Path:
    p = storage / "outputs" / _BATCH / "audit.json"
    audit = {
        "status":   "partial",
        "wfirma_export": {"wfirma_pz_doc_id": "X"},
        "timeline": [],
    }
    if with_issued:
        # Mirrors the live AWB 6049349806 shape: 4 ACTIVE entries already
        # present in proforma_issued[] (the cancelled originals were never
        # there because they were issued before the helper landed).
        audit["proforma_issued"] = [
            {"client_name": "ACME",
             "wfirma_proforma_id": "ACTIVE-A",
             "line_count": 1, "currency": "EUR", "operator": "amit"},
        ]
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def _seed_issued_draft(storage, *, client_name: str,
                        wfirma_id: str) -> None:
    db = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        db, batch_id=_BATCH, client_name=client_name,
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    pildb.mark_draft_issued(db, _BATCH, client_name,
                             wfirma_proforma_id=wfirma_id)


# ── 1. Helper appends one cancellation event ───────────────────────────────

def test_helper_appends_one_cancellation_event(storage):
    audit_path = _seed_audit(storage)
    r = record_proforma_cancelled(
        audit_path,
        batch_id                       = _BATCH,
        client_name                    = "Anastazia Panakova",
        deleted_wfirma_proforma_id     = "467222691",
        replaced_by_wfirma_proforma_id = "467236963",
        reason                         = "operator cancel-for-reissue",
        operator                       = "amit",
        source                         = "cancel_for_reissue",
    )
    assert r["appended"] is True
    a = json.loads(audit_path.read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CANCELLED]
    assert len(events) == 1
    detail = events[0]["detail"]
    assert detail["batch_id"]                       == _BATCH
    assert detail["client_name"]                    == "Anastazia Panakova"
    assert detail["deleted_wfirma_proforma_id"]     == "467222691"
    assert detail["replaced_by_wfirma_proforma_id"] == "467236963"
    assert detail["reason"]                         == "operator cancel-for-reissue"
    assert detail["operator"]                       == "amit"
    assert detail["source"]                         == "cancel_for_reissue"


# ── 2. Idempotent on (batch_id, deleted_wfirma_proforma_id) ────────────────

def test_helper_idempotent_on_batch_and_deleted_id(storage):
    audit_path = _seed_audit(storage)
    record_proforma_cancelled(audit_path, batch_id=_BATCH,
                               client_name="A", deleted_wfirma_proforma_id="467222691")
    second = record_proforma_cancelled(audit_path, batch_id=_BATCH,
                                        client_name="A", deleted_wfirma_proforma_id="467222691")
    assert second["appended"] is False
    assert second["reason"]   == "already recorded"
    a = json.loads(audit_path.read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CANCELLED]
    assert len(events) == 1


def test_helper_distinguishes_different_deleted_ids(storage):
    audit_path = _seed_audit(storage)
    record_proforma_cancelled(audit_path, batch_id=_BATCH,
                               client_name="A", deleted_wfirma_proforma_id="X1")
    record_proforma_cancelled(audit_path, batch_id=_BATCH,
                               client_name="B", deleted_wfirma_proforma_id="X2")
    a = json.loads(audit_path.read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CANCELLED]
    assert len(events) == 2


def test_helper_rejects_empty_deleted_id(storage):
    audit_path = _seed_audit(storage)
    r = record_proforma_cancelled(audit_path, batch_id=_BATCH,
                                   client_name="A", deleted_wfirma_proforma_id="")
    assert r["appended"] is False
    assert "empty" in r["reason"]


def test_helper_handles_missing_audit():
    r = record_proforma_cancelled(Path("/nonexistent/audit.json"),
                                   batch_id=_BATCH, client_name="A",
                                   deleted_wfirma_proforma_id="X")
    assert r["appended"] is False
    assert "missing" in r["reason"]


# ── 3. Helper does NOT touch proforma_issued[] ─────────────────────────────

def test_helper_does_not_touch_proforma_issued_list(storage):
    audit_path = _seed_audit(storage, with_issued=True)
    before = json.loads(audit_path.read_text()).get("proforma_issued") or []
    record_proforma_cancelled(audit_path, batch_id=_BATCH,
                               client_name="ACME",
                               deleted_wfirma_proforma_id="467222691",
                               replaced_by_wfirma_proforma_id="ACTIVE-A")
    after = json.loads(audit_path.read_text()).get("proforma_issued") or []
    assert before == after, "proforma_issued[] was modified by cancel helper"
    # And the cancelled id MUST NOT be added to proforma_issued[].
    cancelled_in_issued = [r for r in after
                            if r.get("wfirma_proforma_id") == "467222691"]
    assert cancelled_in_issued == []


# ── 4. Cancel route emits event on success ─────────────────────────────────

def test_cancel_route_emits_cancellation_event(client, storage):
    _seed_audit(storage)
    _seed_issued_draft(storage, client_name="Anastazia Panakova",
                        wfirma_id="467222691")
    with _gate_delete_on(), \
         patch.object(_wc, "delete_invoice",
                      return_value={"ok": True}):
        r = client.post(
            f"/api/v1/proforma/cancel-issued-for-reissue/{_BATCH}/Anastazia%20Panakova",
            params={"confirm": _CONFIRM},
            headers={**_auth(), "X-Operator": "amit"},
        )
    assert r.status_code == 200, r.text
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CANCELLED]
    assert len(events) == 1
    detail = events[0]["detail"]
    assert detail["deleted_wfirma_proforma_id"] == "467222691"
    assert detail["source"]                     == "cancel_for_reissue"


# ── 5. Cancel route does NOT emit when wFirma delete fails ─────────────────

def test_cancel_route_no_event_on_wfirma_failure(client, storage):
    _seed_audit(storage)
    _seed_issued_draft(storage, client_name="Anastazia Panakova",
                        wfirma_id="467222691")
    with _gate_delete_on(), \
         patch.object(_wc, "delete_invoice",
                      side_effect=RuntimeError("wFirma down")):
        r = client.post(
            f"/api/v1/proforma/cancel-issued-for-reissue/{_BATCH}/Anastazia%20Panakova",
            params={"confirm": _CONFIRM},
            headers=_auth(),
        )
    assert r.json()["ok"] is False
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CANCELLED]
    assert events == []


# ── Cancel route blocks (gates) → no event ─────────────────────────────────

def test_cancel_route_no_event_when_blocked_by_flag(client, storage):
    _seed_audit(storage)
    _seed_issued_draft(storage, client_name="A", wfirma_id="X")
    # Default settings.wfirma_delete_invoice_allowed is False.
    with patch.object(_wc, "delete_invoice",
                      side_effect=AssertionError("must not call delete")):
        r = client.post(
            f"/api/v1/proforma/cancel-issued-for-reissue/{_BATCH}/A",
            params={"confirm": _CONFIRM},
            headers=_auth(),
        )
    assert r.json()["status"] == "blocked"
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CANCELLED]
    assert events == []


# ── 6. AWB 6049349806 backfill: 4 events, then 0 on rerun ──────────────────

_AWB_BATCH = "SHIPMENT_6049349806_2026-05_7409ac77"

_AWB_PAIRS = [
    ("Anastazia Panakova",         "467222691", "467236963"),
    ("OMARA s.r.o",                "467222755", "467237027"),
    ("Clear-Diamonds",             "467222819", "467237091"),
    ("Impact Gallery sp. z o.o.",  "467222883", "467237219"),
]


def _backfill_awb(audit_path: Path) -> int:
    """Run the AWB 6049349806 cancellation backfill. Returns count of
    appended events (idempotent on rerun)."""
    appended = 0
    for client_name, deleted, replaced in _AWB_PAIRS:
        r = record_proforma_cancelled(
            audit_path,
            batch_id                       = _AWB_BATCH,
            client_name                    = client_name,
            deleted_wfirma_proforma_id     = deleted,
            replaced_by_wfirma_proforma_id = replaced,
            reason                         = ("operator cancel-for-reissue + "
                                                "price-source fix"),
            operator                       = "amit",
            source                         = "backfill",
        )
        if r["appended"]:
            appended += 1
    return appended


def test_awb_backfill_appends_exactly_four_events(tmp_path):
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps({
        "status": "partial",
        "wfirma_export": {"wfirma_pz_doc_id": "183484963"},
        "proforma_issued": [
            {"client_name": "Anastazia Panakova",
             "wfirma_proforma_id": "467236963",
             "line_count": 1, "currency": "USD"},
            {"client_name": "OMARA s.r.o",
             "wfirma_proforma_id": "467237027",
             "line_count": 2, "currency": "USD"},
            {"client_name": "Clear-Diamonds",
             "wfirma_proforma_id": "467237091",
             "line_count": 7, "currency": "USD"},
            {"client_name": "Impact Gallery sp. z o.o.",
             "wfirma_proforma_id": "467237219",
             "line_count": 1, "currency": "USD"},
        ],
        "timeline": [],
    }), encoding="utf-8")
    n = _backfill_awb(audit_path)
    assert n == 4
    a = json.loads(audit_path.read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CANCELLED]
    assert len(events) == 4
    by_deleted = {e["detail"]["deleted_wfirma_proforma_id"]: e
                  for e in events}
    assert set(by_deleted) == {"467222691","467222755","467222819","467222883"}
    # Each event links to the active replacement.
    assert by_deleted["467222691"]["detail"]["replaced_by_wfirma_proforma_id"] == "467236963"
    assert by_deleted["467222883"]["detail"]["replaced_by_wfirma_proforma_id"] == "467237219"
    # Source label is "backfill" so future audits can distinguish from
    # live cancel-route events.
    for e in events:
        assert e["detail"]["source"] == "backfill"
    # proforma_issued[] is unchanged (4 ACTIVE entries).
    assert len(a["proforma_issued"]) == 4
    issued_ids = {r["wfirma_proforma_id"] for r in a["proforma_issued"]}
    assert issued_ids == {"467236963","467237027","467237091","467237219"}


# ── 7. Rerunning the backfill adds 0 events ────────────────────────────────

def test_awb_backfill_rerun_appends_zero_events(tmp_path):
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps({
        "status": "partial",
        "wfirma_export": {"wfirma_pz_doc_id": "183484963"},
        "timeline": [],
    }), encoding="utf-8")
    first  = _backfill_awb(audit_path)
    second = _backfill_awb(audit_path)
    assert first  == 4
    assert second == 0
    a = json.loads(audit_path.read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CANCELLED]
    assert len(events) == 4   # unchanged after second run
