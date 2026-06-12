"""
test_wfirma_post_failure_hardening.py — wFirma proforma post-failure hardening
(draft #33 incident, 2026-06-12).

Workflow class (Lesson I): "post-time wFirma rejection with an opaque error and
no audit evidence". Three coupled defects fixed:

  (a) `_parse_status` dropped nested ``<errors><error><field>/<message>``
      blocks — operator saw ``invoices/add wFirma status=ERROR:`` (empty).
  (b) WDT (0% intra-EU) posts with an empty NIP on the live wFirma contractor
      are technically doomed — wFirma hard-rejects them. ADR-027 D3 stays
      warn-not-block for present-but-unverified VAT numbers; the new gate
      blocks ONLY the doomed case, pre-commit, with no draft state change.
  (c) Failed posts persisted no request/response evidence — now written as a
      ``wfirma_post_exchange`` draft event (sanitized: wFirma auth travels in
      HTTP headers only, never in XML bodies).

Coverage
--------
Unit — _extract_field_errors:
  E1. Real draft-#33-shape contractor errors → ["contractor.zip: …", …]
  E2. OK response → []
  E3. Malformed XML → []
  E4. limit honoured
  E5. message-only error (no <field>) still surfaced

Unit — WFirmaCreateError via create_proforma_draft (HTTP mocked):
  C1. status=ERROR + nested errors → WFirmaCreateError, message carries field
      detail, .request_xml/.response_xml/.field_errors populated
  C2. HTTP 500 → WFirmaCreateError with response body attached
  C3. WFirmaCreateError is a RuntimeError (handler compatibility guarantee)

Integration — /draft/{id}/post (wFirma fully mocked):
  G1. WDT + contractor NIP empty → 400 blocked, readable reason, NO
      invoices/add call, draft stays approved (retry-safe)
  G2. WDT + contractor NIP present → 200 posted
      (covers: successful EUR proforma, qty=1, foreign EU contractor)
  G3. Contractor fetch fails → gate fail-open → post proceeds
  G4. Domestic (non-WDT) + empty NIP → gate does not fire → posted
  G5. wFirma rejects invoices/add → status=failed, error names the offending
      fields, ``wfirma_post_exchange`` event carries request/response XML
  G6. Retry duplicate guard: wfirma_proforma_id already set → 409, no call
  G7. Missing wFirma contractor mapping → 400 blocked before any state change
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_client
from app.services.customer_master_db import CustomerMaster
from app.services.wfirma_client import (
    ProformaRequest,
    ReservationLine,
    WFirmaCreateError,
    _extract_field_errors,
)


# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures / constants (mirrors test_adr027_vat_from_master.py harness)
# ──────────────────────────────────────────────────────────────────────────────

BATCH = "B-POSTFAIL"
CLIENT = "HORAK-SK"
CONTRACTOR_ID = "195596259"
PRODUCT_CODE = "RING-001"
WFIRMA_GOOD_ID = "42001"
WFIRMA_PROFORMA_ID = "77001"

# Real response shape from the draft #33 incident (2026-06-12): status block
# carries an empty <description>; the actual reasons live in nested
# <errors><error> blocks on the entity node.
HORAK_ERROR_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<api><invoices><invoice>"
    "<contractor><id>195596259</id>"
    "<errors>"
    "<error><field>zip</field><message>Pole nie może być puste.</message></error>"
    "<error><field>city</field><message>Pole nie może być puste.</message></error>"
    "</errors>"
    "</contractor>"
    "</invoice></invoices>"
    "<status><code>ERROR</code><description></description></status></api>"
)


def _make_cm(**kwargs) -> CustomerMaster:
    import dataclasses
    defaults = dict(
        bill_to_contractor_id=CONTRACTOR_ID,
        bill_to_name=CLIENT,
        country=None,
        vat_eu_number=None,
        vat_eu_valid=None,
        vat_mode=None,
        default_currency=None,
        default_language_id=None,
        preferred_proforma_series_id=None,
        preferred_invoice_series_id=None,
        preferred_payment_method=None,
        payment_terms_days=None,
        nip=None,
    )
    defaults.update(kwargs)
    valid = {f.name for f in dataclasses.fields(CustomerMaster)}
    return CustomerMaster(**{k: v for k, v in defaults.items() if k in valid})


def _wfirma_add_ok_xml(proforma_id: str = WFIRMA_PROFORMA_ID) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f"<api><status><code>OK</code></status>"
        f"<invoices><invoice><id>{proforma_id}</id>"
        f"<fullnumber>PROF 9/2026</fullnumber></invoice></invoices></api>"
    )


def _wfirma_verify_xml(
    proforma_id: str = WFIRMA_PROFORMA_ID,
    good_id: str = WFIRMA_GOOD_ID,
    vat_code_id: str = "228",
) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f"<api><status><code>OK</code></status>"
        f"<invoices><invoice><id>{proforma_id}</id>"
        f"<invoicecontents><invoicecontent>"
        f"<good><id>{good_id}</id></good>"
        f"<vat_code><id>{vat_code_id}</id></vat_code>"
        f"</invoicecontent></invoicecontents></invoice></invoices></api>"
    )


def _contractor_xml(nip: str, name: str = "Jozef Horak-HORNAK klenoty") -> str:
    """contractors/get/{id} response with a parameterizable <nip>."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<api><contractors><contractor>"
        f"<id>{CONTRACTOR_ID}</id>"
        f"<name>{name}</name>"
        f"<nip>{nip}</nip>"
        "<country>SK</country><zip>92701</zip><city>Sala</city>"
        "<different_contact_address>0</different_contact_address>"
        "</contractor></contractors>"
        "<status><code>OK</code></status></api>"
    )


