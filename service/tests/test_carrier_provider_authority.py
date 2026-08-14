"""Carrier provider is owned by carrier_shipments — one authority, no UI default.

Guards the Slice A consolidation: the provider is persisted on the shipment row,
a legacy NULL is interpreted in exactly one place, and no consumer invents DHL.
"""
from pathlib import Path

import pytest

from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentResult,
    ShipmentState,
)
from app.services.carrier.persistence import shipment_db


def _result(key: str) -> ShipmentResult:
    return ShipmentResult(
        idempotency_key=key,
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING,
    )


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "carrier_shipments.db"
    shipment_db.init_db(p)
    return p


def test_legacy_null_provider_resolves_to_dhl():
    """Rows booked before the column existed came from the DHL-only adapter."""
    assert shipment_db.resolve_provider(None) == "DHL"
    assert shipment_db.resolve_provider("") == "DHL"
    assert shipment_db.resolve_provider("   ") == "DHL"


def test_stored_provider_is_normalised_not_defaulted():
    assert shipment_db.resolve_provider("fedex") == "FEDEX"
    assert shipment_db.resolve_provider(" ups ") == "UPS"


def test_provider_defaults_to_dhl_for_existing_callers(db: Path):
    """Callers that predate the provider kwarg keep working unchanged."""
    shipment_db.insert_shipment(db, _result("k-legacy"), "B1")
    assert shipment_db.get_shipment(db, "k-legacy")["provider"] == "DHL"


def test_customer_arranged_provider_round_trips(db: Path):
    shipment_db.insert_shipment(db, _result("k-ups"), "B2", provider="UPS")
    assert shipment_db.get_shipment(db, "k-ups")["provider"] == "UPS"


def test_unknown_provider_is_rejected(db: Path):
    with pytest.raises(ValueError, match="Unknown carrier provider"):
        shipment_db.insert_shipment(db, _result("k-bad"), "B3", provider="TNT")


def test_null_provider_row_reads_back_as_dhl(db: Path):
    """A row written before the migration (provider IS NULL) still reads DHL."""
    shipment_db.insert_shipment(db, _result("k-null"), "B4")
    with shipment_db._connect(db) as conn:
        conn.execute(
            "UPDATE carrier_shipments SET provider = NULL WHERE idempotency_key = ?",
            ("k-null",),
        )
    row = shipment_db.get_shipment(db, "k-null")
    assert row["provider"] == "DHL"


def test_migration_is_idempotent(db: Path):
    """init_db re-runs on an existing DB without raising (additive pattern)."""
    shipment_db.insert_shipment(db, _result("k-keep"), "B5", provider="FEDEX")
    shipment_db.init_db(db)
    shipment_db.init_db(db)
    assert shipment_db.get_shipment(db, "k-keep")["provider"] == "FEDEX"


def test_shipment_api_does_not_hardcode_carrier():
    """The GET projection must read the stored provider, not a literal."""
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "api" / "routes_carrier_actions.py"
    ).read_text(encoding="utf-8")
    assert '"carrier": row.get("provider")' in src
    assert '"carrier": "DHL"' not in src


def test_v2_projection_has_no_dhl_fallback():
    """proforma-detail.jsx must not re-invent a carrier the backend didn't send."""
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "static" / "v2" / "proforma-detail.jsx"
    ).read_text(encoding="utf-8")
    assert "ship.carrier || 'DHL'" not in src
    assert "carrierShipment.carrier || 'DHL'" not in src
    assert "(carrierShipment && carrierShipment.carrier) || 'DHL'" not in src
    assert "|| 'DHL'" not in src


def test_canonical_cmr_consumes_persisted_provider_from_transport():
    """One surviving CMR renderer reads carrier from the single _transport projection."""
    root = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
    detail = (root / "proforma-detail.jsx").read_text(encoding="utf-8")
    cmr = (root / "estrella-doc-cmr.jsx").read_text(encoding="utf-8")
    index = (root / "index.html").read_text(encoding="utf-8")

    assert 'src="estrella-doc-cmr.jsx"' in index
    assert "name:        _transport.carrier" in detail
    assert "carrier:  _transport.linked" in detail
    assert "EJCMRCarrierChip" in cmr
    assert "|| 'DHL'" not in cmr
    assert '|| "DHL"' not in cmr
    assert "function EJCMRClassic" in cmr
    assert "function EJCMRModern" in cmr
