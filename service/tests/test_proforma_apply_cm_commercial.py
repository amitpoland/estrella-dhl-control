"""test_proforma_apply_cm_commercial.py — Slice 1: Preview→Apply for Customer
Master commercial defaults.

Tests:
1. blank draft + populated CM → preview offers the fields; apply(selected)
   persists exactly those to the draft; re-GET shows saved values.
2. non-empty draft field is NOT overwritten unless selected.
3. optimistic-lock conflict → 409.
4. CM unresolvable → 404.
5. audit event "commercial_defaults_from_customer_master" written with
   before/after and selected_fields.
6. reload durability: re-fetch draft shows persisted values.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ── path bootstrap ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")

from app.core.config import settings
from app.services import customer_master_db as cmdb
from app.services import proforma_invoice_link_db as pildb

# ── Synthetic test data ───────────────────────────────────────────────────────
CID    = "80000001"                  # synthetic contractor ID — no real PII
NAME   = "Test Commercial Client"
BATCH  = "BATCH_CM_COMMERCIAL_TEST"
CLIENT = "Test Commercial Client"

# Customer Master column values
_CM_PAYMENT_METHOD  = "transfer"
_CM_PAYMENT_DAYS    = 30
_CM_LANGUAGE_ID     = "1"
_CM_VAT_MODE        = "wdt"
_CM_FREIGHT_EUR     = Decimal("120.00")
_CM_FREIGHT_SVC_ID  = "13002743"
_CM_INS_RATE        = Decimal("0.0035")
_CM_INS_SVC_ID      = "13102217"


def _seed_cm(tmp: Path) -> None:
    """Seed a single Customer Master row with full commercial defaults."""
    db = tmp / "customer_master.sqlite"
    cmdb.init_db(db)
    now = "2026-07-13T00:00:00Z"
    cols = (
        "bill_to_contractor_id, bill_to_name, country, "
        "default_currency, default_language_id, payment_terms_days, "
        "preferred_payment_method, vat_mode, "
        "freight_fixed_amount_eur, freight_currency, freight_mode, freight_service_id, "
        "insurance_rate, insurance_service_id, insurance_enabled, "
        "created_at, updated_at"
    )
    vals = (
        CID, NAME, "DE",
        "EUR", _CM_LANGUAGE_ID, _CM_PAYMENT_DAYS,
        _CM_PAYMENT_METHOD, _CM_VAT_MODE,
        str(_CM_FREIGHT_EUR), "EUR", "fixed", _CM_FREIGHT_SVC_ID,
        str(_CM_INS_RATE), _CM_INS_SVC_ID, 1,
        now, now,
    )
    with sqlite3.connect(str(db)) as con:
        ph = ",".join(["?"] * len(vals))
        con.execute(f"INSERT INTO customer_master ({cols}) VALUES ({ph})", vals)
        con.commit()


def _seed_draft(tmp: Path, *,
                payment_method: str = "",
                payment_days: int | None = None,
                ) -> int:
    """Create a proforma draft in state 'draft' with client_contractor_id set.

    Returns the new draft id.
    """
    db = tmp / "proforma_links.db"
    pildb.init_db(db)
    now = "2026-07-13T00:00:00Z"
    pt: dict = {}
    if payment_method:
        pt["method"] = payment_method
    if payment_days is not None:
        pt["days"] = payment_days
    with sqlite3.connect(str(db)) as con:
        # Ensure schema
        pildb._ensure_drafts_table(con)
        cur = con.execute(
            """
            INSERT INTO proforma_drafts
                (batch_id, client_name, status, currency, exchange_rate,
                 source_lines_json, editable_lines_json, service_charges_json,
                 buyer_override_json, ship_to_override_json, payment_terms_json,
                 remarks, draft_state, draft_version, created_at, updated_at,
                 client_contractor_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                BATCH, CLIENT, "draft", "EUR", None,
                "[]", "[]", "[]",
                "{}", "{}", json.dumps(pt) if pt else "{}",
                "", "draft", 1, now, now,
                CID,
            ),
        )
        con.commit()
        return cur.lastrowid


