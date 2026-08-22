"""Booking authorization = authorized operator + valid data + no duplicate.

The per-batch ``carrier_live_allowlist`` was retired from the DHL and FedEx
booking paths on 2026-08-22. It had been promoted from a release control into
transaction authority: an operator whose shipment satisfied every business
authority was still refused until someone edited ``.env`` and restarted the
service. This file pins what replaced it, and — more importantly — pins the
protection that had to be REAL before the allowlist could go.

The hole the allowlist was accidentally covering
------------------------------------------------
``compute_idempotency_key`` hashes batch_id, shipper_account, weight, declared
value and currency. It answers "is this the same REQUEST". It does NOT answer
"is this the same SHIPMENT": an operator who books, then corrects the weight
from 2.4 to 2.5 kg and presses Generate AWB again, computes a DIFFERENT key,
misses the replay path entirely, and books a SECOND chargeable AWB for one
parcel. ``CarrierCoordinator._refuse_duplicate_leg`` closes that, and
``test_correcting_the_weight_does_not_book_a_second_awb`` is the pin.

Every identifier here is synthetic. No batch, AWB, customer or contractor from
the real system appears in this file or in the runtime it pins — see
``test_no_shipment_specific_identifier_in_the_runtime_delta``.

Named test_carrier_* deliberately: these pins sit inside the metered carrier
glob in .claude/contracts/test-baseline.md and count toward its floor.

No live calls. All carrier HTTP is mocked; DBs are tmp_path only.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig, get_adapter
from app.services.carrier.adapters.fedex import FedExSandboxAdapter
from app.services.carrier.adapters.live import DhlExpressLiveAdapter
from app.services.carrier.models.shipment import (
    CarrierConfigError,
    CarrierDuplicateBookingError,
    CarrierGateError,
    ShipmentRequest,
    ShipmentState,
    compute_idempotency_key,
)
from app.services.carrier.persistence import shipment_db

# Synthetic throughout — never a real batch, AWB or customer.
_BATCH = "SHIPMENT_SYNTHETIC_1001"
_OTHER_BATCH = "SHIPMENT_SYNTHETIC_1002"
_CLIENT = "SYNTHETIC CLIENT A"
_OTHER_CLIENT = "SYNTHETIC CLIENT B"

_RUNTIME_DELTA = [
    "app/services/carrier/adapters/live.py",
    "app/services/carrier/adapters/fedex.py",
    "app/services/carrier/coordinator.py",
    "app/services/carrier/factory.py",
    "app/services/carrier/booking_readiness.py",
    "app/services/carrier/persistence/shipment_db.py",
    "app/api/routes_carrier_actions.py",
]
_APP = Path(__file__).resolve().parents[1]


# ── harness ──────────────────────────────────────────────────────────────────


def _req(
    batch_id: str = _BATCH,
    *,
    client_ref: str = _CLIENT,
    weight_kg: float = 2.4,
) -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=batch_id,
        shipper_account="000000000",
        client_ref=client_ref,
        recipient_address={
            "name": "Synthetic Receiver", "street": "Test 1", "city": "Vilnius",
            "postal_code": "01000", "country_code": "LT", "phone": "+37060000000",
        },
        declared_value=500.0,
        currency="EUR",
        weight_kg=weight_kg,
        dimensions={"length_cm": 20, "width_cm": 15, "height_cm": 10},
        product_code="U",
        incoterm="DAP",
    )


def _dhl_config(*, allowlist: str = "", api_key: str = "k", api_secret: str = "s") -> CarrierConfig:
    """A live DHL config. ``allowlist`` defaults EMPTY on purpose: every DHL
    booking test in this file runs with the allowlist that used to refuse
    everything, so a regression that re-attaches the gate fails here first."""
    return CarrierConfig(
        status="live",
        api_key=api_key,
        api_secret=api_secret,
        api_url="https://express.api.dhl.com",
        use_sandbox=False,
        account_number="000000000",
        live_allowlist=allowlist,
    )


def _coordinator(tmp_path, config: CarrierConfig = None) -> CarrierCoordinator:
    return CarrierCoordinator(CoordinatorConfig(
        carrier_config=config if config is not None else _dhl_config(),
        shipment_db_path=tmp_path / "shipments.db",
        shadow_log_db_path=tmp_path / "shadow.db",
    ))


@contextmanager
def _mock_dhl_settings():
    mock = MagicMock()
    mock.dhl_express_shipper_name = "Synthetic Shipper"
    mock.dhl_express_shipper_address1 = "Test 1"
    mock.dhl_express_shipper_city = "Warszawa"
    mock.dhl_express_shipper_postal_code = "02-174"
    mock.dhl_express_shipper_country_code = "PL"
    mock.dhl_express_shipper_phone = "+48000000000"
    mock.dhl_express_shipper_email = "synthetic@example.invalid"
    mock.carrier_storage_root = None
    mock.outbound_tracking_registration_enabled = False
    with patch("app.core.config.settings", mock), \
         patch("app.services.carrier.coordinator.settings", mock):
        yield mock


@contextmanager
def _dhl_returns(awb: str):
    """Mock the DHL POST. Yields the mock so a test can assert it was NOT called."""
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = {"shipmentTrackingNumber": awb, "documents": []}
    with patch("app.services.carrier.adapters.live.httpx.Client") as cls:
        client = cls.return_value.__enter__.return_value
        client.post.return_value = resp
        client.get.side_effect = Exception("rates unavailable")  # product discovery
        yield client


def _book(coordinator, request, awb: str):
    with _mock_dhl_settings(), _dhl_returns(awb):
        return coordinator.create_shipment(request)


# ── 1. a new DHL shipment books without allowlist membership ─────────────────


def test_a_new_dhl_shipment_books_with_an_empty_allowlist(tmp_path):
    """The exact refusal this campaign removed: an empty allowlist used to
    raise CarrierAllowlistError before the operator's request was even read."""
    result = _book(_coordinator(tmp_path), _req(), "AWB-SYNTH-0001")
    assert result.tracking_ref == "AWB-SYNTH-0001"
    assert result.state is ShipmentState.COMPLETE
    assert result.simulated is False


