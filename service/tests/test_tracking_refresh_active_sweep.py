"""The bulk/login tracking refresh is refresh-ONLY.

``scan_active_shipments`` runs the whole workflow engine — it queues and sends
SMTP mail and dispatches clearance actions — so it can never be the login
hook.  ``refresh_active_tracking`` exists to poll carrier tracking and nothing
else, which is what makes it safe for every authenticated operator.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


def _seed_carrier_db(db_path: Path, rows: list) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS carrier_shipments (
            idempotency_key TEXT PRIMARY KEY,
            batch_id TEXT, mode TEXT, state TEXT, error TEXT,
            simulated INTEGER, created_at TEXT, updated_at TEXT,
            tracking_ref TEXT, do_not_use INTEGER DEFAULT 0, client_ref TEXT,
            shipment_direction TEXT
        )
        """
    )
    for i, r in enumerate(rows):
        con.execute(
            "INSERT INTO carrier_shipments(idempotency_key, batch_id, mode, state,"
            " simulated, created_at, updated_at, tracking_ref, do_not_use, client_ref)"
            " VALUES (?,?,?,?,0,?,?,?,?,?)",
            (f"k{i}", r["batch_id"], "live", r.get("state") or "complete",
             "2026-08-10T10:00:00Z", "2026-08-10T10:00:00Z",
             r["tracking_ref"], int(r.get("do_not_use") or 0), "Client"),
        )
    con.commit()
    con.close()


def _write_audit(root: Path, batch_id: str, audit: dict) -> None:
    d = root / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps(audit), encoding="utf-8")


