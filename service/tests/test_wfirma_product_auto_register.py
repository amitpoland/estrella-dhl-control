"""
test_wfirma_product_auto_register.py — pin batch auto-register contract.

Mirrors the AWB 6049349806 shape (9 invoice-line product_codes) and
exercises every branch of the per-code state machine without ever
calling the live wFirma API.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
from unittest.mock import patch, MagicMock

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


# ── Fixtures ────────────────────────────────────────────────────────────────

def _seed_invoice_lines(documents_db: Path, batch_id: str,
                        rows: List[Tuple[str, str, str]]) -> None:
    """rows = [(product_code, description, hsn_code), ...]"""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(documents_db)) as con:
        for i, (pc, desc, hsn) in enumerate(rows):
            con.execute(
                """INSERT INTO invoice_lines
                   (id, document_id, batch_id, invoice_no, line_position,
                    product_code, description, quantity, unit_price, total_value,
                    currency, hs_code, created_at, gross_weight, net_weight,
                    rate_usd, amount_usd, hsn_code)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), "doc-1", batch_id, "EJL/26-27/121",
                 i + 1, pc, desc, 1.0, 100.0, 100.0,
                 "USD", "", now, 0.0, 0.0,
                 100.0, 100.0, hsn),
            )


@pytest.fixture
def isolated_dbs(tmp_path, monkeypatch):
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(_s, "wfirma_create_product_allowed", False, raising=False)

    from app.services import wfirma_db as wfdb
    from app.services import document_db as ddb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _awb_6049349806_lines() -> List[Tuple[str, str, str]]:
    return [
        ("EJL/26-27/121-1", "PCS, 14KT Gold,Stud With Diam Jewel RING",       "71131913"),
        ("EJL/26-27/122-1", "PCS, 14KT Gold,LGD Gold Stud Jewell RING",       "71131914"),
        ("EJL/26-27/122-2", "PCS, 14KT Gold,Plain Jewellery RING",             "71131911"),
        ("EJL/26-27/123-1", "PCS, 14KT Gold,LGD Gold Stud Jewellery RING",     "71131914"),
        ("EJL/26-27/123-2", "PCS, 14KT Gold,Plain Jewellery PENDANT",          "71131911"),
        ("EJL/26-27/123-3", "PCS, SL925 SILVERPlain Jewellery PENDANT",        "71131141"),
        ("EJL/26-27/123-4", "PRS, SL925 SILVERLGD Silver Std Jewellery EARRINGS","71131144"),
        ("EJL/26-27/123-5", "PRS, SL925 SILVERLGD Gold Stud Jewellery EARRINGS","71131914"),
        ("EJL/26-27/124-1", "PCS, 14KT Gold,LGD Gold Stud Jewellery RING",     "71131914"),
    ]


# ── item_type derivation ────────────────────────────────────────────────────

class TestItemTypeDerivation:

    def test_ring(self):
        from app.services.wfirma_product_auto_register import _derive_item_type
        assert _derive_item_type("PCS, 14KT Gold,Stud With Diam Jewel RING") == "RING"

    def test_pendant(self):
        from app.services.wfirma_product_auto_register import _derive_item_type
        assert _derive_item_type("PCS, 14KT Gold,Plain Jewellery PENDANT") == "PENDANT"

    def test_earrings(self):
        from app.services.wfirma_product_auto_register import _derive_item_type
        assert _derive_item_type(
            "PRS, SL925 SILVERLGD Silver Std Jewellery EARRINGS"
        ) == "EARRINGS"

    def test_unknown_fallbacks_to_empty(self):
        from app.services.wfirma_product_auto_register import _derive_item_type
        assert _derive_item_type("some weird description") == ""


# ── Service unit tests ──────────────────────────────────────────────────────

