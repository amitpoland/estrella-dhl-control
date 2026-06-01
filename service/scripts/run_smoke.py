"""
run_smoke.py — repeatable smoke runbook driver.

Reads a smoke-spec JSON file, executes each step against an HTTP endpoint,
captures actual status code + response excerpt, and writes a markdown report
into tasks/smoke-reports/.

Spec format (smoke-spec.json):

  {
    "title": "Carriers Config post-deploy",
    "batches": ["B9"],
    "environment": "production",
    "base_url": "http://127.0.0.1:47213",
    "headers": {"X-API-KEY": ""},
    "cleanup_after": true,
    "steps": [
      {
        "name": "Create dhl",
        "method": "PUT",
        "path": "/api/v1/carriers-config/dhl",
        "body": {"name": "DHL Express", "api_type": "api"},
        "expected_status": 200
      },
      {"name": "Delete dhl", "method": "DELETE",
       "path": "/api/v1/carriers-config/dhl", "expected_status": 204}
    ]
  }

The driver does NOT navigate a browser; it covers the API contract that the
frontend would call. Visual / DOM smoke remains an operator step.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class StepResult:
    name:            str
    method:          str
    path:            str
    expected_status: int
    actual_status:   Optional[int] = None
    actual_excerpt:  Optional[str] = None
    error:           Optional[str] = None

    @property
    def verdict(self) -> str:
        if self.error:
            return "FAIL"
        if self.actual_status == self.expected_status:
            return "PASS"
        return "FAIL"


@dataclass
class SmokeRun:
    title:        str
    batches:      List[str]
    environment:  str
    base_url:     str
    headers:      Dict[str, str]
    steps:        List[StepResult] = field(default_factory=list)
    started_at:   str = ""
    finished_at:  str = ""
    # P6 metadata extensions (read from spec; round-tripped to report)
    required_entities: List[str]      = field(default_factory=list)
    expected_console:  str            = "clean"
    expected_api:      str            = "all 2xx unless otherwise stated"
    required_cleanup:  List[str]      = field(default_factory=list)
    artifacts:         List[str]      = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return all(s.verdict == "PASS" for s in self.steps)

    @property
    def verdict(self) -> str:
        if not self.steps:
            return "PARTIAL"
        return "PASS" if self.all_pass else "FAIL"


def _validate_spec_metadata(spec: Dict[str, Any]) -> List[str]:
    """P6: validate the smoke-spec's metadata extension. Returns list of warnings
    (not errors) so old specs without the new fields still run.

    Recommended additional fields in a P6 smoke spec:
      - required_entities:  list of entity names this smoke covers
      - expected_console:   string description (default "clean")
      - expected_api:       string description (default "all 2xx ...")
      - required_cleanup:   list of resources the smoke MUST clean up
      - slug:               short kebab-case identifier
    """
    warnings: List[str] = []
    if not spec.get("required_entities"):
        warnings.append("missing recommended field: required_entities")
    if not spec.get("slug"):
        warnings.append("missing recommended field: slug (used for report filename)")
    return warnings


# ── Spec / runner ────────────────────────────────────────────────────────────

def load_spec(spec_file: Path) -> Dict[str, Any]:
    return json.loads(spec_file.read_text(encoding="utf-8"))


def _http_call(method: str, url: str, body: Optional[Dict[str, Any]],
              headers: Dict[str, str], timeout: int = 15) -> tuple[int, str]:
    data = None
    h = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(512).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body_excerpt = ""
        try:
            body_excerpt = e.read(512).decode("utf-8", errors="replace")
        except Exception:
            pass
        return e.code, body_excerpt


def run_smoke(spec: Dict[str, Any]) -> SmokeRun:
    run = SmokeRun(
        title=spec.get("title", "Smoke run"),
        batches=spec.get("batches", []),
        environment=spec.get("environment", "local"),
        base_url=spec.get("base_url", "http://127.0.0.1:47213"),
        headers=spec.get("headers", {}),
        started_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        # P6 metadata
        required_entities=list(spec.get("required_entities", []) or []),
        expected_console=spec.get("expected_console", "clean"),
        expected_api=spec.get("expected_api", "all 2xx unless otherwise stated"),
        required_cleanup=list(spec.get("required_cleanup", []) or []),
    )
    for step_spec in spec.get("steps", []):
        sr = StepResult(
            name=step_spec.get("name", step_spec.get("path", "?")),
            method=step_spec.get("method", "GET").upper(),
            path=step_spec["path"],
            expected_status=int(step_spec.get("expected_status", 200)),
        )
        url = run.base_url.rstrip("/") + sr.path
        try:
            sr.actual_status, sr.actual_excerpt = _http_call(
                sr.method, url, step_spec.get("body"), run.headers
            )
        except Exception as exc:
            sr.error = str(exc)
        run.steps.append(sr)
    run.finished_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return run


# ── Report ───────────────────────────────────────────────────────────────────

def render_markdown(run: SmokeRun) -> str:
    lines = [
        f"# Smoke report — {run.title}",
        "",
        f"**Date:** {run.started_at[:10]}",
        f"**Batches:** {', '.join(run.batches) or '—'}",
        f"**Environment:** {run.environment}",
        f"**Tester:** run_smoke.py driver",
    ]
    # P6: emit metadata sections when present
    if run.required_entities:
        lines.append("")
        lines.append(f"**Required entities:** {', '.join(run.required_entities)}")
    lines.append(f"**Expected console:** {run.expected_console}")
    lines.append(f"**Expected API:** {run.expected_api}")
    if run.required_cleanup:
        lines.append(f"**Required cleanup:** {', '.join(run.required_cleanup)}")
    lines.extend([
        "",
        "## Coverage",
        "",
        "| Step | Method | Path | Expected | Actual | Verdict |",
        "|---|---|---|---|---|---|",
    ])
    for s in run.steps:
        actual = str(s.actual_status) if s.actual_status is not None else f"ERR:{s.error or '?'}"
        lines.append(
            f"| {s.name} | {s.method} | `{s.path}` | {s.expected_status} | {actual} | {s.verdict} |"
        )
    lines.extend([
        "",
        f"**Started:**  {run.started_at}",
        f"**Finished:** {run.finished_at}",
        "",
        f"## Verdict",
        "",
        f"**{run.verdict}**",
    ])
    return "\n".join(lines) + "\n"


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="run_smoke",
        description="Run a smoke-spec JSON file and write a markdown report.",
    )
    p.add_argument("spec", type=Path, help="Path to smoke-spec JSON")
    p.add_argument("--output", "-o", type=Path,
                  help="Output report path (default: tasks/smoke-reports/<date>-<slug>.md)")
    p.add_argument("--print-only", action="store_true",
                  help="Print report to stdout instead of writing")
    p.add_argument("--api-key", default="",
                  help="X-API-Key to inject into every request (never committed to spec files)")
    args = p.parse_args(argv)

    if not args.spec.exists():
        print(f"Spec file not found: {args.spec}", file=sys.stderr)
        return 2

    spec = load_spec(args.spec)
    if args.api_key:
        spec.setdefault("headers", {})
        spec["headers"]["X-API-Key"] = args.api_key
    run = run_smoke(spec)
    report = render_markdown(run)

    if args.print_only:
        print(report)
    else:
        if args.output is None:
            date = run.started_at[:10]
            slug = (spec.get("slug") or run.title.lower()
                                              .replace(" ", "-")
                                              .replace("/", "-"))
            args.output = Path("tasks/smoke-reports") / f"{date}-{slug}.md"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output}")

    return 0 if run.all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
