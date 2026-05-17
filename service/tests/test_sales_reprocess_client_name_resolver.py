"""test_sales_reprocess_client_name_resolver.py — Self-healing
resolver for sales_packing_list reprocess.

When sales_packing_lines.client_name was wiped before PR #187,
reprocess now recovers it from local DB evidence:
  Pass 3: shipment_documents.client_contractor_id → wfirma_customers
  Pass 4: _guess_client_from_filename (conservative last resort)

PR #187 Pass 1+2 (existing-row preservation) still wins when applicable.
All operations are local-DB read + targeted UPDATE on sales_documents.
No external API calls.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@local"}
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def _make_corrupted_batch(tmp: Path, bid: str, file_name: str,
                          client_contractor_id: str = "",
                          wfirma_cust: dict = None) -> str:
    """Mirror the corrupted-batch state: shipment_documents row has
    client_contractor_id but sales_documents and sales_packing_lines
    have empty client_name (as if a pre-PR-#187 reprocess wiped them)."""
    out = tmp / "outputs" / bid
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps({
        "batch_id": bid, "awb": "TEST-AWB", "timeline": [],
    }), encoding="utf-8")

    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    sid = ddb.register_document(
        batch_id=bid, document_type="sales_packing_list",
        file_name=file_name, file_path=str(out / file_name),
        file_hash=f"h-{file_name}", source="intake",
        client_contractor_id=client_contractor_id,
    )
    ddb.store_sales_document(
        batch_id=bid, document_id=sid,
        data={"client_name": "",   # CORRUPTED — pre-PR-#187 state
              "client_ref": "",
              "document_type": "sales_packing_list",
              "source_file_path": str(out / file_name),
              "extraction_status": "extracted"},
    )
    (out / file_name).write_bytes(b"stub")

    if wfirma_cust:
        from app.services import wfirma_db as wfdb
        wfdb.init_wfirma_db(tmp / "wfirma.db")
        wfdb.upsert_customer(**wfirma_cust)
    return sid


def _read_sales(tmp: Path, bid: str):
    from app.services import document_db as ddb
    return ddb.get_sales_packing_lines(bid)


def _patch_parser(monkeypatch, rows):
    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: (rows, "fake", "1.0", {"failure_reason": None}),
    )


# ── Test 1 — reverse helper ──────────────────────────────────────────────

def test_wfirma_reverse_helper(tmp_path):
    """get_customer_by_wfirma_id returns row by wfirma_customer_id;
    None when not found; None for empty input."""
    from app.services import wfirma_db as wfdb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    wfdb.upsert_customer(client_name="ACME Corp",
                         wfirma_customer_id="12345",
                         vat_id="PL123", country="PL")
    cust = wfdb.get_customer_by_wfirma_id("12345")
    assert cust is not None
    assert cust["client_name"] == "ACME Corp"
    assert wfdb.get_customer_by_wfirma_id("99999") is None
    assert wfdb.get_customer_by_wfirma_id("") is None


# ── Test 2 — Pass 3 resolves from wfirma_customers ─────────────────────

def test_pass3_resolves_from_wfirma_customers(client, monkeypatch):
    cli, tmp = client
    bid = "B-PASS3"
    _make_corrupted_batch(
        tmp, bid, "146 sales.xlsx",
        client_contractor_id="42",
        wfirma_cust={"client_name": "ACME Corp",
                     "wfirma_customer_id": "42",
                     "vat_id": "PL42", "country": "PL"},
    )
    _patch_parser(monkeypatch, [{"product_code": "X", "quantity": 1.0,
                                  "unit_price": 100.0, "currency": "USD"}])
    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200, r.text
    rows = _read_sales(tmp, bid)
    assert rows, "no rows after reprocess"
    assert all(rec["client_name"] == "ACME Corp" for rec in rows), (
        f"Pass 3 failed; client_names="
        f"{[rec['client_name'] for rec in rows]}"
    )


# ── Test 3 — Pass 4 resolves from filename ────────────────────────────

def test_pass4_resolves_from_filename(client, monkeypatch):
    cli, tmp = client
    bid = "B-PASS4"
    # client_contractor_id present BUT not in wfirma cache → Pass 3 fails
    # → Pass 4 fires from filename.
    _make_corrupted_batch(
        tmp, bid, "200 Client BetaCo.xlsx",
        client_contractor_id="9999",   # NOT in wfirma_customers
        wfirma_cust=None,
    )
    _patch_parser(monkeypatch, [{"product_code": "Y", "quantity": 1.0,
                                  "unit_price": 50.0, "currency": "EUR"}])
    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200
    rows = _read_sales(tmp, bid)
    assert rows
    assert all(rec["client_name"] == "BetaCo" for rec in rows), (
        f"Pass 4 filename hint failed: "
        f"{[rec['client_name'] for rec in rows]}"
    )


# ── Test 4 — PR #187 Pass 1/2 still wins ──────────────────────────────

