"""
test_cancel_for_reissue_normalization.py — Cancel-for-reissue must use the
SAME client_name normalisation as the create path. Otherwise drafts
persisted by create cannot be located by cancel.

Regression context
------------------
Live AWB 6049349806 had four issued Proformas with mixed-case client
names ("Anastazia Panakova", "Clear-Diamonds", …). The cancel route
used to call ``_norm(client_name)`` which uppercased the input, so
``pildb.get_draft`` found no row (it does an exact-case match). The
fix swaps to ``_validate_args`` (strip-only) — same helper the create
route uses.

Pins (each maps to a numbered scope rule):
  1. cancel finds draft for ``Anastazia Panakova``
  2. cancel finds draft for ``Impact Gallery sp. z o.o.``
  3. wrong confirm still blocks before lookup/delete
  4. delete flag false still blocks
  5. no wFirma delete attempted when draft missing
"""
from __future__ import annotations

import json
import sqlite3
import uuid
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


_BATCH   = "BATCH_CANCEL_NORM"
_CONFIRM = "YES_DELETE_AND_REISSUE_ONE_PROFORMA"


@pytest.fixture(autouse=True)
def _prime_vat():
    _wc._VAT_CODE_ID_CACHE["23"]  = "222"
    _wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    _wc._VAT_CODE_ID_CACHE["EXP"] = "229"
    yield


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    scdb.init(tmp_path / "proforma_links.db")
    pildb.init_db(tmp_path / "proforma_links.db")
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


def _seed_issued_draft(storage, *, client_name: str,
                        wfirma_id: str = "467222691") -> None:
    """Persist an issued proforma_drafts row with mixed-case client_name."""
    db = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        db,
        batch_id          = _BATCH,
        client_name       = client_name,
        currency          = "EUR",
        exchange_rate     = None,
        source_lines_json = "[]",
    )
    pildb.mark_draft_issued(db, _BATCH, client_name,
                             wfirma_proforma_id=wfirma_id)


def _cancel_url(name: str) -> str:
    # Build the URL without forcing case — operator passes the actual
    # name they read off the dashboard / live wFirma.
    return f"/api/v1/proforma/cancel-issued-for-reissue/{_BATCH}/{name}"


def _stub_delete_ok():
    """Patch wfirma_client.delete_invoice to a no-op that returns ok."""
    return patch.object(_wc, "delete_invoice", return_value={"ok": True})


# ── 1. Mixed-case client name resolves ─────────────────────────────────────

def test_cancel_finds_mixed_case_anastazia(client, storage):
    """Regression: ``Anastazia Panakova`` must resolve to its draft.
    Previously this returned 'no local draft found' because cancel
    uppercased to ``ANASTAZIA PANAKOVA`` while the row stored mixed case."""
    _seed_issued_draft(storage, client_name="Anastazia Panakova",
                        wfirma_id="467222691")
    with _gate_delete_on(), _stub_delete_ok():
        r = client.post(
            _cancel_url("Anastazia%20Panakova"),
            params={"confirm": _CONFIRM},
            headers=_auth(),
        )
    body = r.json()
    assert r.status_code == 200, r.text
    assert body["ok"] is True
    assert body["status"]            == "cancelled_for_reissue"
    assert body["deleted_wfirma_id"] == "467222691"
    # Local draft is now retryable, wfirma id cleared.
    draft = pildb.get_draft(storage / "proforma_links.db",
                             _BATCH, "Anastazia Panakova")
    assert draft is not None
    assert draft.status == "failed"
    assert draft.wfirma_proforma_id is None


def test_cancel_finds_mixed_case_impact_gallery(client, storage):
    """Long mixed-case name with periods/spaces must also resolve."""
    name = "Impact Gallery sp. z o.o."
    _seed_issued_draft(storage, client_name=name,
                        wfirma_id="467222883")
    import urllib.parse as _u
    url = _cancel_url(_u.quote(name))
    with _gate_delete_on(), _stub_delete_ok():
        body = client.post(url, params={"confirm": _CONFIRM},
                            headers=_auth()).json()
    assert body["ok"] is True
    assert body["status"]            == "cancelled_for_reissue"
    assert body["deleted_wfirma_id"] == "467222883"
    draft = pildb.get_draft(storage / "proforma_links.db", _BATCH, name)
    assert draft is not None
    assert draft.status == "failed"


