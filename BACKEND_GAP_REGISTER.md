# Proforma Toolbar Backend Gap Register

**Audit date:** 2026-06-06
**Scope:** Every toolbar button in `proforma-detail.jsx` vs actual backend routes in `routes_proforma.py` and related API modules.
**Branch:** `fix/proforma-toolbar-authority-map`

---

## 1. Existing Backend APIs (confirmed present)

| # | Route | Method | Purpose | Used by button |
|---|-------|--------|---------|----------------|
| 1 | `/api/v1/proforma/draft/{draft_id}` | GET | Fetch single draft | Page load |
| 2 | `/api/v1/proforma/drafts/{batch_id}` | GET | List drafts for batch | Page load |
| 3 | `/api/v1/proforma/draft/{draft_id}` | PATCH | Update draft header fields | Lines tab (inline) |
| 4 | `/api/v1/proforma/draft/{draft_id}/lines/{line_id}` | PATCH | Update single line | Lines tab (inline) |
| 5 | `/api/v1/proforma/draft/{draft_id}/lines` | POST | Add line to draft | Lines tab |
| 6 | `/api/v1/proforma/draft/{draft_id}/lines/{line_id}` | DELETE | Remove line from draft | Lines tab |
| 7 | `/api/v1/proforma/draft/{draft_id}/service-charges` | POST | Add service charge | Lines tab |
| 8 | `/api/v1/proforma/draft/{draft_id}/service-charges/{charge_id}` | DELETE | Remove service charge | Lines tab |
| 9 | `/api/v1/proforma/draft/{draft_id}/clone` | POST | Clone draft as new unposted draft | **tb-duplicate** |
| 10 | `/api/v1/proforma/draft/{draft_id}/post` | POST | Post draft to wFirma | **tb-post** |
| 11 | `/api/v1/proforma/draft/{draft_id}/to-invoice` | POST | Convert proforma to invoice | **tb-convert** |
| 12 | `/api/v1/proforma/draft/{draft_id}/to-invoice-preview` | GET | Preview conversion plan | **tb-convert** (modal) |
| 13 | `/api/v1/proforma/{batch_id}/{cn}/document.pdf` | GET | Download wFirma proforma PDF | **proforma-detail-download-pdf** (Print) |
| 14 | `/api/v1/proforma/draft/{draft_id}/disclose-post` | GET | Payload disclosure before post | **tb-post** (modal) |
| 15 | `/api/v1/proforma/draft/{draft_id}/disclose-convert` | GET | Payload disclosure before convert | **tb-convert** (modal) |
| 16 | `/api/v1/proforma/draft/{draft_id}/events` | GET | Event timeline | History tab |
| 17 | `/api/v1/proforma/draft/{draft_id}/approve` | POST | Approve draft locally | Lifecycle |
| 18 | `/api/v1/proforma/draft/{draft_id}/re-open` | POST | Reopen draft | Lifecycle |
| 19 | `/api/v1/proforma/draft/{draft_id}/cancel` | POST | Cancel draft locally | Lifecycle |
| 20 | `/api/v1/proforma/draft/{draft_id}/reset-from-sales-packing` | POST | Reset lines from packing | Lifecycle |
| 21 | `/api/v1/proforma/draft/{draft_id}/enrich-from-product-descriptions` | POST | Enrich line names from product master | Line enrichment |
| 22 | `/api/v1/proforma/draft/{draft_id}/bulk-price-recovery` | POST | Recover prices from product master | Price recovery |
| 23 | `/api/v1/proforma/draft/{draft_id}/suggest-freight` | GET | Suggest freight charge | Service charges |
| 24 | `/api/v1/proforma/draft/{draft_id}/suggest-insurance` | GET | Suggest insurance charge | Service charges |
| 25 | `/api/v1/proforma/draft/{draft_id}/preview.html` | GET | Server-rendered HTML preview | Preview (legacy) |
| 26 | `/api/v1/proforma/draft/{draft_id}/visibility` | GET | Workflow visibility panel | Overview tab |
| 27 | `/api/v1/proforma/draft/{draft_id}/intelligence` | GET | AI intelligence lane | Intelligence tab |
| 28 | `/api/v1/proforma/draft/{draft_id}/invoice-link` | GET | Conversion result lookup | Overview tab |
| 29 | `/api/v1/proforma/preview/{batch_id}/{client_name}` | POST | Reservation / blocking reasons | Reservation tab |
| 30 | `/api/v1/proforma/pipeline/{batch_id}` | GET | Pipeline state for batch | Dashboard |
| 31 | `/api/v1/proforma/{batch_id}/{cn}/document` | GET | Proforma document metadata | Internal |
| 32 | `/api/v1/proforma/cancel-issued-for-reissue/{batch_id}/{cn}` | POST | Cancel wFirma proforma for reissue | Internal |
| 33 | `/api/v1/proforma/adopt-issued/{batch_id}/{cn}` | POST | Adopt externally issued proforma | Internal |
| 34 | `/api/v1/proforma/{wfirma_id}/refresh-line-names` | POST | Refresh line names from wFirma | Internal |
| 35 | `/api/v1/proforma/create/{batch_id}/{cn}` | POST | Create proforma (legacy path) | Internal |
| 36 | `/api/v1/settings/company-profile` | GET | Exporter identity | SELLER card |
| 37 | `/api/v1/customer-master/{contractor_id}/carrier-accounts` | GET/POST/PUT/DELETE | Carrier account CRUD | Customer master |
| 38 | `/api/v1/carrier/{batch_id}/shipment` | POST | Create DHL shipment | Shipment flow |
| 39 | `/api/v1/carrier/{batch_id}/label-package` | POST | Generate customs document package | Shipment flow |

