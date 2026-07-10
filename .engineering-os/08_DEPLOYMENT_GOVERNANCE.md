# 08 — Deployment Governance

**The Engineering OS never defines a new deploy path.** Every production sync to `C:\PZ` is
owned by the **existing 7-agent deploy gate** (CLAUDE.md "Production deployment rule" +
`.claude/agents/deploy_*.md`). This file points to that gate and states the surrounding
discipline; it authorizes nothing.

---

## 1. The 7-agent deploy gate (unchanged, referenced)

Run in parallel before any sync; `deploy-lead-coordinator` issues the written go/no-go:

1. `deploy-lead-coordinator` — final go/no-go
2. `deploy-git-diff-reviewer` — file classification, forbidden paths
3. `deploy-backend-impact-reviewer` — routes, auth, imports, registration
4. `deploy-persistence-storage-reviewer` — schema, storage writes
5. `deploy-security-reviewer` — credentials, auth removal, injection (**terminal blocker**)
6. `deploy-qa-reviewer` — test pass/fail vs `.claude/contracts/test-baseline.md`
7. `deploy-release-manager` — branch hygiene, rollback command, sync plan

Every Git-based production deploy requires the **full** gate. No exceptions. GATE 1 (PR-open
discipline) specialises to this gate for production.

---

## 2. Operator-only actions (the OS + Coordinator never perform)

These are guard-blocked and remain the operator's:

- `git push`, `gh pr merge`
- `robocopy` **into** `C:\PZ` (production is never robocopy'd into by an agent)
- `Restart-Service` / `sc.exe` on `PZService`
- `git reset --hard` on `C:\PZ`

The Coordinator prepares a package to be *ready* for deploy; the operator executes the sync +
restart. This is the established division of labor.

---

## 3. Canonical trees (PATH GUARD — permanent)

| Path | Role |
|---|---|
| `C:\PZ` | Production — NSSM AppDirectory (`PZService`, port 47213). Never `reset --hard`, never robocopy'd into by an agent. |
| `C:\PZ-verify` | Verification clone — tracks `origin/main`. **Source of truth** for all git/file-hash checks. |
| `C:\Users\Super Fashion\PZ APP` | **RETIRED** — forbidden to read/verify/deploy from. |

All verification reads + git ops use `C:\PZ-verify`. One-session rule: only one session operates
against the verify tree at a time.

---

## 4. Sync layout + Lesson J (engine files deploy separately)

- Standard sync: `service/app → C:\PZ\app` via robocopy, excluding `storage`, `__pycache__`,
  `*.db` (never deploy test DBs; never touch live `C:\PZ\storage`).
- **Root engine files** (`pz_import_processor.py`, `polish_description_generator.py`) deploy to
  `C:\PZ\engine\` via a **separate** robocopy — NOT covered by the standard sync. Any package
  touching an engine file must declare the additional sync command in its PR body and rollback.

---

## 5. LOCAL-COMMIT-ONLY discipline (Lesson D)

Any deploy that is not backed by a merged GitHub PR must carry a disclosure header (SHA,
"GitHub PR: NONE", bypass reason, reconciliation plan) visible to the operator before any sync,
be acknowledged, and append to `.claude/memory/local-commit-deploys.jsonl`. A reconciliation PR
is filed before the next `git pull --ff-only origin main`.

---

## 6. Post-deploy verification (mandatory before Close)

After the operator syncs + restarts, verify against production before declaring done:

- `PZService` RUNNING; process **start time > file write time** (guards the stale-process
  failure mode — a silent non-elevated restart serves old code).
- `/docs` returns 200 (no ImportError on load).
- New endpoints reachable with correct guard behavior (e.g. 401 on privileged no-key, 404 on
  unknown id) — not 404-because-not-loaded.
- Additive schema auto-created in the live DB; **no test DBs deployed**; live storage untouched.
- No new backend errors in logs.

Record the verified SHA + result in the deployment record + PROJECT_STATE (`10`).

---

## 6.1 Deploy-source discipline + release certification (v1.2 — operator-ratified 2026-07-10)

Codified after the 2026-07-10 double deploy incident (stale bytes shipped from a feature-branch
tree; back-to-back stop/start left the service STOPPED). Binding on every sync:

1. **Source at target SHA first.** Verify the sync source tree is checked out at the target
   SHA **before** robocopy (when `main` is held by another worktree: `git fetch` +
   `git checkout --detach origin/main`), and **hash-verify the deployed files after**
   (`git hash-object` vs `git ls-tree origin/main` — byte-level proof).
2. **No destructive mirror.** `/MIR` is forbidden; the app sync always excludes storage
   (`/XD storage`) so production data can never be shadowed or deleted by a copy.
3. **Restart sequence.** `sc.exe stop PZService` → poll until **STOPPED** → `sc.exe start` →
   verify **STATE: 4 RUNNING**. Never stop;start back-to-back. A deployment is **incomplete
   until PZService reports RUNNING**.
4. **Never seal from chat claims.** Merge/deploy completion is proven by fetch + PR-state +
   PID + hash evidence, never by a claim (even a relayed one); a false completion claim is a
   **HALT**. The full Phase-8 release-certification chain (Git → disk → process → logs →
   endpoint → business behavior, with main/production/rollback SHAs recorded) is defined in
   `00 §8`.

> The OS stops at "ready + reviewed + operable." The gate and the operator take it to
> production. Verification is autonomous and mandatory; the sync is not the OS's to perform.
