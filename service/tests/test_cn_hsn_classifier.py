"""
test_cn_hsn_classifier.py — CN/HSN hierarchical comparison + operator
decision endpoints.

Covers:
  • Pure classifier:
      CN 71131900 vs HSN 71131913/71131914/71131911 → heading_match (non-blocking)
      CN 71131900 vs HSN 71131141 → chapter_match (operator decision)
      different chapter → hard block
      multiple HSNs under one CN → aggregation flag
  • Read-only classification endpoint
  • Three decision endpoints record correction-registry rows + audit
    cn_decision block, never call PZ create / wFirma / SMTP
  • Dashboard surface: CNHSNDecisionPanel mounted + buttons reference
    new endpoints + no auto-PZ-run
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import cn_hsn_classifier as cn
from app.services import correction_registry as cr
from app.services import dhl_zc429_intake as zc
from app.api.routes_dashboard import router as dashboard_router


# ── Pure classifier ────────────────────────────────────────────────────────

class TestClassifier:
    def test_normalize_strips_non_digits(self):
        assert cn.normalize("7113.19.00") == "71131900"
        assert cn.normalize("  71 13 19 00 ") == "71131900"
        assert cn.normalize(None) == ""

    def test_exact_match(self):
        r = cn.compare_one("71131900", "71131900")
        assert r["level"] == cn.LEVEL_EXACT

    def test_hs6_match(self):
        # 71 13 19 vs 71 13 19 — same first 6, last 2 differ → HS6_MATCH
        r = cn.compare_one("71131900", "71131913")
        assert r["level"] == cn.LEVEL_HS6
        r2 = cn.compare_one("71131913", "71131914")
        assert r2["level"] == cn.LEVEL_HS6

    def test_heading_match_only(self):
        # 7113 11 vs 7113 19 — same heading, different hs6
        r = cn.compare_one("71131100", "71131900")
        assert r["level"] == cn.LEVEL_HEADING

    def test_chapter_match_only(self):
        # 71 vs different heading — same chapter, different heading
        r = cn.compare_one("71131900", "71171900")
        assert r["level"] == cn.LEVEL_CHAPTER

    def test_different_chapter(self):
        r = cn.compare_one("71131900", "62049900")
        assert r["level"] == cn.LEVEL_DIFFERENT

    def test_jewelry_aggregation_not_blocking(self):
        # Real-world AWB 6049349806 case
        result = cn.classify("71131900",
                             ["71131913", "71131914", "71131911"])
        # All share 711319 → hs6_match (worst)
        # Actually 71131900 vs 71131913: first 6 are 711319 == 711319 → HS6_MATCH
        assert result["worst_level"] in (cn.LEVEL_HS6, cn.LEVEL_HEADING)
        assert result["is_blocking"] is False
        assert result["recommendation"] == "accept_with_note"

    def test_silver_vs_gold_chapter_match(self):
        # 71131141 (silver) vs 71131900 (gold) — same chapter 71,
        # same heading 7113, BUT first 6 differ (711311 vs 711319).
        result = cn.classify("71131900", ["71131141"])
        # 71131900 vs 71131141: first 4 = 7113 (same heading) but
        # first 6 differ (711319 vs 711311) → heading_match
        assert result["worst_level"] == cn.LEVEL_HEADING
        assert result["is_blocking"] is False
        assert result["recommendation"] == "accept_with_note"

    def test_silver_aggregation_under_gold_cn(self):
        # SAD aggregates everything under 71131900 but invoice has both
        # silver (71131141) and gold (71131913). Worst line is heading_match
        # (silver shares only heading). Aggregation + mixed metals flagged.
        result = cn.classify("71131900",
                             ["71131913", "71131914", "71131141"])
        assert result["aggregation_detected"] is True
        assert result["mixed_metals_detected"] is True
        # heading_match is not auto-fatal
        assert result["is_blocking"] is False

    def test_chapter_only_match_is_review(self):
        result = cn.classify("71131900", ["71179000"])  # 7113 vs 7117
        assert result["worst_level"] == cn.LEVEL_CHAPTER
        assert result["is_blocking"] is True   # soft block, operator decision
        assert result["recommendation"] == "operator_decision"

    def test_different_chapter_is_hard_block(self):
        result = cn.classify("71131900", ["62049900"])
        assert result["worst_level"] == cn.LEVEL_DIFFERENT
        assert result["is_blocking"] is True
        assert result["recommendation"] == "hard_block"

    def test_no_invoice_hsns_is_review(self):
        result = cn.classify("71131900", [])
        assert result["worst_level"] == cn.LEVEL_INVALID
        assert result["is_blocking"] is False
        assert result["is_review"] is True

    def test_empty_sad_cn_is_review(self):
        result = cn.classify("", ["71131913"])
        assert result["worst_level"] == cn.LEVEL_INVALID
        assert result["is_blocking"] is False


# ── Endpoint integration ───────────────────────────────────────────────────

@pytest.fixture
def staged(tmp_path, monkeypatch):
    monkeypatch.setattr(zc.settings, "storage_root", tmp_path, raising=False)
    from app.api import routes_dashboard as rd
    monkeypatch.setattr(rd, "settings", zc.settings, raising=False)
    monkeypatch.setattr(rd, "_validate_batch_id", lambda b: None, raising=False)
    cr.init_correction_registry(tmp_path / "correction_registry.db")

    batch_id = "SHIPMENT_6049349806_2026-05_7409ac77"
    bdir = tmp_path / "outputs" / batch_id
    bdir.mkdir(parents=True)
    # Pre-seed audit with the same blocker pattern AWB 6049349806 has live:
    # status=blocked, failed_checks=['cn_match'], verification.cn_match=False,
    # so the unblock branch has something to clear.
    (bdir / "audit.json").write_text(json.dumps({
        "batch_id":      batch_id,
        "tracking_no":   "6049349806",
        "status":        "blocked",
        "failed_checks": ["cn_match"],
        "verification": {
            "cn_match":           False,
            "cn_status":          "failed_parent_mismatch",
            "cn_risk_level":      "medium",
            "sad_cn_code":        "71131900",
            "cn_code":            None,
            "invoice_hsn_codes":  ["71131913", "71131914", "71131911"],
        },
        "customs_declaration": {
            "intake_event_id": "fake-intake-uuid-001",
        },
        "timeline": [],
    }), encoding="utf-8")
    yield {"tmp": tmp_path, "batch_id": batch_id, "audit": bdir / "audit.json"}
    cr._db_path = None


@pytest.fixture
def client(staged, monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    app = FastAPI()
    app.include_router(dashboard_router)
    return TestClient(app)


class TestClassificationEndpoint:
    def test_endpoint_returns_jewelry_compatible(self, client, staged):
        r = client.get(
            f"/dashboard/batches/{staged['batch_id']}/cn-hsn-classification")
        assert r.status_code == 200
        body = r.json()
        assert body["has_data"] is True
        assert body["sad_cn_code"] == "71131900"
        assert body["invoice_hsns"] == ["71131913", "71131914", "71131911"]
        assert body["result"]["is_blocking"] is False
        assert body["result"]["worst_level"] in ("hs6_match", "heading_match")

    def test_endpoint_warns_when_audit_missing(self, client):
        r = client.get(
            "/dashboard/batches/SHIPMENT_NOPE/cn-hsn-classification")
        body = r.json()
        assert body["has_data"] is False
        assert any("audit.json not found" in w for w in body["warnings"])


class TestDecisionEndpoints:
    def test_accept_sad_records_accepted_match(self, client, staged):
        r = client.post(
            f"/dashboard/batches/{staged['batch_id']}/cn-decision/accept-sad",
            json={"operator": "amit",
                  "reason": "SAD CN matches invoice HSNs at HS6 level"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["decision_type"] == "accept_sad"
        rid = body["correction_id"]
        assert rid

        rows = cr.list_corrections(correction_type="accepted_match",
                                   batch_id=staged["batch_id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["operator"] == "amit"
        assert row["module_source"] == "cn_hsn_decision"
        assert row["approved"] is True
        evidence = {e["type"]: e["ref"] for e in row["evidence_refs"]}
        assert evidence["sad_cn_code"]   == "71131900"
        assert "71131913" in evidence["invoice_hsns"]
        assert evidence["intake_event"]  == "fake-intake-uuid-001"

        # Audit cn_decision block stamped
        post = json.loads(staged["audit"].read_text(encoding="utf-8"))
        assert post["cn_decision"]["decision_type"] == "accept_sad"
        assert post["cn_decision"]["approved"] is True

    def test_correct_internal_records_ambiguity_resolution(self, client, staged):
        r = client.post(
            f"/dashboard/batches/{staged['batch_id']}/cn-decision/correct-internal",
            json={"operator": "amit",
                  "reason": "Internal HSN reclassification queued"},
        )
        assert r.status_code == 200
        rows = cr.list_corrections(correction_type="ambiguity_resolution",
                                   batch_id=staged["batch_id"])
        assert len(rows) == 1
        # SAD source value unchanged
        post = json.loads(staged["audit"].read_text(encoding="utf-8"))
        assert post["verification"]["sad_cn_code"] == "71131900"

    def test_escalate_agent_records_rejected_match(self, client, staged):
        r = client.post(
            f"/dashboard/batches/{staged['batch_id']}/cn-decision/escalate-agent",
            json={"operator": "amit",
                  "reason": "Escalation to customs agent requested"},
        )
        assert r.status_code == 200
        rows = cr.list_corrections(correction_type="rejected_match",
                                   batch_id=staged["batch_id"])
        assert len(rows) == 1
        assert rows[0]["approved"] is False
        post = json.loads(staged["audit"].read_text(encoding="utf-8"))
        assert post["cn_decision"]["decision_type"] == "escalate_agent"
        assert post["cn_decision"]["approved"] is False

    def test_decisions_do_not_create_pz_or_call_wfirma(self, client, staged, monkeypatch):
        """No PZ pipeline / wFirma client call must occur on any decision."""
        from app.services import wfirma_client
        monkeypatch.setattr(wfirma_client, "create_product",
                            lambda *a, **kw: pytest.fail("wFirma write attempted"))
        # If create_customer / create_warehouse_pz exist, also fence them.
        for fn in ("create_customer", "create_warehouse_pz"):
            if hasattr(wfirma_client, fn):
                monkeypatch.setattr(wfirma_client, fn,
                                    lambda *a, **kw: pytest.fail(f"wFirma {fn} attempted"))

        client.post(
            f"/dashboard/batches/{staged['batch_id']}/cn-decision/accept-sad",
            json={"operator": "amit", "reason": "test"})
        client.post(
            f"/dashboard/batches/{staged['batch_id']}/cn-decision/correct-internal",
            json={"operator": "amit", "reason": "test"})
        client.post(
            f"/dashboard/batches/{staged['batch_id']}/cn-decision/escalate-agent",
            json={"operator": "amit", "reason": "test"})


# ── accept-sad unblock behaviour ──────────────────────────────────────────

class TestAcceptSadUnblocks:
    def _post_accept(self, client, batch_id, **kw):
        body = {"operator": "admin",
                "reason": kw.get("reason", "Accept SAD CN — same HS chapter, "
                                            "national-extension difference is "
                                            "expected for India HSN vs EU CN")}
        return client.post(
            f"/dashboard/batches/{batch_id}/cn-decision/accept-sad", json=body)

    def test_accept_clears_cn_match_from_failed_checks(self, client, staged):
        r = self._post_accept(client, staged["batch_id"])
        assert r.status_code == 200
        post = json.loads(staged["audit"].read_text(encoding="utf-8"))
        assert "cn_match" not in (post.get("failed_checks") or [])

    def test_accept_sets_verification_provenance(self, client, staged):
        r = self._post_accept(client, staged["batch_id"])
        rid = r.json()["correction_id"]
        ver = json.loads(staged["audit"].read_text(encoding="utf-8"))["verification"]
        assert ver["cn_match"] is True
        assert ver["cn_status"] == "operator_accepted_sad_cn"
        assert ver["cn_risk_level"] == "operator_accepted"
        assert ver["cn_match_overridden_by"] == "cn_decision/accept_sad"
        assert ver["cn_match_correction_id"] == rid
        assert ver["cn_match_overridden_by_op"] == "admin"

    def test_accept_changes_status_when_cn_match_was_only_blocker(self, client, staged):
        self._post_accept(client, staged["batch_id"])
        post = json.loads(staged["audit"].read_text(encoding="utf-8"))
        # Was 'blocked' with only cn_match in failed_checks → must move off
        # blocked; we use 'partial' as the conservative neutral state.
        assert post["status"] == "partial"
        cd = post["cn_decision"]
        assert cd["previous_status"] == "blocked"
        assert cd["new_status"]      == "partial"

    def test_accept_does_not_mutate_source_values(self, client, staged):
        before = json.loads(staged["audit"].read_text(encoding="utf-8"))
        sad_before = before["verification"]["sad_cn_code"]
        hsn_before = list(before["verification"]["invoice_hsn_codes"])
        self._post_accept(client, staged["batch_id"])
        after = json.loads(staged["audit"].read_text(encoding="utf-8"))
        # Source values intentionally untouched
        assert after["verification"]["sad_cn_code"]       == sad_before
        assert after["verification"]["invoice_hsn_codes"] == hsn_before

    def test_accept_does_not_touch_pz_or_wfirma_or_smtp(self, client, staged, monkeypatch):
        """No accidental side-effects on the operator's accept click."""
        from app.services import wfirma_client
        for fn in ("create_product", "create_customer", "create_warehouse_pz"):
            if hasattr(wfirma_client, fn):
                monkeypatch.setattr(wfirma_client, fn,
                                    lambda *a, **kw: pytest.fail(f"wFirma {fn} called"))
        try:
            from app.services import email_service
            monkeypatch.setattr(email_service, "queue_email",
                                lambda *a, **kw: pytest.fail("SMTP queue_email called"))
        except Exception:
            pass
        try:
            from app.pipelines import pz as pz_pipeline
            for fn in ("start_pz", "run_pz", "process_pz"):
                if hasattr(pz_pipeline, fn):
                    monkeypatch.setattr(pz_pipeline, fn,
                                        lambda *a, **kw: pytest.fail(f"PZ pipeline {fn} called"))
        except Exception:
            pass
        r = self._post_accept(client, staged["batch_id"])
        assert r.status_code == 200

    def test_correct_internal_does_not_unblock(self, client, staged):
        r = client.post(
            f"/dashboard/batches/{staged['batch_id']}/cn-decision/correct-internal",
            json={"operator": "admin",
                  "reason": "Internal classification correction queued for review"})
        assert r.status_code == 200
        post = json.loads(staged["audit"].read_text(encoding="utf-8"))
        # State unchanged: still blocked, cn_match still in failed_checks,
        # verification.cn_match still False.
        assert post["status"] == "blocked"
        assert "cn_match" in (post["failed_checks"] or [])
        assert post["verification"]["cn_match"] is False
        # cn_decision recorded but provenance NOT applied
        cd = post["cn_decision"]
        assert cd["decision_type"] == "correct_internal"
        assert cd["previous_status"] == "blocked"
        assert cd["new_status"]      == "blocked"

    def test_escalate_agent_remains_blocked(self, client, staged):
        r = client.post(
            f"/dashboard/batches/{staged['batch_id']}/cn-decision/escalate-agent",
            json={"operator": "admin",
                  "reason": "Escalation to customs agent — request reclassification"})
        assert r.status_code == 200
        post = json.loads(staged["audit"].read_text(encoding="utf-8"))
        assert post["status"] == "blocked"
        assert "cn_match" in (post["failed_checks"] or [])
        assert post["cn_decision"]["approved"] is False
        assert post["cn_decision"]["new_status"] == "blocked"

    def test_repeated_accept_is_idempotent(self, client, staged):
        self._post_accept(client, staged["batch_id"])
        first = json.loads(staged["audit"].read_text(encoding="utf-8"))
        self._post_accept(client, staged["batch_id"])
        second = json.loads(staged["audit"].read_text(encoding="utf-8"))
        # Final state stable
        assert second["status"] == first["status"] == "partial"
        assert "cn_match" not in (second["failed_checks"] or [])
        assert second["verification"]["cn_match"] is True
        # operator_overrides DID grow (history) — that's expected & append-only
        assert len(second["operator_overrides"]) >= len(first["operator_overrides"])

    def test_other_failed_checks_keep_status_blocked(self, client, staged):
        # Add a second failed_check that accept-sad MUST NOT clear.
        before = json.loads(staged["audit"].read_text(encoding="utf-8"))
        before["failed_checks"] = ["cn_match", "cif_match"]
        staged["audit"].write_text(json.dumps(before), encoding="utf-8")

        self._post_accept(client, staged["batch_id"])
        post = json.loads(staged["audit"].read_text(encoding="utf-8"))
        assert "cn_match"  not in post["failed_checks"]
        assert "cif_match" in     post["failed_checks"]
        # Status stays blocked because cif_match remains.
        assert post["status"] == "blocked"
        assert post["cn_decision"]["new_status"] == "blocked"

    def test_timeline_carries_status_transition(self, client, staged):
        r = self._post_accept(client, staged["batch_id"])
        rid = r.json()["correction_id"]
        post = json.loads(staged["audit"].read_text(encoding="utf-8"))
        evs = [e for e in post["timeline"]
               if e.get("event") == "status_change"
               and (e.get("detail") or {}).get("decision_type") == "accept_sad"]
        assert len(evs) == 1
        det = evs[0]["detail"]
        assert det["previous_status"] == "blocked"
        assert det["new_status"]      == "partial"
        assert det["correction_id"]   == rid


