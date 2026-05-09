"""
test_pz_cli_flow.py — targeted tests for the PZ pre-fill CLI flow in
send_wfirma_proforma_to_invoice_live_test.py.

Covers:
    1. dry-run prints aggregated PZ lines
    2. existing wfirma_pz_doc_id skips creation
    3. WFIRMA_CREATE_PZ_ALLOWED=false blocks live PZ write
    4. missing --confirm-pz phrase blocks live PZ write
    5. successful PZ saves wfirma_pz_doc_id in link DB
    6. failed PZ (wFirma ERROR) does not save id
    7. no invoice conversion when only PZ flags are passed
"""
from __future__ import annotations

import sys
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import wfirma_client as wfc
from app.services.proforma_invoice_link_db import (
    ProformaInvoiceLink, create_pending_link, get_link_by_proforma,
    get_pz_doc_id, init_db, set_pz_doc_id,
)
from app.tools.send_wfirma_proforma_to_invoice_live_test import main


# ── Shared fixtures ───────────────────────────────────────────────────────────

# Minimal valid proforma XML — 2 lines with distinct good_ids.
_PROFORMA_XML = """<api>
<invoices>
<invoice>
  <id>465954147</id>
  <fullnumber>PROF 94/2026</fullnumber>
  <type>proforma</type>
  <contractor><id>176578339</id></contractor>
  <currency>USD</currency>
  <price_currency_exchange>4.000000</price_currency_exchange>
  <paymentmethod>transfer</paymentmethod>
  <paymentdate>2026-06-01</paymentdate>
  <date>2026-05-01</date>
  <description></description>
  <series><id>15827088</id></series>
  <total>526.00</total>
  <netto>526.00</netto>
  <invoicecontents>
    <invoicecontent>
      <id>1001</id>
      <name>Ring A</name>
      <unit>szt.</unit>
      <unit_count>1.0000</unit_count>
      <price>173.00</price>
      <vat_code><id>228</id></vat_code>
      <good><id>48611875</id></good>
    </invoicecontent>
    <invoicecontent>
      <id>1002</id>
      <name>Ring B</name>
      <unit>szt.</unit>
      <unit_count>2.0000</unit_count>
      <price>176.50</price>
      <vat_code><id>228</id></vat_code>
      <good><id>48612067</id></good>
    </invoicecontent>
  </invoicecontents>
</invoice>
</invoices>
<status><code>OK</code></status>
</api>"""

_PZ_OK_XML = """<api>
  <warehouse_documents>
    <warehouse_document><id>999001</id></warehouse_document>
  </warehouse_documents>
  <status><code>OK</code></status>
</api>"""

_PZ_ERROR_XML = """<api>
  <status><code>ERROR</code><description>Stan magazynowy nie może być ujemny</description></status>
</api>"""

_PROFORMA_ID = "465954147"
_WAREHOUSE_ID = "347088"


def _temp_db() -> Path:
    tmp = tempfile.mktemp(suffix=".sqlite")
    p = Path(tmp)
    init_db(p)
    return p


def _full_creds(**overrides):
    """Patch settings with wFirma credentials and PZ gate."""
    base = {
        "wfirma_access_key":          "ACC-KEY",
        "wfirma_secret_key":          "SEC-KEY",
        "wfirma_app_key":             "APP-KEY",
        "wfirma_company_id":          "359292",
        "wfirma_warehouse_id":        _WAREHOUSE_ID,
        "wfirma_warehouse_module_enabled": True,
        "wfirma_create_pz_allowed":   False,
    }
    base.update(overrides)
    return patch.multiple(settings, **base)


def _http_returns(pairs: list[tuple[int, str]]):
    """Mock _http_request to return the given (status, text) pairs in sequence."""
    it = iter(pairs)
    def _fake(*args, **kwargs):
        return next(it)
    return patch("app.services.wfirma_client._requests.request",
                 side_effect=lambda method, url, **kw: _make_resp(*next(it)))


def _make_resp(status: int, text: str):
    """Return a minimal mock response object."""
    from unittest.mock import MagicMock
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


def _http_seq(*pairs):
    """Patch _requests.request to return (status, text) pairs in order."""
    it = iter(pairs)
    def _fake(method, url, **kwargs):
        status, text = next(it)
        return _make_resp(status, text)
    return patch("app.services.wfirma_client._requests.request", side_effect=_fake)


def _pz_argv(db: Path, *, confirm_pz: str | None = None, extra: list | None = None) -> list:
    """Build argv for a PZ-only dry-run or live run."""
    argv = [
        "--proforma-id", _PROFORMA_ID,
        "--create-pz-before-invoice",
        "--warehouse-id", _WAREHOUSE_ID,
        "--db", str(db),
    ]
    if confirm_pz:
        argv += ["--confirm-pz", confirm_pz]
    if extra:
        argv += extra
    return argv


# ── Test 1: dry-run prints PZ lines ──────────────────────────────────────────

def test_dry_run_prints_pz_lines(capsys):
    """--create-pz-before-invoice without --confirm-pz prints aggregated lines."""
    db = _temp_db()
    with _full_creds():
        with _http_seq((200, _PROFORMA_XML)):
            rc = main(_pz_argv(db))  # no --confirm-pz
    out = capsys.readouterr().out
    assert rc == 0
    assert "PZ" in out
    assert "48611875" in out
    assert "48612067" in out
    assert "DRY-RUN" in out


# ── Test 2: existing PZ id skips creation ────────────────────────────────────

