"""
test_dhl_shadow_db.py — DL-F2 shadow-log SQLite store tests.

Required:
  1. init_db creates the carrier_shadow_log table and indexes.
  2. record_call_outcome stores one row.
  3. compute_request_hash is deterministic.
  4. compute_request_hash differs across methods.
  5. list_recent ordered newest first.
  6. summarise_last_n_days groups by (method, diff_outcome).
  7. Source-grep guards (no FastAPI / coordinator / adapter / HTTP).
  8. truncate_summary caps at 200 chars.
  9. Diff outcome outside the allowlist falls back to "unknown".
  10. record_call_outcome rejects empty method or empty request_hash.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from app.services.carrier.adapters import dhl_shadow_db as dsdb


_DB_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "adapters" / "dhl_shadow_db.py"
)


@pytest.fixture(scope="module")
def src() -> str:
    return _DB_FILE.read_text(encoding="utf-8")


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "carrier_shadow.db"
    dsdb.init_db(p)
    return p


# ── 1. init creates the table and indexes ─────────────────────────────────

def test_init_creates_table(db):
    con = sqlite3.connect(str(db))
    rows = con.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='carrier_shadow_log'"
    ).fetchall()
    con.close()
    assert [r[0] for r in rows] == ["carrier_shadow_log"]


def test_init_creates_indexes(db):
    con = sqlite3.connect(str(db))
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name LIKE 'idx_csl_%'"
    ).fetchall()
    con.close()
    names = sorted(r[0] for r in rows)
    assert "idx_csl_method"     in names
    assert "idx_csl_diff"       in names
    assert "idx_csl_created_at" in names


def test_init_creates_all_documented_columns(db):
    con = sqlite3.connect(str(db))
    cols = [r[1] for r in con.execute(
        "PRAGMA table_info(carrier_shadow_log)"
    ).fetchall()]
    con.close()
    expected = {
        "id", "method", "request_hash", "actor",
        "stub_status", "stub_awb", "stub_label_format",
        "stub_label_size", "stub_error_class", "stub_error_summary",
        "live_status", "live_awb", "live_label_format",
        "live_label_size", "live_http_status",
        "live_error_class", "live_error_summary",
        "live_duration_ms", "diff_outcome", "diff_notes",
        "created_at",
        # DL-F3 — Paperless Trade metadata columns added via
        # idempotent ALTER TABLE in init_db.
        "live_paperless_trade_attached",
        "live_paperless_trade_size",
        "live_paperless_trade_sha256",
    }
    assert set(cols) == expected


# ── 2. record_call_outcome stores one row ────────────────────────────────

def test_record_call_outcome_stores_row(db):
    rid = dsdb.record_call_outcome(
        method="create_shipment",
        request_hash="abc",
        actor="op-1",
        stub_status="ok", stub_awb="DHLSTUB1", stub_label_format="pdf",
        stub_label_size=123,
        live_status="ok", live_awb="LIVE9", live_label_format="pdf",
        live_label_size=456, live_duration_ms=42,
        diff_outcome="match",
    )
    assert rid
    row = dsdb.get_row(rid)
    assert row is not None
    assert row["method"] == "create_shipment"
    assert row["actor"] == "op-1"
    assert row["stub_awb"] == "DHLSTUB1"
    assert row["live_awb"] == "LIVE9"
    assert row["diff_outcome"] == "match"
    assert row["stub_label_size"] == 123
    assert row["live_label_size"] == 456
    assert row["live_duration_ms"] == 42
    assert row["created_at"]


# ── 3. compute_request_hash is deterministic ──────────────────────────────

def test_compute_request_hash_is_deterministic():
    a = dsdb.compute_request_hash("create_shipment", "B-1", "R", 1, "x", "P")
    b = dsdb.compute_request_hash("create_shipment", "B-1", "R", 1, "x", "P")
    assert a == b
    # 64 hex chars
    assert re.fullmatch(r"[0-9a-f]{64}", a)


def test_compute_request_hash_changes_with_inputs():
    a = dsdb.compute_request_hash("create_shipment", "B-1")
    b = dsdb.compute_request_hash("create_shipment", "B-2")
    assert a != b


# ── 4. compute_request_hash differs across methods ───────────────────────

def test_compute_request_hash_differs_across_methods():
    a = dsdb.compute_request_hash("create_shipment", "X", "Y")
    b = dsdb.compute_request_hash("cancel_shipment", "X", "Y")
    c = dsdb.compute_request_hash("fetch_label", "X", "Y")
    d = dsdb.compute_request_hash("schedule_pickup", "X", "Y")
    assert len({a, b, c, d}) == 4


def test_compute_request_hash_method_case_insensitive():
    a = dsdb.compute_request_hash("CREATE_SHIPMENT", "X")
    b = dsdb.compute_request_hash("create_shipment", "X")
    assert a == b


# ── 5. list_recent ordered newest first ──────────────────────────────────

def test_list_recent_newest_first(db):
    ids = []
    for awb in ["A1", "A2", "A3"]:
        ids.append(dsdb.record_call_outcome(
            method="create_shipment", request_hash="h-" + awb,
            stub_awb=awb, diff_outcome="match",
        ))
    rows = dsdb.list_recent()
    # The last inserted is first in the list
    awbs = [r["stub_awb"] for r in rows]
    assert awbs[0] == "A3"
    assert awbs[-1] == "A1"


def test_list_recent_filter_by_method(db):
    dsdb.record_call_outcome(
        method="create_shipment", request_hash="c1", diff_outcome="match",
    )
    dsdb.record_call_outcome(
        method="cancel_shipment", request_hash="c2", diff_outcome="match",
    )
    only_create = dsdb.list_recent(method="create_shipment")
    only_cancel = dsdb.list_recent(method="cancel_shipment")
    assert all(r["method"] == "create_shipment" for r in only_create)
    assert all(r["method"] == "cancel_shipment" for r in only_cancel)


def test_list_recent_filter_by_diff_outcome(db):
    dsdb.record_call_outcome(
        method="create_shipment", request_hash="d1", diff_outcome="match",
    )
    dsdb.record_call_outcome(
        method="create_shipment", request_hash="d2",
        diff_outcome="live_only_error",
    )
    matched = dsdb.list_recent(diff_outcome="match")
    live_err = dsdb.list_recent(diff_outcome="live_only_error")
    assert all(r["diff_outcome"] == "match" for r in matched)
    assert all(r["diff_outcome"] == "live_only_error" for r in live_err)


def test_list_recent_respects_limit(db):
    for i in range(15):
        dsdb.record_call_outcome(
            method="create_shipment", request_hash=f"L-{i}",
            diff_outcome="match",
        )
    rows = dsdb.list_recent(limit=5)
    assert len(rows) == 5


# ── 6. summarise_last_n_days groups by (method, diff_outcome) ────────────

def test_summarise_groups_correctly(db):
    for i in range(3):
        dsdb.record_call_outcome(
            method="create_shipment", request_hash=f"c-{i}",
            diff_outcome="match",
        )
    for i in range(2):
        dsdb.record_call_outcome(
            method="create_shipment", request_hash=f"e-{i}",
            diff_outcome="live_only_error",
        )
    dsdb.record_call_outcome(
        method="cancel_shipment", request_hash="x",
        diff_outcome="match",
    )

    summary = dsdb.summarise_last_n_days(7)
    by_key = {(s["method"], s["diff_outcome"]): s["count"] for s in summary}
    assert by_key[("create_shipment", "match")] == 3
    assert by_key[("create_shipment", "live_only_error")] == 2
    assert by_key[("cancel_shipment", "match")] == 1


# ── 7. Source-grep guards ────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "import fastapi", "from fastapi",
    "import flask",   "from flask",
])
def test_source_no_web_framework(src, forbidden):
    assert forbidden not in src


@pytest.mark.parametrize("forbidden", [
    "carrier_coordinator", "CarrierCoordinator",
    "from .carrier_coordinator", "from . import carrier_coordinator",
])
def test_source_no_coordinator_import(src, forbidden):
    assert forbidden not in src


@pytest.mark.parametrize("forbidden", [
    "DHLExpressLiveAdapter", "DHLExpressStubAdapter",
    "DHLExpressShadowAdapter",
])
def test_source_no_concrete_adapter_class(src, forbidden):
    assert forbidden not in src, (
        f"dhl_shadow_db.py contains {forbidden!r} — the store is "
        f"adapter-agnostic; data flows in via record_call_outcome."
    )


@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_source_no_http(src, forbidden):
    assert forbidden not in src


def test_source_no_env_reads(src):
    for forbidden in ["os.environ", "os.getenv", "getenv("]:
        assert forbidden not in src


# ── 8. truncate_summary caps at 200 chars ────────────────────────────────

def test_truncate_summary_caps_at_200():
    long = "x" * 500
    out = dsdb.truncate_summary(long)
    assert len(out) == 200
    assert out.endswith("...")


def test_truncate_summary_passes_short_strings():
    out = dsdb.truncate_summary("short")
    assert out == "short"


def test_truncate_summary_handles_none():
    assert dsdb.truncate_summary("") == ""
    assert dsdb.truncate_summary(None) == ""


def test_record_call_outcome_truncates_long_summaries(db):
    long = "y" * 500
    rid = dsdb.record_call_outcome(
        method="create_shipment", request_hash="trunc",
        stub_status="error", stub_error_summary=long,
        live_status="error", live_error_summary=long,
        diff_notes=long,
    )
    row = dsdb.get_row(rid)
    assert len(row["stub_error_summary"]) == 200
    assert len(row["live_error_summary"]) == 200
    assert len(row["diff_notes"]) == 200


# ── 9. Diff outcome outside allowlist → "unknown" ─────────────────────────

def test_diff_outcome_outside_allowlist_falls_back_to_unknown(db):
    rid = dsdb.record_call_outcome(
        method="create_shipment", request_hash="weird",
        diff_outcome="totally-made-up",
    )
    row = dsdb.get_row(rid)
    assert row["diff_outcome"] == "unknown"


@pytest.mark.parametrize("outcome", [
    "match", "live_only_error", "stub_only_error",
    "both_error", "shape_diff", "unknown",
])
def test_all_documented_outcomes_persist_verbatim(db, outcome):
    rid = dsdb.record_call_outcome(
        method="create_shipment", request_hash=f"d-{outcome}",
        diff_outcome=outcome,
    )
    row = dsdb.get_row(rid)
    assert row["diff_outcome"] == outcome


# ── 10. Validation ────────────────────────────────────────────────────────

def test_record_rejects_empty_method(db):
    with pytest.raises(ValueError):
        dsdb.record_call_outcome(method="", request_hash="h")


def test_record_rejects_empty_request_hash(db):
    with pytest.raises(ValueError):
        dsdb.record_call_outcome(method="create_shipment", request_hash="")


def test_count_total_returns_count(db):
    assert dsdb.count_total() == 0
    dsdb.record_call_outcome(
        method="create_shipment", request_hash="c1", diff_outcome="match",
    )
    assert dsdb.count_total() == 1


def test_init_required_before_writes(monkeypatch):
    monkeypatch.setattr(dsdb, "_db_path", None, raising=False)
    with pytest.raises(RuntimeError):
        dsdb.record_call_outcome(method="create_shipment", request_hash="x")
