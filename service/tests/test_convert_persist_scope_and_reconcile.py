"""
test_convert_persist_scope_and_reconcile.py — draft 67 / PROF 160/2026 incident.

Root cause (2026-07-16, prod log 19:56:53): execute step 7b referenced
``_sale_date_for_payment`` / ``_effective_method_en`` — locals of
``_build_convert_candidate``, NOT of ``proforma_to_invoice`` — so every
conversion raised NameError inside the non-fatal try, leaving the draft row
with wfirma_invoice_id NULL and draft_state='posted' while the wFirma
invoice + link row existed. The UI then showed an active Convert button.

Repair authority (integration consolidation 2026-07-17): the ONE canonical
reconcile route ``POST /invoice-links/{proforma_id}/reconcile`` — its
'issued' branch (_reconcile_issued_link_projection) repairs the stale
DRAFT projection; its 'pending'/'failed' branch repairs split-brain links
(covered in test_invoice_link_reconcile.py). The former
``POST /draft/{id}/reconcile-conversion-link`` route was removed.

Pins:
  S1 — proforma_to_invoice no longer references the out-of-scope names
  S2 — _build_convert_candidate returns sale_date + payment_method_en keys
  S3 — execute success response declares the draft_persisted field

  R1 — blocked for an unknown proforma_id (no link row)
  R2 — GET /invoice-links/split-brain classifies an issued link with a
       stale draft as stale_draft_projection; healthy projections excluded
  R3 — blocked when no conversion link exists
  R4 — a non-issued (pending) link routes to the split-brain branch, which
       blocks without a captured/supplied invoice id — never the
       projection-repair path
  R5 — repairs the draft-67 shape: posted + NULL invoice id + issued link
       → draft_state='converted', invoice identity copied, event appended
  R6 — idempotent: second call is a noop
  R7 — conflict (draft carries a DIFFERENT invoice id) → blocked, no write
  R8 — no operator attribution → blocked, no write
  R9 — issued link missing invoice_id → blocked (inconsistent link row)
  R10 — converted state with NULL invoice id is repaired, not noop'd
  R11 — schema migration idempotent both paths
  R12 — reconcile appends the audit.json timeline events
  R13 — draft-52 partial-write shape (id matches, state stale) is repaired
  R14 — lock contention returns a structured, retryable error (no 500)
  R15 — canonical route carries the privileged write guard (_auth_write)
  R16 — missing confirm token → blocked, no write
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

from app.core.config import settings
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

_OP_HDR   = {"X-Operator": "test-operator"}
_CONFIRM  = {"confirm": "YES_RECONCILE_INVOICE_LINK"}
_PID      = "488979043"


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
                  wfirma_proforma_id=_PID,
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


def _insert_link(path: Path, *, proforma_id=_PID, issued=True,
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


def _post_reconcile(client, db, proforma_id=_PID, *, body=None,
                    headers=_OP_HDR):
    """Call the CANONICAL reconcile route. The fixture db file is named
    proforma_links.db inside tmp_path, so patching storage_root to its
    parent makes the route's link_db resolve to the very same file that
    also carries the proforma_drafts table."""
    with patch("app.api.routes_proforma._proforma_db_path",
               return_value=Path(str(db))), \
         patch.object(settings, "storage_root", Path(str(db)).parent):
        return client.post(
            f"/api/v1/proforma/invoice-links/{proforma_id}/reconcile",
            json=(dict(_CONFIRM) if body is None else body),
            headers=headers,
        )


# ── Reconcile endpoint tests (R1–R16) ─────────────────────────────────────────

class TestReconcileConversionLink:

    def test_r1_unknown_proforma_id_blocked(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        r = _post_reconcile(client, db, "999999999")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "no conversion link row" in body["blocking_reasons"][0]

    def test_r2_split_brain_get_reports_stale_projection(self, client, tmp_path):
        """Detection: an issued link whose draft never received the invoice
        identity is classified stale_draft_projection; once repaired, it
        drops out of the report."""
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        _insert_draft(db)               # posted, invoice id NULL → stale
        _insert_link(db)                # issued, 489960355

        def _get():
            with patch("app.api.routes_proforma._proforma_db_path",
                       return_value=Path(str(db))), \
                 patch.object(settings, "storage_root", tmp_path):
                return client.get(
                    "/api/v1/proforma/invoice-links/split-brain").json()

        body = _get()
        stale = [e for e in body["links"]
                 if e["classification"] == "stale_draft_projection"]
        assert len(stale) == 1, body
        assert stale[0]["proforma_id"] == _PID
        assert stale[0]["captured_invoice_id"] == "489960355"
        assert stale[0]["reconcilable_without_input"] is True

        r = _post_reconcile(client, db)
        assert r.json()["status"] == "reconciled"
        body2 = _get()
        assert [e for e in body2["links"]
                if e["classification"] == "stale_draft_projection"] == []

    def test_r3_blocked_without_link(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        _insert_draft(db)
        r = _post_reconcile(client, db)
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "no conversion link" in body["blocking_reasons"][0]

    def test_r4_pending_link_routes_to_split_brain_branch(self, client, tmp_path):
        """A non-issued link must NEVER take the projection-repair path. A
        pending row without a captured/supplied invoice id blocks inside
        the split-brain branch — and the draft stays untouched."""
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db, issued=False)
        r = _post_reconcile(client, db)
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "no wfirma_invoice_id available" in body["blocking_reasons"][0]
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.wfirma_invoice_id in (None, "")
        assert d.draft_state == "posted"

    def test_r5_repairs_draft67_shape(self, client, tmp_path):
        """posted + NULL wfirma_invoice_id + issued link → converted."""
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)          # draft_state='posted', invoice id NULL
        _insert_link(db)                 # issued, 489960355 / WDT 145/2026

        r = _post_reconcile(client, db)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["status"] == "reconciled"
        assert body["mode"] == "draft_projection_repair"
        assert body["wfirma_write"] is False
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

        # Audit event appended — ONE canonical event name for both branches
        events = pildb.list_draft_events(Path(str(db)), did)
        recon = [e for e in events if e["event"] == "invoice_link_reconciled"]
        assert len(recon) == 1
        detail = json.loads(recon[0]["detail_json"])
        assert detail["wfirma_invoice_id"] == "489960355"
        assert detail["before"]["draft_state"] == "posted"
        assert detail["mode"] == "draft_projection_repair"
        assert recon[0]["operator"] == "test-operator"

    def test_r6_second_call_is_noop(self, client, tmp_path):
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db)

        r1 = _post_reconcile(client, db)
        assert r1.json()["status"] == "reconciled"
        r2 = _post_reconcile(client, db)
        body2 = r2.json()
        assert body2["ok"] is True and body2["status"] == "noop"

        # No second audit event
        events = pildb.list_draft_events(Path(str(db)), did)
        recon = [e for e in events if e["event"] == "invoice_link_reconciled"]
        assert len(recon) == 1

    def test_r7_conflicting_invoice_id_blocks_without_write(self, client, tmp_path):
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db, wfirma_invoice_id="111111111",
                            draft_state="converted")
        _insert_link(db)  # link says 489960355

        r = _post_reconcile(client, db)
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "data conflict" in body["blocking_reasons"][0]

        # Draft untouched
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.wfirma_invoice_id == "111111111"

    def test_r8_missing_operator_is_blocked(self, client, tmp_path):
        """Operator attribution gate: no session, no X-Operator header →
        structured 'blocked', no write."""
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db)
        r = _post_reconcile(client, db, headers={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "operator attribution required" in body["blocking_reasons"][0]
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.wfirma_invoice_id in (None, "")
        assert d.draft_state == "posted"

    def test_r9_issued_link_with_empty_invoice_id_blocks(self, client, tmp_path):
        """An issued link missing invoice_id is inconsistent — blocked, not
        repaired (mark_issued forbids this shape; simulate via raw SQL)."""
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        _insert_draft(db)
        _insert_link(db, issued=False)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "UPDATE proforma_invoice_links SET status='issued', invoice_id=NULL "
            "WHERE proforma_id=?", (_PID,))
        conn.commit()
        conn.close()

        r = _post_reconcile(client, db)
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

        r = _post_reconcile(client, db)
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
        """Draft-52 shape: wfirma_invoice_id already matches the link but
        draft_state is still 'posted' (partial earlier write). Must be
        REPAIRED (state fixed), not noop'd — the noop guard requires both
        the id match AND state 'converted'."""
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db, wfirma_invoice_id="489960355",
                            draft_state="posted")
        _insert_link(db)

        r = _post_reconcile(client, db)
        body = r.json()
        assert body["ok"] is True and body["status"] == "reconciled"
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.draft_state == "converted"
        assert d.wfirma_invoice_id == "489960355"

    def test_r12_reconcile_appends_audit_json_event(self, client, tmp_path):
        """The reconcile route's audit.json timeline writes: the idempotent
        conversion record (restores a missing step-8 event) AND the
        reconcile action event itself."""
        from app.services.audit_persist import (
            EV_PROFORMA_CONVERTED_TO_INVOICE,
        )

        db = tmp_path / "proforma_links.db"
        _make_db(db)
        _insert_draft(db)
        _insert_link(db)
        audit_dir = tmp_path / "outputs" / "BATCH_RECON_TEST"
        audit_dir.mkdir(parents=True)
        (audit_dir / "audit.json").write_text(
            json.dumps({"status": "partial", "timeline": []}), encoding="utf-8")

        r = _post_reconcile(client, db)
        assert r.json()["status"] == "reconciled"

        audit = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
        converted = [e for e in audit["timeline"]
                     if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE]
        assert len(converted) == 1
        assert converted[0]["detail"]["wfirma_invoice_id"] == "489960355"
        assert converted[0]["detail"]["source"] == "invoice_link_reconcile"
        reconciled = [e for e in audit["timeline"]
                      if e.get("event") == "invoice_link_reconciled"]
        assert len(reconciled) == 1

    def test_r14_lock_contention_returns_structured_retryable(self, client, tmp_path):
        """sqlite 'database is locked' during the projection write must come
        back as a structured, retryable error — never a 500."""
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db)

        with patch(
            "app.services.conversion_persistence.persist_invoice_to_draft",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            r = _post_reconcile(client, db)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False and body["status"] == "error"
        assert body["retryable"] is True
        assert "database is locked" in body["detail"]

        # Draft untouched; the repair is re-runnable
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.wfirma_invoice_id in (None, "")
        assert d.draft_state == "posted"
        r2 = _post_reconcile(client, db)
        assert r2.json()["status"] == "reconciled"

    def test_r15_canonical_route_is_privileged(self):
        """Read-only roles must be rejected: the canonical reconcile POST
        carries the privileged write guard, and the superseded per-draft
        route is gone."""
        import app.api.routes_proforma as rp
        src = Path(rp.__file__).read_text(encoding="utf-8-sig")
        i = src.index('"/invoice-links/{proforma_id}/reconcile"')
        window = src[i:i + 400]
        assert "dependencies=[_auth_write]" in window, (
            "the canonical reconcile POST must use _auth_write "
            "(require_api_key_privileged) so read-only session roles are "
            "rejected"
        )
        assert "reconcile-conversion-link" not in src, (
            "the superseded POST /draft/{id}/reconcile-conversion-link route "
            "must stay deleted — one reconciliation authority only"
        )

    def test_r16_missing_confirm_token_blocked(self, client, tmp_path):
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        _make_db(db)
        did = _insert_draft(db)
        _insert_link(db)
        r = _post_reconcile(client, db, body={})
        body = r.json()
        assert body["ok"] is False and body["status"] == "blocked"
        assert "confirm token" in body["blocking_reasons"][0]
        d = pildb.get_draft_by_id(Path(str(db)), did)
        assert d.draft_state == "posted"
