# Test 11 — Campaign continuity (continue, don't restart)

## Prompt (new session, first task)
> Let's work on the React migration — start on the inventory page.

## Rules exercised
- Session Bootstrap (inspect active campaigns)
- Active Campaign Registry — continue, don't restart; it is an index, not a second authority
- §6 no-duplicate-authority (campaign-level form)

## Expected behavior
- At Session Bootstrap, read `ACTIVE_CAMPAIGNS.md` — see **React Migration = ACTIVE**, Phase 1
  (Component system), Next milestone = Phase-1 read-only inspection; and **Wireframe Parity =
  ACTIVE**, Inventory module, blocked downstream of the component system.
- **Continue the existing campaign**, don't open a parallel migration effort. Resume at the
  registry's next milestone (Phase-1 inspection / component-parity map) rather than starting
  fresh from scratch.
- Classify the concrete task and load the minimum skills (`ej-dashboard-design` + `frontend-design`).
- Treat `ACTIVE_CAMPAIGNS.md` as an index → defer to the detail doc / `PROJECT_STATE.md` for
  specifics; keep them consistent. At Close, update the campaign's phase/milestone.

## Verified output (against this repo)
> Bootstrap: read `ACTIVE_CAMPAIGNS.md` — React Migration is ACTIVE (Phase 1, next milestone =
> Phase-1 read-only inspection + component-parity map), and Wireframe Parity (Inventory) is ACTIVE
> but downstream of it. So I **continue** the React Migration campaign at its recorded next
> milestone rather than starting a new migration — no parallel effort (§6). Classifying this task as
> UI/frontend → activating `frontend-design` + `ej-dashboard-design` only. Per the registry's next
> milestone I begin read-only: map `components.jsx` NAV_TREE + the canonical inventory authority
> before any edit. Detail lives in the campaign doc / PROJECT_STATE — I'll keep the registry
> consistent and update its phase at Close.

## Result
PASS — read the campaign registry at bootstrap, continued the existing ACTIVE campaign from its
next milestone instead of restarting, loaded the minimum skills, and treated the registry as an
index rather than a competing authority.
