# Operator Flow Map

Last updated: 2026-05-03  
Scope: Full business flow from invoice upload through shipment closure.

---

## Reading this document

Each step lists:
- **UI location** — which dashboard tab + which card the operator uses
- **Endpoint** — the API path called
- **Service / file** — the backend service that executes the work
- **Audit fields** — which fields in `audit.json` are written
- **Status** — whether this step is fully wired (✅), partially wired (🔶), or missing UI (❌)
- **Blocked actions** — things the operator cannot currently do from the UI

---

## Phase 1 — Shipment Intake

### Step 1.1 — Upload invoice PDFs

| Field | Value |
|-------|-------|
| **UI location** | Documents tab — Invoice Upload card |
| **Endpoint** | `POST /api/v1/pz/upload-invoices` (or equivalent) |
| **Service** | `pz_import_processor.py` |
| **Audit fields** | `invoices[]`, `invoice_count` |
| **Status** | ✅ |
| **Blocked** | — |

Operator selects one or more invoice PDFs. Each is staged for processing. Multiple invoices per batch are supported.

---

### Step 1.2 — Upload ZC429 / SAD PDF

| Field | Value |
|-------|-------|
| **UI location** | Documents tab — ZC429/SAD Upload card |
| **Endpoint** | `POST /api/v1/pz/upload-sad` (or equivalent) |
| **Service** | `pz_import_processor.py` — SAD reader |
| **Audit fields** | `zc429_path`, `sad_path` |
| **Status** | ✅ |
| **Blocked** | — |

One ZC429 or SAD PDF per batch. The engine extracts duty (A00), quantity, and importer fields from this document.

---

### Step 1.3 — Run PZ Processing

| Field | Value |
|-------|-------|
| **UI location** | PZ / wFirma tab — Process button |
| **Endpoint** | `POST /api/v1/pz/process` |
| **Service** | `pz_import_processor.py` — `process_batch()` |
| **Audit fields** | `status`, `lines[]`, `total_net`, `total_gross`, `duty_a00`, `verification`, `amendment_flags`, `pz_filename`, `xlsx_filename` |
| **Status** | ✅ |
| **Blocked** | — |

The engine runs. Landed cost (freight + duty proportional by value) is calculated. SAD vs invoice verification runs (True / False / None+[VERIFY-GAP]). If strict match is active and any check is False, the run fails with a BLOCKED status.

---

### Step 1.4 — Review Verification Result

| Field | Value |
|-------|-------|
| **UI location** | PZ / wFirma tab — verification status display |
| **Endpoint** | (reads from process response or `GET /api/v1/batch/{batch_id}/detail`) |
| **Service** | `pz_import_processor.py` |
| **Audit fields** | read-only display |
| **Status** | ✅ |
| **Blocked** | — |

Operator reviews per-field verification state. Green = confirmed match, red = mismatch (amendment flag raised), grey = could not verify from SAD format ([VERIFY-GAP]). [VERIFY-GAP] is not a failure — it is informational.

---

### Step 1.5 — Download PDF and XLSX

| Field | Value |
|-------|-------|
| **UI location** | PZ / wFirma tab — download buttons |
| **Endpoint** | `GET /api/v1/pz/{batch_id}/pdf`, `GET /api/v1/pz/{batch_id}/xlsx` |
| **Service** | `pdf_generator.py`, `xlsx_generator.py` |
| **Audit fields** | `pz_filename`, `xlsx_filename` |
| **Status** | ✅ |
| **Blocked** | — |

Both files are generated during `process_batch()`. Download links are available immediately after a successful run.

---

### Step 1.6 — WorkDrive Upload (automatic)

| Field | Value |
|-------|-------|
| **UI location** | Not visible — happens automatically after processing |
| **Endpoint** | WorkDrive REST API (internal, via `workdrive_uploader.py`) |
| **Service** | `services/workdrive_uploader.py` |
| **Audit fields** | `workdrive_pdf_resource_id`, `workdrive_xlsx_resource_id`, `workdrive_upload_status` |
| **Status** | ✅ (automatic) |
| **Blocked** | — |

Upload happens inside the `/api/v1/pz/process` call. Resource IDs come back in the response. If upload fails, status is `retry_queued` — local files are safe.

---

### Step 1.7 — Cliq Notification

