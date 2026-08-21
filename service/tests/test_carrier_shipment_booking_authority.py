"""A completed booking outranks a newer shadow reservation for the same leg.

Production incident (batch SHIPMENT_6696117050_2026-08_100ab076, client
"SAGAR SHAH"): the live AWB 4323685634 was booked into a PENDING row created
2026-08-18, because the coordinator's in-flight recovery re-executes an existing
row rather than inserting a new one. A shadow reservation created 2026-08-20 was
therefore NEWER, and ``ORDER BY created_at DESC`` handed every consumer the
shadow row. The live AWB vanished from Logistics, Documents, readiness and the
CMR/insurance projections at once, while the booking itself was perfectly fine.

The selector is shared, so these tests pin the ranking rule once, at the
persistence boundary that all of those consumers read through.

All tests use tmp_path. No production paths. No live calls.
"""
from __future__ import annotations

import sqlite3

from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentResult,
    ShipmentState,
)
from app.services.carrier.persistence.shipment_db import (
    get_shipment_for_draft,
    init_db,
    insert_shipment,
    list_outbound_rows_for_batches,
    update_state,
)

BATCH = "SHIPMENT_6696117050_2026-08_100ab076"
CLIENT = "SAGAR SHAH"
LIVE_AWB = "4323685634"


def _db(tmp_path):
    path = tmp_path / "carrier_shipments.db"
    init_db(path)
    return path


def _pending(key: str) -> ShipmentResult:
    return ShipmentResult(
        idempotency_key=key,
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING,
        simulated=True,
    )


def _stamp(db, key: str, created_at: str) -> None:
    """Pin created_at explicitly.

    The scenario is entirely about relative age, and rows inserted in the same
    millisecond would make the ordering ambiguous rather than wrong. Setting the
    timestamps reproduces the real sequence instead of racing the clock.
    """
    con = sqlite3.connect(str(db))
    con.execute(
        "UPDATE carrier_shipments SET created_at = ? WHERE idempotency_key = ?",
        (created_at, key),
    )
    con.commit()
    con.close()


def _set_direction(db, key: str, direction: str) -> None:
    con = sqlite3.connect(str(db))
    con.execute(
        "UPDATE carrier_shipments SET shipment_direction = ? "
        "WHERE idempotency_key = ?",
        (direction, key),
    )
    con.commit()
    con.close()


def _seed_production_shape(tmp_path):
    """The exact row set the incident produced, ages included."""
    db = _db(tmp_path)

    # Booked 2026-08-18, later completed live in place by in-flight recovery.
    insert_shipment(db, _pending("live-key"), BATCH, CLIENT)
    _stamp(db, "live-key", "2026-08-18T10:44:25.093Z")
    update_state(
        db, "live-key", ShipmentState.COMPLETE,
        tracking_ref=LIVE_AWB, mode=ShipmentMode.LIVE, simulated=False,
    )

    # A shadow reservation created two days LATER for the same leg.
    insert_shipment(db, _pending("shadow-new"), BATCH, CLIENT)
    _stamp(db, "shadow-new", "2026-08-20T02:29:18.342Z")
    return db


def test_completed_booking_beats_a_newer_shadow_row(tmp_path):
    db = _seed_production_shape(tmp_path)
    row = get_shipment_for_draft(db, BATCH, CLIENT)
    assert row is not None
    assert row["tracking_ref"] == LIVE_AWB
    assert row["state"] == ShipmentState.COMPLETE.value
    assert row["simulated"] in (0, False)


def test_the_newer_shadow_row_is_still_present_as_audit_evidence(tmp_path):
    """Ranking must not be implemented by deleting or hiding the loser."""
    db = _seed_production_shape(tmp_path)
    con = sqlite3.connect(str(db))
    keys = {r[0] for r in con.execute(
        "SELECT idempotency_key FROM carrier_shipments")}
    con.close()
    assert keys == {"live-key", "shadow-new"}


