"""
test_pz_totals_in_response.py — GET /dashboard/batches/{id} exposes PZ financial totals.

Problem fixed:
  The engine never writes total_net_pln / total_gross_pln / duty_a00_pln to
  audit.json root.  batch_detail now reads pz_rows.json at response-build time
  and injects the three totals if any are absent.  Never writes to audit.json.

Coverage
--------
  1. totals injected from pz_rows.json when absent from audit
  2. injected values match pz_rows.json sums (accuracy)
  3. rounding: values rounded to 2 decimal places
  4. no crash when pz_rows.json is missing
  5. no crash when pz_rows.json is empty list
  6. no crash when pz_rows.json is corrupt JSON
  7. totals already present in audit are NOT overwritten (pass-through)
  8. audit.json is NOT modified by the response read
  9. existing response fields (status, doc_no, batch_id) unchanged
 10. partial totals: only missing fields filled in
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import require_api_key


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    from app.api import routes_dashboard as rd
    from app.core.config import settings as s

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr(s, "storage_root", tmp_path)
    monkeypatch.setattr(rd, "_OUTPUTS", outputs, raising=False)

    app = FastAPI()
    app.include_router(rd.router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True), outputs


def _write_audit(outputs: Path, batch_id: str, extra: dict | None = None) -> Path:
    d = outputs / batch_id
    d.mkdir(parents=True, exist_ok=True)
    data = {
        "batch_id":  batch_id,
        "status":    "partial",
        "doc_no":    "PZ 1/5/2026",
        "inputs":    {},
        "failed_checks":    [],
        "amendment_flags":  [],
        "operator_overrides": [],
        "customs_declaration": {"mrn": "26PLTEST001"},
    }
    if extra:
        data.update(extra)
    p = d / "audit.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _write_pz_rows(outputs: Path, batch_id: str, rows: list) -> Path:
    p = outputs / batch_id / "pz_rows.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


_SAMPLE_ROWS = [
    {"invoice_no": "INV-001", "line_netto_pln": 1000.00, "line_brutto_pln": 1230.00, "allocated_duty_pln": 50.00},
    {"invoice_no": "INV-001", "line_netto_pln":  500.00, "line_brutto_pln":  615.00, "allocated_duty_pln": 25.00},
    {"invoice_no": "INV-002", "line_netto_pln":  250.33, "line_brutto_pln":  307.91, "allocated_duty_pln": 12.50},
]
_EXPECTED_NET   = round(1000.00 + 500.00 + 250.33, 2)   # 1750.33
_EXPECTED_GROSS = round(1230.00 + 615.00 + 307.91, 2)   # 2152.91
_EXPECTED_DUTY  = round(  50.00 +  25.00 +  12.50, 2)   #   87.50


# ═══════════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_totals_injected_from_pz_rows(tmp_path, monkeypatch):
    """1. totals injected when all three fields absent from audit."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T1"
    _write_audit(outputs, batch_id)
    _write_pz_rows(outputs, batch_id, _SAMPLE_ROWS)

    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["total_net_pln"]   == _EXPECTED_NET
    assert body["total_gross_pln"] == _EXPECTED_GROSS
    assert body["duty_a00_pln"]    == _EXPECTED_DUTY


def test_totals_match_pz_rows_sums(tmp_path, monkeypatch):
    """2. injected values equal per-row column sums exactly."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T2"
    rows = [
        {"line_netto_pln": 8895.93, "line_brutto_pln": 10941.99, "allocated_duty_pln": 221.00},
    ]
    _write_audit(outputs, batch_id)
    _write_pz_rows(outputs, batch_id, rows)

    r = client.get(f"/dashboard/batches/{batch_id}")
    body = r.json()
    assert body["total_net_pln"]   == 8895.93
    assert body["total_gross_pln"] == 10941.99
    assert body["duty_a00_pln"]    == 221.00


def test_totals_rounded_to_two_decimal_places(tmp_path, monkeypatch):
    """3. totals rounded to 2 decimal places."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T3"
    rows = [
        {"line_netto_pln": 100.001, "line_brutto_pln": 123.005, "allocated_duty_pln": 5.0049},
        {"line_netto_pln": 100.001, "line_brutto_pln": 123.005, "allocated_duty_pln": 5.0049},
    ]
    _write_audit(outputs, batch_id)
    _write_pz_rows(outputs, batch_id, rows)

    r = client.get(f"/dashboard/batches/{batch_id}")
    body = r.json()
    # Python round() — result must be 2dp
    assert body["total_net_pln"]   == round(200.002, 2)
    assert body["total_gross_pln"] == round(246.010, 2)
    assert body["duty_a00_pln"]    == round(10.0098, 2)


