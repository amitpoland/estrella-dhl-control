"""
test_service_product_registry_phase2_3.py — Phase 2 (service-product registry) and
Phase 3 (commercial line emission) regression tests.

Coverage:
  1.  _build_service_charge_lines — empty input
  2.  _build_service_charge_lines — mapped freight
  3.  _build_service_charge_lines — mapped insurance
  4.  _build_service_charge_lines — both charge types mapped
  5.  _build_service_charge_lines — unknown charge_type excluded with note
  6.  _build_service_charge_lines — charge type allowed but not mapped → unmapped note
  7.  _build_service_charge_lines — currency mismatch → excluded with note
  8.  _build_service_charge_lines — empty charge currency adopts doc currency
  9.  _build_service_charge_lines — zero amount skipped (no line, no note)
  10. _build_service_charge_lines — negative amount skipped
  11. _build_service_charge_lines — invalid amount → unmapped note
  12. _build_service_charge_lines — mirror DB absent → unmapped note (C-3g)
  13. GET /api/v1/proforma/service-products — returns all charge types
  14. GET returns "unmapped" status before any mapping registered
  15. GET returns "mapped" after PUT registers a product
  16. PUT /api/v1/proforma/service-products/freight — registers mapping successfully
  17. PUT returns ok=true with correct fields
  18. PUT with unknown charge_type → 400
  19. PUT with empty wfirma_product_id → 400
  20. PUT charge_type is case-normalised to lowercase
  21. Integration: proforma XML includes service charge line when mapping present
  22. Integration: proforma XML omits service charge line when no mapping

C-3g (Wave-2 ratification): identity = wfirma_product_mirror; emission
metadata = pildb.service_product_registry; the legacy wfirma_products cache
is retired from this path. Fixtures seed the REAL stores under tmp storage.
Also pins the C-1f `prod` NameError fix (source-grep + mapped-charge tests).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# ── path bootstrap ────────────────────────────────────────────────────────────

def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

# ── imports ───────────────────────────────────────────────────────────────────

from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_client
from app.services import wfirma_db as wfdb


# ── helpers ───────────────────────────────────────────────────────────────────

def _auth_headers(operator: str = "alice") -> dict:
    return {
        "X-API-KEY":  settings.api_key or "test-key",
        "X-Operator": operator,
    }


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    from app.main import app
    monkeypatch.setattr(settings, "wfirma_create_proforma_allowed", True)
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# C-3g: service-charge identity lives in wfirma_product_mirror; emission
# metadata (label/vat/unit) lives in pildb's service_product_registry. The
# legacy wfirma_products cache is no longer consulted, so these helpers seed
# the REAL stores under a tmp storage_root instead of monkeypatching wfdb.

def _seed_unmapped(monkeypatch, tmp_path):
    """Empty storage → no mirror rows → all charge types unmapped."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)


def _seed_mirror_and_meta(monkeypatch, tmp_path, mapping):
    """Seed mirror identity + registry metadata for {ct: (wfirma_id, name)}."""
    from app.services import reservation_db as _rdb
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    db = tmp_path / "reservation_queue.db"
    _rdb.init_reservation_db(db)
    for ct, (wid, name) in mapping.items():
        _rdb.upsert_product_mirror(db, wfirma_id=wid, product_code=ct)
        pildb.upsert_service_product_meta(
            tmp_path / "proforma_links.db", ct,
            product_name=name, vat_rate="23", unit="szt.",
        )


def _seed_freight_only(monkeypatch, tmp_path):
    """freight mapped, insurance not."""
    _seed_mirror_and_meta(monkeypatch, tmp_path,
                          {"freight": ("WFP-99001", "Fracht")})


def _seed_both(monkeypatch, tmp_path):
    """Both freight and insurance mapped."""
    _seed_mirror_and_meta(monkeypatch, tmp_path, {
        "freight":   ("WFP-99001", "Fracht"),
        "insurance": ("WFP-99002", "Ubezpieczenie"),
    })


# ── Unit tests: _build_service_charge_lines ───────────────────────────────────

