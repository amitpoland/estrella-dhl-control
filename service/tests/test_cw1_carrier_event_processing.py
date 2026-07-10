"""CW-1 (MASTER-EXEC-1 Phase 5) — carrier webhook event processing tests.

Pins: ingest-time tracking_ref→batch correlation (raw tracking id still never
persisted), the processor writing ONLY via tracking_db (idempotent on
source_ref), uncorrelated events skipped, Run-Now/status wiring, and authority
boundaries (no booking/label/customs/finance/reservation tokens).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.carrier import event_processor as ep                    # noqa: E402
from app.services.carrier.persistence import event_db, shipment_db        # noqa: E402
from app.services import tracking_db as tdb                               # noqa: E402
from app.api import routes_carrier_webhook as wh                          # noqa: E402
from app.api import routes_carrier_shadow as shadow_routes                # noqa: E402


@pytest.fixture()
def carrier_root(tmp_path, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "carrier_storage_root", tmp_path)
    tdb.init_tracking_db(tmp_path / "tracking_events.db")
    return tmp_path


def _seed_shipment(root: Path, batch_id: str, tracking_ref: str) -> None:
    db = root / "carrier_shipments.db"
    shipment_db.init_db(db)
    import sqlite3
    with sqlite3.connect(str(db)) as c:
        c.execute(
            "INSERT INTO carrier_shipments (batch_id, tracking_ref, mode, state, "
            "idempotency_key) VALUES (?, ?, 'shadow', 'complete', ?)",
            (batch_id, tracking_ref, f"idem-{batch_id}"),
        )


def _seed_event(root: Path, event_id: str, batch_id: str,
                event_type: str = "delivered") -> None:
    db = root / "carrier_events.db"
    event_db.init_db(db)
    event_db.insert_event(db, event_id, batch_id, event_type,
                          {"timestamp": "2026-07-10T08:00:00Z",
                           "description": "Delivered - signed"})


class TestCorrelation:
    def test_resolves_batch_by_tracking_ref(self, carrier_root):
        _seed_shipment(carrier_root, "SHIPMENT_A", "AWB123")
        got = shipment_db.get_batch_by_tracking_ref(
            carrier_root / "carrier_shipments.db", "AWB123")
        assert got == "SHIPMENT_A"

    def test_unknown_ref_returns_none(self, carrier_root):
        _seed_shipment(carrier_root, "SHIPMENT_A", "AWB123")
        assert shipment_db.get_batch_by_tracking_ref(
            carrier_root / "carrier_shipments.db", "NOPE") is None

    def test_webhook_route_correlates_before_stripping(self):
        # Source pins: correlation happens BEFORE make_log_safe, uses the
        # shipment record, and the raw tracking number is never persisted.
        src = inspect.getsource(wh.receive_dhl_webhook)
        assert src.index("get_batch_by_tracking_ref") < src.index("make_log_safe")
        assert "_TRACKING_KEYS" in src
        assert "background.add_task(run_carrier_event_processing" in src

    def test_route_has_background_param(self):
        assert "background" in inspect.signature(wh.receive_dhl_webhook).parameters


class TestProcessor:
    def test_writes_via_tracking_db(self, carrier_root):
        _seed_shipment(carrier_root, "SHIPMENT_B", "AWB999")
        _seed_event(carrier_root, "ev-1", "SHIPMENT_B", "delivered")
        res = ep.run_carrier_event_processing("SHIPMENT_B")
        assert res["written"] == 1 and res["errors"] == 0
        rows = tdb.get_events_for_batch("SHIPMENT_B")
        assert len(rows) == 1
        r = rows[0]
        assert r["source"] == "carrier_webhook"
        assert r["stage"] == "DELIVERED"
        assert r["awb"] == "AWB999"

    def test_idempotent_rerun_writes_zero(self, carrier_root):
        _seed_shipment(carrier_root, "SHIPMENT_C", "AWB77")
        _seed_event(carrier_root, "ev-2", "SHIPMENT_C", "transit")
        assert ep.run_carrier_event_processing("SHIPMENT_C")["written"] == 1
        assert ep.run_carrier_event_processing("SHIPMENT_C")["written"] == 0
        assert len(tdb.get_events_for_batch("SHIPMENT_C")) == 1

    def test_uncorrelated_events_skipped_not_crashed(self, carrier_root):
        _seed_event(carrier_root, "ev-3", "", "transit")   # no batch — orphan
        res = ep.run_carrier_event_processing()
        assert res["skipped_uncorrelated"] >= 1 and res["errors"] == 0

    def test_unknown_event_type_tolerated(self, carrier_root):
        _seed_shipment(carrier_root, "SHIPMENT_D", "AWB55")
        _seed_event(carrier_root, "ev-4", "SHIPMENT_D", "weird.new.thing")
        res = ep.run_carrier_event_processing("SHIPMENT_D")
        assert res["written"] == 1
        assert tdb.get_events_for_batch("SHIPMENT_D")[0]["stage"] == "WEIRD.NEW.THING"

    def test_stage_map(self):
        assert ep.map_stage("delivered") == "DELIVERED"
        assert ep.map_stage("transit") == "IN_TRANSIT"
        assert ep.map_stage("") == "CARRIER_EVENT"

    def test_status_envelope(self, carrier_root):
        _seed_shipment(carrier_root, "SHIPMENT_E", "AWB1")
        _seed_event(carrier_root, "ev-5", "SHIPMENT_E")
        ep.run_carrier_event_processing("SHIPMENT_E")
        st = ep.get_status()
        for k in ("healthy", "running", "ever_run", "last_completed_at",
                  "processed", "written", "errors", "events_total"):
            assert k in st
        assert st["ever_run"] is True and st["healthy"] is True


class TestAuthorityBoundaries:
    def test_processor_never_books_or_mutates_other_domains(self):
        src = inspect.getsource(ep)
        for forbidden in ("create_shipment(", "dispatch_proactive",
                          "create_reservation(", "invoices/add",
                          "dhl_clearance", "finance_postings",
                          "label", "ProformaRequest"):
            assert forbidden not in src, forbidden

    def test_processor_writes_only_tracking_db(self):
        src = inspect.getsource(ep.run_carrier_event_processing)
        assert "record_events_batch" in src
        for forbidden in ("INSERT INTO carrier_shipments", "UPDATE ",
                          "DELETE FROM", "insert_event("):
            assert forbidden not in src

    def test_run_now_and_status_routes_exist(self):
        paths = {getattr(r, "path", "") for r in shadow_routes.router.routes}
        assert "/api/v1/carrier/events/process" in paths
        assert "/api/v1/carrier/events/status" in paths
