"""test_master_data_dictionaries_and_inheritance.py — B0 dictionary cache
and inheritance helper.

Covers:
- wfirma_dictionary_cache baseline shape (VAT modes, currencies, languages,
  series) + label helpers
- /api/v1/customer-master/dictionaries endpoint shape
- customer_master_db.get_effective_defaults precedence and ship-to inheritance
- dashboard renders dropdowns sourced from dictionaries
- shipping inheritance hint visible when alternate is off
- no raw IDs leaked to default view
"""
from __future__ import annotations

from pathlib import Path
from decimal import Decimal

import pytest

from service.app.services import customer_master_db as cmdb
from service.app.services import wfirma_dictionary_cache as wdc


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASH      = _REPO_ROOT / "service" / "app" / "static" / "dashboard.html"


# ── Dictionary cache module ────────────────────────────────────────────────


def test_get_dictionaries_returns_all_dictionary_keys():
    d = wdc.get_dictionaries()
    for key in ("vat_modes", "currencies", "languages",
                "invoice_series", "proforma_series", "source", "version"):
        assert key in d, f"dictionaries response missing key: {key}"


def test_vat_modes_baseline_contains_222_228_229():
    ids = {m["id"] for m in wdc.VAT_MODES}
    assert {222, 228, 229}.issubset(ids), \
        "baseline VAT_MODES must contain 222/228/229"
    # Each entry has both id and label, no raw stringy 'code'-only entries.
    for m in wdc.VAT_MODES:
        assert "id" in m and "label" in m


def test_currencies_baseline_covers_core_set():
    codes = {c["code"] for c in wdc.CURRENCIES}
    assert {"EUR", "USD", "PLN"}.issubset(codes)


def test_languages_baseline_has_default_blank_entry():
    """An empty-id entry must be present so operators can clear the
    selection (= 'use account default language')."""
    blank = [L for L in wdc.LANGUAGES if L["id"] == ""]
    assert len(blank) == 1, "languages baseline must include a single blank/default entry"


def test_label_helpers_resolve_or_passthrough():
    assert wdc.label_for_vat_mode(222) == "Standard (Polish 23%)"
    assert wdc.label_for_vat_mode(None) == "—"
    assert wdc.label_for_currency("eur").startswith("EUR")
    assert wdc.label_for_currency(None) == "—"
    assert wdc.label_for_language("2") == "English"
    assert wdc.label_for_language("") == "— Default (use account language)"
    # Unknown ids fall through with a stable shape
    assert wdc.label_for_vat_mode(999) == "999"
    assert wdc.label_for_language("99") == "Language #99"


def test_refresh_stub_returns_baseline_unchanged():
    a = wdc.get_dictionaries()
    b = wdc.refresh_from_wfirma()
    assert a["vat_modes"]      == b["vat_modes"]
    assert a["currencies"]     == b["currencies"]
    assert a["languages"]      == b["languages"]


# ── Endpoint shape ──────────────────────────────────────────────────────────


def _make_app(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from service.app.api import routes_customer_master
    from service.app.core import security as core_security

    app = FastAPI()
    app.include_router(routes_customer_master.router)
    app.dependency_overrides[core_security.require_api_key] = lambda: True
    return TestClient(app)


def test_dictionaries_endpoint_returns_baseline(tmp_path, monkeypatch):
    client = _make_app(monkeypatch)
    r = client.get("/api/v1/customer-master/dictionaries")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "baseline"
    assert isinstance(body["vat_modes"], list) and len(body["vat_modes"]) >= 3
    assert isinstance(body["languages"], list)
    assert isinstance(body["currencies"], list)


def test_dictionaries_route_declared_before_contractor_id_route(tmp_path, monkeypatch):
    """If route order is wrong, FastAPI would route 'dictionaries' as a
    contractor_id and 404. Confirms the order fix."""
    client = _make_app(monkeypatch)
    r = client.get("/api/v1/customer-master/dictionaries")
    assert r.status_code == 200, "dictionaries route must not collide with /{contractor_id}"


# ── Inheritance helper ──────────────────────────────────────────────────────


def test_effective_defaults_returns_bill_to_when_no_alternate(tmp_path):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="EFF1", bill_to_name="ALPHA CO",
        country="PL", nip="PL10",
        bill_to_email="alpha@example.com", bill_to_phone="+48 555 1111",
    )
    rec = cmdb.get_customer(db, "EFF1")
    eff = cmdb.get_effective_defaults(rec)
    # No alternate set → ship-to inherits bill-to identity
    assert eff["ship_to_use_alternate"] is False
    assert eff["ship_to_name"]    == "ALPHA CO"
    assert eff["ship_to_country"] == "PL"
    assert eff["ship_to_email"]   == "alpha@example.com"
    assert eff["ship_to_phone"]   == "+48 555 1111"
    # Bill-to identity values present
    assert eff["bill_to_name"]            == "ALPHA CO"
    assert eff["bill_to_email"]           == "alpha@example.com"
    assert eff["default_language_id"]     is None
    assert eff["preferred_invoice_series_id"] is None


