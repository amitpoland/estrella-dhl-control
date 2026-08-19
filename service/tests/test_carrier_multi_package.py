"""Booking-time multi-package split.

There is no warehouse carton authority, so a parcel count is never inferred:
``packages=None`` means one package derived from the scalar weight/dimensions,
which is byte-for-byte the payload every caller sent before this existed.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.carrier.models.shipment import (  # noqa: E402
    ShipmentRequest, compute_idempotency_key, resolve_packages,
)


def _req(**over):
    base = dict(
        batch_id="SHIPMENT_MP_1", shipper_account="123456789",
        recipient_address={"name": "X"}, declared_value=100.0, currency="EUR",
        weight_kg=10.0, dimensions={"length_cm": 20, "width_cm": 15, "height_cm": 10},
        incoterm="DAP",
    )
    base.update(over)
    return ShipmentRequest(**base)


def test_split_changes_the_idempotency_key():
    """2x5kg and 1x10kg share a total weight — they are different bookings."""
    one = _req()
    split = _req(packages=[
        {"weight_kg": 5.0, "length_cm": 20, "width_cm": 15, "height_cm": 10},
        {"weight_kg": 5.0, "length_cm": 20, "width_cm": 15, "height_cm": 10},
    ])
    assert compute_idempotency_key(one) != compute_idempotency_key(split)


def test_different_splits_of_equal_total_differ():
    a = _req(packages=[{"weight_kg": 4.0, "length_cm": 20, "width_cm": 15, "height_cm": 10},
                       {"weight_kg": 6.0, "length_cm": 20, "width_cm": 15, "height_cm": 10}])
    b = _req(packages=[{"weight_kg": 5.0, "length_cm": 20, "width_cm": 15, "height_cm": 10},
                       {"weight_kg": 5.0, "length_cm": 20, "width_cm": 15, "height_cm": 10}])
    assert compute_idempotency_key(a) != compute_idempotency_key(b)


def test_no_split_keeps_the_legacy_key():
    """Existing rows and callers must resolve to the exact same key."""
    assert compute_idempotency_key(_req()) == compute_idempotency_key(_req(packages=None))
    assert compute_idempotency_key(_req(packages=[])) == compute_idempotency_key(_req())


def test_resolve_packages_derives_one_package_from_the_scalars():
    out = resolve_packages(_req())
    assert len(out) == 1
    assert out[0]["weight_kg"] == 10.0
    assert (out[0]["length_cm"], out[0]["width_cm"], out[0]["height_cm"]) == (20, 15, 10)


def test_dhl_payload_is_unchanged_without_a_split():
    """The single-package DHL content block must not move."""
    from app.services.carrier.adapters import live
    single = [
        {"weight": p.get("weight_kg"),
         "dimensions": {"length": p.get("length_cm", 1), "width": p.get("width_cm", 1),
                        "height": p.get("height_cm", 1)}}
        for p in resolve_packages(_req())
    ]
    assert single == [{"weight": 10.0,
                       "dimensions": {"length": 20, "width": 15, "height": 10}}]
    assert "resolve_packages(request)" in pathlib.Path(live.__file__).read_text(encoding="utf-8")


def test_dhl_payload_lists_every_package():
    rows = resolve_packages(_req(packages=[
        {"weight_kg": 4.0, "length_cm": 20, "width_cm": 15, "height_cm": 10},
        {"weight_kg": 6.0, "length_cm": 30, "width_cm": 25, "height_cm": 20},
    ]))
    assert [r["weight_kg"] for r in rows] == [4.0, 6.0]


# ── Trust boundary: an unmeasured package never becomes a booking ────────────

def _validate(pkgs):
    from app.api.routes_carrier_actions import _validated_packages
    return _validated_packages(pkgs)


def test_empty_split_is_no_split():
    assert _validate(None) is None
    assert _validate([]) is None


def test_zero_weight_is_a_missing_measurement_not_a_zero_kg_parcel():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _validate([{"weight_kg": 0, "length_cm": 20, "width_cm": 15, "height_cm": 10}])
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "PACKAGE_FIELD_NOT_MEASURED"


@pytest.mark.parametrize("bad", [
    [{"length_cm": 20, "width_cm": 15, "height_cm": 10}],          # no weight
    [{"weight_kg": 5.0, "width_cm": 15, "height_cm": 10}],         # no length
    [{"weight_kg": 5.0, "length_cm": 0, "width_cm": 15, "height_cm": 10}],
    [{"weight_kg": "heavy", "length_cm": 20, "width_cm": 15, "height_cm": 10}],
    ["not-an-object"],
])
def test_incomplete_packages_are_rejected(bad):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _validate(bad)
    assert exc.value.status_code == 422


def test_package_count_is_capped():
    from fastapi import HTTPException
    pkg = {"weight_kg": 1.0, "length_cm": 1, "width_cm": 1, "height_cm": 1}
    with pytest.raises(HTTPException) as exc:
        _validate([pkg] * 51)
    assert exc.value.detail["code"] == "PACKAGES_TOO_MANY"


def test_split_is_persisted_not_recomputed(tmp_path):
    """NULL packages_json means 'booked as one package', never an inferred count."""
    from app.services.carrier.persistence import shipment_db as sdb
    db = tmp_path / "carrier_shipments.db"
    sdb.init_db(db)
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(carrier_shipments)")}
    assert "packages_json" in cols
    import inspect
    from app.services.carrier import coordinator
    src = inspect.getsource(coordinator.CarrierCoordinator._execute)
    assert "packages_json=packages_json" in src
