"""test_proforma_visibility_endpoint.py — Phase 5.5A/6 endpoint tests.

Coverage:
  - GET /draft/{draft_id}/visibility → 200 with expected keys
  - GET /draft/{draft_id}/visibility → 404 for unknown draft
  - GET /draft/{draft_id}/intelligence → 200 with expected keys
  - GET /draft/{draft_id}/intelligence → 404 for unknown draft
  - visibility.readiness.commercial_state present and non-empty
  - visibility.shipment_panel.awb defaults to None when no audit
  - visibility.company_completeness.present key exists
  - intelligence.confidence.overall in 0.0–1.0
  - intelligence.anomalies is a list
  - intelligence.suggestions is a list (language policy: no name_sk)
  - visibility route is read-only (no DB mutations on call)
  - intelligence route is read-only (no DB mutations on call)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb


_API_KEY = "test-key"
_HEADERS = {"X-API-Key": _API_KEY}


@pytest.fixture(autouse=True)
def _patch_api_key(monkeypatch):
    monkeypatch.setattr(settings, "api_key", _API_KEY)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    # Ensure the DB is initialised
    pildb.init_db(tmp_path / "proforma_links.db")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _create_draft(tmp_path: Path, batch_id: str = "B001",
                  client_name: str = "ClientA",
                  lines: list | None = None) -> int:
    """Insert a minimal proforma_draft row; return its integer id."""
    if lines is None:
        lines = [
            {"line_id": "L1", "product_code": "P001",
             "unit_price": 100.0, "hs_code": "7113191000",
             "name_pl": "Pierścień", "name_en": "Ring",
             "qty": 1, "currency": "EUR"},
        ]
    db = tmp_path / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        now = "2026-01-01T00:00:00"
        cur = conn.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, draft_state, draft_version, "
            " editable_lines_json, created_at, updated_at) "
            "VALUES (?, ?, 'pending_local', 'draft', 1, ?, ?, ?)",
            (batch_id, client_name, json.dumps(lines), now, now),
        )
        conn.commit()
        return cur.lastrowid


# ── /visibility ───────────────────────────────────────────────────────────────

def test_visibility_200_basic(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/visibility", headers=_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["draft_id"] == draft_id


def test_visibility_has_required_keys(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/visibility", headers=_HEADERS)
    body = r.json()
    for key in ("shipment_panel", "company_completeness", "readiness",
                "document_status", "product_lines_panel"):
        assert key in body, f"Missing key: {key}"


def test_visibility_readiness_commercial_state(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/visibility", headers=_HEADERS)
    body = r.json()
    cs = body["readiness"]["commercial_state"]
    assert isinstance(cs, str)
    assert cs  # non-empty


def test_visibility_shipment_panel_awb_none_when_no_audit(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/visibility", headers=_HEADERS)
    body = r.json()
    assert body["shipment_panel"]["awb"] is None


def test_visibility_company_completeness_keys(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/visibility", headers=_HEADERS)
    body = r.json()
    cc = body["company_completeness"]
    assert "present" in cc
    assert "score" in cc
    assert "missing_mandatory" in cc
    assert "missing_recommended" in cc


def test_visibility_document_status_keys(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/visibility", headers=_HEADERS)
    body = r.json()
    ds = body["document_status"]
    assert "has_local_preview" in ds
    assert "wfirma_issued" in ds
    assert ds["has_local_preview"] is True


def test_visibility_product_lines_panel_is_list(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/visibility", headers=_HEADERS)
    body = r.json()
    assert isinstance(body["product_lines_panel"], list)


def test_visibility_product_lines_panel_no_name_sk(client, tmp_path):
    """Language policy: name_sk must never appear in product_lines_panel."""
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/visibility", headers=_HEADERS)
    body = r.json()
    for row in body["product_lines_panel"]:
        assert "name_sk" not in row, "name_sk must never appear in product_lines_panel"


def test_visibility_404_unknown_draft(client, tmp_path):
    r = client.get("/api/v1/proforma/draft/9999999/visibility", headers=_HEADERS)
    assert r.status_code == 404


def test_visibility_no_mutations(client, tmp_path, monkeypatch):
    """Calling visibility must not mutate the draft row."""
    draft_id = _create_draft(tmp_path)
    db = tmp_path / "proforma_links.db"

    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT updated_at FROM proforma_drafts WHERE id=?", (draft_id,)
        ).fetchone()
        before_ts = row["updated_at"]

    client.get(f"/api/v1/proforma/draft/{draft_id}/visibility", headers=_HEADERS)

    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT updated_at FROM proforma_drafts WHERE id=?", (draft_id,)
        ).fetchone()
        after_ts = row["updated_at"]

    assert before_ts == after_ts, "visibility endpoint must not mutate draft.updated_at"


# ── /intelligence ─────────────────────────────────────────────────────────────

def test_intelligence_200_basic(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["draft_id"] == draft_id


def test_intelligence_has_required_keys(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)
    body = r.json()
    for key in ("anomalies", "suggestions", "confidence", "corpus_size"):
        assert key in body, f"Missing key: {key}"


def test_intelligence_confidence_subkeys(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)
    body = r.json()
    conf = body["confidence"]
    for k in ("overall", "company", "lines", "shipment", "pricing"):
        assert k in conf, f"Missing confidence sub-key: {k}"
        assert 0.0 <= conf[k] <= 1.0, f"confidence.{k} out of range: {conf[k]}"


def test_intelligence_anomalies_is_list(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)
    body = r.json()
    assert isinstance(body["anomalies"], list)


def test_intelligence_suggestions_is_list(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)
    body = r.json()
    assert isinstance(body["suggestions"], list)


def test_intelligence_no_name_sk_in_suggestions(client, tmp_path):
    """Language policy: name_sk must never appear in suggestions."""
    # Draft with empty names to maximise chance of suggestions
    lines = [{"line_id": "L1", "product_code": "P001",
              "unit_price": 100.0, "qty": 1}]
    draft_id = _create_draft(tmp_path, lines=lines)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)
    body = r.json()
    for s in body["suggestions"]:
        assert s.get("field") != "name_sk", (
            "name_sk must never be suggested (language policy: PL+EN only)"
        )


def test_intelligence_clean_lines_no_anomalies(client, tmp_path):
    lines = [
        {"line_id": "L1", "product_code": "P001",
         "unit_price": 100.0, "hs_code": "7113191000",
         "name_pl": "Pierścień", "name_en": "Ring",
         "qty": 1, "currency": "EUR"},
    ]
    draft_id = _create_draft(tmp_path, lines=lines)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)
    body = r.json()
    high_anomalies = [a for a in body["anomalies"] if a["severity"] == "high"]
    assert high_anomalies == []


def test_intelligence_zero_price_anomaly_detected(client, tmp_path):
    lines = [
        {"line_id": "L1", "product_code": "P001",
         "unit_price": 0, "hs_code": "7113",
         "name_pl": "ok", "name_en": "ok", "qty": 1},
    ]
    draft_id = _create_draft(tmp_path, lines=lines)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)
    body = r.json()
    types = [a["anomaly_type"] for a in body["anomalies"]]
    assert "zero_price" in types


def test_intelligence_corpus_size_zero_when_no_posted_drafts(client, tmp_path):
    draft_id = _create_draft(tmp_path)
    r = client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)
    body = r.json()
    assert body["corpus_size"] == 0  # no posted drafts seeded


def test_intelligence_404_unknown_draft(client, tmp_path):
    r = client.get("/api/v1/proforma/draft/9999999/intelligence", headers=_HEADERS)
    assert r.status_code == 404


def test_intelligence_no_mutations(client, tmp_path):
    """Calling intelligence must not mutate the draft row."""
    draft_id = _create_draft(tmp_path)
    db = tmp_path / "proforma_links.db"

    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT updated_at FROM proforma_drafts WHERE id=?", (draft_id,)
        ).fetchone()
        before_ts = row["updated_at"]

    client.get(f"/api/v1/proforma/draft/{draft_id}/intelligence", headers=_HEADERS)

    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT updated_at FROM proforma_drafts WHERE id=?", (draft_id,)
        ).fetchone()
        after_ts = row["updated_at"]

    assert before_ts == after_ts, "intelligence endpoint must not mutate draft.updated_at"
