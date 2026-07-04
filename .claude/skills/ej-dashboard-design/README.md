# ej-dashboard-design (Claude Code project skill)

Project-level governance skill for UI work on the EJ Dashboard Portal (Estrella Jewels / Atlas-v2 frontend). Scoped to this repo only — installed at `.claude/skills/ej-dashboard-design/`, not globally.

## What it does

Constrains how Claude Code makes UI changes on this codebase:
- Identifies the canonical/routed version of a page before editing (resolves the `pages.jsx` vs `pages-v2.jsx`-style collisions via the router, not filename age)
- Preserves API wiring and business logic — visual changes stay visual
- Reuses existing design tokens/components instead of introducing new palettes, fonts, or one-off components
- Blocks accidental duplicate-authority patterns (parallel components like `*New`/`*Modern`/`*V2`, unpropagated renames, edits to non-routed legacy files)
- Applies a narrow-safe-edit-by-default policy: resolves most ambiguity with a stated assumption rather than asking, but stops to confirm before it could create a new page, change API behavior, add a new design authority, or touch financial/customs/accounting logic

## Relationship to `frontend-design`

This skill **layers on top of** the general `frontend-design` skill — it does not replace it. `frontend-design` governs visual craft (typography, layout, motion); this skill governs project-specific safety and consistency. Both should stay enabled together; see `SKILL.md` Section headers for how they interact when they conflict.

## Install

```bash
mkdir -p .claude/skills/ej-dashboard-design
cp SKILL.md .claude/skills/ej-dashboard-design/SKILL.md
```

Restart Claude Code (or start a new session) after first install so the new skills directory is picked up, then verify:

```bash
claude skills list
# expect to see: ej-dashboard-design, frontend-design
```

## Usage

```
/context
/frontend-design
/ej-dashboard-design
```

`/context` first so Claude inspects the repo (router, canonical pages, shared components, API wiring) before applying either design skill.

## Maintaining this skill

- Keep `SKILL.md` under ~500 lines; if it grows past that, split detail into a `references/` subfolder and link to it from `SKILL.md`.
- Any change to the governance rules (hard rules, ambiguity defaults, ask-triggers) should be re-validated against the six governance test prompts documented in the skill's development history before merging.
- This file (`README.md`) is for humans only — Claude Code does not read it as instructions.
