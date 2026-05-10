"""
PLT document packager.

Assembles a PltPackage from caller-supplied file paths.
Returns metadata-only references — file bytes are never embedded in
the returned model.

Safety model for input paths:
  1. Filename component must pass _validate_filename() from plt/storage.py
     (rejects hidden/dot-prefixed names, '..' in filename, null bytes,
     empty names).
  2. Full path must be absolute.
  3. Full path must not contain '..' traversal components anywhere.
  4. Null bytes must not appear in the path string.
  5. Path must resolve to an existing regular file.

No DB writes. No production file writes. No DHL API calls.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..models.plt import PltDocumentRef, PltPackage
from .storage import PltPathError, _validate_filename


class PltPackageError(Exception):
    """Raised when a document path fails safety validation or is inaccessible."""


# ── internal path validator ───────────────────────────────────────────────────


def _validate_input_path(path: Path) -> None:
    """
    Validate a caller-supplied input document path.

    Raises PltPackageError for any unsafe or inaccessible path.
    Does NOT write any file.
    """
    path_str = str(path)

    # Null bytes in path string.
    if "\0" in path_str:
        raise PltPackageError(f"Input path contains null bytes: {path_str!r}")

    # Must be absolute — relative paths are ambiguous and unsafe.
    if not path.is_absolute():
        raise PltPackageError(
            f"Input path must be absolute: {path_str!r}"
        )

    # No '..' traversal components anywhere in the path tree.
    if ".." in path.parts:
        raise PltPackageError(
            f"Input path contains traversal component '..': {path_str!r}"
        )

    # Filename must pass the same safety check used for PLT output filenames.
    # This rejects hidden files (.env, .secret), empty names, and further
    # traversal patterns in the final component.
    try:
        _validate_filename(path.name)
    except PltPathError as exc:
        raise PltPackageError(
            f"Unsafe filename in input path {path_str!r}: {exc}"
        ) from exc

    # File must exist and be a regular file (not a directory or device).
    if not path.exists():
        raise PltPackageError(f"Input file not found: {path_str!r}")

    if not path.is_file():
        raise PltPackageError(f"Input path is not a regular file: {path_str!r}")


# ── document reference builder ────────────────────────────────────────────────


def _make_doc_ref(path: Path) -> PltDocumentRef:
    """
    Validate path and compute file metadata.

    Reads the file to compute SHA-256 checksum.
    Returns a PltDocumentRef (metadata only — no bytes field).
    """
    _validate_input_path(path)

    size_bytes = path.stat().st_size

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)

    return PltDocumentRef(
        path=path,
        filename=path.name,
        size_bytes=size_bytes,
        checksum_sha256=h.hexdigest(),
    )


# ── public API ────────────────────────────────────────────────────────────────


def build_package(
    batch_id: str,
    invoice_paths: List[Path],
    customs_doc_path: Optional[Path] = None,
) -> PltPackage:
    """
    Assemble a PltPackage from the given file paths.

    Validates every path before reading any metadata.
    Returns a PltPackage with PltDocumentRef entries — no file bytes embedded.

    Raises PltPackageError for any unsafe or inaccessible path.
    """
    invoice_refs = [_make_doc_ref(p) for p in invoice_paths]

    customs_doc_ref: Optional[PltDocumentRef] = None
    if customs_doc_path is not None:
        customs_doc_ref = _make_doc_ref(customs_doc_path)

    return PltPackage(
        batch_id=batch_id,
        invoice_refs=invoice_refs,
        customs_doc_ref=customs_doc_ref,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
