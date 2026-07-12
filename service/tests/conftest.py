"""conftest.py — shared pytest fixtures and path setup."""
import os
import sys
from pathlib import Path

import pytest

# customs_description_engine.py lives at the CLI root (one level above service/)
_cli_root = Path(__file__).parent.parent.parent  # Downloads/CLI/
if str(_cli_root) not in sys.path:
    sys.path.insert(0, str(_cli_root))


# ── Session-wide storage sandbox (test-only, IMPORT-TIME) ─────────────────────
#
# The storage-leak guard below (_guard_storage_root) watches the REAL live
# storage roots (service/app/storage, service/storage).  Four classes of write
# escape any per-test sandbox and land in whichever root settings.storage_root
# points at, at a time the *running* test never controls:
#
#   1. app.main lifespan startup — init_*_db(_root / "*.db") creates ~20
#      root-level DB/JSON files (wfirma.db, users.db, master_data.sqlite, …)
#      the moment the first TestClient(app) enters.
#   2. Background threads — batch_manager.start_sweep() / start_watcher() /
#      dhl_orchestrator keep writing under the root AFTER the test that started
#      them has torn down.
#   3. Import-time module constants — e.g. agency_email_builder._POLISH_DIR and
#      action_email_builder._OUTPUTS bind `settings.storage_root / "…"` at import,
#      so a later per-test monkeypatch of settings.storage_root cannot redirect
#      them.
#   4. importlib.reload(app.core.config) — test_compliance_resolver_injection
#      reloads the config module (and never restores it), replacing the shared
#      `settings` object with a fresh one whose storage_root reverts to the real
#      default.  Every later test that resolves `from app.core.config import
#      settings` at call time (e.g. proforma_draft_sync._cm_name_for_cid) then
#      reads/writes the real root — an object-attribute redirect on the ORIGINAL
#      singleton cannot reach this reload-created replacement.
#
# When settings.storage_root still points at the real live root, all four write
# into a root the current test did not touch, and the guard implicates the test
# that happens to be in teardown when the file first appears (its own docstring:
# "implicates the next test, not the culprit").  Because the deploy gate treats
# ANY test ERROR as an unconditional block, this non-deterministically blocks the
# gate on fresh-storage hosts.
#
# Fix (deterministic, host-independent) — two complementary redirects applied at
# conftest IMPORT time (not in a fixture), BEFORE any test module — and therefore
# app.main and every storage-writing service — is imported:
#   (a) point the existing settings singleton's storage_root at a throwaway
#       per-session temp dir (covers classes 1–3, incl. the import-time
#       constants which must capture the sandbox path), and
#   (b) export STORAGE_ROOT into the environment so any *newly constructed*
#       Settings() — reload-created or otherwise — also resolves to the sandbox
#       (covers class 4).
# With both in place the real live roots stay quiescent for the whole session and
# the guard is 0-error regardless of whether the host's storage was pre-seeded.
# The guard keeps watching the real roots, so a test that writes to them via a
# HARDCODED path (bypassing settings.storage_root) is still caught.
import atexit
import shutil
import tempfile

# Ensure service/ is importable so `app.core.config` resolves even when pytest
# was launched as bare `pytest` (not `python -m pytest` from service/).
_service_root = Path(__file__).parent.parent  # service/
if str(_service_root) not in sys.path:
    sys.path.insert(0, str(_service_root))

from app.core.config import settings as _pz_settings  # noqa: E402

# The ORIGINAL host STORAGE_ROOT (if any) is what the leak-guard must keep
# watching — capture it BEFORE we overwrite the env var with the sandbox below.
_ORIG_STORAGE_ROOT_ENV = os.environ.get("STORAGE_ROOT")

_SESSION_STORAGE_SANDBOX = Path(tempfile.mkdtemp(prefix="pz_test_storage_"))

# (a) Point the already-constructed settings singleton at the sandbox.
_pz_settings.storage_root = _SESSION_STORAGE_SANDBOX

# (b) Also export STORAGE_ROOT so that any *newly constructed* Settings() —
#     including one created by ``importlib.reload(app.core.config)`` inside a
#     test — resolves storage_root to the sandbox as well.  This is essential:
#     test_compliance_resolver_injection reloads app.core.config and does NOT
#     restore it, replacing the module-global ``settings`` with a fresh object
#     whose storage_root reverts to the real default.  Every later test that
#     resolves ``from app.core.config import settings`` at call time (e.g.
#     proforma_draft_sync._cm_name_for_cid) would then read/write the REAL live
#     root.  Exporting STORAGE_ROOT makes the sandbox the config default for
#     every Settings() instance, reload-created or not.  STORAGE_ROOT is already
#     the idiomatic per-test isolation knob here — dozens of tests override it
#     with monkeypatch.setenv("STORAGE_ROOT", tmp_path), which auto-restores to
#     this sandbox value on teardown, so global export is fully compatible.
os.environ["STORAGE_ROOT"] = str(_SESSION_STORAGE_SANDBOX)

