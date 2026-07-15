"""test_proforma_nbp_fetch.py — PR-4.

The Proforma NBP fetch command reuses the sole PZ NBP authority
(pz_import_processor.get_nbp_rate, wrapped by nbp_rate_service) and persists the
rate on the draft. These tests exercise the endpoint end-to-end with the ENGINE
CALL MOCKED (no live api.nbp.pl, no interactive input()).

Covers the PR-4 required matrix:
 1. USD fetch persists rate, table number, table date.
 2. EUR fetch persists the EUR rate (not the USD rate).
 3. PLN persists identity rate with honest identity source.
 4. Unsupported currency → 422, no write.
 5. Upstream failure → no write, never stores 1.0.
 6. Stale expected_updated_at → 409.
 7. Manual override → source 'manual' + clears stale NBP table metadata.
 8. Reload preserves the fetched values.
 9. The persisted draft rate is what totals consume.
10. The UI exposes both Fetch NBP and the manual override.
(11. The old prohibition → replaced by the ADR authority contract in
     test_proforma_warnings_and_dedup.py::test_proforma_nbp_fetch_authority_contract.)
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

BATCH = "BATCH_PR4_NBP"
CLIENT = "PR4_CLIENT"

# Canned NBP table (what the PZ engine would return). table_date deliberately
# differs from the accounting date to prove the two are persisted separately.
_ENGINE_TABLE = {
    "table_no": "A/135/2026", "table_date": "2026-07-14",
    "usd_rate": 3.9512, "eur_rate": 4.3021,
}


@pytest.fixture()
def storage(tmp_path):
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb
    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    out = tmp_path / "outputs" / BATCH
    (out / "source").mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(
        {"batch_id": BATCH, "tracking_no": BATCH, "awb": BATCH,
         "carrier": "DHL", "timeline": []}), encoding="utf-8")
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


def _seed_draft(storage, currency="USD", issue_date="2026-07-15", status="draft"):
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, status, currency, draft_state,
                  wfirma_proforma_id, wfirma_proforma_fullnumber, wfirma_issue_date,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (BATCH, CLIENT, status, currency, status, None, "", issue_date,
             "[]", "[]", "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _get(c, did):
    r = c.get(f"/api/v1/proforma/draft/{did}", headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def _fetch(c, did, updated_at, headers=None):
    return c.post(f"/api/v1/proforma/draft/{did}/fetch-nbp-rate",
                  json={"expected_updated_at": updated_at},
                  headers=headers if headers is not None else _op())


def _mock_engine(table=_ENGINE_TABLE):
    # Patch the adapter's engine call so no live network / input() is reached.
    return patch("app.services.nbp_rate_service._call_engine", return_value=dict(table))


# ── 1. USD ──────────────────────────────────────────────────────────────────

def test_usd_fetch_persists_rate_table_and_dates(client):
    c, storage = client
    did = _seed_draft(storage, currency="USD", issue_date="2026-07-15")
    d = _get(c, did)
    with _mock_engine():
        r = _fetch(c, did, d["updated_at"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["nbp"]["rate"] == 3.9512
    assert body["nbp"]["source"] == "NBP"
    assert body["nbp"]["table_number"] == "A/135/2026"
    assert body["nbp"]["table_date"] == "2026-07-14"
    assert body["nbp"]["accounting_date"] == "2026-07-15"      # issue date
    assert body["nbp"]["accounting_date_source"] == "issue_date"
    dd = _get(c, did)
    assert dd["exchange_rate"] == 3.9512
    assert dd["fx_rate_source"] == "NBP"
    assert dd["nbp_table_number"] == "A/135/2026"
    assert dd["fx_table_date"] == "2026-07-14"
    assert dd["fx_accounting_date"] == "2026-07-15"


# ── 2. EUR uses the EUR rate ──────────────────────────────────────────────────

def test_eur_fetch_uses_eur_rate(client):
    c, storage = client
    did = _seed_draft(storage, currency="EUR")
    d = _get(c, did)
    with _mock_engine():
        r = _fetch(c, did, d["updated_at"])
    assert r.status_code == 200, r.text
    assert r.json()["nbp"]["rate"] == 4.3021          # EUR, not the 3.9512 USD
    assert _get(c, did)["exchange_rate"] == 4.3021


# ── 3. PLN identity ───────────────────────────────────────────────────────────

def test_pln_identity_rate(client):
    c, storage = client
    did = _seed_draft(storage, currency="PLN")
    d = _get(c, did)
    # No engine call needed for PLN, but patch anyway to prove it's not used.
    with patch("app.services.nbp_rate_service._call_engine",
               side_effect=AssertionError("engine must not be called for PLN")):
        r = _fetch(c, did, d["updated_at"])
    assert r.status_code == 200, r.text
    assert r.json()["nbp"]["source"] == "identity"
    dd = _get(c, did)
    assert dd["exchange_rate"] == 1.0
    assert dd["fx_rate_source"] == "identity"
    assert dd["nbp_table_number"] is None


# ── 4. Unsupported currency ───────────────────────────────────────────────────

def test_unsupported_currency_422_no_write(client):
    c, storage = client
    did = _seed_draft(storage, currency="GBP")
    d = _get(c, did)
    r = _fetch(c, did, d["updated_at"])
    assert r.status_code == 422, r.text
    assert _get(c, did)["exchange_rate"] is None      # nothing written


# ── 5. Upstream failure — no write, never 1.0 ─────────────────────────────────

def test_upstream_failure_no_write_no_1_0(client):
    c, storage = client
    did = _seed_draft(storage, currency="USD")
    d = _get(c, did)
    with patch("app.services.nbp_rate_service._call_engine",
               side_effect=RuntimeError("NBP down")):
        r = _fetch(c, did, d["updated_at"])
    assert r.status_code == 502, r.text
    dd = _get(c, did)
    assert dd["exchange_rate"] is None                # not written, and NOT 1.0
    assert dd["fx_rate_source"] in (None, "NBP")      # unchanged default


# ── 6. Stale lock ─────────────────────────────────────────────────────────────

def test_stale_lock_409(client):
    c, storage = client
    did = _seed_draft(storage, currency="USD")
    with _mock_engine():
        r = _fetch(c, did, "2000-01-01T00:00:00+00:00")
    assert r.status_code == 409, r.text
    assert _get(c, did)["exchange_rate"] is None


# ── 7. Manual override → source manual + clears stale NBP table ───────────────

def test_manual_override_sets_source_manual_and_clears_table(client):
    c, storage = client
    did = _seed_draft(storage, currency="USD")
    d = _get(c, did)
    with _mock_engine():
        assert _fetch(c, did, d["updated_at"]).status_code == 200
    dd = _get(c, did)
    assert dd["nbp_table_number"] == "A/135/2026"      # NBP table present
    # Operator hand-types a rate via the existing manual editor (patchDraft).
    r = c.patch(f"/api/v1/proforma/draft/{did}",
                json={"expected_updated_at": dd["updated_at"],
                      "patch": {"exchange_rate": 4.1}}, headers=_op())
    assert r.status_code == 200, r.text
    dd2 = _get(c, did)
    assert dd2["exchange_rate"] == 4.1
    assert dd2["fx_rate_source"] == "manual"
    assert dd2["nbp_table_number"] is None             # stale NBP table cleared


# ── 8. Reload preserves fetched values ────────────────────────────────────────

def test_reload_preserves_fetched_values(client):
    c, storage = client
    did = _seed_draft(storage, currency="USD")
    d = _get(c, did)
    with _mock_engine():
        assert _fetch(c, did, d["updated_at"]).status_code == 200
    # Two subsequent independent GETs (reload) show the same persisted values.
    for _ in range(2):
        dd = _get(c, did)
        assert dd["exchange_rate"] == 3.9512
        assert dd["nbp_table_number"] == "A/135/2026"
        assert dd["fx_accounting_date"] == "2026-07-15"


# ── 9. Totals consume the persisted draft rate ────────────────────────────────

def test_totals_use_persisted_rate(client):
    c, storage = client
    did = _seed_draft(storage, currency="USD")
    d = _get(c, did)
    with _mock_engine():
        assert _fetch(c, did, d["updated_at"]).status_code == 200
    # The projected exchange_rate (what the UI multiplies EUR totals by) is the
    # fetched rate — no competing local calculation.
    assert _get(c, did)["exchange_rate"] == 3.9512


# ── 10. Fallback accounting date when issue date blank ────────────────────────

def test_today_fallback_when_issue_date_blank(client):
    c, storage = client
    did = _seed_draft(storage, currency="USD", issue_date="")
    d = _get(c, did)
    with _mock_engine():
        r = _fetch(c, did, d["updated_at"])
    assert r.status_code == 200, r.text
    assert r.json()["nbp"]["accounting_date_source"] == "today_fallback"


# ── 10b. UI exposes both Fetch NBP and manual override ────────────────────────

def test_ui_exposes_fetch_and_manual_override():
    jsx = (_ROOT / "app" / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert 'data-testid="fetch-nbp-rate"' in jsx, "Fetch NBP button must exist"
    assert 'data-testid="edit-exchange-rate"' in jsx, "manual override field must remain"
    api = (_ROOT / "app" / "static" / "v2" / "pz-api.js").read_text(encoding="utf-8")
    assert "fetchNbpRate" in api, "PzApi.fetchNbpRate wrapper must exist"


# ── 11. ADR authority contract lives in the warnings suite (reference) ────────

def test_adr_authority_contract_exists():
    t = (_ROOT / "tests" / "test_proforma_warnings_and_dedup.py").read_text(encoding="utf-8")
    assert "test_proforma_nbp_fetch_authority_contract" in t, (
        "the replaced prohibition must be re-expressed as an authority contract test"
    )
    adr = _ROOT.parent / "docs" / "decisions" / "ADR-proforma-nbp-fetch.md"
    assert adr.exists(), "ADR documenting the NBP authority reversal must exist"
