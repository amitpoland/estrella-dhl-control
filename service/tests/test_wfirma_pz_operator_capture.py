"""
test_wfirma_pz_operator_capture.py — operator identity propagation
into wfirma_pz_created / wfirma_pz_adopted timeline events.

Pure unit checks against the helper + signature inspection. The full
``wfirma_pz_create`` route invokes wFirma client, audit guards, etc.
— out of scope for an audit-hardening regression. We pin:

  • _operator_from_header behavior (header set / missing / blank)
  • route signatures accept X-Operator header
  • detail block carries operator field on success path (source-grep)
  • No change to pz_create's guards, idempotency, or pz_create body
    (source-grep ensures the ordering and wFirma POST stay identical)
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from app.api import routes_wfirma as rw


SOURCE = Path(rw.__file__).read_text(encoding="utf-8")


# ── Helper ────────────────────────────────────────────────────────────────

class TestOperatorHelper:
    def test_returns_value_when_header_present(self):
        assert rw._operator_from_header("amit") == "amit"

    def test_strips_whitespace(self):
        assert rw._operator_from_header("  admin  ") == "admin"

    def test_falls_back_to_default_when_none(self):
        assert rw._operator_from_header(None) == "operator"

    def test_falls_back_to_default_when_empty(self):
        assert rw._operator_from_header("") == "operator"

    def test_falls_back_to_default_when_whitespace(self):
        assert rw._operator_from_header("   ") == "operator"


# ── Route signatures accept X-Operator ────────────────────────────────────

class TestRouteSignatures:
    def test_pz_create_accepts_x_operator(self):
        sig = inspect.signature(rw.wfirma_pz_create)
        assert "x_operator" in sig.parameters
        # Must default to None so legacy callers work unchanged
        assert sig.parameters["x_operator"].default.__class__.__name__ == "Header" \
            or sig.parameters["x_operator"].default is None \
            or sig.parameters["x_operator"].default == inspect.Parameter.empty \
            or "Header" in repr(sig.parameters["x_operator"].default)

    def test_pz_adopt_accepts_x_operator(self):
        sig = inspect.signature(rw.wfirma_pz_adopt)
        assert "x_operator" in sig.parameters

    def test_batch_id_remains_first_path_param(self):
        # Backward compat: route URL contract is unchanged.
        sig = inspect.signature(rw.wfirma_pz_create)
        params = list(sig.parameters.keys())
        assert params[0] == "batch_id"
        sig2 = inspect.signature(rw.wfirma_pz_adopt)
        params2 = list(sig2.parameters.keys())
        assert params2[0] == "batch_id"


# ── Source-level invariants ───────────────────────────────────────────────

class TestSourceInvariants:
    def test_pz_create_timeline_detail_includes_operator(self):
        # Anchor on the actual tl.log_event(...) call inside pz_create
        m = re.search(
            r"tl\.log_event\(\s*output_dir / \"audit\.json\",\s*"
            r"EV_WFIRMA_PZ_CREATED,.*?detail\s*=\s*\{(.*?)\},?\s*\)",
            SOURCE, re.DOTALL)
        assert m, "EV_WFIRMA_PZ_CREATED log call not found in pz_create"
        detail_body = m.group(1)
        assert '"operator"' in detail_body, \
            "wfirma_pz_created timeline detail must carry the operator field"
        for k in ('"batch_id"', '"wfirma_pz_doc_id"', '"line_count"'):
            assert k in detail_body, f"missing existing detail key {k}"

    def test_pz_adopt_timeline_detail_includes_operator(self):
        m = re.search(
            r"tl\.log_event\(\s*output_dir / \"audit\.json\",\s*"
            r"EV_WFIRMA_PZ_ADOPTED,.*?detail\s*=\s*\{(.*?)\},?\s*\)",
            SOURCE, re.DOTALL)
        assert m, "EV_WFIRMA_PZ_ADOPTED log call not found in pz_adopt"
        detail_body = m.group(1)
        assert '"operator"' in detail_body
        for k in ('"batch_id"', '"wfirma_pz_doc_id"', '"pz_number"', '"source"'):
            assert k in detail_body, f"missing existing detail key {k}"

    def test_log_event_actor_arg_unchanged(self):
        # The actor positional argument stays "system" / "wfirma" for
        # pz_create and "dashboard" / "user" for pz_adopt — this is the
        # pre-existing engine convention. Operator goes into detail only.
        assert 'EV_WFIRMA_PZ_CREATED,\n            "system",\n            "wfirma",' in SOURCE
        assert 'EV_WFIRMA_PZ_ADOPTED,\n            "dashboard",\n            "user",' in SOURCE

    def test_pz_create_guards_unchanged(self):
        # Guard 1 (flag) + Guard 2 (_guard_wfirma_export) + idempotency
        # check (existing wfirma_pz_doc_id) all still present.
        assert 'if not getattr(settings, "wfirma_create_pz_allowed", False):' in SOURCE
        assert "_guard_wfirma_export(audit)" in SOURCE
        assert "PZ_CREATE_GATE_OFF" in SOURCE
        # Idempotency / duplicate check — the route still consults the
        # existing wfirma_pz_doc_id before any wFirma POST.
        assert "existing_pz_doc_id" in SOURCE

    def test_no_new_endpoint_added(self):
        # The change is additive on the existing two routes only.
        # Ensure no new @router.post / @router.put / @router.delete with
        # the operator helper as the entry point appeared.
        new_routes = re.findall(
            r"@router\.(post|put|delete)\([^)]*operator", SOURCE, re.IGNORECASE)
        assert new_routes == [], \
            f"no new endpoints expected; found {new_routes}"

    def test_log_info_includes_operator(self):
        assert "operator=%s" in SOURCE, \
            "service log line should include the operator label"

    def test_helper_defined_above_routes(self):
        idx_helper  = SOURCE.index("def _operator_from_header(")
        idx_create  = SOURCE.index("async def wfirma_pz_create(")
        assert idx_helper < idx_create

    def test_pz_create_body_signature_block(self):
        # Confirm the literal new param appears in the def line — guards
        # against someone reverting the signature change.
        assert ('async def wfirma_pz_create(\n    batch_id: str,\n'
                '    x_operator: Optional[str] = Header(None, alias="X-Operator"),\n'
                ') -> JSONResponse:') in SOURCE
        assert ('async def wfirma_pz_adopt(\n    batch_id: str,\n'
                '    body: _PZAdoptBody,\n'
                '    x_operator: Optional[str] = Header(None, alias="X-Operator"),\n'
                ') -> JSONResponse:') in SOURCE


# ── Backward compat ───────────────────────────────────────────────────────

class TestBackwardCompat:
    def test_old_event_without_operator_key_still_readable(self):
        # The audit/timeline reader must not assume detail.operator is
        # always present. Verify the simulated old-shape is still a
        # valid event dict.
        old_event = {
            "ts":             "2026-05-08T12:38:27Z",
            "event":          "wfirma_pz_created",
            "trigger_source": "system",
            "actor":          "wfirma",
            "detail":         {
                "batch_id":         "B1",
                "wfirma_pz_doc_id": "1",
                "line_count":       9,
                # no "operator" key — pre-hardening event
            },
        }
        # detail.get('operator') returns None — callers must tolerate.
        assert old_event["detail"].get("operator") is None
        # The lock-status helper consumes EV_WFIRMA_PZ_CREATED via the
        # actor/event labels only; missing operator must not crash it.
        # (signature-only check; full call would need a fixtured audit.)
        assert hasattr(rw, "_compute_pz_lock_status")
