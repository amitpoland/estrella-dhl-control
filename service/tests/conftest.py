"""conftest.py — shared pytest fixtures and path setup."""
import os
import sys
from pathlib import Path

import pytest

# customs_description_engine.py lives at the CLI root (one level above service/)
_cli_root = Path(__file__).parent.parent.parent  # Downloads/CLI/
if str(_cli_root) not in sys.path:
    sys.path.insert(0, str(_cli_root))


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

    # Reset both circuit breakers
    if gw is not None:
        gw.reset_circuit_breaker()
        gw.reset_cowork_circuit_breaker()

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


# ── Safety fixture: prevent tests from writing to live storage ───────────────

# Paths that tests must NEVER write new files into.
_LIVE_ROOTS = {
    Path(__file__).parent.parent / "app" / "storage",          # default config.py
    Path(__file__).parent.parent / "storage",                  # legacy fallback
}

# Expand the user-specific production path from .env (if set)
_env_storage = os.environ.get("STORAGE_ROOT")
if _env_storage:
    _LIVE_ROOTS.add(Path(_env_storage).resolve())


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
    """
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
