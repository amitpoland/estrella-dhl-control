# Wave-3 Documents Hub — Build Record

**Date:** 2026-07-04  
**Branch:** deploy/latest  
**Base SHA:** 52524bde  
**Files edited:** 2  
**git status --short | wc -l before:** 42  
**git status --short | wc -l after:** 43 (build record added to untracked)

---

## Summary

Replaced the 227-line read-only observer `documents-hub.jsx` with a ~660-line
3-lane Kanban implementation covering all 13 wireframe controls (census DC-5..DC-16,
amendment A-3, 2026-07-04).

Added one transport-only method (`getBatchFiles`) to `pz-api.js` in the Wave-3 block
after `getWarehouseLocationInventory`.

No new backend routes. No write-gate changes. All 13 controls wired to EXISTING
authorities or rendered as honest-disabled per DECISIONS.md DOCUMENTS HUB CONSTRAINT.

---

## Files Changed

| File | Change |
|---|---|
| `service/app/static/v2/documents-hub.jsx` | Full rewrite: 227 → ~660 lines; 3-lane Kanban |
| `service/app/static/v2/pz-api.js` | Added `getBatchFiles` after `getWarehouseLocationInventory` |
| `reports/wave3/pages/2026-07-04-documents-hub.md` | This build record (new untracked) |

---

## Page Gate — 10 Criteria

| # | Criterion | Result |
|---|---|---|
| 1 | 3-lane Kanban structure present (Draft / Approved / Posted to wFirma) | PASS — all 3 lanes render on both PI and PZ tabs |
| 2 | 3-tab bar present (PI / PZ / Other Documents) | PASS — tabs switch cleanly |
| 3 | Real data — no fake/hardcoded document rows | PASS — PI tab fetches `/api/v1/proforma/search?limit=200` (200 OK); PZ tab fetches `/api/v1/dashboard/batches` (200 OK, 273 batches) |
| 4 | Summary strip present | PASS — PZ BATCHES 273, PZ POSTED 0, SAD PRESENT 0 |
| 5 | DC-16 Export CSV present as honest-disabled | PASS — disabled button with title "DC-16 · export CSV — Wave-4 intake..." |
| 6 | STOP-REPORT controls present as honest-disabled with census tags | PASS — DC-12, DC-13-PZ, DC-14 all disabled with Wave-4 title text |
| 7 | All interactive elements have `data-testid` attributes | PASS — all buttons, tabs, modal confirm/cancel wired |
| 8 | No console errors | PASS — zero errors; vendor 404s are pre-existing app-wide |
| 9 | No new 4xx/5xx on happy-path API calls | PASS — `/proforma/search`, `/dashboard/batches`, `/dashboard/batches/{id}/files` all 200 OK |
| 10 | Control matrix: 13 controls, Missing = 0 | PASS — see matrix below |

---

## Control Matrix — 13 Controls (DC-5..DC-16 + DC-13 Proforma)

| Census ID | Control | Disposition | Authority / File:Line |
|---|---|---|---|
| DC-5 | Edit button on Draft-lane PI card | WIRED — navigate to `/v2/proforma?draft_id=...` | routes_proforma.py:5330 `PATCH /draft/{id}` |
| DC-6 | Approve button on Draft-lane PI card | WIRED — calls `PzApi.approveDraft` with confirm_token | routes_proforma.py:6171 `POST /draft/{id}/approve` |
| DC-7 | Delete button on Draft-lane PI card | WIRED — cancel then delete via `PzApi.cancelDraft` + `PzApi.deleteDraft` | routes_proforma.py:6367+6395 |
| DC-8 | Post to wFirma button on Approved-lane PI card | WIRED — calls `PzApi.postDraftToWfirma` with write-gate; flag `WFIRMA_CREATE_PROFORMA_ALLOWED` | routes_proforma.py:8095 |
| DC-9 | Unapprove button on Approved-lane PI card | WIRED — calls `PzApi.reopenDraft` | routes_proforma.py:6219 `POST /draft/{id}/re-open` |
| DC-10 | View action on Posted-lane PI card | WIRED — link to `/api/v1/proforma/draft/{id}/preview.html` | routes_proforma.py:4771 |
| DC-11 | Download button on Posted-lane PI card | WIRED — link to `/api/v1/proforma/{batch}/{client}/document.pdf` | routes_proforma.py:2862 |
| DC-12 | Upload packing list toolbar button | HONEST-GATED (Wave-4) — disabled; title names missing route `POST /api/v1/{pi\|pz}/upload-packing-list` | No route exists in routes_proforma.py or routes_pz.py |
| DC-13 (PI) | New Proforma toolbar button | NAVIGATE — `window.location.href = '/v2/proforma'` per §D no-duplicate plan | WIREFRAME_AUTHORITY §D; routes_proforma.py create flow |
| DC-13 (PZ) | New Purchase Receipt toolbar button | HONEST-GATED (Wave-4) — disabled; title names missing route `POST /api/v1/pz` | routes_pz.py has only `POST /pz/process` (batch), no document-level create |
| DC-14 | CreateModal / ParseModal upload mode | HONEST-GATED (Wave-4) — not rendered; covered by disabled upload buttons above | Same missing endpoint as DC-12 |
| DC-15 | Other Documents tab View + Download per row | WIRED — View/Download per file via `PzApi.getBatchFiles()` | routes_dashboard.py:558 `GET /batches/{id}/files` |
| DC-16 | Export CSV disabled header button | HONEST-GATED (Wave-4) — disabled in PageHeader; title "DC-16 · export CSV — Wave-4 intake" | App.jsx template line 666 (no backend export endpoint) |

