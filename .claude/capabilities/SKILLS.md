# SKILLS.md — Atlas V2 Capability Registry: All Skills

**Generated:** 2026-06-06 · **Source:** direct filesystem inspection of `.claude/skills/` + `~/.claude/skills/`
**Canonical tree:** `C:\PZ-verify` · No product code modified.

---

## Overview

Skills are **knowledge/governance surfaces**, not actors. They tell an agent *how* to do
something correctly; they do not themselves mutate production. A skill's output must always
pass through the appropriate implementation gate before any code ships.

| # | Skill | Location | Type | Capability tier |
|---|---|---|---|---|
| 1 | `frontend-design` | REPO `.claude/skills/` | Governance / Standard | SAFE_READ_ONLY |
| 2 | `atlas-v2-render-gate` | REPO `.claude/skills/` | Review / Checklist | SAFE_READ_ONLY |
| 3 | `ui-ux-pro-max` | REPO `.claude/skills/` | Reference / Search | SAFE_READ_ONLY |
| 4 | `ej-dashboard-design` | REPO `.claude/skills/` | Governance / project layer | SAFE_READ_ONLY |
| 5 | `senior-architect` | USER `~/.claude/skills/` | Reference / Scripts | SAFE_READ_ONLY |

---

## Repo Skills (`C:\PZ-verify\.claude\skills\`)

---

### S1. `frontend-design`

| Field | Value |
|---|---|
| **Name** | `frontend-design` |
| **Source** | REPO · `C:\PZ-verify\.claude\skills\frontend-design.md` |
| **Version** | original repo install |
| **Type** | Governance standard — EJ Dashboard Portal UI design rules |
| **Purpose** | Governs all UI work on `shipment-detail.html`, `dashboard.html`, and any V2 page. Enforces CSS custom properties, shared components, testid conventions, no-auto-save rule, no fake readiness, operator-visible flow discipline. |
| **Tools granted** | None — read-only reference document |
| **R/W level** | READ-ONLY reference |
| **Production risk** | NONE — informs; never mutates |
| **Dispatchable** | N/A — invoked by reading the file, not via Agent tool |
| **Tested** | ✅ referenced in Sprint 30/31/32 implementations |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | **Read BEFORE any UI implementation or frontend-flow-reviewer run.** Mandatory for all V2 shell-wiring sprints. Governs both V1 (frozen) and V2 (active). |
| **Forbidden use** | Does not authorize generic stack defaults. This project is vanilla HTML + Babel JSX — NO TypeScript, NO Tailwind, NO bundler. Does not govern backend logic, deploy decisions, or financial calculations. |
| **Key rules enforced** | CSS variables (`--bg`, `--text`, `--badge-*`) not hardcoded hex · shared components (`Btn`, `Badge`, `Card`, `Sel`, `Toast`) · every write button labels exactly what it writes · no auto-save · no fake readiness · no duplicate renderers · legacy sections in `<details>` (collapsed) · every interactive element has `data-testid` |
| **Stack constraint** | Vanilla HTML + Babel JSX (React 18 CDN). No bundler, no TypeScript, no Tailwind. CLAUDE.md `Frontend Design Standard`. |

---

### S2. `atlas-v2-render-gate`

