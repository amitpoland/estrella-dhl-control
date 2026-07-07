"""test_returns_qc_disposition.py — Returns QC Disposition (Phase 2).

Pins the QC disposition authority: one endpoint / one writer drives the
RETURNED_FROM_CLIENT piece to WAREHOUSE_STOCK (restock) / RETURNED_TO_PRODUCER
(repair) / WRITTEN_OFF (write-off) via the single state writer transition(),
records the QC outcome, is idempotent, role-gated, session-operatored, and has
ZERO accounting / wFirma side effects.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import inventory_state_engine as ise
from app.services import inventory_qc_writer as qc
from app.services import warehouse_db as wdb


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_returned_from_client(scan: str = "SC-1") -> None:
    """Drive a fresh piece None → PURCHASE_TRANSIT → WAREHOUSE_STOCK →
    RETURNED_FROM_CLIENT (with the required evidence)."""
    ise.transition(scan_code=scan, to_state=ise.PURCHASE_TRANSIT, operator="seed")
    ise.transition(scan_code=scan, to_state=ise.WAREHOUSE_STOCK, operator="seed")
    ise.transition(
        scan_code=scan, to_state=ise.RETURNED_FROM_CLIENT, operator="seed",
        return_reason="quality_complaint", origin_context="RMA-1",
        received_at=_now_iso(),
    )


@pytest.fixture()
def db(tmp_path, monkeypatch):
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    return tmp_path / "warehouse.db"


# ── 1-3. decision → transition ───────────────────────────────────────────────

def test_restock_transition(db):
    _seed_returned_from_client("SC-R")
    r = qc.apply_qc_disposition(scan_code="SC-R", decision="restock",
                                operator="alice", idempotency_key="k1",
                                condition="good", inspector="qc1")
    assert r["status"] == "qc_disposed" and r["to_state"] == ise.WAREHOUSE_STOCK
    assert ise.get_state("SC-R")["state"] == ise.WAREHOUSE_STOCK
    rows = wdb.get_qc_dispositions("SC-R")
    assert len(rows) == 1 and rows[0]["decision"] == "restock" and rows[0]["operator"] == "alice"


def test_repair_transition(db):
    _seed_returned_from_client("SC-P")
    r = qc.apply_qc_disposition(scan_code="SC-P", decision="repair",
                                operator="alice", idempotency_key="k1",
                                producer_name="Acme Mfg", dispatch_reference="RMA-9")
    assert r["to_state"] == ise.RETURNED_TO_PRODUCER
    assert ise.get_state("SC-P")["state"] == ise.RETURNED_TO_PRODUCER
    assert wdb.get_qc_dispositions("SC-P")[0]["producer_name"] == "Acme Mfg"


def test_repair_without_producer_rejected(db):
    _seed_returned_from_client("SC-NP")
    with pytest.raises(qc.QCError) as ei:
        qc.apply_qc_disposition(scan_code="SC-NP", decision="repair",
                                operator="alice", idempotency_key="k1")
    assert ei.value.code == "INVALID_INPUT"
    assert ise.get_state("SC-NP")["state"] == ise.RETURNED_FROM_CLIENT  # unchanged


def test_writeoff_transition(db):
    _seed_returned_from_client("SC-W")
    r = qc.apply_qc_disposition(scan_code="SC-W", decision="write_off",
                                operator="alice", idempotency_key="k1")
    assert r["to_state"] == ise.WRITTEN_OFF
    assert ise.get_state("SC-W")["state"] == ise.WRITTEN_OFF


# ── 4. illegal transitions ───────────────────────────────────────────────────

def test_qc_from_wrong_state_rejected(db):
    # piece sitting in WAREHOUSE_STOCK (never returned) → QC disposition illegal
    ise.transition(scan_code="SC-WS", to_state=ise.PURCHASE_TRANSIT, operator="seed")
    ise.transition(scan_code="SC-WS", to_state=ise.WAREHOUSE_STOCK, operator="seed")
    with pytest.raises(qc.QCError) as ei:
        qc.apply_qc_disposition(scan_code="SC-WS", decision="restock",
                                operator="alice", idempotency_key="k1")
    assert ei.value.code == "WRONG_STATE"
    assert ise.get_state("SC-WS")["state"] == ise.WAREHOUSE_STOCK  # unchanged


def test_written_off_is_terminal(db):
    _seed_returned_from_client("SC-T")
    qc.apply_qc_disposition(scan_code="SC-T", decision="write_off",
                            operator="alice", idempotency_key="k1")
    # No legal transition OUT of WRITTEN_OFF — engine refuses.
    assert ise.LEGAL_TRANSITIONS[ise.WRITTEN_OFF] == frozenset()
    for tgt in (ise.WAREHOUSE_STOCK, ise.RETURNED_FROM_CLIENT, ise.CLOSED):
        with pytest.raises(ValueError):
            ise.transition(scan_code="SC-T", to_state=tgt, operator="x")


def test_invalid_decision_rejected(db):
    _seed_returned_from_client("SC-BAD")
    with pytest.raises(qc.QCError) as ei:
        qc.apply_qc_disposition(scan_code="SC-BAD", decision="teleport",
                                operator="alice", idempotency_key="k1")
    assert ei.value.code == "INVALID_INPUT"
    assert ise.get_state("SC-BAD")["state"] == ise.RETURNED_FROM_CLIENT  # unchanged


def test_piece_not_found(db):
    with pytest.raises(qc.QCError) as ei:
        qc.apply_qc_disposition(scan_code="GHOST", decision="restock",
                                operator="alice", idempotency_key="k1")
    assert ei.value.code == "PIECE_NOT_FOUND"


# ── 5. idempotency (replay safety) ───────────────────────────────────────────

def test_idempotent_replay_no_double_transition(db):
    _seed_returned_from_client("SC-ID")
    a = qc.apply_qc_disposition(scan_code="SC-ID", decision="repair",
                                operator="alice", idempotency_key="same",
                                producer_name="Acme Mfg")
    b = qc.apply_qc_disposition(scan_code="SC-ID", decision="repair",
                                operator="alice", idempotency_key="same",
                                producer_name="Acme Mfg")
    assert a["status"] == "qc_disposed"
    assert b["status"] == "replayed"
    # exactly one QC row and the state moved exactly once
    assert len(wdb.get_qc_dispositions("SC-ID")) == 1
    assert ise.get_state("SC-ID")["state"] == ise.RETURNED_TO_PRODUCER
    # one transition event for the RFC→RTP move (not two)
    hist = ise.get_history("SC-ID")
    moves = [e for e in hist if e["to_state"] == ise.RETURNED_TO_PRODUCER]
    assert len(moves) == 1


# ── 6. single-writer + no accounting/wFirma side effects (source pins) ───────

def test_single_writer_no_direct_inventory_state_write():
    src = Path(qc.__file__).read_text(encoding="utf-8")
    # writer must NOT issue raw inventory_state DML — only transition() writes state
    assert not re.search(r"(INSERT INTO|UPDATE|DELETE FROM)\s+inventory_state\b", src, re.I)
    assert "inventory_state_engine.transition(" in src


def test_no_accounting_or_wfirma_side_effects():
    src = Path(qc.__file__).read_text(encoding="utf-8")
    # Check CODE (imports + calls), not prose: strip comment/docstring lines so
    # the module's own "no wFirma side effect" guarantee text isn't a false hit.
    code_lines = []
    in_doc = False
    for ln in src.splitlines():
        s = ln.strip()
        if s.startswith('"""') or s.startswith("'''"):
            in_doc = not in_doc if s.count('"""') % 2 or s.count("'''") % 2 else in_doc
            continue
        if in_doc or s.startswith("#"):
            continue
        code_lines.append(ln)
    code = "\n".join(code_lines).lower()
    for forbidden in ("wfirma", "proforma", "accounting", "invoice", "payment", "ledger",
                      "product_master", "packing_lines", "sales_packing_lines"):
        assert forbidden not in code, f"QC writer code must not reference {forbidden!r}"
    # Imports are inventory-domain only.
    imports = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
    assert all(("inventory_state_engine" in l or "warehouse_db" in l
                or "typing" in l or "sqlite3" in l or "__future__" in l)
               for l in imports), f"unexpected import in QC writer: {imports}"


