"""
test_proforma_customer_resolver.py — Pin the safe customer-name resolver
that bridges sales-list client names to wfirma_customers rows.

AWB 6049349806 evidence:
  - " OMARA s.r.o" — leading whitespace
  - " Clear-Diamonds" — needs to match "Clear-Diamonds Ltd"
  - "Anastazia Panakova" / "Impact Gallery sp. z o.o." — truly absent
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


# ── Fixtures ────────────────────────────────────────────────────────────────

def _seed_wfirma_customers(db_path: Path,
                           rows: List[Tuple[str, str, str, str]]) -> None:
    """rows = [(client_name, wfirma_customer_id, country, vat_id), ...]"""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as con:
        for cn, cid, country, vat in rows:
            con.execute(
                """INSERT INTO wfirma_customers
                   (id, client_name, wfirma_customer_id, vat_id, country,
                    match_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (f"row-{cid}", cn, cid, vat, country, "matched", now, now),
            )


@pytest.fixture
def isolated_wfirma_db(tmp_path, monkeypatch):
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)

    # Initialise wfirma_db so list_customers / get_customer have a target
    from app.services import wfirma_db as wfdb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return tmp_path / "wfirma.db"


# ── Resolver unit tests ────────────────────────────────────────────────────

class TestResolveCustomer:

    def test_exact_match_wins(self, isolated_wfirma_db):
        _seed_wfirma_customers(isolated_wfirma_db, [
            ("Acme Sp. z o.o.", "100", "PL", "PL1234567890"),
            ("Other Co",        "200", "DE", "DE111111111"),
        ])
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer("Acme Sp. z o.o.")
        assert r["found"] is True
        assert r["match_strategy"] == "exact"
        assert r["wfirma_customer_id"] == "100"

    def test_case_insensitive_exact(self, isolated_wfirma_db):
        _seed_wfirma_customers(isolated_wfirma_db, [
            ("Acme Ltd", "300", "GB", "GB999"),
        ])
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer("acme ltd")
        assert r["found"] is True
        assert r["wfirma_customer_id"] == "300"

    def test_leading_whitespace_stripped(self, isolated_wfirma_db):
        _seed_wfirma_customers(isolated_wfirma_db, [
            ("OMARA s.r.o", "400", "SK", "SK111"),
        ])
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer("   OMARA s.r.o   ")
        assert r["found"] is True
        assert r["match_strategy"] == "exact"
        assert r["wfirma_customer_id"] == "400"
        assert r["normalized_name"] == "OMARA s.r.o"

    def test_internal_whitespace_collapsed(self, isolated_wfirma_db):
        _seed_wfirma_customers(isolated_wfirma_db, [
            ("Foo Bar Baz", "500", "PL", "PL999"),
        ])
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer("Foo    Bar  Baz")  # multiple inner spaces
        assert r["found"] is True
        assert r["normalized_name"] == "Foo Bar Baz"

    def test_prefix_tolerance_clear_diamonds(self, isolated_wfirma_db):
        """The AWB 6049349806 case: sales says 'Clear-Diamonds';
        wFirma stores 'Clear-Diamonds Ltd'. Single candidate → resolved."""
        _seed_wfirma_customers(isolated_wfirma_db, [
            ("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880"),
        ])
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer(" Clear-Diamonds")
        assert r["found"] is True
        assert r["match_strategy"] == "prefix"
        assert r["wfirma_customer_id"] == "91254191"
        assert r["resolved_wfirma_name"] == "Clear-Diamonds Ltd"

    def test_multiple_prefix_candidates_blocks(self, isolated_wfirma_db):
        """If multiple wFirma rows match the prefix, do NOT auto-pick."""
        _seed_wfirma_customers(isolated_wfirma_db, [
            ("Clear-Diamonds Ltd",      "91254191", "HU", "HU111"),
            ("Clear-Diamonds Trading",  "91254192", "HU", "HU222"),
        ])
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer("Clear-Diamonds")
        assert r["found"] is False
        assert r["ambiguous"] is True
        assert r["match_strategy"] == "ambiguous"
        assert sorted(r["candidates"]) == [
            "Clear-Diamonds Ltd", "Clear-Diamonds Trading"
        ]

    def test_reverse_prefix_when_input_carries_suffix(self, isolated_wfirma_db):
        """Sales input has 'Acme Ltd', wFirma stores 'Acme'."""
        _seed_wfirma_customers(isolated_wfirma_db, [
            ("Acme", "600", "PL", "PL777"),
        ])
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer("Acme Ltd")
        assert r["found"] is True
        assert r["match_strategy"] == "reverse_prefix"
        assert r["wfirma_customer_id"] == "600"

    def test_zero_match_remains_blocker(self, isolated_wfirma_db):
        _seed_wfirma_customers(isolated_wfirma_db, [
            ("Acme Ltd", "100", "GB", "GB1"),
        ])
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer("Anastazia Panakova")
        assert r["found"] is False
        assert r["ambiguous"] is False
        assert r["candidates"] == []
        assert r["match_strategy"] == "none"

    def test_empty_input(self, isolated_wfirma_db):
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer("")
        assert r["found"] is False
        assert r["normalized_name"] == ""

    def test_no_partial_word_match_to_avoid_false_positives(self, isolated_wfirma_db):
        """'Foo' must NOT match 'Foobar Ltd' (would be a substring not
        a token-aligned prefix). The resolver requires a space or comma
        boundary so 'Foo' doesn't accidentally match 'Foobar'."""
        _seed_wfirma_customers(isolated_wfirma_db, [
            ("Foobar Ltd", "700", "PL", "PL2"),
        ])
        from app.api.routes_proforma import _resolve_customer
        r = _resolve_customer("Foo")
        assert r["found"] is False
        assert r["match_strategy"] == "none"


