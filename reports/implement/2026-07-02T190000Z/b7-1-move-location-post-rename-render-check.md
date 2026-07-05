# B×7-1 post-rename render check — Move Location (cold origin) — PASS

- **Date:** 2026-07-02 (post-commit 362f4c02 / eb809b4a, branch deploy/latest)
- **Purpose:** clear disclosure (1) of the rework report — the committed render
  evidence (2026-07-02T170000Z) predates the move_stock → move_location rename;
  the advisor placed a post-rename cold-origin re-check on the pre-deploy
  checklist. This record satisfies that item.
- **Origin:** cold — fresh port **8144** (never used before; Babel fetches
  scripts uncached), `python -m http.server 8144 --directory
  C:/PZ-verify/service/app/static`, app at `http://localhost:8144/v2/`.
  (First attempt on 8143 served the v2 dir at root — the app resolves assets
  under `/v2/…`, so everything 404'd and the shell died on `Sidebar is not
  defined`. Lesson: static render checks must serve the PARENT `static/` dir
  and open `/v2/`.)

## Checks (8/8 PASS)

1. **Window globals / collision retirement** — `typeof window.MoveLocationPage
   === 'function'`; `typeof window.MoveStockPage === 'undefined'` (wireframe
   stub stays retired; no last-write-wins owner for either name but the live
   page). PASS
2. **WIRED_PAGES** — length 19, includes `move_location`, excludes
   `move_stock`. PASS
3. **Navigation** — sidebar `◫ Inventory ›` group expands to Stock Hub / Move
   Location; clicking Move Location lands on `/v2/move_location`; SubTabStrip
   shows both siblings with Move Location active. PASS (note: two DOM matches
   for the label — expanded sidebar child + SubTabStrip tab; both navigate.)
4. **Page root** — `data-testid="move-location-root"` present; old
   `move-stock-root` absent. PASS
5. **Header** — title "Move Location"; subtitle rendered (verified as
   rendered text, not script source): "Physical location move (shelf/zone) —
   metadata only, does NOT change inventory state. Multi-select runs
   sequential per-piece moves." PASS
6. **Honest-mechanics banner** — verbatim "Batch = sequential single-piece
   moves (backend is per-piece)…" visible; no MOCK banner
   (`data-testid="mock-banner"` absent). PASS
7. **Controls** — `ms-batch-input` present; `ms-load` disabled while input
   empty, enabled after fill. PASS
8. **Error path (honest)** — Load with batch `SHIPMENT_TEST_RENDER` against
   the API-less static origin → `ms-load-error` renders the raw HTTP 404; no
   table, no fake rows. Console: **zero errors** on this origin. PASS

## Verdict

PASS — the rename is render-complete. Disclosure (1) from the rework report is
cleared; the pre-deploy checklist item "post-rename cold-origin render
re-check" is satisfied. Remaining pre-deploy items are unchanged (7-agent
gate, prod migration application under deploy_persistence_storage_reviewer).
