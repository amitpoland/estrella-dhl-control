"""
test_correction_registry.py — append-only operator-correction memory.

Covers:
  • append-only invariant (no row ever overwritten / deleted by API)
  • rejected match retained alongside accepted
  • historical lookup ordered newest-first
  • frequency / confidence aggregation
  • explainability envelope returns the source rows
  • route surface: POST is the only writer; reads are pure
  • registry never mutates other DBs / files
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import correction_registry as cr
from app.api.routes_correction_registry import router as cr_router


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """Initialise a fresh correction_registry.db in tmp_path."""
    db = tmp_path / "correction_registry.db"
    cr.init_correction_registry(db)
    # Disable API key check for tests
    monkeypatch.setenv("API_KEY", "")
    yield db
    cr._db_path = None


@pytest.fixture
def client(isolated_registry):
    app = FastAPI()
    app.include_router(cr_router)
    return TestClient(app)


# ── Service-layer tests ──────────────────────────────────────────────────────

class TestAppendOnly:
    def test_two_writes_for_same_key_both_persist(self, isolated_registry):
        a = cr.record_correction(
            correction_type="customer_resolution_override",
            entity_key="clear-diamonds",
            new_value="91254191",
            operator="amit",
            approved=True,
        )
        b = cr.record_correction(
            correction_type="customer_resolution_override",
            entity_key="clear-diamonds",
            new_value="91254192",       # operator changed mind
            operator="amit",
            approved=True,
        )
        assert a and b and a != b
        rows = cr.list_corrections(
            correction_type="customer_resolution_override",
            entity_key="clear-diamonds",
        )
        assert len(rows) == 2
        # newest-first
        assert rows[0]["new_value"] == "91254192"
        assert rows[1]["new_value"] == "91254191"

    def test_no_update_or_delete_method_exposed(self):
        public = {n for n in dir(cr) if not n.startswith("_")}
        assert not any(n.startswith(("update_", "delete_", "remove_", "drop_"))
                       for n in public), "registry must be append-only"

    def test_rejected_row_retained(self, isolated_registry):
        cr.record_correction(
            correction_type="rejected_match",
            entity_key="omara s.r.o",
            new_value="VAT-OMARA-PROPOSED",
            operator="amit",
            approved=False,
            notes="not the right OMARA",
        )
        cr.record_correction(
            correction_type="rejected_match",
            entity_key="omara s.r.o",
            new_value="VAT-OMARA-OTHER",
            operator="amit",
            approved=False,
        )
        rejected = cr.get_rejected("rejected_match", "omara s.r.o")
        assert len(rejected) == 2
        assert all(r["approved"] is False for r in rejected)


class TestHistoricalLookup:
    def test_last_accepted_returns_most_recent(self, isolated_registry):
        cr.record_correction(
            correction_type="product_mapping_override",
            entity_key="EJL/26-27/121-1",
            new_value="WF_111",
            operator="amit",
            approved=True,
        )
        cr.record_correction(
            correction_type="product_mapping_override",
            entity_key="EJL/26-27/121-1",
            new_value="WF_222",
            operator="amit",
            approved=True,
        )
        last = cr.get_last_accepted("product_mapping_override",
                                    "EJL/26-27/121-1")
        assert last is not None
        assert last["new_value"] == "WF_222"
        assert last["approved"] is True

    def test_last_accepted_none_when_only_rejected(self, isolated_registry):
        cr.record_correction(
            correction_type="accepted_match",
            entity_key="ghost",
            new_value="X",
            operator="amit",
            approved=False,
        )
        assert cr.get_last_accepted("accepted_match", "ghost") is None

    def test_filter_by_shipment(self, isolated_registry):
        cr.record_correction(
            correction_type="vat_override",
            entity_key="omara s.r.o",
            new_value="SK2020000000",
            operator="amit",
            shipment_id="SHIPMENT_A",
            approved=True,
        )
        cr.record_correction(
            correction_type="vat_override",
            entity_key="omara s.r.o",
            new_value="SK2020000001",
            operator="amit",
            shipment_id="SHIPMENT_B",
            approved=True,
        )
        rows = cr.list_corrections(shipment_id="SHIPMENT_A")
        assert len(rows) == 1
        assert rows[0]["shipment_id"] == "SHIPMENT_A"


class TestAggregations:
    def test_frequency_counts(self, isolated_registry):
        for _ in range(3):
            cr.record_correction(
                correction_type="ambiguity_resolution",
                entity_key="PND",
                new_value="WF_PND_ROSE",
                operator="amit",
                approved=True,
            )
        cr.record_correction(
            correction_type="ambiguity_resolution",
            entity_key="PND",
            new_value="WF_PND_BLUE",
            operator="amit",
            approved=False,
        )
        f = cr.get_frequency("ambiguity_resolution", "PND")
        assert f["accepted"] == 3
        assert f["rejected"] == 1
        assert f["total"]    == 4
        assert f["accept_ratio"] == 0.75
        assert f["top_new_value"] == "WF_PND_ROSE"
        assert f["top_new_value_count"] == 3

    def test_confidence_score_bounded(self, isolated_registry):
        # Three identical accepts → stability=1, accept_ratio=1, vol=1 → 1.0
        for _ in range(3):
            cr.record_correction(
                correction_type="contractor_alias",
                entity_key="impact gallery sp z o o",
                new_value="Impact Gallery sp. z o.o.",
                operator="amit",
                approved=True,
            )
        c = cr.confidence_score("contractor_alias", "impact gallery sp z o o")
        assert 0.0 <= c["score"] <= 1.0
        assert c["score"] == pytest.approx(1.0, abs=1e-6)

    def test_confidence_score_drops_with_rejections(self, isolated_registry):
        cr.record_correction(correction_type="accepted_match",
                             entity_key="X", new_value="A",
                             operator="amit", approved=True)
        cr.record_correction(correction_type="accepted_match",
                             entity_key="X", new_value="A",
                             operator="amit", approved=False)
        cr.record_correction(correction_type="accepted_match",
                             entity_key="X", new_value="A",
                             operator="amit", approved=False)
        c = cr.confidence_score("accepted_match", "X")
        assert c["accept_ratio"] == pytest.approx(1/3, abs=1e-6)
        # Lower than 1.0 because of mixed signal
        assert c["score"] < 0.5


class TestExplainability:
    def test_explain_returns_history_and_provenance(self, isolated_registry):
        cr.record_correction(
            correction_type="customer_resolution_override",
            entity_key="anastazia panakova",
            new_value="WF_999",
            operator="amit",
            approved=True,
            shipment_id="SHIPMENT_6049349806",
            evidence_refs=[{"type": "audit", "ref": "audit.json#L42"},
                           {"type": "email", "ref": "msg-id-1"}],
            notes="confirmed by VAT",
        )
        env = cr.explain_for("customer_resolution_override",
                             "anastazia panakova")
        assert env["last_accepted"]["new_value"] == "WF_999"
        assert env["last_accepted"]["evidence_refs"] == [
            {"type": "audit", "ref": "audit.json#L42"},
            {"type": "email", "ref": "msg-id-1"},
        ]
        assert env["history"][0]["notes"] == "confirmed by VAT"
        assert env["frequency"]["accepted"] == 1
        assert "score" in env["confidence"]

    def test_explain_empty_when_no_history(self, isolated_registry):
        env = cr.explain_for("vat_override", "unknown-key")
        assert env["last_accepted"] is None
        assert env["history"] == []
        assert env["frequency"]["total"] == 0
        assert env["confidence"]["score"] == 0.0


class TestSchemaInvariants:
    def test_supported_types_match_spec(self):
        expected = {
            "customer_resolution_override",
            "vat_override",
            "product_mapping_override",
            "ambiguity_resolution",
            "unit_override",
            "wording_override",
            "warehouse_override",
            "contractor_alias",
            "rejected_match",
            "accepted_match",
        }
        assert set(cr.SUPPORTED_TYPES) == expected

    def test_unknown_type_rejected(self, isolated_registry):
        with pytest.raises(ValueError):
            cr.record_correction(
                correction_type="not_a_real_type",
                entity_key="x",
                operator="amit",
            )

    def test_confidence_clamped_to_unit_interval(self, isolated_registry):
        rid = cr.record_correction(
            correction_type="unit_override",
            entity_key="kpl",
            new_value="szt.",
            operator="amit",
            confidence=999.0,
        )
        assert rid
        rows = cr.list_corrections(correction_type="unit_override")
        assert rows[0]["confidence"] == 1.0


class TestNoOverwrite:
    def test_db_row_count_grows_monotonically(self, isolated_registry):
        for i in range(5):
            cr.record_correction(
                correction_type="wording_override",
                entity_key="line-1",
                new_value=f"v{i}",
                operator="amit",
                approved=True,
            )
        with sqlite3.connect(str(isolated_registry)) as con:
            n = con.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
        assert n == 5

    def test_each_record_has_unique_id_and_timestamp(self, isolated_registry):
        ids = [
            cr.record_correction(
                correction_type="warehouse_override",
                entity_key="WH1",
                new_value=f"v{i}",
                operator="amit",
            )
            for i in range(3)
        ]
        assert len(set(ids)) == 3


# ── Route surface tests ──────────────────────────────────────────────────────

class TestRouteSurface:
    def test_post_rejects_unknown_type(self, client):
        r = client.post("/api/v1/corrections", json={
            "correction_type": "bogus",
            "entity_key": "x",
            "operator": "amit",
        })
        assert r.status_code == 400

    def test_post_requires_operator(self, client):
        r = client.post("/api/v1/corrections", json={
            "correction_type": "vat_override",
            "entity_key": "x",
        })
        assert r.status_code in (400, 422)

    def test_post_then_explain_round_trip(self, client):
        r = client.post("/api/v1/corrections", json={
            "correction_type": "vat_override",
            "entity_key":      "omara s.r.o",
            "old_value":       "",
            "new_value":       "SK2020000000",
            "operator":        "amit",
            "approved":        True,
            "evidence_refs":   [{"type": "audit", "ref": "abc"}],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["id"]

        e = client.get("/api/v1/corrections/explain", params={
            "correction_type": "vat_override",
            "entity_key":      "omara s.r.o",
        }).json()
        assert e["explanation"]["last_accepted"]["new_value"] == "SK2020000000"
        assert e["explanation"]["last_accepted"]["evidence_refs"] == [
            {"type": "audit", "ref": "abc"}
        ]

    def test_no_update_or_delete_route(self):
        from app.api.routes_correction_registry import router
        methods = {(r.path, m) for r in router.routes
                   for m in getattr(r, "methods", [])}
        assert all(m not in {"PUT", "PATCH", "DELETE"}
                   for _, m in methods), \
            "registry routes must not expose PUT/PATCH/DELETE"

    def test_stats_endpoint(self, client):
        client.post("/api/v1/corrections", json={
            "correction_type": "accepted_match",
            "entity_key":      "k1",
            "operator":        "amit",
            "approved":        True,
        })
        client.post("/api/v1/corrections", json={
            "correction_type": "rejected_match",
            "entity_key":      "k2",
            "operator":        "anna",
            "approved":        False,
        })
        s = client.get("/api/v1/corrections/stats").json()["stats"]
        assert s["total"] == 2
        assert s["distinct_operators"] == 2
        assert s["by_type"]["accepted_match"]["accepted"] == 1
        assert s["by_type"]["rejected_match"]["rejected"] == 1


class TestIsolation:
    def test_writes_only_touch_registry_db(self, isolated_registry, tmp_path):
        # Touch witnesses; ensure registry write doesn't change them.
        wfirma = tmp_path / "wfirma.db"; wfirma.write_bytes(b"")
        docs   = tmp_path / "documents.db"; docs.write_bytes(b"")
        rq     = tmp_path / "reservation_queue.db"; rq.write_bytes(b"")
        emailq = tmp_path / "email_queue.json"; emailq.write_text("[]")
        before = {p: p.stat().st_mtime_ns for p in (wfirma, docs, rq, emailq)}

        cr.record_correction(
            correction_type="accepted_match",
            entity_key="x",
            operator="amit",
            approved=True,
        )
        after = {p: p.stat().st_mtime_ns for p in (wfirma, docs, rq, emailq)}
        assert before == after, "registry write must not touch other DBs"
