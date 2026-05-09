"""
test_wfirma_customer_auto_resolve.py — pin batch customer-resolve contract.

AWB 6049349806 evidence:
  Sales clients: Anastazia Panakova, ' OMARA s.r.o', ' Clear-Diamonds',
                 'Impact Gallery sp. z o.o.'
  wFirma_customers contains 'Clear-Diamonds Ltd' (matched id 91254191).
  Expected outcome: 1 prefix_match (Clear-Diamonds), 3 missing.
"""
from __future__ import annotations

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

def _seed_sales_documents(documents_db: Path, batch_id: str,
                          client_names: List[str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(documents_db)) as con:
        for cn in client_names:
            con.execute(
                """INSERT INTO sales_documents
                   (id, batch_id, document_id, client_name, client_ref,
                    document_type, sales_doc_no, sales_doc_date,
                    source_file_path, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), batch_id, "doc-1", cn, "EJL/26-27/121",
                 "sales_packing_list", "", "", "", now, now),
            )


def _seed_sales_packing_lines(documents_db: Path, batch_id: str,
                              client_names: List[str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(documents_db)) as con:
        for cn in client_names:
            con.execute(
                """INSERT INTO sales_packing_lines
                   (id, batch_id, sales_document_id, client_name, client_ref,
                    product_code, design_no, bag_id, quantity, remarks,
                    created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), batch_id, "sales-doc-1", cn,
                 "EJL/26-27/121", "PCODE", "DESIGN", "", 1.0, "", now),
            )


def _seed_wfirma_customers(wfirma_db_path: Path,
                          rows: List[Tuple[str, str, str, str]]) -> None:
    """rows = [(client_name, wfirma_customer_id, country, vat_id), ...]"""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(wfirma_db_path)) as con:
        for cn, cid, country, vat in rows:
            con.execute(
                """INSERT INTO wfirma_customers
                   (id, client_name, wfirma_customer_id, vat_id, country,
                    match_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (f"row-{cid}", cn, cid, vat, country, "matched", now, now),
            )


def _seed_reservation_queue_db(tmp_path):
    p = tmp_path / "reservation_queue.db"
    with sqlite3.connect(str(p)) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS wfirma_customer_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL UNIQUE,
                wfirma_customer_id TEXT NOT NULL DEFAULT '',
                vat_id TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT '',
                match_status TEXT NOT NULL DEFAULT 'pending',
                last_checked_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
    return p


@pytest.fixture
def isolated_dbs(tmp_path, monkeypatch):
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(_s, "smtp_user", "", raising=False)
    monkeypatch.setattr(_s, "smtp_password", "", raising=False)

    from app.services import wfirma_db as wfdb
    from app.services import document_db as ddb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    ddb.init_document_db(tmp_path / "documents.db")
    _seed_reservation_queue_db(tmp_path)
    return tmp_path


# ── Normalization unit tests ───────────────────────────────────────────────

class TestNormalizeName:

    def test_strips_outer_whitespace(self):
        from app.services.wfirma_customer_auto_resolve import _normalize_name
        assert _normalize_name("   Foo Co  ") == "Foo Co"

    def test_collapses_internal_whitespace(self):
        from app.services.wfirma_customer_auto_resolve import _normalize_name
        assert _normalize_name("Foo    Bar  Baz") == "Foo Bar Baz"

    def test_empty_input_returns_empty(self):
        from app.services.wfirma_customer_auto_resolve import _normalize_name
        assert _normalize_name("") == ""
        assert _normalize_name("   \t\n  ") == ""


# ── Per-name resolver unit tests ───────────────────────────────────────────

class TestResolveOne:

    def test_invalid_name(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        r = _resolve_one("   ")
        assert r["status"] == "invalid_name"
        assert r["normalized_name"] == ""

    def test_exact_match(self, isolated_dbs):
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("Acme Sp. z o.o.", "100", "PL", "PL1")])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ) as p_live:
            r = _resolve_one("Acme Sp. z o.o.")
        assert r["status"] == "exact_match"
        assert r["wfirma_customer_id"] == "100"
        # No live fallback when local hit
        p_live.assert_not_called()

    def test_normalized_match_strips_whitespace(self, isolated_dbs):
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("OMARA s.r.o", "200", "SK", "SK1")])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ) as p_live:
            r = _resolve_one("   OMARA s.r.o   ")
        # Either exact_match (UPPER comparison strips on the SQL side) or
        # normalized_match — both signal "same row reached via normalized form".
        assert r["status"] in ("exact_match", "normalized_match")
        assert r["wfirma_customer_id"] == "200"
        assert r["normalized_name"] == "OMARA s.r.o"
        p_live.assert_not_called()

    def test_prefix_match_clear_diamonds(self, isolated_dbs):
        """The AWB 6049349806 case: input ' Clear-Diamonds' resolves to
        stored 'Clear-Diamonds Ltd' via prefix tolerance."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880")])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ) as p_live:
            r = _resolve_one(" Clear-Diamonds")
        assert r["status"] == "prefix_match"
        assert r["wfirma_customer_id"] == "91254191"
        assert r["matched_name"] == "Clear-Diamonds Ltd"
        p_live.assert_not_called()

    def test_reverse_prefix_match(self, isolated_dbs):
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("Acme", "300", "PL", "PL2")])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ) as p_live:
            r = _resolve_one("Acme Ltd")
        assert r["status"] == "reverse_prefix_match"
        assert r["wfirma_customer_id"] == "300"
        p_live.assert_not_called()

    def test_ambiguity_blocks_auto_resolution(self, isolated_dbs):
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd",     "1", "HU", "HU1"),
            ("Clear-Diamonds Trading", "2", "HU", "HU2"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ) as p_live:
            r = _resolve_one("Clear-Diamonds")
        assert r["status"] == "ambiguous"
        assert sorted(r["candidates"]) == [
            "Clear-Diamonds Ltd", "Clear-Diamonds Trading"
        ]
        # Ambiguity does NOT fall through to live search
        p_live.assert_not_called()

    def test_live_fallback_when_local_misses(self, isolated_dbs):
        """No local row → live wFirma search; on UNIQUE EXACT hit, mirror locally."""
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        live_rows = [{
            "wfirma_id": "WF-LIVE-7", "name": "Anastazia Panakova",
            "country":   "PL",        "nip":  "PL999",
        }]
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=live_rows,
        ):
            r = _resolve_one("Anastazia Panakova")
        assert r["status"] == "exact_match"
        assert r["resolution_source"] == "live"
        assert r["wfirma_customer_id"] == "WF-LIVE-7"
        from app.services import wfirma_db as wfdb
        cust = wfdb.get_customer("Anastazia Panakova")
        assert cust is not None
        assert cust["wfirma_customer_id"] == "WF-LIVE-7"

    def test_truly_missing_when_local_and_live_miss(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ):
            r = _resolve_one("Some Brand New Customer Co")
        assert r["status"] == "missing"
        assert r["wfirma_customer_id"] == ""
        assert r["candidates"] == []

    def test_never_calls_create_customer(self, isolated_dbs):
        """No code path may invoke wfirma_client.create_customer."""
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer") as p_create:
            _resolve_one("Anyone")
        p_create.assert_not_called()


