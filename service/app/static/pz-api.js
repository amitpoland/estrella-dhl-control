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

  // ── PZ Correction wFirma confirmation sentinel ────────────────────────────
  // Must match _CONFIRM_SENTINEL in service/app/services/global_pz_push.py
  // (lines 76-79) byte-for-byte. Backend Gate 1 enforces exact-match at
  // line 348 of global_pz_push.py.
  //
  // SYNTHESISE-ONLY constant. Never render this string as visible DOM text;
  // it ships in the POST body of correction-commit and nowhere else.
  // Operator-language gate G3 source-greps JSX text nodes to catch
  // accidental rendering.
  const _CONFIRM_SENTINEL =
    "I confirm this will create a new wFirma PZ document and cannot be undone " +
    "without manual wFirma intervention";

  // ── buildCommitIdempotencyKey ─────────────────────────────────────────────
  // Stable 32-hex key per (batch_id, staged_option_id, decision_ts) tuple.
  //
  // Server Gate 6 (global_pz_push.py, per routes_pz.py:945) enforces
  // (idempotency_key, option_id) must not match an existing push record.
  // This client key is defense-in-depth: a double-click during slow
  // network would otherwise send two distinct keys and produce two
  // attempted pushes — Gate 6 catches them, but the second one wastes a
  // round-trip and surfaces a 409 to the operator. A stable key avoids
  // even that.
  //
  // Uses Web Crypto SHA-256; falls back to a deterministic 32-hex hash
  // when crypto.subtle is unavailable (very old browsers / non-HTTPS dev).
  async function buildCommitIdempotencyKey(batchId, stagedOptionId, decisionTs) {
    const payload = `${batchId || ''}|${stagedOptionId || ''}|${decisionTs || ''}`;
    if (window.crypto && window.crypto.subtle && window.TextEncoder) {
      try {
        const buf = new TextEncoder().encode(payload);
        const hashBuf = await window.crypto.subtle.digest('SHA-256', buf);
        const hex = Array.from(new Uint8Array(hashBuf))
          .map(b => b.toString(16).padStart(2, '0'))
          .join('');
        return hex.slice(0, 32);
      } catch (_) { /* fall through to fallback */ }
    }
    // Fallback: deterministic FNV-1a 64-bit expanded to 32 hex chars.
    // Not cryptographic, but stable across (batch_id, option_id, ts).
    let h1 = 0xcbf29ce4, h2 = 0x84222325;
    for (let i = 0; i < payload.length; i++) {
      const c = payload.charCodeAt(i);
      h1 ^= c; h1 = (h1 * 16777619) >>> 0;
      h2 ^= (c << 1); h2 = (h2 * 16777619) >>> 0;
    }
    const part = (n) => n.toString(16).padStart(8, '0');
    return (part(h1) + part(h2) + part(h1 ^ h2) + part(~h1 >>> 0)).slice(0, 32);
  }

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

    // ── PZ Correction — read ─────────────────────────────────────────
    // 8 endpoints under /api/v1/pz/lineage/{batch_id}/correction-*
    // Backend authority: service/app/api/routes_pz.py lines 739–1346.
    // Frontend never decides legality or write-permission; it reads
    // backend responses and maps to operator-friendly UX phases via
    // PzState.correctionUiPhase().

    // GET /api/v1/pz/lineage/{batch_id}/correction-proposal
    // Returns CorrectionProposal as dict. is_global_supplier=false when not Global.
    getCorrectionProposal: (batchId) =>
      _get(`${BASE}/pz/lineage/${encodeURIComponent(batchId)}/correction-proposal`),

    // GET /api/v1/pz/lineage/{batch_id}/correction-state
    // Returns CorrectionLifecycleRecord as dict.
    // 503 when pz_correction_lifecycle_enabled=false — V2 maps to 'not-enabled' UX.
    // 403 for non-Global batches.
    getCorrectionState: (batchId) =>
      _get(`${BASE}/pz/lineage/${encodeURIComponent(batchId)}/correction-state`),

    // ── PZ Correction — write ────────────────────────────────────────

    // POST /api/v1/pz/lineage/{batch_id}/correction-execute
    // Legacy execute path (pre-lifecycle); included for completeness.
    postCorrectionExecute: (batchId, body) =>
      _postM(`${BASE}/pz/lineage/${encodeURIComponent(batchId)}/correction-execute`, body || {}),

    // POST /api/v1/pz/lineage/{batch_id}/correction-push-wfirma
    // Legacy push path; included for completeness.
    postCorrectionPushWfirma: (batchId, body) =>
      _postM(`${BASE}/pz/lineage/${encodeURIComponent(batchId)}/correction-push-wfirma`, body || {}),

    // POST /api/v1/pz/lineage/{batch_id}/correction-stage
    // Stages a correction option locally. No wFirma write.
    // Body: { option_id, operator_reason }
    // Returns updated lifecycle record.
    postCorrectionStage: (batchId, body) =>
      _postM(`${BASE}/pz/lineage/${encodeURIComponent(batchId)}/correction-stage`, body),

    // DELETE /api/v1/pz/lineage/{batch_id}/correction-stage
    // Resets STAGED → OPERATOR_REVIEWED so operator can choose different option.
    deleteCorrectionStage: (batchId) =>
      _del(`${BASE}/pz/lineage/${encodeURIComponent(batchId)}/correction-stage`),

    // POST /api/v1/pz/lineage/{batch_id}/correction-commit
    // FINAL wFirma push. Server enforces:
    //  Gate 1: confirm_understanding === _CONFIRM_SENTINEL (exact match)
    //  Gate 6: idempotency_key + option_id has no prior push record
    // 503 when wfirma_correction_push_allowed=false — V2 surfaces this as
    // 'push-disabled' UX (amber, not red).
    // Body: { operator_reason, idempotency_key, confirm_understanding }
    postCorrectionCommit: (batchId, body) =>
      _postM(`${BASE}/pz/lineage/${encodeURIComponent(batchId)}/correction-commit`, body),

    // POST /api/v1/pz/lineage/{batch_id}/correction-suppress
    // Closes the workflow into TERMINAL_SUPPRESSED. No wFirma write.
    // Body: { reason }
    postCorrectionSuppress: (batchId, body) =>
      _postM(`${BASE}/pz/lineage/${encodeURIComponent(batchId)}/correction-suppress`, body),

    // ── Exposed primitives for tests / advanced callers ──────────────
    _CONFIRM_SENTINEL,
    buildCommitIdempotencyKey,
  });
})();
