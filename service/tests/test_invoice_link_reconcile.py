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
  13. gates: missing confirm / missing operator / id conflict /
      no id available → blocked, no state change. An issued link is NOT a
      gate anymore — it takes the draft-projection repair branch (2026-07-17
      consolidation; full coverage in
      test_convert_persist_scope_and_reconcile.py).
  14. reconcile performs NO wFirma write (invoices/get only).
  Source-grep:
  15. _verify_created_invoice is the single shared check authority.
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
               operator="amit", invoice_id: str = "",
               invoice_number: str = ""):
    headers = dict(_auth())
    if operator:
        headers["X-Operator"] = operator
    body = {"confirm": confirm}
    if invoice_id:
        body["wfirma_invoice_id"] = invoice_id
    if invoice_number:
        body["wfirma_invoice_number"] = invoice_number
    return client.post(_RECONCILE_URL.format(pid=pid),
                       headers=headers, json=body).json()


def _invoices_find_xml(*rows) -> str:
    """Real ``invoices/find`` collection response shape (Lesson A).

    rows: (invoice_id, fullnumber) tuples.
    """
    nodes = ""
    for inv_id, fullnumber in rows:
        nodes += f"""    <invoice>
      <id>{inv_id}</id>
      <fullnumber>{fullnumber}</fullnumber>
      <type>normal</type>
    </invoice>
"""
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
{nodes}  </invoices>
  <status><code>OK</code></status>
</api>"""


def _find_returns(*rows):
    """Patch target for the read-only invoices/find transport."""
    return patch.object(wc, "_http_request",
                        return_value=(200, _invoices_find_xml(*rows)))


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


def test_reconcile_issued_link_repairs_stale_draft_projection(client, storage):
    """Integration consolidation 2026-07-17: an 'issued' link no longer
    blocks — it takes the draft-projection branch (draft 67/52 incident
    class): local link→draft copy, NO wFirma call, then noop when healthy."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    pildb.mark_issued(_links_db(storage), PID, invoice_id=IID,
                      invoice_number=INUM, invoice_total=Decimal("306.00"))

    def _no_wfirma(*a, **k):
        raise AssertionError("issued-branch repair must not call wFirma")

    with patch.object(wc, "fetch_invoice_xml", side_effect=_no_wfirma), \
         patch.object(wc, "_http_request", side_effect=_no_wfirma):
        body = _reconcile(client)
    assert body["ok"] is True, body
    assert body["status"] == "reconciled"
    assert body["mode"] == "draft_projection_repair"
    assert body["wfirma_write"] is False
    assert body["wfirma_invoice_id"] == IID

    # Healthy projection now → second call is a noop
    body2 = _reconcile(client)
    assert body2["ok"] is True
    assert body2["status"] == "noop"


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


# ── 16. Consolidation mitigations (2026-07-17 GATE-1 review) ──────────────────

