"""
test_proforma_readiness_panel.py — pin the read-only Proforma readiness
aggregator endpoint + dashboard.html panel surface.

The aggregator at GET /dashboard/batches/{batch_id}/proforma-readiness
is the single read-only snapshot the dashboard panel consumes on mount.
It must:
  • never call live wFirma APIs;
  • never write to wfirma_products, wfirma_customers, or
    wfirma_*_mapping (the mirror writes happen behind the explicit
    Preview / Create buttons, not on page load);
  • surface the AWB 6049349806 evidence: 9 product codes (0 mapped),
    4 customers (1 prefix-resolved + 3 missing), PND ambiguity, and
    the headline ready=False verdict.

The dashboard surface tests check that the panel is wired into the
PZ / Accounting tab and references the existing endpoint paths only —
the React tree itself is not exercised here.
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
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


# ── Fixtures ────────────────────────────────────────────────────────────────

def _seed_invoice_lines(documents_db: Path, batch_id: str,
                        rows: List[Tuple[str, str]]) -> None:
    """rows = [(product_code, description), ...]"""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(documents_db)) as con:
        for i, (pc, desc) in enumerate(rows):
            con.execute(
                """INSERT INTO invoice_lines
                   (id, document_id, batch_id, invoice_no, line_position,
                    product_code, description, quantity, unit_price, total_value,
                    currency, hs_code, created_at, gross_weight, net_weight,
                    rate_usd, amount_usd, hsn_code)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), "doc-1", batch_id, "INV-001",
                 i + 1, pc, desc, 1.0, 100.0, 100.0,
                 "USD", "", now, 0.0, 0.0, 100.0, 100.0, ""),
            )


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
                (str(uuid.uuid4()), batch_id, "doc-1", cn, "",
                 "sales_packing_list", "", "", "", now, now),
            )


def _seed_wfirma_customers(wfirma_db_path: Path,
                          rows: List[Tuple[str, str, str, str]]) -> None:
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


def _seed_design_product_mappings(reservation_db_path: Path,
                                  rows: List[Tuple[str, str]]) -> None:
    """rows = [(design_no, product_code), ...]"""
    with sqlite3.connect(str(reservation_db_path)) as con:
        for d, pc in rows:
            con.execute(
                """INSERT OR IGNORE INTO design_product_mapping
                   (design_no, product_code, confidence, source)
                   VALUES (?,?,'locked','packing_bridge')""",
                (d, pc),
            )


def _seed_audit(outputs_dir: Path, batch_id: str, **fields) -> Path:
    bdir = outputs_dir / batch_id
    bdir.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, **fields}
    p = bdir / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