class TestBuildServiceChargeLines:
    """Direct tests on _build_service_charge_lines without HTTP layer."""

    def _fn(self):
        from app.api.routes_proforma import _build_service_charge_lines
        return _build_service_charge_lines

    def test_empty_charges_returns_empty(self, monkeypatch):
        lines, note = self._fn()([], "EUR")
        assert lines == []
        assert note == ""

    def test_mapped_freight_emits_line(self, monkeypatch, tmp_path):
        _seed_freight_only(monkeypatch, tmp_path)
        lines, note = self._fn()(
            [{"charge_type": "freight", "amount": "150.00", "currency": "EUR"}],
            "EUR",
        )
        assert len(lines) == 1
        ln = lines[0]
        assert ln.product_code == "freight"
        assert ln.wfirma_good_id == "WFP-99001"
        assert ln.product_name == "Fracht"
        assert abs(ln.unit_price - 150.00) < 0.001
        assert ln.qty == 1.0
        assert ln.currency == "EUR"
        assert note == ""

    def test_mapped_insurance_emits_line(self, monkeypatch, tmp_path):
        _seed_both(monkeypatch, tmp_path)
        lines, note = self._fn()(
            [{"charge_type": "insurance", "amount": "22.50", "currency": "EUR"}],
            "EUR",
        )
        assert len(lines) == 1
        assert lines[0].wfirma_good_id == "WFP-99002"
        # Phase 3 (insurance_wording campaign): insurance line name is now the
        # canonical wording from insurance_wording.DEFAULT_INSURANCE_LINE_NAME,
        # not the product registry text.  Verify it matches the canonical string.
        from app.services.insurance_wording import DEFAULT_INSURANCE_LINE_NAME
        assert lines[0].product_name == DEFAULT_INSURANCE_LINE_NAME
        assert note == ""

    def test_both_charge_types_both_emitted(self, monkeypatch, tmp_path):
        _seed_both(monkeypatch, tmp_path)
        charges = [
            {"charge_type": "freight",   "amount": "100.00", "currency": "EUR"},
            {"charge_type": "insurance", "amount": "15.00",  "currency": "EUR"},
        ]
        lines, note = self._fn()(charges, "EUR")
        assert len(lines) == 2
        codes = {ln.product_code for ln in lines}
        assert codes == {"freight", "insurance"}
        assert note == ""

    def test_unknown_charge_type_excluded_with_note(self, monkeypatch, tmp_path):
        _seed_both(monkeypatch, tmp_path)
        lines, note = self._fn()(
            [{"charge_type": "handling", "amount": "50.00", "currency": "EUR"}],
            "EUR",
        )
        assert lines == []
        assert "handling(unknown_type)" in note

    def test_allowed_type_unmapped_product_gives_note(self, monkeypatch, tmp_path):
        _seed_unmapped(monkeypatch, tmp_path)
        lines, note = self._fn()(
            [{"charge_type": "freight", "amount": "75.00", "currency": "EUR"}],
            "EUR",
        )
        assert lines == []
        assert "freight" in note

    def test_currency_mismatch_excluded_with_note(self, monkeypatch, tmp_path):
        _seed_freight_only(monkeypatch, tmp_path)
        lines, note = self._fn()(
            [{"charge_type": "freight", "amount": "100.00", "currency": "USD"}],
            "EUR",
        )
        assert lines == []
        assert "currency_mismatch" in note
        assert "USD" in note

    def test_empty_charge_currency_adopts_doc_currency(self, monkeypatch, tmp_path):
        _seed_freight_only(monkeypatch, tmp_path)
        # charge.currency is absent → adopts "EUR"
        lines, note = self._fn()(
            [{"charge_type": "freight", "amount": "80.00"}],
            "EUR",
        )
        assert len(lines) == 1
        assert lines[0].currency == "EUR"
        assert note == ""

    def test_zero_amount_skipped_no_note(self, monkeypatch, tmp_path):
        _seed_freight_only(monkeypatch, tmp_path)
        lines, note = self._fn()(
            [{"charge_type": "freight", "amount": "0.00", "currency": "EUR"}],
            "EUR",
        )
        assert lines == []
        # zero amount is silently skipped — no note needed
        assert note == ""

    def test_negative_amount_skipped(self, monkeypatch, tmp_path):
        _seed_freight_only(monkeypatch, tmp_path)
        lines, note = self._fn()(
            [{"charge_type": "freight", "amount": "-10.00", "currency": "EUR"}],
            "EUR",
        )
        assert lines == []
        assert note == ""

    def test_invalid_amount_gives_unmapped_note(self, monkeypatch, tmp_path):
        _seed_freight_only(monkeypatch, tmp_path)
        lines, note = self._fn()(
            [{"charge_type": "freight", "amount": "not_a_number", "currency": "EUR"}],
            "EUR",
        )
        assert lines == []
        assert "invalid_amount" in note

    def test_missing_mirror_db_treats_as_unmapped(self, monkeypatch, tmp_path):
        """C-3g: no reservation_queue.db under storage_root -> no identity ->
        the charge is unmapped (the legacy wfdb cache is never consulted)."""
        monkeypatch.setattr(settings, "storage_root", tmp_path)
        lines, note = self._fn()(
            [{"charge_type": "freight", "amount": "50.00", "currency": "EUR"}],
            "EUR",
        )
        assert lines == []
        assert "freight" in note

    def test_decimal_rounding_half_even(self, monkeypatch, tmp_path):
        """ROUND_HALF_EVEN applied: 0.005 → 0.00 (banker's rounding)."""
        _seed_freight_only(monkeypatch, tmp_path)
        lines, _ = self._fn()(
            [{"charge_type": "freight", "amount": "99.995", "currency": "EUR"}],
            "EUR",
        )
        # 99.995 ROUND_HALF_EVEN → 100.00 (5 at midpoint, round to even "0")
        assert len(lines) == 1
        assert abs(lines[0].unit_price - 100.00) < 0.001

    def test_mixed_mapped_unmapped_partial_emit(self, monkeypatch, tmp_path):
        """freight mapped, insurance not → freight emitted, note mentions insurance."""
        _seed_freight_only(monkeypatch, tmp_path)
        charges = [
            {"charge_type": "freight",   "amount": "100.00", "currency": "EUR"},
            {"charge_type": "insurance", "amount": "20.00",  "currency": "EUR"},
        ]
        lines, note = self._fn()(charges, "EUR")
        assert len(lines) == 1
        assert lines[0].product_code == "freight"
        assert "insurance" in note


