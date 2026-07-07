# 02 — Council Registry

**Councils review; they do not implement.** A council is a standing set of review agents with
a mandate, a blocking authority, and an explicit non-power (it cannot mutate). Councils are
convened by the Executive Coordinator (`01`) and report verdict blocks. Membership is drawn
from `.claude/agents/AGENT_REGISTRY.md` (the source of truth for agents).

> A council seat **recommends**. The operator + the 7-agent deploy gate **act**. Runtime-only
> members (e.g. `system-architect`, `browser-verifier`, `testing-verification`) are helpers
> whose output must be independently verified (Lesson B).

---

## Council roster

| Council | Members (agents) | Mandate | May BLOCK on | May NOT |
|---|---|---|---|---|
| **Architecture** | `system-architect` (runtime), `reviewer-challenge`, `integration-boundary`, `gap-hunter` / `gap-detection` | Fit with existing FastAPI + SQLite + JSX + wFirma/DHL; authority preservation; no duplicate authority | duplicate authority, bypass of `process_batch()`, unregistered router, cross-authority guard with no business rule | implement; author craft rules a skill owns |
| **Backend & Persistence** | `backend-safety-reviewer`, `backend-route-inspector`, `service-scheduler-inspector`, `api-wrapper-inspector`, `deploy-persistence-storage-reviewer` | Safe writes, idempotency, real paths, `main.py` registration, schema-change discipline | unsafe write, missing idempotency, unregistered route, undisclosed schema mutation | run migrations; deploy |
| **Frontend** | `frontend-flow-reviewer`, `frontend-authority-inspector`, `navigation-inspector`, `ux-flow` | One canonical URL per module, no hidden actions, testids, no capability suppression (Lesson M) | duplicate page, hidden/suppressed capability without cancellation record, direct unsafe API call | edit styling itself (defers to `frontend-design`) |
| **Security & Write-risk** | `security-write-action-reviewer`, `deploy-security-reviewer` | Credentials, auth guards, write gates, operator identity, injection, fiscal-write gating | credential exposure, auth removal/bypass, ungated fiscal write, injection vector | be overridden by any other council (security blockers are terminal) |
| **Test & Verification** | `test-coverage-reviewer`, `browser-verifier` (runtime), `testing-verification` (runtime), `deploy-qa-reviewer` | Regression + negative cases + browser proof; test failure is an unconditional blocker | failing regression, missing negative case, unverified UI flow (GATE 6) | mark done without evidence; deploy |
| **Deploy (7-agent gate)** | `deploy-git-diff-reviewer`, `deploy-backend-impact-reviewer`, `deploy-persistence-storage-reviewer`, `deploy-security-reviewer`, `deploy-qa-reviewer`, `deploy-release-manager` → `deploy-lead-coordinator` | Production go/no-go for any sync to `C:\PZ` | any forbidden-path edit, security blocker, failing test, missing rollback | this council **is** the only deploy authority; see `08` |
| **Governance & State** | `flow-context-keeper`, `agent-performance-observer`, `adr-historian` | PROJECT_STATE currency, scorecards, ADRs, lesson capture | (advisory) unrecorded decision, uncited scorecard (RULE 6) | implement; gate production |

---

## Convening rules

1. **Fast Path** convenes a **minimal** council set — typically the one domain council plus
   Security if any write is touched (see `06`). It does not convene all councils.
2. **Deep Path** convenes the full relevant set in **parallel** (single dispatch message so
   they run concurrently — token + latency economy, `09`).
3. **Every HIGH/CRITICAL finding** must be resolved inline OR escalated to the operator before
   PR-open (GATE 1). "Recommendation noted" is not a disposition (GATE 4 — SCHEDULED / ISSUE /
   REJECTED).
4. **Security blockers are terminal** — no other council, including Deploy-lead, overrides them.
5. **Substitution disclosure (GATE 5):** if a named council member is unavailable, the
   substitute is named explicitly with capability-equivalence stated. Silent substitution is
   forbidden.

## Non-powers (all councils)

- No council edits application code, runs a migration, or authorizes a sync.
- No council invents a craft rule a skill already owns (it defers to the skill).
- A council verdict is advisory to the Coordinator except where a GATE makes it terminal
  (security, failing tests, forbidden-path).