atexit.register(shutil.rmtree, _SESSION_STORAGE_SANDBOX, ignore_errors=True)


# ── ai_gateway isolation fixture ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_ai_gateway():
    """Prevent ai_gateway global state from leaking between tests.

    Two isolation problems are addressed:

    1. Circuit-breaker pollution — Phase 2B tests that call ai_gateway.call()
       with a real (unmocked) _cowork_call() trip the cowork CB.  Phase 3 tests
       reset CBs at the start of each test, but this fixture guarantees isolation
       regardless of execution order.

    2. Lazy-import module-attribute caching — Python's _handle_fromlist shortcut
       checks hasattr(package, 'submod') first.  If True, it returns the cached
       package attribute WITHOUT consulting sys.modules.  This means
       ``patch.dict("sys.modules", {"app.services.ai_call_ledger": mock})``
       is silently ignored when Phase 2B tests have already set the package
       attribute by patching functions on the real module.

       Fix: before each test, save then remove the submodule from BOTH the
       package's __dict__ AND sys.modules.  This forces the next import (whether
       via patch._importer or via 'from . import') to go through
       _find_and_load_unlocked, which re-consults sys.modules and re-sets the
       package attribute — so any active patch.dict mock is honoured correctly.

    This fixture is a no-op for tests that have not imported app.services,
    so it does not slow down the 10,000+ non-gateway tests.
    """
    # Submodules whose cached package-attribute must be cleared each test
    _SUBMODULES = ('ai_call_ledger', 'ai_redactor')

    svc = sys.modules.get('app.services')
    gw  = sys.modules.get('app.services.ai_gateway')

    # Save and evict: remove from both the package __dict__ and sys.modules
    saved: dict = {}
    if svc is not None:
        for name in _SUBMODULES:
            full = f'app.services.{name}'
            attr_val = svc.__dict__.pop(name, None)      # package attribute
            mod_val  = sys.modules.pop(full, None)       # sys.modules entry
            saved[name] = (attr_val, mod_val)

    # Reset both ai_gateway circuit breakers
    if gw is not None:
        gw.reset_circuit_breaker()
        gw.reset_cowork_circuit_breaker()

    # Reset every registry-backed circuit breaker (e.g. "wfirma") so a breaker
    # tripped OPEN by an earlier test cannot reject a later test's live re-probe.
    # ai_gateway's own resets above only touch the gateway breakers; the shared
    # app.core.circuit_breaker registry (wfirma, etc.) is otherwise never reset
    # between tests.  Guarded on prior import to keep this fixture a no-op for the
    # 10,000+ tests that never touch app.core.circuit_breaker.
    _cb = sys.modules.get('app.core.circuit_breaker')
    if _cb is not None:
        _cb.reset_all()

    yield

    # Teardown: restore what we saved so non-ai-gateway tests see a clean state
    svc = sys.modules.get('app.services')
    if svc is not None:
        for name, (attr_val, mod_val) in saved.items():
            full = f'app.services.{name}'
            # Restore sys.modules entry (real module — any test-time mock is gone)
            if mod_val is not None:
                sys.modules[full] = mod_val
            # Restore package attribute
            if attr_val is not None:
                svc.__dict__[name] = attr_val

    # Reset CBs again for the next test
    gw = sys.modules.get('app.services.ai_gateway')
    if gw is not None:
        gw.reset_circuit_breaker()
        gw.reset_cowork_circuit_breaker()

    # Symmetric teardown reset of registry-backed breakers (see setup note above)
    _cb = sys.modules.get('app.core.circuit_breaker')
    if _cb is not None:
        _cb.reset_all()


# ── Safety fixture: prevent tests from writing to live storage ───────────────

# Paths that tests must NEVER write new files into.
_LIVE_ROOTS = {
    Path(__file__).parent.parent / "app" / "storage",          # default config.py
    Path(__file__).parent.parent / "storage",                  # legacy fallback
}

