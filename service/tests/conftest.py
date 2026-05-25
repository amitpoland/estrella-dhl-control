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
    # Snapshot existing files in live-storage directories before the test
    before: dict = {}
    for lp in _LIVE_ROOTS:
        resolved_lp = lp.resolve()
        if resolved_lp.exists():
            for f in resolved_lp.rglob("*"):
                if f.is_file():
                    before[str(f)] = f.stat().st_mtime

    yield  # run the test

    # After the test: fail if any NEW file was written to live storage
    for lp in _LIVE_ROOTS:
        resolved_lp = lp.resolve()
        if resolved_lp.exists():
            for f in resolved_lp.rglob("*"):
                if f.is_file() and str(f) not in before:
                    pytest.fail(
                        f"STORAGE LEAK: test wrote {f!r} into live storage root "
                        f"{resolved_lp!r}.  Use tmp_path / monkeypatch to redirect "
                        f"settings.storage_root in the test or its autouse fixture."
                    )
