# Development Status Audit

Last updated: 2026-05-03  
Test count: 2324 collected  
Scope: `/Users/amitgupta/Downloads/CLI/service/`

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Complete — backend + UI + tests present |
| 🔶 | Partial — backend exists, UI or tests incomplete |
| 🔷 | Backend only — no UI, no user-facing card |
| ❌ | Missing — planned but not built |
| ⚠️ | Risky — exists but has safety concern |
| 🔒 | Blocked — depends on unbuilt prerequisite |

---

## 1. Core PZ Processing Pipeline

### 1.1 Invoice PDF Parsing
- **Status:** ✅ Complete
- **Backend:** `services/pz_import_processor.py` — `process_batch()`
- **UI:** Documents tab — file upload card
- **Tests:** test_pz_import_processor.py, test_golden_*.py
- **Notes:** Engine-only calculation path. No UI calculation.

### 1.2 ZC429 / SAD PDF Parsing
- **Status:** ✅ Complete
- **Backend:** `services/pz_import_processor.py` — ZC429/SAD reader
- **UI:** Documents tab
- **Tests:** test_pz_import_processor.py

### 1.3 Landed Cost Calculation (freight + duty allocation)
- **Status:** ✅ Complete
- **Backend:** `services/pz_import_processor.py`
- **UI:** PZ / wFirma tab — result display
- **Tests:** test_golden_*.py (golden constant validation)
- **Notes:** Freight allocated proportionally by value, never by piece count. Duty from A00 field only.

### 1.4 SAD vs Invoice Verification
- **Status:** ✅ Complete
- **Backend:** `services/pz_import_processor.py` — three-state: True / False / None+[VERIFY-GAP]
- **UI:** PZ / wFirma tab — verification status display
- **Tests:** test_pz_import_processor.py

### 1.5 Amendment Flag Generation
- **Status:** ✅ Complete
- **Backend:** `services/pz_import_processor.py` — escalates on confirmed False only
- **UI:** PZ / wFirma tab — flags shown
- **Tests:** test_pz_import_processor.py

### 1.6 Bilingual Item Naming
- **Status:** ✅ Complete
- **Backend:** `services/pz_import_processor.py`
- **UI:** PZ output display
- **Tests:** test_pz_import_processor.py

---

## 2. Output Generation

### 2.1 PDF Generation
- **Status:** ✅ Complete
- **Backend:** `services/pdf_generator.py`
- **UI:** PZ / wFirma tab — download button
- **Tests:** test_pdf_generator.py (where present)

### 2.2 XLSX Generation
- **Status:** ✅ Complete
- **Backend:** `services/xlsx_generator.py` (or via `process_batch()` xlsx param)
- **UI:** PZ / wFirma tab — download button
- **Tests:** test_xlsx_*.py

### 2.3 Terminal / Clipboard Output
- **Status:** ✅ Complete (CLI only)
- **Backend:** CLI flags `--clipboard`
- **UI:** N/A (CLI only)
- **Tests:** CLI integration tests

---

## 3. WorkDrive Integration

### 3.1 WorkDrive Upload (REST API)
- **Status:** ✅ Complete
- **Backend:** `services/workdrive_uploader.py` — uploads via WorkDrive REST API directly
- **UI:** Implicit — resource IDs returned in `/api/v1/pz/process` response
- **Tests:** test_workdrive_uploader.py
- **Notes:** TrueSync is NOT the upload path. Direct REST upload only. Resource IDs come from API response.

### 3.2 WorkDrive Share Link Creation
- **Status:** ✅ Complete (via Claude MCP step)
- **Backend:** Handled post-response via `ZohoWorkdrive_createExternalShareLink`
- **UI:** Links posted to Cliq
- **Tests:** Integration tested via CLAUDE.md workflow

### 3.3 WorkDrive Retry Queue
- **Status:** 🔷 Backend only
- **Backend:** Referenced in `workdrive_upload_status` field as `retry_queued`
- **UI:** Cliq message says "upload pending retry"
- **Tests:** Partial

---

## 4. Zoho Cliq Integration