# ── Mirror behaviour ───────────────────────────────────────────────────────

class TestMirrorBehaviour:

    def test_match_writes_local_mirror(self, isolated_dbs):
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880")])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch("app.services.wfirma_customer_auto_resolve._search_live_candidates", return_value=[]):
            _resolve_one(" Clear-Diamonds")

        # wfirma_customers should now ALSO have a row keyed by the
        # normalized 'Clear-Diamonds' so future direct lookups by the
        # sales-list spelling resolve in one hop.
        from app.services import wfirma_db as wfdb
        cust = wfdb.get_customer("Clear-Diamonds")
        assert cust is not None, "normalized name not mirrored"
        assert cust["wfirma_customer_id"] == "91254191"

        # reservation_queue.wfirma_customer_mapping receives the same row.
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM wfirma_customer_mapping WHERE client_name=?",
                ("Clear-Diamonds",),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["wfirma_customer_id"] == "91254191"
        assert rows[0]["match_status"]       == "matched"

    def test_ambiguous_does_not_mirror(self, isolated_dbs):
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd",     "1", "HU", "HU1"),
            ("Clear-Diamonds Trading", "2", "HU", "HU2"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        _resolve_one("Clear-Diamonds")

        # Mapping table empty — ambiguity must NOT auto-mirror
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute("SELECT COUNT(*) FROM wfirma_customer_mapping").fetchone()[0]
        assert n == 0

    def test_missing_does_not_mirror(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch("app.services.wfirma_customer_auto_resolve._search_live_candidates", return_value=[]):
            _resolve_one("Brand New Co")
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute("SELECT COUNT(*) FROM wfirma_customer_mapping").fetchone()[0]
        assert n == 0


# ── Batch entrypoint ───────────────────────────────────────────────────────

class TestEnsureCustomersForBatch:

    def test_awb_6049349806_shape(self, isolated_dbs):
        """The headline contract: AWB 6049349806 sales has 4 clients;
        only Clear-Diamonds Ltd is in wFirma; live search returns nothing
        for the others. Expected: 1 prefix_match, 3 missing."""
        bid = "B_AWB_SHAPE"
        _seed_sales_documents(isolated_dbs / "documents.db", bid, [
            "Anastazia Panakova",
            " OMARA s.r.o",
            " Clear-Diamonds",
            "Impact Gallery sp. z o.o.",
        ])
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880")])

        from app.services import wfirma_customer_auto_resolve as svc
        with patch("app.services.wfirma_customer_auto_resolve._search_live_candidates", return_value=[]):
            r = svc.ensure_customers_for_batch(bid)

        assert r["scanned"] == 4
        assert r["prefix_match"] == 1
        assert r["missing"]      == 3
        assert r["ambiguous"]    == 0
        # Per-result sanity
        by_raw = {x["raw_name"]: x for x in r["results"]}
        assert by_raw[" Clear-Diamonds"]["status"] == "prefix_match"
        assert by_raw[" Clear-Diamonds"]["wfirma_customer_id"] == "91254191"
        assert by_raw[" Clear-Diamonds"]["matched_name"] == "Clear-Diamonds Ltd"
        for raw in ("Anastazia Panakova", " OMARA s.r.o",
                    "Impact Gallery sp. z o.o."):
            assert by_raw[raw]["status"] == "missing"

    def test_duplicate_names_scanned_once(self, isolated_dbs):
        bid = "B_DUPES"
        _seed_sales_documents(isolated_dbs / "documents.db", bid, [
            "Acme Co", "Acme Co", "Acme Co",
        ])
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("Acme Co", "1", "PL", "PL1")])
        from app.services import wfirma_customer_auto_resolve as svc
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ) as p_live:
            r = svc.ensure_customers_for_batch(bid)
        assert r["scanned"] == 1
        # Only one search needed; live not even called (local hit)
        p_live.assert_not_called()

    def test_fallback_to_sales_packing_when_no_sales_docs(self, isolated_dbs):
        """When sales_documents has no rows for the batch, the resolver
        reads sales_packing_lines instead."""
        bid = "B_FALLBACK"
        _seed_sales_packing_lines(isolated_dbs / "documents.db", bid,
                                   ["OMARA s.r.o"])
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("OMARA s.r.o", "200", "SK", "SK1")])
        from app.services import wfirma_customer_auto_resolve as svc
        with patch("app.services.wfirma_customer_auto_resolve._search_live_candidates", return_value=[]):
            r = svc.ensure_customers_for_batch(bid)
        assert r["scanned"] == 1
        assert r["exact_match"] + r["normalized_match"] == 1

    def test_no_clients_returns_error_summary(self, isolated_dbs):
        from app.services import wfirma_customer_auto_resolve as svc
        r = svc.ensure_customers_for_batch("B_EMPTY")
        assert r["scanned"] == 0
        assert r["errors"]
        assert "no client names" in r["errors"][0]