def test_execute_reports_draft_persisted_false_when_persist_fails(client, storage):
    """Forward path step 7b: mark_issued succeeds but persist_invoice_to_draft
    raises — the response must disclose draft_persisted=False (behavioral
    counterpart of source-pin S3)."""
    import sqlite3 as _sq
    _seed_issued_draft(storage)
    fetch_calls = [_proforma_xml(), _created_invoice_xml()]

    def _fake_http(method, module, op, body):
        return 200, _invoices_add_response()

    with _gate_invoice_on(), _readiness_ready(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch.object(wc, "_http_request", side_effect=_fake_http), \
         patch("app.services.conversion_persistence.persist_invoice_to_draft",
               side_effect=_sq.OperationalError("database is locked")):
        body = _convert(client)

    assert body["ok"] is True, body
    assert body["draft_persisted"] is False
    # Link is issued; the canonical reconcile route can complete the repair.
    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link.status == "issued"


def test_split_brain_repair_discloses_draft_persist_failure(client, storage):
    """Split-brain branch: mark_issued lands but the draft projection write
    fails — the 'reconciled' response must carry draft_persisted=False + an
    advisory, and a SECOND call (issued branch, no wFirma) completes it."""
    import sqlite3 as _sq
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    _seed_audit(storage)

    fetch_calls = [_proforma_xml(), _created_invoice_xml()]
    with patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls), \
         patch("app.services.conversion_persistence.persist_invoice_to_draft",
               side_effect=_sq.OperationalError("database is locked")):
        body = _reconcile(client)

    assert body["ok"] is True, body
    assert body["status"] == "reconciled"
    assert body["draft_persisted"] is False
    assert "re-run reconcile" in (body["advisory"] or "")
    # Link repaired, draft still stale
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "issued"
    draft = pildb.get_draft(_links_db(storage), BATCH, CLIENT)
    assert draft.wfirma_invoice_id in (None, "")

    # Second call: issued branch, local-only, completes the projection.
    def _no_wfirma(*a, **k):
        raise AssertionError("issued-branch repair must not call wFirma")
    with patch.object(wc, "fetch_invoice_xml", side_effect=_no_wfirma):
        body2 = _reconcile(client)
    assert body2["status"] == "reconciled"
    assert body2["mode"] == "draft_projection_repair"
    draft = pildb.get_draft(_links_db(storage), BATCH, CLIENT)
    assert draft.wfirma_invoice_id == IID
    assert draft.draft_state == "converted"


def test_reconcile_second_call_after_split_brain_repair_is_noop(client, storage):
    """End-to-end idempotency across branches: split-brain repair, then a
    second call routes the now-issued healthy link to the issued branch →
    noop (no wFirma call)."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    _seed_audit(storage)

    fetch_calls = [_proforma_xml(), _created_invoice_xml()]
    with patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client)
    assert body["status"] == "reconciled"

    def _no_wfirma(*a, **k):
        raise AssertionError("noop path must not call wFirma")
    with patch.object(wc, "fetch_invoice_xml", side_effect=_no_wfirma):
        body2 = _reconcile(client)
    assert body2["ok"] is True
    assert body2["status"] == "noop"


def test_detection_excludes_healthy_issued_projection(client, storage):
    """An issued link whose DRAFT already mirrors the invoice identity in
    state 'converted' is healthy — excluded from the split-brain report."""
    from app.services.conversion_persistence import persist_invoice_to_draft
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    pildb.mark_issued(_links_db(storage), PID, invoice_id=IID,
                      invoice_number=INUM, invoice_total=Decimal("306.00"))
    draft = pildb.get_draft(_links_db(storage), BATCH, CLIENT)
    persist_invoice_to_draft(
        db_path=_links_db(storage), draft_id=int(draft.id),
        wfirma_invoice_id=IID, wfirma_invoice_number=INUM,
    )
    body = client.get(_DETECT_URL, headers=_auth()).json()
    assert body["count"] == 0, body
    assert body["truncated"] is False


def test_reconcile_rejects_non_numeric_supplied_id(client, storage):
    """Operator-supplied wfirma_invoice_id flows into the invoices/get URL —
    anything non-numeric is rejected before any wFirma call."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending")   # no captured id

    def _no_wfirma(*a, **k):
        raise AssertionError("validation must fire before any wFirma call")
    with patch.object(wc, "fetch_invoice_xml", side_effect=_no_wfirma):
        body = _reconcile(client, invoice_id="999/../../contractors/find")
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("not a numeric" in r for r in body["blocking_reasons"])


def test_split_brain_blocked_on_pre_existing_draft_conflict(client, storage):
    """Conflict pre-check: a draft already carrying a DIFFERENT invoice id
    must block the split-brain repair BEFORE any wFirma fetch or link write."""
    from app.services.conversion_persistence import persist_invoice_to_draft
    _seed_issued_draft(storage)
    _seed_link(storage, status="failed", invoice_id=IID,
               notes="verify-after-create FAILED: x")
    draft = pildb.get_draft(_links_db(storage), BATCH, CLIENT)
    persist_invoice_to_draft(
        db_path=_links_db(storage), draft_id=int(draft.id),
        wfirma_invoice_id="777777", wfirma_invoice_number="FA 7/2026",
    )

    def _no_wfirma(*a, **k):
        raise AssertionError("conflict pre-check must fire before wFirma")
    with patch.object(wc, "fetch_invoice_xml", side_effect=_no_wfirma):
        body = _reconcile(client)
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("data conflict" in r for r in body["blocking_reasons"])
    # Link untouched
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "failed"


