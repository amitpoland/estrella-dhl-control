# ACTIVE_CAMPAIGNS.md — EJ Dashboard Active Campaign Registry

**Status: ACTIVE.** Read by `ej-dashboard-master` at Session Bootstrap and at task start, so
long-running campaigns are **continued, not restarted**, across sessions.

> This is a **state registry, not a planning tool.** It holds only where each campaign is and
> what's next — no Gantt charts, estimates, deadlines, or assignments. It is an **index**, not a
> second source of truth: detailed campaign state stays owned by the authoritative docs
> (`.claude/campaigns/*`, `.claude/memory/PROJECT_STATE.md`); this file points to them and must
> stay consistent with them. Never let it fork campaign authority.

**Status vocabulary (use exactly these):** `PLANNED` · `ACTIVE` · `BLOCKED` · `ON HOLD` ·
`REVIEW` · `COMPLETE` · `ARCHIVED`.

**Per-campaign fields:** Objective · Current phase · Last completed milestone · Next milestone ·
Blockers · Authority owner · Detail doc.

---

## ⛔ Completed phases — DO NOT REOPEN (router authority guard)

Router milestone resolution **must not reactivate** the phases below. They are CLOSED with
objective evidence. A closed phase may be reopened **only** by objective regression evidence — a
named failing gate / test / render — and then **only that specific slice**, never the whole wave.
Subjective dissatisfaction, a stale registry line, or "it might not be ported" is **not**
regression evidence (LESSONS_LEARNED #9: control-presence ≠ visual parity; the operator
Recognition Gate is the only closer of visual parity and is not automatable).

| Closed phase | Status | Objective evidence | Source of truth |
|---|---|---|---|
| Phase-C Wave 1 — Authority | `COMPLETE` | manifest §1 "Already complete before launch"; PROJECT_STATE DECISIONS | `.claude/campaigns/phase-c-master/MASTER_MANIFEST.md` |
| Phase-C Wave 2 — Backend | `COMPLETE` | PROJECT_STATE "Phase-C Wave 2 (Backend) — COMPLETE 2026-07-03" (C-3a..C-3f; C-4a OI-deferred) | `.claude/memory/PROJECT_STATE.md` |
| Phase-C Wave 3 — Entire UI | `COMPLETE` | census CLOSED (git `9efa7cd8`); every page control-matrix Wireframe-Required-Missing = 0; 38 CP3 composites generated (`aef3b10b` → refreshed `944b036c`); live render gate 14/14 pages clean | git log `w3-*` + `reports/wave3/cp3/` |

