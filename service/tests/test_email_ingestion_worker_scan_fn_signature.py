"""
Regression test for email_ingestion_worker scan_fn signature bug (2026-05-26).

Bug: the fallback `scan_fn` wrapper inside `run_ingestion_cycle` was defined
with positional `token, account_id` parameters, but the call-site invokes it
with kwargs only (target_awb, limit, api_base, token_provider, dhl_ticket).
This produced WARNING on every cycle for every active shipment:

    scan_fn() missing 2 required positional arguments: 'token' and 'account_id'

The fix changed the wrapper to accept the exact kwargs the call-site passes.
This test pins the kwarg contract so the bug cannot regress silently.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from service.app.services import email_ingestion_worker as eiw


def _make_audit(tmp_path: Path, batch_id: str, awb: str) -> Path:
    outputs = tmp_path / "outputs" / batch_id
    outputs.mkdir(parents=True, exist_ok=True)
    audit_path = outputs / "audit.json"
    audit_path.write_text(json.dumps({
        "batch_id":     batch_id,
        "status":       "in_progress",
        "tracking_no":  awb,
    }), encoding="utf-8")
    return audit_path


def test_default_scan_fn_accepts_call_site_kwargs(tmp_path, monkeypatch, caplog):
    """
    With NO injected scan_fn the worker must resolve the in-tree fallback and
    invoke it with the exact kwargs the call-site uses, without raising
    TypeError / emitting the 'missing 2 required positional arguments' warning.
    """
    monkeypatch.setattr(eiw.settings, "storage_root", tmp_path, raising=False)
    _make_audit(tmp_path, "B1", "1234567890")

    caplog.set_level(logging.WARNING, logger=eiw.log.name)
    res = eiw.run_ingestion_cycle(
        token_provider=lambda: "dummy-token",
        download_fn=lambda *a, **k: [],
    )

    # Cycle must complete without the signature error
    assert res.get("ok") is True, f"cycle failed: {res}"
    for rec in caplog.records:
        assert "missing 2 required positional" not in rec.getMessage(), (
            "regression: scan_fn signature mismatch reintroduced — "
            f"warning: {rec.getMessage()}"
        )


def test_injected_scan_fn_receives_expected_kwargs(tmp_path, monkeypatch):
    """
    Pin the kwarg contract: the worker MUST call scan_fn with these kwargs:
    target_awb, limit, api_base, token_provider, dhl_ticket.
    """
    monkeypatch.setattr(eiw.settings, "storage_root", tmp_path, raising=False)
    _make_audit(tmp_path, "B2", "9876543210")

    received: dict = {}

    def fake_scan_fn(**kwargs):
        received.update(kwargs)
        return {"emails": []}

    res = eiw.run_ingestion_cycle(
        scan_fn=fake_scan_fn,
        token_provider=lambda: "dummy-token",
        download_fn=lambda *a, **k: [],
    )
    assert res["ok"] is True
    # The contract: these kwarg names are what the call-site passes.
    assert set(received.keys()) >= {
        "target_awb", "limit", "api_base", "token_provider", "dhl_ticket",
    }, f"unexpected kwargs delivered to scan_fn: {received.keys()}"
    assert received["target_awb"] == "9876543210"
    # token_provider must be callable so scanners can pull the pre-refreshed token
    assert callable(received["token_provider"])
    assert received["token_provider"]() == "dummy-token"
