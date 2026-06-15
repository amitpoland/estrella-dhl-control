"""
test_wfirma_grammar_import_dedup.py — Regression for Issue #598.

Background
----------
routes_wfirma.py originally carried TWO `from description_grammar import
METAL_PREPOSITIONAL` blocks at module load:

  Block 1 (dead / broken-in-prod):
      sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
      from description_grammar import METAL_PREPOSITIONAL
    In production (C:\\PZ\\app\\api\\routes_wfirma.py) parents[3] resolves to
    the drive root C:\\, NOT the engine dir. The import only succeeded by
    accident — an earlier-imported module had already populated sys.path. This
    is exactly the import-order fragility Lesson J warns against.

  Block 2 (correct, Lesson J):
      _grammar_engine_dir = str(settings.engine_dir)   # = C:\\PZ\\engine in prod
      if _grammar_engine_dir not in sys.path:
          sys.path.insert(0, _grammar_engine_dir)
      from description_grammar import METAL_PREPOSITIONAL

Issue #598 removes Block 1. Block 2 is the sole grammar import. This test pins
that the dead block stays gone and the correct block + the import-time grammar
compatibility gate remain intact. Source-grep only — no JSX/heavy execution.
"""
from __future__ import annotations

from pathlib import Path

ROUTES_WFIRMA = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_wfirma.py"


def _src() -> str:
    return ROUTES_WFIRMA.read_text(encoding="utf-8")


def _code_lines() -> list[str]:
    """Source lines with full-line comments stripped, so assertions about
    *executable* code are not fooled by explanatory comments that mention the
    forbidden pattern on purpose (the Lesson-J block documents why parents[3]
    is wrong)."""
    out = []
    for line in _src().splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(line)
    return out


# ── Dead block removed ────────────────────────────────────────────────────────

def test_exactly_one_grammar_import():
    """Issue #598: there must be exactly ONE grammar import after dedup."""
    n = _src().count("from description_grammar import METAL_PREPOSITIONAL")
    assert n == 1, (
        f"Expected exactly 1 'from description_grammar import METAL_PREPOSITIONAL', "
        f"found {n}. The dead parents[3] duplicate must be removed (Issue #598)."
    )


def test_no_executable_parents3_syspath_insert():
    """The dead parents[3] sys.path manipulation must not survive in code.
    Comment references (the Lesson-J rationale) are allowed; executable lines
    are not."""
    offenders = [
        ln for ln in _code_lines()
        if "parents[3]" in ln
    ]
    assert not offenders, (
        "Executable parents[3] usage must be gone (Issue #598). Offending "
        f"code lines: {offenders!r}"
    )


def test_no_raw_parents3_syspath_call():
    """Belt-and-suspenders: the exact dead pattern string must not be in code."""
    offenders = [
        ln for ln in _code_lines()
        if "sys.path.insert" in ln and "parents[" in ln
    ]
    assert not offenders, (
        "sys.path.insert based on Path(__file__)...parents[N] must not be used "
        f"for the grammar import (use settings.engine_dir). Offenders: {offenders!r}"
    )


# ── Correct Lesson-J block retained ───────────────────────────────────────────

def test_lesson_j_engine_dir_block_present():
    """The Lesson-J correct path (settings.engine_dir) must remain the grammar
    import mechanism."""
    src = _src()
    assert "_grammar_engine_dir = str(settings.engine_dir)" in src, (
        "Lesson-J grammar import block (settings.engine_dir) is missing — the "
        "dedup must KEEP the correct block, not the dead one."
    )
    assert "if _grammar_engine_dir not in sys.path:" in src


# ── Import-time grammar compatibility gate (hard invariant) intact ────────────

def test_import_time_grammar_gate_present():
    """The Phase 2B4 import-time compatibility gate must not be disturbed by
    the dedup."""
    src = _src()
    assert "_WFIRMA_METAL_COMPAT_FAILURES" in src, "grammar-compat gate accumulator missing"
    assert "Grammar drift detected" in src, "grammar-compat gate ImportError message missing"
    assert "raise ImportError(" in src, "grammar-compat gate must still raise on drift"


# ── Import smoke ──────────────────────────────────────────────────────────────

def test_module_imports_and_exposes_metal_prepositional():
    """The cleaned module must still import and expose METAL_PREPOSITIONAL via
    the single remaining import."""
    import app.api.routes_wfirma as m
    assert isinstance(m.METAL_PREPOSITIONAL, dict)
    assert len(m.METAL_PREPOSITIONAL) > 0
