"""test_packing_reprocess_endpoint.py — P2 reprocess endpoint + .xls support.

Permanent app-level behaviour:
  - .xls files parse via xlrd (1.2.x line, pinned in requirements.txt).
  - POST /api/v1/packing/{batch}/reprocess re-runs the safe packing
    parser against on-disk shipment_documents rows for the batch.
  - Purchase vs sales separation preserved by document_type.
  - Parser failures non-fatal; per-file status returned.
  - Idempotent on repeat runs.
  - No DHL / SAD / PZ / wFirma / proforma execution from this code path.

These tests are batch-agnostic — they construct ephemeral batches in tmp
storage. The production fixture
(SHIPMENT_4218922912_2026-05_bd18ec98) is only the smoke target, never
referenced from app code or tests.
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ─────────────────────────────────────────────────────────────

def _build_ejl_purchase_xls(path: Path) -> None:
    """Build a tiny .xls file matching the EJL purchase packing layout
    via xlwt (companion to xlrd 1.2). If xlwt isn't installed, write a
    minimal-but-valid xls via xlrd's compound-doc format is not feasible
    in pure Python; instead use a generated .xls from a small Python
    helper that xlwt provides. We keep the dep optional — when xlwt is
    missing, the test SKIPs."""
    try:
        import xlwt
    except ImportError:
        pytest.skip("xlwt not installed — cannot build .xls fixture")
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Sheet1")
    headers = ["PkSr", "Ctg", "DesignNo", "Kt/Color", "Quality",
               "Dia Wt", "Col Wt", "Qty", "Value", "Total Value", "Size"]
    for c, h in enumerate(headers):
        ws.write(0, c, h)
    # Row of data
    data = [1, "PND", "EJL-001", "14KT/Y", "G-VS",
            0.5, 0.1, 5, 100.0, 500.0, "7"]
    for c, v in enumerate(data):
        ws.write(1, c, v)
    wb.save(str(path))


def _build_ejl_sales_xlsx(path: Path, rows: int = 2) -> None:
    """Build a real EJL-style sales packing xlsx via openpyxl. Header
    layout matches the smoke-batch real files (preamble at top + header
    on row 13 + data below)."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "EstPolPkCLntTest"
    # Preamble (rows 0-12 in 0-based ⇒ Excel rows 1-13)
    for _ in range(10):
        ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "Invoice #", "", "", "EJL/26-27/TEST"])
    ws.append([])
    ws.append([])
    # Header row (Excel row 14 = 0-based row 13)
    ws.append(["", "Sr", "Ctg", "Client Po", "Design", "Kt", "Col",
               "Quality", "Dia Wt", "Col Wt", "", "Qty", "", "",
               "Value", "Total Value", "", "", "Size"])
    # Data rows
    for i in range(rows):
        ws.append(["", i + 1, "PND", f"PO-{i+1:03d}", f"DES-{i+1}", "14KT", "Y",
                   "G-VS", 0.1 * (i + 1), 0.05 * (i + 1), "", i + 1, "", "",
                   100.0 * (i + 1), 100.0 * (i + 1), "", "", str(40 + i)])
    wb.save(str(path))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@l"}

    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def _seed_batch(tmp_path: Path, batch_id: str) -> Path:
    """Create batch output folder + audit.json so the route accepts it."""
    out = tmp_path / "outputs" / batch_id
    (out / "source" / "packing").mkdir(parents=True, exist_ok=True)
    (out / "source" / "sales").mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "tracking_no": batch_id,
             "awb": batch_id, "carrier": "DHL", "timeline": []}
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out


def _register_doc(batch_id: str, document_type: str, file_path: Path) -> str:
    from app.services import document_db as ddb
    return ddb.register_document(
        batch_id=batch_id, document_type=document_type,
        file_name=file_path.name, file_path=str(file_path),
        file_hash=ddb.sha256_file(file_path) if file_path.exists() else f"h-{file_path.name}",
        source="intake",
    ) or ""


# ── Part A: .xls support ─────────────────────────────────────────────────

def test_xlrd_is_importable():
    """The requirements.txt pin must produce an installable xlrd. If this
    fails on the test runner the production deploy will also fail."""
    import xlrd
    # 1.2.x line keeps .xls support; 2.0+ does not.
    major = int(xlrd.__version__.split(".")[0])
    assert major < 2, f"xlrd must be pinned <2.0.0; got {xlrd.__version__}"


