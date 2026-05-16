# Campaign Runner v2 — Operator Runbook

> The runner is a **supervised** orchestrator. You drive it; it tracks state
> and refuses to do anything unsafe. No daemon, no auto-merge, no auto-deploy.
> Every state transition is your decision.
>
> Last updated: 2026-05-16. Tested against runner v2 at SHA TBD.

---

## 1 — What the runner does (and doesn't)

### What it DOES

- Tracks campaigns + batches in `tasks/campaign-state.json`.
- Tells you the next ready batch (`next`).
- Verifies a batch against gates before you mark it smoked (`verify`).
- Detects stuck batches, branch-stack misroutes, interrupted campaigns (`doctor`).
- Renders a markdown dashboard you can paste anywhere (`dashboard`).
- Records deploy metadata (`previous_main_sha`, `robocopy_exit_codes`,
  `restart_seconds`, `rollback_command`).

### What it DOES NOT

- Does not merge PRs. You do, via `gh pr merge`.
- Does not deploy. You do, via robocopy + service restart.
- Does not write to wFirma / proforma / PZ engine / accounting.
- Does not run in the background.
- Does not modify `.env`, production storage, or any external service.

---

## 2 — The 7 batch states

```
planned → active → pr_open → merged → deployed → smoked   (= done)
                ↘     ↘         ↘         ↘         ↘
                              blocked  (reversible side branch)
```

Use `update --status` to move forward. Use `block --reason` to side-branch.
Use `unblock` to resume. Use `retry` to reset to `planned` keeping audit
fields (merge_sha, pr_url, etc.).

---

## 3 — Standard batch lifecycle (one batch end-to-end)

```bash
# 1. Operator decides to start B<N>
python service/scripts/campaign_status.py next <CAMPAIGN_ID>
#    → Shows the next ready batch

# 2. Create feature branch off main and implement
git checkout main && git pull --ff-only
git checkout -b feat/<short-name>
# ... edit code, add tests ...

# 3. Mark batch active
python service/scripts/campaign_status.py update <C> B<N> --status active

# 4. Run local tests
cd service && python -m pytest tests/<scope> -q
python test_pz_regression.py

# 5. Push + open PR
git push -u origin feat/<short-name>
gh pr create --title "..." --body "..."

# 6. Record PR
python service/scripts/campaign_status.py update <C> B<N> \
    --status pr_open --pr <NUMBER> --pr-url <URL>

# 7. After operator merge
python service/scripts/campaign_status.py update <C> B<N> \
    --status merged --sha <MERGE_SHA>

# 8. Robocopy runtime files + restart PZService
# ... your existing deploy procedure ...

# 9. Record deploy
python service/scripts/campaign_status.py deploy <C> B<N> \
    --sha <NEW_HEAD> \
    --previous-main-sha <PREV_HEAD> \
    --robocopy-exit-codes 1,1,1,0 \
    --restart-seconds 10

# 10. Run smoke
python service/scripts/run_smoke.py tasks/smoke-specs/<spec>.json

# 11. Attach smoke report
python service/scripts/campaign_status.py smoke <C> B<N> \
    --report tasks/smoke-reports/<date>-<slug>.md

# 12. Verify gates
python service/scripts/campaign_status.py verify <C> B<N>
#    → should return ok=True (exit 0)

# 13. Inspect dashboard
python service/scripts/campaign_status.py dashboard
```

---

## 4 — Detecting trouble: `doctor`

```bash
python service/scripts/campaign_status.py doctor
```

The doctor surfaces:

| Issue type   | Trigger | Recovery |
|---|---|---|
| **stuck** (pr_open) | PR open > 3 days | Merge it, ping reviewer, or `block` with reason |
| **stuck** (merged) | Merged but no deploy > 1 day | Deploy it OR `retry` if work was abandoned |
| **stuck** (deployed) | Deployed but no smoke report > 1 day | Run smoke; `smoke` attach report |
| **stack** | `stack_depth > 0` with `base_branch == 'main'` | Open a forward-merge PR (see L-018, L-029, L-035) |
| **interrupted** | Campaign 'active' but no open work | Add new batches OR mark campaign 'completed' manually |
| **schema** | `schema_version != 1` | Halt; ping maintainer |

