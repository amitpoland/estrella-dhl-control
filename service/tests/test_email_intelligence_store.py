"""
test_email_intelligence_store.py — persistent email intelligence layer.

Verifies:
  - save_email_scan_result writes by_awb + indexes by invoice/MRN/ticket
  - get_by_awb / get_by_invoice / get_by_mrn / get_by_ticket return records
  - find_existing_email_context resolves via AWB → ticket → MRN → invoice
  - merging across multiple scans preserves linked_batches
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _settings_with_root(tmp_path: Path):
    """Mock settings.storage_root to point at tmp_path."""
    class S:
        storage_root = tmp_path
    return S()


def _scan_result(awb="2824221912", matched=10, **extras):
    base = {
        "awb":             awb,
        "matched":         matched,
        "confidence":      "high",
        "dhl_ticket":      "T#1WA2603100000499",
        "mrn":             "26PL44302D005LJ4R0",
        "searched":        {"invoice_numbers": ["EJL-25-26-1247-09-03-26"]},
        "threads":         [],
        "emails":          [],
        "derived_events":  [],
        "recommended_next_action": "no_action_required",
        "search_unreliable":      False,
        "manual_review_required": False,
        "source":          "claude_cowork_verified",
        "connector_used":  "mcp__620999a3",
        "account_id":      "2261204000000002002",
        "mailbox":         "amit@estrellajewels.eu",
    }
    base.update(extras)
    return base


# ── save + indexes ───────────────────────────────────────────────────────────

def test_save_writes_by_awb_index(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    rec = ei.save_email_scan_result(_scan_result(), audit={"batch_id": "B1"})
    assert rec["awb"] == "2824221912"
    by_awb = tmp_path / "email_intelligence" / "by_awb" / "2824221912.json"
    assert by_awb.exists()


def test_save_writes_invoice_index(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "B1"})
    inv_idx = tmp_path / "email_intelligence" / "by_invoice" / "EJL-25-26-1247-09-03-26.json"
    assert inv_idx.exists()
    data = json.loads(inv_idx.read_text())
    assert "2824221912" in data["awbs"]


def test_save_writes_mrn_and_ticket_indexes(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "B1"})
    mrn_idx    = tmp_path / "email_intelligence" / "by_mrn"    / "26PL44302D005LJ4R0.json"
    ticket_idx = tmp_path / "email_intelligence" / "by_ticket" / "T_1WA2603100000499.json"
    assert mrn_idx.exists()
    assert ticket_idx.exists()


def test_master_map_updated(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(awb="111"), audit={"batch_id": "B1"})
    ei.save_email_scan_result(_scan_result(awb="222"), audit={"batch_id": "B2"})
    master = json.loads((tmp_path / "email_intelligence" / "master_email_map.json").read_text())
    assert "111" in master and "222" in master


# ── lookups ──────────────────────────────────────────────────────────────────

def test_get_by_awb_returns_full_record(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "B1"})
    rec = ei.get_by_awb("2824221912")
    assert rec is not None
    assert rec["matched"] == 10
    assert rec["dhl_ticket"] == "T#1WA2603100000499"


def test_get_by_invoice_resolves_to_records(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "B1"})
    recs = ei.get_by_invoice("EJL-25-26-1247-09-03-26")
    assert len(recs) == 1
    assert recs[0]["awb"] == "2824221912"


def test_get_by_mrn_and_ticket(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "B1"})
    assert ei.get_by_mrn("26PL44302D005LJ4R0")[0]["awb"] == "2824221912"
    assert ei.get_by_ticket("T#1WA2603100000499")[0]["awb"] == "2824221912"


# ── find_existing_email_context ──────────────────────────────────────────────

def test_find_by_awb(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "B1"})
    rec = ei.find_existing_email_context({"awb": "2824221912"})
    assert rec is not None
    assert rec["awb"] == "2824221912"


def test_find_by_tracking_no_fallback(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "B1"})
    # awb missing — falls back to tracking_no
    rec = ei.find_existing_email_context({"tracking_no": "2824221912"})
    assert rec is not None


def test_find_by_ticket_when_awb_missing(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "B1"})
    rec = ei.find_existing_email_context({
        "dhl_email": {"ticket": "T#1WA2603100000499"},
    })
    assert rec is not None
    assert rec["awb"] == "2824221912"


def test_find_returns_none_when_nothing_matches(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    rec = ei.find_existing_email_context({"awb": "9999999999"})
    assert rec is None


# ── linked_batches accumulate across rescans ─────────────────────────────────

def test_linked_batches_accumulate_across_scans(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "BATCH_FIRST"})
    ei.save_email_scan_result(_scan_result(), audit={"batch_id": "BATCH_SECOND"})
    rec = ei.get_by_awb("2824221912")
    assert "BATCH_FIRST"  in rec["linked_batches"]
    assert "BATCH_SECOND" in rec["linked_batches"]


# ── unreliable cache must be saved but flagged ───────────────────────────────

def test_unreliable_record_is_stored_with_flag(tmp_path, monkeypatch):
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(ei, "settings", _settings_with_root(tmp_path))
    ei.save_email_scan_result(
        _scan_result(matched=0, search_unreliable=True, manual_review_required=True),
        audit={"batch_id": "B_BAD"},
    )
    rec = ei.get_by_awb("2824221912")
    assert rec["matched"] == 0
    assert rec["search_unreliable"] is True
    assert rec["manual_review_required"] is True