# Expand the user-specific production path from the ORIGINAL host STORAGE_ROOT
# (if the host set one).  We deliberately use the value captured BEFORE the
# session sandbox overwrote os.environ["STORAGE_ROOT"] — the sandbox itself must
# never be added here, or the guard would watch the very directory app startup
# and background threads legitimately write into.
if _ORIG_STORAGE_ROOT_ENV:
    _LIVE_ROOTS.add(Path(_ORIG_STORAGE_ROOT_ENV).resolve())


# SQLite WAL-mode sidecar extensions.  These are created by the SQLite engine
# whenever ANY connection opens a WAL-mode database — even a read-only one —
# as OS-level shared-memory coordination files.  They are NOT business data
# written by test logic.  Including them in the storage-leak check produces
# non-deterministic failures when an external or prior-session process has
# left a live database in WAL mode: the sidecar materialises during the test
# but is not attributable to the test itself.
#
# .db-wal  — write-ahead log (present when uncommitted WAL transactions exist)
# .db-shm  — shared-memory header (present whenever a WAL-mode DB is open)
# .db-journal — rollback journal (present during non-WAL transactions)
#
# Opened-for-reading-only databases that create these sidecars are a genuine
# test-isolation concern, but the storage guard is not the right tool to
# catch them: the guard implicates the *next* test, not the culprit.
# See GitHub issue filed alongside the conftest TOCTOU fix for follow-up.
_SQLITE_SIDECAR_SUFFIXES = (".db-shm", ".db-wal", ".db-journal", ".db-wal-summary")

# Background-service subdirectory prefixes to skip during leak detection.
#
# C:\PZ-verify\service\app\storage is the live storage directory for the
# PZ-verify clone.  Background services (AI gateway, DHL intake, PZ processor)
# write to specific subdirectories while tests run, producing non-deterministic
# false positives on whichever carrier test happens to be executing at that
# moment.  These paths are written ONLY by the respective service, never by
# test code.  A carrier test that accidentally calls a service touching these
# paths would be caught by other means (mock verification, service-level tests).
#
# ai_bridge/    — AI gateway background task queue (tasks/*.json)
# outputs/      — PZ batch processor outputs (per-batch directories)
# tracking/     — DHL tracking event cache
# email_evidence/ — DHL email evidence attachments
#
# If tests begin writing to these directories, remove the exclusion and fix
# the test isolation instead.  Each exclusion here is intentional debt; see
# the GitHub issue filed alongside this change for the follow-up audit.
_BACKGROUND_SERVICE_DIRS = frozenset({
    "ai_bridge",
    "outputs",
    "tracking",
    "email_evidence",
})


# Session-scoped baseline manifests.  Each distinct resolved root in
# _LIVE_ROOTS is walked exactly ONCE per pytest session (instead of twice
# per test).  The per-test guard does a single walk and diffs vs the
# running baseline, then updates it.  This trades a 4x-walk-per-test
# (was: ~1.6s/test on a 973-file/25.8MB tree) for a 1x-walk-per-test
# (~0.4s/test/root) while preserving NEW-file detection and adding
# IN-PLACE MODIFICATION detection (strictly stronger than the prior
# set-diff-on-paths-only check).
_DISTINCT_ROOTS: list[Path] = []
_BASELINE_MANIFEST: dict[Path, dict[str, tuple[int, int]]] = {}


def _build_root_manifest(resolved_lp: Path) -> dict[str, tuple[int, int]]:
    """Walk one resolved root and return {str(path): (st_mtime_ns, st_size)}.

    Skips SQLite WAL/SHM sidecars and background-service subdirectories
    (same exemptions as the old guard).  Wrap stat() in try/except because
    WAL-mode sidecars can vanish between rglob() and stat() on Windows.
    """
    manifest: dict[str, tuple[int, int]] = {}
    if not resolved_lp.exists():
        return manifest
    for f in resolved_lp.rglob("*"):
        if not f.is_file():
            continue
        if any(f.name.endswith(s) for s in _SQLITE_SIDECAR_SUFFIXES):
            continue
        try:
            rel = f.relative_to(resolved_lp)
            if rel.parts and rel.parts[0] in _BACKGROUND_SERVICE_DIRS:
                continue
        except ValueError:
            pass
        try:
            st = f.stat()
            manifest[str(f)] = (st.st_mtime_ns, st.st_size)
        except (FileNotFoundError, OSError):
            pass  # transient file vanished between rglob and stat
    return manifest


