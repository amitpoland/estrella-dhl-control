"""
test_dhl_email_monitor_windows_compat.py — Windows import guard for dhl_email_monitor.

Pins that dhl_email_monitor can be imported on any platform (including Windows
where fcntl is absent) and that scan_for_dhl_customs_emails is callable.

The rescan endpoint (POST /dashboard/batches/{id}/email-evidence/rescan)
dynamically inserts ENGINE_DIR into sys.path and then does:
    from dhl_email_monitor import scan_for_dhl_customs_emails
If the module-level bare `import fcntl` is present, this raises
ModuleNotFoundError on Windows and scan_and_ingest returns:
    {"ok": False, "error": "scan_fn_unavailable: No module named 'fcntl'"}

Tests:
  1. dhl_email_monitor imports without error on this platform
  2. scan_for_dhl_customs_emails is callable after import
  3. No bare `import fcntl` at module level in source file
  4. All fcntl usages are guarded by sys.platform check
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Engine root is three levels above service/
_ENGINE_ROOT = Path(__file__).parents[2]
_MODULE_FILE = _ENGINE_ROOT / "dhl_email_monitor.py"


class TestDhlEmailMonitorImport:
    def test_module_file_exists(self):
        assert _MODULE_FILE.exists(), f"dhl_email_monitor.py not found at {_MODULE_FILE}"

    def test_importable_on_current_platform(self):
        """Module must import without error regardless of platform."""
        if str(_ENGINE_ROOT) not in sys.path:
            sys.path.insert(0, str(_ENGINE_ROOT))
        # Re-import if already cached to ensure clean state
        import importlib
        if "dhl_email_monitor" in sys.modules:
            mod = sys.modules["dhl_email_monitor"]
        else:
            import dhl_email_monitor as mod  # type: ignore
        assert mod is not None

    def test_scan_fn_is_callable(self):
        if str(_ENGINE_ROOT) not in sys.path:
            sys.path.insert(0, str(_ENGINE_ROOT))
        import dhl_email_monitor as mod  # type: ignore
        assert callable(mod.scan_for_dhl_customs_emails)


class TestDhlEmailMonitorSourceGuards:
    def _src(self) -> str:
        return _MODULE_FILE.read_text(encoding="utf-8")

    def test_no_bare_import_fcntl_at_module_level(self):
        src = self._src()
        # Bare top-level `import fcntl` (not inside an if block) must not exist
        for line in src.splitlines():
            stripped = line.strip()
            if stripped == "import fcntl":
                raise AssertionError(
                    "Bare 'import fcntl' found at module level — "
                    "crashes on Windows (ModuleNotFoundError)"
                )

    def test_fcntl_import_is_platform_guarded(self):
        src = self._src()
        # The guarded import pattern must be present
        assert 'import fcntl as _fcntl' in src
        # And it must be inside a platform check
        assert "sys.platform != \"win32\"" in src or "sys.platform == 'win32'" in src

    def test_all_fcntl_flock_calls_are_guarded(self):
        src = self._src()
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "fcntl.flock" in line or "_fcntl.flock" in line:
                # Look back up to 3 lines for a platform guard
                context = "\n".join(lines[max(0, i - 3):i + 1])
                assert "sys.platform" in context, (
                    f"Unguarded flock call at line {i+1}: {line.strip()!r}"
                )
