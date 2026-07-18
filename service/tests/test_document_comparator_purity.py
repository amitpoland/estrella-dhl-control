"""test_document_comparator_purity.py — Campaign-2 A1.1 · PERMANENT GOVERNANCE.

The single comparison authority ``services.document_comparator`` MUST stay pure:
no database, no HTTP, no filesystem, no audit, no environment mutation, no
subprocess. This is a fiscal comparison gate feeding both the irreversible
invoice-create path and (later) the read-only reconciliation report — any
accidental import of ``sqlite3`` / ``requests`` / ``os`` / an app service would
turn a pure function into a side-effecting authority and break the "readers are
never writers" constitution.

This test is the enforcement mechanism for that rule. It fails CI the moment a
forbidden dependency is introduced. It parses the module's AST (not its runtime
behaviour) so the guard holds even for code paths tests do not execute.

Rule reference: docs/decisions/ADR-invoice-comparison-authority.md.
"""
from __future__ import annotations

import ast
from pathlib import Path

_MODULE = (
    Path(__file__).resolve().parent.parent
    / "app" / "services" / "document_comparator.py"
)

# Only these import roots are permitted. Everything the comparator needs is
# pure-stdlib data handling. Adding to this list is a governance decision and
# must be justified in the ADR.
_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "xml",          # xml.etree.ElementTree — parse only, no I/O
    "dataclasses",
    "decimal",
    "typing",
}

# Modules that must NEVER appear (side-effecting / stateful). Explicit denylist
# on top of the allowlist so the failure message names the offender.
_FORBIDDEN_IMPORT_ROOTS = {
    "sqlite3", "requests", "httpx", "urllib", "http", "socket", "ssl",
    "os", "sys", "subprocess", "shutil", "pathlib", "io", "tempfile",
    "threading", "multiprocessing", "asyncio", "logging", "time", "random",
    "app",  # no reaching into app services/routes/db/audit
}

# Call/attribute patterns that indicate I/O or mutation, checked structurally.
_FORBIDDEN_CALL_NAMES = {"open", "eval", "exec", "compile", "__import__", "print"}
_FORBIDDEN_ATTR_METHODS = {"write", "writelines", "execute", "executemany",
                           "commit", "system", "popen", "getenv", "putenv"}


def _tree():
    return ast.parse(_MODULE.read_text(encoding="utf-8"), filename=str(_MODULE))


def _import_roots(tree) -> set:
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # relative imports (node.level>0) reach into app.* — always forbidden
            if node.level and node.level > 0:
                roots.add("app")
            elif node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_only_allowlisted_imports():
    roots = _import_roots(_tree())
    extra = roots - _ALLOWED_IMPORT_ROOTS
    assert not extra, (
        f"document_comparator.py imports non-allowlisted module(s): {sorted(extra)}. "
        f"The comparator must stay pure — justify in the ADR before extending "
        f"the allowlist."
    )


def test_no_forbidden_imports():
    roots = _import_roots(_tree())
    hit = roots & _FORBIDDEN_IMPORT_ROOTS
    assert not hit, (
        f"document_comparator.py imports FORBIDDEN side-effecting module(s): "
        f"{sorted(hit)}. A pure comparison authority may not do DB/HTTP/FS/env/"
        f"subprocess work."
    )


def test_no_io_or_mutation_calls():
    tree = _tree()
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _FORBIDDEN_CALL_NAMES:
                offenders.append(fn.id)
            elif isinstance(fn, ast.Attribute) and fn.attr in _FORBIDDEN_ATTR_METHODS:
                offenders.append(f".{fn.attr}()")
    assert not offenders, (
        f"document_comparator.py contains I/O / mutation calls: "
        f"{sorted(set(offenders))}. Keep the comparator side-effect free."
    )


def test_single_xml_parse_only():
    """Exactly one XML parse per comparison (performance + purity)."""
    src = _MODULE.read_text(encoding="utf-8")
    assert src.count("fromstring(") == 1, (
        "comparator must parse the actual XML exactly once per call"
    )
    # No ET.parse (file-based) — only fromstring (string-based, pure)
    assert ".parse(" not in src.replace("compare_invoice_plan", ""), (
        "comparator must not use file-based ElementTree.parse()"
    )