def test_existing_pz_skips_creation(capsys):
    """If wfirma_pz_doc_id is already set, creation is skipped."""
    db = _temp_db()
    # Pre-populate: insert a pending link with PZ doc id already set.
    link = ProformaInvoiceLink(
        proforma_id=_PROFORMA_ID,
        proforma_number="PROF 94/2026",
        converted_at="2026-05-06T00:00:00Z",
        operator="test",
        source_total=Decimal("526.00"),
        currency="USD",
        status="pending",
    )
    create_pending_link(db, link)
    set_pz_doc_id(db, _PROFORMA_ID, "EXISTING-PZ-001")

    with _full_creds(wfirma_create_pz_allowed=True):
        with _http_seq((200, _PROFORMA_XML)):
            rc = main(_pz_argv(db, confirm_pz="YES_CREATE_ONE_PZ"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "EXISTING-PZ-001" in out
    assert "skipping" in out.lower()
    # PZ doc id must remain unchanged
    assert get_pz_doc_id(db, _PROFORMA_ID) == "EXISTING-PZ-001"


# ── Test 3: WFIRMA_CREATE_PZ_ALLOWED=false blocks live write ─────────────────

def test_gate_off_blocks_pz_write(capsys):
    """Live PZ write is blocked when WFIRMA_CREATE_PZ_ALLOWED=false."""
    db = _temp_db()
    with _full_creds(wfirma_create_pz_allowed=False):
        with _http_seq((200, _PROFORMA_XML)):
            rc = main(_pz_argv(db, confirm_pz="YES_CREATE_ONE_PZ"))
    out = capsys.readouterr().out
    assert rc == 0  # dry-run exit, not error
    assert "DRY-RUN" in out
    assert get_pz_doc_id(db, _PROFORMA_ID) is None


# ── Test 4: missing --confirm-pz blocks live write ───────────────────────────

def test_missing_confirm_pz_blocks_write(capsys):
    """Live PZ write is blocked when --confirm-pz phrase is absent."""
    db = _temp_db()
    with _full_creds(wfirma_create_pz_allowed=True):
        with _http_seq((200, _PROFORMA_XML)):
            rc = main(_pz_argv(db, confirm_pz=None))  # no phrase
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert get_pz_doc_id(db, _PROFORMA_ID) is None


# ── Test 5: successful PZ saves wfirma_pz_doc_id ─────────────────────────────

def test_successful_pz_saves_doc_id(capsys):
    """Successful PZ creation stores the wFirma document id in the link DB."""
    db = _temp_db()
    with _full_creds(wfirma_create_pz_allowed=True):
        with _http_seq(
            (200, _PROFORMA_XML),    # fetch_proforma_xml
            (200, _PZ_OK_XML),       # create_warehouse_pz
        ):
            rc = main(_pz_argv(db, confirm_pz="YES_CREATE_ONE_PZ"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "999001" in out
    assert get_pz_doc_id(db, _PROFORMA_ID) == "999001"


# ── Test 6: failed PZ does not save id ───────────────────────────────────────

def test_failed_pz_does_not_save_doc_id(capsys):
    """wFirma ERROR on PZ → rc=8 and no wfirma_pz_doc_id stored."""
    db = _temp_db()
    with _full_creds(wfirma_create_pz_allowed=True):
        with _http_seq(
            (200, _PROFORMA_XML),    # fetch_proforma_xml
            (200, _PZ_ERROR_XML),    # create_warehouse_pz → ERROR
        ):
            rc = main(_pz_argv(db, confirm_pz="YES_CREATE_ONE_PZ"))
    assert rc == 8
    assert get_pz_doc_id(db, _PROFORMA_ID) is None


# ── Test 7b: failed+PZ row skips duplicate PZ creation ───────────────────────

def test_failed_link_with_pz_skips_creation(capsys):
    """A status=failed link row with wfirma_pz_doc_id set must skip PZ creation."""
    import sqlite3 as _sqlite3
    db = _temp_db()
    # Insert a failed link (simulates previous blocked invoice attempt)
    link = ProformaInvoiceLink(
        proforma_id=_PROFORMA_ID,
        proforma_number="PROF 94/2026",
        converted_at="2026-05-06T00:00:00Z",
        operator="test",
        source_total=Decimal("526.00"),
        currency="USD",
        status="pending",
    )
    create_pending_link(db, link)
    # Manually set status to failed + store pz_doc_id (mirrors real sequence)
    with _sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_invoice_links SET status='failed', wfirma_pz_doc_id='PZ-FAIL-001' "
            "WHERE proforma_id=?", (_PROFORMA_ID,)
        )
        conn.commit()

    with _full_creds(wfirma_create_pz_allowed=True):
        with _http_seq((200, _PROFORMA_XML)):
            rc = main(_pz_argv(db, confirm_pz="YES_CREATE_ONE_PZ"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "PZ-FAIL-001" in out
    assert "skipping" in out.lower()


# ── Test 7: no invoice conversion when only PZ flags passed ──────────────────

def test_pz_only_flags_do_not_trigger_invoice(capsys):
    """When only PZ flags are supplied (no invoice live-confirm), no invoices/add call."""
    db = _temp_db()
    calls = []

    def _spy(method, url, **kwargs):
        calls.append((method, url))
        if "invoices/find" in url:
            return _make_resp(200, _PROFORMA_XML)
        if "warehouse_document_p_z" in url:
            return _make_resp(200, _PZ_OK_XML)
        return _make_resp(200, "<api><status><code>OK</code></status></api>")

    with _full_creds(wfirma_create_pz_allowed=True):
        with patch("app.services.wfirma_client._requests.request", side_effect=_spy):
            rc = main(_pz_argv(db, confirm_pz="YES_CREATE_ONE_PZ"))

    assert rc == 0
    # invoices/add must NOT have been called
    invoice_add_calls = [c for c in calls if "invoices/add" in c[1]]
    assert invoice_add_calls == [], f"invoices/add was called unexpectedly: {invoice_add_calls}"
