# TASK_STATE.md

In-flight **single-task** tracker. Records the current task's goal,
completion criteria, status, and HOLD reason (if stopped). Ephemeral —
rewrite the `## Current task` block when a new task begins.

Rules and boundary vs PROJECT_STATE.md:
`docs/governance/anti-hold-and-completion.md` §5.

---

## Current task

- **Task:** B-019 production DB backup authority (status API + Run Now UI + schtask + restore drill)
- **Status:** `IMPLEMENTING`
- **Campaign code:** B-019
- **origin/main / production (measured after B-012/B-014 App deploy):** `57bf4e2b79d4d6ecd6225106320a1e56994d414a`
- **Worktree:** `C:\PZ-wt\b019-db-backup-authority` / `fix/b019-db-backup-authority`
- **Do not reopen:** B-011..B-018; B-014 V1→V2 cutover remains HOLD
- **Next after B-019 close:** B-021 (RO assessment only — no mutation without operator auth)

### Prior — B-012/B-014 App deploy debt

**COMPLETE** 2026-08-14. Production App at `57bf4e2b`. Rollback unit
`57bf4e2b79d4d6ecd6225106320a1e56994d414a-20260814-010033` (restores `15cd1057`).
External writes during smoke: 0. No V1→V2 cutover.

### B-011..B-018 dispositions (CLOSED — do not reopen)

| ID | Disposition |
|---|---|
| B-011..B-018 | CLOSED (see prior TASK_STATE / BACKLOG) |

### B-019 discovery facts (2026-08-14)

- `EstrellaDBBackup` schtask: ABSENT
- Stale advisor paths (`C:\PZ\venv`, `C:\PZ\scripts\run_backup.py`): absent
- Live authority: `C:\PZ\app\services\backup_service.py` `run_backup()` + admin routes
- `C:\PZ-backups` holds Deploy-PZ SHA units; DB timestamp manifests were missing pre-B-019
- No Admin UI for backup until this PR; no GET `/status` until this PR
