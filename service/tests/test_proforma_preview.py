"""
test_proforma_preview.py — Read-only proforma preview endpoint.

Covers POST /api/v1/proforma/preview/{batch_id}/{client_name}.

Required coverage:
  1. preview returns client/product/design/qty
  2. unmatched design produces ready=false with blocking reason
  3. USD currency carried, not coerced to PLN
  4. missing pricing blocks readiness
  5. endpoint is read-only — no rows created in proforma_invoice_links,
     wfirma_reservation_drafts, wfirma_reservation_lines, or sales tables
  6. product_match=false blocks readiness
"""
from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as _wc
from app.services import packing_db   as pdb
from app.services import warehouse_db as wdb
from app.services import document_db  as ddb
from app.services import wfirma_db    as wfdb
from app.services import inventory_state_engine as ise


BATCH = "BATCH_PFP_TEST"


@pytest.fixture(autouse=True)
def _prime_vat_code_cache():
    """
    Proforma build path now resolves vat_code_id by code ("23"/"WDT"/
    "EXP") via a live helper. Pre-populate the cache so tests stay
    offline. Cleared after each test so negative tests can exercise
    the live lookup if they need to.
    """
    _wc._VAT_CODE_ID_CACHE["23"]  = "222"
    _wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    _wc._VAT_CODE_ID_CACHE["EXP"] = "229"
    yield
    for k in ("23", "WDT", "EXP"):
        _wc._VAT_CODE_ID_CACHE.pop(k, None)


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── seed helpers ─────────────────────────────────────────────────────────────

def _seed_purchase(*, design_no: str, product_code: str, pack_sr: float = 1.0):
    pdb.upsert_packing_lines([{
        "batch_id":              BATCH,
        "invoice_no":            "INV/X",
        "invoice_line_position": int(pack_sr),
        "product_code":          product_code,
        "design_no":             design_no,
        "bag_id":                "",
        "tray_id":               "",
        "item_type":             "RNG",
        "uom":                   "PCS",
        "quantity":              1.0,
        "gross_weight":          0.0,
        "net_weight":            0.0,
        "metal":                 "",
        "karat":                 "",
        "stone_type":            "",
        "remarks":               "",
        "extracted_confidence":  1.0,
        "requires_manual_review": False,
        "pack_sr":               pack_sr,
        "unit_price":            0.0,
        "total_value":           0.0,
    }])


def _seed_sales(client_name: str, designs: list, sales_doc_no: str = "SO-1"):
    """Seed sales packing rows. Each design may carry per-row price/currency:
        designs=[{"sku": "JE03137", "qty": 2.0, "price": 150, "currency": "USD"}]
    Defaults: price=100.0, currency="USD" — tests that intentionally exercise
    missing-price behaviour pass `price=0` and `currency=""`.
    """
    sd = ddb.store_sales_document(
        batch_id=BATCH,
        document_id=str(uuid.uuid4()),
        data={"client_name": client_name, "client_ref": "REF",
              "sales_doc_no": sales_doc_no},
    )
    rows = [{
        "client_name":  client_name,
        "client_ref":   "REF",
        "product_code": d["sku"],
        "design_no":    d["sku"],
        "bag_id":       "",
        "quantity":     d.get("qty", 1.0),
        "remarks":      "",
        "unit_price":   float(d.get("price",   100.0) or 0),
        "total_value":  float(d.get("price",   100.0) or 0) * float(d.get("qty", 1.0)),
        "currency":     str(d.get("currency", "USD") or ""),
        "price_source": "packing_list" if d.get("price", 100.0) else "",
    } for d in designs]
    ddb.store_sales_packing_lines(sd, BATCH, rows)


def _seed_invoice_pricing(product_code: str, unit_price: float, currency: str):
    """Insert one invoice_lines row so the preview has price + currency."""
    ddb.store_invoice_lines("doc-x", BATCH, [{
        "invoice_no":    "INV/X",
        "line_position": 1,
        "product_code":  product_code,
        "description":   "",
        "quantity":      1.0,
        "unit_price":    unit_price,
        "total_value":   unit_price,
        "currency":      currency,
        "rate_usd":      unit_price,
        "amount_usd":    unit_price,
    }])


def _match_product(product_code: str):
    wfdb.upsert_product(
        product_code=product_code,
        wfirma_product_id="42",
        sync_status="matched",
    )


def _match_customer(client_name: str, country: str = "PL", vat_id: str = ""):
    """
    Default to a PL domestic customer so the proforma create flow can
    decide VAT 23% without a live wFirma fallback. Tests that need EU
    WDT or non-EU export pass explicit country/vat_id.
    """
    wfdb.upsert_customer(
        client_name=client_name,
        wfirma_customer_id="9",
        country=country,
        vat_id=vat_id,
        match_status="matched",
    )


# ── 1. Happy path: client + product + design + qty surface in response ──────

def test_preview_returns_client_product_design_qty(client):
    _seed_purchase(design_no="JE03137", product_code="EJL/26-27/100-1")
    # Sales price drives Proforma now; import cost is ignored.
    _seed_sales("ACME", [{"sku": "JE03137", "qty": 2.0,
                           "price": 150.0, "currency": "USD"}])
    _seed_invoice_pricing("EJL/26-27/100-1", 999.0, "USD")  # red herring
    _match_product("EJL/26-27/100-1")
    _match_customer("ACME")

    r = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME", headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["ok"] is True
    assert body["client_name"] == "ACME"
    assert body["currency"] == "USD"
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["product_code"]  == "EJL/26-27/100-1"
    assert line["design_no"]     == "JE03137"
    assert line["qty"]           == 2.0
    assert line["unit_price"]    == 150.0
    assert line["currency"]      == "USD"
    assert line["line_value"]    == 300.0
    assert line["product_match"] is True


# ── 2. Unmatched design → ready=false ───────────────────────────────────────

def test_unmatched_design_blocks_ready(client):
    # No purchase row → design will be unmatched in the view
    _seed_sales("ACME", [{"sku": "GHOST", "qty": 1.0}])
    _match_customer("ACME")

    r = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME", headers=_auth())
    body = r.json()
    assert body["ready"] is False
    assert any("not mapped to a wFirma product_code" in br
               for br in body["blocking_reasons"])
    assert body["lines"][0]["product_code"] is None
    assert body["lines"][0]["design_no"]    == "GHOST"


# ── 3. USD currency carried, not coerced to PLN ─────────────────────────────

def test_usd_currency_not_coerced_to_pln(client):
    _seed_purchase(design_no="JE100", product_code="EJL/U-1")
    _seed_sales("USDCLIENT", [{"sku": "JE100", "qty": 1.0}])
    _seed_invoice_pricing("EJL/U-1", 200.0, "USD")
    _match_product("EJL/U-1")
    _match_customer("USDCLIENT")

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/USDCLIENT",
                       headers=_auth()).json()
    assert body["currency"] == "USD"
    assert body["lines"][0]["currency"] == "USD"
    # The PLN default in wfirma_reservation must NOT leak here
    for line in body["lines"]:
        assert line["currency"] != "PLN"


# ── 4. Missing pricing blocks readiness ─────────────────────────────────────

def test_missing_pricing_blocks_ready(client):
    _seed_purchase(design_no="JE200", product_code="EJL/N-1")
    # Explicit zero sales price + no currency — exercises missing-price gate.
    _seed_sales("ACME", [{"sku": "JE200", "qty": 1.0,
                           "price": 0, "currency": ""}])
    _match_product("EJL/N-1")
    _match_customer("ACME")

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is False
    assert any("missing sales unit_price or currency" in br
               for br in body["blocking_reasons"])
    assert body["lines"][0]["unit_price"] is None
    assert body["lines"][0]["currency"]   == "unknown"


# ── 5. Endpoint is read-only — verify no DB rows written ─────────────────────

