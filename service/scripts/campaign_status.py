"""
campaign_status.py — CLI for the file-based campaign tracker.

State file:    tasks/campaign-state.json
Schema doc:    tasks/campaign-runner.md
Smoke reports: tasks/smoke-reports/

Usage:
  python service/scripts/campaign_status.py list
  python service/scripts/campaign_status.py show MDC-2026-05
  python service/scripts/campaign_status.py show MDC-2026-05 --batch B9
  python service/scripts/campaign_status.py update MDC-2026-05 B9 --status merged \\
         --pr 106 --sha e166c0e
  python service/scripts/campaign_status.py block  MDC-2026-05 B3 \\
         --reason "security contract relaxation needed"
  python service/scripts/campaign_status.py unblock MDC-2026-05 B3
  python service/scripts/campaign_status.py smoke  MDC-2026-05 B9 \\
         --report tasks/smoke-reports/2026-05-16-carriers-config.md
  python service/scripts/campaign_status.py export MDC-2026-05  # markdown

No HTTP, no service touch, no DB. Pure JSON read/write. The CLI is safe to
run from any directory; the state file is resolved relative to the repo root.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


VALID_STATUSES = (
    "planned", "active", "pr_open", "merged",
    "deployed", "smoked", "blocked",
)


# ── State file resolution ────────────────────────────────────────────────────

def _find_repo_root(start: Path) -> Path:
    """Walk up looking for tasks/campaign-state.json. Falls back to the parent
    of this script's directory."""
    p = start.resolve()
    for _ in range(8):
        if (p / "tasks" / "campaign-state.json").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    # Default to repo root inferred from this script's location.
    return Path(__file__).resolve().parents[2]


def _state_path(repo_root: Optional[Path] = None) -> Path:
    root = repo_root or _find_repo_root(Path.cwd())
    return root / "tasks" / "campaign-state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── Core IO ──────────────────────────────────────────────────────────────────

def load_state(state_file: Optional[Path] = None) -> Dict[str, Any]:
    sp = state_file or _state_path()
    if not sp.exists():
        return {"schema_version": 1, "campaigns": []}
    return json.loads(sp.read_text(encoding="utf-8"))


def save_state(state: Dict[str, Any], state_file: Optional[Path] = None) -> None:
    sp = state_file or _state_path()
    sp.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write
    tmp = sp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    tmp.replace(sp)


def _get_campaign(state: Dict[str, Any], cid: str) -> Dict[str, Any]:
    for c in state.get("campaigns", []):
        if c.get("campaign_id") == cid:
            return c
    raise KeyError(f"Campaign not found: {cid}")


def _get_batch(campaign: Dict[str, Any], bid: str) -> Dict[str, Any]:
    for b in campaign.get("batches", []):
        if b.get("batch_id") == bid:
            return b
    raise KeyError(f"Batch not found in {campaign['campaign_id']}: {bid}")


# ── Mutations ────────────────────────────────────────────────────────────────

def create_campaign(state: Dict[str, Any], campaign_id: str, title: str) -> Dict[str, Any]:
    if any(c["campaign_id"] == campaign_id for c in state.get("campaigns", [])):
        raise ValueError(f"Campaign already exists: {campaign_id}")
    new = {
        "campaign_id": campaign_id, "title": title, "status": "active",
        "started_at": _now_iso(), "closed_at": None, "batches": [],
    }
    state.setdefault("campaigns", []).append(new)
    return new


def add_batch(state: Dict[str, Any], campaign_id: str, batch_id: str, title: str) -> Dict[str, Any]:
    c = _get_campaign(state, campaign_id)
    if any(b["batch_id"] == batch_id for b in c.get("batches", [])):
        raise ValueError(f"Batch already exists: {batch_id}")
    new = {"batch_id": batch_id, "title": title, "status": "planned",
           "pr_url": None, "next_batch": None, "block_reason": None}
    c.setdefault("batches", []).append(new)
    return new


def update_batch(state: Dict[str, Any], campaign_id: str, batch_id: str,
                 status: Optional[str] = None, pr_url: Optional[str] = None,
                 pr_number: Optional[int] = None, merge_sha: Optional[str] = None,
                 deployed_sha: Optional[str] = None,
                 tests: Optional[Dict[str, str]] = None,
                 smoke_report: Optional[str] = None,
                 next_batch: Optional[str] = None) -> Dict[str, Any]:
    c = _get_campaign(state, campaign_id)
    b = _get_batch(c, batch_id)
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status!r}. Must be one of {VALID_STATUSES}")
        b["status"] = status
        if status == "deployed":
            b.setdefault("deployed_at", _now_iso())
    if pr_url is not None:
        b["pr_url"] = pr_url
    if pr_number is not None:
        b["pr_number"] = pr_number
    if merge_sha is not None:
        b["merge_sha"] = merge_sha
    if deployed_sha is not None:
        b["deployed_sha"] = deployed_sha
    if tests is not None:
        b.setdefault("tests", {}).update(tests)
    if smoke_report is not None:
        b["smoke_report"] = smoke_report
    if next_batch is not None:
        b["next_batch"] = next_batch
    return b


