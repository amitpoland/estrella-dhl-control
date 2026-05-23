"""
test_ai_call_ledger.py — Unit tests for ai_call_ledger.py.

Uses a temp directory for the SQLite DB to avoid touching real storage.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

import pytest


def _make_entry(**kwargs):
    base = {
        "timestamp":               time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "service":                 "test_service",
        "object_id":               "batch_001",
        "task_type":               "customs_extraction",
        "requested_model":         None,
        "selected_model":          "claude-sonnet-4-6",
        "model_tier":              "sonnet",
        "selection_reason":        "moderate_default",
        "escalation_reason":       None,
        "confidence_score":        1.0,
        "prompt_hash":             "abc123",
        "estimated_input_tokens":  400,
        "estimated_output_tokens": 200,
        "estimated_cost":          0.0042,
        "actual_input_tokens":     None,
        "actual_output_tokens":    None,
        "actual_cost":             None,
        "latency_ms":              1200,
        "success":                 True,
        "fallback_reason":         None,
        "error_type":              None,
    }
    base.update(kwargs)
    return base


# ── record() ─────────────────────────────────────────────────────────────────

def test_record_creates_row(tmp_path):
    from app.services import ai_call_ledger as ledger

    db_path = tmp_path / "ai_call_ledger.db"
    with patch.object(ledger, "_db_path", return_value=db_path):
        ledger.record(_make_entry())

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()
    conn.close()
    assert rows[0] == 1


def test_record_stores_correct_fields(tmp_path):
    from app.services import ai_call_ledger as ledger

    db_path = tmp_path / "ai_call_ledger.db"
    entry = _make_entry(
        service="ai_customs_parser",
        selected_model="claude-opus-4-7",
        model_tier="opus",
        escalation_reason="complexity=complex, risk=high",
        success=True,
        latency_ms=3000,
    )
    with patch.object(ledger, "_db_path", return_value=db_path):
        ledger.record(entry)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT service, selected_model, model_tier, escalation_reason, latency_ms, success FROM ai_calls").fetchone()
    conn.close()
    assert row[0] == "ai_customs_parser"
    assert row[1] == "claude-opus-4-7"
    assert row[2] == "opus"
    assert row[3] == "complexity=complex, risk=high"
    assert row[4] == 3000
    assert row[5] == 1


def test_record_failure_row(tmp_path):
    from app.services import ai_call_ledger as ledger

    db_path = tmp_path / "ai_call_ledger.db"
    entry = _make_entry(success=False, error_type="APIStatusError")
    with patch.object(ledger, "_db_path", return_value=db_path):
        ledger.record(entry)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT success, error_type FROM ai_calls").fetchone()
    conn.close()
    assert row[0] == 0
    assert row[1] == "APIStatusError"


def test_record_never_raises(tmp_path):
    """record() must not raise even with an invalid path."""
    from app.services import ai_call_ledger as ledger

    bad_path = tmp_path / "no_such_dir" / "sub" / "ledger.db"
    # Should create parent dirs and not raise
    with patch.object(ledger, "_db_path", return_value=bad_path):
        ledger.record(_make_entry())  # no exception


# ── get_daily_cost_usd() ──────────────────────────────────────────────────────

def test_daily_cost_empty_db(tmp_path):
    from app.services import ai_call_ledger as ledger

    db_path = tmp_path / "ai_call_ledger.db"
    with patch.object(ledger, "_db_path", return_value=db_path):
        cost = ledger.get_daily_cost_usd("2026-05-23")
    assert cost == 0.0


def test_daily_cost_missing_db(tmp_path):
    from app.services import ai_call_ledger as ledger

    db_path = tmp_path / "nonexistent.db"
    with patch.object(ledger, "_db_path", return_value=db_path):
        cost = ledger.get_daily_cost_usd("2026-05-23")
    assert cost == 0.0


def test_daily_cost_uses_actual_when_present(tmp_path):
    from app.services import ai_call_ledger as ledger

    db_path = tmp_path / "ai_call_ledger.db"
    entry = _make_entry(
        timestamp="2026-05-23T10:00:00Z",
        actual_cost=0.05,
        estimated_cost=0.03,
        success=True,
    )
    with patch.object(ledger, "_db_path", return_value=db_path):
        ledger.record(entry)
        cost = ledger.get_daily_cost_usd("2026-05-23")
    # actual_cost takes precedence via COALESCE
    assert abs(cost - 0.05) < 0.0001


def test_daily_cost_falls_back_to_estimated(tmp_path):
    from app.services import ai_call_ledger as ledger

    db_path = tmp_path / "ai_call_ledger.db"
    entry = _make_entry(
        timestamp="2026-05-23T10:00:00Z",
        actual_cost=None,
        estimated_cost=0.02,
        success=True,
    )
    with patch.object(ledger, "_db_path", return_value=db_path):
        ledger.record(entry)
        cost = ledger.get_daily_cost_usd("2026-05-23")
    assert abs(cost - 0.02) < 0.0001


def test_daily_cost_excludes_failures(tmp_path):
    from app.services import ai_call_ledger as ledger

    db_path = tmp_path / "ai_call_ledger.db"
    with patch.object(ledger, "_db_path", return_value=db_path):
        ledger.record(_make_entry(timestamp="2026-05-23T10:00:00Z", actual_cost=0.10, success=True))
        ledger.record(_make_entry(timestamp="2026-05-23T11:00:00Z", actual_cost=0.50, success=False))
        cost = ledger.get_daily_cost_usd("2026-05-23")
    # Only success=True row counted
    assert abs(cost - 0.10) < 0.0001


def test_daily_cost_excludes_other_dates(tmp_path):
    from app.services import ai_call_ledger as ledger

    db_path = tmp_path / "ai_call_ledger.db"
    with patch.object(ledger, "_db_path", return_value=db_path):
        ledger.record(_make_entry(timestamp="2026-05-22T23:00:00Z", actual_cost=1.00, success=True))
        ledger.record(_make_entry(timestamp="2026-05-23T01:00:00Z", actual_cost=0.03, success=True))
        cost = ledger.get_daily_cost_usd("2026-05-23")
    assert abs(cost - 0.03) < 0.0001


# ── prompt_hash() ─────────────────────────────────────────────────────────────

def test_prompt_hash_deterministic():
    from app.services.ai_call_ledger import prompt_hash
    h1 = prompt_hash("system text", "user text")
    h2 = prompt_hash("system text", "user text")
    assert h1 == h2


def test_prompt_hash_different_inputs_differ():
    from app.services.ai_call_ledger import prompt_hash
    h1 = prompt_hash("system A", "user A")
    h2 = prompt_hash("system B", "user B")
    assert h1 != h2


def test_prompt_hash_is_hex_string():
    from app.services.ai_call_ledger import prompt_hash
    h = prompt_hash("s", "u")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ── estimate_tokens() / estimate_cost() ──────────────────────────────────────

def test_estimate_tokens_rough():
    from app.services.ai_call_ledger import estimate_tokens
    # 4 chars per token heuristic
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


def test_estimate_cost_sonnet():
    from app.services.ai_call_ledger import estimate_cost
    cost = estimate_cost("claude-sonnet-4-6", 1000, 500)
    # 1k in * 0.003 + 0.5k out * 0.015 = 0.003 + 0.0075 = 0.0105
    assert abs(cost - 0.0105) < 0.0001


def test_estimate_cost_haiku_cheaper_than_sonnet():
    from app.services.ai_call_ledger import estimate_cost
    haiku  = estimate_cost("claude-haiku-4-5-20251001", 1000, 500)
    sonnet = estimate_cost("claude-sonnet-4-6",          1000, 500)
    opus   = estimate_cost("claude-opus-4-7",            1000, 500)
    assert haiku < sonnet < opus
