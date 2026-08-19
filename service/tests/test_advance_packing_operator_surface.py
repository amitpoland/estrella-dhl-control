"""The advance-packing workflow as an OPERATOR can actually reach it.

Two halves:

  * HTTP — every endpoint the UI calls, through the real router, including the
    refusals.  test_advance_packing.py already covers the service layer; this
    file pins the surface, because a service function nobody can reach is not
    a workflow.
  * Wiring — the V2 component is loaded and mounted.  Source-grep only, the
    house convention for V2 UI pins (see test_accounting_cfo_mis_ui_wiring.py).

The wiring half also pins the ABSENCE of things: an advance list must offer no
route to stock, fiscal identity or barcodes, so the surface must not grow a
button for any of them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.core.config import settings          # noqa: E402
from app.services import advance_packing as adv   # noqa: E402
from app.services import packing_db as pdb        # noqa: E402

_V2 = _svc / "app" / "static" / "v2"


def _read(name: str) -> str:
    return (_V2 / name).read_text(encoding="utf-8", errors="replace")


def _code(name: str) -> str:
    """Source with comments stripped. The absence-assertions below are about
    what the UI OFFERS, and a comment explaining why something is absent is not
    an affordance."""
    src = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.S)
    return "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("//"))


# ── HTTP surface ──────────────────────────────────────────────────────────────

_ROWS = [
    {"design_no": "D-100", "quantity": 4, "bag_id": "B1"},
    {"design_no": "D-200", "quantity": 6, "bag_id": "B1"},
    {"design_no": "D-100", "quantity": 3, "bag_id": "B2"},   # repeat, must survive
]


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    monkeypatch.setattr(adv, "_storage", lambda: tmp_path)
    monkeypatch.setattr(adv, "extract_packing",
                        lambda p, **kw: (list(_ROWS), "stub", "1", {}))
    return tmp_path


@pytest.fixture()
def client(storage):
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@t"}
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    app.dependency_overrides.clear()


def _upload(client, name="advance.xlsx"):
    return client.post("/api/v1/packing-advance/upload",
                       files={"file": (name, b"x" * 32,
                                       "application/vnd.ms-excel")})


def _shipment(storage, batch_id="SHIPMENT_777_2026-08_abcd1234"):
    (storage / "outputs" / batch_id).mkdir(parents=True, exist_ok=True)
    return batch_id


def test_upload_creates_an_advance_batch(client):
    r = _upload(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert adv.is_advance_batch(body["batch_id"])
    assert body["doc_stage"] == "advance"
    assert body["rows_stored"] == 3, "the repeated design must not be collapsed"


def test_upload_rejects_an_unsupported_file_type(client):
    r = client.post("/api/v1/packing-advance/upload",
                    files={"file": ("list.txt", b"x", "text/plain")})
    assert r.status_code == 400
    assert ".txt" in r.json()["detail"]


def test_a_rejected_upload_leaves_no_file_behind(client, storage, monkeypatch):
    monkeypatch.setattr(adv, "extract_packing",
                        lambda p, **kw: (_ for _ in ()).throw(RuntimeError("bad parse")))
    r = _upload(client)
    assert r.status_code == 422
    stray = list((storage / "advance_packing").rglob("*.xlsx"))
    assert stray == [], f"un-ingested upload left behind: {stray}"


def test_list_filters_on_the_waiting_state(client, storage):
    doc = _upload(client).json()["document_id"]
    assert client.get("/api/v1/packing-advance?linked=false").json()["count"] == 1
    assert client.get("/api/v1/packing-advance?linked=true").json()["count"] == 0

    batch = _shipment(storage)
    assert client.post(f"/api/v1/packing-advance/{doc}/link",
                       json={"batch_id": batch}).status_code == 200

    assert client.get("/api/v1/packing-advance?linked=false").json()["count"] == 0
    listed = client.get("/api/v1/packing-advance?linked=true").json()
    assert listed["count"] == 1
    assert listed["documents"][0]["linked_batch_id"] == batch


def test_the_detail_view_returns_the_announced_lines(client):
    doc = _upload(client).json()["document_id"]
    body = client.get(f"/api/v1/packing-advance/{doc}").json()
    assert body["line_count"] == 3
    assert {ln["design_no"] for ln in body["lines"]} == {"D-100", "D-200"}
    # Nothing that would pass for physical or fiscal identity.
    assert all(ln["product_code"] is None for ln in body["lines"])
    assert all(ln["scan_code"] is None for ln in body["lines"])


def test_link_refuses_a_shipment_that_does_not_exist(client):
    doc = _upload(client).json()["document_id"]
    r = client.post(f"/api/v1/packing-advance/{doc}/link",
                    json={"batch_id": "SHIPMENT_000_2026-08_ffffffff"})
    assert r.status_code == 400
    assert "does not exist" in r.json()["detail"]


def test_link_requires_a_batch_id(client):
    doc = _upload(client).json()["document_id"]
    r = client.post(f"/api/v1/packing-advance/{doc}/link", json={"batch_id": "  "})
    assert r.status_code == 400


def test_reconciliation_refuses_before_a_link_exists(client):
    doc = _upload(client).json()["document_id"]
    r = client.get(f"/api/v1/packing-advance/{doc}/reconciliation")
    assert r.status_code == 400
    assert "not linked" in r.json()["detail"]


def test_reconciliation_reports_the_variance(client, storage):
    doc   = _upload(client).json()["document_id"]
    batch = _shipment(storage)
    client.post(f"/api/v1/packing-advance/{doc}/link", json={"batch_id": batch})

    # The shipment actually arrives with 7 of D-100 (announced 4+3) and no D-200.
    real_doc = pdb.upsert_packing_document(batch_id=batch, invoice_no="INV-1",
                                           source_file_path="real.xlsx",
                                           extraction_status="extracted")
    pdb.upsert_packing_lines([
        {"packing_document_id": real_doc, "batch_id": batch, "invoice_no": "INV-1",
         "design_no": "D-100", "quantity": 7, "pack_sr": 1},
    ])

    body = client.get(f"/api/v1/packing-advance/{doc}/reconciliation").json()
    by_design = {ln["design_no"]: ln for ln in body["lines"]}
    assert by_design["D-100"]["status"] == "match"      # 4 + 3 announced, 7 shipped
    assert by_design["D-200"]["status"] == "missing"    # announced, never shipped
    assert body["summary"]["fully_matched"] is False


def test_a_final_document_is_not_reachable_through_this_surface(client, storage):
    batch = _shipment(storage)
    final = pdb.upsert_packing_document(batch_id=batch, invoice_no="INV-9",
                                        source_file_path="real.xlsx",
                                        extraction_status="extracted")
    assert client.get(f"/api/v1/packing-advance/{final}").status_code == 404


# ── V2 wiring ─────────────────────────────────────────────────────────────────

def test_component_exports_both_mounts():
    src = _read("advance-packing.jsx")
    assert "window.AdvancePackingHub  = AdvancePackingHub" in src
    assert "window.AdvancePackingCard = AdvancePackingCard" in src


def test_index_loads_the_component():
    assert "advance-packing.jsx" in _read("index.html")


def test_shipments_page_mounts_the_hub():
    idx = _read("index.html")
    assert "window.AdvancePackingHub &&" in idx, "hub must be mounted, not merely loaded"
    # Inside the shipments route, next to the shipment list.
    hub  = idx.index("window.AdvancePackingHub &&")
    page = idx.index("page === 'shipments'")
    assert page < hub < idx.index("<DashboardPage onViewShipment")


def test_shipment_detail_mounts_the_card():
    src = _read("shipment-detail-page.jsx")
    assert "window.AdvancePackingCard batchId={batchId}" in src


def test_no_second_page_or_nav_entry_was_created():
    """The workflow lives inside Shipments; a redundant page would be a second
    place an operator has to look for the same fact."""
    tree = _read("components.jsx").split("const NAV_TREE")[1]
    tree = tree.split("\n];")[0]
    assert "advance" not in tree.lower()


def test_the_surface_calls_only_the_advance_api():
    src = _read("advance-packing.jsx")
    calls = [ln for ln in src.splitlines() if "apiFetch(" in ln and "/api/" in ln]
    assert calls, "component must actually call the API"
    assert all("/api/v1/packing-advance" in ln for ln in calls), calls


@pytest.mark.parametrize("forbidden", [
    "wfirma", "product_code", "scan_code", "/pz", "inventory",
    "seed_purchase_transit", "proforma",
])
def test_the_surface_offers_no_route_to_physical_or_fiscal_truth(forbidden):
    """An advance list describes goods that do not exist. The operator surface
    must not offer a path that would turn it into stock, a barcode or a fiscal
    record — those belong to the final shipment."""
    assert forbidden.lower() not in _code("advance-packing.jsx").lower()


def test_the_surface_does_not_call_expected_goods_stock():
    """Wording is the guard an operator actually reads: expected quantities are
    announced, never received."""
    src = _code("advance-packing.jsx")
    assert "Announced" in src and "Shipped" in src
    assert "Received" not in src, "warehouse_receipt owns physical receipt, not this"


def test_the_surface_states_the_boundary_to_the_operator():
    """The one place 'barcode' may appear is the sentence telling the operator
    there isn't one yet."""
    assert "no product codes, no barcodes until the real shipment arrives"         in _code("advance-packing.jsx")


