"""P0 Accounting Hub — normalizer + cardinality + PDF + warehouse + no writes."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import require_api_key as get_current_user
from app.services.accounting_documents import (
    expense_payment_outstanding,
    map_payment_state,
    normalize_invoices_from_xml,
    normalize_warehouse_documents_from_xml,
)

# ── Fixtures: nested-stub XML (live shape: 20 commercial + N id-only stubs) ──

def _invoice_commercial(i: int, *, paymentstate: str = "paid", ctype: str = "normal") -> str:
    return f"""
    <invoice>
      <id>{1000 + i}</id>
      <fullnumber>FV {i}/2026</fullnumber>
      <date>2026-0{(i % 9) + 1:d}-15</date>
      <type>{ctype}</type>
      <contractor_detail><name>Party {i}</name></contractor_detail>
      <contractor><id>{200 + i}</id></contractor>
      <netto>{1000 + i}.00</netto><tax>230.00</tax><brutto>{1230 + i}.00</brutto>
      <currency>EUR</currency>
      <paymentstate>{paymentstate}</paymentstate>
      <paymentdate>2026-0{(i % 9) + 1:d}-30</paymentdate>
      <alreadypaid>0.00</alreadypaid>
      <remaining>{1230 + i}.00</remaining>
      <invoices>
        <invoice><id>{1000 + i}</id></invoice>
        <invoice><id>{9000 + i}</id></invoice>
        <invoice><id>{8000 + i}</id></invoice>
        <invoice><id>{7000 + i}</id></invoice>
        <invoice><id>{6000 + i}</id></invoice>
        <invoice><id>{5000 + i}</id></invoice>
        <invoice><id>{4000 + i}</id></invoice>
        <invoice><id>{3000 + i}</id></invoice>
        <invoice><id>{2500 + i}</id></invoice>
        <invoice><id>{2400 + i}</id></invoice>
        <invoice><id>{2300 + i}</id></invoice>
      </invoices>
    </invoice>"""


def _xml_invoices(n: int = 20, *, ctype: str = "normal", paymentstate: str = "paid") -> str:
    body = "".join(_invoice_commercial(i, paymentstate=paymentstate, ctype=ctype) for i in range(1, n + 1))
    return f"<api><invoices>{body}</invoices><status><code>OK</code></status></api>"


def _warehouse_commercial(i: int, wh_type: str = "WZ") -> str:
    return f"""
    <warehouse_document>
      <id>{5000 + i}</id>
      <type>{wh_type}</type>
      <fullnumber>{wh_type} {i}/2026</fullnumber>
      <date>2026-03-{i:02d}</date>
      <netto>{100 * i}.00</netto><brutto>{123 * i}.00</brutto>
      <currency>PLN</currency>
      <status>done</status>
      <contractor_detail><name>WH Party {i}</name></contractor_detail>
      <warehouse_documents>
        <warehouse_document><id>{5000 + i}</id></warehouse_document>
        <warehouse_document><id>{6000 + i}</id></warehouse_document>
        <warehouse_document><id>{7000 + i}</id></warehouse_document>
        <warehouse_document><id>{8000 + i}</id></warehouse_document>
        <warehouse_document><id>{9000 + i}</id></warehouse_document>
        <warehouse_document><id>{9100 + i}</id></warehouse_document>
        <warehouse_document><id>{9200 + i}</id></warehouse_document>
        <warehouse_document><id>{9300 + i}</id></warehouse_document>
        <warehouse_document><id>{9400 + i}</id></warehouse_document>
        <warehouse_document><id>{9500 + i}</id></warehouse_document>
        <warehouse_document><id>{9600 + i}</id></warehouse_document>
        <warehouse_document><id>{9700 + i}</id></warehouse_document>
        <warehouse_document><id>{9800 + i}</id></warehouse_document>
        <warehouse_document><id>{9900 + i}</id></warehouse_document>
      </warehouse_documents>
    </warehouse_document>"""


def _xml_warehouse(n: int = 20, wh_type: str = "WZ") -> str:
    body = "".join(_warehouse_commercial(i, wh_type) for i in range(1, n + 1))
    return (
        f"<api><warehouse_documents>{body}</warehouse_documents>"
        f"<status><code>OK</code></status></api>"
    )


# ── Cardinality ──────────────────────────────────────────────────────────────

def test_invoice_nested_stub_cardinality_20_not_240():
    xml = _xml_invoices(20)
    # Deep count would be 20 + 20*11 = 240
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    assert len(root.findall(".//invoice")) == 240
    rows = normalize_invoices_from_xml(xml)
    assert len(rows) == 20
    assert all(r["number"].startswith("FV ") for r in rows)
    assert all(r["wfirma_id"].isdigit() for r in rows)
    # Never surface raw numeric id as the document number
    assert not any(r["number"] == r["wfirma_id"] for r in rows)


def test_credit_note_nested_stub_cardinality():
    xml = _xml_invoices(20, ctype="correction", paymentstate="unpaid")
    rows = normalize_invoices_from_xml(xml)
    assert len(rows) == 20
    assert all(r["doc_kind"] == "credit_note" for r in rows)
    assert all(r["payment_state"] == "Outstanding" for r in rows)


def test_no_metadata_only_rows():
    xml = """<api><invoices>
      <invoice><id>1</id></invoice>
      <invoice><id>2</id><fullnumber>FV 1/2026</fullnumber><date>2026-01-01</date>
        <brutto>10.00</brutto><currency>EUR</currency><paymentstate>paid</paymentstate>
        <contractor_detail><name>A</name></contractor_detail>
        <netto>8.00</netto><tax>2.00</tax>
      </invoice>
    </invoices></api>"""
    rows = normalize_invoices_from_xml(xml)
    assert len(rows) == 1
    assert rows[0]["number"] == "FV 1/2026"


def test_payment_state_mapping():
    assert map_payment_state("paid") == "Paid"
    assert map_payment_state("unpaid") == "Outstanding"
    assert map_payment_state("open") == "Outstanding"
    assert map_payment_state("undefined") == "Not specified"
    assert map_payment_state("") == "Not specified"
    assert map_payment_state(None) == "Not specified"


def test_warehouse_top_level_parsing_not_deep():
    xml = _xml_warehouse(20, "PZ")
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    assert len(root.findall(".//warehouse_document")) == 20 + 20 * 14  # 300
    rows = normalize_warehouse_documents_from_xml(xml, allowed_types={"PZ"})
    assert len(rows) == 20
    assert all(r["doc_type"] == "PZ" for r in rows)
    assert all(r["pdf_available"] is False for r in rows)


def test_supplier_expense_payment_reconciliation_fixture():
    """expense − linked payments = outstanding (one known supplier proof)."""
    proof = expense_payment_outstanding(1000.00, [250.00, 150.00])
    assert proof["expense_gross"] == 1000.00
    assert proof["payments_total"] == 400.00
    assert proof["outstanding"] == 600.00


# ── list_invoices_by_type integration ────────────────────────────────────────

def _resp(status_code: int, text: str):
    from unittest.mock import MagicMock
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.content = text.encode("utf-8")
    return r


def test_list_invoices_by_type_uses_normalizer_cardinality(monkeypatch):
    from app.services import wfirma_client as wc

    xml = _xml_invoices(20)
    # Patch settings check path used by _http_request — reuse contract helper pattern
    with patch.object(wc, "_http_request", return_value=(200, xml)):
        out = wc.list_invoices_by_type("normal", limit=25)
    assert out["count"] == 20
    assert out["rows"][0]["state"] == "Paid"
    assert out["rows"][0]["payment_state"] == "Paid"


def test_list_warehouse_documents_by_type_top_level():
    from app.services import wfirma_client as wc

    xml = _xml_warehouse(20, "WZ")
    captured = {}

    def _capture(method, module, action, body="", **kwargs):
        captured["body"] = body
        return (200, xml)

    with patch.object(wc, "_http_request", side_effect=_capture):
        out = wc.list_warehouse_documents_by_type("WZ", page=2, limit=15)
    assert out["count"] == 20
    assert out["rows"][0]["number"].startswith("WZ ")
    # Sibling page contract (nested page/start is ignored by live wFirma)
    assert "<page>2</page>" in captured["body"]
    assert "<limit>15</limit>" in captured["body"]
    assert "<page><start>" not in captured["body"]


def test_list_warehouse_mm_raises():
    from app.services import wfirma_client as wc
    with pytest.raises(ValueError, match="MM"):
        wc.list_warehouse_documents_by_type("MM")


# ── Routes ───────────────────────────────────────────────────────────────────

def _client():
    app.dependency_overrides[get_current_user] = lambda: {"username": "t", "role": "admin"}
    return TestClient(app)


def test_route_invoice_ok():
    c = _client()
    try:
        with patch(
            "app.api.routes_accounting.wfirma_client.list_invoices_by_type",
            return_value={"rows": [{"number": "FV 1/2026", "wfirma_id": "1", "state": "Paid"}], "count": 1},
        ):
            r = c.get("/api/v1/accounting/documents/invoice")
        assert r.status_code == 200
        assert r.json()["count"] == 1
        assert r.json()["authority"] == "wfirma.invoices"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_route_warehouse_wz_ok():
    c = _client()
    try:
        with patch(
            "app.api.routes_accounting.wfirma_client.list_warehouse_documents_by_type",
            return_value={"rows": [{"number": "WZ 1/2026", "doc_type": "WZ"}], "count": 1},
        ) as m:
            r = c.get("/api/v1/accounting/documents/wz")
        assert r.status_code == 200
        assert r.json()["warehouse_type"] == "WZ"
        assert m.call_args.args[0] == "WZ"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_route_mm_blocked():
    c = _client()
    try:
        r = c.get("/api/v1/accounting/documents/mm")
        assert r.status_code == 404
        assert "unavailable" in r.json()["detail"].lower()
        assert "pending" not in r.json()["detail"].lower() or "not" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_route_invoice_pdf_proxy():
    c = _client()
    try:
        with patch(
            "app.api.routes_accounting.wfirma_client.fetch_invoice_pdf",
            return_value=b"%PDF-1.4 " + b"x" * 300,
        ) as m:
            r = c.get("/api/v1/accounting/documents/invoice/97820621/pdf?disposition=attachment")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert "no-store" in r.headers.get("cache-control", "")
        assert "attachment" in r.headers.get("content-disposition", "")
        m.assert_called_once_with("97820621")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_route_warehouse_pdf_not_exposed():
    c = _client()
    try:
        r = c.get("/api/v1/accounting/documents/wz/123/pdf")
        assert r.status_code == 404
        assert "unproven" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_accounting_hub_zero_write_methods():
    """No POST/PUT/PATCH/DELETE reachable under /api/v1/accounting."""
    from app.api import routes_accounting as ra
    methods = set()
    for route in ra.router.routes:
        methods |= set(getattr(route, "methods", []) or [])
    assert methods <= {"GET", "HEAD", "OPTIONS"}
    assert "POST" not in methods
    assert "PUT" not in methods
    assert "PATCH" not in methods
    assert "DELETE" not in methods


def test_accounting_hub_pz_not_batch_proxy():
    """PZ register must call warehouse authority, not dashboard batches."""
    src = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "accounting-hub.jsx"
    text = src.read_text(encoding="utf-8")
    assert "PurchaseLedgerTab" not in text
    assert "listBatches" not in text
    assert "pz: 'pz'" in text or 'pz: "pz"' in text or "pz: 'pz'" in text.replace('"', "'")
    assert "_ACC_DOC_LIVE" in text
    assert "warehouse" in text.lower()


def test_client_ledger_route_reuse_source():
    src = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "accounting-hub.jsx"
    text = src.read_text(encoding="utf-8")
    assert "LedgersPage" in text
    assert "window.LedgersPage" in text


def test_no_n_plus_one_in_list_helpers():
    """list_* helpers issue exactly one _http_request per call."""
    from app.services import wfirma_client as wc

    xml_inv = _xml_invoices(5)
    xml_wh = _xml_warehouse(5, "RW")
    with patch.object(wc, "_http_request", return_value=(200, xml_inv)) as m:
        wc.list_invoices_by_type("normal")
        assert m.call_count == 1
    with patch.object(wc, "_http_request", return_value=(200, xml_wh)) as m:
        wc.list_warehouse_documents_by_type("RW")
        assert m.call_count == 1


def test_list_invoices_by_type_uses_sibling_page(monkeypatch):
    """Accounting Hub start offset must map to sibling page=N, not nested start."""
    from app.services import wfirma_client as wc

    captured = {}

    def _stub(method, module, action, body=""):
        captured["body"] = body
        return 200, _xml_invoices(2)

    monkeypatch.setattr(wc, "_http_request", _stub)
    wc.list_invoices_by_type("normal", start=20, limit=20)
    body = captured["body"]
    assert "<page>2</page>" in body
    assert "<limit>20</limit>" in body
    assert "<page><start>" not in body
