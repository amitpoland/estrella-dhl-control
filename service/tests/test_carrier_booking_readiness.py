"""Shipment-leg duplicate protection + booking-readiness projection.

Three business rules are pinned here because getting any of them wrong stops a
real shipment leaving India:

1. **Warehouse receipt is DOWNSTREAM of dispatch.** Goods are packed and weighed
   in India and the AWB is created before they travel. A pending destination
   receipt is the expected state at booking time — never a blocker, never a
   warning, never a booking dependency.
2. **The Proforma Invoice is the value document at AWB stage.** A final sales /
   commercial invoice is not required and is never consulted.
3. **Direction alone never blocks a booking.** Duplicate protection is tied to
   leg identity: the same canonical leg must not receive a second AWB.

Nothing here contacts a carrier, creates a shipment, or widens an allowlist.
The batch ids are synthetic.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = pathlib.Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

INBOUND_AWB = "1000000002"
BATCH = "SHIPMENT_" + INBOUND_AWB + "_2026-08_bbbb2222"
PLAIN_BATCH = "SHIPMENT_NOAWB_2026-08_cccc3333"
CLIENT_A = "CUSTOMER_A"
CLIENT_B = "CUSTOMER_B"


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def storage(tmp_path):
    from app.services import proforma_invoice_link_db as pildb

    pildb.init_db(tmp_path / "proforma_links.db")
    out = tmp_path / "outputs" / BATCH
    out.mkdir(parents=True, exist_ok=True)
    # An intake-uploaded supplier AWB — this leg is already booked.
    (out / "audit.json").write_text(json.dumps({
        "batch_id": BATCH, "awb": INBOUND_AWB, "tracking_no": INBOUND_AWB,
        "carrier": "DHL", "source": "intake_upload", "timeline": [],
    }), encoding="utf-8")
    # A batch carrying NO AWB at all — nothing to protect against.
    plain = tmp_path / "outputs" / PLAIN_BATCH
    plain.mkdir(parents=True, exist_ok=True)
    (plain / "audit.json").write_text(json.dumps({
        "batch_id": PLAIN_BATCH, "carrier": "DHL", "source": "intake_upload",
        "timeline": [],
    }), encoding="utf-8")
    return tmp_path


def _seed_draft(storage, client_name, *, box=None, gross=None, batch=BATCH):
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, status, currency, draft_state,
                  wfirma_proforma_id, wfirma_proforma_fullnumber,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, box_type_code,
                  manual_gross_weight, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (batch, client_name, "draft", "EUR", "draft", None, "", "[]", "[]",
             "[]", 0, 1, box, gross),
        )
        conn.commit()
        return cur.lastrowid


def _settings(storage, **over):
    s = MagicMock()
    s.storage_root = storage
    s.carrier_storage_root = None
    s.carrier_live_allowlist = ""
    s.carrier_api_status = "live"
    s.dhl_express_account_number = "ACC123"
    s.dhl_express_api_key = "k"
    s.dhl_express_api_secret = "s"
    for k, v in over.items():
        setattr(s, k, v)
    return s


@pytest.fixture(autouse=True)
def _stub_external_authorities(monkeypatch):
    """Customer Master / warehouse / Incoterm / description have their own suites."""
    monkeypatch.setattr(
        "app.services.awb_address_authority.derive_awb_address_authority",
        lambda batch_id, storage_root, client_ref=None: {
            "name": "Stub Customer", "street": "Stub Street 1", "city": "Stub City",
            "country": "PL", "phone": "+48100200300", "source": "bill_to",
        },
    )
    monkeypatch.setattr(
        "app.api.routes_carrier_actions._resolve_booking_incoterm",
        lambda **kw: {"value": "DAP", "source": "customer_master"},
    )
    monkeypatch.setattr(
        "app.api.routes_carrier_actions._project_shipment_description_for_client",
        # The REAL builder returns the whole projection dict, never a bare
        # string. This stub said "Jewellery" and every test passed against a
        # shape production never produces, so the readiness endpoint 500'd on
        # the first real request (Lesson A). Stub matches the real return
        # shape now; test_description_projection_real_shape_is_a_dict pins it
        # against the real builder with no stub at all.
        lambda **kw: {"batch_id": kw.get("batch_id"),
                      "client_ref": kw.get("client_ref"),
                      "shipment_description": "Jewellery",
                      "source": "canonical"},
    )
    # Goods have NOT reached the destination warehouse — the normal state at
    # booking time, since the AWB is created before they travel.
    monkeypatch.setattr(
        "app.services.warehouse_receipt.get_receipt_status",
        lambda batch_id: {"total_lines": 2, "confirmed_lines": 0,
                          "fully_confirmed": False, "serial_controlled": False},
    )


def _project(storage, batch=BATCH, **kw):
    from app.services.carrier.booking_readiness import project_booking_readiness

    params = dict(
        storage_root=storage,
        proforma_db_path=storage / "proforma_links.db",
        shipment_db_path=storage / "carrier_shipments.db",
        settings=_settings(storage, **kw.pop("settings_over", {})),
        weight_kg=2.5,
        declared_value=1000.0,
    )
    params.update(kw)
    return project_booking_readiness(batch, **params)


def _codes(items):
    return {i["code"] for i in items}


def _blockers(proj):
    return _codes(proj["business_readiness"]["blockers"])


# ── RULE 1 — warehouse receipt is downstream, never a gate ──────────────────


def test_warehouse_not_received_does_not_block_business_readiness(storage):
    """Goods are packed in India; the AWB is created before they travel."""
    _seed_draft(storage, CLIENT_A, box="BOX-A", batch=PLAIN_BATCH)
    proj = _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A)
    assert proj["warehouse"]["state"] == "pending"
    assert proj["business_readiness"]["ready"] is True
    assert proj["business_readiness"]["blockers"] == []


def test_warehouse_never_appears_as_a_blocker_or_a_warning(storage):
    _seed_draft(storage, CLIENT_A, batch=PLAIN_BATCH)
    biz = _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A)["business_readiness"]
    assert "WAREHOUSE" not in json.dumps(biz).upper()


def test_warehouse_declares_itself_a_non_dependency(storage):
    """A permanent contract, not an incidental value."""
    assert _project(storage, batch=PLAIN_BATCH)["warehouse"]["booking_dependency"] is False


def test_create_shipment_never_consults_warehouse_receipt():
    """Server-side: the booking path must not import or read receipt state."""
    routes = (_ROOT / "app" / "api" / "routes_carrier_actions.py").read_text(encoding="utf-8")
    body = routes[routes.index("def create_shipment("):
                  routes.index("def _external_shipment_payload(")]
    for banned in ("warehouse_receipt", "get_receipt_status", "fully_confirmed",
                   "WAREHOUSE_NOT_RECEIVED"):
        assert banned not in body, banned


# ── RULE 2 — proforma is the AWB value document ─────────────────────────────


def test_final_sales_invoice_is_not_required_for_awb(storage):
    """No sales/commercial invoice exists in this fixture at all."""
    _seed_draft(storage, CLIENT_A, box="BOX-A", batch=PLAIN_BATCH)
    proj = _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A)
    assert proj["proforma"]["ready"] is True
    assert proj["proforma"]["final_sales_invoice_required"] is False
    assert proj["business_readiness"]["ready"] is True
    assert proj["declared_value"]["authority"] == "proforma_invoice"


def test_readiness_never_reads_a_sales_invoice_authority():
    src = _SRC.read_text(encoding="utf-8").lower()
    body = src[src.index("from __future__"):]      # skip the explanatory docstring
    for banned in ("import invoice", "invoice_db", "get_sales_invoice",
                   "wfirma_invoice", "list_invoices"):
        assert banned not in body, banned
    # The one permitted mention is the declared negative contract itself.
    assert body.count("sales_invoice") == body.count("final_sales_invoice_required")


# ── RULE 3 — direction never blocks; leg identity does ──────────────────────


def test_inbound_direction_alone_does_not_block_a_booking(storage):
    """India -> Poland is 'inbound' at the warehouse while origin-side booking
    is exactly the normal workflow."""
    _seed_draft(storage, CLIENT_A, box="BOX-A", batch=PLAIN_BATCH)
    proj = _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A)
    assert proj["existing_booking"]["existing"] is False
    assert proj["business_readiness"]["ready"] is True


def test_direction_is_never_consulted_by_the_duplicate_rule():
    import ast
    import inspect

    from app.services.carrier import booking_readiness as br

    fn = ast.parse(inspect.getsource(br.resolve_existing_leg_awb)).body[0]
    # Drop the docstring: it EXPLAINS why direction is irrelevant, at length.
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    code = ast.dump(ast.Module(body=fn.body, type_ignores=[])).lower()
    for banned in ("direction", "inbound_batch", "is_inbound"):
        assert banned not in code, banned


def test_same_leg_with_an_existing_awb_blocks_a_duplicate(storage):
    proj = _project(storage)                      # unscoped -> the batch leg
    assert proj["existing_booking"]["awb"] == INBOUND_AWB
    assert proj["existing_booking"]["blocks_duplicate_booking"] is True
    assert "SHIPMENT_LEG_ALREADY_BOOKED" in _blockers(proj)


def test_a_distinct_customer_leg_is_not_the_already_booked_leg(storage):
    """The supplier AWB must not make every customer in the batch unbookable."""
    _seed_draft(storage, CLIENT_A, box="BOX-A")
    proj = _project(storage, client_ref=CLIENT_A)
    assert proj["existing_booking"]["existing"] is False
    assert "SHIPMENT_LEG_ALREADY_BOOKED" not in _blockers(proj)
    assert proj["business_readiness"]["ready"] is True


def test_two_customers_in_one_batch_stay_independently_scoped(storage):
    from app.services.carrier.booking_readiness import resolve_outbound_intents

    _seed_draft(storage, CLIENT_A)
    _seed_draft(storage, CLIENT_B)
    db = storage / "proforma_links.db"
    assert {i["client_ref"] for i in resolve_outbound_intents(BATCH, proforma_db_path=db)} \
        == {CLIENT_A, CLIENT_B}
    assert [i["client_ref"] for i in resolve_outbound_intents(
        BATCH, proforma_db_path=db, client_ref=CLIENT_A)] == [CLIENT_A]


def test_readiness_scopes_by_client_ref_not_by_batch(storage):
    _seed_draft(storage, CLIENT_A, box="BOX-A", batch=PLAIN_BATCH)
    _seed_draft(storage, CLIENT_B, batch=PLAIN_BATCH)
    assert "OUTBOUND_SCOPE_AMBIGUOUS" in _blockers(_project(storage, batch=PLAIN_BATCH))
    scoped = _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A)
    assert scoped["customer_scope"] == CLIENT_A
    assert scoped["box"]["box_type_code"] == "BOX-A"
    assert "OUTBOUND_SCOPE_AMBIGUOUS" not in _blockers(scoped)


# ── physical / business facts ───────────────────────────────────────────────


def test_missing_packed_gross_blocks_and_zero_is_never_a_measurement(storage):
    _seed_draft(storage, CLIENT_A, batch=PLAIN_BATCH)
    for value in (None, 0, 0.0, "0", "", "not-a-number", -1):
        proj = _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A, weight_kg=value)
        assert "WEIGHT_NOT_MEASURED" in _blockers(proj), value
        assert proj["weight"]["gross_weight"] is None
        assert proj["weight"]["ready"] is False


def test_origin_entered_packed_weight_is_accepted_before_dispatch(storage):
    """The India-side operator records actual packed weight; that IS the truth."""
    _seed_draft(storage, CLIENT_A, gross=3.2, batch=PLAIN_BATCH)
    proj = _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A, weight_kg=None)
    assert proj["weight"]["gross_weight"] == 3.2
    assert proj["weight"]["source"] == "draft_manual_gross"
    assert proj["warehouse"]["state"] == "pending"     # and still not received


def test_missing_declared_value_blocks(storage):
    _seed_draft(storage, CLIENT_A, batch=PLAIN_BATCH)
    assert "DECLARED_VALUE_MISSING" in _blockers(
        _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A, declared_value=0))


def test_unmapped_customer_blocks_through_the_one_recipient_authority(storage, monkeypatch):
    from app.services.awb_address_authority import CustomerNotFoundError

    def _boom(batch_id, storage_root, client_ref=None):
        raise CustomerNotFoundError("no contractor")

    monkeypatch.setattr(
        "app.services.awb_address_authority.derive_awb_address_authority", _boom)
    _seed_draft(storage, CLIENT_A, batch=PLAIN_BATCH)
    proj = _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A)
    assert "CUSTOMER_NOT_FOUND" in _blockers(proj)
    assert proj["recipient"]["ready"] is False
    assert proj["recipient"]["authority"] == "customer_master"


# ── business readiness vs live release are independent ──────────────────────


def test_business_ready_true_with_live_release_false_is_valid(storage):
    _seed_draft(storage, CLIENT_A, box="BOX-A", batch=PLAIN_BATCH)
    proj = _project(storage, batch=PLAIN_BATCH, client_ref=CLIENT_A)
    assert proj["business_readiness"]["ready"] is True
    assert proj["live_release"]["specifically_allowlisted"] is False
    assert proj["live_release"]["ready"] is False


def test_release_reason_never_suggests_widening_the_allowlist(storage):
    _seed_draft(storage, CLIENT_A, batch=PLAIN_BATCH)
    reason = _project(storage, batch=PLAIN_BATCH,
                      client_ref=CLIENT_A)["live_release"]["reason"]
    assert "governed live-booking process" in reason
    assert "*" not in reason and "CARRIER_LIVE_ALLOWLIST" not in reason


def test_allowlist_reading_matches_the_live_gate_exactly(storage):
    """One string, two readers — they must never disagree about a batch."""
    from app.services.carrier.adapters.live import DhlExpressLiveAdapter
    from app.services.carrier.factory import CarrierConfig
    from app.services.carrier.models.shipment import CarrierAllowlistError

    for raw in ("", "  ", BATCH, "other," + BATCH, "other", "*", " " + BATCH + " , other "):
        adapter = DhlExpressLiveAdapter(CarrierConfig(status="live", live_allowlist=raw))
        try:
            adapter._check_allowlist(BATCH)
            gate_allows = True
        except CarrierAllowlistError:
            gate_allows = False
        projected = _project(
            storage, settings_over={"carrier_live_allowlist": raw},
        )["live_release"]["specifically_allowlisted"]
        assert projected == gate_allows, raw


# ── server-side duplicate guard on the booking endpoint ─────────────────────


@contextmanager
def _booking_client(storage):
    from app.api.routes_carrier_actions import _get_coordinator, router
    from app.auth.dependencies import get_current_user
    from app.core.security import require_api_key

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1, "email": "t@test.internal", "role": "logistics",
        "is_active": True, "is_approved": True,
    }
    coord = MagicMock()
    coord.create_shipment.side_effect = AssertionError(
        "CarrierCoordinator was reached - the duplicate guard must refuse first")
    app.dependency_overrides[_get_coordinator] = lambda: coord
    with patch("app.core.config.settings", _settings(storage)):
        yield TestClient(app, raise_server_exceptions=True), coord


def _book(client, batch=BATCH, **extra):
    body = {
        "shipper_account": "ACC123",
        "recipient_address": {"name": "N", "street": "S", "city": "C",
                              "country": "Poland", "phone": "+48100200300"},
        "declared_value": 100.0, "currency": "EUR", "weight_kg": 1.0,
        "dimensions": {"length": 10, "width": 10, "height": 10},
    }
    body.update(extra)
    return client.post("/api/v1/carrier/" + batch + "/shipment", json=body)


def test_booking_an_already_booked_leg_fails_before_any_carrier_call(storage):
    with _booking_client(storage) as (client, coord):
        resp = _book(client)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "SHIPMENT_LEG_ALREADY_BOOKED"
    assert detail["existing_awb"] == INBOUND_AWB
    assert "No carrier request was sent." in detail["guidance"]
    coord.create_shipment.assert_not_called()


def test_already_booked_guidance_never_mentions_the_allowlist(storage):
    """The operator must not be told to allowlist a leg that is already booked."""
    with _booking_client(storage) as (client, _):
        detail = _book(client).json()["detail"]
    blob = json.dumps(detail)
    # It may say the allowlist is IRRELEVANT here; it must never point at one.
    assert "nothing needs to be released or allowlisted" in detail["guidance"]
    for banned in ("CARRIER_LIVE_ALLOWLIST", "Add this batch", "add it to", "*"):
        assert banned not in blob, banned
    assert detail["code"] != "CARRIER_LIVE_ALLOWLIST_BLOCKED"


def test_a_distinct_customer_leg_reaches_the_coordinator(storage):
    """The guard must not become 'inbound batch => nothing may ever ship'."""
    _seed_draft(storage, CLIENT_A)
    with _booking_client(storage) as (client, _):
        with pytest.raises(AssertionError, match="duplicate guard must refuse first"):
            _book(client, client_ref=CLIENT_A)


def test_a_batch_with_no_existing_awb_is_never_blocked_by_the_guard(storage):
    with _booking_client(storage) as (client, _):
        with pytest.raises(AssertionError, match="duplicate guard must refuse first"):
            _book(client, batch=PLAIN_BATCH)


def test_warehouse_pending_never_blocks_create_shipment(storage):
    """Receipt is pending in every fixture here; booking still proceeds."""
    _seed_draft(storage, CLIENT_A, batch=PLAIN_BATCH)
    with _booking_client(storage) as (client, _):
        with pytest.raises(AssertionError, match="duplicate guard must refuse first"):
            _book(client, batch=PLAIN_BATCH, client_ref=CLIENT_A)


# ── authority containment (adversarial) ─────────────────────────────────────


_SRC = _ROOT / "app" / "services" / "carrier" / "booking_readiness.py"


def test_readiness_persists_nothing_and_owns_no_store():
    src = _SRC.read_text(encoding="utf-8")
    for banned in ("CREATE TABLE", "INSERT INTO", "UPDATE ", "DELETE FROM", "commit()"):
        assert banned not in src, banned


def test_readiness_books_nothing_and_tracks_nothing_of_its_own():
    """CarrierCoordinator stays the only booking executor; tracking stays put."""
    src = _SRC.read_text(encoding="utf-8")
    assert "CarrierCoordinator" not in src
    assert "create_shipment" not in src
    assert "httpx" not in src and "requests" not in src


def test_no_source_anywhere_suggests_a_wildcard_allowlist():
    app_dir = _ROOT / "app"
    offenders = []
    for path in list(app_dir.rglob("*.py")) + list(app_dir.rglob("*.js")) + \
            list(app_dir.rglob("*.jsx")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for phrase in ("CARRIER_LIVE_ALLOWLIST=*", "set it to *",
                       "or set CARRIER_LIVE_ALLOWLIST", "ALLOWLIST=* to permit"):
            if phrase in text:
                offenders.append(path.name + ": " + phrase)
    assert not offenders, offenders


# ── HTTP surface ────────────────────────────────────────────────────────────


def test_readiness_endpoint_is_registered_and_creates_nothing(storage):
    """The literal path must not be captured by a /{batch_id}/... route."""
    _seed_draft(storage, CLIENT_A, box="BOX-A", batch=PLAIN_BATCH)
    with _booking_client(storage) as (client, coord):
        resp = client.get(
            "/api/v1/carrier/" + PLAIN_BATCH + "/booking-readiness",
            params={"client_ref": CLIENT_A, "weight_kg": 2.5, "declared_value": 900.0},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["batch_id"] == PLAIN_BATCH
    assert body["customer_scope"] == CLIENT_A
    assert body["business_readiness"]["ready"] is True
    assert body["live_release"]["ready"] is False        # allowlist closed, correctly
    assert body["warehouse"]["booking_dependency"] is False
    coord.create_shipment.assert_not_called()


def test_readiness_reports_the_existing_awb_for_an_already_booked_leg(storage):
    with _booking_client(storage) as (client, _):
        body = client.get("/api/v1/carrier/" + BATCH + "/booking-readiness").json()
    assert body["existing_booking"]["awb"] == INBOUND_AWB
    assert body["existing_booking"]["carrier"] == "DHL"
    assert body["existing_booking"]["blocks_duplicate_booking"] is True


def test_readiness_response_carries_no_contact_pii(storage):
    _seed_draft(storage, CLIENT_A, batch=PLAIN_BATCH)
    with _booking_client(storage) as (client, _):
        body = client.get("/api/v1/carrier/" + PLAIN_BATCH + "/booking-readiness",
                          params={"client_ref": CLIENT_A}).json()
    assert set(body["recipient"]) <= {"ready", "source", "company", "city",
                                      "country", "blocker", "authority"}
    assert "+48100200300" not in json.dumps(body)


def test_readiness_response_carries_no_carrier_secret(storage):
    with _booking_client(storage) as (client, _):
        blob = json.dumps(client.get(
            "/api/v1/carrier/" + BATCH + "/booking-readiness").json())
    for secret in ("ACC123", '"k"', '"s"'):
        assert secret not in blob, secret


def test_readiness_carries_the_same_auth_guard_as_its_sibling_reads():
    """Asserting a status code here would measure the dev-mode auth bypass
    (``require_api_key`` returns early when API_KEY is unset outside prod), not
    the route. Pin the declared dependency instead — that is what a regression
    would actually remove."""
    from app.api.routes_carrier_actions import router
    from app.core.security import require_api_key

    def _guards(path, method):
        for r in router.routes:
            if getattr(r, "path", None) == path and method in getattr(r, "methods", ()):
                return {d.call for d in r.dependant.dependencies}
        raise AssertionError("route not registered: " + method + " " + path)

    assert require_api_key in _guards("/api/v1/carrier/{batch_id}/booking-readiness", "GET")
    assert require_api_key in _guards("/api/v1/carrier/{batch_id}/shipment", "GET")


# ── operator-facing contract pins (source-grep) ─────────────────────────────

_V2 = _ROOT / "app" / "static" / "v2"


def test_modal_preflights_before_the_operator_fills_it_in():
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "PzApi.getBookingReadiness" in src
    for tid in ("awb-readiness-panel", "awb-readiness-existing",
                "awb-readiness-release", "awb-readiness-warehouse",
                "awb-readiness-already-booked", "awb-readiness-blockers"):
        assert 'data-testid="' + tid + '"' in src, tid
    api = (_V2 / "pz-api.js").read_text(encoding="utf-8")
    assert "getBookingReadiness:" in api and "booking-readiness" in api


def test_ui_shows_warehouse_as_downstream_not_as_a_blocker():
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    start = src.index('data-testid="awb-readiness-warehouse"')
    assert "not required for origin dispatch" in src[start:start + 600]
    # It must not participate in the submit gate.
    gate = src[src.index("const readinessBlocksSubmit"):]
    assert "warehouse" not in gate[:200].lower()


def test_ui_keeps_business_readiness_and_live_release_separate():
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "const releaseBlocked   = !!(_rdyRelease && !_rdyRelease.ready);" in src
    start = src.index('data-testid="awb-readiness-release-blocked"')
    panel = src[start:start + 800]
    assert "shipment data above is unaffected" in panel
    assert "CARRIER_LIVE_ALLOWLIST" not in panel


def test_ui_presents_an_already_booked_leg_instead_of_an_allowlist_prompt():
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    start = src.index('data-testid="awb-readiness-already-booked"')
    panel = src[start:start + 800]
    assert "already represents this shipment leg" in panel
    assert "allowlist" not in panel.lower()
    # The release warning is suppressed while the leg is already booked.
    assert "releaseBlocked && !legAlreadyBooked" in src


def test_readiness_validates_batch_id_at_the_trust_boundary(storage):
    """batch_id reaches a filesystem path, so a traversal attempt is REFUSED.

    Read-only is not a licence to skip the check: every sibling batch-scoped
    route in this module validates before use, and this one must match them.
    """
    from app.api.routes_carrier_actions import _SAFE_BATCH

    with _booking_client(storage) as (client, _):
        for bad in ("../../etc/passwd", "..", "a/b", "x" * 200, "ab", "a b"):
            assert not _SAFE_BATCH.match(bad), bad
            resp = client.get(
                "/api/v1/carrier/" + bad + "/booking-readiness",
                params={"client_ref": CLIENT_A},
            )
            # Refused by the route's own guard, or never routed at all.
            assert resp.status_code in (400, 404), (bad, resp.status_code)
        # The real batch id still resolves.
        assert client.get(
            "/api/v1/carrier/" + BATCH + "/booking-readiness").status_code == 200


# ── Lesson A: pin the REAL builder's return shape, with no stub ─────────────
# The readiness consumer called .strip() on this builder's return value. Every
# stubbed test passed because the stub returned a bare string; production
# raised AttributeError: 'dict' object has no attribute 'strip' on the first
# real request and the endpoint 500'd. These two tests use the real builder,
# so a future shape change breaks them here instead of in production.

def test_description_projection_real_shape_is_a_dict(tmp_path):
    """The real builder returns the projection DICT, never a bare string."""
    from app.api.routes_carrier_actions import (
        _project_shipment_description_for_client,
    )

    out = _project_shipment_description_for_client(
        storage_root=tmp_path, batch_id="SHIPMENT_1_2026-08_aaaa1111",
        client_ref=None,
    )
    assert isinstance(out, dict), "builder contract is dict, got %r" % type(out)
    assert "shipment_description" in out
    assert isinstance(out["shipment_description"], str)
    # A bare string must never be the contract again.
    assert not isinstance(out, str)


def test_readiness_normalises_the_real_description_shape(tmp_path):
    """_description_state survives the real builder's dict return."""
    from app.api.routes_carrier_actions import (
        _project_shipment_description_for_client,
    )
    from app.services.carrier import booking_readiness as br

    real = _project_shipment_description_for_client(
        storage_root=tmp_path, batch_id="SHIPMENT_1_2026-08_aaaa1111",
        client_ref=None,
    )
    # The normaliser accepts exactly what the builder emits — no AttributeError.
    assert br._normalise_description(real) is None or isinstance(
        br._normalise_description(real), str)
    assert br._normalise_description(
        {"shipment_description": "  Jewellery  "}) == "Jewellery"
    assert br._normalise_description({"shipment_description": ""}) is None

    # And the state wrapper never raises on the real shape.
    state = br._description_state(
        "SHIPMENT_1_2026-08_aaaa1111", tmp_path, None)
    assert state["authority"] == "description_engine"
    assert set(state) == {"ready", "authority", "value"}