### 4.1 Processing Acknowledgment ("Processing…" message)
- **Status:** ✅ Complete
- **Backend:** webhook → `CLIQ_WEBHOOK_URL` → bot chat
- **Tests:** Integration

### 4.2 Final Batch Result Posting
- **Status:** ✅ Complete
- **Backend:** Estrella Cliq MCP → `Post_message_in_a_channel` → `#PZ`
- **Tests:** Integration

### 4.3 Resend from Dashboard
- **Status:** ✅ Complete
- **Backend:** webhook → `post_to_channel` (OAuth fallback) → `#PZ`
- **Tests:** Integration

---

## 5. DHL / Customs Workflow

### 5.1 DHL Reply Builder
- **Status:** 🔷 Backend only
- **Backend:** `services/dhl_reply_builder.py`
- **UI:** ❌ No UI card
- **Tests:** test_dhl_reply_builder.py
- **Notes:** Builds reply to DHL DSK request emails. Invoked via Cowork pipeline.

### 5.2 DHL SLA Engine
- **Status:** 🔷 Backend only
- **Backend:** `services/dhl_sla_engine.py` (referenced in routes)
- **UI:** DHL / Customs tab — DHL readiness card displays SLA status
- **Tests:** test_dhl_sla_engine.py
- **Notes:** Tracks response deadlines for DHL correspondence.

### 5.3 DHL Readiness Check
- **Status:** ✅ Complete
- **Backend:** `services/dhl_readiness.py` — `GET /api/v1/dhl/{batch_id}/readiness`
- **UI:** DHL / Customs tab — readiness card
- **Tests:** test_dhl_readiness.py

### 5.4 DHL Documents Received Registration
- **Status:** 🔶 Partial
- **Backend:** `services/dhl_document_tracker.py` (or equivalent) — server path registration
- **UI:** DHL / Customs tab — card present
- **Tests:** test_lifecycle_layer.py (registration path)
- **Notes:** Browser upload path exists at `/api/v1/agency-documents/{batch_id}/upload`. DHL-specific upload may differ.

### 5.5 Agency Documents Upload
- **Status:** ✅ Complete
- **Backend:** `routes_lifecycle.py` — `POST /api/v1/agency-documents/{batch_id}/upload` (multipart)
- **UI:** DHL / Customs tab — "Agency Documents Received" card ✅
- **Tests:** test_lifecycle_layer.py (30 tests), test_dashboard_agency_docs_card.py (20 tests)
- **Notes:** Accepts .pdf, .xml, .html, .htm, .jpg, .jpeg, .png. 50MB per file limit. Real file upload only — no fake paths.

### 5.6 Agency SLA Engine
- **Status:** 🔷 Backend only
- **Backend:** `services/agency_sla_engine.py`
- **UI:** ❌ No dedicated UI card — SLA state may appear in DHL readiness
- **Tests:** test_agency_sla_engine.py

### 5.7 Agency Forward (after DHL DSK)
- **Status:** 🔷 Backend only
- **Backend:** `services/agency_forward_after_dhl_builder.py`
- **UI:** ❌ No UI card
- **Tests:** Partial
- **Notes:** Builds agency forwarding email after DHL supplies DS/cesja. Invoked via Cowork pipeline.

---

## 6. Customs Document Processing

### 6.1 SAD Importer
- **Status:** 🔷 Backend only
- **Backend:** `services/sad_importer.py`
- **UI:** ❌ No dedicated UI card — triggered via Cowork pipeline
- **Tests:** test_sad_importer.py

### 6.2 Service Invoice Registration (server path)
- **Status:** 🔷 Backend only
- **Backend:** `routes_lifecycle.py` — `POST /api/v1/service-invoices/{batch_id}/received`
- **UI:** ❌ No UI card for service invoice upload
- **Tests:** test_lifecycle_layer.py (server path tests)
- **Notes:** Accepts server file paths only — no browser upload path built yet.

### 6.3 Service Invoice Monitor
- **Status:** 🔷 Backend only
- **Backend:** `services/service_invoice_monitor.py`
- **UI:** ❌ No UI card
- **Tests:** test_service_invoice_monitor.py

---

## 7. Shipment Closure

