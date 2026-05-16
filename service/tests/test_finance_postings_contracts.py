"""test_finance_postings_contracts.py — Phase 6F.1.5 contract pinning.

These tests pin ``finance_postings_db.py`` as DORMANT — present in the
codebase but used by NO production code path. They are the safety net
between Batch 6F.1 (schema) and any later batch that wires behaviour
(6F.3 read endpoint, 6F.5 dual-write, 6F.6 settlement-close, …).

Every test in this file MUST stay green until a deliberate operator-
approved batch lands. When that future batch lands, the test that fails
must be updated in the SAME diff with a comment naming the batch.

Rules covered (per Phase 6F.1.5 brief):
  1. No runtime module imports ``finance_postings_db``
  2. No route registration / no path containing "finance-postings"
  3. No production code path calls ``init_db`` on this module
  4. No behaviour coupling to posting/settlement/FX/PZ/wFirma engines
  5. Schema allow-lists pinned (CHARGE_TYPES, POSTING_KINDS, PAYMENT_SOURCES,
     ALLOCATION_METHODS, CHARGE_SOURCES)
  6. Monetary safety pinned (INTEGER minor units; no REAL/FLOAT money)
  7. Idempotency pinned (init_db × 2 → schema_version stays 1)
  8. Campaign order pinned (6F.1.5 listed BEFORE 6F.2 backfill)
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[2]
_SVC  = Path(__file__).resolve().parents[1]
_APP  = _SVC / "app"


def _ensure_path() -> None:
    for p in (str(_SVC), str(_REPO)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()


# ── Rule 1: NO runtime module imports finance_postings_db ──────────────────

_FP_IMPORT_RE = re.compile(
    r"(?:from\s+\S*finance_postings_db|import\s+finance_postings_db|"
    r"from\s+\.+services\.finance_postings_db|from\s+app\.services\.finance_postings_db)"
)

#: Files allowed to reference finance_postings_db. Adding to this list
#: requires also adding the matching production wiring in a future batch
#: AND removing the dormancy test that follows.
#:
#: 6F.3 added: routes_finance_postings.py (the single READ-ONLY route file)
#:             test_finance_postings_breakdown_route.py (its tests)
_ALLOWED_REFERENCES = {
    "finance_postings_db.py",
    "test_finance_postings_db.py",
    "test_finance_postings_contracts.py",
    "test_master_data_hard_rules.py",
    # 6F.3 ──────────────────────────────────────────────────────────────
    "routes_finance_postings.py",
    "test_finance_postings_breakdown_route.py",
}


def _scan_for_finance_postings_imports(root: Path) -> list:
    found = []
    for p in root.rglob("*.py"):
        if p.name in _ALLOWED_REFERENCES:
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if _FP_IMPORT_RE.search(src):
            found.append(p)
    return found


def test_no_runtime_module_imports_finance_postings_in_api():
    leaks = _scan_for_finance_postings_imports(_APP / "api")
    assert not leaks, \
        f"6F.1.5: finance_postings_db must remain dormant — found in api: {leaks}"


def test_no_runtime_module_imports_finance_postings_in_services():
    """Scans service modules except finance_postings_db.py itself."""
    leaks = _scan_for_finance_postings_imports(_APP / "services")
    assert not leaks, \
        f"6F.1.5: finance_postings_db must remain dormant — found in services: {leaks}"


def test_no_finance_postings_reference_in_static_assets():
    """The dashboard.html or any static asset must not reference the module
    until 6F.4 (UI panel) batch lands."""
    static = _APP / "static"
    if not static.exists():
        pytest.skip("no static dir")
    for p in static.rglob("*"):
        if not p.is_file():
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for forbidden in ("finance_postings_db", "finance-postings",
                          "/api/v1/finance/"):
            assert forbidden not in src, \
                f"6F.1.5: static asset references {forbidden}: {p}"


def test_main_references_only_read_only_router_for_finance_postings():
    """6F.3: main.py is allowed to import the READ-ONLY finance_postings_router
    and call include_router on it. Any other reference (write helpers, DB
    init in lifespan, settlement engine) is still forbidden."""
    mp = _APP / "main.py"
    if not mp.exists():
        pytest.skip("main.py missing")
    src = mp.read_text(encoding="utf-8")
    # Allowed references (6F.3)
    assert "finance_postings_router" in src, \
        "6F.3: main.py must import finance_postings_router"
    assert "include_router(finance_postings_router)" in src, \
        "6F.3: main.py must include_router(finance_postings_router)"
    # Forbidden references (still locked)
    for forbidden in ("finance_postings_db.init_db",
                      "from .services.finance_postings_db import init_db",
                      "from ..services.finance_postings_db import init_db",
                      "create_charge", "create_posting", "create_payment",
                      "create_allocation", "record_settlement"):
        assert forbidden not in src, \
            f"6F.3: main.py must NOT reference {forbidden}"


# ── Rule 2: route registration is now positive (single read-only route) ────

def test_routes_finance_postings_file_exists():
    """6F.3 adds the single read-only route file."""
    f = _APP / "api" / "routes_finance_postings.py"
    assert f.exists(), \
        "6F.3: routes_finance_postings.py must exist"


def test_route_path_is_exactly_breakdown():
    """6F.3 allows exactly one path literal under finance-postings:
       /{posting_id}/breakdown
    Any other path on this prefix (e.g. /, /list) is forbidden until a
    later batch deliberately adds it."""
    f = _APP / "api" / "routes_finance_postings.py"
    if not f.exists():
        pytest.skip("6F.3 not landed")
    src = f.read_text(encoding="utf-8")
    # The only allowed path inside @router.get(...) is /{posting_id}/breakdown
    decorator_pattern = re.compile(
        r"@router\.get\(\s*['\"]([^'\"]+)['\"]"
    )
    found_paths = decorator_pattern.findall(src)
    assert len(found_paths) >= 1, "6F.3 must declare at least one GET route"
    for path in found_paths:
        assert path == "/{posting_id}/breakdown", \
            f"6F.3 allows only /{{posting_id}}/breakdown; found {path!r}"


def test_router_prefix_is_finance_postings_exact():
    """The only APIRouter prefix containing 'finance' must be exactly
    '/api/v1/finance/postings' (no other 'finance' prefixes)."""
    api_dir = _APP / "api"
    if not api_dir.exists():
        pytest.skip("no api dir")
    pattern = re.compile(r"APIRouter\([^)]*prefix\s*=\s*['\"]([^'\"]*finance[^'\"]*)['\"]")
    for p in api_dir.glob("routes_*.py"):
        src = p.read_text(encoding="utf-8")
        for prefix in pattern.findall(src):
            assert prefix == "/api/v1/finance/postings", \
                f"6F.3 allows only /api/v1/finance/postings prefix; "\
                f"found {prefix!r} in {p.name}"


# ── Rule 3: production code allowed to touch finance_postings.sqlite only
#    via the read-only route handler ──────────────────────────────────────

def test_init_db_called_only_from_route_handler():
    """6F.3 explicitly chose handler-level init_db. main.py lifespan MUST NOT
    initialise the DB; the only production caller is routes_finance_postings."""
    # 1) main.py does NOT call finance_postings_db.init_db
    mp = _APP / "main.py"
    if mp.exists():
        src = mp.read_text(encoding="utf-8")
        for forbidden in ("finance_postings_db.init_db",
                          "from .services.finance_postings_db import init_db",
                          "from ..services.finance_postings_db import init_db",
                          "init_finance_postings_db"):
            assert forbidden not in src, \
                f"6F.3: main.py must NOT initialise finance_postings: {forbidden}"
    # 2) The route module IS allowed to import init_db (read-only path)
    rf = _APP / "api" / "routes_finance_postings.py"
    if not rf.exists():
        pytest.skip("6F.3 not landed")
    rsrc = rf.read_text(encoding="utf-8")
    assert "init_db" in rsrc, \
        "6F.3: route handler must call init_db (lazy initialisation)"


def test_only_route_module_mentions_finance_postings_sqlite():
    """Scan all production code for the literal 'finance_postings.sqlite'.
    Only the DB module itself and the read-only route module are allowed."""
    pattern = re.compile(r"finance_postings\.sqlite")
    for root in (_APP / "api", _APP / "services"):
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if p.name in _ALLOWED_REFERENCES:
                continue
            src = p.read_text(encoding="utf-8", errors="ignore")
            assert not pattern.search(src), \
                f"6F.3: production file mentions finance_postings.sqlite: {p}"


# ── Rule 4: NO behaviour coupling to existing engines ──────────────────────

@pytest.mark.parametrize("engine_file", [
    _APP / "api" / "routes_proforma.py",
    _APP / "api" / "routes_wfirma.py",
    _APP / "api" / "routes_wfirma_capabilities.py",
    _APP / "api" / "routes_pz.py",
    _APP / "services" / "ledger_aggregator.py",
    _APP / "services" / "wfirma_client.py",
    _APP / "services" / "proforma_service_charges_db.py",
    _APP / "services" / "export_service.py",
    _REPO / "pz_import_processor.py",
])
def test_engine_does_not_reference_finance_postings(engine_file):
    if not engine_file.exists():
        pytest.skip(f"{engine_file.name} not present")
    src = engine_file.read_text(encoding="utf-8")
    for forbidden in ("finance_postings_db", "finance_postings.sqlite",
                      "from ..services.finance_postings",
                      "from .services.finance_postings",
                      "import finance_postings"):
        assert forbidden not in src, \
            f"6F.1.5: {engine_file.name} must not reference {forbidden}"


# ── Rule 5: Schema allow-lists pinned ──────────────────────────────────────

def _import_fp():
    """Lazy import so failing earlier rules surface first."""
    from app.services import finance_postings_db as fp  # type: ignore
    return fp


def test_charge_types_locked_exact():
    fp = _import_fp()
    expected = {
        "net_goods", "freight", "insurance", "customs_duty",
        "vat_eu", "vat_pl", "rounding_adjustment", "fx_delta_at_settlement",
    }
    assert set(fp.CHARGE_TYPES) == expected, \
        f"6F.1.5: CHARGE_TYPES drift: {set(fp.CHARGE_TYPES) ^ expected}"


def test_posting_kinds_locked_exact():
    fp = _import_fp()
    assert set(fp.POSTING_KINDS) == {"proforma", "invoice", "correction"}


def test_payment_sources_locked_exact():
    fp = _import_fp()
    assert set(fp.PAYMENT_SOURCES) == {"wfirma", "bank_recon", "operator"}


def test_allocation_methods_locked_exact():
    fp = _import_fp()
    assert set(fp.ALLOCATION_METHODS) == {"proportional", "operator_directed"}


def test_charge_sources_locked_exact():
    fp = _import_fp()
    assert set(fp.CHARGE_SOURCES) == {"operator", "derived", "wfirma", "legacy_backfill"}


def test_allow_lists_are_frozensets():
    """Allow-lists must be frozenset (immutable). A list would be mutable
    and could drift at runtime."""
    fp = _import_fp()
    for name in ("CHARGE_TYPES", "CHARGE_SOURCES", "POSTING_KINDS",
                 "PAYMENT_SOURCES", "ALLOCATION_METHODS"):
        val = getattr(fp, name)
        assert isinstance(val, frozenset), \
            f"6F.1.5: {name} must be a frozenset, got {type(val).__name__}"


# ── Rule 6: Monetary safety pinned ─────────────────────────────────────────

def test_schema_has_no_real_or_float_columns(tmp_path):
    fp = _import_fp()
    db = tmp_path / "fp.sqlite"
    fp.init_db(db)
    with sqlite3.connect(str(db)) as c:
        # PRAGMA table_info returns: cid, name, type, notnull, dflt, pk
        for table in ("charges", "postings", "payments",
                      "payment_allocations", "settlements"):
            cols = c.execute(f"PRAGMA table_info({table})").fetchall()
            for cid, name, type_, *_ in cols:
                # Monetary fields: any column ending in _minor must be INTEGER
                if name.endswith("_minor"):
                    assert type_.upper() == "INTEGER", \
                        f"6F.1.5: {table}.{name} must be INTEGER, got {type_!r}"
                # No REAL or FLOAT columns anywhere
                assert type_.upper() not in ("REAL", "FLOAT", "DOUBLE"), \
                    f"6F.1.5: {table}.{name} has forbidden numeric type {type_!r}"


def test_validator_rejects_float_amount_minor():
    fp = _import_fp()
    errs = fp.validate_charge({
        "batch_id": "B1", "client_name": "C", "charge_type": "freight",
        "amount_minor": 12.50,  # FLOAT — must be rejected
        "currency": "EUR", "source": "operator",
    })
    assert any("amount_minor" in e and "int" in e for e in errs), \
        "6F.1.5: validate_charge MUST reject Python float on amount_minor"


def test_validator_rejects_float_applied_minor():
    fp = _import_fp()
    errs = fp.validate_allocation({
        "payment_id": 1, "charge_id": 1,
        "applied_minor": 99.5,  # FLOAT
        "allocation_method": "proportional",
    })
    assert any("applied_minor" in e for e in errs), \
        "6F.1.5: validate_allocation MUST reject Python float on applied_minor"


def test_validator_rejects_float_payment_amount():
    fp = _import_fp()
    errs = fp.validate_payment({
        "posting_id": 1, "paid_at": "2026-05-16",
        "amount_minor": 100.5, "currency": "EUR", "source": "operator",
    })
    assert any("amount_minor" in e and "int" in e for e in errs)


def test_source_has_no_float_money_field_assignments():
    """Belt + braces source-grep: no obvious float assignment to monetary
    fields in the module."""
    src = (_APP / "services" / "finance_postings_db.py").read_text(encoding="utf-8")
    for pattern in (r"amount_minor\s*=\s*\d+\.\d+",
                    r"applied_minor\s*=\s*\d+\.\d+",
                    r"fx_delta_minor\s*=\s*\d+\.\d+",
                    r"issued_total_minor\s*=\s*\d+\.\d+"):
        m = re.search(pattern, src)
        assert m is None, \
            f"6F.1.5: float literal assignment to minor field: {m.group(0) if m else ''}"


# ── Rule 7: Idempotency pinned ─────────────────────────────────────────────

def test_init_db_twice_does_not_drift_schema(tmp_path):
    fp = _import_fp()
    db = tmp_path / "fp.sqlite"
    fp.init_db(db)

    # Snapshot every table's schema
    def _snapshot():
        with sqlite3.connect(str(db)) as c:
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()]
            shape = {}
            for t in tables:
                cols = c.execute(f"PRAGMA table_info({t})").fetchall()
                shape[t] = [(name, type_, notnull, pk)
                            for _, name, type_, notnull, _, pk in cols]
        return shape

    before = _snapshot()
    fp.init_db(db)  # second call
    fp.init_db(db)  # third call for good measure
    after = _snapshot()

    assert before == after, \
        f"6F.1.5: init_db must be idempotent. Diff: {set(before) ^ set(after)}"


def test_init_db_preserves_schema_version_at_1(tmp_path):
    fp = _import_fp()
    db = tmp_path / "fp.sqlite"
    fp.init_db(db)
    assert fp.current_schema_version(db) == 1
    fp.init_db(db)
    assert fp.current_schema_version(db) == 1, \
        "6F.1.5: schema_version must remain 1 after re-init"


def test_init_db_does_not_insert_duplicate_version_rows(tmp_path):
    """The schema_version row is inserted once, on first init. Re-running
    init_db must NOT add another row."""
    fp = _import_fp()
    db = tmp_path / "fp.sqlite"
    fp.init_db(db)
    fp.init_db(db)
    fp.init_db(db)
    with sqlite3.connect(str(db)) as c:
        rows = c.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert rows == 1, \
        f"6F.1.5: schema_version table must have exactly 1 row, got {rows}"


# ── Rule 8: Campaign order pinned ──────────────────────────────────────────

def _load_campaign_state():
    sp = _REPO / "tasks" / "campaign-state.json"
    if not sp.exists():
        pytest.skip("campaign-state.json missing")
    return json.loads(sp.read_text(encoding="utf-8"))


def test_campaign_state_has_p6f_campaign():
    data = _load_campaign_state()
    p6f = next((c for c in data["campaigns"] if c["campaign_id"] == "P6F-2026-05"),
               None)
    assert p6f is not None, "6F.1.5: P6F-2026-05 must be tracked in state"


def test_6F1_5_listed_before_6F2_in_state():
    """Refined migration order: 6F.1 → 6F.1.5 → 6F.3 → 6F.2 → …"""
    data = _load_campaign_state()
    p6f = next(c for c in data["campaigns"] if c["campaign_id"] == "P6F-2026-05")
    batch_ids = [b["batch_id"] for b in p6f["batches"]]
    assert "6F.1.5" in batch_ids, "6F.1.5 must appear in P6F campaign batch list"
    assert "6F.2" in batch_ids, "6F.2 must appear in P6F campaign batch list"
    i_15 = batch_ids.index("6F.1.5")
    i_2  = batch_ids.index("6F.2")
    assert i_15 < i_2, \
        f"6F.1.5 must precede 6F.2 in declaration order; got {batch_ids}"


def test_6F2_not_active_before_6F1_5_done():
    """6F.2 (backfill) must NOT be in any forward status while 6F.1.5 is
    not yet smoked."""
    data = _load_campaign_state()
    p6f = next(c for c in data["campaigns"] if c["campaign_id"] == "P6F-2026-05")
    by_id = {b["batch_id"]: b for b in p6f["batches"]}
    b_15 = by_id.get("6F.1.5")
    b_2  = by_id.get("6F.2")
    assert b_15 is not None and b_2 is not None
    if b_15.get("status") != "smoked":
        forward = ("active", "pr_open", "merged", "deployed", "smoked")
        assert b_2.get("status") not in forward, \
            (f"6F.1.5: 6F.2 has status {b_2.get('status')} but 6F.1.5 is "
             f"only {b_15.get('status')} — refined order would be violated")


def test_readiness_doc_references_6F1_5_before_backfill():
    """The readiness doc (`tasks/phase-6f-readiness-2026-05-16.md`) must
    list 6F.1.5 BEFORE 6F.2 in its migration-order table.

    We locate the migration table by finding the row that bold-marks
    ``**6F.1**`` (only present in the migration table) and then scan from
    there for 6F.1.5 and 6F.2 — preventing prose references higher in the
    doc from confusing the order check.
    """
    rp = _REPO / "tasks" / "phase-6f-readiness-2026-05-16.md"
    if not rp.exists():
        pytest.skip("readiness doc missing")
    text = rp.read_text(encoding="utf-8")
    assert "6F.1.5" in text, "Readiness doc must mention 6F.1.5"

    # Anchor at the migration table row that mentions **6F.1**
    anchor = text.find("**6F.1**")
    assert anchor != -1, "Readiness doc missing migration-order table"
    block = text[anchor:]

    i_15 = block.find("**6F.1.5")
    i_2  = block.find("**6F.2**")
    assert i_15 != -1, "Migration table must include **6F.1.5** row"
    assert i_2 != -1, "Migration table must include **6F.2** row"
    assert i_15 < i_2, \
        "Migration table must list 6F.1.5 row before 6F.2 row"


# ── Dormancy meta-assertion: this whole file must keep passing ─────────────

def test_finance_postings_module_is_read_only_only():
    """6F.3 roll-up assertion. Replaces the 6F.1.5 dormancy-summary test.

    The single intentional consumer is the READ-ONLY route module. If any
    OTHER production file imports finance_postings_db, fail loudly.

    Additionally: the route module itself must declare only GET; no write
    helpers may be imported.

    If this test fails, finance_postings_db has acquired a write-path
    consumer WITHOUT the corresponding 6F.5/6F.6/6F.7 batch having
    explicitly updated the contracts. Stop and investigate.
    """
    # Step 1: imports outside the single allowed route module
    api_leaks      = _scan_for_finance_postings_imports(_APP / "api")
    services_leaks = _scan_for_finance_postings_imports(_APP / "services")
    leaks = api_leaks + services_leaks
    assert not leaks, \
        f"6F.3 read-only-only: import leak found in: {leaks}"

    # Step 2: route module exists
    routes_file = _APP / "api" / "routes_finance_postings.py"
    assert routes_file.exists(), \
        "6F.3 read-only-only: routes_finance_postings.py must exist"

    # Step 3: route module declares only GET
    rsrc = routes_file.read_text(encoding="utf-8")
    for forbidden_decorator in ("@router.post", "@router.put",
                                 "@router.patch", "@router.delete"):
        assert forbidden_decorator not in rsrc, \
            f"6F.3 read-only-only: route module declares {forbidden_decorator}"

    # Step 4: route module does NOT import write helpers
    for forbidden_helper in ("create_charge", "create_posting",
                              "create_payment", "create_allocation",
                              "record_settlement", "link_charge_to_posting"):
        assert forbidden_helper not in rsrc, \
            f"6F.3 read-only-only: route imports write helper {forbidden_helper}"

    # Step 5: main.py imports the router but no write helper
    main_src = (_APP / "main.py").read_text(encoding="utf-8") if (_APP / "main.py").exists() else ""
    assert "finance_postings_router" in main_src, \
        "6F.3: main.py must import finance_postings_router"
    for forbidden in ("create_charge", "create_posting", "create_payment",
                       "create_allocation", "record_settlement",
                       "finance_postings_db.init_db"):
        assert forbidden not in main_src, \
            f"6F.3 read-only-only: main.py must NOT reference {forbidden}"
