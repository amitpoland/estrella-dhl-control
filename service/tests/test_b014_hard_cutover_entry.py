"""B-014 HARD CUTOVER — V1 Shipment Detail Sales/Pro Forma → V2.

Pins that normal canonical entry routes to /v2/proforma?batch_id= and that
ProformaDraftPanel source is retained (not deleted). No routes_proforma /
permission / financial-authority changes in this campaign.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_V1 = _ROOT / "app" / "static" / "shipment-detail.html"
_V2_SHIP = _ROOT / "app" / "static" / "v2" / "shipment-detail-page.jsx"
_ROUTES = _ROOT / "app" / "api" / "routes_proforma.py"


def _v1() -> str:
    return _V1.read_text(encoding="utf-8")


class TestHardCutoverSalesEntry:
    def test_sales_tab_mounts_cutover_gate_not_panel(self):
        src = _v1()
        # Render branch (not the useEffect that also mentions Sales)
        start = src.index("{activeTab === 'Sales' && (")
        end = src.index("{activeTab === 'PZ / Accounting' && (", start)
        sales = src[start:end]
        assert "SalesProformaV2CutoverGate" in sales
        assert "<ProformaDraftPanel" not in sales
        assert 'data-testid="sales-tab-proforma-cutover-gate"' in src
        assert 'data-testid="sales-tab-proforma-v2-entry"' in src

    def test_cutover_href_is_v2_proforma_batch_id(self):
        src = _v1()
        gate_start = src.index("function SalesProformaV2CutoverGate(")
        gate = src[gate_start: gate_start + 1800]
        assert "/v2/proforma?batch_id=" in gate
        assert "window.location.assign" in gate
        assert "encodeURIComponent(batchId)" in gate

    def test_panel_source_retained_not_deleted(self):
        src = _v1()
        assert "function ProformaDraftPanel(" in src
        assert "YES_REOPEN_LOCAL_PROFORMA_DRAFT" in src  # recovery code still present

    def test_no_classic_escape_affordance(self):
        src = _v1()
        gate_start = src.index("function SalesProformaV2CutoverGate(")
        gate = src[gate_start: gate_start + 2500]
        assert "Classic" not in gate
        assert "classic panel" not in gate.lower() or "rollback" in gate.lower()


class TestHardCutoverOverviewPills:
    def test_wfirma_proforma_pill_navigates_to_v2(self):
        src = _v1()
        # Find the Overview pill button block
        assert 'data-testid="pipeline-summary-wfirma-pill"' in src
        idx = src.index('data-testid="pipeline-summary-wfirma-pill"')
        window = src[idx: idx + 600]
        assert 'data-nav-target="/v2/proforma"' in window
        assert 'data-proforma-cutover="v2"' in window
        assert "setActiveTab('PZ / Accounting')" not in window

    def test_sales_pill_navigates_to_v2(self):
        src = _v1()
        idx = src.index('data-testid="pipeline-summary-sales-pill"')
        window = src[idx: idx + 700]
        assert 'data-nav-target="/v2/proforma"' in window
        assert "/v2/proforma?batch_id=" in window


class TestV2ShipmentProformaCtaUnchanged:
    def test_v2_shipment_still_opens_v2_hub(self):
        src = _V2_SHIP.read_text(encoding="utf-8")
        assert "/v2/proforma?batch_id=" in src
        assert 'data-testid="proforma-tab-open"' in src


class TestNoFinancialAuthorityDrift:
    def test_routes_proforma_unchanged_in_this_campaign(self):
        """Cutover is frontend navigation only — routes file must not be in the
        working tree as a modified sibling of this pin's intent. Content
        presence check: privileged write deps still named on key endpoints."""
        src = _ROUTES.read_text(encoding="utf-8")
        assert 'dependencies=[_auth_write]' in src
        assert '/draft/{draft_id}/approve' in src
        assert '/draft/{draft_id}/re-open' in src
        assert 'reset-from-sales-packing' in src
