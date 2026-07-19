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

  // Blob download reusing the same cookie auth as _apiFetch (credentials:'include').
  // Fetches the file, triggers a client-side download, revokes the object URL.
  async function _download(url, fallbackName) {
    let res;
    try {
      res = await fetch(url, { credentials: 'include' });
    } catch (_) {
      return { ok: false, error: 'Service unreachable — check that the backend is running.' };
    }
    if (res.status === 401 || res.status === 403) return { ok: false, error: 'Session expired or access denied.' };
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    const blob = await res.blob();
    let name = fallbackName;
    const cd = res.headers.get('Content-Disposition') || '';
    const m = /filename="?([^"]+)"?/.exec(cd);
    if (m) name = m[1];
    const objUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objUrl; a.download = name || 'export.csv';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(objUrl);
    return { ok: true, filename: name };
  }

  // Multipart upload reusing _apiFetch auth; returns parsed JSON (preview/commit result).
  async function _uploadCsv(url, file) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const data = await _apiFetch(url, { method: 'POST', body: fd });
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: (err && err.message) || 'Upload failed', type: err && err.type };
    }
  }

  const BASE = '/api/v1';

  // ── Shared, in-flight-aware cache for the LIVE Client-Balance roster ────────
  // GET /ledgers/clients computes balances LIVE per client (routes_ledgers.py
  // warns to keep `limit` small). Accounting Overview and the embedded Client
  // Ledger page both read limit=100; without sharing, that is two large live
  // wFirma sweeps per hub navigation. This memoizes the in-flight/settled RAW
  // response promise per fully-resolved query string for a short TTL so both
  // consumers reuse ONE read. Transport-layer only — no business logic, no
  // rendering, no balance math; an in-process Map only (never localStorage).
  //   • key = resolved query string  → limit=25 and limit=100 never collide
  //   • the in-flight promise is stored immediately → concurrent callers coalesce
  //   • a failure is NEVER cached: the entry is evicted on reject and the
  //     original error is rethrown unchanged (a retry performs a real request)
  //   • force=true (manual Refresh) evicts the entry, then performs a new request
  const _clientBalancesCache = new Map();   // key(qs) -> { promise, at }
  const _CLIENT_BALANCES_TTL_MS = 8000;     // short-lived: bridges one hub navigation

  const _clientBalancesQs = (params) =>
    (params ? '?' + new URLSearchParams(params).toString() : '');

  // Raw shared roster fetch. Resolves to the raw response body ({ period, rows[],
  // ... }) or rejects with the ORIGINAL error. `force` bypasses + refreshes the
  // matching entry. Backs both listClientBalances (wrapped) and
  // listClientBalancesShared (raw) so identical params share ONE live read.
  function _fetchClientBalancesShared(params, force) {
    const key = _clientBalancesQs(params);
    const now = Date.now();
    if (force) {
      _clientBalancesCache.delete(key);
    } else {
      const hit = _clientBalancesCache.get(key);
      if (hit && (now - hit.at) < _CLIENT_BALANCES_TTL_MS) return hit.promise;
    }
    const entry = { promise: null, at: now };
    entry.promise = _apiFetch(`${BASE}/ledgers/clients${key}`).catch((err) => {
      // Never cache a failure — evict THIS entry (identity-checked so a newer
      // force-refresh entry is never dropped) and rethrow the original error.
      if (_clientBalancesCache.get(key) === entry) _clientBalancesCache.delete(key);
      throw err;
    });
    _clientBalancesCache.set(key, entry);
    return entry.promise;
  }

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

    // GET /api/v1/accounting/documents/{doc_type}  (Wave 4 Item 3A — wFirma invoices/find)
    // doc_type ∈ { invoice, credit_note }. Returns { ok, data: { doc_type, wfirma_type, rows[], count } }
    listAccountingDocs: (docType, start, limit) => {
      const qs = '?' + new URLSearchParams({ start: start || 0, limit: limit || 25 }).toString();
      return _get(`${BASE}/accounting/documents/${encodeURIComponent(docType)}${qs}`);
    },

    // GET /api/v1/ledgers/clients  (Wave 4 Item 4 — Client Balance roster)
    // params: { from?, to?, start?, limit?, country?, q? }. Default window = YTD.
    // Returns { ok, data: { period, count, rows[], column_status } }
    // rows[]: { contractor_id, name, open, overdue_invoice_age, ytd_invoiced,
    //           last_30d (null · Backend Pending), currency, state, balance_available }
    // Shares ONE short-TTL, in-flight-aware cache entry (keyed by resolved query
    // string) with listClientBalancesShared, so Accounting Overview and the
    // embedded Client Ledger no longer issue two independent live reads for the
    // same params. Response contract is UNCHANGED: { ok, data } / { ok:false, ... }.
    listClientBalances: (params) =>
      _fetchClientBalancesShared(params, false)
        .then((data) => ({ ok: true, data }))
        .catch((err) => ({
          ok:     false,
          status: err.status || 0,
          error:  err.message || String(err),
          type:   err.type,
        })),

    // GET /api/v1/ledgers/clients — RAW shared variant for consumers that want
    // the raw response body + their own error handling (the embedded Client
    // Ledger page). Shares the SAME cache entry as listClientBalances for
    // identical params (one live read per navigation). opts.force === true
    // bypasses the cache (used by manual Refresh) and performs a real new
    // request. Resolves to the raw body; rejects with the original error.
    listClientBalancesShared: (params, opts) =>
      _fetchClientBalancesShared(params, !!(opts && opts.force)),

    // GET /api/v1/analytics/phase-a  (Wave 4 Item 1A — reuse for Last wFirma Sync)
    // Read-only. Returns { ok, data: { wfirma_sync: { last_exported_at, exported,
    //           pending, last_exported_doc, ... }, ... } }. No new endpoint.
    getAnalyticsPhaseA: () => _get(`${BASE}/analytics/phase-a`),

    // POST /api/v1/wfirma/sync/payments-pull  (Wave 4 Item 7 — PULL-ONLY)
    // READ-ONLY vs wFirma (payments/find GET) → local payment_state.db snapshot.
    // Bounded to one contractor. NOT a push; no wFirma mutation.
    // Returns { ok, data: { new, existing, contractor_id, direction:'PULL' } }
    pullPayments: (contractorId) =>
      _post(`${BASE}/wfirma/sync/payments-pull`, { contractor_id: contractorId }),

    // POST /api/v1/packing/{batch_id}/upload (multipart — EXISTING authority).
    // Wave 4 Item 8: reuse-only. Parses the packing file, upserts packing lines,
    // and idempotently creates/syncs proforma drafts by (batch_id, client_name).
    // NO new endpoint, no wFirma write. batchId MUST be an explicit real batch —
    // never auto-picked. No JSON headers (browser sets the multipart boundary).
    // Returns { ok, data: { batch_id, file, total_rows, matched_count,
    //           unmatched_count, inserted_count, suggested_client_name, ... } }
    uploadPackingList: async (batchId, file, forceReextract) => {
      const fd = new FormData();
      fd.append('file', file);
      const qs = forceReextract ? '?force_reextract=true' : '';
      try {
        const data = await _apiFetch(
          `${BASE}/packing/${encodeURIComponent(batchId)}/upload${qs}`,
          { method: 'POST', body: fd });
        return { ok: true, data };
      } catch (err) {
        return { ok: false, status: err.status || 0, error: err.message || String(err), type: err.type };
      }
    },

    // POST /api/v1/packing/{batch_id}/reprocess
    // Fileless, batch-level re-extraction: re-parses every stored packing file
    // for the batch through the canonical deterministic extractor (the same
    // authority V1's "Reparse all" uses). No new file is uploaded. Transport
    // only — the backend owns extraction, dedup, and idempotent inventory.
    // Returns { ok, data: { summary: { files, rows, purchase, sales }, ... } }.
    reprocessPacking: (batchId) =>
      _postM(`${BASE}/packing/${encodeURIComponent(batchId)}/reprocess`, {}),

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
    // expected_updated_at + force ride as query params (DELETE has no body
    // in our convention; backend defaults force=false and rejects removing
    // the last line without it). Additive signature — no existing callers.
    deleteDraftLine: (draftId, lineId, updatedAt, force) =>
      _del(`${BASE}/proforma/draft/${draftId}/lines/${lineId}`
        + `?expected_updated_at=${encodeURIComponent(updatedAt || '')}`
        + (force ? '&force=true' : '')),

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

    // PATCH /api/v1/proforma/draft/{draft_id}/service-charges/{charge_id} (X-Operator)
    // Edit an existing freight/insurance charge in place. charge_type is immutable.
    // updates: { amount?, currency?, label?, wfirma_service_id?, rate_pct?, resolution? }
    updateServiceCharge: (draftId, chargeId, updates, updatedAt) =>
      _patch(`${BASE}/proforma/draft/${draftId}/service-charges/${chargeId}`, {
        expected_updated_at: updatedAt || '',
        updates,
      }),

    // POST /api/v1/proforma/draft/{draft_id}/service-charge-resolution (X-Operator)
    // PR-6 — record an explicit commercial decision for a freight/insurance
    // charge. A zero amount is valid (customer_courier / waived / not_applicable /
    // manual_amount). 'calculated' is NOT accepted here — use Calculate from CM.
    // resolution: 'manual_amount'|'customer_courier'|'waived'|'not_applicable'|'unresolved'
    setChargeResolution: (draftId, chargeType, resolution, amount, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/service-charge-resolution`, {
        expected_updated_at: updatedAt || '',
        charge_type: chargeType,
        resolution,
        ...(amount != null ? { amount } : {}),
      }),

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

    // GET /api/v1/proforma/draft/{draft_id}/invoice.pdf
    // Read-only URL for the final wFirma invoice PDF this draft converted to.
    // Transport-layer URL builder only (Lesson F: pz-api.js decides nothing) —
    // the caller navigates to it. 404 when the draft has no linked invoice.
    draftInvoicePdfUrl: (draftId) =>
      `${BASE}/proforma/draft/${encodeURIComponent(draftId)}/invoice.pdf`,

    // GET /api/v1/proforma/draft/{draft_id}/reconciliation
    // Read-only A2 reconciliation report. Transport only (Lesson F): pz-api does
    // NO comparison and NO status inference — it returns the backend view-model.
    getDraftReconciliation: (draftId) =>
      _get(`${BASE}/proforma/draft/${encodeURIComponent(draftId)}/reconciliation`),

    // GET /api/v1/proforma/draft/{draft_id}/preview.html
    // Local EJ-rendered SOURCE-document preview (no wFirma call). URL builder
    // only — reuses the existing preview authority; not a second preview path.
    draftPreviewHtmlUrl: (draftId) =>
      `${BASE}/proforma/draft/${encodeURIComponent(draftId)}/preview.html`,

    // GET /api/v1/proforma/draft/{draft_id}/invoice-link
    // Read-only join on proforma_invoice_links for this draft's proforma id.
    // Returns { ok:true, status:'pending'|'issued'|'failed'|'rolled_back', ... }
    // or { ok:false, status:'not_converted' } when no link row exists. This is
    // the row the backend convert guard reads, so the page can gate on the same
    // authority instead of on the draft mirror alone.
    getDraftInvoiceLink: (draftId) =>
      _get(`${BASE}/proforma/draft/${encodeURIComponent(draftId)}/invoice-link`),

    // GET /api/v1/proforma/invoice-links/split-brain[?proforma_id=...]
    // R-2 read-only detection: conversion links stuck 'pending'/'failed'
    // while a REAL wFirma invoice exists. No write, no wFirma call.
    getInvoiceLinkSplitBrain: (proformaId) =>
      _get(`${BASE}/proforma/invoice-links/split-brain${proformaId ? `?proforma_id=${encodeURIComponent(proformaId)}` : ''}`),

    // POST /api/v1/proforma/invoice-links/{proforma_id}/reconcile
    // R-2 operator-gated LOCAL repair of a split-brain link. Re-fetches the
    // remote invoice read-only, re-runs verify-after-create; NO wFirma write.
    // body: { confirm: 'YES_RECONCILE_INVOICE_LINK', wfirma_invoice_id? }
    reconcileInvoiceLink: (proformaId, body) =>
      _postM(`${BASE}/proforma/invoice-links/${encodeURIComponent(proformaId)}/reconcile`, body || {}),

    // GET /api/v1/proforma/draft/{draft_id}/disclose-convert
    // Read-only payload preview for the proforma→invoice convert action.
    // Returns the exact fields that would be sent to wFirma — no write, no invoice created.
    // 422 if draft has no wfirma_proforma_id (not yet posted). 502 if wFirma unreachable.
    // Optional params: { override_payment_method, override_invoice_date,
    //                    override_sale_date, override_payment_days }
    // When supplied the response includes description_preview and a payload_core_hash
    // that covers the exact description text (so the execute guard catches stale modals).
    getDisclosureConvert: (draftId, params) => {
      let url = `${BASE}/proforma/draft/${draftId}/disclose-convert`;
      if (params) {
        const qs = new URLSearchParams();
        if (params.override_payment_method)
          qs.append('override_payment_method', params.override_payment_method);
        if (params.override_invoice_date)
          qs.append('override_invoice_date', params.override_invoice_date);
        if (params.override_sale_date)
          qs.append('override_sale_date', params.override_sale_date);
        if (params.override_payment_days != null)
          qs.append('override_payment_days', String(params.override_payment_days));
        const qstr = qs.toString();
        if (qstr) url += '?' + qstr;
      }
      return _get(url);
    },

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

    // POST /api/v1/proforma/draft/{draft_id}/assign-packing-product-code
    // Operator confirms a packing design's identity, stamping product_code onto
    // the currently-UNASSIGNED packing piece(s) for that design so the over-bill
    // authority credits them truthfully. Backend refuses anything that is not a
    // currently-surfaced unassigned-packing over-bill repair (no arbitrary
    // assignment). Requires the explicit confirm_token.
    assignPackingProductCode: (draftId, designNo, productCode, expectedCount) =>
      _postM(`${BASE}/proforma/draft/${draftId}/assign-packing-product-code`, {
        design_no:      designNo    || '',
        product_code:   productCode || '',
        expected_count: (expectedCount == null ? undefined : expectedCount),
        confirm_token:  'YES_ASSIGN_PACKING_PRODUCT_CODE',
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

    // DELETE /api/v1/customer-master/{client_key} — soft-delete (default) or ?hard=true
    deleteCustomerMaster: (clientKey, hard) =>
      _del(`${BASE}/customer-master/${encodeURIComponent(clientKey)}${hard ? '?hard=true' : ''}`),

    // POST /api/v1/customer-master/{client_key}/restore
    restoreCustomerMaster: (clientKey) =>
      _postM(`${BASE}/customer-master/${encodeURIComponent(clientKey)}/restore`, {}),

    // GET /api/v1/customer-master/export/csv — triggers a client-side download
    exportCustomersCsv: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _download(`${BASE}/customer-master/export/csv${qs}`, 'customer_master_export.csv');
    },

    // POST /api/v1/customer-master/import/csv — dry-run unless commit=true
    importCustomersCsv: (file, commit) =>
      _uploadCsv(`${BASE}/customer-master/import/csv${commit ? '?commit=true' : ''}`, file),

    // ── Customer Master sub-resources ────────────────────────────────────
    // Transport only (Lesson F): the Customer Master owns the authority; these
    // are the shipping-address and carrier-account child collections that the
    // V1 Client Master already consumed. Responses:
    //   addresses → { count, addresses: [...] }
    //   accounts  → { count, accounts:  [...] }

    // GET/POST/PUT/DELETE /api/v1/customer-master/{cid}/shipping-addresses
    // NOTE the trailing slash on list/create: both routers declare those
    // handlers at "/" (routes_client_addresses.py, routes_client_carrier_accounts.py).
    // Calling them slash-less makes Starlette answer 307 and the browser
    // re-issue the request — every list/create would hit the network twice.
    listShippingAddresses: (contractorId) =>
      _get(`${BASE}/customer-master/${encodeURIComponent(contractorId)}/shipping-addresses/`),
    createShippingAddress: (contractorId, body) =>
      _postM(`${BASE}/customer-master/${encodeURIComponent(contractorId)}/shipping-addresses/`, body),
    updateShippingAddress: (contractorId, addrId, body) =>
      _put(`${BASE}/customer-master/${encodeURIComponent(contractorId)}/shipping-addresses/${addrId}`, body),
    deleteShippingAddress: (contractorId, addrId) =>
      _del(`${BASE}/customer-master/${encodeURIComponent(contractorId)}/shipping-addresses/${addrId}`),

    // GET/POST/PUT/DELETE /api/v1/customer-master/{cid}/carrier-accounts
    listCarrierAccounts: (contractorId) =>
      _get(`${BASE}/customer-master/${encodeURIComponent(contractorId)}/carrier-accounts/`),
    createCarrierAccount: (contractorId, body) =>
      _postM(`${BASE}/customer-master/${encodeURIComponent(contractorId)}/carrier-accounts/`, body),
    updateCarrierAccount: (contractorId, acctId, body) =>
      _put(`${BASE}/customer-master/${encodeURIComponent(contractorId)}/carrier-accounts/${acctId}`, body),
    deleteCarrierAccount: (contractorId, acctId) =>
      _del(`${BASE}/customer-master/${encodeURIComponent(contractorId)}/carrier-accounts/${acctId}`),

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

    // POST /api/v1/carrier/{batch_id}/shipment
    // Creates a DHL Express AWB. Requires CARRIER_API_STATUS=live and credentials.
    // body: { recipient_address, declared_value, currency, weight_kg, dimensions,
    //         shipper_account?, special_instructions?,
    //         product_code?, description?, customer_reference?, shipment_reference?,
    //         receiver_vat_id?, receiver_eori?, box_type_code? }
    // Returns: { batch_id, idempotency_key, mode, state, tracking_ref, simulated,
    //            replayed, label_download_url, commercial_documents_url,
    //            documents_available, saved_labels_exist, carrier, service_code,
    //            box_type_code, weight_kg, dimensions, declared_value, currency }
    createCarrierShipment: (batchId, body) =>
      _postM(`${BASE}/carrier/${encodeURIComponent(batchId)}/shipment`, body),

    // GET /api/v1/carrier/{batch_id}/shipment?client_ref={client_name}
    // The carrier shipment that belongs to THIS client's draft (404 when none).
    // client_ref (draft client_name) scopes resolution to one client so two
    // clients in the same import batch never resolve to the same AWB/CMR
    // (2026-07-16 cross-client AWB leak). Legacy single-client batches still
    // resolve; multi-client legacy batches return an honest 404.
    getCarrierShipment: (batchId, clientRef) =>
      _get(`${BASE}/carrier/${encodeURIComponent(batchId)}/shipment`
        + (clientRef ? `?client_ref=${encodeURIComponent(clientRef)}` : '')),

    // GET /api/v1/carrier/{batch_id}/shipment/legacy-probe
    // Pre-booking probe (ADR-proforma-cmr-short-number §Known limitation):
    // does a legacy (pre-client_ref) shipment row exist for this batch? A
    // client_ref re-book computes a NEW idempotency key, so the coordinator
    // will NOT replay that row — the AWB modal requires explicit operator
    // confirmation first. Pass clientRef to also learn has_client_row: a
    // non-failed row already scoped to THIS client means a same-params
    // re-book replays it (no new record), so the modal suppresses the
    // warning. Read-only; never books, never cancels/voids.
    // Returns: { batch_id, legacy_exists, tracking_ref?, state?, created_at?,
    //            has_client_row? (only when clientRef was sent) }
    probeCarrierLegacyShipment: (batchId, clientRef) =>
      _get(`${BASE}/carrier/${encodeURIComponent(batchId)}/shipment/legacy-probe`
        + (clientRef ? `?client_ref=${encodeURIComponent(clientRef)}` : '')),

    // POST /api/v1/carrier/{batch_id}/shipment/{tracking_ref}/do-not-use
    // LOCAL operational flag for duplicate/unused labels — never calls DHL,
    // never voids the AWB, never deletes label PDFs.
    // body: { reason (required), operator? }
    markCarrierShipmentDoNotUse: (batchId, trackingRef, body) =>
      _postM(`${BASE}/carrier/${encodeURIComponent(batchId)}/shipment/${encodeURIComponent(trackingRef)}/do-not-use`, body),

    // GET /api/v1/carrier/services
    // Returns static DHL Express product code catalogue. No credentials required.
    // Returns: [{ code, name, delivery }]
    listCarrierServices: () =>
      _get(`${BASE}/carrier/services`),

    // GET /api/v1/box-types/?active=true|all
    // Box Profile master (Box Master authority). Used by the AWB modal dropdown
    // (active only) and the Master Data management view ('all').
    // Returns: { count, box_types: [{ id, code, name, carrier, length_cm, width_cm,
    //            height_cm, tare_weight_kg, max_weight_kg, package_type,
    //            sort_order, active, notes }] }
    listBoxTypes: (active = true) =>
      _get(`${BASE}/box-types/${active === 'all' ? '?active=all' : (active ? '?active=true' : '?active=false')}`),

    // PUT /api/v1/box-types/{code} — create or update a Box Profile.
    // Deactivate with { active: false }; profiles are never deleted.
    upsertBoxType: (code, body) =>
      _put(`${BASE}/box-types/${encodeURIComponent(code)}`, body),

    // POST /api/v1/box-types/seed-defaults — insert-only default DHL profiles.
    seedBoxTypeDefaults: () =>
      _postM(`${BASE}/box-types/seed-defaults`, {}),

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

    // -- Inventory: Move Stock (slice B×7-1) ------------------------------
    // GET /api/v1/inventory/state/{batch_id}
    // INVENTORY read authority: counts + per-piece list.
    // { batch_id, as_of, counts, pieces:[{scan_code, state, product_code,
    //   design_no, updated_at, synthetic?, source?}], total, synthetic,
    //   source, degraded }. Honest-empty: unknown batch -> 200 with total=0.
    // synthetic:true pieces are C13A purchase-transit projections (not movable).
    getInventoryState: (batchId) =>
      _get(`${BASE}/inventory/state/${encodeURIComponent(batchId)}`),

    // -- Warehouse: locations + per-location inventory (Phase B fold) -----
    // The NON-PASTE selection feed for the Move Stock modal (operator rule:
    // no raw internal-ID paste; select from lists). Both GET, read-only.
    // GET /api/v1/warehouse/locations  → { count, locations:[{location_code,
    //   warehouse, active, …}] }
    getWarehouseLocations: () =>
      _get(`${BASE}/warehouse/locations`),

    // GET /api/v1/warehouse/locations/{code}/inventory → { location_code,
    //   count, items:[{scan_code, design_no, product_code, batch_id,
    //   current_status, …}] } — items carry scan_code (movePieceLocation key).
    getLocationInventory: (locationCode) =>
      _get(`${BASE}/warehouse/locations/${String(locationCode).split('/').map(encodeURIComponent).join('/')}/inventory`),

    // -- Inventory: Stock Promotion Notes (Phase B slice B2) --------------
    // GET /api/v1/inventory/promotion-notes/{batch_id}
    // { batch_id, total, notes:[header…] } — honest-empty: total=0.
    getPromotionNotes: (batchId) =>
      _get(`${BASE}/inventory/promotion-notes/${encodeURIComponent(batchId)}`),

    // GET /api/v1/inventory/promotion-note/{note_no:path}
    // note_no contains SLASHES (SPN/NNN/YYYY) and the backend route uses a
    // :path converter — encode PER SEGMENT so segment contents stay safe
    // while the slashes remain literal path separators. Do NOT
    // encodeURIComponent the whole id (that would send %2F).
    // 404 -> { detail: { code: "NOTE_NOT_FOUND", … } }.
    getPromotionNote: (noteNo) =>
      _get(`${BASE}/inventory/promotion-note/${String(noteNo).split('/').map(encodeURIComponent).join('/')}`),

    // POST /api/v1/inventory/pieces/{piece_id}/location
    //   body: { to_location, operator, idempotency_key, note? }
    // LOCAL metadata-only write — moves physical location; does NOT change
    // inventory_state; NO wFirma/fiscal write. Idempotent on (piece, key):
    // replays return status:"replayed" with the prior event_id.
    // Operator identity rides in the BODY (backend contract) — action-proposals
    // precedent: _call (no X-Operator) + _resolveOperator(); a blank operator
    // REFUSES to POST.
    movePieceLocation: (pieceId, { toLocation, operator, idempotencyKey, note } = {}) => {
      const op = ((operator || '') || _resolveOperator() || '').trim();
      if (!op)
        return Promise.resolve({ ok: false, status: 0, type: 'operator',
          error: 'Operator name required -- move cancelled.' });
      const body = {
        to_location:     toLocation,
        operator:        op,
        idempotency_key: idempotencyKey,
      };
      const n = (note || '').trim();
      if (n) body.note = n;
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/location`, body);
    },

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

    // POST /api/v1/wfirma/contractors/scan — triggers full contractor scan (skips 6h cooldown)
    // Returns { ok, data: { scan: { healthy, running, last_started_at, last_completed_at, processed, created, updated, skipped, errors, last_error } } }
    runContractorScan: () =>
      _post(`${BASE}/wfirma/contractors/scan`),

    // GET /api/v1/wfirma/contractors/scan/status — read-only scan state
    // Returns { ok, data: { scan: { ... same shape ... } } }
    getContractorScanStatus: () =>
      _get(`${BASE}/wfirma/contractors/scan/status`),

    // GET /api/v1/wfirma/goods/search?q=
    searchWfirmaGoods: (q) =>
      _get(`${BASE}/wfirma/goods/search?q=${encodeURIComponent(q || '')}`),

    // GET /api/v1/wfirma/goods/search?product_code=X — per-code lookup for the
    // ProductMappingResolver in proforma-detail (resolves the product blocker).
    // Uses the canonical product_code param (line 316 of routes_wfirma_capabilities.py).
    // Returns { ok, found, result }. Read-only; never writes to wFirma or mirror.
    wfirmaGoodsSearch: (productCode) =>
      _get(`${BASE}/wfirma/goods/search?product_code=${encodeURIComponent(productCode || '')}`),

    // POST /api/v1/wfirma/goods/create-and-adopt/{code} — CANONICAL product create
    // path. Gated on WFIRMA_CREATE_PRODUCT_ALLOWED (403 "blocked" when off; 409 if
    // the product already exists in wFirma → caller should adopt). NEVER mints a
    // code — the operator supplies the existing product_master code in the URL.
    // body: {item_type, description_en?}. Returns { ok, ... } or the block payload.
    // LIVE wFirma write — never call without explicit operator confirmation.
    wfirmaGoodsCreateAndAdopt: (code, body) =>
      _postM(`${BASE}/wfirma/goods/create-and-adopt/${encodeURIComponent(code)}`, body || {}),

    // POST /api/v1/wfirma/goods/adopt/{code} — adopt an EXISTING wFirma product
    // (no wFirma create). Use when create-and-adopt returns 409 already_in_wfirma.
    wfirmaGoodsAdopt: (code) =>
      _postM(`${BASE}/wfirma/goods/adopt/${encodeURIComponent(code)}`, {}),

    // POST /api/v1/wfirma/goods/update-and-adopt/{code} — edit wFirma metadata +
    // adopt. Gated on WFIRMA_EDIT_PRODUCT_ALLOWED. body: {item_type?, description_en?}
    // wFirma write — never call without explicit operator confirmation.
    wfirmaGoodsUpdateAndAdopt: (code, body) =>
      _postM(`${BASE}/wfirma/goods/update-and-adopt/${encodeURIComponent(code)}`, body || {}),

    // ── Master Data — read (Sprint 38) ─────────────────────────────

    // GET /api/v1/suppliers/[?country=&active=&limit=]
    // Returns { count, suppliers: [{id, supplier_code, name, country, ...}] }
    listSuppliers: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/suppliers${qs}`);
    },

    // GET /api/v1/suppliers/{id}
    getSupplier: (id) => _get(`${BASE}/suppliers/${encodeURIComponent(id)}`),

    // POST /api/v1/suppliers/ — create; body incl. supplier_code, name, country
    createSupplier: (body) => _postM(`${BASE}/suppliers/`, body),

    // PUT /api/v1/suppliers/{id} — partial update merges over existing
    saveSupplier: (id, body) => _put(`${BASE}/suppliers/${encodeURIComponent(id)}`, body),

    // DELETE /api/v1/suppliers/{id} — soft-delete (default) or ?hard=true
    deleteSupplier: (id, hard) =>
      _del(`${BASE}/suppliers/${encodeURIComponent(id)}${hard ? '?hard=true' : ''}`),

    // POST /api/v1/suppliers/{id}/restore
    restoreSupplier: (id) => _postM(`${BASE}/suppliers/${encodeURIComponent(id)}/restore`, {}),

    // GET /api/v1/suppliers/sync-from-wfirma/preview — read-only proposals
    previewWfirmaSyncSupplier: () => _get(`${BASE}/suppliers/sync-from-wfirma/preview`),

    // POST /api/v1/suppliers/sync-from-wfirma/apply — writes ONLY to local suppliers
    applyWfirmaSyncSupplier: (wfirmaIds) =>
      _postM(`${BASE}/suppliers/sync-from-wfirma/apply`, { wfirma_ids: wfirmaIds }),

    // GET /api/v1/suppliers/export/csv — triggers a client-side download
    exportSuppliersCsv: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _download(`${BASE}/suppliers/export/csv${qs}`, 'suppliers_export.csv');
    },

    // POST /api/v1/suppliers/import/csv — dry-run unless commit=true
    importSuppliersCsv: (file, commit) =>
      _uploadCsv(`${BASE}/suppliers/import/csv${commit ? '?commit=true' : ''}`, file),

    // GET /api/v1/product-local/[?active=&limit=]
    // Returns { count, items: [{product_code, hs_code_override, unit_override, ...}] }
    listProductLocal: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/product-local${qs}`);
    },

    // PUT /api/v1/product-local/{code} — upsert the LOCAL OVERLAY only (HS/unit
    // override, design_code_link, notes). Does NOT touch product_master (which is
    // consume-only). body: {hs_code_override, unit_override, design_code_link, notes, origin_country, active}
    saveProductLocal: (code, body) =>
      _put(`${BASE}/product-local/${encodeURIComponent(code)}`, body),

    // ── Product Master sync (Slice 1) — read authority + observable Run Now ──
    // GET /api/v1/product-master[?batch_id=]
    // Returns { count, rows: [{product_code, design_no, normalized_design_attributes, status, ...}] }
    listProductMaster: (batchId) => {
      const qs = batchId ? '?batch_id=' + encodeURIComponent(batchId) : '';
      return _get(`${BASE}/product-master${qs}`);
    },

    // GET /api/v1/product-master/sync/status[?batch_id=]
    // Returns { healthy, running, last_started_at, last_completed_at, processed,
    //           created, updated, skipped, errors, last_error, ever_run }
    getProductMasterSyncStatus: (batchId) => {
      const qs = batchId ? '?batch_id=' + encodeURIComponent(batchId) : '';
      return _get(`${BASE}/product-master/sync/status${qs}`);
    },

    // POST /api/v1/product-master/sync/{batch_id}  body { dry_run }
    // Advisory-only sync from the purchase packing list. Never mints product_codes,
    // never creates wFirma products (mirror step is preview). Returns the run summary.
    productMasterSync: (batchId, opts) => {
      const dryRun = !opts || opts.dryRun !== false;   // default: dry-run first
      return _post(`${BASE}/product-master/sync/${encodeURIComponent(batchId)}`, { dry_run: !!dryRun });
    },

    // GET /api/v1/designs/[?active=&limit=]
    // Returns { ok, count, designs: [{design_code, display_name, ...}] }
    listDesigns: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/designs${qs}`);
    },

    // GET /api/v1/designs/{code}
    getDesign: (code) => _get(`${BASE}/designs/${encodeURIComponent(code)}`),

    // PUT /api/v1/designs/{code} — upsert the DESIGN master (design_code is the
    // operator-supplied key; never a product code). body: {display_name, product_ref,
    // design_family, collection, metal, stone_summary, hs_code, unit, notes, active}
    saveDesign: (code, body) =>
      _put(`${BASE}/designs/${encodeURIComponent(code)}`, body),

    // DELETE /api/v1/designs/{code} — soft-delete (default) or ?hard=true
    deleteDesign: (code, hard) =>
      _del(`${BASE}/designs/${encodeURIComponent(code)}${hard ? '?hard=true' : ''}`),

    // POST /api/v1/designs/{code}/restore
    restoreDesign: (code) => _postM(`${BASE}/designs/${encodeURIComponent(code)}/restore`, {}),

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

    // ── Wave 7: master capability contract + remaining-master CRUD writers ────
    // GET /api/v1/master/capabilities — the single source of truth the master
    // page renders (per-domain available/routes/permission/reason/flags).
    getMasterCapabilities: () => _get(`${BASE}/master/capabilities`),

    // HS Codes — PUT natural-key upsert, soft-delete (?hard), restore
    saveHsCode: (code, body) => _put(`${BASE}/hs-codes/${encodeURIComponent(code)}`, body),
    deleteHsCode: (code, hard) => _del(`${BASE}/hs-codes/${encodeURIComponent(code)}${hard ? '?hard=true' : ''}`),
    restoreHsCode: (code) => _postM(`${BASE}/hs-codes/${encodeURIComponent(code)}/restore`, {}),

    // Units
    saveUnit: (code, body) => _put(`${BASE}/units/${encodeURIComponent(code)}`, body),
    deleteUnit: (code, hard) => _del(`${BASE}/units/${encodeURIComponent(code)}${hard ? '?hard=true' : ''}`),
    restoreUnit: (code) => _postM(`${BASE}/units/${encodeURIComponent(code)}/restore`, {}),

    // Incoterms
    saveIncoterm: (code, body) => _put(`${BASE}/incoterms/${encodeURIComponent(code)}`, body),
    deleteIncoterm: (code, hard) => _del(`${BASE}/incoterms/${encodeURIComponent(code)}${hard ? '?hard=true' : ''}`),
    restoreIncoterm: (code) => _postM(`${BASE}/incoterms/${encodeURIComponent(code)}/restore`, {}),

    // Carriers config (non-secret; credential fields rejected by the backend)
    saveCarrierConfig: (code, body) => _put(`${BASE}/carriers-config/${encodeURIComponent(code)}`, body),
    deleteCarrierConfig: (code, hard) => _del(`${BASE}/carriers-config/${encodeURIComponent(code)}${hard ? '?hard=true' : ''}`),
    restoreCarrierConfig: (code) => _postM(`${BASE}/carriers-config/${encodeURIComponent(code)}/restore`, {}),

    // VAT config — POST create (autoincrement id), PUT update, soft-delete, restore
    createVatConfig: (body) => _postM(`${BASE}/vat-config/`, body),
    saveVatConfig: (id, body) => _put(`${BASE}/vat-config/${encodeURIComponent(id)}`, body),
    deleteVatConfig: (id, hard) => _del(`${BASE}/vat-config/${encodeURIComponent(id)}${hard ? '?hard=true' : ''}`),
    restoreVatConfig: (id) => _postM(`${BASE}/vat-config/${encodeURIComponent(id)}/restore`, {}),

    // FX rates — reference-only store (POST create, PUT update, soft-delete, restore)
    createFxRate: (body) => _postM(`${BASE}/fx-rates/`, body),
    saveFxRate: (id, body) => _put(`${BASE}/fx-rates/${encodeURIComponent(id)}`, body),
    deleteFxRate: (id, hard) => _del(`${BASE}/fx-rates/${encodeURIComponent(id)}${hard ? '?hard=true' : ''}`),
    restoreFxRate: (id) => _postM(`${BASE}/fx-rates/${encodeURIComponent(id)}/restore`, {}),

    // Users — admin actions only (no edit/delete endpoint exists). /auth prefix.
    approveUser: (id) => _postM(`/auth/users/${encodeURIComponent(id)}/approve`, {}),
    rejectUser: (id) => _postM(`/auth/users/${encodeURIComponent(id)}/reject`, {}),
    setUserRole: (id, role) => _postM(`/auth/users/${encodeURIComponent(id)}/role`, { role }),
    activateUser: (id) => _postM(`/auth/users/${encodeURIComponent(id)}/activate`, {}),
    deactivateUser: (id) => _postM(`/auth/users/${encodeURIComponent(id)}/deactivate`, {}),

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

    // POST /api/v1/shipment/intake (multipart — EXISTING B1 intake authority).
    // The single canonical shipment-creation path. Caller builds the FormData
    // (tracking_no, carrier, metadata JSON, idempotency_key, and the file
    // fields: invoices[], packing_lists[], awb, sales_documents[],
    // sales_packing_lists[], service_invoices[], carnet_docs[], other_docs[]).
    // No JSON headers — the browser sets the multipart boundary. Auth is the
    // session cookie (require_api_key); no X-Operator needed. Passing the same
    // idempotency_key on a retry returns the ORIGINAL batch (no duplicate).
    // Returns { ok, data: { batch_id, status:'draft', warnings?, awb?, sad?,
    //           purchase, sales, documents_registered, idempotent_replay? } }.
    intakeShipment: async (formData) => {
      try {
        const data = await _apiFetch(`${BASE}/shipment/intake`, { method: 'POST', body: formData });
        return { ok: true, data };
      } catch (err) {
        return { ok: false, status: err.status || 0, error: err.message || String(err), type: err.type };
      }
    },

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

    // ── DHL live tracking (carrier status) — read ───────────────────
    // GET /api/v1/tracking/{tracking_no}?carrier=&batch_id=&refresh=
    // Authority: tracking_service.get_tracking_status. Caches per-batch; gated by
    // DHL_TRACKING_API_STATUS (default "pending" → fallback, NO live DHL call).
    // Never raises server-side — returns { available, ok, status, status_label,
    // last_event, last_location, last_update, source, tracking_url, ... }.
    getDhlTracking: (trackingNo, batchId, opts = {}) => {
      const qs = new URLSearchParams();
      if (batchId)      qs.set('batch_id', batchId);
      if (opts.carrier) qs.set('carrier', opts.carrier);
      if (opts.refresh) qs.set('refresh', 'true');
      const q = qs.toString();
      return _get(`${BASE}/tracking/${encodeURIComponent(trackingNo)}${q ? '?' + q : ''}`);
    },

    // POST /api/v1/tracking/{tracking_no}/refresh?batch_id=
    // Forces a fresh carrier read + patches audit.tracking under the batch lock.
    // get_current_user (session) auth — no X-Operator, no operator prompt.
    refreshDhlTracking: (trackingNo, batchId) => {
      const q = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : '';
      return _post(`${BASE}/tracking/${encodeURIComponent(trackingNo)}/refresh${q}`);
    },

    // ── DHL correspondence commands (same backend authority as the DHL Console) ─
    // Wired so the canonical V2 Shipment Detail page can run the proven follow-up
    // workflow without leaving the shipment context. Send stays confirmation-gated
    // in the UI; none of these fire wFirma / PZ / accounting / inventory writes.

    // GET /api/v1/dhl/scan-inbox?batch_id=&refresh=  (require_api_key)
    // Reads the mailbox; auto-sets dhl_email.received + emits dhl_email_received
    // when a DHL customs sender email is matched for an active batch.
    scanDhlInbox: (batchId, opts = {}) => {
      const qs = new URLSearchParams();
      if (batchId)      qs.set('batch_id', batchId);
      if (opts.refresh) qs.set('refresh', 'true');
      const q = qs.toString();
      return _get(`${BASE}/dhl/scan-inbox${q ? '?' + q : ''}`);
    },

    // POST /api/v1/dhl/mark-email-received/{batch_id}  (admin/logistics)
    markDhlEmailReceived: (batchId, body = {}) =>
      _postM(`${BASE}/dhl/mark-email-received/${encodeURIComponent(batchId)}`, body),

    // POST /api/v1/dhl/generate-description/{batch_id}?awb=&force=  (admin/logistics)
    // Local Polish-description PDF + SAD-ready JSON generation; emits description_ready.
    generatePolishDescription: (batchId, opts = {}) => {
      const qs = new URLSearchParams();
      if (opts.awb)   qs.set('awb', opts.awb);
      if (opts.force) qs.set('force', 'true');
      const q = qs.toString();
      return _postM(`${BASE}/dhl/generate-description/${encodeURIComponent(batchId)}${q ? '?' + q : ''}`);
    },

    // POST /api/v1/dsk/generate  {batch_id, awb, value_usd}  (admin/logistics)
    // Local DSK PDF generation; emits dsk_generated.
    generateDsk: (batchId, opts = {}) =>
      _postM(`${BASE}/dsk/generate`, { batch_id: batchId, awb: opts.awb, value_usd: opts.value_usd }),

    // POST /api/v1/dsk/email-package  {batch_id, awb}  (admin/logistics)
    // Builds the reply package (audit.reply_package) — does NOT send.
    buildDhlReplyPackage: (batchId, opts = {}) =>
      _postM(`${BASE}/dsk/email-package`, { batch_id: batchId, awb: opts.awb }),

    // POST /api/v1/dhl/send-reply/{batch_id}  (admin/logistics)
    // Queues the prepared reply for sending (SMTP-gated); emits reply_approved /
    // dsk_transfer_sent. Confirmation-gated in the UI — never auto-sent.
    sendDhlReply: (batchId) =>
      _postM(`${BASE}/dhl/send-reply/${encodeURIComponent(batchId)}`),

    // GET /api/v1/dashboard/batches/{batch_id}/dhl-action-state — next-action
    // descriptor (which correspondence action the backend considers next).
    getDhlActionState: (batchId) =>
      _get(`${BASE}/dashboard/batches/${encodeURIComponent(batchId)}/dhl-action-state`),

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

    // POST /api/v1/proforma/draft/{draft_id}/apply-customer-commercial
    // Applies operator-selected Customer Master commercial defaults.
    // ``fields`` = string[] subset of:
    //   payment_method, payment_terms_days, invoice_language_id, vat_mode,
    //   freight_amount, freight_service_id, insurance_rate, insurance_service_id
    // Records audit event commercial_defaults_from_customer_master.
    applyCustomerCommercial: (draftId, fields, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/apply-customer-commercial`, {
        fields,
        expected_updated_at: updatedAt || '',
      }),

    // POST /api/v1/proforma/draft/{id}/set-commercial-defaults (X-Operator).
    // Operator-CHOSEN commercial terms from controlled wFirma-backed dropdowns —
    // distinct from applyCustomerCommercial (which copies Customer Master defaults).
    // fields: { payment_method?, payment_terms_days?, invoice_language_id?, vat_mode? }
    // Validated server-side: an invalid enum/id is rejected with a field-level 422.
    setCommercialDefaults: (draftId, fields, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/set-commercial-defaults`, {
        ...(fields || {}),
        expected_updated_at: updatedAt || '',
      }),

    // POST /api/v1/proforma/draft/{id}/fetch-nbp-rate (X-Operator).
    // Fetches + persists the NBP exchange rate for the draft currency, reusing the
    // sole PZ NBP authority server-side (ADR-2026-07-15-proforma-nbp-fetch — this
    // supersedes the earlier display-only prohibition). Returns the refreshed
    // canonical draft plus an `nbp` evidence block (rate/source/table_number/
    // table_date/accounting_date). USD/EUR fetched, PLN identity; other → 422.
    fetchNbpRate: (draftId, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/fetch-nbp-rate`, {
        expected_updated_at: updatedAt || '',
      }),

    // POST /api/v1/proforma/draft/{id}/weight-override (X-Operator).
    // Operator manual net/gross weight (KG) for the CMR / Packing List. The
    // extracted packing weight stays the historical authority; this becomes the
    // effective value only after this explicit save. fields: { manual_net_weight?,
    // manual_gross_weight?, reason? }. Invalid weight → field-level 422.
    setWeightOverride: (draftId, fields, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/weight-override`, {
        ...(fields || {}),
        expected_updated_at: updatedAt || '',
      }),

    // POST /api/v1/proforma/draft/{id}/clear-weight-override (X-Operator).
    // Clears the manual override, restoring the extracted packing weight.
    clearWeightOverride: (draftId, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/clear-weight-override`, {
        expected_updated_at: updatedAt || '',
      }),

    // POST /api/v1/proforma/draft/{id}/confirm-product-review (X-Operator).
    // Operator review-STATE authority: records the current authoritative review
    // decision for a mapped product_code (badge → "Operator confirmed"). Never
    // touches machine extraction evidence (extracted_confidence /
    // requires_manual_review) and never changes a mapping. Advisory (Lesson N) —
    // does not gate Approve/Post/Convert. expected_updated_at is optional OCC.
    confirmProductReview: (draftId, productCode, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${draftId}/confirm-product-review`, {
        product_code: productCode,
        expected_updated_at: updatedAt || '',
      }),


    // NOTE: suggestServiceCharges + applyServiceCharges are defined once, in the
    // Wave-3 block below (search "apply-service-charges"). The earlier duplicate
    // definitions that lived here were removed — duplicate object keys meant the
    // later ones silently won, which masked a contract regression.

    // ── Supplier Invoice OCR — extraction drafts + operator review ──────────

    // POST /api/v1/supplier-invoice-ocr/upload (multipart). No JSON headers —
    // the browser sets the multipart boundary. 422/503 bodies still carry a
    // draft_id (file + row are persisted even when extraction fails).
    uploadSupplierInvoice: async (file) => {
      const fd = new FormData();
      fd.append('file', file);
      try {
        const data = await _apiFetch(`${BASE}/supplier-invoice-ocr/upload`, {
          method: 'POST',
          body: fd,
        });
        return { ok: true, data };
      } catch (err) {
        return { ok: false, status: err.status || 0, error: err.message || String(err), type: err.type };
      }
    },

    // GET /api/v1/supplier-invoice-ocr/drafts?status=&limit=&offset=
    listSupplierInvoiceDrafts: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/supplier-invoice-ocr/drafts${qs}`);
    },

    // GET /api/v1/supplier-invoice-ocr/drafts/{draft_id}
    getSupplierInvoiceDraft: (draftId) =>
      _get(`${BASE}/supplier-invoice-ocr/drafts/${encodeURIComponent(draftId)}`),

    // POST /api/v1/supplier-invoice-ocr/drafts/{draft_id}/confirm
    // _post (NOT _postM): operator identity is derived SERVER-SIDE from the
    // session (require_role) — an X-Operator header would be ignored.
    confirmSupplierInvoiceDraft: (draftId, confirmedFields) =>
      _post(`${BASE}/supplier-invoice-ocr/drafts/${encodeURIComponent(draftId)}/confirm`, {
        confirmed_fields: confirmedFields,
      }),

    // POST /api/v1/supplier-invoice-ocr/drafts/{draft_id}/reject
    rejectSupplierInvoiceDraft: (draftId) =>
      _post(`${BASE}/supplier-invoice-ocr/drafts/${encodeURIComponent(draftId)}/reject`, {}),

    // ── Inventory: Sample Out register — Wave-3 U-1 ────────────────────────
    // GET /api/v1/inventory/samples?status=&recipient=&limit=
    // → { ok, count, samples: [{sample_id, scan_code, recipient_client_name,
    //     recipient_client_id, sample_reason, expected_return_date, out_operator,
    //     out_at, notes, return_event_id, returned_at, return_operator, status}] }
    // status filter: 'open' | 'returned' (omit for all)
    // Authority: routes_inventory_sample.py:149 (C-3b, Wave-2 backend LIVE)
    getInventorySamples: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/inventory/samples${qs}`);
    },

    // ── WF-2: Inventory Fiscal Reconciliation (READ-ONLY) ─────────────────
    // Dashboard operational stock vs wFirma fiscal quantity. No writes, no
    // auto-correction. Authority: routes_inventory.py fiscal-reconciliation.
    // GET /api/v1/inventory/fiscal-reconciliation?warehouse_id=&warehouse=&product=&severity=&difference_type=&search=
    // → { generated_at, fiscal_source, summary, differences[], warehouses[] }
    getFiscalReconciliation: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/inventory/fiscal-reconciliation${qs}`);
    },
    // POST /api/v1/inventory/fiscal-reconciliation/run?warehouse_id= — Run Now (records an audit run)
    runFiscalReconciliation: (warehouseId) => {
      const qs = warehouseId ? '?warehouse_id=' + encodeURIComponent(warehouseId) : '';
      return _call('POST', `${BASE}/inventory/fiscal-reconciliation/run${qs}`, {});
    },
    // GET /api/v1/inventory/fiscal-reconciliation/status — last recorded run
    getFiscalReconciliationStatus: () =>
      _get(`${BASE}/inventory/fiscal-reconciliation/status`),

    // POST /api/v1/inventory/pieces/{piece_id}/sample-out
    //   body: { operator, recipient_client_name, recipient_client_id?,
    //           expected_return_date, sample_reason, idempotency_key, notes? }
    // Moves piece WAREHOUSE_STOCK → SAMPLE_OUT. Idempotent on (scan_code, key).
    // Authority: routes_inventory_sample.py:91
    issueSampleOut: (pieceId, payload) => {
      const op = ((payload && payload.operator) || _resolveOperator() || '').trim();
      if (!op)
        return Promise.resolve({ ok: false, status: 0, type: 'operator',
          error: 'Operator name required — sample-out cancelled.' });
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/sample-out`,
        { ...payload, operator: op });
    },

    // ── Inventory: Sample Return — Wave-3 U-1 page 2 ──────────────────────
    // POST /api/v1/inventory/pieces/{piece_id}/sample-return
    //   body: { operator, idempotency_key, notes? }
    // Moves piece SAMPLE_OUT → WAREHOUSE_STOCK. Idempotent on (scan_code, key).
    // Authority: routes_inventory_sample.py:125 (LIVE)
    recordSampleReturn: (pieceId, payload) => {
      const op = ((payload && payload.operator) || _resolveOperator() || '').trim();
      if (!op)
        return Promise.resolve({ ok: false, status: 0, type: 'operator',
          error: 'Operator name required — sample-return cancelled.' });
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/sample-return`,
        { ...payload, operator: op });
    },

    // ── Inventory: Client Return register — Wave-3 U-2 page 3 ─────────────
    // GET /api/v1/inventory/returns?direction=from_client&status=&limit=
    // → { ok, count, returns: [{id, scan_code, direction, operator,
    //     source_holder_name, return_reason, received_at, notes,
    //     occurred_at, created_at, status}] }
    // direction fixed to from_client for this tab. status filter: 'recorded' (omit for all).
    // Authority: routes_inventory_returns.py:212 (C-3a/C-3c, Wave-2 backend LIVE)
    getInventoryReturns: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/inventory/returns${qs}`);
    },

    // POST /api/v1/inventory/pieces/{piece_id}/return-from-client
    //   body: { operator, return_reason, origin_context, received_at,
    //           idempotency_key, source_holder_name?, notes? }
    // Moves piece WAREHOUSE_STOCK|SAMPLE_OUT → RETURNED_FROM_CLIENT.
    // Idempotent on (scan_code, idempotency_key).
    // return_reason enum: warranty_claim | customer_refused |
    //   post_sample_review_reject | dimension_issue |
    //   quality_complaint | wrong_item_shipped | other
    // Authority: routes_inventory_returns.py:116 (C-3a, LIVE)
    recordClientReturn: (pieceId, payload) => {
      const op = ((payload && payload.operator) || _resolveOperator() || '').trim();
      if (!op)
        return Promise.resolve({ ok: false, status: 0, type: 'operator',
          error: 'Operator name required — client-return cancelled.' });
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/return-from-client`,
        { ...payload, operator: op });
    },

    // ── Inventory: Return to Producer register — Wave-3 U-2 page 4 ───────────
    // GET /api/v1/inventory/returns?direction=to_producer&status=&limit=
    // → { ok, count, returns: [{id, scan_code, direction, operator,
    //     producer_name, producer_id, return_reason, dispatch_reference,
    //     expected_resolution_date, notes, occurred_at, created_at,
    //     resolution_event_id, resolved_at, status}] }
    // status filter: 'open' (awaiting/in-transit) | 'resolved' (confirmed) (omit=all)
    // Authority: routes_inventory_returns.py:212 (C-3c, Wave-2 backend LIVE)
    getProducerReturns: (params) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return _get(`${BASE}/inventory/returns${qs}`);
    },

    // POST /api/v1/inventory/pieces/{piece_id}/return-to-producer
    //   body: { operator, producer_name, idempotency_key,
    //           return_reason?, dispatch_reference?, producer_id?,
    //           expected_resolution_date?, notes? }
    // Moves piece WAREHOUSE_STOCK | RETURNED_FROM_CLIENT → RETURNED_TO_PRODUCER.
    // Idempotent on (scan_code, idempotency_key).
    // return_reason enum: defect | dimension_out_of_spec | quality_reject |
    //   post_inspection_reject | recall | other
    // Authority: routes_inventory_returns.py:148 (LIVE)
    returnToProducer: (pieceId, payload) => {
      const op = ((payload && payload.operator) || _resolveOperator() || '').trim();
      if (!op)
        return Promise.resolve({ ok: false, status: 0, type: 'operator',
          error: 'Operator name required — return-to-producer cancelled.' });
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/return-to-producer`,
        { ...payload, operator: op });
    },

    // POST /api/v1/inventory/pieces/{piece_id}/return-from-producer
    //   body: { operator, idempotency_key, notes? }
    // Restock leg: RETURNED_TO_PRODUCER → WAREHOUSE_STOCK.
    // Idempotent on (scan_code, idempotency_key).
    // Authority: routes_inventory_returns.py:181 (LIVE)
    returnFromProducer: (pieceId, payload) => {
      const op = ((payload && payload.operator) || _resolveOperator() || '').trim();
      if (!op)
        return Promise.resolve({ ok: false, status: 0, type: 'operator',
          error: 'Operator name required — return-from-producer cancelled.' });
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/return-from-producer`,
        { ...payload, operator: op });
    },

    // POST /api/v1/inventory/pieces/{piece_id}/qc-disposition
    //   body: { decision, condition?, inspector?, notes?, producer_name?,
    //           dispatch_reference?, idempotency_key }
    // Returns QC Disposition — decision drives the lifecycle transition:
    //   restock → WAREHOUSE_STOCK · repair → RETURNED_TO_PRODUCER ·
    //   write_off → WRITTEN_OFF. Only legal from RETURNED_FROM_CLIENT.
    // NOTE: operator is DERIVED FROM THE SESSION server-side — never sent from
    // the client (privileged, role-gated route). Idempotent on (piece, key).
    // Authority: routes_inventory_returns.py qc-disposition (LIVE)
    qcDisposition: (pieceId, payload) => {
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/qc-disposition`,
        { ...payload });
    },

    // GET /api/v1/inventory/pieces/{piece_id}/qc-dispositions
    // → { piece_id, dispositions: [{ condition, inspector, decision, notes,
    //     producer_name, dispatch_reference, operator, disposed_at, ... }] }
    // Read-only QC history (newest first). Authority: routes_inventory_returns.py (LIVE)
    getQcDispositions: (pieceId) => {
      return _call('GET',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/qc-dispositions`);
    },

    // ── Inventory Correction — Engineering OS Package A + D-identity ──────
    // POST /api/v1/inventory/pieces/{piece_id}/correction/identity
    //   body: { reason, idempotency_key, product_code?, design_no?, batch_id? }
    // Fixes blank/wrong product_code, design_no, or batch_id on an existing
    // piece. Does NOT change lifecycle state. NOTE: operator is DERIVED FROM
    // THE SESSION server-side — never sent from the client (privileged,
    // role-gated route). Idempotent on (piece, key).
    // Authority: routes_inventory_returns.py correction/identity (LIVE)
    correctIdentity: (pieceId, payload) => {
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/correction/identity`,
        { ...payload });
    },

    // POST /api/v1/inventory/pieces/{piece_id}/correction/archive-proposal
    //   body: { reason, idempotency_key }
    // Records an archive PROPOSAL for an over-scan / duplicate piece. Never
    // mutates inventory_state and never physically deletes audit history —
    // a supervisor reviews the proposal out-of-band. Idempotent on (piece, key).
    // Authority: routes_inventory_returns.py correction/archive-proposal (LIVE)
    proposeArchive: (pieceId, payload) => {
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/correction/archive-proposal`,
        { ...payload });
    },

    // GET /api/v1/inventory/pieces/{piece_id}/corrections
    // → { piece_id, corrections: [{ correction_type, old_product_code,
    //     new_product_code, old_design_no, new_design_no, old_batch_id,
    //     new_batch_id, reason, operator, status, created_at, ... }] }
    // Read-only correction audit history (newest first).
    // Authority: routes_inventory_returns.py (LIVE)
    getCorrections: (pieceId) => {
      return _call('GET',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/corrections`);
    },

    reverseToStock: (pieceId, reversalTarget, payload) => {
      return _call('POST',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/reversal/${encodeURIComponent(reversalTarget)}`,
        payload);
    },

    getReversals: (pieceId) => {
      return _call('GET',
        `${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}/reversals`);
    },

    getInventoryPieceState: (pieceId) => {
      return _get(`${BASE}/inventory/pieces/${encodeURIComponent(pieceId)}`);
    },

    // ── Inventory: Temp Sale register — Wave-3 U-3 page 5 ─────────────────
    // GET /api/v1/inventory/state/{batch_id}
    // → { ok:true, batch_id, as_of, counts:{state: int}, pieces:[{scan_code,
    //     state, product_code, design_no, updated_at}], total, source, degraded? }
    // Callers filter pieces to state==='SALES_TRANSIT'.
    // Authority: routes_inventory.py:74 (GET /api/v1/inventory/state/{batch_id}, LIVE)
    // Cross-batch aggregate: NO endpoint exists — tab uses per-batch picker.
    // Lesson-M note (IV-TS-1): cross-batch SALES_TRANSIT aggregate not backed
    // by any live endpoint; per-batch read is the only available authority.
    getInventoryBatchState: (batchId) =>
      _get(`${BASE}/inventory/state/${encodeURIComponent(batchId)}`),

    // GET /api/v1/inventory/movements/{batch_id}
    // → { ok:true, batch_id, count, events:[{id, scan_code, from_state,
    //     to_state, trigger, occurred_at, operator, note}], document_trails }
    // Used by TempSaleTab to extract client_name from the invoice_issued
    // transition note field ("invoice issue: {client_name}").
    // Authority: routes_inventory.py:203 (C-3f, LIVE)
    getInventoryMovements: (batchId, limit) => {
      const qs = limit ? `?limit=${encodeURIComponent(limit)}` : '';
      return _get(`${BASE}/inventory/movements/${encodeURIComponent(batchId)}${qs}`);
    },

    // ── Inventory: Temp Purchase merchandising register — Wave-3 U-3 page 7 ──
    // GET /api/v1/inventory/merchandising/{batch_id}
    // → { ok:true, batch_id, count, rows:[{
    //     scan_code, product_code, design_no, batch_no,
    //     pack_sr, ctg, client_po,
    //     karat, color, quality, dia_wt, size, qty, uom,
    //     gross_weight, net_weight, state }] }
    //
    // C-3e joined read (packing_lines ⋈ inventory_state per piece):
    //   - pack_sr/ctg/client_po/design/karat/color/quality/dia_wt/qty from packing_lines
    //   - state from inventory_state (current engine state of each scan_code)
    // Client-side: filter rows where state === 'PURCHASE_TRANSIT' for Temp Purchase tab.
    // Honest empty: unknown batch_id → rows=[] (HTTP 200).
    // Authority: routes_inventory.py:127 (C-3e, LIVE)
    // Cross-batch aggregate: NO endpoint exists — tab uses per-batch picker.
    getMerchandisingView: (batchId) =>
      _get(`${BASE}/inventory/merchandising/${encodeURIComponent(batchId)}`),

    // ── Inventory: Final Stock location view — Wave-3 page 9 ─────────────────
    // Authority: R-Q4 (DECISIONS.md 2026-07-04): "Final Stock = location/bag-assigned
    // inventory. Temp Warehouse = received but not yet assigned."
    //
    // Strategy: load all warehouse locations, then per-location inventory filtered
    // to a given batch. Returns a flat list of items that have a non-empty
    // current_location — these are the Final Stock pieces for the batch.
    //
    // Two sequential calls:
    //   1. GET /api/v1/warehouse/locations  → location list
    //   2. GET /api/v1/warehouse/locations/{code}/inventory  → per location (parallel)
    //      filter client-side to items.batch_id === batchId
    //
    // Returns: { ok, items: [{scan_code, product_code, design_no, bag_id,
    //   current_location, batch_id, current_status, updated_at}], locationCount }
    //
    // The shared disjoint predicate (exported for TempWarehouseTab amendment):
    //   isLocationAssigned(item) ← item.current_location is non-empty
    //
    // Cross-tab disjoint guarantee: FinalStockTab = isLocationAssigned(item) for
    // WAREHOUSE_STOCK pieces; TempWarehouseTab amendment = !isLocationAssigned(scan_code)
    // for WAREHOUSE_STOCK rows. Shared predicate: PzApi.isLocationAssigned.
    //
    // Honest empty: unknown batch → items=[] (HTTP 200 from both endpoints).
    // No new backend route — reuses existing getWarehouseLocations +
    //   getLocationInventory (pz-api.js:402/408, routes_warehouse.py:184/190).
    isLocationAssigned: (item) => !!(item && item.current_location && item.current_location.trim() !== ''),

    getWarehouseLocationInventory: async (batchId) => {
      // Step 1: load all active locations
      const locRes = await _get(`${BASE}/warehouse/locations`);
      if (!locRes.ok) return locRes;
      const locs = (locRes.data && locRes.data.locations) || [];
      if (locs.length === 0) return { ok: true, status: 200, data: { items: [], locationCount: 0 } };

      // Step 2: load inventory for each location in parallel, filter to batch
      const perLoc = await Promise.all(
        locs.map(loc =>
          _get(`${BASE}/warehouse/locations/${String(loc.location_code).split('/').map(encodeURIComponent).join('/')}/inventory`)
        )
      );

      const items = [];
      perLoc.forEach((res, idx) => {
        if (!res.ok) return;
        const locItems = (res.data && res.data.items) || [];
        locItems.forEach(it => {
          // Filter to the requested batch; include only assigned (non-empty location) rows
          if (it.batch_id === batchId && it.current_location && it.current_location.trim() !== '') {
            items.push(it);
          }
        });
      });

      return { ok: true, status: 200, data: { items, locationCount: locs.length } };
    },

    // ── Wave-3 Documents Hub transport additions ─────────────────────────────
    // These are transport-only wrappers for EXISTING endpoints.
    // All endpoints were live before this wave; these wrappers were absent from
    // pz-api.js. Added after getWarehouseLocationInventory per the build brief.
    // No new backend routes — EXISTING authorities only (DECISIONS.md constraint).

    // GET /api/v1/dashboard/batches/{batch_id}/files
    // Returns file availability for a batch folder: pz_pdf, xlsx, sad, sources…
    // Authority: routes_dashboard.py:558 (GET /batches/{batch_id}/files)
    // Used by: Documents Hub OtherDocs tab, PZ kanban Download button
    getBatchFiles: (batchId) =>
      _get(`${BASE}/dashboard/batches/${encodeURIComponent(batchId)}/files`),

    // ── Wave-3 Accounting Hub transport additions ─────────────────────────────
    // Transport-only wrappers for EXISTING endpoints.
    // No new backend routes — EXISTING authorities only (DECISIONS.md constraint).

    // GET /api/v1/wfirma/contractors/scan/status
    // Contractor sync status: healthy, running, last_started_at,
    // last_completed_at, duration_ms, processed, created, updated, skipped,
    // errors, last_error.
    // Authority: routes_wfirma_contractors.py:117
    // Used by: Accounting Hub wFirma Sync tab
    getWfirmaContractorScanStatus: () =>
      _get(`${BASE}/wfirma/contractors/scan/status`),

    // ── Wave-3 Shipment Detail transport additions ────────────────────────────
    // Transport-only wrappers for EXISTING endpoints.
    // No new backend routes — EXISTING authorities only (DECISIONS.md constraint).

    // GET /api/v1/tracking/shipment/{batch_id}/timeline
    // Full shipment timeline: chronological audit events with timestamps.
    // Authority: routes_tracking.py (get_shipment_timeline)
    // Used by: shipment-detail-page.jsx TimelineTab (SD-7 gap closure)
    getShipmentTimeline: (batchId) =>
      _get(`${BASE}/tracking/shipment/${encodeURIComponent(batchId)}/timeline`),

    // ── Wave-3 Dashboard transport additions ─────────────────────────────────
    // Transport-only wrappers for EXISTING endpoints.
    // No new backend routes — EXISTING authorities only (DECISIONS.md constraint).

    // GET /api/v1/webhooks/wfirma/status
    // wFirma sync scheduler heartbeat: scheduler_running, last_tick_at,
    // last_completed_at, next_tick_at, queue state, snapshot totals.
    // Authority: routes_webhooks_wfirma_status.py
    // Used by: wireframe-update.jsx OperationalStatusStrip (D-5 gap closure)
    getWfirmaWebhookStatus: () =>
      _get(`${BASE}/webhooks/wfirma/status`),

    // GET /api/v1/deploy/status
    // Deployment health: live SHA, deployed_at, GATE 2 state, verification results.
    // Authority: routes_deploy_status.py
    // Used by: wireframe-update.jsx OperationalStatusStrip (D-5 gap closure)
    getDeployStatus: () =>
      _get(`${BASE}/deploy/status`),

    // ── Wave-3 Proforma List + Detail transport additions ─────────────────────
    // Transport-only wrappers for EXISTING endpoints.
    // No new backend routes — EXISTING authorities only (DECISIONS.md constraint).

    // GET /api/v1/proforma/pipeline/{batch_id}
    // Batch-level pipeline state: aggregated draft lifecycle, reservation stats,
    // pipeline_stage label, and per-state counts.
    // Authority: routes_proforma.py (get_batch_pipeline)
    // Used by: proforma-list.jsx PipelineKpiStrip (PL-1 gap closure)
    getProformaPipeline: (batchId) =>
      _get(`${BASE}/proforma/pipeline/${encodeURIComponent(batchId)}`),

    // GET /api/v1/proforma/search
    // Cross-batch proforma search.
    // Auth params: client_name, batch_id, draft_state, currency, date_from,
    //              date_to, page, page_size.
    // Authority: routes_proforma.py (search_proforma_drafts)
    // Used by: proforma-list.jsx cross-batch search (PL-2 gap closure)
    searchProformaDrafts: (params) =>
      _get(`${BASE}/proforma/search${params ? '?' + new URLSearchParams(params).toString() : ''}`),

    // GET /api/v1/proforma/draft/{draft_id}/events
    // Audit event trail for a draft: array of {event_type, created_at, detail}.
    // Authority: routes_proforma.py (get_draft_events)
    // Used by: proforma-detail.jsx ProformaHistoryTab (PD-5 gap closure)
    getDraftEvents: (draftId) =>
      _get(`${BASE}/proforma/draft/${encodeURIComponent(draftId)}/events`),

    // GET /api/v1/proforma/draft/{draft_id}/suggest-service-charges
    // Combined freight + insurance suggestion from Customer Master.
    // Authority: routes_proforma.py (suggest_service_charges)
    // Used by: proforma-detail.jsx ServiceChargesPanel (PL-5 gap closure)
    suggestServiceCharges: (draftId) =>
      _get(`${BASE}/proforma/draft/${encodeURIComponent(draftId)}/suggest-service-charges`),

    // POST /api/v1/proforma/draft/{draft_id}/apply-service-charges
    // Apply Customer Master freight/insurance as service charges.
    // Authority: routes_proforma.py (apply_service_charges) — requires an
    // object body {expected_updated_at, apply:[...]} AND the X-Operator header
    // (_require_operator). Caller (proforma-detail.jsx:4152) invokes this as
    // applyServiceCharges(id, [type], updatedAt). An earlier Wave-3 override
    // used (draftId, body)+_post, which posted a bare array with no operator
    // header and no expected_updated_at → 400. This restores the correct
    // 3-arg mutation contract (_postM injects X-Operator).
    applyServiceCharges: (draftId, applyList, updatedAt) =>
      _postM(`${BASE}/proforma/draft/${encodeURIComponent(draftId)}/apply-service-charges`, {
        expected_updated_at: updatedAt || '',
        apply: applyList || [],
      }),

    // PUT /api/v1/proforma/service-products/{charge_type}
    // Register a wFirma product for a service charge type.
    // Authority: routes_proforma.py (put_service_product)
    // Used by: proforma-detail.jsx ServiceProductRegistryPanel (PL-5 gap closure)
    putServiceProduct: (chargeType, body) =>
      _put(`${BASE}/proforma/service-products/${encodeURIComponent(chargeType)}`, body),

    // ── Wave 3: Shipment Detail — SAD/ZC429 + canonical document manifest ────
    // All routes are the EXISTING backend document authority (routes_upload.py,
    // routes_dashboard.py, routes_dhl_clearance.py) — no new endpoints.

    // GET /api/v1/upload/shipment/{batch_id}/documents
    // Canonical document manifest. Each row carries the identity contract:
    // document_id, document_type, authority, is_generated, is_current,
    // original_filename, mime_type, can_view/can_download/can_replace/can_delete,
    // view_url, download_url. Never leaks file_path.
    getShipmentDocuments: (batchId) =>
      _get(`${BASE}/upload/shipment/${encodeURIComponent(batchId)}/documents`),

    // Direct browser URLs (NOT JSON-wrapped — used for window.open / <a href>).
    // The manifest already returns view_url/download_url; these construct the
    // same canonical registry-keyed content URL for callers that only hold ids.
    viewDocument: (batchId, documentId) =>
      `${BASE}/upload/shipment/${encodeURIComponent(batchId)}/documents/${encodeURIComponent(documentId)}/content?disposition=inline`,
    downloadDocument: (batchId, documentId) =>
      `${BASE}/upload/shipment/${encodeURIComponent(batchId)}/documents/${encodeURIComponent(documentId)}/content?disposition=attachment`,

    // POST /api/v1/upload/shipment/{batch_id}/sad (multipart). Add/replace SAD.
    // No JSON headers — the browser sets the multipart boundary. No X-Operator:
    // the SAD upload route is api-key/session authed and derives its actor from
    // the session (unlike replaceDocument, which needs explicit X-Operator for
    // the supersede audit event). Returns { ok, data } or { ok:false, status }.
    uploadSad: async (batchId, file) => {
      const fd = new FormData();
      fd.append('sad', file);
      try {
        const data = await _apiFetch(`${BASE}/upload/shipment/${encodeURIComponent(batchId)}/sad`, { method: 'POST', body: fd });
        return { ok: true, data };
      } catch (err) {
        return { ok: false, status: err.status || 0, error: err.message || String(err), type: err.type };
      }
    },

    // POST /dashboard/batches/{batch_id}/recheck  body { mode: 'sad' }
    // Parse/verify the SAD (role-gated: admin/logistics/accounts). _postM injects
    // X-Operator for audit attribution.
    recheckSad: (batchId) =>
      _postM(`/dashboard/batches/${encodeURIComponent(batchId)}/recheck`, { mode: 'sad' }),

    // DELETE /api/v1/upload/shipment/{batch_id}/documents/{document_id}
    // Canonical delete-by-id. Sends X-Operator (audit) + X-Confirm-Delete:true
    // (backend confirmation gate, in addition to the UI confirm dialog). Backend
    // 409s for generated fiscal / customs (non-deletable), 428 without confirm.
    deleteDocument: async (batchId, documentId) => {
      const op = _resolveOperator();
      const headers = { 'X-Confirm-Delete': 'true' };
      if (op) headers['X-Operator'] = op;
      try {
        const data = await _apiFetch(
          `${BASE}/upload/shipment/${encodeURIComponent(batchId)}/documents/${encodeURIComponent(documentId)}`,
          { method: 'DELETE', headers });
        return { ok: true, data };
      } catch (err) {
        return { ok: false, status: err.status || 0, error: err.message || String(err), type: err.type };
      }
    },

    // POST /api/v1/upload/shipment/{batch_id}/documents/{document_id}/replace
    // (multipart). Audited supersede — old row is_current=0. X-Operator header
    // for attribution. Extension must match the original.
    replaceDocument: async (batchId, documentId, file) => {
      const fd = new FormData();
      fd.append('file', file);
      const op = _resolveOperator();
      try {
        const data = await _apiFetch(
          `${BASE}/upload/shipment/${encodeURIComponent(batchId)}/documents/${encodeURIComponent(documentId)}/replace`,
          { method: 'POST', body: fd, headers: op ? { 'X-Operator': op } : {} });
        return { ok: true, data };
      } catch (err) {
        return { ok: false, status: err.status || 0, error: err.message || String(err), type: err.type };
      }
    },

    // GET /api/v1/dhl/clearance-status/{batch_id} — read-only DHL clearance
    // status (correspondence WRITE actions stay on the standalone DHL Console).
    getDhlClearanceStatus: (batchId) =>
      _get(`${BASE}/dhl/clearance-status/${encodeURIComponent(batchId)}`),

  });
})();
