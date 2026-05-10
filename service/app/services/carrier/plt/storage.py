"""
PLT filesystem containment utility.

All PLT label writes must stay under storage_root/carrier/plt/<batch_id>/.
Unsafe paths raise PltPathError before any file content is written.

Safety model (applied in order):
  1. batch_id validation — must be a single path component; no separators, no .., no dot
  2. filename validation — reject absolute paths, reject .. components, reject hidden
                           (dot-prefixed) names; strip directory components to basename
  3. mkdir — creates the target directory (always safe: no content)
  4. resolve() containment check — after mkdir, resolved target must be under
                                   resolved plt_root; catches symlink attacks

No HTTP, no DB, no DHL API calls. Pure filesystem utility.
"""
from __future__ import annotations

from pathlib import Path


class PltPathError(Exception):
    """Raised when a PLT path violates containment rules."""


class PltStorage:
    """
    Writes PLT label files within storage_root/carrier/plt/<batch_id>/.

    Caller provides storage_root (at runtime: from Settings.carrier_storage_root
    or Settings.storage_root / "carrier").  All validation is eager — unsafe
    inputs raise PltPathError before any filesystem mutation (except mkdir,
    which is always safe).
    """

    def __init__(self, storage_root: Path) -> None:
        self._storage_root = Path(storage_root)

    # ── public ────────────────────────────────────────────────────────────────

    def write(self, batch_id: str, filename: str, content: bytes) -> Path:
        """
        Write content to storage_root/carrier/plt/<batch_id>/<safe_filename>.

        Returns the resolved absolute path of the written file.
        Raises PltPathError for any unsafe batch_id or filename.
        """
        safe_batch_id = _validate_batch_id(batch_id)
        safe_filename = _validate_filename(filename)

        plt_root = self._storage_root / "carrier" / "plt"
        target_dir = plt_root / safe_batch_id
        target_path = target_dir / safe_filename

        # Create directory tree — safe: no file content written yet.
        target_dir.mkdir(parents=True, exist_ok=True)

        # Resolve with the directory existing so symlinks are followed fully.
        resolved_target = target_path.resolve()
        resolved_plt_root = plt_root.resolve()

        # Containment check — resolved path must be a descendant of plt_root.
        try:
            resolved_target.relative_to(resolved_plt_root)
        except ValueError:
            raise PltPathError(
                f"Resolved path {str(resolved_target)!r} escapes PLT storage root "
                f"{str(resolved_plt_root)!r}. Possible symlink or traversal attack."
            )

        resolved_target.write_bytes(content)
        return resolved_target

    def plt_root(self) -> Path:
        """Return the PLT root directory (storage_root/carrier/plt)."""
        return self._storage_root / "carrier" / "plt"


# ── validation helpers (module-level for direct testability) ──────────────────


def _validate_batch_id(batch_id: str) -> str:
    """
    Accept a batch_id that is a safe single path component.

    Rejects: empty, null bytes, path separators, multi-component paths, '.' and '..'.
    """
    if not batch_id:
        raise PltPathError("batch_id must not be empty")
    if "\0" in batch_id:
        raise PltPathError("batch_id must not contain null bytes")
    if "/" in batch_id or "\\" in batch_id:
        raise PltPathError(
            f"batch_id must not contain path separators: {batch_id!r}"
        )
    # Path(x).name equals x only when x is a single non-empty component.
    if Path(batch_id).name != batch_id:
        raise PltPathError(
            f"batch_id is not a single path component: {batch_id!r}"
        )
    if batch_id in ("..", "."):
        raise PltPathError(f"batch_id must not be '.' or '..': {batch_id!r}")
    return batch_id


def _validate_filename(filename: str) -> str:
    """
    Accept a filename and return a safe basename.

    Rejects: empty, null bytes, absolute paths (POSIX and Windows root-relative),
             any '..' component.
    Strips nested directory components — only the basename is used.
    Rejects hidden (dot-prefixed) basenames.
    """
    if not filename:
        raise PltPathError("filename must not be empty")
    if "\0" in filename:
        raise PltPathError("filename must not contain null bytes")

    # Reject absolute paths — covers POSIX (/path), Windows drive (C:\path),
    # and Windows root-relative (\path) which is_absolute() misses on Windows.
    if filename.startswith("/") or filename.startswith("\\"):
        raise PltPathError(f"filename must not be absolute: {filename!r}")
    if Path(filename).is_absolute():
        raise PltPathError(f"filename must not be absolute: {filename!r}")

    # Reject any '..' traversal component before basename reduction.
    parts = Path(filename).parts
    if ".." in parts:
        raise PltPathError(
            f"filename contains path traversal '..': {filename!r}"
        )

    # Reduce to basename — neutralises nested components like 'nested/label.pdf'.
    safe_name = Path(filename).name

    if not safe_name:
        raise PltPathError(f"filename has no safe basename: {filename!r}")

    # Reject hidden / dot-prefixed files (.env, .secret, etc.).
    if safe_name.startswith("."):
        raise PltPathError(
            f"filename must not be hidden (dot-prefixed): {safe_name!r}"
        )

    return safe_name
