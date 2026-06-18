"""test_vision_invoice_confirm_route.py — POST /dashboard/batches/{batch_id}/vision-invoice/confirm.

Route-level HTTP tests for the PR-2 operator-confirm endpoint. The service-layer
behaviour (sole-writer, sticky guard, layer isolation, idempotency, supplier
crosscheck) is pinned in test_vision_invoice_confirm.py; THIS file pins the HTTP
contract the service tests cannot reach:

  * happy path → 200, operator_confirmed=true, confirmed_by = authenticated user,
    next_step disclosure present (PZ still blocked)
  * no proposal → 409
  * missing batch → 404
  * path-traversal batch_id → 400 (guard, before any filesystem touch)
  * unauthenticated → 401/403 (require_role gate)
  * operator identity comes from the SERVER-SIDE authenticated user, never a
    client header/body; confirmed_by is the real full_name (no ghost identity)
  * idempotent second confirm over HTTP → 200, already_confirmed
  * layer-3 / CIF blocks byte-unchanged through the HTTP path

Auth is supplied by overriding get_current_user — require_role's inner
dependency — which both satisfies the role gate and injects session_user.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_USER = {
    "id": "op-1",
    "role": "admin",
    "full_name": "Test Operator",
    "email": "op@example.com",
    "is_active": 1,
    "is_approved": 1,
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)

    from app.main import app
    from app.api import routes_dashboard as rd
    # Module-level path constants are computed at import time from a possibly
    # different storage_root (prior test). Repoint them at THIS tmp dir.
    monkeypatch.setattr(rd, "_OUTPUTS", tmp_path / "outputs", raising=False)
    monkeypatch.setattr(rd, "_WORKING", tmp_path / "working", raising=False)

    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: dict(_USER)
    try:
        yield TestClient(app), tmp_path
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _seed(tmp_path: Path, batch_id: str, vision_invoice) -> Path:
    out = tmp_path / "outputs" / batch_id
    out.mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id": batch_id,
        "timeline": [],
        # layer-3 / CIF — must stay byte-identical across confirm
        "invoice_totals": {"total_fob_usd": 0, "rows": []},
        "rows": [],
        "awb_customs": {"value_usd": 732.0, "currency": "EUR"},
        "clearance_decision": {"status": "RESOLVED", "cif": 732.0},
        "customs_declaration": {"mrn": "X"},
    }
    if vision_invoice is not None:
        audit["vision_invoice"] = vision_invoice
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out / "audit.json"


def _proposal():
    return {
        "supplier": "Acme Jewels Co",
        "invoice_no": "INV-1",
        "currency": "USD",
        "fob_usd": 1234.5,
        "line_items": [{"description": "ring", "amount_usd": 1234.5}],
        "confidence": 0.8,
        "operator_confirmed": False,
        "status": "proposed",
        "source": "vision_llm",
    }


_URL = "/dashboard/batches/{bid}/vision-invoice/confirm"


def test_confirm_happy_path_returns_200_and_attests(client):
    cl, tmp = client
    bid = "B-ROUTE-OK"
    audit_path = _seed(tmp, bid, _proposal())

    r = cl.post(_URL.format(bid=bid))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["operator_confirmed"] is True
    # Identity is the SERVER-SIDE authenticated user — never client-supplied.
    assert body["confirmed_by"] == "Test Operator"
    assert body.get("confirmed_at")
    # Stage C is live: confirm arms the PZ engine bridge, so next_step now
    # directs the operator to Run/Retry PZ (and notes wFirma is a separate
    # step). Confirm itself still does not generate PZ or post to wFirma.
    assert "next_step" in body
    _ns = body["next_step"].lower()
    assert "pz" in _ns and ("run" in _ns or "retry" in _ns)
    assert "wfirma" in _ns

    # Persisted on disk: flag flipped, lifecycle advanced.
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["vision_invoice"]["operator_confirmed"] is True
    assert audit["vision_invoice"]["status"] == "confirmed"
    assert audit["vision_invoice"]["confirmed_by"] == "Test Operator"


def test_confirm_no_proposal_returns_409(client):
    cl, tmp = client
    bid = "B-ROUTE-NOPROP"
    _seed(tmp, bid, None)  # no vision_invoice at all

    r = cl.post(_URL.format(bid=bid))
    assert r.status_code == 409, r.text


def test_confirm_ledger_only_block_returns_409(client):
    cl, tmp = client
    bid = "B-ROUTE-LEDGER"
    # A run-ledger-only block is not a confirmable proposal.
    _seed(tmp, bid, {"runs": [{"attempt": 1}], "attempted_signatures": ["x"]})

    r = cl.post(_URL.format(bid=bid))
    assert r.status_code == 409, r.text


def test_confirm_missing_batch_returns_404(client):
    cl, _tmp = client
    r = cl.post(_URL.format(bid="B-DOES-NOT-EXIST"))
    assert r.status_code == 404, r.text


def test_confirm_path_traversal_batch_id_returns_400(client):
    cl, _tmp = client
    # ".." in the batch_id trips the guard before any filesystem resolution.
    r = cl.post(_URL.format(bid="a..b"))
    assert r.status_code == 400, r.text


def test_confirm_backslash_batch_id_returns_400(client):
    cl, _tmp = client
    # Windows path separator must be rejected by the guard too.
    r = cl.post(_URL.format(bid="a%5Cb"))  # %5C == backslash
    assert r.status_code == 400, r.text


def test_confirm_requires_authenticated_operator(client):
    cl, tmp = client
    bid = "B-ROUTE-AUTH"
    _seed(tmp, bid, _proposal())

    # Drop the auth override → require_role gate must reject.
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides.pop(get_current_user, None)

    r = cl.post(_URL.format(bid=bid))
    assert r.status_code in (401, 403), r.text

    # Proposal must remain UNconfirmed — an unauthenticated call cannot attest.
    audit = json.loads((tmp / "outputs" / bid / "audit.json").read_text(encoding="utf-8"))
    assert audit["vision_invoice"]["operator_confirmed"] is False


def test_confirm_is_idempotent_over_http(client):
    cl, tmp = client
    bid = "B-ROUTE-IDEM"
    _seed(tmp, bid, _proposal())

    r1 = cl.post(_URL.format(bid=bid))
    assert r1.status_code == 200, r1.text
    assert r1.json()["operator_confirmed"] is True

    r2 = cl.post(_URL.format(bid=bid))
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["operator_confirmed"] is True
    assert body2.get("already_confirmed") is True


def test_confirm_does_not_touch_layer3_or_cif_over_http(client):
    cl, tmp = client
    bid = "B-ROUTE-ISO"
    audit_path = _seed(tmp, bid, _proposal())

    before = json.loads(audit_path.read_text(encoding="utf-8"))
    r = cl.post(_URL.format(bid=bid))
    assert r.status_code == 200, r.text
    after = json.loads(audit_path.read_text(encoding="utf-8"))

    for key in ("invoice_totals", "rows", "awb_customs",
                "clearance_decision", "customs_declaration"):
        assert before[key] == after[key], f"{key} mutated by confirm route"