def test_reconcile_unrecognized_link_status_blocked(client, storage):
    """A corrupted/future link status (neither pending/failed/issued) is
    blocked, never routed to either repair branch."""
    import sqlite3 as _sq
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    conn = _sq.connect(str(_links_db(storage)))
    conn.execute("UPDATE proforma_invoice_links SET status='archived' "
                 "WHERE proforma_id=?", (PID,))
    conn.commit()
    conn.close()
    body = _reconcile(client)
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("not reconcilable" in r for r in body["blocking_reasons"])


# ── 4. Duplicate-guard truthfulness ──────────────────────────────────────────
#
# Origin (2026-07-17, draft 64 / proforma_id 489002275): the convert modal opened
# on a proforma that already had a link row, the operator confirmed the
# irreversible action, and the server refused. The refusal was right; the message
# just did not say WHICH state blocked, so 'already invoiced' and 'an attempt is
# stranded' — which need opposite responses — looked identical to the operator.

@pytest.mark.parametrize("status", ["pending", "failed", "issued"])
def test_link_already_exists_blocks_on_every_status(storage, status):
    """REGRESSION PIN (Lesson N true-blocker #5 — duplicate document risk).

    'pending' and 'failed' must block exactly as hard as 'issued'. After an
    ambiguous wFirma failure we cannot know whether an invoice was created, so a
    retry could double-issue one. Narrowing this guard to 'issued' would be a
    fiscal regression: the repair for a stranded row is reconcile, never a retry.
    """
    from app.api import routes_proforma as rp
    _seed_link(storage, status="failed" if status == "failed" else "pending")
    if status == "issued":
        pildb.mark_issued(_links_db(storage), PID, invoice_id=IID,
                          invoice_number=INUM, invoice_total=Decimal("306.00"))
    with patch.object(settings, "storage_root", storage):
        assert rp._link_status(PID) == status
        assert rp._link_already_exists(PID) is True, (
            f"status={status!r} must block a second conversion"
        )


def test_link_status_is_none_when_no_row_exists(storage):
    """No row = convertible. The guard must not block a first conversion."""
    from app.api import routes_proforma as rp
    with patch.object(settings, "storage_root", storage):
        assert rp._link_status(PID) is None
        assert rp._link_already_exists(PID) is False


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_duplicate_refusal_names_the_link_status(client, storage, status):
    """The operator must be able to tell 'already invoiced' from 'stranded'."""
    _seed_issued_draft(storage)
    _seed_link(storage, status=status)
    with _gate_invoice_on(), _readiness_ready():
        body = _convert(client)
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert body["link_status"] == status
    assert any(f"status={status!r}" in r for r in body["blocking_reasons"]), (
        f"refusal must name the blocking status; got {body['blocking_reasons']}"
    )


# ── 5. Write-ahead failure durability ────────────────────────────────────────

def test_failed_convert_reports_when_link_state_could_not_be_recorded(client, storage):
    """The link row is written BEFORE the wFirma call (write-ahead reservation).
    If invoices/add fails AND mark_failed cannot land, the row is stranded in
    'pending' — so the API must not answer a clean 'failed', which would assert a
    state the database does not hold. It must disclose the strand and name the
    repair."""
    _seed_issued_draft(storage)
    _seed_audit(storage)
    with _gate_invoice_on(), _readiness_ready(), \
         patch.object(wc, "fetch_invoice_xml", return_value=_proforma_xml()), \
         patch.object(wc, "_http_request", side_effect=RuntimeError("wFirma 500")), \
         patch.object(pildb, "mark_failed", side_effect=RuntimeError("db locked")):
        body = _convert(client)

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body.get("link_state_unrecorded") is True, (
        "a swallowed mark_failed leaves the row in 'pending' while the response "
        "claims 'failed' — the strand must be disclosed, not hidden"
    )
    assert any("reconcile" in r.lower() for r in body["blocking_reasons"])
    # The row must SURVIVE: wFirma may hold a real invoice, and this row is the
    # duplicate guard. Deleting it to 'unblock' the operator is how you
    # double-issue an invoice.
    assert pildb.get_link_by_proforma(_links_db(storage), PID) is not None


