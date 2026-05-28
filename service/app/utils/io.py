"""
utils/io.py — Atomic file I/O helpers
======================================
write_json_atomic: write JSON to a temp file in the same directory,
then os.replace() into the final path so readers never see a partial write.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def write_json_atomic(path: str | Path, data: Any, indent: int = 2) -> None:
    """
    Write *data* as JSON to *path* atomically.

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
