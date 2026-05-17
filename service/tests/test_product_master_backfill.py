"""test_product_master_backfill.py — PR-4 Product Master Backfill.

Verifies the admin-gated, dry-run-first projection of historical
invoice_lines.product_code into product_master.

Architecture rules verified:
  * invoice_lines is the only source — product_code never invented.
  * Idempotent: 2nd run produces inserted=0.
  * dry_run=True writes nothing and returns a preview.
  * PR #193 preserve-on-blank semantics protect existing rows.
  * Local-DB only — no external HTTP / wFirma / SMTP / DHL calls.
  * Admin-gated endpoint refuses non-admin users.
  * No product_code mint patterns appear in the backfill source.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)

    from app.services import document_db as ddb
    from app.services import reservation_db as rdb
    ddb.init_document_db(tmp_path / "documents.db")
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    return tmp_path


@pytest.fixture()
def admin_client(fresh):
    """TestClient with an admin user via dependency override."""
    tmp = fresh
    from app.main import app
    from app.auth.dependencies import require_admin, get_current_user

    def _admin():
        return {"id": "admin-1", "email": "admin@local",
                "role": "admin", "is_active": 1, "is_approved": 1}

    app.dependency_overrides[require_admin]     = _admin
    app.dependency_overrides[get_current_user]  = _admin
    yield TestClient(app), tmp
    app.dependency_overrides.clear()


@pytest.fixture()
def non_admin_client(fresh):
    """TestClient where require_admin is NOT overridden (default = 401)."""
    tmp = fresh
    from app.main import app
    yield TestClient(app), tmp


def _seed_doc(tmp: Path, batch_id: str, file_hash: str = "h") -> str:
    from app.services import document_db as ddb
    return ddb.register_document(
        batch_id=batch_id, document_type="invoice",
        file_name="inv.pdf", file_path="/tmp/inv.pdf",
        file_hash=f"{file_hash}-{batch_id}", source="intake",
    ) or ""


def _seed_invoice_line(tmp: Path, batch_id: str, doc_id: str,
                        *, product_code: str, invoice_no: str = "INV-X",
                        line_position: int = 1, description: str = "",
                        currency: str = "USD", unit_price: float = 0.0,
                        hsn_code: str = "", hs_code: str = "") -> None:
    """Insert one invoice_lines row directly so we control created_at order."""
    db = tmp / "documents.db"
    now = time.strftime("%Y-%m-%dT%H:%M:%S",
                        time.gmtime(time.time() + line_position * 0.001))
    with sqlite3.connect(str(db)) as con:
        con.execute(
            """INSERT OR IGNORE INTO invoice_lines
               (id, document_id, batch_id, invoice_no, line_position,
                product_code, description, quantity, unit_price,
                total_value, currency, hs_code,
                gross_weight, net_weight, rate_usd, amount_usd, hsn_code,
                created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), doc_id, batch_id, invoice_no, line_position,
             product_code, description, 1.0, unit_price,
             unit_price, currency, hs_code,
             0.0, 0.0, unit_price, unit_price, hsn_code,
             now),
        )


def _pm_count(tmp: Path) -> int:
    with sqlite3.connect(str(tmp / "reservation_queue.db")) as con:
        return con.execute("SELECT COUNT(*) FROM product_master").fetchone()[0]


def _pm_row(tmp: Path, pc: str):
    with sqlite3.connect(str(tmp / "reservation_queue.db")) as con:
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT * FROM product_master WHERE product_code=?", (pc,),
        ).fetchone()
    return dict(r) if r else None


# ── 1. inserts all missing codes ──────────────────────────────────────────

def test_inserts_all_missing_codes(fresh):
    tmp = fresh
    bid = "B-INSERT"
    doc = _seed_doc(tmp, bid)
    for i, pc in enumerate(["EJL/X-1", "EJL/X-2", "EJL/X-3"], start=1):
        _seed_invoice_line(tmp, bid, doc, product_code=pc,
                            invoice_no="INV-A", line_position=i,
                            currency="USD", unit_price=100.0 + i,
                            hsn_code="7113")

    from app.services.product_master_backfill import backfill_from_invoice_lines
    summary = backfill_from_invoice_lines(tmp, dry_run=False)

    assert summary["scanned_codes"] == 3
    assert summary["inserted"] == 3
    assert summary["updated"] == 0
    assert summary["errors"] == []
    assert _pm_count(tmp) == 3


