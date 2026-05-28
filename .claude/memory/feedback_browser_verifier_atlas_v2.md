---
name: browser-verifier-atlas-v2-constraint
description: Browser verifier limitation for Atlas-V2 static-file sprints — dev server needs auth; workaround for future sprints
metadata:
  type: feedback
---

Browser verification for Atlas-V2 sprints is constrained by two structural factors:

1. Dev server (uvicorn from working tree) requires an authenticated session — the browser must have a cookie for the dev-server port, which it doesn't when first connecting
2. NSSM production service serves deployed code (`C:\PZ\app\static\`), not the working tree — so sprint changes aren't visible until deployed

**Why:** Sprint 01 scorecard (2026-05-28) flagged browser-verifier as NEEDS-TUNING. GATE 4 requires disposition.

**Disposition: SCHEDULED** — fix for Sprint 02 onwards: copy `C:\PZ\app\storage\users.db` to `service/app/storage/users.db` at dev-server start time so the dev server shares the production auth DB. With that, the browser's existing session cookie (for port 47213) won't apply to port 47214, but the operator can log in once at the start of a verification session.

Alternative: for static-file-only sprints (no new API endpoints), source-grep contract tests are accepted as the primary verification layer; browser verification confirms page structure only (mounts, no errors) and is supplemented by post-deploy smoke test.

**How to apply:** Before running browser-verifier on a V2 sprint: (1) check if dev server port shares auth DB, (2) if not, note the static-file verification substitution explicitly in the GATE 6 report, (3) include post-deploy smoke test checklist in the PR body.

---

## Cache-layer verification protocol (added 2026-05-28, Sprint 01 smoke)

**Root cause observed:** `serve_static` in `main.py` sets `Cache-Control: public, max-age=3600` for all JS files. After a static deploy, the browser may serve a cached pre-deploy version of `pz-components.js` for up to 1 hour — causing Sprint N testids to be absent from the DOM even though the server is correctly serving Sprint N code.

**Three-layer verification protocol for post-deploy smoke tests:**

| Layer | Check | Tool |
|---|---|---|
| 1. Disk | `C:\PZ\app\static\pz-components.js` contains expected testid strings | `Select-String` or `Grep` |
| 2. Server (cache-busted) | `fetch('/dashboard/pz-components.js?bust=DATE.NOW()', {cache:'no-store'})` returns Sprint N content | JS console or Chrome MCP |
| 3. React runtime | Fiber props inspection — `onSave`, `resolution`, etc. are correctly wired | Chrome MCP `javascript_tool` |

**Rule:** If layers 1 and 2 pass but a testid is absent from the DOM, classify as **client cache drift** — NOT a code or deploy defect. Do not attempt to "fix" by mutating production logic or bypassing governance.

**Hard-refresh protocol:** For immediate DOM verification, use Ctrl+Shift+R (hard refresh) in the browser before checking testids. This bypasses `max-age` and forces a fresh JS fetch. Add this to the smoke checklist for every Atlas-V2 sprint.

**Smoke checklist addition (Sprint 02+):**
1. Hard-refresh before checking DOM testids (Ctrl+Shift+R)
2. Verify Layer 1 (disk grep) + Layer 2 (cache-busted fetch) independently
3. If DOM testid absent after hard-refresh → genuine issue; if absent only before hard-refresh → cache drift, PASS

[[feedback_reconciliation_engine_strategy]]
