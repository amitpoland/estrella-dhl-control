"""
utils/io.py — Atomic file I/O helpers
======================================
write_json_atomic: write JSON to a temp file in the same directory,
then os.replace() into the final path so readers never see a partial write.
Always writes UTF-8 **without** BOM (byte 0 of output is always '{').

read_json: read JSON from a file transparently handling UTF-8 BOM.
Uses encoding="utf-8-sig" which silently strips the BOM when present.
Logs a WARNING when a BOM is detected so operators know the file needs
re-saving with write_json_atomic.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)


def read_json(path: str | Path) -> Dict[str, Any]:
    """
    Read JSON from *path*, transparently handling a UTF-8 BOM if present.

    Uses ``encoding="utf-8-sig"`` which silently strips the BOM (EF BB BF)
    when present and behaves identically to ``"utf-8"`` when not present.

    If the file contained a BOM, a WARNING is emitted recommending the
    operator re-save the file with ``write_json_atomic`` to repair it
    permanently.

    Raises ``FileNotFoundError`` if *path* does not exist.
    Raises ``json.JSONDecodeError`` on malformed JSON (caller handles).
    """
    path = Path(path)
    raw = path.read_bytes()
    _BOM = b"\xef\xbb\xbf"
    had_bom = raw.startswith(_BOM)
    text = raw.decode("utf-8-sig")  # strips BOM if present
    if had_bom:
        log.warning(
            "read_json: UTF-8 BOM detected in %s — parsed successfully with "
            "utf-8-sig.  Re-save with write_json_atomic to repair permanently "
            "(use Python, not PowerShell, for any manual JSON edits).",
            path,
        )
    return json.loads(text)


def write_json_atomic(path: str | Path, data: Any, indent: int = 2) -> None:
    """
    Write *data* as JSON to *path* atomically.

    **Always writes UTF-8 without BOM** — the first byte of the output file
    is guaranteed to be ``{`` (0x7B), never the BOM sequence (EF BB BF).
    This is the correct repair path when a file has accidentally been given
    a BOM by PowerShell or another tool.

    Writes to a sibling temp-file first, then os.replace() swaps it in.
    On POSIX, os.replace() is guaranteed atomic at the filesystem level;
    on Windows it is best-effort (same drive required).

    On Windows, os.replace() raises PermissionError (WinError 5) when the
    destination file is momentarily held open by another reader (service,
    antivirus, etc.).  We retry up to _WINDOWS_REPLACE_RETRIES times with
    a short sleep before re-raising so transient locks don't crash the engine.

    Raises on any I/O or serialisation error — caller decides how to handle.
    """
    _WINDOWS_REPLACE_RETRIES = 5
    _WINDOWS_REPLACE_DELAY = 0.1  # seconds between retries

    path = Path(path)
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=indent)

        if sys.platform == "win32":
            for attempt in range(_WINDOWS_REPLACE_RETRIES):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    if attempt == _WINDOWS_REPLACE_RETRIES - 1:
                        raise
                    time.sleep(_WINDOWS_REPLACE_DELAY)
        else:
            os.replace(tmp, path)
    except Exception:
        # Clean up orphaned temp file; re-raise so the caller knows
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