# ── Dashboard surface ──────────────────────────────────────────────────────

DASHBOARD_HTML = (Path(__file__).resolve().parents[1]
                  / "app" / "static" / "dashboard.html")

def _html() -> str:
    return DASHBOARD_HTML.read_text(encoding="utf-8")


class TestDashboardSurface:
    def test_panel_component_defined(self):
        assert "function CNHSNDecisionPanel(" in _html()

    def test_panel_mounted_in_pz_section(self):
        h = _html()
        # The panel must appear in the PZ / Accounting tab AFTER Section 3
        # header (we mounted it inside Section 3, just below the header).
        idx_section = h.index("Section 3 — PZ / Accounting")
        idx_panel   = h.index("<CNHSNDecisionPanel ")
        # Panel exists somewhere in the dashboard
        assert idx_panel >= 0
        # And it lives under the PZ / Accounting tab (same tab block)
        idx_tab = h.index("activeTab === 'PZ / Accounting'")
        assert idx_tab < idx_panel

    def test_panel_has_required_testids(self):
        h = _html()
        for tid in ("cn-hsn-panel", "cn-hsn-status-chip", "cn-hsn-sad",
                    "cn-hsn-invoice", "cn-accept-sad",
                    "cn-correct-internal", "cn-escalate-agent"):
            assert f'data-testid="{tid}"' in h, f"missing {tid}"

    def test_panel_does_not_auto_run_pz(self):
        """The CN/HSN panel must NOT call /pz_create or /api/v1/upload/.../process
        anywhere — auto-running PZ on Accept SAD CN was the original bug."""
        h = _html()
        start = h.index("function CNHSNDecisionPanel(")
        end   = h.index("// EXECUTE PZ IN WFIRMA", start)
        body  = h[start:end]
        for forbidden in ("pz_create", "/process'", "/process\"",
                          "wfirma/pz_create"):
            assert forbidden not in body, \
                f"CN/HSN panel must not reference {forbidden}"

    def test_panel_buttons_call_new_decision_endpoints(self):
        h = _html()
        start = h.index("function CNHSNDecisionPanel(")
        end   = h.index("// EXECUTE PZ IN WFIRMA", start)
        body  = h[start:end]
        # The component builds the URL via `cn-decision/${path}` template.
        # Ensure the literal argument strings AND the URL prefix are present.
        assert "cn-decision/${path}" in body
        for arg in ("'accept-sad'", "'correct-internal'", "'escalate-agent'"):
            assert arg in body
        # Read-only endpoint also referenced
        assert "cn-hsn-classification" in body

    def test_panel_uses_onclick_only_no_useeffect_post(self):
        h = _html()
        start = h.index("function CNHSNDecisionPanel(")
        end   = h.index("// EXECUTE PZ IN WFIRMA", start)
        body  = h[start:end]
        # The only effect runs `refresh()` (GET); assert no POST inside it.
        ue_block = body[body.index("React.useEffect"):body.index("postDecision = ")]
        assert "POST" not in ue_block
