"""Regression: auth._connect() must refuse an uninitialised DB path.

Before the guard, str(None) -> "None" and sqlite3 silently created an empty
database file named "None" in the process CWD; every auth query then returned
zero rows instead of failing. See app/auth/database.py:_connect.
"""
import os

import pytest

from app.auth import database as d


def test_connect_without_init_db_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "_db_path", None)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="not initialised"):
        d._connect()

    assert not (tmp_path / "None").exists(), "created a stray 'None' database file"


def test_connect_works_after_init_db(tmp_path):
    d.init_db(tmp_path / "users.db")
    with d._connect() as con:
        assert con.execute("SELECT 1").fetchone()[0] == 1
    assert not (tmp_path / "None").exists()
    assert os.path.exists(tmp_path / "users.db")