# ── Reconcile by invoice NUMBER (operator recovery input) ────────────────────
#
# Operator requirement (2026-07-17): the recovery action accepts "wFirma
# invoice number or immutable wFirma invoice ID". A number is NEVER evidence
# on its own — it only selects WHICH invoice the IDENTICAL verify matrix runs
# against. Anything short of a unique, verified match changes nothing locally.

def test_reconcile_by_number_resolves_uniquely_and_repairs(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id="")   # no captured id
    _seed_audit(storage)

    fetch_calls = [_proforma_xml(), _created_invoice_xml()]
    with _find_returns((IID, INUM)) as http, \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client, invoice_number=INUM)

    assert body["ok"] is True, body
    assert body["status"] == "reconciled"
    assert body["wfirma_invoice_id"] == IID
    assert body["id_source"] == "operator_supplied_number"
    assert body["wfirma_write"] is False

    # Resolution is READ-ONLY: invoices/find is the only module/action it may
    # touch — never add/edit/delete.
    assert http.call_args_list, "expected an invoices/find lookup"
    for call in http.call_args_list:
        assert call.args[0] == "GET"
        assert call.args[1] == "invoices"
        assert call.args[2] == "find"

    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link.status == "issued"
    assert link.invoice_id == IID

    draft = pildb.get_draft(_links_db(storage), BATCH, CLIENT)
    assert draft.wfirma_invoice_id == IID
    assert draft.draft_state == "converted"

    # Audit records HOW the id was obtained — a number-resolved repair stays
    # distinguishable from a link-row one forever after.
    audit = json.loads((storage / "outputs" / BATCH / "audit.json")
                       .read_text(encoding="utf-8"))
    events = [e for e in audit.get("timeline", [])
              if e.get("event") == "invoice_link_reconciled"]
    assert len(events) == 1
    assert events[0]["detail"]["id_source"] == "operator_supplied_number"
    assert events[0]["detail"]["wfirma_write"] is False


def test_reconcile_by_number_matching_nothing_is_refused(client, storage):
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id="")
    _seed_audit(storage)

    def _no_fetch(*a, **k):
        raise AssertionError("must not fetch when the number resolves to nothing")

    with _find_returns(), patch.object(wc, "fetch_invoice_xml",
                                       side_effect=_no_fetch):
        body = _reconcile(client, invoice_number="WDT 999/2099")

    assert body["ok"] is False
    assert body["status"] == "refused"
    assert body["reconcile_refused"] is True
    assert "no wFirma invoice carries number" in body["error"]

    # NO local change.
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"
    draft = pildb.get_draft(_links_db(storage), BATCH, CLIENT)
    assert not (draft.wfirma_invoice_id or "")
    audit = json.loads((storage / "outputs" / BATCH / "audit.json")
                       .read_text(encoding="utf-8"))
    assert not [e for e in audit.get("timeline", [])
                if e.get("event") == "invoice_link_reconciled"]