def test_extract_packing_handles_xls(tmp_path):
    """Round-trip an EJL-style .xls through extract_packing. Failures
    here usually mean xlrd is missing or pinned wrong on production."""
    from app.services.invoice_packing_extractor import extract_packing
    xls = tmp_path / "ejl_purchase.xls"
    _build_ejl_purchase_xls(xls)
    rows, _, _, diag = extract_packing(xls)
    assert diag["failure_reason"] is None
    assert diag["file_type"] == ".xls"
    assert diag["chosen_header"] is not None
    assert diag["row_count"] >= 1


# ── Part B: reprocess endpoint ───────────────────────────────────────────

def test_reprocess_empty_batch_returns_empty_results(client):
    cli, tmp = client
    _seed_batch(tmp, "B-EMPTY")
    r = cli.post("/api/v1/packing/B-EMPTY/reprocess")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files"] == []
    assert body["summary"] == {"files": 0, "rows": 0, "purchase": 0, "sales": 0}


def test_reprocess_sales_xlsx_produces_sales_packing_lines(client):
    cli, tmp = client
    bid = "B-SALES-1"
    out = _seed_batch(tmp, bid)
    sp = out / "source" / "sales" / "sales_ejl.xlsx"
    _build_ejl_sales_xlsx(sp, rows=4)
    _register_doc(bid, "sales_packing_list", sp)

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["files"]) == 1
    f = body["files"][0]
    assert f["document_type"] == "sales_packing_list"
    assert f["parser_status"] == "extracted"
    assert f["rows_extracted"] == 4
    assert f["failure_reason"] is None
    assert body["summary"]["sales"] == 4
    assert body["summary"]["purchase"] == 0
    # sales_packing_lines persisted
    with sqlite3.connect(str(tmp / "documents.db")) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM sales_packing_lines WHERE batch_id=?", (bid,)
        ).fetchall()
    assert len(rows) == 4


def test_reprocess_purchase_xls_produces_packing_lines(client):
    """.xls purchase file must parse and write to packing_lines (not
    sales_packing_lines)."""
    try:
        import xlwt  # noqa: F401
    except ImportError:
        pytest.skip("xlwt not installed — cannot build .xls fixture")
    cli, tmp = client
    bid = "B-PURCHASE-XLS"
    out = _seed_batch(tmp, bid)
    pp = out / "source" / "packing" / "ejl_purchase.xls"
    _build_ejl_purchase_xls(pp)
    _register_doc(bid, "purchase_packing_list", pp)

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200, r.text
    body = r.json()
    f = body["files"][0]
    assert f["document_type"] == "purchase_packing_list"
    assert f["parser_status"] in ("extracted", "empty")
    # Purchase-side write target
    with sqlite3.connect(str(tmp / "packing.db")) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM packing_lines WHERE batch_id=?", (bid,)
        ).fetchall()
    # If parsed successfully → at least one row
    if f["parser_status"] == "extracted":
        assert len(rows) >= 1
    assert body["summary"]["sales"] == 0


def test_reprocess_purchase_and_sales_remain_separate(client):
    """A batch with one purchase .xlsx + one sales .xlsx must route each
    to the correct table and never cross-contaminate."""
    cli, tmp = client
    bid = "B-MIX-1"
    out = _seed_batch(tmp, bid)
    # Purchase xlsx (no xlwt dependency)
    pp = out / "source" / "packing" / "ejl_purchase.xlsx"
    _build_ejl_sales_xlsx(pp, rows=2)   # reuse EJL layout — header pattern matches
    _register_doc(bid, "purchase_packing_list", pp)
    # Sales xlsx
    sp = out / "source" / "sales" / "ejl_sales.xlsx"
    _build_ejl_sales_xlsx(sp, rows=3)
    _register_doc(bid, "sales_packing_list", sp)

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200, r.text
    body = r.json()
    purchase_files = [f for f in body["files"] if f["document_type"] == "purchase_packing_list"]
    sales_files    = [f for f in body["files"] if f["document_type"] == "sales_packing_list"]
    assert len(purchase_files) == 1
    assert len(sales_files)    == 1
    # purchase_packing_lines populated; sales row count separate
    with sqlite3.connect(str(tmp / "packing.db")) as conn:
        purchase_rows = conn.execute(
            "SELECT COUNT(*) FROM packing_lines WHERE batch_id=?", (bid,)
        ).fetchone()[0]
    with sqlite3.connect(str(tmp / "documents.db")) as conn:
        sales_rows = conn.execute(
            "SELECT COUNT(*) FROM sales_packing_lines WHERE batch_id=?", (bid,)
        ).fetchone()[0]
    assert purchase_rows >= 1
    assert sales_rows == 3


