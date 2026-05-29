"""
app/tools/dashboard_route_audit.py

Dashboard Route Audit — compares frontend API calls in dashboard.html against
FastAPI registered routes and reports stale / missing / duplicate endpoints.

Usage:
    python3 -m app.tools.dashboard_route_audit
    python3 -m app.tools.dashboard_route_audit --html /path/to/dashboard.html

Exit codes:
    0 — all known frontend endpoints matched a backend route
    1 — stale or unmatched endpoints found
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

# ── default paths ──────────────────────────────────────────────────────────────
_HERE    = Path(__file__).resolve().parent
_SERVICE = _HERE.parents[1]                        # …/CLI/service/
_HTML    = _SERVICE / "app" / "static" / "dashboard.html"


# ── data types ─────────────────────────────────────────────────────────────────

class FrontendCall(NamedTuple):
    method: str    # HTTP verb inferred from context; "GET" when absent
    path:   str    # normalised path — ${…} → {param}, query stripped
    raw:    str    # original string from source (for display)
    line:   int
    concat: bool = False   # URL was built by string concatenation ('/a/' + id + '/b')


class BackendRoute(NamedTuple):
    methods: List[str]   # e.g. ["GET", "POST"]
    path:    str         # FastAPI path, e.g. /api/v1/batches/{batch_id}


class AuditResult(NamedTuple):
    ok:         List[Tuple[FrontendCall, BackendRoute]]
    stale:      List[FrontendCall]
    duplicates: List[Tuple[str, str, int]]   # (method, path, count)


# ── HTML extraction ────────────────────────────────────────────────────────────

# ${…} immediately following a "/" — a genuine path-segment variable
_TVAR_PATH_RE = re.compile(r"(?<=/)\$\{[^}]+\}")
# ${…} NOT following "/" — a query-string fragment or string-concatenated suffix
_TVAR_NONPATH_RE = re.compile(r"\$\{[^}]+\}")

# method: 'POST' or method: "DELETE" in nearby context
_METHOD_RE = re.compile(r"""\bmethod\s*:\s*['"]([A-Z]+)['"]""", re.IGNORECASE)

# Guard against external URLs
_EXTERNAL_RE = re.compile(r"^https?://", re.IGNORECASE)

# A '+' (with optional whitespace) immediately after a fetch URL literal means
# the URL is built by string concatenation: apiFetch('/a/' + id + '/b').
_CONCAT_AFTER_RE = re.compile(r"^\s*\+")


def _normalise(raw: str) -> str:
    """
    Normalise a raw URL string extracted from dashboard source.

    Rules (in order):
    1. ${…} preceded by "/" is a path-segment variable → replace with {param}.
    2. Remaining ${…} (appended to a segment, or inside a query string) is a
       query-string fragment or string-concat suffix → strip entirely.
    3. Strip query string (everything from "?" onward).

    Examples
    --------
    /api/v1/wfirma/customers${qs}          → /api/v1/wfirma/customers
    /api/v1/wfirma/customers/${name}       → /api/v1/wfirma/customers/{param}
    /api/v1/tracking/${id}/timeline        → /api/v1/tracking/{param}/timeline
    /api/v1/dhl/scan-inbox?x=${batchId}   → /api/v1/dhl/scan-inbox
    """
    path = _TVAR_PATH_RE.sub("{param}", raw)   # step 1: path-segment vars
    path = _TVAR_NONPATH_RE.sub("", path)       # step 2: strip remaining vars
    return path.split("?")[0]                   # step 3: strip query string


def _infer_method(context_after: str) -> str:
    """Return HTTP method from the option object that follows the URL, or GET."""
    m = _METHOD_RE.search(context_after)
    return m.group(1).upper() if m else "GET"


def _lineno(html: str, pos: int) -> int:
    return html.count("\n", 0, pos) + 1


