"""
test_proforma_failed_link_recovery.py — permanent recovery for a FAILED
proforma->invoice conversion link that carries NO invoice identity.

Origin: proforma_id 489002275 (PROF 163/2026). The 2026-07-17 convert called
wFirma invoices/add, which returned status=ERROR (empty detail); the route
recorded proforma_invoice_links.status='failed' with invoice_id/number NULL.
The link was then a DEAD-END: reconcile (#939) needs an invoice identity to
supply, and re-Convert hit ProformaAlreadyConverted — so the proforma could be
neither reconciled nor retried.

Recovery model (operator-confirmed 2026-07-18): DISCOVERY-FIRST + explicit
operator confirm.
  * reconcile(recover_without_identity=true): read-only discovery of an orphan
    invoice back-referencing the proforma. one -> reconcile via the identical
    verify+mark_issued path; >1 -> refused; none -> retry_ready (safe).
  * convert(retry_failed_link=true): reopen the SAME failed row (never a 2nd
    row) and re-run invoices/add. Duplicate guard preserved throughout.

Coverage (the six required areas):
  retry               — reopen_for_retry + convert retry acceptance
  reconciliation      — discovery one/none/many at the reconcile route
  concurrency         — reopen_for_retry single-winner (sequential + threaded)
  storage preservation— failed row never deleted; note appended, not clobbered
  deployment safety   — additive only: VALID_STATUSES unchanged; UNIQUE guard held
  error capture       — extract_error_detail pulls nested wFirma error detail
"""
from __future__ import annotations

import json
import sqlite3
import threading
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as wc
from app.services import packing_db    as pdb
from app.services import warehouse_db  as wdb
from app.services import document_db    as ddb
from app.services import wfirma_db      as wfdb
from app.services import proforma_invoice_link_db as pildb
from app.services import proforma_service_charges_db as scdb


BATCH  = "BATCH_RECOVERY_TEST"
CLIENT = "ANASTAZIA"
PID    = "489002275"
PNUM   = "PROF 163/2026"
IID    = "500777"
INUM   = "FA 1/7/2026"
CONVERT_TOKEN   = "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"
RECONCILE_TOKEN = "YES_RECONCILE_INVOICE_LINK"


# ── wFirma XML fixtures (real response shapes — Lesson A) ─────────────────────

def _proforma_xml(*, pid=PID, pnum=PNUM, contractor_id="9001",
                  currency="EUR", total="306.00") -> str:
    return f"""<?xml version="1.0"?>
<api><invoices><invoice>
  <id>{pid}</id><type>proforma</type><fullnumber>{pnum}</fullnumber>
  <date>2026-07-14</date><paymentmethod>transfer</paymentmethod>
  <paymentdate>2026-07-21</paymentdate><currency>{currency}</currency>
  <contractor><id>{contractor_id}</id></contractor>
  <series><id>15827088</id></series><total>{total}</total><netto>{total}</netto>
  <description>Source proforma</description>
  <invoicecontents><invoicecontent>
    <name>RING</name><good><id>42</id></good><unit>szt.</unit>
    <unit_count>1.0000</unit_count><price>306.00</price>
    <vat_code><id>228</id></vat_code>
  </invoicecontent></invoicecontents>
</invoice></invoices><status><code>OK</code></status></api>"""


def _created_invoice_xml(*, inv_id=IID, contractor_id="9001", currency="EUR",
                         total="306.00", line_count=1) -> str:
    lines = "".join("""<invoicecontent>
      <name>RING</name><good><id>42</id></good><unit>szt.</unit>
      <unit_count>1.0000</unit_count><price>306.00</price>
      <vat_code><id>228</id></vat_code></invoicecontent>""" for _ in range(line_count))
    return f"""<?xml version="1.0"?>
<api><invoices><invoice>
  <id>{inv_id}</id><type>normal</type><fullnumber>{INUM}</fullnumber>
  <date>2026-07-17</date><currency>{currency}</currency>
  <contractor><id>{contractor_id}</id></contractor><total>{total}</total>
  <netto>{total}</netto>
  <description>Dokument wystawiony do proformy {PNUM}</description>
  <invoicecontents>{lines}</invoicecontents>
</invoice></invoices><status><code>OK</code></status></api>"""