### 7.1 Closure Evaluation (read-only check)
- **Status:** ✅ Complete
- **Backend:** `routes_lifecycle.py` — `GET /api/v1/closure/{batch_id}/check` → `evaluate_closure()`
- **UI:** Overview tab — "Closure Evaluation" card ✅
- **Tests:** test_dashboard_closure_eval_card.py (22 tests)
- **Notes:** Pure read-only. Never writes audit. Safe to call at any time.

### 7.2 Closure Apply (write action)
- **Status:** ⚠️ Backend only — RISKY
- **Backend:** `routes_lifecycle.py` — `POST /api/v1/closure/{batch_id}/evaluate` → `closure_for_batch()` → `apply_closure()`
- **UI:** ❌ No UI confirmation gate
- **Tests:** test_lifecycle_layer.py (closure apply path)
- **Security concern:** This endpoint writes `status=completed` and `ready_for_accounting=True` to the audit. It is exposed on the API with no confirmation step, no "are you sure" gate, and no UI protection. A caller who hits this endpoint with the right conditions will close the shipment permanently. This must be gated before any UI exposes it.

### 7.3 Closure-Ready Accounting Flag
- **Status:** 🔷 Backend only
- **Backend:** `apply_closure()` sets `ready_for_accounting=True` in audit
- **UI:** ❌ No UI display
- **Tests:** test_shipment_closure.py

---

## 8. Proforma / Invoice Conversion

### 8.1 Proforma to Invoice
- **Status:** 🔷 Backend only
- **Backend:** `services/proforma_to_invoice.py`
- **UI:** ❌ No UI card
- **Tests:** test_proforma_to_invoice.py (partial)
- **Notes:** Converts proforma entries to invoice records. Not yet surfaced in any tab.

---

## 9. Batch Readiness

### 9.1 Batch Readiness Check
- **Status:** ✅ Complete
- **Backend:** `services/batch_readiness.py` — `GET /api/v1/batch/{batch_id}/readiness`
- **UI:** Overview tab — readiness card with per-check status
- **Tests:** test_batch_readiness.py

### 9.2 Missing Functions Matrix
- **Status:** ✅ Complete (display only)
- **Backend:** Derived from batch readiness checks
- **UI:** Overview tab — `<MissingFunctionsMatrix />` component
- **Tests:** test_dashboard_*.py (structural marker tests)

---

## 10. Cowork (AI Sub-Agent) Pipeline

### 10.1 Cowork Task Creation
- **Status:** 🔷 Backend only
- **Backend:** `services/cowork_task_manager.py` (or routes_cowork.py)
- **UI:** Intelligence tab — shows cowork task status
- **Tests:** Partial

### 10.2 Cowork Result Processor
- **Status:** 🔷 Backend only
- **Backend:** `services/cowork_result_processor.py` — validates evidence, writes safe fields to audit
- **UI:** ❌ No dedicated UI
- **Tests:** test_cowork_result_processor.py

### 10.3 Cowork Action Runner
- **Status:** 🔷 Backend only
- **Backend:** `services/cowork_action_runner.py` — executes DHL/agency actions post-result
- **UI:** ❌ No dedicated UI
- **Tests:** test_cowork_action_runner.py

### 10.4 Email Draft Generation
- **Status:** 🔷 Backend only
- **Backend:** Cowork returns structured `email_draft` JSON; `cowork_result_processor.py` validates; `cowork_action_runner.py` injects routing + sends
- **UI:** Intelligence tab — draft display (partial)
- **Tests:** test_cowork_result_processor.py

---

## 11. Email Services

### 11.1 Email Queue (SMTP)
- **Status:** ✅ Complete
- **Backend:** `services/email_service.py` — `queue_email()`
- **UI:** N/A (background service)
- **Tests:** test_email_service.py

### 11.2 Email Routing
- **Status:** ✅ Complete
- **Backend:** `services/email_routing.py` — per-type recipient resolution
- **UI:** N/A
- **Tests:** test_email_routing.py

---

## 12. Shipment Audit Trail

### 12.1 Audit JSON Read/Write
- **Status:** ✅ Complete
- **Backend:** `write_json_atomic()` (used across services) — atomic writes prevent corruption
- **UI:** Timeline tab — audit event display
- **Tests:** Multiple service tests validate audit mutations