# ── Endpoint integration ───────────────────────────────────────────────────

@pytest.fixture
def client(isolated_dbs):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestEndpoint:

    def test_preview_endpoint(self, isolated_dbs, client):
        bid = "B_ENDPOINT"
        _seed_sales_documents(isolated_dbs / "documents.db", bid,
                              ["Acme Co"])
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("Acme Co", "999", "PL", "PL999")])
        with patch("app.services.wfirma_customer_auto_resolve._search_live_candidates", return_value=[]) as p_live, \
             patch("app.services.wfirma_client.create_customer") as p_create:
            r = client.post(
                f"/api/v1/wfirma/customers/auto-resolve-preview/{bid}",
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scanned"] == 1
        assert body["exact_match"] == 1
        assert body["dry_run"] is True
        # No live search needed (local hit) and never a create_customer call
        p_create.assert_not_called()

    def test_preview_invalid_batch_id_400(self, client):
        r = client.post(
            "/api/v1/wfirma/customers/auto-resolve-preview/has..dotdot",
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 400, r.text

    def test_endpoint_never_calls_create_customer(self, isolated_dbs, client):
        """Belt-and-suspenders: even when EVERYTHING misses, the
        endpoint must never invoke create_customer."""
        bid = "B_NO_CREATE"
        _seed_sales_documents(isolated_dbs / "documents.db", bid,
                              ["Brand X"])
        with patch("app.services.wfirma_customer_auto_resolve._search_live_candidates", return_value=[]), \
             patch("app.services.wfirma_client.create_customer") as p_create:
            r = client.post(
                f"/api/v1/wfirma/customers/auto-resolve-preview/{bid}",
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code == 200
        assert r.json()["missing"] == 1
        p_create.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# Live-resolver ambiguity safety
# ──────────────────────────────────────────────────────────────────────────

class TestLiveResolverAmbiguity:

    def _live_row(self, wf_id, name, country="PL", nip=""):
        return {
            "wfirma_id": wf_id, "name": name,
            "country":   country, "nip": nip,
        }

    def test_unique_live_exact_match_mirrors(self, isolated_dbs):
        """Single live row whose normalized name equals input → mirror."""
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        rows = [self._live_row("LIVE-1", "Anastazia Panakova")]
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=rows,
        ):
            r = _resolve_one("Anastazia Panakova")
        assert r["status"] == "exact_match"
        assert r["resolution_source"] == "live"
        assert r["wfirma_customer_id"] == "LIVE-1"
        assert r["live_candidate_count"] == 1
        # mirror landed
        from app.services import wfirma_db as wfdb
        assert wfdb.get_customer("Anastazia Panakova") is not None

    def test_unique_live_prefix_match_mirrors(self, isolated_dbs):
        """Input 'Clear-Diamonds'; live returns ONE row 'Clear-Diamonds Ltd'."""
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        rows = [self._live_row("LIVE-CD", "Clear-Diamonds Ltd",
                                 country="HU", nip="HU32207880")]
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=rows,
        ):
            r = _resolve_one("Clear-Diamonds")
        assert r["status"] == "prefix_match"
        assert r["wfirma_customer_id"] == "LIVE-CD"
        assert r["live_candidate_count"] == 1
        from app.services import wfirma_db as wfdb
        cust = wfdb.get_customer("Clear-Diamonds")
        assert cust is not None and cust["wfirma_customer_id"] == "LIVE-CD"

    def test_multiple_live_candidates_block_with_ambiguous(self, isolated_dbs):
        """The OMARA-style risk case: live LIKE %OMARA% returns 3 rows.
        The resolver must NOT auto-pick. Surface all candidates."""
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        rows = [
            self._live_row("LIVE-O1", "OMARA s.r.o"),
            self._live_row("LIVE-O2", "OMARA TRADING SP. Z O.O."),
            self._live_row("LIVE-O3", "OMARA HOLDINGS LTD"),
        ]
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=rows,
        ):
            r = _resolve_one("OMARA")
        assert r["status"] == "ambiguous"
        assert r["wfirma_customer_id"] == ""   # no auto-pick
        assert sorted(r["candidates"]) == [
            "OMARA HOLDINGS LTD", "OMARA TRADING SP. Z O.O.", "OMARA s.r.o"
        ]
        assert r["live_candidate_count"] == 3
        # No mirror written
        from app.services import wfirma_db as wfdb
        assert wfdb.get_customer("OMARA") is None

    def test_token_boundary_safety_drops_substring_only_hits(self, isolated_dbs):
        """Live LIKE may surface 'FOOBAR LTD' for input 'FOO' — that is
        NOT a token-boundary safe match and must be dropped."""
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        rows = [self._live_row("LIVE-FOOBAR", "FOOBAR LTD")]
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=rows,
        ):
            r = _resolve_one("FOO")
        assert r["status"] == "missing"
        assert r["wfirma_customer_id"] == ""
        assert r["live_candidate_count"] == 1
        # The candidate name surfaces in the diagnostic so the operator
        # can see what wFirma's LIKE returned.
        assert r["candidate_names"] == ["FOOBAR LTD"]
        # No mirror
        from app.services import wfirma_db as wfdb
        assert wfdb.get_customer("FOO") is None

    def test_local_match_prevents_live_query(self, isolated_dbs):
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("Clear-Diamonds Ltd", "LOCAL-CD", "HU", "HU99")])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
        ) as p_live:
            r = _resolve_one(" Clear-Diamonds")
        assert r["status"] == "prefix_match"
        assert r["resolution_source"] == "local"
        p_live.assert_not_called()

    def test_local_ambiguous_does_not_fall_through_to_live(self, isolated_dbs):
        """When local says ambiguous, do NOT consult live (would multiply
        the candidate set without resolving the operator's choice)."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd",     "1", "HU", "HU1"),
            ("Clear-Diamonds Trading", "2", "HU", "HU2"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
        ) as p_live:
            r = _resolve_one("Clear-Diamonds")
        assert r["status"] == "ambiguous"
        assert r["resolution_source"] == "local"
        p_live.assert_not_called()

    def test_ambiguous_live_does_not_mirror(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        rows = [
            self._live_row("LIVE-1", "Acme Co"),
            self._live_row("LIVE-2", "Acme Corp"),
        ]
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=rows,
        ):
            _resolve_one("Acme")

        # No mirror in either registry
        from app.services import wfirma_db as wfdb
        assert wfdb.get_customer("Acme") is None
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute(
                "SELECT COUNT(*) FROM wfirma_customer_mapping "
                "WHERE client_name='Acme'"
            ).fetchone()[0]
        assert n == 0

    def test_unique_live_candidate_mirrors_correctly(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        rows = [self._live_row("LIVE-7", "Brand X SP. Z O.O.",
                                 country="PL", nip="PL12345")]
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=rows,
        ):
            r = _resolve_one("Brand X")
        assert r["status"] == "prefix_match"
        from app.services import wfirma_db as wfdb
        cust = wfdb.get_customer("Brand X")
        assert cust is not None
        assert cust["wfirma_customer_id"] == "LIVE-7"
        assert cust["country"] == "PL"
        assert cust["vat_id"]  == "PL12345"

    def test_create_customer_never_called_in_any_live_branch(self, isolated_dbs):
        """Belt-and-suspenders: regardless of live response shape (none,
        single, multiple, token-boundary-rejected), create_customer is
        NEVER invoked."""
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        scenarios = [
            ("Empty live",   []),
            ("Single exact", [self._live_row("X1", "Acme")]),
            ("Single prefix", [self._live_row("X2", "Acme Ltd")]),
            ("Multiple",      [self._live_row("X3", "Acme A"),
                               self._live_row("X4", "Acme B")]),
            ("Substring-only",[self._live_row("X5", "Acmebar Ltd")]),
        ]
        with patch("app.services.wfirma_client.create_customer") as p_create:
            for label, rows in scenarios:
                with patch(
                    "app.services.wfirma_customer_auto_resolve._search_live_candidates",
                    return_value=rows,
                ):
                    _resolve_one("Acme")
        p_create.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# VAT-first identity resolution
# ──────────────────────────────────────────────────────────────────────────

class TestVatNormalization:

    def test_uppercase_strip_separators(self):
        from app.services.wfirma_customer_auto_resolve import _normalize_vat
        assert _normalize_vat("PL 525-281-21-19") == "PL5252812119"
        assert _normalize_vat("hu 32.207.880")    == "HU32207880"
        assert _normalize_vat("  pl5252812119 ")  == "PL5252812119"
        assert _normalize_vat("")                 == ""
        assert _normalize_vat(None)               == ""

    def test_variants_strip_country_prefix(self):
        from app.services.wfirma_customer_auto_resolve import _vat_variants
        assert "PL5252812119" in _vat_variants("PL5252812119")
        assert "5252812119"   in _vat_variants("PL5252812119")

    def test_variants_add_country_prefix_when_input_bare(self):
        from app.services.wfirma_customer_auto_resolve import _vat_variants
        v = _vat_variants("5252812119", "PL")
        assert "5252812119"   in v
        assert "PL5252812119" in v

    def test_vat_matches_with_and_without_prefix(self):
        from app.services.wfirma_customer_auto_resolve import (
            _vat_variants, _vat_matches,
        )
        v = _vat_variants("PL5252812119")
        assert _vat_matches("5252812119",   v)
        assert _vat_matches("PL5252812119", v)
        assert _vat_matches("pl-5252812119", v)
        assert not _vat_matches("PL9999999999", v)

    def test_empty_input_yields_empty_variants(self):
        from app.services.wfirma_customer_auto_resolve import _vat_variants
        assert _vat_variants("")   == []
        assert _vat_variants(None) == []


class TestVatFirstResolverLocal:

    def test_unique_local_vat_match_resolves_identity_vat(self, isolated_dbs):
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ) as p_live:
            r = _resolve_one("Some Other Spelling Co",
                             input_vat="HU32207880", input_country="HU")
        assert r["status"] == "exact_match"
        assert r["resolution_identity"] == "vat"
        assert r["resolution_source"]   == "local"
        assert r["wfirma_customer_id"]  == "91254191"
        assert r["matched_name"]        == "Clear-Diamonds Ltd"
        assert r["matched_vat_id"]      == "HU32207880"
        assert r["vat_match_confidence"] == "exact"
        # Live name-search is NOT consulted on VAT hit
        p_live.assert_not_called()
        # Soft warning fired because the input name doesn't match the
        # stored legal name
        assert any("VAT matched but legal name differs" in w
                   for w in r["warnings"])

    def test_vat_match_with_normalized_format_difference(self, isolated_dbs):
        """Stored 'HU32207880' vs input ' hu-32 207 880 '."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ):
            r = _resolve_one("Clear-Diamonds Ltd",
                             input_vat=" hu-32 207 880 ")
        assert r["status"] == "exact_match"
        assert r["resolution_identity"] == "vat"

    def test_vat_match_strips_country_prefix(self, isolated_dbs):
        """Stored bare '5252812119' (PL) vs input 'PL5252812119'."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Estrella Jewels Sp. z o.o.", "42", "PL", "5252812119"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ):
            r = _resolve_one("Estrella Jewels Sp. z o.o.",
                             input_vat="PL5252812119")
        assert r["status"] == "exact_match"
        assert r["resolution_identity"] == "vat"
        assert r["wfirma_customer_id"] == "42"

    def test_duplicate_local_vat_returns_ambiguous_vat_no_mirror(self, isolated_dbs):
        """Two local rows share the same VAT → ambiguous_vat, no mirror."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Brand A Ltd", "1", "HU", "HU99"),
            ("Brand B Ltd", "2", "HU", "HU99"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ):
            r = _resolve_one("Brand", input_vat="HU99")
        assert r["status"] == "ambiguous_vat"
        assert r["resolution_identity"] == "vat"
        assert sorted(r["candidates"]) == ["Brand A Ltd", "Brand B Ltd"]
        assert r["wfirma_customer_id"] == ""
        # No mirror written
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute(
                "SELECT COUNT(*) FROM wfirma_customer_mapping "
                "WHERE client_name='Brand'"
            ).fetchone()[0]
        assert n == 0

    def test_vat_match_overrides_name_mismatch(self, isolated_dbs):
        """Legal-name materially different from input but VAT matches —
        resolution still succeeds via VAT, with a soft warning."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Acme Polska Sp. z o.o.", "777", "PL", "PL5252812119"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ):
            r = _resolve_one("Some Different Brand Name",
                             input_vat="PL5252812119")
        assert r["status"] == "exact_match"
        assert r["resolution_identity"] == "vat"
        assert r["wfirma_customer_id"] == "777"
        # Warning explicitly mentions the divergence
        warns = [w for w in r["warnings"]
                 if "legal name differs" in w]
        assert warns, f"missing soft warning, got {r['warnings']}"
        assert "Some Different Brand Name" in warns[0]
        assert "Acme Polska Sp. z o.o." in warns[0]

    def test_vat_absent_falls_back_to_name_logic(self, isolated_dbs):
        """No VAT supplied → resolver behaves exactly like the name path
        (Clear-Diamonds prefix-match contract preserved)."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ):
            r = _resolve_one(" Clear-Diamonds")    # no VAT
        assert r["status"] == "prefix_match"
        assert r["resolution_identity"] == "prefix"
        assert r["wfirma_customer_id"] == "91254191"

    def test_vat_supplied_but_unknown_falls_through_to_name(self, isolated_dbs):
        """Unknown VAT → still try name resolution; don't bail early."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ):
            r = _resolve_one(" Clear-Diamonds", input_vat="XX99")
        # VAT didn't match → name path resolves via prefix tolerance
        assert r["status"] == "prefix_match"
        assert r["resolution_identity"] == "prefix"


class TestVatFirstResolverLive:

    def _live_row(self, wf_id, name, country="PL", nip=""):
        return {"wfirma_id": wf_id, "name": name,
                "country":   country, "nip":  nip}

    def test_unique_live_vat_match_resolves(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        live_match = MagicMock()
        live_match.wfirma_id = "WF-LIVE-VAT"
        live_match.name      = "Brand New Ltd"
        live_match.nip       = "GB987654321"
        live_match.country   = "GB"
        with patch("app.services.wfirma_client.search_customer",
                   return_value=live_match) as p_search, \
             patch(
                 "app.services.wfirma_customer_auto_resolve._search_live_candidates",
                 return_value=[],
             ):
            r = _resolve_one("Brand New Ltd", input_vat="GB987654321")
        assert r["status"] == "exact_match"
        assert r["resolution_identity"] == "vat"
        assert r["resolution_source"]   == "live"
        assert r["wfirma_customer_id"]  == "WF-LIVE-VAT"
        # VAT-search uses the existing client.search_customer(name="", nip=...)
        p_search.assert_called_once()
        args, kwargs = p_search.call_args
        # called with name="" and nip=normalized VAT
        assert (args and args[0] == "") or kwargs.get("name") == ""
        assert kwargs.get("nip") == "GB987654321"

    def test_live_unique_vat_mirrors_to_local(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        live_match = MagicMock()
        live_match.wfirma_id = "WF-MIRROR-VAT"
        live_match.name      = "OMARA s.r.o"
        live_match.nip       = "SK12345"
        live_match.country   = "SK"
        with patch("app.services.wfirma_client.search_customer",
                   return_value=live_match), \
             patch(
                 "app.services.wfirma_customer_auto_resolve._search_live_candidates",
                 return_value=[],
             ):
            _resolve_one("OMARA s.r.o", input_vat="SK12345")
        from app.services import wfirma_db as wfdb
        cust = wfdb.get_customer("OMARA s.r.o")
        assert cust is not None
        assert cust["wfirma_customer_id"] == "WF-MIRROR-VAT"
        assert cust["vat_id"] == "SK12345"

    def test_live_no_vat_match_falls_back_to_name_ambiguity(self, isolated_dbs):
        """VAT searched live → 0 hits → falls through to name resolver,
        which should still apply the existing ambiguity logic."""
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        rows = [
            {"wfirma_id": "L1", "name": "OMARA s.r.o",     "country": "SK", "nip": "SK1"},
            {"wfirma_id": "L2", "name": "OMARA TRADING",   "country": "SK", "nip": "SK2"},
        ]
        with patch("app.services.wfirma_client.search_customer",
                   return_value=None), \
             patch(
                 "app.services.wfirma_customer_auto_resolve._search_live_candidates",
                 return_value=rows,
             ):
            r = _resolve_one("OMARA", input_vat="UNKNOWN-VAT")
        # VAT-live miss → name resolver kicks in → multiple candidates
        assert r["status"] == "ambiguous"
        assert sorted(r["candidates"]) == ["OMARA TRADING", "OMARA s.r.o"]

    def test_live_create_customer_never_called_in_vat_path(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch("app.services.wfirma_client.search_customer",
                   return_value=None), \
             patch(
                 "app.services.wfirma_customer_auto_resolve._search_live_candidates",
                 return_value=[],
             ), patch("app.services.wfirma_client.create_customer") as p_create:
            _resolve_one("Anyone", input_vat="ZZ999")
        p_create.assert_not_called()


class TestRegressionWithVatExtension:

    def test_clear_diamonds_still_resolves_when_vat_absent(self, isolated_dbs):
        """The headline regression check: AWB 6049349806 contract
        ' Clear-Diamonds' → 'Clear-Diamonds Ltd' must still hold when
        no VAT is supplied."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880"),
        ])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ):
            r = _resolve_one(" Clear-Diamonds")
        assert r["status"] == "prefix_match"
        assert r["wfirma_customer_id"] == "91254191"

    def test_omara_ambiguous_still_blocks_when_vat_absent(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        rows = [
            {"wfirma_id": "L1", "name": "OMARA s.r.o",  "country": "SK", "nip": ""},
            {"wfirma_id": "L2", "name": "OMARA TRADING","country": "SK", "nip": ""},
        ]
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=rows,
        ):
            r = _resolve_one("OMARA")
        assert r["status"] == "ambiguous"
        assert r["wfirma_customer_id"] == ""

    def test_vat_first_does_not_break_local_only_workflows(self, isolated_dbs):
        """Without VAT, the existing local exact-name path remains intact."""
        _seed_wfirma_customers(isolated_dbs / "wfirma.db",
                               [("Acme Sp. z o.o.", "100", "PL", "PL1")])
        from app.services.wfirma_customer_auto_resolve import _resolve_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ):
            r = _resolve_one("Acme Sp. z o.o.")
        assert r["status"] == "exact_match"
        assert r["resolution_identity"] == "name"


