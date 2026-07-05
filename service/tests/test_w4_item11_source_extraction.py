"""
test_w4_item11_source_extraction.py — Wave 4 Item 11 (REUSE-ONLY).

The Source & Extraction advisory read endpoint
``GET /api/v1/proforma/draft/{id}/extraction`` composes, read-only, from
existing authorities (draft editable_lines + Customer Master + Product Master +
Import/Packing). Coverage:

  1. test_extraction_404_on_missing_draft
     — unknown draft id → HTTPException 404 (only hard failure allowed).
  2. test_extraction_advisory_shape_matched_and_unmatched
     — 2 lines: one whose product_code is in Product Master (matched, no unmatched
       flag) and one that is not (unmatched); per-row extraction confidence +
       manual-review pulled from the packing index; source document surfaced with
       a basename; customer_match present. Asserts unmatched_count==1 and — the
       Lesson N contract — the payload carries NO blocking key.
  3. test_extraction_never_500_when_packing_unavailable
     — packing reads raise → endpoint still returns ok=True with advisory nulls,
       never 500.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.api import routes_proforma


# ── helper ─────────────────────────────────────────────────────────────────────

def _make_mock_draft(editable_lines: List[Dict[str, Any]]) -> MagicMock:
    d = MagicMock()
    d.editable_lines_json   = json.dumps(editable_lines, ensure_ascii=False)
    d.source_lines_json     = "[]"
    d.service_charges_json  = "[]"
    d.buyer_override_json    = "{}"
    d.ship_to_override_json  = "{}"
    d.payment_terms_json     = "{}"
    d.remarks               = ""
    d.notes                 = ""
    d.exchange_rate         = None
    d.status                = "draft"
    d.id                    = 1
    d.batch_id              = "BATCH-001"
    d.client_name           = "SUOKKO"
    d.currency              = "EUR"
    d.draft_state           = "draft"
    d.draft_version         = 1
    d.wfirma_proforma_id    = ""
    d.wfirma_proforma_fullnumber = ""
    d.created_at            = "2026-01-01T00:00:00Z"
    d.updated_at            = "2026-01-01T00:00:00Z"
    d.last_packing_sync_at  = None
    d.packing_sync_warning  = None
    return d


# ── 1. 404 on missing draft ─────────────────────────────────────────────────────

def test_extraction_404_on_missing_draft():
    with patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=None), \
         patch.object(routes_proforma, "_proforma_db_path", return_value=Path("/tmp/x.db")):
        with pytest.raises(HTTPException) as ei:
            routes_proforma.get_proforma_draft_extraction(draft_id=999)
    assert ei.value.status_code == 404


# ── 2. advisory shape — matched + unmatched, no blocking ────────────────────────

def test_extraction_advisory_shape_matched_and_unmatched(tmp_path, monkeypatch):
    # Product Master exists and holds only EJL-RNG-417G → line 1 matched, line 2 not.
    monkeypatch.setattr(routes_proforma.settings, "storage_root", tmp_path)
    (tmp_path / "reservation_queue.db").write_text("")  # so rdb_path.exists() is True
    monkeypatch.setattr(
        "app.services.reservation_db.list_product_masters",
        lambda _p: [{"product_code": "EJL-RNG-417G", "item_type": "ring"}],
    )

    mock_draft = _make_mock_draft([
        {"product_code": "EJL-RNG-417G", "qty": 1.0, "unit_price": 145.0,
         "name_pl": "Pierścionek", "currency": "EUR"},
        {"product_code": "EJL-PND-ROSE", "qty": 2.0, "unit_price": 89.5,
         "name_pl": "Wisiorek", "currency": "EUR"},
    ])

    packing_lines = [
        {"product_code": "EJL-RNG-417G", "design_no": "D001", "quantity": 1.0,
         "extracted_confidence": 0.92, "requires_manual_review": 0},
        {"product_code": "EJL-PND-ROSE", "design_no": "D002", "quantity": 2.0,
         "extracted_confidence": 0.40, "requires_manual_review": 1},
    ]
    packing_docs = [
        {"id": "pd-1", "source_file_path": r"C:\store\uploads\packing_apr.xlsx",
         "invoice_no": "INV-001", "parser_name": "ejl_sales",
         "extraction_status": "extracted", "created_at": "2026-01-01T00:00:00Z"},
    ]

    with patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=mock_draft), \
         patch.object(routes_proforma, "_proforma_db_path", return_value=Path("/tmp/x.db")), \
         patch.object(routes_proforma, "_resolve_customer",
                      return_value={"found": True, "ambiguous": False,
                                    "match_strategy": "customer_master",
                                    "resolved_wfirma_name": "Suokko Oy",
                                    "candidates": []}), \
         patch.object(routes_proforma, "_enrich_customer_resolution_with_email",
                      lambda cr: None), \
         patch.object(routes_proforma.pdb, "get_packing_lines_for_batch",
                      return_value=packing_lines), \
         patch.object(routes_proforma.pdb, "get_packing_documents_for_batch",
                      return_value=packing_docs):
        resp = routes_proforma.get_proforma_draft_extraction(draft_id=1)

    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["advisory"] is True
    # Advisory contract (Lesson N): nothing here is a fiscal gate.
    assert "blocking_reasons" not in body
    assert "blockers" not in body

    assert body["unmatched_count"] == 1
    assert body["customer_unmatched"] is False

    lines = {ln["product_code"]: ln for ln in body["lines"]}
    ring = lines["EJL-RNG-417G"]
    pend = lines["EJL-PND-ROSE"]
    assert ring["product_matched"] is True and ring["unmatched"] is False
    assert ring["extracted_confidence"] == 0.92
    assert ring["requires_manual_review"] is False
    assert pend["product_matched"] is False and pend["unmatched"] is True
    assert pend["requires_manual_review"] is True

    # Source document surfaced with a computed basename (no full path leak).
    assert len(body["source_documents"]) == 1
    assert body["source_documents"][0]["file_name"] == "packing_apr.xlsx"


# ── 3. never 500 when packing authority unavailable ─────────────────────────────

def test_extraction_never_500_when_packing_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_proforma.settings, "storage_root", tmp_path)

    mock_draft = _make_mock_draft([
        {"product_code": "EJL-RNG-417G", "qty": 1.0, "unit_price": 145.0, "currency": "EUR"},
    ])

    def _boom(*a, **k):
        raise RuntimeError("packing.db offline")

    with patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=mock_draft), \
         patch.object(routes_proforma, "_proforma_db_path", return_value=Path("/tmp/x.db")), \
         patch.object(routes_proforma, "_resolve_customer",
                      return_value={"found": False, "ambiguous": False,
                                    "match_strategy": "none", "candidates": []}), \
         patch.object(routes_proforma, "_enrich_customer_resolution_with_email",
                      lambda cr: None), \
         patch.object(routes_proforma.pdb, "get_packing_lines_for_batch", side_effect=_boom), \
         patch.object(routes_proforma.pdb, "get_packing_documents_for_batch", side_effect=_boom):
        resp = routes_proforma.get_proforma_draft_extraction(draft_id=1)

    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["advisory"] is True
    assert len(body["lines"]) == 1
    # Packing offline → confidence degrades to null, still advisory, never blocks.
    assert body["lines"][0]["extracted_confidence"] is None
    assert body["source_documents"] == []
    assert body["customer_unmatched"] is True
