# EJ Dashboard Portal — Project Overrides for ej-dashboard-design

**Status**: These overrides are BINDING for all EJ frontend work.
They bind the generic guidance in this folder's `SKILL.md` to the concrete
EJ token set, stack, and V2 authority map of THIS repository.
Full binding EJ design standard: `.claude/skills/frontend-design.md`.

> `SKILL.md` in this folder is a **verbatim mirror** of the upstream
> `anthropic-skills:ej-dashboard-design` plugin (SKILL.md + README.md +
> `tests/01..06`). It was copied faithfully — no bundled assets were missing.
> Do not edit `SKILL.md` to add project specifics; put them here instead, so the
> mirror can be re-synced against upstream without losing local overrides.

---

## 0. Authority precedence (read this first)

Highest authority first — this resolves the "which skill wins" question for
this repo concretely:

1. **`.claude/skills/frontend-design.md`** — the binding EJ design standard AND the
   canonical token set (§3). When `SKILL.md` (this folder) says *"reuse this
   project's existing design tokens / shared components,"* **"this project's tokens"
   means the `:root` custom properties in `frontend-design.md` §3** — not a
   generic guess and not tokens invented per page. `frontend-design.md` wins any
   token / stack / hard-rule conflict.
2. **`ej-dashboard-design` (`SKILL.md`, this folder)** — governs *architecture and
   safety*: single-authority resolution, routing-based canonical-file
   identification, API/business-logic preservation, no-duplicate-page rules, and
   the ambiguity/ask-trigger policy. It wins over generic craft instinct on
   anything touching architecture, tokens, or existing business logic.
3. **`ui-ux-pro-max`** — supplemental search only (accessibility, layout ideas),
   filtered through its own `EJ_OVERRIDES.md`.

There is **no automatic inheritance** between the `frontend-design` craft layer and
this governance layer — both must be consulted together on every UI task.

---

## 1. Stack Override (Critical)

The upstream `SKILL.md` is codebase-aware but stack-agnostic in wording. On this
repo the stack is fixed and non-negotiable:

| Generic / default assumption | EJ actual |
|------------------------------|-----------|
| npm / bundler build | **No bundler — single-file CDN delivery, JSX in `<script type="text/babel">`** |
| TypeScript / `.tsx` | **Plain JS / `.jsx` only — no type annotations** |
| Tailwind utility classes | **CSS custom properties only** (`--bg`, `--text-*`, `--badge-*`, `--accent`, `--sidebar-*`) |
| shadcn / MUI / component libs | **Shared primitives**: V2 → `static/v2/components.jsx`; V1 → `static/dashboard-shared.js` |
| Heroicons / Lucide (npm) | **Inline SVG / existing icon pattern in file** |
| Hardcoded hex colors | **Design tokens only — never hardcode a hex that changes between light/dark themes** |

Every interactive element gets a `data-testid`; every write button labels exactly
what it writes (no auto-save); legacy blocks live in `<details>` collapsed.
(Full rule list: `frontend-design.md` §4–§9.)

---

## 2. Canonical V2 authority map (for SKILL.md Section 0 "identify the canonical page")

`SKILL.md` Section 0 requires resolving the canonical/routed page before editing.
On this repo the router truth lives here:

- **Shell / router**: `service/app/static/v2/index.html` (served at `/v2/`;
  `GET /v2/{path}` in `service/app/main.py`). Default slug = `dashboard`.
- **NAV_TREE / slug→component map**: `service/app/static/v2/components.jsx`.
- **Home / landing** ("the Portal home") = slug `dashboard` →
  `DashboardKanban` in `service/app/static/v2/dashboard-kanban.jsx`. There is **no**
  separate `portal`/`home`/`landing` page — do not create one (single-authority).
- **Known collision (as SKILL.md warns)**: `pages.jsx` (legacy stubs) vs
  `pages-v2.jsx` (live overrides). Resolve via the slug→component binding in
  `components.jsx` NAV_TREE, never by filename age.
- **V1 is frozen** (`shipment-detail.html`, `dashboard.html`) — critical fixes only
  (Lesson F). New operator surfaces are V2 pages.

State the confirmed canonical file path back to the user before editing, per
`SKILL.md` Section 0 step 3.

---

## 3. Token reconciliation (canonical set = frontend-design.md §3)

When `SKILL.md` says "reuse existing tokens / no new palette," use exactly these
(defined in `frontend-design.md` §3 `:root`, with `[data-theme="dark"]` overrides):

| Group | Tokens |
|-------|--------|
| Surfaces | `--bg`, `--bg-subtle`, `--card`, `--row-hover`, `--surface-1/2` |
| Borders | `--border`, `--border-subtle` |
| Text | `--text`, `--text-2`, `--text-3` |
| Accent (gold) | `--accent`, `--accent-light`, `--accent-text`, `--accent-subtle`, `--accent-border` |
| Sidebar | `--sidebar-bg`, `--sidebar-border`, `--sidebar-active`, `--sidebar-hover`, `--sidebar-text`, `--sidebar-text-muted`, `--sidebar-icon` |
| Badges | `--badge-{neutral,blue,amber,orange,green,red,purple,accent}-{bg,text,border}` |
| Shadow / overlay | `--shadow`, `--shadow-heavy`, `--overlay` |
| Font | Plus Jakarta Sans (Google Fonts CDN) |

Rules:
- If the upstream skill (or a Figma reference) implies a color/type not in the table
  above, treat it as **supplemental-only** — map it onto the nearest existing token;
  do **not** add a new `:root` variable without an explicit written user override.
- V2 status colors are also centralized in `components.jsx` `STATUS_MAP`
  (status string → token triple). Reuse it; do not re-map statuses per page.

---

## 4. Financial / customs / accounting guardrail (reinforces SKILL.md Section 4 #4)

Per `SKILL.md` ask-trigger #4 AND `frontend-design.md` §7: never let a "display /
formatting" request mutate figures, VAT/duty math, readiness gates, or add
`Create PZ` / `Post invoice` / `Submit to wFirma` / `override` / `force-clear`
buttons. These route through backend gates (see also Lesson N — advisory signals
must never be rendered as hard fiscal blockers, and vice-versa). Any such change is
a separate, confirmed change — stop and ask.