# ── Endpoint tests: GET /api/v1/proforma/service-products ────────────────────

class TestGetServiceProducts:
    _PATH = "/api/v1/proforma/service-products"

    def test_returns_ok_true(self, client, monkeypatch, tmp_path):
        _seed_unmapped(monkeypatch, tmp_path)
        r = client.get(self._PATH, headers=_auth_headers())
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_returns_all_allowed_charge_types(self, client, monkeypatch, tmp_path):
        _seed_unmapped(monkeypatch, tmp_path)
        r = client.get(self._PATH, headers=_auth_headers())
        data = r.json()
        types_returned = {row["charge_type"] for row in data["service_products"]}
        assert types_returned == set(pildb.ALLOWED_SERVICE_CHARGE_TYPES)

    def test_unmapped_status_before_registration(self, client, monkeypatch, tmp_path):
        _seed_unmapped(monkeypatch, tmp_path)
        r = client.get(self._PATH, headers=_auth_headers())
        for row in r.json()["service_products"]:
            assert row["status"] == "unmapped"
            assert row["wfirma_product_id"] is None

    def test_mapped_status_after_freight_registered(self, client, monkeypatch, tmp_path):
        _seed_freight_only(monkeypatch, tmp_path)
        r = client.get(self._PATH, headers=_auth_headers())
        rows = {row["charge_type"]: row for row in r.json()["service_products"]}
        assert rows["freight"]["status"] == "mapped"
        assert rows["freight"]["wfirma_product_id"] == "WFP-99001"
        # insurance still unmapped
        assert rows["insurance"]["status"] == "unmapped"

    def test_both_mapped_both_show_mapped_status(self, client, monkeypatch, tmp_path):
        _seed_both(monkeypatch, tmp_path)
        r = client.get(self._PATH, headers=_auth_headers())
        for row in r.json()["service_products"]:
            assert row["status"] == "mapped", f"{row['charge_type']} should be mapped"

    def test_requires_auth_when_api_key_configured(self, client, monkeypatch, tmp_path):
        """Auth is enforced only when settings.api_key is non-empty; skip in dev mode."""
        if not settings.api_key:
            pytest.skip("api_key not configured — auth disabled in dev mode")
        _seed_unmapped(monkeypatch, tmp_path)
        r = client.get(self._PATH)
        assert r.status_code in (401, 403)


# ── Endpoint tests: PUT /api/v1/proforma/service-products/{charge_type} ───────

