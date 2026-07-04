---
name: ej-dashboard-fullstack-governance
metadata:
  version: 1.0.0
description: >
  Project governance layer for FULL-STACK changes on the EJ Dashboard (Estrella
  Jewels / Atlas-v2). Use whenever a change spans both the backend and the frontend
  at once — a new or changed endpoint plus its UI, "add a field end-to-end", "wire X
  to the backend", "expose Y in the dashboard", or any change that touches route +
  service + persistence together. Adapted from the generic senior-fullstack
  discipline but bound to THIS repository's real stack (FastAPI + one-SQLite-file-
  per-domain + vanilla HTML/Babel JSX, no bundler) and its existing authorities. It
  locks out wrong-stack defaults (Next.js, TypeScript, Tailwind, GraphQL, PostgreSQL,
  scaffolding), forces route→service→model mapping before edits, protects financial /
  customs / accounting / inventory / shipment logic, and requires tests + a rollback
  plan. It is a governance layer that COMPOSES with ej-dashboard-design and
  frontend-design (frontend craft/authority), the 7-agent deploy gate (production),
  and the Engineering Lessons — it points to them, it does not replace or override
  them. Consult it together with those skills on any cross-layer task.
---

# EJ Dashboard — Full-Stack Change Governance

This skill governs changes that cross the backend↔frontend boundary on the EJ
Dashboard. It is **not** a build tool and it introduces **no** new stack. It adapts
the *idea* of a senior full-stack review discipline to this repo's fixed reality and
composes with the skills that already own each layer:

- **Frontend craft + authority** → `frontend-design` + `ej-dashboard-design` (canonical
  routed file, tokens, testids, read-only-observer rules). This skill defers to them for
  anything visual; it does not restate their rules.
- **Production** → the 7-agent deploy gate (`/deploy`) is the only authority that syncs
  to `C:\PZ`. This skill never authorizes a deploy.
- **Cross-cutting rules** → the CLAUDE.md GATES 1–6 and Engineering Lessons A/E/G/J/N.
  This skill points to them at the relevant step; where it appears to conflict, they win.

## 0. Before touching any code: inspect, then map

1. **Run `/context`** (or `/context-lite`) and read the CLAUDE.md authority sections
   (Calculation authority, Databases, Frontend authority, Route registration, Financial
   rules, the Lessons). Load state, don't re-derive it from memory.
2. **Produce the route→service→model map first (Section 3).** No code until the chain is
   written down. If any link can't be named, STOP and ask.
3. State back, in one line, the exact files you will touch on each layer before editing —
   e.g. *"UI `inventory-page.jsx` → `PzApi.getX` → `routes_inventory.py:get_x` → `inventory_service.py` → `inventory_db.py`; no other files."*

## 1. Stack lock — what this repo IS, and what is FORBIDDEN to assume

**This repo IS (do not deviate):**
- **Backend**: FastAPI in `service/app/` (production `PZService`, port 47213). Routes in
  `service/app/api/routes_*.py`; **all** business logic in `service/app/services/*`;
  decision engines in `agents/`; config/guards in `core/`.
- **Persistence**: **SQLite, one file per domain**, each owned by a
  `service/app/services/*_db.py` module using **direct `sqlite3`** calls. **No shared ORM.**
  Some state also lives in per-batch `audit.json` / storage files.
- **Calculation**: root `pz_import_processor.py` `process_batch()` is the ONLY calc path
  (landed cost, freight, duty, totals). See §2.
- **Frontend**: vanilla HTML + Babel JSX in `service/app/static/` — no bundler, no
  TypeScript, no Tailwind. V1 is frozen; V2 (`static/v2/*.jsx`) is the authority.

