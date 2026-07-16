"""
test_invoice_link_reconcile.py — R-2 split-brain conversion-link recovery.

Covers the known risk R-2 from the proforma-convert certification campaign:
in POST /to-invoice, if wFirma invoices/add succeeds but a later local step
fails, the link row is left 'pending' (mark_issued crash) or 'failed'
(verify-after-create failure) while a REAL wFirma invoice exists.

Standing rules preserved (pinned here): no retry, no duplicate create, never
delete the remote invoice. Recovery = read-only detection + operator-gated
LOCAL repair after a read-only re-fetch re-passes the identical
verify-after-create matrix.

Pins:
  Forward identity capture (POST /to-invoice step 6):
   1. verify-after-create failure leaves link 'failed' WITH invoice_id captured.
   2. mark_issued crash leaves link 'pending' WITH invoice_id captured.
  Detection (GET /proforma/invoice-links/split-brain — read-only):
   3. failed link with captured id → confirmed_split_brain, reconcilable.
   4. failed link with verify-after-create note but no id → confirmed_split_brain.
   5. pending link without id → suspected_split_brain.
   6. plain failed link (invoices/add rejected, no evidence) → excluded.
   7. issued link → excluded; proforma_id filter works.
  Reconcile (POST /proforma/invoice-links/{proforma_id}/reconcile):
   8. pending-with-id → repaired: link issued, draft converted, audit event.
   9. failed-with-id → repaired.
  10. remote mismatch (contractor) → REFUSED, local state untouched.
  11. remote invoice without proforma back-reference → REFUSED.
  12. operator-supplied id for a historical row (no captured id) → repaired
      with id_source=operator_supplied.
  13. gates: missing confirm / missing operator / issued link / id conflict /
      no id available → blocked, no state change.
  14. reconcile performs NO wFirma write (invoices/get only).
  Source-grep:
  15. _verify_created_invoice is the single shared check authority.
"""
from __future__ import annotations

import json
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
from app.services import proforma_service_charges_db as scdb


BATCH  = "BATCH_RECONCILE_TEST"
CLIENT = "ACME"
PID    = "467236963"            # wFirma proforma id
PNUM   = "PROF 92/2026"
IID    = "500001"               # wFirma final invoice id
INUM   = "FA 1/5/2026"
CONVERT_TOKEN   = "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"
RECONCILE_TOKEN = "YES_RECONCILE_INVOICE_LINK"


# ── wFirma XML fixtures (real response shapes — Lesson A) ────────────────────

def _proforma_xml(*, pid=PID, pnum=PNUM, contractor_id="9001",
                  currency="EUR", total="306.00") -> str:
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
      <series><id>15827088</id></series>
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


def _created_invoice_xml(*, inv_id=IID, inv_type="normal",
                         contractor_id="9001", currency="EUR",
                         total="306.00", line_count=1,
                         description=f"Dokument wystawiony do proformy {PNUM}",
                         ) -> str:
    lines = ""
    for _ in range(line_count):
        lines += """        <invoicecontent>
          <name>RING</name>
          <good><id>42</id></good>
          <unit>szt.</unit>
          <unit_count>1.0000</unit_count>
          <price>306.00</price>
          <vat_code><id>228</id></vat_code>
        </invoicecontent>
"""
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>{inv_id}</id>
      <type>{inv_type}</type>
      <fullnumber>{INUM}</fullnumber>
      <date>2026-06-08</date>
      <paymentmethod>transfer</paymentmethod>
      <paymentdate>2026-05-15</paymentdate>
      <currency>{currency}</currency>
      <total>{total}</total>
      <netto>{total}</netto>
      <description>{description}</description>
      <contractor><id>{contractor_id}</id></contractor>
      <invoicecontents>
{lines}      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


def _invoices_add_response(inv_id=IID, fullnumber=INUM) -> str:
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


# ── Fixtures ─────────────────────────────────────────────────────────────────

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


def _readiness_ready():
    """Neutralise the (orthogonal) step-2c convert readiness gate — this
    suite pins identity capture + reconcile, not readiness derivation."""
    from app.api import routes_proforma as rp
    return patch.object(
        rp, "_derive_draft_readiness",
        return_value={"ready": True, "blocking_reasons": [], "blockers": []},
    )


def _links_db(storage) -> Path:
    return storage / "proforma_links.db"


