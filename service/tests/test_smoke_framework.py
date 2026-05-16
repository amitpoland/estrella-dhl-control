"""test_smoke_framework.py — unit tests for run_smoke.py.

Uses urllib mocking via monkeypatch to avoid real HTTP calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    scripts = here.parents[1] / "scripts"
    for p in (str(here.parents[1]), str(scripts)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

import run_smoke  # type: ignore


def test_step_result_verdict_pass():
    s = run_smoke.StepResult(name="x", method="GET", path="/x",
                              expected_status=200, actual_status=200)
    assert s.verdict == "PASS"


def test_step_result_verdict_fail_on_status_mismatch():
    s = run_smoke.StepResult(name="x", method="GET", path="/x",
                              expected_status=200, actual_status=500)
    assert s.verdict == "FAIL"


def test_step_result_verdict_fail_on_error():
    s = run_smoke.StepResult(name="x", method="GET", path="/x",
                              expected_status=200, error="connection refused")
    assert s.verdict == "FAIL"


def test_smoke_run_all_pass_property():
    run = run_smoke.SmokeRun(title="t", batches=[], environment="local",
                              base_url="http://x", headers={})
    run.steps = [
        run_smoke.StepResult(name="a", method="GET", path="/a",
                              expected_status=200, actual_status=200),
        run_smoke.StepResult(name="b", method="GET", path="/b",
                              expected_status=200, actual_status=200),
    ]
    assert run.all_pass is True
    assert run.verdict == "PASS"


def test_smoke_run_fail_property():
    run = run_smoke.SmokeRun(title="t", batches=[], environment="local",
                              base_url="http://x", headers={})
    run.steps = [
        run_smoke.StepResult(name="a", method="GET", path="/a",
                              expected_status=200, actual_status=200),
        run_smoke.StepResult(name="b", method="GET", path="/b",
                              expected_status=200, actual_status=500),
    ]
    assert run.all_pass is False
    assert run.verdict == "FAIL"


def test_render_markdown_contains_steps():
    run = run_smoke.SmokeRun(title="My run", batches=["B9"], environment="prod",
                              base_url="http://x", headers={},
                              started_at="2026-05-16T10:00:00+00:00",
                              finished_at="2026-05-16T10:00:01+00:00")
    run.steps = [
        run_smoke.StepResult(name="create", method="PUT", path="/api/v1/x",
                              expected_status=200, actual_status=200),
    ]
    md = run_smoke.render_markdown(run)
    assert "# Smoke report — My run" in md
    assert "B9" in md
    assert "/api/v1/x" in md
    assert "**PASS**" in md


def test_render_markdown_fail_marker():
    run = run_smoke.SmokeRun(title="My fail run", batches=[], environment="local",
                              base_url="http://x", headers={},
                              started_at="2026-05-16T10:00:00+00:00",
                              finished_at="2026-05-16T10:00:01+00:00")
    run.steps = [
        run_smoke.StepResult(name="boom", method="GET", path="/x",
                              expected_status=200, actual_status=500,
                              actual_excerpt="oops"),
    ]
    md = run_smoke.render_markdown(run)
    assert "FAIL" in md


def test_load_spec_from_file(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({
        "title": "T", "batches": ["B1"], "environment": "local",
        "base_url": "http://x", "headers": {}, "steps": []
    }))
    s = run_smoke.load_spec(spec_path)
    assert s["title"] == "T"


def test_run_smoke_with_mocked_http(monkeypatch):
    """run_smoke must call _http_call once per step and assemble results."""
    calls = []

    def fake_http(method, url, body, headers, timeout=15):
        calls.append((method, url, body))
        # Return status 200 for the first step, 422 for the second
        if "create" in url:
            return 200, '{"id": 1}'
        return 422, '{"detail": "bad"}'

    monkeypatch.setattr(run_smoke, "_http_call", fake_http)

    spec = {
        "title": "X", "batches": ["B"], "environment": "local",
        "base_url": "http://test", "headers": {},
        "steps": [
            {"name": "create", "method": "PUT", "path": "/api/v1/create",
             "body": {"x": 1}, "expected_status": 200},
            {"name": "reject", "method": "PUT", "path": "/api/v1/reject",
             "body": {}, "expected_status": 422},
        ]
    }
    run = run_smoke.run_smoke(spec)
    assert len(run.steps) == 2
    assert run.steps[0].actual_status == 200
    assert run.steps[1].actual_status == 422
    assert run.all_pass is True  # expected 422 actually 422 → PASS
    assert len(calls) == 2


def test_run_smoke_records_unexpected_status_as_fail(monkeypatch):
    def fake_http(method, url, body, headers, timeout=15):
        return 500, "internal error"

    monkeypatch.setattr(run_smoke, "_http_call", fake_http)
    spec = {
        "title": "X", "batches": [], "environment": "local",
        "base_url": "http://test", "headers": {},
        "steps": [{"name": "x", "method": "GET", "path": "/x",
                   "expected_status": 200}]
    }
    run = run_smoke.run_smoke(spec)
    assert run.steps[0].verdict == "FAIL"
    assert run.verdict == "FAIL"


def test_main_writes_report_file(tmp_path, monkeypatch):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({
        "title": "smoke-test-write",
        "batches": ["B1"], "environment": "local",
        "base_url": "http://test", "headers": {},
        "slug": "smoke-test-write",
        "steps": []
    }))
    out_path = tmp_path / "report.md"
    rc = run_smoke.main([str(spec_path), "--output", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    content = out_path.read_text()
    assert "smoke-test-write" in content


def test_main_returns_nonzero_on_failure(tmp_path, monkeypatch):
    def fake_http(method, url, body, headers, timeout=15):
        return 500, ""
    monkeypatch.setattr(run_smoke, "_http_call", fake_http)
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({
        "title": "fails", "batches": [], "environment": "local",
        "base_url": "http://test", "headers": {},
        "slug": "fails",
        "steps": [{"name": "x", "method": "GET", "path": "/x",
                   "expected_status": 200}]
    }))
    out_path = tmp_path / "report.md"
    rc = run_smoke.main([str(spec_path), "--output", str(out_path)])
    assert rc == 1


# ── Real smoke-reports directory sanity ──────────────────────────────────────

def test_smoke_reports_readme_exists():
    p = Path(__file__).resolve().parents[2] / "tasks" / "smoke-reports" / "README.md"
    assert p.exists(), f"smoke-reports README must exist at {p}"
    text = p.read_text(encoding="utf-8")
    assert "Required sections" in text


def test_real_smoke_reports_are_markdown():
    sr_dir = Path(__file__).resolve().parents[2] / "tasks" / "smoke-reports"
    if not sr_dir.exists():
        pytest.skip(f"smoke-reports dir not present: {sr_dir}")
    for f in sr_dir.glob("*.md"):
        if f.name == "README.md":
            continue
        text = f.read_text(encoding="utf-8")
        assert text.startswith("# "), f"Smoke report must start with H1: {f.name}"
        assert "Verdict" in text, f"Smoke report must declare a Verdict: {f.name}"
