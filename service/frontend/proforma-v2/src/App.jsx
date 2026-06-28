// App.jsx — Shell that renders ProformaDetailPage from URL params.
// Reads ?batch_id=&client_name= from the query string (same as the Babel V2 shell).

import React, { useState, useEffect } from 'react'
import ProformaDetailPage from './ProformaDetail.jsx'
import './styles/tokens.css'

function parseParams() {
  const p = new URLSearchParams(window.location.search)
  return {
    batchId:    p.get('batch_id')    || '',
    clientName: p.get('client_name') || '',
    draftId:    p.get('draft_id')    || null,
  }
}

export default function App() {
  const [params] = useState(parseParams)
  const [draft,  setDraft]  = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    if (params.draftId) {
      // Draft-ID path: load the draft directly
      fetch(`/api/v1/proforma/draft/${params.draftId}`, { credentials: 'include' })
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          return r.json()
        })
        .then(data => { setDraft(data); setLoading(false) })
        .catch(e => { setError(e.message); setLoading(false) })
    } else if (params.batchId && params.clientName) {
      // Batch+client path: load drafts list and pick the first
      fetch(`/api/v1/proforma/drafts/${encodeURIComponent(params.batchId)}`, { credentials: 'include' })
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          return r.json()
        })
        .then(data => {
          const drafts = (data.drafts || []).filter(
            d => d.client_name === params.clientName
          )
          setDraft(drafts[0] || null)
          setLoading(false)
        })
        .catch(e => { setError(e.message); setLoading(false) })
    } else {
      setLoading(false)
    }
  }, [params.draftId, params.batchId, params.clientName])

  if (loading) return (
    <div style={{ padding: 40, color: 'var(--text-2)', fontSize: 14 }}>Loading…</div>
  )
  if (error) return (
    <div style={{ padding: 40, color: 'var(--badge-red-text)', fontSize: 14 }}>Error: {error}</div>
  )
  if (!draft) return (
    <div style={{ padding: 40, color: 'var(--text-2)', fontSize: 14 }}>
      No draft found. Provide ?draft_id= or ?batch_id=&amp;client_name= in the URL.
    </div>
  )

  return (
    <div data-theme="light" style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <ProformaDetailPage
        draft={draft}
        batchId={params.batchId || draft.batch_id || ''}
        clientName={params.clientName || draft.client_name || ''}
        onBack={() => window.history.back()}
        onConvert={(d) => { window.location.reload() }}
      />
    </div>
  )
}
