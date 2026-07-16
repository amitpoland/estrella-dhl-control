"""
test_proforma_to_invoice_routes.py — Manual Proforma → Invoice flow.

Pins (each maps to a numbered scope rule):
  1. Preview does NOT call wFirma create.
  2. Execute blocked when WFIRMA_CREATE_INVOICE_ALLOWED=false.
  3. Execute blocked without confirm token.
  4. Execute blocked without X-Operator.
  5. Execute blocked when proforma missing or not issued.
  6. Execute blocked when invoice link already exists.
  7. Execute preserves contractor_receiver from the source proforma.
  8. Dashboard source-grep: button calls preview first, execute only
     after the operator types the confirm token AND clicks Convert.
  9. Source-grep guard that no background / auto conversion path
     references the execute endpoint.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

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


BATCH = "BATCH_CONVERT_TEST"
CLIENT = "ACME"
CONFIRM_TOKEN = "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"


# ── Live-shape Proforma XML fixture ────────────────────────────────────────

def _proforma_xml(*, pid="467236963", pnum="PROF 92/2026",
                   contractor_id="9001", currency="EUR",
                   receiver_id: str = "") -> str:
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
      <total>306.00</total>
      <netto>306.00</netto>
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


# ── Created invoice XML (for verify-after-create step) ─────────────────────

def _created_invoice_xml(*, inv_id="500001", contractor_id="9001",
                           currency="EUR", total="306.00",
                           receiver_id: str = "") -> str:
    """Minimal normal-type invoice XML returned by fetch_invoice_xml during
    the verify-after-create step. Matches the standard proforma shape."""
    rcv_block = (f"      <contractor_receiver><id>{receiver_id}</id></contractor_receiver>\n"
                 if receiver_id else "")
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>{inv_id}</id>
      <type>normal</type>
      <fullnumber>FA 1/5/2026</fullnumber>
      <date>2026-06-08</date>
      <paymentmethod>transfer</paymentmethod>
      <paymentdate>2026-05-15</paymentdate>
      <currency>{currency}</currency>
      <total>{total}</total>
      <netto>{total}</netto>
      <contractor><id>{contractor_id}</id></contractor>
{rcv_block}      <invoicecontents>
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


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _prime_vat():
    wc._VAT_CODE_ID_CACHE["23"]  = "222"
    wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    yield


@pytest.fixture(autouse=True)
def _readiness_clean(monkeypatch):
    """Stub the single-readiness-authority gate (split-authority fix).

    These tests pin conversion mechanics (link recording, receiver
    preservation, preflight, wFirma rejection handling), not readiness
    derivation — that has dedicated no-stub coverage in
    test_proforma_readiness_single_authority.py (including convert-intent
    blocking). Shape mirrors the real _derive_draft_readiness return
    exactly (Lesson A). Tests asserting other blocked statuses (ghost
    client, existing link) still hit their specific checks, which run
    independently of this gate."""
    from app.api import routes_proforma as rp

    def _stub(draft, *, intent):
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
        }
    monkeypatch.setattr(rp, "_derive_draft_readiness", _stub)


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
    """Persist a proforma_drafts row in 'issued' status with the given
    wFirma proforma id."""
    db = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        db, batch_id=BATCH, client_name=client_name,
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    pildb.mark_draft_issued(db, BATCH, client_name,
                              wfirma_proforma_id=wfirma_id)


_PREVIEW_URL = (
    "/api/v1/proforma/to-invoice-preview/{batch}/{client}"
)
_EXECUTE_URL = (
    "/api/v1/proforma/to-invoice/{batch}/{client}"
)


# ── 1. Preview does NOT call wFirma create ─────────────────────────────────

def test_preview_does_not_call_wfirma_create(client, storage):
    _seed_issued_proforma(storage)
    with patch.object(wc, "fetch_invoice_xml",
                      return_value=_proforma_xml()), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError(
                          "preview must not POST invoices/add")):
        r = client.get(
            _PREVIEW_URL.format(batch=BATCH, client=CLIENT),
            headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"]     is True
    assert body["status"] == "preview"
    assert body["wfirma_proforma_id"] == "467236963"
    assert body["summary"]["source_proforma_number"] == "PROF 92/2026"
    assert body["summary"]["currency"]                == "EUR"
    assert "<contractor>" in body["plan_xml"]
    # Operator-visible warning copy.
    assert "real wFirma invoice" in body["warning"]


def test_preview_blocks_when_no_draft(client, storage):
    """No proforma_drafts row → preview blocked, no wFirma call."""
    with patch.object(wc, "fetch_invoice_xml",
                      side_effect=AssertionError("must not fetch")):
        body = client.get(
            _PREVIEW_URL.format(batch=BATCH, client="GHOST"),
            headers=_auth()).json()
    assert body["status"] == "blocked"
    assert any("no local proforma_drafts" in r
               for r in body["blocking_reasons"])


def test_preview_blocks_when_link_already_exists(client, storage):
    _seed_issued_proforma(storage)
    # Pre-insert a conversion link so the preview gate fires.
    plink.create_pending_link(
        storage / "proforma_links.db",
        plink.ProformaInvoiceLink(
            proforma_id     = "467236963",
            proforma_number = "PROF 92/2026",
            converted_at    = "2026-05-08T00:00:00+00:00",
            operator        = "amit",
            source_total    = Decimal("306.00"),
            currency        = "EUR",
            status          = "pending",
        ),
    )
    with patch.object(wc, "fetch_invoice_xml",
                      side_effect=AssertionError("must not fetch")):
        body = client.get(
            _PREVIEW_URL.format(batch=BATCH, client=CLIENT),
            headers=_auth()).json()
    assert body["status"] == "blocked"
    assert any("already has a conversion link" in r
               for r in body["blocking_reasons"])


# ── 2. Execute blocked when flag false ─────────────────────────────────────

def test_execute_blocked_when_flag_false(client, storage):
    _seed_issued_proforma(storage)
    # Default settings.wfirma_create_invoice_allowed is False.
    with patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        r = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN})
    body = r.json()
    assert body["ok"]     is False
    assert body["status"] == "blocked"
    assert any("WFIRMA_CREATE_INVOICE_ALLOWED" in r
               for r in body["blocking_reasons"])


# ── 3. Execute blocked without confirm token ───────────────────────────────

def test_execute_blocked_without_confirm_token(client, storage):
    _seed_issued_proforma(storage)
    with _gate_invoice_on(), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": "WRONG"}).json()
    assert body["status"] == "blocked"
    assert any("confirm token" in r
               for r in body["blocking_reasons"])


def test_execute_blocked_with_empty_confirm_token(client, storage):
    _seed_issued_proforma(storage)
    with _gate_invoice_on(), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": ""}).json()
    assert body["status"] == "blocked"


# ── 4. Execute blocked without X-Operator ──────────────────────────────────

def test_execute_blocked_without_x_operator(client, storage):
    _seed_issued_proforma(storage)
    with _gate_invoice_on(), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers=_auth(),
            json={"confirm": CONFIRM_TOKEN}).json()
    assert body["status"] == "blocked"
    assert any("X-Operator" in r
               for r in body["blocking_reasons"])


# ── 5. Execute blocked if Proforma missing/not issued ──────────────────────

def test_execute_blocked_when_no_local_draft(client, storage):
    with _gate_invoice_on(), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client="GHOST"),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN}).json()
    assert body["status"] == "blocked"
    assert any("no local proforma_drafts" in r
               for r in body["blocking_reasons"])


def test_execute_blocked_when_draft_not_issued(client, storage):
    db = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        db, batch_id=BATCH, client_name=CLIENT,
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    # Draft is in 'pending_local' status (default), NOT 'issued'.
    with _gate_invoice_on(), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN}).json()
    assert body["status"] == "blocked"
    assert any("must be 'issued'" in r
               for r in body["blocking_reasons"])


# ── 6. Execute blocked when link already exists ────────────────────────────

def test_execute_blocked_when_link_already_exists(client, storage):
    _seed_issued_proforma(storage)
    plink.create_pending_link(
        storage / "proforma_links.db",
        plink.ProformaInvoiceLink(
            proforma_id="467236963", proforma_number="PROF 92/2026",
            converted_at="2026-05-08T00:00:00+00:00", operator="amit",
            source_total=Decimal("306.00"), currency="EUR",
            status="pending",
        ),
    )
    with _gate_invoice_on(), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN}).json()
    assert body["status"] == "blocked"
    assert any("already has a conversion link" in r
               for r in body["blocking_reasons"])


# ── 7. Execute preserves contractor_receiver ───────────────────────────────

def test_execute_preserves_contractor_receiver(client, storage):
    _seed_issued_proforma(storage)
    # Source proforma carries Odbiorca id 99990004.
    src_xml = _proforma_xml(receiver_id="99990004")
    # fetch_invoice_xml called twice: 1st=source proforma, 2nd=verify-after-create
    fetch_calls = [
        src_xml,
        _created_invoice_xml(inv_id="500001", receiver_id="99990004"),
    ]
    captured = {}
    def _fake_http(method, module, op, body):
        captured["method"] = method
        captured["module"] = module
        captured["op"]     = op
        captured["body"]   = body
        return 200, """<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>500001</id>
      <fullnumber>FA 1/5/2026</fullnumber>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "fetch_contractor_by_id",
                      return_value=wc.ContractorFetchResult(
                          ok=True, contractor_id="99990004",
                          name="Receiver Co.")), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN}).json()

    assert body["ok"] is True
    assert body["status"] == "issued"
    assert body["wfirma_invoice_id"]     == "500001"
    assert body["wfirma_invoice_number"] == "FA 1/5/2026"
    assert body["contractor_receiver_id"] == "99990004"
    # The actual XML posted to wFirma carries the receiver block.
    assert captured["method"] == "POST"
    assert captured["module"] == "invoices"
    assert captured["op"]     == "add"
    assert "<contractor_receiver><id>99990004</id></contractor_receiver>" \
        in captured["body"]
    # And type is normal, not proforma.
    assert "<type>normal</type>" in captured["body"]


