# Forbidden Paths — Deploy Blocklist

If any path in this list appears as a changed file in any diff, the deploy is **immediately blocked**.
Referenced by: `deploy_git_diff_reviewer.md`, `deploy_persistence_storage_reviewer.md`, `deploy_release_manager.md`.

No override. No exception. Production data-protection hard stops.

---

## Blocked patterns

| Pattern | Category | Block type |
|---------|----------|------------|
| `C:\PZ\.env` | Credentials | Immediate block |
| `.env` (repo root) | Credentials | Immediate block |
| `C:\PZ\storage\*` | Production data | Immediate block |
| `storage/*` (relative) | Production data | Immediate block |
| `C:\PZ\outputs\*` | Production outputs | Immediate block |
| `outputs/*` (relative) | Production outputs | Immediate block |
| `C:\PZ\logs\*` | Production logs | Immediate block |
| `logs/*` (relative) | Production logs | Immediate block |
| `*.db` | Database files | Immediate block |
| `C:\PZ\cloudflared\*` | Tunnel config | Immediate block |

---

## Reviewer responsibilities

Git/Diff Reviewer and Persistence/Storage Reviewer each check this list independently.
Either finding a match → report `FORBIDDEN_PATH` to Lead Coordinator → Lead Coordinator blocks.
Independent checks are intentional redundancy, not duplication error.

In the sync plan: no path from this list may appear in the robocopy scope or `/MIR` target.

---

## What is NOT blocked

- `service/app/` — safe to diff and sync
- `service/tests/` — safe to diff
- `docs/` and `.md` files — safe to diff
- `.claude/` — governance files, safe to diff