def test_a_new_dhl_shipment_books_when_the_allowlist_names_only_other_batches(tmp_path):
    """Membership is not consulted at all — a populated allowlist that omits
    this batch is the case the operator hit in production."""
    coordinator = _coordinator(tmp_path, _dhl_config(allowlist=_OTHER_BATCH))
    result = _book(coordinator, _req(), "AWB-SYNTH-0002")
    assert result.tracking_ref == "AWB-SYNTH-0002"


def test_the_dhl_adapter_has_no_allowlist_guard_left(tmp_path):
    """Structural: the guard is gone, not merely bypassed by configuration."""
    adapter = DhlExpressLiveAdapter(_dhl_config(allowlist=""))
    assert not hasattr(adapter, "_check_allowlist")
    assert not hasattr(adapter, "_allowlist")


# ── 2. FedEx books on configuration, not on release ──────────────────────────


def _fedex(*, production: bool, allowlist: str = "") -> FedExSandboxAdapter:
    return FedExSandboxAdapter(SimpleNamespace(
        status="live", fedex_allow_production=production, live_allowlist=allowlist,
    ))


@contextmanager
def _fedex_credentials(client_id="cid", client_secret="csec"):
    with patch(
        "app.services.carrier.adapters.fedex._fedex_fields",
        return_value={"client_id": client_id, "client_secret": client_secret},
    ):
        yield


def test_fedex_production_is_allowed_without_allowlist_membership():
    """Configured for production + credentials resolvable ⇒ the operator books.
    No batch is named anywhere, and none needs to be."""
    with _fedex_credentials():
        _fedex(production=True, allowlist="")._check_production_allowed(_BATCH)
        _fedex(production=True, allowlist=_OTHER_BATCH)._check_production_allowed(_BATCH)


def test_fedex_treats_every_batch_alike():
    """No per-batch decision survives: the same config answers the same way for
    any batch_id, which is what "not a release list" means operationally."""
    with _fedex_credentials():
        adapter = _fedex(production=True)
        for batch in (_BATCH, _OTHER_BATCH, "SHIPMENT_SYNTHETIC_9999"):
            adapter._check_production_allowed(batch)


def test_fedex_production_still_requires_the_configuration_flag():
    """The kill switch survives — it is configuration, not per-shipment release."""
    with _fedex_credentials():
        with pytest.raises(CarrierGateError, match="FEDEX_PRODUCTION_BLOCKED"):
            _fedex(production=False)._check_production_allowed(_BATCH)


# ── 6. missing credentials still fail safely (and as CONFIGURATION) ──────────