class TestPutServiceProduct:
    _BASE = "/api/v1/proforma/service-products"

    def _put(self, client, charge_type: str, payload: dict, operator="alice"):
        return client.put(
            f"{self._BASE}/{charge_type}",
            json=payload,
            headers=_auth_headers(operator),
        )

    def test_registers_freight_successfully(self, client, monkeypatch):
        # C-3g: PUT writes the mirror (identity) + pildb registry (metadata);
        # the legacy wfdb cache is not involved.
        r = self._put(client, "freight", {
            "wfirma_product_id": "12345",
            "product_name": "Fracht",
            "vat_rate": "23",
            "unit": "szt.",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["charge_type"] == "freight"
        assert body["wfirma_product_id"] == "12345"
        assert body["status"] == "mapped"

    def test_c1w1_registration_populates_mirror_not_master(self, client, tmp_path, monkeypatch):
        # C-1w1/C-3g: registering a service product writes the MIRROR
        # (code->wfirma_id sync identity) — but does NOT create a Product
        # Master row (service charges are not products; a master row would
        # pollute the product picker). C-3g retired the transitional cache
        # dual-write; metadata goes to pildb's service_product_registry.
        r = self._put(client, "freight",
                      {"wfirma_product_id": "77777", "product_name": "Fracht"})
        assert r.status_code == 200 and r.json()["wfirma_product_id"] == "77777"

        import sqlite3
        from app.services import reservation_db as _rdb
        db = tmp_path / "reservation_queue.db"
        con = sqlite3.connect(str(db)); con.row_factory = sqlite3.Row
        mrow = con.execute(
            "SELECT wfirma_id FROM wfirma_product_mirror WHERE product_code='freight'"
        ).fetchone()
        con.close()
        assert mrow is not None and mrow["wfirma_id"] == "77777", \
            "C-1w1: mirror must carry the freight->wfirma_id sync identity"
        assert _rdb.get_product_master(db, "freight") is None, \
            "C-1w1: a service charge must NOT create a Product Master row"

    def test_c1w1_wfirma_id_collision_returns_409(self, client, tmp_path, monkeypatch):
        # Two charge types cannot claim the same wfirma_id — the second is a 409,
        # not a silent 200 with an unwritten mirror (the divergence 1d would trip on).
        assert self._put(client, "freight",
                         {"wfirma_product_id": "SHARED"}).status_code == 200
        r2 = self._put(client, "insurance", {"wfirma_product_id": "SHARED"})
        assert r2.status_code == 409
        assert r2.json()["detail"]["error"] == "wfirma_id_collision"
        assert r2.json()["detail"]["owner_product_code"] == "freight"

    def test_registers_insurance_successfully(self, client, monkeypatch):
        r = self._put(client, "insurance", {"wfirma_product_id": "99999"})
        assert r.status_code == 200
        assert r.json()["charge_type"] == "insurance"

    def test_unknown_charge_type_returns_400(self, client, monkeypatch):
        r = self._put(client, "handling_fee", {"wfirma_product_id": "12345"})
        assert r.status_code == 400
        assert "not allowed" in r.json()["detail"]

    def test_empty_wfirma_product_id_returns_400(self, client, monkeypatch):
        r = self._put(client, "freight", {"wfirma_product_id": "   "})
        assert r.status_code == 400
        assert "wfirma_product_id" in r.json()["detail"]

    def test_charge_type_normalised_to_lowercase(self, client, monkeypatch):
        """PUT /service-products/FREIGHT (uppercased) must be accepted."""
        r = self._put(client, "FREIGHT", {"wfirma_product_id": "55555"})
        assert r.status_code == 200
        assert r.json()["charge_type"] == "freight"

    def test_operator_header_echoed_in_response(self, client, monkeypatch):
        r = self._put(client, "freight", {"wfirma_product_id": "777"},
                      operator="bob")
        assert r.json()["operator"] == "bob"

    def test_put_does_not_touch_legacy_wfdb_cache(self, client, monkeypatch):
        """C-3g regression: PUT must succeed with wfdb uninitialised and must
        never call wfdb.upsert_product (the dual-write is retired)."""
        monkeypatch.setattr(wfdb, "_db_path", None, raising=False)

        def _boom(*a, **kw):  # any cache write is a C-3g violation
            raise AssertionError("wfdb.upsert_product must not be called (C-3g)")

        monkeypatch.setattr(wfdb, "upsert_product", _boom)
        r = self._put(client, "freight", {"wfirma_product_id": "12345"})
        assert r.status_code == 200
        assert r.json()["status"] == "mapped"

    def test_requires_auth_when_api_key_configured(self, client, monkeypatch):
        """Auth is enforced only when settings.api_key is non-empty; skip in dev mode."""
        if not settings.api_key:
            pytest.skip("api_key not configured — auth disabled in dev mode")
        monkeypatch.setattr(wfdb, "_db_path", Path("/tmp/_phantom.db"), raising=False)
        r = client.put(
            f"{self._BASE}/freight",
            json={"wfirma_product_id": "12345"},
        )
        assert r.status_code in (401, 403)


# ── Integration: proforma XML includes service charge line ───────────────────

class TestServiceChargesInProformaXml:
    """
    Source-grep tests confirm the XML-level wiring from service-charge lines
    to the proforma document without invoking the full create flow.
    """

    def test_build_proforma_xml_includes_service_charge_line(self, monkeypatch):
        """
        If a ReservationLine with product_code='freight' is added to
        ProformaRequest.lines, _build_proforma_xml must emit a <good> block
        for it with the correct wfirma_good_id.
        """
        from app.services.wfirma_client import (
            ProformaRequest, ReservationLine, _build_proforma_xml,
        )
        req = ProformaRequest(
            client_name="ACME",
            client_zip="",
            client_city="",
            currency="EUR",
            wfirma_contractor_id="WFC-001",
            vat_code_id="VAT-23",
            lines=[
                ReservationLine(
                    product_code="RNG-100",
                    wfirma_good_id="WFG-100",
                    product_name="Ring",
                    qty=2.0,
                    unit_price=50.00,
                    unit="szt.",
                    currency="EUR",
                ),
                ReservationLine(
                    product_code="freight",
                    wfirma_good_id="WFP-99001",
                    product_name="Fracht",
                    qty=1.0,
                    unit_price=120.00,
                    unit="szt.",
                    currency="EUR",
                ),
            ],
        )
        xml = _build_proforma_xml(req)
        # wFirma XML references the good by <good><id>…</id></good> only —
        # the product name is resolved server-side from the wfirma_good_id.
        assert "WFP-99001" in xml, "Service charge good_id must appear in XML"

    def test_build_proforma_xml_excludes_service_charge_line_when_absent(self):
        """When no service charge lines are added, WFP-99001 must not appear."""
        from app.services.wfirma_client import (
            ProformaRequest, ReservationLine, _build_proforma_xml,
        )
        req = ProformaRequest(
            client_name="ACME",
            client_zip="",
            client_city="",
            currency="EUR",
            wfirma_contractor_id="WFC-001",
            vat_code_id="VAT-23",
            lines=[
                ReservationLine(
                    product_code="RNG-100",
                    wfirma_good_id="WFG-100",
                    product_name="Ring",
                    qty=2.0,
                    unit_price=50.00,
                    unit="szt.",
                    currency="EUR",
                ),
            ],
        )
        xml = _build_proforma_xml(req)
        assert "WFP-99001" not in xml

    def test_service_product_registry_source_grep_wires_into_build_lines(self):
        """Source-grep (C-3g): _build_service_charge_lines resolves identity
        from the mirror and metadata from the pildb registry — and never
        touches the retired wfdb cache. Also pins the C-1f defect fix: no
        dangling `prod.get` reference may survive (the removed assignment
        left a NameError on every mapped charge)."""
        import inspect
        from app.api.routes_proforma import _build_service_charge_lines
        src = inspect.getsource(_build_service_charge_lines)
        assert "_c1f_mirror_good_id" in src, (
            "_build_service_charge_lines must resolve wfirma_good_id from the "
            "Product MIRROR (identity authority)"
        )
        assert "get_all_service_product_meta" in src, (
            "_build_service_charge_lines must read emission metadata from the "
            "pildb service_product_registry (PROFORMA authority)"
        )
        assert "wfdb.get_product" not in src, (
            "C-3g: the legacy wfdb cache read is retired from "
            "_build_service_charge_lines"
        )
        assert "prod.get" not in src, (
            "C-1f regression: a dangling `prod.get(...)` here is the NameError "
            "that broke every mapped service-charge emission (fixed in C-3g)"
        )

    def test_build_service_charge_lines_respects_allowed_types(self):
        """Source-grep: only ALLOWED_SERVICE_CHARGE_TYPES are emitted."""
        import inspect
        from app.api.routes_proforma import _build_service_charge_lines
        src = inspect.getsource(_build_service_charge_lines)
        assert "ALLOWED_SERVICE_CHARGE_TYPES" in src, (
            "_build_service_charge_lines must gate on ALLOWED_SERVICE_CHARGE_TYPES"
        )

    def test_build_service_charge_lines_decimal_safe(self):
        """Source-grep: Decimal used for amount parsing (not float)."""
        import inspect
        from app.api.routes_proforma import _build_service_charge_lines
        src = inspect.getsource(_build_service_charge_lines)
        assert "Decimal" in src, (
            "_build_service_charge_lines must use Decimal for amount parsing"
        )
        assert "ROUND_HALF_EVEN" in src, (
            "_build_service_charge_lines must use ROUND_HALF_EVEN for rounding"
        )
