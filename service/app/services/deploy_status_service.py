"""
deploy_status_service.py — Read-only deployment state reader.

Data sources (both are optional and degrade gracefully):
  1. storage_root/version.json   — written by deploy-service.sh; provides live_sha + deployed_at
  2. DEPLOY_STATE_MD_PATH env var — points to TASK_STATE.md in the Claude memory directory;
                                    parsed with regex for PR queue, gate results, deploy status

No write operations. No external calls. Safe to expose via API.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)


# ── version.json reader ───────────────────────────────────────────────────────

def _read_version_json() -> dict[str, Any]:
    version_file = settings.storage_root / "version.json"
    try:
        data = json.loads(version_file.read_text(encoding="utf-8"))
        return {
            "live_sha":     data.get("commit", "unknown"),
            "deployed_at":  data.get("deployed_at", "unknown"),
            "source":       "version_json",
        }
    except FileNotFoundError:
        return {"live_sha": "dev", "deployed_at": "not deployed", "source": "version_json_missing"}
    except Exception as exc:
        log.warning("deploy_status: version.json read error: %s", exc)
        return {"live_sha": "unknown", "deployed_at": "unknown", "source": "version_json_error"}



# ── TASK_STATE.md parser ──────────────────────────────────────────────────────

_STATUS_RE   = re.compile(r'\*\*(CLOSED|OPEN)\*\*\s*[—–-]\s*SHA\s*`([^`]+)`', re.IGNORECASE)
_PR_ROW_RE   = re.compile(r'^\|\s*#(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|', re.MULTILINE)
_GATE_ROW_RE = re.compile(r'^\|\s*([^|#][^|]+?)\s*\|\s*([^|]+?)\s*\|', re.MULTILINE)
_GATE2_RE    = re.compile(r'GATE\s*2\s*=\s*(\d+)\s*impl\s*PR', re.IGNORECASE)


def _classify_pr_type(raw_type: str) -> str:
    t = raw_type.strip().lower()
    if "impl" in t:
        return "impl"
    if any(k in t for k in ("governance", "ci", "script", "docs", "draft")):
        return "governance"
    return t


def _parse_task_state_md(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}

    # Deployment status + SHA from markdown
    m = _STATUS_RE.search(text)
    if m:
        result["deployment_status"] = m.group(1).upper()
        result["task_state_sha"]    = m.group(2)

    # GATE 2 impl count (authoritative line from markdown)
    g2 = _GATE2_RE.search(text)
    if g2:
        result["open_impl_pr_count"] = int(g2.group(1))

    # PR table rows
    impl_prs:       list[dict] = []
    governance_prs: list[dict] = []

    for m2 in _PR_ROW_RE.finditer(text):
        number    = int(m2.group(1))
        title     = m2.group(2).strip()
        raw_type  = m2.group(3).strip()

        # Skip header rows and separator rows
        if title.lower() in ("title", "---") or raw_type.lower() in ("type", "---"):
            continue

        pr_type = _classify_pr_type(raw_type)
        entry = {"number": number, "title": title, "type": pr_type, "notes": raw_type}

        if pr_type == "impl":
            impl_prs.append(entry)
        else:
            governance_prs.append(entry)

    if impl_prs or governance_prs:
        result["open_impl_prs"]       = impl_prs
        result["open_governance_prs"] = governance_prs
        # Use parsed list count as fallback if explicit line wasn't found
        if "open_impl_pr_count" not in result:
            result["open_impl_pr_count"] = len(impl_prs)

    # Verification gate rows (the DEPLOYMENT STATUS gate table)
    # Look for the section between "| Gate |" header and the next empty line
    gate_section = re.search(
        r'\|\s*Gate\s*\|\s*Result\s*\|(.*?)(?:\n\n|\Z)', text, re.DOTALL | re.IGNORECASE
    )
    if gate_section:
        gates: dict[str, str] = {}
        for gm in _GATE_ROW_RE.finditer(gate_section.group(1)):
            key = gm.group(1).strip().lower().replace(" ", "_").replace("/", "_")
            val = gm.group(2).strip()
            if key and val and key != "gate" and key != "---":
                gates[key] = val
        if gates:
            result["verification_gates"] = gates

    return result


def _read_task_state_md() -> tuple[dict[str, Any], list[str]]:
    """Return (parsed_data, warnings)."""
    md_path_str: str = getattr(settings, "deploy_state_md_path", "") or ""
    if not md_path_str:
        return {}, ["DEPLOY_STATE_MD_PATH not configured — PR queue and gate data unavailable"]

    md_path = Path(md_path_str)
    if not md_path.exists():
        return {}, [f"deploy_state_md_path file not found: {md_path}"]

    try:
        text   = md_path.read_text(encoding="utf-8")
        parsed = _parse_task_state_md(text)
        return parsed, []
    except Exception as exc:
        log.warning("deploy_status: TASK_STATE.md read error: %s", exc)
        return {}, [f"TASK_STATE.md parse error: {exc}"]


# ── Public API ────────────────────────────────────────────────────────────────

_GATE2_IMPL_LIMIT = 3


def read_deploy_status() -> dict[str, Any]:
    """
    Return a merged deployment status dict. Never raises — returns warnings
    instead of failing so the endpoint is always reachable.
    """
    warnings: list[str] = []

    version = _read_version_json()
    md_data, md_warnings = _read_task_state_md()
    warnings.extend(md_warnings)

    impl_count = md_data.get("open_impl_pr_count", None)
    gate2_blocked = (impl_count is not None and impl_count > _GATE2_IMPL_LIMIT)

    return {
        # Primary deploy identity (from version.json)
        "live_sha":            version["live_sha"],
        "deployed_at":         version["deployed_at"],
        # Task-state enrichment (from TASK_STATE.md)
        "deployment_status":   md_data.get("deployment_status"),        # "CLOSED" | "OPEN" | null
        "task_state_sha":      md_data.get("task_state_sha"),           # SHA recorded in TASK_STATE
        "verification_gates":  md_data.get("verification_gates", {}),
        "open_impl_prs":       md_data.get("open_impl_prs", []),
        "open_governance_prs": md_data.get("open_governance_prs", []),
        "open_impl_pr_count":  impl_count,
        # GATE 2 interpretation
        "gate_2_limit":        _GATE2_IMPL_LIMIT,
        "gate_2_blocked":      gate2_blocked,
        # Provenance
        "data_sources": {
            "version_json":  version["source"] == "version_json",
            "task_state_md": bool(md_data),
        },
        "warnings": warnings,
    }
