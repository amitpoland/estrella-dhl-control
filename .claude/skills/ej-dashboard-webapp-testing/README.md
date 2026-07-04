# ej-dashboard-webapp-testing (Claude Code project skill)

Project-level governance skill for **safely browser-testing** the EJ Dashboard Portal
(Estrella Jewels / Atlas-v2, served at `/v2/`) with Playwright-style browser automation.
Scoped to this repo only — installed at `.claude/skills/ej-dashboard-webapp-testing/`, not
globally.

## Provenance — adapted, NOT installed raw

Adapted from the *idea* of the generic `development/webapp-testing` template
(`claude-code-templates`). The generic template was **not** installed. Only the discipline
was kept (detect server, wait for load, capture evidence, report); everything concrete is
bound to this repo's real run surfaces, helper scripts, and safety rules.

## What it does

Constrains how Claude Code browser-tests this app:
- Inspect first (`/context`), state route + actions before driving the browser
- **Read-only** — never modifies application code; the only writes are test artifacts
  (report + screenshots + logs)
- Detects an already-running server before starting one; local surfaces only
  (`make dev` :8000, or `.claude/launch.json` preview configs :8135/:8200/:8136) — **never
  production** (:47213 / `pz.estrellajewels.eu`)
- Prefers existing project surfaces: the harness-native **Claude Preview MCP** and helper
  scripts (`service/scripts/run_smoke.py`, `lifecycle_smoke_tests.py`) before hand-rolled
  Playwright; treats helper scripts as **black boxes** (`--help` before reading source)
- Waits for **networkidle** before DOM inspection (the V2 shell compiles JSX in-browser and
  fetches live data)
- Captures **screenshots + console errors + failed network requests** every run
- **No destructive/write action** without explicit approval; protects financial, customs,
  accounting, shipment, inventory, and **document-generation** flows (observe, don't trigger)
- Produces a structured report (route · server · actions · result · evidence · failures ·
  skipped) in the existing `tasks/smoke-reports/` convention

## Relationship to other skills / gates

Composes with — does not replace:
- **CLAUDE.md `preview_tools` + GATE 6** — this skill is the EJ-specific how-to for the
  browser-verification gate.
- **`frontend-design` / `ej-dashboard-design`** — own the frontend authority; this skill
  verifies their output, it does not restyle.
- **`ej-dashboard-fullstack-governance`** — if a test surfaces a bug, the *fix* routes there;
  this skill only reports.
- **The 7-agent deploy gate** — owns production; this skill never tests prod and never
  authorizes a deploy.

## Install

```bash
mkdir -p .claude/skills/ej-dashboard-webapp-testing
cp SKILL.md .claude/skills/ej-dashboard-webapp-testing/SKILL.md
```

Restart Claude Code (or start a new session) so the skill is picked up, then verify:

```bash
claude skills list
# expect to see: ej-dashboard-webapp-testing
```

## Usage

```
/context
/ej-dashboard-webapp-testing
```

Run `/context` first so Claude inspects the repo (run surfaces, router/canonical pages, helper
scripts, health endpoint) before testing.

## Maintaining this skill

- Keep `SKILL.md` under ~500 lines; split detail into a `references/` subfolder if it grows.
- Any change to the rules (server detection, read-only posture, destructive-action gate,
  protected flows, evidence/report format) must be re-validated against the prompts in `tests/`
  before merging.
- This file (`README.md`) is for humans only — Claude Code does not read it as instructions.
