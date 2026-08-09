"""
test_v2_shipments_front_parity.py
=================================
V2 Shipments front/list page — B1 operational parity + duplicate-authority cleanup.

Pins:
  - uploaded_at projection from audit.inputs
  - newest-first list_date sort (uploaded_at → timestamp → pz_generated_at)
  - missing dates sort last
  - Visa Date / Visa Generated Date have no authority → em-dash only
  - filters / Active-Archived / CSV / actions use canonical dashboard endpoints
  - no View Detail duplicate; Open in New Tab → V2 detail deep-link
  - atlas/shipments-v2.html redirects to /v2/shipments
  - detail page business file untouched by this campaign's mutation surface
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

os.environ.setdefault("API_KEY", "test-key")

from app.api import routes_dashboard as rd  # noqa: E402

_V2 = _SVC / "app" / "static" / "v2"
_DASH = _V2 / "dashboard-page.jsx"
_INDEX = _V2 / "index.html"
_PZ_API = _V2 / "pz-api.js"
_DETAIL = _V2 / "shipment-detail-page.jsx"
_ATLAS = _SVC / "app" / "static" / "atlas" / "shipments-v2.html"


def _src() -> str:
    return _DASH.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    return "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("//")
    )


def _audit(batch_id="SHIPMENT_123_2026-05_abc", generated_at=None, **extra):
    a = {
        "batch_id": batch_id,
        "status": "success",
        "doc_no": "PZ/001/2026",
        "totals": {"net": 100.0, "gross": 123.0, "duty": 5.0},
        "inputs": {},
    }
    if generated_at is not None:
        a["pz_output"] = {"pdf": "pz.pdf", "xlsx": "pz.xlsx", "generated_at": generated_at}
    a.update(extra)
    return a


# ── Backend projection ──────────────────────────────────────────────────────


class TestUploadedAtProjection:

    def test_uploaded_at_from_inputs(self):
        a = _audit(inputs={"uploaded_at": "2026-08-01T10:00:00+02:00"})
        s = rd._batch_summary(a, "d")
        assert s["uploaded_at"] == "2026-08-01T10:00:00+02:00"

    def test_missing_uploaded_at_is_none(self):
        s = rd._batch_summary(_audit(), "d")
        assert s["uploaded_at"] is None

    def test_blank_uploaded_at_is_none(self):
        s = rd._batch_summary(_audit(inputs={"uploaded_at": "   "}), "d")
        assert s["uploaded_at"] is None

    def test_no_visa_fields_invented(self):
        s = rd._batch_summary(_audit(), "d")
        assert "visa_date" not in s
        assert "visa_generated_date" not in s
        assert "visa_generated_at" not in s


# ── Frontend sort / dates / columns ─────────────────────────────────────────


class TestNewestFirstSort:

    def test_default_sort_is_list_date_desc(self):
        code = _code_only(_src())
        assert "React.useState('list_date')" in code
        assert "React.useState('desc')" in code

    def test_list_date_prefers_uploaded_then_timestamp_then_pz(self):
        code = _code_only(_src())
        assert "row.uploaded_at || row.timestamp || row.pz_generated_at" in code

    def test_missing_dates_sort_last_before_direction_flip(self):
        code = _code_only(_src())
        null_check = code.index("if (av === null")
        dir_flip = code.index("sortDir === 'asc' ? r : -r")
        assert null_check < dir_flip

    def test_pagination_slices_after_sort(self):
        code = _code_only(_src())
        assert "sorted.slice(pageStart, pageEnd)" in code
        assert "PAGE_SIZE = 25" in code


class TestDateColumns:

    def test_upload_date_column_present(self):
        assert "Upload Date" in _src()

    def test_visa_columns_are_honest_gaps(self):
        code = _code_only(_src())
        assert "No Visa Date authority in shipment list" in code
        assert "No Visa Generated Date authority in shipment list" in code
        # Must not bind invented backend fields
        assert "row.visa" not in code
        assert "visa_date" not in code
        assert "visa_generated" not in code

    def test_date_formatter_ddmmyyyy(self):
        assert "${m[3]}.${m[2]}.${m[1]}" in _code_only(_src())


class TestFiltersAndOpsCards:

    def test_status_filters_include_b1_set(self):
        src = _src()
        for label in ("Ready for PZ", "Awaiting DHL", "Awaiting SAD",
                      "Action Required", "Ready for Booking", "Exported"):
            assert label in src

    def test_active_archived_toggle(self):
        src = _src()
        assert 'data-testid="shipments-hub-view-active"' in src
        assert 'data-testid="shipments-hub-view-archived"' in src

    def test_ops_cards_present(self):
        src = _src()
        assert 'data-testid="warehouse-operations-card"' in src
        assert 'data-testid="sales-accounting-operations-card"' in src
        assert 'data-testid="dhl-customs-operations-card"' in src

    def test_kpi_labels(self):
        src = _src()
        for label in ("Total Shipments", "Awaiting DHL", "Awaiting SAD",
                      "Ready for PZ", "Action Required", "Ready for Booking",
                      "Total Duty A00", "Total Gross Value"):
            assert label in src

    def test_csv_export_control(self):
        assert 'data-testid="shipments-hub-csv-export"' in _src()


class TestActionsCanonical:

    def test_view_present_view_detail_absent(self):
        code = _code_only(_src())
        assert "View" in code
        assert "View Detail" not in code

    def test_open_new_tab_uses_v2_detail_deeplink(self):
        code = _code_only(_src())
        assert "/v2/shipments?batch_id=" in code
        assert "batch.html" not in code

    def test_recheck_uses_canonical_endpoint(self):
        code = _code_only(_src())
        assert "/api/v1/dashboard/batches/" in code
        assert "recheck" in code
        assert "{ mode: 'all' }" in code or "mode: 'all'" in code

    def test_archive_uses_delete_batches(self):
        code = _code_only(_src())
        assert "method: 'DELETE'" in code
        assert "archived by user" in code

    def test_no_duplicate_kpi_status_calculator_module(self):
        """Predicates live once in this page (namespaced), not a second JS authority file."""
        assert (_V2 / "shipments-kpi.js").exists() is False
        assert (_V2 / "shipments-status.js").exists() is False


class TestPzApiCanonicalMutations:

    def test_pz_api_exposes_list_and_mutations(self):
        src = _PZ_API.read_text(encoding="utf-8")
        for name in ("listBatches", "listArchived", "recheckBatch",
                     "archiveBatch", "restoreBatch", "permanentlyDeleteArchived"):
            assert f"{name}:" in src or f"{name} :" in src, f"PzApi missing {name}"

    def test_recheck_batch_distinct_from_recheck_sad(self):
        src = _PZ_API.read_text(encoding="utf-8")
        assert "recheckBatch:" in src
        assert "recheckSad:" in src
        assert "mode: 'all'" in src
        assert "mode: 'sad'" in src


class TestDetailRoutingUnchangedAuthority:

    def test_index_deeplink_opens_existing_detail_page(self):
        idx = _INDEX.read_text(encoding="utf-8")
        assert "shipmentDetailUrl" in idx
        assert "ShipmentDetailPage" in idx
        assert "batch_id" in idx
        assert "handleViewShipment" in idx

    def test_detail_page_still_fetches_full_audit(self):
        detail = _DETAIL.read_text(encoding="utf-8")
        assert "/api/v1/dashboard/batches/" in detail
        assert "function ShipmentDetailPage" in detail

    def test_atlas_duplicate_redirects_to_v2(self):
        atlas = _ATLAS.read_text(encoding="utf-8")
        assert "/v2/shipments" in atlas
        assert "location.replace" in atlas
        assert "useBatches" not in atlas
