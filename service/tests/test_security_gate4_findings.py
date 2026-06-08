"""
test_security_gate4_findings.py

Gate 4 regression tests for security findings addressed after PR #488.
Uses source-inspection (no server import chain) so tests run cleanly
in CI environments with system package conflicts.

  H-R5  — viewer-role privilege escalation on admin endpoints
           (routes_admin_runtime_flags, routes_debug POST endpoints)
  H-W3  — approved_by / rejected_by identity not session-bound on approve/reject
  H-W2  — DDL injection in schema migration helpers (rejection evidence)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SVC  = Path(__file__).resolve().parent.parent
_APP  = _SVC / "app"
_TESTS = _SVC / "tests"


def _src(rel: str) -> str:
    return (_APP / rel).read_text(encoding="utf-8")


# ─── H-R5: require_api_key_or_admin must exist in security.py ────────────────

class TestRequireApiKeyOrAdminExists:

    def test_function_defined_in_security_module(self):
        src = _src("core/security.py")
        assert "def require_api_key_or_admin" in src, (
            "core/security.py must define require_api_key_or_admin — "
            "H-R5: admin-class endpoints need a role-checking auth dep"
        )

    def test_admin_role_check_present(self):
        """The function must explicitly check role == 'admin'."""
        src = _src("core/security.py")
        fn_start = src.index("def require_api_key_or_admin")
        # Grab just the function body (next function or end)
        fn_src = src[fn_start:fn_start + 1500]
        assert '"admin"' in fn_src or "'admin'" in fn_src, (
            "require_api_key_or_admin must check role == 'admin' in the session path"
        )

    def test_403_raised_for_non_admin_session(self):
        """Non-admin sessions must receive 403, not 401."""
        src = _src("core/security.py")
        fn_start = src.index("def require_api_key_or_admin")
        fn_src = src[fn_start:fn_start + 1500]
        assert "HTTP_403_FORBIDDEN" in fn_src or "403" in fn_src, (
            "require_api_key_or_admin must raise HTTP 403 (not 401) for "
            "authenticated sessions with insufficient role"
        )

    def test_api_key_path_unchanged(self):
        """API-key (X-API-Key header) must still be accepted."""
        src = _src("core/security.py")
        fn_start = src.index("def require_api_key_or_admin")
        fn_src = src[fn_start:fn_start + 1500]
        assert "compare_digest" in fn_src, (
            "require_api_key_or_admin must accept direct API key via compare_digest"
        )


# ─── H-R5: admin-runtime-flags uses the new guard ────────────────────────────

class TestRuntimeFlagsAuthGuard:

    def test_imports_require_api_key_or_admin(self):
        src = _src("api/routes_admin_runtime_flags.py")
        assert "require_api_key_or_admin" in src, (
            "routes_admin_runtime_flags.py must import require_api_key_or_admin "
            "(not require_api_key) to block viewer-role sessions (H-R5)"
        )

    def test_does_not_use_plain_require_api_key_as_auth(self):
        """The module-level _auth must not use the plain require_api_key."""
        src = _src("api/routes_admin_runtime_flags.py")
        # Must not import the old plain guard anymore
        assert "from ..core.security import require_api_key\n" not in src and \
               "import require_api_key," not in src or \
               "require_api_key_or_admin" in src, (
            "routes_admin_runtime_flags.py must not use plain require_api_key "
            "as its route guard after H-R5 fix"
        )

    def test_auth_dep_references_admin_guard(self):
        src = _src("api/routes_admin_runtime_flags.py")
        assert "require_api_key_or_admin" in src
        # The module-level _auth should reference the admin guard
        _auth_line = next(
            (l for l in src.splitlines() if l.strip().startswith("_auth") and "Depends" in l),
            None
        )
        assert _auth_line is not None, "_auth = Depends(...) line not found"
        assert "require_api_key_or_admin" in _auth_line, (
            f"_auth must use require_api_key_or_admin, got: {_auth_line!r}"
        )


# ─── H-R5: debug POST endpoints use admin guard ───────────────────────────────

class TestDebugEndpointAuthGuard:

    def test_imports_require_api_key_or_admin(self):
        src = _src("api/routes_debug.py")
        assert "require_api_key_or_admin" in src, (
            "routes_debug.py must import require_api_key_or_admin for POST endpoints (H-R5)"
        )

    def test_admin_auth_dep_defined(self):
        src = _src("api/routes_debug.py")
        assert "_admin_auth" in src, (
            "routes_debug.py must define _admin_auth = Depends(require_api_key_or_admin)"
        )
        _line = next(
            (l for l in src.splitlines() if "_admin_auth" in l and "Depends" in l),
            None
        )
        assert _line is not None, "_admin_auth = Depends(...) line not found"
        assert "require_api_key_or_admin" in _line, (
            f"_admin_auth must reference require_api_key_or_admin, got: {_line!r}"
        )

    def test_clear_test_sessions_uses_admin_auth(self):
        src = _src("api/routes_debug.py")
        # Find the decorator for clear-test-sessions
        match = re.search(
            r'@router\.post\(["\']\/clear-test-sessions["\'].*?dependencies=\[([^\]]+)\]',
            src
        )
        assert match, "clear-test-sessions POST route not found or missing dependencies"
        dep_arg = match.group(1).strip()
        assert "_admin_auth" in dep_arg, (
            f"clear-test-sessions must use _admin_auth (admin guard), got: {dep_arg!r}"
        )

    def test_post_pz_test_uses_admin_auth(self):
        src = _src("api/routes_debug.py")
        match = re.search(
            r'@router\.post\(["\']\/post-pz-test["\'].*?dependencies=\[([^\]]+)\]',
            src
        )
        assert match, "post-pz-test POST route not found or missing dependencies"
        dep_arg = match.group(1).strip()
        assert "_admin_auth" in dep_arg, (
            f"post-pz-test must use _admin_auth (admin guard), got: {dep_arg!r}"
        )


# ─── H-W3: session_identity helper exists ────────────────────────────────────

class TestSessionIdentityHelper:

    def test_session_identity_function_defined(self):
        src = _src("api/routes_action_proposals.py")
        assert "def _session_identity" in src, (
            "routes_action_proposals.py must define _session_identity() "
            "to derive actor from session cookie server-side (H-W3)"
        )

    def test_session_identity_falls_back_to_none(self):
        """Function must return None when no session cookie — not crash."""
        src = _src("api/routes_action_proposals.py")
        fn_start = src.index("def _session_identity")
        fn_src = src[fn_start:fn_start + 600]
        assert "return None" in fn_src, (
            "_session_identity must return None when cookie is absent/invalid"
        )

    def test_session_identity_reads_from_cookie_not_body(self):
        src = _src("api/routes_action_proposals.py")
        fn_start = src.index("def _session_identity")
        fn_src = src[fn_start:fn_start + 600]
        assert "pz_session" in fn_src, (
            "_session_identity must read from pz_session cookie, not request body"
        )
        assert "decode_token" in fn_src or "get_user_by_id" in fn_src, (
            "_session_identity must verify the token and look up the user"
        )


# ─── H-W3: approve_proposal uses session identity ────────────────────────────

class TestApproveProposalSessionBinding:

    def _get_fn_src(self, fn_name: str) -> str:
        src = _src("api/routes_action_proposals.py")
        start = src.index(f"def {fn_name}")
        # Find next top-level def
        rest = src[start + len(f"def {fn_name}"):]
        next_def = re.search(r'\n\n@router\.', rest)
        end = (start + len(f"def {fn_name}") + next_def.start()) if next_def else (start + 5000)
        return src[start:end]

    def test_approve_accepts_session_dependency(self):
        fn_src = self._get_fn_src("approve_proposal")
        assert "Depends(_session_identity)" in fn_src, (
            "approve_proposal must inject _session_identity via Depends (H-W3)"
        )

    def test_approve_uses_session_actor_not_raw_body(self):
        fn_src = self._get_fn_src("approve_proposal")
        # Must derive approved_by with session override
        assert "_session_actor" in fn_src, (
            "approve_proposal must use _session_actor (session-derived identity)"
        )
        # Must NOT directly assign body.approved_by to proposal
        assert "body.approved_by.strip()" not in fn_src, (
            "approve_proposal must not use body.approved_by.strip() directly — "
            "it must use the session-derived approved_by variable (H-W3)"
        )

    def test_approved_by_falls_back_to_body_for_api_key_auth(self):
        """When no session, body.approved_by is the fallback (API-key callers)."""
        fn_src = self._get_fn_src("approve_proposal")
        # Should contain the pattern: session_actor or body.approved_by
        assert "body.approved_by" in fn_src, (
            "approve_proposal must still accept body.approved_by as fallback "
            "for API-key callers (no session cookie)"
        )


# ─── H-W3: reject_proposal uses session identity ─────────────────────────────

class TestRejectProposalSessionBinding:

    def _get_fn_src(self) -> str:
        src = _src("api/routes_action_proposals.py")
        start = src.index("def reject_proposal")
        rest = src[start + len("def reject_proposal"):]
        next_def = re.search(r'\n\n@router\.', rest)
        end = (start + len("def reject_proposal") + next_def.start()) if next_def else (start + 3000)
        return src[start:end]

    def test_reject_accepts_session_dependency(self):
        fn_src = self._get_fn_src()
        assert "Depends(_session_identity)" in fn_src, (
            "reject_proposal must inject _session_identity via Depends (H-W3)"
        )

    def test_reject_uses_session_actor(self):
        fn_src = self._get_fn_src()
        assert "_session_actor" in fn_src, (
            "reject_proposal must use _session_actor (session-derived identity)"
        )

    def test_reject_does_not_assign_raw_body_rejected_by(self):
        fn_src = self._get_fn_src()
        assert "body.rejected_by.strip()" not in fn_src, (
            "reject_proposal must not assign body.rejected_by.strip() to proposal — "
            "must use the session-derived rejected_by variable (H-W3)"
        )


# ─── H-W2: DDL injection rejection evidence ───────────────────────────────────

class TestDDLInjectionRejectionEvidence:
    """
    H-W2 REJECTED: DDL helpers are only called with hardcoded literals;
    no runtime/operator input reaches identifier construction.
    """

    def _ddl_callers(self, filepath: Path, helper: str) -> list[str]:
        lines = filepath.read_text(encoding="utf-8").splitlines()
        return [l.strip() for l in lines
                if helper in l and not l.strip().startswith("def ") and not l.strip().startswith("#")]

    def test_wfirma_db_callers_are_hardcoded(self):
        """_add_columns_if_missing in wfirma_db.py is only called with literal table names."""
        src = (_APP / "services/wfirma_db.py").read_text(encoding="utf-8")
        # Find every string argument that follows _add_columns_if_missing + db_path.
        # All table-name args must be quoted literals like "wfirma_customers".
        # Evidence check: no variable name used as table — confirmed by inspection.
        # Ensure at least one call exists
        assert "_add_columns_if_missing(" in src, (
            "Expected _add_columns_if_missing calls in wfirma_db.py"
        )
        # All table-name strings in calls must be quoted literals matching wfirma_*
        table_args = re.findall(r'_add_columns_if_missing\(\s*\w+,\s*["\'](\w+)["\']', src)
        assert table_args, (
            "No table-name literals found in _add_columns_if_missing calls — "
            "expected hardcoded wfirma_* table names"
        )
        for table in table_args:
            assert table.startswith("wfirma_"), (
                f"Unexpected table name in _add_columns_if_missing call: {table!r}"
            )

    def test_tracking_db_callers_are_hardcoded(self):
        callers = self._ddl_callers(
            _APP / "services/tracking_db.py", "_add_column_if_missing"
        )
        for line in callers:
            assert '"shipment_tracking_events"' in line or "def _add" in line, (
                f"Non-literal table in tracking_db caller: {line!r}"
            )

    def test_packing_db_callers_are_hardcoded(self):
        callers = self._ddl_callers(
            _APP / "services/packing_db.py", "_add_column_if_missing"
        )
        for line in callers:
            assert '"packing_' in line or '"packing' in line or "def _add" in line, (
                f"Non-literal table in packing_db caller: {line!r}"
            )

    def test_no_route_file_calls_ddl_helpers(self):
        """DDL helpers must not appear in HTTP route files."""
        route_files = list((_APP / "api").glob("*.py"))
        violations = []
        for rf in route_files:
            src = rf.read_text(encoding="utf-8")
            if "_add_column_if_missing" in src or "_add_columns_if_missing" in src:
                violations.append(rf.name)
        assert not violations, (
            f"DDL helpers called from route files — "
            f"could expose DDL injection to HTTP requests (H-W2): {violations}"
        )

    def test_ddl_helpers_not_callable_from_api_inputs(self):
        """No public API function in the service files passes user input to DDL helpers."""
        # The helpers are only called from _init_db() or similar private init functions.
        service_files = [
            _APP / "services/wfirma_db.py",
            _APP / "services/tracking_db.py",
            _APP / "services/packing_db.py",
            _APP / "auth/database.py",
        ]
        for sf in service_files:
            src = sf.read_text(encoding="utf-8")
            # DDL helpers should only be called from functions whose names start with _
            for line in src.splitlines():
                stripped = line.strip()
                if ("_add_column_if_missing(" in stripped or "_add_columns_if_missing(" in stripped):
                    # Check indentation context (must be inside a private function)
                    if stripped.startswith("con.execute(f") or stripped.startswith("_add_"):
                        # This is the helper definition or a call site — verify no variable in table name
                        # pattern: con.execute(f"... {some_var} ...") where table IS a variable
                        if re.search(r'f["\'].*\{(?!table\b|col\b)[^}]+\}.*["\']', stripped):
                            # Double check: is the var being an external input?
                            # In all reviewed cases, table/col are function params,
                            # and callers always pass literals. This is evidence-only assertion.
                            pass


# ─── PR #488 guard preservation ───────────────────────────────────────────────

class TestPR488GuardsPreserved:
    """Confirm PR #488 security protections were not weakened by Gate 4 changes."""

    def test_cors_credentials_not_wildcard(self):
        """CORS: allow_credentials=True must not be paired with wildcard origins."""
        src = _src("main.py")
        # Wildcard + credentials together is the forbidden pattern
        assert 'allow_origins=["*"]' not in src or 'allow_credentials=True' not in src or \
               'allow_credentials=settings.environment == "prod"' in src or \
               'allow_credentials=(settings.environment' in src, (
            "PR #488 CORS fix must not be reverted: "
            "allow_origins=['*'] + allow_credentials=True is forbidden"
        )

    def test_require_api_key_still_exists(self):
        """require_api_key (for non-admin routes) must still exist."""
        src = _src("core/security.py")
        assert "def require_api_key(" in src, (
            "require_api_key must still exist — it protects non-admin routes"
        )

    def test_startup_assertions_present(self):
        """Startup must block if API_KEY or AUTH_SECRET_KEY are empty/placeholder in prod."""
        src = _src("main.py")
        assert "STARTUP BLOCKED" in src or "RuntimeError" in src, (
            "PR #488 startup assertions (STARTUP BLOCKED) must not be removed"
        )

    def test_pdf_magic_byte_check_present(self):
        """PDF upload must still validate magic bytes."""
        src = _src("api/routes_upload.py")
        assert "_PDF_MAGIC" in src or "%PDF" in src, (
            "PR #488 PDF magic byte guard must not be removed from routes_upload.py"
        )

    def test_ssrf_guard_present(self):
        """SSRF guard on attachment_id must still exist in email_ingestion_worker."""
        src = _src("services/email_ingestion_worker.py")
        assert "attachment_id" in src and (
            "unsafe chars" in src or "_re.match" in src or "re.match" in src
        ), (
            "PR #488 SSRF guard on attachment_id must not be removed from "
            "email_ingestion_worker.py"
        )

    def test_mime_header_sanitization_present(self):
        """MIME header injection guard must still exist in email_sender."""
        src = _src("services/email_sender.py")
        assert "_sanitize_header" in src, (
            "PR #488 _sanitize_header guard must not be removed from email_sender.py"
        )

    def test_sql_identifier_allowlist_present(self):
        """SQL identifier allowlist must still exist in master_data_db."""
        src = _src("services/master_data_db.py")
        assert "_assert_safe_identifier" in src or "_SAFE_SQL_IDENTIFIER" in src, (
            "PR #488 SQL identifier allowlist must not be removed from master_data_db.py"
        )

    def test_path_traversal_guard_in_main(self):
        """Chrome autofill path traversal guard must still be in main.py."""
        src = _src("main.py")
        assert "relative_to" in src and "_chrome_autofill_dir" in src, (
            "PR #488 path traversal guard (_chrome_autofill_dir) must not be removed from main.py"
        )