def test_a_real_booking_outranks_a_simulated_completed_one(tmp_path):
    db = _db(tmp_path)
    insert_shipment(db, _pending("sim"), BATCH, CLIENT)
    _stamp(db, "sim", "2026-08-20T00:00:00.000Z")
    update_state(db, "sim", ShipmentState.COMPLETE, tracking_ref="SIMULATED-1")

    insert_shipment(db, _pending("real"), BATCH, CLIENT)
    _stamp(db, "real", "2026-08-18T00:00:00.000Z")
    update_state(
        db, "real", ShipmentState.COMPLETE,
        tracking_ref=LIVE_AWB, mode=ShipmentMode.LIVE, simulated=False,
    )

    assert get_shipment_for_draft(db, BATCH, CLIENT)["tracking_ref"] == LIVE_AWB


def test_without_a_completed_booking_the_newest_row_still_wins(tmp_path):
    """The previous behaviour is preserved wherever it was never wrong."""
    db = _db(tmp_path)
    insert_shipment(db, _pending("older"), BATCH, CLIENT)
    _stamp(db, "older", "2026-08-18T00:00:00.000Z")
    insert_shipment(db, _pending("newer"), BATCH, CLIENT)
    _stamp(db, "newer", "2026-08-20T00:00:00.000Z")

    assert get_shipment_for_draft(db, BATCH, CLIENT)["idempotency_key"] == "newer"


def test_a_completed_booking_without_a_tracking_ref_is_not_a_booking(tmp_path):
    """COMPLETE alone is not authority — the AWB is what makes it a booking."""
    db = _db(tmp_path)
    insert_shipment(db, _pending("complete-no-awb"), BATCH, CLIENT)
    _stamp(db, "complete-no-awb", "2026-08-18T00:00:00.000Z")
    update_state(db, "complete-no-awb", ShipmentState.COMPLETE)

    insert_shipment(db, _pending("newer-shadow"), BATCH, CLIENT)
    _stamp(db, "newer-shadow", "2026-08-20T00:00:00.000Z")

    row = get_shipment_for_draft(db, BATCH, CLIENT)
    assert row["idempotency_key"] == "newer-shadow"


def test_another_clients_live_booking_is_never_returned(tmp_path):
    """Ranking must not weaken the 2026-07-16 cross-client scope guarantee."""
    db = _db(tmp_path)
    insert_shipment(db, _pending("other-live"), BATCH, "DG GmbH")
    _stamp(db, "other-live", "2026-08-18T00:00:00.000Z")
    update_state(
        db, "other-live", ShipmentState.COMPLETE,
        tracking_ref="9999999999", mode=ShipmentMode.LIVE, simulated=False,
    )
    insert_shipment(db, _pending("ours"), BATCH, CLIENT)
    _stamp(db, "ours", "2026-08-20T00:00:00.000Z")

    row = get_shipment_for_draft(db, BATCH, CLIENT)
    assert row["idempotency_key"] == "ours"
    assert row["tracking_ref"] in (None, "")


def test_a_return_leg_never_satisfies_an_outbound_query(tmp_path):
    """A return booking outranks nothing — it is a different direction."""
    db = _db(tmp_path)
    insert_shipment(db, _pending("return-live"), BATCH, CLIENT)
    _stamp(db, "return-live", "2026-08-18T00:00:00.000Z")
    update_state(
        db, "return-live", ShipmentState.COMPLETE,
        tracking_ref="7777777777", mode=ShipmentMode.LIVE, simulated=False,
    )
    _set_direction(db, "return-live", "return")

    insert_shipment(db, _pending("outbound-shadow"), BATCH, CLIENT)
    _stamp(db, "outbound-shadow", "2026-08-20T00:00:00.000Z")

    row = get_shipment_for_draft(db, BATCH, CLIENT)
    assert row["idempotency_key"] == "outbound-shadow"
    assert row["tracking_ref"] in (None, "")


def test_the_bulk_projection_names_the_same_shipment_as_the_per_draft_one(tmp_path):
    """Pro Forma search takes the FIRST row per leg from the bulk query.

    If the two orderings disagreed, one page would show the AWB and another
    would not -- the same class of split truth this ranking exists to end.
    """
    db = _seed_production_shape(tmp_path)
    rows = [r for r in list_outbound_rows_for_batches(db, [BATCH])
            if (r.get("client_ref") or "") == CLIENT]
    assert rows, "bulk projection returned no rows for the leg"
    assert rows[0]["tracking_ref"] == LIVE_AWB
    assert rows[0]["idempotency_key"] == get_shipment_for_draft(
        db, BATCH, CLIENT)["idempotency_key"]