def extract_frontend_calls(html: str) -> List[FrontendCall]:
    """Parse dashboard HTML and return every internal API call found."""
    calls: List[FrontendCall] = []

    # ── 1. apiFetch / fetch with quoted or backtick URL ───────────────────────
    #   apiFetch(`/path`, { method: 'POST', … })
    #   fetch('/path', { … })
    # Context is looked up separately so the match doesn't swallow next calls.
    FETCH_RE = re.compile(
        r"""(?:apiFetch|fetch)\(\s*"""
        r"""(?:`([^`]*?)`|'([^']*?)'|"([^"]*?)")""",
        re.DOTALL,
    )
    _NEXT_CALL_RE = re.compile(r"(?:apiFetch|fetch)\(")

    for m in FETCH_RE.finditer(html):
        raw = m.group(1) or m.group(2) or m.group(3) or ""
        if not raw.startswith("/") or _EXTERNAL_RE.match(raw):
            continue
        # Look ahead from the URL's closing delimiter for a method option.
        # Stop at the next fetch/apiFetch call to avoid cross-call contamination.
        window = html[m.end(): m.end() + 220]
        # Detect string-concatenation URL building before trimming the window.
        is_concat = bool(_CONCAT_AFTER_RE.match(window))
        next_call = _NEXT_CALL_RE.search(window)
        if next_call:
            window = window[: next_call.start()]
        method = _infer_method(window)
        calls.append(FrontendCall(
            method=method,
            path=_normalise(raw),
            raw=raw,
            line=_lineno(html, m.start()),
            concat=is_concat,
        ))

    # ── 2. href="/api/..." or href='/api/...' (static) ────────────────────────
    HREF_STATIC_RE = re.compile(r"""href=["'](/(?:api|dashboard|auth)[^"'#?]*)["']""")
    for m in HREF_STATIC_RE.finditer(html):
        raw = m.group(1)
        if _EXTERNAL_RE.match(raw):
            continue
        calls.append(FrontendCall(
            method="GET",
            path=_normalise(raw),
            raw=raw,
            line=_lineno(html, m.start()),
        ))

    # ── 3. href={`/...`} (JSX template literal) ───────────────────────────────
    HREF_TMPL_RE = re.compile(r"""href=\{`(/[^`]+)`\}""")
    for m in HREF_TMPL_RE.finditer(html):
        raw = m.group(1)
        if _EXTERNAL_RE.match(raw):
            continue
        calls.append(FrontendCall(
            method="GET",
            path=_normalise(raw),
            raw=raw,
            line=_lineno(html, m.start()),
        ))

    # ── 4. window.open('/path') ────────────────────────────────────────────────
    OPEN_RE = re.compile(r"""window\.open\(\s*['"]([^'"]+)['"]""")
    for m in OPEN_RE.finditer(html):
        raw = m.group(1)
        if not raw.startswith("/") or _EXTERNAL_RE.match(raw):
            continue
        calls.append(FrontendCall(
            method="GET",
            path=_normalise(raw),
            raw=raw,
            line=_lineno(html, m.start()),
        ))

    return calls


# ── Backend route loading ──────────────────────────────────────────────────────

def load_backend_routes() -> List[BackendRoute]:
    """Import FastAPI app and return all registered HTTP routes."""
    from app.main import app  # noqa: PLC0415 (local import — tool only)
    routes: List[BackendRoute] = []
    for route in app.routes:
        if not (hasattr(route, "methods") and hasattr(route, "path")):
            continue
        methods = sorted(
            m.upper() for m in (route.methods or []) if m.upper() != "HEAD"
        )
        if methods:
            routes.append(BackendRoute(methods=methods, path=route.path))
    return routes


# ── Path matching ──────────────────────────────────────────────────────────────

def _path_segments(path: str) -> List[str]:
    return [s for s in path.split("/") if s]