def test_fedex_missing_credentials_fail_closed_as_configuration():
    """A misconfigured FedEx must refuse BEFORE any token round-trip, and must
    not be mistaken for a batch that needs releasing."""
    with _fedex_credentials(client_id="", client_secret=""):
        with pytest.raises(CarrierConfigError, match="FEDEX_NOT_CONFIGURED"):
            _fedex(production=True)._check_production_allowed(_BATCH)


@pytest.mark.parametrize("field", ["api_key", "api_secret"])
def test_dhl_missing_credentials_still_fail_closed(tmp_path, field):
    adapter = DhlExpressLiveAdapter(_dhl_config(**{field: ""}))
    with _mock_dhl_settings(), patch(
        "app.services.carrier.adapters.live.httpx.Client"
    ) as cls:
        with pytest.raises(CarrierConfigError):
            adapter.create_shipment(_req())
        cls.assert_not_called()      # no HTTP, so nothing was charged


def test_a_credential_refusal_never_echoes_the_credential():
    adapter = DhlExpressLiveAdapter(_dhl_config(api_key="", api_secret="super-secret"))
    with pytest.raises(CarrierConfigError) as exc:
        adapter.create_shipment(_req())
    assert "super-secret" not in str(exc.value)


# ── 3 + 4. the canonical leg cannot take a second AWB ────────────────────────


def test_an_identical_retry_replays_and_never_reaches_the_carrier(tmp_path):
    """Same request ⇒ same key ⇒ stored result, zero adapter calls."""
    coordinator = _coordinator(tmp_path)
    first = _book(coordinator, _req(), "AWB-SYNTH-0003")

    with _mock_dhl_settings(), _dhl_returns("AWB-SHOULD-NEVER-EXIST") as client:
        second = coordinator.create_shipment(_req())
        client.post.assert_not_called()

    assert second.tracking_ref == first.tracking_ref == "AWB-SYNTH-0003"
    assert second.replayed is True


def test_correcting_the_weight_does_not_book_a_second_awb(tmp_path):
    """THE regression. A corrected weight computes a DIFFERENT idempotency key,
    so the replay path cannot fire — before this guard existed, this booked a
    second chargeable AWB for one parcel."""
    coordinator = _coordinator(tmp_path)
    _book(coordinator, _req(weight_kg=2.4), "AWB-SYNTH-0004")

    assert compute_idempotency_key(_req(weight_kg=2.4)) != \
        compute_idempotency_key(_req(weight_kg=2.5))

    with _mock_dhl_settings(), _dhl_returns("AWB-SHOULD-NEVER-EXIST") as client:
        with pytest.raises(CarrierDuplicateBookingError) as exc:
            coordinator.create_shipment(_req(weight_kg=2.5))
        client.post.assert_not_called()      # no carrier request was sent

    assert "AWB-SYNTH-0004" in str(exc.value)
    assert exc.value.existing.get("tracking_ref") == "AWB-SYNTH-0004"


@pytest.mark.parametrize("changed", [
    {"weight_kg": 9.9},
])
def test_the_duplicate_refusal_leaves_no_new_row(tmp_path, changed):
    """A refusal must not write the PENDING anchor: a leftover row would be a
    phantom booking in Logistics and in every document projection."""
    coordinator = _coordinator(tmp_path)
    _book(coordinator, _req(), "AWB-SYNTH-0005")
    db = tmp_path / "shipments.db"
    before = sqlite3.connect(str(db)).execute(
        "SELECT COUNT(*) FROM carrier_shipments").fetchone()[0]

    with _mock_dhl_settings(), _dhl_returns("AWB-SHOULD-NEVER-EXIST"):
        with pytest.raises(CarrierDuplicateBookingError):
            coordinator.create_shipment(_req(**changed))

    after = sqlite3.connect(str(db)).execute(
        "SELECT COUNT(*) FROM carrier_shipments").fetchone()[0]
    assert after == before


def test_the_duplicate_error_is_a_gate_error_subclass():
    """Fail-closed by inheritance: a caller that only handles the broad type
    still REFUSES the booking rather than falling through to the adapter."""
    assert issubclass(CarrierDuplicateBookingError, CarrierGateError)