def block_batch(state: Dict[str, Any], campaign_id: str, batch_id: str,
                reason: str) -> Dict[str, Any]:
    if not reason:
        raise ValueError("block reason is required")
    c = _get_campaign(state, campaign_id)
    b = _get_batch(c, batch_id)
    b["status"] = "blocked"
    b["block_reason"] = reason
    return b


def unblock_batch(state: Dict[str, Any], campaign_id: str, batch_id: str,
                  resume_status: str = "planned") -> Dict[str, Any]:
    if resume_status not in VALID_STATUSES or resume_status == "blocked":
        raise ValueError(f"Cannot resume to {resume_status!r}")
    c = _get_campaign(state, campaign_id)
    b = _get_batch(c, batch_id)
    b["status"] = resume_status
    b["block_reason"] = None
    return b


def attach_smoke(state: Dict[str, Any], campaign_id: str, batch_id: str,
                 report_path: str, *, verify_exists: bool = True) -> Dict[str, Any]:
    c = _get_campaign(state, campaign_id)
    b = _get_batch(c, batch_id)
    if verify_exists:
        # Resolve relative to repo root
        rp = Path(report_path)
        if not rp.is_absolute():
            rp = _find_repo_root(Path.cwd()) / rp
        if not rp.exists():
            raise FileNotFoundError(f"Smoke report not found: {rp}")
    b["smoke_report"] = report_path
    b["status"] = "smoked"
    return b


# ── P3 hardening: deploy + stack metadata ────────────────────────────────────

def record_deploy(state: Dict[str, Any], campaign_id: str, batch_id: str, *,
                  deployed_sha: str, previous_main_sha: Optional[str] = None,
                  robocopy_exit_codes: Optional[List[int]] = None,
                  restart_seconds: Optional[int] = None,
                  rollback_command: Optional[str] = None) -> Dict[str, Any]:
    """Record a deploy event with full audit metadata. Sets status=deployed
    and stamps deployed_at automatically."""
    c = _get_campaign(state, campaign_id)
    b = _get_batch(c, batch_id)
    if not deployed_sha:
        raise ValueError("deployed_sha is required")
    b["status"] = "deployed"
    b["deployed_sha"] = deployed_sha
    b["deployed_at"] = _now_iso()
    if previous_main_sha is not None:
        b["previous_main_sha"] = previous_main_sha
    if rollback_command is not None:
        b["rollback_command"] = rollback_command
    elif previous_main_sha is not None:
        b["rollback_command"] = f"git revert -m 1 {deployed_sha[:7]} --no-edit"
    # Deploy metadata sub-object
    meta = b.setdefault("deploy_metadata", {})
    if robocopy_exit_codes is not None:
        meta["robocopy_exit_codes"] = list(robocopy_exit_codes)
        # robocopy exit codes 0-3 are success; 4+ are errors
        meta["robocopy_ok"] = all(0 <= c <= 3 for c in robocopy_exit_codes)
    if restart_seconds is not None:
        meta["restart_seconds"] = int(restart_seconds)
    return b


def record_branch_stack(state: Dict[str, Any], campaign_id: str, batch_id: str, *,
                        base_branch: str,
                        stack_depth: int = 0,
                        stacked_on: Optional[str] = None) -> Dict[str, Any]:
    """Record branch-stack metadata so stack-into-stack misroutes are
    detectable from the state file alone."""
    if stack_depth < 0:
        raise ValueError("stack_depth must be >= 0")
    if stack_depth > 0 and not stacked_on:
        raise ValueError("stacked_on is required when stack_depth > 0")
    c = _get_campaign(state, campaign_id)
    b = _get_batch(c, batch_id)
    stack = b.setdefault("branch_stack", {})
    stack["base_branch"] = base_branch
    stack["stack_depth"] = int(stack_depth)
    if stacked_on:
        stack["stacked_on"] = stacked_on
    if stack_depth > 0 and base_branch == "main":
        stack["warning"] = (
            "stack_depth > 0 but base_branch is 'main' — verify the base "
            "was retargeted before merge, or plan a forward-merge PR."
        )
    return b


# ── P3 hardening: summary dashboard ──────────────────────────────────────────

