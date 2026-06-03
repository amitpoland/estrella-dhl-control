# ADR-028: Atlas-V2 (/v2/) shell MUST NOT load dashboard-shared.js; apiFetch provided inline

**Status:** Proposed (pending operator approval)
**Date:** 2026-06-02
**Deciders:** Operator (to approve), engineering gate
**Refs:** PR #427 (`chore/atlas-v2-reconcile-prod-index-html`), Sprint 1 verification report

---

## Context

The Atlas-V2 design shell (`/v2/`) is a Track-2 rebuild of the Estrella dashboard using a
self-contained JSX bundle (`components.jsx`, `pages.jsx`, etc.) ported from the design canvas.
It is architecturally separate from the Track-1 (`/dashboard/`) surface.

`dashboard-shared.js` is the Track-1 shared layer. It exports to `window.EstrellaShared`:

```
apiFetch, fmtPLN, Badge, Card, Btn, Sel, Toast, SessionBanner,
EstrellaMark, SubTabStrip, Sidebar, StatusDot, GateBlock,
SectionHeader, CompactTable, EmptyState, _resolveOperator
```

The Track-2 design shell's `components.jsx` defines its own `Badge`, `Btn`, `Sidebar`,
`Card`, `SectionHeader`, `SubTabStrip` etc. These are assigned directly to `window`
(via `Object.assign(window, {...})`), NOT to `window.EstrellaShared`.

---

## Decision

**The `/v2/` shell MUST NOT load `dashboard-shared.js`.**

**Instead, apiFetch is provided by a minimal inline shim in `index.html`.**

---

## Rationale

### Source-verified namespace analysis

`dashboard-shared.js` exports to `window.EstrellaShared.{X}` (nested).
`components.jsx` exports to `window.{X}` (root).
These are different slots — no direct overwrite occurs between them.

The actual reason for exclusion is simpler and stronger:

1. **Dead code.** The v2 shell consumes exactly one symbol from `window.EstrellaShared`:
   `apiFetch` (used at `pz-api.js:22` and `proforma-detail.jsx:24`). Every other export
   from `dashboard-shared.js` is unreachable dead code in the v2 context.

2. **Coupling without benefit.** Loading `dashboard-shared.js` introduces a hard dependency
   on the Track-1 shared layer into a surface that is supposed to be architecturally
   independent. If `dashboard-shared.js` changes (new exports, modified behaviour, removal
   of symbols), `/v2/` becomes an unintended consumer.

3. **Future pollution risk.** Although the namespaces are currently separate, `dashboard-shared.js`
   also exports `window.EstrellaDash` and `window.NAV_TREE` (via alias). If any v2 component
   happens to read `window.Badge` and `dashboard-shared.js` is loaded, it would receive the
   Track-1 Badge, not the Track-2 one — a latent bug waiting for an accidental global read.

4. **The inline shim is sufficient.** `apiFetch` is a 15-line function. Inlining it avoids
   the above risks while providing exactly what v2 needs.

### Shim contract

The inline apiFetch shim MUST maintain behavioural parity with `dashboard-shared.js:apiFetch`:
- `credentials: 'include'` (required for session cookie auth)
- Network error catch block: `TypeError` from a failed `fetch()` must be caught and converted
  to a user-friendly "Service unreachable" error with `err.type = 'network'`
- `err.status` property on 401/403 errors
- 204/205 null return
- Content-type JSON dispatch

The X-Operator header is NOT injected by apiFetch itself — it is added by `pz-api.js`
before calling apiFetch (verified at `pz-api.js:_callM`). This is consistent in both
implementations and must remain so.

### Shim contract enforcement

The shim at commit `9ba9b3f` (post-rebase onto `35d662d`) has been verified to implement
the full canonical contract including D1 and D2. Two tests in `test_atlas_v2_sprint1.py`
pin this contract (`test_v2_shim_has_network_error_catch`, `test_v2_shim_sets_err_status_on_auth`).

**PATH GUARD LESSON — verification must use a clean, pinned clone:**
The path `C:\Users\Super Fashion\PZ APP` is a dev scratch workspace currently on branch
`feat/description-resolver` (commits ahead of main). Subagents that read from it instead of
`C:\PZ-verify` will see unreleased feature code and may produce false verdicts (e.g. F1
in this session reported D1/D2 "present on main" by reading from the working tree rather
than `git show origin/main:...`). Every verification task must state `WORKING DIR: C:\PZ-verify`
as its first output line. Coordinator rejects any verdict not rooted there.

**LESSON — prod was hand-edited off-git with a false rationale AND a latent defect:**
The original manual prod edit to `C:\PZ\app\static\v2\index.html` introduced the shim
with D1 and D2 missing. The prod comment also stated a false "overwrite" rationale
(dashboard-shared.js and components.jsx use different namespaces; no overwrite occurs).
The real reason is simpler: dashboard-shared.js exports are dead code in the v2 context.
This reinforces the LOCAL-COMMIT-ONLY discipline: hand-edits directly in C:\PZ bypass
review, carry unverified rationales, and may introduce silent defects. Every prod change
should originate from a reviewed, tested commit.

**Former defects now fixed:**
- D1 (network error catch): fixed at `index.html:27-33` in commit `9ba9b3f`
- D2 (err.status on auth): fixed at `index.html:37` in commit `9ba9b3f`

---

## Consequences

### Positive
- `/v2/` has no runtime dependency on Track-1 shared layer
- Future changes to `dashboard-shared.js` cannot affect `/v2/` behaviour
- Smaller payload on `/v2/` initial load (one fewer script)

### Negative / Risk
- The inline shim must be kept in sync with `dashboard-shared.js:apiFetch` when the
  contract changes (new error types, PR #422 enforcement, etc.)
- Detecting a shim drift requires manual review; there is no automated cross-check
- Mitigation: the test `test_v2_index_provides_api_fetch` is a guard; consider adding
  a contract test that verifies the shim handles 401, network failure, and JSON dispatch

### Constraint for all future Sprints
**Do not add `<script src="dashboard-shared.js"></script>` to `/v2/index.html`.**
If a new symbol from `dashboard-shared.js` is needed in v2, port or inline it minimally
rather than loading the full module.

---

## Alternatives considered

### A: Load dashboard-shared.js, suppress the unused exports
Not feasible — `dashboard-shared.js` sets `window.EstrellaShared = Object.freeze(...)`,
making it impossible to selectively un-expose symbols.

### B: Refactor dashboard-shared.js to export only apiFetch in a v2-compatible way
Valid long-term direction, but out of scope for Sprint 1. File under tech-debt.

### C: Use pz-api.js's own `_apiFetch` wrapper as the sole call path (already done)
`pz-api.js` already wraps all calls through `EstrellaShared.apiFetch`. This is why
only 2 call sites consume it directly and the rest are mediated. Keep this invariant.
