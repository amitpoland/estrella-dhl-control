# SKILL_REGISTRY.md — Atlas V2 Project Skills

**Source of truth for skills version-controlled in `.claude/skills/`.**
Generated 2026-06-06 by direct inspection. 8 project skills (ej-dashboard-design added 2026-07-04; ej-dashboard-fullstack-governance added 2026-07-04; ej-dashboard-webapp-testing added 2026-07-04; ej-dashboard-clean-code added 2026-07-04; ej-dashboard-master router added 2026-07-04).

> Skills are knowledge/governance surfaces, not actors. They tell an agent
> *how* to do something correctly; they do not themselves mutate production.

---

## Quick matrix

| Skill | Type | Allowed domains | Forbidden domains | Capability |
|---|---|---|---|---|
| `frontend-design` | Governance / standard | All UI work (V1 + V2 pages, new dashboard pages) | Backend logic, deploy decisions, financial/customs calc | Read-before-edit reference |
| `atlas-v2-render-gate` | Review / verification checklist | V2 (`/v2/`) post-deploy eyeball verification | Non-V2 surfaces; not a substitute for the deploy gate | Manual verification checklist |
| `ui-ux-pro-max` | Reference / search tool | UI/UX design ideas, accessibility, layout, palettes | Anything outside UI styling; stack defaults (Tailwind/TS) do NOT apply here | Search-only intelligence |
| `ej-dashboard-design` | Governance / project layer | EJ Dashboard V2 UI — authority resolution, canonical-file identification, tokens, cross-module consistency | Backend/deploy/financial-customs logic; creating new pages/authorities without written approval | Read-with-`frontend-design` governance |
| `ej-dashboard-fullstack-governance` | Governance / fullstack layer | Cross-layer changes on EJ Dashboard — route + service + persistence + UI together; stack lock; route→service→model mapping | New stack/scaffold (Next.js/TS/Tailwind/GraphQL/Postgres); protected-domain figures (financial/customs/accounting/inventory/shipment); bypassing `process_batch()`/master chain; authorizing a deploy | Read-before-edit governance |
| `ej-dashboard-webapp-testing` | Governance / verification | Safe browser testing of EJ Dashboard (`/v2/`) — server detection, networkidle waits, screenshot/console/network capture, structured report | Modifying application code; testing against production (:47213); destructive/write actions without approval; triggering financial/customs/accounting/shipment/inventory/document-generation flows | Read-only browser verification |
| `ej-dashboard-clean-code` | Governance / refactor | Clean-code / refactor / cleanup on EJ Dashboard — authority preservation, small scoped behavior-preserving changes, dependent inspection, repo-real verify | Over-engineering / new frameworks; unnecessary new files or duplicate helper layers; auto-fixing protected financial/customs/accounting/inventory/shipment/document-generation logic; non-repo-real tooling (eslint/prettier); proceeding past erroring validation | Read-before-edit refactor governance |
| `ej-dashboard-master` | Orchestration / router | Task classification + minimum-skill activation + inspect→plan→implement→verify→close for EJ Dashboard work | Owning craft/authority rules itself; replacing/duplicating the routed skills; loading every skill per task; editing protected domains without approval; authorizing a deploy | Skill-selection dispatcher (delegates, no craft rules) |

---

## Per-skill detail

### `frontend-design`
- **Purpose:** EJ Dashboard Portal design standard. Governs all UI work on `shipment-detail.html`, `dashboard.html`, and any new dashboard / V2 page.
- **Invocation context:** **Read before any UI implementation or review**, and before any `frontend-flow-reviewer` run. Mandatory for V2 shell-wiring sprints (e.g. Sprint 30 Inventory, Sprint 31 DHL).
- **Allowed domains:** Frontend / UI — CSS custom properties (`--bg`, `--text`, `--badge-*`), shared components (`Btn`, `Badge`, `Card`, `Sel`, `Toast`), test IDs, operator-visible flows.
- **Forbidden domains:** Backend logic, deploy decisions, financial/customs/wFirma calculation. Does not authorize generic stack defaults — **this project is vanilla HTML + Babel JSX (no bundler, no TypeScript, no Tailwind).**
- **Key rules it enforces:** CSS variables not hardcoded hex; shared components; every write button labels exactly what it writes; no auto-save; no fake readiness; no duplicate renderers; legacy sections in `<details>`; every interactive element has a `data-testid`.
- **Example:** "Before wiring the DHL Hub, read `frontend-design` to confirm the read-only panel pattern, testid convention, and no-write-button rule."