def _find_xml(*rows) -> str:
    """invoices/find collection. rows: (id, fullnumber, description)."""
    nodes = "".join(
        f"<invoice><id>{i}</id><fullnumber>{n}</fullnumber>"
        f"<type>normal</type><description>{d}</description></invoice>"
        for (i, n, d) in rows
    )
    return (f'<?xml version="1.0"?><api><invoices>{nodes}</invoices>'
            f'<status><code>OK</code></status></api>')


def _add_error_xml(detail="<errors><error>VAT rate invalid</error></errors>") -> str:
    return (f'<?xml version="1.0"?><api><invoices></invoices>'
            f'<status><code>ERROR</code><description></description></status>'
            f'{detail}</api>')


def _add_ok_xml(inv_id=IID, inv_num=INUM) -> str:
    return (f'<?xml version="1.0"?><api><invoices><invoice>'
            f'<id>{inv_id}</id><fullnumber>{inv_num}</fullnumber>'
            f'<type>normal</type></invoice></invoices>'
            f'<status><code>OK</code></status></api>')


# ── Fixtures / helpers (mirror test_invoice_link_reconcile.py) ────────────────

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


def _readiness_ready():
    from app.api import routes_proforma as rp
    return patch.object(rp, "_derive_draft_readiness",
                        return_value={"ready": True, "blocking_reasons": [], "blockers": []})


def _gate_invoice_on():
    return patch.object(settings, "wfirma_create_invoice_allowed", True)


def _links_db(storage) -> Path:
    return storage / "proforma_links.db"


def _seed_issued_draft(storage, *, wfirma_id=PID, client_name=CLIENT):
    db = _links_db(storage)
    pildb.upsert_pending_draft(db, batch_id=BATCH, client_name=client_name,
                               currency="EUR", exchange_rate=None,
                               source_lines_json="[]")
    pildb.mark_draft_issued(db, BATCH, client_name, wfirma_proforma_id=wfirma_id)


def _seed_failed_link(storage, *, pid=PID, pnum=PNUM,
                      notes="RuntimeError: invoices/add wFirma status=ERROR: "):
    db = _links_db(storage)
    pildb.create_pending_link(db, pildb.ProformaInvoiceLink(
        proforma_id=pid, proforma_number=pnum, converted_at="",
        operator="Amit Saniya", source_total=Decimal("306.00"),
        currency="EUR", status="pending"))
    pildb.mark_failed(db, pid, notes=notes)


def _seed_audit(storage):
    d = storage / "outputs" / BATCH
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps({"batch_id": BATCH, "timeline": []}),
                                  encoding="utf-8")


def _events(storage, draft_id):
    db = _links_db(storage)
    con = sqlite3.connect(db)
    try:
        return [r[0] for r in con.execute(
            "SELECT event FROM proforma_draft_events WHERE draft_id=? ORDER BY id",
            (draft_id,))]
    finally:
        con.close()


def _draft_id(storage):
    con = sqlite3.connect(_links_db(storage))
    try:
        r = con.execute("SELECT id FROM proforma_drafts WHERE batch_id=? "
                        "AND client_name=?", (BATCH, CLIENT)).fetchone()
        return r[0] if r else None
    finally:
        con.close()


_CONVERT_URL   = f"/api/v1/proforma/to-invoice/{BATCH}/{CLIENT}"
_RECONCILE_URL = "/api/v1/proforma/invoice-links/{pid}/reconcile"


def _reconcile(client, *, pid=PID, recover_without_identity=False,
               invoice_id="", operator="Amit Saniya"):
    body = {"confirm": RECONCILE_TOKEN}
    if recover_without_identity:
        body["recover_without_identity"] = True
    if invoice_id:
        body["wfirma_invoice_id"] = invoice_id
    return client.post(_RECONCILE_URL.format(pid=pid),
                       headers={**_auth(), "X-Operator": operator},
                       json=body).json()


def _convert(client, *, retry_failed_link=False):
    body = {"confirm": CONVERT_TOKEN}
    if retry_failed_link:
        body["retry_failed_link"] = True
    return client.post(_CONVERT_URL,
                       headers={**_auth(), "X-Operator": "Amit Saniya"},
                       json=body).json()


