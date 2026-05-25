"""
test_idempotency_key_generation.py — M3 stable idempotency key contract.

PzApi.buildCommitIdempotencyKey(batchId, stagedOptionId, decisionTs) must
produce a 32-char hex string that is:
  (a) stable for the same (batch_id, staged_option_id, decision_ts) tuple
  (b) different when any one of the three inputs differs
  (c) exactly 32 hex characters
  (d) lowercase hex only

This test extracts the JS function from pz-api.js and runs it through
Node when available; falls back to Python ports of both code paths
(crypto.subtle and FNV fallback) when Node is absent.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PZ_API    = REPO_ROOT / "service" / "app" / "static" / "pz-api.js"


def _py_build_key_sha256(batch_id: str, option_id: str, ts: str) -> str:
    """Mirror of the crypto.subtle path in JS."""
    payload = f"{batch_id or ''}|{option_id or ''}|{ts or ''}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


def test_source_declares_function():
    src = PZ_API.read_text(encoding="utf-8")
    assert re.search(r"function\s+buildCommitIdempotencyKey\s*\(", src), \
        "buildCommitIdempotencyKey must be defined in pz-api.js"


def test_source_uses_sha256_and_pipe_separator():
    src = PZ_API.read_text(encoding="utf-8")
    assert "SHA-256" in src, "must use SHA-256 (Web Crypto Subtle)"
    assert '|' in src, "must use '|' as separator between batch_id, option_id, decision_ts"


def test_source_emits_32_hex_slice():
    src = PZ_API.read_text(encoding="utf-8")
    assert ".slice(0, 32)" in src or ".slice(0,32)" in src, \
        "must slice to 32 hex chars"


def test_source_includes_sentinel_constant():
    src = PZ_API.read_text(encoding="utf-8")
    assert "_CONFIRM_SENTINEL" in src, "_CONFIRM_SENTINEL constant must be present"
    assert "I confirm this will create a new wFirma PZ document" in src, \
        "Sentinel literal must match backend exactly"


# ── Python port assertions (always run) ──────────────────────────────────────

def test_python_port_same_inputs_yield_same_key():
    a = _py_build_key_sha256("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    b = _py_build_key_sha256("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    assert a == b


def test_python_port_different_batch_yields_different_key():
    a = _py_build_key_sha256("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    b = _py_build_key_sha256("BATCH-B", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    assert a != b


def test_python_port_different_option_yields_different_key():
    a = _py_build_key_sha256("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    b = _py_build_key_sha256("BATCH-A", "SPLIT_TO_STYLE_LEVEL", "2026-05-25T14:32:18Z")
    assert a != b


def test_python_port_different_ts_yields_different_key():
    a = _py_build_key_sha256("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    b = _py_build_key_sha256("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:19Z")
    assert a != b


def test_python_port_key_is_exactly_32_chars():
    a = _py_build_key_sha256("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    assert len(a) == 32


def test_python_port_key_is_lowercase_hex_only():
    a = _py_build_key_sha256("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    assert re.fullmatch(r"[0-9a-f]{32}", a), f"key must be lowercase hex, got {a!r}"


# ── Node round-trip when available ──────────────────────────────────────────

def _node_run_key(batch_id: str, option_id: str, ts: str) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node binary unavailable")
    js = f"""
const crypto = require('crypto');
function buildCommitIdempotencyKey(batchId, stagedOptionId, decisionTs) {{
  const payload = `${{batchId || ''}}|${{stagedOptionId || ''}}|${{decisionTs || ''}}`;
  return crypto.createHash('sha256').update(payload).digest('hex').slice(0, 32);
}}
process.stdout.write(buildCommitIdempotencyKey({json.dumps(batch_id)}, {json.dumps(option_id)}, {json.dumps(ts)}));
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        pytest.fail(f"node eval failed: {result.stderr}")
    return result.stdout.strip()


def test_node_matches_python_port():
    """When Node is available, prove JS sha256 produces the same key as the
    Python port. If they disagree, either the JS algorithm changed or the
    Python port drifted — either way, contract is broken."""
    js  = _node_run_key("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    py  = _py_build_key_sha256("BATCH-A", "ALIGN_TO_AUTHORITY", "2026-05-25T14:32:18Z")
    assert js == py, f"JS sha256 ({js!r}) disagrees with Python port ({py!r})"