### `atlas-v2-render-gate`
- **Purpose:** Reusable post-deploy eyeball checklist for every sprint at `/v2/`. Run after every robocopy/Copy-Item sync to `C:\PZ\app\static\v2\` before declaring a sprint done.
- **Invocation context:** **After** a V2 static deploy, **before** declaring the sprint complete. Complements (does not replace) the 7-agent deploy gate and the automated browser smoke.
- **Allowed domains:** V2 render verification — page loads, no MOCK banner where wired, console clean, expected panels visible.
- **Forbidden domains:** Non-V2 surfaces; it is a verification aid, not a deploy authority. It cannot authorize a deploy.
- **Capability:** Manual checklist (operator/agent eyeball). Read-only.
- **Example:** "After deploying Sprint 31, run the atlas-v2-render-gate checklist against `/v2/dhl` to confirm the live hub renders with no MOCK banner."

### `ui-ux-pro-max`
- **Purpose:** UI/UX design intelligence search tool (styles, palettes, font pairings, charts, accessibility guidelines, layout best practices).
- **Invocation context:** Supplemental search during UI design. **Subordinate to `frontend-design`** (CLAUDE.md). Invoke via `python3 .claude/skills/ui-ux-pro-max/scripts/search.py`.
- **Allowed domains:** UI/UX styling ideas, accessibility, layout references.
- **Forbidden domains:** Anything outside UI styling. **Read `EJ_OVERRIDES.md` inside the skill dir before applying any output — stack defaults (Tailwind, TypeScript, shadcn/ui, Next.js, etc.) do NOT apply to this vanilla-JSX project.**
- **Capability:** Search-only reference; produces suggestions, not code that ships unreviewed.
- **Example:** "Search ui-ux-pro-max for accessible table patterns, then translate to the project's vanilla-JSX + CSS-variable stack per EJ_OVERRIDES."

### `ej-dashboard-design`
- **Purpose:** Project governance layer for EJ Dashboard Portal (Estrella Jewels / Atlas-v2) UI work. Enforces single-authority / routing-based canonical-file resolution, API + business-logic preservation, and design-system consistency across 25+ modules. Consistency across modules beats novelty on any single page.
- **Invocation context:** Consult **together with `frontend-design`** on every UI task — there is no automatic inheritance, so both must be active. Triggers on EJ Dashboard / EJ Portal / V2 pages / any `.jsx` under `service/app/static/`, and on "redesign / restyle / polish / clean up / modernize" requests. Run `/context` first (inspect router, canonical pages, shared components, API wiring).
- **Allowed domains:** V2 UI governance — canonical page identification, token/component reuse, visual change scoping, accessibility, responsive checks.
- **Forbidden domains:** Creating new pages/routes/components or duplicate authorities without written approval; changing API wiring or business logic as a side effect of a visual change; any financial/customs/accounting figure or logic change. Stack defaults (Tailwind/TS/bundler) do NOT apply.
- **Relationship / provenance:** `SKILL.md` (+ `README.md`, `tests/01..06`) is a **verbatim mirror** of the upstream `anthropic-skills:ej-dashboard-design` cloud plugin, installed 2026-07-04 for version control + reliable discovery. Local layer `EJ_OVERRIDES.md` binds its generic "existing tokens/components" to the canonical set in `frontend-design.md` §3 and the V2 authority map. **Precedence:** `frontend-design.md` wins token/stack/hard-rule conflicts; `ej-dashboard-design` wins architecture/authority/safety conflicts.
- **Key rules it enforces:** Resolve canonical routed page before editing (`pages.jsx` vs `pages-v2.jsx` via router, not filename age); never create duplicate/parallel components (`*New`/`*Modern`/`*V2`); preserve API wiring + business logic; no placeholder/hardcoded data; reuse existing tokens/components; match provided Figma exactly; keyboard-accessible + focus states; check desktop/tablet/mobile; subtle motion only.
- **Example:** "Before restyling the Inventory page, consult `frontend-design` + `ej-dashboard-design`; confirm `inventory-page.jsx` is the routed V2 authority via `components.jsx` NAV_TREE, then edit in place with existing tokens."

### `ej-dashboard-fullstack-governance`
- **Purpose:** Governance layer for **full-stack** changes on the EJ Dashboard — any change that crosses the backend↔frontend boundary (an endpoint plus its UI, "add a field end-to-end", a change touching route + service + persistence together). Forces inspect-first + a written route→service→model map, locks the stack, protects sensitive logic, and requires tests + rollback.
- **Invocation context:** Run `/context` first, then consult **together with `frontend-design` + `ej-dashboard-design`** on any cross-layer task (they own the frontend layer; this skill owns the cross-layer discipline). Triggers on "add X end-to-end", "wire X to the backend", "expose Y in the dashboard", new endpoint + UI, or route+service+persistence changes.
- **Allowed domains:** Cross-layer route + service + persistence + UI changes — chain mapping, stack-lock enforcement, authority preservation, test/rollback discipline.
- **Forbidden domains:** Introducing a new stack/framework/DB or scaffolding (Next.js, TypeScript, Tailwind, GraphQL, PostgreSQL, ORM, bundler, generators); changing protected-domain figures/logic (financial, customs, accounting, inventory, shipment) without confirmation; bypassing `process_batch()` or the Master→Mirror→wFirma chain; authorizing a production sync (that is the 7-agent deploy gate).
- **Relationship / provenance:** **Adapted from — NOT a copy of** — the generic `development/senior-fullstack` template (`claude-code-templates`). The generic template was never installed; each of its wrong-stack defaults is inverted into a hard prohibition and bound to this repo's real stack (FastAPI + one-SQLite-file-per-domain + vanilla Babel JSX). **Composes with** `frontend-design` + `ej-dashboard-design` (frontend), the 7-agent deploy gate (production), and Engineering Lessons A/E/G/J/N; on conflict, those authorities win.
- **Key rules it enforces:** `/context` + route→service→model map before edits; no new stack/scaffold; `process_batch()` is the only calc path; routes are thin callers, logic in services; `main.py` route registration; masters own product/customer data (no direct wFirma from a module); protected-domain changes are stop-and-confirm; a regression test for the changed route+service contract + a stated rollback (covering the separate `C:\PZ\engine\` sync) are mandatory before "done".
- **Example:** "To add a `warehouse_note` field to the inventory page, map UI (`inventory-page.jsx`) → `PzApi` → `routes_inventory.py` → `inventory_service.py` → `inventory_db.py` first, flag the new column as a schema change, add a response-shape regression test, and state the rollback — before writing any code."

### `ej-dashboard-webapp-testing`
- **Purpose:** Safely **browser-test** the EJ Dashboard Portal (`/v2/`) with Playwright-style automation. Detect a running server before starting one, prefer existing project run commands/logs/helper scripts, wait for networkidle before DOM inspection, capture screenshots + console errors + failed network requests, and produce a structured test report. Read-only verification — it does not fix or deploy.
- **Invocation context:** Run `/context` first. Triggers on "browser-test / smoke-test / verify a dashboard route or flow in the browser". This is the EJ-specific how-to for CLAUDE.md `preview_tools` + GATE 6 (browser-verification completeness). Composes with `frontend-design` / `ej-dashboard-design` (verifies their output) and `ej-dashboard-fullstack-governance` (a bug found → the *fix* routes there).
- **Allowed domains:** Browser verification of `/v2/` routes — navigation, DOM/console/network inspection, screenshots, running existing smoke helpers, writing a report under `tasks/smoke-reports/`.
- **Forbidden domains:** Modifying application code; testing against production (:47213 / `pz.estrellajewels.eu`); running destructive/write actions (Create PZ, Post/Convert/Submit to wFirma, Delete, Send, override) without explicit approval; triggering protected flows — financial, customs, accounting, shipment, inventory, and document-generation (PDF/XLSX); authorizing a deploy.
- **Relationship / provenance:** **Adapted from — NOT a copy of** — the generic `development/webapp-testing` template (`claude-code-templates`); the template was never installed. Only the discipline was kept and bound to this repo's run surfaces (`make dev` :8000; `.claude/launch.json` preview configs :8135/:8200/:8136; V2 at `/v2/`), helper scripts (`run_smoke.py`, `lifecycle_smoke_tests.py` — treated as black boxes, `--help` before source), and safety rules.
- **Key rules it enforces:** `/context` + state route/actions first; detect-before-start; local server only, never prod; prefer existing surfaces (Preview MCP / `run_smoke.py`) over hand-rolled flows; `--help` before reading helper source; wait for `networkidle` before inspection; capture screenshot + console errors + failed (4xx/5xx) requests; no app-code edits; no destructive/protected-flow trigger without approval; structured report (route · server · actions · result · evidence · failures · skipped).
- **Example:** "To verify the dashboard home: detect a running server (else start `pz-service-verify` :8135), open `/v2/dashboard`, wait for networkidle, capture a screenshot + console + network, confirm the KPI strip and six kanban lanes render with no MOCK banner, and write the report to `tasks/smoke-reports/` — triggering no write actions."

### `ej-dashboard-clean-code`
- **Purpose:** Governance for **clean-code / refactor / cleanup** on the EJ Dashboard — tidy existing code without changing what it does, where it lives, or who owns it. Preserves architecture/authority, refuses over-engineering and duplicate helper layers, requires dependent inspection before shared-file edits, keeps changes small and behavior-preserving, and gates on repo-real verification.
- **Invocation context:** Run `/context` first. Triggers on "clean up / refactor / simplify / de-duplicate / rename / tidy / improve code quality". Composes with `ej-dashboard-design` (frontend cleanups defer to it), `ej-dashboard-fullstack-governance` (cross-layer cleanups use its chain-mapping + test/rollback), and `ej-dashboard-webapp-testing` (browser re-verify after a UI-visible cleanup).
- **Allowed domains:** Behavior-preserving tidying — de-duplication of existing copies, readability, dead-code removal (non-protected), scoped renames with all dependents updated.
- **Forbidden domains:** Over-engineering (new frameworks/plugin/config/abstraction layers for single callers); unnecessary new files or duplicate helper layers; moving/blurring an authority (bypassing `process_batch()`, merging domain DBs, relocating routers, forking a canonical page); auto-fixing protected financial/customs/accounting/inventory/shipment/document-generation logic without approval; referencing non-repo-real tooling (no eslint/prettier/npm-lint here); proceeding past erroring validation; authorizing a deploy.
- **Relationship / provenance:** **Adapted from — NOT a copy of** — the generic `development/clean-code` template (`claude-code-templates`); the template was never installed. Only the discipline was kept and bound to this repo — crucially it references only repo-real gates (`make verify`, `make verify-full`, `pytest`), never generic clean-code scripts that don't exist in this no-bundler codebase.
- **Key rules it enforces:** `/context` + grep a shared file's dependents before editing; preserve `process_batch()` calc authority, per-domain SQLite, `main.py` registration, single V2 authority, master ownership; YAGNI (no framework/abstraction for one caller); reuse existing shared primitives (`components.jsx`/`pz-api.js`/`dashboard-shared.js`) — no duplicate helper; small scoped behavior-preserving changes; honor no-spread-rest + Babel-7 pin; protected-domain cleanups are approval-gated; run repo-real verify and report with counts; on validation errors, summarize and ask (no auto-cascade).
- **Example:** "To de-duplicate the batch status mappers: grep their callers, fold the repeated `_map*` bodies onto a shared lookup with one consistent fallback, keep them as plain functions in place (no framework/registry), run `make verify` to confirm the golden output is unchanged, and report the result — no new files, no authority moved."

### `ej-dashboard-master`
- **Purpose:** Master **router / orchestration** skill for EJ Dashboard work — classify the request, activate the **minimum** required project skills, and enforce inspect → plan → implement → verify → close. A dispatcher, NOT a super-skill: it owns no craft rules and delegates to the owning skill.
- **Invocation context:** Invoke at the **start** of a non-trivial EJ Dashboard task. Runs `/context` first, then names the minimum skills it is activating and why. Composes with `chief-orchestrator` / agent routing (it is the skill-selection layer, not a replacement).
- **Allowed domains:** Task classification, minimum-skill activation, workflow-gate enforcement, protected-trigger detection, duplicate-authority prevention.
- **Forbidden domains:** Authoring craft/authority rules of its own; replacing, restating, or duplicating the routed skills; loading every skill for every task; editing protected domains (financial/customs/accounting/shipment/inventory/document-generation/API-authority/persistence) without approval; authorizing a deploy.
- **Relationship / provenance:** Project-authored orchestration layer (no upstream template). Routes to `frontend-design` (UI craft), `ej-dashboard-design` (V2 governance), `ej-dashboard-fullstack-governance` (backend/fullstack + protected-domain), `ej-dashboard-clean-code` (scoped refactor + repo-real validation), `ej-dashboard-webapp-testing` (browser verify); `ui-ux-pro-max` is reference-only. On conflict the owning skill wins; CLAUDE.md GATES 1–6 + Engineering Lessons win over all; the 7-agent deploy gate owns production. Full task-type→skill mapping in the skill's `ARCHITECTURE_DECISION_MATRIX.md`.
- **Key rules it enforces:** `/context` before planning; **classify** the request into one category (Discussion / Question / Planning / Architecture Review / Code Review / UI / Backend / Full Stack / Refactoring / Browser Verification / Bug Investigation / Deployment / Documentation) before loading any skill; **discussion/planning/architecture-review load NO implementation skills** (answer directly); **Minimum Skill Principle** — never more than TWO skills unless genuinely multi-domain (UI→`frontend-design`+`ej-dashboard-design`, backend→`fullstack-governance`+`clean-code`, refactor→`clean-code`+domain, code-review→`clean-code`, browser→`webapp-testing`); `ui-ux-pro-max` reference-only, never an authority; show a **confidence report** before implementing; **protected-domain** trigger → stop and ask before editing; **no duplicate** page/route/API/state or parallel `*New`/`*Modern`/`*V2`/`*Next` component without approval; **conflict resolution** — `frontend-design` wins tokens/styling/typography, `ej-dashboard-design` wins page/routing/governance, `ej-dashboard-fullstack-governance` wins backend/API/persistence, `ej-dashboard-clean-code` wins refactor/repo-safety, `ej-dashboard-webapp-testing` wins verification, `ui-ux-pro-max` never overrides. Workflow: Inspect→Classify→Skill Selection→Plan→Implement→Verify→Close. **Session-aware:** Session Bootstrap at session start (inspect repo + **inspect active campaigns** via `ACTIVE_CAMPAIGNS.md` + detect skills + build/cache the routing table, NO implementation skill loaded until the first task is classified); **Dynamic Routing** (on each user pivot, unload the prior task's skills and load only the new minimum set); **Skill Lifecycle** `Available→Selected→Active→Completed→Released` — release every Active skill from context at Close. **Four state surfaces:** Skill Registry, **Active Campaign Registry** (`ACTIVE_CAMPAIGNS.md` — state registry, not a planning tool; an index into the authoritative campaign docs; read at bootstrap/task-start so long-running campaigns are **continued, not restarted**), Architecture Decision Matrix, and Skill Freeze Policy. The campaign registry is NOT a new skill — it does not affect the freeze.
- **Example:** "For 'add a `warehouse_note` field end-to-end': classify as Full Stack (the only >2-skill case) → activate the design pair + `ej-dashboard-fullstack-governance` (+ `clean-code`); the new DB column trips the persistence trigger → stop and ask before the schema change; verify with `make verify` + `ej-dashboard-webapp-testing`. For 'should the accounting hub own ledger state?' → classify as Architecture Review → discussion only, no implementation skills, answer directly."

---

## Safety rule (binding)

Skills inform; they do not act. A skill never authorizes a production mutation or a
deploy. UI suggestions from `ui-ux-pro-max` must be filtered through `frontend-design` +
`EJ_OVERRIDES.md` before any code is written. The deploy gate, not a render-gate checklist,
authorizes production.

---

## Skill Freeze Policy

**Status: FROZEN (2026-07-04).** The seven-skill EJ Dashboard skill architecture is complete:
`frontend-design`, `ej-dashboard-design`, `ej-dashboard-fullstack-governance`,
`ej-dashboard-clean-code`, `ej-dashboard-webapp-testing`, `ui-ux-pro-max` (reference), and the
`ej-dashboard-master` orchestrator.

No new project skill may be added unless **all** of the following hold:
- a recurring problem has been observed in real development,
- the problem cannot be solved by the existing skills, and
- an architectural review approves the new skill.

Generic third-party skills must **never** be installed directly (no raw `npx …templates`
installs). Only EJ-specific adaptations of external skill philosophy are permitted, following
the pattern of the existing `ej-dashboard-*` skills. This policy exists to keep the ecosystem
controlled and prevent skill sprawl. The next investment is implementation value (React
migration, wireframe parity, workflow stabilization), not new skills.