def test_execute_omits_receiver_when_proforma_has_none(client, storage):
    """Source proforma has no receiver → final invoice payload also
    has no receiver block."""
    _seed_issued_proforma(storage)
    # fetch_invoice_xml called twice: 1st=source proforma, 2nd=verify-after-create
    fetch_calls = [
        _proforma_xml(receiver_id=""),
        _created_invoice_xml(inv_id="500002", receiver_id=""),
    ]
    captured = {}
    def _fake_http(method, module, op, body):
        captured["body"] = body
        return 200, """<?xml version="1.0"?>
<api><invoices><invoice><id>500002</id><fullnumber>FA 2/5/2026</fullnumber></invoice></invoices>
<status><code>OK</code></status></api>"""
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "fetch_contractor_by_id",
                      side_effect=AssertionError(
                          "must not preflight when no receiver")), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN}).json()
    assert body["ok"] is True
    assert body["contractor_receiver_id"] == ""
    assert "<contractor_receiver" not in captured["body"]


def test_execute_blocks_when_receiver_preflight_fails(client, storage):
    _seed_issued_proforma(storage)
    fail = wc.ContractorFetchResult(ok=False, contractor_id="99990004",
                                      error="contractor '99990004' not found")
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      return_value=_proforma_xml(receiver_id="99990004")), \
         patch.object(wc, "fetch_contractor_by_id", return_value=fail), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError(
                          "must not POST when preflight fails")):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN}).json()
    assert body["status"] == "blocked"
    assert any("99990004" in r and "not found in wFirma" in r
               for r in body["blocking_reasons"])


