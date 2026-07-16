"""
test_convert_persist_scope_and_reconcile.py — draft 67 / PROF 160/2026 incident.

Root cause (2026-07-16, prod log 19:56:53): execute step 7b referenced
``_sale_date_for_payment`` / ``_effective_method_en`` — locals of
``_build_convert_candidate``, NOT of ``proforma_to_invoice`` — so every
conversion raised NameError inside the non-fatal try, leaving the draft row
with wfirma_invoice_id NULL and draft_state='posted' while the wFirma
invoice + link row existed. The UI then showed an active Convert button.

Pins:
  S1 — proforma_to_invoice no longer references the out-of-scope names
  S2 — _build_convert_candidate returns sale_date + payment_method_en keys
  S3 — execute success response declares the draft_persisted field

  R1 — reconcile endpoint 404 for unknown draft
  R2 — blocked when the draft has no wfirma_proforma_id
  R3 — blocked when no conversion link exists
  R4 — blocked when the link is not status='issued'
  R5 — repairs the draft-67 shape: posted + NULL invoice id + issued link
       → draft_state='converted', invoice identity copied, event appended
  R6 — idempotent: second call is a noop
  R7 — conflict (draft carries a DIFFERENT invoice id) → blocked, no write
"""
from __future__ import annotations

import ast
import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_current_user

# ── Auth bypass ───────────────────────────────────────────────────────────────

_TEST_USER = {
    "id": "test-id", "email": "test@local",
    "full_name": "Test Operator", "role": "admin",
    "is_active": True, "is_approved": True,
}

@pytest.fixture(autouse=True)
def bypass_auth():
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)

_OP_HDR = {"X-Operator": "test-operator"}


# ── Source pins (S1–S3) ───────────────────────────────────────────────────────

def _routes_proforma_tree():
    import app.api.routes_proforma as rp
    # utf-8-sig: the file carries a BOM; plain utf-8 leaves U+FEFF in the
    # source and ast.parse rejects it.
    src = Path(rp.__file__).read_text(encoding="utf-8-sig")
    return ast.parse(src)


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found in routes_proforma.py")


def test_s1_execute_does_not_reference_candidate_locals():
    """The exact NameError that broke draft 67: step 7b must never reference
    _build_convert_candidate's locals from proforma_to_invoice's scope."""
    fn = _find_func(_routes_proforma_tree(), "proforma_to_invoice")
    referenced = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    for forbidden in ("_sale_date_for_payment", "_effective_method_en"):
        assert forbidden not in referenced, (
            f"proforma_to_invoice references {forbidden!r} — a local of "
            "_build_convert_candidate. This is the draft-67 NameError regression."
        )


def test_s2_candidate_exposes_sale_date_and_payment_method():
    fn = _find_func(_routes_proforma_tree(), "_build_convert_candidate")
    returned_keys: set = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for k in node.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    returned_keys.add(k.value)
    for required in ("sale_date", "payment_method_en", "paymentdate"):
        assert required in returned_keys, (
            f"_build_convert_candidate return dict must expose {required!r} "
            "for execute step 7b"
        )


def test_s3_execute_response_declares_draft_persisted():
    import app.api.routes_proforma as rp
    src = Path(rp.__file__).read_text(encoding="utf-8-sig")
    assert '"draft_persisted"' in src, (
        "execute success response must surface the step-7b outcome as "
        "draft_persisted (silent persist failure = draft-67 incident class)"
    )


# ── Reconcile endpoint fixtures ───────────────────────────────────────────────

def _make_db(path: Path):
    from app.services import proforma_invoice_link_db as pildb
    pildb.init_db(Path(str(path)))


def _insert_draft(path: Path, *, batch_id="BATCH_RECON_TEST",
                  client_name="Recon Test Client",
                  draft_state="posted",
                  wfirma_proforma_id="488979043",
                  wfirma_invoice_id=None) -> int:
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(str(path))
    cur = conn.execute(
        "INSERT INTO proforma_drafts"
        " (batch_id, client_name, status, draft_state, currency,"
        "  wfirma_proforma_id, wfirma_invoice_id, editable_lines_json,"
        "  source_lines_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (batch_id, client_name, "issued", draft_state, "EUR",
         wfirma_proforma_id, wfirma_invoice_id, "[]", "[]", now, now),
    )
    conn.commit()
    draft_id = int(cur.lastrowid)
    conn.close()
    return draft_id