def test_preview_writes_nothing_to_proforma_or_reservation(client, storage):
    _seed_purchase(design_no="JE999", product_code="EJL/RO-1")
    _seed_sales("ACME", [{"sku": "JE999", "qty": 1.0}])
    _seed_invoice_pricing("EJL/RO-1", 99.0, "EUR")
    _match_product("EJL/RO-1")
    _match_customer("ACME")

    # Snapshot row counts before
    def _counts():
        out = {}
        with sqlite3.connect(str(storage / "wfirma.db")) as con:
            for t in ("wfirma_reservation_drafts", "wfirma_reservation_lines"):
                try:
                    out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except sqlite3.OperationalError:
                    out[t] = -1
            try:
                out["proforma_invoice_links"] = con.execute(
                    "SELECT COUNT(*) FROM proforma_invoice_links"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                out["proforma_invoice_links"] = -1
        return out

    before = _counts()
    r = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME", headers=_auth())
    assert r.status_code == 200
    after = _counts()
    assert before == after, (before, after)


# ── 6. product_match=false blocks readiness ─────────────────────────────────

def test_product_match_false_blocks_ready(client):
    _seed_purchase(design_no="JE300", product_code="EJL/PM-1")
    _seed_sales("ACME", [{"sku": "JE300", "qty": 1.0}])
    _seed_invoice_pricing("EJL/PM-1", 50.0, "USD")
    # Customer matched but product NOT matched in wfirma_products
    _match_customer("ACME")

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is False
    assert any("not matched in wfirma_products" in br
               for br in body["blocking_reasons"])
    assert body["lines"][0]["product_match"] is False


# ── 7. No sales rows for client → ok=False, single blocking reason ──────────

def test_no_sales_rows_returns_blocked(client):
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/NOBODY",
                       headers=_auth()).json()
    assert body["ok"] is False
    assert body["ready"] is False
    assert body["lines"] == []
    assert any("no sales rows for client" in br
               for br in body["blocking_reasons"])


# ── 8. Stock readiness via inventory_state ──────────────────────────────────

def _advance_state(scan_code: str, *, target: str, batch_id: str = BATCH,
                   product_code: str = "", design_no: str = "") -> None:
    """Walk the lifecycle from start to *target*."""
    chain = [ise.PURCHASE_TRANSIT, ise.WAREHOUSE_STOCK,
             ise.SALES_TRANSIT, ise.CLOSED]
    for step in chain:
        ise.transition(scan_code=scan_code, to_state=step,
                       batch_id=batch_id, product_code=product_code,
                       design_no=design_no)
        if step == target:
            return


def _scan_code_for(design_no: str, product_code: str) -> str:
    return f"{product_code}|sr1|{design_no}"


def test_warehouse_stock_makes_stock_ok_true(client):
    """A line whose scan_code is at WAREHOUSE_STOCK is sellable."""
    _seed_purchase(design_no="JE400", product_code="EJL/SK-1")
    _seed_sales("ACME", [{"sku": "JE400", "qty": 1.0}])
    _seed_invoice_pricing("EJL/SK-1", 20.0, "USD")
    _match_product("EJL/SK-1")
    _match_customer("ACME")
    _advance_state(_scan_code_for("JE400", "EJL/SK-1"),
                   target=ise.WAREHOUSE_STOCK,
                   product_code="EJL/SK-1", design_no="JE400")

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_ok"]     is True
    assert body["lines"][0]["stock_status"] == "warehouse_stock"
    assert body["ready"] is True


# Authority separation (2026-06-22): stock state is ADVISORY for a proforma — a
# proforma may be issued before goods are received. Stock states must NOT appear in
# blocking_reasons; they appear in stock_advisories. The double-bill risk is owned by
# the over-bill fail-closed gate at draft readiness, not the preview stock gate.

def test_purchase_transit_is_advisory_not_blocker(client):
    _seed_purchase(design_no="JE401", product_code="EJL/PT-1")
    _seed_sales("ACME", [{"sku": "JE401", "qty": 1.0}])
    _seed_invoice_pricing("EJL/PT-1", 20.0, "USD")
    _match_product("EJL/PT-1")
    _match_customer("ACME")
    _advance_state(_scan_code_for("JE401", "EJL/PT-1"),
                   target=ise.PURCHASE_TRANSIT,
                   product_code="EJL/PT-1", design_no="JE401")

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_status"] == "purchase_transit"
    assert not any("PURCHASE_TRANSIT" in br for br in body["blocking_reasons"])
    assert any("PURCHASE_TRANSIT" in a for a in body["stock_advisories"])


def test_sales_transit_is_advisory_not_blocker(client):
    _seed_purchase(design_no="JE402", product_code="EJL/ST-1")
    _seed_sales("ACME", [{"sku": "JE402", "qty": 1.0}])
    _seed_invoice_pricing("EJL/ST-1", 20.0, "USD")
    _match_product("EJL/ST-1")
    _match_customer("ACME")
    _advance_state(_scan_code_for("JE402", "EJL/ST-1"),
                   target=ise.SALES_TRANSIT,
                   product_code="EJL/ST-1", design_no="JE402")

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_status"] == "sales_transit"
    assert not any("SALES_TRANSIT" in br for br in body["blocking_reasons"])
    assert any("SALES_TRANSIT" in a for a in body["stock_advisories"])


def test_closed_state_is_advisory_not_blocker(client):
    _seed_purchase(design_no="JE403", product_code="EJL/CL-1")
    _seed_sales("ACME", [{"sku": "JE403", "qty": 1.0}])
    _seed_invoice_pricing("EJL/CL-1", 20.0, "USD")
    _match_product("EJL/CL-1")
    _match_customer("ACME")
    _advance_state(_scan_code_for("JE403", "EJL/CL-1"),
                   target=ise.CLOSED,
                   product_code="EJL/CL-1", design_no="JE403")

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_status"] == "closed"
    assert not any("CLOSED" in br for br in body["blocking_reasons"])
    assert any("CLOSED" in a for a in body["stock_advisories"])


def test_missing_inventory_state_is_advisory_not_blocker(client):
    """Packing lines exist with scan_codes but were never seeded — advisory, not block."""
    _seed_purchase(design_no="JE404", product_code="EJL/MS-1")
    _seed_sales("ACME", [{"sku": "JE404", "qty": 1.0}])
    _seed_invoice_pricing("EJL/MS-1", 20.0, "USD")
    _match_product("EJL/MS-1")
    _match_customer("ACME")
    # NO seed_purchase_transit — inventory_state empty for this scan_code

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_ok"]     is False
    assert body["lines"][0]["stock_status"] == "missing_state"
    assert not any("inventory_state" in br for br in body["blocking_reasons"])
    assert any("inventory_state" in a for a in body["stock_advisories"])


