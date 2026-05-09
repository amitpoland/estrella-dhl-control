"""
test_audit_evidence.py — Read-time effective PZ/customs evidence.

Pins the contract for app/services/audit_evidence.effective_pz_evidence,
plus its integration into:
  - routes_lifecycle._customs_cleared_from_audit (mark-direct-dispatch path)
  - routes_packing._pz_done (seed-batch auto target)

Stale-audit shape used in tests mirrors AWB 6049349806 (live: PZ doc
183484963 created, ``status="failed"``, ``wfirma_export`` empty, only the
``wfirma_pz_created`` timeline event carries the proof).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.audit_evidence import effective_pz_evidence


# ── helpers ──────────────────────────────────────────────────────────────────

def _stale_audit_with_timeline(doc_id: str = "183484963") -> dict:
    """AWB 6049349806-shape stale audit: status=failed, wfirma_export empty,
    but a wfirma_pz_created timeline entry carries the doc id."""
    return {
        "status": "failed",
        "wfirma_export": {},
        "customs_declaration": {},
        "timeline": [
            {"ts": "2026-05-06T00:00:00+00:00",
             "event": "wfirma_pz_created",
             "trigger_source": "system", "actor": "wfirma",
             "detail": {"batch_id": "B", "wfirma_pz_doc_id": doc_id,
                        "line_count": 9, "operator": "amit"}},
        ],
    }


def _stale_audit_with_mrn(mrn: str = "26PL44302D00AUCWR3") -> dict:
    return {
        "status": "failed",
        "wfirma_export": {},
        "customs_declaration": {"mrn": mrn},
        "timeline": [],
    }


def _empty_audit() -> dict:
    return {"status": "failed", "wfirma_export": {},
            "customs_declaration": {}, "timeline": []}


# ── 1. Stale audit + wfirma_pz_created timeline → has_evidence=True ─────────

def test_timeline_wfirma_pz_created_is_evidence():
    a = _stale_audit_with_timeline("183484963")
    ev = effective_pz_evidence(a)
    assert ev["has_evidence"] is True
    assert "timeline:wfirma_pz_created" in ev["signals"]
    assert ev["wfirma_pz_doc_id"] == "183484963"
    # The export-side signal did NOT fire (empty in stale shape).
    assert "wfirma_export.wfirma_pz_doc_id" not in ev["signals"]


def test_timeline_event_without_doc_id_does_not_count():
    a = _empty_audit()
    a["timeline"] = [{
        "ts": "2026-05-06T00:00:00+00:00",
        "event": "wfirma_pz_created", "trigger_source": "system",
        "actor": "wfirma", "detail": {"batch_id": "B"},  # no doc id
    }]
    ev = effective_pz_evidence(a)
    assert ev["has_evidence"] is False
    assert "timeline:wfirma_pz_created" not in ev["signals"]


# ── 2. customs_declaration.mrn alone is sufficient ──────────────────────────

def test_mrn_alone_is_evidence():
    ev = effective_pz_evidence(_stale_audit_with_mrn())
    assert ev["has_evidence"] is True
    assert "customs_declaration.mrn" in ev["signals"]


# ── 3. No reliable signal → has_evidence=False ──────────────────────────────

def test_no_signals_returns_false():
    ev = effective_pz_evidence(_empty_audit())
    assert ev["has_evidence"] is False
    assert ev["signals"] == []
    # All signal keys are listed as missing — operators see exactly what
    # the helper looked for.
    assert "wfirma_export.wfirma_pz_doc_id"  in ev["missing"]
    assert "timeline:wfirma_pz_created"      in ev["missing"]
    assert "customs_declaration.mrn"         in ev["missing"]


def test_non_dict_input_safe():
    """Defensive: callers must not raise when audit is None/garbage."""
    assert effective_pz_evidence(None)["has_evidence"] is False  # type: ignore[arg-type]
    assert effective_pz_evidence("nope")["has_evidence"] is False  # type: ignore[arg-type]
    assert effective_pz_evidence([])["has_evidence"] is False     # type: ignore[arg-type]


# ── Multi-signal aggregation ────────────────────────────────────────────────

def test_multiple_signals_listed_in_canonical_order():
    a = _stale_audit_with_timeline("183484963")
    a["wfirma_export"] = {"wfirma_pz_doc_id": "183484963"}
    a["customs_declaration"] = {"mrn": "MRN-1"}
    a["inputs"] = {"zc429": "/path/to/sad.pdf"}
    ev = effective_pz_evidence(a)
    assert ev["has_evidence"] is True
    sigs = ev["signals"]
    # Canonical order from _ALL_SIGNAL_KEYS: PZ-side first, then customs-side.
    assert sigs.index("wfirma_export.wfirma_pz_doc_id") < \
           sigs.index("timeline:wfirma_pz_created") < \
           sigs.index("customs_declaration.mrn") < \
           sigs.index("inputs.zc429")
    # Export id wins for canonical doc id (preferred over timeline).
    assert ev["wfirma_pz_doc_id"] == "183484963"


def test_export_doc_id_preferred_over_timeline():
    a = _stale_audit_with_timeline("OLD-ID")
    a["wfirma_export"] = {"wfirma_pz_doc_id": "NEW-ID"}
    ev = effective_pz_evidence(a)
    assert ev["wfirma_pz_doc_id"] == "NEW-ID"


# ── DHL/agency clearance signals still recognised ──────────────────────────

@pytest.mark.parametrize("audit_patch, expected", [
    ({"dhl_email": {"received": True}},      "dhl_email.received"),
    ({"dsk_received": True},                  "dsk_received"),
    ({"sad_received": True},                  "sad_received"),
    ({"agency_sad_received": True},           "agency_sad_received"),
    ({"clearance_status": "customs_cleared"}, "clearance_status"),
])
def test_post_dhl_signals_still_recognised(audit_patch, expected):
    a = _empty_audit()
    a.update(audit_patch)
    ev = effective_pz_evidence(a)
    assert ev["has_evidence"] is True
    assert expected in ev["signals"]


def test_unknown_clearance_status_does_not_count():
    a = _empty_audit()
    a["clearance_status"] = "still_pending"
    ev = effective_pz_evidence(a)
    assert ev["has_evidence"] is False
    assert "clearance_status" not in ev["signals"]


# ── 4. mark-direct-dispatch accepts stale-audit-with-timeline ───────────────
# (route-level integration test)

import sqlite3
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as _wc
from app.services import packing_db   as pdb
from app.services import warehouse_db as wdb
from app.services import document_db  as ddb
from app.services import wfirma_db    as wfdb
from app.services import inventory_state_engine as ise


_BATCH = "BATCH_AUDIT_EVIDENCE_INT"


@pytest.fixture(autouse=True)
def _prime_vat():
    _wc._VAT_CODE_ID_CACHE["23"] = "222"
    yield
    _wc._VAT_CODE_ID_CACHE.pop("23", None)


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    (tmp_path / "outputs" / _BATCH).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _seed_full_line(design_no="D-AE-1", product_code="EJL/AE/1") -> str:
    pdb.upsert_packing_lines([{
        "batch_id": _BATCH, "invoice_no": "INV/X",
        "invoice_line_position": 1, "product_code": product_code,
        "design_no": design_no, "bag_id": "", "tray_id": "",
        "item_type": "RNG", "uom": "PCS", "quantity": 1.0,
        "gross_weight": 0.0, "net_weight": 0.0,
        "metal": "", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": 1.0, "unit_price": 0.0, "total_value": 0.0,
    }])
    sc = f"{product_code}|sr1|{design_no}"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   batch_id=_BATCH)
    con = sqlite3.connect(str(wdb._db_path))
    con.execute(
        """INSERT INTO inventory_movement_events
           (id, batch_id, scan_code, action, from_location, to_location,
            operator, event_time, note, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), _BATCH, sc, "RECEIVE",
         "", "MAIN-WH-INBOUND", "amit",
         datetime.now(timezone.utc).isoformat(), "",
         datetime.now(timezone.utc).isoformat()),
    )
    con.commit(); con.close()
    return sc