def test_pr187_existing_row_preservation_still_wins(client, monkeypatch):
    """When existing sales_packing_lines already have a non-empty
    client_name, Pass 1 (per-doc) or Pass 2 (batch) must win — Pass 3/4
    should NOT override.  Regression guard for PR #187 precedence."""
    cli, tmp = client
    bid = "B-PR187-WINS"
    _make_corrupted_batch(
        tmp, bid, "300 Client WrongName.xlsx",
        client_contractor_id="42",
        wfirma_cust={"client_name": "Distractor Inc",
                     "wfirma_customer_id": "42",
                     "vat_id": "PL42", "country": "PL"},
    )
    # Seed existing sales_packing_lines with the canonical client_name
    # (mimicking intake-good state).
    from app.services import document_db as ddb
    sd_rows = ddb.get_sales_documents(bid)
    real_sd_id = sd_rows[0]["id"]
    ddb.store_sales_packing_lines(
        sales_document_id=real_sd_id, batch_id=bid,
        lines=[{"client_name": "CorrectClient Ltd", "client_ref": "",
                "product_code": "P-OLD", "design_no": "", "bag_id": "",
                "quantity": 1.0, "remarks": "",
                "unit_price": 10.0, "currency": "USD", "total_value": 10.0}],
    )
    _patch_parser(monkeypatch, [{"product_code": "P-NEW", "quantity": 2.0,
                                  "unit_price": 20.0, "currency": "USD"}])
    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200
    rows = _read_sales(tmp, bid)
    new_rows = [rec for rec in rows if rec["product_code"] == "P-NEW"]
    assert new_rows
    # Pass 1 or 2 should have lifted "CorrectClient Ltd" — NOT
    # "Distractor Inc" from wfirma, NOT "WrongName" from filename.
    assert new_rows[0]["client_name"] == "CorrectClient Ltd", (
        f"PR #187 preservation regressed: client_name="
        f"{new_rows[0]['client_name']!r} (expected 'CorrectClient Ltd')"
    )


# ── Test 5 — sales_documents.client_name backfilled ───────────────────

def test_sales_documents_client_name_backfilled(client, monkeypatch):
    """After Pass 3 recovery, sales_documents.client_name must be
    backfilled when previously empty."""
    cli, tmp = client
    bid = "B-BACKFILL"
    _make_corrupted_batch(
        tmp, bid, "400 sales.xlsx",
        client_contractor_id="55",
        wfirma_cust={"client_name": "Filled Co",
                     "wfirma_customer_id": "55",
                     "vat_id": "PL55", "country": "PL"},
    )
    _patch_parser(monkeypatch, [{"product_code": "Z", "quantity": 1.0,
                                  "unit_price": 1.0, "currency": "EUR"}])
    cli.post(f"/api/v1/packing/{bid}/reprocess")
    from app.services import document_db as ddb
    sds = ddb.get_sales_documents(bid)
    assert any(sd["client_name"] == "Filled Co" for sd in sds), (
        f"sales_documents.client_name not backfilled: "
        f"{[sd['client_name'] for sd in sds]}"
    )


# ── Test 6 — no inference possible → empty + log warn ─────────────────

def test_no_inference_possible_leaves_empty(client, monkeypatch, caplog):
    """When no client_contractor_id AND no filename pattern, resolver
    leaves client_name empty and logs a WARN."""
    cli, tmp = client
    bid = "B-NONE"
    _make_corrupted_batch(
        tmp, bid, "random_data_file.xlsx",
        client_contractor_id="",
        wfirma_cust=None,
    )
    _patch_parser(monkeypatch, [{"product_code": "W", "quantity": 1.0,
                                  "unit_price": 1.0, "currency": "EUR"}])
    with caplog.at_level(logging.WARNING):
        cli.post(f"/api/v1/packing/{bid}/reprocess")
    rows = _read_sales(tmp, bid)
    assert rows
    assert all(rec["client_name"] == "" for rec in rows)
    assert any("NO client_name resolvable" in rec.message
               for rec in caplog.records), \
        "expected WARN log for unresolvable client_name"


# ── Test 7 — resolver path has no external calls ──────────────────────

def test_resolver_source_has_no_external_calls():
    """Source-grep guard — sales reprocess branch must not introduce
    HTTP or wFirma API client calls."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_packing.py").read_text(encoding="utf-8")
    idx = src.index('elif document_type == "sales_packing_list":')
    end_str = src.find("else:", idx)
    if end_str < 0 or end_str - idx > 30000:
        end_str = idx + 30000
    sales_branch = src[idx:end_str]
    for forbidden in ("requests.", "httpx.", "wfirma_client",
                      "smtp", "send_email", "dhl_dispatch"):
        assert forbidden not in sales_branch, (
            f"sales reprocess branch must not reference {forbidden!r}"
        )


# ── Test 8 — purchase branch untouched ────────────────────────────────

def test_purchase_branch_does_not_contain_resolver_markers():
    """The purchase reprocess branch must not contain client-name
    resolver markers — resolver is sales-only."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_packing.py").read_text(encoding="utf-8")
    idx_purchase = src.index('if document_type == "purchase_packing_list":')
    idx_sales = src.index('elif document_type == "sales_packing_list":')
    purchase_branch = src[idx_purchase:idx_sales]
    for marker in ("get_customer_by_wfirma_id",
                   "preserved_client_name",
                   "_guess_client_from_filename"):
        assert marker not in purchase_branch, (
            f"purchase branch must not contain resolver marker {marker!r}"
        )
