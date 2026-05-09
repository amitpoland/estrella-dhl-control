# Roadmap — Next Phases

Last updated: 2026-05-03  
Current state: Phase 1 complete (core PZ pipeline + primary UI cards + test infrastructure)

---

## Phase 1 — COMPLETED

Core PZ processing pipeline, output generation, WorkDrive upload, Cliq posting, DHL readiness, agency documents upload card, closure evaluation card, full test suite (2324 tests).

---

## Phase 2 — Cleanup & Safety Gates

**Goal:** Close known gaps in the existing feature set before adding new write actions. No new flows, only correctness and safety.

### 2.1 — Gate the Closure Write Endpoint (PRIORITY: HIGH)

**Problem:** `POST /api/v1/closure/{batch_id}/evaluate` calls `apply_closure()` which writes `status=completed` immediately. It is exposed on the API with no confirmation step, no UI protection, and no audit trail for who triggered it.

**Required work:**
1. Add a confirmation token or two-step pattern to `POST /api/v1/closure/{batch_id}/evaluate`
   - Option A: Require a `confirm=true` body field — endpoint checks, rejects without it
   - Option B: Add a `POST /api/v1/closure/{batch_id}/confirm` endpoint that takes a token from a prior "prepare" call
2. Add `closed_by` field to audit when closure is applied
3. Write test: `test_closure_apply_requires_confirmation`
4. Add the guarded closure button to the Overview tab only after this gate is in place

**Dependencies:** None — standalone safety fix.

---

### 2.2 — DHL Documents Browser Upload Card

**Problem:** DHL DS/Cesja documents arrive by email. The agency documents card exists for agency files, but there is no equivalent browser upload card for DHL-sourced documents. Operators must use server paths or CLI.

**Required work:**
1. Add `POST /api/v1/dhl-documents/{batch_id}/upload` multipart endpoint (same pattern as agency docs upload)
2. Register backend handler in `routes_lifecycle.py` or new `routes_dhl.py`
3. Add "DHL Documents Received" upload card to DHL / Customs tab
4. After upload: refresh DHL readiness + batch readiness
5. Write tests: test_lifecycle_layer.py + test_dashboard_dhl_docs_card.py

**Dependencies:** None — self-contained upload path.

---

### 2.3 — Service Invoice Browser Upload Card

**Problem:** `POST /api/v1/service-invoices/{batch_id}/received` accepts server file paths only. No browser upload path exists. Operators cannot upload invoices from the dashboard.

**Required work:**
1. Add `POST /api/v1/service-invoices/{batch_id}/upload` multipart endpoint (same pattern as agency docs)
2. Add "Service Invoices" upload card to DHL / Customs tab (or new Invoices tab)
3. Accept both agency invoices and DHL invoices (distinguish by `source` form field: `"agency"` | `"dhl"`)
4. After upload: refresh batch readiness
5. Write tests: test_lifecycle_layer.py (upload path) + test_dashboard_service_invoices_card.py

**Dependencies:** None — self-contained upload path.

---

### 2.4 — DHL / Customs Tab Completeness

**Problem:** The DHL / Customs tab has readiness display and the new agency docs card, but several actions visible in the MissingFunctionsMatrix have no UI entry point.

**Required work:**
1. Add DHL documents browser upload card (from 2.2)
2. Add service invoices browser upload card (from 2.3)
3. Add agency SLA status display card (read from `dhl_readiness` response fields)
4. Add manual "Mark DHL email received" action (simple POST to write `dhl_email_received=true` to audit)

**Dependencies:** 2.2 and 2.3 must be complete first.

---

### 2.5 — Fix CORS Dev Mode Risk

**Problem:** `allow_origins=["*"]` when `settings.environment == "dev"`. If `environment` is accidentally set to `"dev"` in a production deployment, all write endpoints are open to any origin.

**Required work:**
1. Add startup assertion: if `environment == "dev"` and `host != "localhost"`, log a loud warning
2. Document the `ENVIRONMENT` env var in deployment docs
3. Consider replacing `"*"` with an explicit `dev_allowed_origins` list even in dev mode

**Dependencies:** None — standalone config fix.

---

## Phase 3 — Guarded Write Actions

**Goal:** Surface the write-path actions that currently exist only on the backend, behind proper confirmation UIs.

### 3.1 — Closure Confirmation UI

**Problem:** `apply_closure()` exists and works but has no UI. After Phase 2.1 gates the endpoint, add the UI.

**Required work:**
1. Phase 2.1 must be complete (confirmation gate on the endpoint)
2. Add "Close Shipment" button to Overview tab — Closure Evaluation card or new dedicated card
3. Button opens a confirmation modal: shows current status, lists all 4 closure conditions (all must be green), requires explicit "Confirm closure" click
4. On confirm: POST to `/api/v1/closure/{batch_id}/evaluate` with `confirm=true`
5. On success: card shows `status=completed`, batch readiness refreshes
6. On failure: show specific blocking reason from response
7. Write tests: test_dashboard_closure_apply_card.py

**Dependencies:** Phase 2.1 (endpoint gate).

---

### 3.2 — Proforma → Invoice Conversion UI

**Problem:** `services/proforma_to_invoice.py` exists but has no UI card.