**FORBIDDEN assumptions (hard — a senior-fullstack template's defaults do NOT apply here):**
- **No Next.js / React app scaffold / bundler / npm build step.**
- **No TypeScript or `.tsx`** — plain `.jsx` / `.js` only, no type annotations.
- **No Tailwind / utility-class frameworks** — CSS custom properties only.
- **No GraphQL** — REST under `/api/v1/...` only.
- **No PostgreSQL / MySQL / any new database engine, and no ORM** — SQLite + `sqlite3` only.
- **No project scaffolding or boilerplate generators** (`create-*`, `npx …templates`,
  code generators). Extend existing files in place; never scaffold a parallel structure.

If a task appears to *need* any of the above, that is a **STOP-and-ask** — do not introduce
the new thing silently.

## 2. Authority preservation (the chain must not be bypassed)

- **`process_batch()` is the ONLY calculation path.** Never recompute landed cost, freight,
  duty, or totals in a route, a service, or the Cliq layer. Routes and services are thin
  callers that render the engine's validated result object.
- **Route registration is explicit.** Every route file is wired via `include_router` in
  `service/app/main.py`. Adding a route file **requires** that edit — no hidden/auto routers.
- **Masters own their data.** Business modules read Product/Customer facts only from the EJ
  Product Master / Customer Master (which sync from wFirma via the Mirror). No module queries
  wFirma product/customer APIs directly, and no module grows its own product/customer table.
- **Single frontend authority.** One canonical routed page/component per module (resolved via
  the V2 router, per `ej-dashboard-design`). No duplicate page/route/state store; no
  `*New`/`*Modern`/`*V2` parallels.

A change that recomputes engine figures elsewhere, adds an unregistered router, calls wFirma
directly from a business module, or forks a second frontend authority is an **authority
violation** — reject it and take the in-authority path.

## 3. Map route → service → model/persistence BEFORE edits (required artifact)

For every full-stack change, write the chain explicitly, end to end, before editing:

```
UI (canonical routed file, .jsx)
  → transport (PzApi.<method> in pz-api.js  OR  EstrellaShared.apiFetch)
  → FastAPI route (service/app/api/routes_*.py, registered in main.py)
  → service (service/app/services/*.py — business logic lives here, not in the route)
  → persistence (service/app/services/*_db.py  OR  audit.json / storage)
  → response contract back to the UI
```

Rules:
- **Name every arrow.** If you cannot identify the existing route, service, or persistence
  owner for the change, STOP — do not invent a parallel one (mirrors CLAUDE.md §20 "prove the
  chain" and the Master-First rule).
- **Business logic goes in the service, never the route.** Routes validate + delegate.
- **Persistence changes are their own review.** A new column / table / migration on a
  `*_db.py` file is a schema change (deploy `persistence-storage-reviewer` territory) — call
  it out separately; never bury a schema mutation inside a UI-driven change.

## 4. Protected domains — confirm before touching

Financial, customs, accounting, inventory, and shipment logic carry real fiscal / tax /
customs / stock-integrity risk. Treat any change to the following as **stop-and-confirm**,
**even when the request is framed as "small", "display only", or "just a tweak":**

- **Financial / accounting**: figures, VAT/WDT math, duty allocation, freight/insurance
  proportioning, totals, ledger/posting logic, currency conversion, `notes`/UWAGI text.
- **Customs**: SAD/ZC429 parsing, duty (A00), MRN/clearance state, customs evidence chains.
- **Inventory**: piece/stock state transitions, reservations, warehouse receipt/scan state.
- **Shipment**: batch status, PZ generation/adoption, AWB/carrier linkage.
- **Fiscal writes**: anything gated by `WFIRMA_CREATE_PRODUCT/PZ/PROFORMA/INVOICE` or an
  Approve / Post / Convert / Reservation action.

Encoded rules to honor (do not restate or weaken them — defer to the source):
- **Financial rules (CLAUDE.md)**: freight/insurance proportional by value; duty from
  ZC429/A00 only; B00 VAT reference-only; notes from the engine only.
- **Lesson N (advisory vs. blocker)**: never promote an advisory-class signal (sales linkage,
  scan/warehouse-confirmation, placeholder-design) into a hard fiscal blocker, and never
  demote a true blocker. Only true fiscal/tax/duplication risk may block Approve/Post/Convert.
- **Authority separation**: PRODUCT / PROFORMA / IMPORT_PZ / WAREHOUSE / SALES each own their
  own gates; a guard must not block across an authority boundary without a named business rule
  + a pinning test.

## 5. Full-stack change protocol — tests + rollback are mandatory

No full-stack change is "done" without **both** a test result and a stated rollback.

**Tests (required):**
- Run the regression suite before and after: `make verify` (root, ~2s) — or
  `make verify-full` before a PR; `cd service && make verify` / targeted
  `pytest service/tests/test_routes_*.py` for the touched surface. State pass/fail **with
  counts** (baseline: `.claude/contracts/test-baseline.md`).
- **Add or extend a regression test for the changed contract** — the route's response shape
  and the service's return type (Lesson A: assert the real builder/service return shape, not a
  stub). A cross-layer change without a contract test is incomplete.

**Rollback plan (required):**
- State the exact revert: feature branch + `git revert <sha>` (prefer revert over reset for
  shared history), and the SHA to return to.
- **Cover both sync targets** (Lesson J): `service/app` deploys via the standard robocopy to
  `C:\PZ\app`, but root engine files (`pz_import_processor.py`,
  `polish_description_generator.py`) deploy via a **separate** robocopy to `C:\PZ\engine\`.
  If the change touches an engine file, the rollback must name that second sync explicitly.

**Completeness (Business Feature standard):** a shared `run_<capability>()` used by both the
scheduler/webhook and a `POST /api/v1/.../action`, plus a Business UI button and an
observability/status surface. A scheduler-only or endpoint-only change is a **draft**, not a
shipped feature.

## 6. Integration with existing governance (compose, don't duplicate)

- **Frontend portion** → defer to `frontend-design` + `ej-dashboard-design`: identify the
  canonical routed file, reuse tokens/shared components, `data-testid` on every interactive
  element, honor read-only-observer surfaces, no duplicate authority.
- **Backend safety** → follow the conventions the review agents enforce
  (`backend-safety-reviewer`, `integration-boundary`, `security-write-action-reviewer`): safe
  writes, idempotency, real evidence/paths, guard-before-action. GATES 1–6 apply to PR open,
  PR count, branch status, and browser verification.
- **Production** → the 7-agent deploy gate owns every sync to `C:\PZ`. This skill produces
  review-ready changes; it never syncs and never declares production done.
- **Lessons A / E / G / J / N** bind at their named gates. This skill routes you to them; it
  does not restate or override them.

## 7. Ask-triggers / stop conditions

Stop and ask (do not proceed on a default) when the change would:
1. Introduce a new stack / framework / language / database / package manager (§1).
2. Scaffold new project structure or run a boilerplate generator (§1).
3. Touch a protected domain — financial, customs, accounting, inventory, or shipment (§4),
   even under cosmetic framing.
4. Leave a route→service→model arrow unnamable (§3).
5. Create a duplicate authority, bypass `process_batch()`, add an unregistered router, or
   call wFirma directly from a business module (§2).
6. Perform a fiscal write (`WFIRMA_CREATE_*` / Approve / Post / Convert / Reservation).

Otherwise: proceed with the **smallest safe cross-layer change**, state the assumptions and
the mapped chain, run tests, and give the rollback.

## 8. Pre-done checklist (before calling a full-stack change complete)

- [ ] `/context` run; CLAUDE.md authority sections read
- [ ] route→service→model/persistence chain written out; every arrow named
- [ ] No new stack, framework, DB, ORM, bundler, or scaffolding introduced
- [ ] `process_batch()` calc authority + master chain + single frontend authority preserved
- [ ] New route file (if any) registered in `main.py`
- [ ] Protected-domain logic untouched, or the change was explicitly confirmed
- [ ] `make verify` (or targeted suite) run — result stated with counts
- [ ] Regression test added/extended for the changed route+service contract
- [ ] Rollback stated, covering the engine `C:\PZ\engine\` sync too if applicable
- [ ] Frontend deferred to `frontend-design` + `ej-dashboard-design`
- [ ] Production left to the 7-agent deploy gate (no self-authorized sync)

## 9. Test cases

`tests/` in this skill folder contains six regression prompts exercising the rules above
(new-stack rejection, scaffolding rejection, route→service→model mapping, protected-domain
confirmation, tests+rollback requirement, and authority preservation). Consult them for a
concrete example of how a rule applies, and re-validate every prompt after editing this skill.