| Field | Value |
|-------|-------|
| **UI location** | Not visible — posts to #PZ channel in Zoho Cliq |
| **Endpoint** | Estrella Cliq MCP → `#PZ` channel |
| **Service** | Claude MCP step post-response |
| **Audit fields** | `cliq_posted` |
| **Status** | ✅ |
| **Blocked** | — |

After processing, Claude posts a concise summary with PDF/XLSX links (or "pending retry" if WorkDrive failed) to `#PZ`. WorkDrive status never blocks the Cliq notification.

---

## Phase 2 — DHL / Customs Correspondence

### Step 2.1 — Receive DHL DSK Request Email

| Field | Value |
|-------|-------|
| **UI location** | DHL / Customs tab — DHL readiness card (shows email status) |
| **Endpoint** | `GET /api/v1/dhl/{batch_id}/readiness` |
| **Service** | `services/dhl_readiness.py` |
| **Audit fields** | `dhl_email_received`, `dhl_email_date` |
| **Status** | ✅ display; ❌ no manual "mark received" card |
| **Blocked** | Operator cannot manually mark a DHL email as received from the UI. This is set by the Cowork pipeline or by direct audit edit. |

---

### Step 2.2 — Send DHL Reply (automated)

| Field | Value |
|-------|-------|
| **UI location** | ❌ No UI card |
| **Endpoint** | Internal — `POST /api/v1/cowork/action` or via `cowork_action_runner.py` |
| **Service** | `services/dhl_reply_builder.py`, `services/email_service.py` |
| **Audit fields** | `dhl_reply_sent`, `dhl_reply_date` |
| **Status** | 🔷 Backend only |
| **Blocked** | Operator cannot trigger DHL reply from the dashboard. Cowork pipeline triggers it automatically, or operator must use CLI/direct API call. |

---

### Step 2.3 — DHL Responds with DS/Cesja Documents

| Field | Value |
|-------|-------|
| **UI location** | DHL / Customs tab — DHL Documents Received card |
| **Endpoint** | `POST /api/v1/dhl-documents/{batch_id}/received` (server path) |
| **Service** | `services/dhl_document_tracker.py` |
| **Audit fields** | `dhl_docs_received`, `dhl_doc_paths[]` |
| **Status** | 🔶 server path only |
| **Blocked** | No browser upload path for DHL documents. Operator must ensure files are server-accessible first. |

---

### Step 2.4 — Forward Documents to Agency (automated)

| Field | Value |
|-------|-------|
| **UI location** | ❌ No UI card |
| **Endpoint** | Internal — via `cowork_action_runner.py` |
| **Service** | `services/agency_forward_after_dhl_builder.py`, `services/email_service.py` |
| **Audit fields** | `agency_forward_sent`, `agency_forward_date` |
| **Status** | 🔷 Backend only |
| **Blocked** | Operator cannot trigger agency forwarding from the dashboard. Cowork handles this. |

---

## Phase 3 — Agency Customs Processing

### Step 3.1 — Receive Agency SAD / PZC Documents

| Field | Value |
|-------|-------|
| **UI location** | DHL / Customs tab — Agency Documents Received card |
| **Endpoint** | `POST /api/v1/agency-documents/{batch_id}/upload` (multipart) |
| **Service** | `services/agency_sad_monitor.py` — `register_agency_documents()` |
| **Audit fields** | `customs_docs.received`, `customs_docs.paths[]` |
| **Status** | ✅ |
| **Blocked** | — |

Operator uploads one or more files (.pdf, .xml, .html, .htm, .jpg, .jpeg, .png). Each file is saved server-side and registered in the audit. After upload: DHL readiness and batch readiness are refreshed automatically.

---

### Step 3.2 — SAD Import (automatic after agency docs)

| Field | Value |
|-------|-------|
| **UI location** | ❌ No UI card |
| **Endpoint** | Internal — via Cowork pipeline |
| **Service** | `services/sad_importer.py` |
| **Audit fields** | `sad_imported`, `sad_import_date`, `sad_path` |
| **Status** | 🔷 Backend only |
| **Blocked** | Operator cannot manually trigger SAD import. This runs automatically when the Cowork pipeline detects agency documents. |

---

### Step 3.3 — Receive Agency Service Invoice

| Field | Value |
|-------|-------|
| **UI location** | ❌ No UI card |
| **Endpoint** | `POST /api/v1/service-invoices/{batch_id}/received` (server path only) |
| **Service** | `services/service_invoice_monitor.py` |
| **Audit fields** | `agency_invoice_received`, `agency_invoice_path` |
| **Status** | 🔷 Backend only (server path only) |
| **Blocked** | No browser upload path. No UI card. Operator must use server path or CLI. |

