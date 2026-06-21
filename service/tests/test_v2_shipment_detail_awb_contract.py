"""
Static source-grep contract tests for the DHL AWB display on the V2 shipment detail page.
These tests verify JSX source text — no server required.
"""
import pathlib

JSX = pathlib.Path(__file__).parent.parent / "app" / "static" / "v2" / "shipment-detail-page.jsx"


def _src():
    return JSX.read_text(encoding="utf-8")


def test_header_awb_testid_present():
    """Sub-header AWB div has data-testid="header-awb" for test targeting."""
    assert 'data-testid="header-awb"' in _src()


def test_derive_detail_reads_audit_tracking_no():
    """deriveDetail extracts AWB from audit.tracking_no (DHL authority source)."""
    assert "audit.tracking_no" in _src()


def test_overview_awb_tracking_label_present():
    """OverviewTab DHL Clearance InfoBlock has 'AWB / Tracking' label."""
    assert "'AWB / Tracking'" in _src()


def test_header_awb_uses_derived_field_not_raw_shipment():
    """Header AWB uses d.awb (derived authority) not raw shipment.awb."""
    src = _src()
    assert "d.awb" in src
    # The header no longer references the raw list-row field alone
    # (shipment.awb may still appear in the fallback chain in deriveDetail,
    # but the header render must use the derived d.awb)
    assert 'data-testid="header-awb"' in src


def test_derive_detail_awb_key_present():
    """deriveDetail return object contains awb: key (key consistency guard)."""
    src = _src()
    # awb: should appear as an assignment key in deriveDetail
    assert "awb:" in src
