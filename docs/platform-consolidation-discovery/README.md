# EJ PLATFORM CONSOLIDATION DISCOVERY — Campaign Index

**Goal:** A complete authority map of the V1/V2 platform + data-driven consolidation guidance for the next ~12 months.
**Inspected:** `origin/main @ fb70e15` (clean detached worktree, read-only). **Date:** 2026-06-18.
**Scope:** Discovery only — **no code changes, no PRs, no migrations, no fixes to PR #630.** These documents are **untracked** in this tree; review and commit them on a dedicated branch when ready.

## Deliverables
1. **[AUTHORITY_MAP.md](./AUTHORITY_MAP.md)** — route→service→persistence→auth ownership; frontend entry points by generation; external integration boundaries; duplicate-authority flags.
2. **[V1_V2_CAPABILITY_MATRIX.md](./V1_V2_CAPABILITY_MATRIX.md)** — per-workflow comparison across the four frontend surfaces; gap & redundancy registers.
3. **[DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md)** — duplicate modules/surfaces with live-vs-orphaned status + DC/M/D risk; conflicting-authority cases.
4. **[MIGRATION_ROADMAP.md](./MIGRATION_ROADMAP.md)** — KEEP V1 / KEEP V2 / MERGE / REBUILD / RETIRE per module; migration waves; the headline decision.

### Governance layer (binding — built on the four discovery docs above)
5. **[AUTHORITY_DECISION_FRAMEWORK.md](./AUTHORITY_DECISION_FRAMEWORK.md)** — the single binding view: consolidated authority map, Atlas decision brief, KEEP/MERGE/REBUILD/RETIRE criteria, leadership sign-off checklist (D-1…D-7), escalation protocol, conflict-to-impact register, wave traceability. **Every migration work item must cite a decision/conflict ID from here.**
6. **[REVERSIBILITY_AND_ROLLBACK_FRAMEWORK.md](./REVERSIBILITY_AND_ROLLBACK_FRAMEWORK.md)** — per-wave rollback checkpoint design, production conflict-detection triggers, templated rollback runbook, discovery-log format, and shadow-mode strategy (reuses the repo's existing carrier shadow-mode pattern). Makes each wave a reversible experiment, not a point of no return.

> Scope note: the six conceptually-named outputs from the decision brief (WORKFLOW_AUTHORITY_MATRIX, UI_SURFACE_DECISION_MATRIX, DUPLICATE_AUTHORITY_REGISTER, BACKEND_AUTHORITY_CONFLICT_REPORT, ATLAS_PLATFORM_DECISION_BRIEF, CONSOLIDATION_WAVE_PLAN) are **consolidated into docs 1–5** rather than duplicated as separate files. Each is cross-referenced by name where its content lives.

## Headline answer for leadership
**V2-FIRST — already decided and substantially executed.** The platform is **one shared FastAPI backend** (the stable layer, "do not rewrite") under a **frozen V1 monolith** plus a **fragmented V2** of three parallel expressions (Track-1 `*-v2.html`, Track-2 `/v2/` JSX shell at WIRED_PAGES 17/17, and an Atlas stub shell). The strategic work is therefore twofold: finish migrating off V1 **and** collapse the V2 fragmentation into one surface with one shared-library source.

## Top findings
- **HIGH (backend):** `routes_wfirma._compute_effective_pz_status` duplicates `operational_authority.derive_pz_status` with extra "Path B" logic → the wFirma PZ-create guard can disagree with dashboard readiness. The only backend authority divergence.
- **HIGH (frontend):** forked `pz-api.js` (263 vs 566 ln), dual **live** proforma write surfaces (Track-1 lacks the readiness pre-check), and two live renderers each for shipment-detail and dashboard.
- **Coverage gaps (backend exists, no UI anywhere):** inventory returns + sample writes, reservation-queue management. **Missing backends:** cross-batch `GET /api/v1/documents`, cross-batch PZ list, CMR/packing PDF generation, DHL live label adapter (Phase D). **No backing at all:** consignment.
- **Cleanup:** identical orphaned `v2/dashboard-shared.js` (ADR-028); orphaned MOCK `shipment-detail-page.v1/v2.jsx`, `shipping-ops.jsx`.

## Open questions (operator decision)
OQ-1 PZ-correction campaign collision · OQ-2 `shipment-detail-v3.html` disposition · OQ-3 `master-data-v2` vs `customer-master-v2` overlap · OQ-4 `reports` shell page source · OQ-5 formalize ADR-028 · OQ-6 reconcile MOCK-audit (2026-06-06) vs WIRED_PAGES 17/17.

## Method & caveats
Inspected the canonical `origin/main` tree read-only via `git ls-files`/`grep`/`git show` (Glob was sandbox-blocked for the external worktree). Every concrete claim carries `file:line` evidence; unverified items are marked **GAP:**. Findings synthesized from four parallel inspection agents and cross-referenced against existing in-repo intelligence (`docs/v2-architecture-plan.md`, `docs/system_inventory_and_ui_plan.md`, `docs/proforma-workspace-consolidation-plan.md`, `docs/architecture/authority-ownership-and-incident-classes.md`, `MOCK_PAGE_AUTHORITY_AUDIT.md`, `.claude/adr/ADR-028/029`, `.claude/campaigns/atlas-v2`). Note: `origin/main` advanced `03ffce9 → fb70e15` during this session (a separate concern for the PR #630 hold).
