"""The outbound proforma page does not fetch inbound clearance (CT-MASTER W4).

The page carried an `ImportClearanceLogisticsPanel` that fired two extra
requests on every render of every proforma - the inbound import timeline and
the inbound clearance status - to draw the import workflow on the outbound
customer shipment page.

It could not draw it either. `audit.json` timeline events are shaped
`{ts, event, trigger_source, actor, detail}`; the panel looked for a timestamp
under `timestamp/time/at/t/date`, so all 3,142 recorded events rendered a dash
for their time, and `detail` is an object, which its value picker rejected.

Fixing the key would have produced a correct panel still on the wrong page, so
the panel is gone and the inbound authority is reached by a link. These are
source-grep pins: there is no bundler here, so the guarantee is about what the
served file contains.
"""
from __future__ import annotations

from pathlib import Path

import pytest


V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
PROFORMA_DETAIL = V2 / "proforma-detail.jsx"


@pytest.fixture(scope="module")
def source() -> str:
    assert PROFORMA_DETAIL.exists(), PROFORMA_DETAIL
    return PROFORMA_DETAIL.read_text(encoding="utf-8")


def test_outbound_page_does_not_fetch_the_inbound_timeline(source):
    assert "/api/v1/tracking/shipment/" not in source, (
        "the outbound proforma page is fetching the inbound import timeline again"
    )


def test_outbound_page_does_not_fetch_inbound_clearance_status(source):
    assert "/api/v1/dhl/clearance-status/" not in source, (
        "the outbound proforma page is fetching inbound clearance status again"
    )


def test_the_panel_and_its_orphaned_helper_are_gone(source):
    assert "ImportClearanceLogisticsPanel" not in source
    assert "_pfPickPrim" not in source


def test_inbound_authority_is_still_reachable_from_the_page(source):
    """Removing the panel must not remove the way to the workflow (Lesson M).

    Capability is relocated, not withdrawn, so no PROJECT_STATE cancellation
    record is owed - but the link has to actually be there.
    """
    assert "ImportClearanceLink" in source
    assert "pf-logistics-inbound-open-batch" in source
    assert "/v2/shipments?batch_id=" in source


def test_the_link_renders_nothing_without_a_batch(source):
    """A proforma with no import batch must not show a dead link."""
    start = source.index("function ImportClearanceLink({ batchId })")
    body = source[start:start + 2000]
    assert "if (!batchId) return null;" in body


def test_outbound_tracking_authority_is_untouched(source):
    """Only the inbound panel was removed. The outbound card is the page's job."""
    assert "function OutboundShipmentTracking(" in source
    assert "EJOutboundTrackingCard" in source
    assert "pf-logistics-outbound" in source
