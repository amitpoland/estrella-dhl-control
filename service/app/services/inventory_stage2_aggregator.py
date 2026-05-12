"""
Inventory Stage 2 read-only aggregator.

Surfaces a 5-bucket summary over existing inventory_state data:
  - final_stock  (count_by_state()['WAREHOUSE_STOCK']) — derivable
  - samples      (count_by_state()['SAMPLE_OUT'])      — derivable (Phase B.1)
  - returns      → null + limitation (no source)
  - consignment  → null + limitation (no source)
  - unknown      → null + limitation (Path A: strict residual undefined)

Phase B.1 activated the SAMPLE_OUT lifecycle state. This aggregator now
counts pieces in inventory_state.state='SAMPLE_OUT' for the samples
tile, mirroring the WAREHOUSE_STOCK derivation used for final_stock.
Returns + consignment still have no backing state or table — they stay
null and surface a limitation.

Failure isolation: if count_by_state() raises (e.g. warehouse_db not
initialised), BOTH final_stock and samples are downgraded to count=null
with limitations, the response top-level status becomes "degraded",
and the endpoint still returns 200. The function NEVER raises.

A separate degrade path exists for the unusual case where the
count_by_state() result dict succeeds but does not contain the
SAMPLE_OUT key (e.g. a test/mock returning a partial dict). In that
case samples degrades alone with a targeted limitation; final_stock
is unaffected.

Read-only invariants:
  - No INSERT / UPDATE / DELETE
  - No .add() / .commit() / .flush()
  - Single call to count_by_state() (which itself runs one SELECT)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import inventory_state_engine


SAMPLES_BASIS_LIVE     = "inventory_state.state = 'SAMPLE_OUT'"
RETURNS_BASIS          = "not_available — no return state or returns table"
CONSIGNMENT_BASIS      = "not_available — no consignment state or table"
UNKNOWN_BASIS          = (
    "not_available — strict residual requires returns/consignment "
    "counts which are null"
)

# Phase B.1 retired the old "samples: SAMPLE_OUT not in STATES" claim.
# Samples is now derivable; only the degrade paths add a limitation.
SAMPLES_LIMITATION_MISSING_KEY = (
    "samples: SAMPLE_OUT state missing from count_by_state result — "
    "count_by_state() returned a dict without the SAMPLE_OUT key"
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
    "returns − consignment) is undefined while returns/consignment "
    "are null"
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

    # ── Single state-count read; feeds final_stock + samples. ─────────────
    final_stock_count = None
    final_stock_basis = ""
    samples_count     = None
    samples_basis     = ""

    try:
        state_counts = inventory_state_engine.count_by_state()
    except Exception as e:  # warehouse_db not initialised, SQL error, etc.
        final_stock_basis = f"source unavailable — {type(e).__name__}"
        samples_basis     = f"source unavailable — {type(e).__name__}"
        limitations.append(
            f"final_stock: count_by_state() raised {type(e).__name__} "
            f"— source unavailable"
        )
        limitations.append(
            f"samples: count_by_state() raised {type(e).__name__} "
            f"— source unavailable"
        )
        status = "degraded"
    else:
        final_stock_count = int(state_counts.get("WAREHOUSE_STOCK", 0))
        final_stock_basis = "inventory_state.state = 'WAREHOUSE_STOCK'"
        if "SAMPLE_OUT" in state_counts:
            samples_count = int(state_counts["SAMPLE_OUT"])
            samples_basis = SAMPLES_BASIS_LIVE
        else:
            # Partial/mock dict missing the key — degrade samples only.
            samples_basis = "not_available — SAMPLE_OUT key missing from source"
            limitations.append(SAMPLES_LIMITATION_MISSING_KEY)
            status = "degraded"

    # ── returns / consignment / unknown: still null today ─────────────────
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
                "count": samples_count,
                "basis": samples_basis,
                "confidence": "HIGH" if samples_count is not None else "NONE",
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
