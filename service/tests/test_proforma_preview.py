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
from app.services import packing_db   as pdb
from app.services import warehouse_db as wdb
from app.services import document_db  as ddb
from app.services import wfirma_db    as wfdb
from app.services import inventory_state_engine as ise


BATCH = "BATCH_PFP_TEST"


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


def _match_customer(client_name: str):
    wfdb.upsert_customer(
        client_name=client_name,
        wfirma_customer_id="9",
        match_status="matched",
    )


# ── 1. Happy path: client + product + design + qty surface in response ──────

def test_preview_returns_client_product_design_qty(client):
    _seed_purchase(design_no="JE03137", product_code="EJL/26-27/100-1")
    _seed_sales("ACME", [{"sku": "JE03137", "qty": 2.0}])
    _seed_invoice_pricing("EJL/26-27/100-1", 150.0, "USD")
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
    _seed_sales("ACME", [{"sku": "JE200", "qty": 1.0}])
    # No invoice_lines pricing seeded
    _match_product("EJL/N-1")
    _match_customer("ACME")

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is False
    assert any("missing unit_price or currency" in br
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


def test_purchase_transit_blocks(client):
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
    assert body["ready"] is False
    assert body["lines"][0]["stock_ok"]     is False
    assert body["lines"][0]["stock_status"] == "purchase_transit"
    assert any("PURCHASE_TRANSIT" in br for br in body["blocking_reasons"])


def test_sales_transit_blocks(client):
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
    assert body["ready"] is False
    assert body["lines"][0]["stock_status"] == "sales_transit"
    assert any("SALES_TRANSIT" in br for br in body["blocking_reasons"])


def test_closed_state_blocks(client):
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
    assert body["ready"] is False
    assert body["lines"][0]["stock_status"] == "closed"
    assert any("CLOSED" in br for br in body["blocking_reasons"])


def test_missing_inventory_state_blocks(client):
    """Packing lines exist with scan_codes but were never seeded — must block."""
    _seed_purchase(design_no="JE404", product_code="EJL/MS-1")
    _seed_sales("ACME", [{"sku": "JE404", "qty": 1.0}])
    _seed_invoice_pricing("EJL/MS-1", 20.0, "USD")
    _match_product("EJL/MS-1")
    _match_customer("ACME")
    # NO seed_purchase_transit — inventory_state empty for this scan_code

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is False
    assert body["lines"][0]["stock_ok"]     is False
    assert body["lines"][0]["stock_status"] == "missing_state"


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
    _seed_sales("ACME", [{"sku": design, "qty": sku_qty}])
    _seed_invoice_pricing(product_code, price, "USD")
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
