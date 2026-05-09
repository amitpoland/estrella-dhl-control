"""
test_proforma_drafts_lifecycle_phase2.py — Phase 2:
auto-create local editable Proforma Drafts after sales packing
upload/reingest, plus the three read-only draft endpoints.

Tests are tightly scoped to the new helper + endpoints. The intake
HTTP path is exercised via the helper directly to avoid pulling in
the full multipart upload pipeline (which has many unrelated parsers
and external dependencies).

Coverage:
  1. _auto_create_draft_for_client (intake helper) creates one local
     draft per client with state='draft', version=1
  2. Draft creation works without PZ evidence (the helper never reads
     packing.db / warehouse.db; the only inputs are the line records)
  3. Helper is idempotent — calling it twice with the same key does
     NOT duplicate the draft and does NOT replace the lines
  4. editable_lines_json contains sales prices/currency from the
     packing list line records
  5. PND-corrected product codes (caller passed product_code=PND-resolved)
     persist into draft lines
  6. created_from_sales_packing event recorded on first creation
  7. GET /api/v1/proforma/drafts/{batch_id} returns summaries
  8. GET /api/v1/proforma/draft/{draft_id} returns full editable payload
  9. GET /api/v1/proforma/draft/{draft_id}/events returns event list
 10. Existing 'issued' rows (e.g. AWB 6049349806) read as draft_state='posted'
 11. Phase 1 helpers continue to work unchanged (regression check)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb


# ── tiny test helpers ────────────────────────────────────────────────────────

def _auth_headers():
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def db_path(tmp_path) -> Path:
    """A tmp drafts DB initialised with the Phase 1 schema."""
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


@pytest.fixture()
def client(tmp_path) -> TestClient:
    """TestClient with settings.storage_root redirected to tmp_path so
    the route's ``_proforma_db_path()`` lands in the tmp dir."""
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _sample_lines():
    """Sales-packing-style line records as the intake handler builds them."""
    return [
        {
            "client_name":  "ACME",
            "client_ref":   "PO-9001",
            "product_code": "RNG-100",
            "design_no":    "D100",
            "bag_id":       "B1",
            "quantity":     2,
            "remarks":      "",
            "unit_price":   25.50,
            "total_value":  51.00,
            "currency":     "EUR",
            "price_source": "packing_list",
        },
        {
            "client_name":  "ACME",
            "client_ref":   "PO-9001",
            "product_code": "RNG-200",
            "design_no":    "D200",
            "bag_id":       "B2",
            "quantity":     1,
            "remarks":      "",
            "unit_price":   100.00,
            "total_value":  100.00,
            "currency":     "EUR",
            "price_source": "packing_list",
        },
    ]


# ── 1, 2. Auto-create — basic shape, no PZ evidence required ────────────────

def test_auto_create_draft_basic(db_path):
    draft, was_created = pildb.auto_create_draft_from_sales_packing(
        db_path,
        batch_id    = "B1",
        client_name = "ACME",
        currency    = "EUR",
        lines       = _sample_lines(),
        operator    = "intake",
    )
    assert was_created is True
    assert draft.id and draft.id > 0
    assert draft.batch_id    == "B1"
    assert draft.client_name == "ACME"
    assert draft.draft_state   == "draft"
    assert draft.draft_version == 1
    assert draft.currency      == "EUR"
    # Phase 2 uses a neutral legacy status outside the Phase 1 backfill
    # map so re-running init_db never clobbers the explicit draft_state.
    assert draft.status == "draft"


def test_auto_create_does_not_require_pz(db_path):
    """The helper takes only line records — it never opens packing.db,
    warehouse.db, or audit.json. Smoke test: it works with no other
    DB file present."""
    draft, was_created = pildb.auto_create_draft_from_sales_packing(
        db_path,
        batch_id="B-NOPZ", client_name="ACME",
        currency="USD", lines=_sample_lines(),
    )
    assert was_created
    assert draft.draft_state == "draft"


# ── 3. Idempotency ───────────────────────────────────────────────────────────

