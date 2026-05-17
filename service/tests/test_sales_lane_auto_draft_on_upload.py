"""test_sales_lane_auto_draft_on_upload.py — 2026-05-17.

Source-grep guards confirming the sales-side auto-draft hook is wired
into both the purchase upload path AND the reprocess path inside
routes_packing.py. The actual sales upload route (routes_intake.py)
already invokes _auto_create_draft_for_client per sales block.
"""
from __future__ import annotations

from pathlib import Path

import pytest


ROUTES_PACKING = (
    Path(__file__).resolve().parents[1] / "app" / "api" / "routes_packing.py"
)
ROUTES_INTAKE = (
    Path(__file__).resolve().parents[1] / "app" / "api" / "routes_intake.py"
)


def test_routes_packing_imports_sync_draft_from_packing_upload():
    """sync_draft_from_packing_upload must be imported in routes_packing —
    both purchase upload (existing) and reprocess (new) call it."""
    src = ROUTES_PACKING.read_text(encoding="utf-8")
    assert src.count("sync_draft_from_packing_upload") >= 3, (
        "sync_draft_from_packing_upload must appear in routes_packing.py "
        "at least 3 times (upload, link-as-sales, reprocess)"
    )


def test_routes_intake_sales_block_calls_auto_create_draft():
    """Sales intake (Atlas-style multi-file upload) auto-creates per-client
    drafts via _auto_create_draft_for_client → auto_create_draft_from_sales_packing."""
    src = ROUTES_INTAKE.read_text(encoding="utf-8")
    assert "_auto_create_draft_for_client" in src
    assert "auto_create_draft_from_sales_packing" in src


def test_routes_packing_no_external_writes_added():
    """Defensive: the new sync hooks must not introduce wFirma/DHL/SMTP
    calls into routes_packing."""
    src = ROUTES_PACKING.read_text(encoding="utf-8")
    for forbidden in (
        "wfirma_client", "wfirma_api",
        "send_email", "queue_email", "smtp",
        "dhl_dispatch", "trigger_clearance",
        "create_pz", "generate_pz",
        "proforma_create", "proforma_post",
        "process_sad",
    ):
        assert forbidden not in src, (
            f"routes_packing.py must not reference {forbidden!r}"
        )
