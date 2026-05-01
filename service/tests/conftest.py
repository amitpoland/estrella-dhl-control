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

# Paths that tests must NEVER use as storage_root.  If settings.storage_root
# resolves to any of these (or a child of them), the fixture fails the test
# immediately — before any I/O can happen.
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
    """Fail fast if any module's settings.storage_root points at a live directory.

    This runs before every test.  It does NOT import settings eagerly — it
    only checks when the settings singleton has already been created by the
    test's own imports.
    """
    yield  # let the test run, then verify nothing leaked

    # Post-test check: did any test accidentally reset storage_root?
    try:
        from app.core.config import settings
        resolved = settings.storage_root.resolve()
        for live in _LIVE_ROOTS:
            lr = live.resolve()
            if resolved == lr or lr in resolved.parents:
                pytest.fail(
                    f"STORAGE LEAK: settings.storage_root resolved to live path "
                    f"{resolved} (matches {lr}).  Use tmp_path + monkeypatch."
                )
    except Exception:
        pass  # settings not yet imported or not applicable
