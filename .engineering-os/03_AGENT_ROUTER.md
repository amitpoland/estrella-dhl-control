# 03 — Agent Router

**Source of truth:** `.claude/agents/AGENT_REGISTRY.md` (refreshed 2026-07-08: 27 repo agents,
54 global runtime agents). This file is the *routing view* over that registry — it says which
agents execute which package type, and under which constraints. It does not duplicate the
registry.

> Agents execute within skill contracts (`04`) and within their capability class. Only
> repo-canonical agents are governed; runtime-only (global / plugin / built-in) agents are
> **never final authority** (Lesson B).

---

## 1. Capability classes (what an agent is allowed to do)

| Class | Meaning | Examples |
|---|---|---|
| **INSPECT-ONLY** | reads + reports; never edits | `backend-route-inspector`, `frontend-authority-inspector`, `navigation-inspector`, `service-scheduler-inspector`, `api-wrapper-inspector`, all `deploy-*` reviewers, `reviewer-challenge`, `gap-hunter` |
| **RUNTIME WRITE-CAPABLE** | can edit/build; runtime-only, never final authority | `backend-api`, `frontend-ui`, `database-storage`, `wfirma-integration`, `git-workflow` (global registry) |
| **SCOPED-IMPLEMENTER** | edits exactly one declared slice, hard-fenced | `reports-authority-implementer`, `shipment-authority-implementer` — guarded by `implement-guard.py` + `EJ_IMPLEMENT=1` + one-slice-then-STOP; **cannot** commit/push/PR/deploy |
| **GOVERNANCE / STATE** | writes docs/state, not app code | `flow-context-keeper`, `agent-performance-observer`, `adr-historian` |

---

## 2. By-package-type routing (lead + parallel reviewers + gate)

| Package type | Lead executor | Reviewers (parallel council) | Gate |
|---|---|---|---|
| **Frontend / UI** | `frontend-ui` | `frontend-flow-reviewer`, `frontend-authority-inspector`, `navigation-inspector`, `ux-flow`, `reviewer-challenge` | browser verify → deploy gate |
| **Backend / API** | `backend-api` | `backend-safety-reviewer`, `backend-route-inspector`, `service-scheduler-inspector`, `api-wrapper-inspector` | `test-coverage-reviewer` → deploy gate |
| **Database / schema** | `database-storage` | `deploy-persistence-storage-reviewer`, `backend-safety-reviewer` | deploy gate (persistence reviewer) |
| **wFirma / integrations** | `wfirma-integration` | `security-write-action-reviewer`, `deploy-security-reviewer` | deploy gate |
| **Write-action / fiscal** | domain actor (e.g. `sales-proforma`, `pz-purchase-accounting`) | `security-write-action-reviewer` (mandatory), `reviewer-challenge`, `integration-boundary` | deploy gate |
| **Deployment** | the 7 `deploy-*` agents | — | `deploy-lead-coordinator` go/no-go |
| **Testing** | `testing-verification`, `browser-verifier` | `test-coverage-reviewer`, `deploy-qa-reviewer` | — |
| **Architecture / design** | `system-architect` | `reviewer-challenge`, `integration-boundary`, `gap-hunter` | — |
| **UX / product review** | `ux-flow` | `frontend-flow-reviewer`, `reviewer-challenge` | — |
| **Scoped code slice** | `reports-` / `shipment-authority-implementer` (via `/implement-slice`) | matching domain reviewer | deploy gate |
| **Governance / post-run** | `flow-context-keeper` | `agent-performance-observer`, `adr-historian` | — |

---

## 3. Routing rules

1. **Manifest first.** Do not route agents until the capability manifest is loaded (`00 §1.7`).
2. **Minimum agents.** Route the smallest set that covers the package. Fast Path routes one
   lead + minimal reviewers; Deep Path routes the full council (`06`, `09`).
3. **Negative scope for write-capable agents (Lesson K).** Every dispatch to a write-capable
   agent names forbidden commands explicitly ("read and report only" is insufficient on its own).
4. **Parallel dispatch.** Independent inspectors/reviewers are dispatched in one message so they
   run concurrently.
5. **Scoped-implementers only via `/implement-slice`.** They run one declared slice, under the
   guard, then STOP — never chained.

---

## 4. Known registry hazards (carry from AGENT_REGISTRY.md 2026-07-08)

- **Duplicate registrations (5):** `final-consistency-review`, `gap-detection`,
  `integration-boundary`, `reviewer-challenge`, `ux-flow` exist in **both** the repo
  (inspect-only) and global (Bash-capable) trees. A dispatch may hit the wrong copy — prefer a
  fresh session after any agent-file change; treat these as runtime-backed until confirmed.
- **Mid-session availability (Lesson B):** agents added mid-session are not reliably invocable
  until a session restart. Do not assume a just-added agent is dispatchable.
- **Model pins:** 7 repo agents and all 54 global agents are model-pinned; a pin change is an
  agent-file change (out of scope for any OS docs package).
