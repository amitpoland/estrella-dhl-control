"""
verify_runtime_sync.py — detect and fix dev-source / runtime divergence.

The service imports Python engine files (pz_import_processor, etc.) at runtime.
If an older copy of those files was installed into site-packages (e.g. via
``pip install .``), Python will find that copy first and silently use stale code
even after the dev source is updated.

This tool:
  1. Resolves the actual import path Python would use for each critical module.
  2. Compares its SHA-256 against the dev-source copy.
  3. Prints a mismatch table and exits non-zero on any divergence.

Flags
-----
  (default)        verify only — print table, exit 1 on any mismatch
  --sync           copy every mismatched dev-source file → runtime path
  --restart-hint   print the kill/restart command (does NOT execute it)

Usage
-----
  python3 -m app.tools.verify_runtime_sync
  python3 -m app.tools.verify_runtime_sync --sync
  python3 -m app.tools.verify_runtime_sync --restart-hint

Run before every live test to confirm the runtime is using current code.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

# ── Locate dev roots ──────────────────────────────────────────────────────────

# This file lives at  service/app/tools/verify_runtime_sync.py
_TOOLS_DIR   = Path(__file__).parent.resolve()
_APP_DIR     = _TOOLS_DIR.parent          # service/app/
_SERVICE_DIR = _APP_DIR.parent            # service/
_CLI_DIR     = _SERVICE_DIR.parent        # CLI/  (engine_dir)

# ── Critical file registry ────────────────────────────────────────────────────
# Each entry maps a logical name to:
#   dev_path  — authoritative source file (absolute)
#   module    — Python dotted import name used by the service (None = no module)
#
# For pure-Python modules the tool uses importlib.util.find_spec() to locate
# the file Python would actually load.  For static assets (dashboard.html) it
# checks the file in-place.

class _Entry(NamedTuple):
    label:   str
    dev_path: Path
    module:  Optional[str]   # dotted module name, or None for static files


_CRITICAL: List[_Entry] = [
    # ── Engine (lives in CLI root, NOT service/app) ──────────────────────────
    _Entry("pz_import_processor",
           _CLI_DIR / "pz_import_processor.py",
           "pz_import_processor"),
    _Entry("pz_pdf_export",
           _CLI_DIR / "pz_pdf_export.py",
           "pz_pdf_export"),
    _Entry("pz_dual_export",
           _CLI_DIR / "pz_dual_export.py",
           "pz_dual_export"),
    _Entry("invoice_learning_agent",
           _CLI_DIR / "invoice_learning_agent.py",
           "invoice_learning_agent"),

    # ── Service — API routes ─────────────────────────────────────────────────
    _Entry("routes_upload",
           _APP_DIR / "api" / "routes_upload.py",
           "app.api.routes_upload"),
    _Entry("routes_dashboard",
           _APP_DIR / "api" / "routes_dashboard.py",
           "app.api.routes_dashboard"),
    _Entry("routes_lifecycle",
           _APP_DIR / "api" / "routes_lifecycle.py",
           "app.api.routes_lifecycle"),
    _Entry("routes_execute",
           _APP_DIR / "api" / "routes_execute.py",
           "app.api.routes_execute"),

    # ── Service — core services ──────────────────────────────────────────────
    _Entry("export_service",
           _APP_DIR / "services" / "export_service.py",
           "app.services.export_service"),
    _Entry("batch_state_normalizer",
           _APP_DIR / "services" / "batch_state_normalizer.py",
           "app.services.batch_state_normalizer"),
    _Entry("audit_merge",
           _APP_DIR / "services" / "audit_merge.py",
           "app.services.audit_merge"),
    _Entry("execution_engine",
           _APP_DIR / "services" / "execution_engine.py",
           "app.services.execution_engine"),

    # ── Static assets ────────────────────────────────────────────────────────
    _Entry("dashboard.html",
           _APP_DIR / "static" / "dashboard.html",
           None),  # not a Python module; checked in-place only
]

# Safety guard: never copy anything under these paths
_FORBIDDEN_DEST_PREFIXES: tuple = (
    "storage",
    "archived",
    "outputs",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _runtime_path(entry: _Entry) -> Optional[Path]:
    """Return the path Python would actually load for this entry, or None."""
    if entry.module is None:
        # Static asset — no separate "runtime" path; always the dev path
        return entry.dev_path if entry.dev_path.is_file() else None

    # Temporarily ensure engine_dir is on sys.path (mirrors export_service.py)
    engine_str = str(_CLI_DIR)
    injected = engine_str not in sys.path
    if injected:
        sys.path.insert(0, engine_str)
    try:
        spec = importlib.util.find_spec(entry.module)
    except (ModuleNotFoundError, ValueError):
        spec = None
    finally:
        if injected:
            sys.path.remove(engine_str)

    if spec is None or not spec.origin:
        return None
    p = Path(spec.origin).resolve()
    return p if p.is_file() else None


def _is_production(path: Path) -> bool:
    """True if `path` lives inside the production runtime tree.

    Matches C:\\PZ and C:\\PZ\\... but NOT C:\\PZ-main, C:\\PZ-verify, C:\\PZ-releases,
    C:\\PZ-backups -- the same token rule pz-deploy-guard.py applies.
    """
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    return re.match(r"(?i)^c:[\\/]pz(?![\w\-])", resolved) is not None


def _is_forbidden(path: Path) -> bool:
    # The production runtime tree is NEVER a sync destination. Deployment into
    # production has exactly one authority: .claude/deploy/Deploy-PZ.ps1, which is
    # gated by a signed operator authorization, takes a lock, creates a
    # manifest-verified backup, and is deny-listed for agents by pz-deploy-guard.py.
    # This tool is a diagnostic; it must never become a second deployment path.
    if _is_production(path):
        return True
    parts = path.parts
    for forbidden in _FORBIDDEN_DEST_PREFIXES:
        if forbidden in parts:
            return True
    return False


# ── Result dataclass ──────────────────────────────────────────────────────────

class _Result(NamedTuple):
    label:       str
    dev_path:    Path
    runtime_path: Optional[Path]
    dev_exists:  bool
    rt_exists:   bool
    shadowed:    bool    # runtime_path != dev_path
    mismatch:    bool    # checksums differ (only meaningful when shadowed=True)
    dev_hash:    str
    rt_hash:     str


def _check(entry: _Entry) -> _Result:
    rt = _runtime_path(entry)
    dev_exists = entry.dev_path.is_file()
    rt_exists  = rt is not None and rt.is_file()
    shadowed   = rt_exists and (rt.resolve() != entry.dev_path.resolve())
    dev_hash   = _sha256(entry.dev_path) if dev_exists else ""
    rt_hash    = _sha256(rt)             if rt_exists  else ""
    mismatch   = shadowed and (dev_hash != rt_hash)
    return _Result(
        label        = entry.label,
        dev_path     = entry.dev_path,
        runtime_path = rt,
        dev_exists   = dev_exists,
        rt_exists    = rt_exists,
        shadowed     = shadowed,
        mismatch     = mismatch,
        dev_hash     = dev_hash,
        rt_hash      = rt_hash,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

_RESTART_CMD = (
    "pkill -9 -f 'uvicorn app.main' ; "
    "pkill -9 -f 'pz-launcher' ; "
    "echo 'Processes killed — restart the service manually'"
)

_COL = {
    "OK":      "\033[32m✔ OK\033[0m",
    "STALE":   "\033[31m✘ STALE\033[0m",
    "MISSING": "\033[33m? MISSING\033[0m",
    "SHADOWED":"\033[33m⚑ SHADOW-OK\033[0m",
}


def _status(r: _Result) -> str:
    if not r.dev_exists:
        return "MISSING"
    if r.mismatch:
        return "STALE"
    if r.shadowed:
        return "SHADOWED"   # same content, different path — unusual but not broken
    return "OK"


def _print_table(results: List[_Result]) -> None:
    print()
    print(f"  {'Label':<30}  {'Status':<12}  {'Runtime path'}")
    print(f"  {'-'*30}  {'-'*12}  {'-'*60}")
    for r in results:
        st  = _status(r)
        col = _COL.get(st, st)
        rp  = str(r.runtime_path) if r.runtime_path else "(not found)"
        print(f"  {r.label:<30}  {col:<22}  {rp}")
    print()


def _sync_file(r: _Result) -> None:
    if not r.dev_exists:
        print(f"  [SKIP] {r.label}: dev source missing — cannot sync")
        return
    if r.runtime_path is None or not str(r.runtime_path).strip():
        print(f"  [SKIP] {r.label}: no runtime path resolved — cannot sync")
        return
    if _is_forbidden(r.runtime_path):
        print(f"  [SKIP] {r.label}: runtime path under forbidden prefix — refusing")
        return
    r.runtime_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(r.dev_path, r.runtime_path)
    print(f"  [SYNC] {r.label}: {r.dev_path} → {r.runtime_path}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify dev-source / runtime-Python file sync for PZ service."
    )
    ap.add_argument("--sync",          action="store_true",
                    help="Copy mismatched files from dev source → runtime path.")
    ap.add_argument("--restart-hint",  action="store_true",
                    help="Print the kill/restart command (does not execute it).")
    args = ap.parse_args(argv)

    results: List[_Result] = [_check(e) for e in _CRITICAL]
    _print_table(results)

    mismatches: List[_Result] = [r for r in results if r.mismatch]
    missing:    List[_Result] = [r for r in results if not r.dev_exists]

    if args.sync:
        if mismatches:
            print("  Syncing mismatched files…")
            for r in mismatches:
                _sync_file(r)
            print()
        else:
            print("  Nothing to sync — all files match.")
            print()

    if args.restart_hint:
        print("  Restart hint (copy and run manually):")
        print(f"    {_RESTART_CMD}")
        print()

    if missing:
        print(f"  ✘ {len(missing)} dev source file(s) not found — check paths.")
    if mismatches:
        print(f"  ✘ {len(mismatches)} file(s) stale in runtime. "
              f"Run with --sync to fix, then restart the service.")
        return 1
    if not missing:
        print(f"  ✔ All {len(results)} critical files are in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