# ══ UNIT — reopen_for_retry (retry / concurrency / storage / deployment) ══════

def test_reopen_for_retry_flips_failed_to_pending_and_preserves_note(storage):
    db = _links_db(storage)
    _seed_failed_link(storage)
    before = pildb.get_link_by_proforma(db, PID)
    assert before.status == "failed"

    assert pildb.reopen_for_retry(db, PID, operator="Amit Saniya") is True

    after = pildb.get_link_by_proforma(db, PID)
    assert after.status == "pending"                    # retry: reopened
    assert "invoices/add wFirma status=ERROR" in (after.notes or "")  # storage: note kept
    assert "reopened_for_retry by Amit Saniya" in (after.notes or "")  # audit: appended


def test_reopen_for_retry_single_winner_sequential(storage):
    db = _links_db(storage)
    _seed_failed_link(storage)
    assert pildb.reopen_for_retry(db, PID) is True      # first flips failed->pending
    assert pildb.reopen_for_retry(db, PID) is False     # concurrency: no longer failed


def test_reopen_for_retry_single_winner_threaded(storage):
    db = _links_db(storage)
    _seed_failed_link(storage)
    results, lock = [], threading.Lock()

    def _worker():
        try:
            r = pildb.reopen_for_retry(db, PID)
        except Exception as exc:               # locked/other -> not a winner
            r = exc
        with lock:
            results.append(r)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert results.count(True) == 1            # EXACTLY one reopened the row


def test_reopen_for_retry_refuses_non_failed(storage):
    db = _links_db(storage)
    _seed_failed_link(storage)
    pildb.record_invoice_identity(db, PID, invoice_id=IID, invoice_number=INUM)
    pildb.mark_issued(db, PID, invoice_id=IID, invoice_number=INUM,
                      invoice_total=Decimal("306.00"))
    assert pildb.reopen_for_retry(db, PID) is False      # issued is not retryable


def test_reopen_for_retry_missing_row_raises(storage):
    with pytest.raises(KeyError):
        pildb.reopen_for_retry(_links_db(storage), "no-such-proforma")


def test_recovery_preserves_duplicate_guard_and_never_deletes(storage):
    db = _links_db(storage)
    _seed_failed_link(storage)
    pildb.reopen_for_retry(db, PID)
    # DEPLOYMENT SAFETY / STORAGE: still exactly ONE row for this proforma, and
    # proforma_id is still UNIQUE — a second create is still refused.
    with pytest.raises(pildb.ProformaAlreadyConverted):
        pildb.create_pending_link(db, pildb.ProformaInvoiceLink(
            proforma_id=PID, proforma_number=PNUM, converted_at="",
            operator="x", source_total=Decimal("1.00"), currency="EUR",
            status="pending"))
    con = sqlite3.connect(db)
    try:
        n = con.execute("SELECT COUNT(*) FROM proforma_invoice_links "
                        "WHERE proforma_id=?", (PID,)).fetchone()[0]
    finally:
        con.close()
    assert n == 1                               # never a duplicate, never deleted


def test_valid_statuses_unchanged_no_new_status_migration(storage):
    # DEPLOYMENT SAFETY: recovery reuses pending/failed — it introduces NO new
    # link status, so no destructive schema/status migration ships with it.
    assert pildb.VALID_STATUSES == ("pending", "issued", "failed", "rolled_back")


# ══ UNIT — read-only discovery + error capture ════════════════════════════════

def test_find_invoices_for_proforma_matches_only_backreference():
    page = _find_xml(
        (IID, INUM, f"Dokument wystawiony do proformy {PNUM}"),   # match
        ("999", "FA 9/2026", "unrelated invoice"),                # no back-ref
    )
    with patch.object(wc, "_http_request", return_value=(200, page)):
        out = wc.find_invoices_for_proforma(PNUM)
    assert [o["id"] for o in out] == [IID]


def test_find_invoices_for_proforma_none_and_ambiguous():
    with patch.object(wc, "_http_request",
                      return_value=(200, _find_xml(("1", "A", "nothing here")))):
        assert wc.find_invoices_for_proforma(PNUM) == []
    twopage = _find_xml((IID, INUM, f"do proformy {PNUM}"),
                        ("601", "FA 6/2026", f"korekta do proformy {PNUM}"))
    with patch.object(wc, "_http_request", return_value=(200, twopage)):
        assert len(wc.find_invoices_for_proforma(PNUM)) == 2