**Wave-3 residual is not reopenable engineering work.** It is (a) the operator **CP3 recognition
gate** (subjective visual parity — operator-owned, per LESSONS_LEARNED #9), and (b) the
operator-gated **production deploy** (CP4/CP5, 7-agent gate). Neither is a page to "re-port."

---

## 1. Phase-C Inventory Master  — PRIMARY, in-flight

- **Status:** `ACTIVE` — at the **Wave 4** boundary, **`BLOCKED`**
- **Objective:** Implement Constitution §16 steps 1–10 (Product Master → Customer Master →
  Reservation → Inventory → Sample → Consignment → Returns → Invoice Selection → MM Integration →
  Webhook Synchronization) **inside the existing EJ Dashboard authorities** — zero duplicate
  authority, zero new master, wireframe as UI authority.
- **Current phase:** Wave 4 — Synchronization
- **Last completed milestone:** Wave 3 — Entire UI `COMPLETE` + 38 CP3 composites generated
  (Waves 1 Authority & 2 Backend also `COMPLETE`; see the DO-NOT-REOPEN guard above)
- **Next milestone:** Wave 4 slices — C-4b · C-4d · C-5a · C-6a · C-7a · C-8a/b/c · C-9a
  (**every slice OI-gated**)
- **Blockers:**
  1. **Ratification** — Wave 4 status is "RESTORED — awaiting ratification" (manifest §2; Launch
     Ruling §5 ratification rule): operator go required before the wave starts.
  2. **Open OIs** — all gating items OPEN: OI-1 (MM API vehicle), OI-3 (WZ add-vs-auto), OI-4
     (get_stock), OI-7/9/10/11 (webhook key + Faktury/Towary/Kontrahenci registration on prod),
     OI-17 (consignment allocation model — operator decision). No Wave-4 slice starts until its OI
     is ruled.
  3. **Interim (independent):** Wave 3 (`deploy/latest`) → production is unshipped — operator-gated
     7-agent deploy (CP4/CP5); the agent does not self-deploy.
- **Authority owner:** `ej-dashboard-fullstack-governance` (backend / sync / protected-domain) +
  `ej-dashboard-master` (orchestration)
- **Detail doc:** `.claude/campaigns/phase-c-master/MASTER_MANIFEST.md` · `…/OPEN_ITEMS.md` ·
  `.claude/memory/PROJECT_STATE.md`

## 2. React Migration

- **Status:** `ACTIVE` (forward campaign — does **not** reopen any Phase-C completed wave)
- **Objective:** Migrate the V2 surface (vanilla HTML + Babel JSX, no bundler) toward a
  maintainable React component system with a shared design system and **zero duplicate authority**.
- **Current phase:** Phase 1 — Component system (not yet started)
- **Last completed milestone:** Skill governance architecture frozen (PR #816)
- **Next milestone:** Phase-1 **read-only** inspection — map the routed V2 authority
  (`components.jsx` NAV_TREE, canonical pages) and produce a component-parity plan before any edit
- **Blockers:** PR #816 merge pending (soft precondition); sequenced after Phase-C
- **Authority owner:** `ej-dashboard-design` (frontend authority) + `ej-dashboard-master` (orchestration)
- **Detail doc:** `.claude/campaigns/atlas-v2.md` / `.claude/memory/PROJECT_STATE.md`

## 3. Wireframe Parity  — RECONCILED into Phase-C Wave 3

- **Status:** `COMPLETE` for the page-build scope (delivered by Phase-C Wave 3) — **do not
  resolve as reopenable work**
- **Objective:** Bring each page to parity with the approved wireframes, existing business logic
  untouched.
- **Current phase:** subsumed by Phase-C Wave 3 (UI built once → CP3). The prior "Inventory module
  / not started" line was **stale** — the entire inventory UI (10 tabs) and all census pages were
  built and passed the objective gate (matrix Missing = 0); the 38 CP3 composites exist.
- **Last completed milestone:** Phase-C Wave 3 UI + CP3 generation
- **Dashboard authority:** **RESOLVED — Ruling C (2026-07-05)**: DashboardKanban canonical;
  dashboard-page.jsx DEPRECATED. Locked rule: kanban/cockpit family = target; where a stale JSX
  component conflicts with the wireframe, the WIREFRAME wins. Detail: DECISIONS.md "Dashboard
  authority-of-record".
- **Next milestone:** continuous per-page authority resolution — no-conflict pages accepted as
  canonical (Documents Hub / Proforma / Shipment Detail); **Accounting = decision artifact + HOLD**
  (6-tab vs wireframe 6-KPI/KSeF/KPO); dead duplicates (dashboard-page.jsx, pages.jsx, pages-v2.jsx)
  flagged for retirement.
- **Blockers:** Accounting operator ruling (decision artifact `reports/wave3/cp3/accounting-authority-comparison.*`)
- **Authority owner:** `ej-dashboard-design` (+ `frontend-design` for craft) — recognition owned by operator
- **Detail doc:** `.claude/campaigns/phase-c-master/MASTER_MANIFEST.md` (Wave 3) · `reports/wave3/cp3/`

## 4. Workflow Stabilization

- **Status:** `ACTIVE` (forward campaign)
- **Objective:** Stabilize core business workflows (shipment, inventory, customs, accounting,
  notifications) without changing protected calculation/authority logic.
- **Current phase:** Shipment workflow
- **Last completed milestone:** — (not started)
- **Next milestone:** Define the shipment-workflow stabilization scope (read-only inspection first)
- **Blockers:** None (independent of Phase-C waves)
- **Authority owner:** `ej-dashboard-fullstack-governance` (protected-domain authority)
- **Detail doc:** `.claude/memory/PROJECT_STATE.md`

## 5. Performance Optimization

- **Status:** `PLANNED`
- **Objective:** Reduce load/interaction latency on the V2 surface once the component system lands.
- **Current phase:** —
- **Next milestone:** Scope after Campaigns 1–4 progress
- **Blockers:** Sequenced after React migration
- **Authority owner:** TBD (`ej-dashboard-fullstack-governance` / `ej-dashboard-design`)

## 6. Production Hardening

- **Status:** `PLANNED`
- **Objective:** Deploy/observability/rollback hardening for the migrated surface.
- **Current phase:** —
- **Next milestone:** Scope after Performance Optimization
- **Blockers:** Sequenced last
- **Authority owner:** TBD (deploy gate + `ej-dashboard-fullstack-governance`)

---

**Maintenance:** at a campaign milestone (workflow Close step), update that campaign's
Current phase / Last completed / Next milestone / Blockers, and keep it consistent with the
authoritative detail doc. Move finished campaigns to `COMPLETE`, then `ARCHIVED`. **Never delete
or downgrade an entry in the DO-NOT-REOPEN guard without objective regression evidence.**
