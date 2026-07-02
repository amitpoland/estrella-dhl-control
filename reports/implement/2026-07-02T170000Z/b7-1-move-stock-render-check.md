# B×7-1 Move Stock — Render Check (2026-07-02, pre-commit): PASS
# (includes one REAL DEFECT found and fixed during the check)

Method: static python http.server over C:/PZ-verify/service/app/static
(no backend, no schedulers). Cache-busted source fetches; cold-origin server
restart used after discovering the script-file cache trap (see Defect + Caveats).

## DEFECT FOUND AND FIXED (the check earned its keep)

First boot rendered the OLD MOCK stub ("Wireframe data — backend not yet wired",
fictional /inventory/move endpoints) instead of the live page:
wireframe-update.jsx loads AFTER move-stock-page.jsx in index.html, so its
surviving stub MoveStockPage silently overwrote the live page on window
(last-write-wins — the identical defect class slice-03 excised for ReportsPage).
FIX: stub function + export entry retired from wireframe-update.jsx (Sprint-31
playbook step P3: mock retired), with citation comments; new promotion test
test_wireframe_stub_retired_no_name_collision pins the name to exactly one
owner. Post-fix: window.MoveStockPage.toString() opens with useState (live
page); no StubPage reference.

## CHECK RESULTS (all post-fix, cold origin)

1. Served index.html (cache-busted): 22 live-shape conditionals; move_stock
   render block present; script tag present; ROUTE_REDIRECTS = 11 entries,
   move_stock absent, B×7-1 preamble comment intact. PASS
2. SPA boot: shell renders; console ZERO errors (no Babel/parse errors from
   move-stock-page.jsx). PASS
3. Nav: g_inventory group renders with Stock Hub + Move Stock children
   (expand is async — first synchronous query raced React; re-query confirmed);
   clicking Move Stock lands /v2/move_stock; page renders with
   move-stock-root / ms-batch-input / ms-load / ms-banner; banner text verbatim
   ("Batch = sequential single-piece moves (backend is per-piece)");
   SubTabStrip shows siblings. PASS
4. States:
   a. REAL load click (no backend): honest error path renders (ms-load-error,
      HTTP 404 surfaced; no crash). PASS
   b. Empty-state branch (component-level, stubbed transport — PzApi is
      Object.frozen, so the whole object reference was swapped and restored):
      ms-empty renders "No pieces in this batch — inventory_state has no rows".
      PASS
   c. Table branch (stubbed 2-piece payload): ms-table / ms-filter /
      ms-destination / ms-note / ms-submit / 2× ms-row-checkbox all render;
      REAL piece checkbox enabled; synthetic piece checkbox DISABLED with title
      "purchase-transit projection — not movable (would 409 WRONG_STATE)" and
      visible "projection — not movable" label. PASS
5. Page-source assertions (cache-busted): all five error codes present;
   MIGRATION_PENDING names draft_20260512_002516_idempotency_key; synthetic
   disable logic present; scanner-optional language present. PASS
6. Stale-URL insurance: /v2/scanner push -> no blank content, no stub header
   (same boot-resolution caveat as slice-04: deep-link redirects resolve at
   parseV2Location boot; entries verified in served bytes + green parse tests).
   /v2/move_stock resolves to the REAL page via nav (url /v2/move_stock,
   live testids). PASS
7. Stock Hub as group child: inventory-hub-root renders at /v2/inventory with
   the Sprint-30 "No write actions" read-only subtitle intact. PASS

Console after full exercise: ZERO errors.

## Caveats recorded honestly

- Backend-dependent states (real pieces table, actual moves, replay path)
  are NOT observable on a static server; empty/table/synthetic states were
  rendered via a stubbed transport (swap-and-restore of the frozen PzApi
  object) — component-level render verification, labeled as such. Real-data
  interaction verification happens at deploy per the DECLARE.
- Browser cache trap round 2: index.html cache-busting is NOT enough — Babel
  fetches script files without busters; a COLD ORIGIN (new port) is required
  after editing any .jsx. Recorded for future render checks.

Pre-commit render gate: PASS. No commit, no deploy, no push.