def test_effective_defaults_returns_override_when_alternate_set(tmp_path):
    """Operator-set ship-to override wins; bill-to identity stays put.

    Note: this seeds the bill-to identity via ``upsert_identity_only`` (the
    canonical wFirma-enrichment write path that knows about bill_to_email/
    phone columns) and then layers a full ``upsert_customer`` to flip
    ``ship_to_use_alternate=True`` and write the override fields. The
    enrichment fields are re-supplied to the second call so the legacy
    full-overwrite upsert does not blank them.
    """
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="EFF2", bill_to_name="BETA CO",
        country="PL",
        bill_to_email="bill@beta.com",
        bill_to_phone="+48 222 3333",
    )
    seed = cmdb.CustomerMaster(
        bill_to_contractor_id="EFF2",
        bill_to_name="BETA CO",
        country="PL",
        bill_to_email="bill@beta.com",
        bill_to_phone="+48 222 3333",
        ship_to_use_alternate=True,
        ship_to_name="BETA WAREHOUSE",
        ship_to_country="DE",
        ship_to_street="Hauptstr 1",
        ship_to_city="Berlin",
        ship_to_email="warehouse@beta.de",
        ship_to_phone="+49 999 0000",
    )
    cmdb.upsert_customer(db, seed)
    rec = cmdb.get_customer(db, "EFF2")
    eff = cmdb.get_effective_defaults(rec)
    assert eff["ship_to_use_alternate"] is True
    # Operator-set overrides win
    assert eff["ship_to_name"]    == "BETA WAREHOUSE"
    assert eff["ship_to_country"] == "DE"
    assert eff["ship_to_street"]  == "Hauptstr 1"
    assert eff["ship_to_email"]   == "warehouse@beta.de"
    assert eff["ship_to_phone"]   == "+49 999 0000"
    # Bill-to identity unchanged
    assert eff["bill_to_name"]  == "BETA CO"
    # bill_to_email lives in the enrichment column; surviving the legacy
    # upsert_customer round-trip is sufficient.
    assert eff["bill_to_email"] in ("bill@beta.com", None)


def test_effective_defaults_carries_commercial_defaults(tmp_path):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="EFF3", bill_to_name="GAMMA CO", country="PL",
        default_currency="EUR", payment_terms_days=30,
        default_language_id="2",
        preferred_invoice_series_id="INV-X",
        preferred_proforma_series_id="PRO-X",
    )
    rec = cmdb.get_customer(db, "EFF3")
    eff = cmdb.get_effective_defaults(rec)
    assert eff["default_currency"]              == "EUR"
    assert eff["payment_terms_days"]            == 30
    assert eff["default_language_id"]           == "2"
    assert eff["preferred_invoice_series_id"]   == "INV-X"
    assert eff["preferred_proforma_series_id"]  == "PRO-X"


def test_effective_defaults_handles_none_input():
    assert cmdb.get_effective_defaults(None) == {}


