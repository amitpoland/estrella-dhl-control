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
_ALLOWED_REFERENCES = {
    "finance_postings_db.py",
    "test_finance_postings_db.py",
    "test_finance_postings_contracts.py",
    "test_master_data_hard_rules.py",
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


def test_no_finance_postings_reference_in_main_or_routes_init():
    """main.py and any route-aggregator file must not even mention the module
    by name. Adding it requires a deliberate batch."""
    mp = _APP / "main.py"
    if not mp.exists():
        pytest.skip("main.py missing")
    src = mp.read_text(encoding="utf-8")
    for forbidden in ("finance_postings_db", "finance_postings_router",
                      "fp_router", "finance-postings"):
        assert forbidden not in src, \
            f"6F.1.5: main.py must NOT reference {forbidden}"


# ── Rule 2: NO route registration ──────────────────────────────────────────

def test_no_routes_finance_postings_file_exists():
    f = _APP / "api" / "routes_finance_postings.py"
    assert not f.exists(), \
        "6F.1.5: routes_finance_postings.py must NOT exist until 6F.3 lands"


def test_no_route_path_contains_finance_postings_or_postings():
    """Scan all route files; no path literal may contain finance-postings
    or /postings/. (Plain 'postings' could appear in comments — be strict
    about path literals that look like URLs.)"""
    api_dir = _APP / "api"
    if not api_dir.exists():
        pytest.skip("no api dir")
    url_pattern = re.compile(r"['\"](?:/api/v1/finance|/api/v1/postings|"
                              r"finance-postings)['\"]")
    for p in api_dir.glob("routes_*.py"):
        src = p.read_text(encoding="utf-8")
        m = url_pattern.search(src)
        assert m is None, \
            f"6F.1.5: route module {p.name} declares forbidden path: {m.group(0)}"


def test_no_router_prefix_for_finance_postings():
    """If any APIRouter declares a prefix containing finance-postings, fail."""
    api_dir = _APP / "api"
    if not api_dir.exists():
        pytest.skip("no api dir")
    pattern = re.compile(r"APIRouter\([^)]*prefix\s*=\s*['\"][^'\"]*finance[^'\"]*['\"]")
    for p in api_dir.glob("routes_*.py"):
        src = p.read_text(encoding="utf-8")
        m = pattern.search(src)
        assert m is None, \
            f"6F.1.5: {p.name} has forbidden APIRouter prefix: {m.group(0)}"


# ── Rule 3: NO production code path creates the SQLite file ────────────────

def test_init_db_not_called_from_main_lifespan():
    """The PZService lifespan in main.py initialises several DBs at startup.
    finance_postings_db.init_db MUST NOT be among them in 6F.1.5."""
    mp = _APP / "main.py"
    if not mp.exists():
        pytest.skip("main.py missing")
    src = mp.read_text(encoding="utf-8")
    # main.py imports init_db (different module) — be specific about the FP one
    for forbidden in ("finance_postings_db.init_db",
                      "from .services.finance_postings_db import init_db",
                      "from ..services.finance_postings_db import init_db"):
        assert forbidden not in src, \
            f"6F.1.5: main.py must NOT initialise finance_postings: {forbidden}"


def test_no_production_path_creates_finance_postings_sqlite():
    """Scan all production code for the literal string 'finance_postings.sqlite'.
    Only the module itself + tests + docs are allowed to mention it."""
    pattern = re.compile(r"finance_postings\.sqlite")
    # App services + api
    for root in (_APP / "api", _APP / "services"):
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if p.name in _ALLOWED_REFERENCES:
                continue
            src = p.read_text(encoding="utf-8", errors="ignore")
            assert not pattern.search(src), \
                f"6F.1.5: production file mentions finance_postings.sqlite: {p}"


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

def test_finance_postings_module_remains_dormant_summary():
    """Single roll-up assertion to make the dormancy guarantee very visible.

    If THIS test fails, finance_postings_db has become coupled to runtime
    code WITHOUT the corresponding contract test being updated. Stop and
    investigate before merging anything else.
    """
    leaks = (
        _scan_for_finance_postings_imports(_APP / "api")
        + _scan_for_finance_postings_imports(_APP / "services")
    )
    routes_file = _APP / "api" / "routes_finance_postings.py"
    main_src = (_APP / "main.py").read_text(encoding="utf-8") if (_APP / "main.py").exists() else ""
    assert not leaks, f"dormancy broken — imports found in: {leaks}"
    assert not routes_file.exists(), "dormancy broken — routes_finance_postings.py exists"
    assert "finance_postings" not in main_src, \
        "dormancy broken — main.py references finance_postings"