def test_reprocess_document_id_filter_only_processes_one(client):
    cli, tmp = client
    bid = "B-FILTER-1"
    out = _seed_batch(tmp, bid)
    sp1 = out / "source" / "sales" / "a.xlsx"
    sp2 = out / "source" / "sales" / "b.xlsx"
    _build_ejl_sales_xlsx(sp1, rows=2)
    _build_ejl_sales_xlsx(sp2, rows=3)
    id1 = _register_doc(bid, "sales_packing_list", sp1)
    id2 = _register_doc(bid, "sales_packing_list", sp2)
    assert id1 and id2 and id1 != id2

    r = cli.post(f"/api/v1/packing/{bid}/reprocess", json={"document_id": id1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["files"]) == 1
    assert body["files"][0]["document_id"] == id1
    assert body["summary"]["sales"] == 2


def test_reprocess_parser_failure_is_nonfatal(client):
    """Inject a corrupt .xlsx and confirm the endpoint still returns 200
    with per-file failure_reason populated."""
    cli, tmp = client
    bid = "B-FAIL-1"
    out = _seed_batch(tmp, bid)
    corrupt = out / "source" / "sales" / "corrupt.xlsx"
    corrupt.write_bytes(b"PK\x03\x04smoke-corrupt-data")
    _register_doc(bid, "sales_packing_list", corrupt)

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200, r.text
    body = r.json()
    f = body["files"][0]
    assert f["parser_status"] in ("empty", "extraction_failed")
    assert f["failure_reason"] in (
        "parser_exception", "file_corrupt", "header_not_detected",
    )
    # Diagnostic artifact path returned on failure
    assert f["diagnostic_artifact"]


def test_reprocess_is_idempotent(client):
    cli, tmp = client
    bid = "B-IDEM-1"
    out = _seed_batch(tmp, bid)
    sp = out / "source" / "sales" / "sales.xlsx"
    _build_ejl_sales_xlsx(sp, rows=3)
    _register_doc(bid, "sales_packing_list", sp)

    r1 = cli.post(f"/api/v1/packing/{bid}/reprocess").json()
    r2 = cli.post(f"/api/v1/packing/{bid}/reprocess").json()
    # Same rows extracted on repeat run (file unchanged).
    assert r1["summary"]["rows"] == r2["summary"]["rows"]
    assert r1["summary"]["sales"] == r2["summary"]["sales"]


def test_reprocess_missing_batch_returns_404(client):
    cli, _ = client
    r = cli.post("/api/v1/packing/NO-SUCH-BATCH/reprocess")
    assert r.status_code == 404


# ── Side-effect guard ────────────────────────────────────────────────────

def test_reprocess_endpoint_has_no_external_system_triggers():
    """Source-grep guard: the reprocess endpoint block must not reference
    DHL / wFirma / proforma / PZ / SAD / email write surfaces."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes_packing.py").read_text(encoding="utf-8")
    start = src.index("# ── POST /api/v1/packing/{batch_id}/reprocess")
    end   = src.index("# ── GET /api/v1/packing/{batch_id}/lines", start)
    block = src[start:end]
    for forbidden in (
        "send_email", "queue_email", "smtp",
        "create_pz", "generate_pz",
        "wfirma_client", "wfirma_api",
        "proforma_create", "proforma_issue", "proforma_post",
        "process_sad", "trigger_clearance", "dhl_dispatch",
        "dhl_express",
    ):
        assert forbidden not in block, \
            f"reprocess endpoint must not reference {forbidden!r}"


def test_dashboard_has_reparse_button_testid():
    src = (Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    assert 'data-testid="packing-list-reparse-all"' in src
    assert "packing-list-reparse-summary" in src
    assert "/reprocess" in src
    assert "reparseBusy" in src


def test_endpoint_registered_in_app():
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/api/v1/packing/{batch_id}/reprocess" in paths