def test_auto_create_is_idempotent(db_path):
    d1, c1 = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(),
    )
    d2, c2 = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(),
    )
    assert c1 is True
    assert c2 is False
    assert d1.id == d2.id
    # Second call must not bump draft_version or replace any lines.
    assert d2.draft_version == 1
    assert d2.editable_lines_json == d1.editable_lines_json


def test_auto_create_idempotent_with_modified_lines(db_path):
    """Even if a re-ingest passes DIFFERENT lines, the live draft must
    not be silently replaced — Phase 2 only seeds at first creation."""
    pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(),
    )
    # Re-call with a totally different line set
    d2, c2 = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR",
        lines=[{"product_code": "ZZZ", "design_no": "ZZZ", "qty": 99,
                "unit_price": 1.0, "currency": "EUR"}],
    )
    assert c2 is False
    parsed = json.loads(d2.editable_lines_json)
    # Original two lines preserved.
    codes = {ln["product_code"] for ln in parsed}
    assert codes == {"RNG-100", "RNG-200"}


# ── 4. editable_lines_json carries sales prices + currency ──────────────────

def test_editable_lines_carry_prices_and_currency(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(),
    )
    lines = json.loads(draft.editable_lines_json)
    assert len(lines) == 2
    by_code = {ln["product_code"]: ln for ln in lines}
    assert by_code["RNG-100"]["qty"]          == 2
    assert by_code["RNG-100"]["unit_price"]   == 25.50
    assert by_code["RNG-100"]["currency"]     == "EUR"
    assert by_code["RNG-100"]["price_source"] == "packing_list"
    assert by_code["RNG-100"]["client_ref"]   == "PO-9001"
    assert by_code["RNG-200"]["qty"]          == 1
    assert by_code["RNG-200"]["unit_price"]   == 100.00


def test_service_charges_default_empty(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(),
    )
    assert draft.service_charges_json == "[]"
    assert json.loads(draft.service_charges_json) == []
    assert draft.buyer_override_json   == "{}"
    assert draft.ship_to_override_json == "{}"
    assert draft.payment_terms_json    == "{}"
    assert draft.remarks               == ""


# ── 5. PND-corrected product codes ───────────────────────────────────────────

def test_pnd_corrected_codes_persist(db_path):
    """The intake handler's PND tiebreak resolves design_no='PND' rows
    into a real product_code. The auto-create helper must preserve that
    real code (and not fall back to 'PND')."""
    lines = [
        # Operator-side PND (no product_code yet) — should be skipped at
        # the upstream level. We pass only the resolved version.
        {
            "client_name":  "ACME",
            "product_code": "PND-PEND-005",   # resolved by tiebreak
            "design_no":    "PND",
            "quantity":     5,
            "unit_price":   60.0,
            "currency":     "EUR",
            "price_source": "packing_list",
        },
    ]
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=lines,
    )
    parsed = json.loads(draft.editable_lines_json)
    assert len(parsed) == 1
    assert parsed[0]["product_code"] == "PND-PEND-005"
    assert parsed[0]["design_no"]    == "PND"


def test_lines_with_no_code_or_design_are_skipped(db_path):
    """Defensive: empty rows must not produce empty draft lines."""
    lines = [
        {"product_code": "", "design_no": "", "qty": 0},
        {"product_code": "OK", "design_no": "OK", "qty": 1, "unit_price": 5.0,
         "currency": "EUR"},
    ]
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=lines,
    )
    parsed = json.loads(draft.editable_lines_json)
    assert len(parsed) == 1
    assert parsed[0]["product_code"] == "OK"


# ── 6. created_from_sales_packing event ──────────────────────────────────────

def test_created_event_recorded_once(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(), operator="intake",
    )
    events = pildb.list_draft_events(db_path, draft.id)
    assert len(events) == 1
    assert events[0]["event"]    == "created_from_sales_packing"
    assert events[0]["operator"] == "intake"
    detail = json.loads(events[0]["detail_json"])
    assert detail["batch_id"]    == "B1"
    assert detail["client_name"] == "ACME"
    assert detail["currency"]    == "EUR"
    assert detail["line_count"]  == 2

    # Idempotent re-call must NOT record a second event.
    pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(), operator="intake",
    )
    events = pildb.list_draft_events(db_path, draft.id)
    assert len(events) == 1


