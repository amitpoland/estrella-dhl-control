// pz-api.js — Transport layer for V2 pages.
//
// Exposes window.PzApi. No business logic, no state, no rendering.
//
// Error shape (always): { ok: false, status: number, error: string, type?: string }
// Success shape:         { ok: true, data: <response body> }
//
// Loaded by V2 pages as:
//   <script type="text/babel" data-presets="env,react" src="/dashboard/pz-api.js"></script>
// MUST load AFTER dashboard-shared.js (uses EstrellaShared.apiFetch as transport).
//
// Layer rules (see docs/v2-architecture-plan.md §4):
//   ALLOWED:  fetch, error normalization, HTTP shape
//   FORBIDDEN: business logic, state management, rendering

(function () {
  'use strict';

  // Lazy accessor — EstrellaShared is set by dashboard-shared.js IIFE which
  // runs before this one due to document order.
  function _apiFetch(url, opts) {
    return window.EstrellaShared.apiFetch(url, opts);
  }

  // Resolve operator name — mirrors the mechanism in dashboard.html.
  // Reads from localStorage key 'pz_operator_name'; prompts once if absent.
  function _resolveOperator() {
    try {
      const cached = (window.localStorage.getItem('pz_operator_name') || '').trim();
      if (cached) return cached;
    } catch (_) {}
    let name = '';
    try {
      name = (window.prompt('Operator name (recorded in audit timeline):', 'admin') || '').trim();
    } catch (_) { name = ''; }
    if (name) {
      try { window.localStorage.setItem('pz_operator_name', name); } catch (_) {}
    }
    return name;
  }

  // Validate an action-proposals action URL before POSTing operator identity to it.
  // Defense in depth: guards against a malformed item.endpoint sending attribution
  // to an arbitrary path. action is 'approve' or 'reject'.
  function _isProposalActionUrl(url, action) {
    const re = new RegExp('^/api/v1/action-proposals/[^/]+/' + action + '$');
    return typeof url === 'string' && re.test(url);
  }

  // Normalize any outcome (success or thrown error) to a uniform shape.
  async function _call(method, url, body) {
    try {
      const opts = { method };
      if (body !== undefined) {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = JSON.stringify(body);
      }
      const data = await _apiFetch(url, opts);
      return { ok: true, data };
    } catch (err) {
      return {
        ok:     false,
        status: err.status || 0,
        error:  err.message || String(err),
        type:   err.type,   // 'auth' | 'network' | undefined
      };
    }
  }

  // Mutation-aware call — injects X-Operator header required by draft mutation endpoints.
  async function _callM(method, url, body) {
    const op = _resolveOperator();
    try {
      const opts = { method };
      if (body !== undefined) {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = JSON.stringify(body);
      }
      opts.headers = { ...(opts.headers || {}), ...(op ? { 'X-Operator': op } : {}) };
      const data = await _apiFetch(url, opts);
      return { ok: true, data };
    } catch (err) {
      return {
        ok:     false,
        status: err.status || 0,
        error:  err.message || String(err),
        type:   err.type,
      };
    }
  }

  const _get   = (url)        => _call('GET',    url);
  const _post  = (url, body)  => _call('POST',   url, body);   // read-like POSTs (no X-Operator)
  const _postM = (url, body)  => _callM('POST',  url, body);   // mutation POSTs (X-Operator)
  const _patch = (url, body)  => _callM('PATCH', url, body);
  const _put   = (url, body)  => _callM('PUT',   url, body);
  const _del   = (url)        => _callM('DELETE', url);

  const BASE = '/api/v1';

  window.PzApi = Object.freeze({

    // ── Proforma — read ──────────────────────────────────────────────

    // GET /api/v1/proforma/search?client_name=&batch_id=&...
    // M6 — cross-batch proforma search. Read-only. Authority: proforma_drafts.
    // params: { client_name?, batch_id?, wfirma_proforma_id?,
    //           wfirma_proforma_fullnumber?, draft_state?, currency?,
    //           date_from?, date_to?, page?, page_size? }
    // Returns { ok, data: { ok, results[], total, page, page_size, filters } }
    searchProformaDrafts: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/proforma/search${qs}`);
    },

    // GET /api/v1/proforma/drafts/{batch_id}
    // Returns { ok, data: { ok, batch_id, drafts[], count } }
    getProformaDrafts: (batchId) =>
      _get(`${BASE}/proforma/drafts/${encodeURIComponent(batchId)}`),

    // POST /api/v1/proforma/preview/{batch_id}/{client_name}
    // Returns { ok, data: previewObj } — previewObj.ready from backend, never computed here
    previewProforma: (batchId, clientName) =>
      _post(
        `${BASE}/proforma/preview/${encodeURIComponent(batchId)}/${encodeURIComponent(clientName)}`
      ),

    // GET /api/v1/proforma/draft/{draft_id}
    // Returns { ok, data: { ok, draft: draftObj } }
    getDraft: (draftId) =>
      _get(`${BASE}/proforma/draft/${draftId}`),

    // GET /api/v1/proforma/service-products
    getServiceProducts: () =>
      _get(`${BASE}/proforma/service-products`),

    // GET /api/v1/proforma/product-options
    getProductOptions: () =>
      _get(`${BASE}/proforma/product-options`),

    // ── Proforma — draft edits ───────────────────────────────────────

    // PATCH /api/v1/proforma/draft/{draft_id}
    // patch: { remarks?, payment_terms?, currency?, exchange_rate?, ... }
    // updatedAt: draft.updated_at for optimistic concurrency
    patchDraft: (draftId, patch, updatedAt) =>
      _patch(`${BASE}/proforma/draft/${draftId}`, {
        expected_updated_at: updatedAt || '',
        patch,
      }),

    // PATCH /api/v1/proforma/draft/{draft_id}/lines/{line_id}
    // patch: { qty?, unit_price?, ... }
    patchDraftLine: (draftId, lineId, patch, updatedAt) =>
      _patch(`${BASE}/proforma/draft/${draftId}/lines/${lineId}`, {
        expected_updated_at: updatedAt || '',
        patch,
      }),

    // POST /api/v1/proforma/draft/{draft_id}/lines
    addDraftLine: (draftId, lineBody) =>
      _postM(`${BASE}/proforma/draft/${draftId}/lines`, lineBody),

    // DELETE /api/v1/proforma/draft/{draft_id}/lines/{line_id}
    deleteDraftLine: (draftId, lineId) =>
      _del(`${BASE}/proforma/draft/${draftId}/lines/${lineId}`),

    // POST /api/v1/proforma/draft/{draft_id}/service-charges
    // charge: { charge_type, amount, currency, label? }
    addServiceCharge: (draftId, charge, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/service-charges`, {
        expected_updated_at: updatedAt || '',
        charge,
      }),

    // DELETE /api/v1/proforma/draft/{draft_id}/service-charges/{charge_id}
    deleteServiceCharge: (draftId, chargeId) =>
      _del(`${BASE}/proforma/draft/${draftId}/service-charges/${chargeId}`),

    // DELETE /api/v1/proforma/draft/{draft_id}
    // Hard-delete a local-only cancelled draft (no wFirma refs).
    deleteDraft: (draftId) =>
      _del(`${BASE}/proforma/draft/${draftId}`),

    // ── Proforma — lifecycle ─────────────────────────────────────────

    // POST /api/v1/proforma/draft/{draft_id}/approve
    // updatedAt: draft.updated_at for optimistic concurrency
    approveDraft: (draftId, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/approve`, {
        expected_updated_at: updatedAt || '',
        confirm_token:       'YES_APPROVE_LOCAL_PROFORMA_DRAFT',
      }),

    // POST /api/v1/proforma/draft/{draft_id}/re-open
    reopenDraft: (draftId, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/re-open`, {
        expected_updated_at: updatedAt || '',
        confirm_token:       'YES_REOPEN_LOCAL_PROFORMA_DRAFT',
      }),

    // POST /api/v1/proforma/draft/{draft_id}/cancel
    // reason: operator-provided cancellation reason (required by backend — must be non-empty)
    cancelDraft: (draftId, updatedAt, reason) =>
      _postM(`${BASE}/proforma/draft/${draftId}/cancel`, {
        expected_updated_at: updatedAt || '',
        reason:              reason || '',
      }),

    // POST /api/v1/proforma/draft/{draft_id}/send-email
    // M2 — Send proforma PDF to customer via email queue.
    // confirm_token: "YES_SEND_PROFORMA_EMAIL" (required)
    // recipient_override: optional override for bill_to_email
    // subject_override: optional custom subject
    // message_body: optional HTML body (default: standard template)
    // cc: optional array of CC addresses
    sendProformaEmail: (draftId, { confirm_token, recipient_override, subject_override, message_body, cc } = {}) =>
      _postM(`${BASE}/proforma/draft/${draftId}/send-email`, {
        confirm_token:      confirm_token || '',
        recipient_override: recipient_override || '',
        subject_override:   subject_override || '',
        message_body:       message_body || '',
        cc:                 cc || [],
      }),

    // POST /api/v1/proforma/draft/{draft_id}/reset-from-sales-packing
    resetDraftFromSalesPacking: (draftId, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/reset-from-sales-packing`, {
        expected_updated_at: updatedAt || '',
        reset_all:           false,
      }),

    // POST /api/v1/proforma/draft/{draft_id}/post
    // Posts draft to wFirma as a proforma invoice.
    // Gated by wfirma_create_proforma_allowed flag — backend enforces; frontend should
    // gate the button on the visibility/disclose-post response.
    postDraftToWfirma: (draftId, body) =>
      _postM(`${BASE}/proforma/draft/${draftId}/post`, body || {}),

    // POST /api/v1/proforma/draft/{draft_id}/clone
    // Clones draft — creates a new draft from this one.
    cloneDraft: (draftId) =>
      _postM(`${BASE}/proforma/draft/${draftId}/clone`, {}),

    // POST /api/v1/proforma/draft/{draft_id}/to-invoice
    // Converts posted proforma to a final wFirma invoice.
    // Gated by wfirma_create_invoice_allowed flag — backend enforces.
    // body: { confirm: 'YES_CREATE_FINAL_INVOICE_FROM_PROFORMA', ... }
    draftToInvoice: (draftId, body) =>
      _postM(`${BASE}/proforma/draft/${draftId}/to-invoice`, body || {}),

    // GET /api/v1/proforma/draft/{draft_id}/events
    // Returns event timeline for the draft.
    getDraftEvents: (draftId) =>
      _get(`${BASE}/proforma/draft/${draftId}/events`),

    // GET /api/v1/proforma/draft/{draft_id}/readiness?intent=approve|post|convert
    // SINGLE READINESS AUTHORITY — same gate the backend enforces on
    // approve/post/convert. Frontend reads it to disable buttons with
    // the exact blocker reason + repair action; it never derives
    // readiness locally (Lesson F rule 5).
    getDraftReadiness: (draftId, intent) =>
      _get(`${BASE}/proforma/draft/${draftId}/readiness?intent=${encodeURIComponent(intent || 'approve')}`),

    // POST /api/v1/proforma/draft/{draft_id}/resolve-ambiguity
    // Operator selects the exact product_code for an ambiguous design_no.
    // Backend validates the code against current batch candidates.
    resolveDraftAmbiguity: (draftId, designNo, productCode) =>
      _postM(`${BASE}/proforma/draft/${draftId}/resolve-ambiguity`, {
        design_no:    designNo    || '',
        product_code: productCode || '',
      }),

    // ── Customer Master ──────────────────────────────────────────────

    // GET /api/v1/customer-master[?q=...]
    listCustomerMaster: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/customer-master${qs}`);
    },

    // GET /api/v1/customer-master/{client_key}
    getCustomerMaster: (clientKey) =>
      _get(`${BASE}/customer-master/${encodeURIComponent(clientKey)}`),

    // PUT /api/v1/customer-master/{client_key}
    saveCustomerMaster: (clientKey, body) =>
      _put(`${BASE}/customer-master/${encodeURIComponent(clientKey)}`, body),

    // GET /api/v1/customer-master/sync-from-wfirma/preview — read-only, no wFirma write
    previewWfirmaSyncCustomer: () =>
      _get(`${BASE}/customer-master/sync-from-wfirma/preview`),

    // POST /api/v1/customer-master/sync-from-wfirma/apply — writes ONLY to local customer_master
    // wfirmaIds: string[] — only selected rows
    applyWfirmaSyncCustomer: (wfirmaIds) =>
      _postM(`${BASE}/customer-master/sync-from-wfirma/apply`, { wfirma_ids: wfirmaIds }),

    // GET /api/v1/customer-master/dictionaries — dropdown options for UI
    getCustomerDictionaries: () =>
      _get(`${BASE}/customer-master/dictionaries`),

    // POST /api/v1/customer-master/dictionaries/refresh — operator-triggered wFirma dict refresh
    refreshCustomerDictionaries: () =>
      _postM(`${BASE}/customer-master/dictionaries/refresh`, {}),

    // ── Packing — link-as-sales backfill ─────────────────────────────────
    // GET /api/v1/packing/{batch_id}/packing-documents
    // Returns { ok, data: { batch_id, count, documents: [{ id,
    //   suggested_client_name, line_count, is_duplicate, canonical_id, ... }] } }
    getPackingDocuments: (batchId) =>
      _get(`${BASE}/packing/${encodeURIComponent(batchId)}/packing-documents`),

    // POST /api/v1/packing/{batch_id}/link-as-sales
    // clientMappings: [{ packing_document_id, client_name, client_contractor_id }]
    // client_contractor_id (the operator's Customer-Master pick) is the customer
    // authority — backend (#696) persists it onto the sales chain. Omit/blank →
    // backend name-fallback. Transport only; the page decides the mappings.
    linkAsSales: (batchId, clientMappings) =>
      _postM(`${BASE}/packing/${encodeURIComponent(batchId)}/link-as-sales`,
        { client_mappings: clientMappings || [] }),

    // ── wFirma reservation ───────────────────────────────────────────────
    // GET /api/v1/wfirma/reservation-preview/{batch_id}
    // Returns { ok, data: { ready_to_create, blocking_reasons[], reservation_exists,
    //   reservation_id, documents: [{ client_name, ready, blocking_reasons[], ... }] } }
    // This is the CANONICAL reservation readiness (distinct from proforma post readiness).
    getReservationPreview: (batchId) =>
      _get(`${BASE}/wfirma/reservation-preview/${encodeURIComponent(batchId)}`),

    // POST /api/v1/wfirma/reservations/create  { batch_id, client_name }
    // LIVE wFirma write — hard-gated by check_wfirma_config + per-draft GATE_* checks.
    // 200 → { ok:true, wfirma_reservation_id }; 409 → gate code; 502 → wFirma error.
    // NOTE: the backend CreateReservationRequest model is exactly {batch_id,
    // client_name} — it does NOT define a confirm_token (unlike the proforma
    // post/convert endpoints). The anti-accident gates are the UI confirm modal
    // (operator-approved) + the server-side hard gates; do NOT add a token the
    // backend would reject as an unexpected field.
    createReservation: (batchId, clientName) =>
      _postM(`${BASE}/wfirma/reservations/create`,
        { batch_id: batchId, client_name: clientName }),

    // GET /api/v1/warehouse/receipt/{batch_id}
    // WAREHOUSE authority: per-line expected vs confirmed received quantities +
    // batch summary { total_lines, confirmed_lines, unconfirmed_lines,
    // shortage_lines, overage_lines, fully_confirmed, serial_controlled, lines[] }.
    getReceiptStatus: (batchId) =>
      _get(`${BASE}/warehouse/receipt/${encodeURIComponent(batchId)}`),

    // POST /api/v1/warehouse/receipt/confirm  { batch_id, lines:[{line_key, accepted_qty}], source_documents? }
    // LOCAL operator confirmation write (X-Operator) — NO wFirma/fiscal write.
    // Expected qty is resolved server-side from the import packing authority, so
    // shortage/overage are derived (not client-trusted).
    confirmReceipt: (batchId, lines, sourceDocuments) =>
      _postM(`${BASE}/warehouse/receipt/confirm`,
        { batch_id: batchId, lines: lines, source_documents: sourceDocuments || null }),

    // -- Action proposals (Inbox 2B.3b write wiring) ----------------------
    // Attribution rides in the BODY (approved_by / rejected_by) per the
    // action-proposals contract -- NOT the X-Operator header that _callM
    // injects. So these use _call (no X-Operator) and place identity in the
    // body. Operator is resolved once via _resolveOperator() (single audit
    // identity authority); a blank operator REFUSES to POST. The endpoint is
    // validated against the action-proposals shape before any network call.

    // POST /api/v1/action-proposals/{id}/approve  body: { approved_by, note? }
    // endpoint: the full URL carried on the inbox item (item.endpoint).
    approveProposal: (endpoint, note) => {
      if (!_isProposalActionUrl(endpoint, 'approve'))
        return Promise.resolve({ ok: false, status: 0, type: 'guard',
          error: 'Refused: not a valid action-proposals approve URL.' });
      const op = _resolveOperator();
      if (!op)
        return Promise.resolve({ ok: false, status: 0, type: 'operator',
          error: 'Operator name required -- approval cancelled.' });
      const body = { approved_by: op };
      const n = (note || '').trim();
      if (n) body.note = n;
      return _call('POST', endpoint, body);
    },

    // POST /api/v1/action-proposals/{id}/reject  body: { rejected_by, reason }
    // endpoint: derive from item.endpoint via .replace(/\/approve$/, '/reject').
    // reason: operator-provided, REQUIRED by backend (422 if blank).
    rejectProposal: (endpoint, reason) => {
      if (!_isProposalActionUrl(endpoint, 'reject'))
        return Promise.resolve({ ok: false, status: 0, type: 'guard',
          error: 'Refused: not a valid action-proposals reject URL.' });
      const op = _resolveOperator();
      if (!op)
        return Promise.resolve({ ok: false, status: 0, type: 'operator',
          error: 'Operator name required -- rejection cancelled.' });
      const r = (reason || '').trim();
      if (!r)
        return Promise.resolve({ ok: false, status: 0, type: 'reason',
          error: 'Reason required -- rejection cancelled.' });
      return _call('POST', endpoint, { rejected_by: op, reason: r });
    },

    // ── wFirma Mapping (Sprint 37) ──────────────────────────────────

    // GET /api/v1/wfirma/capabilities
    // Returns { ok, data: { api_configured, customer_api_supported, ..., blocking_reasons[] } }
    getWfirmaCapabilities: () =>
      _get(`${BASE}/wfirma/capabilities`),

    // GET /api/v1/wfirma/customers
    // Returns { ok, data: { count, customers[] } }
    getWfirmaCustomers: () =>
      _get(`${BASE}/wfirma/customers`),

    // GET /api/v1/wfirma/products
    // Returns { ok, data: { count, products[] } }
    getWfirmaProducts: () =>
      _get(`${BASE}/wfirma/products`),

    // GET /api/v1/wfirma/contractors/search?q=
    searchWfirmaContractors: (q) =>
      _get(`${BASE}/wfirma/contractors/search?q=${encodeURIComponent(q || '')}`),

    // GET /api/v1/wfirma/goods/search?q=
    searchWfirmaGoods: (q) =>
      _get(`${BASE}/wfirma/goods/search?q=${encodeURIComponent(q || '')}`),

    // ── Master Data — read (Sprint 38) ─────────────────────────────

    // GET /api/v1/suppliers/[?country=&active=&limit=]
    // Returns { count, suppliers: [{id, supplier_code, name, country, ...}] }
    listSuppliers: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/suppliers${qs}`);
    },

    // GET /api/v1/product-local/[?active=&limit=]
    // Returns { count, items: [{product_code, hs_code_override, unit_override, ...}] }
    listProductLocal: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/product-local${qs}`);
    },

    // GET /api/v1/designs/[?active=&limit=]
    // Returns { ok, count, designs: [{design_code, display_name, ...}] }
    listDesigns: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/designs${qs}`);
    },

    // GET /api/v1/hs-codes/[?active=&limit=]
    // Returns { count, hs_codes: [{hs_code, description_pl, duty_rate_pct, ...}] }
    listHsCodes: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/hs-codes${qs}`);
    },

    // GET /api/v1/fx-rates/[?from_currency=&limit=]
    // Returns { count, fx_rates: [{id, rate_date, from_currency, to_currency, rate, ...}] }
    listFxRates: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/fx-rates${qs}`);
    },

    // GET /api/v1/vat-config/[?active=&limit=]
    // Returns { count, vat_config: [{id, country, product_type, rate_pct, rate_code, ...}] }
    listVatConfig: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/vat-config${qs}`);
    },

    // GET /api/v1/incoterms/[?active=&limit=]
    // Returns { count, incoterms: [{code, name, risk_transfer_point, ...}] }
    listIncoterms: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/incoterms${qs}`);
    },

    // GET /api/v1/units/[?active=&limit=]
    // Returns { count, units: [{code, name_pl, name_en, unit_type, ...}] }
    listUnits: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/units${qs}`);
    },

    // GET /api/v1/carriers-config/[?active=&limit=]
    // Returns { count, carriers: [{carrier_code, name, parser_type, ...}] }
    listCarriersConfig: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/carriers-config${qs}`);
    },

    // GET /api/v1/carrier/status
    // Returns { carrier_api_status, carrier_plt_status }
    getCarrierStatus: () =>
      _get(`${BASE}/carrier/status`),

    // ── System health / API Status — read ──────────────────────────

    // GET /api/v1/debug/health-full
    // Guardian Agent 12-dimension diagnostic snapshot (FastAPI, tunnel,
    // routes, sessions, dashboard, bot, Cliq, OAuth, engine, PZ post,
    // outputs, fonts).  Makes live HTTP probes — may be slow (~5s).
    getHealthFull: () =>
      _get(`${BASE}/debug/health-full`),

    // GET /api/v1/debug/pending
    // Bot pipeline state: active_sessions, bot_pending, last 20 events/
    // stages/posts/errors, counts object.
    getDebugPending: () =>
      _get(`${BASE}/debug/pending`),

    // GET /api/v1/debug/storage/health
    // Storage health: real/test/quarantine batch dirs, lock files, ok flag.
    getStorageHealth: () =>
      _get(`${BASE}/debug/storage/health`),

    // GET /api/v1/debug/storage/locks
    // Lock file probe: lock_files_found, actively_held, releasable,
    // details[{batch_id, lock_file_exists, actively_held}], probe_note.
    getStorageLocks: () =>
      _get(`${BASE}/debug/storage/locks`),

    // GET /api/v1/system/version
    // Service version: { commit, deployed_at, short }.
    getSystemVersion: () =>
      _get(`${BASE}/system/version`),

    // GET /openapi.json
    // Returns FastAPI's OpenAPI spec — the authority for registered routes.
    getOpenApiSpec: () =>
      _get('/openapi.json'),

    // GET /api/v1/pz/health
    // PZ engine: { status, engine, environment, detail }.
    getPzHealth: () =>
      _get(`${BASE}/pz/health`),

    // GET /api/v1/dashboard/batches/{batch_id}
    // Full batch detail: status, clearance_status, action_reason, failed_checks,
    // sales_status_hint, has_sad, files_detail.source_files (invoices/awb/sad),
    // net, gross, duty, mrn, and enriched audit fields.
    // Authority: routes_dashboard.py:batch_detail — read-only, no side effects.
    getBatchDetail: (batchId) =>
      _get(`${BASE}/dashboard/batches/${encodeURIComponent(batchId)}`),

    // GET /api/v1/dhl/readiness/{batch_id}
    // DHL customs pipeline state: dhl_status (7-state pipeline), next_required_action,
    // sla_breach (bool), sla_breach_reason, missing_documents[], awb, timestamps.
    // Authority: dhl_readiness.py:get_dhl_readiness — read-only, no side effects.
    getDhlReadiness: (batchId) =>
      _get(`${BASE}/dhl/readiness/${encodeURIComponent(batchId)}`),

    // GET /api/v1/dhl/auto-scan-status
    // DHL inbox scanner: status, started_at, batches_checked, received_set,
    // b2_triggered, errors_count, next_run_at.
    getDhlAutoScanStatus: () =>
      _get(`${BASE}/dhl/auto-scan-status`),

    // GET /api/v1/dhl/daily-summary
    // Full DHL ops report: lane_a_health, active_shipments, dhl_waiting_queue,
    // lane_b_candidates, exceptions, summary counters.
    getDhlDailySummary: () =>
      _get(`${BASE}/dhl/daily-summary`),

    // GET /api/v1/dhl/followup-automation/status
    // Follow-up SLA card: flags, active/monitoring/eligible counts,
    // next-due, last sent/suppressed, traffic light.
    getDhlFollowupStatus: () =>
      _get(`${BASE}/dhl/followup-automation/status`),

    // GET /api/v1/admin/email-queue
    // Email queue: { pending_count, emails: [...] }.  Requires admin session.
    getEmailQueue: () =>
      _get(`${BASE}/admin/email-queue`),

    // GET /api/v1/intelligence/status
    // Intelligence engine: config age, research docs, capabilities, actors.
    getIntelligenceStatus: () =>
      _get(`${BASE}/intelligence/status`),

    // ── Dashboard — read ────────────────────────────────────────────

    // GET /api/v1/dashboard/batches
    // Returns { ok, data: [...batch summaries] }
    // Each batch summary has 32+ fields from routes_dashboard._batch_summary().
    listBatches: () =>
      _get(`${BASE}/dashboard/batches`),

    // GET /auth/users  (requires admin cookie)
    // Returns [{id, full_name, email, role, is_active, ...}]
    listUsers: () =>
      _get('/auth/users'),

    // GET /api/v1/master/audit/[?entity_type=&limit=]
    // Returns { count, entries: [...] }
    listMasterAudit: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/master/audit${qs}`);
    },

    // ── Ledger — read ───────────────────────────────────────────────

    // GET /api/v1/ledgers/clients/{contractor_id}/invoice-ledger.json
    // Returns { ok, data: { contractor, period, invoices_by_currency, ... } }
    // from and to are YYYY-MM-DD strings (both required by backend)
    getClientInvoiceLedger: (contractorId, from, to) =>
      _get(`${BASE}/ledgers/clients/${encodeURIComponent(contractorId)}/invoice-ledger.json?from=${encodeURIComponent(from || '')}&to=${encodeURIComponent(to || '')}`),

    // ── Proforma — PR B: Customer address + service-charge authority ──

    // POST /api/v1/proforma/draft/{draft_id}/apply-customer-address
    // Applies Customer Master billing/shipping address to buyer_override.
    // Records audit event buyer_override_from_customer_master.
    applyCustomerAddress: (draftId, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/apply-customer-address`, {
        expected_updated_at: updatedAt || '',
      }),

    // GET /api/v1/proforma/draft/{draft_id}/suggest-service-charges
    // Returns combined freight+insurance suggestions from Customer Master.
    suggestServiceCharges: (draftId) =>
      _get(`${BASE}/proforma/draft/${draftId}/suggest-service-charges`),

    // POST /api/v1/proforma/draft/{draft_id}/apply-service-charges
    // Idempotent: already-applied charge type → skipped with reason.
    // apply: ['freight'] | ['insurance'] | ['freight','insurance']
    applyServiceCharges: (draftId, applyList, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/apply-service-charges`, {
        expected_updated_at: updatedAt || '',
        apply: applyList || [],
      }),

  });
})();