@pytest.fixture()
def app_client(tmp_path, monkeypatch) -> TestClient:
    from app.main import app
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "wfirma_create_proforma_allowed", True)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _patch_env(tmp_path, monkeypatch):
    from app.api import routes_proforma as rp
    monkeypatch.setattr(rp, "_proforma_db_path",
                        lambda: tmp_path / "proforma_drafts.sqlite")
    monkeypatch.setattr(rp, "_customer_master_db_path",
                        lambda: tmp_path / "customer_master.sqlite")
    from app.services import wfirma_db as wfdb
    monkeypatch.setattr(wfdb, "_db_path", tmp_path / "wfirma.sqlite")


def _setup_db_for_draft(
    tmp_path: Path,
    cm: CustomerMaster,
    *,
    register_contractor: bool = True,
    draft_client_name: str = CLIENT,
) -> pildb.ProformaDraft:
    """Approved EUR draft (qty=1) + customer_master + wFirma mappings.

    NOTE: _patch_env must run BEFORE this — wfdb helpers resolve the module-
    level _db_path at call time.

    ``draft_client_name`` lets a test put a name on the draft that matches
    neither Customer Master nor the wfirma_customers cache (identity-
    resolution failure scenario).
    """
    from app.services import customer_master_db as cmdb
    from app.services import wfirma_db as wfdb

    db_path = tmp_path / "proforma_drafts.sqlite"

    cm_db = tmp_path / "customer_master.sqlite"
    cmdb.init_db(cm_db)
    cmdb.upsert_customer(cm_db, cm)

    wf_db = tmp_path / "wfirma.sqlite"
    wfdb.init_wfirma_db(wf_db)
    if register_contractor:
        wfdb.upsert_customer(
            CLIENT,
            wfirma_customer_id=CONTRACTOR_ID,
            vat_id=cm.nip or "",
            country=cm.country or "SK",
        )
    wfdb.upsert_product(
        product_code=PRODUCT_CODE,
        wfirma_product_id=WFIRMA_GOOD_ID,
        product_name="Ring",
    )

    lines_json = json.dumps([{
        "product_code": PRODUCT_CODE, "design_no": "R1",
        "qty": 1.0, "unit_price": 100.0, "currency": "EUR",
    }])
    now = "2026-01-01T00:00:00Z"
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        pildb._ensure_drafts_table(conn)
        conn.execute(
            """
            INSERT INTO proforma_drafts
              (batch_id, client_name, status, draft_state, currency,
               source_lines_json, editable_lines_json, service_charges_json,
               clone_generation, created_at, updated_at)
            VALUES (?, ?, 'draft', 'approved', 'EUR', ?, ?, '[]', 0, ?, ?)
            """,
            (BATCH, draft_client_name, lines_json, lines_json, now, now),
        )
        row_id = conn.execute(
            "SELECT id FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
            (BATCH, draft_client_name),
        ).fetchone()["id"]

    return pildb.get_draft_by_id(db_path, row_id)