@pytest.fixture
def isolated_dbs(tmp_path, monkeypatch):
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(_s, "smtp_user", "", raising=False)
    monkeypatch.setattr(_s, "smtp_password", "", raising=False)
    monkeypatch.setattr(_s, "wfirma_create_product_allowed", False, raising=False)
    monkeypatch.setattr(_s, "wfirma_create_customer_allowed", False, raising=False)

    from app.services import wfirma_db as wfdb
    from app.services import document_db as ddb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    ddb.init_document_db(tmp_path / "documents.db")

    # Reservation queue with the schema the bridge writes to
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
            CREATE TABLE wfirma_customer_mapping (
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
    return tmp_path


@pytest.fixture
def client(isolated_dbs):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _awb_lines() -> List[Tuple[str, str]]:
    return [
        ("EJL/26-27/121-1", "PCS, 14KT Gold,Stud With Diam Jewel RING"),
        ("EJL/26-27/122-1", "PCS, 14KT Gold,LGD Gold Stud Jewell RING"),
        ("EJL/26-27/122-2", "PCS, 14KT Gold,Plain Jewellery RING"),
        ("EJL/26-27/123-1", "PCS, 14KT Gold,LGD Gold Stud Jewellery RING"),
        ("EJL/26-27/123-2", "PCS, 14KT Gold,Plain Jewellery PENDANT"),
        ("EJL/26-27/123-3", "PCS, SL925 SILVERPlain Jewellery PENDANT"),
        ("EJL/26-27/123-4", "PRS, SL925 LGD Silver Std EARRINGS"),
        ("EJL/26-27/123-5", "PRS, SL925 LGD Gold Stud EARRINGS"),
        ("EJL/26-27/124-1", "PCS, 14KT Gold,LGD Gold Stud Jewellery RING"),
    ]


# ── Aggregator endpoint tests ──────────────────────────────────────────────

class TestProformaReadinessAggregator:

    def test_full_awb_6049349806_shape(self, isolated_dbs, client):
        bid = "SHIPMENT_TEST"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid, _awb_lines())
        _seed_sales_documents(isolated_dbs / "documents.db", bid, [
            "Anastazia Panakova",
            " OMARA s.r.o",
            " Clear-Diamonds",
            "Impact Gallery sp. z o.o.",
        ])
        # Only Clear-Diamonds Ltd is in wFirma master mirror — prefix match
        _seed_wfirma_customers(isolated_dbs / "wfirma.db", [
            ("Clear-Diamonds Ltd", "91254191", "HU", "HU32207880"),
        ])
        # PND maps to two distinct invoice codes (the canonical ambiguity)
        _seed_design_product_mappings(isolated_dbs / "reservation_queue.db", [
            ("CSTR07718",      "EJL/26-27/121-1"),
            ("PND",            "EJL/26-27/123-2"),
            ("PND",            "EJL/26-27/123-3"),
            ("JE02648",        "EJL/26-27/123-4"),
        ])
        # No SAD, no PZ
        _seed_audit(isolated_dbs / "outputs", bid)

        # Live wFirma must NOT be called by the aggregator
        with patch("app.services.wfirma_client.search_customer") as p_search, \
             patch("app.services.wfirma_client.create_customer") as p_create_c, \
             patch("app.services.wfirma_client.create_product") as p_create_p, \
             patch("app.services.wfirma_client.get_product_by_code") as p_get_p:
            r = client.get(
                f"/dashboard/batches/{bid}/proforma-readiness",
                headers={"X-API-Key": "test-key"},
            )

        assert r.status_code == 200, r.text
        body = r.json()

        # Products: 9 codes, 0 mapped
        assert body["products"]["total"]   == 9
        assert body["products"]["mapped"]  == 0
        assert body["products"]["missing"] == 9
        assert body["products"]["create_flag_on"] is False

        # Customers: 4 total, 1 resolved (Clear-Diamonds via prefix), 3 missing
        assert body["customers"]["total"]     == 4
        assert body["customers"]["resolved"]  == 1
        assert body["customers"]["missing"]   == 3
        assert body["customers"]["ambiguous"] == 0
        # The 1 resolved row carries the wFirma id
        resolved = [c for c in body["customers"]["details"]
                    if c["status"] in ("exact_match","normalized_match",
                                       "prefix_match","reverse_prefix_match")]
        assert len(resolved) == 1
        assert resolved[0]["wfirma_customer_id"] == "91254191"

        # Bridge: 4 mappings, PND ambiguity surfaced
        assert body["bridge"]["design_product_mappings"] == 4
        assert "PND" in body["bridge"]["ambiguous_design_codes"]
        assert sorted(body["bridge"]["ambiguous_design_codes"]["PND"]) == [
            "EJL/26-27/123-2", "EJL/26-27/123-3"
        ]

        # PZ: nothing yet
        assert body["pz"]["sad_received"] is False
        assert body["pz"]["wfirma_pz_doc_id"] is None
        assert body["pz"]["ready_for_pz_create"] is False

        # Verdict: blocked, with concrete blocking reasons + next action
        assert body["proforma"]["ready"] is False
        assert len(body["proforma"]["blocking_reasons"]) >= 1
        assert body["proforma"]["next_action"]

        # Critical: live wFirma APIs NEVER called by the aggregator
        p_search.assert_not_called()
        p_create_c.assert_not_called()
        p_create_p.assert_not_called()
        p_get_p.assert_not_called()

    def test_aggregator_writes_nothing_to_wfirma_mirrors(self, isolated_dbs, client):
        bid = "READ_ONLY"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid, _awb_lines()[:1])
        _seed_sales_documents(isolated_dbs / "documents.db", bid, ["New Co"])
        _seed_audit(isolated_dbs / "outputs", bid)

        # Snapshot table sizes before
        with sqlite3.connect(str(isolated_dbs / "wfirma.db")) as con:
            n_prod_before = con.execute("SELECT COUNT(*) FROM wfirma_products").fetchone()[0]
            n_cust_before = con.execute("SELECT COUNT(*) FROM wfirma_customers").fetchone()[0]
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n_pmap_before = con.execute("SELECT COUNT(*) FROM wfirma_customer_mapping").fetchone()[0]

        client.get(f"/dashboard/batches/{bid}/proforma-readiness",
                   headers={"X-API-Key": "test-key"})

        with sqlite3.connect(str(isolated_dbs / "wfirma.db")) as con:
            n_prod_after = con.execute("SELECT COUNT(*) FROM wfirma_products").fetchone()[0]
            n_cust_after = con.execute("SELECT COUNT(*) FROM wfirma_customers").fetchone()[0]
        with sqlite3.connect(str(isolated_dbs / "reservation_queue.db")) as con:
            n_pmap_after = con.execute("SELECT COUNT(*) FROM wfirma_customer_mapping").fetchone()[0]

        assert (n_prod_before, n_cust_before, n_pmap_before) == \
               (n_prod_after,  n_cust_after,  n_pmap_after), (
            "aggregator must not mutate any local mirror table"
        )

    def test_pz_ready_when_sad_received_and_products_mapped(self, isolated_dbs, client):
        bid = "PZ_READY"
        _seed_invoice_lines(isolated_dbs / "documents.db", bid, [
            ("EJL/PZ-1", "PCS RING"),
        ])
        # Mirror the product (legacy split cache — now a dead-read after C-1c)
        from app.services import wfirma_db as wfdb
        wfdb.upsert_product(
            product_code      = "EJL/PZ-1",
            wfirma_product_id = "WF-PZ-1",
            sync_status       = "matched",
        )
        # C-1c: the readiness endpoint reads the Product Master (status='mapped'),
        # not the wfirma_db cache — seed the Master as the authority. (The
        # isolated_dbs fixture hand-creates reservation_queue.db with only two
        # tables, so ensure the full schema exists first.)
        from app.services import reservation_db as rdb
        _rdb = isolated_dbs / "reservation_queue.db"
        rdb.init_reservation_db(_rdb)
        rdb.upsert_product_master(_rdb, "EJL/PZ-1", "D-PZ-1")
        rdb.set_product_master_status(_rdb, "EJL/PZ-1", "mapped")
        # SAD present in audit
        _seed_audit(isolated_dbs / "outputs", bid,
                    customs_declaration={"mrn": "PL12345"})

        r = client.get(f"/dashboard/batches/{bid}/proforma-readiness",
                       headers={"X-API-Key": "test-key"})
        body = r.json()
        assert body["pz"]["sad_received"] is True
        assert body["pz"]["ready_for_pz_create"] is True

    def test_invalid_batch_id_400(self, client):
        r = client.get("/dashboard/batches/has..dotdot/proforma-readiness",
                       headers={"X-API-Key": "test-key"})
        assert r.status_code == 400