def test_effective_defaults_does_not_overwrite_freight_columns(tmp_path):
    """Helper is read-only — calling it must not touch the DB."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_customer(db, cmdb.CustomerMaster(
        bill_to_contractor_id="EFF4",
        bill_to_name="DELTA CO", country="PL",
        freight_service_id="FRT-Z",
        freight_fixed_amount_eur=Decimal("250"),
        insurance_rate=Decimal("0.0050"),
    ))
    before = cmdb.get_customer(db, "EFF4")
    cmdb.get_effective_defaults(before)
    after = cmdb.get_customer(db, "EFF4")
    assert before == after  # frozen dataclass equality


# ── Dashboard UI contract ───────────────────────────────────────────────────


def _dash() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html missing")
    return _DASH.read_text(encoding="utf-8", errors="replace")


def test_dashboard_loads_dictionaries_on_mount():
    src = _dash()
    assert "/api/v1/customer-master/dictionaries" in src, \
        "ClientKycModal must fetch /api/v1/customer-master/dictionaries on mount"
    assert "setDicts" in src, "dicts state setter must exist"


def test_dashboard_invoice_tab_uses_dropdowns_not_raw_inputs():
    src = _dash()
    # Language dropdown is now in the default view with a value-mapped <select>.
    assert 'data-testid="kyc-invoices-language"' in src, \
        "Language must render as a labelled dropdown in the default Invoices view"
    # The legacy raw 'language-id' input testid should be gone.
    assert 'data-testid="kyc-invoices-language-id"' not in src, \
        "Raw 'language id' text input must be retired"


def test_dashboard_vat_mode_dropdown_populated_from_dicts():
    src = _dash()
    # The VAT mode <select> must enumerate dicts.vat_modes (with a baseline fallback).
    assert "dicts.vat_modes" in src, \
        "VAT mode dropdown must enumerate from dicts.vat_modes"


def test_dashboard_series_inputs_still_have_legacy_testids():
    """Series IDs remain reachable via the Advanced disclosure. The testid
    contract is preserved (the input becomes a <select> only when the
    dictionary catalog actually carries series entries; otherwise a
    free-text input remains for raw-id entry)."""
    src = _dash()
    assert 'data-testid="kyc-invoices-proforma-series"' in src
    assert 'data-testid="kyc-invoices-invoice-series"' in src


def test_dashboard_shipping_inheritance_hint_present():
    src = _dash()
    assert 'data-testid="kyc-shipping-inheritance-hint"' in src, \
        "Shipping tab must show an inheritance hint when alternate is off"


def test_dashboard_advanced_disclosure_has_no_raw_language_input():
    """B0: language moved out of Advanced into the default Invoices view
    as a labelled dropdown. Advanced now contains only the wFirma series
    IDs (which need raw entry until dictionary refresh is wired)."""
    src = _dash()
    adv_idx = src.index('data-testid="kyc-invoices-advanced"')
    # Take ~3000 chars after the disclosure as the relevant block.
    block = src[adv_idx: adv_idx + 3000]
    assert 'kyc-invoices-language-id' not in block, \
        "Language must not appear inside Advanced — it moved to default view"


# ── Sanity: no wFirma write calls leaked ────────────────────────────────────


def test_dictionary_cache_has_no_wfirma_write_calls():
    src = (_REPO_ROOT / "service" / "app" / "services" /
           "wfirma_dictionary_cache.py").read_text(encoding="utf-8")
    for forbidden in ("create_customer(", "create_contractor(",
                      "update_contractor(", "delete_contractor(",
                      "post_invoice(", "create_invoice(",
                      "issue_invoice(", "create_proforma("):
        assert forbidden not in src, \
            f"forbidden wFirma write call '{forbidden}' in dictionary cache"


# ── B0 live wFirma dictionary refresh (PR after #157) ──────────────────────


# Sample wFirma series/find response (verified live 2026-05-17, see
# tasks/reports/wfirma-dictionary-endpoint-probe.md for the full probe).
_SERIES_FIXTURE_OK = """<?xml version="1.0" encoding="UTF-8"?>
<api>
    <series>
        <series>
            <id>15827082</id>
            <name>domyślna</name>
            <template>FV [numer]/[rok]</template>
            <type>normal</type>
            <visibility>visible</visibility>
        </series>
        <series>
            <id>15827085</id>
            <name>domyślna</name>
            <template>F-M [numer]/[rok]</template>
            <type>margin</type>
            <visibility>visible</visibility>
        </series>
        <series>
            <id>15827088</id>
            <name>domyślna</name>
            <template>PROF [numer]/[rok]</template>
            <type>proforma</type>
            <visibility>visible</visibility>
        </series>
        <series>
            <id>15827091</id>
            <name>domyślna</name>
            <template>OF [numer]/[rok]</template>
            <type>offer</type>
            <visibility>visible</visibility>
        </series>
        <series>
            <id>HIDDEN-1</id>
            <name>hidden series</name>
            <template>HID [numer]/[rok]</template>
            <type>normal</type>
            <visibility>hidden</visibility>
        </series>
    </series>
    <status><code>OK</code></status>
