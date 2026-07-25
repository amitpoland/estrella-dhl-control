"""#992: best-effort blocks in import_bridge_result must LOG when they swallow.

Several best-effort blocks used `except Exception: pass`. After #991 wrapped
them in batch_write_lock, a lock TimeoutError (30s contention) lands in those
handlers and was silently discarded — e.g. tracking_complete just would not be
written, with no log line (the same shape that hid an UnboundLocalError until
#973). Best-effort is fine; silent is not.

Guards:
  1. Structural (AST): no except handler in import_bridge_result is a bare
     `pass`, and none re-raises (best-effort preserved).
  2. Behavioural: a forced lock TimeoutError is logged at WARNING and does NOT
     fail the request.
"""
from __future__ import annotations

import ast
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_ai_bridge as rd  # noqa: E402

_ROUTES = _SVC / "app" / "api" / "routes_ai_bridge.py"


# ── storage isolation (mirrors test_ai_bridge) ────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(rd, "_OUTPUTS", tmp_path / "outputs")


def _make_batch(root: Path, extra: Dict[str, Any] | None = None):
    bid = str(uuid.uuid4())[:8]
    d = root / "outputs" / bid
    d.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": bid, "awb": "1234567890", "tracking_no": "1234567890",
             "status": "processing", "carrier": "DHL", "timeline": []}
    if extra:
        audit.update(extra)
    ap = d / "audit.json"
    ap.write_text(json.dumps(audit), encoding="utf-8")
    return bid, ap


# ── structural pin ────────────────────────────────────────────────────────────

def _fn() -> ast.FunctionDef:
    for n in ast.walk(ast.parse(_ROUTES.read_text(encoding="utf-8"))):
        if isinstance(n, ast.FunctionDef) and n.name == "import_bridge_result":
            return n
    raise AssertionError("import_bridge_result not found")


def _best_effort_handlers(fn: ast.FunctionDef) -> list[ast.ExceptHandler]:
    """The broad `except Exception` catch-all handlers — the best-effort swallow
    sites. Deliberately excludes typed handlers like `except ValueError: raise
    HTTPException(422)`, which are intentional error propagation, not swallows.
    """
    out = []
    for h in [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]:
        t = h.type
        if isinstance(t, ast.Name) and t.id == "Exception":
            out.append(h)
    return out


def test_no_best_effort_handler_is_silent_or_reraises():
    handlers = _best_effort_handlers(_fn())
    assert handlers, "no `except Exception` handlers found — test would be vacuous"
    silent = [h.lineno for h in handlers
              if len(h.body) == 1 and isinstance(h.body[0], ast.Pass)]
    reraises = [h.lineno for h in handlers
                if any(isinstance(x, ast.Raise) and x.exc is not None for x in ast.walk(h))]
    assert not silent, (
        f"best-effort handler(s) at {silent} are a bare `pass` — a swallowed "
        f"failure (incl. a batch_write_lock timeout) is invisible (#992)."
    )
    assert not reraises, (
        f"best-effort handler(s) at {reraises} re-raise; these paths must stay "
        f"best-effort (log, do not fail the request)"
    )


def test_every_best_effort_handler_logs():
    for h in _best_effort_handlers(_fn()):
        has_log = any(
            isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
            and isinstance(x.func.value, ast.Name) and x.func.value.id == "log"
            for x in ast.walk(h)
        )
        assert has_log, (
            f"`except Exception` handler at line {h.lineno} does not call log.* "
            f"— swallowed failures must be observable (#992)"
        )


# ── behavioural ───────────────────────────────────────────────────────────────

def test_lock_timeout_is_logged_and_does_not_fail_the_request(tmp_path, monkeypatch, caplog):
    bid, ap = _make_batch(tmp_path, extra={
        "tracking": {"cowork_tracking_required": True, "cowork_result_received": False},
    })
    task_id = rd.create_bridge_task(bid, rd.CreateTaskBody(task_type="tracking_lookup"))["task_id"]

    # Force the tracking block's `with batch_write_lock(...)` to raise, as a real
    # 30s contention timeout would.
    def _timeout(*_a, **_k):
        raise TimeoutError("Could not acquire batch lock (test)")
    monkeypatch.setattr(rd, "batch_write_lock", _timeout)

    body = rd.ImportResultBody(
        task_id=task_id,
        result_data={"tracking": {"status": "customs", "last_event": "At customs"}},
        source="claude_cowork",
    )
    with caplog.at_level(logging.WARNING):
        result = rd.import_bridge_result(task_id, body)

    # best-effort: the import itself still succeeded, the request did not fail
    assert result.get("ok") is True

    # observable: a warning names the skipped tracking patch (not silent)
    msgs = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert "tracking patch skipped" in msgs, (
        f"lock timeout was swallowed with no WARNING log (#992). captured: {msgs!r}"
    )
