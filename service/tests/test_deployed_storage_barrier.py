r"""The barrier is only worth having if it actually refuses.

Every assertion here attempts a write against ``C:\PZ\storage`` and requires it
to raise.  Nothing is ever written: if the barrier were absent these tests
would fail loudly rather than silently touching production, because the
missing RuntimeError is the failure.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

import _deployed_storage_barrier as dsb

PROD = Path(r"C:\PZ\storage")
TARGET = PROD / "barrier_probe_never_created.tmp"


def test_barrier_is_armed():
    assert dsb._armed, "conftest must arm the barrier at import"


@pytest.mark.parametrize("path", [
    PROD,
    PROD / "packing.db",
    PROD / "outputs" / "anything" / "deep.json",
    Path(r"c:\pz\storage\packing.db"),      # Windows is case-insensitive
    Path(r"C:\PZ\storage\..\storage\x"),    # normalises back inside
])
def test_under_prod_recognises_the_tree(path):
    assert dsb.under_prod(path)


@pytest.mark.parametrize("path", [
    Path(r"C:\PZ-main\service\storage\packing.db"),
    Path(r"C:\PZ\storage-other\x"),         # sibling, not a child
    Path(r"C:\PZ\logs\service.log"),
])
def test_under_prod_does_not_over_reach(path):
    assert not dsb.under_prod(path)


def test_under_prod_never_raises_on_junk():
    for junk in (None, 3, object(), b"\xff\xfe"):
        assert dsb.under_prod(junk) is False


def test_bytes_paths_are_still_recognised():
    """open() accepts bytes paths, so the barrier has to decode them."""
    assert dsb.under_prod(rb"C:\PZ\storage\packing.db")
    with pytest.raises(RuntimeError, match="WRITE BLOCKED"):
        open(str(TARGET).encode(), "wb")
    assert not TARGET.exists()


@pytest.mark.parametrize("mode", ["w", "a", "x", "r+", "wb"])
def test_open_for_writing_is_refused(mode):
    with pytest.raises(RuntimeError, match="WRITE BLOCKED"):
        open(TARGET, mode)
    assert not TARGET.exists()


def test_pathlib_writes_are_refused():
    # Path.write_text/write_bytes/open all route through io.open.
    with pytest.raises(RuntimeError, match="WRITE BLOCKED"):
        TARGET.write_text("nope", encoding="utf-8")
    with pytest.raises(RuntimeError, match="WRITE BLOCKED"):
        TARGET.write_bytes(b"nope")
    assert not TARGET.exists()


def test_sqlite_connect_is_refused():
    # A plain connect() CREATES the file and can migrate the schema -- this is
    # the exact call that ALTERed the running service's packing.db.
    with pytest.raises(RuntimeError, match="WRITE BLOCKED"):
        sqlite3.connect(str(PROD / "packing.db"))


def test_sqlite_read_only_uri_is_allowed():
    db = PROD / "packing.db"
    if not db.exists():
        pytest.skip("deployed storage has no packing.db")
    con = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM packing_documents").fetchone()[0] >= 0
    finally:
        con.close()


def test_reads_stay_allowed():
    db = PROD / "packing.db"
    if not db.exists():
        pytest.skip("deployed storage has no packing.db")
    with open(db, "rb") as fh:
        assert fh.read(16).startswith(b"SQLite format 3")


@pytest.mark.parametrize("call", [
    lambda: os.remove(TARGET),
    lambda: os.unlink(TARGET),
    lambda: os.mkdir(PROD / "new_dir"),
    lambda: os.makedirs(PROD / "a" / "b"),
    lambda: os.rename(__file__, TARGET),
    lambda: os.replace(__file__, TARGET),
    lambda: shutil.rmtree(PROD),
    lambda: shutil.copy(__file__, TARGET),
    lambda: shutil.copy2(__file__, TARGET),
    lambda: shutil.move(__file__, TARGET),
])
def test_destructive_entry_points_are_refused(call):
    with pytest.raises(RuntimeError, match="WRITE BLOCKED"):
        call()


def test_the_regression_that_caused_this(tmp_path):
    """The original defect, replayed: init_packing_db against production."""
    from app.services import packing_db

    with pytest.raises(RuntimeError, match="WRITE BLOCKED"):
        packing_db.init_packing_db(PROD / "packing.db")


def test_snapshot_fixture_hands_back_a_writable_copy(production_db_snapshot):
    db = production_db_snapshot("packing.db")
    assert dsb.under_prod(db) is False
    from app.services import packing_db

    packing_db.init_packing_db(db)          # migrating the copy is fine
    con = sqlite3.connect(str(db))
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM packing_documents").fetchone()[0] > 0
    finally:
        con.close()
