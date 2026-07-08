"""test_inventory_corrections.py — Inventory Correction authority (Package A).

Pins the identity-correction authority: product_code / design_no / batch_id
fixes on an existing inventory_state row go through the single state writer
inventory_state_engine.correct_identity() (NOT transition() — an identity fix
is not a lifecycle transition), are recorded append-only in
inventory_corrections, are idempotent, role-gated, session-operatored, never
write Product Master, and never touch inventory_state_events. Also covers the
archive-proposal case (over-scan/duplicate) — proposal only, never a mutation.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import inventory_correction_writer as corr
from app.services import inventory_state_engine as ise
from app.services import warehouse_db as wdb


def _seed_warehouse_stock(
    scan: str = "SC-1",
    *,
    product_code: str = "PC-OLD",
    design_no: str = "DN-OLD",
    batch_id: str = "BATCH-1",
) -> None:
    """Drive a fresh piece None → PURCHASE_TRANSIT (with identity) →
    WAREHOUSE_STOCK."""
    ise.transition(scan_code=scan, to_state=ise.PURCHASE_TRANSIT, operator="seed",
                    product_code=product_code, design_no=design_no, batch_id=batch_id)
    ise.transition(scan_code=scan, to_state=ise.WAREHOUSE_STOCK, operator="seed")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    return tmp_path / "warehouse.db"


# ── 1-4. identity correction happy paths ─────────────────────────────────────

def test_correct_product_code(db):
    _seed_warehouse_stock("SC-PC")
    r = corr.apply_identity_correction(
        scan_code="SC-PC", operator="alice", reason="wrong product code",
        idempotency_key="k1", product_code="PC-NEW",
    )
    assert r["status"] == "corrected"
    state = ise.get_state("SC-PC")
    assert state["product_code"] == "PC-NEW"
    assert state["design_no"] == "DN-OLD" and state["batch_id"] == "BATCH-1"
    rows = wdb.get_corrections("SC-PC")
    assert len(rows) == 1
    assert rows[0]["old_product_code"] == "PC-OLD" and rows[0]["new_product_code"] == "PC-NEW"
    assert rows[0]["operator"] == "alice" and rows[0]["correction_type"] == "identity"


def test_correct_design_no(db):
    _seed_warehouse_stock("SC-DN")
    corr.apply_identity_correction(
        scan_code="SC-DN", operator="alice", reason="wrong design",
        idempotency_key="k1", design_no="DN-NEW",
    )
    state = ise.get_state("SC-DN")
    assert state["design_no"] == "DN-NEW"
    assert state["product_code"] == "PC-OLD"  # unrelated field untouched


def test_correct_batch_id(db):
    _seed_warehouse_stock("SC-BATCH")
    corr.apply_identity_correction(
        scan_code="SC-BATCH", operator="alice", reason="wrong batch",
        idempotency_key="k1", batch_id="BATCH-2",
    )
    assert ise.get_state("SC-BATCH")["batch_id"] == "BATCH-2"


def test_correct_blank_product_code(db):
    # Case 1: a piece minted with no product_code gets one assigned.
    ise.transition(scan_code="SC-BLANK", to_state=ise.PURCHASE_TRANSIT, operator="seed",
                    design_no="DN-1", batch_id="BATCH-1")
    ise.transition(scan_code="SC-BLANK", to_state=ise.WAREHOUSE_STOCK, operator="seed")
    assert ise.get_state("SC-BLANK")["product_code"] == ""
    corr.apply_identity_correction(
        scan_code="SC-BLANK", operator="alice", reason="assign missing code",
        idempotency_key="k1", product_code="PC-ASSIGNED",
    )
    assert ise.get_state("SC-BLANK")["product_code"] == "PC-ASSIGNED"


def test_correct_multiple_fields_at_once(db):
    _seed_warehouse_stock("SC-MULTI")
    corr.apply_identity_correction(
        scan_code="SC-MULTI", operator="alice", reason="multi-field fix",
        idempotency_key="k1", product_code="PC-NEW", design_no="DN-NEW", batch_id="BATCH-9",
    )
    state = ise.get_state("SC-MULTI")
    assert state["product_code"] == "PC-NEW"
    assert state["design_no"] == "DN-NEW"
    assert state["batch_id"] == "BATCH-9"


# ── 5-7. rejections ───────────────────────────────────────────────────────────

def test_no_fields_provided_rejected(db):
    _seed_warehouse_stock("SC-NOFIELD")
    with pytest.raises(corr.CorrectionError) as ei:
        corr.apply_identity_correction(
            scan_code="SC-NOFIELD", operator="alice", reason="nothing to change",
            idempotency_key="k1",
        )
    assert ei.value.code == "INVALID_INPUT"


def test_blank_reason_rejected(db):
    _seed_warehouse_stock("SC-NOREASON")
    with pytest.raises(corr.CorrectionError) as ei:
        corr.apply_identity_correction(
            scan_code="SC-NOREASON", operator="alice", reason="   ",
            idempotency_key="k1", product_code="PC-NEW",
        )
    assert ei.value.code == "INVALID_INPUT"


def test_piece_not_found(db):
    with pytest.raises(corr.CorrectionError) as ei:
        corr.apply_identity_correction(
            scan_code="GHOST", operator="alice", reason="fix",
            idempotency_key="k1", product_code="PC-NEW",
        )
    assert ei.value.code == "PIECE_NOT_FOUND"


# ── 8-9. idempotency (replay safety) ─────────────────────────────────────────

def test_idempotent_replay_no_double_correction(db):
    _seed_warehouse_stock("SC-ID")
    a = corr.apply_identity_correction(
        scan_code="SC-ID", operator="alice", reason="fix code",
        idempotency_key="same", product_code="PC-NEW",
    )
    b = corr.apply_identity_correction(
        scan_code="SC-ID", operator="alice", reason="fix code",
        idempotency_key="same", product_code="PC-NEW",
    )
    assert a["status"] == "corrected"
    assert b["status"] == "replayed"
    assert len(wdb.get_corrections("SC-ID")) == 1
    assert ise.get_state("SC-ID")["product_code"] == "PC-NEW"


def test_archive_proposal_idempotent_replay(db):
    _seed_warehouse_stock("SC-ARCH-ID")
    a = corr.propose_archive(scan_code="SC-ARCH-ID", operator="alice",
                              reason="duplicate scan", idempotency_key="same")
    b = corr.propose_archive(scan_code="SC-ARCH-ID", operator="alice",
                              reason="duplicate scan", idempotency_key="same")
    assert a["status"] == "archive_proposed"
    assert b["status"] == "replayed"
    assert len(wdb.get_corrections("SC-ARCH-ID")) == 1


# ── 10-11. lifecycle isolation: not a transition, no events row ──────────────

def test_identity_correction_does_not_change_lifecycle_state(db):
    _seed_warehouse_stock("SC-LIFECYCLE")
    before = ise.get_state("SC-LIFECYCLE")["state"]
    corr.apply_identity_correction(
        scan_code="SC-LIFECYCLE", operator="alice", reason="fix code",
        idempotency_key="k1", product_code="PC-NEW",
    )
    assert ise.get_state("SC-LIFECYCLE")["state"] == before == ise.WAREHOUSE_STOCK


def test_identity_correction_writes_no_inventory_state_event(db):
    _seed_warehouse_stock("SC-NOEVENT")
    n_before = len(ise.get_history("SC-NOEVENT"))
    corr.apply_identity_correction(
        scan_code="SC-NOEVENT", operator="alice", reason="fix code",
        idempotency_key="k1", product_code="PC-NEW",
    )
    assert len(ise.get_history("SC-NOEVENT")) == n_before  # no new lifecycle event


def test_archive_proposal_never_mutates_inventory_state(db):
    _seed_warehouse_stock("SC-ARCH")
    before = dict(ise.get_state("SC-ARCH"))
    r = corr.propose_archive(scan_code="SC-ARCH", operator="alice",
                              reason="over-scan duplicate", idempotency_key="k1")
    assert r["status"] == "archive_proposed"
    after = dict(ise.get_state("SC-ARCH"))
    assert before == after  # zero mutation — proposal only
    rows = wdb.get_corrections("SC-ARCH")
    assert len(rows) == 1 and rows[0]["correction_type"] == "archive_proposal"
    assert rows[0]["status"] == "proposed"


# ── 12-13. single-writer + no Product Master / wFirma side effects (source pins)

def test_single_writer_no_direct_inventory_state_write():
    src = Path(corr.__file__).read_text(encoding="utf-8")
    assert not re.search(r"(INSERT INTO|UPDATE|DELETE FROM)\s+inventory_state\b", src, re.I)
    assert "inventory_state_engine.correct_identity(" in src


def test_no_product_master_or_wfirma_side_effects():
    src = Path(corr.__file__).read_text(encoding="utf-8")
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
        assert forbidden not in code, f"Correction writer code must not reference {forbidden!r}"
    imports = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
    assert all(("inventory_state_engine" in l or "warehouse_db" in l
                or "typing" in l or "sqlite3" in l or "__future__" in l)
               for l in imports), f"unexpected import in correction writer: {imports}"


def test_correct_identity_is_separate_from_transition_source():
    src = Path(ise.__file__).read_text(encoding="utf-8")
    assert "def correct_identity(" in src
    # LEGAL_TRANSITIONS has no self-loop entries — identity fix can't be a
    # transition, which is exactly why correct_identity() must exist standalone.
    for state, targets in ise.LEGAL_TRANSITIONS.items():
        if state is not None:
            assert state not in targets, f"unexpected self-loop for {state!r}"


# ── 14-16. endpoint: role gate, session operator, happy path ────────────────

def _client(monkeypatch, tmp_path, *, api_key: str = "", env: str = "dev") -> TestClient:
    from app.core import config as _cfg
    monkeypatch.setattr(_cfg.settings, "api_key", api_key, raising=False)
    monkeypatch.setattr(_cfg.settings, "environment", env, raising=False)
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    from app.api.routes_inventory_returns import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_identity_request_model_has_no_operator_field():
    from app.api.routes_inventory_returns import IdentityCorrectionRequest
    assert "operator" not in IdentityCorrectionRequest.model_fields, \
        "operator must be session-derived, never a client field"


def test_archive_request_model_has_no_operator_field():
    from app.api.routes_inventory_returns import ArchiveProposalRequest
    assert "operator" not in ArchiveProposalRequest.model_fields, \
        "operator must be session-derived, never a client field"


def test_correction_endpoints_use_privileged_guard_source():
    src = (Path(_SVC) / "app" / "api" / "routes_inventory_returns.py").read_text(encoding="utf-8")
    m1 = re.search(r'correction/identity"[\s\S]{0,160}?dependencies=\[Depends\(require_api_key_privileged\)\]', src)
    assert m1, "identity-correction endpoint must declare require_api_key_privileged"
    m2 = re.search(r'correction/archive-proposal"[\s\S]{0,160}?dependencies=\[Depends\(require_api_key_privileged\)\]', src)
    assert m2, "archive-proposal endpoint must declare require_api_key_privileged"


def test_identity_correction_endpoint_happy_path_dev(monkeypatch, tmp_path):
    cli = _client(monkeypatch, tmp_path, api_key="", env="dev")
    _seed_warehouse_stock("SC-EP")
    resp = cli.post("/api/v1/inventory/pieces/SC-EP/correction/identity",
                     json={"reason": "wrong code", "idempotency_key": "e1",
                           "product_code": "PC-NEW"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "corrected"
    assert ise.get_state("SC-EP")["product_code"] == "PC-NEW"
    # operator was session-derived (dev label), never from the request body
    assert wdb.get_corrections("SC-EP")[0]["operator"] == "dev-operator"


def test_identity_correction_endpoint_anonymous_rejected_when_api_key_set(monkeypatch, tmp_path):
    cli = _client(monkeypatch, tmp_path, api_key="secret", env="prod")
    _seed_warehouse_stock("SC-401")
    resp = cli.post("/api/v1/inventory/pieces/SC-401/correction/identity",
                     json={"reason": "wrong code", "idempotency_key": "e1",
                           "product_code": "PC-NEW"})
    assert resp.status_code == 401, resp.text
    assert ise.get_state("SC-401")["product_code"] == "PC-OLD"  # unchanged


def test_archive_proposal_endpoint_happy_path_dev(monkeypatch, tmp_path):
    cli = _client(monkeypatch, tmp_path, api_key="", env="dev")
    _seed_warehouse_stock("SC-ARCH-EP")
    resp = cli.post("/api/v1/inventory/pieces/SC-ARCH-EP/correction/archive-proposal",
                     json={"reason": "duplicate over-scan", "idempotency_key": "e1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "archive_proposed"
    assert wdb.get_corrections("SC-ARCH-EP")[0]["operator"] == "dev-operator"


# ── 17-18. read-back, read-only ──────────────────────────────────────────────

def test_read_endpoint_returns_correction_history(monkeypatch, tmp_path):
    cli = _client(monkeypatch, tmp_path, api_key="", env="dev")
    _seed_warehouse_stock("SC-RD")
    cli.post("/api/v1/inventory/pieces/SC-RD/correction/identity",
              json={"reason": "wrong code", "idempotency_key": "r1", "product_code": "PC-NEW"})
    resp = cli.get("/api/v1/inventory/pieces/SC-RD/corrections")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["piece_id"] == "SC-RD"
    assert isinstance(body["corrections"], list) and len(body["corrections"]) == 1
    c = body["corrections"][0]
    for f in ("old_product_code", "new_product_code", "old_design_no", "new_design_no",
              "old_batch_id", "new_batch_id", "reason", "operator", "status", "created_at"):
        assert f in c, f"read-back missing field {f}"
    assert c["old_product_code"] == "PC-OLD" and c["new_product_code"] == "PC-NEW"
    assert c["operator"] == "dev-operator"


def test_read_endpoint_is_read_only(monkeypatch, tmp_path):
    cli = _client(monkeypatch, tmp_path, api_key="", env="dev")
    _seed_warehouse_stock("SC-RO")
    before = ise.get_state("SC-RO")["state"]
    n_before = len(wdb.get_corrections("SC-RO"))
    cli.get("/api/v1/inventory/pieces/SC-RO/corrections")
    cli.get("/api/v1/inventory/pieces/SC-RO/corrections")
    assert ise.get_state("SC-RO")["state"] == before
    assert len(wdb.get_corrections("SC-RO")) == n_before


# ── 19-24. Final Stock stale-display fix (HOLD DEPLOY blocker) ──────────────
# After identity correction, Final Stock / location inventory must show the
# corrected identity by overlaying inventory_state onto
# inventory_current_location — never by writing to the physical cache.

def _seed_location_row(
    scan: str,
    *,
    product_code: str,
    design_no: str,
    batch_id: str,
    location: str = "MAIN-A1",
) -> None:
    """Seed a physical-location cache row directly (bypasses record_scan's
    packing_lines dependency — this suite only needs a scan_code present in
    inventory_current_location, not a full packing-intake replay)."""
    import uuid as _uuid

    with wdb._connect() as con:
        con.execute(
            """INSERT INTO inventory_current_location
               (id, batch_id, product_code, design_no, bag_id, pack_sr,
                scan_code, current_location, current_status, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(_uuid.uuid4()), batch_id, product_code, design_no, "", None,
             scan, location, "in_warehouse", "2026-07-08T00:00:00Z", "seed"),
        )