def _post_draft(app_client, draft_id: int, draft) -> "object":
    return app_client.post(
        f"/api/v1/proforma/draft/{draft_id}/post",
        json={
            "expected_updated_at": draft.updated_at,
            "confirm_token": "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA",
        },
        headers={"X-API-Key": "test-key", "X-Operator": "test-op"},
    )


def _mock_wfirma_http(
    monkeypatch,
    *,
    vat_code_id: str = "228",
    contractor_nip: Optional[str] = None,
    add_response: Optional[tuple] = None,
    captured: Optional[List[tuple]] = None,
):
    """Mock _http_request.

    contractor_nip:
      None → contractors/get/{id} returns OK with NO <contractor> node
             (fetch_contractor_by_id → ok=False → preflight gate fail-opens)
      str  → contractor XML with that <nip> value ("" = empty NIP)
    add_response: optional (http_status, body) override for invoices/add.
    captured: list collecting (controller, action, body) tuples.
    """
    calls: List[tuple] = captured if captured is not None else []

    def _fake_http(method, controller, action, body=""):
        calls.append((controller, action, body))

        if controller == "contractors" and action.startswith("get/"):
            if contractor_nip is None:
                return 200, ('<?xml version="1.0" encoding="UTF-8"?>'
                             "<api><status><code>OK</code></status></api>")
            return 200, _contractor_xml(nip=contractor_nip)

        if controller == "invoices" and action == "add":
            if add_response is not None:
                return add_response
            return 200, _wfirma_add_ok_xml()
        if controller == "invoices" and (action == "get" or action.startswith("get/")):
            return 200, _wfirma_verify_xml(vat_code_id=vat_code_id)

        if controller == "vat_codes" and action == "find":
            _code_map = {
                "23": "222", "WDT": "228", "EXP": "229",
                "NP": "230", "NPUE": "231", "ZW": "233", "0": "234",
            }
            for code_str, num_id in _code_map.items():
                if f"<value>{code_str}</value>" in body:
                    return 200, (
                        f'<?xml version="1.0" encoding="UTF-8"?>'
                        f"<api><status><code>OK</code></status>"
                        f"<vat_codes><vat_code>"
                        f"<id>{num_id}</id><code>{code_str}</code>"
                        f"</vat_code></vat_codes></api>"
                    )
            return 200, ('<?xml version="1.0" encoding="UTF-8"?>'
                         "<api><status><code>OK</code></status>"
                         "<vat_codes></vat_codes></api>")

        return 200, ('<?xml version="1.0" encoding="UTF-8"?>'
                     "<api><status><code>OK</code></status></api>")

    monkeypatch.setattr(wfirma_client, "_http_request", _fake_http)
    wfirma_client._VAT_CODE_ID_CACHE.clear()
    return calls


def _add_calls(calls: List[tuple]) -> List[tuple]:
    return [c for c in calls if c[0] == "invoices" and c[1] == "add"]


