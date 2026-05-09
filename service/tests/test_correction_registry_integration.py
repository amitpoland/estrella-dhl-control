"""
test_correction_registry_integration.py — verify operator-approved
Proforma readiness actions append correction-registry rows.

Scope (read carefully):
  • product auto-register existing_mapped → product_mapping_override
  • product auto-register created          → product_mapping_override
  • customer auto-resolve accepted match   → accepted_match
  • customer auto-resolve ambiguous        → rejected_match
  • customer auto-create created           → customer_resolution_override
  • Logging failure must NOT break the operator action.
  • Dashboard readiness GET must NOT create correction rows.
  • Multiple runs append multiple history rows (append-only).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import correction_registry as cr
from app.services import wfirma_db as wfdb
from app.services import wfirma_product_auto_register as wfar
from app.services import wfirma_customer_auto_resolve as wfcar


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Initialise a fresh correction_registry.db + wfirma.db in tmp_path."""
    cr.init_correction_registry(tmp_path / "correction_registry.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    yield tmp_path
    cr._db_path = None
    wfdb._db_path = None


# ── Product auto-register ────────────────────────────────────────────────────

class TestProductAutoRegister:
    def test_existing_mapped_logs_product_mapping_override(self, isolated):
        existing = SimpleNamespace(wfirma_id="WF-EXIST-001",
                                   name="Test Product",
                                   unit="szt.", code="EJL/26-27/121-1")
        with patch.object(wfar.wfirma_client, "get_product_by_code",
                          return_value=existing):
            res = wfar._register_one(
                product_code   = "EJL/26-27/121-1",
                item_type      = "ring",
                description_en = "Gold Ring",
                dry_run        = True,
                operator       = "amit",
                batch_id       = "SHIPMENT_X",
            )
        assert res["status"] == "existing_mapped"
        rows = cr.list_corrections(correction_type="product_mapping_override",
                                   entity_key="EJL/26-27/121-1")
        assert len(rows) == 1
        r = rows[0]
        assert r["new_value"] == "WF-EXIST-001"
        assert r["operator"]  == "amit"
        assert r["batch_id"]  == "SHIPMENT_X"
        assert r["module_source"] == "wfirma_product_auto_register"
        assert r["approved"] is True
        assert r["confidence"] == 1.0
        assert r["notes"] == "existing_mapped"
        # Evidence must reference the endpoint + product code
        types = {e["type"] for e in r["evidence_refs"]}
        assert {"endpoint", "product_code"}.issubset(types)

    def test_created_logs_product_mapping_override(self, isolated, monkeypatch):
        # Force write-mode flag on
        monkeypatch.setattr(wfar.settings, "wfirma_create_product_allowed",
                            True, raising=False)
        with patch.object(wfar.wfirma_client, "get_product_by_code",
                          return_value=None), \
             patch("app.services.description_engine.get_description_block",
                   return_value={
                       "description_line": "Złoty Pierścionek",
                       "name_pl": "Pierścionek",
                       "description_block": "blob",
                   }), \
             patch.object(wfar.wfirma_client, "find_vat_code_id",
                          return_value="VAT_23"), \
             patch.object(wfar.wfirma_client, "create_product",
                          return_value=SimpleNamespace(
                              wfirma_id="WF-NEW-002",
                              name="Pierścionek",
                              unit="szt.", code="EJL/26-27/121-2")):
            res = wfar._register_one(
                product_code   = "EJL/26-27/121-2",
                item_type      = "ring",
                description_en = "Gold Ring",
                dry_run        = False,
                operator       = "amit",
                batch_id       = "SHIPMENT_X",
            )
        assert res["status"] == "created"
        rows = cr.list_corrections(correction_type="product_mapping_override",
                                   entity_key="EJL/26-27/121-2")
        assert len(rows) == 1
        assert rows[0]["new_value"] == "WF-NEW-002"
        assert rows[0]["notes"]     == "created"

    def test_missing_does_not_log(self, isolated):
        with patch.object(wfar.wfirma_client, "get_product_by_code",
                          return_value=None):
            res = wfar._register_one(
                product_code   = "GHOST",
                item_type      = "",
                description_en = "",
                dry_run        = True,
                operator       = "amit",
                batch_id       = "SHIPMENT_X",
            )
        assert res["status"] == "missing"
        assert cr.list_corrections(correction_type="product_mapping_override",
                                   entity_key="GHOST") == []

    def test_blocked_does_not_log(self, isolated, monkeypatch):
        monkeypatch.setattr(wfar.settings, "wfirma_create_product_allowed",
                            False, raising=False)
        with patch.object(wfar.wfirma_client, "get_product_by_code",
                          return_value=None):
            res = wfar._register_one(
                product_code   = "BLOCKED-1",
                item_type      = "",
                description_en = "",
                dry_run        = False,
                operator       = "amit",
                batch_id       = "SHIPMENT_X",
            )
        assert res["status"] == "blocked"
        assert cr.list_corrections(correction_type="product_mapping_override",
                                   entity_key="BLOCKED-1") == []

    def test_logging_failure_does_not_break_action(self, isolated):
        existing = SimpleNamespace(wfirma_id="WF-X", name="x",
                                   unit="szt.", code="X")
        with patch.object(wfar.wfirma_client, "get_product_by_code",
                          return_value=existing), \
             patch.object(cr, "record_correction",
                          side_effect=RuntimeError("boom")):
            res = wfar._register_one(
                product_code   = "X",
                item_type      = "",
                description_en = "",
                dry_run        = True,
                operator       = "amit",
                batch_id       = "SHIPMENT_X",
            )
        # Action still succeeded
        assert res["status"] == "existing_mapped"
        assert res["wfirma_product_id"] == "WF-X"
        # Warning surfaced for the log failure
        assert any("correction_registry log failed" in w
                   for w in res["warnings"])

    def test_append_only_multiple_runs(self, isolated):
        existing = SimpleNamespace(wfirma_id="WF-A", name="x",
                                   unit="szt.", code="A")
        with patch.object(wfar.wfirma_client, "get_product_by_code",
                          return_value=existing):
            for _ in range(3):
                wfar._register_one(
                    product_code   = "A",
                    item_type      = "", description_en = "",
                    dry_run        = True,
                    operator       = "amit",
                    batch_id       = "SHIPMENT_X",
                )
        rows = cr.list_corrections(correction_type="product_mapping_override",
                                   entity_key="A")
        assert len(rows) == 3, "append-only: every run must add a new row"


# ── Customer auto-resolve ────────────────────────────────────────────────────

class TestCustomerResolve:
    def test_accepted_match_logs_accepted_match(self, isolated):
        # Seed wfirma_customers with a row the resolver will exact-match.
        wfdb.upsert_customer(
            client_name        = "Clear-Diamonds",
            wfirma_customer_id = "91254191",
            vat_id             = "GB123",
            country            = "GB",
            match_status       = "matched",
        )
        out = wfcar._resolve_one(
            "Clear-Diamonds",
            operator      = "amit",
            batch_id      = "SHIPMENT_Y",
            module_source = "wfirma_customer_auto_resolve",
        )
        assert out["status"] == "exact_match"
        rows = cr.list_corrections(correction_type="accepted_match",
                                   entity_key="Clear-Diamonds")
        assert len(rows) == 1
        r = rows[0]
        assert r["operator"] == "amit"
        assert r["batch_id"] == "SHIPMENT_Y"
        assert r["module_source"] == "wfirma_customer_auto_resolve"
        assert r["approved"] is True

    def test_ambiguous_logs_rejected_match(self, isolated, monkeypatch):
        # Two stored rows whose names BOTH start with the input → ambiguous.
        wfdb.upsert_customer(client_name="Acme Ltd",
                             wfirma_customer_id="111",
                             match_status="matched")
        wfdb.upsert_customer(client_name="Acme Limited Co",
                             wfirma_customer_id="222",
                             match_status="matched")
        out = wfcar._resolve_one(
            "Acme",
            operator      = "amit",
            batch_id      = "SHIPMENT_Y",
        )
        assert out["status"] == "ambiguous"
        rows = cr.list_corrections(correction_type="rejected_match",
                                   entity_key="Acme")
        assert len(rows) == 1
        r = rows[0]
        assert r["approved"] is False
        assert isinstance(r["new_value"], str)  # JSON-encoded payload
        assert "candidates" in r["new_value"]

    def test_missing_does_not_log(self, isolated):
        with patch.object(wfcar, "_search_live_candidates",
                          return_value=[]):
            out = wfcar._resolve_one(
                "Nobody Here",
                operator = "amit",
                batch_id = "SHIPMENT_Y",
            )
        assert out["status"] == "missing"
        assert cr.list_corrections(entity_key="Nobody Here") == []

    def test_logging_failure_does_not_break_resolve(self, isolated):
        wfdb.upsert_customer(client_name="ZZZ Co",
                             wfirma_customer_id="999",
                             match_status="matched")
        with patch.object(cr, "record_correction",
                          side_effect=RuntimeError("boom")):
            out = wfcar._resolve_one(
                "ZZZ Co",
                operator = "amit",
                batch_id = "SHIPMENT_Y",
            )
        assert out["status"] == "exact_match"
        assert out["wfirma_customer_id"] == "999"
        # Resolver appended a soft warning
        assert any("correction_registry log failed" in w
                   for w in out.get("warnings") or [])


# ── Customer auto-create ─────────────────────────────────────────────────────

class TestCustomerAutoCreate:
    def test_created_logs_customer_resolution_override(self, isolated, monkeypatch):
        monkeypatch.setattr(wfcar.settings, "wfirma_create_customer_allowed",
                            True, raising=False)
        # Ensure resolver returns "missing" so create proceeds.
        with patch.object(wfcar, "_resolve_one_core",
                          return_value={"status": "missing"}), \
             patch("app.services.wfirma_client.create_customer",
                   return_value=SimpleNamespace(
                       wfirma_id="WF-CUST-777",
                       name="Anastazia Panakova",
                       nip="SK0000000",
                       country="SK")):
            out = wfcar.create_one(
                client_name  = "Anastazia Panakova",
                vat_id       = "SK0000000",
                country_code = "SK",
                operator     = "amit",
            )
        assert out["status"]              == "created"
        assert out["wfirma_customer_id"]  == "WF-CUST-777"
        rows = cr.list_corrections(
            correction_type="customer_resolution_override",
            entity_key="Anastazia Panakova",
        )
        assert len(rows) == 1
        r = rows[0]
        assert r["operator"] == "amit"
        assert r["module_source"] == "wfirma_customer_auto_create"
        assert r["approved"] is True
        assert "WF-CUST-777" in r["new_value"]

    def test_pre_create_gate_does_not_log_resolution(self, isolated):
        """When the create gate refuses (resolver hit something), the
        gate must NOT also log a redundant accepted_match — the
        resolver core path is used precisely so logging is skipped.
        """
        wfdb.upsert_customer(client_name="Already-There",
                             wfirma_customer_id="555",
                             match_status="matched")
        out = wfcar.create_one(
            client_name = "Already-There",
            operator    = "amit",
        )
        assert out["status"] == "already_exists_or_ambiguous"
        # Pre-create gate must not produce its own accepted_match log.
        assert cr.list_corrections(entity_key="Already-There") == []


# ── Dashboard readiness GET must NOT mutate the registry ────────────────────

class TestDashboardReadinessNoMutation:
    def test_proforma_readiness_endpoint_writes_no_corrections(self, isolated, monkeypatch):
        """The aggregator endpoint reads only — no service calls into
        the auto-register / auto-resolve flows happen on GET."""
        from app.api.routes_dashboard import proforma_readiness
        # Aggregator is read-only and uses _resolve_local (not _resolve_one),
        # so even without DBs initialised it must produce zero registry rows.
        proforma_readiness("BATCH_DOES_NOT_EXIST")
        with cr._connect() as con:
            n = con.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
        assert n == 0