# ── FastAPI client fixture ────────────────────────────────────────────────────
@pytest.fixture()
def tmp_storage(tmp_path):
    _seed_cm(tmp_path)
    return tmp_path


@pytest.fixture()
def api_client(tmp_storage):
    from app.main import app
    with patch.object(settings, "storage_root", tmp_storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, tmp_storage


def _hdrs():
    return {
        "X-API-KEY": settings.api_key or "test-key",
        "X-Operator": "test-operator",
    }


def _get_draft(api_client_tuple, draft_id: int):
    c, _ = api_client_tuple
    r = c.get(f"/api/v1/proforma/draft/{draft_id}", headers=_hdrs())
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def _apply(api_client_tuple, draft_id: int, fields: list, updated_at: str):
    c, _ = api_client_tuple
    return c.post(
        f"/api/v1/proforma/draft/{draft_id}/apply-customer-commercial",
        json={"fields": fields, "expected_updated_at": updated_at},
        headers=_hdrs(),
    )


# ── Test 1: blank draft + full CM → apply selected persists ─────────────────
def test_apply_selected_fields_persisted(api_client, tmp_storage):
    """Blank draft → apply payment_method + payment_terms_days.
    After apply, re-GET shows those values; vat_code is unchanged."""
    draft_id = _seed_draft(tmp_storage)
    d = _get_draft(api_client, draft_id)
    updated_at = d["updated_at"]

    # Verify suggestions show "suggested" for payment_method
    sug = d.get("customer_master_suggestions") or {}
    assert sug.get("status") == "mapped", f"expected mapped, got: {sug}"
    fields_by_key = {f["key"]: f for f in sug.get("fields", [])}
    assert fields_by_key.get("payment_method", {}).get("source") in ("suggested", "missing")

    # Apply two fields
    r = _apply(api_client, draft_id,
               ["payment_method", "payment_terms_days"], updated_at)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True

    # Check returned draft
    refreshed = body["draft"]
    pt = refreshed.get("payment_terms") or {}
    assert pt.get("method") == _CM_PAYMENT_METHOD, pt
    assert int(pt.get("days")) == _CM_PAYMENT_DAYS, pt
    # vat_code not selected → unchanged
    assert refreshed.get("vat_code") is None


# ── Test 2: non-empty draft field is NOT overwritten unless selected ──────────
def test_non_selected_field_not_overwritten(api_client, tmp_storage):
    """Draft already has payment_method='cash'. Apply only payment_terms_days.
    payment_method must remain 'cash' after apply."""
    draft_id = _seed_draft(tmp_storage, payment_method="cash", payment_days=7)
    d = _get_draft(api_client, draft_id)
    updated_at = d["updated_at"]

    r = _apply(api_client, draft_id, ["payment_terms_days"], updated_at)
    assert r.status_code == 200, r.text

    refreshed = r.json()["draft"]
    pt = refreshed.get("payment_terms") or {}
    # payment_method was NOT in fields → must stay "cash"
    assert pt.get("method") == "cash", f"expected 'cash', got: {pt.get('method')}"
    # payment_terms_days WAS in fields → must be updated from CM
    assert int(pt.get("days")) == _CM_PAYMENT_DAYS, pt


# ── Test 3: optimistic-lock conflict → 409 ───────────────────────────────────
def test_optimistic_lock_conflict_returns_409(api_client, tmp_storage):
    """Supplying a stale expected_updated_at must return 409."""
    draft_id = _seed_draft(tmp_storage)
    d = _get_draft(api_client, draft_id)

    # Use a deliberately wrong timestamp
    r = _apply(api_client, draft_id,
               ["payment_method"], "2000-01-01T00:00:00+00:00")
    assert r.status_code == 409, r.text


# ── Test 4: CM unresolvable → 404 ────────────────────────────────────────────
def test_cm_unresolvable_returns_404(api_client, tmp_storage):
    """Draft with no client_contractor_id → CM cannot be resolved → 404."""
    db = tmp_storage / "proforma_links.db"
    pildb.init_db(db)
    now = "2026-07-13T00:00:00Z"
    with sqlite3.connect(str(db)) as con:
        pildb._ensure_drafts_table(con)
        cur = con.execute(
            """
            INSERT INTO proforma_drafts
                (batch_id, client_name, status, currency, exchange_rate,
                 source_lines_json, editable_lines_json, service_charges_json,
                 buyer_override_json, ship_to_override_json, payment_terms_json,
                 remarks, draft_state, draft_version, created_at, updated_at,
                 client_contractor_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (BATCH, "No-CM Client", "draft", "EUR", None,
             "[]", "[]", "[]", "{}", "{}", "{}", "",
             "draft", 1, now, now, ""),   # empty contractor id
        )
        con.commit()
        draft_id = cur.lastrowid

    d = _get_draft(api_client, draft_id)
    r = _apply(api_client, draft_id, ["payment_method"], d["updated_at"])
    assert r.status_code == 404, r.text


# ── Test 5: audit event recorded with before/after + selected_fields ─────────
def test_audit_event_written_with_correct_shape(api_client, tmp_storage):
    """After apply, the proforma_draft_events table must contain an event
    'commercial_defaults_from_customer_master' with the expected shape."""
    draft_id = _seed_draft(tmp_storage)
    d = _get_draft(api_client, draft_id)

    r = _apply(api_client, draft_id,
               ["payment_method", "freight_service_id"], d["updated_at"])
    assert r.status_code == 200, r.text

    db = tmp_storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as con:
        rows = con.execute(
            "SELECT event, detail_json, operator FROM proforma_draft_events "
            "WHERE draft_id=? ORDER BY id DESC LIMIT 1",
            (draft_id,),
        ).fetchall()
    assert rows, "no event rows found"
    event, detail_raw, operator = rows[0]
    assert event == "commercial_defaults_from_customer_master"
    assert operator == "test-operator"

    detail = json.loads(detail_raw)
    assert detail["source_contractor_id"] == CID
    assert detail["source_name"] == NAME
    assert set(detail["selected_fields"]) == {"payment_method", "freight_service_id"}
    assert "before" in detail
    assert "after" in detail
    assert "from_state" in detail
    assert "to_state" in detail
    # Verify before/after shapes
    assert "payment_terms" in detail["before"]
    assert "payment_terms" in detail["after"]
    after_pt = detail["after"]["payment_terms"]
    assert after_pt.get("method") == _CM_PAYMENT_METHOD
    # freight_service_id must appear in after.freight
    assert detail["after"].get("freight") is not None
    assert detail["after"]["freight"]["wfirma_service_id"] == _CM_FREIGHT_SVC_ID


# ── Test 6: reload durability — re-fetch draft shows persisted values ─────────
def test_persisted_values_survive_reload(api_client, tmp_storage):
    """Values applied in one request must be present in a subsequent GET."""
    draft_id = _seed_draft(tmp_storage)
    d = _get_draft(api_client, draft_id)

    fields = ["payment_method", "payment_terms_days", "freight_service_id", "insurance_service_id"]
    r = _apply(api_client, draft_id, fields, d["updated_at"])
    assert r.status_code == 200, r.text

    # Re-fetch via GET
    reloaded = _get_draft(api_client, draft_id)
    pt = reloaded.get("payment_terms") or {}
    assert pt.get("method") == _CM_PAYMENT_METHOD
    assert int(pt.get("days")) == _CM_PAYMENT_DAYS

    charges = reloaded.get("service_charges") or []
    fr = next((c for c in charges if c.get("charge_type") == "freight"), None)
    ins = next((c for c in charges if c.get("charge_type") == "insurance"), None)

    assert fr is not None, "freight charge not found after reload"
    assert fr.get("wfirma_service_id") == _CM_FREIGHT_SVC_ID

    assert ins is not None, "insurance charge not found after reload"
    assert ins.get("wfirma_service_id") == _CM_INS_SVC_ID
