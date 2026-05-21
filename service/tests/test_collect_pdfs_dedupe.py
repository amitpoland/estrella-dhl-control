"""collect_pdfs dedupe regression (2026-05-21).

On Windows the filesystem is case-insensitive: globbing both *.pdf and
*.PDF returned the same file twice, silently doubling invoice totals
once the Global PZ engine authority bridge made the parser actually
return non-empty items. Dedupe at collection time so all callers are
safe.
"""
from __future__ import annotations

from pathlib import Path

import pz_import_processor as p


def test_dedupes_when_dir_has_lowercase_extension(tmp_path: Path):
    f = tmp_path / "inv.pdf"
    f.write_bytes(b"stub")
    out = p.collect_pdfs([str(tmp_path)])
    assert len(out) == 1
    assert Path(out[0]).name == "inv.pdf"


def test_dedupes_when_dir_has_uppercase_extension(tmp_path: Path):
    f = tmp_path / "INV.PDF"
    f.write_bytes(b"stub")
    out = p.collect_pdfs([str(tmp_path)])
    assert len(out) == 1


def test_multiple_distinct_pdfs_all_returned(tmp_path: Path):
    (tmp_path / "a.pdf").write_bytes(b"stub")
    (tmp_path / "b.pdf").write_bytes(b"stub")
    (tmp_path / "c.pdf").write_bytes(b"stub")
    out = p.collect_pdfs([str(tmp_path)])
    assert len(out) == 3
    assert sorted(Path(x).name for x in out) == ["a.pdf", "b.pdf", "c.pdf"]


def test_dedupes_explicit_file_passed_twice(tmp_path: Path):
    f = tmp_path / "inv.pdf"
    f.write_bytes(b"stub")
    out = p.collect_pdfs([str(f), str(f)])
    assert len(out) == 1


def test_dedupes_dir_and_explicit_pointing_at_same_file(tmp_path: Path):
    f = tmp_path / "inv.pdf"
    f.write_bytes(b"stub")
    out = p.collect_pdfs([str(tmp_path), str(f)])
    assert len(out) == 1


def test_empty_dir_returns_empty(tmp_path: Path):
    out = p.collect_pdfs([str(tmp_path)])
    assert out == []


def test_non_pdf_files_ignored(tmp_path: Path):
    (tmp_path / "readme.txt").write_bytes(b"stub")
    (tmp_path / "a.pdf").write_bytes(b"stub")
    out = p.collect_pdfs([str(tmp_path)])
    assert len(out) == 1
    assert Path(out[0]).name == "a.pdf"
