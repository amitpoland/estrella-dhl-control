"""Shipment-leg model + booking-readiness projection.

An import batch is NOT one shipment. It carries the supplier's inbound AWB and,
separately, zero or more outbound customer intents scoped by ``client_ref``.
These pin both halves:

* the READ projection (``GET .../booking-readiness``) reports what the booking
  authorities already know, before the operator fills the modal in;
* the server-side leg guard refuses to re-book the inbound supplier leg, and
  refuses it BEFORE any carrier adapter is reached.

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
CLIENT_A = "CUSTOMER_A"
CLIENT_B = "CUSTOMER_B"


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def storage(tmp_path):
    from app.services import proforma_invoice_link_db as pildb

    pildb.init_db(tmp_path / "proforma_links.db")
    out = tmp_path / "outputs" / BATCH
    out.mkdir(parents=True, exist_ok=True)
    # An intake-uploaded supplier AWB — the inbound leg.
    (out / "audit.json").write_text(json.dumps({
        "batch_id": BATCH, "awb": INBOUND_AWB, "tracking_no": INBOUND_AWB,
        "carrier": "DHL", "source": "intake_upload", "timeline": [],
    }), encoding="utf-8")
    return tmp_path


def _seed_draft(storage, client_name, *, box=None, gross=None):
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, status, currency, draft_state,
                  wfirma_proforma_id, wfirma_proforma_fullnumber,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, box_type_code,
                  manual_gross_weight, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (BATCH, client_name, "draft", "EUR", "draft", None, "", "[]", "[]",
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
    for k, v in over.items():
        setattr(s, k, v)
    return s


@pytest.fixture(autouse=True)
def _stub_external_authorities(monkeypatch):
    """Customer Master / warehouse / Incoterm have their own pinned suites."""
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
        "app.services.warehouse_receipt.get_receipt_status",
        lambda batch_id: {"total_lines": 2, "confirmed_lines": 0,
                          "fully_confirmed": False, "serial_controlled": False},
    )


def _project(storage, **kw):
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
    return project_booking_readiness(BATCH, **params)


def _codes(items):
    return {i["code"] for i in items}


# ── shipment-leg model ──────────────────────────────────────────────────────


def test_batch_alone_never_identifies_a_shipment(storage):
    """Two customers in one import batch stay independently scoped."""
    from app.services.carrier.booking_readiness import resolve_outbound_intents

    _seed_draft(storage, CLIENT_A)
    _seed_draft(storage, CLIENT_B)
    db = storage / "proforma_links.db"

    both = resolve_outbound_intents(BATCH, proforma_db_path=db)
    assert {i["client_ref"] for i in both} == {CLIENT_A, CLIENT_B}

    only_a = resolve_outbound_intents(BATCH, proforma_db_path=db, client_ref=CLIENT_A)
    assert [i["client_ref"] for i in only_a] == [CLIENT_A]


def test_readiness_scopes_by_client_ref_not_by_batch(storage):
    _seed_draft(storage, CLIENT_A, box="BOX-A")
    _seed_draft(storage, CLIENT_B)

    # No scope + several customers = ambiguous, and it says so rather than
    # silently picking one customer's shipment.
    assert "OUTBOUND_SCOPE_AMBIGUOUS" in _codes(_project(storage)["booking"]["blockers"])

    scoped = _project(storage, client_ref=CLIENT_A)
    assert scoped["customer_scope"] == CLIENT_A
    assert scoped["box"]["code"] == "BOX-A"
    assert "OUTBOUND_SCOPE_AMBIGUOUS" not in _codes(scoped["booking"]["blockers"])


def test_inbound_leg_is_reported_and_never_becomes_an_outbound_intent(storage):
    proj = _project(storage)
    assert proj["existing_awb"] == INBOUND_AWB
    assert proj["existing_awb_provider"] == "DHL"
    assert proj["outbound_intents"] == []
    assert proj["shipment_intent"] == "inbound_existing"
    assert "NO_OUTBOUND_CUSTOMER_INTENT" in _codes(proj["booking"]["blockers"])


def test_an_outbound_intent_coexists_with_the_inbound_leg(storage):
    """An inbound batch does NOT forbid preparing a customer shipment."""
    _seed_draft(storage, CLIENT_A, box="BOX-A")
    proj = _project(storage, client_ref=CLIENT_A)
    assert proj["existing_awb"] == INBOUND_AWB          # still tracked
    assert proj["shipment_intent"] == "outbound_customer"
    assert "NO_OUTBOUND_CUSTOMER_INTENT" not in _codes(proj["booking"]["blockers"])


# ── physical / business facts ───────────────────────────────────────────────


def test_missing_packed_gross_blocks_and_zero_is_never_a_measurement(storage):
    _seed_draft(storage, CLIENT_A)
    for value in (None, 0, 0.0, "0", "", "not-a-number", -1):
        proj = _project(storage, client_ref=CLIENT_A, weight_kg=value)
        assert "WEIGHT_NOT_MEASURED" in _codes(proj["booking"]["blockers"]), value
        assert proj["weight"]["value"] is None
        assert proj["weight"]["ready"] is False


def test_persisted_manual_gross_satisfies_weight_without_a_caller_value(storage):
    _seed_draft(storage, CLIENT_A, gross=3.2)
    proj = _project(storage, client_ref=CLIENT_A, weight_kg=None)
    assert proj["weight"]["value"] == 3.2
    assert proj["weight"]["source"] == "draft_manual_gross"


def test_missing_declared_value_blocks(storage):
    _seed_draft(storage, CLIENT_A)
    proj = _project(storage, client_ref=CLIENT_A, declared_value=0)
    assert "DECLARED_VALUE_MISSING" in _codes(proj["booking"]["blockers"])


def test_warehouse_receipt_is_advisory_never_a_blocker(storage):
    """Lesson R: WAREHOUSE may hard-block on quantity risk only.

    A pending receipt is disclosed so the operator sees it, and preparation
    still proceeds — promoting it to a hard gate would need an explicit
    business rule naming the fiscal/duplication risk it protects (Lesson N).
    """
    _seed_draft(storage, CLIENT_A, box="BOX-A")
    proj = _project(storage, client_ref=CLIENT_A)
    assert proj["warehouse"]["state"] == "pending"
    assert "WAREHOUSE_RECEIPT_PENDING" in _codes(proj["booking"]["advisories"])
    assert "WAREHOUSE_RECEIPT_PENDING" not in _codes(proj["booking"]["blockers"])
    assert proj["booking"]["ready"] is True


def test_unmapped_customer_blocks_through_the_one_recipient_authority(storage, monkeypatch):
    from app.services.awb_address_authority import CustomerNotFoundError

    def _boom(batch_id, storage_root, client_ref=None):
        raise CustomerNotFoundError("no contractor")

    monkeypatch.setattr(
        "app.services.awb_address_authority.derive_awb_address_authority", _boom)
    _seed_draft(storage, CLIENT_A)
    proj = _project(storage, client_ref=CLIENT_A)
    assert "CUSTOMER_NOT_FOUND" in _codes(proj["booking"]["blockers"])
    assert proj["recipient"]["ready"] is False


# ── release axis ────────────────────────────────────────────────────────────


def test_live_release_is_a_separate_axis_from_business_readiness(storage):
    """Prepared and ready, with live writing still closed, is the NORMAL state."""
    _seed_draft(storage, CLIENT_A, box="BOX-A")
    proj = _project(storage, client_ref=CLIENT_A)
    assert proj["booking"]["ready"] is True
    assert proj["ready_to_generate_real_awb"] is True
    assert proj["release"]["live_allowlisted"] is False
    assert proj["release"]["production_write_ready"] is False
    assert proj["live_release_blocked"] is True


def test_release_reason_never_suggests_widening_the_allowlist(storage):
    _seed_draft(storage, CLIENT_A)
    reason = _project(storage, client_ref=CLIENT_A)["release"]["reason"]
    assert "governed live-booking process" in reason
    assert "*" not in reason
    assert "CARRIER_LIVE_ALLOWLIST" not in reason


def test_allowlist_reading_matches_the_live_gate_exactly(storage):
    """One string, two readers — they must never disagree about a batch."""
    from app.services.carrier.adapters.live import DhlExpressLiveAdapter
    from app.services.carrier.factory import CarrierConfig
    from app.services.carrier.models.shipment import CarrierAllowlistError

    for raw in ("", "  ", BATCH, f"other,{BATCH}", "other", "*", f" {BATCH} , other "):
        adapter = DhlExpressLiveAdapter(CarrierConfig(status="live", live_allowlist=raw))
        try:
            adapter._check_allowlist(BATCH)
            gate_allows = True
        except CarrierAllowlistError:
            gate_allows = False
        projected = _project(
            storage, settings_over={"carrier_live_allowlist": raw},
        )["release"]["live_allowlisted"]
        assert projected == gate_allows, raw


# ── server-side leg guard on the booking endpoint ───────────────────────────


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
        "CarrierCoordinator was reached — the leg guard must refuse first")
    app.dependency_overrides[_get_coordinator] = lambda: coord
    with patch("app.core.config.settings", _settings(storage)):
        yield TestClient(app, raise_server_exceptions=True), coord


def _book(client, **extra):
    body = {
        "shipper_account": "ACC123",
        "recipient_address": {"name": "N", "street": "S", "city": "C",
                              "country": "Poland", "phone": "+48100200300"},
        "declared_value": 100.0, "currency": "EUR", "weight_kg": 1.0,
        "dimensions": {"length": 10, "width": 10, "height": 10},
    }
    body.update(extra)
    return client.post(f"/api/v1/carrier/{BATCH}/shipment", json=body)


def test_booking_the_inbound_leg_fails_before_any_carrier_call(storage):
    """No outbound customer intent = a request to re-book the supplier's AWB."""
    with _booking_client(storage) as (client, coord):
        resp = _book(client)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "INBOUND_EXISTING_AWB"
    assert detail["existing_awb"] == INBOUND_AWB
    assert "No carrier request was sent." in detail["guidance"]
    coord.create_shipment.assert_not_called()