def test_an_unreadable_shipment_store_fails_closed(tmp_path):
    """Wrong-in-your-favour is the severe class (Lesson Q rule 6): a failed
    read must never be interpreted as "no duplicate exists"."""
    coordinator = _coordinator(tmp_path)
    with patch(
        "app.services.carrier.coordinator._db_active_booking",
        side_effect=sqlite3.OperationalError("database is locked"),
    ):
        with _mock_dhl_settings(), _dhl_returns("AWB-SHOULD-NEVER-EXIST") as client:
            with pytest.raises(CarrierDuplicateBookingError, match="Cannot confirm"):
                coordinator.create_shipment(_req())
            client.post.assert_not_called()


# ── the operator's release valve — never a config-file edit ──────────────────


def test_retiring_the_label_releases_the_leg_for_re_booking(tmp_path):
    """The operator is never stuck. Marking the existing AWB DO NOT USE is an
    attributed, audited action that frees the leg — no .env edit, no restart,
    no allowlist. Nothing is cancelled or voided at the carrier."""
    coordinator = _coordinator(tmp_path)
    _book(coordinator, _req(), "AWB-SYNTH-0006")

    with _mock_dhl_settings(), _dhl_returns("AWB-SHOULD-NEVER-EXIST"):
        with pytest.raises(CarrierDuplicateBookingError):
            coordinator.create_shipment(_req(weight_kg=2.5))

    shipment_db.mark_do_not_use(
        tmp_path / "shipments.db", _BATCH, "AWB-SYNTH-0006",
        reason="misprinted label", operator="synthetic-operator",
    )

    result = _book(coordinator, _req(weight_kg=2.5), "AWB-SYNTH-0007")
    assert result.tracking_ref == "AWB-SYNTH-0007"


# ── 5. different shipments stay independently bookable ───────────────────────


def test_a_different_batch_is_unaffected_by_another_batchs_booking(tmp_path):
    coordinator = _coordinator(tmp_path)
    _book(coordinator, _req(_BATCH), "AWB-SYNTH-0008")
    result = _book(coordinator, _req(_OTHER_BATCH), "AWB-SYNTH-0009")
    assert result.tracking_ref == "AWB-SYNTH-0009"


def test_a_second_customer_in_the_same_batch_is_still_bookable(tmp_path):
    """One import batch splits into several per-client legs. Client B's AWB
    must not be refused because client A already has one — that would be the
    duplicate guard over-blocking, which is as much a defect as under-blocking."""
    coordinator = _coordinator(tmp_path)
    _book(coordinator, _req(client_ref=_CLIENT), "AWB-SYNTH-0010")
    result = _book(coordinator, _req(client_ref=_OTHER_CLIENT), "AWB-SYNTH-0011")
    assert result.tracking_ref == "AWB-SYNTH-0011"


def test_the_leg_read_scopes_to_the_client(tmp_path):
    """Direct pin on the canonical read, independent of the coordinator."""
    coordinator = _coordinator(tmp_path)
    _book(coordinator, _req(client_ref=_CLIENT), "AWB-SYNTH-0012")
    db = tmp_path / "shipments.db"

    assert (shipment_db.get_active_booking_for_leg(db, _BATCH, _CLIENT) or {}) \
        .get("tracking_ref") == "AWB-SYNTH-0012"
    assert shipment_db.get_active_booking_for_leg(db, _BATCH, _OTHER_CLIENT) is None
    assert shipment_db.get_active_booking_for_leg(db, _OTHER_BATCH, _CLIENT) is None


def test_an_unscoped_request_sees_the_batch_level_leg(tmp_path):
    """A blank client_ref does NOT mean "match nothing". An unscoped booking
    request identifies the batch itself, so it must see the batch's bookings —
    otherwise the one request that names no customer is the one that can
    duplicate freely."""
    coordinator = _coordinator(tmp_path)
    _book(coordinator, _req(client_ref=_CLIENT), "AWB-SYNTH-0013")
    db = tmp_path / "shipments.db"

    for blank in (None, "", "   "):
        assert (shipment_db.get_active_booking_for_leg(db, _BATCH, blank) or {}) \
            .get("tracking_ref") == "AWB-SYNTH-0013", repr(blank)
        assert shipment_db.get_active_booking_for_leg(db, _OTHER_BATCH, blank) is None

    with _mock_dhl_settings(), _dhl_returns("AWB-SHOULD-NEVER-EXIST") as client:
        with pytest.raises(CarrierDuplicateBookingError):
            coordinator.create_shipment(_req(client_ref=None))
        client.post.assert_not_called()