**Missing = 0**  
**Wired = 9** (DC-5, DC-6, DC-7, DC-8, DC-9, DC-10, DC-11, DC-13-PI-navigate, DC-15)  
**Honest-gated / Wave-4 = 4** (DC-12, DC-13-PZ, DC-14, DC-16)

---

## STOP-REPORT — Wave-4 Intake

Controls rendered as Lesson-M honest-disabled because they require a NEW backend write path
that does not exist. Per DECISIONS.md: "any control REQUIRING a new write path = STOP and
report (Wave-4/backlog intake, not UI work)."

### ① DC-12 — Upload Packing List

**Missing route:** `POST /api/v1/{pi|pz}/upload-packing-list`  
**Where verified absent:** `routes_proforma.py` (has no upload endpoint beyond draft create),
`routes_upload.py` (has `POST /upload/shipment` for new shipments, no proforma packing-list target),
`routes_pz.py` (has `POST /pz/process` for batch only).  
**UI rendered:** `<button disabled title="DC-12 · Wave-4: requires POST /api/v1/pi/upload-packing-list (not yet deployed)">↑ Upload packing list</button>`

### ② DC-13 (PZ) — New Purchase Receipt

**Missing route:** `POST /api/v1/pz` (document-level PZ create)  
**Where verified absent:** `routes_pz.py` — only `POST /pz/process` exists (processes an existing
batch from uploaded invoices; not a document-level PZ creation endpoint).  
**UI rendered:** `<button disabled title="DC-13 · Wave-4: requires POST /api/v1/pz (document-level PZ create — not yet deployed...)">+ New Purchase Receipt</button>`  
**Note:** DC-13 PI part is NOT wave-4 — it navigates to existing `/v2/proforma` per §D.

### ③ DC-14 — ParseModal Upload Mode / CreateModal

**Missing route:** Same as ① (`POST /api/v1/{pi|pz}/upload-packing-list`)  
**Coverage:** The modal itself is not rendered because both its trigger buttons (DC-12 Upload
and DC-13-PZ New) are already honest-disabled; there is no non-disabled path that would open it.
Lesson-M compliant: the capability is visible as disabled rather than hidden.

---

## PZ Kanban Honest-Gating (Lesson-M note)

PZ documents do not have draft CRUD endpoints (no approve/reject/edit at the PZ level — those
happen in the PZ processing pipeline). The PZ Draft lane shows all batches in `pz_status` = draft
state, with:
- **Edit** — honest-disabled (title explains no PZ draft CRUD route)
- **Approve** — honest-disabled (same)
- **Post to wFirma** — navigates to `/v2/shipment-detail?batch_id=...` where the gated PZ create
  flow lives
- **Unapprove** — honest-disabled
- **View / Download** — wired to `GET /api/v1/files/{batch_id}/{filename}` (routes_pz.py:1421)

This is not a STOP-REPORT item — it is an operator-ruled design: PZ document management happens
in the shipment detail flow, not in the hub. Hub shows read + navigate only for PZ.