# ──────────────────────────────────────────────────────────────────────────
# Customer auto-create — operator-triggered, gated by resolver
# ──────────────────────────────────────────────────────────────────────────

class TestCreateOne:

    def test_invalid_name_refuses_before_resolver(self, isolated_dbs):
        from app.services.wfirma_customer_auto_resolve import create_one
        with patch("app.services.wfirma_client.create_customer") as p_create:
            r = create_one("   ")
        assert r["status"] == "invalid_name"
        assert r["created"] is False
        p_create.assert_not_called()

    def test_missing_flag_off_returns_blocked_no_create(self, isolated_dbs, monkeypatch):
        """Resolver returns missing; flag is False → blocked_flag_off."""
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", False, raising=False)
        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer") as p_create:
            r = create_one("Brand New Co")
        assert r["status"] == "blocked_flag_off"
        assert r["created"] is False
        assert r["mirrored"] is False
        p_create.assert_not_called()

    def test_missing_flag_on_creates_and_mirrors(self, isolated_dbs, monkeypatch):
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)

        new_stub = MagicMock()
        new_stub.wfirma_id = "WF-NEW-12345"
        new_stub.name      = "Brand New Co"
        new_stub.country   = "PL"
        new_stub.nip       = "PL5252812119"

        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer",
                 return_value=new_stub) as p_create:
            r = create_one("Brand New Co", vat_id="PL5252812119", country_code="PL")

        assert r["status"] == "created"
        assert r["created"] is True
        assert r["mirrored"] is True
        assert r["wfirma_customer_id"] == "WF-NEW-12345"
        # create_customer called exactly once with normalized inputs
        assert p_create.call_count == 1
        kw = p_create.call_args.kwargs
        assert kw.get("name")    == "Brand New Co"
        assert kw.get("nip")     == "PL5252812119"
        assert kw.get("country") == "PL"
        # Local registries received the row
        from app.services import wfirma_db as wfdb
        cust = wfdb.get_customer("Brand New Co")
        assert cust is not None and cust["wfirma_customer_id"] == "WF-NEW-12345"
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute(
                "SELECT COUNT(*) FROM wfirma_customer_mapping "
                "WHERE client_name='Brand New Co'"
            ).fetchone()[0]
        assert n == 1

    def test_exact_match_refuses_create(self, isolated_dbs, monkeypatch):
        """Local exact name match → resolver returns exact_match → create
        endpoint refuses ('already exists')."""
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Existing Co", "EXISTING-1", "PL", "PL999"),
        ])
        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer") as p_create:
            r = create_one("Existing Co")
        assert r["status"] == "already_exists_or_ambiguous"
        assert r["created"] is False
        assert r["wfirma_customer_id"] == "EXISTING-1"
        p_create.assert_not_called()
        # Resolution surfaced for operator UI
        assert r["resolution_before_create"]["status"] == "exact_match"

    def test_prefix_match_refuses_create(self, isolated_dbs, monkeypatch):
        """ ' Clear-Diamonds' → resolver returns prefix_match against
        'Clear-Diamonds Ltd' → refuse create."""
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880"),
        ])
        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer") as p_create:
            r = create_one(" Clear-Diamonds")
        assert r["status"] == "already_exists_or_ambiguous"
        assert r["wfirma_customer_id"] == "91254191"
        p_create.assert_not_called()

    def test_ambiguous_name_refuses_create(self, isolated_dbs, monkeypatch):
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Brand Ltd",      "1", "PL", "PL1"),
            ("Brand Trading",  "2", "PL", "PL2"),
        ])
        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer") as p_create:
            r = create_one("Brand")
        assert r["status"] == "already_exists_or_ambiguous"
        assert r["created"] is False
        # Resolution lists candidates for the operator
        assert sorted(r["resolution_before_create"]["candidates"]) == [
            "Brand Ltd", "Brand Trading"
        ]
        p_create.assert_not_called()

    def test_ambiguous_vat_refuses_create(self, isolated_dbs, monkeypatch):
        """Two local rows share the same VAT → ambiguous_vat → refuse."""
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Twin A Ltd", "1", "HU", "HU99"),
            ("Twin B Ltd", "2", "HU", "HU99"),
        ])
        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer") as p_create:
            r = create_one("Twin C Ltd", vat_id="HU99")
        assert r["status"] == "already_exists_or_ambiguous"
        assert r["resolution_before_create"]["status"] == "ambiguous_vat"
        p_create.assert_not_called()

    def test_create_raises_returns_failed_no_mirror(self, isolated_dbs, monkeypatch):
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)
        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer",
                 side_effect=RuntimeError("contractors/add wFirma status=ERROR")):
            r = create_one("Brand New Co")
        assert r["status"] == "failed"
        assert r["created"] is False
        assert r["mirrored"] is False
        assert any("contractors/add" in e for e in r["errors"])
        # No local mirror written
        from app.services import wfirma_db as wfdb
        assert wfdb.get_customer("Brand New Co") is None
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute("SELECT COUNT(*) FROM wfirma_customer_mapping").fetchone()[0]
        assert n == 0

    def test_create_returns_empty_id_returns_failed_no_mirror(self, isolated_dbs, monkeypatch):
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)

        empty_stub = MagicMock()
        empty_stub.wfirma_id = ""
        empty_stub.name      = "Brand New Co"
        empty_stub.country   = "PL"
        empty_stub.nip       = ""

        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer",
                 return_value=empty_stub):
            r = create_one("Brand New Co")
        assert r["status"] == "failed"
        assert r["created"] is False
        assert r["mirrored"] is False
        assert any("no wfirma_id" in e for e in r["errors"])
        # No local mirror
        from app.services import wfirma_db as wfdb
        assert wfdb.get_customer("Brand New Co") is None

    def test_vat_first_resolver_still_used(self, isolated_dbs, monkeypatch):
        """create_one MUST consult the VAT-first resolver — when a VAT
        match exists locally, the resolver returns exact_match (identity=vat)
        and create is refused even though the input name doesn't appear
        in wfirma_customers."""
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Existing Vat Holder", "VAT-HOLDER-1", "PL", "PL5252812119"),
        ])
        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer") as p_create:
            # Different name but same VAT
            r = create_one("Totally Different Brand",
                          vat_id="PL5252812119", country_code="PL")
        assert r["status"] == "already_exists_or_ambiguous"
        assert r["wfirma_customer_id"] == "VAT-HOLDER-1"
        assert r["resolution_before_create"]["resolution_identity"] == "vat"
        p_create.assert_not_called()

    def test_create_called_at_most_once(self, isolated_dbs, monkeypatch):
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)

        stub = MagicMock()
        stub.wfirma_id = "WF-ONCE"
        stub.name      = "Brand New Co"
        stub.country   = "PL"
        stub.nip       = ""

        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer",
                 return_value=stub) as p_create:
            create_one("Brand New Co")
        assert p_create.call_count == 1

    def test_rerun_after_create_does_not_duplicate(self, isolated_dbs, monkeypatch):
        """Second create_one call after the first succeeded → resolver
        finds the freshly-mirrored row and refuses (already_exists);
        wFirma create is NOT called twice."""
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)

        stub = MagicMock()
        stub.wfirma_id = "WF-IDEM"
        stub.name      = "Brand New Co"
        stub.country   = "PL"
        stub.nip       = ""

        from app.services.wfirma_customer_auto_resolve import create_one
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer",
                 return_value=stub) as p_create:
            r1 = create_one("Brand New Co")
            r2 = create_one("Brand New Co")
        assert r1["status"] == "created"
        assert r2["status"] == "already_exists_or_ambiguous"
        # create_customer called only on the first run
        assert p_create.call_count == 1
        # Mapping table has exactly one row
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n = con.execute(
                "SELECT COUNT(*) FROM wfirma_customer_mapping "
                "WHERE client_name='Brand New Co'"
            ).fetchone()[0]
        assert n == 1