def test_a_valid_outbound_intent_is_not_refused_by_the_leg_guard(storage):
    """The guard must not become 'inbound batch ⇒ nothing may ever ship'."""
    _seed_draft(storage, CLIENT_A)
    with _booking_client(storage) as (client, coord):
        # The coordinator stub raises on call: reaching it proves the guard let
        # this request through, which is the behaviour under test.
        with pytest.raises(AssertionError, match="leg guard must refuse first"):
            _book(client, client_ref=CLIENT_A)


def test_leg_guard_is_scoped_per_customer_not_per_batch(storage):
    """Customer A having a draft does not authorise booking for customer B."""
    _seed_draft(storage, CLIENT_A)
    with _booking_client(storage) as (client, coord):
        resp = _book(client, client_ref=CLIENT_B)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "INBOUND_EXISTING_AWB"
    coord.create_shipment.assert_not_called()


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
    # Tracking facts are read through the existing inbound projector only —
    # no adapter, no carrier HTTP client, no second tracking authority.
    assert "adapters" not in src
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
                offenders.append(f"{path.name}: {phrase}")
    assert not offenders, offenders


# ── operator-facing contract pins (source-grep) ─────────────────────────────

_V2 = _ROOT / "app" / "static" / "v2"


def test_modal_preflights_before_the_operator_fills_it_in():
    """The raw carrier 422 must not be how the operator learns what is missing."""
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "PzApi.getBookingReadiness" in src
    assert 'data-testid="awb-readiness-panel"' in src
    assert 'data-testid="awb-readiness-blockers"' in src
    assert 'data-testid="awb-readiness-release-blocked"' in src
    # The inbound supplier leg is shown, never offered as a re-booking.
    assert 'data-testid="awb-readiness-inbound-leg"' in src
    api = (_V2 / "pz-api.js").read_text(encoding="utf-8")
    assert "getBookingReadiness:" in api
    assert "booking-readiness" in api