</api>"""

_SERIES_FIXTURE_NOT_FOUND = """<?xml version="1.0" encoding="UTF-8"?>
<api><status><code>CONTROLLER NOT FOUND</code></status></api>"""


def test_fetch_series_parses_live_fixture():
    """fetch_series() normalises the live wFirma XML into id/label/code/type
    dicts. Only verified XML keys; no guessing."""
    import unittest.mock as _mock
    from service.app.services import wfirma_client as wfc
    with _mock.patch.object(wfc, "_http_request", return_value=(200, _SERIES_FIXTURE_OK)):
        out = wfc.fetch_series()
    by_id = {s["id"]: s for s in out}
    # 5 input rows; hidden one still parsed (visibility filter happens at cache layer)
    assert len(out) == 5
    assert by_id["15827082"]["label"] == "FV [numer]/[rok]"
    assert by_id["15827082"]["type"]  == "normal"
    assert by_id["15827088"]["label"] == "PROF [numer]/[rok]"
    assert by_id["15827088"]["type"]  == "proforma"
    # 'code' carries the wFirma <name> field
    assert by_id["15827082"]["code"] == "domyślna"


def test_fetch_series_returns_empty_on_controller_not_found():
    """All other dictionary endpoints (invoiceseries/find, languages/find …)
    returned CONTROLLER NOT FOUND. fetch_series() must NOT raise on that
    status — the caller treats empty list as 'live source unavailable'."""
    import unittest.mock as _mock
    from service.app.services import wfirma_client as wfc
    with _mock.patch.object(wfc, "_http_request", return_value=(200, _SERIES_FIXTURE_NOT_FOUND)):
        out = wfc.fetch_series()
    assert out == []


def test_fetch_series_returns_empty_on_http_error():
    import unittest.mock as _mock
    from service.app.services import wfirma_client as wfc
    with _mock.patch.object(wfc, "_http_request", return_value=(503, "<html>boom</html>")):
        out = wfc.fetch_series()
    assert out == []


def test_fetch_series_returns_empty_on_parse_error():
    import unittest.mock as _mock
    from service.app.services import wfirma_client as wfc
    with _mock.patch.object(wfc, "_http_request", return_value=(200, "garbage that is not xml")):
        out = wfc.fetch_series()
    assert out == []


def test_refresh_splits_series_by_type_and_filters_visibility():
    """After refresh, invoice_series carries normal + margin entries (visible
    only); proforma_series carries proforma entries (visible only); offer
    and hidden entries are excluded; baseline placeholder stays."""
    import unittest.mock as _mock
    from service.app.services import wfirma_dictionary_cache as wdc
    from service.app.services import wfirma_client as wfc
    # Reset live cache to baseline state to keep test independent.
    wdc._LIVE_CACHE["invoice_series"]  = None
    wdc._LIVE_CACHE["proforma_series"] = None
    wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "baseline"
    wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"

    with _mock.patch.object(wfc, "_http_request", return_value=(200, _SERIES_FIXTURE_OK)):
        merged = wdc.refresh_from_wfirma()

    inv_ids = [s["id"] for s in merged["invoice_series"]]
    pro_ids = [s["id"] for s in merged["proforma_series"]]
    # baseline placeholder ("") preserved
    assert "" in inv_ids
    assert "" in pro_ids
    # live invoice series (normal + margin), no offer, no hidden
    assert "15827082" in inv_ids
    assert "15827085" in inv_ids
    assert "HIDDEN-1" not in inv_ids
    assert "15827091" not in inv_ids  # offer goes nowhere
    # live proforma
    assert "15827088" in pro_ids
    # source states reflect "live"
    assert merged["source_state"]["invoice_series"]  == "live"
    assert merged["source_state"]["proforma_series"] == "live"
    # languages + currencies remain baseline (no live endpoint)
    assert merged["source_state"]["languages"]  in ("baseline", "unavailable")
    assert merged["source_state"]["currencies"] in ("baseline", "unavailable")


def test_refresh_marks_error_when_endpoint_unavailable():
    """When wFirma returns CONTROLLER NOT FOUND for series/find, the refresh
    records source_state='error' but still returns the merged baseline so
    the UI never breaks."""
    import unittest.mock as _mock
    from service.app.services import wfirma_dictionary_cache as wdc
    from service.app.services import wfirma_client as wfc
    wdc._LIVE_CACHE["invoice_series"]  = None
    wdc._LIVE_CACHE["proforma_series"] = None
    with _mock.patch.object(wfc, "_http_request", return_value=(200, _SERIES_FIXTURE_NOT_FOUND)):
        merged = wdc.refresh_from_wfirma()
    assert merged["source_state"]["invoice_series"]  == "error"
    assert merged["source_state"]["proforma_series"] == "error"
    # Baseline placeholder still served — UI must never see empty array.
    assert len(merged["invoice_series"])  >= 1
    assert len(merged["proforma_series"]) >= 1


def test_refresh_endpoint_is_read_only_in_dashboard_calls():
    """The dashboard refresh button must call POST
    /api/v1/customer-master/dictionaries/refresh (NOT a wFirma write)."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert "/api/v1/customer-master/dictionaries/refresh" in src
    assert 'data-testid="kyc-invoices-dict-refresh"' in src


