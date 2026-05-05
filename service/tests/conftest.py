"""conftest.py — shared pytest fixtures and path setup."""
import os
import sys
from pathlib import Path

import pytest

# customs_description_engine.py lives at the CLI root (one level above service/)
_cli_root = Path(__file__).parent.parent.parent  # Downloads/CLI/
if str(_cli_root) not in sys.path:
    sys.path.insert(0, str(_cli_root))


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