def test_preparation_is_possible_while_live_release_is_closed():
    """Release is a separate axis: a closed allowlist blocks the CALL, not the work."""
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "const releaseBlocked = !!(readiness && readiness.live_release_blocked);" in src
    assert "readinessBlocksSubmit" in src
    # Only the submit is gated — no field, panel or section is hidden by it.
    assert src.count("readinessBlocksSubmit") == 2


def test_ui_never_tells_the_operator_to_widen_the_allowlist():
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    start = src.index('data-testid="awb-readiness-release-blocked"')
    panel = src[start:start + 600]
    assert "governed" in panel
    assert "CARRIER_LIVE_ALLOWLIST" not in panel


def test_ups_guidance_states_the_real_external_blocker():
    """UPS has an adapter in the factory — the blocker is external, not code."""
    routes = (_ROOT / "app" / "api" / "routes_carrier_actions.py").read_text(encoding="utf-8")
    assert "UPS has no adapter" not in routes
    assert "customer-arranged" in routes
    factory = (_ROOT / "app" / "services" / "carrier" / "factory.py").read_text(encoding="utf-8")
    assert "UpsSandboxAdapter" in factory      # the adapter the old text denied


# ── HTTP surface ────────────────────────────────────────────────────────────


def test_readiness_endpoint_is_registered_and_creates_nothing(storage):
    """The literal path must not be captured by a /{batch_id}/... route."""
    _seed_draft(storage, CLIENT_A, box="BOX-A")
    with _booking_client(storage) as (client, coord):
        resp = client.get(
            f"/api/v1/carrier/{BATCH}/booking-readiness",
            params={"client_ref": CLIENT_A, "weight_kg": 2.5,
                    "declared_value": 900.0},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["batch_id"] == BATCH
    assert body["customer_scope"] == CLIENT_A
    assert body["shipment_intent"] == "outbound_customer"
    assert body["existing_awb"] == INBOUND_AWB
    assert body["ready_to_generate_real_awb"] is True
    assert body["live_release_blocked"] is True     # allowlist closed, correctly
    # A read projection books nothing.
    coord.create_shipment.assert_not_called()


def test_readiness_response_carries_no_contact_pii(storage):
    _seed_draft(storage, CLIENT_A)
    with _booking_client(storage) as (client, _):
        body = client.get(f"/api/v1/carrier/{BATCH}/booking-readiness",
                          params={"client_ref": CLIENT_A}).json()
    assert set(body["recipient"]) <= {"ready", "source", "company", "city",
                                      "country", "blocker"}
    assert "+48100200300" not in json.dumps(body)


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
        raise AssertionError(f"route not registered: {method} {path}")

    readiness = _guards("/api/v1/carrier/{batch_id}/booking-readiness", "GET")
    assert require_api_key in readiness
    # Same guard the existing shipment read carries — no weaker, no stronger.
    assert require_api_key in _guards("/api/v1/carrier/{batch_id}/shipment", "GET")
