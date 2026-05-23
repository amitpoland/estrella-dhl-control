"""
test_ai_advisory_no_writes.py — Safety/source-grep proof tests.

Enforces docs/ai-governance/ai-capability-map.md §6 forbidden-action list
on the Phase 1 AI advisory surface.

If any of these tests fail, the PR must NOT merge — the contract has
drifted.
"""
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE   = REPO_ROOT / "service" / "app"

ADVISORY_SERVICE_PATH = SERVICE / "services" / "ai_advisory.py"
ADVISORY_ROUTE_PATH   = SERVICE / "api" / "routes_ai_advisory.py"


def _executable_source(path: Path) -> str:
    """
    Return the file's executable source with docstrings stripped.

    Uses AST round-trip so the unparsed source preserves real code
    structure (decorators, attribute access, etc.) while every module-,
    class-, and function-level docstring is removed. Inline string
    literals that intentionally contain a forbidden symbol would still
    be visible — that is acceptable, since intentionally embedding such
    a literal in executable code is itself a smell.

    The Phase 1 modules document the forbidden-symbol list inside their
    own docstrings; raw grep would false-positive on those.
    """
    import ast
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Strip docstrings from Module, FunctionDef, AsyncFunctionDef, ClassDef.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# ── Source-grep proofs: the advisory module imports nothing forbidden ────────

@pytest.mark.parametrize("forbidden", [
    "wfirma_writer",
    "wfirma_create",
    "queue_email",
    "smtplib",
    "execute_action",
    "dhl_send",
    "dhl_orchestrator",
    "process_batch",
])
def test_ai_advisory_service_imports_no_forbidden_symbols(forbidden: str) -> None:
    """AI advisory service must not reference any write-path symbol."""
    src = _executable_source(ADVISORY_SERVICE_PATH)
    assert forbidden not in src, (
        f"ai_advisory.py references forbidden symbol {forbidden!r} — "
        f"capability map §6 violation"
    )


@pytest.mark.parametrize("forbidden", [
    "wfirma_writer",
    "wfirma_create",
    "queue_email",
    "smtplib",
    "execute_action",
    "dhl_send",
    "/api/v1/execute",
])
def test_ai_advisory_route_imports_no_forbidden_symbols(forbidden: str) -> None:
    """AI advisory route module must not reference any write-path symbol."""
    src = _executable_source(ADVISORY_ROUTE_PATH)
    assert forbidden not in src, (
        f"routes_ai_advisory.py references forbidden symbol {forbidden!r} — "
        f"capability map §6 violation"
    )


# ── No write HTTP verbs on the advisory router ───────────────────────────────

def test_advisory_route_declares_no_write_verbs() -> None:
    """The advisory router must only expose GET endpoints."""
    src = _executable_source(ADVISORY_ROUTE_PATH)
    for verb in ("router.post", "router.put", "router.delete", "router.patch"):
        assert verb not in src, (
            f"routes_ai_advisory.py declares @{verb} — advisory class R "
            f"is read-only by contract"
        )
    # Sanity: at least one GET is registered.
    assert "router.get" in src, "advisory route must declare at least one GET"


# ── No database write operations in the advisory service ─────────────────────

@pytest.mark.parametrize("write_op", [
    "INSERT INTO",
    "UPDATE ",
    "DELETE FROM",
    "CREATE TABLE",
    "DROP TABLE",
    ".commit(",
    "open(",  # accidental file write
    ".write(",
    ".write_text(",
])
def test_ai_advisory_service_has_no_write_operations(write_op: str) -> None:
    """The advisory service must not perform any write operation."""
    src = _executable_source(ADVISORY_SERVICE_PATH)
    # `open(`/`.write` are allowed if they're inside docstrings / comments —
    # but the simplest enforcement is: the working set has none. Re-evaluate
    # if a legitimate need arises.
    assert write_op not in src, (
        f"ai_advisory.py contains {write_op!r} — capability map §6 violation"
    )


# ── No HTTP outbound calls to live integration endpoints ─────────────────────

@pytest.mark.parametrize("forbidden", [
    "requests.post",
    "requests.put",
    "requests.delete",
    "httpx.post",
    "httpx.put",
    "httpx.delete",
    "urllib.request.urlopen",
])
def test_ai_advisory_service_makes_no_outbound_writes(forbidden: str) -> None:
    src = _executable_source(ADVISORY_SERVICE_PATH)
    assert forbidden not in src, (
        f"ai_advisory.py would issue an outbound write via {forbidden!r}"
    )


# ── Public contract: advisory result always reports llm_used=False in Phase 1 ──

def test_ai_advisory_phase1_reports_llm_not_used() -> None:
    """
    Phase 1 ships no LLM call. The `llm_used` field on the result must be
    hard-False so the surface is honest about Phase 1's deterministic path.
    """
    src = ADVISORY_SERVICE_PATH.read_text(encoding="utf-8")
    # Look for the literal assignment in the result dict.
    assert re.search(r'"llm_used"\s*:\s*False', src), (
        '"llm_used": False must remain in the Phase 1 advisory result. '
        "Phase 2 may change this only with a corresponding capability-map update."
    )


# ── Capability-map document exists and pins forbidden list ───────────────────

def test_capability_map_document_exists() -> None:
    doc = REPO_ROOT / "docs" / "ai-governance" / "ai-capability-map.md"
    assert doc.exists(), "AI capability map document missing"
    text = doc.read_text(encoding="utf-8")
    for marker in (
        "Forbidden-Action List",
        "wfirma_writer",
        "execute_action",
    ):
        assert marker in text, f"capability map missing required marker: {marker!r}"
