# ej-dashboard-fullstack-governance (Claude Code project skill)

Project-level governance skill for **full-stack** changes on the EJ Dashboard (Estrella
Jewels / Atlas-v2) — changes that cross the backend↔frontend boundary (an endpoint plus
its UI, "add a field end-to-end", a change touching route + service + persistence together).
Scoped to this repo only — installed at `.claude/skills/ej-dashboard-fullstack-governance/`,
not globally.

## Provenance — adapted, NOT installed raw

This skill was **adapted from the idea of** the generic
`development/senior-fullstack` template (`claude-code-templates`). The generic template
was **not** installed. Its stack defaults are wrong for this repository and every one of
them is inverted into a hard prohibition here:

| Generic senior-fullstack default | This repo |
|---|---|
| Next.js / React app + bundler | FastAPI backend + vanilla HTML/Babel JSX, **no bundler** |
| TypeScript / `.tsx` | Plain `.jsx` / `.js`, **no types** |
| Tailwind | **CSS custom properties only** |
| GraphQL | **REST `/api/v1/...` only** |
| PostgreSQL + ORM | **SQLite, one file per domain, direct `sqlite3`, no ORM** |
| Project scaffolding / generators | **Extend existing files in place, no scaffold** |

Only the *discipline* was kept: inspect first, map the layers before editing, protect
sensitive logic, and require tests + a rollback for cross-layer changes.

## What it does

Constrains how Claude Code makes changes that span both backend and frontend:
- Forces `/context` inspection + a written **route → service → model/persistence** map
  before any edit
- Locks the stack (no Next.js / TypeScript / Tailwind / GraphQL / PostgreSQL / scaffolding)
- Preserves existing authorities: `process_batch()` as the only calc path, `main.py` route
  registration, the Product/Customer Master → Mirror → wFirma chain, single V2 frontend
  authority
- Treats financial, customs, accounting, inventory, and shipment logic as stop-and-confirm
- Requires a regression test for the changed route+service contract and a stated rollback
  (covering the separate `C:\PZ\engine\` sync where relevant)

## Relationship to other skills / gates

This skill **composes with** — it does not replace:
- `ej-dashboard-design` + `frontend-design` — own the frontend layer (canonical file,
  tokens, testids, read-only-observer rules). The full-stack skill defers to them for
  anything visual.
- The **7-agent deploy gate** (`/deploy`) — the only authority that syncs to `C:\PZ`. This
  skill never authorizes a deploy.
- CLAUDE.md **GATES 1–6** and **Engineering Lessons A/E/G/J/N** — it points to them at the
  relevant step; on conflict, they win.

## Install

```bash
mkdir -p .claude/skills/ej-dashboard-fullstack-governance
cp SKILL.md .claude/skills/ej-dashboard-fullstack-governance/SKILL.md
```

Restart Claude Code (or start a new session) so the skill is picked up, then verify:

```bash
claude skills list
# expect to see: ej-dashboard-fullstack-governance
```

## Usage

```
/context
/ej-dashboard-fullstack-governance
```

Run `/context` first so Claude inspects the repo (routes, services, persistence, router,
canonical pages, API wiring) before applying the governance rules. On a change with a UI
surface, also enable `frontend-design` + `ej-dashboard-design`.

## Maintaining this skill

- Keep `SKILL.md` under ~500 lines; split detail into a `references/` subfolder if it grows.
- Any change to the rules (stack lock, protected domains, ask-triggers, test/rollback
  requirement) must be re-validated against the six prompts in `tests/` before merging.
- This file (`README.md`) is for humans only — Claude Code does not read it as instructions.
