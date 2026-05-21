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

  });
})();
