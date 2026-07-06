"""
Weight unit authority — packing weights are GRAMS, not kg (2026-07-06).

Root cause pinned here: packing_lines.net_weight / gross_weight are stored
in grams (supplier sheet columns "GR.WT/NT.WT (GMS)"), but the Logistics tab
and CMR renderer labelled the raw values as kg (a 2.01 g ring displayed as
"2.010 kg").

Convention pinned by this suite:
  - per-line jewellery weights display in GRAMS ("2.010 g")
  - shipment-level totals display in KG via grams / 1000 ("0.030 kg")
  - package weight composition: package_weight_kg = goods_g / 1000 + tare_kg
  - stored data is never rewritten; conversion happens only at display /
    composition boundaries
  - the DHL live booking weight (operator-entered kg in the AWB modal) is a
    separate authority and is untouched — the live adapter never reads
    packing_lines

No live DHL calls anywhere in this suite.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.carrier.doc_package import package_weight_kg


_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
JSX_DETAIL = _V2 / "proforma-detail.jsx"
JSX_CMR = _V2 / "estrella-doc-cmr.jsx"
JSX_PACKING = _V2 / "estrella-doc-packing.jsx"
LIVE = (Path(__file__).resolve().parents[1]
        / "app" / "services" / "carrier" / "adapters" / "live.py")
DOC_PKG = (Path(__file__).resolve().parents[1]
           / "app" / "services" / "carrier" / "doc_package.py")


def _js_toFixed3(v: float) -> str:
    """Python equivalent of JS Number(v).toFixed(3) for the pinned formatters."""
    return f"{v:.3f}"


def _fmt_g(v: float) -> str:
    """Mirror of the pinned Logistics _fmtG: per-line grams."""
    return _js_toFixed3(v) + " g" if v > 0 else "—"


def _fmt_kg_from_g(g: float) -> str:
    """Mirror of the pinned Logistics _fmtKgFromG: totals in kg from grams."""
    return _js_toFixed3(g / 1000.0) + " kg" if g > 0 else "—"


# ── Display convention (numeric examples from the incident) ───────────────────


class TestDisplayConvention:
    def test_ring_2_01_displays_grams_not_kg(self):
        """A 2.01-gram ring renders '2.010 g' — never '2.010 kg'."""
        assert _fmt_g(2.01) == "2.010 g"
        assert _fmt_g(2.01) != "2.010 kg"

    def test_total_29_965_grams_as_kg(self):
        """Shipment-level context: 29.965 g total renders '0.030 kg'."""
        assert _fmt_kg_from_g(29.965) == "0.030 kg"

    def test_total_29_965_grams_as_grams(self):
        """Per-line context: the same total renders '29.965 g'."""
        assert _fmt_g(29.965) == "29.965 g"

    def test_zero_weight_renders_dash(self):
        assert _fmt_g(0) == "—"
        assert _fmt_kg_from_g(0) == "—"


# ── Path-DOC package weight composition ───────────────────────────────────────


class TestPackageWeightComposition:
    def test_gross_grams_plus_tare_kg(self):
        """29.965 g goods + 0.1 kg box tare = 0.129965 kg (≈ 0.130 kg)."""
        assert package_weight_kg(29.965, 0.1) == pytest.approx(0.129965)
        assert _js_toFixed3(package_weight_kg(29.965, 0.1)) == "0.130"

    def test_grams_are_converted_before_adding_tare(self):
        """The incident shape: grams must NOT be added directly to tare kg —
        2000 g + 0.1 kg is 2.1 kg, not 2000.1."""
        assert package_weight_kg(2000, 0.1) == pytest.approx(2.1)
        assert package_weight_kg(2000, 0.1) < 3

    def test_tare_only_when_no_goods_weight(self):
        assert package_weight_kg(0, 0.1) == pytest.approx(0.1)
        assert package_weight_kg(None, None) == 0.0

    def test_cn23_composition_uses_the_shared_formula(self):
        """CN23 declared weight goes through package_weight_kg (no second
        composition path that could relabel grams as kg)."""
        src = DOC_PKG.read_text(encoding="utf-8")
        assert "declared_weight_kg = package_weight_kg(" in src
        assert "Gross weight (kg):" in src            # kg label only after conversion

    def test_doc_package_labels_line_weights_as_grams(self):
        """Packing list + CN23 line columns declare grams explicitly."""
        src = DOC_PKG.read_text(encoding="utf-8")
        assert "Gross Wt (g)" in src                  # packing list header
        assert '"Wt (g)"' in src                      # CN23 contents header


# ── Logistics tab (proforma-detail.jsx) ───────────────────────────────────────


class TestLogisticsTabPins:
    def _src(self):
        return JSX_DETAIL.read_text(encoding="utf-8")

    def test_per_line_weight_uses_gram_formatter(self):
        src = self._src()
        assert "_fmtG(r.net_weight)" in src
        assert "toFixed(3) + ' g'" in src

    def test_totals_convert_grams_to_kg(self):
        src = self._src()
        assert "_fmtKgFromG(_grossTotal)" in src
        assert "/ 1000).toFixed(3) + ' kg'" in src

    def test_raw_gram_values_never_labelled_kg(self):
        """The old formatter (raw value + ' kg') is gone from the tab."""
        src = self._src()
        assert "_fmtKg(r.net_weight)" not in src
        assert "_fmtKg(_netTotal)" not in src
        assert "_fmtKg(_grossTotal)" not in src

    def test_unit_authority_comment_present(self):
        assert "stored\n          // in GRAMS" in self._src() or "GRAMS" in self._src()

    def test_awb_modal_weight_behavior_untouched(self):
        """The AWB card weight is the operator-entered kg from the modal —
        still rendered as kg, unconverted (separate authority)."""
        src = self._src()
        assert "`${carrierShipment.weight_kg} kg`" in src


# ── CMR renderer (estrella-doc-cmr.jsx) ───────────────────────────────────────


class TestCmrPins:
    def _src(self):
        return JSX_CMR.read_text(encoding="utf-8")

    def test_per_line_net_weight_in_grams(self):
        src = self._src()
        assert src.count("net_weight).toFixed(3)} g`") >= 2   # Classic + Modern
        assert "net_weight).toFixed(3)} kg" not in src        # grams never as kg

    def test_totals_divide_grams_by_1000(self):
        src = self._src()
        assert src.count("(_totNw / 1000).toFixed(3)} kg") >= 2

    def test_modern_variant_defines_gram_total(self):
        """EJCMRModern computes _totNw (was only inline reduces before)."""
        src = self._src()
        modern = src.split("function EJCMRModern")[1]
        assert "_totNw" in modern

    def test_carrier_weight_kg_untouched(self):
        """carrier.weight_kg (AWB modal kg authority) stays plain kg."""
        assert "carrier.weight_kg ? `${carrier.weight_kg} kg`" in self._src()

    def test_source_comment_declares_grams(self):
        assert "GRAMS" in self._src()


# ── Packing list document (estrella-doc-packing.jsx) ──────────────────────────


class TestPackingDocPins:
    def test_headers_declare_units(self):
        src = JSX_PACKING.read_text(encoding="utf-8")
        assert "Gross Wt (g)" in src
        assert "Net Wt (g)" in src
        assert "Dia Wt (ct)" in src
        assert "Col Wt (ct)" in src

    def test_weights_never_labelled_kg(self):
        src = JSX_PACKING.read_text(encoding="utf-8")
        assert "Wt (kg)" not in src
        assert "_pkgFmtWt" in src                      # raw values, unit in header


# ── DHL live booking isolation ────────────────────────────────────────────────


class TestDhlBookingIsolation:
    def test_live_adapter_never_reads_packing_weights(self):
        """DHL booking weight comes from ShipmentRequest.weight_kg (operator-
        entered kg in the AWB modal) — the live adapter must not read the
        gram-based packing authority at all."""
        src = LIVE.read_text(encoding="utf-8")
        assert "packing_lines" not in src
        assert "net_weight" not in src
        assert "gross_weight" not in src
        assert "request.weight_kg" in src