def test_a_simulated_shadow_booking_does_not_block_a_real_one(tmp_path):
    """A shadow SIM- reference is not a parcel anyone can hand to a courier.
    Letting it block a real booking would be the same over-blocking this guard
    replaced the allowlist to end."""
    shadow = _coordinator(tmp_path, CarrierConfig(status="shadow"))
    simulated = shadow.create_shipment(_req())
    assert simulated.simulated is True
    assert simulated.tracking_ref

    db = tmp_path / "shipments.db"
    assert shipment_db.get_active_booking_for_leg(db, _BATCH, _CLIENT) is None

    live = _coordinator(tmp_path)                      # same DBs, live config
    result = _book(live, _req(weight_kg=2.5), "AWB-SYNTH-0014")
    assert result.tracking_ref == "AWB-SYNTH-0014"
    assert result.simulated is False

    # ...and now the REAL one does block.
    assert (shipment_db.get_active_booking_for_leg(db, _BATCH, _CLIENT) or {}) \
        .get("tracking_ref") == "AWB-SYNTH-0014"


def test_a_failed_attempt_is_not_a_booking(tmp_path):
    """Only a real completed booking blocks. A failed row has no AWB, so the
    leg must stay bookable — otherwise one carrier error strands the shipment."""
    db = tmp_path / "shipments.db"
    shipment_db.init_db(db)
    from app.services.carrier.models.shipment import ShipmentMode, ShipmentResult
    shipment_db.insert_shipment(
        db,
        # SHADOW/PENDING is the coordinator's own crash-safe anchor shape:
        # insert_shipment refuses a LIVE insert outright, so this is what a
        # real interrupted booking actually looks like on disk.
        ShipmentResult(idempotency_key="k-failed", mode=ShipmentMode.SHADOW,
                       state=ShipmentState.PENDING, simulated=True),
        _BATCH, _CLIENT,
    )
    shipment_db.update_state(db, "k-failed", ShipmentState.FAILED, error="carrier 500")
    assert shipment_db.get_active_booking_for_leg(db, _BATCH, _CLIENT) is None


# ── 7. UPS still cannot book ─────────────────────────────────────────────────


def test_ups_is_still_unbookable():
    """UPS is tracking-link only. Nothing in this campaign opened a UPS booking
    path, and an unconfigured UPS is never substituted with DHL."""
    with patch(
        "app.services.carrier.adapters.ups.ups_credentials_present", return_value=False
    ):
        with pytest.raises(CarrierGateError, match="UPS_NOT_CONFIGURED"):
            get_adapter(_dhl_config(), provider="UPS")


def test_ups_has_no_production_field_on_the_carrier_config():
    """UpsSandboxAdapter reads ups_allow_production via getattr; the field's
    absence from CarrierConfig is what keeps UPS sandbox-only."""
    assert not hasattr(CarrierConfig(status="live"), "ups_allow_production")


# ── the kill switch survives ─────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["pending", "not-a-status"])
def test_carrier_api_status_is_still_the_kill_switch(status):
    """Removing the per-batch list did not remove the service-wide gate."""
    with pytest.raises(CarrierGateError):
        get_adapter(CarrierConfig(status=status))


def test_shadow_status_still_yields_a_simulating_adapter():
    adapter = get_adapter(CarrierConfig(status="shadow"))
    assert type(adapter).__name__ == "DhlExpressShadowAdapter"


# ── readiness stops reporting a release that no longer exists ────────────────


def test_readiness_never_reports_a_batch_as_specifically_allowlisted():
    from app.services.carrier.booking_readiness import _release_state
    state = _release_state(_BATCH, SimpleNamespace(
        carrier_api_status="live", carrier_live_allowlist="",
        dhl_express_api_key="k", dhl_express_api_secret="s",
        dhl_express_account_number="000000000",
    ))
    assert state["specifically_allowlisted"] is False
    assert state["ready"] is True
    assert state["reason"] is None


def test_readiness_gives_the_same_answer_for_every_batch():
    """Per-shipment release is gone, so the projection must not vary by batch."""
    from app.services.carrier.booking_readiness import _release_state
    settings = SimpleNamespace(
        carrier_api_status="live", carrier_live_allowlist=_OTHER_BATCH,
        dhl_express_api_key="k", dhl_express_api_secret="s",
        dhl_express_account_number="000000000",
    )
    assert _release_state(_BATCH, settings) == _release_state(_OTHER_BATCH, settings)


