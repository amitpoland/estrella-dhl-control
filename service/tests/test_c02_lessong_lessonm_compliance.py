"""test_c02_lessong_lessonm_compliance.py

Campaign 02 (Authority Consolidation) — B1 + B2 compliance pins.

B1 / Lesson G: every download endpoint serving a REGENERABLE artifact must
send ``Cache-Control: no-store, no-cache, must-revalidate, max-age=0`` so the
browser never serves a stale cached copy after a delete-and-regenerate cycle.
The 2026-06-12 platform audit found two non-compliant endpoints (confirmed by
adversarial verification at HEAD ff1f4b5):

  * routes_tracking_db.py  — SHIPMENT_TRACKING_MASTER.xlsx (regenerated in
    full on every export call)
  * routes_dsk.py          — DSK PDFs (versioned regeneration)

A third candidate (routes_dashboard.py email-attachment download) was REFUTED:
email attachments are permanent evidence files, not regenerable artifacts, so
browser caching there is correct and intentionally left unchanged.

B2 / Lesson M: every disabled operator-visible capability must display the
exact reason it is unavailable plus the next required action. The audit found
three disabled buttons in the V2 shell (v2/index.html) with no reason title:
Connect Carrier, Re-probe All, Export CSV. They stay visible + disabled and
now carry explanatory ``title`` attributes (five-state UI truth model:
backend-pending).
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "app"

_NO_STORE = '"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"'


# -- B1 / Lesson G: tracking master XLSX download --------------------------


def test_tracking_master_download_sets_no_store():
    src = (_APP / "api" / "routes_tracking_db.py").read_text(encoding="utf-8")
    idx = src.find("def download_master_xlsx(")
    assert idx >= 0, "download_master_xlsx endpoint missing"
    body = src[idx : idx + 1500]
    assert _NO_STORE in body, (
        "tracking master XLSX is a regenerable artifact - download must send "
        "Cache-Control: no-store (Lesson G)"
    )
    assert '"Pragma": "no-cache"' in body
    assert '"Expires": "0"' in body


# -- B1 / Lesson G: DSK PDF download ---------------------------------------


def test_dsk_download_sets_no_store():
    src = (_APP / "api" / "routes_dsk.py").read_text(encoding="utf-8")
    idx = src.find("async def download_dsk(")
    assert idx >= 0, "download_dsk endpoint missing"
    body = src[idx : idx + 1500]
    assert _NO_STORE in body, (
        "DSK PDFs are regenerable artifacts - download must send "
        "Cache-Control: no-store (Lesson G)"
    )
    assert '"Pragma": "no-cache"' in body
    assert '"Expires": "0"' in body


def test_dsk_download_keeps_content_disposition():
    """Adding cache headers must not drop the attachment disposition."""
    src = (_APP / "api" / "routes_dsk.py").read_text(encoding="utf-8")
    idx = src.find("async def download_dsk(")
    body = src[idx : idx + 1500]
    assert "Content-Disposition" in body


# -- B2 / Lesson M: disabled V2 shell buttons carry reason titles ----------


def _v2_index() -> str:
    return (_APP / "static" / "v2" / "index.html").read_text(encoding="utf-8")


def _button_line(src: str, label: str) -> str:
    for line in src.split("\n"):
        if label in line and "disabled" in line:
            return line
    raise AssertionError("disabled button %r not found in v2/index.html" % label)


def test_connect_carrier_button_has_disabled_reason():
    line = _button_line(_v2_index(), "+ Connect Carrier")
    assert 'title="Disabled:' in line, (
        "Lesson M: disabled Connect Carrier button must state the exact "
        "reason + next action in a title attribute"
    )
    assert "GAP-C10" in line, "reason must reference the backend gap register entry"


def test_reprobe_all_button_has_disabled_reason():
    line = _button_line(_v2_index(), "Re-probe All")
    assert 'title="Disabled:' in line, (
        "Lesson M: disabled Re-probe All button must state the exact "
        "reason + next action in a title attribute"
    )
    assert "Sprint 22" in line, "reason must reference the owning sprint"


def test_export_csv_button_has_disabled_reason():
    line = _button_line(_v2_index(), "⬇ Export CSV")
    assert 'title="Disabled:' in line, (
        "Lesson M: disabled Export CSV button must state the exact "
        "reason + next action in a title attribute"
    )
    assert "Sprint 04" in line, "reason must reference the owning sprint"


def test_disabled_buttons_remain_visible_not_removed():
    """Lesson M: compliance is achieved by ADDING reasons, never by removing
    the capability from the surface."""
    src = _v2_index()
    assert "+ Connect Carrier" in src
    assert "Re-probe All" in src
    assert "⬇ Export CSV" in src
