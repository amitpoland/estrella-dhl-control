"""
test_product_master_authority.py — PRODUCT MASTER CHARTER: authority enforcement.

Machine-enforced companion to the sealed Product Master Charter. Product Master is
SEALED and CONSUME-ONLY. This file pins AUTHORITY (classified by role, not just
filenames, so a future package move updates ONE declaration):

  1. WRITE authority   — only approved authorities write product_master.
  2. IDENTITY authority — only Purchase Import + Sync may modify identity FIELDS
                          (protects the identity model, not just the table).
  3. NO UPWARD DEPENDENCY — consumer domains must not import Product Master
                          write internals; they consume the read API only.
  4. DESCRIPTION single writer — only description_engine writes product_descriptions.

Complements (does NOT duplicate):
  * test_master_consumption_rule.py — READ authority (no business module reads
    wFirma/mirror for product data; mirror = 6 columns).
  * test_product_master_foundation.py — product_code minted only by
    store_invoice_lines.

Detection is comment/docstring-stripped, so prose is never mistaken for code.
"""
from __future__ import annotations

import re
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "app"

# ── Writers classified by AUTHORITY (not a flat filename list) ───────────────
# These are the DIRECT writers of product_master (callers of upsert_product_master
# / set_product_master_status / raw SQL). The Purchase Import ROUTES
# (routes_intake.py, routes_packing.py) and product_master_sync.py are NOT direct
# writers — they write THROUGH the CPA boundary
# (cpa_product_service.upsert_product_master_from_packing) — so only the boundary
# appears here. To move a module to another package, update its authority set below.
_WRITE_AUTHORITIES = {
    "Product Master Owner":               {"reservation_db.py"},
    "CPA Write Boundary (Import + Sync)":  {"cpa_product_service.py"},
    "Purchase Import (direct)":            {"reservation_worker.py", "document_db.py"},
    "wFirma Product Registration (C-1b)":  {"routes_wfirma.py"},
    "Approved Maintenance":                {"product_master_backfill.py"},
}
_PM_WRITE_ALLOWLIST = set().union(*_WRITE_AUTHORITIES.values())

# Raw SQL to product_master is stricter: owner + backfill only.
_PM_DIRECT_SQL_ALLOWLIST = {"reservation_db.py", "product_master_backfill.py"}

# product_descriptions writers: description_engine is THE authority; document_db
# owns the table + the upsert accessor.
_DESC_WRITE_ALLOWLIST = {"description_engine.py", "document_db.py"}

# Identity fields — the business/physical model. Only Purchase Import + Sync may
# modify these (via upsert_product_master / raw SQL). Sync-state fields (status,
# is_active, last_sync, timestamps) are deliberately NOT identity.
_IDENTITY_FIELDS = (
    "product_code", "design_no", "item_type", "karat", "metal", "metal_color",
    "quality_string", "stone_type", "size", "diamond_weight", "color_weight",
    "normalized_design_attributes", "hsn_code", "supplier_id",
    "supplier_product_code",
)

# Consumer domains — pure readers. Must not WRITE the Master, and must not IMPORT
# its write internals (upward dependency = architectural erosion).
_CONSUMER_DOMAIN_SUBSTRINGS = (
    "inventory", "warehouse", "analytics", "dashboard", "tally", "ledger",
)
# Forbidden write-side internals for consumers to import (reads via
# reservation_db.get_product_master remain the allowed public consumption path).
_PM_WRITE_INTERNALS = ("cpa_product_service", "product_master_sync")

_PM_WRITE = re.compile(
    r"\bupsert_product_master\s*\(|\bset_product_master_status\s*\("
    r"|\b(?:INSERT\s+INTO|UPDATE)\s+product_master\b"
)
# Identity write = upsert_product_master (sets identity fields) or raw SQL.
# Excludes set_product_master_status (sync-state only).
_PM_IDENTITY_WRITE = re.compile(
    r"\bupsert_product_master\s*\(|\b(?:INSERT\s+INTO|UPDATE)\s+product_master\b"
)
_PM_SQL = re.compile(r"\b(?:INSERT\s+INTO|UPDATE)\s+product_master\b")
_DESC_WRITE = re.compile(
    r"\bupsert_product_description\s*\("
    r"|\b(?:INSERT\s+INTO|UPDATE)\s+product_descriptions\b"
)


def _strip(src: str) -> str:
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    out = []
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(re.sub(r"\s+#.*$", "", line))
    return "\n".join(out)


def _writers(rx: re.Pattern) -> set:
    hit = set()
    for py in _APP.rglob("*.py"):
        if rx.search(_strip(py.read_text(encoding="utf-8", errors="replace"))):
            hit.add(py.name)
    return hit


