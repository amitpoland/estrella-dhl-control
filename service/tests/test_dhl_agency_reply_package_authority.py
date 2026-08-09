"""
Authority split: audit.reply_package (DHL) vs audit.agency_reply_package (agency).

Pins the permanent contract that an agency package alone must never mark the
DHL reply package ready, never enable Send Reply in the V2 UI derivation, and
never satisfy POST /api/v1/dhl/send-reply/{batch}. Both packages may coexist.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.timeline_milestones import build_milestones

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_DETAIL = _V2 / "shipment-detail-page.jsx"
_V1 = Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html"
_DHL_PREFIX = "/api/v1/dhl"


def _ms(audit):
    return {m["key"]: m for m in build_milestones(audit)}


# ── Milestone / field authority ───────────────────────────────────────────────

def test_agency_package_alone_does_not_mark_dhl_package_ready():
    m = _ms({"agency_reply_package": {"status": "queued", "to": "agency@example.com"}})
    assert m["reply_package_generated"]["done"] is False
    assert m["agency_package_generated"]["done"] is True


def test_real_reply_package_enables_dhl_step():
    m = _ms({"reply_package": {"to": "odprawacelna@dhl.com", "subject": "RE: AWB"}})
    assert m["reply_package_generated"]["done"] is True


def test_both_packages_coexist_without_collision():
    m = _ms({
        "reply_package": {"to": "odprawacelna@dhl.com"},
        "agency_reply_package": {"status": "queued", "to": "agency@example.com"},
        "clearance_decision": {"clearance_path": "external_agency_clearance"},
    })
    assert m["reply_package_generated"]["done"] is True
    assert m["agency_package_generated"]["done"] is True


def test_agency_package_event_alone_does_not_complete_dhl_milestone():
    m = _ms({"timeline": [{"ts": "2026-08-05T09:00:00+00:00", "event": "agency_package_auto_built"}]})
    assert m["reply_package_generated"]["done"] is False
    assert m["agency_package_generated"]["done"] is True


# ── Backend send-reply 422 unchanged ─────────────────────────────────────────

def _agency_only_audit(storage: Path, batch_id: str, awb: str) -> Path:
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id": batch_id,
        "awb": awb,
        "carrier": "DHL",
        "status": "blocked",
        "clearance_status": "dhl_email_received",
        "agency_reply_package": {
            "to": "agency@example.com",
            "status": "queued",
            "subject": f"Zgłoszenie celne – AWB {awb}",
        },
        # intentionally NO reply_package
    }
    p = d / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def _make_reply_client():
    from app.core.security import require_api_key
    from app.auth.dependencies import get_current_user
    from app.api.routes_dhl_clearance import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-user", "role": "admin", "is_active": True, "is_approved": True,
    }
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def tmp_storage(tmp_path, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "storage_root", tmp_path, raising=False)
    yield tmp_path


def test_send_reply_422_when_only_agency_package_present(tmp_storage):
    batch_id = "AUTH_SPLIT_AGENCY_ONLY"
    awb = "5831878861"
    _agency_only_audit(tmp_storage, batch_id, awb)
    client = _make_reply_client()

    r = client.post(f"{_DHL_PREFIX}/send-reply/{batch_id}")
    assert r.status_code == 422, r.text
    detail = r.json().get("detail")
    assert detail == "Reply package not found. Run 'Build Reply Package' first."


def test_send_reply_does_not_accept_agency_reply_package_key():
    """Source pin: send route must keep reading audit.reply_package only."""
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "api" / "routes_dhl_clearance.py"
    ).read_text(encoding="utf-8")
    # The send-reply handler resolves reply_pkg from reply_package, not agency.
    assert 'reply_pkg = audit.get("reply_package")' in src
    handler = src.split("async def send_dhl_reply")[1].split("\nasync def ")[0]
    assert 'audit.get("agency_reply_package")' not in handler
    assert 'audit.get("reply_package")' in handler


# ── V2 / V1 UI source contract ───────────────────────────────────────────────

def test_v2_ui_does_not_or_agency_into_dhl_package_built():
    src = _DETAIL.read_text(encoding="utf-8")
    # The historical mixed-authority OR must be gone.
    assert "audit.reply_package || audit.dhl_reply_package || audit.agency_reply_package" not in src
    assert "replyPackageBuilt:   !!(audit.reply_package)" in src or 'replyPackageBuilt: !!(audit.reply_package)' in src
    assert "Agency package exists. DHL reply package has not been built yet." in src
    assert 'data-testid="agency-package-status"' in src
    assert 'data-testid="dhl-reply-package-status"' in src
    assert "replyPackageSendReady" in src
    # Send blocked reason for agency-only split
    assert "agencyOnlySplit" in src


def test_v2_ui_agency_alone_does_not_enable_send_in_derivation():
    """Static pin: sendState uses sendReady (reply_package.to), not pkgCompleted alone,
    and agencyOnlySplit cannot set sendReady."""
    src = _DETAIL.read_text(encoding="utf-8")
    assert "const sendReady     = !!(d.replyPackageSendReady);" in src or "replyPackageSendReady" in src
    assert "const sendState  = sendCompleted ? 'completed' : (sendReady ? 'available' : 'blocked');" in src
    # sendReady must come from reply_package.to, not agency
    assert "replyPackageSendReady: !!(audit.reply_package && audit.reply_package.to)" in src


def test_v1_ui_does_not_treat_agency_as_dhl_package_built():
    src = _V1.read_text(encoding="utf-8")
    assert "NEVER treat agency_reply_package as DHL-package proof" in src
    assert "_agencyOnlySplit" in src
    assert "Agency package exists. DHL reply package has not been built yet." in src
    # _drpBuilt must not reference agency_reply_package
    m = re.search(r"const _drpBuilt\s*=\s*[^;]+;", src)
    assert m, "_drpBuilt declaration missing"
    assert "agency_reply_package" not in m.group(0)
    assert "_rp.to" in m.group(0)
