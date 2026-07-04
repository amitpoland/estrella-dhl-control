# SKILL_REGISTRY.md — Atlas V2 Project Skills

**Source of truth for skills version-controlled in `.claude/skills/`.**
Generated 2026-06-06 by direct inspection. 5 project skills (ej-dashboard-design added 2026-07-04; ej-dashboard-fullstack-governance added 2026-07-04).

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

---

## Safety rule (binding)

Skills inform; they do not act. A skill never authorizes a production mutation or a
deploy. UI suggestions from `ui-ux-pro-max` must be filtered through `frontend-design` +
`EJ_OVERRIDES.md` before any code is written. The deploy gate, not a render-gate checklist,
authorizes production.
