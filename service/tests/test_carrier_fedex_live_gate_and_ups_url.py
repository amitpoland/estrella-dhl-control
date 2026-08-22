"""FedEx production gate + UPS URL-only tracking.

Two capabilities, one campaign:

  * FedEx becomes bookable in production through the SAME carrier authority
    DHL uses — but only behind two gates read from the same settings.
  * UPS gets a tracking link and nothing else: no API, no credential, no
    invented status.

Every identifier here is synthetic. Nothing in this file names a real batch,
AWB, customer, contractor or proforma, and neither does the runtime code it
pins — see ``test_no_shipment_specific_identifier_in_the_runtime_delta``.

Named test_carrier_* deliberately: these pins sit inside the metered carrier
glob in .claude/contracts/test-baseline.md and count toward its floor.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app.services.carrier.adapters.fedex import FedExSandboxAdapter
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import CarrierGateError
from app.services.tracking_service import (
    TRACKING_SUPPORTED_CARRIERS,
    _dhl_tracking_url,
    _fedex_tracking_url,
    _ups_tracking_url,
    supports_tracking,
    tracking_url_for,
)

# Synthetic throughout. "1Z" + 16 alphanumerics is the UPS reference shape.
_UPS_REF = "1Z999AA10123456784"
_FEDEX_REF = "794600000001"
_DHL_REF = "1234567890"
_BATCH = "SHIPMENT_SYNTHETIC_0001"
_OTHER_BATCH = "SHIPMENT_SYNTHETIC_0002"


def _fedex(*, production: bool, allowlist: str = "") -> FedExSandboxAdapter:
    return FedExSandboxAdapter(
        SimpleNamespace(
            status="live",
            fedex_allow_production=production,
            live_allowlist=allowlist,
        )
    )


# ── FedEx: the two gates ─────────────────────────────────────────────────────


def test_production_is_refused_without_the_flag():
    with pytest.raises(CarrierGateError, match="FEDEX_PRODUCTION_BLOCKED"):
        _fedex(production=False)._check_production_allowed(_BATCH)


def test_the_flag_alone_does_not_release_a_booking():
    """An empty allowlist blocks even with the kill switch turned on."""
    with pytest.raises(CarrierGateError, match="carrier_live_allowlist is empty"):
        _fedex(production=True, allowlist="")._check_production_allowed(_BATCH)


def test_a_wildcard_allowlist_is_refused():
    """DHL honours "*"; FedEx never does — release is one batch at a time."""
    with pytest.raises(CarrierGateError, match="wildcard"):
        _fedex(production=True, allowlist="*")._check_production_allowed(_BATCH)


def test_a_batch_outside_the_allowlist_is_refused():
    adapter = _fedex(production=True, allowlist=_OTHER_BATCH)
    with pytest.raises(CarrierGateError, match="not in"):
        adapter._check_production_allowed(_BATCH)


def test_both_gates_cleared_releases_the_batch_and_only_that_batch():
    adapter = _fedex(production=True, allowlist=f"{_OTHER_BATCH},{_BATCH}")
    adapter._check_production_allowed(_BATCH)          # allowed: no raise
    with pytest.raises(CarrierGateError):
        adapter._check_production_allowed("SHIPMENT_SYNTHETIC_0003")


def test_the_base_url_and_credential_environment_follow_the_gate():
    sandbox = _fedex(production=False)
    assert sandbox._base_url() == "https://apis-sandbox.fedex.com"
    assert sandbox._environment() == "sandbox"

    live = _fedex(production=True, allowlist=_BATCH)
    assert live._base_url() == "https://apis.fedex.com"
    assert live._environment() == "production"


def test_production_credentials_are_never_read_on_a_sandbox_booking(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        "app.services.carrier.credentials.consumer_bridge.resolve_carrier_credentials",
        lambda carrier, capability, environment, **kw: seen.append(environment)
        or SimpleNamespace(fields={"client_id": "cid", "client_secret": "sec"}),
    )
    _fedex(production=False)._credentials()
    assert seen == ["sandbox"]


def test_a_blocked_booking_never_reaches_fedex(monkeypatch):
    """The gate fires before the token request, not after."""
    def _explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("a blocked FedEx booking opened an HTTP connection")

    monkeypatch.setattr("app.services.carrier.adapters.fedex.httpx.post", _explode)
    monkeypatch.setattr(
        "app.services.carrier.adapters.fedex._fedex_fields",
        lambda *_a, **_k: {"client_id": "cid", "client_secret": "sec"},
    )
    from app.services.carrier.models.shipment import ShipmentRequest

    request = ShipmentRequest(
        batch_id=_BATCH,
        shipper_account="000000000",
        recipient_address={
            "address_line1": "1 Test Street",
            "city": "Warsaw",
            "postal_code": "00-001",
            "country_code": "PL",
            "phone": "+48000000000",
        },
        declared_value=100.0,
        currency="EUR",
        weight_kg=1.0,
        dimensions={"length_cm": 10, "width_cm": 10, "height_cm": 10},
        product_code="INTERNATIONAL_PRIORITY",
        incoterm="DAP",
        description="Jewellery",
    )
    with pytest.raises(CarrierGateError, match="FEDEX_PRODUCTION_BLOCKED"):
        _fedex(production=True, allowlist=_OTHER_BATCH).create_shipment(request)


def test_carrier_config_defaults_fedex_production_off():
    assert CarrierConfig(status="live").fedex_allow_production is False


def test_ups_has_no_production_field_so_ups_stays_sandbox_only():
    """UPS must not gain a production switch from this campaign."""
    assert not hasattr(CarrierConfig(status="live"), "ups_allow_production")


# ── DHL regression: the shared abstraction still behaves as it did ───────────


def test_dhl_live_allowlist_semantics_are_unchanged():
    """DHL keeps its own wildcard tolerance and its own exception type.

    FedEx raises CarrierGateError for every gate refusal (its established
    error contract); DHL raises the sibling CarrierAllowlistError. Both map
    to 422 in routes_carrier_actions — the point here is that adding the
    FedEx gate moved neither.
    """
    from app.services.carrier.adapters.live import DhlExpressLiveAdapter
    from app.services.carrier.models.shipment import CarrierAllowlistError

    wildcard = DhlExpressLiveAdapter(CarrierConfig(status="live", live_allowlist="*"))
    wildcard._check_allowlist(_BATCH)                       # DHL still honours "*"

    named = DhlExpressLiveAdapter(CarrierConfig(status="live", live_allowlist=_BATCH))
    named._check_allowlist(_BATCH)
    with pytest.raises(CarrierAllowlistError):
        named._check_allowlist(_OTHER_BATCH)


# ── UPS: a link, and nothing that pretends to be more ───────────────────────


def test_a_ups_awb_resolves_to_the_official_ups_tracking_page():
    url = tracking_url_for("UPS", _UPS_REF)
    assert url.startswith("https://www.ups.com/track?")
    assert f"tracknum={_UPS_REF}" in url


@pytest.mark.parametrize(
    "ref",
    ["1Z0000000000000000", "1ZW8X5Y70398765432", "H9205024221", "999999999"],
)
def test_the_link_is_built_for_any_ups_reference(ref):
    """Generic: no reference is special-cased, none is hard-coded."""
    assert tracking_url_for("UPS", ref).endswith(f"tracknum={ref}")


def test_no_credential_and_no_network_call_is_needed_for_a_ups_link(monkeypatch):
    import app.services.tracking_service as ts

    def _explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("the UPS link path opened an HTTP connection")

    monkeypatch.setattr(ts.httpx, "post", _explode)
    monkeypatch.setattr(ts.httpx, "get", _explode)
    assert tracking_url_for("UPS", _UPS_REF)


def test_ups_status_is_link_only_and_never_claims_carrier_data(tmp_path, monkeypatch):
    import app.services.tracking_service as ts

    def _explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("a UPS tracking read called a carrier API")

    monkeypatch.setattr(ts.httpx, "post", _explode)
    monkeypatch.setattr(ts.httpx, "get", _explode)

    result = ts.get_tracking_status(_UPS_REF, "UPS", tmp_path)

    assert result["source"] == "public_link_only"
    assert result["status_label"] == "Track on UPS"
    assert result["available"] is False
    assert result["status"] == "unknown"          # no invented event
    assert not result.get("events")
    assert result["tracking_url"] == _ups_tracking_url(_UPS_REF)


def test_ups_is_not_claimed_as_a_tracked_carrier():
    assert "UPS" not in TRACKING_SUPPORTED_CARRIERS
    assert supports_tracking("UPS") is False


def test_the_urls_are_provider_specific():
    dhl = tracking_url_for("DHL", _DHL_REF)
    fedex = tracking_url_for("FedEx", _FEDEX_REF)
    ups = tracking_url_for("UPS", _UPS_REF)
    assert "dhl.com" in dhl and "fedex.com" in fedex and "ups.com" in ups
    assert len({dhl, fedex, ups}) == 3


def test_dhl_and_fedex_urls_are_byte_for_byte_what_they_were():
    assert tracking_url_for("DHL", _DHL_REF) == (
        "https://www.dhl.com/pl-en/home/tracking/tracking-express.html"
        f"?tracking-id={_DHL_REF}"
    )
    assert tracking_url_for("FedEx", _FEDEX_REF) == (
        f"https://www.fedex.com/en-pl/tracking.html?trknbr={_FEDEX_REF}"
    )
    assert _dhl_tracking_url(_DHL_REF) == tracking_url_for("DHL", _DHL_REF)
    assert _fedex_tracking_url(_FEDEX_REF) == tracking_url_for("FedEx", _FEDEX_REF)


@pytest.mark.parametrize("carrier", ["UPS", "DHL", "FedEx", "OTHER", ""])
def test_a_missing_reference_fails_honestly_rather_than_guessing(carrier):
    assert tracking_url_for(carrier, "") == ""
    assert tracking_url_for(carrier, "   ") == ""
    assert tracking_url_for(carrier, None) == ""


def test_an_unknown_carrier_gets_no_link():
    assert tracking_url_for("GLS", _UPS_REF) == ""
    assert tracking_url_for("", _UPS_REF) == ""


def test_the_reference_is_escaped_before_it_reaches_an_href():
    url = _ups_tracking_url('1Z"><script>alert(1)</script>')
    assert "<" not in url and '"' not in url and ">" not in url


def test_the_carrier_name_is_matched_case_insensitively():
    assert tracking_url_for("ups", _UPS_REF) == tracking_url_for("UPS", _UPS_REF)
    assert tracking_url_for("FEDEX", _FEDEX_REF) == tracking_url_for("FedEx", _FEDEX_REF)


# ── Detection and projection ─────────────────────────────────────────────────


def test_a_ups_reference_is_detected_as_ups_not_as_another_carrier():
    from app.api.routes_tracking import _auto_carrier

    assert _auto_carrier(_UPS_REF) == "UPS"
    assert _auto_carrier("1z999aa10123456784") == "UPS"      # case-insensitive
    assert _auto_carrier(_DHL_REF) == "DHL"                  # unchanged
    assert _auto_carrier(_FEDEX_REF) == "FedEx"              # unchanged


def test_the_dashboard_detector_hands_ups_the_same_single_link():
    from app.api.routes_dashboard import _detect_carrier

    info = _detect_carrier(_UPS_REF)
    assert info["carrier"] == "UPS"
    assert info["tracking_url"] == _ups_tracking_url(_UPS_REF)
    assert info["tracking_label"] == "Track on UPS"

    # A filename hint counts, but "ups" is a substring of ordinary words.
    assert _detect_carrier("", "ups-awb.pdf")["carrier"] == "UPS"
    for innocent in ("backups.pdf", "pickups.pdf", "groups-list.pdf"):
        assert _detect_carrier("", innocent)["carrier"] != "UPS", innocent


def test_the_upload_draft_writes_the_same_single_link():
    from app.api.routes_upload import _tracking_url

    assert _tracking_url("UPS", _UPS_REF) == _ups_tracking_url(_UPS_REF)
    assert _tracking_url("UPS", "") == ""


def test_a_carrier_shipment_record_projects_its_tracking_url():
    """The projection is generic: provider + tracking_ref, no carrier branch."""
    import inspect

    from app.api import routes_carrier_actions as rca

    source = inspect.getsource(rca)
    assert source.count('"tracking_url": tracking_url_for(') == 3, (
        "every carrier shipment payload must project the link from the one resolver"
    )


# ── Future-shipment guarantee ────────────────────────────────────────────────

_RUNTIME_DELTA = (
    "app/services/tracking_service.py",
    "app/services/carrier/adapters/fedex.py",
    "app/services/carrier/factory.py",
    "app/services/carrier/credentials/consumer_bridge.py",
    "app/api/routes_tracking.py",
    "app/api/routes_dashboard.py",
    "app/api/routes_upload.py",
    "app/api/routes_carrier_actions.py",
    "app/static/v2/estrella-outbound-tracking.jsx",
)

# A real AWB (10+ consecutive digits) or a concrete SHIPMENT_ batch id must not
# appear in the runtime delta. The FedEx/UPS paths must work for any future
# eligible shipment, so no shipment identity may be baked into them.
_LITERAL_AWB = re.compile(r"(?<![\w-])\d{10,}(?![\w-])")
_LITERAL_BATCH = re.compile(r"SHIPMENT_[A-Z0-9]+_\d{4}-\d{2}_[0-9a-f]{6,}")


def _code_only(line: str) -> str:
    """Drop comments. Prose may cite a historical AWB; executable code may not."""
    stripped = line.strip()
    if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*"):
        return ""
    for marker in ("  # ", "  // "):
        head, sep, _tail = line.partition(marker)
        if sep:
            line = head
    return line


def test_no_shipment_specific_identifier_in_the_runtime_delta():
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for rel in _RUNTIME_DELTA:
        path = app_root / rel
        assert path.exists(), f"runtime delta file missing: {rel}"
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            code = _code_only(line)
            if _LITERAL_BATCH.search(code) or _LITERAL_AWB.search(code):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:90]}")
    assert not offenders, "shipment-specific identifier in runtime code:\n" + "\n".join(
        offenders
    )