def _client_with_warehouse(monkeypatch, tmp_path, *, api_key: str = "", env: str = "dev") -> TestClient:
    from app.core import config as _cfg
    monkeypatch.setattr(_cfg.settings, "api_key", api_key, raising=False)
    monkeypatch.setattr(_cfg.settings, "environment", env, raising=False)
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    from app.api.routes_inventory_returns import router as returns_router
    from app.api.routes_warehouse import router as warehouse_router
    app = FastAPI()
    app.include_router(returns_router)
    app.include_router(warehouse_router)
    return TestClient(app)


def test_final_stock_read_reflects_corrected_identity(db):
    _seed_warehouse_stock("SC-STALE-1")
    _seed_location_row("SC-STALE-1", product_code="PC-OLD", design_no="DN-OLD", batch_id="BATCH-1")
    corr.apply_identity_correction(
        scan_code="SC-STALE-1", operator="alice", reason="wrong design",
        idempotency_key="k1", design_no="DN-NEW",
    )
    items = wdb.get_inventory_at_location("MAIN-A1")
    assert len(items) == 1
    assert items[0]["design_no"] == "DN-NEW"
    assert items[0]["product_code"] == "PC-OLD"  # untouched field stays as-is


def test_final_stock_read_endpoint_returns_corrected_identity(monkeypatch, tmp_path):
    cli = _client_with_warehouse(monkeypatch, tmp_path, api_key="", env="dev")
    _seed_warehouse_stock("SC-STALE-2")
    _seed_location_row("SC-STALE-2", product_code="PC-OLD", design_no="DN-OLD", batch_id="BATCH-1")
    cli.post("/api/v1/inventory/pieces/SC-STALE-2/correction/identity",
              json={"reason": "wrong code", "idempotency_key": "k1", "product_code": "PC-NEW"})
    resp = cli.get("/api/v1/warehouse/locations/MAIN-A1/inventory")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["product_code"] == "PC-NEW"
    assert body["items"][0]["scan_code"] == "SC-STALE-2"