# ── 7-9. endpoint: role gate, session operator, happy path ───────────────────

def _client(monkeypatch, tmp_path, *, api_key: str = "", env: str = "dev") -> TestClient:
    from app.core import config as _cfg
    monkeypatch.setattr(_cfg.settings, "api_key", api_key, raising=False)
    monkeypatch.setattr(_cfg.settings, "environment", env, raising=False)
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    from app.api.routes_inventory_returns import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_endpoint_request_model_has_no_operator_field():
    from app.api.routes_inventory_returns import QCDispositionRequest
    assert "operator" not in QCDispositionRequest.model_fields, \
        "operator must be session-derived, never a client field"


def test_endpoint_uses_privileged_guard_source():
    src = (Path(_SVC) / "app" / "api" / "routes_inventory_returns.py").read_text(encoding="utf-8")
    # the qc-disposition route must be role-gated (privileged), not plain require_api_key
    m = re.search(r'qc-disposition"[\s\S]{0,160}?dependencies=\[Depends\(require_api_key_privileged\)\]', src)
    assert m, "qc-disposition endpoint must declare require_api_key_privileged"


def test_endpoint_happy_path_dev(monkeypatch, tmp_path):
    cli = _client(monkeypatch, tmp_path, api_key="", env="dev")
    _seed_returned_from_client("SC-EP")
    resp = cli.post("/api/v1/inventory/pieces/SC-EP/qc-disposition",
                    json={"decision": "restock", "condition": "ok",
                          "inspector": "qc9", "idempotency_key": "e1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["to_state"] == ise.WAREHOUSE_STOCK
    # operator was session-derived (dev label), never from the request body
    assert wdb.get_qc_dispositions("SC-EP")[0]["operator"] == "dev-operator"


def test_endpoint_anonymous_rejected_when_api_key_set(monkeypatch, tmp_path):
    cli = _client(monkeypatch, tmp_path, api_key="secret", env="prod")
    _seed_returned_from_client("SC-401")
    resp = cli.post("/api/v1/inventory/pieces/SC-401/qc-disposition",
                    json={"decision": "restock", "idempotency_key": "e1"})
    assert resp.status_code == 401, resp.text  # no key + no session → rejected
    assert ise.get_state("SC-401")["state"] == ise.RETURNED_FROM_CLIENT  # unchanged


def test_resolve_operator_api_key_is_system_label(monkeypatch):
    from app.core import config as _cfg
    from app.api.routes_inventory_returns import resolve_session_operator
    monkeypatch.setattr(_cfg.settings, "api_key", "secret", raising=False)
    assert resolve_session_operator(key="secret", pz_session=None) == "system:api-key"