# ── 1. WRITE authority ───────────────────────────────────────────────────────

def test_only_approved_authorities_write_product_master():
    writers = _writers(_PM_WRITE)
    unexpected = writers - _PM_WRITE_ALLOWLIST
    assert not unexpected, (
        f"NEW product_master writer(s) outside the sealed Charter authorities "
        f"{list(_WRITE_AUTHORITIES)}: {sorted(unexpected)}. Product Master is "
        f"CONSUME-ONLY — route the write through the CPA boundary / Sync, or file "
        f"a Charter amendment."
    )


def test_consumer_domains_never_write_product_master():
    bad = sorted(f for f in _writers(_PM_WRITE)
                 if any(s in f for s in _CONSUMER_DOMAIN_SUBSTRINGS))
    assert not bad, (
        f"CONSUMER-domain file writes Product Master (Charter violation): {bad}. "
        f"These modules must READ the Master, never write it."
    )


def test_direct_product_master_sql_only_in_owner_and_backfill():
    unexpected = _writers(_PM_SQL) - _PM_DIRECT_SQL_ALLOWLIST
    assert not unexpected, (
        f"direct product_master SQL outside owner/backfill: {sorted(unexpected)} "
        f"— all writes must go through reservation_db accessors."
    )


def test_write_authority_allowlist_has_no_stale_entry():
    """Every allowlisted writer must really write — a stale entry could mask a
    new writer after a rename."""
    stale = _PM_WRITE_ALLOWLIST - _writers(_PM_WRITE)
    assert not stale, (
        f"authority allowlist names {sorted(stale)} as writer(s) but they no "
        f"longer write product_master — prune the declaration."
    )


# ── 2. IDENTITY authority (protects the model, not just the table) ───────────

def test_identity_fields_written_only_by_import_or_sync():
    writers = _writers(_PM_IDENTITY_WRITE)
    unexpected = writers - _PM_WRITE_ALLOWLIST
    assert not unexpected, (
        f"module {sorted(unexpected)} modifies Product Master IDENTITY fields "
        f"{_IDENTITY_FIELDS[:4]}… outside Purchase Import + Sync. Identity is the "
        f"canonical model — only those two authorities may change it."
    )


# ── 3. NO UPWARD DEPENDENCY (prevents architectural erosion) ─────────────────

def test_consumer_domains_do_not_import_write_internals():
    bad = {}
    for py in _APP.rglob("*.py"):
        if not any(s in py.name for s in _CONSUMER_DOMAIN_SUBSTRINGS):
            continue
        code = _strip(py.read_text(encoding="utf-8", errors="replace"))
        for line in code.splitlines():
            if "import" not in line:
                continue
            for mod in _PM_WRITE_INTERNALS:
                if re.search(rf"\b{mod}\b", line):
                    bad.setdefault(py.name, set()).add(mod)
    bad = {k: sorted(v) for k, v in bad.items()}
    assert not bad, (
        f"CONSUMER domain imports Product Master WRITE internals {bad} — consume "
        f"the read API (reservation_db.get_product_master / list_product_masters) "
        f"only; never the write path."
    )


# ── 4. DESCRIPTION single writer ─────────────────────────────────────────────

def test_product_description_single_writer():
    unexpected = _writers(_DESC_WRITE) - _DESC_WRITE_ALLOWLIST
    assert not unexpected, (
        f"NEW product_descriptions writer(s): {sorted(unexpected)}. "
        f"description_engine is the SINGLE Description authority."
    )


# ── positive / negative controls ─────────────────────────────────────────────

def test_detectors_positive_and_negative_control():
    assert _PM_WRITE.search("rdb.upsert_product_master(db, pc)")
    assert _PM_WRITE.search("upsert_product_master(db, product_code=pc)")
    assert _PM_WRITE.search("con.execute('UPDATE product_master SET x=1')")
    assert _PM_IDENTITY_WRITE.search("upsert_product_master(db, pc)")
    assert _DESC_WRITE.search("ddb.upsert_product_description(product_code=pc)")
    # boundary indirection + status-only + reads + prose are NOT identity writes
    assert not _PM_WRITE.search("cpa.upsert_product_master_from_packing(db, b, rows)")
    assert not _PM_IDENTITY_WRITE.search("rdb.set_product_master_status(db, pc, 'x')")
    assert not _PM_WRITE.search("row = rdb.get_product_master(db, pc)")
    assert not _PM_WRITE.search('msg = "product_master is the canonical catalog"')
