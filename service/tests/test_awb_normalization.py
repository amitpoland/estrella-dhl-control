"""
test_awb_normalization.py — AWB normalization at intake (prevention of space-corrupted batch IDs).

Coverage
--------
_normalize_awb():
  1. Spaces stripped — "53 7881 9972" → "5378819972"
  2. Spaces stripped — "566591 6826"  → "5665916826"
  3. Spaces stripped — "97 6541 6334" → "9765416334"
  4. Clean AWB unchanged — "8722845401" → "8722845401"
  5. Leading/trailing whitespace stripped
  6. Interior hyphens between digits removed — "1234-5678" → "12345678"
  7. Hyphens not between digits preserved (non-numeric code)
  8. Empty string returns empty string

_make_batch_id():
  9.  Spaced AWB "53 7881 9972" produces batch_id containing "5378819972"
  10. Spaced AWB "566591 6826" produces batch_id containing "5665916826"
  11. Clean AWB "8722845401" produces batch_id containing "8722845401"
  12. Empty tracking_no produces batch_id containing "AUTO"

audit fields (via _write_draft_audit):
  13. audit["awb"] is normalized (no spaces)
  14. audit["raw_awb"] preserves original operator input
  15. audit["tracking_no"] preserved as entered (backward compat)
  16. No awb_missing warning for spaced-but-valid AWB
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.api.routes_upload import _normalize_awb, _make_batch_id, _write_draft_audit


# ── _normalize_awb ────────────────────────────────────────────────────────────

def test_normalize_spaced_awb_1():
    assert _normalize_awb("53 7881 9972") == "5378819972"


def test_normalize_spaced_awb_2():
    assert _normalize_awb("566591 6826") == "5665916826"


def test_normalize_spaced_awb_3():
    assert _normalize_awb("97 6541 6334") == "9765416334"


def test_normalize_clean_awb_unchanged():
    assert _normalize_awb("8722845401") == "8722845401"


def test_normalize_strips_leading_trailing_whitespace():
    assert _normalize_awb("  1234567890  ") == "1234567890"


def test_normalize_removes_intra_digit_hyphens():
    assert _normalize_awb("1234-5678") == "12345678"


def test_normalize_preserves_hyphens_not_between_digits():
    # Leading hyphen (e.g. "-ABC") — not between digits, must be left alone
    result = _normalize_awb("-ABC")
    assert "-" in result


def test_normalize_empty_returns_empty():
    assert _normalize_awb("") == ""


# ── _make_batch_id ────────────────────────────────────────────────────────────

def test_make_batch_id_spaced_awb_1():
    bid = _make_batch_id("53 7881 9972")
    assert "5378819972" in bid
    assert " " not in bid


def test_make_batch_id_spaced_awb_2():
    bid = _make_batch_id("566591 6826")
    assert "5665916826" in bid
    assert " " not in bid


def test_make_batch_id_clean_awb_unchanged():
    bid = _make_batch_id("8722845401")
    assert "8722845401" in bid


def test_make_batch_id_empty_uses_auto():
    bid = _make_batch_id("")
    assert "AUTO" in bid


# ── audit fields via _write_draft_audit ───────────────────────────────────────

def test_audit_awb_is_normalized(tmp_path):
    d = tmp_path / "outputs" / "B_NORM"
    d.mkdir(parents=True)
    _write_draft_audit(d, "BATCH_TEST", "53 7881 9972", "DHL", "", [], "", "")
    audit = json.loads((d / "audit.json").read_text())
    assert audit["awb"] == "5378819972", "awb must be normalized"
    assert " " not in audit["awb"]


def test_audit_raw_awb_preserves_original(tmp_path):
    d = tmp_path / "outputs" / "B_RAW"
    d.mkdir(parents=True)
    _write_draft_audit(d, "BATCH_TEST", "53 7881 9972", "DHL", "", [], "", "")
    audit = json.loads((d / "audit.json").read_text())
    assert audit.get("raw_awb") == "53 7881 9972", "raw_awb must preserve original input"


def test_audit_tracking_no_preserved(tmp_path):
    d = tmp_path / "outputs" / "B_TRK"
    d.mkdir(parents=True)
    _write_draft_audit(d, "BATCH_TEST", "53 7881 9972", "DHL", "", [], "", "")
    audit = json.loads((d / "audit.json").read_text())
    assert audit["tracking_no"] == "53 7881 9972", "tracking_no backward compat must be preserved"


def test_no_awb_missing_warning_for_spaced_awb(tmp_path):
    d = tmp_path / "outputs" / "B_WARN"
    d.mkdir(parents=True)
    _write_draft_audit(d, "BATCH_TEST", "53 7881 9972", "DHL", "", [], "", "")
    audit = json.loads((d / "audit.json").read_text())
    assert "awb_missing" not in (audit.get("warnings") or [])
