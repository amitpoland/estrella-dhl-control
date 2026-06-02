// pz-state.js — React data hooks for V2 pages.
//
// Exposes window.PzState. No global shared state.
//
// Loaded by V2 pages as:
//   <script type="text/babel" data-presets="env,react" src="/dashboard/pz-state.js"></script>
// MUST load AFTER pz-api.js (uses window.PzApi).
//
// Layer rules (see docs/v2-architecture-plan.md §4):
//   ALLOWED:  normalize API responses, cache, derive UI-friendly structure,
//             coordinate view state (loading/error/reload per component)
//   FORBIDDEN: silently decide workflow legality, redefine accounting readiness,
//              reinterpret customs truth, bypass backend authority, global singletons
//
// Each hook returns independent per-component state. No shared state between hooks.

(function () {
  'use strict';

  const { useState, useEffect, useCallback, useRef } = React;

  // ── Generic async-fetch hook ──────────────────────────────────────────────
  // Returns { data, loading, error, errorType, reload }
  // fetcher: () => Promise<{ ok, data?, error?, type? }>
  // deps: dependency array for re-fetching
  function _useApiCall(fetcher, deps) {
    const [state, setState] = useState({ data: null, loading: true, error: null, errorType: null });
    const mountedRef = useRef(true);
    // Keep latest fetcher without re-triggering effect
    const fetcherRef = useRef(fetcher);
    fetcherRef.current = fetcher;

    const run = useCallback(async () => {
      setState(s => ({ ...s, loading: true, error: null, errorType: null }));
      const res = await fetcherRef.current();
      if (!mountedRef.current) return;
      if (res.ok) {
        setState({ data: res.data, loading: false, error: null, errorType: null });
      } else {
        setState({ data: null, loading: false, error: res.error || 'Request failed', errorType: res.type || null });
      }
    // deps drives re-fetch; eslint-disable is intentional here
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, deps);

    useEffect(() => {
      mountedRef.current = true;
      run();
      return () => { mountedRef.current = false; };
    }, [run]);

    return { ...state, reload: run };
  }

  // ── useProformaDrafts ─────────────────────────────────────────────────────
  // Fetches the draft list for a batch.
  // Returns { data: { drafts[], count }, loading, error, reload }
  function useProformaDrafts(batchId) {
    return _useApiCall(
      () => batchId
        ? window.PzApi.getProformaDrafts(batchId)
        : Promise.resolve({ ok: true, data: { drafts: [], count: 0 } }),
      [batchId],
    );
  }

  // ── useProformaPreview ────────────────────────────────────────────────────
  // Fetches the readiness preview for a batch + client.
  // Returns { data: previewObj, loading, error, reload }
  //
  // CRITICAL INVARIANT: data.ready comes from the backend.
  // This hook NEVER computes ready locally. Do not add logic here that
  // re-derives ready from blocking_reasons — that would violate the authority boundary.
  function useProformaPreview(batchId, clientName) {
    return _useApiCall(
      () => (batchId && clientName)
        ? window.PzApi.previewProforma(batchId, clientName)
        : Promise.resolve({ ok: true, data: null }),
      [batchId, clientName],
    );
  }

  // ── useDraft ──────────────────────────────────────────────────────────────
  // Fetches the full editable draft payload.
  // Returns { data: { draft: draftObj }, loading, error, reload }
  function useDraft(draftId) {
    return _useApiCall(
      () => (draftId != null && draftId !== '')
        ? window.PzApi.getDraft(draftId)
        : Promise.resolve({ ok: true, data: null }),
      [draftId],
    );
  }

  // ── useCustomerMaster ─────────────────────────────────────────────────────
  // Fetches a customer master record with a save action.
  // Returns { data: record, loading, error, reload, save, saving }
  function useCustomerMaster(clientKey) {
    const [saving, setSaving] = useState(false);
    const base = _useApiCall(
      () => clientKey
        ? window.PzApi.getCustomerMaster(clientKey)
        : Promise.resolve({ ok: true, data: null }),
      [clientKey],
    );

    const save = useCallback(async (body) => {
      setSaving(true);
      const res = await window.PzApi.saveCustomerMaster(clientKey, body);
      setSaving(false);
      if (res.ok) base.reload();
      return res;
    }, [clientKey]); // eslint-disable-line react-hooks/exhaustive-deps

    return { ...base, save, saving };
  }

  // ── useCustomerList ───────────────────────────────────────────────────────
  // Fetches the customer list with optional filters.
  // params: { country?, risk_status?, active?, limit? }
  // Returns { data: { count, customers }, loading, error, reload }
  function useCustomerList(params) {
    const key = JSON.stringify(params || {});
    return _useApiCall(
      () => window.PzApi.listCustomerMaster(params || {}),
      [key],
    );
  }

  // ── Export ────────────────────────────────────────────────────────────────
  window.PzState = Object.freeze({
    useProformaDrafts,
    useProformaPreview,
    useDraft,
    useCustomerMaster,
    useCustomerList,
  });
})();
