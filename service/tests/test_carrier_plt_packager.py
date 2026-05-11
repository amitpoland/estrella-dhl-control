"""
Phase H tests — PLT document packager.

Verifies that build_package() returns metadata-only references,
validates all input paths through the safety model, and never
embeds file bytes in the returned PltPackage.

All file I/O uses tmp_path. No DHL API calls. No DB. No production storage.
"""
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from app.services.carrier.plt.packager import PltPackageError, build_package
from app.services.carrier.models.plt import PltDocumentRef, PltPackage


# ── helpers ───────────────────────────────────────────────────────────────────


def _write(path: Path, content: bytes = b"PDF content") -> Path:
    path.write_bytes(content)
    return path


def _invoice(tmp_path: Path, name: str = "invoice.pdf", content: bytes = b"INV") -> Path:
    return _write(tmp_path / name, content)


def _customs(tmp_path: Path, name: str = "sad.pdf", content: bytes = b"SAD") -> Path:
    return _write(tmp_path / name, content)


# ── happy path ────────────────────────────────────────────────────────────────


def test_build_package_returns_plt_package(tmp_path):
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    assert isinstance(pkg, PltPackage)


def test_build_package_batch_id_stored(tmp_path):
    inv = _invoice(tmp_path)
    pkg = build_package("MY-BATCH", [inv])
    assert pkg.batch_id == "MY-BATCH"


def test_build_package_single_invoice_ref(tmp_path):
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    assert len(pkg.invoice_refs) == 1


def test_build_package_multiple_invoice_refs(tmp_path):
    inv1 = _invoice(tmp_path, "invoice1.pdf")
    inv2 = _invoice(tmp_path, "invoice2.pdf")
    pkg = build_package("BATCH-H", [inv1, inv2])
    assert len(pkg.invoice_refs) == 2


def test_build_package_with_customs_doc(tmp_path):
    inv = _invoice(tmp_path)
    sad = _customs(tmp_path)
    pkg = build_package("BATCH-H", [inv], customs_doc_path=sad)
    assert pkg.customs_doc_ref is not None


def test_build_package_no_customs_doc_ref_is_none(tmp_path):
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    assert pkg.customs_doc_ref is None


def test_build_package_empty_invoice_list(tmp_path):
    """build_package accepts empty invoice list — eligibility check is caller's job."""
    pkg = build_package("BATCH-H", [])
    assert pkg.invoice_refs == []


def test_build_package_created_at_is_set(tmp_path):
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    assert pkg.created_at != ""


def test_build_package_created_at_contains_utc_marker(tmp_path):
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    # isoformat with timezone includes '+00:00' or 'Z'
    assert "+" in pkg.created_at or "Z" in pkg.created_at or "00:00" in pkg.created_at


# ── document reference metadata ───────────────────────────────────────────────


def test_doc_ref_filename_is_basename(tmp_path):
    inv = _invoice(tmp_path, "my-label.pdf")
    pkg = build_package("BATCH-H", [inv])
    assert pkg.invoice_refs[0].filename == "my-label.pdf"


def test_doc_ref_size_bytes_correct(tmp_path):
    content = b"X" * 512
    inv = _invoice(tmp_path, content=content)
    pkg = build_package("BATCH-H", [inv])
    assert pkg.invoice_refs[0].size_bytes == 512


def test_doc_ref_checksum_is_hex_string(tmp_path):
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    checksum = pkg.invoice_refs[0].checksum_sha256
    assert isinstance(checksum, str)
    assert len(checksum) == 64  # sha256 hex = 64 chars
    int(checksum, 16)  # must be valid hex


def test_doc_ref_checksum_matches_file_content(tmp_path):
    content = b"test payload for checksum"
    inv = _invoice(tmp_path, content=content)
    pkg = build_package("BATCH-H", [inv])
    expected = hashlib.sha256(content).hexdigest()
    assert pkg.invoice_refs[0].checksum_sha256 == expected


def test_doc_ref_path_is_absolute(tmp_path):
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    assert pkg.invoice_refs[0].path.is_absolute()


def test_customs_doc_ref_filename(tmp_path):
    inv = _invoice(tmp_path)
    sad = _customs(tmp_path, "customs.pdf")
    pkg = build_package("BATCH-H", [inv], customs_doc_path=sad)
    assert pkg.customs_doc_ref.filename == "customs.pdf"


def test_customs_doc_ref_checksum_correct(tmp_path):
    content = b"SAD content"
    inv = _invoice(tmp_path)
    sad = _customs(tmp_path, content=content)
    pkg = build_package("BATCH-H", [inv], customs_doc_path=sad)
    expected = hashlib.sha256(content).hexdigest()
    assert pkg.customs_doc_ref.checksum_sha256 == expected


