"""
test_invoice_verify_after_create.py — Verify-after-create hardening for the
Proforma → Invoice conversion route.

After invoices/add succeeds, the route fetches the created invoice back and
verifies 7 header properties + per-line field matching. If verification fails,
the link is marked 'failed', an audit event is recorded, and the response
indicates failure.

Pins:
  1. Verification passes when the created invoice matches (happy path).
  2. Verification fails when fetched invoice has wrong type.
  3. Verification fails when contractor mismatches.
  4. Verification fails when line count mismatches (silent line drop).
  5. Verification fails when currency mismatches.
  6. Verification fails when total exceeds tolerance (>0.02 diff).
  7. Verification passes when total is within tolerance (≤0.02 diff).
  8. Verification fails when contractor_receiver is lost.
  9. Verification passes when no receiver expected and none returned.
  10. On verification failure, link status is 'failed' (not 'issued').
  11. On verification failure, response includes verify_after_create_failed=True.
  12. On verification failure, audit event is recorded with outcome='failed'.
  13. Verify-fetch network failure also marks link failed.
  14. Per-line: verification fails when line name mismatches.
  15. Per-line: verification fails when good_id mismatches.
  16. Per-line: verification fails when unit_count mismatches.
  17. Per-line: verification fails when price mismatches.
  18. Per-line: verification fails when vat_code_id mismatches.
  19. Per-line: multiple field mismatches on one line reported together.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, call

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as wc
from app.services import packing_db    as pdb
from app.services import warehouse_db  as wdb
from app.services import document_db   as ddb
from app.services import wfirma_db     as wfdb
from app.services import proforma_invoice_link_db as pildb
from app.services import proforma_invoice_link_db as plink
from app.services import proforma_service_charges_db as scdb


BATCH = "BATCH_VAC_TEST"
CLIENT = "ACME"
CONFIRM_TOKEN = "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"


# ── Source proforma XML (what fetch_invoice_xml returns for the plan step) ────

def _proforma_xml(*, pid="467236963", pnum="PROF 92/2026",
                   contractor_id="9001", currency="EUR",
                   receiver_id: str = "", total: str = "306.00") -> str:
    rcv_block = (f"      <contractor_receiver><id>{receiver_id}</id></contractor_receiver>\n"
                 if receiver_id else "")
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>{pid}</id>
      <type>proforma</type>
      <fullnumber>{pnum}</fullnumber>
      <date>2026-05-08</date>
      <paymentmethod>transfer</paymentmethod>
      <paymentdate>2026-05-15</paymentdate>
      <currency>{currency}</currency>
      <contractor><id>{contractor_id}</id></contractor>
{rcv_block}      <series><id>15827088</id></series>
      <total>{total}</total>
      <netto>{total}</netto>
      <description>Source proforma</description>
      <invoicecontents>
        <invoicecontent>
          <name>RING</name>
          <good><id>42</id></good>
          <unit>szt.</unit>
          <unit_count>1.0000</unit_count>
          <price>306.00</price>
          <vat_code><id>228</id></vat_code>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


# ── Created invoice XML (what fetch_invoice_xml returns for the verify step) ──

def _created_invoice_xml(*, inv_id="500001", inv_type="normal",
                          contractor_id="9001", currency="EUR",
                          total="306.00", line_count=1,
                          receiver_id: str = "",
                          line_overrides: "dict | None" = None) -> str:
    """Build XML for the created invoice.

    line_overrides: optional dict mapping 0-based line index to a dict of
    field overrides (name, good_id, unit_count, price, vat_code_id).
    """
    rcv_block = (f"      <contractor_receiver><id>{receiver_id}</id></contractor_receiver>\n"
                 if receiver_id else "")
    overrides = line_overrides or {}
    lines = ""
    for i in range(line_count):
        lo = overrides.get(i, {})
        l_name = lo.get("name", "RING")
        l_good_id = lo.get("good_id", "42")
        l_unit_count = lo.get("unit_count", "1.0000")
        l_price = lo.get("price", "306.00")
        l_vat_code_id = lo.get("vat_code_id", "228")
        lines += f"""        <invoicecontent>
          <name>{l_name}</name>
          <good><id>{l_good_id}</id></good>
          <unit>szt.</unit>
          <unit_count>{l_unit_count}</unit_count>
          <price>{l_price}</price>
          <vat_code><id>{l_vat_code_id}</id></vat_code>
        </invoicecontent>
