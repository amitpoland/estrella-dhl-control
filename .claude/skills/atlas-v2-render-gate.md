# Atlas-V2 Render Gate

Reusable post-deploy eyeball checklist for every Sprint at `/v2/`.
Run after every robocopy sync to C:\PZ\app\static\v2\ before declaring a sprint done.

---

## Prerequisites

- PZService running (`sc.exe query PZService` → RUNNING)
- Admin session available (logged-in browser or can log in)
- **Health watchdog must be disabled for the duration of the deploy and re-enabled after.**
  See `service/docs/windows-deploy-runbook-template.md` step 0 + step 7.
  Task name: `PZService-HealthWatchdog` (exact — a wrong name fails silently).
  ENABLE is also the first step in every rollback path.
  A deploy that leaves the watchdog disabled after abort is worse than no watchdog.

---

## Checklist (run in order)

### 1. Shell loads clean
- Open `https://pz.estrellajewels.eu/v2/` (or `http://127.0.0.1:47213/v2/`)
- Log in as admin
- F12 → Console → **zero red errors on initial load**
- Sidebar visible, header reads "Estrella Atlas — Operations Control"

### 2. MOCK badges on all un-wired pages
For every sidebar item that is NOT listed as LIVE (see §Wired pages below):
- Click the item
- **Purple MOCK banner must appear**: "This page is not yet wired to the live backend"
- No banner = DEFECT — file a bug before proceeding

### 3. Pro Forma loads real data (LIVE page)
- Navigate to Pro Forma
- Draft list renders with actual rows (not empty, not hardcoded fake names)
- Clicking a row opens the detail view
- No Babel parse error in Console
- Network tab: GET `/api/v1/proforma/drafts/…` returns 200

### 4. Network clean
- DevTools → Network → hard-refresh (Ctrl+Shift+R)
- No 4xx/5xx on any request during page load
- JSX files all load 200 (confirm no 404 on new sprint files)

### 5. Hard-refresh idempotency
- Hard-refresh a second time
- Same result — no cache-drift errors

### 6. Responsive layout
- Resize window to 1280px width
- Sidebar and content area both remain visible and functional

### 7. Deep-link + hard-refresh check (added after URL-architecture verification)
Navigate DIRECTLY to a deep URL (do not click in the sidebar — paste it in the address bar):
```
https://pz.estrellajewels.eu/v2/proforma
```
Then hard-refresh (Ctrl+Shift+R):
- Shell must load the correct page (Pro Forma list), not the default dashboard
- F12 → Network → all JSX files must load 200 (no 404 on proforma-list.jsx etc.)
- Console must be clean (zero red errors)
- Repeat for `/v2/inbox` to confirm a MOCK-badged page also deep-links correctly

**This check guards against base-href or script-src regressions that would silently
break direct-link sharing and browser-history navigation.**

### 8. Pro Forma table columns eyeball (Sprint 1 data check)
With a batch loaded in the Pro Forma list (URL: `/v2/proforma?batch_id=<real_id>`):
- Table must show **6 columns**: Draft ID · Client · State · **Currency** · **Lines** · **Created**
- Currency column: real ISO code (e.g. EUR, USD) — not blank, not "—" for real drafts
- Lines column: integer count from `editable_lines_json`
- Created column: 10-char ISO date prefix (YYYY-MM-DD) — not blank

**This check verifies the Sprint 1 truncation fix (proforma-list.jsx columns 4-6)
rendered the correct data. If any of the last 3 columns are blank, the fix may
have regressed or the backend shape diverged.**

---

## Wired pages (LIVE — no MOCK badge expected)

| Page | Backend endpoint | Sprint wired |
|---|---|---|
| `proforma` | `GET /api/v1/proforma/drafts/{batch_id}` | Sprint 1 |
| `proforma_detail` | `GET /api/v1/proforma/draft/{id}` etc. | Sprint 1 |

Update this table as each sprint wires additional pages.

---

## Pass criteria

All 6 checks green → **RENDER-GATE PASS** → proceed to JSONL fingerprint entry.

Any red → **RENDER-GATE FAIL** → stop; file a bug with console output + network log; do not log JSONL until resolved.

---

## Notes

- The forbidden-token guard for the description engine does NOT apply here — that's a backend concern.
- Do not substitute automated test results for this gate. Tests prove the file is syntactically correct; the eyeball gate proves it actually renders the intended UI in a real browser session.
- If Babel fails to parse a JSX file: check for truncated files (file ends mid-tag or mid-expression). This was the Sprint 1 defect pattern.
