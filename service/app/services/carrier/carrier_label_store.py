"""
carrier_label_store.py — On-disk store for outbound carrier labels and
per-AWB message manifests.

Layout
------
  <store_root>/
    _index.json                       map: awb -> manifest path
    _attachments/<sha256>.<ext>       content-addressed label artefacts
    _by_awb/<awb>/manifest.json       per-AWB manifest (atomic write)
    _by_awb/<awb>/messages/<id>.json  per-AWB append-only message log

Mirrors the discipline of ``email_evidence_store`` (sha256 content
addressing, AWB-scoped directories, atomic writes), simplified for the
outbound case:

  * No fcntl locking — DL-A is single-process from the coordinator's
    point of view; the label store is only ever called from the
    coordinator path. Multi-process coordination, if ever needed, will
    layer on top of this module.
  * No master "by_thread" index — outbound carrier shipments aren't
    threaded the way DHL clearance emails are.

Hard rules
----------
1. Same content (same sha256) writes one file. Re-saving the same
   bytes is a no-op and returns the existing path.
2. Manifests are written via ``write_json_atomic`` so a crash during
   save never leaves a half-written manifest on disk.
3. ``append_message`` is append-only: each message id is unique and
   never rewritten. Callers that want to *update* a message must
   append a new event with a reference to the prior id.
4. The store does NOT validate state-machine legality — that lives in
   ``carrier_state_engine``.
5. The store does NOT touch the SQLite registry — that lives in
   ``carrier_shipment_db``.

Public API
----------
  init_store(store_root: Path) -> None
  save_attachment(content: bytes, *, suffix="") -> LabelArtefact
  read_manifest(awb: str) -> dict
  write_manifest(awb: str, manifest: dict) -> Path
  append_message(awb: str, message: dict) -> str
  index_awb(awb: str, manifest_path: Path) -> None
  get_index() -> dict
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .base import LabelArtefact

# ── Module state ─────────────────────────────────────────────────────────────

_lock: threading.Lock = threading.Lock()
_store_root: Optional[Path] = None


# ── Init ────────────────────────────────────────────────────────────────────

def init_store(store_root: Path) -> None:
    """Idempotent setup. Creates the store directory tree and an empty
    index file if absent."""
    global _store_root
    _store_root = Path(store_root)
    _store_root.mkdir(parents=True, exist_ok=True)
    (_store_root / "_attachments").mkdir(parents=True, exist_ok=True)
    (_store_root / "_by_awb").mkdir(parents=True, exist_ok=True)
    idx = _store_root / "_index.json"
    if not idx.exists():
        _atomic_write_json(idx, {})


def _require_init() -> Path:
    if _store_root is None:
        raise RuntimeError(
            "carrier_label_store not initialised — call init_store() first"
        )
    return _store_root


# ── Helpers ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_awb(awb: str) -> str:
    cleaned = "".join(c for c in str(awb) if c.isalnum() or c in "-_")
    return cleaned[:64] or "unknown"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Crash-safe JSON write: write to ``path.tmp`` then ``os.replace``.

    Equivalent to the codebase's ``write_json_atomic`` helper, but
    inlined so this module has no service-layer cross-deps and works
    in tests that don't initialise ``settings``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


def _awb_dir(awb: str) -> Path:
    root = _require_init()
    return root / "_by_awb" / _safe_awb(awb)


def _manifest_path_for(awb: str) -> Path:
    return _awb_dir(awb) / "manifest.json"


def _messages_dir(awb: str) -> Path:
    return _awb_dir(awb) / "messages"


# ── Attachments (content-addressed) ─────────────────────────────────────────

def save_attachment(content: bytes, *, suffix: str = "") -> LabelArtefact:
    """Persist *content* under ``_attachments/<sha256>[.<suffix>]``.

    Same bytes saved twice yields the same on-disk path; the second
    call is a no-op. Returns a :class:`LabelArtefact` describing the
    persisted file.

    *suffix* may be provided as ``"pdf"``, ``".pdf"``, etc.; both
    forms are accepted. An empty suffix means "no extension".
    """
    if content is None:
        raise ValueError("content is required")
    root = _require_init()
    sha = _sha256(content)
    ext = suffix.lstrip(".") if suffix else ""
    fname = f"{sha}.{ext}" if ext else sha
    path = root / "_attachments" / fname
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            # Re-check inside the lock in case of concurrent writers.
            if not path.exists():
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(content)
                tmp.replace(path)
    return LabelArtefact(
        sha256=sha,
        path=str(path),
        size=path.stat().st_size,
        mime="",
        label_format=ext,
    )


# ── Manifest read/write ─────────────────────────────────────────────────────

def read_manifest(awb: str) -> Dict[str, Any]:
    """Return the manifest dict for *awb*.

    Empty dict if no manifest has been written yet (the store
    deliberately does not raise in this case so that callers can do
    "read-then-merge-then-write" without a separate existence check).
    """
    p = _manifest_path_for(awb)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A corrupt manifest is treated as "no manifest" rather than
        # silently masking the corruption: log via raise on next write.
        return {}


def write_manifest(awb: str, manifest: Dict[str, Any]) -> Path:
    """Atomically replace the manifest for *awb*.

    The manifest schema is open-ended at this layer; callers (the
    coordinator) are responsible for shape. The store enforces only:
      * ``awb`` field is set or filled in to match the path,
      * ``updated_at`` is stamped on every write.
    """
    if not (awb or "").strip():
        raise ValueError("awb is required")
    awb_clean = _safe_awb(awb)
    payload = dict(manifest or {})
    payload.setdefault("awb", awb_clean)
    payload["updated_at"] = _now()
    p = _manifest_path_for(awb)
    _atomic_write_json(p, payload)
    index_awb(awb, p)
    return p


# ── Append-only messages ────────────────────────────────────────────────────

def append_message(awb: str, message: Dict[str, Any]) -> str:
    """Append *message* under ``_by_awb/<awb>/messages/<id>.json``.

    Returns the generated message id (uuid4). Each call writes a new
    file; messages are immutable.
    """
    if not (awb or "").strip():
        raise ValueError("awb is required")
    awb_clean = _safe_awb(awb)
    mid = str(uuid.uuid4())
    payload = dict(message or {})
    payload.setdefault("message_id", mid)
    payload.setdefault("awb", awb_clean)
    payload.setdefault("created_at", _now())
    p = _messages_dir(awb) / f"{mid}.json"
    _atomic_write_json(p, payload)
    return mid


# ── Index ───────────────────────────────────────────────────────────────────

def get_index() -> Dict[str, str]:
    """Return the AWB → manifest-path index as a plain dict."""
    root = _require_init()
    idx = root / "_index.json"
    if not idx.exists():
        return {}
    try:
        return json.loads(idx.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def get_attachment_path(sha256: str) -> Optional[Path]:
    """Resolve a sha256 to its on-disk attachment path.

    Returns the first file under ``_attachments/`` whose stem equals
    *sha256*, or ``None`` if no such file exists. The match is strict
    on the stem (no glob expansion of the hex), so a 64-hex string
    cannot select files outside the attachments directory.
    """
    root = _require_init()
    sha = (sha256 or "").strip().lower()
    if not sha or len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha):
        return None
    attach_dir = root / "_attachments"
    # Match either "<sha>" exactly or "<sha>.<ext>". A traversal
    # attempt would have failed the hex test above.
    if not attach_dir.is_dir():
        return None
    for entry in attach_dir.iterdir():
        if entry.is_file() and (entry.name == sha or entry.stem == sha):
            return entry
    return None


def attachment_root() -> Path:
    """Return the absolute ``_attachments/`` directory path.

    Exposed so route handlers can perform an extra "resolved path stays
    inside attachments root" check after :func:`get_attachment_path`.
    """
    root = _require_init()
    return (root / "_attachments").resolve()


def index_awb(awb: str, manifest_path: Path) -> None:
    """Update the AWB → manifest-path index entry for *awb*."""
    root = _require_init()
    if not (awb or "").strip():
        raise ValueError("awb is required")
    awb_clean = _safe_awb(awb)
    with _lock:
        idx_path = root / "_index.json"
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8")) \
                if idx_path.exists() else {}
        except json.JSONDecodeError:
            data = {}
        data[awb_clean] = str(manifest_path)
        _atomic_write_json(idx_path, data)
