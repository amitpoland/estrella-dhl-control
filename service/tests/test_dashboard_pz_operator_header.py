"""
test_dashboard_pz_operator_header.py — frontend-only regression for
the X-Operator header propagation on PZ create / adopt actions.

We grep dashboard.html source so the assertions are deterministic and
do not depend on a JS runtime. The same approach is used by the other
dashboard surface tests in this repo.

Spec checks:
  1. PZ create fetch (both call sites) includes X-Operator header.
  2. PZ adopt fetch includes X-Operator when present.
  3. confirm() flow unchanged.
  4. No endpoint URL changed.
  5. Operator identity helper defined and reused (no inline prompt copies).
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD_HTML = (Path(__file__).resolve().parents[1]
                  / "app" / "static" / "dashboard.html")


def _html() -> str:
    return DASHBOARD_HTML.read_text(encoding="utf-8")


# ── Helper ────────────────────────────────────────────────────────────────

class TestOperatorResolverHelper:
    def test_helper_defined(self):
        h = _html()
        assert "function _resolveOperator()" in h

    def test_helper_uses_localstorage_cache(self):
        h = _html()
        # Cache key + read + write
        assert "pz_operator_name" in h
        assert "localStorage.getItem('pz_operator_name')" in h
        assert "localStorage.setItem('pz_operator_name'" in h

    def test_helper_falls_back_to_default_admin_in_prompt(self):
        h = _html()
        assert "window.prompt('Operator name (recorded in audit timeline):',\n                           'admin'" in h

    def test_helper_handles_cancel_and_disabled_storage(self):
        h = _html()
        # Function body has try/catch around localStorage usage and
        # initialises name to empty so a cancel returns "" (backend
        # falls back to "operator").
        start = h.index("function _resolveOperator()")
        end   = h.index("\n}\n\nasync function apiFetch", start)
        body  = h[start:end]
        assert "let name = ''" in body
        # try/catch guards on both localStorage paths
        assert body.count("try {") >= 3      # cache read + prompt + cache write
        assert body.count("} catch") >= 3


# ── PZ create call sites ──────────────────────────────────────────────────

class TestPzCreateOperatorHeader:
    def _create_blocks(self):
        """Return the two function bodies that call /wfirma/pz_create."""
        h = _html()
        # 1) submitPzCreate (legacy section 3 button)
        a = h.index("const submitPzCreate = React.useCallback")
        a_end = h.index("}, [batchId, onToast, loadPzPreview])", a)
        # 2) ExecutePZGate.onExecute
        b = h.index("const onExecute = React.useCallback")
        # Find the close — onExecute ends with `}, [batchId, refresh, onToast])`
        b_end = h.index("[batchId, refresh, onToast]", b)
        return h[a:a_end], h[b:b_end]

    def test_legacy_submit_pz_create_passes_x_operator(self):
        legacy, _gate = self._create_blocks()
        assert "_resolveOperator()" in legacy
        assert "'X-Operator'" in legacy
        # Endpoint unchanged
        assert "/wfirma/pz_create" in legacy
        # Method still POST
        assert "method: 'POST'" in legacy

    def test_executepz_gate_passes_x_operator(self):
        _legacy, gate = self._create_blocks()
        assert "_resolveOperator()" in gate
        assert "'X-Operator'" in gate
        assert "/wfirma/pz_create" in gate
        assert "method: 'POST'" in gate
        # Existing API-key header path preserved
        assert "window.__apiHeaders" in gate

    def test_executepz_gate_confirm_flow_intact(self):
        _legacy, gate = self._create_blocks()
        assert "window.confirm(" in gate
        # Phase 3: confirm dialog updated from "Execute PZ in wFirma?" to more descriptive text.
        assert "Create goods receipt in wFirma?" in gate or "Execute PZ in wFirma?" in gate
        # The confirm runs BEFORE _resolveOperator (don't prompt for
        # name when the user already cancelled the action)
        idx_confirm = gate.index("window.confirm(")
        idx_resolve = gate.index("_resolveOperator()")
        assert idx_confirm < idx_resolve

    def test_executepz_gate_resolves_after_confirm(self):
        """Operator prompt only appears after the operator confirms,
        avoiding an annoying second dialog when they cancel."""
        _legacy, gate = self._create_blocks()
        # If confirm returned false the function returns immediately
        assert "if (!window.confirm(" in gate
        assert ")) return" in gate


# ── PZ adopt call site ────────────────────────────────────────────────────

class TestPzAdoptOperatorHeader:
    def _adopt_block(self):
        h = _html()
        a = h.index("const submitPzAdopt = React.useCallback")
        a_end = h.index("}, [batchId, pzAdoptInput, onToast, loadPzPreview])", a)
        return h[a:a_end]

    def test_pz_adopt_passes_x_operator(self):
        body = self._adopt_block()
        assert "_resolveOperator()" in body
        assert "'X-Operator'" in body
        # Endpoint unchanged
        assert "/wfirma/pz_adopt" in body
        # Existing Content-Type still present
        assert "'Content-Type': 'application/json'" in body

    def test_pz_adopt_method_unchanged(self):
        body = self._adopt_block()
        assert "method: 'POST'" in body


# ── No endpoint URL change ────────────────────────────────────────────────

class TestEndpointsUnchanged:
    def test_pz_create_url_count_unchanged(self):
        h = _html()
        # Two call sites for pz_create remain (legacy + ExecutePZGate)
        n = h.count("/wfirma/pz_create")
        assert n >= 2, f"expected ≥2 pz_create references; got {n}"

    def test_pz_adopt_url_unchanged(self):
        h = _html()
        assert "/wfirma/pz_adopt" in h

    def test_no_new_endpoint_introduced(self):
        h = _html()
        # The only X-Operator-bearing fetches must target the existing
        # pz_create / pz_adopt endpoints — no new URLs spawned.
        for line in h.splitlines():
            if "'X-Operator'" in line and "fetch(" in line:
                # Sanity — every fetch carrying X-Operator hits a known URL
                # (the actual fetch call may be split across lines, so this
                # is a soft check; the explicit URL-count tests above are
                # the hard checks).
                assert any(p in line for p in ("/pz_create", "/pz_adopt"))


# ── Backend tolerance regression ──────────────────────────────────────────

class TestBackendTolerance:
    def test_operator_header_falls_back_to_default_when_missing(self):
        """Backend helper accepts None and returns 'operator'. This is
        the safety net when the dashboard cache is empty AND the
        operator cancels the prompt."""
        from app.api import routes_wfirma as rw
        assert rw._operator_from_header(None)   == "operator"
        assert rw._operator_from_header("")     == "operator"
        assert rw._operator_from_header("   ")  == "operator"
        assert rw._operator_from_header("amit") == "amit"
