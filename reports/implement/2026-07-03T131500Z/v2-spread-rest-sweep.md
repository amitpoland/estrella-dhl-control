# V2-wide spread-rest collision sweep — build + render record

- **Date:** 2026-07-03 · V2 JSX only, zero behavior change intended · no deploy
- **Declared:** PROJECT_STATE DECISIONS "V2-wide spread-rest collision sweep".
- **Origin:** the B2 render-check defect (0602ddd3 fixed inventory-page.jsx
  only). Mechanism: Babel-standalone hoists compiled object-rest destructure
  helpers (`var _excluded = [...]`) to GLOBAL scope in un-wrapped classic
  `<script type="text/babel">`; the last-loaded V2 file wins that name, so an
  earlier component's excluded-prop list is silently replaced → excluded
  props (onChange) leak into `{...rest}` → raw state setter on a DOM input →
  first keystroke crashes the tree.

## STEP 0 — census (read-only, before edits)

| File (load order) | Component | Line | Rest-forwarded attrs (census-complete) | Collider? |
|---|---|---|---|---|
| components.jsx (4th) | Card | 379 | data-testid ×2 | |
| components.jsx (4th) | Btn | 393 | data-testid ×19, title ×10, aria-label ×1 | |
| components.jsx (4th) | Input | 453 | data-testid ×1 | |
| proforma-detail.jsx (27th) | **TbBtn** | 22 | (none in current usage) | **YES** — its list `['children','onClick','disabled','title','warn','style']` was the exact `window._excluded` observed during the B2 crash |
| inventory-page.jsx (11th) | InvInput, InvFetchBtn | — | — | already fixed in 0602ddd3 |

Only these are true `_excluded` emitters. Object-LITERAL spreads the census
also surfaced (`{ ...prev }`, `{ ...p }`, inline `...style`) compile to
idempotent `_extends`/`_objectSpread` — NO `_excluded`, NOT flagged.
**Total: 4 rest-destructure components across 2 files** (+2 pre-fixed).

## STEP 2 — fix (the 0602ddd3 idiom, V2-wide)

Each `...rest` replaced with EXPLICIT named destructuring of the exact
census-complete forwarded attrs, applied as explicit JSX attributes before
`style=`:
- Card → `'data-testid': testid` → `data-testid={testid}` on `<div>`.
- Btn → `'data-testid': testid, title, 'aria-label': ariaLabel` → applied on
  `<button>` before style.
- Input → `'data-testid': testid` → on `<input>`.
- TbBtn (collider) → `'data-testid': testid` → on `<button>`; the `{...rest}`
  spread removed. Zero behavior change (census: TbBtn forwarded nothing).

Post-edit grep: **zero** rest-destructures remain across all v2/*.jsx +
index.html (the only `...rest` token left is inside a DECISIONS-citing
comment).

## STEP 3 — pins

- NEW `test_v2_no_spread_rest.py`: parametrized over every v2/*.jsx +
  index.html inline JSX — asserts no `...name }` rest-destructure closing a
  param list (regex excludes object-literal spreads and `//` comments).
  Drop-can't-return: a future PR reintroducing `...rest` fails.
- REBASED `test_v2_components_rest_prop_forwarding.py`: the Lesson-I CONTRACT
  (data-testid/title/aria-label reach the DOM) is unchanged; the 7
  spread-rest-form assertions became explicit-destructure assertions. The
  known-caller-testid canaries (client-detail cd-*, master-search,
  error/loading-state) and Btn variant coverage are untouched and green.

## STEP 4 — render check (cold origin :8161, throwaway storage copy)

- **AuditPanel** (the pre-fix crasher's sibling on Stock Hub): typed
  `SWEEP_AUDIT_TEST` → panel + notes panel stay alive, value retained,
  `window._excluded === undefined` (no hoisted helper anywhere).
- **Master page** (uses Input + Btn + Card, a 2026-06-10 victim page):
  `data-testid="master-search"` reached the DOM (Input forwarding intact),
  typed "ACME" clean; 25 Btn `data-testid`s + 9 Btn `title` tooltips present
  (Btn forwarding intact); `_excluded` undefined.
- **proforma-detail** (the TbBtn collider file, loaded 27th): 6 TbBtn toolbar
  buttons render (Edit/Cancel/Duplicate/Approve/Post/Convert/Preview/Print/
  Send/Generate visible in screenshot); zero console errors; `_excluded`
  undefined.

Verdict: **PASS** — `window._excluded` is undefined on every page tested (the
global no longer exists), forwarding contract preserved, no tree crash, no
console errors.

## Gates

```
test_v2_no_spread_rest.py + test_v2_components_rest_prop_forwarding.py (rebased)
  + phase_b2_b3 + sprint30 + proforma-detail authority/hydration → 182 passed
PYTHONUTF8=1 python test_pz_regression.py → 160/160 golden PASS
```
