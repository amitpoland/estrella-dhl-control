# Orchestration Router
# Read this before activating agents. Pick the route, read its row, activate only listed agents.
# Updated: 2026-05-19

## Routing matrix

| Route | Trigger keywords | Governance depth | Max agents | Topology | Required reviewers |
|-------|-----------------|-----------------|------------|----------|-------------------|
| `ui_only` | dashboard, HTML, CSS, button, modal | GATE 6 only | 5 | sequential | frontend-ui, button-functionality, browser-verifier |
| `backend_logic` | route, service, endpoint, FastAPI | GATES 1+6 | 7 | sequential | backend-api, testing-verification, security-permissions |
| `schema_change` | migration, ALTER TABLE, new column, DB schema | GATES 1+3+6 | 8 | sequential | database-storage, backend-api, testing-verification, integration-boundary |
| `deploy` | deploy, robocopy, nssm, Windows prod | 7-AGENT GATE | 7 | parallel then sequential | all 7 deploy_* agents |
| `governance_only` | CLAUDE.md, contracts, ADR, memory, lessons | GATE 2 check only | 3 | sequential | flow-context-keeper, memory-lessons |
| `queue_orchestrator` | campaign, multi-phase, audit, hardening | GATES 1–6 | 12 | parallel waves | chief-orchestrator + domain agents |
| `production_incident` | broken, down, 500, white screen, data loss | INCIDENT PROTOCOL | 5 | parallel | backend-api, security-permissions, deployment-windows-ops |
| `hotfix` | fix, patch, broken endpoint, regression | GATES 1+6 | 6 | sequential | backend-api, testing-verification, release-manager |

## Token optimization rules (binding, not suggestions)

1. **Snapshot-first**: every session reads PROJECT_STATE.md BEFORE any task work
2. **No repeated deploy prose**: use `windows_prod_v2.json` profile + delta manifest — never re-state robocopy commands inline
3. **No repeated governance prose**: cite contract file + rule number, do not re-quote full text
4. **Adaptive depth**: use minimum route from table above — do not upgrade to `queue_orchestrator` for single-file changes
5. **Compact-after-major-run**: after any 7+ agent campaign, run flow-context-keeper to update PROJECT_STATE.md; future sessions start from snapshot, not re-derived state
6. **Minimal sufficient agents**: every agent activation must map to a specific deliverable — no "advisory" activations
7. **Gate output contract**: every agent returns structured block per `.claude/contracts/gate_output_contract.md` — no prose-only verdicts
8. **One incident per registry entry**: DHL hooks, PR #227, Lesson D are in `incident_registry.md` — do not re-narrate inline

## Standard chain shortcuts

- **small UI fix**: `ui_only` → frontend-ui → browser-verifier → git-workflow → release-manager
- **API + DB**: `schema_change` → database-storage → backend-api → testing-verification → git-workflow
- **post-merge deploy**: `deploy` → 7-agent gate → windows_prod_v2 profile + delta manifest
- **governance update**: `governance_only` → flow-context-keeper → memory-lessons (no code agents)