def test_inventory_current_location_row_unchanged_after_correction(db):
    _seed_warehouse_stock("SC-STALE-3")
    _seed_location_row("SC-STALE-3", product_code="PC-OLD", design_no="DN-OLD", batch_id="BATCH-1")
    corr.apply_identity_correction(
        scan_code="SC-STALE-3", operator="alice", reason="wrong batch",
        idempotency_key="k1", batch_id="BATCH-9",
    )
    raw = wdb.get_current_location("SC-STALE-3")
    assert raw["product_code"] == "PC-OLD"
    assert raw["design_no"] == "DN-OLD"
    assert raw["batch_id"] == "BATCH-1"  # physical cache untouched by the correction


def test_correction_audit_still_append_only_after_stale_display_fix(db):
    _seed_warehouse_stock("SC-STALE-4")
    _seed_location_row("SC-STALE-4", product_code="PC-OLD", design_no="DN-OLD", batch_id="BATCH-1")
    corr.apply_identity_correction(
        scan_code="SC-STALE-4", operator="alice", reason="wrong code",
        idempotency_key="k1", product_code="PC-NEW",
    )
    wdb.get_inventory_at_location("MAIN-A1")  # read path must not mutate audit
    rows = wdb.get_corrections("SC-STALE-4")
    assert len(rows) == 1
    assert rows[0]["old_product_code"] == "PC-OLD" and rows[0]["new_product_code"] == "PC-NEW"


def test_stale_display_fix_touches_no_product_master():
    src = Path(wdb.__file__).read_text(encoding="utf-8")
    fn_start = src.index("def get_inventory_at_location(")
    fn_end = src.index("\n\n\n", fn_start)
    fn_src = src[fn_start:fn_end].lower()
    for forbidden in ("product_master", "wfirma", "reservation_db"):
        assert forbidden not in fn_src, f"get_inventory_at_location must not reference {forbidden!r}"


def test_stale_display_fix_is_read_only_no_inventory_state_dml():
    src = Path(wdb.__file__).read_text(encoding="utf-8")
    fn_start = src.index("def get_inventory_at_location(")
    fn_end = src.index("\n\n\n", fn_start)
    fn_src = src[fn_start:fn_end]
    assert not re.search(r"(INSERT INTO|UPDATE|DELETE FROM)\s+inventory_state\b", fn_src, re.I)
    assert not re.search(r"(INSERT INTO|UPDATE|DELETE FROM)\s+inventory_current_location\b", fn_src, re.I)
    assert re.search(r"LEFT JOIN inventory_state\b", fn_src, re.I)