# ── 2. idempotent ─────────────────────────────────────────────────────────

def test_idempotent_second_run_inserted_zero(fresh):
    tmp = fresh
    bid = "B-IDEM"
    doc = _seed_doc(tmp, bid)
    _seed_invoice_line(tmp, bid, doc, product_code="EJL/Y-1")

    from app.services.product_master_backfill import backfill_from_invoice_lines
    s1 = backfill_from_invoice_lines(tmp, dry_run=False)
    assert s1["inserted"] == 1
    s2 = backfill_from_invoice_lines(tmp, dry_run=False)
    assert s2["inserted"] == 0
    assert s2["updated"]  == 1
    assert _pm_count(tmp) == 1


# ── 3. dry_run writes nothing and returns preview ─────────────────────────

def test_dry_run_writes_nothing_and_previews(fresh):
    tmp = fresh
    bid = "B-DRY"
    doc = _seed_doc(tmp, bid)
    _seed_invoice_line(tmp, bid, doc, product_code="EJL/D-1")
    _seed_invoice_line(tmp, bid, doc, product_code="EJL/D-2",
                        line_position=2)

    from app.services.product_master_backfill import backfill_from_invoice_lines
    summary = backfill_from_invoice_lines(tmp, dry_run=True)

    assert summary["dry_run"] is True
    assert summary["inserted"] == 0
    assert summary["updated"] == 0
    assert _pm_count(tmp) == 0
    actions = sorted([p["action"] for p in summary["preview"]])
    assert actions == ["insert", "insert"]
    pcs = sorted([p["product_code"] for p in summary["preview"]])
    assert pcs == ["EJL/D-1", "EJL/D-2"]


# ── 4. preserves existing non-empty fields ────────────────────────────────

def test_preserves_existing_non_empty_design_no(fresh):
    """If PM already has a row with design_no='D-X', backfill (which
    passes design_no='') must NOT overwrite it (PR #193 preserve-on-blank)."""
    tmp = fresh
    from app.services import reservation_db as rdb
    rdb.upsert_product_master(
        tmp / "reservation_queue.db",
        product_code="EJL/P-1", design_no="D-X",
        source_batch_id="B-OLD", source_invoice_no="INV-OLD",
    )
    bid = "B-NEW"
    doc = _seed_doc(tmp, bid)
    _seed_invoice_line(tmp, bid, doc, product_code="EJL/P-1",
                        invoice_no="INV-NEW")

    from app.services.product_master_backfill import backfill_from_invoice_lines
    summary = backfill_from_invoice_lines(tmp, dry_run=False)
    assert summary["updated"] == 1
    row = _pm_row(tmp, "EJL/P-1")
    assert row["design_no"]         == "D-X"        # preserved
    assert row["source_batch_id"]   == "B-OLD"      # preserved
    assert row["source_invoice_no"] == "INV-OLD"    # preserved
    assert row["last_seen_batch_id"] == "B-NEW"    # advanced


# ── 5. skip empty product_code ────────────────────────────────────────────

def test_skips_empty_product_code(fresh):
    tmp = fresh
    bid = "B-SKIP"
    doc = _seed_doc(tmp, bid)
    _seed_invoice_line(tmp, bid, doc, product_code="")        # smell
    _seed_invoice_line(tmp, bid, doc, product_code="EJL/S-2",
                        line_position=2)

    from app.services.product_master_backfill import backfill_from_invoice_lines
    summary = backfill_from_invoice_lines(tmp, dry_run=False)
    assert summary["skipped_empty_code"] == 1
    assert summary["inserted"] == 1
    assert _pm_count(tmp) == 1


# ── 6. partial existing state handled ─────────────────────────────────────

