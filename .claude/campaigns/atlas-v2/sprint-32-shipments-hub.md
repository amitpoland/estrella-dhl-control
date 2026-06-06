# Sprint 32 — Shipments Hub (read-only batch list)

**Campaign:** Atlas-V2 (V2 shell wiring)
**Sprint:** 32 — Shipments Hub
**Predecessor:** Sprint 31 (DHL Hub) — MERGED `a5a4e5e` (PR #463) + DEPLOYED 2026-06-06
**Branch:** `feat/sprint32-shipments-hub`
**Base:** `origin/main` (HEAD `67707da` at planning time)
**New file:** `service/tests/test_sprint32_shipments_shell_wiring.py` (NEW); no new static file — wire the existing `DashboardPage`
**Authoring audit:** Atlas-V2 Canonical Authority Audit (this session, 2026-06-06, workflow `wf_7a68ba47-9a2`, 18 agents). Shipments selected as the only read-only domain with live authority and zero existing live wiring. Evidence: `routes_dashboard.py` `GET /api/v1/dashboard/batches` (+ `/{id}`, `/{id}/files`) verified real; `DashboardPage` (`dashboard-page.jsx`, route `page === 'shipments'`) still on `MOCK_SHIPMENTS`.

---

## 1. Objective

Replace the inline **mock** data in `DashboardPage` (V2 shell `page === 'shipments'`) with **live, read-only, GET-backed rendering** from existing batch authority. Same pattern as Sprint 30 (Inventory) and Sprint 31 (DHL): existing authority → read-only renderer → browser verification → static-only deploy.

```
Existing batch authority  →  read-only renderer  →  browser verification  →  static deploy
(NOT: new UI → new backend → new authority → new workflow)
```

This Hub is a **visibility surface** over completed batches. It does not start, reprocess, archive, delete, override, or resend anything — those authorities live in V1 dashboard + the engine and are out of scope.

---

## 2. Authority Boundary

```
OWNS (this page):  read-only rendering of the completed-batch list (newest first,
                   deduped per document by the backend), with pipeline status
                   columns and value totals, plus an external carrier-tracking link.

NEVER:             Start batch · Reprocess · Regenerate · Recheck · Resend ·
                   Operator-override · Archive · Restore · Delete batch ·
                   Delete file · CN-decision accept/correct/escalate ·
                   any POST/PUT/PATCH/DELETE · any batch mutation · any
                   email send · any customs/inventory/wFirma write.
```

**Authority owner (backend, unchanged):** `routes_dashboard.py` `list_batches()` →
`_batch_summary(audit.json)`. The frontend is a dumb renderer; the backend remains the
sole authority for batch truth.

---

## 3. The ONLY endpoint this page may consume (exactly 1 — and nothing else)

| Endpoint | Source | Purpose | Load |
|---|---|---|---|
| `GET /api/v1/dashboard/batches` | routes_dashboard.py:490 | completed batches, newest first, deduped per (mrn, doc_no) | auto on mount |

`GET`, `Depends(require_api_key)`, read-only, no mutation. Returns `List[batch_summary]`.

**Do NOT add** in this sprint: `GET /batches/{id}`, `GET /batches/{id}/files`,
`/actions`, `/action-diagnostics`, `/email-evidence*`, `/proforma-readiness`,
`/zc429-lineage`, `/cn-hsn-classification`, `/dhl-action-state`, `/broker-followups`,
`/archive`. They are deferred to keep the surface minimal and unambiguous. The
detail-drill (`/batches/{id}`) belongs to the **shipment-detail** sprint, not this one.

**Field map (verified against `_batch_summary`, routes_dashboard.py:308–351):**

| Column | Live field |
|---|---|
| AWB / Tracking | `tracking_no` (fallback `batch_id`); external link via `tracking_url` when present |
| Carrier | `carrier` |
| DHL / Clearance | `dhl_status` |
| Rec. | `action_reason` |
| SAD | `sad_status` |
| MRN | `mrn` |
| PZ | `pz_status` |
| Net | `net` |
| Gross | `gross` |
| Duty A00 | `duty` |
| Overall | `status` |

**Refresh rule:** auto-load on mount only. A passive client-side **"↻ Reload"** that
re-issues the same GET is permitted ONLY because it has zero server side-effect. It must
NOT be labeled "Reprocess" / "Recheck" / "Refresh batch", must NOT call any POST, and a
regression test must assert GET-only.

---

## 4. VISIBILITY-ONLY INVARIANT (hard gate — reviewer-challenge must block on violation)

The Shipments Hub must expose **none** of the following. Any button, link, event, or
fetch implying one is an automatic BLOCK:

- ❌ Edit Draft / Reprocess / Regenerate / Recheck (mock action menu — REMOVE)
- ❌ Archive / Restore / Delete batch / Delete file
- ❌ Resend / Operator-override / Start batch / Submit
- ❌ CN-decision accept-sad / correct-internal / escalate-agent
- ❌ Any `POST`/`PUT`/`PATCH`/`DELETE` to any endpoint
- ❌ Drill into the V2 `ShipmentDetailPage` (it is mock-shaped — reads `shipment.awb`, does not fetch by `batch_id`; drilling a live row renders an empty page). **Defer** to the shipment-detail sprint.

```
Shipments Hub  = Observer (visibility only)
V1 dashboard   = the existing batch-action authority (unchanged)
Engine         = the only processor
```

If the list shows a blocked/failed batch, the correct UI behavior is to **display its
status and stop** — never offer a button to act on it.

---

## 5. Scope — files ALLOWED to edit

- `service/app/static/v2/dashboard-page.jsx` — **`DashboardPage` only** (mock → live `apiFetch`; remove action menu + pagination; derive summary tiles from live data).
- `service/app/static/v2/mock-badge.jsx` — add `'shipments'` to `WIRED_PAGES`.
- `service/app/static/v2/index.html` — **`page === 'shipments'` route block only** (header subtitle → read-only descriptor; remove the dead `↓ Export CSV` button and the misleading "click any AWB to open detail" promise; drop the now-unused `onViewShipment` prop). Same scope shape as Sprint 31's `page === 'dhl'` header cleanup.
- `service/tests/test_sprint32_shipments_shell_wiring.py` — NEW regression suite.
- `.claude/memory/PROJECT_STATE.md` — record sprint outcome (post-merge).

The shipments route already shows no MOCK banner once WIRED_PAGES includes `'shipments'`.
`DashboardPage` takes no `onViewShipment` prop (no internal drill — see §4). Do not touch
other components.

---

## 6. FORBIDDEN — files & domains (reviewer-challenge auto-fires)

- ❌ `routes_*.py` / any backend `.py` / `main.py` (endpoint already exists)
- ❌ `dashboard-kanban.jsx` (route `page === 'dashboard'` — the aggregator, built LAST)
- ❌ `pages.jsx` `FilteredShipmentsTable` (orphaned legacy table, not route-bound)
- ❌ `shipment-detail-page*.jsx` (separate shipment-detail sprint)
- ❌ V1 pages (`shipment-detail.html`, `dashboard.html`) — Lesson F freeze
- ❌ `dashboard-shared.js` domain knowledge — Lesson F shared-layer rule
- ❌ email queue / `email_service` / `queue_email` (Lesson E)
- ❌ inventory · wFirma · accounting · customs · carrier write paths
- ❌ Config / `.env` / Task Scheduler / NSSM / standing rules

---

## 7. Implementation steps

1. Mirror the Sprint 31 DHL observer structure (`DhlCustomsPage`): `useState` for data/loading/error, `window.EstrellaShared.apiFetch`, passive "↻ Reload", per-surface read-only disclaimer, `data-testid`s.
2. In `dashboard-page.jsx`, rewrite `DashboardPage`: remove the `MOCK_SHIPMENTS` + static `SUMMARY_CARDS` constants; fetch `GET /api/v1/dashboard/batches` on mount; map real fields (§3); derive summary counts from the live rows; keep the filter bar (client-side over live data).
3. Remove the `⋯` action menu (Edit Draft / Reprocess / Archive / Delete) and the `← Prev` / `Next →` pagination (no API pagination). Render AWB as an external `tracking_url` link when present, else plain mono text — **no internal drill**.
4. Add `data-testid="shipments-hub-root"` + panel/table testids.
5. In `mock-badge.jsx`, add `'shipments'` to `WIRED_PAGES`.
6. Write `test_sprint32_shipments_shell_wiring.py` (§9).
7. Browser-verify (§8). Fix findings inline.
8. Open PR (GATE 1). 7-agent deploy gate. Static-only deploy. Update PROJECT_STATE.

---

## 8. Browser verification plan (GATE 6 — mandatory)

Isolated dev server on `C:\PZ-verify` (temp storage, `API_KEY=""`, `ENVIRONMENT=dev`,
`RUN_VERIFY_ON_STARTUP=false`, automation flags OFF), Preview MCP. Confirm:

1. `/v2/` loads → Shipments nav opens **inside the shell**
2. **No MOCK banner** for Shipments
3. `shipments-hub-root` present
4. Table renders from `GET /api/v1/dashboard/batches` (or shows a clear empty/error state when no batches exist in the dev store)
5. The batches GET fires and returns 200; summary tiles + filter operate on live rows
6. **ZERO POST/PUT/PATCH/DELETE** across the whole session (network log)
7. **Zero** §4 forbidden affordances in the DOM (no Edit/Reprocess/Archive/Delete/Resend/Override menu; no Prev/Next)
8. Zero console errors caused by Sprint 32 files
9. AWB external link (if a row has `tracking_url`) opens carrier page in a new tab; no internal navigation to a mock detail page
10. Other shell pages still render; the 5 already-live domains unaffected

---

## 9. Regression coverage — `test_sprint32_shipments_shell_wiring.py`

Source-grep + contract tests (mirror Sprint 31):
- `'shipments'` in `WIRED_PAGES` (array literal); proforma/proforma_detail/inbox/inventory/dhl still present
- `DashboardPage` uses `window.EstrellaShared.apiFetch`
- Exactly the 1 allowed endpoint (`/api/v1/dashboard/batches`) referenced; **none** of the deferred batch sub-endpoints present in the DashboardPage region
- `MOCK_SHIPMENTS` constant removed from `dashboard-page.jsx`
- **No write HTTP methods** in `dashboard-page.jsx` (`method: 'POST'|'PUT'|'PATCH'|'DELETE'`)
- **No forbidden affordance strings** in `dashboard-page.jsx`: `Reprocess`, `Regenerate`, `Recheck`, `Archive`, `Delete`, `Operator-override`, `Resend`, `accept-sad`, `escalate-agent`
- `shipments-hub-root` testid present; read-only disclaimer present
- Baselines unaffected (frontend-only): PZ 160/160, Carrier ≥381

---

## 10. Deploy & rollback

- **Deploy:** static-only — sync `dashboard-page.jsx`, `mock-badge.jsx` → `C:\PZ\app\static\v2\`. No backend restart. Full 7-agent gate (no exceptions). Pre-deploy backup dir. Byte-identical (sha256) verification post-sync.
- **Rollback:** code — `git revert <sprint32 sha>`; production — restore the 2 files from the pre-deploy backup. Static-only, no restart. (Identical profile to Sprint 30/31.)

---

## 11. Recommended sprint sequence (then reassess)

| Sprint | Page | Status |
|---|---|---|
| 32 | **Shipments Hub** | THIS sprint (read-only) |
| 33 | Intelligence Hub | `routes_intelligence` read endpoints (verified real) |
| 34 | Automation Hub | `routes_ai_bridge` read endpoints (verified real; UI currently unused) |
| 35 | Proposals | `routes_action_proposals` read endpoints; fix `proposals → inbox` redirect first |

**Then stop and reassess.**

**Deferred (do NOT schedule yet):**
- **Documents Hub** — claims `/api/v1/pi`, `/api/v1/pz` endpoints that DO NOT EXIST; needs backend first.
- **Accounting Hub** — wFirma write risk + missing read endpoints; financial-governance campaign required.
- **Shipping / Carriers / Master** — write/secret/CRUD surfaces; separate write-safety campaign required.
- **Dashboard (kanban)** — aggregator; built LAST after domain pages stable.

---

## 12. `/run` prompt (paste into a fresh Claude Code session to execute Sprint 32)

```
ROLE: Sprint 32 implementer — Shipments Hub (read-only) into V2 shell.
PATH GUARD: C:\PZ-verify only. Base origin/main.

Read .claude/campaigns/atlas-v2/sprint-32-shipments-hub.md and execute it exactly.

Wire DashboardPage (dashboard-page.jsx, route page === 'shipments') to live,
read-only GET rendering using ONLY this endpoint — and nothing else:
  GET /api/v1/dashboard/batches
Map fields per §3. Derive summary tiles from live rows. Keep client-side filter.

VISIBILITY-ONLY — the page must NEVER expose: Edit Draft, Reprocess, Regenerate,
Recheck, Archive, Restore, Delete, Operator-override, Resend, CN-decision, or any
POST/PUT/PATCH/DELETE. Remove the mock action menu + Prev/Next pagination. Render
AWB as an external tracking_url link only; DO NOT drill into the mock
ShipmentDetailPage (defer to the shipment-detail sprint).

ALLOWED EDITS: dashboard-page.jsx (DashboardPage only), mock-badge.jsx (add
'shipments' to WIRED_PAGES), new test_sprint32_shipments_shell_wiring.py,
PROJECT_STATE.md (post-merge).
FORBIDDEN: routes_*.py, dashboard-kanban.jsx, pages.jsx, shipment-detail-page*.jsx,
V1 pages, dashboard-shared.js domain logic, email queue, inventory, wFirma,
accounting, carrier writes, config/.env.

Then: browser-verify (isolated dev server) per §8, fix findings inline, open PR,
run the 7-agent deploy gate, static-only deploy, update PROJECT_STATE. Honor all
CLAUDE.md gates.
```
