"""
test_wf3_invoice_series.py — ADR-027 D6: preferred_invoice_series_id at WF3 convert.

Pins the three-step series precedence in the proforma→invoice convert route:
  1. body.final_series_id (operator-chosen)         — wins if provided
  2. customer_master.preferred_invoice_series_id     — SSOT
  3. empty                                           — <series> omitted; wFirma default

Also pins:
  - snap.series_id (proforma series) is NOT in the fallback chain (regression guard)
  - Convert stays blocked when WFIRMA_CREATE_INVOICE_ALLOWED=False
  - Builder-layer: <series> present/absent in XML matches series_id

Coverage:
  U1. XML includes <series> when final_series_id provided
  U2. XML omits <series> when series_id is empty
  U3. build_final_invoice_plan: empty final_series_id no longer raises
  U4. check_convert_series: empty series passes (omit is valid); "0" blocked by governance
  R1. Route: customer_master.preferred_invoice_series_id used when no explicit final_series_id
  R2. Route: explicit final_series_id overrides customer_master
  R3. Route: null/empty on both → <series> omitted (no block)
  R4. Route: convert blocked when WFIRMA_CREATE_INVOICE_ALLOWED=False
  R5. snap.series_id NOT used as fallback (proforma series must not bleed into invoice)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.services.proforma_to_invoice import (
    build_final_invoice_plan,
    build_final_invoice_xml,
    parse_proforma_xml,
    FinalInvoicePlan,
    LineItem,
)
from app.services.proforma_draft_governance import check_convert_series


# ── Minimal proforma XML fixture ──────────────────────────────────────────────

def _proforma_xml(series: str = "PROF-SERIES-99") -> str:
    """Minimal valid proforma XML with configurable series_id.

    Must include all fields required by parse_proforma_xml:
    id, fullnumber, type, contractor>id, currency, paymentmethod,
    paymentdate, date, at least one invoicecontent with good>id.
    """
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>12345678</id>
      <type>proforma</type>
      <fullnumber>PROF 1/2026</fullnumber>
      <contractor><id>9001</id></contractor>
      <currency>EUR</currency>
      <paymentmethod>transfer</paymentmethod>
      <series><id>{series}</id></series>
      <total>100.00</total>
      <netto>100.00</netto>
      <date>2026-01-01</date>
      <paymentdate>2026-01-15</paymentdate>
      <invoicecontents>
        <invoicecontent>
          <name>Ring</name>
          <good><id>42001</id></good>
          <unit>szt.</unit>
          <unit_count>1</unit_count>
          <price>100.00</price>
          <vat_code><id>228</id></vat_code>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


def _make_plan(series_id: str) -> FinalInvoicePlan:
    snap = parse_proforma_xml(_proforma_xml())
    return build_final_invoice_plan(
        snap, final_series_id=series_id, invoice_date=date(2026, 6, 1)
    )


# ── U-series: builder unit tests ─────────────────────────────────────────────

class TestBuilderSeriesUnit:

    def test_u1_xml_includes_series_when_set(self):
        """U1: <series><id>X</id></series> present when series_id resolved."""
        plan = _make_plan("INV-SERIES-42")
        xml = build_final_invoice_xml(plan)
        assert "<series><id>INV-SERIES-42</id></series>" in xml

    def test_u2_xml_omits_series_when_empty(self):
        """U2: <series> absent when series_id is empty (ADR-027 D6 step 3)."""
        plan = _make_plan("")
        xml = build_final_invoice_xml(plan)
        assert "<series>" not in xml, (
            "Expected <series> absent for empty series_id; XML:\n" + xml
        )

    def test_u2b_xml_omits_series_for_zero_sentinel(self):
        """U2b: literal '0' (wFirma no-series sentinel) also omitted."""
        plan = _make_plan("0")
        xml = build_final_invoice_xml(plan)
        assert "<series>" not in xml

    def test_u3_plan_empty_series_no_raise(self):
        """U3: build_final_invoice_plan must NOT raise when final_series_id is empty."""
        snap = parse_proforma_xml(_proforma_xml())
        plan = build_final_invoice_plan(snap, final_series_id="",
                                        invoice_date=date(2026, 6, 1))
        assert plan.series_id == ""

    def test_u4a_check_convert_series_empty_passes(self):
        """U4a: empty series_id passes check_convert_series (omit is valid)."""
        check_convert_series("")    # must not raise
        check_convert_series(None)  # must not raise

    def test_u4b_check_convert_series_zero_no_raise_when_governance_off(self):
        """U4b: '0' passes silently when governance is off (default dev mode)."""
        from app.services.proforma_draft_governance import _enabled
        if not _enabled():
            check_convert_series("0")  # governance off → silently passes
        else:
            with pytest.raises(ValueError, match="'0'"):
                check_convert_series("0")

    def test_u5_proforma_series_does_not_appear_in_invoice_xml(self):
        """U5: the proforma series id must NOT bleed into the invoice XML."""
        snap = parse_proforma_xml(_proforma_xml(series="PROF-SERIES-99"))
        plan = build_final_invoice_plan(snap, final_series_id="INV-SERIES-42",
                                        invoice_date=date(2026, 6, 1))
        xml = build_final_invoice_xml(plan)
        assert "PROF-SERIES-99" not in xml, "Proforma series must not appear in invoice"
        assert "<series><id>INV-SERIES-42</id></series>" in xml


# ── R-series: route-layer integration tests ──────────────────────────────────
# Tests the series-resolution logic in proforma_to_invoice() by mocking the
# heavy dependencies (wFirma HTTP, proforma_drafts DB, link DB) and asserting
# on the XML payload captured by the wFirma POST mock.

BATCH = "WF3-SERIES-TEST"
CLIENT = "TESTCO"
PROFORMA_ID = "PROF-12345"
CONTRACTOR_ID = "9001"
INVOICE_SERIES_FROM_CM = "INV-CM-99"


def _make_cm_mock(invoice_series: Optional[str]) -> Any:
    """Minimal CustomerMaster-like object."""
    return SimpleNamespace(
        bill_to_contractor_id=CONTRACTOR_ID,
        preferred_invoice_series_id=invoice_series,
        preferred_proforma_series_id=None,
    )


class TestConvertRouteSeriesPrecedence:
    """Route-level tests: verify the three-step precedence in proforma_to_invoice()."""

    def _setup_mocks(self, monkeypatch, tmp_path, *,
                     cm_invoice_series: Optional[str],
                     explicit_final_series: str = "",
                     captured_xml: Optional[list] = None) -> dict:
        """Patch all I/O so the route can run without real DB / wFirma."""
        from app.api import routes_proforma as rp
        from app.core.config import settings

        monkeypatch.setattr(settings, "wfirma_create_invoice_allowed", True)
        monkeypatch.setattr(settings, "storage_root", tmp_path)

        # --- proforma draft (issued) ---
        draft_mock = SimpleNamespace(
            batch_id=BATCH, client_name=CLIENT,
            wfirma_proforma_id=PROFORMA_ID,
            status="issued", id=1,
        )
        monkeypatch.setattr(rp, "_gather_conversion_inputs",
                            lambda batch_id, cn: (PROFORMA_ID, None))
        monkeypatch.setattr(rp, "_link_already_exists", lambda pid: False)
        monkeypatch.setattr(rp, "_check_invoice_approval_gates",
                            lambda **kw: None)  # gate passes

        # --- customer master ---
        cm = _make_cm_mock(cm_invoice_series)
        monkeypatch.setattr(rp, "get_customer_master",
                            lambda db, cid: cm if cid == CONTRACTOR_ID else None)

        # --- pick_invoice_series_id ---
        from app.services import customer_master as cm_mod
        monkeypatch.setattr(rp, "pick_invoice_series_id",
                            lambda c: (c.preferred_invoice_series_id or "") if c else "")

        # --- wFirma HTTP (captures the XML payload) ---
        _bodies: list = captured_xml if captured_xml is not None else []

        # Created invoice XML for verify-after-create (matches the single line
        # in the proforma fixture: name=Ring, good=42001, unit_count=1, price=100.00, vat=228)
        _created_inv_xml = (
            '<?xml version="1.0"?><api><invoices><invoice>'
            '<id>INV-NEW-001</id><type>normal</type>'
            '<fullnumber>FV 1/2026</fullnumber>'
            '<currency>EUR</currency><total>100.00</total><netto>100.00</netto>'
            '<contractor><id>9001</id></contractor>'
            '<invoicecontents><invoicecontent>'
            '<name>Ring</name><good><id>42001</id></good>'
            '<unit>szt.</unit><unit_count>1</unit_count>'
            '<price>100.00</price><vat_code><id>228</id></vat_code>'
            '</invoicecontent></invoicecontents>'
            '</invoice></invoices><status><code>OK</code></status></api>'
        )

        def _fake_http(method, controller, action, body=""):
            _bodies.append(body)
            if controller == "invoices" and action == "add":
                return 200, (
                    '<?xml version="1.0"?><api>'
                    '<status><code>OK</code></status>'
                    f'<invoices><invoice><id>INV-NEW-001</id>'
                    '<fullnumber>FV 1/2026</fullnumber></invoice></invoices></api>'
                )
            # fetch_invoice_xml — differentiate by ID in the URL path:
            # get/INV-NEW-001 is the verify-after-create fetch (return normal invoice)
            # get/<anything else> is the source proforma fetch
            if controller == "invoices" and action == "get/INV-NEW-001":
                return 200, _created_inv_xml
            if controller == "invoices" and action.startswith("get/"):
                return 200, _proforma_xml(series="PROF-SERIES-SNAP")
            if controller == "invoices" and action == "get":
                return 200, _proforma_xml(series="PROF-SERIES-SNAP")
            return 200, '<api><status><code>OK</code></status></api>'

        import app.services.wfirma_client as wc
        monkeypatch.setattr(wc, "_http_request", _fake_http)

        # --- link DB stubs (use real function names from proforma_invoice_link_db) ---
        monkeypatch.setattr(rp, "_proforma_db_path", lambda: tmp_path / "pd.sqlite")
        import app.services.proforma_invoice_link_db as plink_mod
        monkeypatch.setattr(plink_mod, "create_pending_link",
                            lambda db, link: 1)
        monkeypatch.setattr(plink_mod, "mark_issued",
                            lambda db, **kw: None)
        monkeypatch.setattr(plink_mod, "mark_failed",
                            lambda db, pid, **kw: None)

        # --- audit / timezone stubs ---
        monkeypatch.setattr(
            "app.api.routes_proforma._customer_master_db_path",
            lambda: tmp_path / "cm.sqlite",
        )

        return {"captured": _bodies}

    def _call_route(self, tmp_path, monkeypatch, *,
                    cm_invoice_series: Optional[str],
                    final_series_id: str = "",
                    captured_xml: Optional[list] = None) -> tuple:
        """Call the proforma_to_invoice function and return (response_body, captured_xml)."""
        from app.api import routes_proforma as rp

        _cap: list = captured_xml if captured_xml is not None else []
        self._setup_mocks(monkeypatch, tmp_path,
                          cm_invoice_series=cm_invoice_series,
                          explicit_final_series=final_series_id,
                          captured_xml=_cap)

        req_body = rp._FinalInvoiceConfirmReq(
            confirm="YES_CREATE_FINAL_INVOICE_FROM_PROFORMA",
            operator_description="Test",
            final_series_id=final_series_id,
        )

        # Patch the timezone util at its source so the local import inside the route works
        from unittest.mock import patch as _patch
        with _patch("app.core.timezone_utils.warsaw_today",
                    return_value=date(2026, 6, 1)):
            resp = rp.proforma_to_invoice(
                batch_id=BATCH, client_name=CLIENT,
                body=req_body, x_operator="test-op",
            )

        body = json.loads(resp.body)
        return body, _cap

    def test_r1_customer_master_series_used_when_no_explicit(
        self, tmp_path, monkeypatch
    ):
        """R1: customer_master.preferred_invoice_series_id used when no explicit final_series_id."""
        body, captured = self._call_route(
            tmp_path, monkeypatch,
            cm_invoice_series=INVOICE_SERIES_FROM_CM,
            final_series_id="",
        )
        assert body.get("ok") is True, f"Expected ok=True: {body}"
        add_xml = next((x for x in captured if "<invoice>" in x and "invoices/add" not in x
                        and "type>normal" in x or "type>proforma" not in x), None)
        # Find the invoices/add body (contains <type>normal)
        add_xml = next((x for x in captured
                        if "<type>normal</type>" in x or "normal" in x), None)
        assert add_xml is not None, f"No invoices/add XML captured: {captured}"
        assert f"<series><id>{INVOICE_SERIES_FROM_CM}</id></series>" in add_xml, (
            f"Expected CM invoice series in XML; got:\n{add_xml}"
        )

    def test_r2_explicit_final_series_overrides_customer_master(
        self, tmp_path, monkeypatch
    ):
        """R2: explicit final_series_id overrides customer_master (step 1 wins)."""
        body, captured = self._call_route(
            tmp_path, monkeypatch,
            cm_invoice_series=INVOICE_SERIES_FROM_CM,
            final_series_id="EXPLICIT-SERIES-777",
        )
        assert body.get("ok") is True, f"Expected ok=True: {body}"
        add_xml = next((x for x in captured if "<type>normal</type>" in x), None)
        assert add_xml is not None
        assert "<series><id>EXPLICIT-SERIES-777</id></series>" in add_xml
        assert INVOICE_SERIES_FROM_CM not in add_xml

    def test_r3_both_null_series_omitted_not_blocked(
        self, tmp_path, monkeypatch
    ):
        """R3: null on both → <series> omitted; wFirma default; NOT blocked."""
        body, captured = self._call_route(
            tmp_path, monkeypatch,
            cm_invoice_series=None,
            final_series_id="",
        )
        assert body.get("ok") is True, (
            f"Expected ok=True (omit is valid, not a block): {body}"
        )
        add_xml = next((x for x in captured if "<type>normal</type>" in x), None)
        assert add_xml is not None
        assert "<series>" not in add_xml, (
            f"Expected <series> absent when both series sources are empty: {add_xml}"
        )

    def test_r4_blocked_when_flag_off(self, tmp_path, monkeypatch):
        """R4: convert stays blocked when WFIRMA_CREATE_INVOICE_ALLOWED=False."""
        from app.api import routes_proforma as rp
        from app.core.config import settings

        monkeypatch.setattr(settings, "wfirma_create_invoice_allowed", False)
        monkeypatch.setattr(settings, "storage_root", tmp_path)

        # _check_invoice_approval_gates will block because flag is False
        req_body = rp._FinalInvoiceConfirmReq(
            confirm="YES_CREATE_FINAL_INVOICE_FROM_PROFORMA",
            final_series_id="ANY-SERIES",
        )
        resp = rp.proforma_to_invoice(
            batch_id=BATCH, client_name=CLIENT,
            body=req_body, x_operator="test-op",
        )
        data = json.loads(resp.body)
        assert data.get("ok") is False
        assert data.get("status") == "blocked"
        assert any("WFIRMA_CREATE_INVOICE_ALLOWED" in r
                   for r in (data.get("blocking_reasons") or []))

    def test_r5_snap_series_not_used_as_fallback(self, tmp_path, monkeypatch):
        """R5: snap.series_id (proforma series) must NOT bleed into the invoice XML.

        ADR-027 D6: the fallback chain is final_series_id → customer_master → omit.
        The proforma's own series_id ('PROF-SERIES-SNAP' from fixture) must not
        appear in the invoice payload when no explicit series and CM series is also absent.
        """
        body, captured = self._call_route(
            tmp_path, monkeypatch,
            cm_invoice_series=None,
            final_series_id="",
        )
        assert body.get("ok") is True
        add_xml = next((x for x in captured if "<type>normal</type>" in x), None)
        assert add_xml is not None
        assert "PROF-SERIES-SNAP" not in add_xml, (
            "Proforma snap series must NOT appear in invoice XML (ADR-027 D6 step 2 "
            "goes to customer_master, not snap.series_id)"
        )
