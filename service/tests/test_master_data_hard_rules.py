"""test_master_data_hard_rules.py — hard-rule contract test suite.

These are source-grep guards that protect the Master Data module from
silently violating campaign hard rules. Every test is read-only: it inspects
file contents on disk and asserts properties without running any service.

Hard rules guarded here:
  1. FX reference table not read by PZ engine
  2. VAT config not used in wFirma posting yet
  3. Carrier Config not used by live DHL shipment creation
  4. Master Data local CRUD does not touch proforma posting
  5. No `.env` writes from the master-data layer
  6. No storage DB files committed to git
  7. Credentials never stored in master-data tables
  8. Single allow-list contract on write methods in MasterDataPage
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SVC_ROOT  = Path(__file__).resolve().parents[1]
_APP_ROOT  = _SVC_ROOT / "app"
_DASH      = _APP_ROOT / "static" / "dashboard.html"


def _read(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"file not present: {p}")
    return p.read_text(encoding="utf-8", errors="replace")


# ── Rule 1: FX reference table is not read by PZ engine ──────────────────────

def test_pz_engine_does_not_read_master_data_fx_table():
    """The PZ landed-cost calculation engine must NOT read fx_rates from
    master_data.sqlite. NBP rates are consumed live."""
    suspect_files = [
        _REPO_ROOT / "pz_import_processor.py",
        _SVC_ROOT / "app" / "services" / "export_service.py",
    ]
    for p in suspect_files:
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        # The engine should never reference both "master_data.sqlite" and "fx_rates" together
        # Allow files to mention either independently for documentation/comments.
        assert not ("master_data.sqlite" in src and "SELECT" in src and "fx_rates" in src), \
            f"PZ engine must not SELECT from master_data fx_rates: {p}"


def test_fx_panel_carries_reference_only_disclaimer():
    src = _read(_DASH)
    # Must mention that PZ uses NBP live and NOT this table
    assert ("NBP rates live" in src) or ("NEVER read by the calculation engine" in src), \
        "FX panel must carry a reference-only disclaimer"


# ── Rule 2: VAT config is not used in wFirma posting ─────────────────────────

def test_wfirma_posting_does_not_read_local_vat_config():
    """wFirma invoice/proforma generation must not source VAT codes from
    master_data.sqlite vat_config table."""
    suspect_dirs = [
        _SVC_ROOT / "app" / "api" / "routes_wfirma.py",
        _SVC_ROOT / "app" / "api" / "routes_wfirma_capabilities.py",
        _SVC_ROOT / "app" / "services" / "wfirma_client.py",
        _SVC_ROOT / "app" / "services" / "wfirma_customer_sync.py",
        _SVC_ROOT / "app" / "api" / "routes_proforma.py",
    ]
    for p in suspect_dirs:
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        assert "vat_config" not in src or "master_data" not in src, \
            f"wFirma/proforma module must not reference master_data vat_config: {p}"


def test_vat_panel_carries_read_only_disclaimer():
    src = _read(_DASH)
    assert "wFirma invoice VAT codes are not overridden" in src, \
        "VAT Config panel must declare it does not override wFirma invoicing"


# ── Rule 3: Carrier Config is not used by live carrier shipment creation ─────

def test_carrier_runtime_does_not_read_local_carriers_config():
    """The carrier runtime (DHL/FedEx/UPS live shipment creation) must NOT
    read from master_data.sqlite carriers_config table."""
    runtime_files = [
        _SVC_ROOT / "app" / "api" / "routes_carrier_actions.py",
        _SVC_ROOT / "app" / "api" / "routes_carrier_shadow.py",
        _SVC_ROOT / "app" / "api" / "routes_carrier_webhook.py",
    ]
    for p in runtime_files:
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        for forbidden in ("carriers_config", "master_data_db",
                          "from ..services.master_data_db"):
            assert forbidden not in src, \
                f"Carrier runtime must not reference master-data carrier config: {p} ↩ {forbidden}"


def test_carriers_config_panel_disclaimer_present():
    src = _read(_DASH)
    assert ".env" in src, "Carriers Config panel must reference .env (credentials stay there)"


def test_routes_master_data_does_not_import_carrier_runtime():
    p = _APP_ROOT / "api" / "routes_master_data.py"
    if not p.exists():
        pytest.skip("routes_master_data not present yet")
    src = p.read_text(encoding="utf-8")
    for forbidden in ("routes_carrier_actions", "routes_carrier_shadow",
                      "routes_carrier_webhook"):
        assert forbidden not in src, \
            f"routes_master_data must not import carrier runtime: {forbidden}"


# ── Rule 4: Master Data local CRUD does not post to proforma ─────────────────

def test_master_data_routes_do_not_call_proforma_posting():
    """Master-data CRUD endpoints must never trigger a proforma post."""
    md_files = [
        _APP_ROOT / "api" / "routes_master_data.py",
        _APP_ROOT / "api" / "routes_suppliers.py",
        _APP_ROOT / "api" / "routes_customer_master.py",
        _APP_ROOT / "api" / "routes_client_addresses.py",
        _APP_ROOT / "api" / "routes_client_carrier_accounts.py",
    ]
    for p in md_files:
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        for forbidden in ("post_proforma", "issue_proforma",
                          "create_proforma_in_wfirma",
                          "from ..services.proforma_pz"):
            assert forbidden not in src, \
                f"Master-data route must not call proforma posting: {p} ↩ {forbidden}"


# ── Rule 5: No .env writes from master-data layer ────────────────────────────

def test_master_data_layer_never_writes_env():
    """Master-data code must NOT open .env for writing."""
    md_files = [
        _APP_ROOT / "api" / "routes_master_data.py",
        _APP_ROOT / "services" / "master_data_db.py",
        _APP_ROOT / "api" / "routes_suppliers.py",
        _APP_ROOT / "services" / "suppliers_db.py",
        _APP_ROOT / "api" / "routes_customer_master.py",
        _APP_ROOT / "services" / "customer_master_db.py",
    ]
    write_modes = re.compile(r"open\(\s*['\"][^'\"]*\.env['\"]\s*,\s*['\"][wa]")
    for p in md_files:
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        assert not write_modes.search(src), \
            f"Master-data file must not open .env for writing: {p}"
        # Also forbid the explicit string ".env" in any write context
        assert "dotenv.set_key" not in src, \
            f"Master-data file must not call dotenv.set_key: {p}"


# ── Rule 6: No storage DB files committed to git ─────────────────────────────

def test_no_sqlite_files_committed_under_storage():
    """Production SQLite files must never be committed. The .gitignore should
    handle this, but contract-test it as a safety net."""
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "--", "*.sqlite", "*.db"],
            cwd=str(_REPO_ROOT), stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("git not available")
    # The schema templates / fixtures in tests/ are OK; production storage is not
    leaked = [
        line for line in out.splitlines()
        if line and "tests/" not in line and "fixtures/" not in line
        and "examples/" not in line
    ]
    assert not leaked, f"SQLite/db files must not be committed: {leaked}"


# ── Rule 7: Credentials never stored in master-data tables ───────────────────

def test_carrier_config_validator_rejects_secret_field_names():
    """The B9 validate_carrier_config function must reject payloads carrying
    credential-shaped field names."""
    p = _APP_ROOT / "services" / "master_data_db.py"
    if not p.exists():
        pytest.skip("master_data_db not present yet")
    src = p.read_text(encoding="utf-8")
    for forbidden in ("api_key", "api_secret", "password", "token",
                      "client_secret", "credentials"):
        assert forbidden in src, \
            f"validate_carrier_config must list secret-shape field for rejection: {forbidden}"


def test_no_master_data_table_has_credential_column():
    """No CREATE TABLE statement in master-data code may declare a column
    whose name suggests it stores a credential."""
    md_files = [
        _APP_ROOT / "services" / "master_data_db.py",
        _APP_ROOT / "services" / "suppliers_db.py",
        _APP_ROOT / "services" / "customer_master_db.py",
        _APP_ROOT / "services" / "client_carrier_accounts_db.py",
        _APP_ROOT / "services" / "client_addresses_db.py",
    ]
    # Look inside CREATE TABLE blocks for credential-shaped column names
    cred_re = re.compile(
        r"\b(?:api_key|api_secret|password|client_secret|auth_secret|"
        r"access_token|refresh_token)\s+TEXT",
        re.IGNORECASE,
    )
    for p in md_files:
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        m = cred_re.search(src)
        assert m is None, \
            f"Master-data DB file declares credential column: {p} ↩ {m.group(0) if m else ''}"


# ── Rule 8: Single allow-list contract on writes in MasterDataPage ───────────

def test_master_data_page_only_uses_allow_listed_write_endpoints():
    """Every POST/DELETE/PUT in MasterDataPage must target one of the
    explicitly approved master-data write endpoints. (The master-design test
    enforces this with regex; here we cross-check the list itself stays
    intact and does not drift to include anything unexpected.)"""
    src = _read(_DASH)
    md_start = src.index("function MasterDataPage(")
    md_end   = src.index("function CarriersPage(", md_start)
    block = src[md_start:md_end]

    write_paths = set()
    for m in re.finditer(r"apiFetch\('([^']+)',\s*\{\s*method:\s*'(?:POST|PUT|DELETE)'", block):
        write_paths.add(m.group(1).rstrip("/"))

    allowed_prefixes = (
        "/api/v1/customer-master",
        "/api/v1/suppliers",
        "/api/v1/hs-codes",
        "/api/v1/units",
        "/api/v1/product-local",
        "/api/v1/incoterms",
        "/api/v1/vat-config",
        "/api/v1/fx-rates",
        "/api/v1/carriers-config",
        "/api/v1/wfirma/capabilities/customers/sync",  # B0 (MDOC-cache): Customer Master Fetch-from-wFirma; local cache write only, no wFirma write
    )

    for path in write_paths:
        # Path may include JS concat (e.g. '/api/v1/suppliers/' + supForm.id);
        # only the literal prefix part needs to match.
        head = path.split("'")[0].rstrip("/")
        assert any(head.startswith(a) for a in allowed_prefixes), \
            f"MasterDataPage writes must be on allow-list — found {path!r}"


# ── Campaign state file sanity ───────────────────────────────────────────────

def test_campaign_state_file_present_and_valid():
    sp = _REPO_ROOT / "tasks" / "campaign-state.json"
    if not sp.exists():
        pytest.skip("campaign-state.json not present yet")
    data = json.loads(sp.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert any(c["campaign_id"] == "MDC-2026-05" for c in data["campaigns"])


def test_campaign_state_records_fx_override_forbidden():
    sp = _REPO_ROOT / "tasks" / "campaign-state.json"
    if not sp.exists():
        pytest.skip("campaign-state.json not present yet")
    data = json.loads(sp.read_text(encoding="utf-8"))
    mdc = next(c for c in data["campaigns"] if c["campaign_id"] == "MDC-2026-05")
    fx_block = next((b for b in mdc["batches"] if b["batch_id"] == "MDC-071"), None)
    assert fx_block is not None, "MDC-071 (FX override) must be tracked"
    assert fx_block["status"] == "blocked"
    assert "FORBIDDEN" in (fx_block.get("block_reason") or ""), \
        "MDC-071 must declare FORBIDDEN in its block_reason"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 6F.1 — finance_postings hard rules
# ══════════════════════════════════════════════════════════════════════════════

def test_6F1_module_exists_and_is_isolated():
    """The new finance_postings_db module must exist and not import any
    posting / wFirma / PZ engine / accounting code."""
    p = _APP_ROOT / "services" / "finance_postings_db.py"
    if not p.exists():
        pytest.skip("Phase 6F.1 not yet landed")
    src = p.read_text(encoding="utf-8")
    for forbidden in (
        "from ..api.routes_wfirma",
        "from ..api.routes_proforma",
        "from ..api.routes_pz",
        "from ..services.wfirma_client",
        "from ..services.proforma_pz",
        "from ..services.ledger_aggregator",
        "from ..services.proforma_service_charges_db",
        "from ..services.export_service",
        "import pz_import_processor",
    ):
        assert forbidden not in src, \
            f"finance_postings_db must not import {forbidden}"


def test_6F1_module_uses_minor_units_only():
    """Architecture §5.2 — minor units (cents) only, NEVER float."""
    p = _APP_ROOT / "services" / "finance_postings_db.py"
    if not p.exists():
        pytest.skip("Phase 6F.1 not yet landed")
    src = p.read_text(encoding="utf-8")
    # No float() conversions on amounts
    for forbidden in ("float(data['amount", "float(data['applied",
                      "float(data.get('amount", "float(data.get('applied"):
        assert forbidden not in src, \
            f"finance_postings_db must not use float on amount fields: {forbidden}"


def test_6F1_no_existing_module_imports_finance_postings():
    """6F.1 enforced full dormancy. 6F.1.5 added the contract-test file to
    the allow-list. 6F.3 added the single read-only route module + its
    tests. Any other import path is still forbidden."""
    import re
    allowed = {
        "finance_postings_db.py", "test_finance_postings_db.py",
        "test_master_data_hard_rules.py",
        "test_finance_postings_contracts.py",
        # 6F.3 additions ──────────────────────────────────────────────
        "routes_finance_postings.py",
        "test_finance_postings_breakdown_route.py",
        # 6F.2.a additions ────────────────────────────────────────────
        "backfill_finance_postings.py",
        "test_backfill_finance_postings.py",
        # 6F.5 additions — dual-write helper + its tests ──────────────
        # The helper imports finance_postings_db; the hook in
        # routes_proforma.py imports the helper, not finance_postings_db
        # directly. Default-OFF flag + source-grep contracts pin safety.
        "finance_dual_write.py",
        "test_finance_dual_write_default_off.py",
        "test_finance_dual_write_idempotent_rerun.py",
        "test_finance_dual_write_decimal_safety.py",
        "test_finance_dual_write_legacy_isolation.py",
        "test_finance_dual_write_error_swallow.py",
        "test_finance_dual_write_no_collision_with_backfill.py",
        "test_finance_dual_write_real_builder.py",
        "test_dual_write_source_grep.py",
    }
    pattern = re.compile(r"(?:from\s+\S*finance_postings_db|import\s+finance_postings_db)")
    for p in (_APP_ROOT.rglob("*.py")):
        if p.name in allowed:
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if pattern.search(src):
            pytest.fail(f"6F.1 must remain unused; found import in {p}")
    # tests directory check
    tests_dir = _SVC_ROOT / "tests"
    for p in tests_dir.rglob("*.py"):
        if p.name in allowed:
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if pattern.search(src):
            pytest.fail(f"6F.1 must remain unused; found import in {p}")


def test_6F3_main_registers_finance_postings_router_get_only():
    """6F.3 wires the single READ-ONLY router. main.py MUST import + register
    it, and the route module MUST declare only GET (no write decorators)."""
    mp = _APP_ROOT / "main.py"
    if not mp.exists():
        pytest.skip("main.py not present")
    src = mp.read_text(encoding="utf-8")
    # Positive: router must be imported + included
    assert "finance_postings_router" in src, \
        "6F.3: main.py must import finance_postings_router"
    assert "include_router(finance_postings_router)" in src, \
        "6F.3: main.py must include_router(finance_postings_router)"
    # Positive: the route file must exist
    routes_file = _APP_ROOT / "api" / "routes_finance_postings.py"
    assert routes_file.exists(), \
        "6F.3: routes_finance_postings.py must exist"
    # Negative: route module must declare only GET — no write decorators
    rsrc = routes_file.read_text(encoding="utf-8")
    for forbidden in ("@router.post", "@router.put",
                      "@router.patch", "@router.delete"):
        assert forbidden not in rsrc, \
            f"6F.3: route module must be GET-only; found {forbidden}"


def test_6F1_pz_engine_does_not_read_finance_postings():
    """The PZ engine must never read from finance_postings.sqlite."""
    suspect = [
        _REPO_ROOT / "pz_import_processor.py",
        _APP_ROOT / "services" / "export_service.py",
    ]
    for f in suspect:
        if not f.exists():
            continue
        src = f.read_text(encoding="utf-8")
        for forbidden in ("finance_postings.sqlite", "finance_postings_db",
                          "from ..services.finance_postings"):
            assert forbidden not in src, \
                f"PZ engine must not reference finance_postings: {f} ↩ {forbidden}"


def test_6F1_module_has_schema_version_locked_to_1():
    p = _APP_ROOT / "services" / "finance_postings_db.py"
    if not p.exists():
        pytest.skip("Phase 6F.1 not yet landed")
    src = p.read_text(encoding="utf-8")
    assert "SCHEMA_VERSION = 1" in src, "6F.1 must lock SCHEMA_VERSION = 1"


def test_6F1_charge_types_allow_list_in_source():
    """The 8 approved charge types must be literally present in source."""
    p = _APP_ROOT / "services" / "finance_postings_db.py"
    if not p.exists():
        pytest.skip("Phase 6F.1 not yet landed")
    src = p.read_text(encoding="utf-8")
    for t in ("net_goods", "freight", "insurance", "customs_duty",
              "vat_eu", "vat_pl", "rounding_adjustment", "fx_delta_at_settlement"):
        assert f'"{t}"' in src, f"6F.1 must enumerate charge type literal: {t}"


# ── B-MD2 Designs master isolation contracts (MDOC-2026-05) ──────────────────

def test_b_md2_product_identity_engine_does_not_read_designs_table():
    """Hard rule: product_identity_engine MUST NOT read the designs master.

    The engine must stay a read-only consumer of its raw inputs
    (karat, metal_color, description_pl, ...). Coupling to a writable
    master would create a corruption path during operator edits.
    """
    pie = _APP_ROOT / "services" / "product_identity_engine.py"
    if not pie.exists():
        pytest.skip("product_identity_engine.py missing")
    src = pie.read_text(encoding="utf-8")
    for forbidden in (
        "designs_db",
        "from .master_data_db import",
        "from ..services.master_data_db import",
        "import master_data_db",
        "list_designs", "get_design", "upsert_design", "delete_design",
        "FROM designs", "INSERT INTO designs", "UPDATE designs",
    ):
        assert forbidden not in src, (
            f"product_identity_engine.py must not reference designs master: "
            f"forbidden token {forbidden!r}"
        )


def test_b_md2_design_product_bridge_does_not_write_to_designs():
    """The packing-side design_product_bridge must stay read-only against
    the NEW Designs master (it operates on packing-side records via the
    separate reservation_db.upsert_design_mapping DAO, NOT on the new
    master_data_db.upsert_design DAO).
    """
    bridge = _APP_ROOT / "services" / "design_product_bridge.py"
    if not bridge.exists():
        pytest.skip("design_product_bridge.py missing")
    src = bridge.read_text(encoding="utf-8")
    for forbidden in (
        "master_data_db.upsert_design",
        "master_data_db.delete_design",
        "from ..services.master_data_db import",
        "from .master_data_db import",
        "INSERT INTO designs (",
        "UPDATE designs SET",
        "DELETE FROM designs",
    ):
        assert forbidden not in src, (
            f"design_product_bridge.py must not write to NEW designs master "
            f"(use reservation_db packing-side DAO instead): {forbidden!r}"
        )


def test_b_md2_designs_table_has_no_fk_constraints():
    """designs table must use soft references only — no SQL FK."""
    md = _APP_ROOT / "services" / "master_data_db.py"
    src = md.read_text(encoding="utf-8")
    # Locate the CREATE TABLE designs block and assert no FOREIGN KEY clause.
    import re
    m = re.search(r"CREATE TABLE IF NOT EXISTS designs\s*\([\s\S]*?\)", src)
    assert m is not None, "designs table CREATE statement must exist"
    block = m.group(0)
    assert "FOREIGN KEY" not in block.upper(), (
        "designs table must have no FOREIGN KEY constraint"
    )
    assert "REFERENCES " not in block.upper(), (
        "designs table must have no SQL REFERENCES clause"
    )


def test_b_md2_designs_routes_use_only_local_md_db():
    """routes for /api/v1/designs must operate ONLY on master_data.sqlite
    via the master_data_db DAO. No wFirma / finance / proforma / PZ imports
    inside the designs router block."""
    rm = _APP_ROOT / "api" / "routes_master_data.py"
    src = rm.read_text(encoding="utf-8")
    # Find the designs router section.
    start = src.find("designs_router = APIRouter")
    assert start >= 0, "designs_router must be declared"
    block = src[start:]
    for forbidden in (
        "wfirma_client", "finance_postings", "proforma_invoice",
        "landed_cost", "fx_rate_at_issue", "settle",
        "/api/v1/wfirma", "/api/v1/finance", "/api/v1/proforma",
    ):
        assert forbidden not in block, (
            f"designs router block must not reference {forbidden!r}"
        )
