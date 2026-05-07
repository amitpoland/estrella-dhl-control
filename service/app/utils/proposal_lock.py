"""
proposal_lock.py — Per-batch in-process advisory lock for action-proposal mutation.

Distinct from :mod:`app.utils.batch_lock` (fcntl, audit-file scope).

This lock guards two critical sections in the action-proposals lifecycle:

  * proposal CREATE — load audit → dedup scan → append → write
  * proposal QUEUE  — fresh audit reload → guard checks → queue_email → mutate → write

Two POSTs against the same batch must serialise under the SAME lock object so
that the dedup-by-active-status check inside :func:`create_proposal` and the
authoritative re-resolution inside :func:`queue_proposal` cannot be raced.

Scope:
  * In-process only (single FastAPI worker — ratified architectural decision).
  * Distinct from :func:`app.utils.batch_lock.batch_write_lock` (fcntl).
    The two locks protect different invariants and live at different layers;
    nesting them is allowed only in the documented direction (audit-file lock
    inside proposal lock — never the reverse).
"""
from __future__ import annotations

import threading
from typing import Dict

# Module-level dict of per-batch locks. The dict ITSELF is mutated under
# _REGISTRY_GUARD; the locks it returns are independent.
_PROPOSAL_LOCKS: Dict[str, threading.Lock] = {}
_REGISTRY_GUARD: threading.Lock = threading.Lock()


def proposal_write_lock(batch_id: str) -> threading.Lock:
    """
    Return the per-batch :class:`threading.Lock` for *batch_id*.

    The same lock object is returned across calls for the same *batch_id*;
    different batch_ids get independent locks. Lazy creation under
    *_REGISTRY_GUARD* so two concurrent first-time callers cannot race the
    dict insert.

    Caller usage::

        with proposal_write_lock(batch_id):
            # critical section: load audit, mutate, write

    The returned object is the underlying lock primitive — callers may also
    use ``acquire(timeout=...)`` directly if a non-blocking variant is
    needed in the future.
    """
    lock = _PROPOSAL_LOCKS.get(batch_id)
    if lock is not None:
        return lock
    with _REGISTRY_GUARD:
        lock = _PROPOSAL_LOCKS.get(batch_id)
        if lock is None:
            lock = threading.Lock()
            _PROPOSAL_LOCKS[batch_id] = lock
        return lock


def _reset_locks_for_tests() -> None:
    """Test-only: drop all per-batch locks. NEVER call from production code."""
    with _REGISTRY_GUARD:
        _PROPOSAL_LOCKS.clear()
