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
    # Source proforma carries Odbiorca id 190263843.
    src_xml = _proforma_xml(receiver_id="190263843")
    # fetch_invoice_xml called twice: 1st=source proforma, 2nd=verify-after-create
    fetch_calls = [
        src_xml,
        _created_invoice_xml(inv_id="500001", receiver_id="190263843"),
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
                          ok=True, contractor_id="190263843",
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
    assert body["contractor_receiver_id"] == "190263843"
    # The actual XML posted to wFirma carries the receiver block.
    assert captured["method"] == "POST"
    assert captured["module"] == "invoices"
    assert captured["op"]     == "add"
    assert "<contractor_receiver><id>190263843</id></contractor_receiver>" \
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
    fail = wc.ContractorFetchResult(ok=False, contractor_id="190263843",
                                      error="contractor '190263843' not found")
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      return_value=_proforma_xml(receiver_id="190263843")), \
         patch.object(wc, "fetch_contractor_by_id", return_value=fail), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError(
                          "must not POST when preflight fails")):
        body = client.post(
            _EXECUTE_URL.format(batch=BATCH, client=CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": CONFIRM_TOKEN}).json()
    assert body["status"] == "blocked"
    assert any("190263843" in r and "not found in wFirma" in r
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
