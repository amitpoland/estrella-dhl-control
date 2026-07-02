"""
test_master_consumption_rule.py — STANDING pin for the MASTER CONSUMPTION RULE
(PROJECT_STATE DECISIONS "C-1 RATIFIED" / the Phase-C Constitution §2, §15).

(a) LAYER RESPONSIBILITIES: the canonical Product MIRROR (wfirma_product_mirror)
    has EXACTLY six columns — wfirma_id, product_code, sync_version, last_sync,
    hash, deleted_flag. Schema drift (any add/remove) FAILS immediately.
(b) MASTER CONSUMPTION: no business module may ACCESS wFirma product data
    directly. The known-violation set is a BASELINE that shrinks per C-1 sub-slice
    and must reach the declared residual (the write slices) by C-1d; a NEW
    violation (a business file not in the baseline) fails immediately.

C-1c REFINEMENT (operator-ruled 2026-07-03): the detector measures REAL
product-authority ACCESS only. It does NOT count prose strings or status messages
(the prior `table:` substring proxy false-positived on messages like
"not in wfirma_products"). After stripping comments + docstrings, a business file
is a violation iff it contains:
 (a) SQL targeting a split product table — FROM/JOIN/INTO/UPDATE wfirma_products
     (or _mapping / _mirror). Real SQL, never a substring inside a status string.
 (b) a wfirma_db split-cache accessor call — .get_product( / .get_products_batch(
     / .list_products( / .upsert_product( .
 (c) a direct wFirma product API call — .get_product_by_code( / .create_product(
     / .edit_product( .
The Product MASTER accessors (reservation_db.get_product_master /
list_product_masters) are the CORRECT path and are NOT matched.

ANTI-GAMING RULE (operator-ruled): editing string literals / prose / status keys
to change pin counts is FORBIDDEN. The detector ignores prose by construction; the
rule makes gaming a violation. The migration is to route reads through the Product
Master (reservation_db accessors), never to reword messages.
"""
from __future__ import annotations

import re
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

# REAL product-authority access (matched on comment/docstring-stripped code).
_REAL_ACCESS_PATTERNS = {
    # (a) SQL touching the split product tables — real SQL keywords, not prose.
    "sql:wfirma_products":        re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+wfirma_products\b"),
    "sql:wfirma_product_mapping": re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+wfirma_product_mapping\b"),
    "sql:wfirma_product_mirror":  re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+wfirma_product_mirror\b"),
    # (b) wfirma_db split-cache accessor calls.
    "acc:get_product":         re.compile(r"\.get_product\s*\("),
    "acc:get_products_batch":  re.compile(r"\.get_products_batch\s*\("),
    "acc:list_products":       re.compile(r"\.list_products\s*\("),
    "acc:upsert_product":      re.compile(r"\.upsert_product\s*\("),
    # (c) direct wFirma product API calls.
    "api:get_product_by_code": re.compile(r"\.get_product_by_code\s*\("),
    "api:create_product":      re.compile(r"\.create_product\s*\("),
    "api:edit_product":        re.compile(r"\.edit_product\s*\("),
}

# BASELINE known violations (files) as of C-1c STAGE 0 — the HONEST real-access
# set measured by the refined detector. This SHRINKS across C-1c STAGE 1 (read
# migrations) and reaches the declared residual (the write slices) by C-1d.
# NOTE: routes_wfirma.py re-appears here — C-1b removed its wFirma CLIENT calls
# but intentionally LEFT its wfirma_db accessor reads/writes as the
# "C-1c-deprecating reader path"; the refined detector now measures them.
KNOWN_PRODUCT_VIOLATION_FILES = {
    "routes_wfirma_capabilities.py",  # reads + writes (create/adopt) — write slice
    "routes_proforma.py",             # ~12 reads (C-1c) + 1 write @4527 (write slice)
    "routes_wfirma.py",               # 5 wfdb reads + 3 upsert writes (residual)
    "routes_packing.py",              # 1 SQL read — C-1c STAGE 1b
    # routes_dashboard.py — MIGRATED to the Product Master in C-1c STAGE 1a.
}


