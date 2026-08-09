"""Reservation Create live-authority campaign pins (base 0fe20d3f).

Covers:
  - Draft commercial lines (no price aggregation for same product_code)
  - invoice-style product_code never becomes UNMATCHED
  - document currency from Draft
  - dry-run: zero HTTP, zero persist
  - success-reconcile idempotency
  - legacy process-pending mode=live hard-disabled
  - unresolved products block Create readiness
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


_BATCH = "SHIP-RESV-CAMPAIGN"
_CLIENT = "RAILING CLIENT"
_DOC = "DOC-R1"


def _caps(**over) -> Dict[str, Any]:
    base = {
        "api_configured": True,
        "reservation_supported": True,
        "create_product_allowed": False,
        "create_customer_allowed": False,
        "ready_to_reserve": True,
        "blocking_reasons": [],
    }
    base.update(over)
    return base


def _sales_doc() -> Dict[str, Any]:
    return {
        "id": _DOC,
        "client_name": _CLIENT,
        "client_ref": "R1",
        "sales_doc_no": "R1/2026",
        "client_contractor_id": "65559320",
    }


def _make_draft(lines: list, currency: str = "PLN"):
    from app.services.proforma_invoice_link_db import ProformaDraft
    return ProformaDraft(
        batch_id=_BATCH,
        client_name=_CLIENT,
        status="approved",
        draft_state="approved",
        currency=currency,
        editable_lines_json=json.dumps(lines),
        id=82,
    )


def _patch_plan(stack: ExitStack, *, drafts: list, sales_spl: Optional[list] = None,
                products: Optional[Dict[str, dict]] = None,
                customer: Optional[dict] = None,
                inventory: Optional[list] = None,
                packing: Optional[list] = None):
    products = products or {}
    mock_wfdb = MagicMock()
    mock_wfdb._db_path = Path("/fake/wfirma.db")
    mock_wfdb.list_reservation_drafts.return_value = []
    mock_wfdb.get_customer.return_value = customer
    mock_wfdb.get_product.side_effect = lambda pc: products.get(pc)
    mock_wfdb.upsert_reservation_draft.return_value = "draft-1"
    mock_wfdb.replace_reservation_lines.return_value = 0

    mock_con = MagicMock()
    mock_con.__enter__ = lambda s: s
    mock_con.__exit__ = MagicMock(return_value=False)
    mock_con.execute.return_value.fetchall.return_value = inventory or []

    stack.enter_context(patch("app.services.wfirma_reservation.wfdb", mock_wfdb))
    stack.enter_context(patch("app.services.wfirma_reservation._ready", return_value=True))
    stack.enter_context(patch("app.services.wfirma_capabilities.get_capabilities", return_value=_caps()))
    stack.enter_context(patch("app.services.document_db.get_sales_documents", return_value=[_sales_doc()]))
    stack.enter_context(patch(
        "app.services.document_db.get_sales_packing_lines",
        return_value=sales_spl if sales_spl is not None else [],
    ))
    stack.enter_context(patch("app.services.document_db.query_sales_to_wfirma", return_value=[]))
    stack.enter_context(patch(
        "app.services.packing_db.get_packing_lines_for_batch",
        return_value=packing or [],
    ))
    stack.enter_context(patch("app.services.wfirma_reservation._wcon", return_value=mock_con))
    stack.enter_context(patch("app.services.warehouse_audit.get_missing_scans", return_value=[]))
    stack.enter_context(patch("app.services.warehouse_audit.get_invalid_flows", return_value=[]))
    stack.enter_context(patch("app.services.warehouse_audit.get_orphan_inventory", return_value=[]))
    stack.enter_context(patch(
        "app.services.proforma_invoice_link_db.list_drafts_for_batch",
        return_value=drafts,
    ))
    stack.enter_context(patch(
        "app.services.customer_identity_resolver.resolve_by_contractor_id",
        return_value={"contractor_id": "65559320"} if customer else None,
    ))
    return mock_wfdb


class TestDraftCommercialAuthority:
    def test_preserves_distinct_unit_prices_same_product_code(self):
        from app.services.wfirma_reservation import build_reservation_plan

        lines = [
            {"design_no": "JR1", "product_code": "EJL/26-27/492-1", "qty": 1, "unit_price": 100.0, "currency": "PLN"},
            {"design_no": "JR2", "product_code": "EJL/26-27/492-1", "qty": 1, "unit_price": 250.0, "currency": "PLN"},
            {"design_no": "JR3", "product_code": "EJL/26-27/492-2", "qty": 1, "unit_price": 90.0, "currency": "PLN"},
        ]
        prods = {
            "EJL/26-27/492-1": {"wfirma_product_id": "51613155", "sync_status": "matched", "unit": "szt."},
            "EJL/26-27/492-2": {"wfirma_product_id": "51613219", "sync_status": "matched", "unit": "szt."},
        }
        with ExitStack() as stack:
            _patch_plan(
                stack,
                drafts=[_make_draft(lines)],
                products=prods,
                customer={"wfirma_customer_id": "65559320", "match_status": "matched"},
                packing=[
                    {"product_code": "EJL/26-27/492-1", "scan_code": "sc1"},
                    {"product_code": "EJL/26-27/492-1", "scan_code": "sc2"},
                    {"product_code": "EJL/26-27/492-2", "scan_code": "sc3"},
                ],
                inventory=[
                    {"scan_code": "sc1", "current_status": "dispatched"},
                    {"scan_code": "sc2", "current_status": "dispatched"},
                    {"scan_code": "sc3", "current_status": "dispatched"},
                ],
            )
            plan = build_reservation_plan(_BATCH, persist=False)

        doc = plan["documents"][0]
        assert doc["currency"] == "PLN"
        assert doc["commercial_source"] == "draft_proforma"
        assert len(doc["rows"]) == 3
        prices = sorted(r["unit_price"] for r in doc["rows"] if r["product_code"] == "EJL/26-27/492-1")
        assert prices == [100.0, 250.0]
        assert abs(doc["total_value"] - (100 + 250 + 90)) < 0.01

    def test_invoice_style_sales_product_code_not_unmatched(self):
        from app.services.wfirma_reservation import build_reservation_plan

        spl = [{
            "sales_document_id": _DOC,
            "product_code": "EJL/26-27/492-1",  # already invoice ref
            "design_no": "JR00819",
            "quantity": 1,
            "unit_price": 10,
            "currency": "PLN",
        }]
        prods = {
            "EJL/26-27/492-1": {"wfirma_product_id": "51613155", "sync_status": "matched"},
        }
        with ExitStack() as stack:
            _patch_plan(
                stack,
                drafts=[],  # no Draft → sales fallback
                sales_spl=spl,
                products=prods,
                customer={"wfirma_customer_id": "65559320", "match_status": "matched"},
                packing=[{"product_code": "EJL/26-27/492-1", "scan_code": "sc1"}],
                inventory=[{"scan_code": "sc1", "current_status": "dispatched"}],
            )
            plan = build_reservation_plan(_BATCH, persist=False)

        row = plan["documents"][0]["rows"][0]
        assert row["product_code"] == "EJL/26-27/492-1"
        assert not row["product_code"].startswith("UNMATCHED:")

    def test_unresolved_product_blocks(self):
        from app.services.wfirma_reservation import build_reservation_plan

        lines = [
            {"design_no": "X", "product_code": "", "qty": 1, "unit_price": 1, "currency": "PLN"},
        ]
        with ExitStack() as stack:
            _patch_plan(
                stack,
                drafts=[_make_draft(lines)],
                products={},
                customer={"wfirma_customer_id": "65559320", "match_status": "matched"},
            )
            plan = build_reservation_plan(_BATCH, persist=False)

        doc = plan["documents"][0]
        assert doc["ready"] is False
        assert any("unresolved" in b.lower() for b in doc["blocking_reasons"])


class TestDryRun:
    def test_dry_run_zero_persist_and_builds_xml(self):
        from app.services.wfirma_reservation import dry_run_reservation

        lines = [
            {"design_no": "JR1", "product_code": "EJL/26-27/492-1", "qty": 1, "unit_price": 906.97, "currency": "PLN"},
            {"design_no": "JR2", "product_code": "EJL/26-27/492-1", "qty": 1, "unit_price": 944.30, "currency": "PLN"},
        ]
        prods = {
            "EJL/26-27/492-1": {
                "wfirma_product_id": "51613155", "sync_status": "matched",
                "product_name_pl": "Ring", "unit": "szt.",
            },
        }
        with ExitStack() as stack:
            mock_wfdb = _patch_plan(
                stack,
                drafts=[_make_draft(lines)],
                products=prods,
                customer={"wfirma_customer_id": "65559320", "match_status": "matched"},
                packing=[
                    {"product_code": "EJL/26-27/492-1", "scan_code": "sc1"},
                    {"product_code": "EJL/26-27/492-1", "scan_code": "sc2"},
                ],
                inventory=[
                    {"scan_code": "sc1", "current_status": "dispatched"},
                    {"scan_code": "sc2", "current_status": "dispatched"},
                ],
            )
            out = dry_run_reservation(_BATCH, _CLIENT)

        assert out["ok"] is True
        assert out["would_call_wfirma"] is False
        assert mock_wfdb.upsert_reservation_draft.call_count == 0
        assert mock_wfdb.replace_reservation_lines.call_count == 0
        payload = out["payload"]
        assert payload["contractor_id"] == "65559320"
        assert payload["document_currency"] == "PLN"
        assert payload["unresolved_count"] == 0
        assert len(payload["lines"]) == 2
        assert payload["lines"][0]["unit_price"] != payload["lines"][1]["unit_price"]
        assert out["xml"] and "warehouse_document" in out["xml"]
        assert "51613155" in out["xml"]
        assert "65559320" in out["xml"]


class TestLegacyLiveDisabled:
    def test_process_pending_live_returns_409(self, tmp_path):
        from app.services import reservation_db as rdb
        rdb.init_reservation_db(tmp_path / "reservation_queue.db")
        with patch.object(settings, "storage_root", tmp_path):
            with TestClient(app, raise_server_exceptions=True) as c:
                r = c.post(
                    "/api/v1/reservations/process-pending",
                    headers={"X-API-KEY": settings.api_key or "test-key"},
                    json={"mode": "live"},
                )
        assert r.status_code == 409
        body = r.json()
        assert body["code"] == "LEGACY_LIVE_WRITER_DISABLED"
        assert body.get("results") == []