---

## 2. Missing Backend APIs (no route exists)

| # | Missing API | Required for | Priority | Contract required |
|---|-------------|-------------|----------|-------------------|
| M1 | `DELETE /api/v1/proforma/draft/{draft_id}` | **tb-delete** — Delete entire draft | MEDIUM | Original gap: hard-delete with audit trail. **M1a Cancel Draft enabled (PR #483)**: tb-delete relabeled to "Cancel Draft", wired to existing `POST /draft/{id}/cancel` (soft-state only). Remaining gap: true hard-delete route if needed (M1 DELETE still unimplemented). |
| M2 | ~~`POST /api/v1/proforma/draft/{draft_id}/send-email`~~ | **tb-send** — Email proforma PDF to customer | ✅ **ENABLED (PR #TBD)** | Gap closed — route implemented in `routes_proforma.py`. Guards: draft exists (404), wfirma_proforma_id present (422), terminal state suppression (422), customer email resolvable (422), confirm_token required (422). Queues via `email_service.queue_email` per Lesson E. Recipient from Customer Master `bill_to_email`. New `sendProformaEmail` transport in pz-api.js. SendProformaModal with recipient display + override + confirmation. |
| M3 | `POST /api/v1/proforma/cmr/generate/{draft_id}` | **tb-cmr** — Generate CMR PDF | LOW | No CMR PDF generation engine exists. Would need: template engine (A4 layout matching `estrella-doc-cmr.jsx`), data assembly from draft + carrier + customer master, PDF renderer (WeasyPrint or similar). Response: `application/pdf` bytes. Requires carrier data (`awb`, `service`, `incoterm`, `origin`, `destination`). |
| M4 | `POST /api/v1/proforma/draft/{draft_id}/generate-documents` | **tb-generate** — Generate document package | LOW | Umbrella endpoint for generating multiple documents (proforma PDF, packing list, CMR, CN23). Would orchestrate existing generators. Body: `{types: ["proforma_pdf", "packing_list", "cmr", "cn23"]}`. Response: `{ok, generated: [{type, url, size}], failed: [{type, reason}]}`. |
| M5 | ~~`PUT /api/v1/proforma/draft/{draft_id}/inline-edit`~~ | **tb-edit** — Bulk inline editing mode | ✅ **ENABLED (PR #483)** | Gap closed — UI-only. Edit button wired to batch-edit mode using existing `PATCH /draft/{id}` endpoint. Editable fields: remarks, payment_terms, currency, exchange_rate, incoterm. Optimistic locking via `expected_updated_at`. |
| M6 | `GET /api/v1/proforma/drafts/search?customer={name}&prior=true` | Prior proforma clone | MEDIUM | Search proforma drafts across batches by customer name for "clone from prior proforma" workflow. Body: `{customer_name?, customer_vat?, status_filter?, limit?}`. Response: `{ok, drafts: [{draft_id, batch_id, client_name, doc_no, total_eur, created_at}]}`. |
| M7 | ~~`GET /api/v1/proforma/invoice-history/{contractor_id}`~~ | Prior invoice history | ✅ **ENABLED (PR #483)** | Gap closed — wired to existing `GET /api/v1/ledgers/clients/{id}/invoice-ledger.json` route. Read-only modal shows 12-month invoice history from wFirma. New `getClientInvoiceLedger` transport in pz-api.js. |

---

## 3. UI State Per Button

| testid | Label | State | Reason | Backend route |
|--------|-------|-------|--------|---------------|
| `tb-edit` | ✎ Edit | **ENABLED (PR #483)** | Conditionally enabled when draft in `draft/editing/post_failed` state | `PATCH /draft/{id}` (routes 3-4) — batch-edit mode with optimistic locking. Editable: remarks, payment_terms, currency, exchange_rate, incoterm. |
| `tb-delete` | 🗑 Cancel Draft | **ENABLED (PR #483)** | Conditionally enabled when draft in `draft/editing/approved/post_failed` state | `POST /draft/{id}/cancel` (route 8) — relabeled from Delete to Cancel Draft. Soft-cancel with confirmation modal + reason. |
| `tb-duplicate` | ⎘ Duplicate | **ENABLED** | Calls `PzApi.cloneDraft(draftId)` | `POST /draft/{draft_id}/clone` (route 9) — **confirmed working**. |
| `tb-post` | ↑ Post to wFirma | **CONDITIONAL** | Enabled when `canPost` (draft in `draft/pending_local/approved/post_failed` state) | `POST /draft/{draft_id}/post` (route 10) + `GET /draft/{draft_id}/disclose-post` (route 14) — **confirmed working**. |
| `tb-convert` | ⚠ Convert to Invoice | **CONDITIONAL** | Enabled when `canConvert` (draft in `posted/ready` state) | `POST /draft/{draft_id}/to-invoice` (route 11) + `GET /draft/{draft_id}/to-invoice-preview` (route 12) + `GET /draft/{draft_id}/disclose-convert` (route 15) — **confirmed working**. |
| `tb-preview` | ◫ Preview | **ENABLED** | Opens client-side preview modal (Proforma Classic/Modern/Bold + CMR Classic/Modern) | Client-side rendering from draft data. No backend route needed. Uses `window.EJProformaClassic/Modern/Bold` and `window.EJCMRClassic/Modern`. |
| `tb-cmr` | ≡ CMR | **DISABLED** | "CMR print — no backend PDF generation route. Use Preview to view CMR layout." | No CMR PDF generation route exists (M3). Client-side CMR preview IS available via the Preview modal. |
| `proforma-detail-download-pdf` | ⎙ Print | **CONDITIONAL** | Enabled when `canPrint` (`wfirma_proforma_id` exists) | `GET /{batch_id}/{cn}/document.pdf` (route 13) — **confirmed working**. Requires proforma to be posted to wFirma first. |
| `tb-send` | ➤ Send | **ENABLED (PR #TBD)** | Conditionally enabled when draft has `wfirma_proforma_id` and state is `posted/approved/ready` | `POST /draft/{id}/send-email` — queues proforma PDF email via `email_service.queue_email`. Confirmation modal with recipient display + override. |
| `tb-generate` | ⚙ Generate ▾ | **DISABLED** | "Document generation not yet available from this view" | No umbrella document generation endpoint exists (M4). Individual generators exist elsewhere (carrier label-package, wFirma PDF). |
| `tb-more` | ⋯ | **DISABLED** | "More actions" | Placeholder for future actions menu. No specific backend gap — this is a UI container. |
| `tb-invoice-history` | 📋 Prior Invoices | **ENABLED (PR #483)** | Enabled when `contractorId` available; disabled with reason "wFirma contractor ID missing" otherwise | `GET /ledgers/clients/{id}/invoice-ledger.json` — read-only 12-month invoice history modal. |
| `tb-back` | ← Back | **ENABLED** | Navigates back to proforma list | Client-side navigation. No backend route needed. |

---

## 4. Exact Backend Contracts Required

### M1 — Delete Draft

```
DELETE /api/v1/proforma/draft/{draft_id}
Headers: X-Operator (required), X-API-Key
Guards:
  - draft must exist (404 if not)
  - draft.wfirma_proforma_id must be null/empty (409 if posted — cannot delete a posted proforma)
  - draft.state must be in ['draft', 'pending_local', 'cancelled'] (422 if in active lifecycle)
Body: { confirm_token: "YES_DELETE_PROFORMA_DRAFT" }
Response 200: { ok: true, deleted_id: int, audit_event: "proforma_draft_deleted" }
Side effects:
  - Soft-delete: set state='deleted', preserve row for audit
  - OR hard-delete: remove from proforma_drafts, log to audit trail
  - Emit proforma_draft_deleted event to timeline
```

### M2 — Send Proforma Email — **ENABLED** (PR #484 + PDF attachment PR)

```
POST /api/v1/proforma/draft/{draft_id}/send-email
Headers: X-Operator (required), X-API-Key
Guards:
  - draft must exist (404)
  - draft.wfirma_proforma_id must be present (422 — cannot email a draft that has no PDF)
  - PDF must be fetchable from wFirma (422 on fetch failure or empty PDF)
  - email_routing must resolve recipient (422 if no routing rule)
  - CRLF injection rejected on recipient/CC/subject (400)
Body: {
  recipient_override?: string,   // optional — default from customer_master bill_to_email
  cc?: string[],
  subject_override?: string,     // optional — default: "Proforma {doc_no}"
  message_body?: string,         // optional — default template
  confirm_token: "YES_SEND_PROFORMA_EMAIL"
}
Response 200: {
  ok: true,
  queued_id: string,
  recipient: string,
  subject: string,
  pdf_filename: string,
  pdf_attached: true,
  pdf_bytes: int,
  audit_event: "proforma_email_queued"
}
PDF attachment authority chain:
  draft.wfirma_proforma_id → wfirma_client.fetch_invoice_pdf (read-only)
  → PDF bytes → temp file under storage_root/proforma_email_pdfs/
  → queue_email(attachments=[{label, path}])
  → email_sender._attachments_for_queue (security: path under storage_root)
  → SMTP attachment → temp file cleanup
Lesson E compliance:
  1. Validate draft state + PDF existence at send time (not schedule time)
  2. Idempotency: AWB + email_type + date_window dedup
  3. Terminal-state suppression: check draft not cancelled/deleted
  4. Replay safety: durable sent-state before send returns
  5. Environment isolation: ENV=production guard
Security:
  - CRLF injection prevention on recipient/CC/subject (_sanitise_email_field)
  - HTML escaping in email body (html.escape)
  - PDF filename sanitised for filesystem safety (no path traversal)
  - Temp PDF written under storage_root only
  - Temp PDF cleaned up in finally block after queue_email
```

### M3 — CMR PDF Generation

```
POST /api/v1/proforma/cmr/generate/{draft_id}
  OR
GET /api/v1/proforma/draft/{draft_id}/cmr.pdf
Headers: X-API-Key
Guards:
  - draft must exist (404)
  - carrier data must be present (422 if no batch_id / AWB)
  - seller identity must be resolvable from company-profile (422)
  - customer must be resolvable from draft (422)
Response 200: application/pdf (CMR document)
Response 422: { ok: false, gaps: ["carrier.awb missing", ...] }
Data assembly:
  - cmr_no: "CMR-EJ-{batch_id}"
  - seller: from company-profile endpoint
  - shipto: from customer_master by draft.contractor_id
  - carrier: from carrier_actions / DHL tracking
  - lines: from draft.editable_lines_json
  - Numbered fields 1-24 per CMR convention
Template engine: server-side A4 PDF renderer (WeasyPrint / ReportLab)
```

### M4 — Document Package Generation

```
POST /api/v1/proforma/draft/{draft_id}/generate-documents
Headers: X-Operator (required), X-API-Key
Body: {
  types: ["proforma_pdf", "packing_list", "cmr", "cn23"],
  confirm_token: "YES_GENERATE_DOCUMENTS"
}
Response 200: {
  ok: true,
  generated: [
    { type: "proforma_pdf", url: "/api/v1/proforma/{bid}/{cn}/document.pdf", size_bytes: int },
    { type: "packing_list", url: "...", size_bytes: int }
  ],
  failed: [
    { type: "cmr", reason: "CMR generation not implemented" }
  ],
  audit_event: "document_package_generated"
}
Orchestrates existing generators where they exist:
  - proforma_pdf → existing document.pdf route (delegates to wFirma)
  - packing_list → existing carrier label-package (if implemented)
  - cmr → M3 (not yet implemented)
  - cn23 → existing carrier label-package CN23 component
```

### M6 — Prior Proforma Search

```
GET /api/v1/proforma/drafts/search
Query params:
  customer_name?: string    // fuzzy match on client_name
  customer_vat?: string     // exact match on contractor VAT
  status_filter?: string    // comma-separated: "posted,invoiced"
  limit?: int               // default 20, max 100
  offset?: int              // pagination
Headers: X-API-Key
Response 200: {
  ok: true,
  total: int,
  drafts: [{
    draft_id: int,
    batch_id: string,
    client_name: string,
    doc_no: string,
    total_eur: float,
    currency: string,
    state: string,
    created_at: string,
    line_count: int
  }]
}
Use case: "Clone from prior proforma" — operator searches customer history,
selects a prior proforma, calls POST /draft/{source_id}/clone.
```

### M7 — Prior Invoice History

```
GET /api/v1/proforma/invoice-history/{contractor_id}
Headers: X-API-Key
Query params:
  limit?: int       // default 10, max 50
  since?: string    // ISO date filter
Response 200: {
  ok: true,
  contractor_id: string,
  invoices: [{
    wfirma_id: string,
    number: string,          // e.g. "FV 45/2026"
    date: string,
    total: float,
    currency: string,
    line_count: int,
    vat_rate: string
  }]
}
Side effects: calls wFirma invoices/find API (read-only).
Use case: "Clone from prior invoice" — operator views invoice history,
selects one, a new draft is created from its line data.
```

---

## 5. Summary

### Buttons with full backend authority (ENABLED / CONDITIONAL)

| Button | State | Backend confidence |
|--------|-------|--------------------|
| Duplicate | ENABLED | Full — `clone` endpoint confirmed |
| Post to wFirma | CONDITIONAL | Full — `post` + `disclose-post` confirmed |
| Convert to Invoice | CONDITIONAL | Full — `to-invoice` + `to-invoice-preview` + `disclose-convert` confirmed |
| Print (PDF) | CONDITIONAL | Full — `document.pdf` confirmed (requires wfirma_proforma_id) |
| Preview | ENABLED | Full — client-side rendering, no backend needed |
| Back | ENABLED | Full — client-side navigation |

### Buttons with no backend authority (DISABLED with honest reason)

| Button | State | Gap ID | Reason displayed |
|--------|-------|--------|------------------|
| ~~Edit~~ | ✅ ENABLED (PR #483) | ~~M5~~ | Wired to PATCH endpoint — batch edit mode |
| ~~Delete~~ | ✅ ENABLED as Cancel Draft (PR #483) | ~~M1a~~ | Wired to POST /cancel — soft-state only |
| CMR | DISABLED | M3 | "CMR print — no backend PDF generation route. Use Preview to view CMR layout." |
| ~~Send~~ | ✅ ENABLED (PR #484 + PDF attachment) | ~~M2~~ | Wired to POST /send-email — PDF fetched from wFirma, attached to email |
| Generate ▾ | DISABLED | M4 | "Document generation not yet available from this view" |
| ⋯ (More) | DISABLED | N/A | "More actions" (placeholder) |

### Priority ranking for gap closure

1. ~~**M2 — Send Email** (HIGH)~~ — ✅ **CLOSED (PR #484 + PDF attachment)** — PDF fetched from wFirma, attached to email, CRLF/XSS protections, temp file cleanup
2. **M1 — Hard Delete Draft** (MEDIUM) — cancel enabled (M1a, PR #483), but true DELETE route still needed if hard-delete is required
3. **M6 — Prior Proforma Search** (MEDIUM) — enables clone-from-history workflow
4. ~~**M7 — Prior Invoice History** (MEDIUM)~~ — ✅ **CLOSED (PR #483)** — wired to existing ledger route
5. ~~**M5 — Inline Edit UI** (LOW)~~ — ✅ **CLOSED (PR #483)** — wired to existing PATCH endpoint
6. **M3 — CMR PDF Generation** (LOW) — requires new PDF template engine; client-side preview exists as interim
7. **M4 — Document Package** (LOW) — orchestration wrapper; individual generators must exist first

---

## 6. No buttons removed

All 13 toolbar buttons remain visible per task constraint. Disabled buttons display exact reasons. No dead buttons — every disabled button explains why it is disabled and what backend authority is missing.
