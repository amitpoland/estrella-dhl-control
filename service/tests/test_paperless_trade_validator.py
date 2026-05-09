"""
test_paperless_trade_validator.py — DL-F3 PLT validator tests.

Required:
  * Returns OK for a valid 1 KB PDF.
  * Rejects with stable reason tokens for: not_pdf, oversize,
    file_not_found, empty_file, no_path_provided, read_error.
  * 5 MB cap is the boundary (5 MB exact passes; 5 MB + 1 byte fails).
  * sha256 is deterministic; same file → same hex.
  * pdf_bytes only populated on ok=True; empty otherwise.
  * Source-grep: no FastAPI / coordinator / adapter import; no env reads;
    no HTTP imports.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from app.services.carrier.adapters.dhl_paperless_trade import (
    PLT_MAX_BYTES,
    PLTValidationResult,
    validate_paperless_trade_pdf,
)


_SRC_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "adapters" / "dhl_paperless_trade.py"
)


@pytest.fixture(scope="module")
def src() -> str:
    return _SRC_FILE.read_text(encoding="utf-8")


def _write_pdf(tmp_path, name: str, content: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def _minimal_pdf(payload: bytes = b"hello") -> bytes:
    """A tiny PDF with the magic header + arbitrary tail. Real PDF
    parsers would reject this, but DHL's validator only checks
    magic + size, mirroring our DL-F3 contract."""
    return b"%PDF-1.4\n" + payload + b"\n%%EOF\n"


# ── 1. Valid PDF → ok ──────────────────────────────────────────────────────

def test_valid_pdf_returns_ok(tmp_path):
    bytes_in = _minimal_pdf(b"%" * 200)
    p = _write_pdf(tmp_path, "ok.pdf", bytes_in)
    result = validate_paperless_trade_pdf(str(p))
    assert isinstance(result, PLTValidationResult)
    assert result.ok is True
    assert result.reason == "ok"
    assert result.size == len(bytes_in)
    assert result.sha256 == hashlib.sha256(bytes_in).hexdigest()
    assert result.pdf_bytes == bytes_in


# ── 2. not_pdf ─────────────────────────────────────────────────────────────

def test_non_pdf_magic_rejected(tmp_path):
    p = _write_pdf(tmp_path, "fake.bin", b"not a pdf at all")
    result = validate_paperless_trade_pdf(str(p))
    assert result.ok is False
    assert result.reason == "not_pdf"
    assert result.size > 0
    assert result.pdf_bytes is None


def test_pdf_extension_but_wrong_magic_still_rejected(tmp_path):
    """A file named .pdf but lacking the magic must still be rejected."""
    p = _write_pdf(tmp_path, "lying.pdf", b"\x89PNG\r\n\x1a\n")
    result = validate_paperless_trade_pdf(str(p))
    assert result.ok is False
    assert result.reason == "not_pdf"


# ── 3. oversize ────────────────────────────────────────────────────────────

def test_oversize_rejected(tmp_path):
    """Use a synthetic max_bytes for a fast test."""
    p = _write_pdf(tmp_path, "big.pdf", _minimal_pdf(b"X" * 1024))
    result = validate_paperless_trade_pdf(
        str(p), max_bytes=100,
    )
    assert result.ok is False
    assert result.reason == "oversize"
    assert result.size > 100
    assert result.pdf_bytes is None


def test_at_max_bytes_passes(tmp_path):
    """Boundary: exactly max_bytes passes."""
    # _minimal_pdf wraps payload with a 9-byte prefix + 7-byte suffix
    target = 1024
    wrapper_overhead = len(b"%PDF-1.4\n") + len(b"\n%%EOF\n")    # 16
    payload_len = target - wrapper_overhead
    bytes_in = _minimal_pdf(b"X" * payload_len)
    assert len(bytes_in) == target
    p = _write_pdf(tmp_path, "exact.pdf", bytes_in)
    result = validate_paperless_trade_pdf(
        str(p), max_bytes=target,
    )
    assert result.ok is True
    assert result.size == target


def test_one_byte_over_max_rejected(tmp_path):
    target = 1024
    wrapper_overhead = len(b"%PDF-1.4\n") + len(b"\n%%EOF\n")    # 16
    bytes_in = _minimal_pdf(b"X" * (target - wrapper_overhead + 1))
    assert len(bytes_in) == target + 1
    p = _write_pdf(tmp_path, "over.pdf", bytes_in)
    result = validate_paperless_trade_pdf(
        str(p), max_bytes=target,
    )
    assert result.ok is False
    assert result.reason == "oversize"


def test_default_max_is_5mb():
    assert PLT_MAX_BYTES == 5 * 1024 * 1024


# ── 4. file_not_found ──────────────────────────────────────────────────────

def test_missing_path_returns_file_not_found(tmp_path):
    result = validate_paperless_trade_pdf(str(tmp_path / "nope.pdf"))
    assert result.ok is False
    assert result.reason == "file_not_found"


def test_directory_not_a_file_returns_file_not_found(tmp_path):
    d = tmp_path / "some_dir"
    d.mkdir()
    result = validate_paperless_trade_pdf(str(d))
    assert result.ok is False
    assert result.reason == "file_not_found"


# ── 5. empty_file ─────────────────────────────────────────────────────────

def test_empty_file_rejected(tmp_path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    result = validate_paperless_trade_pdf(str(p))
    assert result.ok is False
    assert result.reason == "empty_file"


# ── 6. no_path_provided ───────────────────────────────────────────────────

@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_path_returns_no_path_provided(blank):
    result = validate_paperless_trade_pdf(blank)
    assert result.ok is False
    assert result.reason == "no_path_provided"


# ── 7. sha256 determinism ─────────────────────────────────────────────────

def test_sha256_is_deterministic(tmp_path):
    bytes_in = _minimal_pdf(b"deterministic")
    p1 = _write_pdf(tmp_path, "a.pdf", bytes_in)
    p2 = _write_pdf(tmp_path, "b.pdf", bytes_in)
    a = validate_paperless_trade_pdf(str(p1))
    b = validate_paperless_trade_pdf(str(p2))
    assert a.sha256 == b.sha256
    assert a.sha256 == hashlib.sha256(bytes_in).hexdigest()


def test_sha256_changes_with_content(tmp_path):
    p1 = _write_pdf(tmp_path, "a.pdf", _minimal_pdf(b"v1"))
    p2 = _write_pdf(tmp_path, "b.pdf", _minimal_pdf(b"v2"))
    a = validate_paperless_trade_pdf(str(p1))
    b = validate_paperless_trade_pdf(str(p2))
    assert a.sha256 != b.sha256


# ── 8. PDFValidationResult shape ─────────────────────────────────────────

def test_failure_result_has_no_pdf_bytes(tmp_path):
    p = _write_pdf(tmp_path, "bad.bin", b"not a pdf")
    result = validate_paperless_trade_pdf(str(p))
    assert result.pdf_bytes is None


def test_result_is_frozen():
    result = PLTValidationResult(ok=True, reason="ok")
    with pytest.raises(Exception):
        result.ok = False  # type: ignore[misc]


# ── 9. Source-grep guards ─────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "import fastapi", "from fastapi",
    "import flask",   "from flask",
])
def test_source_no_web_framework(src, forbidden):
    assert forbidden not in src


@pytest.mark.parametrize("forbidden", [
    "carrier_coordinator", "CarrierCoordinator",
    "DHLExpressLiveAdapter", "DHLExpressStubAdapter",
    "DHLExpressShadowAdapter",
])
def test_source_no_coordinator_or_adapter(src, forbidden):
    assert forbidden not in src, (
        f"validator must be adapter/coordinator-agnostic; "
        f"contains {forbidden!r}"
    )


@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_source_no_http(src, forbidden):
    assert forbidden not in src


def test_source_no_env_reads(src):
    for forbidden in ["os.environ", "os.getenv", "getenv("]:
        assert forbidden not in src
