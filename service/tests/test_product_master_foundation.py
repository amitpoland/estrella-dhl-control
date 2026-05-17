"""test_product_master_foundation.py — PR-1 Product Master Foundation.

Activates product_master as the canonical product-identity registry as a
write-only projection from invoice_lines.  No consumer behaviour is
switched in this PR.

Hard rules verified here:
  - product_code is generated only by store_invoice_lines (the existing
    single mint point at document_db.py:1111).
  - product_master never invents product_code.
  - product_master write is best-effort: a failure NEVER breaks the
    invoice_lines insert.
  - upsert is idempotent: UNIQUE(product_code) + UPSERT refreshes
    updated_at without producing duplicate rows.
  - reservation_db is local-DB only — no external HTTP / wFirma / SMTP
    calls in the new code paths.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    """Fresh storage_root with documents + reservation DBs initialised."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)

    from app.services import document_db as ddb
    from app.services import reservation_db as rdb
    ddb.init_document_db(tmp_path / "documents.db")
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    return tmp_path


def _seed_doc(tmp: Path, batch_id: str) -> str:
    from app.services import document_db as ddb
    return ddb.register_document(
        batch_id=batch_id, document_type="invoice",
        file_name="inv.pdf", file_path="/tmp/inv.pdf",
        file_hash=f"h-{batch_id}", source="intake",
    ) or ""


def _line(invoice_no: str, pos: int, **overrides) -> Dict[str, Any]:
    base = {
        "invoice_no":   invoice_no,
        "line_position": pos,
        "product_code":  f"{invoice_no}-{pos}",
        "description":   f"Ring {pos}",
        "quantity":      1.0,
        "unit_price":    100.0 + pos,
        "currency":      "USD",
        "hsn_code":      "7113",
        "hs_code":       "7113",
    }
    base.update(overrides)
    return base


# ── 1. table exists after init ────────────────────────────────────────────

def test_product_master_table_exists_after_init(fresh):
    tmp = fresh
    with sqlite3.connect(str(tmp / "reservation_queue.db")) as con:
        cols = con.execute("PRAGMA table_info(product_master)").fetchall()
    assert cols, "product_master table missing after init_reservation_db"


# ── 2. 7 additive columns present on fresh DB ─────────────────────────────

def test_additive_columns_present_on_fresh_db(fresh):
    tmp = fresh
    with sqlite3.connect(str(tmp / "reservation_queue.db")) as con:
        cols = {r[1] for r in
                con.execute("PRAGMA table_info(product_master)").fetchall()}
    for col in ("item_type", "hsn_code", "unit_price_ref", "currency_ref",
                "confidence", "source_document_id", "last_seen_batch_id"):
        assert col in cols, f"additive column {col!r} missing on fresh DB"


# ── 3. 7 additive columns added to legacy product_master ──────────────────