# ──────────────────────────────────────────────────────────────────────────────
# E-series: _extract_field_errors unit tests
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractFieldErrors:

    def test_e1_real_contractor_error_shape(self):
        """E1: draft-#33 response shape → entity-qualified field errors."""
        out = _extract_field_errors(HORAK_ERROR_XML)
        assert out == [
            "contractor.zip: Pole nie może być puste.",
            "contractor.city: Pole nie może być puste.",
        ]

    def test_e2_ok_response_empty(self):
        """E2: OK response with no error nodes → []."""
        assert _extract_field_errors(_wfirma_add_ok_xml()) == []

    def test_e3_malformed_xml_empty(self):
        """E3: unparseable input → [] (never raises)."""
        assert _extract_field_errors("<api><unclosed>") == []
        assert _extract_field_errors("") == []

    def test_e4_limit_honoured(self):
        """E4: more errors than limit → truncated to limit."""
        errs = "".join(
            f"<error><field>f{i}</field><message>m{i}</message></error>"
            for i in range(15)
        )
        xml = (f"<api><invoices><invoice><contractor><errors>{errs}</errors>"
               f"</contractor></invoice></invoices>"
               f"<status><code>ERROR</code></status></api>")
        out = _extract_field_errors(xml, limit=3)
        assert len(out) == 3
        assert out[0] == "contractor.f0: m0"

    def test_e5_message_only_error(self):
        """E5: error with <message> but no <field> still surfaces."""
        xml = ("<api><invoices><invoice><errors>"
               "<error><message>Dokument nie istnieje.</message></error>"
               "</errors></invoice></invoices>"
               "<status><code>ERROR</code></status></api>")
        out = _extract_field_errors(xml)
        assert len(out) == 1
        assert "Dokument nie istnieje." in out[0]


# ──────────────────────────────────────────────────────────────────────────────
# C-series: WFirmaCreateError via create_proforma_draft
# ──────────────────────────────────────────────────────────────────────────────

def _minimal_request() -> ProformaRequest:
    return ProformaRequest(
        client_name=CLIENT,
        client_zip="92701",
        client_city="Sala",
        lines=[ReservationLine(
            product_code=PRODUCT_CODE,
            wfirma_good_id=WFIRMA_GOOD_ID,
            product_name="Ring",
            qty=1.0,
            unit_price=100.0,
            currency="EUR",
        )],
        currency="EUR",
        wfirma_contractor_id=CONTRACTOR_ID,
        vat_code_id="228",
    )


class TestWFirmaCreateError:

    def test_c1_error_status_carries_field_detail(self, monkeypatch):
        """C1: status=ERROR + nested errors → readable message + audit XML."""
        def _fake_http(method, controller, action, body=""):
            assert (controller, action) == ("invoices", "add")
            return 200, HORAK_ERROR_XML
        monkeypatch.setattr(wfirma_client, "_http_request", _fake_http)

        with pytest.raises(WFirmaCreateError) as ei:
            wfirma_client.create_proforma_draft(_minimal_request())
        exc = ei.value
        # The operator-facing message names the offending fields — no more
        # opaque "status=ERROR:" (draft #33 failure mode).
        assert "contractor.zip" in str(exc)
        assert "Pole nie może być puste." in str(exc)
        assert exc.field_errors and exc.field_errors[0].startswith("contractor.zip")
        # Sanitized exchange evidence for the audit trail.
        assert exc.response_xml == HORAK_ERROR_XML
        assert "<invoice>" in exc.request_xml
        # Credentials never appear in XML bodies (header-auth only).
        assert "appKey" not in exc.request_xml
        assert "accessKey" not in exc.request_xml

    def test_c2_http_error_attaches_body(self, monkeypatch):
        """C2: HTTP 500 → WFirmaCreateError with response body."""
        monkeypatch.setattr(
            wfirma_client, "_http_request",
            lambda m, c, a, b="": (500, "Internal Server Error"))
        with pytest.raises(WFirmaCreateError) as ei:
            wfirma_client.create_proforma_draft(_minimal_request())
        assert "HTTP 500" in str(ei.value)
        assert ei.value.response_xml == "Internal Server Error"

    def test_c3_is_runtimeerror_subclass(self):
        """C3: existing `except RuntimeError` handlers keep working."""
        assert issubclass(WFirmaCreateError, RuntimeError)
        exc = WFirmaCreateError("x")
        assert exc.request_xml == "" and exc.response_xml == ""
        assert exc.field_errors == []