# ── Audit trail ───────────────────────────────────────────────────────────────

def _audit(storage, batch_id):
    return storage / "outputs" / batch_id / "audit.json"


def test_linking_is_recorded_on_the_shipment_timeline(client, storage):
    import json

    doc   = _upload(client).json()["document_id"]
    batch = _shipment(storage)
    _audit(storage, batch).write_text(json.dumps({"batch_id": batch, "timeline": []}),
                                      encoding="utf-8")

    client.post(f"/api/v1/packing-advance/{doc}/link", json={"batch_id": batch},
                headers={"X-Operator-User": "anna"})

    timeline = json.loads(_audit(storage, batch).read_text(encoding="utf-8"))["timeline"]
    events = [e for e in timeline if e.get("event") == "advance_packing_linked"]
    assert len(events) == 1, timeline
    d = events[0]["detail"]
    assert d["advance_document_id"] == doc
    assert d["operator"] == "anna"
    assert d["line_count"] == 3
    assert d["expected_total"] == 13          # 4 + 6 + 3 announced
    # The event must say plainly that nothing physical or fiscal happened.
    assert d["evidence_class"] == "commercial"
    assert d["inventory_write"] is False and d["wfirma_write"] is False


def test_the_audit_event_is_not_duplicated_by_a_repeat_link(client, storage):
    import json

    doc   = _upload(client).json()["document_id"]
    batch = _shipment(storage)
    _audit(storage, batch).write_text(json.dumps({"batch_id": batch, "timeline": []}),
                                      encoding="utf-8")

    for _ in range(3):
        client.post(f"/api/v1/packing-advance/{doc}/link", json={"batch_id": batch})

    timeline = json.loads(_audit(storage, batch).read_text(encoding="utf-8"))["timeline"]
    assert sum(e.get("event") == "advance_packing_linked" for e in timeline) == 1


def test_a_missing_audit_file_does_not_undo_the_link(client, storage):
    """Audit emission is best-effort; the link is the operator's decision and
    must survive a batch whose audit.json has not been written yet."""
    doc   = _upload(client).json()["document_id"]
    batch = _shipment(storage)                 # no audit.json
    r = client.post(f"/api/v1/packing-advance/{doc}/link", json={"batch_id": batch})
    assert r.status_code == 200 and r.json()["changed"] is True
