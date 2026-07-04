# ej-dashboard-clean-code (Claude Code project skill)

Project-level governance skill for **clean-code / refactor / cleanup** work on the EJ
Dashboard (Estrella Jewels / Atlas-v2). Scoped to this repo only — installed at
`.claude/skills/ej-dashboard-clean-code/`, not globally.

## Provenance — adapted, NOT installed raw

Adapted from the *idea* of the generic `development/clean-code` template
(`claude-code-templates`). The generic template was **not** installed. Only the discipline
was kept (small scoped changes, DRY without over-abstraction, verify before done); every
concrete rule is bound to this repo — and crucially, the skill references **only repo-real
tooling** (`make verify` / `pytest`), never generic clean-code scripts like eslint/prettier
that do not exist here (this is a no-bundler, vanilla Babel-JSX frontend).

## What it does

Constrains how Claude Code tidies this codebase:
- Inspect first (`/context`); grep a shared file's dependents before editing it
- **Preserve architecture and authority ownership** — `process_batch()` as the only calc
  path, one SQLite file per domain, `main.py` route registration, single V2 frontend
  authority, masters own product/customer data
- **No over-engineering** (YAGNI), **no unnecessary new files**, **no duplicate helper layers**
  — reuse existing shared primitives (`components.jsx`, `pz-api.js`, `dashboard-shared.js`)
- Keep changes small, scoped, behavior-preserving (golden regression must not move); honor the
  V2 no-spread-rest rule and the Babel-7 pin
- **Do not auto-fix protected logic** — financial, customs, accounting, inventory, shipment,
  document-generation — without approval
- Require a **repo-real verification summary** before completion (`make verify` /
  `make verify-full` / targeted `pytest`)
- If validation output has errors, **summarize and ask before fixing** (no auto-cascade)

## Relationship to other skills / gates

Composes with — does not replace:
- **`ej-dashboard-design`** — frontend authority/tokens; a JSX cleanup defers to it.
- **`ej-dashboard-fullstack-governance`** — if a cleanup crosses layers or touches
  route/service/persistence, its chain-mapping + test/rollback discipline applies.
- **`ej-dashboard-webapp-testing`** — for browser re-verification after a UI-visible cleanup.
- **CLAUDE.md GATES 1–6 + Engineering Lessons** — on conflict, they win.
- **The 7-agent deploy gate** — owns production; cleanup never authorizes a deploy.

## Install

```bash
mkdir -p .claude/skills/ej-dashboard-clean-code
cp SKILL.md .claude/skills/ej-dashboard-clean-code/SKILL.md
```

Restart Claude Code (or start a new session) so the skill is picked up, then verify:

```bash
claude skills list
# expect to see: ej-dashboard-clean-code
```

## Usage

```
/context
/ej-dashboard-clean-code
```

Run `/context` first so Claude inspects the architecture, shared files, and their dependents
before refactoring.

## Maintaining this skill

- Keep `SKILL.md` under ~500 lines; split detail into a `references/` subfolder if it grows.
- Any change to the rules (authority preservation, over-engineering/duplicate-helper bans,
  protected domains, repo-real verification, errors→ask) must be re-validated against the
  prompts in `tests/` before merging.
- This file (`README.md`) is for humans only — Claude Code does not read it as instructions.