def test_readiness_never_tells_the_operator_to_release_or_allowlist():
    """No operator-facing text may send someone back to a process that is gone."""
    from app.services.carrier.booking_readiness import _release_state
    for status in ("live", "shadow", "pending"):
        reason = _release_state(_BATCH, SimpleNamespace(
            carrier_api_status=status, carrier_live_allowlist="",
            dhl_express_api_key="k", dhl_express_api_secret="s",
            dhl_express_account_number="000000000",
        ))["reason"] or ""
        low = reason.lower()
        for banned in ("allowlist", "release this", "governed live-booking"):
            assert banned not in low, f"{status}: {reason!r}"


# ── 8. no shipment-specific hardcoding ───────────────────────────────────────


def test_no_shipment_specific_identifier_in_the_runtime_delta():
    """No batch id, AWB, customer or contractor id may be baked into the files
    this campaign changed. The fix is a workflow class, not a patch for one
    shipment (Lesson I)."""
    patterns = [
        (re.compile(r"SHIPMENT_\d{6,}"), "a real batch id"),
        (re.compile(r"\b\d{10}\b"), "a bare 10-digit AWB / contractor id"),
        (re.compile(r"c8d73183|1545637144|6696117050"), "an identifier from the incident"),
    ]
    offenders = []
    for rel in _RUNTIME_DELTA:
        text = (_APP / rel).read_text(encoding="utf-8")
        for line_no, raw in enumerate(text.splitlines(), 1):
            # Inline comments are stripped: "hardcoding" is about what the code
            # DOES, and a worked example in prose is not a code path. (One such
            # example predates this campaign — routes_carrier_actions.py cites a
            # real AWB in a field comment; tracked separately rather than
            # widened into this pin, which would make the pin about prose.)
            line = raw.split("#", 1)[0]
            for pattern, what in patterns:
                if pattern.search(line):
                    offenders.append(f"{rel}:{line_no} — {what}: {raw.strip()[:90]}")
    assert not offenders, "shipment-specific identifiers in runtime:\n" + "\n".join(offenders)


# ── the AWB modal offers no release step ─────────────────────────────────────

_MODAL = _APP / "app" / "static" / "v2" / "proforma-detail.jsx"


def test_the_awb_modal_says_ready_without_any_release_step():
    """A complete, valid shipment reads "Ready to create <carrier> AWB" and
    nothing sends the operator to a release or allowlist process."""
    src = _MODAL.read_text(encoding="utf-8")
    assert "Ready to create {selectedCarrier} AWB" in src
    # Scoped to the CARRIER sense of the word: this file legitimately uses
    # "allowlist" elsewhere for a field-projection allowlist, which is an
    # unrelated concept and must not be caught here.
    for banned in ("carrier_live_allowlist", "CARRIER_LIVE_ALLOWLIST",
                   "live-booking process", "release this shipment",
                   "Release this shipment", "widen the allowlist",
                   "add this batch", "Add this batch"):
        assert banned not in src, banned


def test_the_modal_never_reads_a_per_shipment_release_signal():
    """live_release / specifically_allowlisted must not become a UI gate: they
    describe service-wide carrier mode, not this shipment's validity."""
    src = _MODAL.read_text(encoding="utf-8")
    for banned in ("live_release", "specifically_allowlisted"):
        assert banned not in src, banned


def test_a_structured_refusal_reaches_the_operator_as_words():
    """The route answers already-booked with a structured detail carrying
    ``error`` and ``guidance``. JSON.stringify'ing the object buried both; the
    modal must read them."""
    src = _MODAL.read_text(encoding="utf-8")
    assert "[msg.error, msg.guidance].filter(Boolean).join(' ')" in src


def test_no_runtime_file_still_reads_the_allowlist_for_a_booking_decision():
    """Structural pin on the removal itself: the two adapters must not contain
    a live_allowlist read at all. Prose mentioning why it was retired is fine;
    an attribute or settings read is not."""
    read = re.compile(r"(config|settings|self)\.\w*live_allowlist|"
                      r"getattr\([^)]*live_allowlist")
    for rel in ("app/services/carrier/adapters/live.py",
                "app/services/carrier/adapters/fedex.py"):
        text = (_APP / rel).read_text(encoding="utf-8")
        assert not read.search(text), f"{rel} still reads live_allowlist"