def test_record_draft_event_helper_validation(db_path):
    """Direct unit test on _record_draft_event — required for Phase 3+."""
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(),
    )
    # Happy path — append a custom event
    eid = pildb._record_draft_event(
        db_path, draft_id=draft.id, event="manual_test",
        detail_json='{"k":"v"}', operator="op1",
    )
    assert eid > 0
    # Validation
    with pytest.raises(ValueError):
        pildb._record_draft_event(db_path, draft_id=0, event="x")
    with pytest.raises(ValueError):
        pildb._record_draft_event(db_path, draft_id=draft.id, event="")
    with pytest.raises(ValueError):
        pildb._record_draft_event(db_path, draft_id=draft.id,
                                   event="x", detail_json="not-json")


# ── 7, 8, 9. Read endpoints ──────────────────────────────────────────────────

def test_list_drafts_endpoint(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(),
    )
    pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="OTHER",
        currency="USD", lines=_sample_lines(),
    )
    r = client.get("/api/v1/proforma/drafts/B1", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["batch_id"] == "B1"
    assert body["count"]    == 2
    names = {d["client_name"] for d in body["drafts"]}
    assert names == {"ACME", "OTHER"}
    # Summary must NOT include the big JSON blobs.
    for d in body["drafts"]:
        assert "editable_lines"     not in d
        assert "service_charges"    not in d
        assert d["draft_state"]   == "draft"
        assert d["draft_version"] == 1


def test_list_drafts_endpoint_empty_batch(client):
    r = client.get("/api/v1/proforma/drafts/NOPE", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["count"]  == 0
    assert body["drafts"] == []


def test_list_drafts_rejects_bad_batch_id(client):
    r = client.get("/api/v1/proforma/drafts/ ", headers=_auth_headers())
    # 400 batch_id is required (whitespace)
    assert r.status_code == 400


def test_get_one_draft_endpoint(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(),
    )
    r = client.get(f"/api/v1/proforma/draft/{draft.id}",
                    headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    d = body["draft"]
    assert d["id"]          == draft.id
    assert d["draft_state"] == "draft"
    assert d["currency"]    == "EUR"
    # Full payload must include parsed editable_lines + service_charges.
    assert isinstance(d["editable_lines"], list)
    assert len(d["editable_lines"]) == 2
    assert d["editable_lines"][0]["product_code"] in {"RNG-100", "RNG-200"}
    assert isinstance(d["service_charges"], list)
    assert d["service_charges"] == []
    assert d["buyer_override"]  == {}


def test_get_one_draft_404(client):
    r = client.get("/api/v1/proforma/draft/99999", headers=_auth_headers())
    assert r.status_code == 404


def test_get_draft_events_endpoint(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_sample_lines(),
    )
    r = client.get(f"/api/v1/proforma/draft/{draft.id}/events",
                    headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["draft_id"] == draft.id
    assert body["count"]    == 1
    assert body["events"][0]["event"] == "created_from_sales_packing"


def test_get_draft_events_404(client):
    r = client.get("/api/v1/proforma/draft/99999/events",
                    headers=_auth_headers())
    assert r.status_code == 404


# ── 10. Existing legacy 'issued' rows (e.g. AWB 6049349806) read as posted ─

def test_legacy_issued_rows_read_as_posted(db_path):
    """Insert a row the way Phase-1-and-earlier code did (status='issued',
    no draft_state column written) and confirm the read shim surfaces
    draft_state='posted'."""
    now = "2026-04-01T12:00:00Z"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """INSERT INTO proforma_drafts
               (batch_id, client_name, status, currency, source_lines_json,
                wfirma_proforma_id, created_at, updated_at, draft_state)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            ("SHIPMENT_6049349806_2026-05_7409ac77", "CLIENT-A",
             "issued", "EUR", "[]", "WFIRMA-PROF-1", now, now, "posted"),
        )
        conn.commit()
    drafts = pildb.list_drafts_for_batch(
        db_path, "SHIPMENT_6049349806_2026-05_7409ac77",
    )
    assert len(drafts) == 1
    assert drafts[0].draft_state == "posted"
    assert drafts[0].status      == "issued"
    assert drafts[0].draft_version == 1


# ── 11. Phase 1 helpers continue to work ─────────────────────────────────────

def test_phase1_legacy_helpers_still_work(db_path):
    """Phase 2 must not regress upsert_pending_draft / mark_draft_issued
    / mark_draft_failed semantics."""
    d, created = pildb.upsert_pending_draft(
        db_path, batch_id="LEGACY-1", client_name="OLDCLIENT",
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    assert created is True
    assert d.status == "pending_local"
    pildb.mark_draft_issued(
        db_path, "LEGACY-1", "OLDCLIENT",
        wfirma_proforma_id="WFIRMA-1234",
    )
    final = pildb.get_draft(db_path, "LEGACY-1", "OLDCLIENT")
    assert final.status             == "issued"
    assert final.wfirma_proforma_id == "WFIRMA-1234"
    # And after issued, the read shim still maps to 'posted'.
    assert final.draft_state == "posted"


# ── 12. Intake helper smoke test (the route-side wrapper) ────────────────────

def test_intake_helper_calls_auto_create(tmp_path, monkeypatch):
    """The intake-route helper ``_auto_create_draft_for_client`` must
    forward sales_packing line records into auto_create_draft_from_sales_packing
    with the right shape (qty/unit_price/currency/client_ref preserved)."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.api import routes_intake as ri

    line_records = [
        {
            "client_name":  "ACME",
            "client_ref":   "PO-1",
            "product_code": "X",
            "design_no":    "X",
            "quantity":     3,
            "unit_price":   10.0,
            "currency":     "USD",
            "price_source": "packing_list",
        },
    ]
    ri._auto_create_draft_for_client(
        batch_id="B-INTAKE", client="ACME", client_ref="PO-1",
        currency="USD", line_records=line_records, operator="intake",
    )
    db = tmp_path / "proforma_links.db"
    drafts = pildb.list_drafts_for_batch(db, "B-INTAKE")
    assert len(drafts) == 1
    assert drafts[0].client_name == "ACME"
    assert drafts[0].draft_state == "draft"
    assert drafts[0].currency    == "USD"
    parsed = json.loads(drafts[0].editable_lines_json)
    assert parsed[0]["qty"]        == 3
    assert parsed[0]["unit_price"] == 10.0
    assert parsed[0]["currency"]   == "USD"
    assert parsed[0]["client_ref"] == "PO-1"


def test_intake_helper_swallows_failures(tmp_path, monkeypatch, caplog):
    """A draft-create failure must NOT raise — it's logged and swallowed
    so intake response is never blocked."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.api import routes_intake as ri

    # Force the underlying helper to raise.
    def _boom(*a, **kw):
        raise RuntimeError("simulated DB failure")
    monkeypatch.setattr(pildb, "auto_create_draft_from_sales_packing", _boom)

    # Must NOT raise.
    ri._auto_create_draft_for_client(
        batch_id="B", client="ACME", client_ref="",
        currency="EUR",
        line_records=[{"product_code": "X", "design_no": "X", "quantity": 1,
                       "unit_price": 1.0, "currency": "EUR"}],
        operator="intake",
    )


def test_intake_helper_skips_no_lines(tmp_path, monkeypatch):
    """Empty line_records → no-op, no draft inserted."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.api import routes_intake as ri
    ri._auto_create_draft_for_client(
        batch_id="B", client="ACME", client_ref="",
        currency="EUR", line_records=[], operator="intake",
    )
    db = tmp_path / "proforma_links.db"
    if db.exists():
        assert pildb.list_drafts_for_batch(db, "B") == []
