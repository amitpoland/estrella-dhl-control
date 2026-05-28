"""test_master_audit_module.py — Phase 0 scaffolding tests.

Covers the standalone audit module behavior. Does NOT exercise any route
wiring (that lands in Phase 1). Pure DB + function-level assertions.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.core import audit as audit_mod
from app.core.audit import (
    AuditWriteError,
    VALID_OPS,
    _field_diff,
    init_audit_db,
    list_audit,
    write_audit,
)
from app.core.config import settings


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    """Isolated audit DB per test. Forces master_audit_enabled=True so
    every call path exercises real writes."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    path = init_audit_db()
    return path


# ── init_db ──────────────────────────────────────────────────────────────────

def test_init_audit_db_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    p1 = init_audit_db()
    p2 = init_audit_db()
    assert p1 == p2 and p1.exists()
    # Second call must not raise; schema must still be queryable.
    with sqlite3.connect(p1) as cx:
        rows = cx.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert ("master_audit",) in rows


def test_init_audit_db_creates_indices(audit_db):
    with sqlite3.connect(audit_db) as cx:
        idx = [r[0] for r in cx.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()]
    assert "ix_master_audit_entity_pk" in idx
    assert "ix_master_audit_actor"      in idx
    assert "ix_master_audit_created_at" in idx


# ── write_audit ──────────────────────────────────────────────────────────────

def test_write_audit_create_row(audit_db):
    aid = write_audit(
        entity="hs_codes", op="create", pk="7113.19.00",
        actor="apikey:admin",
        before=None,
        after={"hs_code": "7113.19.00", "active": True},
        request_id="req-1", reason="seed",
    )
    assert aid > 0
    rows = list_audit(entity="hs_codes")
    assert len(rows) == 1
    row = rows[0]
    assert row["op"] == "create"
    assert row["pk"] == "7113.19.00"
    assert row["actor"] == "apikey:admin"
    assert row["before_json"] is None
    assert row["after_json"]["hs_code"] == "7113.19.00"
    assert row["diff_json"] is None  # pure create → no diff
    assert row["request_id"] == "req-1"
    assert row["reason"] == "seed"


def test_write_audit_update_produces_diff(audit_db):
    before = {"hs_code": "7113.19.00", "active": True,  "duty_rate_pct": "2.5"}
    after  = {"hs_code": "7113.19.00", "active": False, "duty_rate_pct": "2.5"}
    write_audit(entity="hs_codes", op="update", pk="7113.19.00",
                actor="apikey:admin", before=before, after=after)
    [row] = list_audit(entity="hs_codes")
    assert row["op"] == "update"
    assert row["diff_json"] == {"active": {"before": True, "after": False}}


def test_write_audit_delete_row(audit_db):
    before = {"hs_code": "7113.19.00", "active": True}
    write_audit(entity="hs_codes", op="delete", pk="7113.19.00",
                actor="apikey:admin", before=before, after=None)
    [row] = list_audit(entity="hs_codes")
    assert row["op"] == "delete"
    assert row["before_json"] == before
    assert row["after_json"] is None
    assert row["diff_json"] is None


def test_write_audit_accepts_dataclass(audit_db):
    @dataclass
    class Foo:
        code: str
        active: bool = True
    write_audit(entity="foo", op="create", pk="x",
                actor="apikey:admin", after=Foo(code="x"))
    [row] = list_audit(entity="foo")
    assert row["after_json"] == {"code": "x", "active": True}


def test_write_audit_decimal_string_preserved(audit_db):
    """Decimal-as-string discipline must survive a JSON round-trip."""
    after = {"rate": "3.6506", "currency": "USD"}
    write_audit(entity="fx_rates", op="create", pk=1,
                actor="apikey:admin", after=after)
    [row] = list_audit(entity="fx_rates")
    assert row["after_json"]["rate"] == "3.6506"
    assert isinstance(row["after_json"]["rate"], str)