def test_partial_existing_state_handled(fresh):
    tmp = fresh
    from app.services import reservation_db as rdb
    # Pre-seed 2 of 5 expected codes.
    for pc in ("EJL/P-A", "EJL/P-B"):
        rdb.upsert_product_master(tmp / "reservation_queue.db",
                                    product_code=pc, design_no="")
    bid = "B-P"
    doc = _seed_doc(tmp, bid)
    for i, pc in enumerate(
        ["EJL/P-A", "EJL/P-B", "EJL/P-C", "EJL/P-D", "EJL/P-E"], start=1
    ):
        _seed_invoice_line(tmp, bid, doc, product_code=pc,
                            line_position=i)

    from app.services.product_master_backfill import backfill_from_invoice_lines
    summary = backfill_from_invoice_lines(tmp, dry_run=False)
    assert summary["inserted"] == 3
    assert summary["updated"]  == 2
    assert _pm_count(tmp) == 5


# ── 7. admin endpoint is gated ────────────────────────────────────────────

def test_admin_endpoint_gated(non_admin_client):
    cli, _tmp = non_admin_client
    r = cli.post("/api/v1/admin/product-master/backfill", json={})
    # Without auth override, require_admin chains get_current_user → 401.
    assert r.status_code in (401, 403), (
        f"non-admin must not be able to trigger backfill; got {r.status_code}"
    )


# ── 8. endpoint default is dry_run=True ──────────────────────────────────

