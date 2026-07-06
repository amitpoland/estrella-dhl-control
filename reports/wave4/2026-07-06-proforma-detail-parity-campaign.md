# Final Proforma Detail HTML-Parity Campaign — Authority-Mapped Gap Inventory

**Objective (operator, 2026-07-06):** Make Proforma Detail visually and functionally
indistinguishable from the approved wireframe while preserving all existing backend
authority. Reuse every existing endpoint. Do not invent authority. Backend Pending
only where authority genuinely does not exist.

**Scope:** `service/app/static/v2/proforma-detail.jsx` (single file) + regression tests.
8-tab structure preserved. No new endpoint, authority, DB, or write path.
Auth note: `require_api_key` accepts the `pz_session` cookie (`core/security.py:36`), so
`EstrellaShared.apiFetch` (credentials: include) reaches every read below.

## Classification — IMPLEMENT (reuse-only) vs BACKEND-PENDING (authority absent)

### 1. Source & Extraction review UX
| Gap | Verdict | Authority reused |
|---|---|---|
| Confidence coloring (high/med/low) | **IMPLEMENT** | `extracted_confidence` already in `GET /draft/{id}/extraction` |
| Derived review status (Accepted / Needs review / Needs mapping) | **IMPLEMENT** | `product_matched` + `requires_manual_review` + `unmatched` |
| Extracted-vs-current per-field diff | **BACKEND-PENDING** | No original-extraction snapshot retained by any authority — extraction read composes over current line state |

### 2. Logistics
| Gap | Verdict | Authority reused |
|---|---|---|
| Shipment timeline / carrier events | **IMPLEMENT** | `GET /api/v1/tracking/shipment/{batch_id}/timeline` (cookie auth, local audit log) |
| Customs clearance / delivery status | **IMPLEMENT** | `GET /api/v1/dhl/clearance-status/{batch_id}` (local audit) |
| Live real-time AWB tracking (position) | **BACKEND-PENDING** | Gated on `dhl_tracking_api_status=active`; real AWB (`tracking_ref`) is not stored on the draft — `batch_id` is the only link |

### 3. Documents
| Gap | Verdict | Authority reused |
|---|---|---|
| Proforma PDF download | DONE | `GET /proforma/{bid}/{cn}/document.pdf` |
| Proforma print preview (A4 HTML) | **IMPLEMENT** | `GET /proforma/draft/{draft_id}/preview.html` |
| CMR / Packing preview | DONE | client-side `ProformaPreviewModal` |
| Real shipment-document registry | **IMPLEMENT** | `GET /api/v1/upload/shipment/{batch_id}/documents` (purchase/sales invoice + packing lists + review_state) |
| Invoice PDF (final wFirma invoice) | **BACKEND-PENDING** | No route wraps `fetch_invoice_pdf` for a converted invoice yet |
| DHL label / customs package bundle | **BACKEND-PENDING (gated)** | `POST /carrier/{batch_id}/label-package` needs box selection + generation; not a passive read |

### 4. Overview (commercial)
| Gap | Verdict | Authority reused |
|---|---|---|
| Fake `Paid: 0.00` hardcoded value | **FIX (honesty)** | was fabricated; replaced with load-on-demand real figure |
| Payment status (invoiced / received / outstanding) | **IMPLEMENT (load-on-demand)** | `GET /api/v1/ledgers/clients/{contractor_id}/statement.json` (live wFirma; on button, not auto) |
| Invoice conversion summary | DONE | invoice identity card reads `wfirma_invoice_id/number/converted_at` on the draft |
| Customer financial profile | **IMPLEMENT (load-on-demand)** | folded into the same statement panel; Customer Master already surfaced on Customer Mapping tab |

### 5. Final operator workflow seamlessness
| Gap | Verdict | Authority reused |
|---|---|---|
| Cross-tab workflow progress rail | **IMPLEMENT (authority-backed)** | `draft_state` machine (`proforma_invoice_link_db.py`: draft/editing/post_failed → approved → posted → converted), cross-confirmed by `wfirma_proforma_id` (posted) + `wfirma_invoice_id` (invoiced) — always present on the draft |
| Shipment stage node on the rail | **NOT BUILT (authority absent)** | no draft-level shipment state; AWB not stored on draft; shipment/customs are a SEPARATE authority (Lesson N). Rail omits it and points to the Logistics tab instead |

**Rail decision (operator condition honored):** the state machine EXISTS, so the rail
was built strictly from it — 4 authority-backed nodes (Review → Approved → Posted →
Invoiced). Reservation loads lazily (would show a false "not reserved") and shipment
has no draft-level authority, so neither is a fabricated rail node; both are redirected
to their own tabs via `pf-workflow-note`. Pinned by
`test_sprint36_proforma_detail_authority.py::test_workflow_rail_*`.

## Not in scope / STOP conditions
- Invoice-PDF endpoint, label-package auto-bundle, live AWB tracking: require new backend
  authority or gated generation — surfaced honestly as Backend-Pending, controls kept visible.
