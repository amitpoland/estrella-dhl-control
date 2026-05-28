"""test_master_jewelry_source_grep.py — Phase 3 ownership invariants.

Hard-pinned rules for the three new entities:

  - Only metals_db.py / stones_db.py / warehouses_db.py may issue
    INSERT/UPDATE/DELETE statements against their own tables.
  - No wFirma / PZ / DHL / proforma / FX engine module may import any of
    the three new DB modules (Lesson F authority isolation).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


SERVICE_DIR = Path(__file__).resolve().parents[1] / "app"
SERVICES_DIR = SERVICE_DIR / "services"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ── Ownership: writes to (metals|stones|warehouses) only inside their DB module

OWNERSHIP = {
    "metals":     "metals_db.py",
    "stones":     "stones_db.py",
    "warehouses": "warehouses_db.py",
}

# Regex for write statements naming the table (table-name boundary on both sides).
def _writes_to(table: str) -> re.Pattern:
    return re.compile(
        rf"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+{table}\b",
        re.IGNORECASE,
    )


@pytest.mark.parametrize("table,owner_filename", sorted(OWNERSHIP.items()))
def test_only_owner_module_writes_to_table(table, owner_filename):
    pat = _writes_to(table)
    offenders = []
    for py in SERVICE_DIR.rglob("*.py"):
        # Exclude the owner module by filename.
        if py.name == owner_filename:
            continue
        # Exclude test files (this test itself contains regex literals).
        if "tests" in py.parts:
            continue
        src = _read(py)
        if pat.search(src):
            offenders.append(str(py.relative_to(SERVICE_DIR.parent.parent)))
    assert not offenders, (
        f"Table '{table}' may only be written to from {owner_filename}; "
        f"found writes in: {offenders}"
    )


# ── Authority isolation: forbidden importers of new DB modules ──────────────

NEW_MODULES = ("metals_db", "stones_db", "warehouses_db")

FORBIDDEN_DOMAINS = (
    # wFirma / external accounting authority
    "wfirma",
    # PZ / landed-cost engine
    "pz_",
    "import_pz_",
    "global_pz_",
    "pz_correction_",
    # DHL / customs
    "dhl_",
    "agency_",
    "customs_",
    "zc429",
    "sad_",
    # Proforma
    "proforma",
    "sales_",
    # FX engine (NBP-backed)
    "freight_resolver", "freight_authority", "freight_history_db",
    # Inventory writers — Phase 3 warehouses are reference, not state.
    "inventory_state_engine", "inventory_batch_state",
    "inventory_location_writer", "inventory_returns_writer",
    "inventory_sample_writer", "inventory_stage2_aggregator",
)


def _is_forbidden(stem: str) -> bool:
    return any(stem == d or stem.startswith(d) for d in FORBIDDEN_DOMAINS)


@pytest.mark.parametrize("mod", NEW_MODULES)
def test_forbidden_domain_does_not_import_new_db(mod):
    # Match either `from .services.<mod>` / `from ..services.<mod>` /
    # `import ...<mod>` style.
    needle = re.compile(rf"\b{mod}\b")
    offenders = []
    for py in SERVICE_DIR.rglob("*.py"):
        stem = py.stem
        if not _is_forbidden(stem):
            continue
        src = _read(py)
        if needle.search(src):
            offenders.append(str(py.relative_to(SERVICE_DIR.parent.parent)))
    assert not offenders, (
        f"Forbidden import of {mod}: {offenders}. "
        "Phase 3 entities must remain authority-isolated from wFirma/PZ/DHL/"
        "proforma/FX/inventory-state domains."
    )


# ── New DB modules MUST live in their own files (not in master_data_db.py) ──

def test_master_data_db_does_not_grow_to_include_new_entities():
    src = _read(SERVICES_DIR / "master_data_db.py")
    for forbidden in ("CREATE TABLE IF NOT EXISTS metals",
                       "CREATE TABLE IF NOT EXISTS stones",
                       "CREATE TABLE IF NOT EXISTS warehouses"):
        assert forbidden not in src, (
            f"master_data_db.py must not contain '{forbidden}'. "
            "Phase 3 entities have their own DB modules by design."
        )


def test_each_new_db_module_owns_its_own_storage_file():
    """Cross-check: each DB module's CREATE TABLE uses the matching table
    name and is the only place declaring that schema."""
    metals  = _read(SERVICES_DIR / "metals_db.py")
    stones  = _read(SERVICES_DIR / "stones_db.py")
    whouses = _read(SERVICES_DIR / "warehouses_db.py")
    assert "CREATE TABLE IF NOT EXISTS metals"     in metals
    assert "CREATE TABLE IF NOT EXISTS stones"     in stones
    assert "CREATE TABLE IF NOT EXISTS warehouses" in whouses
    # And NOT the other way around.
    assert "CREATE TABLE IF NOT EXISTS stones"     not in metals
    assert "CREATE TABLE IF NOT EXISTS warehouses" not in stones
    assert "CREATE TABLE IF NOT EXISTS metals"     not in whouses