def _seed_issued_draft(storage, *, wfirma_id=PID, client_name=CLIENT):
    db = _links_db(storage)
    pildb.upsert_pending_draft(
        db, batch_id=BATCH, client_name=client_name,
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    pildb.mark_draft_issued(db, BATCH, client_name, wfirma_proforma_id=wfirma_id)


def _seed_link(storage, *, pid=PID, pnum=PNUM, status="pending",
               invoice_id: str = "", notes: str = "") -> None:
    db = _links_db(storage)
    pildb.create_pending_link(db, pildb.ProformaInvoiceLink(
        proforma_id=pid, proforma_number=pnum, converted_at="",
        operator="amit", source_total=Decimal("306.00"),
        currency="EUR", status="pending",
    ))
    if invoice_id:
        pildb.record_invoice_identity(db, pid, invoice_id=invoice_id,
                                      invoice_number=INUM)
    if status == "failed":
        pildb.mark_failed(db, pid, notes=notes or "some failure")


def _seed_audit(storage):
    audit_dir = storage / "outputs" / BATCH
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "audit.json").write_text(
        json.dumps({"batch_id": BATCH, "timeline": []}), encoding="utf-8",
    )


_EXECUTE_URL   = f"/api/v1/proforma/to-invoice/{BATCH}/{CLIENT}"
_DETECT_URL    = "/api/v1/proforma/invoice-links/split-brain"
_RECONCILE_URL = "/api/v1/proforma/invoice-links/{pid}/reconcile"


def _convert(client):
    return client.post(
        _EXECUTE_URL,
        headers={**_auth(), "X-Operator": "amit"},
        json={"confirm": CONVERT_TOKEN},
    ).json()


def _reconcile(client, *, pid=PID, confirm=RECONCILE_TOKEN,
               operator="amit", invoice_id: str = ""):
    headers = dict(_auth())
    if operator:
        headers["X-Operator"] = operator
    body = {"confirm": confirm}
    if invoice_id:
        body["wfirma_invoice_id"] = invoice_id
    return client.post(_RECONCILE_URL.format(pid=pid),
                       headers=headers, json=body).json()


# ── 1. Forward capture: verify-after-create failure keeps the id ─────────────

def test_verify_failure_captures_invoice_id_on_failed_link(client, storage):
    _seed_issued_draft(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(line_count=0),   # verify fails: lines dropped
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), _readiness_ready(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        body = _convert(client)

    assert body["ok"] is False
    assert body["verify_after_create_failed"] is True

    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link is not None
    assert link.status == "failed"
    # R-2 forward fix: the remote invoice id is now durably captured.
    assert link.invoice_id == IID
    assert "verify-after-create" in (link.notes or "").lower()


# ── 2. Forward capture: mark_issued crash leaves pending WITH the id ─────────

def test_mark_issued_crash_leaves_pending_link_with_captured_id(client, storage):
    _seed_issued_draft(storage)
    fetch_calls = [
        _proforma_xml(),
        _created_invoice_xml(),               # verify passes
    ]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), _readiness_ready(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http), \
         patch.object(pildb, "mark_issued",
                      side_effect=RuntimeError("db locked")):
        body = _convert(client)

    # The remote invoice was created and verified — the response reports it.
    assert body["ok"] is True
    assert body["wfirma_invoice_id"] == IID

    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link is not None
    assert link.status == "pending"           # split-brain: promote crashed
    assert link.invoice_id == IID             # …but the id survived (R-2)


# ── 3–7. Detection report ─────────────────────────────────────────────────────

def test_detection_failed_with_captured_id_is_confirmed(client, storage):
    _seed_link(storage, status="failed", invoice_id=IID,
               notes="verify-after-create FAILED: RuntimeError: total mismatch")
    body = client.get(_DETECT_URL, headers=_auth()).json()
    assert body["ok"] is True
    assert body["count"] == 1
    e = body["links"][0]
    assert e["proforma_id"] == PID
    assert e["classification"] == "confirmed_split_brain"
    assert e["captured_invoice_id"] == IID
    assert e["reconcilable_without_input"] is True


def test_detection_failed_with_vac_note_but_no_id_is_confirmed(client, storage):
    _seed_link(storage, status="failed",
               notes="verify-after-create FAILED: RuntimeError: line count mismatch")
    body = client.get(_DETECT_URL, headers=_auth()).json()
    assert body["count"] == 1
    e = body["links"][0]
    assert e["classification"] == "confirmed_split_brain"
    assert e["captured_invoice_id"] == ""
    assert e["reconcilable_without_input"] is False


def test_detection_pending_without_id_is_suspected(client, storage):
    _seed_link(storage, status="pending")
    body = client.get(_DETECT_URL, headers=_auth()).json()
    assert body["count"] == 1
    assert body["links"][0]["classification"] == "suspected_split_brain"


