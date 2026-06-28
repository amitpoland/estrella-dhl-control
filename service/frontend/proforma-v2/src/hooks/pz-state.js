// pz-state.js — React data hooks for Proforma V2 React.
// ES module port of service/app/static/v2/pz-state.js.
// No window.PzState. No window.PzApi. Same hook contracts.

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getProformaDrafts,
  previewProforma,
  getDraft,
  getCustomerMaster,
  saveCustomerMaster as _saveCustomerMaster,
  listCustomerMaster,
} from '../api/pz-api.js'

// Returns { data, loading, error, errorType, reload }
function _useApiCall(fetcher, deps) {
  const [state, setState] = useState({ data: null, loading: true, error: null, errorType: null })
  const mountedRef = useRef(true)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const run = useCallback(async () => {
    setState(s => ({ ...s, loading: true, error: null, errorType: null }))
    const res = await fetcherRef.current()
    if (!mountedRef.current) return
    if (res.ok) {
      setState({ data: res.data, loading: false, error: null, errorType: null })
    } else {
      setState({ data: null, loading: false, error: res.error || 'Request failed', errorType: res.type || null })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    mountedRef.current = true
    run()
    return () => { mountedRef.current = false }
  }, [run])

  return { ...state, reload: run }
}

export function useProformaDrafts(batchId) {
  return _useApiCall(
    () => batchId
      ? getProformaDrafts(batchId)
      : Promise.resolve({ ok: true, data: { drafts: [], count: 0 } }),
    [batchId],
  )
}

// CRITICAL INVARIANT: data.ready comes from the backend. Never recompute locally.
export function useProformaPreview(batchId, clientName) {
  return _useApiCall(
    () => (batchId && clientName)
      ? previewProforma(batchId, clientName)
      : Promise.resolve({ ok: true, data: null }),
    [batchId, clientName],
  )
}

export function useDraft(draftId) {
  return _useApiCall(
    () => (draftId != null && draftId !== '')
      ? getDraft(draftId)
      : Promise.resolve({ ok: true, data: null }),
    [draftId],
  )
}

export function useCustomerMaster(clientKey) {
  const [saving, setSaving] = useState(false)
  const base = _useApiCall(
    () => clientKey
      ? getCustomerMaster(clientKey)
      : Promise.resolve({ ok: true, data: null }),
    [clientKey],
  )

  const save = useCallback(async (body) => {
    setSaving(true)
    const res = await _saveCustomerMaster(clientKey, body)
    setSaving(false)
    if (res.ok) base.reload()
    return res
  }, [clientKey]) // eslint-disable-line react-hooks/exhaustive-deps

  return { ...base, save, saving }
}

export function useCustomerList(params) {
  const key = JSON.stringify(params || {})
  return _useApiCall(
    () => listCustomerMaster(params || {}),
    [key],
  )
}

// Convenience object for code that uses PzState.useDraft(...) pattern.
export const PzState = Object.freeze({
  useProformaDrafts,
  useProformaPreview,
  useDraft,
  useCustomerMaster,
  useCustomerList,
})
