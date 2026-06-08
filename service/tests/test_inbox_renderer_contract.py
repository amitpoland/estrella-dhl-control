"""
test_inbox_renderer_contract.py — PERMANENT architectural guard.

Inbox is a RENDERER, not a workflow engine. Per the Proforma Source D authority
contract (PROJECT_STATE 2026-06-08): Inbox aggregates existing authority and
emits pointers to existing endpoints; it never owns draft lifecycle, readiness,
or invoice conversion.

This guard fails the moment any write route (@router.post/put/patch/delete) is
added to routes_inbox.py — blocking the "second workflow engine" anti-pattern at
merge time, independent of any feature branch. Complements the Source-D suite's
``test_no_write_imports_in_inbox`` (which guards write *imports*); this guards
write *routes*.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_WRITE_METHODS = {"post", "put", "patch", "delete"}


def _inbox_source() -> str:
    spec = importlib.util.find_spec("app.api.routes_inbox")
    assert spec is not None and spec.origin, "routes_inbox module not found"
    return Path(spec.origin).read_text(encoding="utf-8")


def _router_methods() -> list:
    """Return [(func_name, http_method)] for every @router.<method> decorator."""
    tree = ast.parse(_inbox_source())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                call = dec.func if isinstance(dec, ast.Call) else dec
                if (isinstance(call, ast.Attribute)
                        and isinstance(call.value, ast.Name)
                        and call.value.id == "router"):
                    found.append((node.name, call.attr))
    return found


def test_routes_inbox_is_get_only():
    """routes_inbox.py must expose ONLY @router.get — never a write route."""
    violations = [(fn, m) for fn, m in _router_methods() if m in _WRITE_METHODS]
    assert not violations, (
        "routes_inbox.py must be GET-only (Inbox renderer contract). "
        f"Write routes found: {violations}. Inbox must never own lifecycle / "
        "readiness / conversion — point to existing proforma endpoints instead."
    )


def test_routes_inbox_has_at_least_one_get():
    """Guard against a vacuous pass: there must be a real @router.get route."""
    gets = [fn for fn, m in _router_methods() if m == "get"]
    assert gets, "expected at least one @router.get route in routes_inbox.py"
