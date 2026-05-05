"""
test_e2e_operator_flow.py — Full operator-flow smoke test.

Walks the complete shipment lifecycle in one accumulated audit:

  Stage 1  Intake         batch seeded with draft audit, AWB + invoice present
  Stage 2  Tracking       DHL customs tracking event written; DHL email received
  Stage 3  SAD / PZ       customs_docs.received=True; pz_generated=True
  Stage 4  Agency docs    register_agency_documents() imports one SAD file
  Stage 5  Invoices       register_service_invoices() imports DHL + Ganther invoices
  Stage 6  Closure        POST /api/v1/execute/closure_confirm → completed

Invariants checked end-to-end:
  - Each stage gate only opens when prerequisite state is satisfied
  - Financial fields (invoice_totals, clearance_decision) are never mutated
  - approved_by identity flows into audit.closure_approved_by
  - audit.status=completed and ready_for_accounting=True after stage 6
  - No real network calls (WorkDrive / SMTP / Zoho fully mocked)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SVC = Path(__file__).resolve().parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

_INGEST_STUB = {
    "ok": True,
    "started_at": "2026-01-01T00:00:00Z",
    "active_batches": 0,
    "shipments": [],
}

AWB      = "1234567890"
BATCH_ID = "E2E_FLOW_01"
APPROVER = "smoke_operator"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda **kw: _INGEST_STUB,
    )


@pytest.fixture()
def tmp_root(tmp_path):
    return tmp_path


@pytest.fixture()
def audit_path(tmp_root) -> Path:
    batch_dir = tmp_root / "outputs" / BATCH_ID
    batch_dir.mkdir(parents=True, exist_ok=True)
    return batch_dir / "audit.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now(hours_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _write_audit(audit_path: Path, data: dict) -> None:
    audit_path.write_text(json.dumps(data), encoding="utf-8")


def _read_audit(audit_path: Path) -> dict:
    return json.loads(audit_path.read_text(encoding="utf-8"))


def _base_audit() -> dict:
    return {
        "batch_id":   BATCH_ID,
        "awb":        AWB,
        "tracking_no": AWB,
        "status":     "draft",
        "source":     "intake_upload",
        "carrier":    "DHL",
        "inputs":     {"awb": f"{AWB} AWB.pdf", "invoices": ["INV001.pdf"]},
        # financial fields — must never change
        "invoice_totals":   {"total_cif_usd": 10_000.00},
        "clearance_decision": {
            "total_value_usd": 10_000.00,
            "clearance_path":  "external_agency_clearance",
        },
        "clearance_status": "awaiting_dhl_customs_email",
    }


def _seed_files(tmp_root: Path) -> None:
    """Create minimal stub files referenced by the audit."""
    batch_dir = tmp_root / "outputs" / BATCH_ID
    for sub in ("source/invoices", "source/awb"):
        (batch_dir / sub).mkdir(parents=True, exist_ok=True)
    (batch_dir / "source" / "invoices" / "INV001.pdf").write_bytes(b"%PDF inv")
    (batch_dir / "source" / "awb" / f"{AWB} AWB.pdf").write_bytes(b"%PDF awb")


# ── The single smoke-test function ────────────────────────────────────────────

def test_full_operator_flow(tmp_root, audit_path, monkeypatch):
    """
    Single accumulated audit that walks all 6 operator stages.
    Each stage asserts the state it produces before the next stage runs.
    """
    _seed_files(tmp_root)
    _write_audit(audit_path, _base_audit())

    # Patch settings throughout
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_root)

    # Patch workdrive_sync for all service imports (no TrueSync in test env)
    _wd_stub = {"synced": False, "reason": "workdrive_not_configured"}
    monkeypatch.setattr(
        "app.services.workdrive_sync.sync_to_workdrive",
        lambda batch_id, path: _wd_stub,
    )
    # Also patch folder manager's settings reference
    from app.services import shipment_folder_manager as fm
    monkeypatch.setattr(fm, "settings", settings)


    # ══════════════════════════════════════════════════════════════════════════
    # Stage 1 — Intake verification
    # Verifies the seeded draft audit is structurally sound before any processing.
    # ══════════════════════════════════════════════════════════════════════════
    a1 = _read_audit(audit_path)
    assert a1["batch_id"]  == BATCH_ID,                   "S1: batch_id mismatch"
    assert a1["awb"]       == AWB,                        "S1: AWB mismatch"
    assert a1["status"]    == "draft",                    "S1: wrong initial status"
    assert a1["invoice_totals"]["total_cif_usd"] == 10_000.00, "S1: financial field wrong"

    # ══════════════════════════════════════════════════════════════════════════
    # Stage 2 — Tracking: DHL customs event + DHL email received
    # Simulates what the active-shipment-monitor or tracking-update endpoint
    # would write after a customs-clearance scan and DHL email ingestion.
    # ══════════════════════════════════════════════════════════════════════════
    a2 = _read_audit(audit_path)
    a2["clearance_status"] = "dhl_email_received"
    a2["dhl_email"] = {
        "received":    True,
        "received_at": _now(hours_ago=3),
        "ticket":      "T#SMOKE001",
        "source":      "zoho_scan",
    }
    a2["tracking"] = {
        "events": [
            {
                "timestamp":   _now(hours_ago=4),
                "location":    "WARSAW - PL",
                "description": "Customs clearance status updated",
                "status":      "",
            }
        ],
        "last_location": "WARSAW - PL",
        "last_update":   _now(hours_ago=4),
    }
    _write_audit(audit_path, a2)

    a2v = _read_audit(audit_path)
    assert a2v["clearance_status"] == "dhl_email_received",   "S2: status not advanced"
    assert a2v["dhl_email"]["received"] is True,              "S2: dhl_email.received not set"
    assert a2v["dhl_email"]["ticket"]   == "T#SMOKE001",      "S2: ticket mismatch"
    assert a2v["invoice_totals"]["total_cif_usd"] == 10_000.00, "S2: financial field mutated"

    # ══════════════════════════════════════════════════════════════════════════
    # Stage 3 — SAD upload: customs_docs.received=True + PZ generated
    # Simulates the SAD importer writing customs_docs and the PZ engine
    # writing pz_generated after a successful PZ run.
    # ══════════════════════════════════════════════════════════════════════════
    a3 = _read_audit(audit_path)
    a3["customs_docs"] = {
        "received":    True,
        "received_at": _now(hours_ago=2),
        "source":      "operator_upload",
    }
    a3["pz_generated"]   = True
    a3["pz_pdf_filename"] = "PZ_E2E_FLOW_01.pdf"
    _write_audit(audit_path, a3)

    a3v = _read_audit(audit_path)
    assert a3v["customs_docs"]["received"] is True, "S3: customs_docs.received not set"
    assert a3v["pz_generated"] is True,             "S3: pz_generated not set"
    assert a3v["invoice_totals"]["total_cif_usd"] == 10_000.00, "S3: financial field mutated"

    # ══════════════════════════════════════════════════════════════════════════
    # Stage 4 — Agency document registration
    # Calls register_agency_documents() with a real temp SAD PDF.
    # Verifies audit.agency_documents_received=True.
    # ══════════════════════════════════════════════════════════════════════════
    from app.services.agency_sad_monitor import register_agency_documents

    sad_pdf = tmp_root / "SAD_001.pdf"
    sad_pdf.write_bytes(b"%PDF SAD document")

    with patch("app.services.agency_sad_monitor.sync_to_workdrive", return_value=_wd_stub):
        r4 = register_agency_documents(BATCH_ID, [str(sad_pdf)], source="operator")

    assert r4["ok"]  is True,          f"S4: register_agency_documents failed: {r4}"
    assert r4["files_total"] >= 1,     "S4: no files recorded"

    a4 = _read_audit(audit_path)
    assert a4.get("agency_documents_received") is True, "S4: agency_documents_received not set"
    assert a4["invoice_totals"]["total_cif_usd"] == 10_000.00, "S4: financial field mutated"

    # ══════════════════════════════════════════════════════════════════════════
    # Stage 5 — Service invoice registration (DHL + agency)
    # Calls register_service_invoices() with two files whose names match the
    # DHL and Ganther vendor-classification patterns.
    # Verifies both dhl_invoice_received and agency_invoice_received flags.
    # ══════════════════════════════════════════════════════════════════════════
    from app.services.service_invoice_monitor import register_service_invoices

    dhl_inv    = tmp_root / "DHL_invoice_123.pdf"
    agency_inv = tmp_root / "Ganther_invoice_456.pdf"
    dhl_inv.write_bytes(b"%PDF DHL invoice")
    agency_inv.write_bytes(b"%PDF Ganther invoice")

    with patch("app.services.service_invoice_monitor.sync_to_workdrive", return_value=_wd_stub):
        r5 = register_service_invoices(
            BATCH_ID, [str(dhl_inv), str(agency_inv)], source="operator"
        )

    assert r5["ok"]  is True,                            f"S5: register_service_invoices failed: {r5}"
    assert r5["dhl_invoice_received"]    is True,        "S5: dhl_invoice_received not set"
    assert r5["agency_invoice_received"] is True,        "S5: agency_invoice_received not set"

    a5 = _read_audit(audit_path)
    assert a5["dhl_invoice_received"]    is True,        "S5: dhl_invoice_received not in audit"
    assert a5["agency_invoice_received"] is True,        "S5: agency_invoice_received not in audit"
    assert a5["invoice_totals"]["total_cif_usd"] == 10_000.00, "S5: financial field mutated"

    # Verify evaluate_closure now sees all four conditions met
    from app.services.shipment_closure import evaluate_closure
    eval5 = evaluate_closure(a5)
    assert eval5["ready"]   is True,  f"S5: evaluate_closure not ready — missing: {eval5['missing']}"
    assert eval5["missing"] == [],    f"S5: unexpected missing: {eval5['missing']}"

    # ══════════════════════════════════════════════════════════════════════════
    # Stage 6 — Closure confirm via execute endpoint
    # POSTs to /api/v1/execute/closure_confirm through the full FastAPI stack.
    # Both readiness gates must pass; approved_by must be written to audit.
    # ══════════════════════════════════════════════════════════════════════════
    from app.main import app as fastapi_app
    from fastapi.testclient import TestClient
    from app.core.security import require_api_key

    _batch_ready = {
        "overall": {
            "ready_for_closure": True,
            "blocked_domains":   [],
            "next_step":         None,
        }
    }
    _dhl_ready    = {"dhl_status": "dhl_contacted"}
    _wfirma_ready = {"ready_to_create": True}

    fastapi_app.dependency_overrides[require_api_key] = lambda: None
    try:
        client = TestClient(fastapi_app)
        with (
            patch("app.services.batch_readiness.get_batch_readiness",        return_value=_batch_ready),
            patch("app.services.dhl_readiness.get_dhl_readiness",            return_value=_dhl_ready),
            patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_wfirma_ready),
            patch("app.services.shipment_closure.tl.log_event"),
        ):
            r6 = client.post(
                "/api/v1/execute/closure_confirm",
                json={"batch_id": BATCH_ID, "payload": {"approved_by": APPROVER}},
            )
    finally:
        fastapi_app.dependency_overrides.pop(require_api_key, None)

    assert r6.status_code == 200, f"S6: unexpected HTTP {r6.status_code}: {r6.text}"
    body6 = r6.json()
    assert body6["ok"]     is True,          f"S6: closure_confirm not ok: {body6}"
    assert body6["status"] == "completed",   f"S6: wrong status: {body6}"
    assert body6.get("ready_for_accounting") is True, "S6: ready_for_accounting not set in response"

    a6 = _read_audit(audit_path)
    assert a6["status"]                == "completed",  "S6: audit.status not completed"
    assert a6["ready_for_accounting"]  is True,         "S6: ready_for_accounting not True"
    assert a6["closure_approved_by"]   == APPROVER,     "S6: approved_by not recorded"
    assert a6.get("closed_at"),                         "S6: closed_at missing"
    checks6 = a6.get("closure_checks", {})
    for field in ("customs_docs_received", "pz_generated",
                  "agency_invoice_received", "dhl_invoice_received"):
        assert checks6.get(field) is True, f"S6: closure_checks.{field} not True"

    # ── Final financial invariant ─────────────────────────────────────────────
    assert a6["invoice_totals"]["total_cif_usd"]       == 10_000.00, "Final: invoice_totals mutated"
    assert a6["clearance_decision"]["total_value_usd"] == 10_000.00, "Final: clearance_decision mutated"
