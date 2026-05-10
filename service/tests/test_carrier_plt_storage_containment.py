"""
Phase F tests — PltStorage filesystem containment.

Verifies that all writes stay under storage_root/carrier/plt/<batch_id>/,
unsafe batch_ids and filenames raise PltPathError before any write,
and the resolve() containment check is the final backstop.

All tests use tmp_path. No HTTP, no DB, no DHL API calls.
"""
import pytest

from app.services.carrier.plt.storage import (
    PltPathError,
    PltStorage,
    _validate_batch_id,
    _validate_filename,
)


# ── normal safe write ─────────────────────────────────────────────────────────


def test_safe_write_returns_resolved_path(tmp_path):
    storage = PltStorage(tmp_path)
    result = storage.write("BATCH-001", "label.pdf", b"PDF content")
    assert result.is_absolute()


def test_safe_write_content_correct(tmp_path):
    storage = PltStorage(tmp_path)
    path = storage.write("BATCH-001", "label.pdf", b"hello bytes")
    assert path.read_bytes() == b"hello bytes"


def test_safe_write_path_under_plt_root(tmp_path):
    storage = PltStorage(tmp_path)
    path = storage.write("BATCH-001", "label.pdf", b"x")
    plt_root = (tmp_path / "carrier" / "plt").resolve()
    assert str(path).startswith(str(plt_root))


def test_safe_write_path_under_batch_dir(tmp_path):
    storage = PltStorage(tmp_path)
    path = storage.write("BATCH-XYZ", "label.pdf", b"x")
    assert path.parent == (tmp_path / "carrier" / "plt" / "BATCH-XYZ").resolve()


def test_safe_write_creates_directory(tmp_path):
    storage = PltStorage(tmp_path)
    storage.write("NEW-BATCH", "label.pdf", b"x")
    assert (tmp_path / "carrier" / "plt" / "NEW-BATCH").is_dir()


def test_write_empty_content_succeeds(tmp_path):
    storage = PltStorage(tmp_path)
    path = storage.write("BATCH-001", "empty.pdf", b"")
    assert path.read_bytes() == b""


def test_multiple_batches_get_separate_dirs(tmp_path):
    storage = PltStorage(tmp_path)
    storage.write("BATCH-A", "label.pdf", b"a")
    storage.write("BATCH-B", "label.pdf", b"b")
    assert (tmp_path / "carrier" / "plt" / "BATCH-A").is_dir()
    assert (tmp_path / "carrier" / "plt" / "BATCH-B").is_dir()


def test_multiple_batches_files_are_independent(tmp_path):
    storage = PltStorage(tmp_path)
    storage.write("BATCH-A", "label.pdf", b"content-a")
    storage.write("BATCH-B", "label.pdf", b"content-b")
    path_a = (tmp_path / "carrier" / "plt" / "BATCH-A" / "label.pdf").resolve()
    path_b = (tmp_path / "carrier" / "plt" / "BATCH-B" / "label.pdf").resolve()
    assert path_a.read_bytes() == b"content-a"
    assert path_b.read_bytes() == b"content-b"


def test_plt_root_method_returns_correct_path(tmp_path):
    storage = PltStorage(tmp_path)
    expected = tmp_path / "carrier" / "plt"
    assert storage.plt_root() == expected


# ── batch_id validation ───────────────────────────────────────────────────────


def test_batch_id_empty_raises():
    with pytest.raises(PltPathError, match="empty"):
        _validate_batch_id("")


def test_batch_id_null_byte_raises():
    with pytest.raises(PltPathError, match="null"):
        _validate_batch_id("BATCH\x00ID")


def test_batch_id_forward_slash_raises():
    with pytest.raises(PltPathError, match="separator"):
        _validate_batch_id("BATCH/ID")


def test_batch_id_backslash_raises():
    with pytest.raises(PltPathError, match="separator"):
        _validate_batch_id("BATCH\\ID")


def test_batch_id_dotdot_raises():
    with pytest.raises(PltPathError):
        _validate_batch_id("..")


def test_batch_id_single_dot_raises():
    with pytest.raises(PltPathError):
        _validate_batch_id(".")


def test_batch_id_valid_returns_unchanged():
    assert _validate_batch_id("BATCH-001") == "BATCH-001"


def test_batch_id_alphanumeric_valid():
    assert _validate_batch_id("BATCH20260101") == "BATCH20260101"


def test_batch_id_with_hyphen_valid():
    assert _validate_batch_id("MY-BATCH-XYZ") == "MY-BATCH-XYZ"


def test_batch_id_with_underscore_valid():
    assert _validate_batch_id("batch_2026") == "batch_2026"


# ── filename validation ───────────────────────────────────────────────────────


def test_filename_empty_raises():
    with pytest.raises(PltPathError, match="empty"):
        _validate_filename("")