def test_endpoint_default_is_dry_run(admin_client):
    cli, tmp = admin_client
    bid = "B-DEFAULT"
    doc = _seed_doc(tmp, bid)
    _seed_invoice_line(tmp, bid, doc, product_code="EJL/DEF-1")

    r = cli.post("/api/v1/admin/product-master/backfill", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["inserted"] == 0
    assert _pm_count(tmp) == 0


# ── 9. endpoint writes only when dry_run=false ────────────────────────────

def test_endpoint_writes_when_dry_run_false(admin_client):
    cli, tmp = admin_client
    bid = "B-WRITE"
    doc = _seed_doc(tmp, bid)
    _seed_invoice_line(tmp, bid, doc, product_code="EJL/W-1")

    r = cli.post("/api/v1/admin/product-master/backfill",
                 json={"dry_run": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    assert body["inserted"] == 1
    assert _pm_count(tmp) == 1


# ── 10. no external calls in backfill source ─────────────────────────────

def test_no_external_calls_in_backfill_source():
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "product_master_backfill.py").read_text(encoding="utf-8")
    for forbidden in ("requests.", "httpx.", "wfirma_client",
                      "smtp", "send_email", "dhl_dispatch"):
        assert forbidden not in src, (
            f"product_master_backfill must not reference {forbidden!r}"
        )


# ── 11. no product_code invention pattern ────────────────────────────────

def test_no_product_code_invention_in_backfill_source():
    """Backfill must COPY product_code from invoice_lines, never invent.
    No f-string mint pattern or design_no assignment to product_code."""
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "product_master_backfill.py").read_text(encoding="utf-8")
    forbidden_patterns = [
        'f"{inv_no}-{pos}"',
        'product_code = f"',
        'product_code = design_no',
        'product_code = dn',
        '"product_code": design_no',
    ]
    for p in forbidden_patterns:
        assert p not in src, (
            f"backfill must not invent product_code: pattern {p!r} found"
        )


# ── 12. oldest row becomes source_batch_id ────────────────────────────────

def test_oldest_row_becomes_source_batch_id(fresh):
    tmp = fresh
    # Two batches sharing the same product_code; A inserted first (older).
    doc_a = _seed_doc(tmp, "B-OLDEST-A", file_hash="ha")
    _seed_invoice_line(tmp, "B-OLDEST-A", doc_a, product_code="EJL/SH-1",
                        invoice_no="INV-A", line_position=1)
    doc_b = _seed_doc(tmp, "B-OLDEST-B", file_hash="hb")
    _seed_invoice_line(tmp, "B-OLDEST-B", doc_b, product_code="EJL/SH-1",
                        invoice_no="INV-B", line_position=5)

    from app.services.product_master_backfill import backfill_from_invoice_lines
    backfill_from_invoice_lines(tmp, dry_run=False)
    row = _pm_row(tmp, "EJL/SH-1")
    assert row["source_batch_id"]   == "B-OLDEST-A"
    assert row["source_invoice_no"] == "INV-A"


# ── 13. newest row becomes last_seen_batch_id ─────────────────────────────

def test_newest_row_becomes_last_seen_batch_id(fresh):
    tmp = fresh
    doc_a = _seed_doc(tmp, "B-LS-A", file_hash="ha")
    _seed_invoice_line(tmp, "B-LS-A", doc_a, product_code="EJL/LS-1",
                        invoice_no="INV-A", line_position=1)
    doc_b = _seed_doc(tmp, "B-LS-B", file_hash="hb")
    _seed_invoice_line(tmp, "B-LS-B", doc_b, product_code="EJL/LS-1",
                        invoice_no="INV-B", line_position=2)

    from app.services.product_master_backfill import backfill_from_invoice_lines
    backfill_from_invoice_lines(tmp, dry_run=False)
    row = _pm_row(tmp, "EJL/LS-1")
    assert row["source_batch_id"]    == "B-LS-A"
    assert row["last_seen_batch_id"] == "B-LS-B"


# ── 14. batch_id_filter scopes scan ───────────────────────────────────────

def test_batch_id_filter_restricts_scan(fresh):
    tmp = fresh
    doc_a = _seed_doc(tmp, "B-FILT-A", file_hash="ha")
    doc_b = _seed_doc(tmp, "B-FILT-B", file_hash="hb")
    _seed_invoice_line(tmp, "B-FILT-A", doc_a, product_code="EJL/F-A")
    _seed_invoice_line(tmp, "B-FILT-B", doc_b, product_code="EJL/F-B",
                        line_position=2)

    from app.services.product_master_backfill import backfill_from_invoice_lines
    summary = backfill_from_invoice_lines(
        tmp, dry_run=False, batch_id_filter="B-FILT-A",
    )
    assert summary["scanned_codes"] == 1
    assert _pm_row(tmp, "EJL/F-A") is not None
    assert _pm_row(tmp, "EJL/F-B") is None


# ── 15. corpus-style 44-code fixture ─────────────────────────────────────

def test_corpus_style_44_codes(fresh):
    """Mirrors the production audit: 44 distinct product_codes across 7
    batches. Backfill must produce exactly 44 product_master rows."""
    tmp = fresh
    pc_idx = 0
    for batch_n in range(1, 8):
        bid = f"B-CORPUS-{batch_n}"
        doc = _seed_doc(tmp, bid, file_hash=f"h{batch_n}")
        # Vary how many codes per batch — total exactly 44.
        codes_in_batch = {1: 1, 2: 1, 3: 1, 4: 1, 5: 8, 6: 11, 7: 21}[batch_n]
        for i in range(codes_in_batch):
            pc_idx += 1
            _seed_invoice_line(
                tmp, bid, doc,
                product_code=f"EJL/CORP-{pc_idx}",
                invoice_no=f"INV-{batch_n}",
                line_position=i + 1,
            )
    assert pc_idx == 44

    from app.services.product_master_backfill import backfill_from_invoice_lines
    summary = backfill_from_invoice_lines(tmp, dry_run=False)
    assert summary["scanned_codes"] == 44
    assert summary["inserted"]      == 44
    assert summary["errors"]        == []
    assert _pm_count(tmp) == 44


# ── 16. failure isolation — partial progress on per-row error ────────────

def test_failure_isolation_partial_progress(fresh, monkeypatch):
    tmp = fresh
    bid = "B-FAIL"
    doc = _seed_doc(tmp, bid)
    for i, pc in enumerate(
        ["EJL/F-1", "EJL/F-2", "EJL/F-BOOM", "EJL/F-4"], start=1
    ):
        _seed_invoice_line(tmp, bid, doc, product_code=pc,
                            line_position=i)

    from app.services import reservation_db as rdb

    real_upsert = rdb.upsert_product_master

    def _maybe_boom(db_path, *, product_code, **kw):
        if product_code == "EJL/F-BOOM":
            raise RuntimeError("simulated failure")
        return real_upsert(db_path, product_code=product_code, **kw)

    monkeypatch.setattr(rdb, "upsert_product_master", _maybe_boom)

    from app.services.product_master_backfill import backfill_from_invoice_lines
    summary = backfill_from_invoice_lines(tmp, dry_run=False)
    # 3 succeeded; 1 errored; job did not abort.
    assert summary["inserted"] == 3
    assert len(summary["errors"]) == 1
    assert "EJL/F-BOOM" in summary["errors"][0]
    assert _pm_count(tmp) == 3
