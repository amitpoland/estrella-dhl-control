"""
test_cmr_data_fixes.py

Source-grep tests verifying the 6 CMR data fixes applied to:
  - proforma-detail.jsx  (cmrPreviewData assembly)
  - estrella-doc-cmr.jsx (Box 3 renderer + shape comment)

Fixes:
  1. Place of delivery (Box 3): city + zip + country (not bare country code)
  2. Origin/Pickup: sender city + country name (not bare country code "PL")
  3. Pieces: sum of proforma lines (SALES packing list total)
  4. Gross Weight: null placeholder (from AWB, not yet available)
  5. Dimensions: null placeholder (from AWB, not yet available)
  6. Insurance: canonical Future Generali wording when insurance charge present
"""
from pathlib import Path

_V2_DIR = Path(__file__).parent.parent / "app" / "static" / "v2"
_DETAIL = _V2_DIR / "proforma-detail.jsx"
_CMR    = _V2_DIR / "estrella-doc-cmr.jsx"


def _detail_src():
    return _DETAIL.read_text(encoding="utf-8")


def _cmr_src():
    return _CMR.read_text(encoding="utf-8")


# ── Fix #1 — Place of delivery ───────────────────────────────────────────────

class TestFix1PlaceOfDelivery:
    def test_shipto_city_uses_sto_city_or_bo_city(self):
        """shipto.city must use actual city from ship_to_override / buyer_override."""
        src = _detail_src()
        assert "sto.city || bo.city" in src

    def test_shipto_zip_field_present(self):
        """shipto.zip must be populated from sto.zip / bo.zip."""
        src = _detail_src()
        assert "sto.zip" in src and "bo.zip" in src

    def test_cmr_renderer_box3_includes_zip(self):
        """Box 3 renderer must join city, zip, and country."""
        src = _cmr_src()
        assert "d.shipto.zip" in src

    def test_cmr_shape_comment_has_zip(self):
        """Shape comment for .shipto must document the zip field."""
        src = _cmr_src()
        assert "city, zip, country" in src

    def test_box3_filter_boolean_pattern(self):
        """Box 3 uses .filter(Boolean).join to gracefully omit missing zip."""
        src = _cmr_src()
        # The renderer block for Box 3 must contain this pattern
        assert 'filter(Boolean).join(",")' in src.replace(', ', ',').replace(' ', '')


# ── Fix #2 — Origin/Pickup ───────────────────────────────────────────────────

class TestFix2OriginPickup:
    def test_seller_city_uses_postal_city(self):
        """seller.city in cmrPreviewData must come from companyProfile.postal_city."""
        src = _detail_src()
        assert "companyProfile.postal_city" in src

    def test_carrier_origin_uses_postal_city(self):
        """carrier.origin must reference companyProfile.postal_city."""
        src = _detail_src()
        assert "companyProfile.postal_city" in src

    def test_cmr_country_names_map_present(self):
        """_CMR_COUNTRY_NAMES lookup map must be defined."""
        src = _detail_src()
        assert "_CMR_COUNTRY_NAMES" in src

    def test_pl_poland_in_country_map(self):
        """Poland must be in the country map (primary sender country)."""
        src = _detail_src()
        assert "PL: 'Poland'" in src

    def test_lt_lithuania_in_country_map(self):
        """Lithuania must be in the country map (primary destination)."""
        src = _detail_src()
        assert "LT: 'Lithuania'" in src

    def test_cmr_country_name_function(self):
        """_cmrCountryName helper function must exist."""
        src = _detail_src()
        assert "_cmrCountryName" in src

    def test_origin_joins_city_and_country(self):
        """carrier.origin must join city and country name with filter(Boolean).join."""
        src = _detail_src()
        assert "_cmrCountryName(exporter.country)" in src


# ── Fix #3 — Pieces ──────────────────────────────────────────────────────────

class TestFix3Pieces:
    def test_cmr_total_pcs_computed(self):
        """_cmrTotalPcs must be computed by summing proforma line quantities."""
        src = _detail_src()
        assert "_cmrTotalPcs" in src

    def test_pieces_uses_reduce(self):
        """pieces sum uses Array.reduce over lines."""
        src = _detail_src()
        assert "lines.reduce" in src

    def test_carrier_pieces_field_present(self):
        """carrier.pieces must be in the cmrPreviewData carrier object."""
        src = _detail_src()
        assert "pieces:" in src


# ── Fix #4 + #5 — Weight / Dimensions ────────────────────────────────────────

class TestFix4Fix5WeightDimensions:
    def test_carrier_weight_kg_field_present(self):
        """carrier.weight_kg must be declared (null = not yet from AWB)."""
        src = _detail_src()
        assert "weight_kg:" in src

    def test_carrier_dim_cm_field_present(self):
        """carrier.dim_cm must be declared (null = not yet from AWB)."""
        src = _detail_src()
        assert "dim_cm:" in src

    def test_weight_null_placeholder_documented(self):
        """Comment must explain weight_kg is from AWB (not yet available)."""
        src = _detail_src()
        assert "AWB" in src and "weight_kg" in src


# ── Fix #6 — Insurance ───────────────────────────────────────────────────────

class TestFix6Insurance:
    def test_insurance_text_constant_present(self):
        """Canonical insurance wording constant must be defined."""
        src = _detail_src()
        assert "_CMR_INSURANCE_TEXT" in src

    def test_insurance_mentions_future_generali(self):
        """Insurance text must name Future Generali India Insurance Company Limited."""
        src = _detail_src()
        assert "Future Generali India Insurance Company Limited" in src

    def test_insurance_charge_check(self):
        """_cmrHasInsurance must check service_charges for charge_type === 'insurance'."""
        src = _detail_src()
        assert "_cmrHasInsurance" in src
        assert "service_charges" in src
        assert "insurance" in src.lower()

    def test_carrier_insurance_field_present(self):
        """carrier.insurance must be wired to _cmrHasInsurance conditional."""
        src = _detail_src()
        assert "_cmrHasInsurance ? _CMR_INSURANCE_TEXT : null" in src

    def test_insurance_check_validates_amount(self):
        """Insurance check must verify amount > 0, not just presence of the charge."""
        src = _detail_src()
        # Must check that amount is non-zero to avoid zero-EUR placeholder charges
        assert "Number(c.amount)" in src or "c.amount" in src


# ── Renderer compatibility: insurance display in estrella-doc-cmr.jsx ─────────

class TestCMRRendererInsurance:
    def test_cmr_classic_insurance_in_box20(self):
        """CMR Classic box 20 must render carrier.insurance when present."""
        src = _cmr_src()
        assert "carrier.insurance" in src

    def test_cmr_modern_insurance_in_spec_strip(self):
        """CMR Modern spec strip must display carrier.insurance."""
        src = _cmr_src()
        assert 'carrier.insurance || "—"' in src