def _strip_comments_and_docstrings(src: str) -> str:
    """Remove triple-quoted blocks + # comments so the detector matches real CODE,
    not prose. Tab- and space-prefixed inline comments are both handled."""
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    out = []
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(re.sub(r"\s+#.*$", "", line))
    return "\n".join(out)


def _real_access_hits(src: str) -> list:
    code = _strip_comments_and_docstrings(src)
    return sorted(name for name, rx in _REAL_ACCESS_PATTERNS.items() if rx.search(code))


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
    for py in sorted((_APP / "api").glob("routes_*.py")):
        if py.name in _SYNC_WHITELIST:
            continue
        yield py


def test_no_new_product_direct_violations():
    offenders = {}
    for py in _business_files():
        hits = _real_access_hits(py.read_text(encoding="utf-8", errors="replace"))
        if hits:
            offenders[py.name] = hits
    new = {f: h for f, h in offenders.items() if f not in KNOWN_PRODUCT_VIOLATION_FILES}
    assert not new, (
        f"NEW product-direct access outside the known baseline — a business module "
        f"must consume the Product Master, not wFirma/mirror/split-cache: {new}"
    )


def test_reservations_router_stays_clean():
    """C-1b rerouted routes_reservations off direct wFirma product access; the
    refined detector must confirm it stays clean (no SQL/accessor/API access)."""
    hits = _real_access_hits((_APP / "api" / "routes_reservations.py").read_text(encoding="utf-8"))
    assert not hits, f"routes_reservations.py regressed to direct product access: {hits}"
    assert "routes_reservations.py" not in KNOWN_PRODUCT_VIOLATION_FILES


def test_known_violation_baseline_is_documented_and_shrinking():
    """C-1c STAGE 0 honest baseline = 5 files with REAL product-authority access.
    STAGE 1 read-migrations shrink this (update the set + this count); the end
    state is the declared residual (proforma write, capabilities write path,
    routes_wfirma reads+writes)."""
    assert len(KNOWN_PRODUCT_VIOLATION_FILES) == 4, (
        "KNOWN_PRODUCT_VIOLATION_FILES changed — update this count as C-1c STAGE 1 "
        "migrates packing/proforma reads (dashboard done in 1a)."
    )


# ── positive control: real access flagged, prose NOT flagged ─────────────────

def test_real_access_detector_positive_control():
    real = (
        'rows = con.execute("SELECT product_code FROM wfirma_products WHERE x=?")\n'   # (a)
        'con.execute("INSERT INTO wfirma_product_mapping VALUES (1)")\n'               # (a)
        'con.execute("UPDATE wfirma_product_mirror SET x=1")\n'                        # (a)
        'p = wfdb.get_product(pc)\n'                                                   # (b)
        'm = wfdb.get_products_batch(codes)\n'                                         # (b)
        'l = wfdb.list_products()\n'                                                   # (b)
        'wfdb.upsert_product(product_code=pc)\n'                                       # (b)
        'x = wfirma_client.get_product_by_code(pc)\n'                                  # (c)
        'y = wfirma_client.create_product(a=1)\n'                                      # (c)
        'z = wfirma_client.edit_product(id="1")\n'                                     # (c)
    )
    hits = _real_access_hits(real)
    for expected in _REAL_ACCESS_PATTERNS:
        assert expected in hits, f"positive control failed to flag {expected}"


def test_prose_and_master_reads_not_flagged():
    benign = (
        '"""readiness: product_code(s) not resolved in wfirma_products."""\n'
        'msg = f"{n} product(s) not matched in wfirma_products"\n'      # status string
        'if "wfirma_products" in reason_key:  # status-key comparison\n'
        '    pass\n'
        'blocked["wfirma_products_missing"] = codes\n'                  # dict key
        'row = rdb.get_product_master(db, pc)\n'                        # MASTER read (allowed)
        'rows = rdb.list_product_masters(db)\n'                         # MASTER read (allowed)
    )
    assert _real_access_hits(benign) == [], (
        "prose / status keys / Product Master reads must NOT be flagged by the "
        "real-access detector"
    )
