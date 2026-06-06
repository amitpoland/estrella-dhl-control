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

  });
})();