def test_write_audit_composite_pk_serialised(audit_db):
    write_audit(entity="vat_config", op="upsert",
                pk={"country": "PL", "rate": "23"},
                actor="apikey:admin", after={"x": 1})
    [row] = list_audit(entity="vat_config")
    # Stable JSON form (sorted keys).
    assert json.loads(row["pk"]) == {"country": "PL", "rate": "23"}


def test_write_audit_disabled_returns_minus_one(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "master_audit_enabled", False)
    rv = write_audit(entity="hs_codes", op="create", pk="x",
                     actor="apikey:admin", after={"x": 1})
    assert rv == -1
    # No DB file required when disabled.
    assert not (tmp_path / "master_audit.sqlite").exists()


@pytest.mark.parametrize("kwargs,err", [
    ({"entity": "",         "op": "create", "pk": "x", "actor": "a"}, "entity"),
    ({"entity": "x", "op": "frobnicate",  "pk": "x", "actor": "a"}, "op"),
    ({"entity": "x", "op": "create", "pk": "",        "actor": "a"}, "pk"),
    ({"entity": "x", "op": "create", "pk": None,      "actor": "a"}, "pk"),
    ({"entity": "x", "op": "create", "pk": "x",       "actor": ""}, "actor"),
])
def test_write_audit_validation(audit_db, kwargs, err):
    with pytest.raises(AuditWriteError) as exc:
        write_audit(**kwargs, after={"y": 1})
    assert err in str(exc.value)


def test_valid_ops_locked():
    """Lock the op vocabulary so a typo elsewhere is caught by this test."""
    assert VALID_OPS == frozenset({
        "create", "update", "upsert",
        "delete", "soft_delete", "restore", "hard_delete",
        "transition",
    })


# ── _field_diff direct ──────────────────────────────────────────────────────

def test_field_diff_skips_housekeeping():
    a = {"x": 1, "updated_at": "t0", "created_at": "t0"}
    b = {"x": 1, "updated_at": "t1", "created_at": "t0"}
    assert _field_diff(a, b) is None


def test_field_diff_detects_change():
    diff = _field_diff({"x": 1, "y": 2}, {"x": 1, "y": 3})
    assert diff == {"y": {"before": 2, "after": 3}}


def test_field_diff_none_on_create_or_delete():
    assert _field_diff(None, {"x": 1}) is None
    assert _field_diff({"x": 1}, None) is None


# ── list_audit ──────────────────────────────────────────────────────────────

def test_list_audit_filters_and_pagination(audit_db):
    for i in range(5):
        write_audit(entity="hs_codes", op="create", pk=f"code-{i}",
                    actor="alice", after={"code": f"code-{i}"})
    for i in range(3):
        write_audit(entity="units", op="create", pk=f"u-{i}",
                    actor="bob", after={"code": f"u-{i}"})

    assert len(list_audit()) == 8
    assert len(list_audit(entity="hs_codes")) == 5
    assert len(list_audit(actor="bob")) == 3
    assert len(list_audit(op="create")) == 8

    page1 = list_audit(limit=3, offset=0)
    page2 = list_audit(limit=3, offset=3)
    assert len(page1) == 3 and len(page2) == 3
    # Disjoint ids; newest first.
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})
    assert page1[0]["id"] > page1[-1]["id"]


def test_list_audit_filter_pk(audit_db):
    write_audit(entity="hs_codes", op="create", pk="A",
                actor="x", after={"k": "A"})
    write_audit(entity="hs_codes", op="create", pk="B",
                actor="x", after={"k": "B"})
    rows = list_audit(entity="hs_codes", pk="A")
    assert len(rows) == 1 and rows[0]["pk"] == "A"


def test_list_audit_limit_clamped(audit_db):
    rv = list_audit(limit=10_000)
    # Should not raise; clamp is internal.
    assert isinstance(rv, list)


# ── Retention constant (documented, not enforced) ───────────────────────────

def test_retention_default_is_seven_years():
    # 7 calendar years + 2 leap days, per operator instruction 2026-05-28.
    assert settings.master_audit_retention_days == 2557