@pytest.fixture(scope="session", autouse=True)
def _storage_guard_session_baseline():
    """Build one baseline manifest per DISTINCT resolved live root.

    Roots that resolve to the same path (e.g. STORAGE_ROOT pointed at the
    same tree as the hardcoded default) are walked exactly once.
    """
    seen: set[Path] = set()
    for lp in _LIVE_ROOTS:
        try:
            resolved_lp = lp.resolve()
        except OSError:
            continue
        if resolved_lp in seen:
            continue
        seen.add(resolved_lp)
        _DISTINCT_ROOTS.append(resolved_lp)
        _BASELINE_MANIFEST[resolved_lp] = _build_root_manifest(resolved_lp)
    yield


@pytest.fixture(autouse=True)
def _guard_storage_root():
    """Detect tests that write OR modify files in live storage roots.

    Single walk per test (post-yield), diffed against a session-scoped
    baseline that is updated in place after every test.  Flags the first
    NEW or MODIFIED file and names the offending test via pytest.fail.

    Detection contract:
      - NEW file in a live root  -> fail (matches old guard).
      - MODIFIED file (mtime_ns or size differs)  -> fail (NEW: stricter
        than old guard, which captured mtime but never compared it).

    Monkeypatch compatibility: checking settings.storage_root in teardown
    is unreliable because monkeypatch restores the default before this
    fixture's teardown runs.  We diff the filesystem directly instead.

    Relationship to the session storage sandbox: the import-time redirect at
    the top of this file (_SESSION_STORAGE_SANDBOX) points settings.storage_root
    at a throwaway temp dir, so app startup, background threads, and import-time
    module constants all write there instead of the real live roots this guard
    watches.  The real roots therefore stay quiescent and this guard is
    deterministically 0-error regardless of storage pre-seeding.  The guard is
    retained as a backstop: it still catches a test that writes to a live root
    via a HARDCODED path (one that bypasses settings.storage_root).
    """
    if os.environ.get("PZ_SKIP_STORAGE_GUARD") == "1":
        yield
        return
    yield  # run the test

    leak: tuple[str, str, Path] | None = None
    for resolved_lp in _DISTINCT_ROOTS:
        baseline = _BASELINE_MANIFEST.get(resolved_lp, {})
        current = _build_root_manifest(resolved_lp)
        if leak is None:
            for path_key, sig in current.items():
                prior = baseline.get(path_key)
                if prior is None:
                    leak = ("new", path_key, resolved_lp)
                    break
                if prior != sig:
                    leak = ("modified", path_key, resolved_lp)
                    break
        # Update baseline so subsequent tests don't re-flag this leak.
        _BASELINE_MANIFEST[resolved_lp] = current

    if leak is not None:
        kind, path_key, resolved_lp = leak
        pytest.fail(
            f"STORAGE LEAK ({kind}): test wrote {path_key!r} into live "
            f"storage root {str(resolved_lp)!r}.  Use tmp_path / monkeypatch "
            f"to redirect settings.storage_root in the test or its autouse "
            f"fixture."
        )


# ── C-3g: mirror-complete product seeding (test-estate invariant) ────────────
# Production write paths are mirror-complete (Mirror Completeness Proof
# 37aaaf27): every confirmed-id product write feeds wfirma_product_mirror.
# Many legacy tests seed via raw wfirma_db.upsert_product (cache only); after
# C-3g's mirror-only business reads such a seed would leave the product
# invisible to routes. This shim upholds the production invariant for direct
# cache seeding: a non-empty wfirma_product_id also upserts the mirror in the
# SAME storage sandbox (derived from wfdb._db_path.parent, which the standard
# storage fixture keeps equal to the patched settings.storage_root).
# Unaffected by design: seeds with an empty id (divergence tests), tests that
# monkeypatch upsert_product themselves (their patch replaces this wrapper),
# and explicit mirror writes (upsert_product_mirror is idempotent).
# Ratified context: phase-c-master DECISIONS.md, C-3g slice decisions.

@pytest.fixture(autouse=True)
def _mirror_complete_product_seeding(monkeypatch):
    try:
        from app.services import wfirma_db as _wfdb
        from app.services import reservation_db as _rdb
    except Exception:
        yield
        return
    _orig = _wfdb.upsert_product

    def _mirror_complete(product_code, **kwargs):
        res = _orig(product_code, **kwargs)
        wid = (kwargs.get("wfirma_product_id") or "").strip()
        try:
            if wid and _wfdb._db_path is not None:
                mdb = Path(_wfdb._db_path).parent / "reservation_queue.db"
                _rdb.init_reservation_db(mdb)
                _rdb.upsert_product_mirror(mdb, wfirma_id=wid, product_code=product_code)
        except Exception:
            pass  # the seeding shim must never fail a test on its own
        return res

    monkeypatch.setattr(_wfdb, "upsert_product", _mirror_complete)
    yield