# ── Dashboard panel surface tests (HTML grep) ──────────────────────────────

class TestDashboardPanelSurface:

    @pytest.fixture
    def html(self):
        path = Path(__file__).parents[1] / "app" / "static" / "dashboard.html"
        return path.read_text(encoding="utf-8")

    def test_panel_component_defined(self, html):
        assert "function ProformaReadinessCard" in html

    def test_panel_mounted_in_pz_wfirma_tab(self, html):
        assert "<ProformaReadinessCard batchId=" in html

    def test_product_identity_section_present(self, html):
        assert 'data-testid="readiness-products"' in html
        assert "1 · Product Identity" in html

    def test_customer_identity_section_present(self, html):
        assert 'data-testid="readiness-customers"' in html
        assert "2 · Customer Identity" in html

    def test_bridge_section_present(self, html):
        assert 'data-testid="readiness-bridge"' in html
        assert "Design → Product Bridge" in html

    def test_pz_prerequisites_section_present(self, html):
        assert 'data-testid="readiness-pz"' in html
        assert "PZ / SAD prerequisites" in html

    def test_verdict_section_present(self, html):
        assert 'data-testid="readiness-verdict"' in html
        assert 'data-testid="proforma-verdict"' in html

    def test_no_auto_write_endpoint_called_on_load(self, html):
        """The mount-time fetch must hit the read-only aggregator only.
        Verify by checking that the fetch URL inside the React.useEffect
        wrapper goes to /proforma-readiness, and that no auto-register
        write endpoint is referenced inside refresh()."""
        # The refresh() function fires on mount and uses this URL:
        assert "/proforma-readiness" in html
        # The component's React.useEffect calls refresh() — that's the
        # only fetch trigger on load. Write endpoints must NOT appear
        # inside refresh; they appear only inside button onClick handlers.
        # Spot-check: the write paths are reachable but only via Btn
        # onClick (constituent of writeProducts / createCustomer fns).
        for write_path in (
            "/api/v1/wfirma/goods/auto-register/",
            "/api/v1/wfirma/customers/auto-create-from-name",
        ):
            # path appears (used by buttons), but never in `refresh = ...`
            assert write_path in html
            # Ensure it's not inside the refresh body (heuristic check):
            refresh_block = html.split("const refresh = React.useCallback")[1]
            refresh_end = refresh_block.split("}, [batchId, onToast]);")[0]
            assert write_path not in refresh_end, (
                f"write path {write_path!r} reachable from on-mount refresh()"
            )

    def test_buttons_reference_existing_endpoint_paths(self, html):
        for path in (
            "/api/v1/wfirma/goods/auto-register-preview/",
            "/api/v1/wfirma/goods/auto-register/",
            "/api/v1/wfirma/customers/auto-resolve-preview/",
            "/api/v1/wfirma/customers/auto-create-from-name",
        ):
            assert path in html, f"missing endpoint reference: {path}"

    def test_blocked_flag_message_visible(self, html):
        # Phase 3: raw env-var names replaced with human-readable messages.
        # Verify the human-readable form exists and the env-var strings are gone.
        assert "contact your admin" in html, \
            "flag-off message must say 'contact your admin'"
        assert "WFIRMA_CREATE_PRODUCT_ALLOWED" not in html, \
            "WFIRMA_CREATE_PRODUCT_ALLOWED must not appear in the dashboard"
        assert "WFIRMA_CREATE_CUSTOMER_ALLOWED" not in html, \
            "WFIRMA_CREATE_CUSTOMER_ALLOWED must not appear in the dashboard"

    def test_pnd_ambiguity_surfaced(self, html):
        # The bridge ambiguity block uses data-testid for tests
        assert 'data-testid="bridge-ambiguous"' in html

    def test_confirmation_required_for_writes(self, html):
        # Both write paths must go through a confirm() prompt
        assert "Auto-register all missing product codes" in html
        assert "Create wFirma contractor for" in html