def test_detection_excludes_plain_add_failure(client, storage):
    _seed_link(storage, status="failed",
               notes="RuntimeError: invoices/add HTTP 500: internal error")
    body = client.get(_DETECT_URL, headers=_auth()).json()
    assert body["count"] == 0


def test_detection_excludes_issued_and_filter_works(client, storage):
    # issued link
    _seed_link(storage, pid="111", pnum="PROF 1/2026", status="pending")
    pildb.record_invoice_identity(_links_db(storage), "111", invoice_id="900")
    pildb.mark_issued(_links_db(storage), "111", invoice_id="900",
                      invoice_number="FA 9/2026",
                      invoice_total=Decimal("306.00"))
    # split-brain link
    _seed_link(storage, pid="222", pnum="PROF 2/2026",
               status="failed", invoice_id="901",
               notes="verify-after-create FAILED: x")
    body = client.get(_DETECT_URL, headers=_auth()).json()
    assert body["count"] == 1
    assert body["links"][0]["proforma_id"] == "222"
    # proforma_id filter
    body = client.get(_DETECT_URL + "?proforma_id=111", headers=_auth()).json()
    assert body["count"] == 0
    body = client.get(_DETECT_URL + "?proforma_id=222", headers=_auth()).json()
    assert body["count"] == 1


def test_detection_includes_draft_context(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    body = client.get(_DETECT_URL, headers=_auth()).json()
    e = body["links"][0]
    assert e["batch_id"] == BATCH
    assert e["client_name"] == CLIENT
    assert e["draft_id"] is not None


# ── 8. Reconcile: pending-with-id → repaired ─────────────────────────────────

def test_reconcile_pending_with_id_repairs_local_state(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    _seed_audit(storage)

    fetch_calls = [_proforma_xml(), _created_invoice_xml()]
    with patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client)

    assert body["ok"] is True, body
    assert body["status"] == "reconciled"
    assert body["wfirma_invoice_id"] == IID
    assert body["previous_status"] == "pending"
    assert body["id_source"] == "link_row"
    assert body["wfirma_write"] is False

    # Link promoted to issued
    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link.status == "issued"
    assert link.invoice_id == IID
    assert link.invoice_number == INUM
    assert "reconciled by amit" in (link.notes or "")

    # Draft carries the invoice identity (Convert hidden after reload)
    draft = pildb.get_draft(_links_db(storage), BATCH, CLIENT)
    assert draft.wfirma_invoice_id == IID
    assert draft.draft_state == "converted"

    # Audit event appended
    audit = json.loads((storage / "outputs" / BATCH / "audit.json")
                       .read_text(encoding="utf-8"))
    events = [e for e in audit.get("timeline", [])
              if e.get("event") == "invoice_link_reconciled"]
    assert len(events) == 1
    d = events[0].get("detail", {})
    assert d["wfirma_proforma_id"] == PID
    assert d["wfirma_invoice_id"] == IID
    assert d["operator"] == "amit"
    assert d["previous_status"] == "pending"
    assert d["wfirma_write"] is False


# ── 9. Reconcile: failed-with-id → repaired ──────────────────────────────────

def test_reconcile_failed_with_id_repairs_local_state(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="failed", invoice_id=IID,
               notes="verify-after-create FAILED: RuntimeError: transient")
    _seed_audit(storage)

    fetch_calls = [_proforma_xml(), _created_invoice_xml()]
    with patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client)

    assert body["ok"] is True, body
    assert body["previous_status"] == "failed"
    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link.status == "issued"


# ── 10. Reconcile: remote mismatch → REFUSED, no state change ────────────────

def test_reconcile_refuses_on_remote_contractor_mismatch(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="failed", invoice_id=IID,
               notes="verify-after-create FAILED: RuntimeError: x")

    fetch_calls = [_proforma_xml(),
                   _created_invoice_xml(contractor_id="9999")]
    with patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client)

    assert body["ok"] is False
    assert body["status"] == "refused"
    assert body["reconcile_refused"] is True
    assert "contractor mismatch" in body["error"]

    # LOCAL STATE UNTOUCHED
    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link.status == "failed"
    draft = pildb.get_draft(_links_db(storage), BATCH, CLIENT)
    assert not (draft.wfirma_invoice_id or "")
    assert draft.draft_state != "converted"


def test_reconcile_refuses_on_remote_total_mismatch(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)

    fetch_calls = [_proforma_xml(), _created_invoice_xml(total="999.00")]
    with patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client)

    assert body["ok"] is False
    assert body["status"] == "refused"
    assert "total mismatch" in body["error"]
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"