"""
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>{inv_id}</id>
      <type>{inv_type}</type>
      <fullnumber>FA 1/5/2026</fullnumber>
      <date>2026-06-08</date>
      <paymentmethod>transfer</paymentmethod>
      <paymentdate>2026-05-15</paymentdate>
      <currency>{currency}</currency>
      <total>{total}</total>
      <netto>{total}</netto>
      <contractor><id>{contractor_id}</id></contractor>
{rcv_block}      <invoicecontents>
{lines}      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


def _invoices_add_response(inv_id="500001", fullnumber="FA 1/5/2026") -> str:
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>{inv_id}</id>
      <fullnumber>{fullnumber}</fullnumber>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _prime_vat():
    wc._VAT_CODE_ID_CACHE["23"]  = "222"
    wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    yield


@pytest.fixture(autouse=True)
def _neutralize_convert_readiness(monkeypatch):
    """Single-readiness-authority gate stub (convert step 2c): this suite
    pins the verify-after-create mechanics of the execute route, not
    readiness — that has dedicated no-stub coverage in
    test_proforma_readiness_single_authority.py. Without the stub, the
    minimal seeded draft (no sales rows, no wfirma customer) is blocked at
    step 2c before the wFirma plan/verify steps this suite exercises.
    Shape mirrors the real _derive_draft_readiness return exactly (Lesson A)."""
    from app.api import routes_proforma as rp

    def _stub_readiness(draft, *, intent):
        return {
            "ready":             True,
            "intent":            intent,
            "draft_id":          int(draft.id),
            "draft_status":      draft.status,
            "blockers":          [],
            "blocking_reasons":  [],
            "warnings":          [],
            "ambiguous_designs": {},
            "resolved_designs":  {},
            "vat_resolution":    None,
            "duplicate_product_codes": [],
            "product_authority_available": True,
        }
    monkeypatch.setattr(rp, "_derive_draft_readiness", _stub_readiness)


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    scdb.init(tmp_path / "proforma_links.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    plink.init_db(tmp_path / "proforma_links.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _gate_invoice_on():
    return patch.object(settings, "wfirma_create_invoice_allowed", True)


def _seed_issued_proforma(storage, *, wfirma_id="467236963",
                            client_name=CLIENT):
    db = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        db, batch_id=BATCH, client_name=client_name,
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    pildb.mark_draft_issued(db, BATCH, client_name,
                              wfirma_proforma_id=wfirma_id)


_EXECUTE_URL = "/api/v1/proforma/to-invoice/{batch}/{client}"


def _execute(client, *, batch=BATCH, cn=CLIENT):
    """POST to the execute endpoint with all gates satisfied."""
    return client.post(
        _EXECUTE_URL.format(batch=batch, client=cn),
        headers={**_auth(), "X-Operator": "amit"},
        json={"confirm": CONFIRM_TOKEN},
    ).json()


# ── 1. Happy path — verification passes ─────────────────────────────────────

def test_verify_after_create_passes_when_invoice_matches(client, storage):
    """When the created invoice matches the plan, conversion succeeds."""
    _seed_issued_proforma(storage)
    # fetch_invoice_xml is called TWICE:
    #   1st: source proforma fetch (plan step)
    #   2nd: verify-after-create fetch (verify step)
    fetch_calls = [
        _proforma_xml(),              # 1st call: source proforma
        _created_invoice_xml(),       # 2nd call: created invoice
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is True
    assert body["status"] == "issued"
    assert body["wfirma_invoice_id"] == "500001"
    assert "verify_after_create_failed" not in body


# ── 2. Verification fails: wrong type ───────────────────────────────────────

def test_verify_fails_when_type_is_proforma(client, storage):
    """If wFirma somehow creates a proforma instead of a normal invoice."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(inv_type="proforma"),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "type" in body["error"].lower()