def test_extract_error_detail_pulls_nested_reason():
    # ERROR CAPTURE: empty <description>, real reason nested — the 489002275 shape.
    assert "VAT rate invalid" in wc.extract_error_detail(_add_error_xml())
    param = _add_error_xml("<parameters><parameter><field>total</field>"
                           "<message>required</message></parameter></parameters>")
    got = wc.extract_error_detail(param)
    assert "total" in got and "required" in got
    # clean OK response -> nothing extra
    assert wc.extract_error_detail(_created_invoice_xml()) == ""


# ══ ROUTE — reconcile no-identity branch (discovery-first) ════════════════════

def test_reconcile_discovery_none_returns_retry_ready(client, storage):
    _seed_issued_draft(storage)
    _seed_failed_link(storage)
    _seed_audit(storage)
    draft_id = _draft_id(storage)
    with patch.object(wc, "find_invoices_for_proforma", return_value=[]):
        body = _reconcile(client, recover_without_identity=True)
    assert body["ok"] is True
    assert body["status"] == "retry_ready"
    # link is PRESERVED as failed (never deleted, never issued)
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "failed"
    # audit gap fix: the retry_ready decision is recorded on the draft log
    assert "invoice_convert_retry_ready" in _events(storage, draft_id)


def test_reconcile_discovery_ambiguous_refused(client, storage):
    _seed_issued_draft(storage)
    _seed_failed_link(storage)
    _seed_audit(storage)
    with patch.object(wc, "find_invoices_for_proforma",
                      return_value=[{"id": IID, "fullnumber": INUM, "description": ""},
                                    {"id": "601", "fullnumber": "FA 6", "description": ""}]):
        body = _reconcile(client, recover_without_identity=True)
    assert body["status"] == "refused"
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "failed"


def test_reconcile_discovery_one_reconciles_to_issued(client, storage):
    _seed_issued_draft(storage)
    _seed_failed_link(storage)
    _seed_audit(storage)
    with patch.object(wc, "find_invoices_for_proforma",
                      return_value=[{"id": IID, "fullnumber": INUM,
                                     "description": f"do proformy {PNUM}"}]), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=[_proforma_xml(), _created_invoice_xml()]), \
         _readiness_ready():
        body = _reconcile(client, recover_without_identity=True)
    # discovered orphan -> fed the identical verify+mark_issued path
    assert body["status"] == "reconciled"
    assert body["id_source"] == "discovered"
    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link.status == "issued" and link.invoice_id == IID


def test_reconcile_no_flag_no_id_still_blocked(client, storage):
    # Existing behaviour preserved: without the opt-in, a failed link with no
    # identity is still blocked (no accidental discovery / retry).
    _seed_issued_draft(storage)
    _seed_failed_link(storage)
    _seed_audit(storage)
    body = _reconcile(client)                    # no recover_without_identity
    assert body["status"] == "blocked"


# ══ ROUTE — convert retry acceptance + duplicate guard ════════════════════════

def test_convert_failed_link_without_retry_flag_is_blocked(client, storage):
    _seed_issued_draft(storage)
    _seed_failed_link(storage)
    _seed_audit(storage)
    with _gate_invoice_on(), _readiness_ready(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=[_proforma_xml()]):
        body = _convert(client)                  # no retry_failed_link
    assert body["status"] == "blocked"
    # duplicate guard holds AND points at the recovery path
    _reasons = " ".join(body.get("blocking_reasons", []))
    assert "refusing duplicate conversion" in _reasons
    assert "recover_without_identity" in _reasons
    # untouched
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "failed"


