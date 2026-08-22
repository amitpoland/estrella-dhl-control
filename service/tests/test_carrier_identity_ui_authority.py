"""One carrier identity, end to end — no layer may invent or overwrite it.

PR #1311 made the tracking URL generic. It did not stop the FRONTEND from
inventing a carrier: `props.carrier || 'DHL'` turned an honest unknown into DHL
and then sent that invention to the backend as an explicit ?carrier=DHL, which
pre-empted server-side detection and — with DHL tracking active — fired a real
DHL API call for a UPS 1Z reference.

These pins hold the repaired chain:

    carrier_shipments.provider
      -> canonical_carrier()            (one normaliser, FEDEX -> FedEx)
      -> carrier-specific capability    (UPS has no client, FedEx does)
      -> carrier-specific URL/status
      -> carrier-specific UI copy

Every identifier here is synthetic.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.tracking_service import (
    TRACKING_SUPPORTED_CARRIERS,
    canonical_carrier,
    supports_tracking,
    tracking_url_for,
)

_UPS_REF = "1Z999AA10123456784"
_DHL_REF = "1234567890"
_FEDEX_REF = "794600000001"

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_TRACK_CARD = _V2 / "estrella-outbound-tracking.jsx"
_PAGES = _V2 / "pages-v2.jsx"
_SHIPMENT_PAGE = _V2 / "shipment-detail-page.jsx"
_PROFORMA = _V2 / "proforma-detail.jsx"


def _src(path: Path) -> str:
    assert path.exists(), f"missing surface: {path}"
    return path.read_text(encoding="utf-8")


def _code_lines(path: Path):
    """Executable lines only — a comment explaining the old bug is not the bug."""
    for n, line in enumerate(_src(path).splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        yield n, line


# ── the normaliser: one spelling, and "unknown" is a real answer ─────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("FEDEX", "FedEx"), ("fedex", "FedEx"), ("FedEx", "FedEx"),
        ("UPS", "UPS"), ("ups", "UPS"),
        ("DHL", "DHL"), ("dhl", "DHL"), (" DHL ", "DHL"),
    ],
)
def test_carrier_names_resolve_to_one_canonical_spelling(raw, expected):
    assert canonical_carrier(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, "GLS", "InPost", "Unknown"])
def test_an_unrecognised_carrier_stays_unrecognised(raw):
    """"" is the answer. Never a default, because every default is a wrong name."""
    assert canonical_carrier(raw) == ""


def test_the_stored_provider_spelling_reaches_the_fedex_tracking_client():
    """carrier_shipments stores FEDEX; this authority compares against FedEx.

    Before normalisation that mismatch demoted a real FedEx shipment to a public
    link, silently losing tracking that is provisioned and working.
    """
    from app.services.carrier.persistence.shipment_db import EXTERNAL_PROVIDERS

    assert "FEDEX" in EXTERNAL_PROVIDERS            # what persistence stores
    assert "FEDEX" not in TRACKING_SUPPORTED_CARRIERS  # what tracking compares
    assert canonical_carrier("FEDEX") in TRACKING_SUPPORTED_CARRIERS
    assert supports_tracking(canonical_carrier("FEDEX")) is True


def test_ups_is_still_not_a_tracked_carrier():
    assert canonical_carrier("UPS") == "UPS"
    assert "UPS" not in TRACKING_SUPPORTED_CARRIERS
    assert supports_tracking("UPS") is False


# ── a UPS reference must never reach DHL ────────────────────────────────────


def test_a_ups_reference_never_opens_an_http_connection(tmp_path, monkeypatch):
    import app.services.tracking_service as ts

    def _explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("a UPS tracking read opened an HTTP connection")

    monkeypatch.setattr(ts.httpx, "post", _explode)
    monkeypatch.setattr(ts.httpx, "get", _explode)

    for carrier in ("UPS", "ups"):
        out = ts.get_tracking_status(_UPS_REF, carrier, tmp_path)
        assert out["carrier"] == "UPS"
        assert out["source"] == "public_link_only"
        assert out["tracking_url"] == tracking_url_for("UPS", _UPS_REF)
        assert "dhl" not in out["tracking_url"].lower()
        assert not out.get("events")
        assert out["available"] is False


def test_a_ups_reference_is_detected_without_the_caller_naming_a_carrier():
    """The frontend now sends nothing when it does not know; detection must work."""
    from app.api.routes_tracking import _auto_carrier

    assert _auto_carrier(_UPS_REF) == "UPS"
    assert _auto_carrier(_DHL_REF) == "DHL"        # unchanged
    assert _auto_carrier(_FEDEX_REF) == "FedEx"    # unchanged


@pytest.mark.parametrize(
    "ref",
    [
        "1Z999AA10123456784",   # digits-then-letters
        "1ZN000AA0000000000",   # letter first, mirrors the reported field shape
        "1ZW8X5Y70398765432",   # letters interleaved with digits
        "1z999aa10123456784",   # lowercase as typed
        "1Z 999AA1 0123456784", # spaced as pasted from a label
    ],
)
def test_every_ups_reference_shape_is_detected_as_ups(ref):
    """The reported field case was a mixed letter/digit 1Z body; the detector
    must not be tuned to one layout."""
    from app.api.routes_tracking import _auto_carrier

    assert _auto_carrier(ref) == "UPS"


def test_an_unknown_carrier_never_resolves_to_a_dhl_url():
    assert tracking_url_for("", _UPS_REF) == ""
    assert tracking_url_for("GLS", _UPS_REF) == ""
    assert tracking_url_for("Unknown", _DHL_REF) == ""


# ── DHL non-regression ──────────────────────────────────────────────────────


def test_dhl_urls_are_unchanged():
    assert tracking_url_for("DHL", _DHL_REF) == (
        "https://www.dhl.com/pl-en/home/tracking/tracking-express.html"
        f"?tracking-id={_DHL_REF}"
    )
    assert tracking_url_for("FedEx", _FEDEX_REF) == (
        f"https://www.fedex.com/en-pl/tracking.html?trknbr={_FEDEX_REF}"
    )


def test_the_dhl_service_catalogue_is_byte_identical_for_dhl():
    """The carrier parameter is additive; DHL callers get exactly what they got."""
    from app.api.routes_carrier_actions import _DHL_SERVICES

    codes = [s["code"] for s in _DHL_SERVICES]
    assert codes == ["P", "Y", "K", "D", "T"]
    assert _DHL_SERVICES[0]["name"] == "Express Worldwide"


def test_a_non_dhl_carrier_gets_an_empty_catalogue_not_dhls_codes():
    """[] is the honest answer that disables booking. Never another carrier's codes.

    The carrier runtime deliberately has no non-DHL catalogue: Rule 3 of
    test_master_data_hard_rules forbids it from reading the operator-editable
    carrier config table, since a code chosen there would drive live shipment
    creation. An earlier revision of this campaign did read it and was caught
    by that rule.
    """
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_carrier_actions.py").read_text(encoding="utf-8")
    assert "carriers_config" not in src
    assert "list_carrier_configs" not in src
    # DHL keeps its catalogue; everything else resolves to an empty list.
    assert "return JSONResponse(_DHL_SERVICES)" in src
    assert "return JSONResponse([])" in src


# ── the tracking card: no invented identity, no DHL-only fallback ───────────


def test_the_tracking_card_no_longer_invents_a_carrier():
    for n, line in _code_lines(_TRACK_CARD):
        assert "props.carrier || 'DHL'" not in line, f"{_TRACK_CARD.name}:{n}"
        assert "carrier || 'DHL'" not in line, f"{_TRACK_CARD.name}:{n}"


def test_the_tracking_card_builds_no_dhl_url_of_its_own():
    """The public tracking URL has exactly one authority: tracking_url_for."""
    for n, line in _code_lines(_TRACK_CARD):
        assert "dhl.com" not in line.lower(), f"{_TRACK_CARD.name}:{n}: {line.strip()[:80]}"


def test_every_dhl_string_in_the_tracking_card_is_carrier_gated():
    """DHL copy may exist only under the isDhl branch."""
    src = _src(_TRACK_CARD)
    assert "var isDhl =" in src, "the card must derive an explicit DHL flag"
    assert "{isDhl && (" in src, "DHL-only copy must render behind isDhl"
    # The MyDHL notification note appears in both branches; both must be gated.
    assert src.count("MyDHL shipmentNotification") == src.count("{isDhl && (")


def test_an_unknown_carrier_renders_as_unknown_not_as_dhl():
    src = _src(_TRACK_CARD)
    assert "'UNKNOWN CARRIER'" in src
    for n, line in _code_lines(_TRACK_CARD):
        assert "'Open DHL tracking" not in line, f"{_TRACK_CARD.name}:{n}"


# ── call sites must pass the real provider ──────────────────────────────────


@pytest.mark.parametrize("path", [_PAGES, _SHIPMENT_PAGE])
def test_no_call_site_hardcodes_the_carrier(path):
    for n, line in _code_lines(path):
        assert "carrier: 'DHL'" not in line, f"{path.name}:{n}: {line.strip()[:80]}"
        assert 'carrier="DHL"' not in line, f"{path.name}:{n}: {line.strip()[:80]}"


def test_the_shipment_page_threads_the_real_provider_through():
    src = _src(_SHIPMENT_PAGE)
    assert "carrier={shipment && shipment.carrier}" in src


def test_the_control_tower_passes_the_rows_own_carrier():
    assert "carrier: row.carrier || ''" in _src(_PAGES)


# ── the booking modal: FedEx must not wear DHL's words ──────────────────────

# Copy that names DHL and is NOT rendered behind a DHL-only condition.
_DHL_ONLY_COPY = (
    "required by DHL Express.",
    "Phone * (required by DHL)",
    "Create FedEx sandbox shipment",
    "Generate FedEx sandbox shipment",
    ">DHL Service<",
)


@pytest.mark.parametrize("phrase", _DHL_ONLY_COPY)
def test_the_booking_modal_carries_no_ungated_dhl_copy(phrase):
    assert phrase not in _src(_PROFORMA), f"ungated DHL copy survives: {phrase!r}"


def test_the_modal_derives_its_carrier_name_instead_of_naming_dhl():
    src = _src(_PROFORMA)
    assert "const carrierName = isFedex ? 'FedEx'" in src
    assert "{carrierName} Service" in src


def test_fedex_without_a_configured_service_cannot_submit():
    src = _src(_PROFORMA)
    assert "const serviceAuthorityMissing = isFedex && servicesLoaded && services.length === 0;" in src
    # the control is disabled...
    assert "disabled={loading || serviceAuthorityMissing" in src
    # ...and says why, which the EJ standard requires of every disabled write.
    assert "FedEx service configuration required" in src


def test_a_non_dhl_carrier_is_never_offered_dhl_service_code_p():
    """The old fallback offered "P" to every carrier; FedEx rejects it outright."""
    src = _src(_PROFORMA)
    assert '<option value="P">Express Worldwide (P) — End of day</option>' in src, (
        "DHL must keep its own offline default"
    )
    assert "? <option value=\"P\">" in src or "isDhl" in src, (
        "the P fallback must be reachable only for DHL"
    )
    assert '<option value="">— No service configured —</option>' in src


def test_switching_carrier_clears_the_previous_carriers_selections():
    """State leak across an in-place carrier change is the recurring failure."""
    src = _src(_PROFORMA)
    assert "setForm(prev => ({ ...prev, product_code: '', box_type_code: '' }));" in src
    assert "}, [selectedCarrier, isApiBooking]);" in src, (
        "the catalogue effect must be keyed on the selected carrier"
    )


def test_the_service_catalogue_request_is_carrier_scoped():
    api = _src(_V2 / "pz-api.js")
    assert "listCarrierServices: (carrier) =>" in api
    assert "?carrier=${encodeURIComponent(carrier)}" in api


# ── nothing shipment-specific ───────────────────────────────────────────────

_LITERAL_AWB = re.compile(r"(?<![\w-])\d{10,}(?![\w-])")
_LITERAL_BATCH = re.compile(r"SHIPMENT_[A-Z0-9]+_\d{4}-\d{2}_[0-9a-f]{6,}")


@pytest.mark.parametrize("path", [_TRACK_CARD, _PAGES, _SHIPMENT_PAGE, _PROFORMA])
def test_no_shipment_specific_identifier_in_the_touched_surfaces(path):
    offenders = []
    for n, line in _code_lines(path):
        code = line.split("  //")[0]
        if _LITERAL_BATCH.search(code) or _LITERAL_AWB.search(code):
            offenders.append(f"{path.name}:{n}: {line.strip()[:80]}")
    assert not offenders, "shipment identity hard-coded:\n" + "\n".join(offenders)


# ── HTTP-level wiring (closes the gate's source-grep-only coverage flags) ────


@pytest.fixture()
def _api():
    """Isolated app exposing the real carrier + tracking routers, auth satisfied.

    Source-grep proves a branch EXISTS; it cannot prove the route reaches it.
    These two gaps were flagged at the gate, so they are exercised over real
    HTTP instead of by reading the file.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes_carrier_actions import router as actions_router
    from app.api.routes_tracking import router as tracking_router
    from app.auth.dependencies import get_current_user
    from app.core.security import require_api_key

    app = FastAPI()
    app.include_router(actions_router)
    app.include_router(tracking_router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin", "username": "t"}
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def test_http_dhl_service_catalogue_is_unchanged(_api):
    """Both the historic no-parameter call and an explicit DHL call."""
    for url in ("/api/v1/carrier/services", "/api/v1/carrier/services?carrier=DHL"):
        r = _api.get(url)
        assert r.status_code == 200, url
        assert [row["code"] for row in r.json()] == ["P", "Y", "K", "D", "T"], url


@pytest.mark.parametrize("carrier", ["FEDEX", "fedex", "UPS", "OTHER"])
def test_http_a_non_dhl_carrier_is_never_served_dhl_codes(_api, carrier):
    r = _api.get(f"/api/v1/carrier/services?carrier={carrier}")
    assert r.status_code == 200
    assert r.json() == [], f"{carrier} was served a catalogue: {r.json()!r}"


def test_http_a_ups_reference_is_detected_when_no_carrier_is_supplied(_api, monkeypatch):
    """The route must reach _auto_carrier — the exact wiring the frontend now relies on.

    The card no longer sends a carrier when it does not know one, so if this
    wiring were broken a UPS waybill would fall through as Unknown.
    """
    import app.services.tracking_service as ts

    def _explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("an unnamed-carrier tracking read opened an HTTP connection")

    monkeypatch.setattr(ts.httpx, "post", _explode)
    monkeypatch.setattr(ts.httpx, "get", _explode)

    r = _api.get(f"/api/v1/tracking/{_UPS_REF}")
    assert r.status_code == 200
    body = r.json()
    assert body["carrier"] == "UPS", body
    assert body["source"] == "public_link_only", body
    assert body["tracking_url"] == tracking_url_for("UPS", _UPS_REF)
    assert "dhl" not in body["tracking_url"].lower()
    assert not body.get("events")
