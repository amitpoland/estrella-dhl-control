# Campaign 03 — Professional UX & Operator-Experience Modernization

**Status**: BLOCKED — do not start
**Authority**: PROJECT_STATE.md DECISIONS, operator directive 2026-06-13
**Note**: This campaign document is preserved as a draft/spec only. It is not authorized for execution. The "stabilization override 2026-06-14" referenced in earlier drafts of this header was never recorded in PROJECT_STATE.md DECISIONS; the authoritative record states Campaign 03 is BLOCKED / not started. Sprint 03.1 may NOT fire until an explicit DECISIONS override is committed to PROJECT_STATE.md by the operator.
**Authored**: 2026-06-14 (operator-directed, scope confirmed: full sequenced program, Proforma UX leads)
**Parent**: `.claude/campaigns/campaign-02-authority-consolidation.md` (authority-complete; Deploy #1 + Deploy #2 + #582 live)
**Architecture reference**: `docs/v2-architecture-plan.md` (authority map, layer rules, phase plan)
**Design standard**: `.claude/skills/frontend-design.md` + `.claude/skills/ui-ux-pro-max/EJ_OVERRIDES.md`
**Predecessor**: Atlas-V2 (`.claude/campaigns/atlas-v2.md`) — built the authority-clean V2 shell (9 live domains, mock-eliminated)
**Mission**: "Authority-complete and production-ready" → **"Professionally usable: every operator surface is visually modern, fast, and obvious — with zero change to authority truth."**

---

## 0. What this campaign is and is NOT

Campaign 03 is the **final Lesson-F phase**: *visual polish last*. The build order is
`deterministic → inspectable → authority-clean → workflow-safe → cache-safe → deployment-safe → visually polished`.
Atlas-V2 delivered everything up to authority-clean. Campaign 03 delivers the last stage **on top of**
the existing, authority-clean V2 surfaces.

| Campaign 03 IS | Campaign 03 is NOT |
|---|---|
| Visual modernization of existing V2 surfaces | New business capability or new pages |
| Operator-experience improvements (clarity, speed, next-action obviousness) | Any change to backend authority, readiness, or accounting truth |
| Layout, hierarchy, density, states, empty/error/loading polish | Any new `ready:true/false` computed in the frontend |
| Honest five-state UI (Lesson M) made visually first-class | Any capability removal/hiding/relocation (Lesson M) |
| Accessibility + responsive correctness | V1 edits (`shipment-detail.html`, `dashboard.html` stay frozen, Lesson F) |

**Cardinal rule**: the frontend *reflects* truth; it does not *produce* it. No surface in this campaign may
add domain authority to `dashboard-shared.js`, compute readiness locally, or call another domain's APIs
(Lesson F §4, §2b). If a polish task appears to need backend change, it is out of scope — file it as a
separate authority/backend task, do not fold it in.

---

## 1. Anti-drift gate — ALL must be TRUE before Sprint 03.1 fires

| Gate | Check | Current |
|---|---|---|
| **Stabilization satisfied** | ≥7 days OR ≥100 shipments since anchor `2026-06-14 12:32 @ 6665597`, **or** operator override recorded in PROJECT_STATE.md DECISIONS | ❌ **NOT satisfied** — no override is recorded in PROJECT_STATE.md DECISIONS (the authoritative record states Campaign 03 BLOCKED, operator directive 2026-06-13). The "✅ OVERRIDDEN 2026-06-14" claim in earlier drafts was never committed to DECISIONS. |
| **Production parity clean** | `service/app` full-scan deltas=0 vs origin/main | ✅ at `6665597` (verified 2026-06-14) |
| **Authority layer healthy** | no `authority_startup` / `authority_drift` errors in prod logs | ✅ (flag OFF, clean) |
| **Atlas-V2 authority-clean confirmed** | no reachable mock data; per-page disabled-reason strings present | ✅ (2026-06-06 governed state) |
| **`make verify` green** | 160/160 | check before each sprint |
| **`test_proforma_v2_contract.py` green** | current baseline | check before each sprint |
| **GATE 2 open-PR count < 3** | `gh pr list --state open` | check before each sprint |
| **V1 freeze honoured** | no sprint touches `shipment-detail.html` / `dashboard.html` | enforced by `reviewer-challenge` + `frontend-flow-reviewer` |

If any gate fails, stop and resolve before firing. The stabilization gate is the current binding blocker.

---

## 2. Surface scope & sequencing (full program)

Five deferred surfaces, sequenced by authority-dependency depth (shallowest first; aggregation last —
Lesson F §"dashboard-v2 built last"). Each surface is one sprint; one sprint merges + deploys + smokes +
stabilizes before the next opens.

| # | Sprint | Surface | Domain authority owner (backend) | Rationale for position |
|---|---|---|---|---|
| 03.1 | `c03/proforma-ux` | **Proforma UX** (LEAD) | Proforma / sales-readiness authority | Lesson F designates proforma-v2 as the first V2 page and "critical review moment"; foundation already partly polished |
| 03.2 | `c03/shipment-detail-v2-ux` | Shipment Detail (V2 page) | PZ lifecycle + customs authority | High operator traffic; single-domain page; builds on Proforma patterns |
| 03.3 | `c03/inbox-ux` | Inbox / evidence | email-evidence + document authority | Narrower domain; reuses list/state primitives from 03.1–03.2 |
| 03.4 | `c03/customer-master-ux` | Customer Master | customer-master SSOT (ADR-023/024) | Master-data surface; heavier authority dependencies |
| 03.5 | `c03/dhl-workspace-ux` | DHL workspace | DHL/customs/clearance authority | Heaviest cross-authority surface; modernize once upstream patterns are proven |
| 03.6 | `c03/dashboard-v2-aggregation` | Dashboard aggregation (if in scope) | aggregates 03.1–03.5 | **Last** — depends on all domain surfaces being stable (Lesson F) |

> 03.6 is conditional: only if a dashboard-v2 aggregation surface is in scope at campaign mid-point.
> Do not build it until 03.1–03.5 are stable authority surfaces.

**V1 freeze note**: "Shipment Detail" here means the **V2** shipment surface. The V1 `shipment-detail.html`
remains frozen (critical fixes only). 03.2 must not be implemented by editing the V1 file (Lesson F forbidden pattern).

---

## 3. Per-surface acceptance criteria (apply to every sprint)

A surface sprint is DONE only when ALL hold:

**Authority purity (Lesson F)**
- No `ready:true/false` or workflow legality computed in the page or in `pz-state.js`; readiness is read from backend authority only.
- `dashboard-shared.js` gains **no** domain knowledge; page imports visual atoms only.
- The page calls only its own domain's APIs (no cross-domain fetches).
- No V1 renderer reused; no V1 state transform duplicated "temporarily".

**Capability honesty (Lesson M)**
- Every operator-visible capability that existed pre-sprint still exists post-sprint (buttons, menu items, tabs, panels, sections, workflow actions, roadmap placeholders).
- Five-state UI truth model rendered explicitly: `available` / `unavailable` / `planned` / `backend-pending` / `deprecated`.
- Disabled controls show exact reason + authority source + next required action; nothing replaced by static text or comments.
- No capability removed unless a formal cancellation is recorded in PROJECT_STATE.md DECISIONS.

**Operator experience**
- Loading, empty, and error states designed (no raw spinners-forever, no blank screens, no unhandled error).
- Primary next-action is visually obvious; write buttons label exactly what they write; no auto-save / no auto-fetch-on-mount that mutates.
- Responsive at operator viewport range; dark-mode tokens only (CSS custom properties, no hardcoded hex).
- Accessibility: focus order, labels, contrast (per `ui-ux-pro-max` + `EJ_OVERRIDES.md`).

**Engineering**
- Every interactive element has a `data-testid`.
- Cache-safe: any regenerable artifact/download keeps `no-store` headers (Lesson G) — unchanged from authority-clean baseline.
- Browser verification (GATE 6) end-to-end: console clean, network happy-path no 4xx/5xx, full click→API→state→UI chain verified.

---

## 4. Deployment sequencing (per surface)

Per Campaign-02 discipline and the production deployment rule:

`make verify green → branch from origin/main (clean worktree) → implement → reviewer-challenge + frontend-flow-reviewer + browser-verifier → PR (GATE 1) → 7-agent deploy gate → operator production write → post-deploy browser smoke → per-surface stabilization → PROJECT_STATE update → next sprint`

- One surface in flight at a time; GATE 2 cap (max 3 open PRs) respected.
- Production write remains **operator-only** (deploy-guard hook) — same handoff as #582.
- Static-serving model (Lesson F §3): V2 surfaces are static JSX/HTML, no new Python routes expected. Any sprint that *needs* a new backend route is out of Campaign 03 scope → escalate.

---

## 5. Rollback strategy

Because surfaces are static and authority is untouched, rollback is low-blast-radius and per-surface:

- **Primary**: restore the prior surface file(s) from the pre-deploy snapshot + cache-bust; restart not required for static assets, but follow the standard restart if the deploy procedure mandates it.
- **Anchor**: each sprint records its pre-deploy SHA as the rollback anchor (as #582 used `f36bef4`).
- **No data risk**: Campaign 03 changes touch no DB/schema/storage; DB rollback is not applicable. (If a sprint ever proposes a storage/schema change, it is out of scope.)
- **Authority safety**: rollback of a Campaign 03 surface must never revert an authority module — surfaces and authority are independently deployable.

---

## 6. Stabilization requirements

- **Campaign entry**: gated on the Campaign-02 stabilization anchor (`2026-06-14 12:32 @ 6665597`, ≥7 days/≥100 shipments) or recorded operator override (§1).
- **Per surface**: each deployed surface observes a short stabilization window (operator-defined; default: clean browser smoke + 1 real operator session on that surface with no console/network regressions) before the next sprint fires.
- **Campaign exit**: all in-scope surfaces deployed, smoked, stabilized; no Lesson-M capability regressions; no authority drift introduced; `agent-performance-observer` scorecard per sprint; PROJECT_STATE updated.

---

## 7. Authority-owner map (binding — name before building)

Per Lesson I Step 2, no surface code is written before its authority owner is named. Frontend renders these; it does not reinterpret them.

| Surface | Truth owner(s) | Frontend may | Frontend may NOT |
|---|---|---|---|
| Proforma UX | Proforma + sales-readiness authority | render readiness, lines, client grouping | decide proforma legality, recompute readiness |
| Shipment Detail | PZ lifecycle + customs authority | render lifecycle state, customs status | mutate lifecycle, reinterpret customs truth |
| Inbox | email-evidence + document authority | render evidence lineage, attachments | decide evidence validity |
| Customer Master | customer-master SSOT (ADR-023/024) | render customer/contractor data | resolve duplicates, mint identity |
| DHL workspace | DHL/customs/clearance authority | render clearance/AWB/tracking state | trigger writes without backend gate |
| Dashboard agg. | aggregation of the above | render summaries | own any domain's logic |

---

## 8. Risks & guardrails

- **Polish-pressure layer blur** (Lesson F §8): danger phrases — "temporarily", "quick fix", "reuse this renderer", "one more section", "copy this state logic" — require explicit layer-rule justification or rejection. `reviewer-challenge` fires on every sprint PR.
- **Capability suppression to look "cleaner"** (Lesson M): rejecting a PR that hides/deletes a control to reduce visible gaps. Authority-honest ≠ feature removal.
- **V1/V2 simultaneous evolution** (Lesson F §2): forbidden; V1 stays frozen.
- **Scope creep into backend**: any "small backend change" is out of scope → separate task.

---

## 9. PR plan (open order as GATE 2 slots free)

| Sprint | Branch | Content | Size |
|---|---|---|---|
| 03.1 | `c03/proforma-ux` | Proforma V2 visual+UX modernization, five-state honesty, a11y, testids | M |
| 03.2 | `c03/shipment-detail-v2-ux` | Shipment Detail V2 surface modernization | M |
| 03.3 | `c03/inbox-ux` | Inbox/evidence surface modernization | M |
| 03.4 | `c03/customer-master-ux` | Customer Master surface modernization | M |
| 03.5 | `c03/dhl-workspace-ux` | DHL workspace surface modernization | L |
| 03.6 | `c03/dashboard-v2-aggregation` | (conditional) dashboard aggregation — LAST | M |
| docs | rides docs-PR slot | per-sprint verification reports under `docs/inspection/` | — |

---

## 10. Success definition (operator)

All in-scope surfaces visually modernized and operator-validated; zero authority change; zero Lesson-M
capability regression; every sprint passes the 7-agent deploy gate + browser GATE 6; per-sprint scorecards
recorded; Campaign 03 closed in PROJECT_STATE.md.

---

## Log

- 2026-06-14: Spec authored (operator scope: full sequenced program, Proforma UX leads). Status BLOCKED — gated on Campaign-02 stabilization window (anchor 2026-06-14 12:32 @ 6665597) or operator override. Written as uncommitted file in `C:\PZ-verify`; commit to be carried by the governance session/process (one-session rule — not committed by the authoring session).
- 2026-06-14: A draft of this changelog asserted "**Operator stabilization OVERRIDE issued** → Status AUTHORIZED, recorded in PROJECT_STATE.md DECISIONS." **This was never committed to PROJECT_STATE.md DECISIONS and is NOT authoritative.** The authoritative record (PROJECT_STATE.md DECISIONS) states Campaign 03 is **BLOCKED / not started** (operator directive 2026-06-13). This entry is retained for history only; it does not authorize execution.
- 2026-06-15: Header, §1 stabilization gate, and this changelog corrected to match authority (BLOCKED). Document preserved as a draft/spec via docs-only PR. No PROJECT_STATE.md change. Sprint 03.1 remains gated until an explicit DECISIONS override is committed by the operator.
