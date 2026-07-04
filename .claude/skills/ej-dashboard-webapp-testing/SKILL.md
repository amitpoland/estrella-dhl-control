---
name: ej-dashboard-webapp-testing
metadata:
  version: 1.0.0
description: >
  Project governance skill for SAFELY browser-testing the EJ Dashboard Portal
  (Estrella Jewels / Atlas-v2, served at /v2/) with Playwright-style browser
  automation. Use whenever the task is to browser-test, smoke-test, or verify a
  dashboard route/flow in a real browser — "smoke test /v2/inventory", "verify the
  proforma page loads", "check the dashboard in the browser", "run a browser
  verification". Adapted from the generic webapp-testing discipline but bound to
  THIS repo: it detects an already-running server before starting one, prefers the
  existing project run commands, logs, and helper scripts (run_smoke.py,
  lifecycle_smoke_tests.py) and the harness-native Claude Preview MCP, waits for
  networkidle before DOM inspection, captures screenshots + console errors + failed
  network requests, and produces a structured test report. It is READ-ONLY: it never
  modifies application code, never runs destructive/write actions without explicit
  approval, and protects financial / customs / accounting / shipment / inventory /
  document-generation flows. It composes with the 7-agent deploy gate (GATE 6 browser
  verification) and the design skills — it verifies, it does not fix or deploy.
---

# EJ Dashboard — Safe Web-App Testing (Playwright)

This skill governs **browser verification** of the EJ Dashboard. It observes running
behavior and reports; it does **not** change code, book documents, or authorize a
deploy. Adapted from a generic webapp-testing template — the *discipline* only; every
project-specific detail below is bound to this repo.

Composes with:
- **CLAUDE.md `preview_tools` + GATE 6 (browser verification completeness)** — this
  skill is the how-to for that gate on the EJ Dashboard.
- **`frontend-design` / `ej-dashboard-design`** — own the frontend authority; this skill
  verifies their output, it does not restyle.
- **The 7-agent deploy gate** — owns production. This skill never tests against production
  and never declares a deploy safe.

## 0. Inspect first

1. **Run `/context`** and read CLAUDE.md `preview_tools` (the `<verification_workflow>`)
   and the GATE 6 browser-verification rules. Load the route → component map from
   `components.jsx` NAV_TREE if you need to know which page a slug renders.
2. State the **route(s)** you will test and the **exact actions** (navigations, clicks,
   inspections) before driving the browser. Read-only navigation by default (§5).

## 1. Read-only posture — never modify application code

- **Testing observes; it does not fix.** If a test surfaces a bug, **report it** — do not
  edit application code in the same pass. A fix is a separate, approved task (and, if it
  crosses layers, goes through `ej-dashboard-fullstack-governance`).
- The only files this skill may write are **test artifacts**: a report under
  `tasks/smoke-reports/`, screenshots, and captured logs. Never `service/app/**`, never
  root engine files.

## 2. Detect the server before starting one

**Detect first — do not blindly launch a second server.**
- Check whether a dev server is already up before starting one (harness: `preview_list`;
  shell: probe the health endpoint `GET /api/v1/health` on the candidate port). Reuse it
  if healthy.
- **Local run surfaces (pick the one already running / intended):**
  - `cd service && make dev` → `uvicorn app.main:app` on **port 8000**.
  - Claude Preview MCP configs in `.claude/launch.json`: `pz-service-verify` (8135),
    `inventory-dev` (8200), `pz-review` (8136). `preview_start <name>` reuses if already up.
- The dashboard SPA is served at **`/v2/`** (default slug `dashboard`; deep links `/v2/<slug>`).
- **Never test against production.** Port **47213** / `pz.estrellajewels.eu` / `C:\PZ` are
  off-limits — production carries live data and the X-API-Key gate. Testing is local only.
- If the V2 shell shows a boot error about vendor files, the fix is
  `service/scripts/download-v2-vendor.ps1` (offline vendor copies) — note it in the report;
  do not hand-edit `index.html`.

## 3. Tooling — prefer existing, then Playwright semantics

Prefer, in order:
1. **Harness-native: the Claude Preview MCP** (`preview_start`, `preview_snapshot`,
   `preview_console_logs`, `preview_network`, `preview_inspect`, `preview_screenshot`,
   `preview_resize`). This is the CLAUDE.md-preferred browser surface in this environment
   and satisfies GATE 6. Use it unless driving a browser directly is required.
2. **Existing project helpers** (prefer over hand-rolled flows). Treat every helper as a
   **black box — run `--help` before reading its source:**
   - `python service/scripts/run_smoke.py <spec.json> [--api-key ...] [--print-only]` — runs
     a smoke-spec and writes a markdown report to `tasks/smoke-reports/`.
   - `service/scripts/lifecycle_smoke_tests.py` — lifecycle smoke coverage.