def _insert_link(path: Path, *, proforma_id="488979043", issued=True,
                 invoice_id="489960355", invoice_number="WDT 145/2026"):
    from app.services import proforma_invoice_link_db as plink
    link = plink.ProformaInvoiceLink(
        proforma_id     = proforma_id,
        proforma_number = "PROF 160/2026",
        converted_at    = "2026-07-16T17:56:53Z",
        operator        = "test-operator",
        source_total    = Decimal("3373.45"),
        currency        = "EUR",
        status          = "pending",
    )
    plink.create_pending_link(Path(str(path)), link)
    if issued:
        plink.mark_issued(
            Path(str(path)), proforma_id,
            invoice_id     = invoice_id,
            invoice_number = invoice_number,
            invoice_total  = Decimal("3373.45"),
        )


def _post_reconcile(client, db, draft_id):
    with patch("app.api.routes_proforma._proforma_db_path",
               return_value=Path(str(db))):
        return client.post(
            f"/api/v1/proforma/draft/{draft_id}/reconcile-conversion-link",
            headers=_OP_HDR,
        )


# ── Reconcile endpoint tests (R1–R7) ──────────────────────────────────────────

class TestReconcileConversionLink:

    def test_r1_404_unknown_draft(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        r = _post_reconcile(client, db, 9999)
        assert r.status_code == 404, r.text

    def test_r2_blocked_without_proforma_id(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db, wfirma_proforma_id=None)
        r = _post_reconcile(client, db, did)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "no wfirma_proforma_id" in body["blocking_reasons"][0]

    def test_r3_blocked_without_link(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        r = _post_reconcile(client, db, did)
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "no conversion link" in body["blocking_reasons"][0]

    def test_r4_blocked_when_link_not_issued(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db, issued=False)
        r = _post_reconcile(client, db, did)
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "'pending'" in body["blocking_reasons"][0]

    def test_r5_repairs_draft67_shape(self, client, tmp_path):
        """posted + NULL wfirma_invoice_id + issued link → converted."""
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)          # draft_state='posted', invoice id NULL
        _insert_link(db)                 # issued, 489960355 / WDT 145/2026

        r = _post_reconcile(client, db, did)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["status"] == "reconciled"
        assert body["before"]["wfirma_invoice_id"] is None
        assert body["before"]["draft_state"] == "posted"
        assert body["after"]["draft_state"] == "converted"
        assert body["after"]["wfirma_invoice_id"] == "489960355"
        assert body["after"]["wfirma_invoice_number"] == "WDT 145/2026"

        # DB truth matches the response
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.draft_state == "converted"
        assert d.wfirma_invoice_id == "489960355"
        assert d.wfirma_invoice_number == "WDT 145/2026"

        # Audit event appended
        events = pildb.list_draft_events(Path(str(db)), did)
        recon = [e for e in events if e["event"] == "conversion_link_reconciled"]
        assert len(recon) == 1
        detail = json.loads(recon[0]["detail_json"])
        assert detail["wfirma_invoice_id"] == "489960355"
        assert detail["before"]["draft_state"] == "posted"
        assert recon[0]["operator"] == "test-operator"

    def test_r6_second_call_is_noop(self, client, tmp_path):
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db)

        r1 = _post_reconcile(client, db, did)
        assert r1.json()["status"] == "reconciled"
        r2 = _post_reconcile(client, db, did)
        body2 = r2.json()
        assert body2["ok"] is True and body2["status"] == "noop"

        # No second audit event
        events = pildb.list_draft_events(Path(str(db)), did)
        recon = [e for e in events if e["event"] == "conversion_link_reconciled"]
        assert len(recon) == 1

    def test_r7_conflicting_invoice_id_blocks_without_write(self, client, tmp_path):
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db, wfirma_invoice_id="111111111",
                            draft_state="converted")
        _insert_link(db)  # link says 489960355

        r = _post_reconcile(client, db, did)
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "data conflict" in body["blocking_reasons"][0]

        # Draft untouched
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.wfirma_invoice_id == "111111111"

    def test_r8_missing_operator_header_is_400(self, client, tmp_path):
        """_require_operator guard: no X-Operator header → HTTP 400, no write."""
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db)
        with patch("app.api.routes_proforma._proforma_db_path",
                   return_value=Path(str(db))):
            r = client.post(
                f"/api/v1/proforma/draft/{did}/reconcile-conversion-link")
        assert r.status_code == 400, r.text
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.wfirma_invoice_id in (None, "")
        assert d.draft_state == "posted"

    def test_r9_issued_link_with_empty_invoice_id_blocks(self, client, tmp_path):
        """An issued link missing invoice_id is inconsistent — blocked, not
        repaired (mark_issued forbids this shape; simulate via raw SQL)."""
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db, issued=False)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "UPDATE proforma_invoice_links SET status='issued', invoice_id=NULL "
            "WHERE proforma_id='488979043'")
        conn.commit()
        conn.close()

        r = _post_reconcile(client, db, did)
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "no invoice_id" in body["blocking_reasons"][0]

    def test_r10_converted_state_with_null_invoice_id_is_repaired(self, client, tmp_path):
        """Orphaned shape from a partial earlier write: draft_state='converted'
        but wfirma_invoice_id NULL — must fall through to the repair path,
        not the noop path."""
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db, draft_state="converted", wfirma_invoice_id=None)
        _insert_link(db)

        r = _post_reconcile(client, db, did)
        body = r.json()
        assert body["ok"] is True and body["status"] == "reconciled"
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.wfirma_invoice_id == "489960355"
        assert d.draft_state == "converted"

    def test_r11_schema_migration_idempotent_both_paths(self, tmp_path):
        """The post-conversion columns are now created by BOTH init_db
        (_ADDITIVE_DRAFT_COLUMNS) and persist_invoice_to_draft's own ALTER
        loop. Running both, in both orders, must not raise or corrupt."""
        from app.services import proforma_invoice_link_db as pildb
        from app.services.conversion_persistence import persist_invoice_to_draft

        db = tmp_path / "order1.db"
        pildb.init_db(db)               # columns via _ADDITIVE_DRAFT_COLUMNS
        did = _insert_draft(db)
        persist_invoice_to_draft(       # its ALTER loop hits duplicate columns
            db_path=db, draft_id=did,
            wfirma_invoice_id="489960355",
            wfirma_invoice_number="WDT 145/2026",
        )
        pildb.init_db(db)               # re-init after persist — still clean
        d = pildb.get_draft_by_id(db, did)
        assert d.wfirma_invoice_id == "489960355"
        assert d.draft_state == "converted"

    def test_r13_partial_write_state_is_repaired(self, client, tmp_path):
        """Partial-write shape: wfirma_invoice_id already matches the link but
        draft_state is still 'posted' (e.g. crash between writes). Must be
        REPAIRED (state fixed), not noop'd — the noop guard requires both
        the id match AND state 'converted'."""
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db, wfirma_invoice_id="489960355",
                            draft_state="posted")
        _insert_link(db)

        r = _post_reconcile(client, db, did)
        body = r.json()
        assert body["ok"] is True and body["status"] == "reconciled"
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.draft_state == "converted"
        assert d.wfirma_invoice_id == "489960355"

    def test_r12_reconcile_appends_audit_json_event(self, client, tmp_path):
        """The reconcile route's audit.json timeline write (previously only
        the draft-events table was asserted)."""
        from app.core.config import settings
        from app.services.audit_persist import EV_PROFORMA_CONVERTED_TO_INVOICE

        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db)
        audit_dir = tmp_path / "outputs" / "BATCH_RECON_TEST"
        audit_dir.mkdir(parents=True)
        (audit_dir / "audit.json").write_text(
            json.dumps({"status": "partial", "timeline": []}), encoding="utf-8")

        with patch.object(settings, "storage_root", tmp_path):
            r = _post_reconcile(client, db, did)
        assert r.json()["status"] == "reconciled"

        audit = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
        events = [e for e in audit["timeline"]
                  if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE]
        assert len(events) == 1
        assert events[0]["detail"]["wfirma_invoice_id"] == "489960355"
        assert events[0]["detail"]["source"] == "reconcile_conversion_link"
