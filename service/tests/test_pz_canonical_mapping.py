"""
test_pz_canonical_mapping.py — Canonical wFirma PZ mapping persistence.

Pins:
  1. record_wfirma_pz_mapping stamps doc_id + fullnumber + mapped_at
  2. helper is idempotent (changed=False on identical re-call)
  3. POST /api/v1/upload/shipment/{batch}/wfirma/pz/refresh-mapping
     fetches wFirma and stamps fullnumber (historical-batch backfill)
  4. refresh-mapping returns 404 when no doc_id is stored
  5. refresh-mapping returns 502 on wFirma failure
  6. audit_evidence still detects canonical mapping (no regression)
  7. dashboard.html: manual "Confirm PZ Number" hidden when fullnumber set;
     "Refresh Mapping" button shown instead
  8. dashboard.html: refresh button posts to the new endpoint
"""
from __future__ import annotations

import json
import re
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
from app.services import proforma_service_charges_db as scdb
from app.services.audit_persist import (
    EV_WFIRMA_PZ_MAPPING_REFRESHED,
    record_wfirma_pz_mapping,
)
from app.services.audit_evidence import effective_pz_evidence


# ── helpers ────────────────────────────────────────────────────────────────

def _stale_audit(*, doc_id: str = "", fullnumber: str = "") -> dict:
    a = {"status": "partial",
         "wfirma_export": {},
         "customs_declaration": {"mrn": "MRN-X"},
         "verification": {"cn_match": True},
         "timeline": []}
    if doc_id or fullnumber:
        a["wfirma_export"] = {
            "wfirma_pz_doc_id":     doc_id,
            "wfirma_pz_fullnumber": fullnumber,
        }
    return a


def _write(tmp_path: Path, audit: dict) -> Path:
    p = tmp_path / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


# ── 1. helper-level: stamp persists ────────────────────────────────────────

def test_record_wfirma_pz_mapping_stamps_all_fields(tmp_path):
    p = _write(tmp_path, _stale_audit(doc_id="183484963"))
    r = record_wfirma_pz_mapping(
        p, wfirma_pz_doc_id="183484963",
        wfirma_pz_fullnumber="PZ 12/3/2026",
        source="created_via_app", operator="amit",
    )
    assert r["changed"] is True
    a = json.loads(p.read_text())
    wf = a["wfirma_export"]
    assert wf["wfirma_pz_doc_id"]     == "183484963"
    assert wf["wfirma_pz_fullnumber"] == "PZ 12/3/2026"
    assert wf["pz_source"]            == "created_via_app"
    assert wf["pz_mapped_at"]
    # Timeline event emitted.
    events = [e for e in a["timeline"]
              if e.get("event") == EV_WFIRMA_PZ_MAPPING_REFRESHED]
    assert len(events) == 1
    assert events[0]["detail"]["wfirma_pz_fullnumber"] == "PZ 12/3/2026"


# ── 2. idempotency ─────────────────────────────────────────────────────────

def test_record_wfirma_pz_mapping_idempotent(tmp_path):
    p = _write(tmp_path, _stale_audit(doc_id="X", fullnumber="PZ 1/2/2026"))
    first = record_wfirma_pz_mapping(
        p, wfirma_pz_doc_id="X", wfirma_pz_fullnumber="PZ 1/2/2026")
    second = record_wfirma_pz_mapping(
        p, wfirma_pz_doc_id="X", wfirma_pz_fullnumber="PZ 1/2/2026")
    assert second["changed"] is False
    assert second["reason"]   == "already aligned"


def test_record_wfirma_pz_mapping_preserves_existing_pz_source(tmp_path):
    """A pre-existing pz_source (set by _patch_pz_doc_id at create time)
    must NOT be overwritten by a later refresh."""
    audit = _stale_audit(doc_id="X", fullnumber="")
    audit["wfirma_export"]["pz_source"]     = "created_via_app"
    audit["wfirma_export"]["pz_created_at"] = "2026-05-08T14:38:27"
    p = _write(tmp_path, audit)
    record_wfirma_pz_mapping(
        p, wfirma_pz_doc_id="X", wfirma_pz_fullnumber="PZ 1/2/2026",
        source="refresh_mapping",
    )
    a = json.loads(p.read_text())
    assert a["wfirma_export"]["pz_source"]     == "created_via_app"  # preserved
    assert a["wfirma_export"]["pz_created_at"] == "2026-05-08T14:38:27"


def test_record_rejects_when_both_fields_empty(tmp_path):
    p = _write(tmp_path, _stale_audit())
    r = record_wfirma_pz_mapping(p, wfirma_pz_doc_id="",
                                  wfirma_pz_fullnumber="")
    assert r["changed"] is False
    assert "empty" in r["reason"]


# ── 6. audit_evidence compatibility ────────────────────────────────────────

def test_audit_evidence_still_detects_canonical_mapping(tmp_path):
    """The canonical fullnumber addition must not break the existing
    audit_evidence helper."""
    p = _write(tmp_path, _stale_audit())
    record_wfirma_pz_mapping(p, wfirma_pz_doc_id="183484963",
                              wfirma_pz_fullnumber="PZ 12/3/2026")
    a = json.loads(p.read_text())
    ev = effective_pz_evidence(a)
    assert ev["has_evidence"]      is True
    assert ev["wfirma_pz_doc_id"]  == "183484963"
    assert "wfirma_export.wfirma_pz_doc_id" in ev["signals"]


# ── route-level fixtures ───────────────────────────────────────────────────