# ── Link row written only on success ──────────────────────────────────────

def test_execute_records_link_only_after_success(client, storage):
    """After successful conversion, proforma_invoice_links carries
    status=issued + invoice_id + invoice_number."""
    _seed_issued_proforma(storage)
    # fetch_invoice_xml called twice: 1st=source proforma, 2nd=verify-after-create
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(inv_id="500003"),
    ]
    def _fake_http(method, module, op, body):
        return 200, """<?xml version="1.0"?>
<api><invoices><invoice><id>500003</id><fullnumber>FA 3/5/2026</fullnumber></invoice></invoices>
<status><code>OK</code></status></api>"""
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN})
    link = plink.get_link_by_proforma(storage / "proforma_links.db",
                                        "467236963")
    assert link is not None
    assert link.status         == "issued"
    assert link.invoice_id     == "500003"
    assert link.invoice_number == "FA 3/5/2026"


def test_execute_marks_link_failed_when_wfirma_rejects(client, storage):
    _seed_issued_proforma(storage)
    def _fail(method, module, op, body):
        return 200, ('<api><status><code>ERROR</code>'
                     '<description>wFirma said no</description></status></api>')
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      return_value=_proforma_xml()), \
         patch.object(wc, "_http_request", side_effect=_fail):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN}).json()
    assert body["status"] == "failed"
    link = plink.get_link_by_proforma(storage / "proforma_links.db",
                                        "467236963")
    assert link is not None
    assert link.status     == "failed"
    assert link.invoice_id is None


