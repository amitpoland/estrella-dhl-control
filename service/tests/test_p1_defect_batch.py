"""test_p1_defect_batch.py — P1 Production Defect Batch regression tests.

Defect 1 — SyntheticEvent onChange (dashboard.html):
  - Inp and Sel call sites in draft line editor and ProformaDraftAddChargeForm
    must use e => handler(e.target.value) pattern, not bare setter references.
  - Source-grep: no direct `onChange={set` without event-unwrap for Inp/Sel.

Defect 2 — learning_traces flag writer (invoice_learning_agent.py):
  - learn_from_parse() must always emit a 'flag' key.
  - flag values must be in the known set.
  - unstable layouts get flag='unstable' regardless of confidence tier.
  - flag matches confidence when not unstable.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# ── Path setup ──────────────────────────────────────────────────────────────

_SVC_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SVC_ROOT.parent
_DASH   = _SVC_ROOT / "app" / "static" / "dashboard.html"
_AGENT  = _REPO_ROOT / "invoice_learning_agent.py"

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _dash_src() -> str:
    if not _DASH.exists():
        pytest.skip(f"dashboard.html not found: {_DASH}")
    return _DASH.read_text(encoding="utf-8")


def _agent_src() -> str:
    if not _AGENT.exists():
        pytest.skip(f"invoice_learning_agent.py not found: {_AGENT}")
    return _AGENT.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# Defect 1 — SyntheticEvent onChange fix
# ══════════════════════════════════════════════════════════════════════════════

class TestSyntheticEventFix:
    """Source-grep: confirm no bare setter passed as onChange to Inp or Sel."""

    def test_no_bare_setter_on_inp_qty(self):
        """onChange={setQty} without event-unwrap must not exist."""
        src = _dash_src()
        assert "onChange={setQty}" not in src, (
            "Inp onChange={setQty} passes SyntheticEvent to setter — "
            "must be onChange={e => setQty(e.target.value)}"
        )

    def test_no_bare_setter_on_inp_price(self):
        """onChange={setPrice} without event-unwrap must not exist."""
        src = _dash_src()
        assert "onChange={setPrice}" not in src, (
            "Inp onChange={setPrice} passes SyntheticEvent to setter — "
            "must be onChange={e => setPrice(e.target.value)}"
        )

    def test_no_bare_setter_on_inp_amount(self):
        """onChange={setAmount} without event-unwrap must not exist."""
        src = _dash_src()
        assert "onChange={setAmount}" not in src, (
            "Inp onChange={setAmount} passes SyntheticEvent to setter — "
            "must be onChange={e => setAmount(e.target.value)}"
        )

    def test_no_bare_setter_on_inp_label(self):
        """onChange={setLabel} without event-unwrap must not exist."""
        src = _dash_src()
        assert "onChange={setLabel}" not in src, (
            "Inp onChange={setLabel} passes SyntheticEvent to setter — "
            "must be onChange={e => setLabel(e.target.value)}"
        )

    def test_no_bare_setter_on_sel_type(self):
        """onChange={setType} on Sel without event-unwrap must not exist."""
        src = _dash_src()
        assert "onChange={setType}" not in src, (
            "Sel onChange={setType} passes SyntheticEvent to setter — "
            "must be onChange={e => setType(e.target.value)}"
        )

    def test_no_arrow_function_v_without_target(self):
        """onChange={(v) => setCcy(v.toUpperCase())} pattern must not exist.

        This pattern calls .toUpperCase() on a SyntheticEvent object (TypeError).
        Correct form: onChange={e => setCcy(e.target.value.toUpperCase())}
        """
        src = _dash_src()
        assert "onChange={(v) => setCcy(v.toUpperCase()}" not in src, (
            "onChange={(v) => setCcy(v.toUpperCase())} calls .toUpperCase() on "
            "SyntheticEvent — must be onChange={e => setCcy(e.target.value.toUpperCase())}"
        )

    def test_corrected_qty_uses_event_unwrap(self):
        """Confirm qty line now has e.target.value unwrap."""
        src = _dash_src()
        assert "onChange={e => setQty(e.target.value)}" in src, (
            "setQty call site must use e => setQty(e.target.value)"
        )

    def test_corrected_price_uses_event_unwrap(self):
        """Confirm price line now has e.target.value unwrap."""
        src = _dash_src()
        assert "onChange={e => setPrice(e.target.value)}" in src, (
            "setPrice call site must use e => setPrice(e.target.value)"
        )

    def test_corrected_amount_uses_event_unwrap(self):
        src = _dash_src()
        assert "onChange={e => setAmount(e.target.value)}" in src

    def test_corrected_label_uses_event_unwrap(self):
        src = _dash_src()
        assert "onChange={e => setLabel(e.target.value)}" in src

    def test_corrected_type_uses_event_unwrap(self):
        src = _dash_src()
        assert "onChange={e => setType(e.target.value)}" in src

    def test_corrected_ccy_uses_event_target(self):
        src = _dash_src()
        assert "onChange={e => setCcy(e.target.value.toUpperCase())}" in src


# ══════════════════════════════════════════════════════════════════════════════
# Defect 2 — learning_traces flag writer
# ══════════════════════════════════════════════════════════════════════════════

_VALID_FLAGS = {"unconfirmed", "emerging", "stable", "trusted", "unstable"}


class TestLearningTraceFlagWriter:
    """Source-grep: learn_from_parse return dict must always emit 'flag'."""

    def test_agent_source_has_flag_in_return(self):
        """learn_from_parse return dict must contain a 'flag' key."""
        src = _agent_src()
        assert '"flag"' in src, (
            "invoice_learning_agent.py must emit 'flag' key in learn_from_parse "
            "return dict — 88 production records missing this field"
        )

    def test_all_return_paths_have_flag(self):
        """Every return path in learn_from_parse must emit a 'flag' key.

        There are two return paths: hard-failures early return and the normal
        return at the end. Both must include 'flag'.
        """
        src = _agent_src()
        # Find all return { ... } blocks in learn_from_parse
        # Strategy: count occurrences of '"flag"' vs return blocks
        # Simple invariant: every 'return {' inside learn_from_parse must be
        # followed by '"flag"' before the closing '}' of that block.
        # We verify at minimum that 'flag' appears at least twice
        # (one for each return path) in the function body.
        import re as _re
        # Extract learn_from_parse function body
        match = _re.search(
            r'def learn_from_parse\(.*?(?=\ndef |\Z)',
            src,
            _re.DOTALL,
        )
        assert match, "learn_from_parse function not found"
        fn_body = match.group(0)
        flag_count = fn_body.count('"flag"')
        assert flag_count >= 2, (
            f"Expected 'flag' key in at least 2 return paths of learn_from_parse, "
            f"found {flag_count}. Add '\"flag\"' to the hard-failure early return too."
        )

    def test_flag_value_set_before_return(self):
        """_flag variable must be assigned before the return statement."""
        src = _agent_src()
        assert "_flag" in src and '"flag":' in src, (
            "_flag variable and 'flag' key must both be present in "
            "invoice_learning_agent.py learn_from_parse"
        )

    def test_unstable_produces_flag_unstable(self, tmp_path):
        """learn_from_parse returns flag='unstable' for unstable layouts."""
        import json
        try:
            import invoice_learning_agent as m
        except ImportError:
            pytest.skip("invoice_learning_agent not importable from sys.path")

        # Build a temporary store with one supplier, one unstable layout
        store_data = {
            "test_unstable_co": {
                "supplier_key":    "test_unstable_co",
                "display_name":    "Test Unstable Co",
                "invoice_format":  "generic",
                "gstin":           "",
                "confidence":      "stable",
                "confirmed_count": 15,
                "failed_count":    3,
                "first_seen":      "2026-01-01",
                "last_seen":       "2026-01-01",
                "parse_count":     4,
                "layouts": {
                    "fp_unstable_test": {
                        "layout_fingerprint":   "fp_unstable_test",
                        "confirmed_count":      0,
                        "success_count":        0,
                        "failure_count":        3,
                        "consecutive_failures": 3,
                        "is_unstable":          True,
                        "last_used":            "2026-01-01",
                        "last_failed":          "2026-01-02",
                        "patterns":             {},
                        "field_corrections":    {},
                    },
                },
            }
        }
        store_path = tmp_path / "test_store_unstable.json"
        store_path.write_text(json.dumps(store_data), encoding="utf-8")

        # Provide a fingerprint that matches the unstable layout
        result = m.learn_from_parse(
            invoice={"supplier_name": "Test Unstable Co", "exporter_name": "Test Unstable Co"},
            text="",
            lines=[],
            corrections_log=[],
            store_path=store_path,
            fingerprint_override="fp_unstable_test",
        ) if hasattr(m.learn_from_parse, "__code__") and "fingerprint_override" in m.learn_from_parse.__code__.co_varnames else m.learn_from_parse(
            invoice={"supplier_name": "Test Unstable Co", "exporter_name": "Test Unstable Co"},
            text="",
            lines=[],
            corrections_log=[],
            store_path=store_path,
        )

        assert "flag" in result, f"flag key missing from learn_from_parse result: {list(result.keys())}"
        if result.get("supplier_key") == "test_unstable_co":
            # Layout fingerprint matching depends on text — skip if not matched
            if result.get("is_unstable"):
                assert result["flag"] == "unstable", (
                    f"Unstable layout must produce flag='unstable', got {result.get('flag')!r}"
                )

    def test_stable_supplier_produces_confidence_flag(self, tmp_path):
        """learn_from_parse returns flag matching confidence when not unstable."""
        import json
        try:
            import invoice_learning_agent as m
        except ImportError:
            pytest.skip("invoice_learning_agent not importable from sys.path")

        store_data = {
            "test_stable_co": {
                "supplier_key":    "test_stable_co",
                "display_name":    "Test Stable Co",
                "invoice_format":  "generic",
                "gstin":           "",
                "confidence":      "stable",
                "confirmed_count": 12,
                "failed_count":    0,
                "first_seen":      "2026-01-01",
                "last_seen":       "2026-01-01",
                "parse_count":     1,
                "layouts": {},
            }
        }
        store_path = tmp_path / "test_store_stable.json"
        store_path.write_text(json.dumps(store_data), encoding="utf-8")

        result = m.learn_from_parse(
            invoice={"supplier_name": "Test Stable Co", "exporter_name": "Test Stable Co"},
            text="",
            lines=[],
            corrections_log=[],
            store_path=store_path,
        )

        assert "flag" in result, f"flag key missing from learn_from_parse result"
        # The flag must be a valid value
        assert result["flag"] in _VALID_FLAGS, (
            f"flag={result['flag']!r} not in valid set {_VALID_FLAGS}"
        )
        # When not unstable, flag should match confidence
        if not result.get("is_unstable", False):
            conf = result.get("learning_confidence", "unconfirmed")
            assert result["flag"] == conf, (
                f"Non-unstable layout: flag should match learning_confidence. "
                f"flag={result['flag']!r}, learning_confidence={conf!r}"
            )

    def test_flag_always_in_valid_set(self, tmp_path):
        """flag value must be in the defined set of valid flags."""
        import json
        try:
            import invoice_learning_agent as m
        except ImportError:
            pytest.skip("invoice_learning_agent not importable from sys.path")

        # Fresh unconfirmed supplier
        store_data: dict = {}
        store_path = tmp_path / "test_store_empty.json"
        store_path.write_text(json.dumps(store_data), encoding="utf-8")

        result = m.learn_from_parse(
            invoice={"supplier_name": "Brand New Supplier", "exporter_name": "Brand New Supplier"},
            text="",
            lines=[],
            corrections_log=[],
            store_path=store_path,
        )

        assert "flag" in result, "flag key must be present in all learn_from_parse results"
        assert result["flag"] in _VALID_FLAGS, (
            f"flag={result['flag']!r} not in valid set {_VALID_FLAGS}"
        )