def test_warehouse_dispatch_no_longer_required(client):
    """
    Regression: under the old logic, items at WAREHOUSE_STOCK without a
    DISPATCH scan would still report stock_ok=False.  After the fix,
    WAREHOUSE_STOCK alone makes stock_ok=True even when the warehouse
    inventory_current_location row says 'received', not 'dispatched'.
    """
    _seed_purchase(design_no="JE405", product_code="EJL/ND-1")
    _seed_sales("ACME", [{"sku": "JE405", "qty": 1.0}])
    _seed_invoice_pricing("EJL/ND-1", 20.0, "USD")
    _match_product("EJL/ND-1")
    _match_customer("ACME")
    sc = _scan_code_for("JE405", "EJL/ND-1")
    _advance_state(sc, target=ise.WAREHOUSE_STOCK,
                   product_code="EJL/ND-1", design_no="JE405")

    # Simulate a warehouse row that's only RECEIVED (not dispatched). The
    # legacy DISPATCH gate would have blocked here; the new state gate must
    # allow it.
    import sqlite3
    with sqlite3.connect(str(wdb._db_path)) as con:
        con.execute(
            """INSERT INTO inventory_current_location
               (id, batch_id, product_code, design_no, bag_id, pack_sr,
                scan_code, current_location, current_status, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ("dummy-id", BATCH, "EJL/ND-1", "JE405", "", 1.0,
             sc, "MAIN/RECV-01", "received",
             "2026-05-06T00:00:00+00:00", "test"),
        )

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is True
    assert body["lines"][0]["stock_ok"]     is True
    assert body["lines"][0]["stock_status"] == "warehouse_stock"


# ── /create endpoint shell ───────────────────────────────────────────────────

import json as _json

from app.services import proforma_invoice_link_db as pildb


def _wfirma_client_calls_blocked():
    """
    Patch wfirma_client primitives so any accidental live call fails the test.
    Returns the patcher list so tests can assert call counts.
    """
    from unittest.mock import patch as _p
    return [
        _p("app.services.wfirma_client.create_proforma_draft",
           side_effect=AssertionError("wfirma_client.create_proforma_draft must NOT be called")),
        _p("app.services.wfirma_client.create_customer",
           side_effect=AssertionError("wfirma_client.create_customer must NOT be called")),
        _p("app.services.wfirma_client.create_product",
           side_effect=AssertionError("wfirma_client.create_product must NOT be called")),
    ]


def test_create_blocked_when_preview_not_ready(client, storage):
    """If preview not ready → status=blocked, no draft row written."""
    _seed_purchase(design_no="JE901", product_code="EJL/CB-1")
    _seed_sales("ACME", [{"sku": "JE901", "qty": 1.0}])
    # No invoice pricing, no product match, no customer match → not ready

    patches = _wfirma_client_calls_blocked()
    for p in patches: p.start()
    try:
        body = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                           headers=_auth()).json()
    finally:
        for p in patches: p.stop()

    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert body["blocking_reasons"]
    # Nothing persisted
    assert pildb.get_draft(storage / "proforma_links.db", BATCH, "ACME") is None


def _seed_ready(design: str, product_code: str, sku_qty: float = 1.0,
                price: float = 100.0):
    """Helper: full ready-preview prerequisites for ACME."""
    _seed_purchase(design_no=design, product_code=product_code)
    # Sales price now wins. _seed_invoice_pricing remains as a red-herring
    # (proves cost data is ignored).
    _seed_sales("ACME", [{"sku": design, "qty": sku_qty,
                           "price": price, "currency": "USD"}])
    _seed_invoice_pricing(product_code, 9999.0, "USD")
    _match_product(product_code)
    _match_customer("ACME")
    _advance_state(_scan_code_for(design, product_code),
                   target=ise.WAREHOUSE_STOCK,
                   product_code=product_code, design_no=design)


def _gate_on():
    from unittest.mock import patch as _p
    return _p.object(settings, "wfirma_create_proforma_allowed", True)


def test_create_gate_off_blocks_ready_preview_no_wfirma_call(client, storage):
    """Gate off + ready preview → blocked with explicit reason; no wFirma call."""
    _seed_ready("JE902", "EJL/CC-1", price=100.0, sku_qty=2.0)

    patches = _wfirma_client_calls_blocked()
    for p in patches: p.start()
    try:
        # Default: settings.wfirma_create_proforma_allowed == False
        body = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                           headers=_auth()).json()
    finally:
        for p in patches: p.stop()

    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("WFIRMA_CREATE_PROFORMA_ALLOWED" in br
               for br in body["blocking_reasons"])
    # Gate-off path must not persist a draft either
    assert pildb.get_draft(storage / "proforma_links.db", BATCH, "ACME") is None


def test_create_gate_on_calls_create_proforma_draft_once(client, storage):
    """Gate on + ready → exactly one wfirma_client.create_proforma_draft call."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_ready("JE903", "EJL/IDM-1", price=50.0)

    fake_result = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-99")
    with _gate_on(), _p.object(wc, "create_proforma_draft",
                                return_value=fake_result) as mock_call:
        body = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                           headers=_auth()).json()
    assert mock_call.call_count == 1
    assert body["ok"] is True
    assert body["status"] == "issued"
    assert body["wfirma_proforma_id"] == "WF-99"
    # caller-controlled fields surface only batch_id + client_name
    req = mock_call.call_args.args[0]
    assert req.client_name == "ACME"
    assert req.currency    == "USD"


def test_create_issued_draft_returns_skipped_no_call(client, storage):
    """An already-issued draft short-circuits with skipped; no wFirma call."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_ready("JE903b", "EJL/IDS-1", price=50.0)
    fake_ok = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-100")

    with _gate_on(), _p.object(wc, "create_proforma_draft", return_value=fake_ok) as mock1:
        r1 = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                         headers=_auth()).json()
    assert r1["status"] == "issued"
    assert mock1.call_count == 1

    # Second call: should NOT invoke wfirma_client at all.
    fake_should_not_fire = _p.object(
        wc, "create_proforma_draft",
        side_effect=AssertionError("must not be called when issued exists"),
    )
    with _gate_on(), fake_should_not_fire:
        r2 = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                         headers=_auth()).json()
    assert r2["status"] == "skipped"
    assert r2["existing_status"]    == "issued"
    assert r2["wfirma_proforma_id"] == "WF-100"
    assert r2["draft_id"]           == r1["draft_id"]


def test_create_failure_marks_failed_and_is_retryable(client, storage):
    """wFirma returns ok=false → draft.failed; second call retries successfully."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_ready("JE906", "EJL/RR-1", price=30.0)
    fake_fail = wc.ProformaResult(ok=False, error="wFirma 502 transient")
    fake_ok   = wc.ProformaResult(ok=True,  wfirma_invoice_id="WF-RTY-1")

    with _gate_on(), _p.object(wc, "create_proforma_draft", return_value=fake_fail):
        r1 = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                         headers=_auth()).json()
    assert r1["status"] == "failed"
    assert r1["error"]
    draft = pildb.get_draft(storage / "proforma_links.db", BATCH, "ACME")
    assert draft.status == "failed"
    assert draft.wfirma_proforma_id is None

    # Retry: same path, same draft row, this time succeeds.
    with _gate_on(), _p.object(wc, "create_proforma_draft", return_value=fake_ok):
        r2 = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                         headers=_auth()).json()
    assert r2["status"] == "issued"
    assert r2["wfirma_proforma_id"] == "WF-RTY-1"
    assert r2["draft_id"] == r1["draft_id"]
    final = pildb.get_draft(storage / "proforma_links.db", BATCH, "ACME")
    assert final.status == "issued"
    assert final.wfirma_proforma_id == "WF-RTY-1"


def test_create_success_persists_id_and_source_lines_json(client, storage):
    """Success path persists wfirma_proforma_id AND source_lines_json on draft."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_ready("JE904", "EJL/NC-1", price=70.0, sku_qty=2.0)
    fake_ok = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-PERSIST")

    with _gate_on(), _p.object(wc, "create_proforma_draft", return_value=fake_ok):
        body = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                           headers=_auth()).json()
    assert body["status"] == "issued"

    draft = pildb.get_draft(storage / "proforma_links.db", BATCH, "ACME")
    assert draft.status == "issued"
    assert draft.wfirma_proforma_id == "WF-PERSIST"
    assert draft.currency == "USD"
    lines = _json.loads(draft.source_lines_json)
    assert len(lines) == 1
    assert lines[0]["product_code"] == "EJL/NC-1"
    assert lines[0]["design_no"]    == "JE904"
    assert lines[0]["qty"]          == 2.0
    assert lines[0]["unit_price"]   == 70.0
    assert lines[0]["currency"]     == "USD"


def test_create_caller_payload_cannot_override_lines_or_amounts(client, storage):
    """A caller-supplied JSON body must be ignored — payload comes from preview."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_ready("JE907", "EJL/PC-1", price=42.0, sku_qty=1.0)
    fake_ok = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-PC-1")

    malicious_body = {
        "lines": [{"product_code": "ATTACKER", "qty": 9999, "unit_price": 0.01}],
        "currency":     "PLN",
        "client_name":  "EVIL",
    }
    with _gate_on(), _p.object(wc, "create_proforma_draft",
                                return_value=fake_ok) as mock_call:
        body = client.post(
            f"/api/v1/proforma/create/{BATCH}/ACME",
            headers=_auth(),
            json=malicious_body,
        ).json()
    assert body["status"] == "issued"
    req = mock_call.call_args.args[0]
    # Server-derived values must override anything in the body
    assert req.client_name      == "ACME"
    assert req.currency         == "USD"
    assert len(req.lines)        == 1
    assert req.lines[0].product_code == "EJL/PC-1"
    assert req.lines[0].qty           == 1.0
    assert req.lines[0].unit_price    == 42.0


