"""
test_wfirma_customer_sync.py — unit + endpoint coverage for the
operator-triggered, dry-run-default wFirma contractor sync.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import wfirma_db as wfdb
from app.services import wfirma_client as wc
from app.services import wfirma_customer_sync as wfsync
from app.services.wfirma_customer_sync import (
    RemoteRow,
    classify_pair,
    normalise_client_name,
    STATUS_INSERT, STATUS_UPDATE_FILL, STATUS_UPDATE_MATCH,
    STATUS_CONFLICT, STATUS_SKIP,
    MATCH_MATCHED, MATCH_MATCHED_FROM_SYNC,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    from app.services.packing_db   import init_packing_db
    from app.services.warehouse_db import init_warehouse_db
    from app.services.document_db  import init_document_db
    init_packing_db(tmp_path / "packing.db")
    init_warehouse_db(tmp_path / "warehouse.db")
    init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── normalise_client_name ───────────────────────────────────────────────────

def test_normalise_strips_whitespace_and_casefolds():
    assert normalise_client_name("  ACME Corp  ") == "acme corp"


def test_normalise_collapses_internal_whitespace():
    assert normalise_client_name("ACME   Corp\tLtd") == "acme corp ltd"


def test_normalise_drops_trailing_punct():
    assert normalise_client_name("Juliany EOOD.") == "juliany eood"
    assert normalise_client_name("Juliany EOOD!") == "juliany eood"
    assert normalise_client_name("Juliany EOOD")  == "juliany eood"


def test_normalise_handles_unicode():
    # NFKC: composed characters; case-fold for case-insensitive comparison.
    assert normalise_client_name("Ångström AB") == normalise_client_name("ångström ab")


def test_normalise_empty_inputs():
    assert normalise_client_name("")    == ""
    assert normalise_client_name(None)  == ""


# ── classify_pair truth table ───────────────────────────────────────────────

def _r(wid="W1", name="ACME", nip="", country=""):
    return RemoteRow(wfirma_id=wid, name=name, nip=nip, country=country)


def test_classify_insert_when_no_local_row():
    assert classify_pair(None, _r()) == STATUS_INSERT


def test_classify_update_fill_when_local_id_blank():
    local = {"client_name": "ACME", "wfirma_customer_id": "",
             "vat_id": "", "country": ""}
    assert classify_pair(local, _r()) == STATUS_UPDATE_FILL


def test_classify_update_fill_when_local_id_none():
    local = {"client_name": "ACME", "wfirma_customer_id": None,
             "vat_id": "", "country": ""}
    assert classify_pair(local, _r()) == STATUS_UPDATE_FILL


def test_classify_skip_when_already_matched_and_identical():
    local = {"client_name": "ACME", "wfirma_customer_id": "W1",
             "vat_id": "", "country": ""}
    assert classify_pair(local, _r(wid="W1", nip="", country="")) == STATUS_SKIP


def test_classify_update_match_when_id_matches_but_drifted_data():
    local = {"client_name": "ACME", "wfirma_customer_id": "W1",
             "vat_id": "OLD-NIP", "country": "PL"}
    remote = _r(wid="W1", nip="NEW-NIP", country="PL")
    assert classify_pair(local, remote) == STATUS_UPDATE_MATCH


def test_classify_conflict_when_local_id_differs():
    local = {"client_name": "ACME", "wfirma_customer_id": "W-OTHER",
             "vat_id": "", "country": ""}
    assert classify_pair(local, _r(wid="W1")) == STATUS_CONFLICT


def test_classify_skip_when_remote_has_no_id():
    """Defensive: a remote row with no id cannot drive any local change."""
    remote = RemoteRow(wfirma_id="", name="X")
    assert classify_pair(None, remote) == STATUS_SKIP


# ── plan_sync end-to-end with mocked client ─────────────────────────────────

def _mock_pages(monkeypatch, contractors):
    """
    Patch wfirma_client.list_contractors_page to return *contractors*
    paginated in chunks of PAGE_SIZE-equivalent (any size up to len).
    """
    def fake_page(start, limit):
        return contractors[start:start + limit]
    monkeypatch.setattr(wc, "list_contractors_page", fake_page)


def _wf(wid, name, nip="", country="PL"):
    return wc.WFirmaContractor(
        wfirma_id=wid, name=name, nip=nip, country=country, zip="", city="",
    )


def test_plan_inserts_when_local_db_empty(storage, monkeypatch):
    _mock_pages(monkeypatch, [_wf("W1", "Foo Sp."), _wf("W2", "Bar AB")])
    plan = wfsync.plan_sync(page_size=50)
    assert plan["total_remote"] == 2
    assert len(plan["insert"]) == 2
    assert plan["update_fill"]  == []
    assert plan["update_match"] == []
    assert plan["conflict"]     == []
    assert plan["skip_count"]   == 0


def test_plan_update_fill_when_local_id_blank(storage, monkeypatch):
    wfdb.upsert_customer("Foo Sp.", wfirma_customer_id="", country="PL")
    _mock_pages(monkeypatch, [_wf("W1", "Foo Sp.")])
    plan = wfsync.plan_sync()
    assert len(plan["update_fill"]) == 1
    assert plan["insert"] == []


def test_plan_update_match_or_skip(storage, monkeypatch):
    # Already-matched + identical → SKIP.
    wfdb.upsert_customer("Foo Sp.", wfirma_customer_id="W1",
                         vat_id="123", country="PL",
                         match_status="matched")
    # Already-matched + drifted vat → UPDATE_MATCH.
    wfdb.upsert_customer("Bar AB", wfirma_customer_id="W2",
                         vat_id="OLD", country="PL",
                         match_status="matched")
    _mock_pages(monkeypatch, [
        _wf("W1", "Foo Sp.", nip="123"),
        _wf("W2", "Bar AB",  nip="NEW"),
    ])
    plan = wfsync.plan_sync()
    assert plan["skip_count"] == 1
    assert len(plan["update_match"]) == 1
    assert plan["update_match"][0]["client_name"] == "Bar AB"


def test_plan_conflict_when_local_id_differs(storage, monkeypatch):
    wfdb.upsert_customer("Foo Sp.", wfirma_customer_id="W-MANUAL",
                         match_status="matched")
    _mock_pages(monkeypatch, [_wf("W1", "Foo Sp.")])
    plan = wfsync.plan_sync()
    assert plan["insert"]      == []
    assert plan["update_fill"] == []
    assert len(plan["conflict"]) == 1
    c = plan["conflict"][0]
    assert "different wfirma_customer_id" in c["reason"]


def test_plan_conflict_on_duplicate_remote_names(storage, monkeypatch):
    # Two wFirma contractors share a name (after normalisation) → both conflict.
    _mock_pages(monkeypatch, [
        _wf("W1", "Twin Co"),
        _wf("W2", "twin co."),    # different case + trailing dot
    ])
    plan = wfsync.plan_sync()
    assert plan["insert"]      == []
    assert plan["update_fill"] == []
    assert len(plan["conflict"]) == 2
    for c in plan["conflict"]:
        assert "duplicate remote names" in c["reason"]


def test_plan_pagination_terminates_on_short_page(monkeypatch, storage):
    contractors = [_wf(f"W{i}", f"Co{i}") for i in range(7)]
    _mock_pages(monkeypatch, contractors)
    # page_size=3 → pages [0..3), [3..6), [6..9)→len=1<3 stop.
    plan = wfsync.plan_sync(page_size=3)
    assert plan["total_remote"] == 7


def test_plan_pagination_terminates_on_empty_page(monkeypatch, storage):
    contractors = [_wf(f"W{i}", f"Co{i}") for i in range(6)]
    _mock_pages(monkeypatch, contractors)
    # page_size=3 → pages [0..3), [3..6), [6..9)→len=0 stop.
    plan = wfsync.plan_sync(page_size=3)
    assert plan["total_remote"] == 6


# ── apply_plan ──────────────────────────────────────────────────────────────

def test_apply_plan_writes_only_safe_categories(storage):
    plan = {
        "insert": [{
            "client_name": "Insert-Only", "wfirma_customer_id": "W-INS",
            "country": "PL", "vat_id": "111",
            "local_client_name": None, "local_wfirma_id": None,
        }],
        "update_fill": [{
            "client_name": "Fill-Me", "wfirma_customer_id": "W-FILL",
            "country": "PL", "vat_id": "222",
            "local_client_name": "Fill-Me", "local_wfirma_id": "",
        }],
        "update_match": [{
            "client_name": "Refresh", "wfirma_customer_id": "W-REF",
            "country": "PL", "vat_id": "333-NEW",
            "local_client_name": "Refresh", "local_wfirma_id": "W-REF",
        }],
        "conflict": [{
            "client_name": "Bad", "wfirma_customer_id": "W-CONFLICT",
            "country": "PL", "vat_id": "",
            "reason": "differs",
        }],
        "skip_count": 0,
    }
    wfdb.upsert_customer("Fill-Me",
                         wfirma_customer_id="", country="PL",
                         match_status="pending")
    wfdb.upsert_customer("Refresh",
                         wfirma_customer_id="W-REF", vat_id="333-OLD",
                         country="PL", match_status="matched")

    out = wfsync.apply_plan(plan)
    assert out["applied_count"]     == 3
    assert out["skipped_conflicts"] == 1
    assert out["rejected_blank"]    == []

    inserted = wfdb.get_customer("Insert-Only")
    assert inserted["wfirma_customer_id"] == "W-INS"
    assert inserted["match_status"] == MATCH_MATCHED_FROM_SYNC

    filled = wfdb.get_customer("Fill-Me")
    assert filled["wfirma_customer_id"] == "W-FILL"
    assert filled["match_status"] == MATCH_MATCHED_FROM_SYNC

    refreshed = wfdb.get_customer("Refresh")
    assert refreshed["wfirma_customer_id"] == "W-REF"
    # update_match must NOT downgrade the original 'matched' status.
    assert refreshed["match_status"] == MATCH_MATCHED
    assert refreshed["vat_id"] == "333-NEW"

    # Conflict must NOT have been written.
    assert wfdb.get_customer("Bad") is None


def test_apply_plan_rejects_blank_ids(storage):
    plan = {
        "insert": [{
            "client_name": "Empty-Id", "wfirma_customer_id": "",
            "country": "PL", "vat_id": "",
            "local_client_name": None, "local_wfirma_id": None,
        }],
        "update_fill": [], "update_match": [], "conflict": [],
        "skip_count": 0,
    }
    out = wfsync.apply_plan(plan)
    assert out["applied_count"] == 0
    assert len(out["rejected_blank"]) == 1
    assert wfdb.get_customer("Empty-Id") is None


# ── HTTP routes ─────────────────────────────────────────────────────────────

def test_route_sync_preview_is_read_only(client, storage, monkeypatch):
    _mock_pages(monkeypatch, [_wf("W1", "Foo Sp.")])
    body = client.get("/api/v1/wfirma/customers/sync-preview",
                      headers=_auth()).json()
    assert body["ok"] is True
    assert body["mode"] == "preview"
    assert body["total_remote"] == 1
    assert len(body["insert"])  == 1
    # No write happened.
    assert wfdb.get_customer("Foo Sp.") is None


def test_route_sync_default_is_dry_run(client, storage, monkeypatch):
    _mock_pages(monkeypatch, [_wf("W1", "Foo Sp.")])
    body = client.post("/api/v1/wfirma/customers/sync",
                       headers=_auth()).json()
    assert body["ok"] is True
    assert body["mode"] == "preview"
    assert body["applied_count"] == 0
    assert wfdb.get_customer("Foo Sp.") is None


def test_route_sync_write_blocked_when_flag_off(client, storage, monkeypatch):
    _mock_pages(monkeypatch, [_wf("W1", "Foo Sp.")])
    with patch.object(settings, "wfirma_sync_customers_allowed", False):
        body = client.post("/api/v1/wfirma/customers/sync?write=true",
                           headers=_auth()).json()
    assert body["ok"] is False
    assert body["mode"] == "blocked"
    assert any("WFIRMA_SYNC_CUSTOMERS_ALLOWED" in br
               for br in body["blocking_reasons"])
    assert wfdb.get_customer("Foo Sp.") is None


def test_route_sync_write_applies_only_safe_rows(client, storage, monkeypatch):
    # Manual mapping that should NOT be overwritten.
    wfdb.upsert_customer("Manual Co",
                         wfirma_customer_id="W-MANUAL",
                         country="PL", match_status="matched")
    _mock_pages(monkeypatch, [
        _wf("W1", "Foo Sp."),                  # → insert
        _wf("W2", "Manual Co"),                # → conflict (different id)
    ])
    with patch.object(settings, "wfirma_sync_customers_allowed", True):
        body = client.post("/api/v1/wfirma/customers/sync?write=true",
                           headers=_auth()).json()
    assert body["ok"] is True
    assert body["mode"] == "write"
    assert body["applied_count"] == 1
    assert len(body["conflict"]) == 1
    # Insert applied:
    foo = wfdb.get_customer("Foo Sp.")
    assert foo["wfirma_customer_id"] == "W1"
    assert foo["match_status"] == MATCH_MATCHED_FROM_SYNC
    # Manual mapping preserved:
    manual = wfdb.get_customer("Manual Co")
    assert manual["wfirma_customer_id"] == "W-MANUAL"
    assert manual["match_status"] == MATCH_MATCHED


def test_route_fetch_failure_returns_502(client, storage, monkeypatch):
    def raiser(start, limit):
        raise RuntimeError("contractors/find wFirma status=ERROR: boom")
    monkeypatch.setattr(wc, "list_contractors_page", raiser)
    r = client.get("/api/v1/wfirma/customers/sync-preview", headers=_auth())
    assert r.status_code == 502


# ── Parser hardening: nested / shadow contractor nodes ──────────────────────

_REAL_NESTED_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <contractors>
    <contractor>
      <id>1001</id><name>ACME Corp</name>
      <country>PL</country><nip>1111111111</nip>
      <addresses>
        <!-- wFirma sometimes nests address records as inner <contractor>
             elements. Our parser must NOT treat these as separate rows. -->
        <contractor><id>0</id><name></name></contractor>
        <contractor><id>1001</id><name></name></contractor>
      </addresses>
    </contractor>
    <contractor>
      <id>1002</id><name>BAR Sp. z o.o.</name>
      <country>PL</country><nip>2222222222</nip>
    </contractor>
    <!-- Top-level shadow with no name and id=0: must also be skipped. -->
    <contractor><id>0</id><name></name></contractor>
    <!-- Top-level row missing the id node: must be skipped. -->
    <contractor><name>NO-ID Corp</name><country>PL</country></contractor>
  </contractors>
  <status><code>OK</code></status>
</api>"""