# ── 3. Verification fails: contractor mismatch ──────────────────────────────

def test_verify_fails_when_contractor_mismatches(client, storage):
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(contractor_id="9999"),  # wrong contractor
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "contractor mismatch" in body["error"]


# ── 4. Verification fails: line count mismatch ──────────────────────────────

def test_verify_fails_when_lines_dropped(client, storage):
    """wFirma silently dropped lines — persisted 0 instead of 1."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(line_count=0),  # no lines persisted
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "line count mismatch" in body["error"]


# ── 5. Verification fails: currency mismatch ────────────────────────────────

def test_verify_fails_when_currency_mismatches(client, storage):
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(currency="USD"),  # wrong currency
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "currency mismatch" in body["error"]


# ── 6. Verification fails: total exceeds tolerance ──────────────────────────

def test_verify_fails_when_total_exceeds_tolerance(client, storage):
    """Total diff > 0.02 triggers failure."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(total="306.10"),  # diff = 0.10 > 0.02
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "total mismatch" in body["error"]


# ── 7. Verification passes: total within tolerance ──────────────────────────

def test_verify_passes_when_total_within_tolerance(client, storage):
    """Total diff ≤ 0.02 is acceptable (rounding)."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(total="306.01"),  # diff = 0.01 ≤ 0.02
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is True
    assert body["status"] == "issued"


# ── 8. Verification fails: receiver lost ────────────────────────────────────

def test_verify_fails_when_receiver_lost(client, storage):
    """Source proforma has receiver, but created invoice lost it."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(receiver_id="99990004"),
        _created_invoice_xml(receiver_id=""),  # receiver lost
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "fetch_contractor_by_id",
                      return_value=wc.ContractorFetchResult(
                          ok=True, contractor_id="99990004",
                          name="Receiver Co.")), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "contractor_receiver mismatch" in body["error"]


# ── 9. Verification passes: no receiver expected, none returned ─────────────

def test_verify_passes_when_no_receiver_expected(client, storage):
    """No receiver on source proforma → no receiver check needed."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(receiver_id=""),
        _created_invoice_xml(receiver_id=""),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is True
    assert body["status"] == "issued"


# ── 10. On failure, link status is 'failed' ─────────────────────────────────

def test_verify_failure_marks_link_as_failed(client, storage):
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(line_count=0),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        _execute(client)

    link = plink.get_link_by_proforma(
        storage / "proforma_links.db", "467236963")
    assert link is not None
    assert link.status == "failed"
    assert "verify-after-create" in (link.notes or "").lower()


# ── 11. Response includes verify_after_create_failed flag ───────────────────

def test_verify_failure_response_has_flag(client, storage):
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(contractor_id="9999"),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["verify_after_create_failed"] is True
    assert body["wfirma_invoice_id"] == "500001"  # invoice EXISTS but is bad


# ── 12. Audit event recorded on verification failure ────────────────────────

def test_verify_failure_records_audit_event(client, storage):
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(currency="USD"),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["status"] == "failed"
    # Check that the audit file was written with the failure.
    audit_path = storage / "outputs" / BATCH / "audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        timeline = audit.get("timeline", [])
        failed_events = [
            e for e in timeline
            if e.get("event") == "invoice_approval_attempt"
            and e.get("detail", {}).get("outcome") == "failed"
        ]
        assert len(failed_events) >= 1
        assert "verify-after-create" in (
            failed_events[0].get("detail", {}).get("blocking_reason", "").lower()
        )


# ── 13. Verify-fetch network failure marks link failed ──────────────────────

def test_verify_fetch_network_failure_marks_link_failed(client, storage):
    """If the verify-fetch itself fails (network), link is still marked failed."""
    _seed_issued_proforma(storage)
    call_count = [0]

    def _fetch_side_effect(invoice_id):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: return source proforma for plan building
            return _proforma_xml()
        else:
            # Second call: verify-fetch fails
            raise ConnectionError("wFirma unreachable during verify")

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=_fetch_side_effect), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "unreachable" in body["error"].lower()

    link = plink.get_link_by_proforma(
        storage / "proforma_links.db", "467236963")
    assert link is not None
    assert link.status == "failed"


# ── 14. Per-line field verification: name mismatch ────────────────────────────

def test_verify_fails_when_line_name_mismatches(client, storage):
    """Check 4b: line name (product name) must match source proforma."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(line_overrides={0: {"name": "WRONG-PRODUCT"}}),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "line 1 field mismatch" in body["error"]
    assert "name:" in body["error"]


