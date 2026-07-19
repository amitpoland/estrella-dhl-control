<!--
PR CLOSURE INTERFACE — EJ Dashboard

This template COLLECTS EVIDENCE. It is not a governance authority: it defines no
lifecycle state, no gate, no acceptance policy, no deploy rule. Where a rule is
needed, it names the canonical file that owns it.

Canonical authorities (read them there, not here):
  .claude/TASK_EXECUTION_PROTOCOL.md            lifecycle states + transitions
  docs/governance/anti-hold-and-completion.md   HOLD / EXECUTION_BLOCKED / resume
  CLAUDE.md                                     GATES 1-6, Business Feature Completeness, deploy rule
  docs/governance/AUTHORITY_MAP.md              write targets / authority ownership
  .claude/contracts/test-baseline.md            test baseline counts
  service/docs/production_deployment_rule.md    7-agent production gate

HOW TO FILL: every section gets an answer. A section that does not apply gets
"N/A - <one-line reason>". Do not delete a section to avoid it; an unexplained
blank or deletion makes the PR incomplete.
-->

## Summary

<!-- One paragraph, plain business language: what changes and why. -->

-

## Task and authority owner

- **Module / domain being extended:** <!-- no answer = STOP (CLAUDE.md, Application Authority Rule) -->
- **Canonical backend authority:** <!-- route file / service module, or N/A - reason -->
- **Canonical frontend file (if UI):** <!-- one canonical file only, or N/A - reason -->
- **Write targets touched:** <!-- DBs / storage / audit files per docs/governance/AUTHORITY_MAP.md; "none (read-only)" -->
- **Lifecycle state at close:** <!-- state name per .claude/TASK_EXECUTION_PROTOCOL.md -->
- [ ] No new parallel authority, duplicate page, or duplicate service introduced.

## Scope and files changed

- **Change type:** <!-- feature | bug fix | refactor | docs/governance | data correction -->
- **Surfaces:** <!-- backend service/app/** | root engine file | frontend V1/V2 | storage/schema | docs/.claude only -->
- [ ] `git diff --name-only` matches the agreed plan file list; no out-of-scope edits.
- **Out-of-scope edits (if any) + why:**

## Acceptance criteria

<!-- The criteria agreed before implementation. List them; mark each met/not met. -->

- [ ]
- [ ]

## Validation evidence

| Suite or check | Command | Result | Baseline comparison |
|---|---|---|---|
| Smoke | `pytest tests/ -m smoke -q` | | |
| Targeted domain | | | |
| Root regression (engine / golden touched) | `python test_pz_regression.py` | | |

<!-- Baseline counts: .claude/contracts/test-baseline.md -->

- **New tests added:**
- **Intentional baseline delta + justification:** <!-- or N/A - reason -->

## User-visible verification

<!-- Answer only the applicable line; mark the others N/A - reason.
     Requirement owner: CLAUDE.md GATE 6. -->

- **UI change:** <!-- browser flow tested end-to-end; console errors; network 4xx/5xx; click -> API -> DB -> UI confirmed -->
- **Backend / API change (no UI surface):** <!-- curl + audit-log evidence -->
- **Docs / governance-only:** <!-- N/A - no runtime surface -->
- **Production verification:** <!-- only if this PR has been deployed; otherwise N/A - not deployed -->
- **Evidence (paths / output / screenshots):**

## Business Feature Completeness

<!-- Standard + the 7 requirements: CLAUDE.md, Business Feature Completeness Standard.
     Do not restate the requirements here. -->

- **Applicable:** YES / NO
- **If NO - reason:** <!-- e.g. bug fix, refactor, docs-only: no new business capability -->
- **If YES - evidence / stage reached:** <!-- per the canonical standard, incl. Business Owner + date if sign-off claimed -->

## Sensitive-system impact

<!-- Declare each explicitly, including "none". Name affected systems only:
     no secrets, tokens, payloads, customer data, or internal record IDs. -->

- **Production data / live service:** none / describe:
- **External booked records** (wFirma, DHL, email, KSeF): none / describe:
- **Credentials, auth, or write gates:** none removed or weakened / describe:
- **Schema / migration:** none / migration plan:
- **Financial, customs, or landed-cost rules:** untouched / describe:

## Rollback

- **Revert:** <!-- exact command, branch delete, or other -->
- **Deploy rollback:** <!-- exact SHA-specific command, or N/A - not synced to production -->

## Deployment status

- [ ] **Code-only** — merging does not reach production; no deploy in this PR.
- [ ] **Reaches production** — operator-executed sync required; gate defined in `service/docs/production_deployment_rule.md`.
- [ ] **Root engine file changed** — separate engine sync required (CLAUDE.md, Lesson J). <!-- or N/A -->

## Review findings

- **Reviews run:** <!-- named reviewers / agents, or N/A - reason -->
- **HIGH / CRITICAL findings:** <!-- resolved inline, escalated to operator, or none -->
- **Unresolved findings + disposition:**

## Closure checklist

<!-- Gate definitions live in CLAUDE.md; state definitions in .claude/TASK_EXECUTION_PROTOCOL.md.
     This is an evidence record, not a redefinition of either. -->

- [ ] GATE 1 pre-open conditions satisfied (CLAUDE.md).
- [ ] Open implementation PR count within the GATE 2 limit (CLAUDE.md). Current count:
- [ ] `.claude/memory/TASK_STATE.md` updated to the closing state.
- [ ] `BACKLOG.md` updated — side-discoveries filed, resolved items closed.
- [ ] Post-merge state + observer obligations handled per CLAUDE.md, MANDATORY OBSERVATION LAYER.

## Linked issues / campaign

<!-- Closes #NNN, campaign doc path, related PRs -->

-
