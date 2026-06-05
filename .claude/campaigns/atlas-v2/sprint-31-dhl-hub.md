# Sprint 31 — DHL Hub (read-only visibility surface)

**Campaign:** Atlas-V2 (V2 shell wiring)
**Sprint:** 31 — DHL Hub
**Predecessor:** Sprint 30 (Inventory V2) — MERGED `498b46e` + DEPLOYED 2026-06-06
**Branch (to create):** `feat/sprint31-dhl-hub-shell-wiring`
**Base:** `origin/main` (HEAD `4563a5a` at planning time)
**New file:** `service/tests/test_sprint31_dhl_shell_wiring.py` (NEW); no new static file — wire the existing `DhlCustomsPage`
**Authoring audit:** Sprint 31 Planning & Authority Audit (this session, 2026-06-06). DHL Hub selected over Shipments/Automation/Intelligence/Accounting/Proposals/Shipping. Evidence: ~13 verified GET endpoints + `dhl_followup_status_projector` + 2 pre-built V2 cards.

---

## 1. Objective

Replace the inline **mock** data in `DhlCustomsPage` (V2 shell `page === 'dhl'`) with **live, read-only, GET-backed rendering** from existing DHL authority. Same pattern as Sprint 30 Inventory: existing authority → read-only renderer → browser verification → static-only deploy.

This Hub is an **Observer**, not an authority. It gives the operator a visibility window into the production DHL automation (Lane A / Lane B / Task Scheduler) **without becoming a second automation authority.**

```
Existing DHL authority  →  read-only renderer  →  browser verification  →  static deploy
(NOT: new UI → new backend → new authority → new workflow)
```

---

## 2. Authority Boundary

```
OWNS (this page):  read-only rendering of DHL automation status, the DHL
                   shipment queue (projector rows), inbox-scanner health,
                   and the daily DHL operations summary.

NEVER:             Retry send · Requeue email · Trigger scan · Run Lane A ·
                   Run Lane B · Force status update · Manual projector refresh ·
                   any POST/PUT/PATCH/DELETE · any DHL workflow mutation ·
                   any email send · any customs write · any inventory/wFirma touch.
```

**Authority owner (backend, unchanged):** `dhl_followup_status_projector`
(`project_automation_status()`, `project_shipment_rows()`) over `active_shipment_monitor`
+ audit.json timelines + `documents.db`. The frontend is a dumb renderer; the backend
remains the sole authority. Lane A / Lane B / Task Scheduler remain the only actors.

---

## 3. The ONLY endpoints this page may consume (exactly 4 — and nothing else)

| Endpoint | Source file | Purpose | Load |
|---|---|---|---|
| `GET /api/v1/dhl/status` | routes_dhl_followup_status.py | automation status projection | auto on mount |
| `GET /api/v1/dhl/shipments` | routes_dhl_followup_status.py | DHL shipment rows (projector) | auto on mount |
| `GET /api/v1/dhl/auto-scan-status` | routes_dhl_clearance.py:2022 | Lane A inbox-scanner health card | auto on mount (reuse `dhl-scan-status.jsx`) |
| `GET /api/v1/dhl/daily-summary` | routes_dhl_clearance.py:2254 | daily DHL operations report | auto on mount (reuse `dhl-daily-summary.jsx`) |

All four are `GET`, `Depends(require_api_key)`, read-only, no mutation. **Do NOT add** the
per-batch lookup endpoints (`/dhl/clearance-status/{id}`, `/dhl/reply-status/{id}`,
`/dhl/sad-ready/{id}`, `/dhl/readiness/{id}`, `/dhl/{id}/mode`, `/dhl/{id}/auto/preview`)
in this sprint — they are deferred to keep the surface minimal and unambiguous.

**Reuse existing live cards:** `service/app/static/v2/dhl-scan-status.jsx`
(already calls `/dhl/auto-scan-status`) and `service/app/static/v2/dhl-daily-summary.jsx`
(already calls `/dhl/daily-summary`). Compose them; do not duplicate their logic.

**Refresh rule:** auto-load on mount only. A passive client-side **"↻ Reload"** that
re-issues the same 4 GETs is permitted ONLY because it has zero server side-effect. It
must NOT be labeled "Refresh status" / "Re-probe" / "Re-scan", must NOT call any POST,
and a regression test must assert it issues GET-only. If in any doubt, omit it.

---

## 4. VISIBILITY-ONLY INVARIANT (hard gate — reviewer-challenge must block on violation)

The DHL Hub must expose **none** of the following affordances. Any button, link, event
dispatch, or fetch that implies one of these is an automatic BLOCK:

- ❌ Retry send / Resend / Send DSK / Send reply
- ❌ Requeue email / Retry failed / email-queue mutation
- ❌ Trigger scan / Scan now / Run inbox check
- ❌ Run Lane A / Run Lane B / enable follow-up
- ❌ Force status update / mark received / advance state
- ❌ Manual projector refresh / recompute / re-probe (server-side)
- ❌ Any `POST`/`PUT`/`PATCH`/`DELETE` to any endpoint

```
DHL Hub        = Observer (visibility only)
Lane A / B     = Authority (the only actors)
Task Scheduler = Execution engine
```

If the Hub detects an anomaly (failed scan, `lane_b_eligible > 0`, aging item), the
correct UI behavior is to **display it and stop** — never offer a button to act on it.

---

## 5. Scope — files ALLOWED to edit

- `service/app/static/v2/pages-v2.jsx` — **`DhlCustomsPage` only** (mock → live `apiFetch`). Do not touch other components in this file.
- `service/app/static/v2/index.html` — **`page === 'dhl'` route block only** (header text; remove any write-implying action buttons — Sprint 30 lesson). No `actions={...}` with mutation affordances.
- `service/app/static/v2/mock-badge.jsx` — add `'dhl'` to `WIRED_PAGES`.
- `service/tests/test_sprint31_dhl_shell_wiring.py` — NEW regression suite.
- `.claude/memory/PROJECT_STATE.md` — record sprint outcome (post-merge).

May **read/compose** (do not modify): `dhl-scan-status.jsx`, `dhl-daily-summary.jsx`.

---

## 6. FORBIDDEN — files & domains (reviewer-challenge auto-fires)

- ❌ `routes_*.py` / any backend `.py` / `main.py` (no backend changes — endpoints already exist)
- ❌ `dhl_followup_status_projector.py` / projector logic (authority owner — read its output, never change it)
- ❌ Lane A (`scan_dhl_inbox`, scheduled-inbox-check) · Lane B (`dhl_followup_sla`, scheduled-followup-check)
- ❌ Task Scheduler / `dhl-email-auto-scan.ps1` / NSSM / service config
- ❌ email queue / `email_service` / `queue_email` (Lesson E)
- ❌ inventory · wFirma · accounting · customs write paths
- ❌ V1 pages (`shipment-detail.html`, `dashboard.html`) — Lesson F freeze
- ❌ `dashboard-shared.js` domain knowledge — Lesson F shared-layer rule
- ❌ Config / `.env` / standing rules

---

## 7. Implementation steps

1. Read the Sprint 30 Inventory pattern (`inventory-page.jsx` + the `page === 'inventory'` block in `index.html`) — copy its read-only structure (IIFE, `window.EstrellaShared.apiFetch`, per-panel "Read-only" disclaimer, `data-testid`s).
2. In `pages-v2.jsx`, rewrite `DhlCustomsPage`: remove inline `emails` / `sadDocs` / `stages` mock arrays; render from the 4 GET endpoints. Compose the existing `dhl-scan-status.jsx` + `dhl-daily-summary.jsx` cards; add read panels for `/dhl/status` (automation status) and `/dhl/shipments` (shipment rows). Add `data-testid="dhl-hub-root"`.
3. In `index.html`, clean the `page === 'dhl'` header — no write-implying `actions`. Subtitle: read-only descriptor.
4. In `mock-badge.jsx`, add `'dhl'` to `WIRED_PAGES`.
5. Write `test_sprint31_dhl_shell_wiring.py` (§9).
6. Browser-verify (§8). Fix findings inline.
7. Open PR (GATE 1). 7-agent deploy gate. Static-only deploy. Update PROJECT_STATE.

---

## 8. Browser verification plan (GATE 6 — mandatory)

Isolated dev server on `C:\PZ-verify` (temp storage, `API_KEY=""`, `ENVIRONMENT=dev`,
`DHL_AUTO_SCAN_ENABLED=false`, `DHL_FOLLOWUP_ENABLED=false`, `RUN_VERIFY_ON_STARTUP=false`),
Preview MCP. Confirm:

1. `/v2/` loads → DHL nav opens **inside the shell**
2. **No MOCK banner** for DHL
3. `dhl-hub-root` present
4. All read panels render from the 4 GETs (or show a clear backend/data error)
5. `/dhl/status` + `/dhl/shipments` + `/dhl/auto-scan-status` + `/dhl/daily-summary` each fire **GET** and return 200
6. **ZERO POST/PUT/PATCH/DELETE** across the whole session (network log)
7. **Zero** of the §4 forbidden affordances present in the DOM (assert no Retry/Requeue/Scan/Lane/Force/Refresh buttons)
8. Zero console errors caused by Sprint 31 files
9. No Lane A / Lane B trigger fires (check dev logs — automation flags OFF anyway)
10. Standalone DHL behavior unaffected; other shell pages still render

