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

## 1. React Migration
- **Status:** ACTIVE
- **Objective:** Migrate the V2 surface (vanilla HTML + Babel JSX, no bundler) toward a
  maintainable React component system with a shared design system and **zero duplicate authority**.
- **Current phase:** Phase 1 — Component system (not yet started)
- **Last completed milestone:** Skill governance architecture frozen (PR #816)
- **Next milestone:** Phase-1 **read-only** inspection — map the routed V2 authority
  (`components.jsx` NAV_TREE, canonical pages) and produce a component-parity plan before any edit
- **Blockers:** PR #816 merge pending (soft precondition)
- **Authority owner:** `ej-dashboard-design` (frontend authority) + `ej-dashboard-master` (orchestration)
- **Detail doc:** `.claude/campaigns/atlas-v2.md` / `.claude/memory/PROJECT_STATE.md`

## 2. Wireframe Parity
- **Status:** ACTIVE
- **Objective:** Bring each page to pixel-level parity with the approved wireframes, **existing
  business logic untouched**.
- **Current phase:** Inventory module
- **Last completed milestone:** — (not started)
- **Next milestone:** Pixel-level review of the Inventory page vs its wireframe (visual only)
- **Blockers:** Downstream of the React component system (Campaign 1 Phase 1)
- **Authority owner:** `ej-dashboard-design` (+ `frontend-design` for craft)
- **Detail doc:** `.claude/campaigns/*` (wireframe references)

## 3. Workflow Stabilization
- **Status:** ACTIVE
- **Objective:** Stabilize core business workflows (shipment, inventory, customs, accounting,
  notifications) without changing protected calculation/authority logic.
- **Current phase:** Shipment workflow
- **Last completed milestone:** — (not started)
- **Next milestone:** Define the shipment-workflow stabilization scope (read-only inspection first)
- **Blockers:** None
- **Authority owner:** `ej-dashboard-fullstack-governance` (protected-domain authority)
- **Detail doc:** `.claude/memory/PROJECT_STATE.md`

## 4. Performance Optimization
- **Status:** PLANNED
- **Objective:** Reduce load/interaction latency on the V2 surface once the component system lands.
- **Current phase:** —
- **Next milestone:** Scope after Campaigns 1–3 progress
- **Blockers:** Sequenced after React migration
- **Authority owner:** TBD (`ej-dashboard-fullstack-governance` / `ej-dashboard-design`)

## 5. Production Hardening
- **Status:** PLANNED
- **Objective:** Deploy/observability/rollback hardening for the migrated surface.
- **Current phase:** —
- **Next milestone:** Scope after Performance Optimization
- **Blockers:** Sequenced last
- **Authority owner:** TBD (deploy gate + `ej-dashboard-fullstack-governance`)

---

**Maintenance:** at a campaign milestone (workflow Close step), update that campaign's
Current phase / Last completed / Next milestone / Blockers, and keep it consistent with the
authoritative detail doc. Move finished campaigns to `COMPLETE`, then `ARCHIVED`.
