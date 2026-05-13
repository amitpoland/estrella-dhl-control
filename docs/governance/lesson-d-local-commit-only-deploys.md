# Governance Reference — Lesson D: LOCAL-COMMIT-ONLY Deploys

**Status:** CODIFIED 2026-05-13  
**Origin:** Wave 1 closure cycle — SHA `4c797e46ff40b09f51292f05e13baef2882622a0` deployed without GitHub PR  
**Short rule:** Any commit deployed to production that is not on `origin/main` via a PR requires a disclosure header in the gate report and a reconciliation PR before the next origin-pull deploy.  
**Full text:** `.claude/memory/engineering_lessons.md` § Lesson D  
**Audit record:** `.claude/memory/local-commit-deploys.jsonl`

---

## Background

The standard deploy flow is:

```
code change → GitHub PR → CI → agent review → merge to origin/main → git pull --ff-only → robocopy → PZService restart
```

In the Wave 1 scenario, the flow was:

```
code change → local commit (no PR) → 7-agent inline gate → robocopy → PZService restart
```

Both paths ran agent review. Both produced CLEAR verdicts. The code was safe. But the second path left no trace in `origin/main` — only the Windows staging machine's git history recorded the change. Anyone auditing production state via GitHub would see a gap.

**SHA lineage evidence (Wave 1):**
- `git log 0b4e381..4c797e4` → 1 commit only (`4c797e4`)
- `git merge-base 0b4e381 4c797e4` → `1b38ea0` (the common ancestor, already on origin)
- `git log 4c797e4..5ee390b` → 3 PRs (#72, #73, #74) all proper GitHub PRs
- Conclusion: `4c797e4` is the only LOCAL-COMMIT-ONLY commit in the Wave 1 lineage

---

## Gate Type Definitions

### PR Gate (standard)

- Code lands on `origin/main` via GitHub PR
- CI runs against the PR branch
- Agent review fires per CLAUDE.md GATE 1
- Merge via "Create a merge commit"
- SHA is publicly attributable to a PR number
- Full reviewer trail accessible via GitHub web/API
- Subsequent deploy is `git pull --ff-only origin main` + robocopy

### Inline Gate (LOCAL-COMMIT-ONLY)

- Code exists as a commit on a local working tree
- No GitHub PR exists for this SHA
- 7-agent deploy review fires against local state (inline OR spawned)
- Lead coordinator issues verdict
- Code ships to production via local sync (robocopy/scp/equivalent)
- SHA has no public PR trail
- `git branch -r --contains <sha>` does NOT list `origin/main`

**Both gate types involve agent review. The distinguishing fact: does the SHA have a public PR trail?**

---

## The 5 Rules

### Rule 1 — Disclosure requirement

Any LOCAL-COMMIT-ONLY deploy must include in its gate report header, before any sync commands execute:

```
⚠ LOCAL-COMMIT-ONLY DEPLOY
SHA being deployed:    <full 40-char SHA>
GitHub PR:             NONE — this SHA is not on origin/main
Bypass reason:         <reason from enumerated list in Rule 4>
Reconciliation plan:   <when and how the reconciliation PR will be filed>
```

**This header must appear at the top of the gate report**, not buried in a section. The operator must see it before executing deploy commands.

Detection command: `git branch -r --contains <sha>` — if `origin/main` is not listed, the header is required.

### Rule 2 — Operator visibility and acknowledgment

The disclosure header must appear at the top of the gate report. The operator must explicitly acknowledge: "I acknowledge LOCAL-COMMIT-ONLY" or equivalent affirmative before sync proceeds. Tacit approval (proceeding without acknowledgment) does not satisfy this rule.

### Rule 3 — Reconciliation requirement (SOFT)

A reconciliation PR must be filed and merged to `origin/main` before any subsequent `git pull --ff-only origin main` is executed on the same production machine.

Pre-check for any future deploy:
```bash
git log origin/main..HEAD
```
If this returns commits AND those commits are currently deployed to production, reconciliation must precede the pull. The deploy gate must fail if the pre-check reveals unreconciled LOCAL-COMMIT-ONLY commits.

The reconciliation PR body must include:
- Original LOCAL-COMMIT-ONLY deploy date and full SHA
- Bypass reason from the inline gate
- Summary of 7-agent gate verdicts produced during inline review
- Byte-identical verification: `git diff <local-sha> <reconcile-pr-head> -- service/app/`
- Explicit statement: "The code in this PR is byte-identical to what was deployed on [date]."

### Rule 4 — Valid bypass reasons (enumerated)

The following reasons justify an inline gate. All other reasons trigger escalation and must not proceed.

| Reason | Required documentation |
|--------|------------------------|
| Production incident requiring fix faster than PR review cycle permits | State the incident in the disclosure header (what broke, when) |
| Operator on production-only machine (Mac dev environment unavailable) | State which machine, why Mac unavailable |
| Toolchain failure preventing PR creation (GitHub API unreachable, `gh` CLI broken) | Cite the specific failure and attempted workaround |

**Reasons that do NOT justify inline gate** (automatic escalation triggers):
- Convenience or speed preference
- Avoiding review friction
- Bypassing failing tests
- Avoiding CI wait time

If a bypass reason is not in the enumerated list, the orchestrator must escalate to the operator and halt the deploy until approval is given explicitly.

### Rule 5 — Audit trail (`local-commit-deploys.jsonl`)

Every LOCAL-COMMIT-ONLY deploy appends an entry to `.claude/memory/local-commit-deploys.jsonl` **immediately after the gate report is produced, before sync**.

Schema:
```json
{
  "timestamp": "<ISO8601>",
  "sha": "<full 40-char SHA>",
  "commit_message": "<first line of commit message>",
  "bypass_reason": "production-incident-timing|production-only-machine|toolchain-failure",
  "bypass_detail": "<free text describing the incident or constraint>",
  "gate_mode": "inline|spawned",
  "gate_verdicts_summary": "<brief summary of all 7 agent verdicts>",
  "reconciliation_status": "PENDING|PENDING_RETROACTIVE|MERGED|ABANDONED",
  "reconciliation_pr": null or <PR number>,
  "reconciliation_merged_at": null or "<ISO8601>",
  "environment": "windows-prod|mac-dev|other",
  "deployed_at": "<ISO8601 when robocopy completed>"
}
```

---

## Worked Example — SHA `4c797e4` (Retroactive)

```json
{
  "timestamp": "2026-05-13T10:43:00Z",
  "sha": "4c797e46ff40b09f51292f05e13baef2882622a0",
  "commit_message": "fix(email): prevent outbound customs emails sending without attachments",
  "bypass_reason": "production-incident-timing",
  "bypass_detail": "Attachment integrity guard needed to reach production before customs emails could be queued. Windows machine only; Mac dev environment was active session context. PR #74 (EV_PACKING fix) was filed via worktree in the same session, confirming GitHub was accessible — bypass reason was operational timing, not toolchain failure.",
  "gate_mode": "inline",
  "gate_verdicts_summary": "All 7 deploy agents returned CLEAR inline. Tests: 160/160 PZ regression, 366/366 carrier suite, 12/12 attachment integrity. Lead coordinator: READY-TO-DEPLOY. Risk level: MEDIUM.",
  "reconciliation_status": "PENDING",
  "reconciliation_pr": null,
  "reconciliation_merged_at": null,
  "environment": "windows-prod",
  "deployed_at": "2026-05-13T10:43:00Z"
}
```

**Note on bypass reason accuracy:** On reflection, GitHub was accessible during this session (PR #74 was filed via `gh pr create` from a worktree in the same session at ~12:26Z). The primary bypass reason was operational timing urgency + the inline-gate pattern being the established Windows-deploy norm at the time (before Lesson D was codified). This entry is marked retroactive accordingly.

**Reconciliation status: CLOSED — 2026-05-13**  
SHA `4c797e4` is now an ancestor of `origin/main`. It was swept onto `origin/main` via the PR #76 governance branch (`chore/governance-lesson-d-codification`), which was created from local `main` (which included `4c797e4`). Confirmed: `git branch -r --contains 4c797e4` → `origin/main`. Dedicated reconciliation PR #77 (`reconcile/4c797e4-plus-lesson-d-backstop`) added the formal closure + lead coordinator backstop. Audit record updated in `.claude/memory/local-commit-deploys.jsonl` (reconciliation-close entry appended). No Windows deploy required — production content was already byte-identical.

---

## 4c797e4 Reconciliation Workflow

### What to do

1. **Create reconciliation branch** from `origin/main` HEAD:
   ```bash
   git checkout -b reconcile/4c797e4-attachment-integrity-hotfix origin/main
   ```

2. **Apply the change** — cherry-pick or re-apply the diff:
   ```bash
   git cherry-pick 4c797e4
   ```
   OR manually apply the patch from `git show 4c797e4`.

3. **Verify byte-identical content**:
   ```bash
   git diff 4c797e4 HEAD --
   # Must output nothing (zero diff — full tree)
   git diff 4c797e4 HEAD -- service/app/
   # Must output nothing (zero diff — production surface subset)
   ```

4. **Create reconciliation PR**:
   - Branch: `reconcile/4c797e4-attachment-integrity-hotfix`
   - Title: `chore(reconcile): backfill 4c797e4 attachment integrity hotfix with proper PR trail`
   - Body template (copy verbatim, fill bracketed fields):

   ```
   ## Reconciliation PR

   This PR backfills SHA `4c797e4` to `origin/main` with a proper PR trail.
   It is byte-identical to what was deployed to Windows production on 2026-05-13T10:43Z.

   ## Original deploy context

   - Deploy date: 2026-05-13T10:43Z
   - Original SHA: `4c797e46ff40b09f51292f05e13baef2882622a0`
   - Bypass reason: Production incident timing — attachment integrity guard needed
     in production before customs email queue could safely run
   - Gate mode: Inline 7-agent review (all 7 CLEAR, MEDIUM risk)
   - Smokes: 160/160 PZ regression, 366/366 carrier, 12/12 attachment integrity

   ## Byte-identical verification

   `git diff 4c797e4 <this-pr-head> --` → empty (zero diff, full tree)
   `git diff 4c797e4 <this-pr-head> -- service/app/` → empty (zero diff, production surface subset)

   ## Agent review required for this reconciliation PR

   - deploy_release_manager (verify reconciliation conditions met)
   - adr-historian (verify no ADR drift)
   - final-consistency-review (verify byte-identical claim)

   ## Lesson D compliance

   This PR satisfies Lesson D Rule 3 (reconciliation before next origin-pull deploy).
   After merge, update `.claude/memory/local-commit-deploys.jsonl` entry for `4c797e4`
   to set `"reconciliation_status": "MERGED"` and fill `reconciliation_pr` + `reconciliation_merged_at`.
   ```

5. **Merge** with "Create a merge commit".

6. **Update audit record** in `.claude/memory/local-commit-deploys.jsonl` to set `reconciliation_status: MERGED`.

### When to execute

> **STATUS: COMPLETED 2026-05-13** — `4c797e4` reconciliation is done (see Reconciliation status note in § Worked Example above). The steps below are preserved as the canonical workflow for future LOCAL-COMMIT-ONLY reconciliations.

- **Recommended**: next governance-focused session
- **Hard requirement**: before any `git pull --ff-only origin main` on Windows production
- **If Wave 2 evidence triggers a new code change before reconciliation**: reconciliation must happen first (per Rule 3)

### Pre-flight verification

Before filing the reconciliation PR, confirm:
```bash
git log origin/main..4c797e4 --oneline
# Should show only: 4c797e4 fix(email): prevent outbound...
```

If additional commits appear between `origin/main` and `4c797e4`, the cherry-pick approach may produce conflicts. Resolve to achieve byte-identical content.

---

## Quick Reference

| Question | Answer |
|---|---|
| When is a deploy LOCAL-COMMIT-ONLY? | When `git branch -r --contains <sha>` does NOT list `origin/main` |
| Is it a hard block? | No — but disclosure + acknowledgment are mandatory before sync |
| When must reconciliation be filed? | Before next `git pull --ff-only origin main` on the same machine |
| Where is the audit record? | `.claude/memory/local-commit-deploys.jsonl` |
| Which agent enforces Rule 1 detection? | `deploy_release_manager.md` § Branch hygiene item 5 + `deploy_lead_coordinator.md` § LOCAL-COMMIT-ONLY detection (backstop, added 2026-05-13) |
| What is the retroactive record for `4c797e4`? | See § Worked Example above + `.claude/memory/local-commit-deploys.jsonl` — entry 1 (original) + entry 2 (reconciliation-close) |
| Has `4c797e4` been reconciled? | YES — merged onto `origin/main` via PR #76 ancestry. Formal closure: PR #77 |