`doctor` returns exit code 1 if any issue found — useful for CI guard
(`python ... doctor || exit 1`).

---

## 5 — Stack-into-stack avoidance

The Master Data campaign lost time on stack-into-stack merges (B7 + B8 →
forward-merge PR #105). The fix is mechanical:

```bash
# When opening a stacked PR, record the stack:
python service/scripts/campaign_status.py stack <C> B<N> \
    --base-branch <PARENT_BRANCH> \
    --stack-depth 1 \
    --stacked-on <PARENT_BATCH>

# If you ever set base-branch=main with stack-depth>0, `doctor` will flag it.
```

Always preferred: **branch every PR off `main`**. Stack only when the parent
is non-trivial and you need to keep changes isolated. After the parent
merges, retarget the stacked PR's base to `main` (GitHub UI) BEFORE merging
the stacked PR.

---

## 6 — Rollback

Every `deploy` event records a `previous_main_sha` and an auto-generated
`rollback_command`. To roll back the most recent deploy:

```bash
# 1. Find the most recent deploy
python service/scripts/campaign_status.py dashboard | grep "Recent deploys"

# 2. Print the rollback plan
python -c "import json; d=json.load(open('tasks/campaign-state.json')); \
  for c in d['campaigns']: \
    for b in c['batches']: \
      if b.get('deployed_at'): print(b.get('rollback_command'))" | tail -1

# 3. Execute the rollback (operator)
git revert -m 1 <MERGE_SHA> --no-edit
git push origin main

# 4. Re-robocopy the reverted files + restart PZService
# 5. Record the rollback as a NEW deploy event
python service/scripts/campaign_status.py deploy <C> ROLLBACK-<N> \
    --sha <NEW_HEAD_AFTER_REVERT> \
    --previous-main-sha <FAILED_DEPLOY_SHA> \
    --rollback-command "(this was a rollback; nothing to revert further)"
```

---

## 7 — Hard rules (carry-forward, mechanically enforced)

`service/tests/test_runner_v2_hard_rules.py` enforces:

1. No `threading.Thread`, `BackgroundScheduler`, `BlockingScheduler`, or
   `while True:` loops in the runner.
2. No `gh pr merge` / `git merge` subprocess invocations from runner.
3. No `robocopy` / `sc.exe` / `Restart-Service` invocations from runner.
4. No writes to `/etc/`, `/var/`, `C:\Windows\`, `.env`, `/storage/`.
5. `save_state` must use atomic `.tmp` + `replace` pattern.
6. Runner does NOT import `pz_import_processor`, `wfirma_client`,
   `routes_proforma`, `proforma_pz`, or `ledger_aggregator`.
7. Smoke driver does NOT shell out (no `subprocess.run`).
8. Runner is file-based only: no `sqlite3`, no `fastapi`, no HTTP server.
9. `VALID_STATUSES` is locked to exactly 7 entries.
10. State file schema is versioned.
11. `tasks/campaign-runner.md` must state "No background process" and
    "No daemon".

Adding behaviour that violates any of these requires changing the test
explicitly — the contract test is the gate, not the prose.

---

## 8 — Common operator questions

**Q: What if a batch fails mid-way?**
A: `block --reason "what went wrong"`. Investigate. Either `unblock` to
resume, or `retry` to start over (preserves audit fields, increments
`retries` counter).

**Q: What if I forgot to update state after a merge?**
A: Just run `update` retroactively. The state is the operator's source of
truth, not a real-time log.

**Q: Can two operators run the runner at the same time?**
A: Single-writer assumption. The state file uses atomic write but does NOT
use file locking. Don't run two CLI invocations concurrently on the same
state file.

**Q: What if `doctor` flags a stack misroute after the fact?**
A: Open a forward-merge PR that pulls the stacked branch into main directly.
See lesson L-018 / L-029 in `tasks/lessons.md`.

**Q: How do I check Phase 6F readiness?**
A: Re-read `tasks/phase-6f-architecture.md` and
`tasks/phase-6f-readiness-2026-05-16.md`. Operator approval of §10.1-§10.3
is the gate.