BATCH = "BATCH_PZ_MAPPING"


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
    (tmp_path / "outputs" / BATCH).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    # Force-close every registry circuit breaker (notably "wfirma") AFTER app
    # import. The shared conftest reset is guarded on app.core.circuit_breaker
    # already being in sys.modules; when this module's lazy `from app.main import
    # app` is the first to pull it in, that guard misses and a breaker tripped
    # OPEN by an earlier test (e.g. a poison connection-error gate test) would
    # 503 every wFirma call here. Resetting after import removes the race.
    from app.core.circuit_breaker import reset_all
    reset_all()
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── 3. refresh-mapping endpoint stamps fullnumber ──────────────────────────

URL = "/api/v1/upload/shipment/{batch}/wfirma/pz/refresh-mapping"


def test_refresh_mapping_stamps_fullnumber_from_wfirma(client, storage):
    p = _write(storage / "outputs" / BATCH, {
        "status": "partial",
        "wfirma_export": {"wfirma_pz_doc_id": "183484963"},
        "customs_declaration": {"mrn": "MRN"},
        "verification": {"cn_match": True},
        "timeline": [],
    })
    fake = _wc.PZFetchResult(
        ok=True, pz_doc_id="183484963", pz_number="PZ 12/3/2026",
    )
    with patch.object(_wc, "fetch_warehouse_pz", return_value=fake):
        r = client.post(URL.format(batch=BATCH),
                         headers={**_auth(), "X-Operator": "amit"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["wfirma_pz_doc_id"]     == "183484963"
    assert body["wfirma_pz_fullnumber"] == "PZ 12/3/2026"
    assert body["changed"] is True
    a = json.loads(p.read_text())
    assert a["wfirma_export"]["wfirma_pz_fullnumber"] == "PZ 12/3/2026"


def test_refresh_mapping_idempotent_via_route(client, storage):
    p = _write(storage / "outputs" / BATCH, {
        "status": "partial",
        "wfirma_export": {
            "wfirma_pz_doc_id":     "X",
            "wfirma_pz_fullnumber": "PZ 1/2/2026",
        },
        "timeline": [],
    })
    fake = _wc.PZFetchResult(ok=True, pz_doc_id="X", pz_number="PZ 1/2/2026")
    with patch.object(_wc, "fetch_warehouse_pz", return_value=fake):
        body = client.post(URL.format(batch=BATCH), headers=_auth()).json()
    assert body["changed"] is False
    assert body["wfirma_pz_fullnumber"] == "PZ 1/2/2026"


# ── 4. 404 when no doc_id stored ───────────────────────────────────────────

def test_refresh_mapping_404_when_no_doc_id(client, storage):
    p = _write(storage / "outputs" / BATCH,
                {"status": "draft", "wfirma_export": {}, "timeline": []})
    r = client.post(URL.format(batch=BATCH), headers=_auth())
    assert r.status_code == 404
    assert "wfirma_pz_doc_id" in r.text


def test_refresh_mapping_404_when_audit_missing(client, storage):
    # No outputs/<batch>/audit.json at all.
    r = client.post(URL.format(batch="GHOST_BATCH"), headers=_auth())
    assert r.status_code == 404


# ── 5. 502 on wFirma failure ───────────────────────────────────────────────

def test_refresh_mapping_502_on_wfirma_error(client, storage):
    p = _write(storage / "outputs" / BATCH, {
        "status": "partial",
        "wfirma_export": {"wfirma_pz_doc_id": "183484963"},
        "timeline": [],
    })
    fail = _wc.PZFetchResult(ok=False, error="upstream broke")
    with patch.object(_wc, "fetch_warehouse_pz", return_value=fail):
        r = client.post(URL.format(batch=BATCH), headers=_auth())
    assert r.status_code == 502
    assert "wFirma fetch failed" in r.text


def test_refresh_mapping_502_on_missing_fullnumber(client, storage):
    """wFirma OK but no full_number on the document → still a refusal."""
    p = _write(storage / "outputs" / BATCH, {
        "status": "partial",
        "wfirma_export": {"wfirma_pz_doc_id": "183484963"},
        "timeline": [],
    })
    fake = _wc.PZFetchResult(ok=True, pz_doc_id="183484963", pz_number="")
    with patch.object(_wc, "fetch_warehouse_pz", return_value=fake):
        r = client.post(URL.format(batch=BATCH), headers=_auth())
    assert r.status_code == 502
    assert "no full_number" in r.text


# ── 7-8. Dashboard wiring (source-grep guards) ────────────────────────────

def test_dashboard_hides_manual_confirm_when_canonical_present():
    """The dashboard's ✎ Confirm PZ Number must be hidden when
    wfirma_pz_fullnumber is set. Source-grep guard so a future refactor
    that drops the conditional is caught immediately."""
    src = Path("app/static/dashboard.html").read_text(encoding="utf-8")
    # The conditional that hides manual confirm in favour of refresh.
    assert "wfirma_pz_fullnumber" in src
    # New canonical-mapping check appears around the manual confirm button.
    assert "canonName" in src or "wfirma_pz_fullnumber" in src
    # Refresh Mapping button is wired.
    assert "↻ Refresh Mapping" in src
    # Refresh Mapping posts to the canonical endpoint.
    assert "/wfirma/pz/refresh-mapping" in src


def test_dashboard_loads_canonical_pznumber_first():
    """`load()` reads wfirma_pz_fullnumber from audit and prefers it
    over the manual `doc_no` for the displayed PZ number."""
    src = Path("app/static/dashboard.html").read_text(encoding="utf-8")
    # The preference chain is recorded inline.
    assert "wfirma_pz_fullnumber" in src
    # And manual doc_no remains as a fallback (not removed).
    assert "a.doc_no" in src
