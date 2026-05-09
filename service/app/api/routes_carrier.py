"""
routes_carrier.py — Read-only HTTP endpoints for the outbound carrier
shipment registry and label store.

DL-C scope
----------
* GET-only endpoints. No POST, PUT, PATCH, DELETE in this file.
* No adapter usage. No DHL stub usage. No live carrier calls.
* No seed data. The registry and label store are populated by the
  coordinator (DL-D), not by these routes.

Endpoints
---------
  GET /api/v1/carrier/shipments
  GET /api/v1/carrier/shipments/{shipment_id}
  GET /api/v1/carrier/shipments/by-batch/{batch_id}
  GET /api/v1/carrier/shipments/{shipment_id}/transitions
  GET /api/v1/carrier/labels/{sha256}

Security and defensive behaviour
--------------------------------
* The label download accepts only a 64-character lowercase hex string;
  any other shape returns 400. This makes the path-traversal class of
  attacks structurally impossible — ``..`` and ``/`` cannot pass the
  hex test.
* After resolving a sha256 to a file via the label store, the route
  re-checks that the resolved absolute path is contained inside the
  attachments root; a symlink or other escape attempt returns 404.
* Empty list responses are explicit ``{"shipments": [], "count": 0}``
  rather than a bare empty array, matching the convention used by
  routes_tracking_db and routes_action_proposals.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..services.carrier import carrier_label_store as cls
from ..services.carrier import carrier_shipment_db as csdb
from ..services.carrier.carrier_state_engine import STATES as CARRIER_STATES

router = APIRouter(prefix="/api/v1/carrier", tags=["carrier"])

# 64 lowercase hex chars — anchored, no metacharacters allowed.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Mime / Content-Type by file extension. Anything unknown gets the
# generic octet-stream so nothing surprising lands in the browser.
_LABEL_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".zpl": "text/plain",
    ".png": "image/png",
}


# ── 1. List all shipments ───────────────────────────────────────────────────

@router.get("/shipments")
def list_shipments(
    state:  Optional[str] = Query(default=None,
                                   description="Filter to one carrier state"),
    limit:  int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Paginated list of shipments, optionally filtered by state.

    Empty result returns ``{"shipments": [], "count": 0}`` and HTTP 200.
    Unknown ``state`` returns HTTP 400.
    """
    if state is not None and state not in CARRIER_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown carrier state {state!r}",
        )
    rows = csdb.list_all(state=state, limit=limit, offset=offset)
    return {
        "shipments": rows,
        "count":     len(rows),
        "limit":     limit,
        "offset":    offset,
        "state":     state,
    }


# ── 2. Single shipment by id ────────────────────────────────────────────────

@router.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str):
    """Return the registry row for *shipment_id*, 404 if unknown."""
    row = csdb.get_by_id(shipment_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"carrier shipment {shipment_id!r} not found",
        )
    return row


# ── 3. Shipments by batch ───────────────────────────────────────────────────

@router.get("/shipments/by-batch/{batch_id}")
def list_shipments_for_batch(batch_id: str):
    """All carrier shipments associated with a parent PZ batch.

    Returns ``{"shipments": [], "count": 0}`` when no shipments are
    linked to the batch (whether the batch itself exists is not the
    carrier's responsibility — checking that here would couple this
    layer to the batch_manager).
    """
    rows = csdb.get_by_batch(batch_id)
    return {
        "batch_id":  batch_id,
        "shipments": rows,
        "count":     len(rows),
    }


# ── 4. Transition history ───────────────────────────────────────────────────

@router.get("/shipments/{shipment_id}/transitions")
def get_shipment_transitions(shipment_id: str):
    """Append-only transition history for *shipment_id*.

    Returns 404 if the shipment itself does not exist (so the caller
    cannot use this endpoint to enumerate shipment ids).
    """
    if csdb.get_by_id(shipment_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"carrier shipment {shipment_id!r} not found",
        )
    transitions = csdb.get_transitions(shipment_id)
    return {
        "shipment_id": shipment_id,
        "count":       len(transitions),
        "transitions": transitions,
    }


# ── 5. Label download by sha256 ─────────────────────────────────────────────

@router.get("/labels/{sha256}")
def download_label(sha256: str):
    """Stream a label artefact identified by its sha256 hash.

    Defensive layers:
      1. *sha256* must match ``^[0-9a-f]{64}$`` — any other shape
         returns 400. ``..`` / ``/`` cannot pass this test.
      2. The label store resolves the sha to a file under
         ``_attachments/<sha>[.<ext>]`` only.
      3. The resolved absolute path must be contained in the
         attachments root (defense in depth against symlinks).
      4. Content-Type is inferred from the file extension and falls
         back to ``application/octet-stream`` for anything unknown.
    """
    sha = (sha256 or "").lower().strip()
    if not _SHA256_RE.fullmatch(sha):
        raise HTTPException(
            status_code=400,
            detail="sha256 must be 64 lowercase hex chars",
        )

    file_path: Optional[Path] = cls.get_attachment_path(sha)
    if file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail="label not found")

    # Defense-in-depth: ensure the resolved file lives in the
    # attachments root, not somewhere else via symlink.
    attach_root = cls.attachment_root()
    try:
        file_path.resolve().relative_to(attach_root)
    except ValueError:
        # Resolved path escapes the attachments dir — refuse.
        raise HTTPException(status_code=404, detail="label not found")

    suffix = file_path.suffix.lower()
    content_type = _LABEL_CONTENT_TYPES.get(suffix, "application/octet-stream")
    data = file_path.read_bytes()
    return Response(
        content     = data,
        media_type  = content_type,
        headers     = {
            "Content-Length":           str(len(data)),
            "Content-Disposition":      f'inline; filename="{sha}{suffix}"',
            "X-Carrier-Label-SHA256":   sha,
        },
    )
