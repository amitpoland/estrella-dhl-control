---
name: ej-dashboard-clean-code
metadata:
  version: 1.0.0
description: >
  Project governance skill for clean-code / refactor / cleanup work on the EJ Dashboard
  (Estrella Jewels / Atlas-v2 — FastAPI backend + one-SQLite-file-per-domain + vanilla
  HTML/Babel JSX, no bundler). Use whenever the task is to clean up, refactor, simplify,
  de-duplicate, rename, tidy, or "improve code quality" on this codebase. Adapted from the
  generic clean-code discipline but bound to THIS repo: it preserves existing architecture
  and authority ownership, refuses over-engineering and unnecessary new files/helper layers,
  requires inspecting imports/dependents before editing shared files, keeps changes small and
  scoped, and never auto-fixes protected financial / customs / accounting / inventory /
  shipment / document-generation logic without approval. It uses only repo-real verification
  commands (make verify / pytest — there is NO eslint/prettier/npm-lint here), requires a
  test/verification summary before completion, and when validation output has errors it
  summarizes and asks before fixing. It composes with ej-dashboard-design (frontend),
  ej-dashboard-fullstack-governance (cross-layer), and the deploy gate — it tidies, it does
  not redesign, re-architect, or deploy.
---

# EJ Dashboard — Clean-Code / Refactor Governance

This skill governs *tidying* on the EJ Dashboard: making existing code clearer without
changing what it does, where it lives, or who owns it. Adapted from a generic clean-code
template — the *discipline* only; every rule below is bound to this repo's real architecture
and tooling. It composes with, and never overrides:

- **`ej-dashboard-design`** — frontend authority/tokens (a JSX cleanup defers to it).
- **`ej-dashboard-fullstack-governance`** — if a cleanup crosses the backend↔frontend
  boundary or touches route/service/persistence, that skill's chain-mapping applies.
- **CLAUDE.md GATES 1–6 + Engineering Lessons** — on conflict, they win.
- **The 7-agent deploy gate** — owns production. Cleanup never authorizes a deploy.

## 0. Inspect first

1. **Run `/context`** and read the CLAUDE.md architecture section (calculation authority,
   databases, route registration, frontend authority).
2. **Before editing a shared file, inspect its dependents** (§3). State the file(s) and the
   scoped change up front. No cleanup until you know who imports/consumes the thing.

## 1. Preserve architecture and authority ownership

A cleanup must not move an authority or blur a boundary:
- **`process_batch()` stays the only calc path.** Never "extract" or "inline" landed-cost /
  freight / duty / total math into a route, service, or the Cliq layer while tidying.
- **One SQLite file per domain**, each owned by its `service/app/services/*_db.py`. Don't
  merge domain databases or introduce a shared data-access layer/ORM in the name of DRY.
- **Routes register in `main.py`.** Don't relocate routers or hide registration.
- **Single frontend authority (V2).** Don't fork a canonical page/component while refactoring
  (no `*New`/`*V2`/`*Refactored`); refactor in place.
- **Masters own product/customer data.** A cleanup never reroutes a module to read wFirma or
  the mirror directly.

If a "cleanup" can only be done by moving an authority, it is not a cleanup — STOP (§7).

## 2. No over-engineering, no unnecessary files, no duplicate helper layers

- **YAGNI.** Prefer the smallest clarifying change. Do NOT introduce generic frameworks,
  plugin systems, config layers, base classes, dependency-injection, or "reusable" abstractions
  for a single caller. Clever ≠ clean here; consistency across 25+ modules beats abstraction.
- **No unnecessary new files.** Extend an existing module in place. A new file must be
  justified by a real need — and a new route file requires its `include_router` line in
  `main.py`. Splitting one file into five is not automatically cleaner.
- **No duplicate helper layers.** Before writing a helper, find the existing one and reuse it:
  - Frontend shared primitives: `service/app/static/v2/components.jsx` (`Btn`, `Badge`, `Card`,
    `Modal`, `Input`, `PageHeader`, `STATUS_MAP`, …, exported on `window`); transport in
    `pz-api.js`; V1 atoms in `dashboard-shared.js`.
  - Reuse formatters/mappers that already exist rather than adding a second one. (De-duplicating
    an *existing* copy-paste is good; adding a third variant is not.)

## 3. Inspect imports/dependents before editing shared files

Shared surfaces are consumed across many pages via `window.*` globals — a signature change
ripples silently.
- **Grep every dependent first.** Before changing a shared component/method/util, find all
  usages (e.g. `Grep` for `Btn(`, `PzApi.<method>`, the `window.X` export) and confirm the
  change is safe for every caller. A rename of a routed/global symbol must update all importers
  in the same change (an unpropagated rename is a silent duplicate authority — Lesson-class).