# ── no bytes embedded ─────────────────────────────────────────────────────────


def test_doc_ref_has_no_content_field(tmp_path):
    """PltDocumentRef must not have a 'content' or 'bytes' field."""
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    ref = pkg.invoice_refs[0]
    fields = {f.name for f in dataclasses.fields(ref)}
    assert "content" not in fields
    assert "data" not in fields
    assert "bytes" not in fields
    assert "file_bytes" not in fields


def test_plt_package_has_no_bytes_field(tmp_path):
    """PltPackage itself must not carry any bytes payload."""
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    fields = {f.name for f in dataclasses.fields(pkg)}
    assert "content" not in fields
    assert "data" not in fields
    assert "bytes" not in fields


def test_doc_ref_checksum_is_string_not_bytes(tmp_path):
    inv = _invoice(tmp_path)
    pkg = build_package("BATCH-H", [inv])
    assert isinstance(pkg.invoice_refs[0].checksum_sha256, str)


# ── unsafe paths rejected ─────────────────────────────────────────────────────


def test_path_with_traversal_in_parent_raises(tmp_path):
    # Create a real file but reference it via a path with '..' components
    real_file = tmp_path / "invoice.pdf"
    real_file.write_bytes(b"x")
    unsafe_path = tmp_path / "subdir" / ".." / "invoice.pdf"
    with pytest.raises(PltPackageError):
        build_package("BATCH-H", [unsafe_path])


def test_hidden_filename_raises(tmp_path):
    hidden = tmp_path / ".env"
    hidden.write_bytes(b"SECRET=abc")
    with pytest.raises(PltPackageError, match="hidden|dot"):
        build_package("BATCH-H", [hidden])


def test_hidden_customs_doc_raises(tmp_path):
    inv = _invoice(tmp_path)
    hidden = tmp_path / ".gitconfig"
    hidden.write_bytes(b"[user]")
    with pytest.raises(PltPackageError):
        build_package("BATCH-H", [inv], customs_doc_path=hidden)


def test_nonexistent_invoice_raises(tmp_path):
    missing = tmp_path / "ghost.pdf"
    with pytest.raises(PltPackageError, match="not found"):
        build_package("BATCH-H", [missing])


def test_nonexistent_customs_doc_raises(tmp_path):
    inv = _invoice(tmp_path)
    missing = tmp_path / "missing_sad.pdf"
    with pytest.raises(PltPackageError, match="not found"):
        build_package("BATCH-H", [inv], customs_doc_path=missing)


def test_directory_path_raises(tmp_path):
    """A directory path is not a regular file."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    with pytest.raises(PltPackageError, match="not a regular file"):
        build_package("BATCH-H", [subdir])


def test_relative_path_raises(tmp_path):
    """Relative paths are unsafe — packager requires absolute paths."""
    inv = _invoice(tmp_path)
    relative = Path(inv.name)  # just the filename, no directory
    with pytest.raises(PltPackageError, match="absolute"):
        build_package("BATCH-H", [relative])


def test_path_with_null_byte_raises():
    """Null bytes in path string must be rejected."""
    null_path = Path("/uploads/invo\x00ice.pdf")
    with pytest.raises((PltPackageError, ValueError)):
        build_package("BATCH-H", [null_path])


# ── safe path accepted ────────────────────────────────────────────────────────


def test_normal_absolute_path_accepted(tmp_path):
    inv = _invoice(tmp_path, "normal-invoice.pdf")
    pkg = build_package("BATCH-H", [inv])
    assert pkg.invoice_refs[0].filename == "normal-invoice.pdf"


def test_multiple_safe_paths_all_accepted(tmp_path):
    inv1 = _invoice(tmp_path, "invoice-A.pdf")
    inv2 = _invoice(tmp_path, "invoice-B.pdf")
    inv3 = _invoice(tmp_path, "invoice-C.pdf")
    pkg = build_package("BATCH-H", [inv1, inv2, inv3])
    assert len(pkg.invoice_refs) == 3


def test_second_invoice_bad_path_raises_and_first_is_not_stored(tmp_path):
    """Error on second invoice — entire package build must fail."""
    inv1 = _invoice(tmp_path, "invoice1.pdf")
    hidden = tmp_path / ".hidden.pdf"
    hidden.write_bytes(b"x")
    with pytest.raises(PltPackageError):
        build_package("BATCH-H", [inv1, hidden])