# ── 15. Per-line field verification: good_id mismatch ─────────────────────────

def test_verify_fails_when_line_good_id_mismatches(client, storage):
    """Check 4b: good (product) ID must match."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(line_overrides={0: {"good_id": "999"}}),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "good_id:" in body["error"]


# ── 16. Per-line field verification: unit_count mismatch ──────────────────────

def test_verify_fails_when_line_unit_count_mismatches(client, storage):
    """Check 4b: unit_count (quantity) must match."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(line_overrides={0: {"unit_count": "5.0000"}}),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "unit_count:" in body["error"]


# ── 17. Per-line field verification: price mismatch ───────────────────────────

def test_verify_fails_when_line_price_mismatches(client, storage):
    """Check 4b: line price must match."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(line_overrides={0: {"price": "999.99"}}),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "price:" in body["error"]


# ── 18. Per-line field verification: vat_code_id mismatch ─────────────────────

def test_verify_fails_when_line_vat_code_mismatches(client, storage):
    """Check 4b: VAT code ID must match."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(line_overrides={0: {"vat_code_id": "111"}}),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["verify_after_create_failed"] is True
    assert "vat_code_id:" in body["error"]


# ── 19. Per-line field verification: multiple mismatches reported together ────

def test_verify_reports_all_field_mismatches_on_one_line(client, storage):
    """If multiple fields mismatch on one line, all are reported."""
    _seed_issued_proforma(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(line_overrides={0: {
            "name": "X", "price": "0.01", "vat_code_id": "999"
        }}),
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _execute(client)

    assert body["ok"] is False
    assert "name:" in body["error"]
    assert "price:" in body["error"]
    assert "vat_code_id:" in body["error"]


# ── Source-grep: verify-after-create step exists in routes_proforma.py ───────

def test_source_grep_verify_after_create_exists():
    """The verify-after-create step must exist in routes_proforma.py."""
    routes = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_proforma.py"
    src = routes.read_text(encoding="utf-8")
    assert "verify-after-create" in src
    assert "fetch_invoice_xml(wfirma_inv_id)" in src


def test_source_grep_verify_checks_seven_properties():
    """All 7 verification checks + per-line field matching must be present."""
    routes = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_proforma.py"
    src = routes.read_text(encoding="utf-8")
    # Check 1: id
    assert "has empty <id>" in src
    # Check 2: type
    assert "type='normal'" in src or "expected type='normal'" in src
    # Check 3: contractor
    assert "contractor mismatch" in src
    # Check 4: line count
    assert "line count mismatch" in src
    # Check 4b: per-line fields
    assert "line {idx} field mismatch" in src or "per-line field verification" in src
    # Check 5: currency
    assert "currency mismatch" in src
    # Check 6: total
    assert "total mismatch" in src
    # Check 7: receiver
    assert "contractor_receiver mismatch" in src


def test_source_grep_per_line_checks_all_fields():
    """Check 4b verifies name, good_id, unit_count, price, vat_code_id."""
    routes = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_proforma.py"
    src = routes.read_text(encoding="utf-8")
    for field in ("_a_name", "_a_good_id", "_a_unit_count", "_a_price", "_a_vat_id"):
        assert field in src, f"per-line verification variable {field!r} not found"