def _ready_preview_dict(client_name="ACME", product_code="EJL/X-1",
                         design_no="X1", currency="USD", unit_price=10.0):
    """Synthetic preview dict that says ready=true. Used to bypass the
    preview's own gate so defensive checks downstream can be exercised."""
    return {
        "ok":               True,
        "batch_id":         BATCH,
        "client_name":      client_name,
        "currency":         currency,
        "exchange_rate":    None,
        "draft_ready":      True,
        "ready":            True,
        "blocking_reasons": [],
        "export_blockers":  [],
        "lines": [{
            "product_code":  product_code,
            "design_no":     design_no,
            "qty":           1.0,
            "unit_price":    unit_price,
            "currency":      currency,
            "exchange_rate": None,
            "line_value":    unit_price,
            "stock_ok":      True,
            "stock_status":  "warehouse_stock",
            "product_match": True,
        }],
    }


def test_create_blocked_when_local_customer_id_missing(client, storage):
    """
    Defensive: if preview reports ready=true but the local mapping row has
    no wfirma_customer_id, _build_proforma_request must refuse and the route
    must surface 'blocked' — not a 500 — and must NOT call wfirma_client.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc
    from app.api import routes_proforma as rp

    # Mapping row with EMPTY wfirma_customer_id; product mapping fine.
    wfdb.upsert_customer(client_name="ACME", wfirma_customer_id="",
                         match_status="matched")
    wfdb.upsert_product(product_code="EJL/X-1", wfirma_product_id="GID-1",
                        sync_status="matched")

    fake_preview = _ready_preview_dict()
    with (
        _gate_on(),
        _p.object(rp, "_build_preview", return_value=fake_preview),
        _p.object(wc, "create_proforma_draft",
                  side_effect=AssertionError("must not be called")),
    ):
        body = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                           headers=_auth()).json()
    assert body["status"] == "blocked"
    assert any("wfirma_customer_id" in br for br in body["blocking_reasons"])


def test_create_blocked_when_local_product_id_missing(client, storage):
    """Defensive: any line missing wfirma_product_id → blocked, no live call."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc
    from app.api import routes_proforma as rp

    wfdb.upsert_customer(client_name="ACME", wfirma_customer_id="CID-1",
                         country="PL",
                         match_status="matched")
    # Product mapping with EMPTY wfirma_product_id
    wfdb.upsert_product(product_code="EJL/X-1", wfirma_product_id="",
                        sync_status="matched")

    fake_preview = _ready_preview_dict()
    with (
        _gate_on(),
        _p.object(rp, "_build_preview", return_value=fake_preview),
        _p.object(wc, "create_proforma_draft",
                  side_effect=AssertionError("must not be called")),
    ):
        body = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                           headers=_auth()).json()
    assert body["status"] == "blocked"
    assert any("wfirma_product_id" in br for br in body["blocking_reasons"])


def test_create_failure_does_not_call_create_again_on_retry_with_locked_draft(
    client, storage,
):
    """Sanity: a failed draft is retried via the same locked path — one call per attempt."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_ready("JE910", "EJL/LCK-1", price=12.0)
    with _gate_on(), _p.object(
        wc, "create_proforma_draft",
        return_value=wc.ProformaResult(ok=False, error="boom"),
    ) as mock_fail:
        client.post(f"/api/v1/proforma/create/{BATCH}/ACME", headers=_auth())
    assert mock_fail.call_count == 1

    with _gate_on(), _p.object(
        wc, "create_proforma_draft",
        return_value=wc.ProformaResult(ok=True, wfirma_invoice_id="WF-OK"),
    ) as mock_ok:
        client.post(f"/api/v1/proforma/create/{BATCH}/ACME", headers=_auth())
    assert mock_ok.call_count == 1


def test_create_blocked_does_not_persist_draft(client, storage):
    """Even when preview is partially valid, blocked status writes nothing."""
    # Stock is at PURCHASE_TRANSIT — readiness blocked, no draft expected
    _seed_purchase(design_no="JE905", product_code="EJL/BD-1")
    _seed_sales("ACME", [{"sku": "JE905", "qty": 1.0}])
    _seed_invoice_pricing("EJL/BD-1", 25.0, "USD")
    _match_product("EJL/BD-1")
    _match_customer("ACME")
    _advance_state(_scan_code_for("JE905", "EJL/BD-1"),
                   target=ise.PURCHASE_TRANSIT,
                   product_code="EJL/BD-1", design_no="JE905")

    body = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["status"] == "blocked"
    assert pildb.get_draft(storage / "proforma_links.db", BATCH, "ACME") is None


# ── Idempotency under concurrency ────────────────────────────────────────────

def test_concurrent_upsert_helper_no_duplicates(tmp_path):
    """
    Direct helper-level race: 8 threads call upsert_pending_draft with the
    same (batch_id, client_name). Exactly one must win; all others observe
    was_created=False; only one row may exist in the table.

    Tests the helper, not the HTTP route — TestClient is single-threaded so
    a true race needs sub-route invocation.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "proforma_links.db"
    pildb.init_db(db_path)

    N = 8
    barrier = threading.Barrier(N)

    def fire():
        barrier.wait()  # all threads block, then race the INSERT
        return pildb.upsert_pending_draft(
            db_path,
            batch_id          = "B_RACE",
            client_name       = "ACME",
            currency          = "USD",
            exchange_rate     = None,
            source_lines_json = "[]",
        )

    with ThreadPoolExecutor(max_workers=N) as ex:
        results = [f.result() for f in [ex.submit(fire) for _ in range(N)]]

    creators = [r for r in results if r[1]]   # was_created == True
    losers   = [r for r in results if not r[1]]
    assert len(creators) == 1, f"expected 1 winner, got {len(creators)}"
    assert len(losers)   == N - 1

    # All winners and losers must reference the SAME row id
    winning_id = creators[0][0].id
    for draft, _ in losers:
        assert draft.id == winning_id

    # And only one row exists in the table
    with sqlite3.connect(str(db_path)) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM proforma_drafts "
            "WHERE batch_id=? AND client_name=?",
            ("B_RACE", "ACME"),
        ).fetchone()[0]
    assert n == 1


