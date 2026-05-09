"""
routes_carrier_proposals.py — Read-only HTTP endpoints surfacing the
output of the carrier proposal builder.

DL-D3 scope
-----------
* GET-only endpoints. Lives in a separate file from routes_carrier.py
  so the source-grep proof on that file (no write decorators, no
  adapter import) stays intact.
* No mutation paths.
* No service-orchestration or carrier-adapter references.
* No proposal-action endpoints — those will land in DL-D4.
* The route file is a thin HTTP wrapper over the proposal builder and
  applies a deterministic sort to the builder's output (rule 19).

Endpoints
---------
  GET /api/v1/carrier/proposals
  GET /api/v1/carrier/proposals/by-batch/{batch_id}

Response shape (always)
-----------------------
  { "proposals": list[dict], "count": int }

Sorting (deterministic, rule 19)
--------------------------------
  severity (info → warning → blocked) → action → awb-or-batch → title
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter

from ..core.config import settings
from ..services.carrier import carrier_proposal_builder as pb

router = APIRouter(prefix="/api/v1/carrier/proposals", tags=["carrier"])


# ── Helpers ─────────────────────────────────────────────────────────────────

# Stable severity rank — info first (immediately actionable), then
# warning (escalated but still actionable), then blocked (informational).
_SEVERITY_ORDER: Dict[str, int] = {
    "info":    0,
    "warning": 1,
    "blocked": 2,
}


def _carrier_db_path() -> Path:
    """Same path that ``main.py`` initialises in lifespan and that
    ``routes_carrier.py`` reads through the singleton.

    Resolved fresh on every call so a test that monkey-patches
    ``settings.storage_root`` is honoured without re-importing the
    module.
    """
    return Path(settings.storage_root) / "carrier_shipments.db"


def _sort_key(p: Dict[str, Any]) -> Tuple[int, str, str, str]:
    """Deterministic sort key — covered by rule 19.

    Tertiary key is awb-or-batch_id-or-empty, never None, so
    ``sorted`` cannot raise on heterogeneous nullability between
    create-shipment proposals (which have batch_id, no awb) and
    per-shipment proposals (which have awb, possibly no batch_id).
    """
    severity = p.get("severity", "")
    action   = p.get("action", "")
    ident    = p.get("awb") or p.get("batch_id") or ""
    title    = p.get("title", "")
    return (
        _SEVERITY_ORDER.get(severity, 99),
        action,
        ident,
        title,
    )


def _envelope(proposals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pin the response shape exactly once."""
    return {
        "proposals": proposals,
        "count":     len(proposals),
    }


# ── 1. GET /api/v1/carrier/proposals ────────────────────────────────────────

@router.get("")
def list_all_open_proposals():
    """Return every per-shipment proposal across the registry.

    Empty registry returns ``{"proposals": [], "count": 0}`` and
    HTTP 200 — never 404. Per rule 16.
    """
    proposals = pb.build_all_open_proposals(_carrier_db_path())
    proposals.sort(key=_sort_key)
    return _envelope(proposals)


# ── 2. GET /api/v1/carrier/proposals/by-batch/{batch_id} ────────────────────

@router.get("/by-batch/{batch_id}")
def list_proposals_for_batch(batch_id: str):
    """All open proposals for a single PZ batch.

    Always emits at least the create-shipment proposal (the builder
    is the source of truth on whether it's enabled). Empty / unknown
    batches return a list with the create-shipment proposal in
    ``info`` state — never 404.
    """
    proposals = pb.build_proposals_for_batch(_carrier_db_path(), batch_id)
    proposals.sort(key=_sort_key)
    return _envelope(proposals)