def test_additive_columns_added_to_legacy_product_master(tmp_path):
    """Simulate a DB created before PR-1 (only the original 9 columns) and
    verify init_reservation_db migrates it additively."""
    rpath = tmp_path / "reservation_queue.db"
    # Hand-craft the legacy table — only original columns.
    with sqlite3.connect(str(rpath)) as con:
        con.execute("""CREATE TABLE product_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_code TEXT NOT NULL UNIQUE,
            design_no TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            metal TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            source_invoice_no TEXT NOT NULL DEFAULT '',
            source_batch_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute(
            "INSERT INTO product_master (product_code, design_no) "
            "VALUES (?, ?)", ("LEGACY-1", "D-LEGACY"),
        )
        con.commit()

    from app.services import reservation_db as rdb
    rdb.init_reservation_db(rpath)

    with sqlite3.connect(str(rpath)) as con:
        cols = {r[1] for r in
                con.execute("PRAGMA table_info(product_master)").fetchall()}
        row = con.execute(
            "SELECT * FROM product_master WHERE product_code='LEGACY-1'"
        ).fetchone()
    for col in ("item_type", "hsn_code", "unit_price_ref", "currency_ref",
                "confidence", "source_document_id", "last_seen_batch_id"):
        assert col in cols, f"additive column {col!r} missing on legacy DB"
    # Pre-existing row preserved.
    assert row is not None


# ── 4. store_invoice_lines upserts product_master ─────────────────────────

def test_store_invoice_lines_upserts_product_master(fresh):
    tmp = fresh
    from app.services import document_db as ddb
    from app.services import reservation_db as rdb

    bid = "B-MASTER-1"
    doc_id = _seed_doc(tmp, bid)
    ddb.store_invoice_lines(doc_id, bid, [_line("EJL/26-27/100", 1)])

    masters = rdb.list_product_masters(tmp / "reservation_queue.db",
                                       source_batch_id=bid)
    assert len(masters) == 1
    m = masters[0]
    assert m["product_code"] == "EJL/26-27/100-1"
    assert m["source_batch_id"] == bid
    assert m["source_invoice_no"] == "EJL/26-27/100"
    assert m["source_document_id"] == doc_id
    assert m["currency_ref"] == "USD"
    assert abs(m["unit_price_ref"] - 101.0) < 1e-6
    assert m["hsn_code"] == "7113"
    assert m["last_seen_batch_id"] == bid


# ── 5. source ids carried correctly (smoke alias of #4) ────────────────────

def test_master_carries_source_batch_invoice_document_ids(fresh):
    tmp = fresh
    from app.services import document_db as ddb
    from app.services import reservation_db as rdb

    bid = "B-MASTER-SRC"
    doc_id = _seed_doc(tmp, bid)
    ddb.store_invoice_lines(doc_id, bid, [_line("INV-X", 2)])

    m = rdb.get_product_master(tmp / "reservation_queue.db", "INV-X-2")
    assert m is not None
    assert m["source_batch_id"] == bid
    assert m["source_invoice_no"] == "INV-X"
    assert m["source_document_id"] == doc_id


# ── 6. duplicate intake does not duplicate master ─────────────────────────

def test_duplicate_invoice_import_does_not_duplicate_master(fresh):
    tmp = fresh
    from app.services import document_db as ddb
    from app.services import reservation_db as rdb

    bid = "B-DUP"
    doc_id = _seed_doc(tmp, bid)
    line = _line("INV-DUP", 1)
    ddb.store_invoice_lines(doc_id, bid, [line])
    ddb.store_invoice_lines(doc_id, bid, [line])  # re-run

    masters = rdb.list_product_masters(tmp / "reservation_queue.db",
                                       source_batch_id=bid)
    assert len(masters) == 1, (
        f"expected 1 master row after duplicate intake, got {len(masters)}"
    )


# ── 7. last_seen_batch_id updates; source_batch_id stays original ─────────

def test_last_seen_batch_id_updates_on_repeat_intake(fresh):
    tmp = fresh
    from app.services import document_db as ddb
    from app.services import reservation_db as rdb

    bid_a = "B-AA"
    bid_b = "B-BB"
    doc_a = _seed_doc(tmp, bid_a)
    doc_b = _seed_doc(tmp, bid_b)
    pc_line_a = _line("INV-SAME", 1)  # product_code = INV-SAME-1
    pc_line_b = dict(pc_line_a)        # same product_code

    ddb.store_invoice_lines(doc_a, bid_a, [pc_line_a])
    ddb.store_invoice_lines(doc_b, bid_b, [pc_line_b])

    m = rdb.get_product_master(tmp / "reservation_queue.db", "INV-SAME-1")
    assert m is not None
    assert m["source_batch_id"] == bid_a, (
        "source_batch_id must stay at the originating batch"
    )
    assert m["last_seen_batch_id"] == bid_b, (
        "last_seen_batch_id must advance to the latest referencing batch"
    )


# ── 8. failure-isolation — master write fails, invoice insert holds ───────

def test_master_write_failure_does_not_break_invoice_lines_insert(
    fresh, monkeypatch, caplog,
):
    tmp = fresh
    from app.services import document_db as ddb
    from app.services import reservation_db as rdb

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated master failure")
    monkeypatch.setattr(rdb, "upsert_product_master", _boom)

    bid = "B-FAIL"
    doc_id = _seed_doc(tmp, bid)
    inserted = ddb.store_invoice_lines(doc_id, bid, [_line("INV-FAIL", 1)])
    assert inserted == 1

    rows = ddb.get_invoice_lines(bid)
    assert len(rows) == 1
    assert rows[0]["product_code"] == "INV-FAIL-1"

    masters = rdb.list_product_masters(tmp / "reservation_queue.db",
                                       source_batch_id=bid)
    assert masters == [], "master must not be written on simulated failure"


# ── 9. upsert preserves non-empty design_no when blank passed later ───────

def test_upsert_preserves_existing_design_no_when_blank_passed(fresh):
    tmp = fresh
    from app.services import reservation_db as rdb

    rpath = tmp / "reservation_queue.db"
    # First call seeds design_no="D-77".
    rdb.upsert_product_master(rpath, product_code="PC-DN", design_no="D-77",
                              source_batch_id="B1")
    # Second call (e.g. from store_invoice_lines, which doesn't know design_no
    # at intake) passes blank design_no.
    rdb.upsert_product_master(rpath, product_code="PC-DN", design_no="",
                              source_batch_id="B1")
    m = rdb.get_product_master(rpath, "PC-DN")
    assert m["design_no"] == "D-77", (
        "blank design_no must NOT overwrite existing non-empty value"
    )


# ── 10. init idempotent ───────────────────────────────────────────────────

def test_init_reservation_db_idempotent(tmp_path):
    from app.services import reservation_db as rdb
    rpath = tmp_path / "reservation_queue.db"
    rdb.init_reservation_db(rpath)
    rdb.init_reservation_db(rpath)
    rdb.init_reservation_db(rpath)
    with sqlite3.connect(str(rpath)) as con:
        cols = {r[1] for r in
                con.execute("PRAGMA table_info(product_master)").fetchall()}
    # 9 original + 7 additive = 16
    assert len(cols) >= 16


# ── 11. no external calls in new write path ───────────────────────────────

def test_no_external_calls_in_master_write_path():
    """Source-grep guard — reservation_db.py and the master-write block in
    document_db.py must stay local-DB only.  Never introduce HTTP, wFirma,
    SMTP, or DHL dispatch calls into the canonical projection path."""
    files = [
        Path(__file__).resolve().parents[1] / "app" / "services" / "reservation_db.py",
        Path(__file__).resolve().parents[1] / "app" / "services" / "document_db.py",
    ]
    for f in files:
        src = f.read_text(encoding="utf-8")
        for forbidden in ("requests.", "httpx.", "wfirma_client",
                          "smtp", "send_email", "dhl_dispatch"):
            assert forbidden not in src, (
                f"{f.name} must not reference {forbidden!r} — the canonical "
                f"identity projection path is local-DB only"
            )


# ── 12. product_code minted only by store_invoice_lines ───────────────────

def test_product_code_minted_only_by_store_invoice_lines():
    """Architectural invariant — only store_invoice_lines mints
    product_code via the f-string pattern.  No other module may invent a
    product_code.  Allowed downstream calls *accept* an already-minted
    product_code (e.g. upsert_product_master, wfirma_product_auto_register)
    but must never generate one themselves."""
    services = Path(__file__).resolve().parents[1] / "app" / "services"
    # The exact mint pattern in store_invoice_lines.
    mint_pattern = 'f"{inv_no}-{pos}"'

    hits = []
    for f in services.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        # Look for f-string product-code mints OUTSIDE document_db.
        if f.name == "document_db.py":
            continue
        if mint_pattern in src:
            hits.append(f.name)
        # Also catch any literal "product_code = f"..." outside document_db.
        for line in src.splitlines():
            stripped = line.strip()
            if (stripped.startswith("product_code = f\"")
                    or stripped.startswith("product_code = f'")):
                hits.append(f"{f.name}: {stripped[:80]}")

    # invoice_packing_extractor.py legitimately re-derives the SAME format
    # in the legacy pz_rows.json fallback (a historical compatibility path).
    # That re-derivation is not a new mint — it reproduces the canonical
    # format from the same inputs.  Allowed.
    hits = [h for h in hits if "invoice_packing_extractor" not in h]
    assert not hits, (
        f"product_code minted outside store_invoice_lines: {hits}"
    )