# ── 11. Reconcile: missing back-reference → REFUSED ──────────────────────────

def test_reconcile_refuses_when_backreference_missing(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="failed", invoice_id=IID,
               notes="verify-after-create FAILED: RuntimeError: x")

    fetch_calls = [_proforma_xml(),
                   _created_invoice_xml(description="Unrelated manual invoice")]
    with patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client)

    assert body["ok"] is False
    assert body["status"] == "refused"
    assert "does not back-reference" in body["error"]
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "failed"


# ── 12. Reconcile: operator-supplied id (historical row, no capture) ─────────

def test_reconcile_operator_supplied_id_repairs_historical_row(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="failed",
               notes="verify-after-create FAILED: RuntimeError: historical")
    _seed_audit(storage)

    fetch_calls = [_proforma_xml(), _created_invoice_xml()]
    with patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client, invoice_id=IID)

    assert body["ok"] is True, body
    assert body["id_source"] == "operator_supplied"
    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link.status == "issued"
    assert link.invoice_id == IID


# ── 13. Gates ─────────────────────────────────────────────────────────────────

def test_reconcile_blocked_without_confirm_token(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    body = _reconcile(client, confirm="yes please")
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("confirm token" in r for r in body["blocking_reasons"])
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"


def test_reconcile_blocked_without_operator(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    body = _reconcile(client, operator="")
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("operator attribution" in r for r in body["blocking_reasons"])


def test_reconcile_blocked_when_link_already_issued(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    pildb.mark_issued(_links_db(storage), PID, invoice_id=IID,
                      invoice_number=INUM, invoice_total=Decimal("306.00"))
    body = _reconcile(client)
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("already 'issued'" in r for r in body["blocking_reasons"])


def test_reconcile_blocked_on_invoice_id_conflict(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="failed", invoice_id=IID,
               notes="verify-after-create FAILED: x")
    body = _reconcile(client, invoice_id="999999")
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("conflict" in r for r in body["blocking_reasons"])
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "failed"


def test_reconcile_blocked_when_no_id_available(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending")
    body = _reconcile(client)
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("no wfirma_invoice_id available" in r
               for r in body["blocking_reasons"])


def test_reconcile_blocked_when_no_link_row(client, storage):
    _seed_issued_draft(storage)
    body = _reconcile(client)
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("no conversion link row" in r for r in body["blocking_reasons"])


# ── 14. Reconcile performs NO wFirma write ───────────────────────────────────

def test_reconcile_never_calls_wfirma_write(client, storage):
    """fetch_invoice_xml (invoices/get) is the ONLY wFirma access. Any call
    reaching _http_request (invoices/add etc.) fails the test."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    _seed_audit(storage)

    def _no_write(*a, **k):
        raise AssertionError(f"unexpected wFirma HTTP call: {a[:3]}")

    fetch_calls = [_proforma_xml(), _created_invoice_xml()]
    with patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_no_write):
        body = _reconcile(client)

    assert body["ok"] is True, body
    assert body["wfirma_write"] is False


# ── 15. Source-grep: shared verify authority + capture wiring ────────────────

def _routes_src() -> str:
    routes = (Path(__file__).resolve().parent.parent
              / "app" / "api" / "routes_proforma.py")
    return routes.read_text(encoding="utf-8")


def test_source_grep_shared_verify_authority():
    src = _routes_src()
    # Single shared check set…
    assert "def _verify_created_invoice" in src
    # …called by BOTH the convert route and the reconcile route.
    assert src.count("_verify_created_invoice(plan, verify_xml)") >= 2


def test_source_grep_identity_capture_before_verify():
    src = _routes_src()
    assert "record_invoice_identity" in src
    # Capture happens in routes; the db helper lives in the link-db authority.
    dbsrc = (Path(__file__).resolve().parent.parent
             / "app" / "services" / "proforma_invoice_link_db.py"
             ).read_text(encoding="utf-8")
    assert "def record_invoice_identity" in dbsrc


def test_source_grep_reconcile_has_no_invoices_add():
    """The reconcile + detection block must never POST invoices/add — the
    standing R-2 rules are no retry and no duplicate create."""
    src = _routes_src()
    start = src.index("R-2 split-brain conversion-link recovery")
    end   = src.index("Phase 9 — Payload disclosure endpoints")
    block = src[start:end]
    assert "invoices" not in block or '"add"' not in block
    assert "_http_request" not in block
    assert "delete_invoice" not in block
