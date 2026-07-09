"""WF-3 Slice 2B-1 — read-only reservation customer-resolution parity harness.

Covers every classification (agree / id_only_resolves / name_only_resolves /
diverge_id_vs_name / no_selection / unresolved), the critical BLOCK rule (any
diverge blocks Slice 2B-2), read-only safety (no DB modified during a run), the
API envelope, and authority separation (no writes, no wFirma API, no reservation
create in the harness).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import reservation_customer_parity as rcp  # noqa: E402
from app.services import wfirma_db as wfdb                    # noqa: E402
from app.services import customer_master_db                   # noqa: E402
from app.main import app                                      # noqa: E402
from app.core.security import require_api_key                 # noqa: E402


# ── pure classification ──────────────────────────────────────────────────────

class TestClassify:
    def test_no_selection(self):
        assert rcp.classify("", "999", False) == rcp.C_NO_SELECTION

    def test_agree(self):
        assert rcp.classify("100", "100", True) == rcp.C_AGREE

    def test_diverge(self):
        assert rcp.classify("100", "999", True) == rcp.C_DIVERGE

    def test_id_only(self):
        assert rcp.classify("100", "", True) == rcp.C_ID_ONLY

    def test_name_only(self):
        assert rcp.classify("500", "777", False) == rcp.C_NAME_ONLY

    def test_unresolved(self):
        assert rcp.classify("404", "", False) == rcp.C_UNRESOLVED


# ── integration ──────────────────────────────────────────────────────────────

@pytest.fixture
def stores(tmp_path):
    cm = tmp_path / "customer_master.sqlite"
    res = tmp_path / "reservation_queue.db"
    wf = tmp_path / "wfirma.db"
    customer_master_db.init_db(cm)
    wfdb.init_wfirma_db(wf)
    return {"cm": cm, "res": res, "wf": wf}


def _draft(batch, name, cid=""):
    wfdb.upsert_reservation_draft(batch, name, client_contractor_id=cid)


def _legacy(name, wid):
    wfdb.upsert_customer(name, wfirma_customer_id=wid)


def _master(cm, cid, name):
    customer_master_db.upsert_identity_only(cm, bill_to_contractor_id=cid,
                                            bill_to_name=name, country="PL")


def _run(stores, batch_id=None):
    return rcp.run_reservation_parity(batch_id=batch_id, wfirma_db_path=stores["wf"],
                                      cm_path=stores["cm"], res_path=stores["res"])


class TestIntegration:

    def test_agree(self, stores):
        _master(stores["cm"], "100", "Acme")
        _legacy("Acme", "100")               # name resolves to the SAME id
        _draft("B1", "Acme", cid="100")
        rep = _run(stores)
        assert rep["counts"][rcp.C_AGREE] == 1 and rep["blocked"] is False

    def test_diverge_blocks(self, stores):
        _master(stores["cm"], "100", "Acme")
        _legacy("Acme", "999")               # name resolves to a DIFFERENT id
        _draft("B1", "Acme", cid="100")
        rep = _run(stores)
        assert rep["counts"][rcp.C_DIVERGE] == 1
        assert rep["blocked"] is True                          # critical rule
        assert rep["diverge_details"][0]["selected_contractor_id"] == "100"
        assert rep["diverge_details"][0]["name_resolved_id"] == "999"

    def test_id_only(self, stores):
        _master(stores["cm"], "100", "Acme")
        _draft("B1", "NoLegacyName", cid="100")   # id resolves; name has no legacy row
        rep = _run(stores)
        assert rep["counts"][rcp.C_ID_ONLY] == 1 and rep["blocked"] is False

    def test_name_only(self, stores):
        _legacy("Acme", "777")                # name resolves
        _draft("B1", "Acme", cid="500")       # cid 500 not in master/mirror/legacy
        rep = _run(stores)
        assert rep["counts"][rcp.C_NAME_ONLY] == 1

    def test_no_selection(self, stores):
        _draft("B1", "Acme", cid="")          # no contractor.id on the draft
        rep = _run(stores)
        assert rep["counts"][rcp.C_NO_SELECTION] == 1

    def test_unresolved(self, stores):
        _draft("B1", "GhostName", cid="404")  # neither id nor name resolves
        rep = _run(stores)
        assert rep["counts"][rcp.C_UNRESOLVED] == 1

    def test_batch_filter(self, stores):
        _master(stores["cm"], "100", "Acme")
        _legacy("Acme", "100")
        _draft("B1", "Acme", cid="100")
        _draft("B2", "Acme", cid="100")
        assert _run(stores, batch_id="B1")["total"] == 1
        assert _run(stores)["total"] == 2

    def test_run_is_read_only(self, stores):
        _master(stores["cm"], "100", "Acme")
        _legacy("Acme", "100")
        _draft("B1", "Acme", cid="100")
        before = stores["wf"].stat().st_mtime_ns, stores["wf"].stat().st_size
        _run(stores); _run(stores)
        after = stores["wf"].stat().st_mtime_ns, stores["wf"].stat().st_size
        assert before == after                # no write to wfirma.db during runs


# ── API envelope ─────────────────────────────────────────────────────────────

app.dependency_overrides[require_api_key] = lambda: None
client = TestClient(app)


class TestApi:
    def test_endpoint_read_only_get_only(self):
        r = client.get("/api/v1/wfirma/reservation-parity")
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("generated_at", "total", "counts", "blocked", "drafts"):
            assert k in data
        for c in rcp.CLASSES:
            assert c in data["counts"]

    def test_endpoint_rejects_writes(self):
        for m in ("post", "put", "patch", "delete"):
            rr = getattr(client, m)("/api/v1/wfirma/reservation-parity")
            assert rr.status_code in (404, 405)


# ── authority separation ─────────────────────────────────────────────────────

class TestAuthoritySeparation:
    def test_harness_has_no_writes_or_wfirma_calls(self):
        src = inspect.getsource(rcp)
        for forbidden in (
            "INSERT INTO", "UPDATE ", "DELETE FROM", ".commit(",
            "create_reservation(", "create_customer(", "search_customer(",
            "fetch_contractor_by_id(", "wfirma_client",
            "upsert_customer(", "upsert_reservation",
        ):
            assert forbidden not in src, f"parity harness contains forbidden op: {forbidden}"

    def test_reads_use_query_only(self):
        assert "PRAGMA query_only=ON" in inspect.getsource(rcp)