def test_no_crash_when_pz_rows_missing(tmp_path, monkeypatch):
    """4. response succeeds with no totals when pz_rows.json absent."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T4"
    _write_audit(outputs, batch_id)   # no pz_rows.json written

    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    body = r.json()
    # Fields absent — not null-injected, not present
    assert body.get("total_net_pln") is None
    assert body.get("total_gross_pln") is None
    assert body.get("duty_a00_pln") is None


def test_no_crash_when_pz_rows_empty_list(tmp_path, monkeypatch):
    """5. empty pz_rows.json list → no totals injected, no crash."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T5"
    _write_audit(outputs, batch_id)
    _write_pz_rows(outputs, batch_id, [])

    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200


def test_no_crash_when_pz_rows_corrupt(tmp_path, monkeypatch):
    """6. corrupt pz_rows.json → no totals injected, no crash."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T6"
    _write_audit(outputs, batch_id)
    (outputs / batch_id / "pz_rows.json").write_text("{not valid json!!}", encoding="utf-8")

    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200


def test_existing_audit_totals_not_overwritten(tmp_path, monkeypatch):
    """7. if totals already present in audit, pz_rows.json is ignored."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T7"
    _write_audit(outputs, batch_id, extra={
        "total_net_pln":   9999.99,
        "total_gross_pln": 11999.99,
        "duty_a00_pln":    999.99,
    })
    # pz_rows would produce different values — must NOT override
    _write_pz_rows(outputs, batch_id, _SAMPLE_ROWS)

    r = client.get(f"/dashboard/batches/{batch_id}")
    body = r.json()
    assert body["total_net_pln"]   == 9999.99
    assert body["total_gross_pln"] == 11999.99
    assert body["duty_a00_pln"]    == 999.99


def test_audit_json_totals_not_persisted_to_disk(tmp_path, monkeypatch):
    """8. PZ totals are injected into the response only — never written to audit.json.
    (Other fields such as clearance_decision may be backfilled by existing logic on
    first load; the constraint here is that total_net_pln / total_gross_pln /
    duty_a00_pln must not appear in the on-disk file after a GET.)"""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T8"
    audit_path = _write_audit(outputs, batch_id)
    _write_pz_rows(outputs, batch_id, _SAMPLE_ROWS)

    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    # Totals must appear in response
    body = r.json()
    assert body["total_net_pln"]   == _EXPECTED_NET
    assert body["total_gross_pln"] == _EXPECTED_GROSS
    assert body["duty_a00_pln"]    == _EXPECTED_DUTY

    # But NOT written back to audit.json on disk
    on_disk = json.loads(audit_path.read_text(encoding="utf-8"))
    assert "total_net_pln"   not in on_disk, "total_net_pln must not persist to disk"
    assert "total_gross_pln" not in on_disk, "total_gross_pln must not persist to disk"
    assert "duty_a00_pln"    not in on_disk, "duty_a00_pln must not persist to disk"


def test_existing_response_fields_unchanged(tmp_path, monkeypatch):
    """9. status, doc_no, batch_id, failed_checks not affected by totals injection."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T9"
    _write_audit(outputs, batch_id)
    _write_pz_rows(outputs, batch_id, _SAMPLE_ROWS)

    r = client.get(f"/dashboard/batches/{batch_id}")
    body = r.json()
    assert body["batch_id"]     == batch_id
    assert body["status"]       == "partial"
    assert body["doc_no"]       == "PZ 1/5/2026"
    assert body["failed_checks"] == []


def test_partial_totals_only_missing_fields_filled(tmp_path, monkeypatch):
    """10. if only duty_a00_pln is absent, only that field is filled from pz_rows."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    batch_id = "T10"
    _write_audit(outputs, batch_id, extra={
        "total_net_pln":   1234.56,
        "total_gross_pln": 1518.51,
        # duty_a00_pln intentionally missing
    })
    _write_pz_rows(outputs, batch_id, _SAMPLE_ROWS)

    r = client.get(f"/dashboard/batches/{batch_id}")
    body = r.json()
    # Pre-existing fields preserved
    assert body["total_net_pln"]   == 1234.56
    assert body["total_gross_pln"] == 1518.51
    # Missing field filled from pz_rows
    assert body["duty_a00_pln"]    == _EXPECTED_DUTY
