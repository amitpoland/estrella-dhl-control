"""
test_infra_hardening_pragmas.py — infra health pass d67d3722 findings #2+#3.

(#2) The four DB modules with FastAPI-handler AND APScheduler writers but no
lock protection now connect via a tuned _connect (dhl_thread_lock idiom,
dhl_thread_lock.py:126-129): timeout=30.0 + PRAGMA busy_timeout=10000 set
BEFORE PRAGMA journal_mode=WAL (so the WAL flip itself waits out a competing
writer). WAL is persistent per file; busy_timeout is per-connection.

(#3) routes_dhl_clearance._write_scan_status called write_json_atomic with
NO import — every lane-a status write failed with a swallowed NameError
(live prod WARNING 2026-07-02 14:06). Fixed with the file's local-import
idiom; pinned here end-to-end.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from app.services import customer_master_db as cmdb
from app.services import proforma_invoice_link_db as plink
from app.services import wfirma_payment_db as wpay
from app.services import wfirma_contractor_poll_db as wpoll

_MODULES = [
    # (module, init function, db filename)
    pytest.param(cmdb,  cmdb.init_db,                "customer_master.sqlite", id="customer_master"),
    pytest.param(plink, plink.init_db,               "proforma_links.db",      id="proforma_links"),
    pytest.param(wpay,  wpay.init_payment_db,        "payment_state.db",       id="payment_state"),
    pytest.param(wpoll, wpoll.init_contractor_poll_db, "contractor_poll.db",   id="contractor_poll"),
]


# ── #2a: WAL persistent + busy_timeout per connection ────────────────────────

@pytest.mark.parametrize("mod,init_fn,fname", _MODULES)
def test_init_flips_file_to_wal_persistently(mod, init_fn, fname, tmp_path):
    db = tmp_path / fname
    init_fn(db)
    # Persistent: a PLAIN sqlite3 connection (no pragmas) must see WAL,
    # because journal_mode=WAL is a property of the FILE once flipped.
    con = sqlite3.connect(str(db))
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        con.close()
    # Header cross-check: bytes 18-19 == 2/2 (WAL read/write version)
    hdr = db.read_bytes()[:100]
    assert (hdr[18], hdr[19]) == (2, 2), "SQLite header must show WAL versions"


@pytest.mark.parametrize("mod,init_fn,fname", _MODULES)
def test_module_connect_sets_busy_timeout_10000(mod, init_fn, fname, tmp_path):
    db = tmp_path / fname
    init_fn(db)
    con = mod._connect(db)
    try:
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        con.close()


def test_proforma_link_connect_supports_deferred_isolation(tmp_path):
    """The two isolation_level='DEFERRED' sites (:1200, :1971 pre-fix) route
    through the same tuned helper — semantics preserved."""
    db = tmp_path / "proforma_links.db"
    plink.init_db(db)
    con = plink._connect(db, isolation_level="DEFERRED")
    try:
        assert con.isolation_level == "DEFERRED"
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
    finally:
        con.close()


# ── #2b: drop-can't-return pin — no bare connects outside the helper ─────────

@pytest.mark.parametrize("mod,init_fn,fname", _MODULES)
def test_no_bare_connect_outside_helper(mod, init_fn, fname):
    from pathlib import Path
    src = Path(mod.__file__).read_text(encoding="utf-8", errors="replace")
    calls = [ln for ln in src.splitlines()
             if "sqlite3.connect(" in ln and not ln.strip().startswith("#")
             and "sqlite3.connect's own" not in ln]   # docstring mention
    assert len(calls) == 1, (
        f"{mod.__name__} must have exactly ONE sqlite3.connect (inside "
        f"_connect); found {len(calls)}: a bare connect would bypass "
        f"WAL/busy_timeout — infra finding #2 regression"
    )
    assert "timeout=30.0" in calls[0]


# ── #3: lane-a status write NameError regression ─────────────────────────────

def test_write_scan_status_no_nameerror_and_atomic(tmp_path, monkeypatch, caplog):
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "storage_root", tmp_path)
    from app.api.routes_dhl_clearance import _write_scan_status, _scan_status_path

    payload = {"state": "idle", "last_run": "2026-07-03T00:00:00+00:00"}
    with caplog.at_level("WARNING"):
        _write_scan_status(payload)

    # The pre-fix behavior was a swallowed NameError -> WARNING + no file.
    assert not [r for r in caplog.records
                if "status write failed" in r.getMessage()], \
        "lane-a status write must no longer fail (was: NameError, d67d3722 #3)"
    out = _scan_status_path()
    assert out.exists(), "status file must be written"
    assert json.loads(out.read_text(encoding="utf-8")) == payload
    # Atomic pattern: write_json_atomic leaves no stray TMP FILE behind.
    # (Other modules create side-effect DIRECTORIES under storage_root —
    # dsk_outputs/, polish_descriptions/, … — those are not residue of this
    # write; only files related to the status path count.)
    stray = [p for p in tmp_path.iterdir()
             if p.is_file() and p.name != out.name]
    assert not stray, f"atomic write must leave no temp-file residue: {stray}"


def test_write_scan_status_has_the_import():
    """Source pin: the local import exists inside _write_scan_status (the
    file's idiom); a refactor that drops it re-introduces the silent
    NameError."""
    from pathlib import Path
    import app.api.routes_dhl_clearance as rdc
    src = Path(rdc.__file__).read_text(encoding="utf-8", errors="replace")
    k = src.index("def _write_scan_status(")
    body = src[k:k + 800]
    assert "from ..utils.io import write_json_atomic" in body, \
        "the missing-import fix must stay inside _write_scan_status"