def test_filename_null_byte_raises():
    with pytest.raises(PltPathError, match="null"):
        _validate_filename("la\x00bel.pdf")


def test_filename_absolute_posix_raises():
    with pytest.raises(PltPathError, match="absolute"):
        _validate_filename("/etc/passwd")


def test_filename_absolute_windows_root_relative_raises():
    with pytest.raises(PltPathError, match="absolute"):
        _validate_filename("\\windows\\system32\\cmd.exe")


def test_filename_dotdot_traversal_raises():
    with pytest.raises(PltPathError, match="traversal"):
        _validate_filename("../../etc/passwd")


def test_filename_dotdot_component_raises():
    with pytest.raises(PltPathError, match="traversal"):
        _validate_filename("subdir/../etc/passwd")


def test_filename_hidden_dotenv_raises():
    with pytest.raises(PltPathError, match="hidden"):
        _validate_filename(".env")


def test_filename_hidden_dot_secret_raises():
    with pytest.raises(PltPathError, match="hidden"):
        _validate_filename(".secret")


def test_filename_hidden_dotfile_raises():
    with pytest.raises(PltPathError, match="hidden"):
        _validate_filename(".gitconfig")


def test_filename_safe_returns_basename():
    assert _validate_filename("label.pdf") == "label.pdf"


def test_filename_nested_safe_reduced_to_basename():
    """Nested path with no '..' is safe — only the basename is used."""
    result = _validate_filename("subdir/label.pdf")
    assert result == "label.pdf"


def test_filename_nested_stripped_to_basename_in_write(tmp_path):
    """Write with nested filename writes only the basename into batch dir."""
    storage = PltStorage(tmp_path)
    path = storage.write("BATCH-001", "nested/label.pdf", b"data")
    assert path.name == "label.pdf"
    assert path.parent == (tmp_path / "carrier" / "plt" / "BATCH-001").resolve()


def test_filename_with_extension_valid():
    assert _validate_filename("shipment-label.pdf") == "shipment-label.pdf"


def test_filename_xlsx_valid():
    assert _validate_filename("report.xlsx") == "report.xlsx"


# ── write raises on unsafe batch_id ──────────────────────────────────────────


def test_write_traversal_batch_id_raises(tmp_path):
    storage = PltStorage(tmp_path)
    with pytest.raises(PltPathError):
        storage.write("../escape", "label.pdf", b"x")


def test_write_slash_in_batch_id_raises(tmp_path):
    storage = PltStorage(tmp_path)
    with pytest.raises(PltPathError):
        storage.write("batch/escape", "label.pdf", b"x")


def test_write_empty_batch_id_raises(tmp_path):
    storage = PltStorage(tmp_path)
    with pytest.raises(PltPathError):
        storage.write("", "label.pdf", b"x")


# ── write raises on unsafe filename ──────────────────────────────────────────


def test_write_traversal_filename_raises(tmp_path):
    storage = PltStorage(tmp_path)
    with pytest.raises(PltPathError):
        storage.write("BATCH-001", "../../etc/passwd", b"x")


def test_write_absolute_filename_raises(tmp_path):
    storage = PltStorage(tmp_path)
    with pytest.raises(PltPathError):
        storage.write("BATCH-001", "/etc/passwd", b"x")


def test_write_hidden_filename_raises(tmp_path):
    storage = PltStorage(tmp_path)
    with pytest.raises(PltPathError):
        storage.write("BATCH-001", ".env", b"x")


def test_write_empty_filename_raises(tmp_path):
    storage = PltStorage(tmp_path)
    with pytest.raises(PltPathError):
        storage.write("BATCH-001", "", b"x")


# ── no file written before PltPathError ──────────────────────────────────────


def test_no_file_written_on_bad_batch_id(tmp_path):
    storage = PltStorage(tmp_path)
    with pytest.raises(PltPathError):
        storage.write("../escape", "label.pdf", b"x")
    # No files should exist under the plt root
    plt_root = tmp_path / "carrier" / "plt"
    assert not plt_root.exists() or not any(plt_root.rglob("*.pdf"))


def test_no_file_written_on_bad_filename(tmp_path):
    storage = PltStorage(tmp_path)
    with pytest.raises(PltPathError):
        storage.write("BATCH-001", "../../etc/passwd", b"x")
    escape_path = tmp_path.parent / "etc" / "passwd"
    assert not escape_path.exists()


# ── overwrite is safe ─────────────────────────────────────────────────────────


def test_overwrite_same_file_updates_content(tmp_path):
    storage = PltStorage(tmp_path)
    storage.write("BATCH-001", "label.pdf", b"first")
    storage.write("BATCH-001", "label.pdf", b"second")
    path = (tmp_path / "carrier" / "plt" / "BATCH-001" / "label.pdf").resolve()
    assert path.read_bytes() == b"second"
