"""
test_json_bom_hardening.py — Regression tests for UTF-8 BOM handling.

Context (Lesson L, 2026-05-28):
    PowerShell 5.1 writes UTF-8 WITH BOM (EF BB BF) by default when using
    ``Set-Content -Encoding utf8`` or ``Out-File -Encoding utf8``.
    Python ``json.load(encoding="utf-8")`` raises JSONDecodeError on BOM-
    prefixed files.  These tests pin the hardened behaviour:

    * read_json / audit_persist._load silently handle BOM and log a warning.
    * write_json_atomic always writes BOM-free output.
    * Round-trip: write then read produces identical data.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import pytest

from app.utils.io import read_json, write_json_atomic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE = {"shipment": "AWB123", "status": "ok", "value": 42, "nested": {"a": 1}}

_BOM = b"\xef\xbb\xbf"


def _write_bom_file(path: Path, data: dict) -> None:
    """Write JSON to *path* with a UTF-8 BOM prefix (simulates PowerShell)."""
    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(_BOM + json_bytes)


def _write_clean_file(path: Path, data: dict) -> None:
    """Write JSON to *path* without BOM (normal Python write)."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# read_json tests
# ---------------------------------------------------------------------------


class TestReadJson:
    def test_reads_bom_prefixed_file_correctly(self, tmp_path):
        """BOM-prefixed file must be parsed to the correct dict, not raise."""
        p = tmp_path / "audit.json"
        _write_bom_file(p, _SAMPLE)
        result = read_json(p)
        assert result == _SAMPLE

    def test_reads_clean_file_correctly(self, tmp_path):
        """BOM-free file must be parsed identically."""
        p = tmp_path / "audit.json"
        _write_clean_file(p, _SAMPLE)
        result = read_json(p)
        assert result == _SAMPLE

    def test_bom_file_emits_warning(self, tmp_path, caplog):
        """read_json must emit a WARNING when a BOM is detected."""
        p = tmp_path / "audit.json"
        _write_bom_file(p, _SAMPLE)
        with caplog.at_level(logging.WARNING, logger="app.utils.io"):
            read_json(p)
        assert any(
            "UTF-8 BOM" in record.message and "utf-8-sig" in record.message
            for record in caplog.records
        ), "Expected a BOM warning from read_json"

    def test_clean_file_no_warning(self, tmp_path, caplog):
        """read_json must NOT emit any BOM warning for a clean file."""
        p = tmp_path / "audit.json"
        _write_clean_file(p, _SAMPLE)
        with caplog.at_level(logging.WARNING, logger="app.utils.io"):
            read_json(p)
        bom_warnings = [r for r in caplog.records if "UTF-8 BOM" in r.message]
        assert bom_warnings == [], "Unexpected BOM warning for clean file"

    def test_raises_file_not_found(self, tmp_path):
        """read_json must raise FileNotFoundError for missing path."""
        with pytest.raises(FileNotFoundError):
            read_json(tmp_path / "nonexistent.json")

    def test_raises_on_malformed_json(self, tmp_path):
        """read_json must raise json.JSONDecodeError for malformed content."""
        p = tmp_path / "bad.json"
        p.write_bytes(b"not-json!!!")
        with pytest.raises(json.JSONDecodeError):
            read_json(p)

    def test_bom_prefixed_malformed_raises(self, tmp_path):
        """BOM + malformed JSON must still raise JSONDecodeError (not crash silently)."""
        p = tmp_path / "bad_bom.json"
        p.write_bytes(_BOM + b"not-json!!!")
        with pytest.raises(json.JSONDecodeError):
            read_json(p)

    def test_unicode_content_preserved(self, tmp_path):
        """Unicode values inside the JSON must survive the BOM-transparent round-trip."""
        data = {"name": "Złoto 24k — Estrella", "currency": "PLN", "emoji_free": True}
        p = tmp_path / "unicode.json"
        _write_bom_file(p, data)
        result = read_json(p)
        assert result == data


# ---------------------------------------------------------------------------
# write_json_atomic output guarantees
# ---------------------------------------------------------------------------


