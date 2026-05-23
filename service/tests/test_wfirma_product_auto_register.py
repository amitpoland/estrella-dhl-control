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

    def test_existing_wfirma_returns_pending_adoption_not_matched(
        self, isolated_dbs, monkeypatch
    ):
        """PR 3 of 4 refit (2026-05-23): when wFirma has a product for a
        queried product_code, the per-code result MUST be
        ``pending_adoption`` and the local row MUST be
        ``sync_status='pending_adoption'`` — NOT ``existing_mapped`` /
        ``'matched'``. This blocks PZ + Proforma until the operator
        chooses /adopt or /update-and-adopt."""
        bid = "B_EXISTING_PENDING"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:3])  # 3 codes

        existing_stub = MagicMock()
        existing_stub.wfirma_id = "WF-EXISTING-1"
        existing_stub.name      = "Pierścionek"
        existing_stub.unit      = "szt."
        existing_stub.code      = ""

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub) as p_get, \
             patch("app.services.wfirma_client.create_product") as p_create:
            r = svc.ensure_products_for_batch(bid, dry_run=True)

        assert r["scanned"] == 3
        assert r["pending_adoption"] == 3, (
            f"expected pending_adoption=3, got result: {r}"
        )
        assert r["existing_mapped"] == 0, (
            "must NOT silently auto-adopt as matched — refit pre-condition"
        )
        assert r["missing"] == 0
        # The per-code status field must be 'pending_adoption' too
        for res in r["results"]:
            assert res["status"] == "pending_adoption", res
            assert res["wfirma_product_id"] == "WF-EXISTING-1"
            assert res["wfirma_name"] == "Pierścionek"
            assert res["wfirma_unit"] == "szt."
        p_create.assert_not_called()

        # Local mirror written with the pending state
        from app.services import wfirma_db as wfdb
        for pc, _, _ in _awb_6049349806_lines()[:3]:
            row = wfdb.get_product(pc)
            assert row is not None, f"local mirror missing for {pc}"
            assert row["wfirma_product_id"] == "WF-EXISTING-1"
            assert row["sync_status"] == "pending_adoption", (
                f"sync_status must be 'pending_adoption' (not 'matched'), "
                f"got {row['sync_status']!r}"
            )

    def test_existing_wfirma_never_calls_edit_product(self, isolated_dbs):
        """Operator-required: when wFirma already has the product_code,
        the auto-register MUST NOT call edit_product. Updates only happen
        through the explicit POST /goods/update-and-adopt endpoint."""
        bid = "B_NO_EDIT"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:2])

        existing_stub = MagicMock()
        existing_stub.wfirma_id = "WF-NO-EDIT-1"
        existing_stub.name      = "Old Name"
        existing_stub.unit      = "szt."
        existing_stub.code      = ""

        from app.services import wfirma_product_auto_register as svc
        # The whole module is patched: even if a regression accidentally
        # adds an edit_product call, this assertion catches it.
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub), \
             patch("app.services.wfirma_client.create_product") as p_create, \
             patch("app.services.wfirma_client.edit_product") as p_edit:
            r = svc.ensure_products_for_batch(bid, dry_run=True)

        assert r["pending_adoption"] == 2
        p_create.assert_not_called()
        p_edit.assert_not_called()

    def test_pending_adoption_blocks_pz_and_proforma_gates(self, isolated_dbs):
        """Operator-required: a product in 'pending_adoption' state MUST
        keep PZ and Proforma blocked. The gates in routes_proforma and
        routes_wfirma check ``sync_status == 'matched'`` exclusively, so
        any other sync_status (including 'pending_adoption') correctly
        fails the gate. This test pins the gate contract via wfdb +
        source-grep — behavioral guarantee that the refit does not
        accidentally re-enable downstream advance."""
        bid = "B_PENDING_GATES"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        existing_stub = MagicMock()
        existing_stub.wfirma_id = "WF-PENDING-GATE-1"
        existing_stub.name      = "Pierścionek"
        existing_stub.unit      = "szt."
        existing_stub.code      = ""

        from app.services import wfirma_product_auto_register as svc
        from app.services import wfirma_db as wfdb
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub):
            r = svc.ensure_products_for_batch(bid, dry_run=True)

        assert r["pending_adoption"] == 1

        # Behavioral: the row sits in 'pending_adoption' — gates will
        # reject it because their condition is sync_status == 'matched'.
        row = wfdb.get_product("EJL/26-27/121-1")
        assert row["sync_status"] == "pending_adoption"
        assert row["sync_status"] != "matched"

        # Source-grep guard: ensure the PZ + Proforma gates still use
        # the exact 'matched' literal — pins the contract that any new
        # sync_status value (including pending_adoption) blocks
        # downstream advance.
        from pathlib import Path
        proforma = (Path(__file__).parents[1] /
                    "app" / "api" / "routes_proforma.py").read_text(
            encoding="utf-8", errors="ignore"
        )
        wfirma_routes = (Path(__file__).parents[1] /
                         "app" / "api" / "routes_wfirma.py").read_text(
            encoding="utf-8", errors="ignore"
        )
        # PZ-side gate: routes_wfirma.py contains the canonical
        # `prod.get("sync_status") == "matched"` literal (line ~140 +
        # ~750). Both substrings must be present.
        assert "sync_status" in wfirma_routes, (
            "routes_wfirma.py must reference sync_status for the gate"
        )
        assert '"matched"' in wfirma_routes, (
            "routes_wfirma.py must reference the 'matched' literal "
            "as the gate threshold"
        )
        # Proforma side: the same 'matched' literal is the gate.
        assert "sync_status" in proforma, (
            "routes_proforma.py must reference sync_status"
        )
        assert "'matched'" in proforma or '"matched"' in proforma, (
            "routes_proforma.py must still gate on 'matched'"
        )

    def test_pending_adoption_fast_path_skips_wfirma_round_trip(
        self, isolated_dbs
    ):
        """A product already in 'pending_adoption' (from a prior run)
        MUST short-circuit without re-querying wFirma — the comparison
        surface lives at GET /goods/search-and-compare for the operator
        UI to consult on demand."""
        bid = "B_PENDING_FAST_PATH"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid,
                            _awb_6049349806_lines()[:1])
        existing_stub = MagicMock()
        existing_stub.wfirma_id = "WF-FAST-1"
        existing_stub.name      = "Initial"
        existing_stub.unit      = "szt."
        existing_stub.code      = ""

        from app.services import wfirma_product_auto_register as svc

        # First run: hit wFirma → pending_adoption row written.
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub) as p_first:
            r1 = svc.ensure_products_for_batch(bid, dry_run=True)
        assert r1["pending_adoption"] == 1
        assert p_first.call_count == 1

        # Second run: fast path fires — wFirma must NOT be called again.
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub) as p_second:
            r2 = svc.ensure_products_for_batch(bid, dry_run=True)
        assert r2["pending_adoption"] == 1
        assert p_second.call_count == 0, (
            "pending_adoption fast path must skip wFirma round-trip"
        )

    def test_pending_adoption_real_shape_ejl_178_jr08007(self, isolated_dbs):
        """Lesson A real-shape regression: the operator-cited example
        product_code 'EJL/26-27/178-1' with design_code 'JR08007' must
        flow through the pending_adoption path correctly. design_code
        appears only as part of the invoice description (metadata); the
        wFirma lookup key is product_code only."""
        bid = "B_LESSON_A"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid, [
            ("EJL/26-27/178-1",
             "PCS, 14KT Gold,Stud With Diam Jewel RING JR08007", "71131913"),
        ])
        existing_stub = MagicMock()
        existing_stub.wfirma_id = "WF-178-1"
        existing_stub.name      = "Pierścionek z brylantami"
        existing_stub.unit      = "szt."
        existing_stub.code      = "EJL/26-27/178-1"

        from app.services import wfirma_product_auto_register as svc
        with patch("app.services.wfirma_client.get_product_by_code",
                   return_value=existing_stub) as p_get:
            r = svc.ensure_products_for_batch(bid, dry_run=True)

        assert r["pending_adoption"] == 1
        # The search key must be the product_code, NOT the design_code.
        p_get.assert_called_once_with("EJL/26-27/178-1")
        # The local row sits in pending state for operator decision.
        from app.services import wfirma_db as wfdb
        row = wfdb.get_product("EJL/26-27/178-1")
        assert row["wfirma_product_id"] == "WF-178-1"
        assert row["sync_status"] == "pending_adoption"

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

    def test_pending_adoption_does_NOT_write_reservation_mapping(
        self, isolated_dbs
    ):
        """PR 3 of 4 refit (2026-05-23): when wFirma already has the
        product, the row is 'pending_adoption' — no reservation can
        legitimately advance against a pending row. The reservation_queue
        mirror MUST therefore NOT be written. (When the operator later
        invokes /goods/adopt or /goods/update-and-adopt, those endpoints
        write to wfirma_products as 'matched'; the reservation chain
        picks up via the existing PZ flow at that point.)"""
        bid = "B_NO_RES_MIRROR_PENDING"
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

        assert r["pending_adoption"] == 2
        assert r["existing_mapped"] == 0
        # Reservation queue mirror MUST be empty — no row should be
        # written for a pending_adoption product. This is the inversion
        # of the pre-refit contract.
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute(
                "SELECT COUNT(*) FROM wfirma_product_mapping"
            ).fetchone()[0]
        assert n == 0, (
            "pending_adoption MUST NOT write to reservation_queue — "
            "would create a false reservation surface"
        )
        # No warnings expected — there is no mirror call to potentially fail
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

    def test_idempotent_second_run_preserves_pending_row(self, isolated_dbs):
        """PR 3 of 4 refit (2026-05-23): second dry_run on a
        pending_adoption product fires the new 'pending_adoption'
        fast path, skips the wFirma API round-trip, and does NOT
        write to reservation_queue.

        The idempotency contract is: still exactly 1 wfirma_products
        row in pending_adoption state, same wfirma_product_id, and
        zero reservation_queue rows (operator still has not chosen)."""
        bid = "B_MIRROR_IDEMPOTENT_PENDING"
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
        assert r1["pending_adoption"] == 1

        # Second dry_run: pending_adoption fast path fires — wFirma not called.
        fetch_calls: list = []
        def counting_fetch(code):
            fetch_calls.append(code)
            return existing_stub
        with patch("app.services.wfirma_client.get_product_by_code",
                   side_effect=counting_fetch):
            r2 = svc.ensure_products_for_batch(bid, dry_run=True)

        assert len(fetch_calls) == 0, (
            "dry_run pending_adoption fast path must skip wFirma round-trip"
        )
        assert r2["pending_adoption"] == 1

        # wfirma_products: still exactly 1 row, still pending
        from app.services import wfirma_db as wfdb
        row = wfdb.get_product("EJL/26-27/121-1")
        assert row is not None
        assert row["wfirma_product_id"] == "WF-IDEM-77"
        assert row["sync_status"] == "pending_adoption"

        # reservation_queue: still empty (no operator decision yet)
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute(
                "SELECT COUNT(*) FROM wfirma_product_mapping"
            ).fetchone()[0]
        assert n == 0, (
            "reservation_queue must stay empty until operator adopts/updates"
        )

    def test_pending_adoption_does_not_attempt_reservation_mirror(
        self, isolated_dbs
    ):
        """PR 3 of 4 refit (2026-05-23): the wFirma-hit branch no longer
        attempts a reservation_queue mirror at all (the prior contract
        was: mirror failure → warning; the new contract is: no mirror
        call → no warning, no failure mode). Even when reservation_queue
        is intentionally absent, the pending_adoption path must complete
        cleanly without warnings."""
        bid = "B_NO_MIRROR_CALL"
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

        # Pending state — wFirma + local mirror both ok
        assert r["pending_adoption"] == 1
        assert r["existing_mapped"] == 0
        assert r["failed"] == 0
        # No warnings — the refit removed the reservation mirror call
        # entirely for pending_adoption, so there is no mirror failure
        # mode to surface.
        assert r["results"][0]["warnings"] == [], (
            f"pending_adoption must produce no warnings; got: "
            f"{r['results'][0]['warnings']}"
        )