---

### Step 3.4 — Receive DHL Service Invoice

| Field | Value |
|-------|-------|
| **UI location** | ❌ No UI card |
| **Endpoint** | `POST /api/v1/service-invoices/{batch_id}/received` (same endpoint, different file) |
| **Service** | `services/service_invoice_monitor.py` |
| **Audit fields** | `dhl_invoice_received`, `dhl_invoice_path` |
| **Status** | 🔷 Backend only (server path only) |
| **Blocked** | Same as 3.3 — no browser upload card. |

---

## Phase 4 — Closure Readiness

### Step 4.1 — Check Closure Readiness (read-only)

| Field | Value |
|-------|-------|
| **UI location** | Overview tab — Closure Evaluation card |
| **Endpoint** | `GET /api/v1/closure/{batch_id}/check` |
| **Service** | `services/shipment_closure.py` — `evaluate_closure()` |
| **Audit fields** | None (read-only) |
| **Status** | ✅ |
| **Blocked** | — |

Operator clicks "Evaluate Closure Readiness". The card shows which of 4 conditions are met:
1. Customs documents received
2. PZ generated
3. Agency invoice received
4. DHL invoice received

For each unmet condition, a next-step hint is shown. The card is explicitly labeled as evaluation-only — it does not close the shipment.

---

### Step 4.2 — Apply Closure (write — NOT YET IN UI)

| Field | Value |
|-------|-------|
| **UI location** | ❌ No UI card — API only |
| **Endpoint** | `POST /api/v1/closure/{batch_id}/evaluate` ⚠️ RISKY — writes immediately |
| **Service** | `services/shipment_closure.py` — `closure_for_batch()` → `apply_closure()` |
| **Audit fields** | `status=completed`, `ready_for_accounting=True`, `closed_at` |
| **Status** | ⚠️ Backend exists, NO UI gate |
| **Blocked** | This endpoint is not exposed in the UI intentionally. It writes `status=completed` with no confirmation gate. Do not add a UI button for this endpoint until a two-step confirmation flow is built. |

---

## Phase 5 — Accounting Hand-Off

### Step 5.1 — Export to wFirma

| Field | Value |
|-------|-------|
| **UI location** | PZ / wFirma tab |
| **Endpoint** | (wFirma integration endpoint — review routes_wfirma.py) |
| **Service** | wFirma integration service |
| **Audit fields** | `wfirma_export_status`, `wfirma_doc_id` |
| **Status** | 🔶 Partial |
| **Blocked** | Details depend on wFirma route implementation. |

---

## Missing UI Actions Summary

The following actions are handled by backend / Cowork but have no operator-facing UI card:

| Action | Where it belongs | Endpoint / Service |
|--------|-----------------|-------------------|
| Manually trigger DHL reply | DHL / Customs tab | `dhl_reply_builder.py` |
| Upload DHL documents (browser) | DHL / Customs tab | needs new upload endpoint |
| Trigger agency document forward | DHL / Customs tab | `agency_forward_after_dhl_builder.py` |
| Upload service invoices (browser) | DHL / Customs tab or new Invoices tab | needs browser upload endpoint |
| Manually trigger SAD import | DHL / Customs tab | `sad_importer.py` |
| Mark DHL email received (manual) | DHL / Customs tab | audit write endpoint |
| Apply shipment closure (guarded) | Overview tab | `POST /closure/{batch_id}/evaluate` — needs confirmation gate |
| Proforma → invoice conversion | PZ / wFirma tab | `proforma_to_invoice.py` |
| View agency SLA status | DHL / Customs tab | `agency_sla_engine.py` |

---

## Audit State Machine

```
[initial]
    │
    ▼ Step 1.3 — process_batch()
[pz_generated = true]
    │
    ▼ Step 3.1 — agency docs uploaded
[customs_docs.received = true]
    │
    ▼ Step 3.3/3.4 — invoices registered
[agency_invoice_received = true]
[dhl_invoice_received = true]
    │
    ▼ Step 4.2 — closure applied (GUARDED)
[status = "completed"]
[ready_for_accounting = true]
```

All intermediate states are safe to re-evaluate at any time using `GET /api/v1/closure/{batch_id}/check`.
