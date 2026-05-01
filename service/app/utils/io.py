"""
utils/io.py — Atomic file I/O helpers
======================================
write_json_atomic: write JSON to a temp file in the same directory,
then os.replace() into the final path so readers never see a partial write.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: str | Path, data: Any, indent: int = 2) -> None:
    """
    Write *data* as JSON to *path* atomically.

    Writes to a sibling temp-file first, then os.replace() swaps it in.
    On POSIX, os.replace() is guaranteed atomic at the filesystem level;
    on Windows it is best-effort (same drive required).

    Raises on any I/O or serialisation error — caller decides how to handle.
    """
    path = Path(path)
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=indent)
        os.replace(tmp, path)
    except Exception:
        # Clean up orphaned temp file; re-raise so the caller knows
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