def _is_param(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


def paths_compatible(fe_path: str, be_path: str) -> bool:
    """
    Return True when fe_path could be a call to be_path.

    Rules:
    - Segment count must match (except FastAPI path converters like {p:path}).
    - A dynamic segment ({…}) in either side matches any concrete value.
    - Literal segments must be equal (case-sensitive).

    Intentional lenience: a frontend {param} matches a backend concrete segment
    (e.g. /action-proposals/{param}/{param} → /action-proposals/{id}/approve).
    This prevents false-negatives for variable action endpoints.  The trade-off
    is an occasional false-positive where a frontend dynamic segment coincidentally
    matches an unrelated backend literal (e.g. {param} matching "status").
    """
    # FastAPI path converters match everything after the prefix
    if re.search(r"\{[^}]+:path\}", be_path):
        prefix = be_path.split("{")[0].rstrip("/")
        return fe_path.startswith(prefix)

    fe_segs = _path_segments(fe_path)
    be_segs = _path_segments(be_path)
    if len(fe_segs) != len(be_segs):
        return False

    for fe, be in zip(fe_segs, be_segs):
        if _is_param(fe) or _is_param(be):
            continue   # dynamic — matches anything
        if fe != be:
            return False
    return True


def path_prefix_compatible(fe_path: str, be_path: str) -> bool:
    """
    Return True when fe_path is a leading path-prefix of be_path.

    Used ONLY for string-concatenation calls, where the static extractor can see
    just the leading literal:

        apiFetch('/api/v1/finance/postings/' + encodeURIComponent(id) + '/breakdown')

    yields the captured literal '/api/v1/finance/postings/'. That literal is a
    genuine prefix of the real route /api/v1/finance/postings/{posting_id}/breakdown,
    so the call resolves — it is not stale. Restricting this leniency to concat
    calls keeps ordinary single-literal calls strictly matched.
    """
    fe_segs = _path_segments(fe_path)
    be_segs = _path_segments(be_path)
    if not fe_segs or len(fe_segs) >= len(be_segs):
        return False   # must be a STRICT prefix (real route has more segments)
    for fe, be in zip(fe_segs, be_segs):
        if _is_param(fe) or _is_param(be):
            continue
        if fe != be:
            return False
    return True


def find_match(fe: FrontendCall, backend: List[BackendRoute]) -> Optional[BackendRoute]:
    """Return the first backend route whose path (and optionally method) match."""
    path_matches: List[BackendRoute] = [
        br for br in backend if paths_compatible(fe.path, br.path)
    ]
    # Prefer method-exact match; fall back to any path match (avoids false positives)
    for br in path_matches:
        if fe.method in br.methods:
            return br
    # Path matched but method differs — still count as matched (route exists)
    if path_matches:
        return path_matches[0]
    # Concatenation-built URLs ('/a/' + id + '/b'): the extractor only saw the
    # leading literal. Match it as a strict path-prefix of a real route so the
    # truncated capture is not mis-reported as stale. Scoped to concat calls.
    if fe.concat:
        prefix_matches = [
            br for br in backend if path_prefix_compatible(fe.path, br.path)
        ]
        for br in prefix_matches:
            if fe.method in br.methods:
                return br
        if prefix_matches:
            return prefix_matches[0]
    return None


# ── Audit ──────────────────────────────────────────────────────────────────────

def audit(
    html: str,
    backend: List[BackendRoute],
    *,
    skip_variable_action: bool = True,
) -> AuditResult:
    """
    Core audit logic — pure function for testability.

    skip_variable_action: skip paths like fetch(action.endpoint, …) where the
    URL is a JavaScript variable, not a string literal.
    """
    calls = extract_frontend_calls(html)

    # Deduplicate by (method, path) — keep first occurrence line number
    seen: Dict[Tuple[str, str], FrontendCall] = {}
    for fc in calls:
        key = (fc.method, fc.path)
        if key not in seen:
            seen[key] = fc
    unique = list(seen.values())

    # Count occurrences for duplicate detection (before dedup)
    counter: Counter[Tuple[str, str]] = Counter((c.method, c.path) for c in calls)
    duplicates = [
        (method, path, cnt)
        for (method, path), cnt in sorted(counter.items())
        if cnt > 1
    ]

    ok:    List[Tuple[FrontendCall, BackendRoute]] = []
    stale: List[FrontendCall] = []

    for fc in unique:
        matched = find_match(fc, backend)
        if matched:
            ok.append((fc, matched))
        else:
            stale.append(fc)

    return AuditResult(ok=ok, stale=stale, duplicates=duplicates)


# ── Report ─────────────────────────────────────────────────────────────────────

def print_report(result: AuditResult, html_path: Path) -> int:
    """Print audit report and return exit code (0=clean, 1=stale found)."""
    HR = "─" * 62

    print()
    print("Dashboard Route Audit")
    print(f"HTML: {html_path}")
    print(HR)

    # OK
    print(f"\n✓  OK routes  ({len(result.ok)})")
    for fc, br in sorted(result.ok, key=lambda x: x[0].path):
        marker = " ⚑ method mismatch" if fc.method not in br.methods else ""
        print(f"   {fc.method:<7}  {fc.path}{marker}")

    # Stale
    print(f"\n✗  Stale / missing routes  ({len(result.stale)})")
    if result.stale:
        for fc in sorted(result.stale, key=lambda x: x.path):
            print(f"   {fc.method:<7}  {fc.path}  [line {fc.line}]")
    else:
        print("   (none)")

    # Duplicates
    print(f"\n⚑  Duplicate frontend calls  ({len(result.duplicates)})")
    if result.duplicates:
        for method, path, cnt in result.duplicates:
            print(f"   {method:<7}  {path}  [{cnt}× in dashboard]")
    else:
        print("   (none)")

    # Summary
    print(f"\n{HR}")
    print("Summary")
    print(f"  OK:           {len(result.ok)}")
    print(f"  Stale:        {len(result.stale)}")
    print(f"  Duplicates:   {len(result.duplicates)}")
    print()

    if result.stale:
        print(f"RESULT: {len(result.stale)} stale endpoint(s) found.")
        return 1
    print("RESULT: All known endpoints matched.")
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit dashboard.html API calls against registered FastAPI routes.",
    )
    parser.add_argument(
        "--html",
        type=Path,
        default=_HTML,
        help="Path to dashboard.html (default: service/app/static/dashboard.html)",
    )
    args = parser.parse_args(argv)

    html_path: Path = args.html
    if not html_path.is_file():
        print(f"ERROR: HTML file not found: {html_path}", file=sys.stderr)
        return 2

    html    = html_path.read_text(encoding="utf-8")
    backend = load_backend_routes()
    result  = audit(html, backend)
    return print_report(result, html_path)


if __name__ == "__main__":
    sys.exit(main())
