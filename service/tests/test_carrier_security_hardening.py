"""
test_carrier_security_hardening.py — DL-F3.5c phase tests.

Pins two security guarantees the live adapter and the webhook
routes must hold before any production cutover:

1. **PLT path containment.** The Paperless Trade validator rejects
   any path that resolves outside ``allowed_root``. The factory
   passes ``settings.storage_root`` so the operator-supplied
   ``customs_invoice_pdf_path`` cannot be used as an
   arbitrary-file-read primitive.

2. **Mandatory IP allowlist when live.** The webhook events
   endpoint refuses to serve (HTTP 503
   ``ip_allowlist_required_when_live``) when
   ``carrier_dhl_live_enabled=True`` and the IP allowlist is empty.
   Closes the URL-leak replay surface flagged by Security Reviewer.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_carrier_webhook as rcw
from app.core.config import settings
from app.services.carrier import carrier_event_db as ced
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier.adapters.dhl_paperless_trade import (
    PLT_MAX_BYTES,
    PLTValidationResult,
    validate_paperless_trade_pdf,
)


def _write_pdf(tmp_path, name: str, content: bytes) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _minimal_pdf() -> bytes:
    return b"%PDF-1.4\nminimal\n%%EOF\n"


# ── PLT path containment ───────────────────────────────────────────────────

def test_plt_no_containment_passes_when_root_unset(tmp_path):
    """Backwards-compat: when allowed_root is empty / None, the
    validator behaves as it did pre-DL-F3.5c."""
    pdf = _write_pdf(tmp_path, "ok.pdf", _minimal_pdf())
    result = validate_paperless_trade_pdf(str(pdf))  # no allowed_root
    assert result.ok is True


def test_plt_containment_under_root_passes(tmp_path):
    sub = tmp_path / "polish_descriptions"
    pdf = _write_pdf(sub, "ok.pdf", _minimal_pdf())
    result = validate_paperless_trade_pdf(
        str(pdf), allowed_root=str(tmp_path),
    )
    assert result.ok is True
    assert result.reason == "ok"


def test_plt_containment_outside_root_rejects(tmp_path):
    """Path explicitly outside the allowed root."""
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(_minimal_pdf())
    inside_root = tmp_path / "storage"
    inside_root.mkdir()
    result = validate_paperless_trade_pdf(
        str(outside), allowed_root=str(inside_root),
    )
    assert result.ok is False
    assert result.reason == "path_outside_root"


def test_plt_containment_traversal_rejects(tmp_path):
    """Path-traversal attempt via .. — must NOT escape."""
    inside_root = tmp_path / "storage"
    inside_root.mkdir()
    sneaky = str(inside_root / ".." / "etc_passwd_lookalike.pdf")
    # File doesn't exist but the resolved path is outside root —
    # containment must fire BEFORE existence check.
    result = validate_paperless_trade_pdf(
        sneaky, allowed_root=str(inside_root),
    )
    assert result.ok is False
    assert result.reason == "path_outside_root"


def test_plt_containment_rejects_absolute_etc_passwd(tmp_path):
    """Operator names a sensitive absolute path — containment fires
    first and returns path_outside_root rather than file_not_found."""
    inside_root = tmp_path / "storage"
    inside_root.mkdir()
    result = validate_paperless_trade_pdf(
        "/etc/passwd", allowed_root=str(inside_root),
    )
    assert result.ok is False
    assert result.reason == "path_outside_root"


def test_plt_containment_resolves_symlinks(tmp_path):
    """Symlink that points outside the root must be caught (Path
    .resolve() follows links before we run the relative_to check)."""
    inside_root = tmp_path / "storage"
    inside_root.mkdir()
    outside_target = tmp_path / "outside_target.pdf"
    outside_target.write_bytes(_minimal_pdf())
    link_in_root = inside_root / "link.pdf"
    try:
        os.symlink(str(outside_target), str(link_in_root))
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this platform")
    result = validate_paperless_trade_pdf(
        str(link_in_root), allowed_root=str(inside_root),
    )
    assert result.ok is False
    assert result.reason == "path_outside_root"


def test_plt_containment_path_outside_root_token_in_validator():
    """The new reason token is exactly 'path_outside_root'. Pinned
    so future contributors don't rename it without thinking."""
    # Provoke the gate against a known-bad path
    result = validate_paperless_trade_pdf(
        "/tmp/anywhere.pdf", allowed_root="/usr/local",
    )
    assert result.reason == "path_outside_root"


# ── Live adapter wires allowed_root through the factory ───────────────────

def test_live_adapter_constructor_accepts_allowed_root():
    from app.services.carrier.adapters.dhl_express_live import (
        DHLExpressLiveAdapter,
    )
    adapter = DHLExpressLiveAdapter(
        base_url="https://x.test/mydhlapi",
        username="u", password="p", account_number="ACC-1",
        http_client=object(),
        paperless_trade_enabled=True,
        paperless_trade_allowed_root="/storage",
    )
    assert adapter._plt_allowed_root == "/storage"


