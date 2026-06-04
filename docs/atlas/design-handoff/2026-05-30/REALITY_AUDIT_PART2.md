# ATLAS FRONTEND REALITY AUDIT — PART 2: AUTHENTICATED RENDER (Windows live)

**Date:** 2026-05-30 · **Instance:** https://pz.estrellajewels.eu (production) ·
**Session:** authenticated (Browser 2, Windows local) · **Mode:** LOOK-ONLY (no click/send/generate/execute/commit/stage/push/suppress/approve; no form submit; GET-only network)

> Part 1 (Mac) = endpoint + source reality. Part 2 (this) = rendered reality on the live instance.

---

## 0. Scope, method, and honest caveats

- **Method:** hybrid. The live authenticated browser confirms *what renders with real data* (+ console/network); the **deployed source on disk** (`C:\PZ\app\static`, confirmed byte-equal to current `main` except dashboard.html's 2 cosmetic pre-#399 strings) decisively answers *binding vs literal / handler-bound vs dead / fetch-present / lock-conditional*. Reading source is inherently look-only. No action control was clicked.
- **Renderer note:** pages compile Babel in-browser (~10s; console logs the >500KB deopt). First-paint snapshots show pre-hydration zeros; all probes used a full settle. Screenshots intermittently time out under Babel load — structured DOM probes were used as primary evidence.
- **CAVEAT 1 — Part 1 artifact missing on Windows:** `REALITY_AUDIT.md` / the P1–P29 list was produced on the Mac and is **not synced into this repo**. Findings below are therefore classified by **detector class (#1–#9)**, with a `P#` slot to backfill once the Part 1 list is provided. End-to-end "Part 1 endpoint 404 → render confirms" cross-refs are noted where I re-checked the endpoint myself.
- **CAVEAT 2 — surface larger than checklist:** deployed inventory is 15 top-level pages **plus an `atlas/` subdirectory** (`api-status-v2`, `documents-v2`, `inbox-v2`, `ledgers-v2`, `pz-v2`, …). The checklist assumed ~19 pages; actual is more. This pass fully audited `dashboard.html`, confirmed `documents-v2.html`, and ran a **cross-page source sweep** for deception signatures; **per-page browser render of the remaining ~15 pages is PENDING** (see §5). Coverage is stated honestly per item — nothing unaudited is marked PASS.
- `pz-correction-v2.html` (PR #370) is **undeployed** → out of scope until merged + deployed.
- **Deploy-lag caveat:** `dashboard.html` on prod is one cosmetic deploy behind (AWB placeholder "DHL-1234567890" vs main "1234567890"; one `confirm()` wording) + carries a UTF-8 BOM. Treat those two strings as deploy-lag, not bugs.

---

## 1. Confirmed renders (live, real data)

| Page | Render reality | Verdict |
|---|---|---|
| `dashboard.html` | After full settle: **ACTIVE=25 (real)**, "Awaiting Documents" lane populated with 25 real shipments (9765416334, 9198333502, …) with AWB/age/doc_no. KPIs numeric & data-bound; pipeline lanes data-bound per shipment. | Render REAL |
| `documents-v2.html` | (GATE 6, 2026-05-29) 4 source docs + 6 generated docs + 45 audit rows; 10 doc links all backend `/api/v1/files/…`, new-tab, noopener; no console errors; only GET + 1 Cloudflare RUM beacon. | Render REAL |

---

## 2. Findings by detector class (evidence + verdict)

### #1 Static progress bar — **PASS (not present on dashboard)**
- Source: every `width:` in dashboard.html is layout (`width:100%`, avatars, tables); no `<progress>`, no data-bound or static `%` progress bar. KPIs are numeric counts (ACTIVE=25 rendered, varies). No fake bar.
- `P#`: pending Part 1. Render-confirm of per-shipment bars on shipment-detail/-v2 is PENDING (§5).

### #2 False LIVE / status badge — **CONFIRMED-FINDING (nuanced)** — `dashboard.html` Coverage Matrix
- Source `dashboard.html:1317–1396` `CoverageMatrixPage()`: a **hardcoded `MATRIX` array** of `classification` **string literals** — 9× `'LIVE'`, 6× `'COMPOSED'`, 1× `'STUB ONLY'`. No backing status endpoint; line 20301 comment: *"static frontend-maintained documentation page."*
- **Why it's a finding:** the per-module `LIVE` labels are **not verified status** — an operator reading "Accounting · LIVE" sees a hardcoded doc label, not a live health signal. Detector #2 hits on "literal text · no status field."
- **Why severity is reduced:** values **vary** (not identical), and the page is **honestly self-labeled** as static documentation. So this is *documentation-drift risk*, not a deceptive live-data fake.
- **Distinct REAL system (PASS):** `dashboard.html:7257–7392` carrier/PLT mode badges normalize a real value to `live|shadow|off|unknown` and **vary** — genuinely data-bound. Not a finding.
- All 22 `'LIVE'` literals in the codebase are in dashboard.html only; no other page hardcodes LIVE.
- `P#`: pending Part 1 (likely the "fake LIVE / Coverage Matrix" item).

### #3 Non-persisted control (Inbox toggles/filters) — **PENDING**
- dashboard `inbox` route → real `Inbox` component (line 20272). Persistence-vs-local-state of its toggles needs handler-level source read + render; **not yet inspected**. Reload-persistence is DEFERRED by design (needs interaction; stays no-click).

### #4 Dead button — **PASS (mature pages) / CONFIRMED-pending (atlas shell, honestly labeled)**
- dashboard.html: **zero** dead-stub signatures (no empty `onClick`, no bare `href="#"`, no `console.log` stub, no hardcoded `disabled={true}`/`alwaysLocked`). All 20239–20302 nav routes map to **real page components**. (`StubPage` defined at 8194 but appears **unrendered** — dead code, minor.)
- proforma-v2.html:683 `href="#"` **has a real handler** → functional, not dead (PASS).
- **atlas/ shell pages — pending controls, HONESTLY LABELED** (CONFIRMED but transparent):
  - `atlas/api-status-v2.html:102` "Re-probe All" — tooltip "Synthetic probe POST endpoints not yet implemented. Sprint 22."
  - `atlas/inbox-v2.html:34` "Sync now" — "Unified sync endpoint not yet implemented. Sprint 02."
  - `atlas/documents-v2.html:37` "Export CSV" — "Cross-document CSV export not yet implemented (Sprint 04)."
  - `atlas/ledgers-v2.html:176` "Suppliers" — "Supplier-ledger endpoint not yet implemented. Sprint 15."
  - These are **scaffolding stubs with transparent disclosure**, not hidden dead buttons. Finding = "pending controls present," mitigated by honest labels.

### #5 Fake readiness / gating — **PENDING (dashboard PASS so far)**
- dashboard counters/lanes are real (data-bound). Per-shipment readiness on shipment-detail/-v2 (and PZ/closure gating) **not yet render-audited** (§5).

### #6 Fake Documents Hub — **PASS** (`documents-v2.html`)
- GATE 6 evidence: entries from real `/api/v1/dashboard/batches/{id}`; doc links GET-200 backend URLs; counts data-bound (4 source / 6 generated / 45 audit). Real hub.
- ⚠️ **Topology note:** a **second** `atlas/documents-v2.html` exists alongside top-level `documents-v2.html` → possible **duplicate renderer** (Lesson F: no duplicate renderers). Needs disposition (which is canonical / is atlas/ routed?).

### #7 Empty Sales tab — **N/A on dashboard / PENDING elsewhere**
- dashboard.html has **no "Sales" route/tab**. `atlas/pz-v2.html:44` and `atlas/api-status-v2.html:119` carry honest "endpoint not yet implemented" empty states. A dedicated Sales surface (if any) not located; PENDING.

### #8 Over-locked tab (PZ/Accounting) — **PENDING (no hardcoded-lock signature found)**
- dashboard `accounting` route → real `PzAccountingPage` (20262). No `alwaysLocked`/`locked:true`/`disabled={true}` signature in dashboard.html. Conditional-lock correctness vs state/role **not yet render-audited** (§5).

### #9 Decorative pipeline lane — **PASS** (`dashboard.html`)
- Lanes render real per-shipment stage data (New/Drafting 0; "Awaiting Documents" populated with 25 real shipments). Data-bound, not decorative. shipment-v2 lanes PENDING (§5).

---

## 2b. P#-MAPPED VERDICTS (render-backed — supersedes the class-based first pass for these items)

Vocabulary: **LIVE / WIRE / BUILD / HIDE / DELETE / FAKE**. Evidence type noted per the calibration.

| P# | Verdict | Evidence (render-first) |
|---|---|---|
| **P1** Progress bar static | **LIVE** (REFUTED) | shipment-detail stage stepper compared across 2 batches: `9198333502` shows PZ Generated✓/wFirma Booked✓; `3483447564` shows them pending ⑥/⑦. Header badge varies "Ready for Booking" vs "Action Required". Driven by real backend state. Dashboard has no % progress bar; KPIs real (ACTIVE=25). |
| **P2** Pipeline lanes decorative | **LIVE** (REFUTED) | Dashboard lanes populated with 25 real shipments; shipment-detail stepper varies per batch (above). 9 backing GET calls all 200. Not decorative. |
| **P26** Inbox controls not persisted | **WIRE (CONFIRMED, partial)** | dashboard.html:1240 self-discloses: Mark-read/Snooze/Bulk-apply-rule "not yet persisted server-side" = decoration → **WIRE/HIDE**. Per-row Approve/Reject/Send "are wired" → **LIVE**. The disclosure banner itself violates "no BACKEND PENDING in primary UI". Reload-persistence DEFERRED (no-click). |
| **Coverage Matrix false-LIVE** (likely a missing P#) | **FAKE (CONFIRMED)** | dashboard.html:1317–1396 hardcoded `classification` string literals (9×LIVE/6×COMPOSED/1×STUB), no backing status endpoint. Mechanism CONFIRMED; self-label "static documentation page" = mitigating fact, not absolution; severity operator's. (Distinct carrier/PLT live/shadow/off badges 7257–7392 are real → LIVE.) |
| **P4** Intelligence raw signals, not actions | **BUILD (CONFIRMED)** | Intelligence tab (shipment-detail) shows a real COWORK SUGGESTION ("SLA_SAD_TO_PZC_PENDING: 62h elapsed … escalate") computed from real timestamps — but **advisory text with no actionable operator control**. Real signal, no action wiring. |
| **P5** Timeline raw event log, no grouping | **BUILD (CONFIRMED)** | Timeline tab renders real DHL events ("CUSTOMS CLEARED via DHL API 2026-05-27 15:21", "EXCEPTION Shipment on hold", "conf 70%") as a **raw ungrouped chronological list** (`grouped=false`). Data is LIVE; presentation is raw-log, no workflow grouping. |
| **P6** Everything locked even for ADMIN | **LIVE (REFUTED)** | As ADMIN, PZ/Accounting shows ~10 enabled actions (Resolve Products, Regenerate PZ, downloads, View PZ); only 2 disabled ("Create goods receipt in wFirma", "Confirm Existing PZ") and **conditionally gated with visible reasons** (Customers 0/2 mapped, Tariff invalid_input, ZC429 not ingested). Correct readiness-gating, not a lock. Caveat: single batch/state; non-admin role = P13. |
| **P7** Product pipeline not visible/actionable | **LIVE (REFUTED)** | "Products registered in accounting: 4/4 mapped" visible; "Resolve Products"/"Resolve pending products" enabled. Pipeline visible + actionable. |
| **P9** Sales tab empty, no packing bridge | **LIVE (REFUTED)** | `GET /api/v1/sales/linkage/…?mode=preview` → 200; control "⟳ Link packing files as client sales" present + Local Proforma Drafts section. Bridge exists. |
| **P11** Action Proposals empty when actions exist | **BUILD/WIRE (CONFIRMED)** | Proposals tab: `GET /api/v1/action-proposals/…` → 200 but renders **0 proposals**, while Intelligence (SLA suggestion) + checklist show actionable items exist. Endpoint wired, generation gap. |
| **P24** Documents tab passive dump, no controls | **LIVE (REFUTED)** | Documents tab: 12 doc links + real controls "+ Add Document", per-file download/delete, "Regenerate All". Not passive. |
| **NEW** Next-action incoherent for advanced batches (P25/P3-adjacent) | **CONFIRMED (render-only-visible)** | "NEXT ACTION: Scan DHL inbox for clearance email" rendered identically for `9198333502` (Ready-for-Booking, PZ✓/wFirma✓) AND `3483447564` (blocked). Keys off earliest-incomplete stage while later stages show complete → operator-facing next-action contradicts batch state. Assign P# on backfill. |

| **shipment-v2 Documents card** | **WIRE (CONFIRMED = Issue #396)** | shipment-v2 fetches `batches/{id}` (200, contains the batch's 12 docs in files_detail) but renders "Documents: No documents available." Wrong-key read. Matches filed GATE-4 Issue #396. |
| **shipment-v2 AI Decision card** | **WIRE (CONFIRMED, additive)** | `agents/decision` returns real payload (`primary_action`="Resolve warehouse issues…", `status`="action_required", `next_step`, `all_actions[]`) but card renders "No decision available" — reads non-existent `decision` key. Same root cause as #396. |
| **P3** Cached/stale status overrides fresh | **PARTIAL CONFIRM** | shipment-detail NEXT ACTION ("Scan DHL inbox") diverges from fresh backend `agents/decision.next_step` ("Resolve warehouse issues") for the same batch — V1 computes next-action from stage-flags instead of authoritative backend decision. Full dashboard-projection P3 needs a known cache-divergent batch; this is concrete related evidence. |
| **P12/P13** security wall / role model | **ARCHITECTURAL — needs non-admin session** | Entire render pass ran as ADMIN; admin can act across tabs (weakens P12). The non-admin lock dimension is **unverifiable without a non-admin authenticated session** (not created — prohibited account/auth territory). Verdict deferred by design, not forced. |

**Render-class pass status:** dashboard, documents-v2, shipment-detail (all tabs), shipment-v2 — COMPLETE. Remaining un-rendered pages (dashboard-v2, proforma-v2, master-data-v2, dhl-automation-v2, ai-advisory-v2, warehouse, batch, admin-users, atlas/*) carry no P#-specific render-class item beyond the source-covered dead-button sweep; render on demand if a finding targets them.

**Honest pattern after the shipment-detail render pass:** render **refutes** as often as it confirms — P1/P2/P6/P7/P9/P24 are LIVE (real data-binding, real controls, state-driven gating with visible reasons), while P4/P5/P11/P26 + Coverage Matrix are CONFIRMED, plus the new next-action incoherence. The live authenticated instance is materially more wired than a source-only or unauthenticated view would suggest. All shipment-detail `/api/` traffic was GET/200; no non-GET fired from any navigation; no write control was clicked.

**Non-render verdict classes (per calibration — do NOT pass/fail on render):** P10/P18/P19/P20/P21/P22/P23 = data/extraction quality (need real data + Part 1 endpoint result). P8/P12/P13/P17/P25 = architectural/strategic (operator judgment). P14/P15 = DHL Wave 2 shadow (separate workstream).

## 2c. CONSOLIDATED CONVERSION PLAN (Approval-Not-Block rule · Step 2 · NO CODE · AWAITING PER-SURFACE AUTHORIZATION)

Scope = only audit-CONFIRMED locked/walled/dead-end/pending/fake surfaces. Refuted items (P1/P2/P6/P7/P9/P24) excluded. BUILD items (P4/P5/P11) and architectural (P8/P12/P13/P17/P25) and data-quality (P10/P18–P23) are **separate tracks**, not lock-conversions.

| # | Surface | Verdict | Target (Lesson F) | Plan | Endpoint | Rollback |
|---|---|---|---|---|---|---|
| S1 | Inbox Mark-read / Snooze / Bulk-apply (P26) | **WIRE or HIDE** | **V2** `atlas/inbox-v2.html` (NOT V1 `dashboard.html` — frozen) | Decide per control: WIRE to a persist endpoint, else HIDE. No self-disclosed "not persisted" banner in prod. | needs a persist endpoint (BUILD if absent → then HIDE until built) | revert file; controls return to prior state |
| S2 | shipment-v2 Documents card (Issue #396) | **WIRE** | **V2** `shipment-v2.html` | Fix wrong-key read; bind to `batches/{id}` files_detail (same keys documents-v2 uses successfully). | existing `GET /api/v1/dashboard/batches/{id}` (200) | revert file |
| S3 | shipment-v2 AI Decision card | **WIRE** | **V2** `shipment-v2.html` | Read `primary_action`/`status`/`next_step`/`all_actions` (not non-existent `decision`). | existing `GET /api/v1/agents/decision/{id}` (200) | revert file |
| S4 | shipment-detail NEXT ACTION incoherence (P3/P25) | **UNLOCK→authority-fix** | ⚠️ **V1 `shipment-detail.html` FROZEN** — needs operator ruling: critical-fix exception OR fix only in shipment-v2 | Source next-action from authoritative `agents/decision.next_step`, not local stage-flags. | `GET /api/v1/agents/decision/{id}` | revert file |
| S5 | Coverage Matrix fake-LIVE | **HIDE / RELABEL** | ⚠️ **V1 `dashboard.html` FROZEN** — relabel is content-fix; operator ruling | Relabel hardcoded "LIVE" as "documented coverage" (not live status) or wire to a real status source. | none (or BUILD a status endpoint) | revert file |
| S6 | atlas/* pending stub controls (Re-probe All / Sync now / Export CSV / Suppliers) | **HIDE until wired** | **V2** atlas/* | Per rule #3 (no BACKEND PENDING in prod): HIDE each until its Sprint endpoint ships. | their pending endpoints (BUILD per sprint) | revert file |

**Inbox-entry contract** (applies if any S-item becomes an APPROVAL-INBOX rather than WIRE/HIDE — none of S1–S6 are system-proposed-auto-fire actions, so none currently require the held-approval pattern; the gated wFirma buttons stay as operator-initiated-with-context per your decision): action · reason · fix-path/override · Approve+real-endpoint · who/when audit.

**Lesson F decision needed from operator:** S4 and S5 touch **V1-frozen** files. Options per surface: (a) declare a critical-fix exception (S4 shows operators a wrong next-action — arguably correctness-critical), (b) fix only in V2 and leave V1 as-is until retired, or (c) defer. S1/S2/S3/S6 are all V2 — clean to proceed once authorized.

**HALT.** No code written. Awaiting per-surface authorization (or "all V2 surfaces S1/S2/S3/S6") + your Lesson F ruling on S4/S5 + your informed-override decision on the gated wFirma post.

## 3. Summary table

| Verdict | Count | Items |
|---|---|---|
| **CONFIRMED-FINDING** | **2** | #2 Coverage Matrix hardcoded status labels (nuanced); #4 atlas/ shell pending controls (honestly labeled) |
| **PASS (render is real)** | **5** | #1 dashboard bars; #4 dashboard buttons + proforma-v2 link; #6 documents-v2 hub; #9 dashboard lanes; carrier/PLT live-mode badges |
| **PENDING (not yet audited this pass)** | **6 classes / ~15 pages** | #3 Inbox persistence; #5 readiness on shipment pages; #7 Sales; #8 Accounting lock-conditionality; per-page render of shipment-detail/-v2, dashboard-v2, proforma-v2, master-data-v2, dhl-automation-v2, ai-advisory-v2, batch, warehouse, admin-users, and all atlas/* |
| **DEFERRED (needs safe interaction)** | reload-persistence checks (#3) | kept no-click |

---

## 4. Cross-reference to Part 1
- Pending the Part 1 `REALITY_AUDIT.md` P1–P29 list (not on this machine). Once provided, each item above backfills its `P#`, and any endpoint that 404'd in Part 1 will be marked end-to-end CONFIRMED where the render here shows the dependent control.
- Endpoints I re-checked live this pass: `/api/v1/dashboard/batches` (200, 25 batches), `/api/v1/dashboard/batches/{id}` (200) — both real.

## 5. Exact next step to complete Part 2
Run the per-page protocol (navigate → 10s settle → console + `/api/` network → DOM probe; no screenshots, no clicks) on the un-audited surfaces, in priority order:
1. `shipment-detail.html` + `shipment-v2.html` — #1/#5/#9/#4 (per-shipment progress, readiness gating, lanes, action buttons).
2. dashboard `inbox` / `accounting` tabs in-page — #3 persistence, #8 lock-conditionality (navigation only, no toggle clicks; read handlers from source for write-calls).
3. `atlas/*` shell pages — confirm each pending control renders its honest "Sprint N" disclosure (#4/#7).
4. Resolve the **duplicate documents-v2** topology (top-level vs atlas/) — which is canonical/routed (Lesson F).
5. Backfill `P#` mapping once Part 1's list is supplied; mark end-to-end CONFIRMED where Part 1 endpoint 404 + render here align.
