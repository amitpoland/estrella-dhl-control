"""
test_master_consumption_rule.py — STANDING pin for the MASTER CONSUMPTION RULE
(PROJECT_STATE DECISIONS "C-1 RATIFIED" / CLAUDE.md constitution).

(a) LAYER RESPONSIBILITIES: the canonical Product MIRROR (wfirma_product_mirror)
    has EXACTLY six columns — wfirma_id, product_code, sync_version, last_sync,
    hash, deleted_flag. Schema drift (any add/remove) FAILS immediately.
(b) MASTER CONSUMPTION: no business module may access wFirma product data
    directly — not via wfirma_client's product functions and not via the
    split/canonical product mirror TABLES. The known-violation set is a BASELINE
    that must SHRINK per C-1 sub-slice and reach zero by C-1d; a NEW violation (a
    business file not in the baseline) fails immediately.

C-1b REFINEMENT (operator-approved 2026-07-03): the detector was crude substring
matching, which false-positived on the gate-flag name (`wfirma_create_product_allowed`
contains `create_product`), on endpoint function identifiers (`wfirma_products_resolve`),
and on docstring prose. It is now PRECISE: comments + docstrings are stripped, and only
REAL access is matched — the client product CALLS and TABLE references. Measured
equivalence at refinement time: the crude and precise detectors flagged the IDENTICAL
6-file set, so this is a precision improvement, not a loosening. A positive-control test
pins that real access is still caught. Baseline corrected to the real offenders (the
C-1a baseline of 8 carried 2 phantom files — routes_master_data / routes_admin — that
never actually violated).

C-1a established the pin + a loose baseline. C-1b refines the detector, reroutes the
routes_wfirma + routes_reservations write paths through the Master, and drops the
baseline to the 4 real remaining offenders. C-1c migrates the readers → 0 by C-1d.
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

# Precise forbidden ACCESS in a business module — real client product calls +
# direct product-table references. Named so failures point at the exact defect.
_PRECISE_PATTERNS = {
    "call:get_product_by_code":   re.compile(r"\.get_product_by_code\s*\("),
    "def:get_product_by_code":    re.compile(r"\bdef\s+get_product_by_code\b"),
    "import:get_product_by_code": re.compile(r"import\s+get_product_by_code\b"),
    "call:create_product":        re.compile(r"\.create_product\s*\("),
    "call:edit_product":          re.compile(r"\.edit_product\s*\("),
    # Table references: the table name NOT followed by an identifier char, so a
    # real table ref (raw SQL / quoted name) matches but function identifiers
    # like `wfirma_products_resolve` / `sync_wfirma_products_by_codes` do NOT.
    "table:wfirma_products":        re.compile(r"\bwfirma_products(?!\w)"),
    "table:wfirma_product_mapping": re.compile(r"\bwfirma_product_mapping(?!\w)"),
    "table:wfirma_product_mirror":  re.compile(r"\bwfirma_product_mirror(?!\w)"),
}

# BASELINE known violations (files) as of C-1b — the REAL remaining offenders
# after routes_wfirma + routes_reservations were rerouted through the Master.
# This set MUST SHRINK across C-1c and reach EMPTY by C-1d. A business file NOT
# listed here that contains a forbidden access fails the pin immediately.
KNOWN_PRODUCT_VIOLATION_FILES = {
    "routes_proforma.py",             # ~7 read sites — C-1c
    "routes_packing.py",              # 2 read sites — C-1c
    "routes_dashboard.py",            # 1 read site — C-1c
    "routes_wfirma_capabilities.py",  # diagnostic probes (wFirma-facing) — C-1c/later
}


def _strip_comments_and_docstrings(src: str) -> str:
    """Remove triple-quoted string blocks (docstrings + triple-quoted literals)
    and # comments, so the detector matches real CODE, not prose. Our patterns
    contain no '#', so a naive inline-comment cut is safe here."""
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    out = []
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        # strip inline comments after any whitespace (space OR tab + '#'); the
        # one-statement-per-line convention makes the string-literal edge moot.
        out.append(re.sub(r"\s+#.*$", "", line))
    return "\n".join(out)


def _precise_hits(src: str) -> list:
    code = _strip_comments_and_docstrings(src)
    return sorted(name for name, rx in _PRECISE_PATTERNS.items() if rx.search(code))


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
    """Business modules = api routes that are NOT in the sync whitelist."""
    for py in sorted((_APP / "api").glob("routes_*.py")):
        if py.name in _SYNC_WHITELIST:
            continue
        yield py


def test_no_new_product_direct_violations():
    offenders = {}
    for py in _business_files():
        hits = _precise_hits(py.read_text(encoding="utf-8", errors="replace"))
        if hits:
            offenders[py.name] = hits
    new = {f: h for f, h in offenders.items() if f not in KNOWN_PRODUCT_VIOLATION_FILES}
    assert not new, (
        f"NEW product-direct violation(s) outside the known C-1 baseline — a "
        f"business module must consume the Product Master, not wFirma/mirror: {new}"
    )


def test_rerouted_files_have_left_the_baseline():
    """C-1b acceptance: routes_wfirma + routes_reservations no longer contain any
    direct wFirma product access (they now go through the reservation_db
    sync-layer helpers). This pins the reroute so a regression is caught."""
    for name in ("routes_wfirma.py", "routes_reservations.py"):
        hits = _precise_hits((_APP / "api" / name).read_text(encoding="utf-8", errors="replace"))
        assert not hits, (
            f"{name} still has direct wFirma product access {hits} — C-1b "
            f"requires it to consume the Product Master via reservation_db helpers."
        )
        assert name not in KNOWN_PRODUCT_VIOLATION_FILES, \
            f"{name} was rerouted in C-1b and must not be in the baseline."


def test_known_violation_baseline_is_documented_and_shrinking():
    """The baseline is the C-1b starting point of REAL remaining offenders. This
    PINS the count so C-1c must consciously shrink it (update the set + this
    number); it must reach 0 by C-1d."""
    # C-1b baseline: 4 real business files still hold product-direct reads.
    # (The C-1a baseline of 8 carried 2 phantom files that never violated; the
    #  2 rerouted files left in C-1b.)
    assert len(KNOWN_PRODUCT_VIOLATION_FILES) == 4, (
        "KNOWN_PRODUCT_VIOLATION_FILES changed — update this count as C-1c "
        "shrinks the baseline (target: 0 by C-1d)."
    )


# ── positive control: the precise detector is NOT blind ──────────────────────

def test_precise_detector_positive_control():
    """Prove the refinement did not create a blind spot: a synthetic business
    source containing real direct access IS flagged for every access class, and
    a benign source (gate-flag reference, function identifier, docstring prose)
    is NOT flagged."""
    bad = (
        'x = wfirma_client.get_product_by_code(pc)\n'
        'y = wfirma_client.create_product(a=1)\n'
        'z = wfirma_client.edit_product(id="1")\n'
        'rows = con.execute("SELECT * FROM wfirma_products")\n'
        'con.execute("INSERT INTO wfirma_product_mapping VALUES (1)")\n'
        'con.execute("DELETE FROM wfirma_product_mirror")\n'
        'def get_product_by_code(code): ...\n'
        'from x import get_product_by_code\n'
    )
    hits = _precise_hits(bad)
    for expected in _PRECISE_PATTERNS:
        assert expected in hits, f"positive control failed to flag {expected}"

    benign = (
        '"""This endpoint calls wfirma_client.create_product for wfirma_products."""\n'
        'if not settings.wfirma_create_product_allowed:  # gate flag, not a call\n'
        '    return\n'
        'async def wfirma_products_resolve(): ...\n'
        'result = rworker.sync_wfirma_products_by_codes(db, client, codes)\n'
        'row = rdb.upsert_product_master(db, product_code=pc)\n'
    )
    assert _precise_hits(benign) == [], (
        "benign source (gate flag + function identifiers + docstring prose) must "
        "NOT be flagged by the precise detector"
    )