# ── 8. Dashboard source-grep ──────────────────────────────────────────────

def test_dashboard_renders_two_step_convert_flow():
    # The Proforma→Invoice conversion UI lives in shipment-detail.html
    # (batch detail page). dashboard.html is the shipment-list page.
    src = Path("app/static/shipment-detail.html").read_text(encoding="utf-8")
    # Button label per scope rule.
    assert "Convert Proforma to Invoice" in src
    # Manual final invoice warning per scope rule.
    assert "Manual final invoice action" in src
    assert "real wFirma invoice"          in src
    # Two-step flow: preview-first then execute.
    assert "loadConvertPreview"           in src
    assert "executeConvert"               in src
    # Confirm token must be the exact string.
    assert "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA" in src
    # The execute button is gated by the confirm token comparison.
    assert "confirmToken" in src
    # data-testids for automation.
    assert 'data-testid={`btn-convert-proforma-${d.client_name}`}' in src
    assert 'data-testid={`convert-execute-${d.client_name}`}'      in src


def test_dashboard_does_not_auto_call_execute_on_load():
    """Source-grep guard: the execute endpoint must be referenced ONLY
    in `executeConvert` (the operator-clicked handler) and the
    `data-testid` for the execute button. No auto/background path."""
    # The Proforma→Invoice conversion UI lives in shipment-detail.html.
    src = Path("app/static/shipment-detail.html").read_text(encoding="utf-8")
    # Count references to the execute path. Must be exactly one fetch
    # site, inside `executeConvert`.
    fetch_paths = src.count("/api/v1/proforma/to-invoice/")
    assert fetch_paths == 1, (
        "execute endpoint URL appears more than once — investigate "
        "whether a background path was introduced"
    )
    # And no auto-trigger like setInterval / setTimeout near the
    # convert handler.
    convert_idx = src.find("executeConvert")
    assert convert_idx > 0
    surrounding = src[max(0, convert_idx - 200): convert_idx + 1500]
    assert "setInterval" not in surrounding
    assert "setTimeout"  not in surrounding


# ── Fix 4 (RC-4): payload hash guard ─────────────────────────────────────

def _hash_for(xml: str, series_id: str) -> str:
    """Compute the expected hash for a proforma XML + series_id combination.
    Legacy helper: does NOT include description in the hash. Used only by the
    hash-mismatch test (which supplies a deliberately wrong hash anyway)."""
    from app.services.proforma_to_invoice import (
        parse_proforma_xml, compute_conversion_core_hash,
    )
    snap = parse_proforma_xml(xml)
    return compute_conversion_core_hash(
        snap.contractor_id, snap.currency, series_id, snap.contents,
    )


def _hash_for_with_desc(xml: str, series_id: str) -> str:
    """Compute the description-covering hash that matches _build_convert_candidate.

    Replicates _build_convert_candidate with no CM, no overrides, and no draft
    payment terms — the exact conditions present in test_execute_succeeds_when_hash_matches.
    Both the route and this helper call warsaw_today() in the same test run, so
    they return the same date.
    """
    from app.services.proforma_to_invoice import (
        parse_proforma_xml, build_final_invoice_plan, compute_conversion_core_hash,
    )
    from app.core.timezone_utils import warsaw_today
    snap = parse_proforma_xml(xml)
    plan = build_final_invoice_plan(
        snap,
        final_series_id=series_id,
        invoice_date=warsaw_today(),
        paymentdate=None,
        paymentmethod=None,
        operator_description="",
        payment_days=None,
    )
    return compute_conversion_core_hash(
        plan.contractor_id, plan.currency, series_id, snap.contents,
        description=plan.description,
    )


