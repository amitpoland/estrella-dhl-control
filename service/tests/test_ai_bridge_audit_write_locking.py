"""#991: every audit.json write in import_bridge_result must hold the batch lock.

import_bridge_result had several read-modify-write paths on audit.json that ran
UNLOCKED — including one that writes clearance_status (customs state). A
concurrent writer interleaving between the read and the write loses one side's
changes (whole-file last-writer-wins), the same class fixed for log_event (#982)
and the confirm race (#987).

Two guards:
  1. Structural (AST): every write_json_atomic(audit_path, ...) inside
     import_bridge_result is lexically nested under a `with batch_write_lock(...)`.
     A grep can be fooled by indentation; walking the tree cannot.
  2. Behavioural: two threads racing a locked read-modify-write on one audit.json
     lose no update.
"""
from __future__ import annotations

import ast
import json
import sys
import threading
from pathlib import Path

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.utils.batch_lock import batch_write_lock  # noqa: E402

_ROUTES = _SVC / "app" / "api" / "routes_ai_bridge.py"


def _import_bridge_result_fn() -> ast.FunctionDef:
    tree = ast.parse(_ROUTES.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "import_bridge_result":
            return node
    raise AssertionError("import_bridge_result not found")


def _is_batch_lock_with(node: ast.AST) -> bool:
    """True if `node` is a `with batch_write_lock(...)` statement."""
    if not isinstance(node, ast.With):
        return False
    for item in node.items:
        call = item.context_expr
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                and call.func.id == "batch_write_lock":
            return True
    return False


def _is_audit_write(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "write_json_atomic"
    )


def test_every_audit_write_is_under_the_batch_lock():
    fn = _import_bridge_result_fn()

    # Walk with a "currently inside a batch_write_lock" depth counter.
    unlocked: list[int] = []

    def visit(node: ast.AST, locked: bool) -> None:
        now_locked = locked or _is_batch_lock_with(node)
        if _is_audit_write(node) and not locked:
            unlocked.append(getattr(node, "lineno", -1))
        for child in ast.iter_child_nodes(node):
            visit(child, now_locked)

    for stmt in fn.body:
        visit(stmt, False)

    assert not unlocked, (
        f"write_json_atomic on audit.json OUTSIDE batch_write_lock at "
        f"lines {unlocked} in import_bridge_result — a concurrent writer can "
        f"clobber it (#991)."
    )


def test_at_least_the_known_write_paths_are_present():
    """Guard against the AST test passing vacuously if the writes were removed."""
    fn = _import_bridge_result_fn()
    writes = [n for n in ast.walk(fn) if _is_audit_write(n)]
    assert len(writes) >= 4, (
        f"expected >=4 audit writes in import_bridge_result, found {len(writes)} "
        "— if the function was refactored, update this test"
    )


def test_locked_rmw_loses_no_update_under_contention(tmp_path):
    """Behavioural: two threads each do a locked read-modify-write adding a
    distinct key to the same audit.json. Both keys must survive."""
    ap = tmp_path / "outputs" / "SHIPMENT_991" / "audit.json"
    ap.parent.mkdir(parents=True)
    ap.write_text(json.dumps({"batch_id": "SHIPMENT_991"}), encoding="utf-8")

    barrier = threading.Barrier(2)

    def _writer(key: str):
        barrier.wait()
        for _ in range(20):
            with batch_write_lock("SHIPMENT_991"):
                a = json.loads(ap.read_text(encoding="utf-8"))
                a[key] = a.get(key, 0) + 1
                ap.write_text(json.dumps(a), encoding="utf-8")

    t1 = threading.Thread(target=_writer, args=("alpha",))
    t2 = threading.Thread(target=_writer, args=("beta",))
    t1.start(); t2.start(); t1.join(); t2.join()

    a = json.loads(ap.read_text(encoding="utf-8"))
    assert a.get("alpha") == 20, f"alpha lost updates: {a.get('alpha')}"
    assert a.get("beta") == 20, f"beta lost updates: {a.get('beta')}"