- **Honor the no-spread-rest rule.** V2 JSX forbids `...rest` props (PROJECT_STATE DECISIONS
  "V2-wide spread-rest collision sweep": Babel-standalone hoists `_excluded` to global scope
  and a later-loaded file overwrites it). Keep explicit destructuring; do not "simplify" a
  component to spread-rest.
- **Respect the Babel-7 pin.** No syntax that requires a newer Babel/ESM (regression guard
  `service/tests/test_v2_babel_pin.py`); the shell compiles JSX in-browser as classic scripts.

## 4. Keep changes small and scoped

- One cleanup = one intent. Don't bundle a rename + a re-layout + a dependency bump.
- Leave unrelated code alone, even if it looks messy — note it, don't drive-by-fix it.
- Prefer edits that leave behavior byte-identical (the golden regression must not move).

## 5. Protected logic — do NOT auto-fix without approval

Never auto-"clean up" logic in these domains without explicit approval, even when the change
looks purely stylistic (dead-code removal, rename, extraction, reformat):
- **Financial / accounting** — figures, VAT/WDT, duty allocation, freight/insurance
  proportioning, totals, ledger/posting, `notes`/UWAGI.
- **Customs** — SAD/ZC429 parsing, duty (A00), MRN/clearance.
- **Inventory** — stock/piece state, reservations, warehouse receipt.
- **Shipment** — batch status, PZ generation/adoption, AWB linkage.
- **Document generation** — PDF/XLSX builders and their generate→validate→replace pipeline
  (Lesson G).

In these areas, propose the cleanup and get a yes before applying it; a wrong "tidy" here has
fiscal/customs/data consequences. (Honor the financial rules + Lesson N advisory-vs-blocker
classification — a refactor must not silently reclassify a gate.)

## 6. Verification (repo-real only) + errors→summarize-and-ask

- **Use only repo-real commands** — do NOT reference generic clean-code scripts that don't
  exist here. There is **no eslint / prettier / npm-lint** (no bundler). The real gates are:
  - `make verify` — fast unit + format regression (~2s), root.
  - `make verify-full` — unit + format + golden PDF pipeline (~30s), before a PR.
  - `cd service && make verify` — PZ regression inside the service.
  - Targeted: `pytest test_pz_regression.py -k "<name>"` / `cd service && pytest tests/...`;
    smoke subset `cd service && pytest tests/ -m smoke`.
  - Repo helpers (black boxes — `--help` first): `service/scripts/run_smoke.py`, etc.
- **A cleanup is not "done" without a verification summary** — run the relevant gate and report
  the result with counts (baseline: `.claude/contracts/test-baseline.md`). A behavior-preserving
  cleanup must leave the golden regression unchanged.
- **If validation output has errors: summarize and ask before fixing.** Do NOT cascade into
  auto-fixes — especially if the failure touches a protected domain (§5). Report what failed,
  the likely cause, and the smallest proposed fix, and wait for direction.

## 7. Ask-triggers / stop conditions

Stop and ask when a "cleanup" would:
1. Move/blur an authority — bypass `process_batch()`, merge domain DBs, relocate a router,
   fork a canonical page, or reroute a module to wFirma/mirror directly (§1).
2. Add an abstraction/framework/config layer or a new file that isn't clearly necessary (§2).
3. Change a shared symbol whose dependents you haven't fully enumerated (§3).
4. Touch protected financial/customs/accounting/inventory/shipment/document-generation logic (§5).
5. Require a non-repo-real tool, or proceed past a failing/erroring verification (§6).

Otherwise: make the smallest scoped, behavior-preserving change, run the gate, and summarize.

## 8. Pre-done checklist

- [ ] `/context` run; shared-file dependents grepped before editing
- [ ] Architecture/authority preserved (calc path, per-domain DB, main.py, V2 authority, masters)
- [ ] No over-engineering; no unnecessary new file; no duplicate helper (existing reused)
- [ ] Change small/scoped; behavior preserved; no drive-by edits
- [ ] No-spread-rest + Babel-7 pin respected on V2 JSX
- [ ] Protected-domain logic untouched, or the cleanup was explicitly approved
- [ ] Repo-real verification run (`make verify` / targeted `pytest`) — result stated with counts
- [ ] Any validation errors summarized + asked, not auto-fixed
- [ ] No application code changed beyond the scoped cleanup; production left to the deploy gate

## 9. Test cases

`tests/` contains six regression prompts exercising the rules above (over-engineering refusal,
duplicate-helper/unnecessary-file refusal, dependent-inspection before a shared edit,
protected-logic no-auto-fix, repo-real-scripts-only, and errors→summarize-and-ask). Consult them
for concrete examples and re-validate every prompt after editing this skill.
