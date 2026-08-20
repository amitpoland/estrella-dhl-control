"""FedEx and UPS ride the SAME carrier architecture as DHL.

Three providers, one of everything: one credential resolver, one coordinator,
one shipment persistence, one tracking authority, one neutral package model,
one Customer Master recipient path, one declared-value authority.

The point of this module is that adding a provider must never add an authority.
It also pins the honest half: a provider whose booking is implemented and whose
tracking is not provisioned must not be reported as ready, and a missing
external dependency must be named rather than papered over with a sandbox pass.

No live carrier call is made anywhere here.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_ADAPTERS = _ROOT / "app" / "services" / "carrier" / "adapters"
_FEDEX = _ADAPTERS / "fedex.py"
_UPS = _ADAPTERS / "ups.py"


# ── one factory, no silent substitution ─────────────────────────────────────


def test_factory_returns_each_provider_or_fails_closed():
    """Never a DHL fallback: an unusable provider raises, it does not substitute."""
    from app.services.carrier.factory import CarrierConfig, get_adapter
    from app.services.carrier.models.shipment import CarrierGateError

    fedex = get_adapter(CarrierConfig(status="live"), "FEDEX")
    assert type(fedex).__name__ == "FedExSandboxAdapter"

    # UPS fails closed when credentials are absent — and the failure names UPS.
    try:
        ups = get_adapter(CarrierConfig(status="live"), "UPS")
        assert type(ups).__name__ == "UpsSandboxAdapter"
    except CarrierGateError as exc:
        assert "UPS" in str(exc)

    for unknown in ("OTHER", "ROYALMAIL"):
        with pytest.raises(CarrierGateError):
            get_adapter(CarrierConfig(status="live"), unknown)


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_a_provider_adapter_never_falls_back_to_another_carrier(path):
    src = path.read_text(encoding="utf-8")
    body = src[src.index("class "):]
    for banned in ("DhlExpressLiveAdapter", "DhlExpressShadowAdapter",
                   "FedExSandboxAdapter" if path is _UPS else "UpsSandboxAdapter"):
        assert banned not in body, banned


# ── one of each authority ───────────────────────────────────────────────────


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_provider_consumes_the_neutral_package_model(path):
    """No dhl_packages / fedex_packages / ups_packages."""
    src = path.read_text(encoding="utf-8")
    assert "resolve_packages" in src
    for banned in ("fedex_packages", "ups_packages", "dhl_packages"):
        assert banned not in src, banned


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_provider_reuses_the_shared_party_builders(path):
    """Recipient identity has ONE path; a provider may reshape it, never re-source it."""
    src = path.read_text(encoding="utf-8")
    assert "_build_receiver_details" in src and "_build_shipper_details" in src
    for banned in ("customer_master", "resolve_delivery_address",
                   "derive_awb_address_authority"):
        assert banned not in src, banned


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_provider_reuses_the_shared_idempotency_key(path):
    src = path.read_text(encoding="utf-8")
    assert "compute_idempotency_key" in src


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_provider_calculates_no_commercial_value_of_its_own(path):
    """Declared value arrives on the request; an adapter never recomputes it.

    Totalling the neutral packages' already-measured weights for a carrier
    payload is serialization, not a second authority — so the ban is on
    COMMERCIAL arithmetic specifically, not on arithmetic.
    """
    src = path.read_text(encoding="utf-8")
    for banned in ("unit_price", "line_total", "editable_lines",
                   "declared_value =", "CommercialChargeAuthority"):
        assert banned not in src, banned
    assert "declared_value" in src            # it is CONSUMED
    # Every aggregation in the adapter is over packages, never over money.
    for line in src.splitlines():
        if "sum(" in line:
            assert "weight" in line or "pkg" in line or "packages" in line, line.strip()


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_provider_owns_no_shipment_store(path):
    src = path.read_text(encoding="utf-8")
    for banned in ("CREATE TABLE", "INSERT INTO", "sqlite3", "shipment_db"):
        assert banned not in src, banned


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_provider_refuses_to_invent_a_service(path):
    """Picking a service picks a price — it is never defaulted."""
    src = path.read_text(encoding="utf-8")
    assert "_SERVICE_NOT_SELECTED" in src


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_provider_production_endpoint_is_refused(path):
    src = path.read_text(encoding="utf-8")
    assert "_PRODUCTION_BLOCKED" in src


# ── tracking: one authority, honest provisioning ────────────────────────────


def test_tracking_support_is_declared_once():
    """The list of carriers tracking_service can call has exactly one home."""
    from app.services import tracking_service as ts

    assert ts.supports_tracking("DHL") is True
    assert ts.supports_tracking("FedEx") is True
    assert ts.supports_tracking("UPS") is False
    assert ts.supports_tracking("") is False


def test_ups_adapter_refuses_to_become_a_second_tracking_authority():
    """UPS tracking lands in tracking_service or nowhere — never in the adapter."""
    from app.services.carrier.adapters.ups import UpsSandboxAdapter
    from app.services.carrier.models.shipment import CarrierGateError

    src = _UPS.read_text(encoding="utf-8")
    fn = src[src.index("def get_shipment("):src.index("def _post_ship(")]
    assert "UPS_TRACK_NOT_PROVISIONED" in fn
    # It refuses; it does not fetch.
    assert "httpx.get" not in fn and "_token(" not in fn

    with pytest.raises(CarrierGateError, match="UPS_TRACK_NOT_PROVISIONED"):
        UpsSandboxAdapter.get_shipment(object(), "1Z999")


def test_fedex_tracking_delegates_to_the_one_tracking_authority():
    src = _FEDEX.read_text(encoding="utf-8")
    fn = src[src.index("def get_shipment("):src.index("def _post_ship(")]
    assert "tracking_service" in fn


# ── Carrier Master reports capability truth, not a roll-up ──────────────────


def test_ups_is_not_reported_ready_on_credentials_alone():
    """Booking implemented + tracking not provisioned != a ready provider."""
    from app.api.routes_master_data import _capability_provisioned

    provisioned, reason = _capability_provisioned("UPS", "track")
    assert provisioned is False
    assert "not provisioned" in reason
    assert "tracking_service" in reason

    # Shipping has no separate provisioning axis — the adapter is the wiring.
    assert _capability_provisioned("UPS", "ship") == (True, None)
    assert _capability_provisioned("DHL", "track") == (True, None)
    assert _capability_provisioned("FEDEX", "track") == (True, None)


def test_readiness_matrix_lists_ups_tracking_so_it_cannot_be_read_as_ready():
    from app.api.routes_master_data import _READINESS_MATRIX

    ups = [row for row in _READINESS_MATRIX if row[0] == "UPS"]
    assert ups, "UPS missing from the readiness matrix"
    assert any("track" in row[2] for row in ups), \
        "UPS tracking must appear, or the row reads as a ready provider"


def test_provider_readiness_rolls_up_capability_ready_not_configured():
    """A configured-but-unprovisioned capability must not count as ready."""
    import app.api.routes_master_data as rmd

    fn = ast.parse(inspect.getsource(rmd.carriers_readiness_endpoint)).body[0]
    code = ast.dump(fn)
    assert "capability_ready" in code
    # The old roll-up asked only whether credentials existed.
    assert "'configured'" not in code and '"configured"' not in code


def test_carriers_page_shows_an_unprovisioned_capability_as_such():
    src = (_ROOT / "app" / "static" / "v2" / "carriers-page.jsx").read_text(encoding="utf-8")
    assert "cr.provisioned === false" in src
    assert "not provisioned" in src
    assert "not_provisioned_reason" in src


# ── no second credential resolver ───────────────────────────────────────────


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_provider_resolves_credentials_through_the_one_bridge(path):
    src = path.read_text(encoding="utf-8")
    assert "consumer_bridge" in src
    for banned in ("os.environ", "os.getenv", "dotenv", "load_dotenv"):
        assert banned not in src, banned


@pytest.mark.parametrize("path", [_FEDEX, _UPS])
def test_provider_never_logs_a_secret(path):
    src = path.read_text(encoding="utf-8")
    for line in src.splitlines():
        if "log." in line and "client_secret" in line:
            raise AssertionError("secret reachable in a log call: " + line.strip())
