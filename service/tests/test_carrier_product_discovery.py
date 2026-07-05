"""
Tests for DHL product/rate capability discovery.

Covers:
  - lookup_available_products(): HTTP success, failure, timeout, caching
  - select_product_code(): selection logic for PL→LT/DE/CH/US routes
  - create_shipment() integration: discovered product injected into shipment body

All DHL HTTP calls are mocked — no real network traffic.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch, call

import httpx
import pytest

from app.services.carrier.adapters.live import (
    DhlExpressLiveAdapter,
    clear_product_cache,
    lookup_available_products,
    select_product_code,
    _build_shipment_body,
)
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    CarrierGateError,
    ShipmentRequest,
)


# ── fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    """Flush the module-level product cache before every test."""
    clear_product_cache()
    yield
    clear_product_cache()


def _make_config(account: str = "427294774") -> CarrierConfig:
    return CarrierConfig(
        status="live",
        api_key="test-key",
        api_secret="test-secret",
        api_url="https://express.api.dhl.com",
        use_sandbox=False,
        account_number=account,
        live_allowlist="*",
    )


def _make_request(
    batch_id: str = "BATCH-001",
    dest_cc: str = "DE",
    dest_city: str = "Hamburg",
    dest_postal: str = "20457",
    product_code: str = "P",
    weight_kg: float = 1.5,
) -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=batch_id,
        shipper_account="427294774",
        recipient_address={
            "name": "Test Receiver",
            "street": "Hauptstrasse 1",
            "city": dest_city,
            "postal_code": dest_postal,
            "country_code": dest_cc,
            "phone": "+49301234567",
        },
        declared_value=500.0,
        currency="EUR",
        weight_kg=weight_kg,
        dimensions={"length_cm": 20, "width_cm": 15, "height_cm": 10},
        product_code=product_code,
    )


@contextmanager
def _mock_settings(tmp_path, country_code: str = "PL"):
    mock = MagicMock()
    mock.dhl_express_shipper_name = "Estrella Jewels"
    mock.dhl_express_shipper_address1 = "ul. Sabaly 58"
    mock.dhl_express_shipper_city = "Warszawa"
    mock.dhl_express_shipper_postal_code = "02-174"
    mock.dhl_express_shipper_country_code = country_code
    mock.dhl_express_shipper_phone = "+48516081994"
    mock.carrier_storage_root = None
    mock.storage_root = tmp_path
    with patch("app.core.config.settings", mock):
        yield mock


def _rates_resp(product_codes: list) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = {
        "products": [{"productCode": c} for c in product_codes]
    }
    return resp


def _rates_error(status_code: int = 422) -> MagicMock:
    resp = MagicMock()
    resp.is_success = False
    resp.status_code = status_code
    resp.text = "error"
    return resp


def _ship_resp(tracking_ref: str = "AWB-TEST-123") -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = {
        "shipmentTrackingNumber": tracking_ref,
        "documents": [],
    }
    return resp


# ── TestProductSelection ──────────────────────────────────────────────────────


class TestProductSelection:
    """Unit tests for select_product_code() — pure logic, no HTTP."""

    def test_requested_available_returns_requested(self):
        assert select_product_code("P", ["P", "U", "W"]) == "P"

    def test_requested_not_available_returns_first_alternative(self):
        assert select_product_code("P", ["U", "K"]) == "U"

    def test_empty_available_returns_requested_unchanged(self):
        assert select_product_code("P", []) == "P"

    # Route-specific selection scenarios

    def test_pl_to_lt_p_not_available_selects_u(self):
        # PL→LT: DHL 803 shows P is not entitled; rates returns U (Express)
        available = ["U", "K"]
        assert select_product_code("P", available) == "U"

    def test_pl_to_de_u_requested_and_available(self):
        # PL→DE CFIT: account entitled for U (Express) — should stay U
        available = ["U", "W", "P"]
        assert select_product_code("U", available) == "U"

    def test_pl_to_ch_p_requested_and_available(self):
        # PL→CH CFIT: account entitled for P (WPX) — should stay P
        available = ["P", "U"]
        assert select_product_code("P", available) == "P"

    def test_pl_to_us_p_requested_and_available(self):
        # PL→US CFIT: account entitled for P (WPX) — should stay P
        available = ["P"]
        assert select_product_code("P", available) == "P"

    def test_single_alternative_used_when_requested_absent(self):
        assert select_product_code("P", ["W"]) == "W"


# ── TestProductLookupHttp ─────────────────────────────────────────────────────


class TestProductLookupHttp:
    """Tests for lookup_available_products() — mocked HTTP."""

    def _call(self, products_response=None, error=False, exc=None):
        with patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            if exc:
                mock_client.get.side_effect = exc
            elif error:
                mock_client.get.return_value = _rates_error()
            else:
                mock_client.get.return_value = _rates_resp(products_response or [])

            return lookup_available_products(
                api_key="key",
                api_secret="secret",
                api_url="https://express.api.dhl.com",
                api_path="/mydhlapi",
                account="427294774",
                origin_cc="PL",
                origin_city="Warszawa",
                origin_postal="02-174",
                dest_cc="LT",
                dest_city="Vilnius",
                dest_postal="01000",
                weight_kg=1.5,
                planned_date="2026-06-26",
            )

    def test_success_returns_product_codes_in_order(self):
        codes = self._call(["U", "K", "W"])
        assert codes == ["U", "K", "W"]

    def test_success_caches_result(self):
        with patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.return_value = _rates_resp(["U", "K"])

            kwargs = dict(
                api_key="key", api_secret="secret",
                api_url="https://express.api.dhl.com", api_path="/mydhlapi",
                account="427294774", origin_cc="PL", origin_city="Warszawa",
                origin_postal="02-174", dest_cc="LT", dest_city="Vilnius",
                dest_postal="01000", weight_kg=1.5, planned_date="2026-06-26",
            )
            first = lookup_available_products(**kwargs)
            second = lookup_available_products(**kwargs)

        assert first == ["U", "K"]
        assert second == ["U", "K"]
        assert mock_client.get.call_count == 1  # second call served from cache

    def test_cache_is_per_route(self):
        """Cache for PL→LT does not collide with PL→DE."""
        with patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.side_effect = [
                _rates_resp(["U", "K"]),   # PL→LT
                _rates_resp(["P", "U"]),   # PL→DE
            ]

            lt_codes = lookup_available_products(
                api_key="key", api_secret="secret",
                api_url="https://express.api.dhl.com", api_path="/mydhlapi",
                account="427294774", origin_cc="PL", origin_city="Warszawa",
                origin_postal="02-174", dest_cc="LT", dest_city="Vilnius",
                dest_postal="01000", weight_kg=1.5, planned_date="2026-06-26",
            )
            de_codes = lookup_available_products(
                api_key="key", api_secret="secret",
                api_url="https://express.api.dhl.com", api_path="/mydhlapi",
                account="427294774", origin_cc="PL", origin_city="Warszawa",
                origin_postal="02-174", dest_cc="DE", dest_city="Hamburg",
                dest_postal="20457", weight_kg=1.5, planned_date="2026-06-26",
            )

        assert lt_codes == ["U", "K"]
        assert de_codes == ["P", "U"]

    def test_http_error_returns_empty_list(self):
        codes = self._call(error=True)
        assert codes == []

    def test_timeout_returns_empty_list(self):
        codes = self._call(exc=httpx.TimeoutException("timeout"))
        assert codes == []

    def test_network_error_returns_empty_list(self):
        codes = self._call(exc=httpx.ConnectError("refused"))
        assert codes == []

    def test_empty_products_array_returns_empty_list(self):
        codes = self._call([])
        assert codes == []

    def test_missing_product_code_field_skipped(self):
        """Products without a productCode key are filtered out."""
        with patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            resp = MagicMock()
            resp.is_success = True
            resp.json.return_value = {
                "products": [
                    {"productCode": "P"},
                    {"localProductCode": "U"},   # no productCode key
                    {"productCode": "W"},
                ]
            }
            mock_client.get.return_value = resp
            codes = lookup_available_products(
                api_key="key", api_secret="secret",
                api_url="https://express.api.dhl.com", api_path="/mydhlapi",
                account="427294774", origin_cc="PL", origin_city="Warszawa",
                origin_postal="02-174", dest_cc="CH", dest_city="Basel",
                dest_postal="4000", weight_kg=1.5, planned_date="2026-06-26",
            )
        assert codes == ["P", "W"]


# ── TestCreateShipmentProductDiscovery ───────────────────────────────────────


class TestCreateShipmentProductDiscovery:
    """
    Integration: create_shipment() calls GET /rates, selects product, then
    calls POST /shipments with the DHL-authoritative productCode.
    """

    def _run(
        self,
        tmp_path,
        dest_cc: str,
        dest_city: str,
        dest_postal: str,
        requested_product: str,
        rates_products: list,
        ship_tracking: str = "AWB-INTEGRATION",
        rates_fail: bool = False,
    ):
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request(
            dest_cc=dest_cc,
            dest_city=dest_city,
            dest_postal=dest_postal,
            product_code=requested_product,
        )

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.return_value = (
                _rates_error() if rates_fail else _rates_resp(rates_products)
            )
            mock_client.post.return_value = _ship_resp(ship_tracking)
            result = adapter.create_shipment(request)

        return result, mock_client

    # ── PL→LT (EU intra-community, P not entitled) ───────────────────────────

    def test_pl_to_lt_uses_dhl_ranked_product_when_p_absent(self, tmp_path):
        """PL→LT: DHL returns [U, K], P requested → shipment sent with U."""
        result, client = self._run(
            tmp_path,
            dest_cc="LT", dest_city="Vilnius", dest_postal="01000",
            requested_product="P",
            rates_products=["U", "K"],
            ship_tracking="LT-AWB-001",
        )

        assert result.tracking_ref == "LT-AWB-001"
        body = client.post.call_args[1]["json"]
        assert body["productCode"] == "U"

    # ── PL→DE (EU, entitlement: U, W, P per CFIT) ────────────────────────────

    def test_pl_to_de_u_requested_and_present_stays_u(self, tmp_path):
        """PL→DE CFIT: U is available and requested → stays U."""
        result, client = self._run(
            tmp_path,
            dest_cc="DE", dest_city="Hamburg", dest_postal="20457",
            requested_product="U",
            rates_products=["U", "W", "P"],
            ship_tracking="DE-AWB-001",
        )

        assert result.tracking_ref == "DE-AWB-001"
        body = client.post.call_args[1]["json"]
        assert body["productCode"] == "U"

    def test_pl_to_de_p_requested_p_available_stays_p(self, tmp_path):
        """PL→DE: P is explicitly requested and available → stays P."""
        result, client = self._run(
            tmp_path,
            dest_cc="DE", dest_city="Hamburg", dest_postal="20457",
            requested_product="P",
            rates_products=["U", "W", "P"],
            ship_tracking="DE-AWB-002",
        )

        body = client.post.call_args[1]["json"]
        assert body["productCode"] == "P"

    # ── PL→CH (non-EU, P entitled per CFIT) ──────────────────────────────────

    def test_pl_to_ch_p_requested_and_available_stays_p(self, tmp_path):
        """PL→CH CFIT: P available and requested → stays P."""
        result, client = self._run(
            tmp_path,
            dest_cc="CH", dest_city="Basel", dest_postal="4000",
            requested_product="P",
            rates_products=["P", "U"],
            ship_tracking="CH-AWB-001",
        )

        assert result.tracking_ref == "CH-AWB-001"
        body = client.post.call_args[1]["json"]
        assert body["productCode"] == "P"

    # ── PL→US (non-EU, P entitled per CFIT) ──────────────────────────────────

    def test_pl_to_us_p_requested_and_available_stays_p(self, tmp_path):
        """PL→US CFIT: P available and requested → stays P."""
        result, client = self._run(
            tmp_path,
            dest_cc="US", dest_city="New York", dest_postal="10001",
            requested_product="P",
            rates_products=["P"],
            ship_tracking="US-AWB-001",
        )

        assert result.tracking_ref == "US-AWB-001"
        body = client.post.call_args[1]["json"]
        assert body["productCode"] == "P"

    # ── Fallback: rates endpoint failure ─────────────────────────────────────

    def test_rates_failure_falls_back_to_requested_product(self, tmp_path):
        """If GET /rates fails, the operator-requested product is used unchanged."""
        result, client = self._run(
            tmp_path,
            dest_cc="LT", dest_city="Vilnius", dest_postal="01000",
            requested_product="P",
            rates_products=[],
            rates_fail=True,
            ship_tracking="LT-FALLBACK-001",
        )

        assert result.tracking_ref == "LT-FALLBACK-001"
        body = client.post.call_args[1]["json"]
        # Fallback: P was requested and rates failed → P used (DHL may reject,
        # but we don't substitute blindly without discovery)
        assert body["productCode"] == "P"

    def test_rates_api_always_called_before_shipment(self, tmp_path):
        """GET /rates is called once; POST /shipments follows."""
        _, client = self._run(
            tmp_path,
            dest_cc="CH", dest_city="Basel", dest_postal="4000",
            requested_product="P",
            rates_products=["P"],
        )

        assert client.get.call_count == 1
        assert client.post.call_count == 1
        # Ensure GET came before POST
        get_url = client.get.call_args[0][0]
        post_url = client.post.call_args[0][0]
        assert "/rates" in get_url
        assert "/shipments" in post_url

    def test_rates_result_cached_across_two_shipments(self, tmp_path):
        """Two create_shipment() calls for the same route hit /rates only once."""
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request(dest_cc="US", dest_city="New York", dest_postal="10001")

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.return_value = _rates_resp(["P"])
            mock_client.post.side_effect = [
                _ship_resp("US-AWB-A"),
                _ship_resp("US-AWB-B"),
            ]
            r1 = adapter.create_shipment(request)
            r2 = adapter.create_shipment(request)

        assert r1.tracking_ref == "US-AWB-A"
        assert r2.tracking_ref == "US-AWB-B"
        # GET /rates hit once despite two shipments
        assert mock_client.get.call_count == 1
        assert mock_client.post.call_count == 2


# ── TestBuildShipmentBodyProductOverride ─────────────────────────────────────


class TestBuildShipmentBodyProductOverride:
    """_build_shipment_body() product_code kwarg takes precedence over request.product_code."""

    def _fake_settings(self):
        mock = MagicMock()
        mock.dhl_express_shipper_name = "Estrella"
        mock.dhl_express_shipper_address1 = "ul. Sabaly 58"
        mock.dhl_express_shipper_city = "Warszawa"
        mock.dhl_express_shipper_postal_code = "02-174"
        mock.dhl_express_shipper_country_code = "PL"
        mock.dhl_express_shipper_phone = "+48516081994"
        return mock

    def test_product_code_kwarg_overrides_request_field(self):
        req = _make_request(product_code="P")
        body = _build_shipment_body(req, self._fake_settings(), product_code="U")
        assert body["productCode"] == "U"

    def test_no_kwarg_falls_back_to_request_product_code(self):
        req = _make_request(product_code="W")
        body = _build_shipment_body(req, self._fake_settings())
        assert body["productCode"] == "W"

    def test_no_kwarg_no_request_field_defaults_to_p(self):
        req = _make_request(product_code="")
        body = _build_shipment_body(req, self._fake_settings())
        assert body["productCode"] == "P"

    def test_none_kwarg_falls_back_to_request_product_code(self):
        req = _make_request(product_code="K")
        body = _build_shipment_body(req, self._fake_settings(), product_code=None)
        assert body["productCode"] == "K"


# ── TestBrazilPLTBypass ───────────────────────────────────────────────────────


class TestBrazilPLTBypass:
    """Brazil routes require bypassPLTError=true in the POST URL and WY in valueAddedServices."""

    def _fake_settings(self):
        mock = MagicMock()
        mock.dhl_express_shipper_name = "Estrella Jewels"
        mock.dhl_express_shipper_address1 = "ul. Sabaly 58"
        mock.dhl_express_shipper_city = "Warszawa"
        mock.dhl_express_shipper_postal_code = "02-174"
        mock.dhl_express_shipper_country_code = "PL"
        mock.dhl_express_shipper_phone = "+48516081994"
        return mock

    def _run(
        self,
        tmp_path,
        dest_cc: str,
        dest_city: str = "Sao Paulo",
        dest_postal: str = "01001-001",
    ):
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request(dest_cc=dest_cc, dest_city=dest_city, dest_postal=dest_postal)

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.return_value = _rates_error()
            mock_client.post.return_value = _ship_resp("AWB-TEST")
            adapter.create_shipment(request)

        return mock_client

    # ── POST URL ──────────────────────────────────────────────────────────────

    def test_br_post_url_contains_bypass_plt_error(self, tmp_path):
        """POST URL must include ?bypassPLTError=true for BR destination."""
        client = self._run(tmp_path, dest_cc="BR")
        url = client.post.call_args[0][0]
        assert "bypassPLTError=true" in url

    def test_de_post_url_has_no_bypass_plt_error(self, tmp_path):
        """DE (EU) route must NOT have bypassPLTError in POST URL."""
        client = self._run(tmp_path, dest_cc="DE", dest_city="Hamburg", dest_postal="20457")
        url = client.post.call_args[0][0]
        assert "bypassPLTError" not in url

    def test_ch_post_url_has_no_bypass_plt_error(self, tmp_path):
        """CH (non-EU, non-BR) route must NOT have bypassPLTError in POST URL."""
        client = self._run(tmp_path, dest_cc="CH", dest_city="Basel", dest_postal="4000")
        url = client.post.call_args[0][0]
        assert "bypassPLTError" not in url

    def test_us_post_url_has_no_bypass_plt_error(self, tmp_path):
        """US route must NOT have bypassPLTError in POST URL."""
        client = self._run(tmp_path, dest_cc="US", dest_city="New York", dest_postal="10001")
        url = client.post.call_args[0][0]
        assert "bypassPLTError" not in url

    # ── POST body ─────────────────────────────────────────────────────────────

    def test_br_body_contains_wy_service(self, tmp_path):
        """WY must be in valueAddedServices for BR destination."""
        client = self._run(tmp_path, dest_cc="BR")
        body = client.post.call_args[1]["json"]
        assert body.get("valueAddedServices") == [{"serviceCode": "WY"}]

    def test_de_body_has_no_wy_service(self, tmp_path):
        """DE body must NOT have WY injected by BR PLT logic."""
        client = self._run(tmp_path, dest_cc="DE", dest_city="Hamburg", dest_postal="20457")
        body = client.post.call_args[1]["json"]
        assert "valueAddedServices" not in body

    def test_ch_body_has_no_wy_service(self, tmp_path):
        """CH body must NOT have WY injected by BR PLT logic."""
        client = self._run(tmp_path, dest_cc="CH", dest_city="Basel", dest_postal="4000")
        body = client.post.call_args[1]["json"]
        assert "valueAddedServices" not in body

    # ── _build_shipment_body() unit ───────────────────────────────────────────

    def test_build_body_br_includes_wy(self):
        """_build_shipment_body() adds WY to valueAddedServices for BR."""
        req = _make_request(dest_cc="BR", dest_city="Sao Paulo", dest_postal="01001-001")
        body = _build_shipment_body(req, self._fake_settings())
        assert body.get("valueAddedServices") == [{"serviceCode": "WY"}]

    def test_build_body_de_no_wy(self):
        """_build_shipment_body() does NOT add WY for DE routes."""
        req = _make_request(dest_cc="DE", dest_city="Hamburg", dest_postal="20457")
        body = _build_shipment_body(req, self._fake_settings())
        assert "valueAddedServices" not in body

    def test_build_body_ch_no_wy(self):
        """_build_shipment_body() does NOT add WY for CH routes."""
        req = _make_request(dest_cc="CH", dest_city="Basel", dest_postal="4000")
        body = _build_shipment_body(req, self._fake_settings())
        assert "valueAddedServices" not in body


# ── TestEuCustomsDeclarable ───────────────────────────────────────────────────


class TestEuCustomsDeclarable:
    """Intra-EU shipments are customs-free: isCustomsDeclarable=false, no
    exportDeclaration. Non-EU destinations stay dutiable (DHL 7121 fix).
    Shipper origin is PL in all cases (settings mock)."""

    def _fake_settings(self, country_code: str = "PL"):
        mock = MagicMock()
        mock.dhl_express_shipper_name = "Estrella Jewels"
        mock.dhl_express_shipper_address1 = "ul. Sabaly 58"
        mock.dhl_express_shipper_city = "Warszawa"
        mock.dhl_express_shipper_postal_code = "02-174"
        mock.dhl_express_shipper_country_code = country_code
        mock.dhl_express_shipper_phone = "+48516081994"
        return mock

    def _body(self, dest_cc, dest_city, dest_postal, origin_cc="PL"):
        req = _make_request(dest_cc=dest_cc, dest_city=dest_city, dest_postal=dest_postal)
        return _build_shipment_body(req, self._fake_settings(origin_cc))

    # ── EU→EU: customs-free ───────────────────────────────────────────────────

    def test_pl_to_lt_not_customs_declarable(self):
        body = self._body("LT", "Vilnius", "01000")
        assert body["content"]["isCustomsDeclarable"] is False

    def test_pl_to_de_not_customs_declarable(self):
        body = self._body("DE", "Hamburg", "20457")
        assert body["content"]["isCustomsDeclarable"] is False

    def test_eu_to_eu_has_no_export_declaration(self):
        body = self._body("LT", "Vilnius", "01000")
        assert "exportDeclaration" not in body["content"]

    def test_eu_dest_lowercase_country_code_still_customs_free(self):
        """Country-code comparison is case-insensitive."""
        body = self._body("lt", "Vilnius", "01000")
        assert body["content"]["isCustomsDeclarable"] is False

    # ── non-EU: dutiable ──────────────────────────────────────────────────────

    def test_pl_to_ch_customs_declarable(self):
        body = self._body("CH", "Basel", "4000")
        assert body["content"]["isCustomsDeclarable"] is True

    def test_pl_to_us_customs_declarable(self):
        body = self._body("US", "New York", "10001")
        assert body["content"]["isCustomsDeclarable"] is True

    def test_pl_to_br_customs_declarable_and_keeps_wy(self):
        """BR stays dutiable AND keeps the WY valueAddedServices injection."""
        body = self._body("BR", "Sao Paulo", "01001-001")
        assert body["content"]["isCustomsDeclarable"] is True
        assert body.get("valueAddedServices") == [{"serviceCode": "WY"}]

    # ── BR integration: bypassPLTError URL param unaffected ──────────────────

    def test_br_url_still_has_bypass_plt_error(self, tmp_path):
        """The EU flag change does not disturb the BR bypassPLTError URL param."""
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request(dest_cc="BR", dest_city="Sao Paulo", dest_postal="01001-001")

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.return_value = _rates_error()
            mock_client.post.return_value = _ship_resp("AWB-BR")
            adapter.create_shipment(request)

        url = mock_client.post.call_args[0][0]
        assert "bypassPLTError=true" in url
        body = mock_client.post.call_args[1]["json"]
        assert body["content"]["isCustomsDeclarable"] is True

    # ── preserved fields regression ───────────────────────────────────────────

    def test_eu_body_preserves_references_and_registration(self):
        """CU references and issuerCountryCode logic unaffected by EU flag."""
        req = ShipmentRequest(
            batch_id="BATCH-EU-1",
            shipper_account="427294774",
            recipient_address={
                "name": "Test", "street": "Gedimino 1", "city": "Vilnius",
                "postal_code": "01000", "country_code": "LT", "phone": "+37060000000",
            },
            declared_value=500.0, currency="EUR", weight_kg=1.5,
            dimensions={"length_cm": 20, "width_cm": 15, "height_cm": 10},
            product_code="U",
            customer_reference="REF-EU-1",
            receiver_vat_id="LT100001738313",
        )
        body = _build_shipment_body(req, self._fake_settings())
        assert body["customerReferences"] == [{"value": "REF-EU-1", "typeCode": "CU"}]
        regs = body["customerDetails"]["receiverDetails"]["registrationNumbers"]
        assert regs == [{"number": "LT100001738313", "typeCode": "EUV",
                         "issuerCountryCode": "LT"}]
        assert body["content"]["isCustomsDeclarable"] is False


# ── TestRatesDutiableThreading ────────────────────────────────────────────────


class TestRatesDutiableThreading:
    """The rates discovery query must ask for the same dutiable class the
    shipment is posted with (DHL 1001 incident: dutiable PL→LT rates returned
    [P, 8], so P sailed into a non-dutiable shipment and DHL rejected it)."""

    def _run(self, tmp_path, dest_cc, dest_city, dest_postal,
             rates_products=None, rates_fail=False, requested="P"):
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request(
            dest_cc=dest_cc, dest_city=dest_city, dest_postal=dest_postal,
            product_code=requested,
        )
        with _mock_settings(tmp_path), patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.return_value = (
                _rates_error() if rates_fail else _rates_resp(rates_products or [])
            )
            mock_client.post.return_value = _ship_resp("AWB-THREAD")
            adapter.create_shipment(request)
        return mock_client

    # ── rates query carries the shipment's dutiable class ────────────────────

    def test_pl_to_lt_rates_query_is_non_dutiable(self, tmp_path):
        client = self._run(tmp_path, "LT", "Vilnius", "01000",
                           rates_products=["U", "K"])
        params = client.get.call_args[1]["params"]
        assert params["isCustomsDeclarable"] is False

    def test_pl_to_de_rates_query_is_non_dutiable(self, tmp_path):
        client = self._run(tmp_path, "DE", "Hamburg", "20457",
                           rates_products=["U", "W"])
        params = client.get.call_args[1]["params"]
        assert params["isCustomsDeclarable"] is False

    def test_pl_to_ch_rates_query_is_dutiable(self, tmp_path):
        client = self._run(tmp_path, "CH", "Basel", "4000",
                           rates_products=["P"])
        params = client.get.call_args[1]["params"]
        assert params["isCustomsDeclarable"] is True

    def test_pl_to_br_rates_query_is_dutiable(self, tmp_path):
        client = self._run(tmp_path, "BR", "Sao Paulo", "01001-001",
                           rates_products=["P"])
        params = client.get.call_args[1]["params"]
        assert params["isCustomsDeclarable"] is True

    # ── resolved product reaches the shipment body ────────────────────────────

    def test_pl_to_lt_requested_p_available_uk_body_has_u_not_p(self, tmp_path):
        """Operator regression: requested P, available [U, K] → body U, no P."""
        client = self._run(tmp_path, "LT", "Vilnius", "01000",
                           rates_products=["U", "K"], requested="P")
        body = client.post.call_args[1]["json"]
        assert body["productCode"] == "U"
        assert body["productCode"] != "P"

    def test_pl_to_lt_real_nondutiable_list_resolves_to_u_not_c(self, tmp_path):
        """Real DHL non-dutiable PL→LT list leads with C (Medical Express) —
        the equivalence table must pick U, never C."""
        client = self._run(tmp_path, "LT", "Vilnius", "01000",
                           rates_products=["C", "T", "U", "7", "B", "W"],
                           requested="P")
        body = client.post.call_args[1]["json"]
        assert body["productCode"] == "U"

    def test_rates_failure_still_falls_back_to_requested(self, tmp_path):
        client = self._run(tmp_path, "LT", "Vilnius", "01000",
                           rates_fail=True, requested="P")
        body = client.post.call_args[1]["json"]
        assert body["productCode"] == "P"

    # ── select_product_code equivalence units ─────────────────────────────────

    def test_select_p_prefers_u_over_list_head(self):
        assert select_product_code("P", ["C", "T", "U", "7", "B", "W"]) == "U"

    def test_select_p_prefers_w_when_u_absent(self):
        assert select_product_code("P", ["C", "T", "7", "B", "W"]) == "W"

    def test_select_p_falls_back_to_list_head_without_equivalents(self):
        assert select_product_code("P", ["C", "T"]) == "C"

    # ── empty rates results are not cached ────────────────────────────────────

    def test_empty_rates_success_not_cached(self):
        """A 200 response with zero products must NOT poison the cache."""
        kwargs = dict(
            api_key="key", api_secret="secret",
            api_url="https://express.api.dhl.com", api_path="/mydhlapi",
            account="427294774", origin_cc="PL", origin_city="Warszawa",
            origin_postal="02-174", dest_cc="LT", dest_city="Vilnius",
            dest_postal="01000", weight_kg=1.5, planned_date="2026-07-03",
            is_customs_declarable=False,
        )
        with patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.side_effect = [
                _rates_resp([]),          # first: empty success
                _rates_resp(["U", "K"]),  # second: real answer
            ]
            first = lookup_available_products(**kwargs)
            second = lookup_available_products(**kwargs)

        assert first == []
        assert second == ["U", "K"]
        assert mock_client.get.call_count == 2  # empty result was not cached

    def test_cache_key_separates_dutiable_class(self):
        """Dutiable and non-dutiable lookups for the same route don't collide."""
        base = dict(
            api_key="key", api_secret="secret",
            api_url="https://express.api.dhl.com", api_path="/mydhlapi",
            account="427294774", origin_cc="PL", origin_city="Warszawa",
            origin_postal="02-174", dest_cc="LT", dest_city="Vilnius",
            dest_postal="01000", weight_kg=1.5, planned_date="2026-07-03",
        )
        with patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.side_effect = [
                _rates_resp(["P", "8"]),                      # dutiable
                _rates_resp(["C", "T", "U", "7", "B", "W"]),  # non-dutiable
            ]
            dutiable = lookup_available_products(**base, is_customs_declarable=True)
            nondutiable = lookup_available_products(**base, is_customs_declarable=False)

        assert dutiable == ["P", "8"]
        assert nondutiable == ["C", "T", "U", "7", "B", "W"]
        assert mock_client.get.call_count == 2
