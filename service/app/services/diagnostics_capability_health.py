"""Capability-aware diagnostics helpers for GET /api/v1/debug/health-full.

Backend owns requirement class + status + aggregation. Frontend only displays.
No second health engine. No fake credentials. No auth weakening.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Status vocabulary (operator-facing)
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_DEPRECATED = "deprecated"
STATUS_NOT_APPLICABLE = "not_applicable"

# Requirement classes — global health uses REQUIRED only
REQ_REQUIRED = "required"
REQ_OPTIONAL = "optional"
REQ_DEPRECATED = "deprecated"
REQ_NOT_APPLICABLE = "not_applicable"

# Deploy marker — same relative rule as routes_webhooks_wfirma_status (C:\\PZ\\version.txt
# when running from C:\\PZ\\app\\api\\*). Also accept explicit env / absolute prod path.
_DEPLOY_VERSION_CANDIDATES = (
    Path(os.environ["PZ_VERSION_FILE"]) if os.environ.get("PZ_VERSION_FILE") else None,
    Path(r"C:\PZ\version.txt"),
    Path(__file__).resolve().parents[2] / "version.txt",  # …/app/version.txt (unusual)
    Path(__file__).resolve().parents[3] / "version.txt",  # …/service/../ or C:\\PZ when app/
)


def make_check(
    *,
    status: str,
    requirement: str,
    detail: str,
    fix: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "status": status,
        "requirement": requirement,
        "detail": detail,
    }
    if fix:
        out["fix"] = fix
    if evidence:
        out["evidence"] = evidence
    return out


def aggregate_checks(checks: Dict[str, Any]) -> Dict[str, Any]:
    """Requirement-aware summary.

    Only REQUIRED status=fail degrades ``overall``. An OPTIONAL capability may be
    status=fail without affecting platform health. Deprecated / not_applicable /
    not_configured never degrade overall.
    """
    required_keys: List[str] = []
    required_ok = 0
    required_failed = 0
    warnings = 0
    optional_not_configured = 0
    optional_failed = 0
    deprecated = 0
    not_applicable = 0

    for key, raw in checks.items():
        if not isinstance(raw, dict):
            continue
        req = raw.get("requirement") or REQ_OPTIONAL
        st = raw.get("status") or STATUS_WARN
        if req == REQ_REQUIRED:
            required_keys.append(key)
            if st == STATUS_FAIL:
                required_failed += 1
            elif st == STATUS_OK:
                required_ok += 1
            elif st == STATUS_WARN:
                warnings += 1
        else:
            if st == STATUS_WARN:
                warnings += 1
            if req == REQ_OPTIONAL and st == STATUS_FAIL:
                optional_failed += 1
        if st == STATUS_NOT_CONFIGURED:
            optional_not_configured += 1
        if st == STATUS_DEPRECATED or req == REQ_DEPRECATED:
            deprecated += 1
        if st == STATUS_NOT_APPLICABLE or req == REQ_NOT_APPLICABLE:
            not_applicable += 1

    required_total = len(required_keys)
    overall = "ok" if required_failed == 0 else "degraded"
    return {
        "overall": overall,
        "required_total": required_total,
        "required_ok": required_ok,
        "required_failed": required_failed,
        "warnings": warnings,
        "optional_not_configured": optional_not_configured,
        "optional_failed": optional_failed,
        "deprecated": deprecated,
        "not_applicable": not_applicable,
        # Back-compat counters (honest: fail_count = required failures only)
        "fail_count": required_failed,
        "warn_count": warnings,
    }


def probe_pdf_unicode_font() -> Tuple[bool, str, str]:
    """Ask the same candidate set the PDF renderers use (statement + pz_pdf_export).

    Returns (ok, detail, fix). Prefer DejaVu / Arial Unicode; accept reportlab Vera
    as last resort (bundled). Never emit macOS-brew-only remediation on Windows.
    """
    import reportlab as _rl
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    _rl_font_dir = os.path.join(os.path.dirname(_rl.__file__), "fonts")
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        (r"C:\Windows\Fonts\DejaVuSans.ttf", r"C:\Windows\Fonts\DejaVuSans-Bold.ttf", "DejaVu"),
        (os.path.join(windir, "Fonts", "arialuni.ttf"), os.path.join(windir, "Fonts", "arialuni.ttf"), "ArialUnicode"),
        (os.path.join(windir, "Fonts", "Arial.ttf"), os.path.join(windir, "Fonts", "Arial.ttf"), "Arial"),
        ("/Library/Fonts/DejaVuSans.ttf", "/Library/Fonts/DejaVuSans-Bold.ttf", "DejaVu"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVu"),
        ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf", "ArialUnicode"),
        (os.path.join(_rl_font_dir, "Vera.ttf"), os.path.join(_rl_font_dir, "VeraBd.ttf"), "Vera"),
    ]
    for reg, bold, name in candidates:
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                # Prove loadable without permanently polluting registry names if already present
                probe_name = f"EJDiagProbe-{name}"
                if probe_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(probe_name, reg))
                return True, f"Unicode TTF via renderer authority: {reg} ({name})", ""
            except Exception as exc:
                continue
    fix = (
        "Install a Unicode TTF used by the PDF renderers (DejaVu / Arial Unicode), "
        "or ensure reportlab ships Vera.ttf."
    )
    if os.name == "nt":
        fix = (
            "Install DejaVuSans.ttf under %WINDIR%\\Fonts or keep reportlab's bundled "
            "Vera.ttf available — do not use macOS brew paths on Windows."
        )
    return False, "No Unicode TTF font resolvable by PDF renderer candidate set", fix


def probe_backup_freshness(backup_root: Path) -> Dict[str, Any]:
    """Reflect Deploy-PZ layout: C:\\PZ-backups\\<unit>\\unit.json (not legacy manifest.json)."""
    if not backup_root.exists():
        return make_check(
            status=STATUS_WARN,
            requirement=REQ_OPTIONAL,
            detail=f"Backup root does not exist: {backup_root}",
        )

    newest_unit = None
    newest_time: Optional[datetime] = None

    for item in backup_root.iterdir():
        if not item.is_dir():
            continue
        unit_path = item / "unit.json"
        legacy = item / "manifest.json"
        meta_path = unit_path if unit_path.exists() else legacy if legacy.exists() else None
        if meta_path is None:
            continue
        try:
            import json
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ts_raw = (
                meta.get("created")
                or meta.get("finished_at")
                or meta.get("created_at")
            )
            if not ts_raw:
                # Fall back to directory mtime
                mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                if newest_time is None or mtime > newest_time:
                    newest_time = mtime
                    newest_unit = item.name
                continue
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if newest_time is None or ts > newest_time:
                newest_time = ts
                newest_unit = item.name
        except Exception:
            continue

    if newest_unit is None or newest_time is None:
        return make_check(
            status=STATUS_WARN,
            requirement=REQ_OPTIONAL,
            detail="No Deploy-PZ backup units (unit.json) found under backup root",
            fix="Run a gated Deploy-PZ release to mint a backup unit under C:\\PZ-backups",
        )

    age_hours = (datetime.now(timezone.utc) - newest_time).total_seconds() / 3600
    if age_hours < 26:
        return make_check(
            status=STATUS_OK,
            requirement=REQ_OPTIONAL,
            detail=f"Latest backup unit {newest_unit}: {age_hours:.1f}h ago",
            evidence={"unit": newest_unit, "age_hours": round(age_hours, 2)},
        )
    return make_check(
        status=STATUS_WARN,
        requirement=REQ_OPTIONAL,
        detail=f"Latest backup unit {newest_unit} is {age_hours:.1f}h old",
        evidence={"unit": newest_unit, "age_hours": round(age_hours, 2)},
    )


def read_deploy_marker_sha() -> Tuple[str, str]:
    """Return (sha, source_label). Prefer C:\\PZ\\version.txt deploy authority."""
    env = os.environ.get("PZ_VERSION")
    if env and env.strip():
        return env.strip(), "env:PZ_VERSION"
    for cand in _DEPLOY_VERSION_CANDIDATES:
        if cand is None:
            continue
        try:
            if cand.is_file():
                sha = cand.read_text(encoding="utf-8-sig").strip()
                if sha:
                    return sha, str(cand)
        except Exception:
            continue
    return "", "missing"


def openapi_paths_from_app(app) -> List[str]:
    paths: List[str] = []
    for route in getattr(app, "routes", []) or []:
        p = getattr(route, "path", None)
        if isinstance(p, str):
            paths.append(p)
    return paths


def classify_http_reachability(status_code: int, *, expect_auth: bool = True) -> Tuple[str, str]:
    """Map HTTP semantics for reachability probes (public or local)."""
    if status_code == 200:
        return STATUS_OK, f"HTTP {status_code}"
    if 300 <= status_code < 400:
        return STATUS_OK, f"HTTP {status_code} (redirect — reachable)"
    if expect_auth and status_code in (401, 403):
        return STATUS_OK, f"HTTP {status_code} (reachable; endpoint protected as designed)"
    if status_code >= 500:
        return STATUS_FAIL, f"HTTP {status_code} (application error)"
    return STATUS_WARN, f"HTTP {status_code}"