# ── Endpoint integration ───────────────────────────────────────────────────

class TestCreateEndpoint:

    def test_endpoint_blocked_when_flag_off(self, isolated_dbs, client, monkeypatch):
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", False, raising=False)
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer") as p_create:
            r = client.post(
                "/api/v1/wfirma/customers/auto-create-from-name",
                json={"client_name": "Brand New Co"},
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "blocked_flag_off"
        p_create.assert_not_called()

    def test_endpoint_creates_when_flag_on_and_missing(self, isolated_dbs, client, monkeypatch):
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)
        stub = MagicMock()
        stub.wfirma_id = "WF-EP-1"
        stub.name      = "Brand New Co"
        stub.country   = "PL"
        stub.nip       = ""
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer",
                 return_value=stub):
            r = client.post(
                "/api/v1/wfirma/customers/auto-create-from-name",
                json={"client_name": "Brand New Co",
                      "vat_id": "PL5252812119",
                      "country_code": "PL"},
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "created"
        assert body["wfirma_customer_id"] == "WF-EP-1"

    def test_endpoint_refuses_existing_match(self, isolated_dbs, client, monkeypatch):
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "wfirma_create_customer_allowed", True, raising=False)
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880"),
        ])
        with patch(
            "app.services.wfirma_customer_auto_resolve._search_live_candidates",
            return_value=[],
        ), patch("app.services.wfirma_client.create_customer") as p_create:
            r = client.post(
                "/api/v1/wfirma/customers/auto-create-from-name",
                json={"client_name": " Clear-Diamonds"},
                headers={"X-API-Key": "test-key"},
            )
        body = r.json()
        assert r.status_code == 200
        assert body["status"] == "already_exists_or_ambiguous"
        assert body["wfirma_customer_id"] == "91254191"
        p_create.assert_not_called()
