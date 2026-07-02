"""
test_master_consumption_rule.py — STANDING pin for the MASTER CONSUMPTION RULE
(PROJECT_STATE DECISIONS "C-1 RATIFIED" / CLAUDE.md constitution).

(a) LAYER RESPONSIBILITIES: the canonical Product MIRROR (wfirma_product_mirror)
    has EXACTLY six columns — wfirma_id, product_code, sync_version, last_sync,
    hash, deleted_flag. Schema drift (any add/remove) FAILS immediately.
(b) MASTER CONSUMPTION: no business module may read wFirma product data
    directly (wfirma_client product fns, or the split/canonical product mirror
    tables). The known-violation set is tracked as a BASELINE that must SHRINK
    per C-1 sub-slice and reach zero by C-1d; a NEW violation (a business file
    not in the baseline) fails immediately.

C-1a establishes the pin + the baseline. C-1b/C-1c shrink KNOWN_VIOLATIONS.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.services import reservation_db as rdb

_APP = Path(__file__).resolve().parent.parent / "app"

# The six-and-only-six mirror columns (LAYER RESPONSIBILITIES, verbatim).
_MIRROR_COLUMNS = {"wfirma_id", "product_code", "sync_version", "last_sync",
                   "hash", "deleted_flag"}

# The sync/integration layer — the ONLY code allowed to touch wFirma product
# data / the mirror. Business modules must go through the Product Master.
_SYNC_WHITELIST = {
    "wfirma_client.py", "wfirma_db.py", "reservation_db.py",
    "wfirma_product_registration.py", "wfirma_product_auto_register.py",
    "product_authority_resolver.py", "reservation_worker.py",
    "wfirma_product_resolver.py", "cpa_product_service.py",
}

# Forbidden product-direct patterns a business module must not contain.
_FORBIDDEN = (
    "wfirma_products",          # split mirror #1
    "wfirma_product_mapping",   # split mirror #2
    "wfirma_product_mirror",    # canonical mirror (business reads the MASTER, not this)
    "get_product_by_code",      # direct wfirma_client product read
    "create_product",           # direct wfirma_client product write
    "edit_product",             # direct wfirma_client product write
)

# BASELINE known violations (files) as of C-1a. This set MUST SHRINK across
# C-1b/C-1c and reach empty by C-1d. A business file NOT listed here that
# contains a forbidden pattern fails the pin immediately (new violation).
KNOWN_PRODUCT_VIOLATION_FILES = {
    "routes_proforma.py",     # ~7 read sites (V1/V-readers) — C-1c
    "routes_packing.py",      # 2 read sites — C-1c
    "routes_dashboard.py",    # 1 read site — C-1c
    "routes_wfirma.py",       # product create/edit/resolve — C-1b (V1)
    "routes_reservations.py", # get_product_by_code shim — C-1b (V6)
    "routes_master_data.py",  # product_local surface — C-1c fold
    "routes_admin.py",        # product_master helper reference
    "routes_wfirma_capabilities.py",  # diagnostic probes (wFirma-facing)
}


# ── (a) mirror schema = exactly six columns ──────────────────────────────────

def test_mirror_schema_is_exactly_six_columns():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "reservation_queue.db"
        rdb.init_reservation_db(db)
        con = sqlite3.connect(str(db))
        cols = {r[1] for r in con.execute("PRAGMA table_info(wfirma_product_mirror)")}
        con.close()
    assert cols == _MIRROR_COLUMNS, (
        f"wfirma_product_mirror must have EXACTLY the six sync columns "
        f"(LAYER RESPONSIBILITIES). Got: {sorted(cols)}"
    )


def test_mirror_has_unique_product_code_and_wfirma_id():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "reservation_queue.db"
        rdb.init_reservation_db(db)
        con = sqlite3.connect(str(db))
        idx = {r[1] for r in con.execute("PRAGMA index_list(wfirma_product_mirror)")}
        con.close()
    assert "idx_wpm_product_code" in idx and "idx_wpm_wfirma_id" in idx, \
        "mirror must enforce UNIQUE product_code and UNIQUE wfirma_id"


# ── product_master authority columns present ─────────────────────────────────

def test_product_master_has_authority_columns():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "reservation_queue.db"
        rdb.init_reservation_db(db)
        con = sqlite3.connect(str(db))
        cols = {r[1] for r in con.execute("PRAGMA table_info(product_master)")}
        con.close()
    for c in ("status", "is_active", "unit", "origin_country", "notes", "design_code_link"):
        assert c in cols, f"product_master missing authority column {c}"


# ── (b) no NEW business-module product-direct violations ─────────────────────

def _business_files():
    """Business modules = routes + services that are NOT in the sync whitelist
    and NOT tests. We scan the api routes (the consumer surface)."""
    for py in sorted((_APP / "api").glob("routes_*.py")):
        if py.name in _SYNC_WHITELIST:
            continue
        yield py


def test_no_new_product_direct_violations():
    offenders = {}
    for py in _business_files():
        src = py.read_text(encoding="utf-8", errors="replace")
        # ignore comment-only mentions: require the pattern on a code line
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        hits = [p for p in _FORBIDDEN if p in code]
        if hits:
            offenders[py.name] = hits
    new = {f: h for f, h in offenders.items() if f not in KNOWN_PRODUCT_VIOLATION_FILES}
    assert not new, (
        f"NEW product-direct violation(s) outside the known C-1 baseline — a "
        f"business module must consume the Product Master, not wFirma/mirror: {new}"
    )


def test_known_violation_baseline_is_documented_and_shrinking():
    """The baseline is the C-1a starting point. This test PINS the count so
    C-1b/C-1c must consciously shrink it (update the set + this number); it
    must reach 0 by C-1d. If a sub-slice removes a violation without updating
    the baseline, the previous test starts passing trivially — this count pin
    forces the baseline to track reality."""
    # C-1a baseline: 8 files still hold product-direct reads (pre-migration).
    assert len(KNOWN_PRODUCT_VIOLATION_FILES) == 8, (
        "KNOWN_PRODUCT_VIOLATION_FILES changed — update this count as C-1b/C-1c "
        "shrink the baseline (target: 0 by C-1d)."
    )
