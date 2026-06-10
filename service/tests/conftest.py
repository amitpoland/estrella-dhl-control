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


@pytest.fixture(autouse=True)
def _guard_storage_root():
    """Detect tests that write files into live storage roots.

    Snapshots live storage before the test runs, then checks for any new files
    after the test completes. Fails only if a file was actually written to a
    live directory.

    This approach is compatible with monkeypatch: checking settings.storage_root
    in teardown is unreliable because monkeypatch restores the live-path default
    before this fixture's teardown runs, causing false positives on every
    correctly-patched test.
    """
    # Snapshot existing files in live-storage directories before the test.
    # Wrap stat() in a try-except: WAL-mode sidecar files (.db-wal, .db-shm)
    # can disappear between rglob() and stat() when SQLite performs a final
    # checkpoint and removes them (TOCTOU race on Windows).  A file that
    # vanishes at this point was not written by this test, so silently skip it.
    before: dict = {}
    for lp in _LIVE_ROOTS:
        resolved_lp = lp.resolve()
        if resolved_lp.exists():
            for f in resolved_lp.rglob("*"):
                if f.is_file():
                    try:
                        before[str(f)] = f.stat().st_mtime
                    except (FileNotFoundError, OSError):
                        pass  # transient file vanished between rglob and stat

    yield  # run the test

    # After the test: fail if any NEW file was written to live storage.
    # SQLite WAL/SHM sidecar files and background-service directories are
    # excluded — see _SQLITE_SIDECAR_SUFFIXES and _BACKGROUND_SERVICE_DIRS.
    for lp in _LIVE_ROOTS:
        resolved_lp = lp.resolve()
        if resolved_lp.exists():
            for f in resolved_lp.rglob("*"):
                if not f.is_file():
                    continue
                if str(f) in before:
                    continue
                if any(f.name.endswith(s) for s in _SQLITE_SIDECAR_SUFFIXES):
                    continue
                # Skip files under background-service subdirectories.
                try:
                    rel = f.relative_to(resolved_lp)
                    if rel.parts and rel.parts[0] in _BACKGROUND_SERVICE_DIRS:
                        continue
                except ValueError:
                    pass
                pytest.fail(
                    f"STORAGE LEAK: test wrote {f!r} into live storage root "
                    f"{resolved_lp!r}.  Use tmp_path / monkeypatch to redirect "
                    f"settings.storage_root in the test or its autouse fixture."
                )