class TestEnsureProductsForBatch:

    def test_dry_run_searches_only_no_create(self, isolated_dbs):
        bid = "B_DRY_RUN"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines())

        # All 9 codes missing in wFirma
        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=None) as p_get, \
             patch("app.services.wfirma_client.create_product") as p_create:
            r = svc.ensure_products_for_batch(bid, dry_run=True)

        assert r["dry_run"] is True
        assert r["scanned"] == 9
        assert r["missing"] == 9
        assert r["existing_mapped"] == 0
        assert r["created"] == 0
        assert r["blocked"] == 0
        # Searched 9 times, never created
        assert p_get.call_count == 9
        p_create.assert_not_called()

    def test_existing_mapped_mirrors_locally_skips_create(self, isolated_dbs, monkeypatch):
        bid = "B_EXISTING"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:3])  # 3 codes

        # All 3 already exist in wFirma
        existing_stub = MagicMock()
        existing_stub.wfirma_id = "WF-EXISTING-1"
        existing_stub.name      = "Pierścionek"
        existing_stub.unit      = "szt."

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub) as p_get, \
             patch("app.services.wfirma_client.create_product") as p_create:
            r = svc.ensure_products_for_batch(bid, dry_run=True)

        assert r["scanned"] == 3
        assert r["existing_mapped"] == 3
        assert r["missing"] == 0
        p_create.assert_not_called()

        # Local mirror written via wfdb
        from app.services import wfirma_db as wfdb
        for pc, _, _ in _awb_6049349806_lines()[:3]:
            row = wfdb.get_product(pc)
            assert row is not None, f"local mirror missing for {pc}"
            assert row["wfirma_product_id"] == "WF-EXISTING-1"
            assert row["sync_status"] == "matched"

    def test_missing_flag_off_returns_blocked(self, isolated_dbs, monkeypatch):
        bid = "B_FLAG_OFF"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:2])
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", False, raising=False)

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=None), \
             patch("app.services.wfirma_client.create_product") as p_create:
            r = svc.ensure_products_for_batch(bid, dry_run=False)

        assert r["scanned"] == 2
        assert r["blocked"] == 2
        assert r["created"] == 0
        p_create.assert_not_called()
        for res in r["results"]:
            assert res["status"] == "blocked"
            assert "wfirma_create_product_allowed is false" in res["error"]

    def test_missing_flag_on_calls_create_and_mirrors(self, isolated_dbs, monkeypatch):
        bid = "B_FLAG_ON"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:2])
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", True, raising=False)

        # Mock wFirma create returning fresh ids
        created_ids = iter(["WF-NEW-1", "WF-NEW-2"])
        def fake_create(**kwargs):
            stub = MagicMock()
            stub.wfirma_id = next(created_ids)
            stub.name      = kwargs.get("name", "")
            stub.code      = kwargs.get("product_code", "")
            stub.unit      = "szt."
            return stub

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=None), \
             patch("app.services.wfirma_client.create_product",
                   side_effect=fake_create) as p_create, \
             patch("app.services.wfirma_client.find_vat_code_id",
                   return_value="2"):
            r = svc.ensure_products_for_batch(bid, dry_run=False)

        assert r["scanned"] == 2
        assert r["created"] == 2
        assert r["blocked"] == 0
        assert p_create.call_count == 2

        from app.services import wfirma_db as wfdb
        for pc in ("EJL/26-27/121-1", "EJL/26-27/122-1"):
            row = wfdb.get_product(pc)
            assert row is not None
            assert row["wfirma_product_id"].startswith("WF-NEW-")
            assert row["sync_status"] == "matched"

    def test_create_failure_writes_no_local_mapping(self, isolated_dbs, monkeypatch):
        bid = "B_CREATE_FAIL"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", True, raising=False)

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=None), \
             patch("app.services.wfirma_client.create_product",
                   side_effect=RuntimeError("goods/add wFirma status=ERROR")), \
             patch("app.services.wfirma_client.find_vat_code_id",
                   return_value="2"):
            r = svc.ensure_products_for_batch(bid, dry_run=False)

        assert r["scanned"] == 1
        assert r["failed"] == 1
        assert r["created"] == 0
        # No local mirror written
        from app.services import wfirma_db as wfdb
        assert wfdb.get_product("EJL/26-27/121-1") is None

    def test_idempotent_second_run_after_create(self, isolated_dbs, monkeypatch):
        """Second invocation: search-first finds the now-mirrored code in
        wFirma → existing_mapped, never calls create again."""
        bid = "B_IDEMPOTENT"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", True, raising=False)

        from app.services import wfirma_product_auto_register as svc

        # First run: not found → create → mapped
        first_existing = [None]   # mutable closure flag
        def fake_get(pc):
            if first_existing[0] is None:
                return None
            stub = MagicMock()
            stub.wfirma_id = first_existing[0]
            stub.name      = "Created"
            stub.unit      = "szt."
            return stub
        def fake_create(**kw):
            first_existing[0] = "WF-IDEM-1"
            stub = MagicMock()
            stub.wfirma_id = "WF-IDEM-1"
            stub.name      = kw.get("name","")
            stub.code      = kw.get("product_code","")
            stub.unit      = "szt."
            return stub

        with patch("app.services.wfirma_client.get_product_by_code", side_effect=fake_get), \
             patch("app.services.wfirma_client.create_product", side_effect=fake_create) as p_create, \
             patch("app.services.wfirma_client.find_vat_code_id", return_value="2"):
            r1 = svc.ensure_products_for_batch(bid, dry_run=False)
            r2 = svc.ensure_products_for_batch(bid, dry_run=False)

        assert r1["created"] == 1
        assert r2["created"] == 0
        assert r2["existing_mapped"] == 1
        assert p_create.call_count == 1   # second run did NOT call create

    def test_duplicate_product_codes_scanned_once(self, isolated_dbs):
        """When invoice_lines has 2 rows with the same product_code,
        the bridge dedupes — scanned counts unique codes only."""
        bid = "B_DUPES"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid, [
            ("EJL/26-27/123-5", "PRS, SILVER LGD EARRINGS", "71131914"),
            ("EJL/26-27/123-5", "PRS, SILVER LGD EARRINGS", "71131914"),
            ("EJL/26-27/123-5", "PRS, SILVER LGD EARRINGS", "71131914"),
        ])

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=None) as p_get:
            r = svc.ensure_products_for_batch(bid, dry_run=True)

        assert r["scanned"] == 1
        assert p_get.call_count == 1   # one search, not three
        assert r["missing"] == 1


