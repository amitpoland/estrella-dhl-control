"""test_proforma_draft_customer_surface.py — proforma draft UI usability.

Verifies the additive ``customer_resolution`` block on
``GET /api/v1/proforma/draft/{draft_id}``.  Read-only; no schema
change; no external HTTP / wFirma client calls.
"""
from __future__ import annotations

import sqlite3 as _s
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb
    from app.services import proforma_service_charges_db as scdb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    scdb.init(tmp_path / "proforma_links.db")
    return tmp_path


@pytest.fixture()
def client(fresh):
    tmp = fresh
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "t", "email": "t@local",
    }
    yield TestClient(app), tmp
    app.dependency_overrides.clear()


def _seed_draft(tmp: Path, *, batch_id: str, client_name: str) -> int:
    from app.services import proforma_invoice_link_db as pildb
    db = tmp / "proforma_links.db"
    pildb.init_db(db)
    with _s.connect(str(db)) as conn:
        pildb._ensure_drafts_table(conn)
        now = pildb._now_utc_iso()
        cur = conn.execute(
            "INSERT INTO proforma_drafts (batch_id, client_name, status, "
            "currency, draft_state, draft_version, source_lines_json, "
            "editable_lines_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (batch_id, client_name, "draft", "USD", "editing", 1,
             "[]", '[{"product_code":"X","qty":1}]', now, now),
        )
        return int(cur.lastrowid)


def _seed_wfirma_customer(tmp: Path, *, name: str,
                            wfirma_id: str = "wfid-1") -> None:
    from app.services import wfirma_db as wfdb
    wfdb.upsert_customer(
        client_name=name, wfirma_customer_id=wfirma_id,
        vat_id="PL1234567890", country="PL", match_status="matched",
    )


# ── 1. matched customer surfaces wfirma_customer_id ───────────────────────

def test_draft_get_includes_customer_resolution_when_matched(client):
    cli, tmp = client
    _seed_wfirma_customer(tmp, name="ACME Corp", wfirma_id="wfid-99")
    draft_id = _seed_draft(tmp, batch_id="B-1", client_name="ACME Corp")

    r = cli.get(f"/api/v1/proforma/draft/{draft_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    draft = body["draft"]
    assert "customer_resolution" in draft, (
        "GET /draft/{id} response missing customer_resolution"
    )
    res = draft["customer_resolution"]
    assert res["wfirma_customer_id"] == "wfid-99"
    assert res["found"] is True
    assert res["match_strategy"] in ("exact", "prefix", "reverse_prefix")


# ── 2. unmatched customer returns safe shape (no 500) ─────────────────────

def test_draft_get_returns_safe_unmatched_when_no_wfirma_customer(client):
    cli, tmp = client
    # No wfirma_customers row seeded for this client_name.
    draft_id = _seed_draft(tmp, batch_id="B-2",
                            client_name="Nonexistent Client Co.")

    r = cli.get(f"/api/v1/proforma/draft/{draft_id}")
    assert r.status_code == 200, r.text
    res = r.json()["draft"]["customer_resolution"]
    assert res["wfirma_customer_id"] == ""
    assert res["found"] is False
    # Match strategy may be "none" or "ambiguous"; never raise.
    assert res["match_strategy"] in ("none", "ambiguous")
    # Either candidates absent or an empty list — both are safe.
    cands = res.get("candidates", [])
    assert isinstance(cands, list)


# ── 3. resolver exception → defensive empty block, never 500 ──────────────

def test_draft_get_never_500s_when_resolver_raises(client, monkeypatch):
    cli, tmp = client
    draft_id = _seed_draft(tmp, batch_id="B-3", client_name="ACME")

    from app.api import routes_proforma as rp

    def _boom(name):
        raise RuntimeError("simulated resolver failure")

    monkeypatch.setattr(rp, "_resolve_customer", _boom)
    r = cli.get(f"/api/v1/proforma/draft/{draft_id}")
    assert r.status_code == 200, r.text
    res = r.json()["draft"]["customer_resolution"]
    # Defensive shape — never raises, always emits a usable dict.
    assert res["wfirma_customer_id"] == ""
    assert res["found"] is False
    assert res["match_strategy"] == "none"


# ── 4. GET remains read-only across multiple invocations ─────────────────

def test_draft_get_remains_read_only(client):
    cli, tmp = client
    _seed_wfirma_customer(tmp, name="ReadOnly Client",
                            wfirma_id="wfid-42")
    draft_id = _seed_draft(tmp, batch_id="B-4",
                            client_name="ReadOnly Client")

    def _snap():
        out = {}
        for fname, tables in (
            ("proforma_links.db", ["proforma_drafts"]),
            ("wfirma.db",         ["wfirma_customers"]),
        ):
            p = tmp / fname
            if not p.exists():
                continue
            with _s.connect(str(p)) as c:
                for t in tables:
                    try:
                        out[t] = c.execute(
                            f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    except Exception:
                        pass
        return out

    before = _snap()
    for _ in range(3):
        cli.get(f"/api/v1/proforma/draft/{draft_id}")
    after = _snap()
    assert before == after, f"row counts changed: {before} → {after}"


# ── 5. Source-grep: customer_resolution path has no external calls ───────

def test_draft_get_customer_resolution_no_external_calls():
    """The new GET path must NOT introduce HTTP/wFirma client / SMTP /
    DHL surfaces.  _resolve_customer already reads only the local
    wfirma_customers mirror — verify here that the GET handler stays
    local-DB only."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_proforma.py").read_text(encoding="utf-8")
    # Find the get_proforma_draft body slice.
    start = src.index("def get_proforma_draft(")
    # Look for the next @router decorator to bound the slice.
    end = src.index("@router.", start + 50)
    body = src[start:end]
    for forbidden in ("requests.", "httpx.", "wfirma_client",
                      "smtp", "send_email", "dhl_dispatch"):
        assert forbidden not in body, (
            f"get_proforma_draft must not reference {forbidden!r}"
        )
