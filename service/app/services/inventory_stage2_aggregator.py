"""
Inventory Stage 2 read-only aggregator.

Surfaces a 5-bucket summary over existing inventory_state data:
  - final_stock  (count_by_state()['WAREHOUSE_STOCK'])  — derivable
  - samples      → null + limitation (no source)
  - returns      → null + limitation (no source)
  - consignment  → null + limitation (no source)
  - unknown      → null + limitation (Path A: strict residual undefined)

Failure isolation: if count_by_state() raises (e.g. warehouse_db not
initialised), final_stock is downgraded to count=null with a limitation,
the response top-level status becomes "degraded", and the endpoint
still returns 200. The function NEVER raises.

Read-only invariants:
  - No INSERT / UPDATE / DELETE
  - No .add() / .commit() / .flush()
  - Single call to count_by_state() (which itself runs one SELECT)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import inventory_state_engine


SAMPLES_BASIS     = "not_available — no sample-out state or table"
RETURNS_BASIS     = "not_available — no return state or returns table"
CONSIGNMENT_BASIS = "not_available — no consignment state or table"
UNKNOWN_BASIS     = (
    "not_available — strict residual requires samples/returns/"
    "consignment counts which are null"
)

SAMPLES_LIMITATION = (
    "samples: no dedicated state (SAMPLE_OUT not in "
    "inventory_state_engine.STATES) and no sample_releases table — "
    "cannot distinguish sample releases from direct dispatches"
)
RETURNS_LIMITATION = (
    "returns: no return state (no RETURNED_FROM_CLIENT or "
    "RETURNED_TO_PRODUCER in inventory_state_engine.STATES) and no "
    "returns table — cannot count returned units"
)
CONSIGNMENT_LIMITATION = (
    "consignment: no consignment state (no CONSIGNMENT in "
    "inventory_state_engine.STATES) and no consignment_* table — "
    "cannot count consigned units"
)
UNKNOWN_LIMITATION = (
    "unknown: strict residual (total Stage 2 − final − samples − "
    "returns − consignment) is undefined while samples/returns/"
    "consignment are null"
)


def aggregate_stage2(as_of: Optional[str] = None) -> dict:
    """
    Read-only Stage 2 aggregation. Returns response payload.
    Never raises. Per-category failures are isolated.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    as_of_iso = as_of or now_iso

    limitations: list = []
    status = "ok"

    # ── final_stock: only derivable category ──────────────────────────────
    final_stock_count = None
    final_stock_basis = ""
    try:
        state_counts = inventory_state_engine.count_by_state()
        final_stock_count = int(state_counts.get("WAREHOUSE_STOCK", 0))
        final_stock_basis = "inventory_state.state = 'WAREHOUSE_STOCK'"
    except Exception as e:  # warehouse_db not initialised, SQL error, etc.
        final_stock_count = None
        final_stock_basis = f"source unavailable — {type(e).__name__}"
        limitations.append(
            f"final_stock: count_by_state() raised {type(e).__name__} "
            f"— source unavailable"
        )
        status = "degraded"

    # ── samples / returns / consignment / unknown: always null today ──────
    limitations.append(SAMPLES_LIMITATION)
    limitations.append(RETURNS_LIMITATION)
    limitations.append(CONSIGNMENT_LIMITATION)
    limitations.append(UNKNOWN_LIMITATION)

    return {
        "status": status,
        "generated_at": now_iso,
        "as_of": as_of_iso,
        "source": {
            "warehouse": "inventory_state_engine.count_by_state",
            "packing": "not_used",
            "lifecycle": "inventory_state.state",
        },
        "stage2": {
            "final_stock": {
                "count": final_stock_count,
                "basis": final_stock_basis,
                "confidence": "HIGH" if final_stock_count is not None else "NONE",
            },
            "samples": {
                "count": None,
                "basis": SAMPLES_BASIS,
                "confidence": "NONE",
            },
            "returns": {
                "count": None,
                "basis": RETURNS_BASIS,
                "confidence": "NONE",
            },
            "consignment": {
                "count": None,
                "basis": CONSIGNMENT_BASIS,
                "confidence": "NONE",
            },
            "unknown": {
                "count": None,
                "basis": UNKNOWN_BASIS,
                "confidence": "NONE",
            },
        },
        "limitations": limitations,
    }