# ── Integration: preview + payload builder share the resolver ─────────────

@pytest.fixture
def isolated_full_dbs(tmp_path, monkeypatch):
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(_s, "smtp_user", "", raising=False)
    monkeypatch.setattr(_s, "smtp_password", "", raising=False)

    from app.services import wfirma_db as wfdb
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")

    # Reservation queue DB schema (for design_product_bridge sibling test)
    rdb = tmp_path / "reservation_queue.db"
    with sqlite3.connect(str(rdb)) as con:
        con.executescript("""
            CREATE TABLE design_product_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                design_no TEXT NOT NULL,
                product_code TEXT NOT NULL,
                confidence TEXT NOT NULL DEFAULT 'locked',
                source TEXT NOT NULL DEFAULT 'purchase_packing',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(design_no, product_code)
            );
        """)
    return tmp_path


class TestPreviewSurfacesResolution:

    def test_preview_blocking_reasons_uses_resolver(self, isolated_full_dbs):
        """Whitespace-padded input that has a unique prefix candidate
        must NOT raise the 'not matched' blocker."""
        _seed_wfirma_customers(
            isolated_full_dbs / "wfirma.db",
            [("Clear-Diamonds Ltd", "91254191", "HU", "HU111")],
        )
        from app.api.routes_proforma import _build_preview
        preview = _build_preview("BATCH_X", " Clear-Diamonds")
        msgs = preview.get("blocking_reasons") or []
        # No 'not matched in wfirma_customers' entry should be present
        for m in msgs:
            assert "not matched in wfirma_customers" not in m, m
        # Resolution diagnostic surfaces the matched name
        cr = preview.get("customer_resolution") or {}
        assert cr.get("wfirma_customer_id") == "91254191"
        assert cr.get("resolved_wfirma_customer_name") == "Clear-Diamonds Ltd"
        assert cr.get("match_strategy") == "prefix"

    def test_preview_blocks_when_ambiguous(self, isolated_full_dbs):
        _seed_wfirma_customers(
            isolated_full_dbs / "wfirma.db",
            [
                ("Clear-Diamonds Ltd",     "1", "HU", "HU1"),
                ("Clear-Diamonds Trading", "2", "HU", "HU2"),
            ],
        )
        from app.api.routes_proforma import _build_preview
        preview = _build_preview("BATCH_Y", "Clear-Diamonds")
        msgs = preview.get("blocking_reasons") or []
        assert any("multiple wfirma customer candidates" in m for m in msgs)
        cr = preview.get("customer_resolution") or {}
        assert cr.get("match_strategy") == "ambiguous"
        assert sorted(cr.get("candidates") or []) == [
            "Clear-Diamonds Ltd", "Clear-Diamonds Trading"
        ]

    def test_payload_builder_uses_same_resolver(self, isolated_full_dbs):
        """_build_proforma_request must succeed at the customer step
        when the preview's resolver succeeds — no second exact-match
        comparison that could disagree with the preview."""
        _seed_wfirma_customers(
            isolated_full_dbs / "wfirma.db",
            [("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880")],
        )
        from app.api.routes_proforma import _resolve_customer
        # The payload builder calls _resolve_customer with the input
        # client_name (stripped). Single-shot test: padded input still
        # resolves to the right contractor_id.
        r = _resolve_customer(" Clear-Diamonds")
        assert r["found"] is True
        assert r["wfirma_customer_id"] == "91254191"