### 12.2 Timeline Display
- **Status:** 🔶 Partial
- **Backend:** Audit events read from `audit.json`
- **UI:** Timeline tab — event list
- **Tests:** test_dashboard_*.py (structural)
- **Notes:** Events displayed but filtering/sorting UI may be incomplete.

---

## 13. Dashboard / UI Infrastructure

### 13.1 React SPA (dashboard.html)
- **Status:** ✅ Complete (functional)
- **Backend:** Served from `app/static/dashboard.html`
- **UI:** 9 tabs: Overview, Documents, DHL / Customs, Warehouse, Sales, PZ / wFirma, Timeline, Intelligence, Proposals
- **Tests:** test_dashboard_*.py series (source-grep pattern)

### 13.2 Cookie Authentication (`apiFetch`)
- **Status:** ✅ Complete
- **Backend:** `core/security.py` — `require_api_key`
- **UI:** `apiFetch()` wrapper uses `credentials: 'include'`
- **Tests:** Dependency override pattern used in all lifecycle tests

### 13.3 API Key / Session Auth
- **Status:** ✅ Complete
- **Backend:** `core/security.py`
- **UI:** Login page / cookie handling
- **Tests:** Auth bypass via `dependency_overrides` in tests

---

## 14. Security Concerns (report only — do not fix without review)

### 14.1 Unguarded Closure Write Endpoint
- **Severity:** HIGH
- **Location:** `routes_lifecycle.py` — `POST /api/v1/closure/{batch_id}/evaluate`
- **Issue:** Calls `closure_for_batch()` → `apply_closure()` which writes `status=completed` and `ready_for_accounting=True`. No confirmation gate. No UI protection. API-callable directly.
- **Recommendation:** Add a confirmation token parameter or require a two-step confirmation before this endpoint executes the write. Do not expose in UI until gate is in place.

### 14.2 CORS Open in Dev Mode
- **Severity:** MEDIUM (dev only)
- **Location:** `app/main.py` or `core/cors.py` — `allow_origins=["*"]` when `settings.environment == "dev"`
- **Issue:** In development, any origin can call all API endpoints including write endpoints.
- **Recommendation:** Ensure `environment` is never accidentally set to `"dev"` in production. Add an assertion or startup check.

---

## Summary Table

| Module | Backend | UI | Tests | Risk |
|--------|---------|-----|-------|------|
| Invoice PDF parsing | ✅ | ✅ | ✅ | — |
| ZC429 / SAD parsing | ✅ | ✅ | ✅ | — |
| Landed cost calculation | ✅ | ✅ | ✅ | — |
| SAD verification | ✅ | ✅ | ✅ | — |
| Amendment flags | ✅ | ✅ | ✅ | — |
| PDF generation | ✅ | ✅ | ✅ | — |
| XLSX generation | ✅ | ✅ | ✅ | — |
| WorkDrive upload | ✅ | implicit | 🔶 | — |
| Cliq posting | ✅ | N/A | 🔶 | — |
| DHL reply builder | ✅ | ❌ | 🔶 | — |
| DHL readiness | ✅ | ✅ | ✅ | — |
| Agency docs upload | ✅ | ✅ | ✅ | — |
| Agency SLA engine | ✅ | ❌ | 🔶 | — |
| Agency forward | ✅ | ❌ | 🔶 | — |
| SAD importer | ✅ | ❌ | 🔶 | — |
| Service invoice (server path) | ✅ | ❌ | ✅ | — |
| Service invoice (browser upload) | ❌ | ❌ | ❌ | — |
| Closure evaluation (read-only) | ✅ | ✅ | ✅ | — |
| Closure apply (write) | ✅ | ❌ | 🔶 | ⚠️ unguarded |
| Proforma to invoice | ✅ | ❌ | 🔶 | — |
| Batch readiness | ✅ | ✅ | ✅ | — |
| Cowork pipeline | ✅ | 🔶 | 🔶 | — |
| Email service | ✅ | N/A | ✅ | — |
| Audit trail | ✅ | 🔶 | ✅ | — |
| CORS (dev mode) | ✅ | N/A | — | ⚠️ open |