def _write_stale_audit_with_timeline(storage, doc_id="183484963"):
    p = storage / "outputs" / _BATCH / "audit.json"
    p.write_text(json.dumps(_stale_audit_with_timeline(doc_id)),
                 encoding="utf-8")


URL = "/api/v1/inventory-state/mark-direct-dispatch"


def test_mark_direct_dispatch_accepts_stale_audit_with_timeline(client, storage):
    """AWB 6049349806 shape: status=failed, wfirma_export empty, only the
    timeline carries the doc id. The route must accept this evidence."""
    sc = _seed_full_line()
    _write_stale_audit_with_timeline(storage, "183484963")

    r = client.post(URL,
        headers={"X-API-KEY": settings.api_key or "test-key"},
        json={"batch_id": _BATCH, "scan_codes": [sc],
              "operator": "amit", "customer_allocation": "Clear-Diamonds Ltd",
              "evidence_note": "stale-audit / timeline only"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transitioned"] == 1
    assert "timeline:wfirma_pz_created" in body["customs_signals"]
    assert ise.get_state(sc)["state"] == ise.DIRECT_DISPATCH_READY


def test_mark_direct_dispatch_still_rejects_when_no_evidence(client, storage):
    """Strict rejection preserved: empty audit → 400."""
    sc = _seed_full_line(design_no="D-AE-2", product_code="EJL/AE/2")
    p = storage / "outputs" / _BATCH / "audit.json"
    p.write_text(json.dumps(_empty_audit()), encoding="utf-8")

    r = client.post(URL,
        headers={"X-API-KEY": settings.api_key or "test-key"},
        json={"batch_id": _BATCH, "scan_codes": [sc],
              "operator": "amit", "customer_allocation": "X"})
    assert r.status_code == 400
    assert "customs/PZ clearance evidence missing" in r.text
    assert ise.get_state(sc)["state"] == ise.PURCHASE_TRANSIT


# ── 5. seed-batch auto resolves WAREHOUSE_STOCK on stale-audit-with-timeline ──

def test_seed_batch_pz_done_recognises_timeline_event():
    """Direct unit test on routes_packing._pz_done: a stale audit whose
    only PZ proof is the timeline event must resolve as PZ-done."""
    from app.api.routes_packing import _pz_done
    assert _pz_done(_stale_audit_with_timeline("183484963")) is True


def test_seed_batch_pz_done_false_when_only_customs_side_signals():
    """Customs-only signals (MRN / DSK / SAD) prove customs cleared but
    NOT that the wFirma PZ document was issued. _pz_done must remain False
    for those — preserving business semantics."""
    from app.api.routes_packing import _pz_done
    a = _empty_audit()
    a["customs_declaration"] = {"mrn": "MRN-1"}
    a["dsk_received"] = True
    a["sad_received"] = True
    assert _pz_done(a) is False


def test_seed_batch_pz_done_false_on_empty_audit():
    from app.api.routes_packing import _pz_done
    assert _pz_done(_empty_audit()) is False


def test_seed_batch_pz_done_legacy_fields_still_work():
    """Regression: pre-existing fields (status/pz_generated/...) must still
    pass _pz_done without consulting the new helper."""
    from app.api.routes_packing import _pz_done
    assert _pz_done({"status": "success"}) is True
    assert _pz_done({"pz_generated": True}) is True
    assert _pz_done({"pz_pdf_filename": "pz.pdf"}) is True
