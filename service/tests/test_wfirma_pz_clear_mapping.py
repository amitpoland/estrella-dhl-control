"""wFirma PZ mapping clear (2026-05-22).

After an operator manually deletes a PZ document in the wFirma admin UI
(or otherwise cancels it), the local audit still holds the old
`wfirma_pz_doc_id`. That linkage blocks `/pz_create` from issuing a new
document for the same batch. This test suite pins the new
`/wfirma/pz/clear-mapping` endpoint behavior:

  - Operator-explicit: refuses without X-Operator header.
  - Idempotent: returns `already_cleared` when no doc id is set.
  - Only clears the four post-create fields; preserves the rest of
    `wfirma_export`.
  - Logs a timeline event.
  - Does NOT attempt to delete the PZ in wFirma (no client wrapper).
"""
from __future__ import annotations

from pathlib import Path


ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_wfirma.py"
)


def _route_body():
    return ROUTES.read_text(encoding="utf-8")


def test_clear_mapping_endpoint_registered():
    body = _route_body()
    assert '@router.post("/shipment/{batch_id}/wfirma/pz/clear-mapping"' in body


def test_clear_mapping_requires_x_operator_header():
    body = _route_body()
    chunk = body[body.find("wfirma_pz_clear_mapping"):]
    end = chunk.find("@router", 1)
    if end > 0:
        chunk = chunk[:end]
    assert "OPERATOR_HEADER_MISSING" in chunk
    assert "X-Operator header is required" in chunk


def test_clear_mapping_returns_already_cleared_when_no_doc_id():
    body = _route_body()
    chunk = body[body.find("wfirma_pz_clear_mapping"):]
    end = chunk.find("@router", 1)
    if end > 0:
        chunk = chunk[:end]
    assert '"already_cleared"' in chunk


def test_clear_mapping_strips_exactly_four_post_create_fields():
    body = _route_body()
    chunk = body[body.find("wfirma_pz_clear_mapping"):]
    end = chunk.find("@router", 1)
    if end > 0:
        chunk = chunk[:end]
    # The four post-create fields the endpoint must pop.
    for key in ("wfirma_pz_doc_id", "wfirma_pz_fullnumber",
                "pz_source", "pz_created_at"):
        assert f'"{key}"' in chunk, f"{key} should be in the clear list"


def test_clear_mapping_logs_timeline_event():
    body = _route_body()
    assert "EV_WFIRMA_PZ_MAPPING_CLEARED" in body
    assert '"wfirma_pz_mapping_cleared"' in body


def test_clear_mapping_never_calls_wfirma_client_to_delete_pz():
    body = _route_body()
    chunk = body[body.find("wfirma_pz_clear_mapping"):]
    end = chunk.find("@router", 1)
    if end > 0:
        chunk = chunk[:end]
    # NO wfirma_client call inside this endpoint — clear-mapping is
    # local-audit-only. The PZ deletion must be done by the operator in
    # the wFirma admin UI.
    assert "wfirma_client" not in chunk


def test_clear_mapping_returns_previous_doc_id():
    body = _route_body()
    chunk = body[body.find("wfirma_pz_clear_mapping"):]
    end = chunk.find("@router", 1)
    if end > 0:
        chunk = chunk[:end]
    assert '"previous_wfirma_pz_doc_id"' in chunk
    assert '"previous_pz_source"' in chunk