**Required work:**
1. Review `proforma_to_invoice.py` to confirm it is safe to call from the dashboard (no unguarded side effects)
2. Add "Convert Proforma to Invoice" card to PZ / wFirma tab
3. Card: show proforma details, "Convert" button, confirmation step
4. After conversion: refresh PZ readiness, post result to audit
5. Write tests: test_dashboard_proforma_card.py

**Dependencies:** Proforma service safety review.

---

### 3.3 — Manual DHL Reply Trigger

**Problem:** DHL reply building is automated via Cowork, but operators may need to manually trigger or re-trigger a reply (e.g., after Cowork fails or if the email was not detected).

**Required work:**
1. Expose a `POST /api/v1/dhl/{batch_id}/send-reply` endpoint with dry-run mode
2. Add "Send DHL Reply" action to DHL / Customs tab — shows draft, requires confirmation
3. On confirm: builds and queues email via `email_service.py`
4. After send: refresh DHL readiness
5. Write tests: test_dhl_reply_trigger.py + dashboard test

**Dependencies:** Phase 2.1 pattern (confirmation before write). DHL docs browser upload (2.2) must be available first so operator can see what they're replying about.

---

## Phase 4 — Automation & Monitoring

**Goal:** Surface the Cowork pipeline, SLA tracking, and background automation status in the UI.

### 4.1 — Cowork Task Status Card

**Problem:** The Cowork pipeline runs in the background. Operators have no visibility into which tasks are pending, running, or failed.

**Required work:**
1. Add `GET /api/v1/cowork/{batch_id}/tasks` endpoint
2. Add Cowork status card to Intelligence tab
3. Show: task type, status (pending/running/complete/failed), created_at, last_updated
4. Show email drafts pending review (from `audit.cowork_email_drafts[]`)
5. Write tests

**Dependencies:** Cowork result processor must be stable.

---

### 4.2 — Email Draft Review UI

**Problem:** Cowork generates email drafts stored in `audit.cowork_email_drafts[]`. Operators cannot review or approve them from the dashboard.

**Required work:**
1. Add draft display to Intelligence tab — show subject, body, type, reason
2. "Approve" button → sends draft via existing `email_service.queue_email`
3. "Reject" button → marks draft as rejected in audit (does not send)
4. Drafts must be shown with "To be sent by PZ App to: [recipient]" label — Cowork does not control recipients
5. Write tests

**Dependencies:** Phase 3.3 pattern (confirmation before send). Phase 4.1 (Cowork task card).

---

### 4.3 — Agency SLA Monitor Card

**Problem:** `agency_sla_engine.py` tracks response deadlines but has no visible UI. Operators cannot see if a deadline is approaching or overdue.

**Required work:**
1. Add SLA status to DHL readiness response or a new `GET /api/v1/agency/{batch_id}/sla` endpoint
2. Add SLA card to DHL / Customs tab — shows DHL SLA and agency SLA deadlines
3. Visual indicators: green (on track), amber (< 24h), red (overdue)
4. Write tests

**Dependencies:** Phase 2.4 (DHL tab completeness).

---

### 4.4 — Background Job Monitor

**Problem:** WorkDrive upload retry queue and email queue are background processes with no UI visibility.

**Required work:**
1. Add `GET /api/v1/system/queue-status` endpoint
2. Add system status panel to Overview tab or new Admin tab
3. Show: pending WorkDrive uploads, pending email sends, last retry time
4. Write tests

**Dependencies:** None — standalone monitoring addition.

---

## Recommended Build Order

Dependencies flow left to right. Numbers match section IDs above.

```
Phase 2 (safety + cleanup):
  2.1 (closure gate) ──────────────────────────────────┐
  2.2 (DHL docs upload) ───────────────────────────────┼── 2.4 (DHL tab completeness)
  2.3 (service invoice upload) ────────────────────────┘
  2.5 (CORS fix) [independent, do first]

Phase 3 (guarded writes):
  2.1 ──► 3.1 (closure UI)
  2.2 ──► 3.3 (DHL reply trigger)
  [review] ──► 3.2 (proforma conversion UI)

Phase 4 (automation UI):
  3.3 ──► 4.2 (email draft review)
  4.1 ──► 4.2
  2.4 ──► 4.3 (SLA monitor)
  [independent] ──► 4.4 (background job monitor)
```

### Strict priority order

1. **2.5** — CORS fix (independent, no risk, do immediately)
2. **2.1** — Closure endpoint gate (HIGH risk unblocked item)
3. **2.2** — DHL docs upload card (unblocks 2.4 and 3.3)
4. **2.3** — Service invoice upload card (unblocks 2.4)
5. **2.4** — DHL tab completeness
6. **3.1** — Closure UI (after 2.1)
7. **3.3** — DHL reply trigger (after 2.2)
8. **4.1** — Cowork task status card
9. **4.2** — Email draft review (after 4.1 + 3.3)
10. **4.3** — SLA monitor
11. **3.2** — Proforma conversion (after safety review)
12. **4.4** — Background job monitor

---

## Test Coverage Requirements Per Phase

Each phase item must ship with:
- **Backend unit tests** in `tests/test_lifecycle_layer.py` or a new `tests/test_{feature}.py`
- **Dashboard source-grep tests** in `tests/test_dashboard_{card}.py` (one file per new card)
- **Brace/paren balance tests** (already included in the standard card test template — copy from `test_dashboard_agency_docs_card.py`)

The existing pattern (read dashboard.html as text, assert structural markers) must be preserved. No JSX execution. No browser automation in unit tests.