def test_cancel_response_preserves_original_case(client, storage):
    """Defensive: response client_name should NOT be uppercased — operator
    UI matches against the persisted row, which is mixed case."""
    _seed_issued_draft(storage, client_name="Clear-Diamonds",
                        wfirma_id="467222819")
    with _gate_delete_on(), _stub_delete_ok():
        body = client.post(
            _cancel_url("Clear-Diamonds"),
            params={"confirm": _CONFIRM},
            headers=_auth(),
        ).json()
    assert body["client_name"] == "Clear-Diamonds"


# ── Leading/trailing-space tolerance (live data sometimes carries them) ────

def test_cancel_strips_url_whitespace(client, storage):
    """A URL-encoded leading space (%20) should be stripped before lookup,
    matching the create path's _validate_args strip-only normalisation."""
    _seed_issued_draft(storage, client_name="OMARA s.r.o",
                        wfirma_id="467222755")
    with _gate_delete_on(), _stub_delete_ok():
        body = client.post(
            _cancel_url("%20OMARA%20s.r.o%20"),  # leading + trailing %20
            params={"confirm": _CONFIRM},
            headers=_auth(),
        ).json()
    assert body["ok"] is True
    assert body["client_name"] == "OMARA s.r.o"


# ── 3. Wrong confirm blocks before lookup/delete ───────────────────────────

def test_wrong_confirm_blocks_before_db_or_wfirma(client, storage):
    """Wrong confirm string must short-circuit BEFORE the draft lookup
    or any wFirma call. Verified by a side_effect that would explode."""
    _seed_issued_draft(storage, client_name="Anastazia Panakova",
                        wfirma_id="467222691")
    with _gate_delete_on(), \
         patch.object(_wc, "delete_invoice",
                      side_effect=AssertionError("must not call delete")):
        body = client.post(
            _cancel_url("Anastazia%20Panakova"),
            params={"confirm": "TRYING_TO_BYPASS"},
            headers=_auth(),
        ).json()
    assert body["ok"]     is False
    assert body["status"] == "blocked"
    assert any("confirm" in br.lower() for br in body["blocking_reasons"])
    # Draft remains 'issued'.
    draft = pildb.get_draft(storage / "proforma_links.db",
                             _BATCH, "Anastazia Panakova")
    assert draft.status == "issued"


# ── 4. Delete flag false blocks ────────────────────────────────────────────

def test_delete_flag_false_blocks(client, storage):
    _seed_issued_draft(storage, client_name="Anastazia Panakova",
                        wfirma_id="467222691")
    with patch.object(_wc, "delete_invoice",
                      side_effect=AssertionError("must not call delete")):
        # Default settings.wfirma_delete_invoice_allowed is False.
        body = client.post(
            _cancel_url("Anastazia%20Panakova"),
            params={"confirm": _CONFIRM},
            headers=_auth(),
        ).json()
    assert body["ok"]     is False
    assert body["status"] == "blocked"
    assert any("WFIRMA_DELETE_INVOICE_ALLOWED" in br
               for br in body["blocking_reasons"])


# ── 5. Missing draft → no wFirma delete attempted ──────────────────────────

def test_missing_draft_does_not_call_wfirma_delete(client, storage):
    """No draft for this batch/client → blocked, never reaches wFirma."""
    # Note: NO _seed_issued_draft call.
    with _gate_delete_on(), \
         patch.object(_wc, "delete_invoice",
                      side_effect=AssertionError(
                          "must not call delete when draft missing")):
        body = client.post(
            _cancel_url("NoSuchClient"),
            params={"confirm": _CONFIRM},
            headers=_auth(),
        ).json()
    assert body["ok"]     is False
    assert body["status"] == "blocked"
    assert any("no local draft" in br.lower()
               for br in body["blocking_reasons"])


# ── Defence-in-depth: cancel + create normalisation are aligned ────────────

def test_cancel_uses_same_normalisation_as_create():
    """
    Source-grep guard: the cancel handler must call ``_validate_args``
    (the helper the create path uses), NOT ``_norm`` (which uppercases).
    Future refactors that rename either helper or revert to ``_norm``
    will break this test before they break live operations.
    """
    from app.api import routes_proforma as rp
    src = open(rp.__file__).read()
    # Find the cancel handler body and check which normaliser is in scope.
    cancel_def = "def cancel_issued_proforma_for_reissue("
    idx = src.find(cancel_def)
    assert idx > 0, "cancel handler not found in routes_proforma.py"
    # First normalisation call after the def.
    body = src[idx: idx + 2000]
    assert "cn = _validate_args(batch_id, client_name)" in body, (
        "cancel handler must use _validate_args (strip-only) so it can "
        "find drafts created by the create handler. Reverting to _norm "
        "(strip+upper) breaks the lookup."
    )
    assert "cn = _norm(client_name)" not in body