def test_reconcile_by_ambiguous_number_is_refused(client, storage):
    """A number can repeat across series/years. Two matches -> refuse and
    name both candidates; never silently pick the first."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id="")
    _seed_audit(storage)

    def _no_fetch(*a, **k):
        raise AssertionError("must not fetch while the number is ambiguous")

    with _find_returns((IID, INUM), ("500002", INUM)), \
         patch.object(wc, "fetch_invoice_xml", side_effect=_no_fetch):
        body = _reconcile(client, invoice_number=INUM)

    assert body["ok"] is False
    assert body["status"] == "refused"
    assert body["reconcile_refused"] is True
    assert "ambiguous" in body["error"]
    assert body["candidate_ids"] == [IID, "500002"]

    # NO local change.
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"
    assert not (pildb.get_draft(_links_db(storage), BATCH, CLIENT)
                .wfirma_invoice_id or "")


def test_reconcile_by_number_still_runs_the_verify_matrix(client, storage):
    """A number resolving uniquely is NOT sufficient — the resolved invoice
    faces the identical matrix, and a contractor mismatch refuses it."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id="")
    _seed_audit(storage)

    fetch_calls = [_proforma_xml(),
                   _created_invoice_xml(contractor_id="9999")]  # wrong party
    with _find_returns((IID, INUM)), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client, invoice_number=INUM)

    assert body["ok"] is False
    assert body["status"] == "refused"
    assert body["reconcile_refused"] is True
    assert "contractor mismatch" in body["error"]

    # NO local change — never marked Invoiced off an unverified number.
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"
    assert not (pildb.get_draft(_links_db(storage), BATCH, CLIENT)
                .wfirma_invoice_id or "")


def test_reconcile_by_number_ignores_silently_unfiltered_collection(client, storage):
    """wFirma silently ignores filter shapes it does not support and returns
    an unfiltered collection (the trap that made fetch_invoice_xml abandon
    find-by-id). Resolution re-checks fullnumber Python-side, so an ignored
    filter degrades to 'not found' — never to a wrong match."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id="")
    _seed_audit(storage)

    def _no_fetch(*a, **k):
        raise AssertionError("unrelated rows must not resolve to an id")

    # Filter ignored: wFirma echoes back unrelated invoices, none of which
    # carry the requested number.
    with _find_returns(("111", "FV 1/2026"), ("222", "FV 2/2026")), \
         patch.object(wc, "fetch_invoice_xml", side_effect=_no_fetch):
        body = _reconcile(client, invoice_number="WDT 144/2026")

    assert body["ok"] is False
    assert body["status"] == "refused"
    assert "no wFirma invoice carries number" in body["error"]
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"


def test_reconcile_rejects_id_and_number_together(client, storage):
    """Two ways to name one invoice — sending both is ambiguous intent."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id="")

    def _no_wfirma(*a, **k):
        raise AssertionError("must not call wFirma on a malformed request")

    with patch.object(wc, "_http_request", side_effect=_no_wfirma), \
         patch.object(wc, "fetch_invoice_xml", side_effect=_no_wfirma):
        body = _reconcile(client, invoice_id=IID, invoice_number=INUM)

    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("both" in r for r in body["blocking_reasons"])
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"


def test_reconcile_number_resolving_against_captured_id_conflicts(client, storage):
    """Link row already carries an id and the operator's number resolves to a
    DIFFERENT invoice -> conflict, refuse before any verification."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)   # captured

    def _no_fetch(*a, **k):
        raise AssertionError("conflict must fire before the verify fetch")

    with _find_returns(("500002", "WDT 7/2026")), \
         patch.object(wc, "fetch_invoice_xml", side_effect=_no_fetch):
        body = _reconcile(client, invoice_number="WDT 7/2026")

    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("invoice id conflict" in r for r in body["blocking_reasons"])
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"


def test_find_invoices_by_fullnumber_is_read_only_and_exact():
    """Unit pin on the resolver: exact Python-side match, read-only."""
    resp = (200, _invoices_find_xml(("1", "WDT 144/2026"),
                                    ("2", "WDT 1440/2026"),    # near-miss
                                    ("3", "wdt  144/2026")))   # case/space variant
    with patch.object(wc, "_http_request", return_value=resp) as http:
        out = wc.find_invoices_by_fullnumber("WDT 144/2026")

    # Near-miss excluded; case/whitespace variant included.
    assert [m["id"] for m in out] == ["1", "3"]
    assert http.call_args.args[0] == "GET"
    assert http.call_args.args[1] == "invoices"
    assert http.call_args.args[2] == "find"


def test_find_invoices_by_fullnumber_requires_a_number():
    with pytest.raises(ValueError):
        wc.find_invoices_by_fullnumber("   ")


def test_reconcile_by_number_refuses_when_backreference_missing(client, storage):
    """The number path gets the back-reference guard too: an invoice that does
    not name the source proforma in its description is not the invoice this
    flow created, even if the number resolved cleanly."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id="")
    _seed_audit(storage)

    fetch_calls = [_proforma_xml(),
                   _created_invoice_xml(description="Unrelated manual invoice")]
    with _find_returns((IID, INUM)), \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client, invoice_number=INUM)

    assert body["ok"] is False
    assert body["status"] == "refused"
    assert "does not back-reference" in body["error"]
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"


