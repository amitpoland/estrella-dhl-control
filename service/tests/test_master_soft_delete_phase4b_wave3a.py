"""test_master_soft_delete_phase4b_wave3a.py — Phase 4B Wave 3a.

Single entity migration: carriers_config.

Mirrors the Phase 4A / Wave 1 / Wave 2 matrix:
  - soft-delete sets active=false + deleted_at; audit op=delete
  - default list excludes inactive
  - active=false list includes inactive
  - get-by-code returns inactive with active=false + deleted_at
  - restore resets active=true and deleted_at=null; audit op=restore
  - hard delete blocked when flag false (409)
  - hard delete blocked for master_editor when flag true (403)
  - hard delete allowed for master_admin when flag true (204 + audit hard_delete)
  - carrier credential isolation: no secret-like fields anywhere in the
    code or response shape.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.audit import list_audit
from app.core.config import settings


_API  = "/api/v1/carriers-config"
_HDR  = {"X-API-Key": "TESTKEY"}
_CODE = "dhl"
_BODY = {"name": "DHL Express", "api_type": "api",
         "parser_type": "dhl_emea"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", False)
    import app.api.routes_master_data as md
    md._DB_PATH = tmp_path / "master_data.sqlite"
    app = FastAPI()
    app.include_router(md.carriers_config_router)
    return TestClient(app, raise_server_exceptions=True)


def _seed(client) -> None:
    r = client.put(f"{_API}/{_CODE}", json=_BODY, headers=_HDR)
    assert r.status_code == 200, r.text


# ── Soft delete ─────────────────────────────────────────────────────────────

def test_soft_delete_sets_active_false_and_deleted_at(client):
    _seed(client)
    r = client.delete(f"{_API}/{_CODE}", headers=_HDR)
    assert r.status_code == 204, r.text
    g = client.get(f"{_API}/{_CODE}", headers=_HDR)
    assert g.status_code == 200
    body = g.json()
    assert body["active"] is False
    assert body.get("deleted_at")


def test_soft_delete_audit_op_is_delete(client):
    _seed(client)
    client.delete(f"{_API}/{_CODE}", headers=_HDR)
    rows = list_audit(entity="carriers_config", pk=_CODE)
    delete_rows = [r for r in rows if r["op"] == "delete"]
    assert len(delete_rows) == 1
    assert delete_rows[0]["before_json"]["carrier_code"] == _CODE
    assert delete_rows[0]["after_json"] is None


def test_default_list_excludes_inactive(client):
    _seed(client)
    client.delete(f"{_API}/{_CODE}", headers=_HDR)
    r = client.get(f"{_API}/", headers=_HDR)
    assert r.status_code == 200
    body = r.json()
    codes = [c["carrier_code"] for c in body["carriers"]]
    assert _CODE not in codes
    assert body["count"] == 0


def test_active_false_list_includes_inactive(client):
    _seed(client)
    client.delete(f"{_API}/{_CODE}", headers=_HDR)
    r = client.get(f"{_API}/?active=false", headers=_HDR)
    assert r.status_code == 200
    codes = [c["carrier_code"] for c in r.json()["carriers"]]
    assert _CODE in codes


def test_active_true_list_excludes_inactive(client):
    _seed(client)
    client.delete(f"{_API}/{_CODE}", headers=_HDR)
    r = client.get(f"{_API}/?active=true", headers=_HDR)
    codes = [c["carrier_code"] for c in r.json()["carriers"]]
    assert _CODE not in codes


def test_get_by_code_returns_inactive_with_deleted_at(client):
    _seed(client)
    client.delete(f"{_API}/{_CODE}", headers=_HDR)
    r = client.get(f"{_API}/{_CODE}", headers=_HDR)
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is False
    assert body["deleted_at"]


# ── Restore ─────────────────────────────────────────────────────────────────

def test_restore_sets_active_true_and_clears_deleted_at(client):
    _seed(client)
    client.delete(f"{_API}/{_CODE}", headers=_HDR)
    r = client.post(f"{_API}/{_CODE}/restore", headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is True
    assert body.get("deleted_at") in (None, "")


def test_restore_writes_audit_row_with_op_restore(client):
    _seed(client)
    client.delete(f"{_API}/{_CODE}", headers=_HDR)
    client.post(f"{_API}/{_CODE}/restore", headers=_HDR)
    rows = list_audit(entity="carriers_config", pk=_CODE)
    restore_rows = [r for r in rows if r["op"] == "restore"]
    assert len(restore_rows) == 1
    assert restore_rows[0]["before_json"]["active"] is False
    assert restore_rows[0]["after_json"]["active"] is True


def test_restore_returns_404_on_missing(client):
    r = client.post(f"{_API}/never-existed/restore", headers=_HDR)
    assert r.status_code == 404


def test_restored_record_visible_in_default_list(client):
    _seed(client)
    client.delete(f"{_API}/{_CODE}", headers=_HDR)
    client.post(f"{_API}/{_CODE}/restore", headers=_HDR)
    r = client.get(f"{_API}/", headers=_HDR)
    codes = [c["carrier_code"] for c in r.json()["carriers"]]
    assert _CODE in codes


# ── Hard delete gating ──────────────────────────────────────────────────────

def test_hard_delete_blocked_when_flag_off(client):
    _seed(client)
    r = client.delete(f"{_API}/{_CODE}?hard=true", headers=_HDR)
    assert r.status_code == 409
    assert "Hard delete is disabled" in r.text
    g = client.get(f"{_API}/{_CODE}", headers=_HDR)
    assert g.status_code == 200
    assert g.json()["active"] is True


def test_hard_delete_blocked_for_master_editor_session_when_flag_on(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_editor"}):
        r = client.delete(f"{_API}/{_CODE}?hard=true",
                          cookies={"pz_session": "fake"})
    assert r.status_code == 403
    assert "master_admin" in r.text


def test_hard_delete_allowed_for_master_admin_session_when_flag_on(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}), \
         patch("app.auth.dependencies.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}):
        r = client.delete(f"{_API}/{_CODE}?hard=true",
                          cookies={"pz_session": "fake"})
    assert r.status_code == 204, r.text
    g = client.get(f"{_API}/{_CODE}", headers=_HDR)
    assert g.status_code == 404


def test_hard_delete_audit_op_is_hard_delete(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    r = client.delete(f"{_API}/{_CODE}?hard=true", headers=_HDR)
    assert r.status_code == 204
    rows = list_audit(entity="carriers_config", pk=_CODE)
    hd = [r for r in rows if r["op"] == "hard_delete"]
    assert len(hd) == 1
    assert hd[0]["before_json"]["carrier_code"] == _CODE
    assert hd[0]["after_json"] is None


def test_hard_delete_admin_api_key_works_when_flag_on(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.delete(f"{_API}/{_CODE}?hard=true", headers=_HDR)
    assert r.status_code == 204


def test_soft_delete_404_on_missing(client):
    r = client.delete(f"{_API}/never-existed", headers=_HDR)
    assert r.status_code == 404


# ── Carrier credential isolation (regression — must NOT relax) ─────────────

_FORBIDDEN_SECRET_TOKENS = (
    "api_key", "secret", "token", "password", "credential",
    "client_secret", "access_token", "refresh_token", "bearer",
)


def test_response_body_contains_no_secret_field_names(client):
    """Phase 4B Wave 3a must not have added credential-like fields to the
    response body. The serialised carrier row must never contain any of
    the canonical secret terms."""
    _seed(client)
    r = client.get(f"{_API}/{_CODE}", headers=_HDR)
    body = r.json()
    for forbidden in _FORBIDDEN_SECRET_TOKENS:
        assert forbidden not in body, (
            f"carriers_config response must not expose '{forbidden}' "
            f"field; got body keys: {list(body.keys())}"
        )


def test_db_schema_contains_no_secret_column_names():
    """PRAGMA introspection — carriers_config table must not declare any
    secret-like column. This is the schema-level regression guard."""
    import sqlite3, tempfile
    from app.services.master_data_db import init_db
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "ms.sqlite"
        init_db(db)
        with sqlite3.connect(db) as cx:
            cols = [r[1] for r in cx.execute(
                "PRAGMA table_info(carriers_config)"
            ).fetchall()]
    for c in cols:
        lc = c.lower()
        for forbidden in _FORBIDDEN_SECRET_TOKENS:
            assert forbidden not in lc, (
                f"carriers_config table column {c!r} contains forbidden "
                f"secret-like token {forbidden!r}"
            )


def test_source_grep_no_new_secret_fields_in_dataclass():
    """Walk the CarrierConfig dataclass source — no FIELD name may
    contain a secret-like token. The docstring is explicitly allowed
    to mention "NON-SECRET" because that documents the contract; we
    strip the docstring before grepping for fields."""
    src_path = (Path(__file__).resolve().parents[1] / "app"
                / "services" / "master_data_db.py")
    src = src_path.read_text(encoding="utf-8")
    m = re.search(r"class\s+CarrierConfig.*?(?=\n@dataclass|\nclass\s)",
                  src, re.S)
    assert m, "CarrierConfig dataclass block not found"
    block = m.group(0)
    # Strip the triple-quoted docstring so its "non-secret" mention
    # doesn't false-positive the grep.
    block_no_docstring = re.sub(r'"""[\s\S]*?"""', "", block)
    # Also strip line comments after #.
    block_no_docstring = re.sub(r"#[^\n]*", "", block_no_docstring)
    for forbidden in _FORBIDDEN_SECRET_TOKENS:
        assert forbidden not in block_no_docstring.lower(), (
            f"CarrierConfig dataclass must not declare a field containing "
            f"{forbidden!r}"
        )