class TestWriteJsonAtomicBomFree:
    def test_first_byte_is_open_brace(self, tmp_path):
        """write_json_atomic output must never start with a BOM byte."""
        p = tmp_path / "out.json"
        write_json_atomic(p, _SAMPLE)
        raw = p.read_bytes()
        assert not raw.startswith(_BOM), (
            f"write_json_atomic wrote a BOM prefix; first 4 bytes: {raw[:4]!r}"
        )
        assert raw[0:1] == b"{", (
            f"Expected first byte to be '{{' (0x7B), got {raw[0:1]!r}"
        )

    def test_output_is_valid_utf8_json(self, tmp_path):
        """Output must be valid UTF-8 JSON that Python can re-parse."""
        p = tmp_path / "out.json"
        write_json_atomic(p, _SAMPLE)
        text = p.read_text(encoding="utf-8")
        assert json.loads(text) == _SAMPLE

    def test_repairs_bom_file_on_overwrite(self, tmp_path):
        """Overwriting a BOM-prefixed file with write_json_atomic must produce BOM-free output."""
        p = tmp_path / "was_bom.json"
        _write_bom_file(p, {"old": True})
        write_json_atomic(p, _SAMPLE)
        raw = p.read_bytes()
        assert not raw.startswith(_BOM), "BOM survived overwrite via write_json_atomic"
        assert json.loads(raw.decode("utf-8")) == _SAMPLE

    def test_unicode_values_written_correctly(self, tmp_path):
        """Unicode data must be preserved with ensure_ascii=False."""
        data = {"desc": "Złoto próba 999", "supplier": "Estrellą"}
        p = tmp_path / "unicode_out.json"
        write_json_atomic(p, data)
        raw = p.read_bytes()
        # Must NOT be ASCII-escaped — real Unicode bytes must appear
        assert "Złoto".encode("utf-8") in raw, "Unicode was incorrectly ASCII-escaped"
        assert json.loads(raw.decode("utf-8")) == data


# ---------------------------------------------------------------------------
# Round-trip: write then read
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_write_then_read_json_identical(self, tmp_path):
        """write_json_atomic → read_json round-trip must be lossless."""
        p = tmp_path / "roundtrip.json"
        write_json_atomic(p, _SAMPLE)
        result = read_json(p)
        assert result == _SAMPLE

    def test_overwrite_bom_then_read_clean(self, tmp_path):
        """After overwriting a BOM file, read_json must not warn about BOM."""
        p = tmp_path / "repaired.json"
        _write_bom_file(p, {"stale": True})
        write_json_atomic(p, _SAMPLE)  # repair
        import logging as _logging
        import io as _io
        handler = _logging.handlers = None  # noqa — just checking caplog alternative

        # Use a manual log capture since we're outside a test using caplog fixture
        records: list = []
        class _Capture(_logging.Handler):
            def emit(self, record):
                records.append(record)

        logger = _logging.getLogger("app.utils.io")
        cap = _Capture()
        logger.addHandler(cap)
        try:
            result = read_json(p)
        finally:
            logger.removeHandler(cap)

        assert result == _SAMPLE
        bom_warnings = [r for r in records if "UTF-8 BOM" in r.getMessage()]
        assert bom_warnings == [], (
            "BOM warning emitted after write_json_atomic repair — file still has BOM!"
        )


# ---------------------------------------------------------------------------
# audit_persist._load integration tests
# ---------------------------------------------------------------------------


class TestAuditPersistLoad:
    """
    Tests for the central audit.json reader.

    audit_persist._load() is used by every audit-reading path in the service
    (79+ call sites).  These tests ensure BOM resilience at that integration
    layer without having to test every call site individually.
    """

    def test_load_bom_file_returns_data(self, tmp_path):
        """_load on a BOM-prefixed audit.json must return the parsed dict, not None."""
        from app.services.audit_persist import _load

        p = tmp_path / "audit.json"
        _write_bom_file(p, _SAMPLE)
        result = _load(p)
        assert result is not None, "_load returned None for a BOM-prefixed audit.json"
        assert result == _SAMPLE

    def test_load_clean_file_returns_data(self, tmp_path):
        """_load on a clean audit.json must return the parsed dict."""
        from app.services.audit_persist import _load

        p = tmp_path / "audit.json"
        _write_clean_file(p, _SAMPLE)
        result = _load(p)
        assert result == _SAMPLE

    def test_load_missing_file_returns_none(self, tmp_path):
        """_load on a missing path must return None (no exception)."""
        from app.services.audit_persist import _load

        result = _load(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_bom_file_emits_warning(self, tmp_path, caplog):
        """_load on a BOM-prefixed file must propagate the BOM warning from read_json."""
        from app.services.audit_persist import _load

        p = tmp_path / "audit.json"
        _write_bom_file(p, _SAMPLE)
        with caplog.at_level(logging.WARNING):
            _load(p)
        assert any(
            "UTF-8 BOM" in record.message
            for record in caplog.records
        ), "Expected BOM warning from _load (via read_json)"

    def test_load_malformed_json_returns_none(self, tmp_path):
        """_load on malformed JSON must return None and log a warning (no crash)."""
        from app.services.audit_persist import _load

        p = tmp_path / "audit.json"
        p.write_text("not-json!", encoding="utf-8")
        result = _load(p)
        assert result is None