# ──────────────────────────────────────────────────────────────────────────────
# G-series: integration — WDT preflight gate + failure audit + retry safety
# ──────────────────────────────────────────────────────────────────────────────

class TestPostFailureHardeningIntegration:

    def _eu_cm_no_vat(self) -> CustomerMaster:
        """SK customer, no EU VAT number anywhere → derived wdt-intent (D3)."""
        return _make_cm(country="SK", vat_eu_number=None, vat_mode=None)

    def _eu_cm_with_vat(self) -> CustomerMaster:
        return _make_cm(country="SK", vat_eu_number="SK2020123456",
                        vat_eu_valid=True, vat_mode=None)

    def test_g1_wdt_empty_nip_blocked_pre_commit(
        self, tmp_path, monkeypatch, app_client
    ):
        """G1: WDT + empty NIP on the live contractor → 400, no wFirma write,
        draft stays approved (retry after fixing data needs no reset)."""
        cm = self._eu_cm_no_vat()
        _patch_env(tmp_path, monkeypatch)
        draft = _setup_db_for_draft(tmp_path, cm)
        calls = _mock_wfirma_http(monkeypatch, contractor_nip="")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 400, resp.text
        data = resp.json()
        assert data["status"] == "blocked"
        reason = " ".join(data.get("blocking_reasons") or [])
        # Reason must be actionable: names the contractor, the cause, the fix.
        assert "no EU VAT number" in reason
        assert CONTRACTOR_ID in reason
        assert "Customer Master" in reason or "customer_master" in reason

        assert not _add_calls(calls), "invoices/add must not be attempted"
        # No state change: draft is still approved → safe to fix data + repost.
        after = pildb.get_draft_by_id(tmp_path / "proforma_drafts.sqlite", draft.id)
        assert after.draft_state == "approved"
        assert not (after.wfirma_proforma_id or "").strip()

    def test_g2_wdt_with_nip_posts(self, tmp_path, monkeypatch, app_client):
        """G2: successful EUR proforma, qty=1, foreign EU contractor with NIP."""
        cm = self._eu_cm_with_vat()
        _patch_env(tmp_path, monkeypatch)
        draft = _setup_db_for_draft(tmp_path, cm)
        calls = _mock_wfirma_http(monkeypatch, contractor_nip="SK2020123456",
                                  vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "posted"
        assert data.get("wfirma_proforma_id") == WFIRMA_PROFORMA_ID
        assert len(_add_calls(calls)) == 1

        after = pildb.get_draft_by_id(tmp_path / "proforma_drafts.sqlite", draft.id)
        assert (after.wfirma_proforma_id or "").strip() == WFIRMA_PROFORMA_ID

    def test_g3_gate_fail_open_on_fetch_failure(
        self, tmp_path, monkeypatch, app_client
    ):
        """G3: contractor fetch fails (no <contractor>) → gate fail-opens,
        post proceeds. A wFirma availability blip must not block posting."""
        cm = self._eu_cm_with_vat()
        _patch_env(tmp_path, monkeypatch)
        draft = _setup_db_for_draft(tmp_path, cm)
        calls = _mock_wfirma_http(monkeypatch, contractor_nip=None,
                                  vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "posted"
        assert len(_add_calls(calls)) == 1

    def test_g4_domestic_gate_not_fired(self, tmp_path, monkeypatch, app_client):
        """G4: non-WDT context → contractor NIP irrelevant, gate skipped."""
        cm = _make_cm(country="PL", vat_mode=222)
        _patch_env(tmp_path, monkeypatch)
        draft = _setup_db_for_draft(tmp_path, cm)
        calls = _mock_wfirma_http(monkeypatch, contractor_nip="",
                                  vat_code_id="222")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "posted"
        assert len(_add_calls(calls)) == 1

    def test_g5_wfirma_rejection_readable_and_audited(
        self, tmp_path, monkeypatch, app_client
    ):
        """G5: wFirma rejects invoices/add → operator-readable error AND
        a wfirma_post_exchange event carrying the sanitized request/response."""
        cm = self._eu_cm_with_vat()
        _patch_env(tmp_path, monkeypatch)
        draft = _setup_db_for_draft(tmp_path, cm)
        _mock_wfirma_http(monkeypatch, contractor_nip="SK2020123456",
                          add_response=(200, HORAK_ERROR_XML))

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "failed"
        # Readable reason — names the fields, not just "status=ERROR:".
        assert "contractor.zip" in (data.get("error") or "")

        db = tmp_path / "proforma_drafts.sqlite"
        after = pildb.get_draft_by_id(db, draft.id)
        assert after.draft_state == "post_failed"
        assert "contractor.zip" in (after.notes or "")

        events = pildb.list_draft_events(db, draft.id)
        exchange = [e for e in events if e["event"] == "wfirma_post_exchange"]
        assert exchange, f"wfirma_post_exchange event missing; got: " \
                         f"{[e['event'] for e in events]}"
        detail = json.loads(exchange[-1]["detail_json"])
        assert detail["field_errors"], "field_errors missing from exchange event"
        assert detail["field_errors"][0].startswith("contractor.zip")
        assert "<invoice>" in detail["request_xml"]
        assert "<error>" in detail["response_xml"]
        # Sanitized: credentials never travel in XML bodies.
        for blob in (detail["request_xml"], detail["response_xml"]):
            assert "appKey" not in blob and "accessKey" not in blob

    def test_g6_retry_duplicate_guard(self, tmp_path, monkeypatch, app_client):
        """G6: draft already carries wfirma_proforma_id → 409, no second
        document is ever created in wFirma."""
        cm = self._eu_cm_with_vat()
        _patch_env(tmp_path, monkeypatch)
        draft = _setup_db_for_draft(tmp_path, cm)
        db = tmp_path / "proforma_drafts.sqlite"
        with sqlite3.connect(str(db)) as conn:
            conn.execute(
                "UPDATE proforma_drafts SET wfirma_proforma_id=? WHERE id=?",
                (WFIRMA_PROFORMA_ID, draft.id),
            )
        calls = _mock_wfirma_http(monkeypatch, contractor_nip="SK2020123456")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 409, resp.text
        assert WFIRMA_PROFORMA_ID in resp.json()["detail"]
        assert not _add_calls(calls), "duplicate post must never reach wFirma"

    def test_g7_missing_contractor_mapping_blocked(
        self, tmp_path, monkeypatch, app_client
    ):
        """G7: client name resolves to NO contractor identity (neither
        Customer Master nor wfirma_customers cache) → 400 blocked pre-commit.

        Note: Customer Master is the PRIMARY identity authority — a CM
        record with bill_to_contractor_id resolves even without the
        wfirma_customers cache row. The unmapped scenario therefore needs a
        draft client name unknown to BOTH stores.
        """
        cm = self._eu_cm_with_vat()  # CM exists, but for a different name
        _patch_env(tmp_path, monkeypatch)
        draft = _setup_db_for_draft(
            tmp_path, cm,
            register_contractor=False,
            draft_client_name="NO-SUCH-CLIENT",
        )
        calls = _mock_wfirma_http(monkeypatch, contractor_nip="SK2020123456")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 400, resp.text
        data = resp.json()
        assert data["status"] == "blocked"
        reason = " ".join(data.get("blocking_reasons") or [])
        assert "register the mapping" in reason or "no wfirma_customer_id" in reason
        assert not _add_calls(calls)
        after = pildb.get_draft_by_id(tmp_path / "proforma_drafts.sqlite", draft.id)
        assert after.draft_state == "approved"