# ── Endpoint integration tests ──────────────────────────────────────────────

@pytest.fixture
def client(isolated_dbs):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestEndpoints:

    def test_preview_is_read_only(self, isolated_dbs, client, monkeypatch):
        bid = "B_PREVIEW_RO"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:3])
        from app.core.config import settings as _s
        # Even with create flag on, the preview must NOT call create
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", True, raising=False)

        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=None), \
             patch("app.services.wfirma_client.create_product") as p_create:
            r = client.post(
                f"/api/v1/wfirma/goods/auto-register-preview/{bid}",
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is True
        assert body["scanned"] == 3
        assert body["missing"] == 3
        p_create.assert_not_called()

    def test_write_endpoint_honors_flag_off(self, isolated_dbs, client, monkeypatch):
        bid = "B_WRITE_FLAG_OFF"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:2])
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", False, raising=False)

        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=None), \
             patch("app.services.wfirma_client.create_product") as p_create:
            r = client.post(
                f"/api/v1/wfirma/goods/auto-register/{bid}",
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is False
        assert body["blocked"] == 2
        assert body["created"] == 0
        p_create.assert_not_called()

    def test_write_endpoint_honors_flag_on(self, isolated_dbs, client, monkeypatch):
        bid = "B_WRITE_FLAG_ON"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", True, raising=False)

        stub = MagicMock()
        stub.wfirma_id = "WF-WRITE-1"
        stub.name      = "Pierścionek"
        stub.code      = "EJL/26-27/121-1"
        stub.unit      = "szt."
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=None), \
             patch("app.services.wfirma_client.create_product",
                   return_value=stub) as p_create, \
             patch("app.services.wfirma_client.find_vat_code_id",
                   return_value="2"):
            r = client.post(
                f"/api/v1/wfirma/goods/auto-register/{bid}",
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1
        assert p_create.call_count == 1

    def test_invalid_batch_id_400(self, client):
        r = client.post(
            "/api/v1/wfirma/goods/auto-register-preview/has..dotdot",
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 400, r.text


# ──────────────────────────────────────────────────────────────────────────
# Reservation-queue mirror — wfirma_product_mapping consistency
# ──────────────────────────────────────────────────────────────────────────

def _seed_reservation_queue_db(tmp_path):
    """Create the wfirma_product_mapping table in reservation_queue.db so
    the mirror call has a target. Mirrors the live schema."""
    p = tmp_path / "reservation_queue.db"
    with sqlite3.connect(str(p)) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS wfirma_product_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_code TEXT NOT NULL UNIQUE,
                wfirma_product_id TEXT NOT NULL DEFAULT '',
                wfirma_code TEXT NOT NULL DEFAULT '',
                wfirma_name TEXT NOT NULL DEFAULT '',
                warehouse_id TEXT NOT NULL DEFAULT '',
                sync_status TEXT NOT NULL DEFAULT 'pending',
                last_checked_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
    return p


class TestReservationMappingMirror:

    def test_existing_mapped_writes_reservation_mapping(self, isolated_dbs):
        bid = "B_MIRROR_EXISTING"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:2])
        _seed_reservation_queue_db(isolated_dbs)

        existing_stub = MagicMock()
        existing_stub.wfirma_id = "WF-EX-9"
        existing_stub.name      = "Pierścionek"
        existing_stub.unit      = "szt."
        existing_stub.code      = ""

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub):
            r = svc.ensure_products_for_batch(bid, dry_run=True)

        assert r["existing_mapped"] == 2
        # Verify mirror rows landed in reservation_queue.wfirma_product_mapping
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT product_code, wfirma_product_id, sync_status "
                "FROM wfirma_product_mapping ORDER BY product_code"
            ).fetchall()
        assert len(rows) == 2
        for row in rows:
            assert row["wfirma_product_id"] == "WF-EX-9"
            assert row["sync_status"] == "matched"
        # Per-code result has no warnings
        for res in r["results"]:
            assert res["warnings"] == []

    def test_created_writes_reservation_mapping(self, isolated_dbs, monkeypatch):
        bid = "B_MIRROR_CREATED"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        _seed_reservation_queue_db(isolated_dbs)
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", True, raising=False)

        stub = MagicMock()
        stub.wfirma_id = "WF-CREATED-1"
        stub.name      = "Created Ring"
        stub.code      = "EJL/26-27/121-1"
        stub.unit      = "szt."

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code", return_value=None), \
             patch("app.services.wfirma_client.create_product", return_value=stub), \
             patch("app.services.wfirma_client.find_vat_code_id", return_value="2"):
            r = svc.ensure_products_for_batch(bid, dry_run=False)

        assert r["created"] == 1
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM wfirma_product_mapping"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["product_code"]      == "EJL/26-27/121-1"
        assert rows[0]["wfirma_product_id"] == "WF-CREATED-1"
        assert rows[0]["sync_status"]       == "matched"
        assert rows[0]["wfirma_name"]       == "Created Ring"

    def test_blocked_does_not_write_mapping(self, isolated_dbs, monkeypatch):
        bid = "B_MIRROR_BLOCKED"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        _seed_reservation_queue_db(isolated_dbs)
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", False, raising=False)

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code", return_value=None), \
             patch("app.services.wfirma_client.create_product"):
            svc.ensure_products_for_batch(bid, dry_run=False)

        # NO mapping rows written — blocked must not fake a mirror
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute("SELECT COUNT(*) FROM wfirma_product_mapping").fetchone()[0]
        assert n == 0

    def test_failed_does_not_write_mapping(self, isolated_dbs, monkeypatch):
        bid = "B_MIRROR_FAILED"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        _seed_reservation_queue_db(isolated_dbs)
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_product_allowed", True, raising=False)

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code", return_value=None), \
             patch("app.services.wfirma_client.create_product",
                   side_effect=RuntimeError("goods/add ERROR")), \
             patch("app.services.wfirma_client.find_vat_code_id", return_value="2"):
            svc.ensure_products_for_batch(bid, dry_run=False)

        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute("SELECT COUNT(*) FROM wfirma_product_mapping").fetchone()[0]
        assert n == 0

    def test_missing_dryrun_does_not_write_mapping(self, isolated_dbs):
        bid = "B_MIRROR_MISSING"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        _seed_reservation_queue_db(isolated_dbs)

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code", return_value=None):
            svc.ensure_products_for_batch(bid, dry_run=True)

        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute("SELECT COUNT(*) FROM wfirma_product_mapping").fetchone()[0]
        assert n == 0

    def test_idempotent_second_run_updates_same_row(self, isolated_dbs):
        bid = "B_MIRROR_IDEMPOTENT"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        _seed_reservation_queue_db(isolated_dbs)

        existing_stub = MagicMock()
        existing_stub.wfirma_id = "WF-IDEM-77"
        existing_stub.name      = "Initial Name"
        existing_stub.code      = ""
        existing_stub.unit      = "szt."

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub):
            r1 = svc.ensure_products_for_batch(bid, dry_run=True)
        # Second run with refreshed name
        existing_stub.name = "Updated Name"
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub):
            r2 = svc.ensure_products_for_batch(bid, dry_run=True)

        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            rows = con.execute(
                "SELECT product_code, wfirma_product_id, wfirma_name "
                "FROM wfirma_product_mapping"
            ).fetchall()
        # Single row, updated to the latest name
        assert len(rows) == 1
        assert rows[0][2] == "Updated Name"

    def test_mirror_failure_does_not_flip_status_records_warning(self, isolated_dbs):
        """If reservation_queue.db is missing, the product result must
        remain `existing_mapped` (wFirma + local mirror succeeded) but
        the per-code result.warnings must record the mirror failure."""
        bid = "B_MIRROR_NO_DB"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        # Deliberately do NOT create reservation_queue.db
        assert not (isolated_dbs / "reservation_queue.db").exists()

        existing_stub = MagicMock()
        existing_stub.wfirma_id = "WF-NO-RDB"
        existing_stub.name      = "Anything"
        existing_stub.code      = ""
        existing_stub.unit      = "szt."

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub):
            r = svc.ensure_products_for_batch(bid, dry_run=True)

        # Status still successful — wFirma side + local mirror both ok
        assert r["existing_mapped"] == 1
        assert r["failed"] == 0
        # Warning recorded on the per-code result
        warnings = r["results"][0]["warnings"]
        assert warnings, "expected a warning when reservation_queue.db absent"
        assert "reservation_queue.db not found" in warnings[0] or \
               "reservation_mapping mirror failed" in warnings[0]
