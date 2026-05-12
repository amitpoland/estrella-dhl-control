"""
proforma_pz_recovery.py — recovery helper for retroactive PZ creation from
an existing proforma snapshot.

RECOVERY WORKAROUND ONLY.  Not part of the normal PZ creation path.

See build_pz_request_from_proforma_snapshot docstring for the full warning.
Kept in its own module so proforma_to_invoice.py remains a pure builder
with no dependency on wfirma_client.
"""
from __future__ import annotations

from datetime import date as _date
from typing import TYPE_CHECKING

from .wfirma_client import PZLine, PZRequest

if TYPE_CHECKING:
    from .proforma_to_invoice import ProformaSnapshot


def build_pz_request_from_proforma_snapshot(
    snap: ProformaSnapshot,
    warehouse_id: str,
) -> PZRequest:
    """
    RECOVERY WORKAROUND ONLY — not the normal PZ creation path.

    Use this only when a PZ must be created retroactively from a proforma that
    already exists in wFirma (e.g. stock pre-fill before final invoice conversion
    when the import calculation PZ was not created first).

    Normal path: import_pz_builder.build_pz_request_from_batch() using
    unit_netto_pln (landed import cost) from pz_import_processor output.

    WARNING: This function uses the proforma's line.price (sales price) as the
    PZ cost basis, which is architecturally incorrect for permanent use. The two
    prices must not be conflated — see docs/wfirma.skill.md §7c.

    Aggregates all LineItems by good_id (sum unit_count). If the same good_id
    appears with different prices, raises ValueError — ambiguous cost basis.

    Returns a PZRequest ready for create_warehouse_pz().
    """
    agg_count: dict = {}    # good_id -> float
    agg_price: dict = {}    # good_id -> float (must be consistent)

    for line in snap.contents:
        gid = line.good_id
        if not gid:
            continue
        try:
            qty = float(line.unit_count)
            price = float(line.price)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"non-numeric unit_count/price for good_id={gid!r}: {exc}"
            ) from exc

        if gid in agg_price and abs(agg_price[gid] - price) > 1e-6:
            raise ValueError(
                f"good_id={gid!r} appears with conflicting prices "
                f"{agg_price[gid]:.4f} and {price:.4f} — cannot build PZ"
            )

        agg_count[gid] = agg_count.get(gid, 0.0) + qty
        agg_price[gid] = price

    if not agg_count:
        raise ValueError("no lines with valid good_id in snapshot")

    today = _date.today().isoformat()

    lines = [
        PZLine(good_id=gid, count=agg_count[gid], price=agg_price[gid])
        for gid in agg_count
    ]

    return PZRequest(
        contractor_id=snap.contractor_id,
        warehouse_id=warehouse_id,
        date=today,
        description=f"PZ pre-fill for {snap.proforma_number}",
        lines=lines,
    )
