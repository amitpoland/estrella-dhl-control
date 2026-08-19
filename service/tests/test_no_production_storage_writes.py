r"""No test may point a database initialiser at the DEPLOYED storage tree.

Origin (2026-08-19): ``test_global_packing_first_authority.py`` called
``init_packing_db(Path(r"C:\PZ\storage\packing.db"))``.  ``init_packing_db`` is
a schema *initialiser* -- CREATE TABLE / CREATE INDEX / ALTER TABLE -- so the
test suite ran DDL against the **running production service's** database.  It
left two columns and an index on ``packing_documents`` that exist in no merged
code.  No row was created, updated or deleted, and the deployed service never
reads those columns, so the damage was schema drift rather than data loss --
but the next such test may not be so lucky.

The per-test isolation in ``conftest.py`` cannot catch this class.  Its
``_guard_storage_root`` watches this checkout's storage roots and deliberately
does not walk ``C:\PZ\storage`` (a full rglob of the deployed tree per test),
and it detects leaks *after* the write has already landed.  A DDL statement
against production is not something to detect afterwards.

So this pin refuses the pattern at source: every ``init_*_db(...)`` call in the
test suite must be handed a temporary path.  Reads of the deployed tree stay
allowed -- several tests legitimately load production fixtures -- because a
read cannot mutate anything.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS_DIR = Path(__file__).parent

# The deployed service's storage tree.  Separators are normalised to "/" before
# matching -- writing a character class that holds both "\\" and "/" through a
# Python string, a regex, and a raw-string literal is exactly the kind of
# escaping trap that silently degrades to matching nothing.
_DEPLOYED_ROOT_RX = re.compile(r"C:\s*/+\s*PZ(?:\s*/+\s*app)?\s*/+\s*storage",
                               re.IGNORECASE)


def _normalise_separators(text: str) -> str:
    """Collapse Windows path separators so one pattern covers every spelling."""
    return text.replace("\\", "/")

# init_packing_db(...), init_payment_db(...), init_<anything>_db(...)
_INIT_CALL_RX = re.compile(r"\binit_\w*_db\s*\(([^)]*)\)", re.DOTALL)


def test_no_test_initialises_a_database_under_deployed_storage() -> None:
    offenders: list[str] = []

    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            src = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _INIT_CALL_RX.finditer(src):
            argument = match.group(1)
            if _DEPLOYED_ROOT_RX.search(_normalise_separators(argument)):
                line_no = src.count("\n", 0, match.start()) + 1
                offenders.append(
                    f"{path.name}:{line_no}: {match.group(0).strip()}"
                )

    assert not offenders, (
        "A database initialiser is pointed at the DEPLOYED storage tree. "
        "init_*_db runs CREATE TABLE / CREATE INDEX / ALTER TABLE against the "
        "path it is given, so this mutates the running production service's "
        "database. Point it at tmp_path instead; if the test needs real "
        "production rows, snapshot them through a read-only "
        "'file:...?mode=ro' connection first (see "
        "test_global_packing_first_authority._prod_packing_snapshot).\n  "
        + "\n  ".join(offenders)
    )


def test_the_pin_actually_matches_the_original_offending_line() -> None:
    """Guard against the pin silently matching nothing (a vacuous PASS)."""
    original = r'    packing_db.init_packing_db(Path(r"C:\PZ\storage\packing.db"))'
    match = _INIT_CALL_RX.search(original)
    assert match is not None, "init-call regex no longer matches the real call"
    assert _DEPLOYED_ROOT_RX.search(_normalise_separators(match.group(1))), (
        "deployed-root regex no longer matches the real production path"
    )

    allowed = '    pdb.init_packing_db(tmp_path / "packing.db")'
    allowed_match = _INIT_CALL_RX.search(allowed)
    assert allowed_match is not None
    assert not _DEPLOYED_ROOT_RX.search(
        _normalise_separators(allowed_match.group(1))), (
        "the pin would reject the normal tmp_path form"
    )
