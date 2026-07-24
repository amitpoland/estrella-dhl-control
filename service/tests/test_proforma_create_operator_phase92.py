"""
test_proforma_create_operator_phase92.py — Phase 9.2:
thread X-Operator through legacy /proforma/create route audit row.

Coverage:
  1. legacy create reads X-Operator and passes it into
     record_proforma_issued.
  2. Missing X-Operator falls back to "operator".
  3. Empty / whitespace X-Operator falls back to "operator".
  4. Phase 5 /post route still rejects empty X-Operator (strict
     mandatory header — regression guard, no behaviour change).
  5. Source-grep pins that the legacy route's signature accepts the
     header and the audit call no longer hard-codes operator="".
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_client


BATCH = "B-LEGACY-CREATE"
CLIENT = "ACME"


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    from app.main import app
    monkeypatch.setattr(settings, "wfirma_create_proforma_allowed", True)
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _stub_legacy_create_path(monkeypatch, db_path: Path):
    """Stub the heavy dependencies of the legacy /proforma/create route
    so we can exercise the flow end-to-end without setting up packing /
    documents / wfirma DBs.

    Returns the mutable ``captured`` dict that record_proforma_issued
    populates with its kwargs.
    """
    from app.api import routes_proforma as rp

    # Preview is already ready and has lines but no service charges.
    monkeypatch.setattr(
        rp, "_build_preview",
        lambda bid, cn, client_contractor_id="": {
            "draft_ready":      True,
            "ready":            True,
            "blocking_reasons": [],
            "export_blockers":  [],
            "currency":         "EUR",
            "exchange_rate":    None,
            "client_name":      cn,
            "lines": [
                {"product_code": "X", "design_no": "X",
                 "qty": 1, "unit_price": 1.0, "currency": "EUR"},
            ],
            "service_charges":  [],
        },
    )
    # Build a minimal ProformaRequest without resolving customers /
    # vat_codes / wfirma_products.
    monkeypatch.setattr(
        rp, "_build_proforma_request",
        # ADR-027: now returns (ProformaRequest, List[str]) tuple
        lambda preview, client_contractor_id="": (wfirma_client.ProformaRequest(
            client_name="ACME", client_zip="", client_city="",
            lines=[
                wfirma_client.ReservationLine(
                    product_code="X", wfirma_good_id="WFP-X",
                    product_name="X", qty=1.0, unit_price=1.0,
                    unit="szt.", currency="EUR",
                ),
            ],
            currency="EUR",
            wfirma_contractor_id="WF-CUST-1",
            vat_code_id="VAT-23",
            wfirma_contractor_receiver_id="",   # no preflight needed
        ), []),
    )
    # wFirma "live" call returns a successful ProformaResult including
    # the Phase 9 fullnumber field.
    monkeypatch.setattr(
        wfirma_client, "create_proforma_draft",
        lambda req: wfirma_client.ProformaResult(
            ok=True,
            wfirma_invoice_id="WF-LEG-9001",
            wfirma_invoice_number="PROF 92/2026",
        ),
    )

    # Capture the audit-record kwargs.
    captured: dict = {}
    def _fake_record(audit_path, **kwargs):
        captured.update(kwargs)
        return {"appended": True}
    monkeypatch.setattr(
        "app.services.audit_persist.record_proforma_issued", _fake_record,
    )
    return captured


def _ensure_pending_draft(db_path: Path):
    """The legacy route short-circuits if a draft already exists in
    pending_local/issued. We seed nothing; the route's
    upsert_pending_draft will create the row."""
    pildb.init_db(db_path)


# ── 1. Legacy create forwards X-Operator into the audit row ────────────────

def test_legacy_create_forwards_x_operator(client, tmp_path, monkeypatch):
    db_path = tmp_path / "proforma_links.db"
    _ensure_pending_draft(db_path)
    captured = _stub_legacy_create_path(monkeypatch, db_path)

    r = client.post(
        f"/api/v1/proforma/create/{BATCH}/{CLIENT}",
        headers={
            "X-API-KEY":  settings.api_key or "test-key",
            "X-Operator": "alice",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "issued"
    assert captured.get("operator") == "alice"
    # And the Phase-9 fullnumber rides through too.
    assert captured.get("wfirma_proforma_fullnumber") == "PROF 92/2026"


# ── 2. Missing X-Operator → safe fallback ─────────────────────────────────

def test_legacy_create_missing_x_operator_falls_back(client, tmp_path, monkeypatch):
    db_path = tmp_path / "proforma_links.db"
    _ensure_pending_draft(db_path)
    captured = _stub_legacy_create_path(monkeypatch, db_path)

    r = client.post(
        f"/api/v1/proforma/create/{BATCH}/{CLIENT}",
        headers={"X-API-KEY": settings.api_key or "test-key"},
        # NB: no X-Operator
    )
    assert r.status_code == 200, r.text
    # Safe fallback per the PZ flow's _operator_or_default rule.
    assert captured.get("operator") == "operator"


# ── 3. Empty / whitespace X-Operator → safe fallback ──────────────────────

@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_legacy_create_empty_x_operator_falls_back(client, tmp_path,
                                                     monkeypatch, value):
    db_path = tmp_path / "proforma_links.db"
    _ensure_pending_draft(db_path)
    captured = _stub_legacy_create_path(monkeypatch, db_path)

    r = client.post(
        f"/api/v1/proforma/create/{BATCH}/{CLIENT}",
        headers={
            "X-API-KEY":  settings.api_key or "test-key",
            "X-Operator": value,
        },
    )
    assert r.status_code == 200, r.text
    assert captured.get("operator") == "operator"


# ── 4. Phase 5 /post route still strict ───────────────────────────────────

def test_phase5_post_still_requires_x_operator(client, tmp_path, monkeypatch):
    """Phase 5 must keep its strict mandatory X-Operator gate. Phase 9.2
    only relaxes the LEGACY route — never the Phase-5 flow."""
    db = tmp_path / "proforma_links.db"
    pildb.init_db(db)
    d, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="ACME", currency="EUR",
        lines=[{"product_code": "X", "design_no": "X",
                 "qty": 1, "unit_price": 1.0, "currency": "EUR"}],
    )
    approved = pildb.approve_draft(
        db, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    # No X-Operator header → must 400.
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": approved.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers={"X-API-KEY": settings.api_key or "test-key"},
    )
    assert r.status_code == 400
    assert "X-Operator" in r.json()["detail"]


# ── 5. Source-grep wiring contract ────────────────────────────────────────

ROUTES_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_proforma.py"
)


def test_legacy_route_signature_accepts_x_operator():
    """The legacy create handler must declare an X-Operator Header
    binding so FastAPI surfaces the value to the function body."""
    src = ROUTES_PATH.read_text(encoding="utf-8")
    needle = "def proforma_create("
    idx = src.find(needle)
    assert idx > 0
    # Walk to the closing ')' of the signature.
    open_paren = idx + len(needle) - 1
    depth = 0
    end = open_paren
    for j in range(open_paren, len(src)):
        c = src[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = j
                break
    sig = src[idx:end + 1]
    assert "x_operator" in sig
    assert 'alias="X-Operator"' in sig


def test_legacy_route_no_longer_hardcodes_empty_operator():
    """Sanity: the old `operator = "",` literal that this phase replaced
    must be gone from the legacy create route's audit call. (Other
    routes that legitimately still pass operator="" stay untouched —
    we look only inside the proforma_create handler block.)"""
    src = ROUTES_PATH.read_text(encoding="utf-8")
    needle = "def proforma_create("
    idx = src.find(needle)
    assert idx > 0
    # The handler ends at the next `def ` or `@router.` at column 0.
    end = src.find("\n@router.", idx + 1)
    if end == -1:
        end = len(src)
    block = src[idx:end]
    assert 'operator           = ""' not in block, (
        "Legacy create must no longer hard-code operator='' — Phase 9.2 "
        "threads X-Operator with a safe fallback"
    )
    # And the new fallback expression is present.
    assert '(x_operator or "").strip()' in block
    assert '"operator"' in block