def _state_summary(state: Dict[str, Any]) -> str:
    """Render a top-level operator dashboard: open PRs, next batch per
    active campaign, blocked items, recent deploys."""
    lines: List[str] = []
    lines.append("=" * 78)
    lines.append("CAMPAIGN STATUS — OPERATOR DASHBOARD")
    lines.append("=" * 78)

    active = [c for c in state.get("campaigns", []) if c.get("status") == "active"]
    completed = [c for c in state.get("campaigns", []) if c.get("status") == "completed"]

    lines.append(f"\nActive campaigns:    {len(active)}")
    for c in active:
        next_b = next((b for b in c["batches"] if b["status"] in ("planned", "active", "pr_open")), None)
        lines.append(f"  {c['campaign_id']:<24}  next: {next_b['batch_id'] if next_b else '—'}  ({next_b['title'] if next_b else 'no next batch'})")

    lines.append(f"\nCompleted campaigns: {len(completed)}")
    for c in completed:
        lines.append(f"  {c['campaign_id']:<24}  {len(c['batches'])} batches  closed {c.get('closed_at', '—')[:10]}")

    # Open PRs
    open_prs: List[Dict[str, Any]] = []
    for c in state.get("campaigns", []):
        for b in c.get("batches", []):
            if b.get("status") == "pr_open" and b.get("pr_url"):
                open_prs.append({"c": c["campaign_id"], "b": b["batch_id"], "url": b["pr_url"]})
    lines.append(f"\nOpen PRs: {len(open_prs)}")
    for p in open_prs:
        lines.append(f"  {p['c']}/{p['b']}: {p['url']}")

    # Blocked items
    blocked: List[Dict[str, Any]] = []
    for c in state.get("campaigns", []):
        for b in c.get("batches", []):
            if b.get("status") == "blocked":
                blocked.append({"c": c["campaign_id"], "b": b["batch_id"],
                                "title": b.get("title", ""),
                                "reason": (b.get("block_reason") or "")[:80]})
    lines.append(f"\nBlocked items: {len(blocked)}")
    for x in blocked:
        lines.append(f"  {x['c']}/{x['b']}: {x['title']}")
        lines.append(f"      reason: {x['reason']}...")

    # Recent deploys (last 5 by deployed_at across all campaigns)
    deploys: List[Dict[str, Any]] = []
    for c in state.get("campaigns", []):
        for b in c.get("batches", []):
            if b.get("deployed_at"):
                deploys.append({"c": c["campaign_id"], "b": b["batch_id"],
                                "at": b["deployed_at"],
                                "sha": (b.get("deployed_sha") or "")[:8],
                                "robocopy_ok": (b.get("deploy_metadata") or {}).get("robocopy_ok")})
    deploys.sort(key=lambda d: d["at"], reverse=True)
    lines.append(f"\nRecent deploys (most recent first):")
    for d in deploys[:5]:
        ok_marker = ""
        if d["robocopy_ok"] is True:
            ok_marker = " [robocopy ok]"
        elif d["robocopy_ok"] is False:
            ok_marker = " [ROBOCOPY ERRORS]"
        lines.append(f"  {d['at'][:19]}  {d['sha']}  {d['c']}/{d['b']}{ok_marker}")

    lines.append("\n" + "=" * 78)
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# v2 RUNNER — Queue + Gates + Failure Recovery
#
# Pure-function additions. No background process, no auto-merge, no auto-deploy.
# Every function is a read or a labelled mutation; the operator is the executor.
# ══════════════════════════════════════════════════════════════════════════════

# ── Status semantics for queue/gate logic ────────────────────────────────────

#: Statuses where the batch is "open" (operator still has work to do)
OPEN_STATUSES = ("planned", "active", "pr_open", "merged", "deployed")

#: Statuses where the batch is "done" (no further action needed by current rules)
DONE_STATUSES = ("smoked",)

#: Statuses that block forward progress on dependents
BLOCKING_STATUSES = ("blocked",)


# ── Phase 1: Queue model + dependency graph ─────────────────────────────────

def batch_dependencies(batch: Dict[str, Any]) -> List[str]:
    """Return the list of batch ids this batch depends on.

    Two sources:
      1. Explicit: ``batch["depends_on"]`` (list)
      2. Implicit: any preceding batch in the same campaign whose
         ``next_batch`` points at this batch.
    """
    deps = list(batch.get("depends_on", []) or [])
    return deps


def compute_dependency_graph(campaign: Dict[str, Any]) -> Dict[str, List[str]]:
    """Build an adjacency map: batch_id → list of batch_ids that depend on it.

    Forward edges. Useful for "what unblocks when B5 lands?" queries."""
    forward: Dict[str, List[str]] = {b["batch_id"]: [] for b in campaign.get("batches", [])}
    by_id = {b["batch_id"]: b for b in campaign.get("batches", [])}

    # Explicit depends_on
    for b in campaign.get("batches", []):
        for dep in batch_dependencies(b):
            if dep in forward:
                forward[dep].append(b["batch_id"])

    # Implicit: next_batch chains
    for b in campaign.get("batches", []):
        nb = b.get("next_batch")
        if nb and nb in by_id:
            if b["batch_id"] not in forward.get(b["batch_id"], []):
                # Mark "next_batch" as soft dependency (only if not already there)
                if b["batch_id"] not in forward[nb]:
                    forward.setdefault(nb, [])
                # Direction: nb depends on b (b must finish before nb can start)
                if b["batch_id"] not in [dep for dep in forward.get(b["batch_id"], [])]:
                    pass
    return forward


def batch_is_ready(state: Dict[str, Any], campaign_id: str, batch: Dict[str, Any]) -> bool:
    """A batch is ready to start when:
       - its own status is in OPEN_STATUSES (not blocked, not smoked)
       - all explicit `depends_on` batches are in DONE_STATUSES
       - the immediate `next_batch` predecessor (if any) is in DONE_STATUSES
    """
    if batch.get("status") not in OPEN_STATUSES:
        return False
    c = _get_campaign(state, campaign_id)
    by_id = {b["batch_id"]: b for b in c.get("batches", [])}
    # Explicit deps
    for dep in batch_dependencies(batch):
        d = by_id.get(dep)
        if d is None:
            return False  # unknown dep — cannot verify
        if d.get("status") not in DONE_STATUSES:
            return False
    # Implicit predecessor via next_batch
    for b in c.get("batches", []):
        if b.get("next_batch") == batch["batch_id"]:
            if b.get("status") not in DONE_STATUSES + ("merged", "deployed"):
                return False
    return True


