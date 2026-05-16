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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
