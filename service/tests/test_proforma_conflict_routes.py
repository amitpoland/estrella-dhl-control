"""
test_proforma_conflict_routes.py — ADR-029 PR-1 flag-gated route tests.

Drives the three conflict routes through the REAL FastAPI app (TestClient):

  POST /api/v1/proforma/draft/{id}/conflicts/scan
  GET  /api/v1/proforma/draft/{id}/conflicts
  POST /api/v1/proforma/draft/{id}/conflicts/{conflict_id}/resolve

Contract pinned here:
  • All three return 404 when ``conflict_detection_enabled`` is OFF (the surface
    is inert by default — flags ship OFF per ADR-029 §7).
  • With the flag ON, scan detects + persists, list reads back, resolve mutates.
  • resolve requires the X-Operator header (400 without it).
  • A conflict that belongs to another draft → 404 (cross-draft isolation).

Detection here uses a GBP draft → V4 bank_account_currency_unsupported (error),
which is customer-independent and therefore deterministic without seeding any
customer master.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_engine_candidates = [
    Path(__file__).parent.parent.parent / "engine",
    Path(__file__).parent.parent.parent.parent / "engine",
]
for _p in _engine_candidates:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break


BATCH  = "BATCH_ADR029_CONFLICTS"
CLIENT = "ADR029_CONFLICT_CLIENT"


# ── fixtures (mirror test_proforma_529_price_source_authority.py) ─────────────

@pytest.fixture()
def storage(tmp_path):
    from app.services import proforma_invoice_link_db as pildb
    pildb.init_db(tmp_path / "proforma_links.db")
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


def _op_headers():
    return {"X-Operator": "test-op", **_auth()}


def _enabled():
    """Patch the conflict flag ON for the duration of a test."""
    from app.core.config import settings
    return patch.object(settings, "conflict_detection_enabled", True)


def _seed_draft(storage: Path, currency: str = "GBP",
                client_name: str | None = None) -> int:
    # Unique batch+client per call — proforma_drafts has a UNIQUE constraint on
    # (batch_id, client_name, clone_generation), so multi-draft tests must vary it.
    suffix = uuid.uuid4().hex[:8]
    cn = client_name if client_name is not None else f"{CLIENT}_{suffix}"
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """
            INSERT INTO proforma_drafts
              (batch_id, client_name, status, currency, draft_state,
               wfirma_proforma_id, wfirma_proforma_fullnumber,
               source_lines_json, editable_lines_json, service_charges_json,
               clone_generation, draft_version,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
            """,
            (f"{BATCH}_{suffix}", cn, "draft", currency,
             "draft", None, "", "[]", "[]", "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _seed_customer_master(storage: Path, *, name: str, contractor_id: str,
                          default_currency: str = "EUR", country: str = "PL") -> None:
    """Seed one Customer Master row so the route's local customer resolution
    (draft.client_name → _resolve_customer → customer_master) succeeds.

    ``contractor_id`` is intentionally NON-NUMERIC in the regression test so the
    old ``int(cid)`` cast would raise ValueError → swallowed → customer never
    resolves. ``str(cid)`` is the fix; this row proves the wired path."""
    from app.services.customer_master_db import CustomerMaster, upsert_customer
    upsert_customer(
        storage / "customer_master.sqlite",
        CustomerMaster(
            bill_to_contractor_id=contractor_id,
            bill_to_name=name,
            country=country,
            default_currency=default_currency,
        ),
    )


# ── flag OFF → inert surface (404 everywhere) ─────────────────────────────────

def test_scan_404_when_flag_off(client):
    c, storage = client
    draft_id = _seed_draft(storage)
    r = c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
               headers=_op_headers())
    assert r.status_code == 404, r.text


def test_list_404_when_flag_off(client):
    c, storage = client
    draft_id = _seed_draft(storage)
    r = c.get(f"/api/v1/proforma/draft/{draft_id}/conflicts", headers=_auth())
    assert r.status_code == 404, r.text


def test_resolve_404_when_flag_off(client):
    c, storage = client
    draft_id = _seed_draft(storage)
    r = c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/1/resolve",
               json={"resolution_type": "revert"}, headers=_op_headers())
    assert r.status_code == 404, r.text


# ── flag ON → scan / list / resolve happy path ────────────────────────────────

def test_scan_detects_gbp_error_when_enabled(client):
    c, storage = client
    draft_id = _seed_draft(storage, currency="GBP")
    with _enabled():
        r = c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
                   headers=_op_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detected_count"] >= 1, body
    types = {cf["conflict_type"] for cf in body["conflicts"]}
    assert "bank_account_currency_unsupported" in types, body
    gbp = [cf for cf in body["conflicts"]
           if cf["conflict_type"] == "bank_account_currency_unsupported"][0]
    assert gbp["severity"] == "error"
    assert gbp["status"] == "open"
    assert gbp["proforma_id"] == str(draft_id)


def test_scan_404_for_unknown_draft(client):
    c, storage = client
    with _enabled():
        r = c.post("/api/v1/proforma/draft/987654/conflicts/scan",
                   headers=_op_headers())
    assert r.status_code == 404, r.text


def test_scan_is_idempotent_no_duplicate_rows(client):
    c, storage = client
    draft_id = _seed_draft(storage, currency="GBP")
    with _enabled():
        c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
               headers=_op_headers())
        r2 = c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
                    headers=_op_headers())
    body = r2.json()
    gbp = [cf for cf in body["conflicts"]
           if cf["conflict_type"] == "bank_account_currency_unsupported"]
    assert len(gbp) == 1, body  # refreshed in place, not duplicated


def test_list_reads_back_after_scan(client):
    c, storage = client
    draft_id = _seed_draft(storage, currency="GBP")
    with _enabled():
        c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
               headers=_op_headers())
        r = c.get(f"/api/v1/proforma/draft/{draft_id}/conflicts", headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    assert body["proforma_id"] == str(draft_id)


def test_list_status_filter(client):
    c, storage = client
    draft_id = _seed_draft(storage, currency="GBP")
    with _enabled():
        c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
               headers=_op_headers())
        r_open = c.get(f"/api/v1/proforma/draft/{draft_id}/conflicts?statuses=open",
                       headers=_auth())
        r_resolved = c.get(
            f"/api/v1/proforma/draft/{draft_id}/conflicts?statuses=resolved",
            headers=_auth())
    assert r_open.json()["count"] >= 1
    assert r_resolved.json()["count"] == 0


def test_resolve_flow_marks_acknowledged(client):
    c, storage = client
    draft_id = _seed_draft(storage, currency="GBP")
    with _enabled():
        scan = c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
                      headers=_op_headers()).json()
        cid = scan["conflicts"][0]["conflict_id"]
        r = c.post(
            f"/api/v1/proforma/draft/{draft_id}/conflicts/{cid}/resolve",
            json={"resolution_type": "accept_and_proceed"},
            headers=_op_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conflict"]["status"] == "acknowledged"
    assert body["conflict"]["resolved_by"] == "test-op"


def test_resolve_override_requires_reason(client):
    c, storage = client
    draft_id = _seed_draft(storage, currency="GBP")
    with _enabled():
        scan = c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
                      headers=_op_headers()).json()
        cid = scan["conflicts"][0]["conflict_id"]
        r = c.post(
            f"/api/v1/proforma/draft/{draft_id}/conflicts/{cid}/resolve",
            json={"resolution_type": "override_with_reason"},
            headers=_op_headers())
    assert r.status_code == 400, r.text


# ── attribution + isolation ───────────────────────────────────────────────────

def test_resolve_requires_operator_header(client):
    c, storage = client
    draft_id = _seed_draft(storage, currency="GBP")
    with _enabled():
        scan = c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
                      headers=_op_headers()).json()
        cid = scan["conflicts"][0]["conflict_id"]
        # No X-Operator header (auth only).
        r = c.post(
            f"/api/v1/proforma/draft/{draft_id}/conflicts/{cid}/resolve",
            json={"resolution_type": "revert"}, headers=_auth())
    assert r.status_code == 400, r.text
    assert "X-Operator" in r.json()["detail"]


def test_resolve_cross_draft_conflict_404(client):
    c, storage = client
    draft_a = _seed_draft(storage, currency="GBP")
    draft_b = _seed_draft(storage, currency="GBP")
    with _enabled():
        scan = c.post(f"/api/v1/proforma/draft/{draft_a}/conflicts/scan",
                      headers=_op_headers()).json()
        cid = scan["conflicts"][0]["conflict_id"]
        # Resolve via the WRONG draft path → conflict does not belong to it.
        r = c.post(
            f"/api/v1/proforma/draft/{draft_b}/conflicts/{cid}/resolve",
            json={"resolution_type": "revert"}, headers=_op_headers())
    assert r.status_code == 404, r.text


def test_resolve_unknown_conflict_404(client):
    c, storage = client
    draft_id = _seed_draft(storage, currency="GBP")
    with _enabled():
        r = c.post(
            f"/api/v1/proforma/draft/{draft_id}/conflicts/424242/resolve",
            json={"resolution_type": "revert"}, headers=_op_headers())
    assert r.status_code == 404, r.text


# ── customer-dependent detection through the real resolution path ─────────────
#
# Regression guard for the GAP-1 broken-link finding (ADR-029 PR-1 review):
# routes_proforma._resolve_customer_for_conflicts must look the customer up by
# the STRING contractor id. The earlier ``int(cid)`` cast raised ValueError on
# any non-numeric wFirma id and was swallowed into (None, None), so V3/V8
# (customer-dependent) detectors silently produced nothing and the scan always
# reported ``customer_resolved: false``. Seeding a NON-NUMERIC contractor id
# here fails loudly if that regression ever returns.

def test_scan_resolves_customer_and_emits_v3_currency_conflict(client):
    c, storage = client
    cn = f"ADR029 V3 Client {uuid.uuid4().hex[:8]}"
    _seed_customer_master(storage, name=cn, contractor_id="CUST-NONNUM-7",
                          default_currency="EUR")
    # Draft currency USD vs customer default EUR → V3 warning. USD is a
    # bank-supported currency, so no V4 noise — V3 is the clean signal.
    draft_id = _seed_draft(storage, currency="USD", client_name=cn)
    with _enabled():
        r = c.post(f"/api/v1/proforma/draft/{draft_id}/conflicts/scan",
                   headers=_op_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["customer_resolved"] is True, body
    types = {cf["conflict_type"] for cf in body["conflicts"]}
    assert "currency_vs_customer_default" in types, body
    v3 = [cf for cf in body["conflicts"]
          if cf["conflict_type"] == "currency_vs_customer_default"][0]
    assert v3["severity"] == "warning"
    assert v3["current_value"] == "USD"
    assert v3["master_value"] == "EUR"