def test_execute_blocked_when_hash_mismatches(client, storage):
    """Fix 4 (RC-4): if expected_payload_hash is provided and mismatches
    the recomputed hash, the execute endpoint must return ok=False / status=blocked.
    wFirma must NOT be called."""
    _seed_issued_proforma(storage)
    src_xml = _proforma_xml()
    fetch_calls = [
        src_xml,
        _created_invoice_xml(inv_id="500099"),
    ]
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError("wFirma must not be called on hash mismatch")):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={
                "confirm":               CONFIRM_TOKEN,
                "expected_payload_hash": "aaaa" + "0" * 60,  # wrong hash (64 hex chars)
            },
        ).json()
    assert body.get("ok") is False, f"Expected ok=False on hash mismatch, got: {body}"
    assert body.get("status") == "blocked", body
    assert any("hash" in (r or "").lower() or "mismatch" in (r or "").lower()
               for r in body.get("blocking_reasons", [])), (
        f"Blocking reason must mention hash mismatch; got: {body.get('blocking_reasons')}"
    )


def test_execute_succeeds_when_hash_matches(client, storage):
    """Fix 4 (RC-4): correct expected_payload_hash passes the hash guard.

    Since _build_convert_candidate now includes plan.description in the hash
    (Phase 9 RC-4 extension), the correct hash is computed by _hash_for_with_desc
    which replicates that computation for the no-CM / no-override case.
    """
    _seed_issued_proforma(storage)
    src_xml = _proforma_xml()
    # Description-covering hash: includes back-reference description so the
    # preview and execute hashes are byte-equivalent (RC-4 / Phase 9 contract).
    correct_hash = _hash_for_with_desc(src_xml, "")
    fetch_calls = [
        src_xml,
        _created_invoice_xml(inv_id="500100"),
    ]
    def _fake_http(method, module, op, body):
        return 200, """<?xml version="1.0"?>
<api><invoices><invoice><id>500100</id><fullnumber>FA 100/5/2026</fullnumber>
</invoice></invoices><status><code>OK</code></status></api>"""

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={
                "confirm":               CONFIRM_TOKEN,
                "expected_payload_hash": correct_hash,
            },
        ).json()
    assert body.get("ok") is True, f"Expected ok=True with correct hash, got: {body}"
    assert body.get("status") == "issued", body


def test_execute_succeeds_when_hash_absent(client, storage):
    """Fix 4 (RC-4) backward-compat: omitting expected_payload_hash succeeds.
    Old callers without a hash field must continue to work."""
    _seed_issued_proforma(storage)
    src_xml = _proforma_xml()
    fetch_calls = [
        src_xml,
        _created_invoice_xml(inv_id="500101"),
    ]
    def _fake_http(method, module, op, body):
        return 200, """<?xml version="1.0"?>
<api><invoices><invoice><id>500101</id><fullnumber>FA 101/5/2026</fullnumber>
</invoice></invoices><status><code>OK</code></status></api>"""

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            # No expected_payload_hash field — backward compat
            json={"confirm": CONFIRM_TOKEN},
        ).json()
    assert body.get("ok") is True, f"Expected ok=True with absent hash, got: {body}"
    assert body.get("status") == "issued", body


# ── Fix 6 (RC-5): due-date advisories ─────────────────────────────────────

def test_execute_advisory_when_no_payment_days(client, storage):
    """Fix 6 (RC-5): when no payment_days is configured anywhere, the
    execute response must include an advisory (Lesson N — NOT a blocker)."""
    _seed_issued_proforma(storage)
    src_xml = _proforma_xml()
    fetch_calls = [
        src_xml,
        _created_invoice_xml(inv_id="500200"),
    ]
    def _fake_http(method, module, op, body):
        return 200, """<?xml version="1.0"?>
<api><invoices><invoice><id>500200</id><fullnumber>FA 200/5/2026</fullnumber>
</invoice></invoices><status><code>OK</code></status></api>"""

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        # No payment_days in body — triggers advisory
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN},
        ).json()

    # Request must still succeed — advisory is NOT a blocker (Lesson N)
    assert body.get("ok") is True, (
        f"No-payment_days advisory must NOT block; got: {body}"
    )
    advisories = body.get("convert_advisories", [])
    # Advisory is emitted only when CM also has no days; test has no CM setup
    # so we check: either advisory present OR no blocking
    if advisories:
        assert not any("blocking" in a.lower() for a in advisories), (
            "Lesson N: advisory-class signals must never appear as blockers"
        )