def next_recommended_batch(state: Dict[str, Any], campaign_id: str) -> Optional[Dict[str, Any]]:
    """Return the first batch (in declaration order) that is `batch_is_ready`."""
    c = _get_campaign(state, campaign_id)
    for b in c.get("batches", []):
        if batch_is_ready(state, campaign_id, b) and b.get("status") in ("planned", "active"):
            return b
    return None


def list_blockers(state: Dict[str, Any], campaign_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all blocked batches and stuck items (open with all-done deps)
    so the operator sees what's parked vs what's ready."""
    out: List[Dict[str, Any]] = []
    campaigns = state.get("campaigns", [])
    if campaign_id:
        campaigns = [_get_campaign(state, campaign_id)]
    for c in campaigns:
        for b in c.get("batches", []):
            if b.get("status") == "blocked":
                out.append({"campaign_id": c["campaign_id"],
                            "batch_id":    b["batch_id"],
                            "title":       b.get("title", ""),
                            "reason":      b.get("block_reason") or ""})
    return out


# ── Phase 2: Stuck-batch detection ───────────────────────────────────────────

def detect_stuck_batches(state: Dict[str, Any], *,
                          pr_open_seconds: int = 86400 * 3,
                          merged_no_deploy_seconds: int = 86400 * 1,
                          deployed_no_smoke_seconds: int = 86400 * 1
                          ) -> List[Dict[str, Any]]:
    """Find batches that have lingered in a transitional status too long.

    Defaults:
      - pr_open: more than 3 days open without merge.
      - merged but no deploy: 1 day without deploy.
      - deployed but no smoke: 1 day without smoke report attached.
    """
    out: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    def _age_seconds(iso_str: Optional[str]) -> Optional[int]:
        if not iso_str:
            return None
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        except Exception:
            return None
        return int((now - dt).total_seconds())

    for c in state.get("campaigns", []):
        for b in c.get("batches", []):
            st = b.get("status")
            if st == "pr_open":
                age = _age_seconds(b.get("opened_at"))
                if age is not None and age > pr_open_seconds:
                    out.append({"campaign_id": c["campaign_id"],
                                "batch_id":    b["batch_id"],
                                "reason":      f"pr_open for {age}s",
                                "threshold":   pr_open_seconds})
            elif st == "merged":
                age = _age_seconds(b.get("merged_at") or b.get("deployed_at"))
                if age is not None and age > merged_no_deploy_seconds:
                    out.append({"campaign_id": c["campaign_id"],
                                "batch_id":    b["batch_id"],
                                "reason":      f"merged but not deployed for {age}s",
                                "threshold":   merged_no_deploy_seconds})
            elif st == "deployed":
                age = _age_seconds(b.get("deployed_at"))
                if (age is not None and age > deployed_no_smoke_seconds
                        and not b.get("smoke_report")):
                    out.append({"campaign_id": c["campaign_id"],
                                "batch_id":    b["batch_id"],
                                "reason":      f"deployed but no smoke for {age}s",
                                "threshold":   deployed_no_smoke_seconds})
    return out


# ── Phase 3: Gate engine ────────────────────────────────────────────────────

def verification_gates(batch: Dict[str, Any]) -> Dict[str, bool]:
    """Return a map of gate-name → satisfied for this batch.

    Gates (all must pass before a batch transitions to `smoked`):
      tests_recorded:     batch has at least one `tests` entry
      pz_regression_ok:   `tests.pz_regression == "160/160"` (the canonical gate)
      pr_present:         `pr_url` is set
      merge_recorded:     `merge_sha` is set
      deploy_recorded:    `deployed_sha` is set
      smoke_report_set:   `smoke_report` is non-null
      no_block:           batch is not in BLOCKING_STATUSES
      stack_safe:         branch_stack metadata absent OR has no warning
    """
    tests = batch.get("tests") or {}
    stack = batch.get("branch_stack") or {}
    return {
        "tests_recorded":     bool(tests),
        "pz_regression_ok":   tests.get("pz_regression") == "160/160",
        "pr_present":         bool(batch.get("pr_url")),
        "merge_recorded":     bool(batch.get("merge_sha")),
        "deploy_recorded":    bool(batch.get("deployed_sha")),
        "smoke_report_set":   bool(batch.get("smoke_report")),
        "no_block":           batch.get("status") not in BLOCKING_STATUSES,
        "stack_safe":         not stack.get("warning"),
    }


def verify_batch(state: Dict[str, Any], campaign_id: str, batch_id: str,
                 *, required: Optional[List[str]] = None
                 ) -> Dict[str, Any]:
    """Return a verification report. `required` defaults to a sensible subset
    depending on the batch's current status — operator can override.

    The report is a dict: {ok: bool, gates: {name: bool}, missing: [name]}.
    """
    c = _get_campaign(state, campaign_id)
    b = _get_batch(c, batch_id)
    gates = verification_gates(b)
    if required is None:
        st = b.get("status")
        if st in ("smoked",):
            required = list(gates.keys())
        elif st in ("deployed",):
            required = ["tests_recorded", "pz_regression_ok", "pr_present",
                        "merge_recorded", "deploy_recorded", "no_block", "stack_safe"]
        elif st in ("merged",):
            required = ["tests_recorded", "pz_regression_ok", "pr_present",
                        "merge_recorded", "no_block", "stack_safe"]
        else:
            required = ["no_block", "stack_safe"]
    missing = [g for g in required if not gates.get(g)]
    return {"campaign_id": campaign_id, "batch_id": batch_id,
            "status": b.get("status"), "gates": gates,
            "required": required, "missing": missing, "ok": not missing}


def detect_branch_stack_misroutes(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Find batches where `branch_stack.warning` is set (stack-into-stack)."""
    out: List[Dict[str, Any]] = []
    for c in state.get("campaigns", []):
        for b in c.get("batches", []):
            stack = b.get("branch_stack") or {}
            if stack.get("warning"):
                out.append({"campaign_id": c["campaign_id"],
                            "batch_id":    b["batch_id"],
                            "warning":     stack["warning"],
                            "base_branch": stack.get("base_branch"),
                            "stack_depth": stack.get("stack_depth")})
    return out


# ── Phase 5: Failure recovery + rollback ────────────────────────────────────

def rollback_plan(batch: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a mechanical rollback plan for a deployed batch."""
    if not batch.get("deployed_sha"):
        return {"ok": False, "reason": "no deployed_sha recorded"}
    if not batch.get("previous_main_sha"):
        return {
            "ok": False,
            "reason": "no previous_main_sha recorded; rollback requires manual SHA lookup",
            "fallback_command": batch.get("rollback_command")
                                or f"git revert -m 1 {batch['deployed_sha'][:7]} --no-edit",
        }
    return {
        "ok": True,
        "previous_sha": batch["previous_main_sha"],
        "command": batch.get("rollback_command")
                   or f"git revert -m 1 {batch['deployed_sha'][:7]} --no-edit",
        "deployed_sha": batch["deployed_sha"],
        "notes": "After revert, re-run robocopy of changed runtime files and restart PZService.",
    }


def detect_interrupted_campaigns(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A campaign is 'interrupted' if it has status='active' but every batch
    is either smoked, blocked, or has no open work."""
    out: List[Dict[str, Any]] = []
    for c in state.get("campaigns", []):
        if c.get("status") != "active":
            continue
        has_open = any(b.get("status") in OPEN_STATUSES + ("blocked",)
                       and b.get("status") not in DONE_STATUSES
                       for b in c.get("batches", []))
        ready = next_recommended_batch(state, c["campaign_id"])
        if not has_open or (ready is None and all(
                b.get("status") in DONE_STATUSES + BLOCKING_STATUSES
                for b in c.get("batches", []))):
            out.append({"campaign_id": c["campaign_id"],
                        "title": c.get("title"),
                        "reason": "no open work; all batches are smoked or blocked",
                        "next_recommended": None})
    return out


# ── Phase 7: Operator dashboard markdown ────────────────────────────────────

def render_dashboard(state: Dict[str, Any]) -> str:
    """Full operator-facing dashboard. Self-contained; suitable for paste
    into a PR description or saved as a status file."""
    lines: List[str] = []
    lines.append("# Campaign Runner — Operator Dashboard")
    lines.append("")
    lines.append(f"Generated: {_now_iso()}")
    lines.append("")
    # Active vs completed
    active = [c for c in state.get("campaigns", []) if c.get("status") == "active"]
    completed = [c for c in state.get("campaigns", []) if c.get("status") == "completed"]
    lines.append(f"**Active campaigns:** {len(active)}  ·  **Completed:** {len(completed)}")
    lines.append("")
    # Next-recommended
    lines.append("## Next recommended batch per active campaign")
    if not active:
        lines.append("_(none active)_")
    for c in active:
        nb = next_recommended_batch(state, c["campaign_id"])
        if nb:
            lines.append(f"- **{c['campaign_id']} / {nb['batch_id']}** — {nb.get('title','')} (status: {nb['status']})")
        else:
            lines.append(f"- {c['campaign_id']}: no batch ready (all done or blocked)")
    lines.append("")
    # Blockers
    bl = list_blockers(state)
    lines.append(f"## Blockers ({len(bl)})")
    for x in bl:
        lines.append(f"- **{x['campaign_id']} / {x['batch_id']}**: {x['title']}")
        lines.append(f"  - reason: {x['reason'][:120]}")
    lines.append("")
    # Stuck batches
    stuck = detect_stuck_batches(state)
    lines.append(f"## Stuck batches ({len(stuck)})")
    if not stuck:
        lines.append("_(none)_")
    for s in stuck:
        lines.append(f"- {s['campaign_id']} / {s['batch_id']}: {s['reason']}")
    lines.append("")
    # Branch stack risks
    risks = detect_branch_stack_misroutes(state)
    lines.append(f"## Branch-stack risks ({len(risks)})")
    if not risks:
        lines.append("_(none)_")
    for r in risks:
        lines.append(f"- {r['campaign_id']} / {r['batch_id']}: {r['warning']}")
    lines.append("")
    # Interrupted campaigns
    interrupted = detect_interrupted_campaigns(state)
    if interrupted:
        lines.append("## Interrupted campaigns")
        for i in interrupted:
            lines.append(f"- {i['campaign_id']}: {i['reason']}")
        lines.append("")
    # Recent deploys
    deploys: List[Dict[str, Any]] = []
    for c in state.get("campaigns", []):
        for b in c.get("batches", []):
            if b.get("deployed_at"):
                deploys.append({
                    "campaign_id": c["campaign_id"], "batch_id": b["batch_id"],
                    "at": b["deployed_at"], "sha": (b.get("deployed_sha") or "")[:8],
                    "ok": (b.get("deploy_metadata") or {}).get("robocopy_ok"),
                })
    deploys.sort(key=lambda d: d["at"], reverse=True)
    lines.append("## Recent deploys")
    for d in deploys[:5]:
        marker = ""
        if d["ok"] is True: marker = " ✅"
        elif d["ok"] is False: marker = " ⚠️ robocopy errors"
        lines.append(f"- `{d['at'][:19]}`  {d['sha']}  {d['campaign_id']} / {d['batch_id']}{marker}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ── Phase 4: CLI subcommand handlers ────────────────────────────────────────

def _cmd_queue(args: argparse.Namespace) -> int:
    state = load_state()
    campaigns = state.get("campaigns", [])
    if args.campaign_id:
        campaigns = [_get_campaign(state, args.campaign_id)]
    for c in campaigns:
        print(f"\n== {c['campaign_id']} ({c.get('status', 'unknown')}) -- {c.get('title','')}")
        for b in c.get("batches", []):
            ready = "x" if batch_is_ready(state, c["campaign_id"], b) else " "
            deps = ", ".join(batch_dependencies(b)) or "-"
            print(f"  [{ready}] {b['batch_id']:<28} {b['status']:<10}  deps: {deps}")
    return 0


def _cmd_next(args: argparse.Namespace) -> int:
    state = load_state()
    nb = next_recommended_batch(state, args.campaign_id)
    if nb is None:
        print(f"No ready batch for {args.campaign_id}.")
        return 1
    print(json.dumps(nb, indent=2))
    return 0


def _cmd_blockers(args: argparse.Namespace) -> int:
    state = load_state()
    out = list_blockers(state, args.campaign_id)
    if not out:
        print("No blocked batches.")
        return 0
    for x in out:
        print(f"{x['campaign_id']} / {x['batch_id']}: {x['title']}")
        print(f"  reason: {x['reason']}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    state = load_state()
    rep = verify_batch(state, args.campaign_id, args.batch,
                       required=args.gate.split(",") if args.gate else None)
    print(json.dumps(rep, indent=2))
    return 0 if rep["ok"] else 1


def _cmd_graph(args: argparse.Namespace) -> int:
    state = load_state()
    c = _get_campaign(state, args.campaign_id)
    graph = compute_dependency_graph(c)
    print(f"# Dependency graph for {c['campaign_id']}")
    for src, dests in graph.items():
        if dests:
            print(f"{src} -> {', '.join(dests)}")
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    state = load_state()
    nb = next_recommended_batch(state, args.campaign_id)
    if nb is None:
        print(f"No ready batch to resume in {args.campaign_id}.")
        return 1
    print(f"# Resume point for {args.campaign_id}")
    print(f"Batch: {nb['batch_id']}  ({nb.get('title','')})")
    print(f"Status: {nb['status']}")
    print(f"Next action: {_next_action_hint(nb)}")
    return 0


def _next_action_hint(b: Dict[str, Any]) -> str:
    st = b.get("status")
    if st == "planned":   return "create branch + implement; then `update --status active`"
    if st == "active":    return "open PR; then `update --status pr_open --pr <n>`"
    if st == "pr_open":   return "merge PR; then `update --status merged --sha <merge>`"
    if st == "merged":    return "deploy + restart; then `deploy --sha <sha> --previous-main-sha <prev>`"
    if st == "deployed":  return "run smoke; then `smoke --report <path>`"
    if st == "smoked":    return "batch is done; move to next"
    return "unknown status"


def _cmd_pause(args: argparse.Namespace) -> int:
    """Soft-pause: mark a batch as blocked with an operator reason. Identical
    to `block`, kept as a separate verb for operator clarity."""
    return _cmd_block(args)


def _cmd_retry(args: argparse.Namespace) -> int:
    """Reset a batch to `planned` status, clearing block_reason but keeping
    all other audit fields (merge_sha, pr_url, etc.) — useful when a batch
    failed and operator wants to start over."""
    state = load_state()
    c = _get_campaign(state, args.campaign_id)
    b = _get_batch(c, args.batch)
    b["status"] = "planned"
    b["block_reason"] = None
    b.setdefault("retries", 0)
    b["retries"] += 1
    save_state(state)
    print(f"{args.campaign_id} / {args.batch}: reset to 'planned' (retry #{b['retries']})")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Health check: surface every anomaly the runner can detect."""
    state = load_state()
    problems = []
    # Stuck batches
    for s in detect_stuck_batches(state):
        problems.append(("stuck", s))
    # Branch-stack risks
    for r in detect_branch_stack_misroutes(state):
        problems.append(("stack", r))
    # Interrupted campaigns
    for i in detect_interrupted_campaigns(state):
        problems.append(("interrupted", i))
    # Schema sanity
    if state.get("schema_version") != 1:
        problems.append(("schema", {"version": state.get("schema_version")}))
    if not problems:
        print("doctor: no issues found.")
        return 0
    print(f"doctor: {len(problems)} issue(s) found:")
    for kind, p in problems:
        print(f"  [{kind}] {json.dumps(p)}")
    return 1


def _cmd_dashboard(args: argparse.Namespace) -> int:
    state = load_state()
    print(render_dashboard(state))
    return 0


# ── Export ───────────────────────────────────────────────────────────────────

def export_markdown(state: Dict[str, Any], campaign_id: str) -> str:
    c = _get_campaign(state, campaign_id)
    lines = [
        f"# Campaign: {c['title']}  [{c['campaign_id']}]",
        f"Status: **{c['status']}**",
        f"Started: {c.get('started_at') or '—'}",
        f"Closed:  {c.get('closed_at')  or '—'}",
        "",
        "| Batch | Title | Status | PR | Merge SHA | Deployed SHA | Tests | Smoke | Block reason |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for b in c.get("batches", []):
        pr = f"#{b['pr_number']}" if b.get("pr_number") else (b.get("pr_url") or "—")
        ms = (b.get("merge_sha") or "—")[:8]
        ds = (b.get("deployed_sha") or "—")[:8]
        tests = b.get("tests") or {}
        tests_str = " · ".join(f"{k}: {v}" for k, v in tests.items()) or "—"
        smoke = b.get("smoke_report") or "—"
        block = b.get("block_reason") or ""
        lines.append(
            f"| {b['batch_id']} | {b['title']} | {b['status']} | {pr} | {ms} | {ds} | "
            f"{tests_str} | {smoke} | {block} |"
        )
    return "\n".join(lines) + "\n"


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_list(args: argparse.Namespace) -> int:
    state = load_state()
    print(f"{'CAMPAIGN':<24} {'STATUS':<12} {'BATCHES':<8} {'TITLE'}")
    for c in state.get("campaigns", []):
        n = len(c.get("batches", []))
        print(f"{c['campaign_id']:<24} {c['status']:<12} {n:<8} {c['title']}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    state = load_state()
    c = _get_campaign(state, args.campaign_id)
    if args.batch:
        b = _get_batch(c, args.batch)
        print(json.dumps(b, indent=2))
    else:
        print(json.dumps(c, indent=2))
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    state = load_state()
    update_batch(state, args.campaign_id, args.batch,
                 status=args.status, pr_url=args.pr_url,
                 pr_number=args.pr, merge_sha=args.sha,
                 deployed_sha=args.deployed_sha, next_batch=args.next_batch)
    save_state(state)
    return 0


def _cmd_block(args: argparse.Namespace) -> int:
    state = load_state()
    block_batch(state, args.campaign_id, args.batch, args.reason)
    save_state(state)
    return 0


def _cmd_unblock(args: argparse.Namespace) -> int:
    state = load_state()
    unblock_batch(state, args.campaign_id, args.batch, args.status)
    save_state(state)
    return 0


def _cmd_smoke(args: argparse.Namespace) -> int:
    state = load_state()
    attach_smoke(state, args.campaign_id, args.batch, args.report,
                 verify_exists=not args.skip_exists_check)
    save_state(state)
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    state = load_state()
    print(export_markdown(state, args.campaign_id))
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    state = load_state()
    print(_state_summary(state))
    return 0


def _cmd_deploy(args: argparse.Namespace) -> int:
    state = load_state()
    codes = None
    if args.robocopy_exit_codes:
        codes = [int(c) for c in args.robocopy_exit_codes.split(",")]
    record_deploy(state, args.campaign_id, args.batch,
                  deployed_sha=args.sha,
                  previous_main_sha=args.previous_main_sha,
                  robocopy_exit_codes=codes,
                  restart_seconds=args.restart_seconds,
                  rollback_command=args.rollback_command)
    save_state(state)
    return 0


def _cmd_stack(args: argparse.Namespace) -> int:
    state = load_state()
    record_branch_stack(state, args.campaign_id, args.batch,
                        base_branch=args.base_branch,
                        stack_depth=args.stack_depth,
                        stacked_on=args.stacked_on)
    save_state(state)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="campaign_status",
                                description="File-based campaign tracker CLI.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="List all campaigns")
    sp.set_defaults(func=_cmd_list)

    sp = sub.add_parser("show", help="Show a campaign or one batch")
    sp.add_argument("campaign_id")
    sp.add_argument("--batch", default=None)
    sp.set_defaults(func=_cmd_show)

    sp = sub.add_parser("update", help="Update batch fields")
    sp.add_argument("campaign_id")
    sp.add_argument("batch")
    sp.add_argument("--status", choices=VALID_STATUSES)
    sp.add_argument("--pr-url", dest="pr_url")
    sp.add_argument("--pr", type=int)
    sp.add_argument("--sha", dest="sha")
    sp.add_argument("--deployed-sha", dest="deployed_sha")
    sp.add_argument("--next-batch", dest="next_batch")
    sp.set_defaults(func=_cmd_update)

    sp = sub.add_parser("block", help="Block a batch with a reason")
    sp.add_argument("campaign_id")
    sp.add_argument("batch")
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=_cmd_block)

    sp = sub.add_parser("unblock", help="Clear block_reason and resume")
    sp.add_argument("campaign_id")
    sp.add_argument("batch")
    sp.add_argument("--status", default="planned",
                    choices=[s for s in VALID_STATUSES if s != "blocked"])
    sp.set_defaults(func=_cmd_unblock)

    sp = sub.add_parser("smoke", help="Attach smoke report and mark batch smoked")
    sp.add_argument("campaign_id")
    sp.add_argument("batch")
    sp.add_argument("--report", required=True)
    sp.add_argument("--skip-exists-check", action="store_true")
    sp.set_defaults(func=_cmd_smoke)

    sp = sub.add_parser("export", help="Export a campaign as markdown")
    sp.add_argument("campaign_id")
    sp.set_defaults(func=_cmd_export)

    sp = sub.add_parser("summary",
                        help="Top-level dashboard: open PRs / next batch / blocked / recent deploys")
    sp.set_defaults(func=_cmd_summary)

    sp = sub.add_parser("deploy",
                        help="Record a deploy event with full audit metadata")
    sp.add_argument("campaign_id")
    sp.add_argument("batch")
    sp.add_argument("--sha", required=True, help="Deployed SHA (= main HEAD post-merge)")
    sp.add_argument("--previous-main-sha", dest="previous_main_sha",
                    help="Main SHA before this deploy (for rollback)")
    sp.add_argument("--robocopy-exit-codes", dest="robocopy_exit_codes",
                    help="Comma-separated list, e.g. '1,1,1,0'")
    sp.add_argument("--restart-seconds", dest="restart_seconds", type=int)
    sp.add_argument("--rollback-command", dest="rollback_command",
                    help="Override default rollback (git revert -m 1 <sha>)")
    sp.set_defaults(func=_cmd_deploy)

    sp = sub.add_parser("stack",
                        help="Record branch-stack metadata (base_branch, stack_depth, stacked_on)")
    sp.add_argument("campaign_id")
    sp.add_argument("batch")
    sp.add_argument("--base-branch", dest="base_branch", required=True)
    sp.add_argument("--stack-depth", dest="stack_depth", type=int, default=0)
    sp.add_argument("--stacked-on", dest="stacked_on")
    sp.set_defaults(func=_cmd_stack)

    # ── v2 runner subcommands ──────────────────────────────────────────────

    sp = sub.add_parser("queue",
                        help="Render the campaign batch queue with readiness markers")
    sp.add_argument("campaign_id", nargs="?", default=None)
    sp.set_defaults(func=_cmd_queue)

    sp = sub.add_parser("next",
                        help="Print the next recommended batch (JSON)")
    sp.add_argument("campaign_id")
    sp.set_defaults(func=_cmd_next)

    sp = sub.add_parser("blockers",
                        help="List blocked batches (optionally filtered by campaign)")
    sp.add_argument("campaign_id", nargs="?", default=None)
    sp.set_defaults(func=_cmd_blockers)

    sp = sub.add_parser("verify",
                        help="Verify a batch against its gates")
    sp.add_argument("campaign_id")
    sp.add_argument("batch")
    sp.add_argument("--gate", help="Comma-separated subset of required gates")
    sp.set_defaults(func=_cmd_verify)

    sp = sub.add_parser("graph",
                        help="Print the dependency graph for a campaign")
    sp.add_argument("campaign_id")
    sp.set_defaults(func=_cmd_graph)

    sp = sub.add_parser("resume",
                        help="Print resume instructions for a campaign")
    sp.add_argument("campaign_id")
    sp.set_defaults(func=_cmd_resume)

    sp = sub.add_parser("pause",
                        help="Alias of `block` (mark batch with operator reason)")
    sp.add_argument("campaign_id")
    sp.add_argument("batch")
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=_cmd_pause)

    sp = sub.add_parser("retry",
                        help="Reset a batch to 'planned' (preserves audit fields)")
    sp.add_argument("campaign_id")
    sp.add_argument("batch")
    sp.set_defaults(func=_cmd_retry)

    sp = sub.add_parser("doctor",
                        help="Health check: detect stuck batches, stack risks, interrupted campaigns")
    sp.set_defaults(func=_cmd_doctor)

    sp = sub.add_parser("dashboard",
                        help="Render full operator dashboard as markdown")
    sp.set_defaults(func=_cmd_dashboard)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