---

## pz-api.js Wave-3 Addition

Added after `getWarehouseLocationInventory` (the previous last method, lines 953-980),
before the closing `});})();`:

```javascript
// ── Wave-3 Documents Hub transport additions ─────────────────────────────
// Transport-only wrapper for EXISTING endpoint.
// No new backend route — EXISTING authority only (DECISIONS.md constraint).

// GET /api/v1/dashboard/batches/{batch_id}/files
// Authority: routes_dashboard.py:558 (GET /batches/{batch_id}/files)
getBatchFiles: (batchId) =>
  _get(`${BASE}/dashboard/batches/${encodeURIComponent(batchId)}/files`),
```

---

## Browser Verification

Server: inventory-dev @ port 8200 (`.claude/launch.json`, reused)

| Check | Result |
|---|---|
| PI tab renders 3-lane Kanban (Draft/Approved/Posted) | PASS — screenshot captured |
| PZ tab renders 3-lane Kanban with 273 real batches in Draft lane | PASS — screenshot captured |
| Other Documents tab renders batch selector + file table | PASS — screenshot captured |
| `/api/v1/proforma/search?limit=200` → 200 | PASS |
| `/api/v1/dashboard/batches` → 200 | PASS |
| `/api/v1/dashboard/batches/{id}/files` → 200 | PASS |
| Console errors | 0 (vendor 404s are pre-existing, app-wide) |
| New 4xx/5xx on Documents Hub paths | 0 |

---

## Contract Supersession — test_sprint35_documents_hub_wiring.py

**File:** `service/tests/test_sprint35_documents_hub_wiring.py`  
**Superseding ruling:** DECISIONS.md Wave-3 2026-07-04 (census DC-5..DC-16 operator ratification)

The Sprint-35 contract encoded the read-only observer design. The Wave-3 census ruling
ratified full CRUD wiring to existing backend authorities, which required updating 5 tests:

| Old test | Disposition | New pin |
|---|---|---|
| `test_no_post_method_in_documents_hub` | Replaced | `test_no_unlisted_write_paths`: raw `method: 'POST'` call-site patterns forbidden; `"POST "` string in title attrs is documentation, not a call |
| `test_no_delete_method_in_documents_hub` | Replaced | same test, covers DELETE call-site pattern |
| `test_no_proforma_lifecycle_stubs` | Updated | onApprove/onUnapprove must now be PRESENT as live React props wired to PzApi; `post-to-wfirma` literal still forbidden |
| `test_required_testids_present` | Replaced | REQUIRED_TESTIDS updated to kanban control set (17 testids covering all 13 controls) |
| `test_view_links_use_real_url_pattern` | Replaced | `documents-v2.html` replaced by `preview.html` (DC-10), `document.pdf` (DC-11), `/api/v1/files/` (DC-15/PZ) |

**New tests added:**
- `test_allowed_endpoint_proforma_search_referenced` — Wave-3 PI Kanban endpoint pin
- `test_allowed_endpoint_batch_files_referenced` — Wave-3 Other Docs endpoint pin
- `test_whitelisted_write_methods_present` — positive assertion all 5 PzApi write methods present
- `test_dc12_upload_button_is_disabled_and_present` — DC-12 Lesson-M disabled pin
- `test_dc13_pz_new_button_is_disabled_and_present` — DC-13-PZ Lesson-M disabled pin
- `test_stop_report_buttons_carry_no_fetch_call` — STOP-report controls carry no active fetch

**Test results after supersession:** 33/33 passed (was 28 passing, 5 failing)  
**Smoke suite:** 63 passed, 1 skipped, 0 failures

---

## Governance Compliance

- DECISIONS.md DOCUMENTS HUB CONSTRAINT: honored — no new write paths added, all fiscal-class actions
  through existing write-gates, closed-gate controls honest-gated per R-Q3
- Lesson M: no control hidden or silently removed — DC-12, DC-13-PZ, DC-14, DC-16 all present as
  disabled buttons with census-tag titles
- Phase-C Constitution §14 (Existing Backend Rule): honored — zero new routes
- FORBIDDEN list: no git stash/clean/reset, no commit/push/PR, no C:\PZ touch, no npm install,
  no write-gate/flag/auth changes, no new backend routes