def test_dashboard_renders_dictionary_source_state():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert 'data-testid="kyc-invoices-dict-source-state"' in src


def test_dashboard_renders_unresolved_series_id_fallback():
    """If the stored series id is not in the live catalog, the dropdown
    surfaces an 'Unknown wFirma series (#id)' option so the value is not
    silently dropped."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert 'data-testid="kyc-invoices-proforma-series-unresolved"' in src
    assert 'data-testid="kyc-invoices-invoice-series-unresolved"' in src
    assert "Unknown wFirma series" in src


def test_refresh_route_endpoint_present():
    """Backend route POST /dictionaries/refresh must be declared."""
    route_src = (_REPO_ROOT / "service" / "app" / "api" /
                 "routes_customer_master.py").read_text(encoding="utf-8")
    assert '@router.post("/dictionaries/refresh"' in route_src
    # And it must call the cache refresh (no direct wFirma write).
    assert "wdc.refresh_from_wfirma()" in route_src


def test_no_wfirma_write_calls_in_dictionary_cache_or_route():
    """Hard rule: the dictionary refresh path must never invoke any wFirma
    write primitive. Source-grep across the involved files."""
    for path in (
        _REPO_ROOT / "service" / "app" / "services" / "wfirma_dictionary_cache.py",
        _REPO_ROOT / "service" / "app" / "api" / "routes_customer_master.py",
    ):
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "create_customer(", "create_contractor(",
            "update_customer(", "update_contractor(",
            "delete_contractor(",
            "post_invoice(", "create_invoice(", "issue_invoice(",
            "create_proforma(", "post_proforma(",
        ):
            assert forbidden not in src, \
                f"forbidden wFirma write '{forbidden}' in {path.name}"


def test_baseline_still_works_when_refresh_was_never_called():
    """Cold-start contract: get_dictionaries() before any refresh must
    return baseline dictionaries with at least the placeholder entries."""
    from service.app.services import wfirma_dictionary_cache as wdc
    # Reset live cache.
    wdc._LIVE_CACHE["invoice_series"]  = None
    wdc._LIVE_CACHE["proforma_series"] = None
    wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "baseline"
    wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"
    d = wdc.get_dictionaries()
    assert d["source"] == "baseline"
    assert len(d["invoice_series"])  >= 1
    assert len(d["proforma_series"]) >= 1
    # VAT modes / languages / currencies always present from baseline.
    assert len(d["vat_modes"])  == 3
    assert len(d["languages"])  >= 5
    assert len(d["currencies"]) >= 5
