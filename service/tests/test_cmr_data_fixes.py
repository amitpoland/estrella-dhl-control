"""
test_cmr_data_fixes.py

CMR data-contract pins after single-canonical cutover.
Authority: commercial_cmr.py + commercial_cmr_html.py.
Frontend consumes cmr.json / cmr.html — does not rebuild parties/carrier locally.
"""
from pathlib import Path

_V2_DIR = Path(__file__).parent.parent / "app" / "static" / "v2"
_DETAIL = _V2_DIR / "proforma-detail.jsx"
_CMR_PY = Path(__file__).parent.parent / "app" / "services" / "commercial_cmr.py"
_CMR_HTML = Path(__file__).parent.parent / "app" / "services" / "commercial_cmr_html.py"


def _detail_src():
    return _DETAIL.read_text(encoding="utf-8")


def _cmr_py():
    return _CMR_PY.read_text(encoding="utf-8")


def _cmr_html():
    return _CMR_HTML.read_text(encoding="utf-8")


class TestFrontendConsumesCanonicalCmr:
    def test_no_local_cmr_projection(self):
        src = _detail_src()
        assert "const cmrPreviewData" not in src
        assert "getCmrDocument" in src
        assert "getCmrHtml" in src
        assert "canonicalCmr" in src


class TestFix1PlaceOfDelivery:
    def test_parties_resolver_owns_shipto_city_zip(self):
        parties = (
            Path(__file__).parent.parent / "app" / "services" / "commercial_document_parties.py"
        ).read_text(encoding="utf-8")
        assert "city" in parties and "zip" in parties
        assert "ship_to_override" in parties or "ship_to" in parties

    def test_cmr_html_renders_shipto_zip(self):
        src = _cmr_html()
        assert "zip" in src.lower()


class TestFix2OriginPickup:
    def test_country_map_in_commercial_cmr(self):
        src = _cmr_py()
        assert "_ISO2_COUNTRY" in src
        assert '"PL": "Poland"' in src
        assert '"LT": "Lithuania"' in src
        assert "def _country_name" in src

    def test_carrier_origin_from_seller_city(self):
        src = _cmr_py()
        assert 'seller.get("city")' in src


class TestFix3Pieces:
    def test_pieces_from_aggregated_line_qty(self):
        src = _cmr_py()
        assert '"pieces":' in src
        assert "total_pcs" in src


class TestFix4And5WeightDimensions:
    def test_weight_from_shipment_row_only(self):
        src = _cmr_py()
        assert 'shipment_row.get("weight_kg")' in src


class TestFix6Insurance:
    def test_insurance_text_canonical(self):
        src = _cmr_py()
        assert "Future Generali" in src
        assert "_draft_has_insurance" in src
        assert "_CMR_INSURANCE_TEXT" in src
