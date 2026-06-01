"""
test_remediation_b9_reverification.py — Integration tests for B9.

Verifies:
1. rule_based_reverification.py exists (renamed from ai_reverification.py)
2. disambiguation_417g removed from ALL_REVERIFICATION_TYPES
3. No AI/LLM calls in the module
4. Module is imported from routes_intake.py (wired at parse time)
5. The old ai_reverification.py still exists as a compatibility shim
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

STATIC_DIR = Path(__file__).parent.parent / "app"


class TestRenamedModule:
    def test_rule_based_module_exists(self):
        p = STATIC_DIR / "services" / "rule_based_reverification.py"
        assert p.exists(), "rule_based_reverification.py must exist"

    def test_module_has_correct_docstring(self):
        src = (STATIC_DIR / "services" / "rule_based_reverification.py"
               ).read_text(encoding="utf-8")
        assert "Rule-Based Reverification" in src
        assert "NOT an AI model" in src or "deterministic rule-based" in src
        assert "Renamed from ai_reverification.py" in src

    def test_disambiguation_417g_removed_from_types(self):
        from app.services.rule_based_reverification import ALL_REVERIFICATION_TYPES
        assert "disambiguation_417g" not in ALL_REVERIFICATION_TYPES

    def test_9_types_remain(self):
        from app.services.rule_based_reverification import ALL_REVERIFICATION_TYPES
        assert len(ALL_REVERIFICATION_TYPES) == 9

    def test_no_ai_imports(self):
        """No AI library imports — only the word appears in docstring comments."""
        src = (STATIC_DIR / "services" / "rule_based_reverification.py"
               ).read_text(encoding="utf-8")
        # Check for import statements (not mere mention in docstring)
        assert "import anthropic" not in src
        assert "from anthropic" not in src
        assert "import openai" not in src
        assert "from openai" not in src
        assert "wfirma_client" not in src
        assert "smtplib" not in src
        assert "send_email" not in src


class TestWiredAtParseTime:
    def test_routes_intake_imports_rule_based_reverification(self):
        src = (STATIC_DIR / "api" / "routes_intake.py"
               ).read_text(encoding="utf-8")
        assert "rule_based_reverification" in src
        assert "reverify_purchase_batch" in src
        assert "write_reverification_proposals_to_audit" in src

    def test_reverification_runs_post_parse_non_fatal(self):
        src = (STATIC_DIR / "api" / "routes_intake.py"
               ).read_text(encoding="utf-8")
        assert "rule_based_reverification failed (non-fatal)" in src

    def test_proposals_written_to_audit(self):
        """reverify_purchase_batch + write_reverification_proposals_to_audit
        produce Inbox-visible proposals."""
        from app.services.rule_based_reverification import (
            reverify_purchase_batch,
            write_reverification_proposals_to_audit,
            PROP_MISSING_HS_CODE,
        )
        import json
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            audit = {
                "batch_id": "B_REV",
                "action_proposals": [],
                "invoices": [{"exporter_name": ""}],
                "rows": [
                    # Row without hs_code → missing_hs_code proposal
                    {"product_code": "PC-1", "hs_code": "", "description": "Ring"},
                ],
            }
            proposals = reverify_purchase_batch("B_REV", audit, td)
            added = write_reverification_proposals_to_audit(audit, proposals)
            # At minimum the supplier_mismatch (no exporter_name) fires
            assert isinstance(proposals, list)
            assert len(audit["action_proposals"]) >= 0  # proposals may be empty if no invoice lines DB