def test_concurrent_upsert_no_integrity_error_leaks(tmp_path):
    """No sqlite3.IntegrityError must escape the helper under contention."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "proforma_links.db"
    pildb.init_db(db_path)

    N = 16
    barrier = threading.Barrier(N)
    exceptions: list = []

    def fire():
        try:
            barrier.wait()
            pildb.upsert_pending_draft(
                db_path,
                batch_id          = "B_NOERR",
                client_name       = "ACME",
                currency          = "USD",
                exchange_rate     = None,
                source_lines_json = "[]",
            )
        except Exception as exc:
            exceptions.append(exc)

    with ThreadPoolExecutor(max_workers=N) as ex:
        for _ in range(N):
            ex.submit(fire)

    assert exceptions == [], f"helper leaked exceptions: {exceptions}"


def test_create_post_race_response_shape(client, storage):
    """
    Sequential gate-on calls — first issues, second returns skipped with
    existing_status='issued'.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_ready("JE906r", "EJL/RR-1", price=30.0)
    fake_ok = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-SHAPE")

    with _gate_on(), _p.object(wc, "create_proforma_draft", return_value=fake_ok):
        r1 = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                         headers=_auth()).json()

    fake_should_not_fire = _p.object(
        wc, "create_proforma_draft",
        side_effect=AssertionError("must not be called when issued exists"),
    )
    with _gate_on(), fake_should_not_fire:
        r2 = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                         headers=_auth()).json()
    assert r1["status"] == "issued"
    assert r2["status"] == "skipped"
    assert r2["existing_status"] == "issued"
    assert r2["draft_id"] == r1["draft_id"]


# ── /refresh-line-names endpoint ─────────────────────────────────────────────

_PROFORMA_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>465611619</id>
      <type>proforma</type>
      <invoicecontents>
        <invoicecontent>
          <id>1495642083</id>
          <name>Pierścionek (EJL/25-26/1274-3)</name>
          <count>1.0000</count>
          <price>173.00</price>
          <unit>szt.</unit>
          <good><id>48611875</id></good>
          <vat_code><id>222</id></vat_code>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""

_FINAL_INVOICE_FIXTURE = _PROFORMA_FIXTURE.replace(
    "<type>proforma</type>", "<type>normal</type>"
)


def _seed_master_for_refresh(product_code: str, wfirma_id: str,
                             description_line: str):
    wfdb.upsert_product(
        product_code=product_code,
        wfirma_product_id=wfirma_id,
        sync_status="matched",
    )
    ddb.upsert_product_description(
        product_code      = product_code,
        item_type         = "RING",
        name_pl           = "Pierścionek",
        description_pl    = description_line.split(" / ")[0],
        description_en    = description_line.split(" / ")[-1],
        material_pl       = "metal szlachetny",
        purpose_pl        = "Ozdoba",
        description_block = description_line,
        description_line  = description_line,
        source            = "auto",
    )


def _refresh_gate_on():
    from unittest.mock import patch as _p
    return _p.object(settings, "wfirma_edit_invoice_allowed", True)


def test_refresh_blocked_when_flag_off(client, storage):
    """Flag off → blocked, no wFirma call (fetch never invoked)."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    fetch = _p.object(wc, "fetch_invoice_xml",
                      side_effect=AssertionError("must not be called when flag off"))
    edit  = _p.object(wc, "edit_invoice_line_name",
                      side_effect=AssertionError("must not edit when flag off"))
    with fetch, edit:
        body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                           headers=_auth()).json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("WFIRMA_EDIT_INVOICE_ALLOWED" in br for br in body["blocking_reasons"])


def test_refresh_blocked_when_invoice_is_not_proforma(client, storage):
    """type != proforma → blocked before any edit; no edits attempted."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    edit = _p.object(wc, "edit_invoice_line_name",
                     side_effect=AssertionError("must not edit non-proforma"))
    with _refresh_gate_on(), \
         _p.object(wc, "fetch_invoice_xml", return_value=_FINAL_INVOICE_FIXTURE), \
         edit:
        body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                           headers=_auth()).json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("normal" in br for br in body["blocking_reasons"])


def test_refresh_blocked_when_product_mapping_missing(client, storage):
    """No wfirma_products row for good_id → blocked, no edits attempted."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    edit = _p.object(wc, "edit_invoice_line_name",
                     side_effect=AssertionError("must not edit when mapping missing"))
    with _refresh_gate_on(), \
         _p.object(wc, "fetch_invoice_xml", return_value=_PROFORMA_FIXTURE), \
         edit:
        body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                           headers=_auth()).json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert body["errors"]
    assert any("48611875" in (e.get("error") or "") for e in body["errors"])


def test_refresh_blocked_when_description_block_missing(client, storage):
    """wfirma_products mapped but no product_descriptions row → blocked."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    wfdb.upsert_product(
        product_code="EJL/25-26/1274-3",
        wfirma_product_id="48611875",
        sync_status="matched",
    )
    edit = _p.object(wc, "edit_invoice_line_name",
                     side_effect=AssertionError("must not edit when block missing"))
    with _refresh_gate_on(), \
         _p.object(wc, "fetch_invoice_xml", return_value=_PROFORMA_FIXTURE), \
         edit:
        body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                           headers=_auth()).json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("product_descriptions" in (e.get("error") or "")
               for e in body["errors"])


def test_refresh_updates_one_stale_line(client, storage):
    """Single stale line → one edit_invoice_line_name call, status=ok, updated=1."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    correct = ("pierścionek ze złota próby 585 z diamentami laboratoryjnymi / "
               "Lab Grown Diamond Studded 14KT Gold Jewellery RING")
    _seed_master_for_refresh("EJL/25-26/1274-3", "48611875", correct)

    edits: list = []
    def fake_edit(invoice_id, ic_xml, new_name):
        edits.append((invoice_id, ic_xml, new_name))
        return {"invoice_id": invoice_id, "invoicecontent_id": "1495642083",
                "new_name": new_name, "raw_response": ""}

    # Verify-after-edit: 1st fetch returns the stale fixture, 2nd fetch
    # returns the post-edit XML with the new name.
    after_xml = _PROFORMA_FIXTURE.replace(
        "<name>Pierścionek (EJL/25-26/1274-3)</name>",
        f"<name>{correct}</name>",
    )
    fetch_calls = {"n": 0}
    def fake_fetch(invoice_id):
        fetch_calls["n"] += 1
        return _PROFORMA_FIXTURE if fetch_calls["n"] == 1 else after_xml

    with _refresh_gate_on(), \
         _p.object(wc, "fetch_invoice_xml", side_effect=fake_fetch), \
         _p.object(wc, "edit_invoice_line_name", side_effect=fake_edit):
        body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                           headers=_auth()).json()
    assert body["ok"] is True
    assert body["status"] == "ok"
    assert body["checked"] == 1
    assert body["updated"] == 1
    assert body["skipped"] == 0
    assert body["errors"]         == []
    assert body["verify_errors"]  == []
    assert fetch_calls["n"] == 2, "verify-after-edit must re-fetch the proforma"
    assert len(edits) == 1
    inv_id, ic_xml, new_name = edits[0]
    assert inv_id == "465611619"
    assert new_name == correct
    # The XML passed to edit must include the full line restated.
    assert "<id>1495642083</id>" in ic_xml
    assert "<good><id>48611875</id></good>" in ic_xml
    assert "<vat_code><id>222</id></vat_code>" in ic_xml


def test_refresh_skips_already_correct_line(client, storage):
    """If current name == correct name → no edit call, skipped=1."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_master_for_refresh(
        "EJL/25-26/1274-3", "48611875",
        "Pierścionek (EJL/25-26/1274-3)",          # matches the fixture <name>
    )
    edit = _p.object(wc, "edit_invoice_line_name",
                     side_effect=AssertionError("must not edit when already correct"))
    with _refresh_gate_on(), \
         _p.object(wc, "fetch_invoice_xml", return_value=_PROFORMA_FIXTURE), \
         edit:
        body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                           headers=_auth()).json()
    assert body["ok"] is True
    assert body["status"] == "ok"
    assert body["checked"] == 1
    assert body["updated"] == 0
    assert body["skipped"] == 1