def test_factory_passes_storage_root_to_live(monkeypatch, tmp_path):
    """When the factory selects the live adapter, it must thread
    settings.storage_root into the live's PLT allowed_root."""
    from app.api import routes_carrier_actions as rca
    from app.services.carrier.adapters.dhl_express_live import (
        DHLExpressLiveAdapter,
    )
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", True,
                          raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_shadow_mode", False,
                          raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_status",
                          "production", raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_username", "u",
                          raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_password", "p",
                          raising=False)
    monkeypatch.setattr(settings, "dhl_express_account_number", "ACC",
                          raising=False)
    monkeypatch.setattr(settings, "storage_root", tmp_path,
                          raising=False)
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressLiveAdapter)
    assert adapter._plt_allowed_root == str(tmp_path)


# ── Webhook IP allowlist mandatory when live ─────────────────────────────

@pytest.fixture()
def webhook_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_webhook_enabled", True,
                          raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_webhook_ip_allowlist", "",
                          raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", False,
                          raising=False)
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_max_shipments_per_push", 200,
        raising=False,
    )
    csdb.init_db(tmp_path / "carrier_shipments.db")
    ced.init_db(tmp_path / "carrier_events.db")
    app = FastAPI()
    app.include_router(rcw.router)
    return TestClient(app, raise_server_exceptions=True,
                       client=("127.0.0.1", 12345))


def _push_payload():
    return {
        "shipments": [{
            "id": "WHSEC-1",
            "service": "express",
            "status": {
                "timestamp": "2026-04-01T10:00:00Z",
                "location": "Warsaw",
                "statusCode": "transit",
                "status": "in transit",
                "description": "moving",
            },
        }],
    }


def test_events_503_when_live_enabled_and_allowlist_empty(webhook_client,
                                                            monkeypatch):
    """The new mandatory-allowlist guard returns 503 when
    carrier_dhl_live_enabled=True AND allowlist is empty."""
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", True,
                          raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_webhook_ip_allowlist", "",
                          raising=False)
    r = webhook_client.post(
        "/api/v1/carrier/webhook/dhl/events", json=_push_payload(),
    )
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["code"] == "ip_allowlist_required_when_live"


def test_activate_503_when_live_enabled_and_allowlist_empty(
    webhook_client, monkeypatch,
):
    """Same guard fires on the activate endpoint."""
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", True,
                          raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_webhook_ip_allowlist", "",
                          raising=False)
    r = webhook_client.post(
        "/api/v1/carrier/webhook/dhl/activate",
        json={"secret": "x"},
        headers={"DHL-Hook-Secret": "x"},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "ip_allowlist_required_when_live"


def test_events_passes_when_live_enabled_with_allowlist_set(
    webhook_client, monkeypatch,
):
    """live_enabled + allowlist that matches client IP → passes."""
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", True,
                          raising=False)
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_ip_allowlist", "127.0.0.0/8",
        raising=False,
    )
    csdb.upsert_shipment(
        carrier="dhl", awb="WHSEC-1", state="handed_to_carrier",
        batch_id="B-WHSEC",
    )
    r = webhook_client.post(
        "/api/v1/carrier/webhook/dhl/events", json=_push_payload(),
    )
    assert r.status_code == 200


def test_events_403_when_live_enabled_and_client_ip_outside_allowlist(
    webhook_client, monkeypatch,
):
    """live_enabled + allowlist that does NOT match client IP → 403."""
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", True,
                          raising=False)
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_ip_allowlist", "10.0.0.0/8",
        raising=False,
    )
    r = webhook_client.post(
        "/api/v1/carrier/webhook/dhl/events", json=_push_payload(),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "forbidden"


def test_events_passes_when_live_disabled_with_empty_allowlist(
    webhook_client, monkeypatch,
):
    """live_disabled + empty allowlist → no IP check applies (dev)."""
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", False,
                          raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_webhook_ip_allowlist", "",
                          raising=False)
    csdb.upsert_shipment(
        carrier="dhl", awb="WHSEC-DEV", state="handed_to_carrier",
        batch_id="B-WHSEC-DEV",
    )
    r = webhook_client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json={"shipments": [{
            "id": "WHSEC-DEV", "service": "express",
            "status": {
                "timestamp": "2026-04-01T10:00:00Z",
                "location": "Warsaw", "statusCode": "transit",
                "status": "in transit", "description": "moving",
            },
        }]},
    )
    assert r.status_code == 200


# ── Source-grep guards ────────────────────────────────────────────────────

def test_validator_source_carries_path_outside_root_token():
    src = (Path(__file__).resolve().parents[1]
           / "app" / "services" / "carrier" / "adapters"
           / "dhl_paperless_trade.py").read_text(encoding="utf-8")
    assert "path_outside_root" in src


def test_validator_uses_resolve_for_symlink_following():
    src = (Path(__file__).resolve().parents[1]
           / "app" / "services" / "carrier" / "adapters"
           / "dhl_paperless_trade.py").read_text(encoding="utf-8")
    assert ".resolve()" in src
    assert "relative_to" in src


def test_webhook_route_guards_when_live():
    src = (Path(__file__).resolve().parents[1]
           / "app" / "api" / "routes_carrier_webhook.py").read_text(
               encoding="utf-8",
           )
    assert "ip_allowlist_required_when_live" in src
    assert "carrier_dhl_live_enabled" in src