def test_reconcile_pure_digit_number_still_routes_through_resolution(client, storage):
    """A wFirma series template of just [numer] can yield an all-digit
    fullnumber. Sent in the NUMBER field it must still be resolved via
    invoices/find — never treated as an immutable id."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id="")
    _seed_audit(storage)

    fetch_calls = [_proforma_xml(), _created_invoice_xml()]
    with _find_returns((IID, "144")) as http, \
         patch.object(wc, "fetch_invoice_xml", side_effect=fetch_calls):
        body = _reconcile(client, invoice_number="144")

    assert body["ok"] is True, body
    assert body["id_source"] == "operator_supplied_number"
    # Resolved to the real id — NOT used as the id "144" verbatim.
    assert body["wfirma_invoice_id"] == IID
    assert http.call_args.args[2] == "find"


def test_reconcile_refuses_number_resolving_to_non_numeric_id(client, storage):
    """A malformed invoices/find response must never build an invoices/get URL
    out of a non-numeric id — the resolved id earns the same numeric guard as
    an operator-supplied one (path-separator injection defence)."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id="")

    def _no_fetch(*a, **k):
        raise AssertionError("must not fetch with a non-numeric resolved id")

    with _find_returns(("999/../../contractors/find", INUM)), \
         patch.object(wc, "fetch_invoice_xml", side_effect=_no_fetch):
        body = _reconcile(client, invoice_number=INUM)

    assert body["ok"] is False
    assert body["status"] == "refused"
    assert "non-numeric" in body["error"]
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"