---

## 9. Regression coverage — `test_sprint31_dhl_shell_wiring.py`

Source-grep + contract tests (mirror Sprint 30):
- `'dhl'` in `WIRED_PAGES` (array literal); proforma/inbox/inventory still present
- `DhlCustomsPage` uses `window.EstrellaShared.apiFetch`
- Exactly the 4 allowed endpoints referenced; **none** of the deferred per-batch endpoints present
- **No write HTTP methods** in the DhlCustomsPage region (`method: 'POST'|'PUT'|'PATCH'|'DELETE'`)
- **No forbidden affordance strings** in the DhlCustomsPage region or the `index.html` dhl route: `Retry`, `Requeue`, `Scan now`, `Run Lane`, `Trigger scan`, `Force`, `Re-probe`, `inv:`-style action events, scan/followup POST paths
- `dhl-hub-root` testid present; per-panel read-only disclaimer; required panel testids
- `index.html` renders `DhlCustomsPage`; dhl route header has no write-implying buttons
- Baselines unaffected (frontend-only): PZ 160/160, Carrier ≥381

---

## 10. Deploy & rollback

- **Deploy:** static-only — sync `pages-v2.jsx`, `index.html`, `mock-badge.jsx` → `C:\PZ\app\static\v2\`. No backend restart. Full 7-agent gate (no exceptions). Pre-deploy backup dir. Byte-identical (sha256) verification post-sync.
- **Rollback:** code — `git revert <sprint31 sha>`; production — restore the 3 files from the pre-deploy backup. Static-only, no restart. (Identical profile to Sprint 30.)

---

## 11. Recommended sprint sequence (then reassess)

| Sprint | Page | Status |
|---|---|---|
| 31 | **DHL Hub** | THIS sprint (read-only) |
| 32 | Shipments Hub | next — `/api/v1/dashboard/batches`, lowest effort/risk |
| 33 | Automation Hub | `routes_ai_bridge` read endpoints (verified real) |
| 34 | Intelligence Hub | `routes_intelligence` / `routes_learning` read endpoints |

**Then stop and reassess.**

**Deferred (do NOT schedule yet):**
- **Accounting Hub** — until the 3 missing GET endpoints are implemented, wFirma read authority is reviewed, and the financial-governance campaign is complete (financial/compliance risk + wFirma credential gating).
- **Shipping Hub** — until a real carrier backend exists (currently wireframe-only, no endpoints).

---

## 12. `/run` prompt (paste into a fresh Claude Code session to execute Sprint 31)

```
ROLE: Sprint 31 implementer — DHL Hub (read-only) into V2 shell.
PATH GUARD: C:\PZ-verify only. Base origin/main.

Read .claude/campaigns/atlas-v2/sprint-31-dhl-hub.md and execute it exactly.

Wire DhlCustomsPage (pages-v2.jsx) to live, read-only GET rendering using ONLY
these 4 endpoints — and nothing else:
  GET /api/v1/dhl/status
  GET /api/v1/dhl/shipments
  GET /api/v1/dhl/auto-scan-status
  GET /api/v1/dhl/daily-summary
Compose the existing dhl-scan-status.jsx + dhl-daily-summary.jsx cards.

VISIBILITY-ONLY — the page must NEVER expose: Retry send, Requeue email,
Trigger scan, Run Lane A, Run Lane B, Force status update, Manual projector
refresh, or any POST/PUT/PATCH/DELETE. Observer only; Lane A/B stay the authority.

ALLOWED EDITS: pages-v2.jsx (DhlCustomsPage only), index.html (dhl route block
only), mock-badge.jsx (add 'dhl' to WIRED_PAGES), new
test_sprint31_dhl_shell_wiring.py, PROJECT_STATE.md (post-merge).
FORBIDDEN: routes_*.py, projector logic, Lane A, Lane B, Task Scheduler,
email queue, inventory, wFirma, V1 pages, dashboard-shared.js domain logic,
config/.env.

Then: browser-verify (isolated dev server, automation OFF) per §8, fix findings
inline, open PR, run the 7-agent deploy gate, static-only deploy, update
PROJECT_STATE. Honor all CLAUDE.md gates. Do NOT enable Lane B or touch any
DHL workflow.
```