| Field | Value |
|---|---|
| **Name** | `atlas-v2-render-gate` |
| **Source** | REPO · `C:\PZ-verify\.claude\skills\atlas-v2-render-gate.md` |
| **Version** | original repo install |
| **Type** | Review / verification checklist |
| **Purpose** | Reusable post-deploy eyeball checklist for every Atlas V2 sprint at `/v2/`. Run after every robocopy/Copy-Item sync to `C:\PZ\app\static\v2\` before declaring a sprint done. |
| **Tools granted** | None — manual checklist |
| **R/W level** | READ-ONLY reference / manual verification |
| **Production risk** | NONE — informs; never mutates |
| **Dispatchable** | N/A — human/operator-executed checklist |
| **Tested** | ✅ referenced in Sprint 30/31/32 smoke verification |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | **After** a V2 static deploy, **before** declaring the sprint complete. Complements (does not replace) the 7-agent deploy gate and automated browser smoke. |
| **Forbidden use** | Not a substitute for the deploy gate. Cannot authorize a deploy. Non-V2 surfaces. |
| **Checklist items** | (1) Shell loads clean, zero red console errors · (2) MOCK banners on all un-wired pages · (3) Pro Forma loads real data · (4) Network clean (no 4xx/5xx) · (5) Hard-refresh idempotency · (6) Responsive layout 1280px · (7) Deep-link + hard-refresh check · (8) Pro Forma table columns eyeball |
| **Wired pages (live)** | proforma (Sprint 1) · proforma_detail (Sprint 1) · inbox (Sprint 2B) · inventory (Sprint 30) · dhl (Sprint 31) · shipments (Sprint 32) |
| **Update rule** | The "Wired pages" table must be updated as each sprint adds a live domain. The skill file itself is the living checklist. |
| **Health watchdog note** | Must disable `PZService-HealthWatchdog` Task Scheduler task before deploy; re-enable after. Exact name matters — wrong name fails silently. |

---

### S3. `ui-ux-pro-max`

| Field | Value |
|---|---|
| **Name** | `ui-ux-pro-max` |
| **Source** | REPO · `C:\PZ-verify\.claude\skills\ui-ux-pro-max\` |
| **Version** | original repo install |
| **Type** | Reference / search tool |
| **Purpose** | UI/UX design intelligence search tool. Provides styles, palettes, font pairings, chart patterns, accessibility guidelines, layout best practices, and UX reasoning examples. |
| **Tools granted** | Python script invocation: `python3 .claude/skills/ui-ux-pro-max/scripts/search.py` |
| **R/W level** | READ-ONLY reference (script reads local CSV data only) |
| **Production risk** | NONE — search + suggest only |
| **Dispatchable** | N/A — invoked via CLI script |
| **Tested** | ✅ installed + referenced in CLAUDE.md |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | Supplemental search during UI design. Accessibility ideas, layout options, palette choices, chart type selection. |
| **Forbidden use** | **Read `EJ_OVERRIDES.md` BEFORE applying any output.** Stack defaults (Tailwind, TypeScript, shadcn/ui, Next.js, React Native) do NOT apply to this vanilla-JSX project. Anything outside UI styling. |
| **Subordination rule** | Subordinate to `frontend-design` (CLAUDE.md). Any suggestion must be translated to vanilla-JSX + CSS-variable stack per EJ_OVERRIDES before shipping. |
| **Data files** | `data/charts.csv` · `data/colors.csv` · `data/icons.csv` · `data/ux-guidelines.csv` · `data/typography.csv` · `data/styles.csv` · `data/stacks/*.csv` (stack-specific; most do not apply) · `data/react-performance.csv` · `data/landing.csv` · `data/prompts.csv` |
| **Override file** | `EJ_OVERRIDES.md` — must be read before applying any output |

---

### S4. `ej-dashboard-design`

| Field | Value |
|---|---|
| **Name** | `ej-dashboard-design` |
| **Source** | REPO · `C:\PZ-verify\.claude\skills\ej-dashboard-design\` (`SKILL.md` + `README.md` + `EJ_OVERRIDES.md` + `tests/01..06`) |
| **Version** | 1.0.0 — verbatim mirror of upstream `anthropic-skills:ej-dashboard-design` cloud plugin, installed 2026-07-04 for version control + reliable discovery |
| **Type** | Governance / project layer — EJ Dashboard Portal UI safety & consistency |
| **Purpose** | Layers project-specific guardrails on top of `frontend-design`: routing-based canonical-file resolution (`pages.jsx` vs `pages-v2.jsx`), single-authority enforcement, API + business-logic preservation, token/component reuse across 25+ modules. Consistency across modules beats novelty on any one page. |
| **Tools granted** | None — read-only governance document (+ `tests/` worked examples) |
| **R/W level** | READ-ONLY reference |
| **Production risk** | NONE — informs; never mutates |
| **Dispatchable** | N/A — invoked via `/ej-dashboard-design` or by reading the file; not via Agent tool |
| **Tested** | ✅ ships with six governance test prompts (`tests/01..06`); local install verified 2026-07-04 |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | **Consult together with `frontend-design` on every UI task** — no automatic inheritance; both must be active. Run `/context` first, then `/frontend-design`, then `/ej-dashboard-design`. |
| **Forbidden use** | Does not authorize creating new pages/routes/components or duplicate authorities without written approval; does not authorize API-wiring or business-logic changes as a side effect of visual work; no financial/customs/accounting figure or logic change. Stack defaults (Tailwind/TS/bundler) do NOT apply. |
| **Key rules enforced** | Resolve canonical routed page before editing · never create parallel/renamed components (`*New`/`*Modern`/`*V2`) · preserve API wiring + business logic · no placeholder/hardcoded data · reuse existing tokens/components · match provided Figma exactly · keyboard-accessible + visible focus · desktop/tablet/mobile · subtle motion only |
| **Precedence** | `frontend-design.md` wins token/stack/hard-rule conflicts; `ej-dashboard-design` wins architecture/authority/safety conflicts. |
| **Override file** | `EJ_OVERRIDES.md` — binds the skill's generic "existing tokens/components" to `frontend-design.md` §3 token set + the V2 authority map; read before applying output. |
| **Stack constraint** | Vanilla HTML + Babel JSX (React CDN). No bundler, no TypeScript, no Tailwind. |

---

## User Skills (`C:\Users\Super Fashion\.claude\skills\`)

---

### S5. `senior-architect`

| Field | Value |
|---|---|
| **Name** | `senior-architect` |
| **Source** | USER · `C:\Users\Super Fashion\.claude\skills\senior-architect\` |
| **Version** | user-level install (not version-controlled in this repo) |
| **Type** | Reference / architecture scripts |
| **Purpose** | Architecture diagram generation, project analysis, dependency analysis. References for architecture patterns, system design workflows, tech decision frameworks. |
| **Tools granted** | Python scripts: `architecture_diagram_generator.py`, `project_architect.py`, `dependency_analyzer.py` |
| **R/W level** | READ + script execution (generates diagrams/reports, no product-code writes) |
| **Production risk** | LOW — output is diagrams/reports, not product mutations |
| **Dispatchable** | N/A — invoked via CLI scripts |
| **Tested** | ⚠️ not verified in EJ context |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | Architecture planning, system design diagrams, dependency mapping. Generic reference only. |
| **Forbidden use** | **Stack defaults in this skill (TypeScript, Next.js, Docker, Kubernetes, PostgreSQL, Prisma, AWS/GCP/Azure) do NOT apply to this project.** This project is Python FastAPI + vanilla-JSX + SQLite + Windows NSSM. Apply `EJ_OVERRIDES.md` principles before using any recommendations. Not for EJ-specific business logic design (use CLAUDE.md + `.claude/agents/` for that). |
| **Tech stack advertised** | TypeScript, JavaScript, Python, Go, Swift, Kotlin, React, Next.js, Node.js, Express, GraphQL, PostgreSQL, Prisma, Docker, Kubernetes — most do not apply. |

---

## Skills Interaction Rules

1. **`frontend-design` governs everything `ui-ux-pro-max` suggests.** Never ship a ui-ux-pro-max suggestion directly without checking it against the EJ stack and frontend-design rules.
0. **`frontend-design` + `ej-dashboard-design` are consulted together on every UI task.** `frontend-design` governs visual craft (what is allowed + the canonical tokens); `ej-dashboard-design` governs project architecture/safety (canonical-file resolution, single authority, API/business-logic preservation). No automatic inheritance — both must be active. On conflict: `frontend-design.md` wins tokens/stack/hard-rules; `ej-dashboard-design` wins architecture/authority/safety.
2. **`atlas-v2-render-gate` is a quality gate, not an authorization gate.** Passing the render-gate checklist is a necessary condition for sprint closure, but the 7-agent deploy gate is the sufficient condition for production authorization.
3. **`senior-architect` is generic infrastructure.** Any architecture recommendation must be translated to the EJ stack (FastAPI + SQLite + Vanilla JSX + Windows NSSM + Cloudflare tunnel) before implementation.
4. **Skills inform; they do not act.** A skill never authorizes a production mutation or a deploy.

---

## Known Gaps

| Gap | Impact | Recommendation |
|---|---|---|
| No V2 API contract skill | Sprint authority audits must grep `routes_*.py` manually | File when a contract-first sprint begins |
| No test-pattern skill | Test structure varies across sprints | Document in a `test-patterns.md` after Sprint 33+ |
| `atlas-v2-render-gate` wired-pages table is stale | Shows only `proforma` + `proforma_detail`; 4 more sprints wired | Update render-gate skill file to Sprint 32 state |
