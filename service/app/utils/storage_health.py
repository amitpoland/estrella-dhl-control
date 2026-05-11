"""
storage_health.py — Read-only storage and batch-lock diagnostic functions.

Pure utility module: no FastAPI imports, no HTTP calls, no writes.
All functions are safe to call from any context (route handler, CLI, test).

Public API:
    classify_outputs(outputs_dir)      — categorise subdirs of outputs/
    probe_lock(batch_id, outputs_dir)  — inspect one .audit.lock file
    scan_locks(outputs_dir)            — probe all .audit.lock files in outputs/
    storage_health_snapshot(storage_root) — full health snapshot (compose all)

Lock probe behaviour:
    Opens the existing .audit.lock file in READ-ONLY mode.
    Attempts fcntl.LOCK_EX | LOCK_NB.
    If acquired  → release immediately, report releasable.
    If blocked   → report actively_held (lock held by another OS process).
    Never creates, truncates, or deletes lock files.

macOS / same-process caveat:
    fcntl.flock() advisory locks are per-process on macOS and Linux.
    Threads in the SAME process always appear able to acquire the lock —
    so actively_held=True reliably detects only locks held by OTHER OS processes
    (e.g. a crashed or concurrent uvicorn worker).  This is documented in every
    response via the 'probe_note' field.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

if sys.platform != "win32":
    import fcntl as _fcntl

log = logging.getLogger(__name__)

_PROBE_NOTE = (
    "fcntl.flock is process-scoped on macOS/Linux. "
    "actively_held=True reliably detects locks held by OTHER OS processes only "
    "(e.g. crashed or concurrent uvicorn workers). "
    "Same-process threads always appear releasable."
)
_PROBE_NOTE_WINDOWS = (
    "Windows: fcntl not available. Cross-process lock detection is skipped. "
    "actively_held is always False on this platform."
)


# ── Classification helpers ────────────────────────────────────────────────────

def _classify_name(name: str) -> str:
    """Return the category string for a directory name."""
    if name.startswith("SHIPMENT_"):
        return "real"
    if name.startswith("B_") or name.startswith("TEST_"):
        return "test"
    if "quarantine" in name.lower():
        return "quarantine"
    return "anomalous"


# ── Public functions ──────────────────────────────────────────────────────────

def classify_outputs(outputs_dir: Path) -> Dict[str, Any]:
    """
    Scan the outputs/ directory and categorise each subdirectory.

    Categories:
        real_batches   — directories matching SHIPMENT_*
        test_batches   — directories matching B_* or TEST_*
        quarantine_dirs — directories whose name contains "quarantine"
        anomalous_dirs — everything else

    Rules:
        - Never reads file contents (no audit.json access)
        - Never modifies any file
        - Missing outputs_dir is not an error: returns all-zero counts

    Returns:
        {
            real_batches:     int,
            test_batches:     int,
            test_batch_ids:   list[str],
            quarantine_dirs:  int,
            quarantine_names: list[str],
            anomalous_dirs:   int,
            anomalous_names:  list[str],
        }
    """
    result: Dict[str, Any] = {
        "real_batches":     0,
        "test_batches":     0,
        "test_batch_ids":   [],
        "quarantine_dirs":  0,
        "quarantine_names": [],
        "anomalous_dirs":   0,
        "anomalous_names":  [],
    }

    if not outputs_dir.is_dir():
        return result

    for entry in sorted(outputs_dir.iterdir()):
        if not entry.is_dir():
            continue
        cat = _classify_name(entry.name)
        if cat == "real":
            result["real_batches"] += 1
        elif cat == "test":
            result["test_batches"] += 1
            result["test_batch_ids"].append(entry.name)
        elif cat == "quarantine":
            result["quarantine_dirs"] += 1
            result["quarantine_names"].append(entry.name)
        else:
            result["anomalous_dirs"] += 1
            result["anomalous_names"].append(entry.name)

    return result


def probe_lock(batch_id: str, outputs_dir: Path) -> Dict[str, Any]:
    """
    Non-destructively probe a single batch's .audit.lock file.

    Opens the file read-only (never creates it).  Attempts LOCK_EX | LOCK_NB.
    If acquired, releases immediately and reports releasable.
    If blocked, reports actively_held without disturbing the lock.

    Returns:
        {
            batch_id:         str,
            lock_file_exists: bool,
            actively_held:    bool,   # True only if held by another OS process
        }
    """
    lock_path = outputs_dir / batch_id / ".audit.lock"

    result: Dict[str, Any] = {
        "batch_id":         batch_id,
        "lock_file_exists": False,
        "actively_held":    False,
    }

    if not lock_path.exists():
        return result

    result["lock_file_exists"] = True

    if sys.platform == "win32":
        # fcntl not available on Windows; threading.Lock is in-process only
        # so cross-process lock detection is not meaningful here.
        return result

    try:
        # Open read-only — will NOT create the file if it doesn't exist.
        fd = open(lock_path, "r")
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            # Acquired — not held by another process; release immediately.
            _fcntl.flock(fd, _fcntl.LOCK_UN)
            result["actively_held"] = False
        except (BlockingIOError, OSError):
            # Lock is held by another OS process.
            result["actively_held"] = True
        finally:
            fd.close()
    except Exception as exc:
        log.warning("[storage_health] probe_lock error for %s: %s", batch_id, exc)

    return result


def scan_locks(outputs_dir: Path) -> Dict[str, Any]:
    """
    Find all .audit.lock files under outputs/ and probe each.

    Returns:
        {
            lock_files_found: int,
            actively_held:    int,
            releasable:       int,
            details:          list[dict],  # one entry per lock file found
            probe_note:       str,
        }
    """
    result: Dict[str, Any] = {
        "lock_files_found": 0,
        "actively_held":    0,
        "releasable":       0,
        "details":          [],
        "probe_note":       _PROBE_NOTE_WINDOWS if sys.platform == "win32" else _PROBE_NOTE,
    }

    if not outputs_dir.is_dir():
        return result

    for batch_dir in sorted(outputs_dir.iterdir()):
        if not batch_dir.is_dir():
            continue
        lock_path = batch_dir / ".audit.lock"
        if not lock_path.exists():
            continue

        probe = probe_lock(batch_dir.name, outputs_dir)
        result["lock_files_found"] += 1
        result["details"].append(probe)

        if probe["actively_held"]:
            result["actively_held"] += 1
        else:
            result["releasable"] += 1

    return result


def storage_health_snapshot(storage_root: Path) -> Dict[str, Any]:
    """
    Full storage health snapshot.

    Combines classify_outputs + scan_locks into a single structured response.

    ok=False if:
        - test_batches > 0   (test pollution in live storage)
        - actively_held > 0  (stale locks from another OS process)

    Quarantine and anomalous dirs are warnings (not fatal).

    Returns:
        {
            ok:                bool,
            checked_at:        str,   # ISO 8601 UTC
            outputs:           dict,  # from classify_outputs
            locks:             dict,  # from scan_locks
            warnings:          list[str],
            errors:            list[str],
        }
    """
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    outputs_dir = storage_root / "outputs"

    warnings: List[str] = []
    errors:   List[str] = []

    # ── Classify outputs ──────────────────────────────────────────────────────
    try:
        outputs = classify_outputs(outputs_dir)
    except Exception as exc:
        log.error("[storage_health] classify_outputs failed: %s", exc)
        errors.append(f"classify_outputs error: {exc}")
        outputs = {
            "real_batches":     0,
            "test_batches":     0,
            "test_batch_ids":   [],
            "quarantine_dirs":  0,
            "quarantine_names": [],
            "anomalous_dirs":   0,
            "anomalous_names":  [],
        }

    # ── Scan locks ────────────────────────────────────────────────────────────
    try:
        locks = scan_locks(outputs_dir)
    except Exception as exc:
        log.error("[storage_health] scan_locks failed: %s", exc)
        errors.append(f"scan_locks error: {exc}")
        locks = {
            "lock_files_found": 0,
            "actively_held":    0,
            "releasable":       0,
            "details":          [],
            "probe_note":       _PROBE_NOTE_WINDOWS if sys.platform == "win32" else _PROBE_NOTE,
        }

    # ── Warnings ──────────────────────────────────────────────────────────────
    if outputs["test_batches"] > 0:
        warnings.append(
            f"Test pollution: {outputs['test_batches']} test batch(es) found in outputs/ "
            f"({', '.join(outputs['test_batch_ids'][:5])}{'…' if len(outputs['test_batch_ids']) > 5 else ''})"
        )
    if outputs["quarantine_dirs"] > 0:
        warnings.append(
            f"Quarantine dirs present: {outputs['quarantine_dirs']} "
            f"({', '.join(outputs['quarantine_names'][:5])})"
        )
    if outputs["anomalous_dirs"] > 0:
        warnings.append(
            f"Anomalous dirs in outputs/: {outputs['anomalous_dirs']} "
            f"({', '.join(outputs['anomalous_names'][:5])})"
        )
    if locks["lock_files_found"] > 0:
        warnings.append(
            f"{locks['lock_files_found']} .audit.lock file(s) exist in outputs/. "
            f"actively_held={locks['actively_held']} (other-process locks only)."
        )

    # ── ok determination ──────────────────────────────────────────────────────
    ok = (
        outputs["test_batches"] == 0
        and locks["actively_held"] == 0
        and not errors
    )

    return {
        "ok":        ok,
        "checked_at": checked_at,
        "outputs":   outputs,
        "locks":     locks,
        "warnings":  warnings,
        "errors":    errors,
    }