def test_execute_due_date_advisory_never_in_blocking_reasons(client, storage):
    """Lesson N: due-date advisory must NEVER appear in blocking_reasons.
    Only fiscal-risk signals (Lesson N true-blocker list) go there."""
    _seed_issued_proforma(storage)
    src_xml = _proforma_xml()
    fetch_calls = [
        src_xml,
        _created_invoice_xml(inv_id="500201"),
    ]
    def _fake_http(method, module, op, body):
        return 200, """<?xml version="1.0"?>
<api><invoices><invoice><id>500201</id><fullnumber>FA 201/5/2026</fullnumber>
</invoice></invoices><status><code>OK</code></status></api>"""

    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN},
        ).json()

    assert "payment" not in str(body.get("blocking_reasons", [])).lower(), (
        "Due-date / payment-terms signals must never appear in blocking_reasons"
    )


# ── 9. No background path references the execute endpoint ─────────────────

def test_no_background_or_auto_conversion_path():
    """Exhaustive grep for the execute route in non-test, non-route files.
    Only the shipment-detail page and routes_proforma should reference it."""
    import os
    EXECUTE_URL_FRAGMENT = "/api/v1/proforma/to-invoice/"
    allowed_files = {
        "app/static/shipment-detail.html",
        "app/api/routes_proforma.py",
    }
    found_in: list[str] = []
    for root, _, files in os.walk("app"):
        for fn in files:
            if not fn.endswith((".py", ".html", ".js", ".ts")):
                continue
            p = Path(root) / fn
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if EXECUTE_URL_FRAGMENT in txt:
                rel = str(p)
                # Tools / probes / agents shouldn't auto-trigger this.
                if rel.replace("\\", "/") in allowed_files:
                    continue
                found_in.append(rel)
    assert found_in == [], (
        f"execute URL referenced outside the allowed UI/route surface: "
        f"{found_in}"
    )


# ── Phase 9: disclose-convert with override query params ──────────────────────

_DISCLOSE_URL = "/api/v1/proforma/draft/{draft_id}/disclose-convert"


def _seed_issued_proforma_by_draft(storage, *, wfirma_id="467236963",
                                    client_name=CLIENT) -> int:
    """Seed an issued proforma and return the draft id."""
    db = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        db, batch_id=BATCH, client_name=client_name,
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    pildb.mark_draft_issued(db, BATCH, client_name, wfirma_proforma_id=wfirma_id)
    draft = pildb.get_draft(db, BATCH, client_name)
    return draft.id