def test_refresh_does_not_call_proforma_to_invoice(client, storage):
    """Conversion path must NEVER be invoked from refresh."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    correct = "X / Y"
    _seed_master_for_refresh("EJL/25-26/1274-3", "48611875", correct)
    after_xml = _PROFORMA_FIXTURE.replace(
        "<name>Pierścionek (EJL/25-26/1274-3)</name>",
        f"<name>{correct}</name>",
    )
    seq = iter([_PROFORMA_FIXTURE, after_xml])

    # If proforma_to_invoice exists in this codebase, ensure refresh never
    # imports/uses it. Patch the module's primary entrypoint defensively.
    try:
        from app.services import proforma_to_invoice as _p2i  # noqa: F401
        guard = _p.object(_p2i, "build_final_invoice_xml",
                          side_effect=AssertionError("must not convert"))
    except Exception:
        guard = None

    with _refresh_gate_on(), \
         _p.object(wc, "fetch_invoice_xml", side_effect=lambda _id: next(seq)), \
         _p.object(wc, "edit_invoice_line_name",
                   return_value={"invoice_id": "465611619",
                                 "invoicecontent_id": "1495642083",
                                 "new_name": correct, "raw_response": ""}):
        if guard is not None:
            with guard:
                body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                                   headers=_auth()).json()
        else:
            body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                               headers=_auth()).json()
    assert body["status"] == "ok"


def test_refresh_does_not_mutate_local_proforma_drafts(client, storage):
    """Refresh route must not touch proforma_drafts rows."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    correct = "x / y"
    _seed_master_for_refresh("EJL/25-26/1274-3", "48611875", correct)
    after_xml = _PROFORMA_FIXTURE.replace(
        "<name>Pierścionek (EJL/25-26/1274-3)</name>",
        f"<name>{correct}</name>",
    )
    seq = iter([_PROFORMA_FIXTURE, after_xml])

    proforma_db = storage / "proforma_links.db"
    before = pildb.get_draft(proforma_db, "no-such-batch", "no-such-client")
    assert before is None

    with _refresh_gate_on(), \
         _p.object(wc, "fetch_invoice_xml", side_effect=lambda _id: next(seq)), \
         _p.object(wc, "edit_invoice_line_name",
                   return_value={"invoice_id": "465611619",
                                 "invoicecontent_id": "1495642083",
                                 "new_name": correct, "raw_response": ""}):
        client.post("/api/v1/proforma/465611619/refresh-line-names",
                    headers=_auth()).json()
    after = pildb.get_draft(proforma_db, "no-such-batch", "no-such-client")
    assert after is None


def test_refresh_failed_verification_when_persisted_name_does_not_match(client, storage):
    """
    edit_invoice_line_name returns OK, but the post-edit re-fetch shows
    the line name was NOT actually updated. Route must surface this as
    failed_verification and report expected vs actual.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    correct = "CORRECT NAME / Lab"
    _seed_master_for_refresh("EJL/25-26/1274-3", "48611875", correct)

    # 1st fetch: stale fixture. 2nd fetch (verify): same stale name —
    # simulating wFirma silently no-op'ing the edit.
    seq = iter([_PROFORMA_FIXTURE, _PROFORMA_FIXTURE])

    with _refresh_gate_on(), \
         _p.object(wc, "fetch_invoice_xml", side_effect=lambda _id: next(seq)), \
         _p.object(wc, "edit_invoice_line_name",
                   return_value={"invoice_id": "465611619",
                                 "invoicecontent_id": "1495642083",
                                 "new_name": correct, "raw_response": ""}):
        body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                           headers=_auth()).json()
    assert body["ok"] is False
    assert body["status"] == "failed_verification"
    assert body["updated"] == 1
    assert len(body["verify_errors"]) == 1
    ve = body["verify_errors"][0]
    assert ve["line_id"]      == "1495642083"
    assert ve["expected"]     == correct
    assert ve["actual"]       == "Pierścionek (EJL/25-26/1274-3)"


def test_refresh_skipped_only_does_not_call_verify_fetch(client, storage):
    """
    All lines already correct → updated=0; verify-after-edit must NOT
    re-fetch (no edits to verify). Total fetch_invoice_xml calls = 1.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_master_for_refresh(
        "EJL/25-26/1274-3", "48611875",
        "Pierścionek (EJL/25-26/1274-3)",
    )
    fetch_calls = {"n": 0}
    def fake_fetch(_id):
        fetch_calls["n"] += 1
        return _PROFORMA_FIXTURE

    with _refresh_gate_on(), \
         _p.object(wc, "fetch_invoice_xml", side_effect=fake_fetch), \
         _p.object(wc, "edit_invoice_line_name",
                   side_effect=AssertionError("no edits expected")):
        body = client.post("/api/v1/proforma/465611619/refresh-line-names",
                           headers=_auth()).json()
    assert body["ok"] is True
    assert body["status"]  == "ok"
    assert body["checked"] == 1
    assert body["updated"] == 0
    assert body["skipped"] == 1
    assert fetch_calls["n"] == 1, "no verify re-fetch when nothing was edited"


# ── VAT context selection in _build_proforma_request ────────────────────────

def _seed_ready_pl(design="JE_VAT_PL", product_code="EJL/VAT-PL"):
    _seed_purchase(design_no=design, product_code=product_code)
    _seed_sales("PL Customer", [{"sku": design, "qty": 1.0}])
    _seed_invoice_pricing(product_code, 100.0, "USD")
    _match_product(product_code)
    _match_customer("PL Customer", country="PL")
    _advance_state(_scan_code_for(design, product_code),
                   target=ise.WAREHOUSE_STOCK,
                   product_code=product_code, design_no=design)


def _seed_ready_eu(design="JE_VAT_EU", product_code="EJL/VAT-EU"):
    _seed_purchase(design_no=design, product_code=product_code)
    _seed_sales("Juliany EOOD", [{"sku": design, "qty": 1.0}])
    _seed_invoice_pricing(product_code, 100.0, "USD")
    _match_product(product_code)
    _match_customer("Juliany EOOD", country="BG", vat_id="BG121281167")
    _advance_state(_scan_code_for(design, product_code),
                   target=ise.WAREHOUSE_STOCK,
                   product_code=product_code, design_no=design)


def _seed_ready_eu_no_vat(design="JE_VAT_EU2", product_code="EJL/VAT-EU2"):
    _seed_purchase(design_no=design, product_code=product_code)
    _seed_sales("DE Customer", [{"sku": design, "qty": 1.0}])
    _seed_invoice_pricing(product_code, 100.0, "USD")
    _match_product(product_code)
    _match_customer("DE Customer", country="DE", vat_id="")
    _advance_state(_scan_code_for(design, product_code),
                   target=ise.WAREHOUSE_STOCK,
                   product_code=product_code, design_no=design)


def test_create_pl_customer_uses_vat_23(client, storage):
    """PL domestic customer → vat_code_id resolved to '23' → '222'."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc
    _seed_ready_pl()
    fake_ok = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-PL")
    with _gate_on(), _p.object(wc, "create_proforma_draft",
                                return_value=fake_ok) as mock_call:
        body = client.post(f"/api/v1/proforma/create/{BATCH}/PL%20Customer",
                           headers=_auth()).json()
    assert body["status"] == "issued"
    req = mock_call.call_args.args[0]
    assert req.vat_code_id == "222"   # PL 23%


def test_create_eu_customer_with_vat_uses_wdt(client, storage):
    """EU non-PL with VAT id → vat_code_id='228' (WDT)."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc
    _seed_ready_eu()
    fake_ok = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-EU")
    with _gate_on(), _p.object(wc, "create_proforma_draft",
                                return_value=fake_ok) as mock_call:
        body = client.post(f"/api/v1/proforma/create/{BATCH}/Juliany%20EOOD",
                           headers=_auth()).json()
    assert body["status"] == "issued"
    req = mock_call.call_args.args[0]
    assert req.vat_code_id == "228"   # WDT
    # AND the customer's country/vat actually drove the decision.
    assert req.client_name == "Juliany EOOD"


