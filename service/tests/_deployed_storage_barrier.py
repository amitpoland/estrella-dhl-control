r"""Write barrier for the DEPLOYED service's storage tree.

``C:\PZ\storage`` belongs to the running PZService, not to this checkout. It is
deliberately absent from conftest's ``_LIVE_ROOTS``: that guard walks each of
its roots once per test, and walking the production tree would add minutes to
a 4600-test suite. The result was a real hole — a test hardcoding the
production path could write there and nothing noticed. It happened: a test
calling ``init_packing_db(r"C:\PZ\storage\packing.db")`` ran the schema
initialiser against production and applied an ALTER TABLE to it.

So this barrier PREVENTS rather than detects, and costs nothing per test.

Reads stay allowed. Several tests legitimately use real historical batches as
fixtures, and proving compatibility against real data is the point of them.
Only writes are refused. A test that needs a real *database* must snapshot it
first — see the ``production_db_snapshot`` fixture in conftest.
"""
from __future__ import annotations

import builtins
import io
import os
import shutil
import sqlite3

PROD_ROOTS = tuple(
    os.path.normcase(os.path.abspath(p))
    for p in (r"C:\PZ\storage", r"C:\PZ\app\storage")
)

_armed = False


def under_prod(path) -> bool:
    """True if *path* lives inside a deployed-storage root.

    Never raises: a barrier that explodes on an exotic argument would be worse
    than the hole it closes.
    """
    try:
        if isinstance(path, int):          # already-open file descriptor
            return False
        p = os.path.normcase(os.path.abspath(os.fspath(path)))
    except (TypeError, ValueError, OSError):
        return False
    return any(p == r or p.startswith(r + os.sep) for r in PROD_ROOTS)


def _refuse(op: str, path) -> None:
    raise RuntimeError(
        "DEPLOYED-STORAGE WRITE BLOCKED: %s on %r.\n"
        "C:\\PZ\\storage belongs to the running service; tests may READ it, "
        "never write it.\n"
        "If you need a real database, use the `production_db_snapshot` "
        "fixture: it copies the file with sqlite3's online backup API and "
        "hands you a throwaway path you can mutate freely." % (op, path)
    )


def _guard_open(orig, op):
    def wrapper(file, mode="r", *a, **kw):
        if isinstance(mode, str) and any(c in mode for c in "wax+") \
                and under_prod(file):
            _refuse(op, file)
        return orig(file, mode, *a, **kw)
    return wrapper


def _guard_arg(orig, op, argno):
    def wrapper(*a, **kw):
        if len(a) > argno and under_prod(a[argno]):
            _refuse(op, a[argno])
        return orig(*a, **kw)
    return wrapper


def _guard_connect(orig):
    def wrapper(database, *a, **kw):
        # A read-only URI is the one sanctioned way to reach production.
        read_only = (kw.get("uri") and isinstance(database, str)
                     and "mode=ro" in database)
        if not read_only and under_prod(database):
            _refuse("sqlite3.connect", database)
        return orig(database, *a, **kw)
    return wrapper


# ``Path.open``, ``Path.write_text`` and ``Path.write_bytes`` all route through
# io.open, so patching the two open builtins covers the pathlib surface too.
_ARG_TARGETS = (
    (os, "remove", 0), (os, "unlink", 0), (os, "rmdir", 0),
    (os, "mkdir", 0), (os, "makedirs", 0), (os, "truncate", 0),
    (os, "rename", 1), (os, "replace", 1),
    (shutil, "rmtree", 0), (shutil, "copy", 1), (shutil, "copy2", 1),
    (shutil, "move", 1),
)


def arm() -> None:
    """Install the barrier. Idempotent; there is no disarm on purpose."""
    global _armed
    if _armed:
        return
    _armed = True
    builtins.open = _guard_open(builtins.open, "open")
    io.open = _guard_open(io.open, "io.open")
    sqlite3.connect = _guard_connect(sqlite3.connect)
    for mod, name, argno in _ARG_TARGETS:
        setattr(mod, name,
                _guard_arg(getattr(mod, name), "%s.%s" % (mod.__name__, name),
                           argno))


def snapshot_db(source, dest):
    """Copy a (possibly live) SQLite database to *dest* via the backup API.

    Read-only on the source, so it works through the barrier and cannot
    disturb a service that is mid-transaction.
    """
    src = sqlite3.connect("file:%s?mode=ro" % os.fspath(source).replace("\\", "/"),
                          uri=True)
    try:
        dst = sqlite3.connect(os.fspath(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest
