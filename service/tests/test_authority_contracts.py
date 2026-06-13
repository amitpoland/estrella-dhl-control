"""
test_authority_contracts.py — Authority Audit Tool contracts (Campaign 02.5 Part A)

Static contracts (C1-C6) ensuring authority module integrity:
- C1: Golden-table parity for name_normalization.py functions
- C2: Duplicate-implementation grep (no orphaned authority code)
- C3: Unreachable-code AST check on registered projector functions
- C4: Purity/isolation sweep on registered authority modules
- C5: Dedup-key SQL contract for tracking_db.py
- C6: AWB authority wiring in routes_carrier_actions.py

Design reference: designs/audit-drift-design.md v2 (APPROVED)
Registry: 4 authority modules per the approved design
"""
from __future__ import annotations

import ast
import inspect
import os
import sqlite3
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

# Test imports
from app.services import name_normalization
from app.services import dhl_followup_authority
from app.services import awb_address_authority
from app.services import tracking_db


class TestAuthorityContracts:
    """Static authority audit contracts from Campaign 02.5 design v2."""

    def test_c1_golden_table_parity_name_normalization(self):
        """C1: Golden-table contract for name_normalization.py functions.

        Literal (input, expected) pairs covering Unicode edge cases.
        Expected outputs are LITERAL STRINGS - readable in diffs,
        failure localizes to exact character, any regeneration is visible.
        Covers all 7 real public functions with diacritic/NFKC/Turkish/legal-suffix probes.
        """
        # Golden table for customer_resolution_normalize_name
        customer_cases = [
            ('Łódź Spółka', 'łódź spółka'),
            ('Søren Kierkegård', 'søren kierkegård'),
            ('Þórsson', 'þórsson'),
            ('Große Straße GmbH', 'große straße gmbh'),
            ('Ðorđe', 'ðorđe'),
            ("Œuvre d'Art", "œuvre d'art"),
            ('Ærøskøbing', 'ærøskøbing'),
            ('Ｉｔｅｍ ２０２６', 'ｉｔｅｍ ２０２６'),  # fullwidth digits
            ('İstanbul', 'i̇stanbul'),  # Turkish İ
            ('ıçecek', 'ıçecek'),  # Turkish ı
            ('Kowalski Sp. z o.o.', 'kowalski sp. z o.o.'),
            ('Estrella Jewels LLP.', 'estrella jewels llp.'),
            ('Co., Ltd.', 'co., ltd.'),
            ('Multiple   Spaces', 'multiple spaces'),
            ('Trailing.,;:!', 'trailing.,;:!'),
            ('', ''),
            (None, ''),
        ]

        for input_val, expected in customer_cases:
            actual = name_normalization.customer_resolution_normalize_name(input_val)
            assert actual == expected, (
                f"customer_resolution_normalize_name({input_val!r}) = {actual!r}, expected {expected!r}"
            )

        # Golden table for proforma_normalize_client_name
        proforma_cases = [
            ('Łódź Spółka', 'Łódź Spółka'),
            ('Søren Kierkegård', 'Søren Kierkegård'),
            ('Þórsson', 'Þórsson'),
            ('Große Straße GmbH', 'Große Straße GmbH'),
            ('Ðorđe', 'Ðorđe'),
            ("Œuvre d'Art", "Œuvre d'Art"),
            ('Ærøskøbing', 'Ærøskøbing'),
            ('Ｉｔｅｍ ２０２６', 'Ｉｔｅｍ ２０２６'),
            ('İstanbul', 'İstanbul'),
            ('ıçecek', 'ıçecek'),
            ('Kowalski Sp. z o.o.', 'Kowalski Sp. z o.o.'),
            ('Estrella Jewels LLP.', 'Estrella Jewels LLP.'),
            ('Co., Ltd.', 'Co., Ltd.'),
            ('Multiple   Spaces', 'Multiple Spaces'),
            ('Trailing.,;:!', 'Trailing.,;:!'),
            ('', ''),
        ]

        for input_val, expected in proforma_cases:
            actual = name_normalization.proforma_normalize_client_name(input_val)
            assert actual == expected, (
                f"proforma_normalize_client_name({input_val!r}) = {actual!r}, expected {expected!r}"
            )

        # Golden table for suppliers_db_normalize_name
        suppliers_cases = [
            ('Łódź Spółka', 'łódź spółka'),
            ('Søren Kierkegård', 'søren kierkegård'),
            ('Þórsson', 'þórsson'),
            ('Große Straße GmbH', 'große straße gmbh'),
            ('Ðorđe', 'ðorđe'),
            ("Œuvre d'Art", 'œuvre d art'),
            ('Ærøskøbing', 'ærøskøbing'),
            ('Ｉｔｅｍ ２０２６', 'ｉｔｅｍ ２０２６'),
            ('İstanbul', 'i stanbul'),
            ('ıçecek', 'ıçecek'),
            ('Kowalski Sp. z o.o.', 'kowalski sp z o o'),
            ('Estrella Jewels LLP.', 'estrella jewels llp'),
            ('Co., Ltd.', 'co ltd'),
            ('Multiple   Spaces', 'multiple spaces'),
            ('Trailing.,;:!', 'trailing'),
            ('', ''),
        ]

        for input_val, expected in suppliers_cases:
            actual = name_normalization.suppliers_db_normalize_name(input_val)
            assert actual == expected, (
                f"suppliers_db_normalize_name({input_val!r}) = {actual!r}, expected {expected!r}"
            )

        # Golden table for wfirma_auto_resolve_normalize_name
        wfirma_auto_cases = [
            ('Łódź Spółka', 'Łódź Spółka'),
            ('Søren Kierkegård', 'Søren Kierkegård'),
            ('Þórsson', 'Þórsson'),
            ('Große Straße GmbH', 'Große Straße GmbH'),
            ('Ðorđe', 'Ðorđe'),
            ("Œuvre d'Art", "Œuvre d'Art"),
            ('Ærøskøbing', 'Ærøskøbing'),
            ('Ｉｔｅｍ ２０２６', 'Ｉｔｅｍ ２０２６'),
            ('İstanbul', 'İstanbul'),
            ('ıçecek', 'ıçecek'),
            ('Kowalski Sp. z o.o.', 'Kowalski Sp. z o.o.'),
            ('Estrella Jewels LLP.', 'Estrella Jewels LLP.'),
            ('Co., Ltd.', 'Co., Ltd.'),
            ('Multiple   Spaces', 'Multiple Spaces'),
            ('Trailing.,;:!', 'Trailing.,;:!'),
            ('', ''),
        ]

        for input_val, expected in wfirma_auto_cases:
            actual = name_normalization.wfirma_auto_resolve_normalize_name(input_val)
            assert actual == expected, (
                f"wfirma_auto_resolve_normalize_name({input_val!r}) = {actual!r}, expected {expected!r}"
            )

        # Golden table for master_data_norm (NFD decomposed results)
        master_data_cases = [
            ('Łódź Spółka', 'łódź spółka'),
            ('Søren Kierkegård', 'søren kierkegård'),
            ('Þórsson', 'þórsson'),
            ('Große Straße GmbH', 'große straße'),
            ('Ðorđe', 'ðorđe'),
            ("Œuvre d'Art", "œuvre d'art"),
            ('Ærøskøbing', 'ærøskøbing'),
            ('Ｉｔｅｍ ２０２６', 'ｉｔｅｍ ２０２６'),
            ('İstanbul', 'i̇stanbul'),
            ('ıçecek', 'ıçecek'),
            ('Kowalski Sp. z o.o.', 'kowalski'),
            ('Estrella Jewels LLP.', 'estrella jewels llp.'),
            ('Co., Ltd.', 'co., ltd.'),
            ('Multiple   Spaces', 'multiple spaces'),
            ('Trailing.,;:!', 'trailing.,;:!'),
            ('', ''),
            (None, ''),
        ]

        for input_val, expected in master_data_cases:
            actual = name_normalization.master_data_norm(input_val)
            # master_data_norm is the ONLY authority fn that emits NFD-decomposed
            # output (uses unicodedata.normalize("NFD", ...)); the golden literals
            # above are stored composed (NFC) for diff-readability. Pin the real
            # NFD form explicitly so a regression to NFC/NFKC output is caught.
            expected = unicodedata.normalize("NFD", expected)
            assert actual == expected, (
                f"master_data_norm({input_val!r}) = {actual!r}, expected {expected!r}"
            )

        # Golden table for packing_contractor_normalise_name
        packing_cases = [
            ('Łódź Spółka', 'lodz spolka'),  # ASCII fallback
            ('Søren Kierkegård', 'soren kierkegard'),
            ('Þórsson', 'thorsson'),
            ('Große Straße GmbH', 'grosse strasse'),  # gmbh suffix removed
            ('Ðorđe', 'dor e'),  # ð -> d, đ -> unclear fallback
            ("Œuvre d'Art", 'uvre d art'),
            ('Ærøskøbing', 'aeroskobing'),
            ('Ｉｔｅｍ ２０２６', 'item 2026'),  # NFKD fullwidth folding
            ('İstanbul', 'istanbul'),
            ('ıçecek', 'cecek'),
            ('Kowalski Sp. z o.o.', 'kowalski'),
            ('Estrella Jewels LLP.', 'estrella jewels'),
            ('Co., Ltd.', ''),  # entire thing removed as legal suffix
            ('Multiple   Spaces', 'multiple spaces'),
            ('Trailing.,;:!', 'trailing'),
            ('', ''),
            (None, ''),
        ]

        for input_val, expected in packing_cases:
            actual = name_normalization.packing_contractor_normalise_name(input_val)
            assert actual == expected, (
                f"packing_contractor_normalise_name({input_val!r}) = {actual!r}, expected {expected!r}"
            )

        # Golden table for wfirma_sync_normalise_client_name
        wfirma_sync_cases = [
            ('Łódź Spółka', 'łódź spółka'),
            ('Søren Kierkegård', 'søren kierkegård'),
            ('Þórsson', 'þórsson'),
            ('Große Straße GmbH', 'grosse strasse gmbh'),  # NFKC casefold ß -> ss
            ('Ðorđe', 'ðorđe'),
            ("Œuvre d'Art", "œuvre d'art"),
            ('Ærøskøbing', 'ærøskøbing'),
            ('Ｉｔｅｍ ２０２６', 'item 2026'),  # NFKC fullwidth normalization
            ('İstanbul', 'i̇stanbul'),
            ('ıçecek', 'ıçecek'),
            ('Kowalski Sp. z o.o.', 'kowalski sp. z o.o'),  # trailing punct removed
            ('Estrella Jewels LLP.', 'estrella jewels llp'),
            ('Co., Ltd.', 'co., ltd'),
            ('Multiple   Spaces', 'multiple spaces'),
            ('Trailing.,;:!', 'trailing'),
            ('', ''),
        ]

        for input_val, expected in wfirma_sync_cases:
            actual = name_normalization.wfirma_sync_normalise_client_name(input_val)
            assert actual == expected, (
                f"wfirma_sync_normalise_client_name({input_val!r}) = {actual!r}, expected {expected!r}"
            )

    def test_c2_duplicate_implementation_detection(self):
        """C2: Grep-based duplicate-implementation detection.

        (a) No str.maketrans tables with diacritic keys outside name_normalization.py
        (b) No orphaned normalization function definitions outside delegates
        """
        service_root = Path(__file__).parent.parent / "app"

        # C2(a): No duplicate str.maketrans tables with diacritic keys
        # Search for str.maketrans usage outside name_normalization.py
        diacritic_keys = ["ł", "Ł", "ø", "Ø", "æ", "Æ", "å", "Å", "ß", "þ", "Þ", "ð", "Ð"]

        violations = []
        for py_file in service_root.rglob("*.py"):
            if py_file.name == "name_normalization.py":
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                if "str.maketrans" in content:
                    # Check if any diacritic keys appear in the same file
                    for key in diacritic_keys:
                        if key in content:
                            violations.append(f"{py_file.relative_to(service_root)}: str.maketrans + diacritic key '{key}'")
                            break
            except Exception:
                pass  # Skip files we can't read

        assert not violations, (
            f"Found duplicate str.maketrans tables with diacritic keys: {violations}. "
            f"All diacritic translation should use name_normalization.py only."
        )

        # C2(b): No legacy normalization function definitions outside allowed delegates
        # Four full names across service/app/**/*.py with 7-file allowed-list
        legacy_names = [
            "_normalize_name",
            "_normalize_client_name",
            "normalise_name",
            "normalise_client_name"
        ]

        # Allowed one-line delegates (exactly the 7 delegate host files from pinned facts)
        allowed_delegates = [
            "packing_contractor_resolver.py",
            "customer_resolution_authority.py",
            "routes_proforma.py",
            "suppliers_db.py",
            "wfirma_customer_auto_resolve.py",
            "master_data_intelligence.py",
            "wfirma_customer_sync.py"
        ]

        violations = []
        for py_file in service_root.rglob("*.py"):
            if py_file.name == "name_normalization.py":
                continue  # Skip the authority module itself

            if py_file.name in allowed_delegates:
                continue  # Skip allowed delegate files

            try:
                content = py_file.read_text(encoding="utf-8")
                for func_name in legacy_names:
                    if f"def {func_name}(" in content:
                        violations.append(f"{py_file.relative_to(service_root)}: def {func_name}()")
            except Exception:
                pass

        assert not violations, (
            f"Found legacy normalization function definitions: {violations}. "
            f"All normalization should delegate to name_normalization.py or be in allowed delegate files: {allowed_delegates}"
        )

        # C2(c): _norm checked ONLY in master_data_intelligence.py (must be delegate)
        # Design narrowing: 4 out-of-scope _norm helpers elsewhere (agency_sad_decision.py:79 MRN normalizer,
        # routes_proforma.py:60 strip/upper key, sales_linkage.py:75 and wfirma_reservation.py:70 whitespace-collapse/upper keys)
        master_data_file = service_root / "master_data_intelligence.py"
        if master_data_file.exists():
            try:
                content = master_data_file.read_text(encoding="utf-8")
                if "def _norm(" in content:
                    # Ensure it delegates to name_normalization.master_data_norm
                    assert "name_normalization.master_data_norm" in content, (
                        "master_data_intelligence.py _norm must delegate to name_normalization.master_data_norm"
                    )
                else:
                    pytest.fail("master_data_intelligence.py must contain _norm delegate function")
            except Exception as e:
                pytest.fail(f"Could not read master_data_intelligence.py: {e}")

    def test_c3_unreachable_code_ast_check(self):
        """C3: AST unreachable-code-after-return check on registered projectors.

        Scoped to registered functions: project_automation_status, project_shipment_rows
        in dhl_followup_authority.py (the verified failure surface from B6).
        """
        dhl_followup_file = Path(__file__).parent.parent / "app" / "services" / "dhl_followup_status_projector.py"

        if not dhl_followup_file.exists():
            pytest.fail(f"Authority module not found: {dhl_followup_file}")

        content = dhl_followup_file.read_text(encoding="utf-8")

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in {dhl_followup_file}: {e}")

        # Find the two registered projector functions
        target_functions = ["project_automation_status", "project_shipment_rows"]
        found_functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in target_functions:
                found_functions.append(node.name)

                # Check for unreachable code after return statements
                unreachable_violations = []

                def check_unreachable_after_return(body: List[ast.stmt], func_name: str):
                    """Check for code after return statements that isn't reachable."""
                    for i, stmt in enumerate(body):
                        if isinstance(stmt, ast.Return):
                            # Check if there are more statements after this return
                            remaining = body[i+1:]
                            for j, remaining_stmt in enumerate(remaining):
                                # Skip comments (they don't exist in AST) and docstrings
                                if isinstance(remaining_stmt, ast.Expr) and isinstance(remaining_stmt.value, ast.Constant):
                                    continue  # Skip docstring constants

                                # This is actual code after return - unreachable
                                line_no = remaining_stmt.lineno if hasattr(remaining_stmt, 'lineno') else '?'
                                unreachable_violations.append(f"Line {line_no}: code after return in {func_name}")

                        # Recursively check compound statements
                        if hasattr(stmt, 'body'):
                            check_unreachable_after_return(stmt.body, func_name)
                        if hasattr(stmt, 'orelse'):
                            check_unreachable_after_return(stmt.orelse, func_name)
                        if hasattr(stmt, 'handlers'):
                            for handler in stmt.handlers:
                                check_unreachable_after_return(handler.body, func_name)
                        if hasattr(stmt, 'finalbody'):
                            check_unreachable_after_return(stmt.finalbody, func_name)

                check_unreachable_after_return(node.body, node.name)

                assert not unreachable_violations, (
                    f"Unreachable code after return in {node.name}: {unreachable_violations}"
                )

        # Verify we found both target functions
        missing = set(target_functions) - set(found_functions)
        assert not missing, f"Missing registered projector functions: {missing}"

    def test_c4_purity_isolation_sweep(self):
        """C4: Registry-driven purity/isolation sweep on authority modules.

        Forbidden imports: smtplib, email_service, queue_email, requests, routes_
        Authority modules must be pure/stdlib-only per Lesson E isolation.
        """
        # Registry of 4 authority modules per approved design
        authority_registry = {
            "name_normalization.py": "Name normalization authority",
            "dhl_followup_authority.py": "DHL follow-up authority (4-state advisory)",
            "awb_address_authority.py": "AWB address resolution authority",
            "tracking_db.py": "Tracking deduplication authority (dedup region only)"
        }

        forbidden_imports = [
            "smtplib",
            "email_service",
            "queue_email",
            "requests",
            "routes_"  # Any routes_ module indicates coupling to web layer
        ]

        service_root = Path(__file__).parent.parent / "app" / "services"
        violations = []

        for module_file, role in authority_registry.items():
            module_path = service_root / module_file

            if not module_path.exists():
                pytest.fail(f"Registry violation: Authority module missing: {module_path} ({role})")

            try:
                content = module_path.read_text(encoding="utf-8")

                for forbidden in forbidden_imports:
                    if forbidden in content:
                        # More precise check to avoid false positives in comments
                        lines = content.split('\n')
                        for line_no, line in enumerate(lines, 1):
                            line = line.strip()
                            if (line.startswith(f'import {forbidden}') or
                                line.startswith(f'from {forbidden}') or
                                f'import {forbidden}' in line or
                                f'from {forbidden}' in line):
                                violations.append(f"{module_file}:{line_no}: forbidden import '{forbidden}'")

            except Exception as e:
                pytest.fail(f"Could not read authority module {module_path}: {e}")

        assert not violations, (
            f"Purity violations in authority modules: {violations}. "
            f"Authority modules must be pure/stdlib-only per Lesson E isolation."
        )

    def test_c5_tracking_dedup_sql_contract(self):
        """C5: Dedup-key SQL contract for tracking_db.py dedup function.

        Assert the dedup SQL contains all 7 column predicates:
        batch_id, awb, stage, event_time, source_ref, email_message_id, direction
        Scoped to the SOURCE OF record_event function only (file-precise).
        """
        import inspect

        # Get the record_event function source directly
        try:
            record_event_source = inspect.getsource(tracking_db.record_event)
        except Exception as e:
            pytest.fail(f"Could not extract record_event function source: {e}")

        # Required dedup columns per design
        required_columns = [
            "batch_id",
            "awb",
            "stage",
            "event_time",
            "source_ref",
            "email_message_id",
            "direction"  # This is the key addition from the tracking campaign
        ]

        missing_columns = []

        # Search for SQL WHERE clause patterns within the function source only
        for col in required_columns:
            # Look for SQL patterns like "col=?" or "col = ?" or "col IS ?"
            if not (f"{col}=?" in record_event_source or f"{col} = ?" in record_event_source or f"{col} IS ?" in record_event_source):
                missing_columns.append(col)

        assert not missing_columns, (
            f"Missing required dedup columns in tracking_db.record_event function: {missing_columns}. "
            f"All 7 columns must be present in dedup WHERE clause: {required_columns}"
        )

    def test_c6_awb_authority_wiring(self):
        """C6: AWB authority wiring in routes_carrier_actions.py.

        Two assertions per challenger resolution:
        (a) Import presence of awb_address_authority module
        (b) Call site presence of derive_awb_address_authority_with_fallback
        """
        routes_file = Path(__file__).parent.parent / "app" / "api" / "routes_carrier_actions.py"

        if not routes_file.exists():
            pytest.fail(f"Routes file not found: {routes_file}")

        content = routes_file.read_text(encoding="utf-8")

        # C6(a): Import presence check
        awb_import_patterns = [
            "from ..services import awb_address_authority",
            "from app.services import awb_address_authority",
            "import awb_address_authority",
            "from ..services.awb_address_authority import"  # Conditional import pattern
        ]

        has_awb_import = any(pattern in content for pattern in awb_import_patterns)
        assert has_awb_import, (
            f"Missing AWB address authority import in routes_carrier_actions.py. "
            f"Expected one of: {awb_import_patterns}"
        )

        # C6(b): Call site presence check (around lines 122-126 per design)
        function_name = "derive_awb_address_authority_with_fallback"
        assert function_name in content, (
            f"Missing call site for {function_name} in routes_carrier_actions.py. "
            f"AWB authority must be used for address resolution."
        )

        # Additional check: ensure it's actually being called, not just mentioned in comments
        # Look for function call patterns
        call_patterns = [
            f"{function_name}(",
            f"awb_address_authority.{function_name}("
        ]

        has_call = any(pattern in content for pattern in call_patterns)
        assert has_call, (
            f"AWB authority function {function_name} is imported but not called. "
            f"Expected call pattern in routes_carrier_actions.py."
        )