def test_create_eu_customer_without_vat_blocked(client, storage):
    """EU non-PL without VAT id must surface as blocked, not silently 23%."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc
    _seed_ready_eu_no_vat()
    # Also stub search_customer fallback so the route can't recover the
    # missing VAT id from wFirma master and slip through to issued.
    with _gate_on(), \
         _p.object(wc, "search_customer", return_value=None), \
         _p.object(wc, "create_proforma_draft",
                   side_effect=AssertionError("must not call create when blocked")):
        body = client.post(f"/api/v1/proforma/create/{BATCH}/DE%20Customer",
                           headers=_auth()).json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("vat decision blocked" in br or "no VAT id" in br
               for br in body["blocking_reasons"])


# ---------------------------------------------------------------------------
# cancel-issued-for-reissue route
# ---------------------------------------------------------------------------

_CANCEL_CONFIRM = "YES_DELETE_AND_REISSUE_ONE_PROFORMA"
_CANCEL_BATCH   = "BATCH_CANCEL_TEST"
_CANCEL_CLIENT  = "ACME"


def _gate_delete_on():
    from unittest.mock import patch as _p
    return _p.object(settings, "wfirma_delete_invoice_allowed", True)


def _seed_issued_draft(storage, wfirma_id: str = "465611619") -> None:
    """Write an issued proforma_drafts row directly."""
    db = storage / "proforma_links.db"
    pildb.init_db(db)
    pildb.upsert_pending_draft(
        db,
        batch_id          = _CANCEL_BATCH,
        client_name       = _CANCEL_CLIENT,
        currency          = "USD",
        exchange_rate     = None,
        source_lines_json = "[]",
    )
    pildb.mark_draft_issued(db, _CANCEL_BATCH, _CANCEL_CLIENT,
                            wfirma_proforma_id=wfirma_id)


def _cancel_url(batch: str = _CANCEL_BATCH,
                client: str = _CANCEL_CLIENT) -> str:
    return f"/api/v1/proforma/cancel-issued-for-reissue/{batch}/{client}"


def test_cancel_blocked_when_flag_off(client, storage):
    """WFIRMA_DELETE_INVOICE_ALLOWED=false → blocked before any wFirma call."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_issued_draft(storage)
    with _p.object(wc, "delete_invoice",
                   side_effect=AssertionError("must not call delete when flag off")):
        body = client.post(
            _cancel_url(),
            params={"confirm": _CANCEL_CONFIRM},
            headers=_auth(),
        ).json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("WFIRMA_DELETE_INVOICE_ALLOWED" in br
               for br in body["blocking_reasons"])


def test_cancel_blocked_wrong_confirm(client, storage):
    """Wrong confirm string → blocked; no wFirma call."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_issued_draft(storage)
    with _gate_delete_on(), \
         _p.object(wc, "delete_invoice",
                   side_effect=AssertionError("must not call delete on bad confirm")):
        body = client.post(
            _cancel_url(),
            params={"confirm": "WRONG_STRING"},
            headers=_auth(),
        ).json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("confirm" in br.lower() for br in body["blocking_reasons"])


def test_cancel_blocked_no_draft(client, storage):
    """No local draft for batch/client → blocked."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    with _gate_delete_on(), \
         _p.object(wc, "delete_invoice",
                   side_effect=AssertionError("must not call delete — no draft")):
        body = client.post(
            _cancel_url(),
            params={"confirm": _CANCEL_CONFIRM},
            headers=_auth(),
        ).json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("no local draft" in br for br in body["blocking_reasons"])


def test_cancel_blocked_non_issued_status(client, storage):
    """Draft exists but status != issued → blocked."""
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    db = storage / "proforma_links.db"
    pildb.init_db(db)
    pildb.upsert_pending_draft(
        db,
        batch_id=_CANCEL_BATCH, client_name=_CANCEL_CLIENT,
        currency="USD", exchange_rate=None, source_lines_json="[]",
    )
    # status is pending_local (not issued)
    with _gate_delete_on(), \
         _p.object(wc, "delete_invoice",
                   side_effect=AssertionError("must not delete non-issued")):
        body = client.post(
            _cancel_url(),
            params={"confirm": _CANCEL_CONFIRM},
            headers=_auth(),
        ).json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("pending_local" in br or "issued" in br
               for br in body["blocking_reasons"])


def test_cancel_delete_failure_leaves_local_issued(client, storage):
    """
    wFirma delete raises → local draft must remain 'issued'.
    The draft is not touched when the remote call fails.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_issued_draft(storage, wfirma_id="465611619")
    db = storage / "proforma_links.db"

    with _gate_delete_on(), \
         _p.object(wc, "delete_invoice",
                   side_effect=RuntimeError("wFirma returned NOT_FOUND")):
        body = client.post(
            _cancel_url(),
            params={"confirm": _CANCEL_CONFIRM},
            headers=_auth(),
        ).json()

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert "local draft unchanged" in body["error"]
    # Local row must still be issued.
    draft = pildb.get_draft(db, _CANCEL_BATCH, _CANCEL_CLIENT)
    assert draft is not None
    assert draft.status == "issued"
    assert draft.wfirma_proforma_id == "465611619"


def test_cancel_success_marks_draft_failed_retryable(client, storage):
    """
    Happy path: delete succeeds → response is cancelled_for_reissue,
    local draft status becomes 'failed' (retryable), wfirma_proforma_id
    cleared, notes record the deleted id.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_issued_draft(storage, wfirma_id="465611619")
    db = storage / "proforma_links.db"

    with _gate_delete_on(), \
         _p.object(wc, "delete_invoice",
                   return_value={"ok": True, "wfirma_invoice_id": "465611619"}):
        body = client.post(
            _cancel_url(),
            params={"confirm": _CANCEL_CONFIRM},
            headers=_auth(),
        ).json()

    assert body["ok"] is True
    assert body["status"] == "cancelled_for_reissue"
    assert body["deleted_wfirma_id"] == "465611619"
    assert body["local_status"] == "failed"

    draft = pildb.get_draft(db, _CANCEL_BATCH, _CANCEL_CLIENT)
    assert draft is not None
    assert draft.status == "failed"
    assert draft.wfirma_proforma_id is None
    assert "465611619" in (draft.notes or "")