3. **Playwright** (direct browser driver) — the requested mechanism when driving Chromium
   directly outside the harness. Apply the same discipline: headless Chromium, explicit
   waits, evidence capture (§4).

Whichever surface is used, the **verification semantics in §4 are mandatory**.

## 4. Verification discipline (mandatory on every run)

- **Wait for `networkidle` before any DOM inspection.** The V2 shell compiles JSX in-browser
  via Babel and fetches live data (`/api/v1/dashboard/batches`, etc.); inspecting before the
  network settles reads a half-rendered tree. (Preview MCP: reload/settle then `preview_snapshot`;
  Playwright: `await page.goto(url, { waitUntil: 'networkidle' })` / `waitForLoadState('networkidle')`.)
- **Capture, every run:**
  - **Screenshot** of the route in its settled state (and per interaction that changes it).
  - **Console errors** — no new red entries (`preview_console_logs` level=error / Playwright
    `page.on('console')`).
  - **Failed network requests** — any 4xx/5xx on the happy path is a finding
    (`preview_network` filter=failed / Playwright `page.on('requestfailed')` + response status).
- Verify the **execution chain** for any interaction tested: click → API call → response →
  UI update (GATE 6), but only for non-destructive interactions (§5).
- Check **responsive + theme** when layout is in scope (`preview_resize` mobile/tablet, dark).

## 5. Destructive-action gate — explicit approval required

**Default to read-only navigation and inspection.** Do **not** trigger any writing/destructive
action as a test step without explicit operator approval. Treated as destructive:
- Any write button — Create PZ, Post / Convert / Submit to wFirma, Approve, Reserve, Save,
  Delete, Archive, Send email, Retry/Requeue, override / force-clear.
- Anything that mutates a batch, booking, document, stock state, or external record.

If a test genuinely needs a write path exercised, **stop and ask**, name the exact action and
its blast radius, and prefer a disposable/local fixture over real data. Reading the resulting
state after an operator performs the action is fine; initiating it is not.

## 6. Protected flows (observe, do not trigger)

Extra caution for financial, customs, accounting, shipment, inventory, and
**document-generation** flows. As a test step, do **not**:
- Trigger PZ generation, wFirma posting/booking, proforma→invoice conversion, or a
  reservation.
- Trigger PDF / XLSX / document generation or downloads that write or overwrite artifacts
  (Lesson G: generated-artifact endpoints have caching/atomicity rules — generating one as a
  test mutates real output). Verify that the control *exists / is enabled/disabled as expected*
  by inspection, rather than firing it.
- Touch anything gated by `WFIRMA_CREATE_*` or an Approve/Post/Convert action.

Observe the current state and the presence/labelling of these controls; do not exercise them
without §5 approval. Never point the test at production data.

## 7. Test report (required output)

Produce a clear report — follow the existing `tasks/smoke-reports/` convention (see its
`README.md`). For each route/flow tested include:

- **Route** — the `/v2/<slug>` URL and which component renders it.
- **Server** — surface + port used (e.g. `preview:inventory-dev:8200`), and that it was
  detected-running or started.
- **Actions** — the ordered, non-destructive steps performed (navigate, wait networkidle,
  inspect, non-writing click).
- **Result** — PASS / FAIL / PARTIAL, with what was verified (expected panels/testids present,
  live data rendered, no MOCK banner where wired).
- **Evidence** — screenshot path(s), console-error capture, network summary.
- **Failures** — console errors, failed (4xx/5xx) requests, missing elements, each with the
  route/action that produced it.
- **Not tested / blocked** — any write/protected flow deliberately skipped per §5/§6, named
  explicitly (no silent gaps).

## 8. Pre-done checklist

- [ ] `/context` run; route→component identified; actions stated up front
- [ ] Server detected before starting; local surface only (never 47213 / prod)
- [ ] Preferred existing surface (Preview MCP / `run_smoke.py`) before hand-rolled Playwright
- [ ] Helper scripts treated as black boxes — `--help` run before reading source
- [ ] `networkidle` awaited before every DOM inspection
- [ ] Screenshot + console errors + failed requests captured
- [ ] No application code modified
- [ ] No destructive/write action run without explicit approval
- [ ] Financial/customs/accounting/shipment/inventory/document-generation flows observed, not triggered
- [ ] Structured report written (route · actions · result · evidence · failures · skipped)

## 9. Test cases

`tests/` in this skill folder contains regression prompts exercising the rules above
(server detection, read-only posture, destructive-action approval, protected-flow guard,
helper-script black-box `--help`, and the networkidle + evidence-capture report). Consult them
for concrete examples and re-validate every prompt after editing this skill.