def _isolate(mon, tmp_path, monkeypatch):
    monkeypatch.setattr(mon.settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(
        mon.settings, "carrier_storage_root", tmp_path / "carrier", raising=False
    )


def _raise_terminal(awb, *, batch_id, carrier="DHL"):
    raise AssertionError("terminal AWB must not be polled")


def test_sweep_polls_inbound_and_outbound_deduped(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    _isolate(mon, tmp_path, monkeypatch)
    _write_audit(tmp_path, "SHIPMENT_IN_1", {
        "batch_id": "SHIPMENT_IN_1", "awb": "1111111111",
        "clearance_status": "in_progress",
    })
    _seed_carrier_db(tmp_path / "carrier" / "carrier_shipments.db", [
        {"tracking_ref": "2222222222", "batch_id": "SHIPMENT_OUT_1"},
        # same AWB + batch as the inbound audit — must collapse to one poll
        {"tracking_ref": "1111111111", "batch_id": "SHIPMENT_IN_1"},
    ])
    calls = []
    monkeypatch.setattr(
        mon, "_poll_awb_tracking",
        lambda awb, *, batch_id, carrier="DHL": calls.append(awb) or {
            "status": "in_transit", "source": "dhl_api",
        },
    )
    out = mon.refresh_active_tracking()

    assert sorted(calls) == ["1111111111", "2222222222"], calls
    assert out["checked"] == 2
    assert out["refreshed"] == 2
    assert out["running"] is False
    assert out["errors"] == []


def test_sweep_counts_fresh_cache_hits_separately(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    _isolate(mon, tmp_path, monkeypatch)
    _write_audit(tmp_path, "SHIPMENT_IN_2", {
        "batch_id": "SHIPMENT_IN_2", "awb": "3333333333",
        "clearance_status": "in_progress",
    })
    monkeypatch.setattr(
        mon, "_poll_awb_tracking",
        lambda awb, *, batch_id, carrier="DHL": {
            "status": "in_transit", "source": "cache",
        },
    )
    out = mon.refresh_active_tracking()
    assert out["checked"] == 1
    assert out["skipped_fresh"] == 1
    assert out["refreshed"] == 0


def test_sweep_never_sends_or_queues_email(tmp_path, monkeypatch):
    """The whole reason this is not scan_active_shipments()."""
    from app.services import active_shipment_monitor as mon
    from app.services import email_sender

    _isolate(mon, tmp_path, monkeypatch)
    _write_audit(tmp_path, "SHIPMENT_IN_3", {
        "batch_id": "SHIPMENT_IN_3", "awb": "4444444444",
        "clearance_status": "in_progress",
    })

    def _boom(*a, **k):
        raise AssertionError("refresh sweep must never touch the email path")

    monkeypatch.setattr(email_sender, "send_queued_email", _boom, raising=False)
    monkeypatch.setattr(mon, "queue_email", _boom, raising=False)
    monkeypatch.setattr(
        mon, "_poll_awb_tracking",
        lambda awb, *, batch_id, carrier="DHL": {
            "status": "in_transit", "source": "dhl_api",
        },
    )
    out = mon.refresh_active_tracking()
    assert out["checked"] == 1


def test_sweep_excludes_terminal_awbs(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    _isolate(mon, tmp_path, monkeypatch)
    _write_audit(tmp_path, "SHIPMENT_IN_4", {
        "batch_id": "SHIPMENT_IN_4", "awb": "5555555555",
        "clearance_status": "in_progress",
    })
    monkeypatch.setattr(mon, "is_carrier_tracking_terminal", lambda awb, bid: True)
    monkeypatch.setattr(mon, "_poll_awb_tracking", _raise_terminal)
    out = mon.refresh_active_tracking()
    assert out["checked"] == 0
    assert out["skipped_terminal"] == 1


def test_concurrent_sweep_returns_running_instead_of_doubling(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    _isolate(mon, tmp_path, monkeypatch)
    _write_audit(tmp_path, "SHIPMENT_IN_5", {
        "batch_id": "SHIPMENT_IN_5", "awb": "6666666666",
        "clearance_status": "in_progress",
    })
    entered = threading.Event()
    release = threading.Event()

    def _slow(awb, *, batch_id, carrier="DHL"):
        entered.set()
        release.wait(timeout=10)
        return {"status": "in_transit", "source": "dhl_api"}

    monkeypatch.setattr(mon, "_poll_awb_tracking", _slow)
    first = {}
    t = threading.Thread(target=lambda: first.update(mon.refresh_active_tracking()))
    t.start()
    try:
        assert entered.wait(timeout=10), "first sweep never started"
        second = mon.refresh_active_tracking()
        assert second["running"] is True
        assert second["checked"] == 0
    finally:
        release.set()
        t.join(timeout=15)
    assert first["running"] is False
    assert first["checked"] == 1


def test_sweep_routes_through_the_single_tracking_authority():
    """No second poller: the sweep must go via _poll_awb_tracking."""
    import inspect
    from app.services import active_shipment_monitor as mon

    src = inspect.getsource(mon.refresh_active_tracking)
    assert "_poll_awb_tracking" in src
    assert "get_tracking_status" not in src


# ── Frontend contract pins (source-grep) ─────────────────────────────────────

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"


def test_outbound_card_interval_does_not_force_carrier_refresh():
    """refresh=true bypasses the cache; on a 120s interval that is 30 carrier
    calls/hour/card against a documented 250/day quota."""
    src = (_V2 / "estrella-outbound-tracking.jsx").read_text(encoding="utf-8")
    start = src.index("setInterval")
    body = src[start:src.index("120000", start)]
    assert "load(true)" not in body, "interval must not force a carrier refresh"
    assert "load(false)" in body
    # the manual button keeps the deliberate forced refresh
    assert "onClick={function () { load(true); loadDelivery(); }}" in src


def test_login_bootstrap_calls_refresh_only_endpoint():
    src = (_V2 / "index.html").read_text(encoding="utf-8")
    assert "/api/v1/tracking/refresh-active" in src
    assert "_pzTrackingBootstrapFired" in src
    # never the workflow sweep — that one sends email
    assert "monitor/active-shipments/run" not in src


def _seed_carrier_db_with_provider(db_path: Path, rows: list) -> None:
    """Same table as :func:`_seed_carrier_db` plus the ``provider`` column."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS carrier_shipments (
            idempotency_key TEXT PRIMARY KEY,
            batch_id TEXT, mode TEXT, state TEXT, error TEXT,
            simulated INTEGER, created_at TEXT, updated_at TEXT,
            tracking_ref TEXT, do_not_use INTEGER DEFAULT 0, client_ref TEXT,
            shipment_direction TEXT, provider TEXT
        )
        """
    )
    for i, r in enumerate(rows):
        con.execute(
            "INSERT INTO carrier_shipments(idempotency_key, batch_id, mode, state,"
            " simulated, created_at, updated_at, tracking_ref, do_not_use,"
            " client_ref, provider) VALUES (?,?,?,?,0,?,?,?,?,?,?)",
            (f"k{i}", r["batch_id"], "live", "complete",
             "2026-08-10T10:00:00Z", "2026-08-10T10:00:00Z",
             r["tracking_ref"], 0, "Client", r.get("provider")),
        )
    con.commit()
    con.close()


def test_sweep_polls_each_shipment_with_its_own_booked_provider(
    tmp_path, monkeypatch
):
    """The booking row's provider decides which carrier is polled.

    ``tracking_service`` dispatches "DHL -> DHL client, anything else -> FedEx
    client", so a provider passed through wrongly does not fail loudly — it
    quietly asks the wrong carrier about an AWB it has never heard of.
    """
    from app.services import active_shipment_monitor as mon

    _isolate(mon, tmp_path, monkeypatch)
    _seed_carrier_db_with_provider(tmp_path / "carrier" / "carrier_shipments.db", [
        {"tracking_ref": "1111111111", "batch_id": "B_DHL",   "provider": "DHL"},
        {"tracking_ref": "222222222222", "batch_id": "B_FDX", "provider": "FEDEX"},
        # Legacy row written before the provider column existed → DHL.
        {"tracking_ref": "3333333333", "batch_id": "B_LEGACY", "provider": None},
    ])
    seen = {}
    monkeypatch.setattr(
        mon, "_poll_awb_tracking",
        lambda awb, *, batch_id, carrier="DHL": seen.setdefault(awb, carrier) and None
        or {"status": "in_transit", "source": "api"},
    )
    out = mon.refresh_active_tracking()

    assert seen == {
        "1111111111": "DHL",
        "222222222222": "FedEx",
        "3333333333": "DHL",
    }, seen
    assert out["checked"] == 3


def test_sweep_skips_providers_tracking_service_cannot_poll(tmp_path, monkeypatch):
    """A UPS AWB must not be polled as DHL/FedEx — it is skipped and counted."""
    from app.services import active_shipment_monitor as mon

    _isolate(mon, tmp_path, monkeypatch)
    _seed_carrier_db_with_provider(tmp_path / "carrier" / "carrier_shipments.db", [
        {"tracking_ref": "1Z999AA10123456784", "batch_id": "B_UPS", "provider": "UPS"},
        {"tracking_ref": "9999999999", "batch_id": "B_OTHER", "provider": "OTHER"},
    ])
    monkeypatch.setattr(
        mon, "_poll_awb_tracking",
        lambda awb, *, batch_id, carrier="DHL": (_ for _ in ()).throw(
            AssertionError(f"{awb} polled as {carrier}; it has no tracking client")
        ),
    )
    out = mon.refresh_active_tracking()

    assert out["checked"] == 0
    assert out["skipped_untrackable"] == 2, out