def test_cancel_then_create_reissue_path(client, storage):
    """
    After cancel, a POST /create on the same batch/client is accepted
    (failed draft is retryable) and issues a new proforma id.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    _seed_ready("JE_REISSUE", "EJL/RI-1", price=200.0)
    db = storage / "proforma_links.db"

    # Step 1: issue first proforma.
    fake_ok_1 = wc.ProformaResult(ok=True, wfirma_invoice_id="OLD-001")
    with _gate_on(), _p.object(wc, "create_proforma_draft",
                                return_value=fake_ok_1):
        r1 = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                         headers=_auth()).json()
    assert r1["status"] == "issued"
    assert r1["wfirma_proforma_id"] == "OLD-001"

    # Step 2: cancel it.
    with _gate_delete_on(), \
         _p.object(wc, "delete_invoice",
                   return_value={"ok": True, "wfirma_invoice_id": "OLD-001"}):
        rc = client.post(
            f"/api/v1/proforma/cancel-issued-for-reissue/{BATCH}/ACME",
            params={"confirm": _CANCEL_CONFIRM},
            headers=_auth(),
        ).json()
    assert rc["ok"] is True
    assert rc["deleted_wfirma_id"] == "OLD-001"

    # Step 3: reissue.
    fake_ok_2 = wc.ProformaResult(ok=True, wfirma_invoice_id="NEW-002")
    with _gate_on(), _p.object(wc, "create_proforma_draft",
                                return_value=fake_ok_2):
        r2 = client.post(f"/api/v1/proforma/create/{BATCH}/ACME",
                         headers=_auth()).json()
    assert r2["status"] == "issued"
    assert r2["wfirma_proforma_id"] == "NEW-002"
    draft = pildb.get_draft(db, BATCH, "ACME")
    assert draft.wfirma_proforma_id == "NEW-002"


# ---------------------------------------------------------------------------
# adopt-issued route
# ---------------------------------------------------------------------------

_ADOPT_BATCH  = "BATCH_ADOPT_TEST"
_ADOPT_CLIENT = "ACME"
_ADOPT_WF_ID  = "465611619"

# Proforma XML returned by wFirma for adopt tests — includes contractor node
_ADOPT_PROFORMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>465611619</id>
      <type>proforma</type>
      <contractor><id>189309475</id></contractor>
      <invoicecontents>
        <invoicecontent>
          <id>1495642083</id>
          <name>Pierścionek (EJL/25-26/1274-3)</name>
          <count>1.0000</count>
          <price>173.00</price>
          <good><id>48611875</id></good>
          <vat_code><id>222</id></vat_code>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""

_ADOPT_NON_PROFORMA_XML = _ADOPT_PROFORMA_XML.replace(
    "<type>proforma</type>", "<type>normal</type>"
)


def _adopt_url(batch: str = _ADOPT_BATCH, client: str = _ADOPT_CLIENT) -> str:
    return f"/api/v1/proforma/adopt-issued/{batch}/{client}"


def test_adopt_happy_path_creates_issued_draft(client, storage):
    """
    Happy path: valid proforma XML, no local draft → created with status=issued.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    db = storage / "proforma_links.db"

    with _p.object(wc, "fetch_invoice_xml", return_value=_ADOPT_PROFORMA_XML):
        body = client.post(
            _adopt_url(),
            json={"wfirma_proforma_id": _ADOPT_WF_ID, "reason": "pre-tracking adoption"},
            headers=_auth(),
        ).json()

    assert body["ok"] is True, body
    assert body["status"] == "adopted"
    assert body["was_created"] is True
    assert body["wfirma_proforma_id"] == _ADOPT_WF_ID

    draft = pildb.get_draft(db, _ADOPT_BATCH, _ADOPT_CLIENT)
    assert draft is not None
    assert draft.status == "issued"
    assert draft.wfirma_proforma_id == _ADOPT_WF_ID


def test_adopt_idempotent_same_wfirma_id(client, storage):
    """
    Second call with same wfirma_proforma_id is a no-op (already_adopted).
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    db = storage / "proforma_links.db"

    with _p.object(wc, "fetch_invoice_xml", return_value=_ADOPT_PROFORMA_XML):
        r1 = client.post(
            _adopt_url(),
            json={"wfirma_proforma_id": _ADOPT_WF_ID, "reason": "first call"},
            headers=_auth(),
        ).json()
        r2 = client.post(
            _adopt_url(),
            json={"wfirma_proforma_id": _ADOPT_WF_ID, "reason": "duplicate call"},
            headers=_auth(),
        ).json()

    assert r1["ok"] is True
    assert r1["status"] == "adopted"
    assert r2["ok"] is True
    assert r2["status"] == "already_adopted"
    assert r2["was_created"] is False

    # Only one row
    draft = pildb.get_draft(db, _ADOPT_BATCH, _ADOPT_CLIENT)
    assert draft.wfirma_proforma_id == _ADOPT_WF_ID


def test_adopt_blocked_non_proforma_type(client, storage):
    """
    If wFirma returns type=normal (not proforma), the route blocks.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    with _p.object(wc, "fetch_invoice_xml", return_value=_ADOPT_NON_PROFORMA_XML):
        body = client.post(
            _adopt_url(),
            json={"wfirma_proforma_id": _ADOPT_WF_ID, "reason": "type test"},
            headers=_auth(),
        ).json()

    assert body["ok"] is False
    assert "normal" in body["error"] or "type" in body["error"]


def test_adopt_blocked_id_mismatch(client, storage):
    """
    If fetched XML has a different id than what was requested, the route blocks.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    mismatch_xml = _ADOPT_PROFORMA_XML.replace("<id>465611619</id>", "<id>999999999</id>", 1)

    with _p.object(wc, "fetch_invoice_xml", return_value=mismatch_xml):
        body = client.post(
            _adopt_url(),
            json={"wfirma_proforma_id": _ADOPT_WF_ID, "reason": "id mismatch test"},
            headers=_auth(),
        ).json()

    assert body["ok"] is False
    assert "mismatch" in body["error"].lower() or "999999999" in body["error"]


def test_adopt_blocked_fetch_failure(client, storage):
    """
    If wFirma XML fetch raises, the route returns blocked with the error.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    with _p.object(wc, "fetch_invoice_xml",
                   side_effect=RuntimeError("invoices/get HTTP 500")):
        body = client.post(
            _adopt_url(),
            json={"wfirma_proforma_id": _ADOPT_WF_ID, "reason": "fetch fail test"},
            headers=_auth(),
        ).json()

    assert body["ok"] is False
    assert "500" in body["error"] or "fetch" in body["error"].lower()


def test_adopt_blocked_different_issued_already_exists(client, storage):
    """
    If a different wfirma_proforma_id is already issued locally, the route
    blocks with a collision error.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    db = storage / "proforma_links.db"
    # Seed a different issued id
    pildb.init_db(db)
    pildb.upsert_pending_draft(
        db,
        batch_id=_ADOPT_BATCH,
        client_name=_ADOPT_CLIENT,
        currency="USD",
        exchange_rate=None,
        source_lines_json="[]",
    )
    pildb.mark_draft_issued(db, _ADOPT_BATCH, _ADOPT_CLIENT,
                            wfirma_proforma_id="DIFFERENT-111")

    different_xml = _ADOPT_PROFORMA_XML.replace("465611619", "DIFFERENT-111")
    with _p.object(wc, "fetch_invoice_xml", return_value=different_xml):
        body = client.post(
            _adopt_url(),
            json={"wfirma_proforma_id": "DIFFERENT-111-NEW", "reason": "collision test"},
            headers=_auth(),
        ).json()

    # The XML has id DIFFERENT-111 but body requests DIFFERENT-111-NEW — id mismatch
    # caught first (or adopt itself raises ValueError). Either way: ok=False.
    assert body["ok"] is False


def test_adopt_then_cancel_full_path(client, storage):
    """
    Full path: adopt existing wFirma proforma → cancel → route returns
    cancelled_for_reissue, local draft is failed/retryable.
    """
    from unittest.mock import patch as _p
    from app.services import wfirma_client as wc

    db = storage / "proforma_links.db"

    # Step 1: adopt
    with _p.object(wc, "fetch_invoice_xml", return_value=_ADOPT_PROFORMA_XML):
        ra = client.post(
            _adopt_url(),
            json={"wfirma_proforma_id": _ADOPT_WF_ID, "reason": "legacy adoption"},
            headers=_auth(),
        ).json()
    assert ra["ok"] is True

    # Step 2: cancel
    with _gate_delete_on(), \
         _p.object(wc, "delete_invoice",
                   return_value={"ok": True, "wfirma_invoice_id": _ADOPT_WF_ID}):
        rc = client.post(
            f"/api/v1/proforma/cancel-issued-for-reissue/{_ADOPT_BATCH}/{_ADOPT_CLIENT}",
            params={"confirm": _CANCEL_CONFIRM},
            headers=_auth(),
        ).json()

    assert rc["ok"] is True
    assert rc["status"] == "cancelled_for_reissue"
    assert rc["deleted_wfirma_id"] == _ADOPT_WF_ID

    draft = pildb.get_draft(db, _ADOPT_BATCH, _ADOPT_CLIENT)
    assert draft.status == "failed"
    assert draft.wfirma_proforma_id is None

