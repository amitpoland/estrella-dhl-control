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

  // ── PZ Correction lifecycle → operator UI phase ───────────────────────────
  //
  // SOLE AUTHORITY for lifecycle-state-to-operator-phase mapping.
  // No other module is permitted to read lcState.state to choose presentation
  // (test_single_renderer_authority.py enforces this with source-grep).
  //
  // This function does NOT decide legality. Legality is owned by
  // service/app/services/pz_correction_state.py VALID_TRANSITIONS.
  // This function chooses what operator-facing phase to render.
  //
  // Inputs (all backend-sourced — frontend never invents):
  //   proposal:               GET /correction-proposal response  | null
  //   lcState:                GET /correction-state response     | null
  //   lifecycleEnabled:       true / false / null (== unknown)
  //   pushDisabledDetected:   true after the backend has returned 503 on a
  //                           commit attempt for the current decision; null
  //                           or false otherwise. Defense-in-depth: if the
  //                           backend rejects the push, V2 stays in
  //                           push-disabled UX rather than re-offering the
  //                           commit button.
  //
  // Output: one of:
  //   'not-enabled' | 'review' | 'accepted' | 'push-enabled' | 'push-disabled'
  //   | 'working' | 'done' | 'needs-attention' | 'closed' | null
  function correctionUiPhase({ proposal, lcState, lifecycleEnabled, pushDisabledDetected }) {
    if (lifecycleEnabled === false) return 'not-enabled';
    if (!proposal) return null;
    if (!proposal.is_global_supplier) return null;
    if (!lcState) return 'review';
    const s = lcState.state;
    if (s === 'PROPOSED')            return 'review';
    if (s === 'OPERATOR_REVIEWED')   return 'accepted';
    if (s === 'STAGED')              return pushDisabledDetected ? 'push-disabled' : 'push-enabled';
    if (s === 'EXECUTING')           return 'working';
    if (s === 'COMPLETED')           return 'done';
    if (s === 'FAILED')              return 'needs-attention';
    if (s === 'TERMINAL_SUPPRESSED') return 'closed';
    return 'review';
  }

  // ── useCorrectionData ─────────────────────────────────────────────────────
  // Parallel-fetches /correction-proposal and /correction-state for a batch.
  // Detects lifecycleEnabled by inspecting the state response status:
  //   200 → lifecycleEnabled = true, lcState = response
  //   503 → lifecycleEnabled = false, lcState = null
  //   403 → lifecycleEnabled = null (non-Global; proposal returns is_global_supplier=false)
  //   404 / network → lifecycleEnabled = null, error surfaced
  //
  // Returns { proposal, lcState, lifecycleEnabled, loading, error, reload }
  function useCorrectionData(batchId) {
    const [data, setData] = useState({
      proposal: null,
      lcState: null,
      lifecycleEnabled: null,
      loading: true,
      error: null,
    });
    const mountedRef = useRef(true);

    const run = useCallback(async () => {
      if (!batchId) {
        setData({ proposal: null, lcState: null, lifecycleEnabled: null, loading: false, error: null });
        return;
      }
      setData(d => ({ ...d, loading: true, error: null }));
      const [propRes, stateRes] = await Promise.all([
        window.PzApi.getCorrectionProposal(batchId),
        window.PzApi.getCorrectionState(batchId),
      ]);
      if (!mountedRef.current) return;
      let lifecycleEnabled = null;
      let lcState = null;
      if (stateRes.ok) {
        lifecycleEnabled = true;
        lcState = stateRes.data;
      } else if (stateRes.status === 503) {
        lifecycleEnabled = false;
      } else if (stateRes.status === 403) {
        lifecycleEnabled = null;
      } else {
        lifecycleEnabled = null;
      }
      const proposal = propRes.ok ? propRes.data : null;
      const error = (!propRes.ok && propRes.status !== 404) ? (propRes.error || 'load failed') : null;
      setData({ proposal, lcState, lifecycleEnabled, loading: false, error });
    }, [batchId]);

    useEffect(() => {
      mountedRef.current = true;
      run();
      return () => { mountedRef.current = false; };
    }, [run]);

    return { ...data, reload: run };
  }

  // ── Export ────────────────────────────────────────────────────────────────
  window.PzState = Object.freeze({
    useProformaDrafts,
    useProformaPreview,
    useDraft,
    useCustomerMaster,
    correctionUiPhase,
    useCorrectionData,
  });
})();