def test_list_contractors_page_skips_nested_and_shadow_nodes(monkeypatch):
    """Only top-level <contractor> rows with id and name pass through."""
    def fake_http(method, module, action, body, id_suffix=None):
        return 200, _REAL_NESTED_FIXTURE
    monkeypatch.setattr(wc, "_http_request", fake_http)
    rows = wc.list_contractors_page(start=0, limit=50)
    ids = [r.wfirma_id for r in rows]
    names = [r.name for r in rows]
    assert ids   == ["1001", "1002"]
    assert names == ["ACME Corp", "BAR Sp. z o.o."]


def test_list_contractors_page_skips_id_zero(monkeypatch):
    only_zero = """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors>
  <contractor><id>0</id><name>Bad</name></contractor>
</contractors><status><code>OK</code></status></api>"""
    monkeypatch.setattr(wc, "_http_request",
                        lambda *a, **k: (200, only_zero))
    assert wc.list_contractors_page(start=0, limit=10) == []


def test_list_contractors_page_skips_blank_name(monkeypatch):
    blank_name = """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors>
  <contractor><id>9999</id><name></name></contractor>
</contractors><status><code>OK</code></status></api>"""
    monkeypatch.setattr(wc, "_http_request",
                        lambda *a, **k: (200, blank_name))
    assert wc.list_contractors_page(start=0, limit=10) == []


def test_plan_sync_belt_and_braces_skips_invalid(storage, monkeypatch):
    """
    Even if list_contractors_page regressed and let bad rows through,
    plan_sync must not classify them as inserts.
    """
    def fake_page(start, limit):
        bads = [
            wc.WFirmaContractor(wfirma_id="",   name="ghost",   country="PL"),
            wc.WFirmaContractor(wfirma_id="0",  name="zero",    country="PL"),
            wc.WFirmaContractor(wfirma_id="42", name="",        country="PL"),
        ]
        good = [_wf("W1", "Real Co")]
        return (bads + good)[start:start + limit]
    monkeypatch.setattr(wc, "list_contractors_page", fake_page)

    plan = wfsync.plan_sync(page_size=50)
    assert plan["total_remote"]    == 1
    assert plan["skipped_invalid"] == 3
    assert len(plan["insert"]) == 1
    assert plan["insert"][0]["client_name"] == "Real Co"
