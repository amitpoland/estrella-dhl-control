# SKILL_REGISTRY.md — Atlas V2 Project Skills

**Source of truth for skills version-controlled in `.claude/skills/`.**
Generated 2026-06-06 by direct inspection. 3 project skills.

> Skills are knowledge/governance surfaces, not actors. They tell an agent
> *how* to do something correctly; they do not themselves mutate production.

---

## Quick matrix

| Skill | Type | Allowed domains | Forbidden domains | Capability |
|---|---|---|---|---|
| `frontend-design` | Governance / standard | All UI work (V1 + V2 pages, new dashboard pages) | Backend logic, deploy decisions, financial/customs calc | Read-before-edit reference |
| `atlas-v2-render-gate` | Review / verification checklist | V2 (`/v2/`) post-deploy eyeball verification | Non-V2 surfaces; not a substitute for the deploy gate | Manual verification checklist |
| `ui-ux-pro-max` | Reference / search tool | UI/UX design ideas, accessibility, layout, palettes | Anything outside UI styling; stack defaults (Tailwind/TS) do NOT apply here | Search-only intelligence |

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

---

## Safety rule (binding)

Skills inform; they do not act. A skill never authorizes a production mutation or a
deploy. UI suggestions from `ui-ux-pro-max` must be filtered through `frontend-design` +
`EJ_OVERRIDES.md` before any code is written. The deploy gate, not a render-gate checklist,
authorizes production.
