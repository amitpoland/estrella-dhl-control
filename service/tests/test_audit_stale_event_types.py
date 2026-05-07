"""
test_audit_stale_event_types.py — read-only sweep regression tests.

Pins the contract for service/scripts/audit_stale_event_types.py:
  * detects messages with event_type='other' AND DHL ticket markers
  * imports markers live from email_thread_mapper (does NOT duplicate)
  * is read-only — never mutates any record
  * --json output parses cleanly
  * customs-value-freeze — never echoes monetary keys
  * exits non-zero on missing evidence directory
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

_SCRIPT_PATH = _SVC / "scripts" / "audit_stale_event_types.py"


# ── Load the sweep module dynamically (it's a script, not a package member)

@pytest.fixture(scope="module")
def sweep_module():
    spec = importlib.util.spec_from_file_location(
        "audit_stale_event_types", _SCRIPT_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ── Fixture builder ────────────────────────────────────────────────────────

def _make_evidence(tmp_path: Path, awb: str, messages: list) -> Path:
    """
    Write a minimal email_evidence/by_awb/{awb}.json with the supplied
    messages list (a single thread). Returns the file path.
    """
    by_awb = tmp_path / "email_evidence" / "by_awb"
    by_awb.mkdir(parents=True, exist_ok=True)
    p = by_awb / f"{awb}.json"
    doc = {
        "awb": awb,
        "batch_ids": ["BATCH_TEST"],
        "threads": [{
            "thread_id":    "thread-1",
            "subject_root": (messages[0].get("subject") or "") if messages else "",
            "messages":     messages,
        }] if messages else [],
        "summary": {},
    }
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def _msg(subject: str, event_type: str = "other",
         message_id: str = "M1", sender: str = "import@estrellajewels.eu",
         direction: str = "outgoing", **extra) -> Dict[str, Any]:
    base = {
        "message_id": message_id,
        "subject":    subject,
        "sender":     sender,
        "direction":  direction,
        "event_type": event_type,
        "timestamp":  "2026-05-07T06:34:46Z",
    }
    base.update(extra)
    return base


# ── A. Clean store: zero suspects ──────────────────────────────────────────

def test_sweep_finds_no_suspects_in_clean_store(tmp_path, sweep_module):
    _make_evidence(tmp_path, "1234567890", [
        _msg("Re:T#1WA000000 - clean reply",
             event_type="our_dhl_reply"),       # already classified correctly
        _msg("Random unrelated subject",
             event_type="other", message_id="M2"),  # other, no markers
    ])
    report = sweep_module.sweep(tmp_path)
    assert report["scanned"]["awb_files"] == 1
    assert report["scanned"]["messages"]  == 2
    assert report["suspects"] == []


# ── B. Ticket token marker ─────────────────────────────────────────────────

def test_sweep_finds_suspect_with_ticket_token(tmp_path, sweep_module):
    _make_evidence(tmp_path, "6049349806", [
        _msg("Re:T#1WA2605070000083 - operator reply"),
    ])
    report = sweep_module.sweep(tmp_path)
    assert len(report["suspects"]) == 1
    s = report["suspects"][0]
    assert s["awb"] == "6049349806"
    assert "ticket_token" in s["matched_markers"]


# ── C. Phrase marker ──────────────────────────────────────────────────────

def test_sweep_finds_suspect_with_phrase_marker(tmp_path, sweep_module):
    _make_evidence(tmp_path, "1234567890", [
        _msg("Agencja Celna DHL — clearance request"),
    ])
    report = sweep_module.sweep(tmp_path)
    assert len(report["suspects"]) == 1
    markers = report["suspects"][0]["matched_markers"]
    # Must match at least one of the canonical phrases
    from app.services.email_thread_mapper import _DHL_TICKET_THREAD_PHRASES
    assert any(m in _DHL_TICKET_THREAD_PHRASES for m in markers)


# ── D. Already-correct event_type ignored ──────────────────────────────────

def test_sweep_ignores_messages_with_correct_event_type(tmp_path, sweep_module):
    _make_evidence(tmp_path, "1234567890", [
        _msg("T#1WA0000 — operator reply already classified",
             event_type="our_dhl_reply"),
    ])
    report = sweep_module.sweep(tmp_path)
    assert report["suspects"] == []


# ── E. JSON output shape ──────────────────────────────────────────────────

def test_sweep_json_output_shape(tmp_path, sweep_module):
    _make_evidence(tmp_path, "6049349806", [
        _msg("Re:T#1WA2605070000083 - operator reply"),
    ])
    buf = io.StringIO()
    sweep_module._render_json(sweep_module.sweep(tmp_path), out=buf)
    parsed = json.loads(buf.getvalue())
    assert set(parsed.keys()) == {"scanned", "suspects"}
    assert set(parsed["scanned"].keys()) == {"awb_files", "messages"}
    assert len(parsed["suspects"]) == 1
    s = parsed["suspects"][0]
    assert {"awb", "message_id", "subject", "sender", "direction",
            "matched_markers"} <= set(s.keys())
    # JSON output preserves the FULL subject (not truncated)
    assert s["subject"] == "Re:T#1WA2605070000083 - operator reply"


# ── F. Read-only — no mutation ─────────────────────────────────────────────

def test_sweep_does_not_mutate_records(tmp_path, sweep_module):
    p = _make_evidence(tmp_path, "6049349806", [
        _msg("Re:T#1WA2605070000083 - operator reply"),
    ])
    before = p.read_bytes()
    before_mtime = p.stat().st_mtime_ns
    sweep_module.sweep(tmp_path)
    sweep_module._render_human(sweep_module.sweep(tmp_path), out=io.StringIO())
    sweep_module._render_json(sweep_module.sweep(tmp_path), out=io.StringIO())
    after = p.read_bytes()
    after_mtime = p.stat().st_mtime_ns
    assert before == after, "sweep mutated the by_awb json file"
    assert before_mtime == after_mtime, "sweep touched mtime"


# ── G. customs-value-freeze: monetary keys never echoed ────────────────────

def test_sweep_does_not_print_monetary_keys(tmp_path, sweep_module):
    _make_evidence(tmp_path, "6049349806", [
        _msg("Re:T#1WA2605070000083 - bad data",
             # Stray monetary keys deliberately injected:
             unit_price=100, total_value=500, cif=999.99, duty=88.0),
    ])
    # Run via the module's render functions and capture stdout
    report = sweep_module.sweep(tmp_path)
    buf_h = io.StringIO()
    sweep_module._render_human(report, out=buf_h)
    buf_j = io.StringIO()
    sweep_module._render_json(report, out=buf_j)

    forbidden = ("unit_price", "total_value", "999.99", "88.0",
                 "\"cif\"", "\"duty\"", "\"vat\"", "\"amount\"")
    for f in forbidden:
        assert f not in buf_h.getvalue(), (
            f"forbidden monetary token {f!r} appeared in human output"
        )
        assert f not in buf_j.getvalue(), (
            f"forbidden monetary token {f!r} appeared in JSON output"
        )


# ── H. Missing evidence directory → non-zero exit ──────────────────────────

def test_sweep_handles_missing_evidence_dir(tmp_path, sweep_module, capsys):
    # tmp_path exists but has no email_evidence/by_awb/ subdir
    rc = sweep_module.main.__wrapped__ if hasattr(sweep_module.main, "__wrapped__") else None
    # Use argv override to simulate CLI run
    with patch.object(sys, "argv", ["audit_stale_event_types.py",
                                     "--storage", str(tmp_path)]):
        rc = sweep_module.main()
    captured = capsys.readouterr()
    assert rc != 0
    assert "evidence directory not found" in (captured.err + captured.out)


# ── I. C5: markers imported from email_thread_mapper, not duplicated ──────

def test_sweep_imports_markers_from_email_thread_mapper(sweep_module):
    """Two-part check: (a) the script source has the explicit import; (b) the
    constants the script uses are the SAME module-level objects as in
    email_thread_mapper (not copies)."""
    # (a) — source-level import statement present
    src = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "from app.services.email_thread_mapper import" in src
    assert "_DHL_TICKET_PATTERN" in src
    assert "_DHL_TICKET_THREAD_PHRASES" in src

    # (b) — runtime identity check
    from app.services import email_thread_mapper as etm
    assert sweep_module._DHL_TICKET_PATTERN is etm._DHL_TICKET_PATTERN
    assert sweep_module._DHL_TICKET_THREAD_PHRASES is etm._DHL_TICKET_THREAD_PHRASES


# ── J. (extra) Multiple markers compound on one subject ────────────────────

def test_sweep_records_multiple_markers_when_both_match(tmp_path, sweep_module):
    """A subject containing both a T# token AND a canonical phrase records
    BOTH markers in matched_markers."""
    _make_evidence(tmp_path, "6049349806", [
        _msg("Re:T#1WA2605070000083 - Agencja Celna DHL - przesyłka"),
    ])
    report = sweep_module.sweep(tmp_path)
    assert len(report["suspects"]) == 1
    markers = report["suspects"][0]["matched_markers"]
    assert "ticket_token" in markers
    assert any(m == "agencja celna dhl" or m == "przesyłka numer"
               or m == "przesylka numer" for m in markers)