def test_convert_retry_reopens_same_row_and_captures_error(client, storage):
    _seed_issued_draft(storage)
    _seed_failed_link(storage)
    _seed_audit(storage)
    draft_id = _draft_id(storage)

    def _http(method, module, op, body):         # invoices/add fails again
        return 200, _add_error_xml()

    with _gate_invoice_on(), _readiness_ready(), \
         patch.object(wc, "find_invoices_for_proforma", return_value=[]), \
         patch.object(wc, "fetch_invoice_xml", side_effect=[_proforma_xml()]), \
         patch.object(wc, "_http_request", side_effect=_http):
        body = _convert(client, retry_failed_link=True)

    assert body["ok"] is False and body["status"] == "failed"
    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link.status == "failed"               # re-failed, still ONE row
    # ERROR CAPTURE: the nested wFirma reason is now on the note (was blank)
    assert "VAT rate invalid" in (link.notes or "")
    # AUDIT HISTORY (append-only event log): the retry path was taken (not
    # blocked as a duplicate) and the re-failure is recorded — both survive even
    # though mark_failed overwrote the single note field.
    evs = _events(storage, draft_id)
    assert "invoice_convert_retry_started" in evs
    assert "invoice_convert_failed" in evs
    # still exactly ONE link row for this proforma (duplicate guard intact)
    con = sqlite3.connect(_links_db(storage))
    try:
        assert con.execute("SELECT COUNT(*) FROM proforma_invoice_links "
                           "WHERE proforma_id=?", (PID,)).fetchone()[0] == 1
    finally:
        con.close()


def test_convert_retry_blocked_when_orphan_invoice_discovered(client, storage):
    # CODE-ENFORCED discovery-first: even with retry_failed_link=True, if an
    # invoice already back-references this proforma the retry is refused BEFORE
    # any reopen / invoices/add — a duplicate can never be created, even if the
    # operator skipped the standalone reconcile step (network-timeout split-brain).
    _seed_issued_draft(storage)
    _seed_failed_link(storage)
    _seed_audit(storage)
    _add_calls = {"n": 0}

    def _http(method, module, op, body):
        if op == "add":
            _add_calls["n"] += 1
        return 200, _add_ok_xml()

    with _gate_invoice_on(), _readiness_ready(), \
         patch.object(wc, "fetch_invoice_xml", side_effect=[_proforma_xml()]), \
         patch.object(wc, "find_invoices_for_proforma",
                      return_value=[{"id": IID, "fullnumber": INUM,
                                     "description": f"do proformy {PNUM}"}]), \
         patch.object(wc, "_http_request", side_effect=_http):
        body = _convert(client, retry_failed_link=True)

    assert body["status"] == "blocked"
    assert IID in body.get("discovered_invoice_ids", [])
    assert _add_calls["n"] == 0                   # invoices/add NEVER called
    # link untouched (still failed — no reopen happened)
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "failed"


def test_convert_retry_success_marks_issued_single_row(client, storage):
    # Primary happy path: discovery finds no invoice, the retry re-runs
    # invoices/add successfully, the SAME row is promoted to issued, and there is
    # still exactly ONE link row (no duplicate).
    _seed_issued_draft(storage)
    _seed_failed_link(storage)
    _seed_audit(storage)

    def _http(method, module, op, body):
        return 200, _add_ok_xml()

    with _gate_invoice_on(), _readiness_ready(), \
         patch.object(wc, "find_invoices_for_proforma", return_value=[]), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=[_proforma_xml(), _created_invoice_xml()]), \
         patch.object(wc, "_http_request", side_effect=_http):
        body = _convert(client, retry_failed_link=True)

    assert body["ok"] is True
    assert body["wfirma_invoice_id"] == IID
    link = pildb.get_link_by_proforma(_links_db(storage), PID)
    assert link.status == "issued" and link.invoice_id == IID
    con = sqlite3.connect(_links_db(storage))
    try:
        assert con.execute("SELECT COUNT(*) FROM proforma_invoice_links "
                           "WHERE proforma_id=?", (PID,)).fetchone()[0] == 1
    finally:
        con.close()


def test_reconcile_discovery_one_nonnumeric_id_refused(client, storage):
    # An orphan found with a non-numeric id must REFUSE (not report retry_ready):
    # an invoice exists, so retrying could duplicate it.
    _seed_issued_draft(storage)
    _seed_failed_link(storage)
    _seed_audit(storage)
    with patch.object(wc, "find_invoices_for_proforma",
                      return_value=[{"id": "not-a-number", "fullnumber": "",
                                     "description": ""}]):
        body = _reconcile(client, recover_without_identity=True)
    assert body["status"] == "refused"
    assert pildb.get_link_by_proforma(_links_db(storage), PID).status == "failed"