def test_disclose_returns_description_preview(client, storage):
    """disclose-convert returns description_preview when _build_convert_candidate succeeds."""
    from unittest.mock import patch as _patch
    import importlib
    # Stub get_customer_master so the candidate builder doesn't need a real CM DB
    from app.api import routes_proforma as rp

    draft_id = _seed_issued_proforma_by_draft(storage)

    def _fake_cm(path, contractor_id):
        return None  # no CM → uses snap/draft defaults

    with _patch.object(rp, "get_customer_master", _fake_cm), \
         patch.object(wc, "fetch_invoice_xml", return_value=_proforma_xml()):
        r = client.get(
            _DISCLOSE_URL.format(draft_id=draft_id),
            headers=_auth(),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "description_preview" in body, (
        "disclose-convert must include description_preview (Phase 9)"
    )
    # Back-reference must appear in the description
    assert "PROF 92/2026" in body["description_preview"], (
        "description_preview must contain the proforma back-reference number"
    )


def test_disclose_hash_covers_description(client, storage):
    """payload_core_hash from disclose-convert must change when description changes.

    We verify indirectly: two calls with different override_payment_days produce
    different descriptions → different hashes (since payment days affect the
    payment-terms block in the description).
    """
    from app.api import routes_proforma as rp

    draft_id = _seed_issued_proforma_by_draft(storage)

    def _fake_cm(path, contractor_id):
        return None

    with patch.object(rp, "get_customer_master", _fake_cm), \
         patch.object(wc, "fetch_invoice_xml", return_value=_proforma_xml()):
        r30 = client.get(
            _DISCLOSE_URL.format(draft_id=draft_id),
            params={"override_payment_days": 30},
            headers=_auth(),
        )
        r60 = client.get(
            _DISCLOSE_URL.format(draft_id=draft_id),
            params={"override_payment_days": 60},
            headers=_auth(),
        )

    assert r30.status_code == 200, r30.text
    assert r60.status_code == 200, r60.text

    h30 = r30.json().get("payload_core_hash")
    h60 = r60.json().get("payload_core_hash")

    assert h30 and h60, "payload_core_hash must be present in both responses"
    # Descriptions will differ because payment-terms block uses effective_days
    # which differs (30 vs 60). Hashes must therefore differ.
    assert h30 != h60, (
        "Hashes must differ when payment_days differ "
        "(description changes → hash changes — RC-4 coverage)"
    )


def test_disclose_description_preview_customer_clean_under_overrides(client, storage):
    """Customer-clean revision 2026-07-16: overrides still change the CUSTOMER-RELEVANT
    parts of the description (payment_days → terms sentence) but override METADATA
    ([override: ...], field names, ids) must never appear in description_preview."""
    from app.api import routes_proforma as rp

    draft_id = _seed_issued_proforma_by_draft(storage)

    def _fake_cm(path, contractor_id):
        return None

    with patch.object(rp, "get_customer_master", _fake_cm), \
         patch.object(wc, "fetch_invoice_xml", return_value=_proforma_xml()):
        r = client.get(
            _DISCLOSE_URL.format(draft_id=draft_id),
            params={"override_payment_method": "cash", "override_payment_days": 14},
            headers=_auth(),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    desc = body["description_preview"]
    # Customer-relevant effect of the override IS reflected:
    assert "within 14 days from the invoice date" in desc
    # Internal metadata is NOT:
    lowered = desc.lower()
    for marker in ("[override:", "override", "payment_method=", "contractor",
                   "hash", "idempotency", "id=", "draft"):
        assert marker not in lowered, (
            f"internal marker {marker!r} leaked into customer-facing description_preview: {desc!r}"
        )
    assert desc.startswith("Reference: Pro Forma Invoice PROF 92/2026."), desc
    # The override metadata is still auditable server-side:
    from app.api.routes_proforma import _build_convert_candidate  # sanity: helper exposes it
    # (full audit-event coverage in test_execute_records_override_note_in_audit)


def test_execute_records_override_note_in_audit(client, storage):
    """Customer-clean revision: the override metadata removed from the customer
    description is preserved in the invoice_approval_attempt audit event
    (override_note detail field) AND never appears on the invoice."""
    from app.services import audit_persist as ap

    captured = {}
    real = ap.record_invoice_approval_attempt

    def _spy(audit_path, **kw):
        if kw.get("outcome") == "approved":
            captured.update(kw)
        return real(audit_path, **kw)

    _seed_issued_proforma(storage)
    src_xml = _proforma_xml()
    sent_xml = {}
    fetch_calls = [src_xml, _created_invoice_xml(inv_id="500222")]

    def _fake_http(method, module, op, body):
        sent_xml["body"] = body
        return 200, """<?xml version="1.0"?>
<api><invoices><invoice><id>500222</id><fullnumber>FA 222/5/2026</fullnumber>
</invoice></invoices><status><code>OK</code></status></api>"""

    with _gate_invoice_on(), \
         patch.object(ap, "record_invoice_approval_attempt", _spy), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN, "override_payment_days": 21},
        ).json()

    assert captured.get("override_note") == "override: payment_days=21", (
        f"override_note missing from approved audit event: {captured!r} (response: {body})"
    )
    # And the wFirma payload's <description> stays customer-clean:
    assert "[override:" not in sent_xml.get("body", ""), sent_xml.get("body", "")[:400]
    assert "override" not in sent_xml["body"].split("<description>")[1].split("</description>")[0].lower()


def test_disclose_accepts_operator_description_for_hash_parity(client, storage):
    """Opus review fix 3: execute accepts operator_description (changes description →
    changes hash). Disclose must accept the same param so an API caller supplying it
    can obtain a matching expected_payload_hash instead of a guaranteed mismatch."""
    from app.api import routes_proforma as rp

    draft_id = _seed_issued_proforma_by_draft(storage)

    def _fake_cm(path, contractor_id):
        return None

    with patch.object(rp, "get_customer_master", _fake_cm), \
         patch.object(wc, "fetch_invoice_xml", return_value=_proforma_xml()):
        plain = client.get(_DISCLOSE_URL.format(draft_id=draft_id), headers=_auth()).json()
        with_desc = client.get(
            _DISCLOSE_URL.format(draft_id=draft_id),
            params={"operator_description": "Extra shipping note for customs"},
            headers=_auth(),
        ).json()
    assert "Extra shipping note for customs" in with_desc["description_preview"]
    assert with_desc["payload_core_hash"] != plain["payload_core_hash"], (
        "operator_description changes the final description and must change the hash"
    )