def test_reconcile_rejects_id_and_number_together_on_issued_link(client, storage):
    """Request-shape guards run before the status branch, so the issued branch
    rejects a malformed request instead of silently ignoring the number."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    pildb.mark_issued(_links_db(storage), PID, invoice_id=IID,
                      invoice_number=INUM, invoice_total=Decimal("306.00"),
                      notes="issued")

    body = _reconcile(client, invoice_id=IID, invoice_number=INUM)
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("both" in r for r in body["blocking_reasons"])


# ── 6. Terminal draft states are never resurrected by a repair ───────────────
#
# Operator ruling 2026-07-17 (GATE-4 salvage, surfaced by reviewer-challenge
# on the reconcile-by-number slice): when a booked wFirma invoice exists but
# the local draft was cancelled, the CANCELLATION WINS. Reconcile refuses and
# escalates rather than silently reversing an operator's decision.
#
# Why this needs a route guard: conversion_persistence.persist_invoice_to_draft
# issues an unconditional ``UPDATE ... SET draft_state='converted'`` whose only
# WHERE clause is ``id=?``. Neither reconcile branch used to read draft_state
# before calling it, so a good-faith Repair click on a split-brain report would
# flip 'cancelled' -> 'converted'; proforma-list.jsx filters out 'cancelled'
# but NOT 'converted', so the draft would re-appear as a live invoiced document.

def _force_terminal_draft_state(storage, state: str) -> int:
    """Put the seeded draft into a terminal lifecycle state while it still
    carries wfirma_proforma_id, and return its id.

    Direct SQL is deliberate — no app writer can produce this shape today:
    ``cancel_draft`` refuses a 'posted' draft (CANCELLABLE_STATES is
    draft/editing/approved/post_failed) and ``migrate_draft_to_canonical_name``
    supersedes only EDITABLE_STATES rows, which never carry a proforma id. The
    guard under test is therefore a defence-in-depth invariant on the write,
    not a repair of a live-reachable path.

    The legacy ``status`` column is parked on the Phase-2 neutral 'draft'
    value on purpose: ``_ensure_drafts_table`` re-derives draft_state from
    status on EVERY read (issued->posted) and protects only 'converted', so a
    terminal state on a status='issued' row is clobbered straight back to
    'posted' before the route ever sees it.
    """
    conn = sqlite3.connect(str(_links_db(storage)))
    try:
        row = conn.execute(
            "SELECT id FROM proforma_drafts WHERE wfirma_proforma_id=? LIMIT 1",
            (PID,),
        ).fetchone()
        assert row is not None, "seed must leave a draft carrying the proforma id"
        conn.execute(
            "UPDATE proforma_drafts SET draft_state=?, status='draft' WHERE id=?",
            (state, row[0]),
        )
        conn.commit()
        return int(row[0])
    finally:
        conn.close()


def _assert_draft_untouched(storage, draft_id: int, state: str) -> None:
    """The ruling is 'changes nothing locally' — pin the whole draft row, not
    just the response shape."""
    d = pildb.get_draft_by_id(_links_db(storage), draft_id)
    assert d is not None
    assert d.draft_state == state, (
        f"draft_state must stay {state!r}, got {d.draft_state!r} — a repair "
        f"resurrected a terminal draft"
    )
    assert not (getattr(d, "wfirma_invoice_id", None) or "").strip(), \
        "a blocked repair must not stamp an invoice identity onto the draft"


def _seed_issued_link(storage) -> None:
    _seed_link(storage, status="pending", invoice_id=IID)
    pildb.mark_issued(_links_db(storage), PID, invoice_id=IID,
                      invoice_number=INUM, invoice_total=Decimal("306.00"),
                      notes="issued")


def test_reconcile_cancelled_draft_is_blocked(client, storage):
    """Issued-link branch: a cancelled draft is not a stale projection to
    repair. Refuse and escalate; change nothing."""
    _seed_issued_draft(storage)
    _seed_issued_link(storage)
    draft_id = _force_terminal_draft_state(storage, "cancelled")

    body = _reconcile(client)

    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("terminal state" in r and "cancelled" in r
               for r in body["blocking_reasons"]), body["blocking_reasons"]
    assert any("escalate to operator" in r for r in body["blocking_reasons"])
    _assert_draft_untouched(storage, draft_id, "cancelled")


def test_reconcile_superseded_draft_is_blocked(client, storage):
    """Issued-link branch: 'superseded' is terminal for the same reason —
    the row has been replaced by a canonical draft and must not be revived."""
    _seed_issued_draft(storage)
    _seed_issued_link(storage)
    draft_id = _force_terminal_draft_state(storage, "superseded")

    body = _reconcile(client)

    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("terminal state" in r and "superseded" in r
               for r in body["blocking_reasons"]), body["blocking_reasons"]
    _assert_draft_untouched(storage, draft_id, "superseded")


def test_reconcile_cancelled_draft_is_blocked_on_pending_link(client, storage):
    """Split-brain (pending) branch: the guard fires before the wFirma re-fetch
    AND before mark_issued — 'changes nothing locally' means the link row is
    untouched too, not merely the draft."""
    _seed_issued_draft(storage)
    _seed_link(storage, status="pending", invoice_id=IID)
    draft_id = _force_terminal_draft_state(storage, "cancelled")

    def _no_fetch(*a, **k):
        raise AssertionError("terminal draft must refuse before any wFirma fetch")

    with patch.object(wc, "fetch_invoice_xml", side_effect=_no_fetch):
        body = _reconcile(client)

    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("terminal state" in r and "cancelled" in r
               for r in body["blocking_reasons"]), body["blocking_reasons"]
    _assert_draft_untouched(storage, draft_id, "cancelled")
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "pending"
