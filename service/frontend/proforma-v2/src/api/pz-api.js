// pz-api.js — Transport layer for Proforma V2 React.
// ES module port of service/app/static/v2/pz-api.js.
// No window.PzApi. No window.EstrellaShared.
// Same error shape: { ok: false, status, error, type? }
// Same success shape: { ok: true, data }

'use strict'

// Standalone fetch wrapper replacing window.EstrellaShared.apiFetch.
// Session cookies are sent automatically for same-origin requests.
async function _apiFetch(url, opts) {
  const res = await fetch(url, opts)
  if (res.status === 401 || res.status === 403) {
    window.location.href = '/login'
    const err = new Error('Session expired')
    err.status = res.status
    err.type = 'auth'
    throw err
  }
  if (!res.ok) {
    let msg = res.statusText
    try {
      const j = await res.clone().json()
      msg = j.detail || j.error || res.statusText
    } catch (_) {}
    const err = new Error(msg)
    err.status = res.status
    throw err
  }
  return res.json()
}

function _resolveOperator() {
  try {
    const cached = (window.localStorage.getItem('pz_operator_name') || '').trim()
    if (cached) return cached
  } catch (_) {}
  let name = ''
  try {
    name = (window.prompt('Operator name (recorded in audit timeline):', 'admin') || '').trim()
  } catch (_) { name = '' }
  if (name) {
    try { window.localStorage.setItem('pz_operator_name', name) } catch (_) {}
  }
  return name
}

function _isProposalActionUrl(url, action) {
  const re = new RegExp('^/api/v1/action-proposals/[^/]+/' + action + '$')
  return typeof url === 'string' && re.test(url)
}

async function _call(method, url, body) {
  try {
    const opts = { method }
    if (body !== undefined) {
      opts.headers = { 'Content-Type': 'application/json' }
      opts.body = JSON.stringify(body)
    }
    const data = await _apiFetch(url, opts)
    return { ok: true, data }
  } catch (err) {
    return {
      ok:     false,
      status: err.status || 0,
      error:  err.message || String(err),
      type:   err.type,
    }
  }
}

async function _callM(method, url, body) {
  const op = _resolveOperator()
  try {
    const opts = { method }
    if (body !== undefined) {
      opts.headers = { 'Content-Type': 'application/json' }
      opts.body = JSON.stringify(body)
    }
    opts.headers = { ...(opts.headers || {}), ...(op ? { 'X-Operator': op } : {}) }
    const data = await _apiFetch(url, opts)
    return { ok: true, data }
  } catch (err) {
    return {
      ok:     false,
      status: err.status || 0,
      error:  err.message || String(err),
      type:   err.type,
    }
  }
}

const _get   = (url)       => _call('GET',    url)
const _post  = (url, body) => _call('POST',   url, body)
const _postM = (url, body) => _callM('POST',  url, body)
const _patch = (url, body) => _callM('PATCH', url, body)
const _put   = (url, body) => _callM('PUT',   url, body)
const _del   = (url)       => _callM('DELETE', url)

const BASE = '/api/v1'

// ── Named exports (one per function, mirrors window.PzApi object) ────────────

export const searchProformaDrafts = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/proforma/search${qs}`)
}

export const getProformaDrafts = (batchId) =>
  _get(`${BASE}/proforma/drafts/${encodeURIComponent(batchId)}`)

export const previewProforma = (batchId, clientName) =>
  _post(
    `${BASE}/proforma/preview/${encodeURIComponent(batchId)}/${encodeURIComponent(clientName)}`
  )

export const getDraft = (draftId) =>
  _get(`${BASE}/proforma/draft/${draftId}`)

export const getServiceProducts = () =>
  _get(`${BASE}/proforma/service-products`)

export const getProductOptions = () =>
  _get(`${BASE}/proforma/product-options`)

export const patchDraft = (draftId, patch, updatedAt) =>
  _patch(`${BASE}/proforma/draft/${draftId}`, {
    expected_updated_at: updatedAt || '',
    patch,
  })

export const patchDraftLine = (draftId, lineId, patch, updatedAt) =>
  _patch(`${BASE}/proforma/draft/${draftId}/lines/${lineId}`, {
    expected_updated_at: updatedAt || '',
    patch,
  })

export const addDraftLine = (draftId, lineBody) =>
  _postM(`${BASE}/proforma/draft/${draftId}/lines`, lineBody)

export const deleteDraftLine = (draftId, lineId) =>
  _del(`${BASE}/proforma/draft/${draftId}/lines/${lineId}`)

export const addServiceCharge = (draftId, charge, updatedAt) =>
  _postM(`${BASE}/proforma/draft/${draftId}/service-charges`, {
    expected_updated_at: updatedAt || '',
    charge,
  })

export const deleteServiceCharge = (draftId, chargeId) =>
  _del(`${BASE}/proforma/draft/${draftId}/service-charges/${chargeId}`)

export const deleteDraft = (draftId) =>
  _del(`${BASE}/proforma/draft/${draftId}`)

export const approveDraft = (draftId, updatedAt) =>
  _postM(`${BASE}/proforma/draft/${draftId}/approve`, {
    expected_updated_at: updatedAt || '',
    confirm_token:       'YES_APPROVE_LOCAL_PROFORMA_DRAFT',
  })

export const reopenDraft = (draftId, updatedAt) =>
  _postM(`${BASE}/proforma/draft/${draftId}/re-open`, {
    expected_updated_at: updatedAt || '',
    confirm_token:       'YES_REOPEN_LOCAL_PROFORMA_DRAFT',
  })

export const cancelDraft = (draftId, updatedAt, reason) =>
  _postM(`${BASE}/proforma/draft/${draftId}/cancel`, {
    expected_updated_at: updatedAt || '',
    reason:              reason || '',
  })

export const sendProformaEmail = (draftId, { confirm_token, recipient_override, subject_override, message_body, cc } = {}) =>
  _postM(`${BASE}/proforma/draft/${draftId}/send-email`, {
    confirm_token:      confirm_token || '',
    recipient_override: recipient_override || '',
    subject_override:   subject_override || '',
    message_body:       message_body || '',
    cc:                 cc || [],
  })

export const resetDraftFromSalesPacking = (draftId, updatedAt) =>
  _postM(`${BASE}/proforma/draft/${draftId}/reset-from-sales-packing`, {
    expected_updated_at: updatedAt || '',
    reset_all:           false,
  })

export const postDraftToWfirma = (draftId, body) =>
  _postM(`${BASE}/proforma/draft/${draftId}/post`, body || {})

export const cloneDraft = (draftId) =>
  _postM(`${BASE}/proforma/draft/${draftId}/clone`, {})

export const draftToInvoice = (draftId, body) =>
  _postM(`${BASE}/proforma/draft/${draftId}/to-invoice`, body || {})

export const getDisclosureConvert = (draftId) =>
  _get(`${BASE}/proforma/draft/${draftId}/disclose-convert`)

export const getDraftEvents = (draftId) =>
  _get(`${BASE}/proforma/draft/${draftId}/events`)

export const getDraftReadiness = (draftId, intent) =>
  _get(`${BASE}/proforma/draft/${draftId}/readiness?intent=${encodeURIComponent(intent || 'approve')}`)

export const resolveDraftAmbiguity = (draftId, designNo, productCode) =>
  _postM(`${BASE}/proforma/draft/${draftId}/resolve-ambiguity`, {
    design_no:    designNo    || '',
    product_code: productCode || '',
  })

export const listCustomerMaster = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/customer-master${qs}`)
}

export const getCustomerMaster = (clientKey) =>
  _get(`${BASE}/customer-master/${encodeURIComponent(clientKey)}`)

export const saveCustomerMaster = (clientKey, body) =>
  _put(`${BASE}/customer-master/${encodeURIComponent(clientKey)}`, body)

export const previewWfirmaSyncCustomer = () =>
  _get(`${BASE}/customer-master/sync-from-wfirma/preview`)

export const applyWfirmaSyncCustomer = (wfirmaIds) =>
  _postM(`${BASE}/customer-master/sync-from-wfirma/apply`, { wfirma_ids: wfirmaIds })

export const getCustomerDictionaries = () =>
  _get(`${BASE}/customer-master/dictionaries`)

export const refreshCustomerDictionaries = () =>
  _postM(`${BASE}/customer-master/dictionaries/refresh`, {})

export const getPackingDocuments = (batchId) =>
  _get(`${BASE}/packing/${encodeURIComponent(batchId)}/packing-documents`)

export const linkAsSales = (batchId, clientMappings) =>
  _postM(`${BASE}/packing/${encodeURIComponent(batchId)}/link-as-sales`,
    { client_mappings: clientMappings || [] })

export const getReservationPreview = (batchId) =>
  _get(`${BASE}/wfirma/reservation-preview/${encodeURIComponent(batchId)}`)

export const createReservation = (batchId, clientName) =>
  _postM(`${BASE}/wfirma/reservations/create`,
    { batch_id: batchId, client_name: clientName })

export const createCarrierShipment = (batchId, body) =>
  _postM(`${BASE}/carrier/${encodeURIComponent(batchId)}/shipment`, body)

export const listCarrierServices = () =>
  _get(`${BASE}/carrier/services`)

export const listBoxTypes = (activeOnly = true) =>
  _get(`${BASE}/box-types/${activeOnly ? '?active=true' : ''}`)

export const getReceiptStatus = (batchId) =>
  _get(`${BASE}/warehouse/receipt/${encodeURIComponent(batchId)}`)

export const confirmReceipt = (batchId, lines, sourceDocuments) =>
  _postM(`${BASE}/warehouse/receipt/confirm`,
    { batch_id: batchId, lines: lines, source_documents: sourceDocuments || null })

export const approveProposal = (endpoint, note) => {
  if (!_isProposalActionUrl(endpoint, 'approve'))
    return Promise.resolve({ ok: false, status: 0, type: 'guard',
      error: 'Refused: not a valid action-proposals approve URL.' })
  const op = _resolveOperator()
  if (!op)
    return Promise.resolve({ ok: false, status: 0, type: 'operator',
      error: 'Operator name required -- approval cancelled.' })
  const body = { approved_by: op }
  const n = (note || '').trim()
  if (n) body.note = n
  return _call('POST', endpoint, body)
}

export const rejectProposal = (endpoint, reason) => {
  if (!_isProposalActionUrl(endpoint, 'reject'))
    return Promise.resolve({ ok: false, status: 0, type: 'guard',
      error: 'Refused: not a valid action-proposals reject URL.' })
  const op = _resolveOperator()
  if (!op)
    return Promise.resolve({ ok: false, status: 0, type: 'operator',
      error: 'Operator name required -- rejection cancelled.' })
  const r = (reason || '').trim()
  if (!r)
    return Promise.resolve({ ok: false, status: 0, type: 'reason',
      error: 'Reason required -- rejection cancelled.' })
  return _call('POST', endpoint, { rejected_by: op, reason: r })
}

export const getWfirmaCapabilities = () => _get(`${BASE}/wfirma/capabilities`)
export const getWfirmaCustomers    = () => _get(`${BASE}/wfirma/customers`)
export const getWfirmaProducts     = () => _get(`${BASE}/wfirma/products`)

export const searchWfirmaContractors = (q) =>
  _get(`${BASE}/wfirma/contractors/search?q=${encodeURIComponent(q || '')}`)

export const searchWfirmaGoods = (q) =>
  _get(`${BASE}/wfirma/goods/search?q=${encodeURIComponent(q || '')}`)

export const listSuppliers = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/suppliers${qs}`)
}

export const listProductLocal = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/product-local${qs}`)
}

export const listDesigns = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/designs${qs}`)
}

export const listHsCodes = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/hs-codes${qs}`)
}

export const listFxRates = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/fx-rates${qs}`)
}

export const listVatConfig = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/vat-config${qs}`)
}

export const listIncoterms = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/incoterms${qs}`)
}

export const listUnits = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/units${qs}`)
}

export const listCarriersConfig = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/carriers-config${qs}`)
}

export const getCarrierStatus    = () => _get(`${BASE}/carrier/status`)
export const getHealthFull       = () => _get(`${BASE}/debug/health-full`)
export const getDebugPending     = () => _get(`${BASE}/debug/pending`)
export const getStorageHealth    = () => _get(`${BASE}/debug/storage/health`)
export const getStorageLocks     = () => _get(`${BASE}/debug/storage/locks`)
export const getSystemVersion    = () => _get(`${BASE}/system/version`)
export const getOpenApiSpec      = () => _get('/openapi.json')
export const getPzHealth         = () => _get(`${BASE}/pz/health`)

export const getBatchDetail = (batchId) =>
  _get(`${BASE}/dashboard/batches/${encodeURIComponent(batchId)}`)

export const getDhlReadiness = (batchId) =>
  _get(`${BASE}/dhl/readiness/${encodeURIComponent(batchId)}`)

export const getDhlAutoScanStatus  = () => _get(`${BASE}/dhl/auto-scan-status`)
export const getDhlDailySummary    = () => _get(`${BASE}/dhl/daily-summary`)
export const getDhlFollowupStatus  = () => _get(`${BASE}/dhl/followup-automation/status`)
export const getEmailQueue         = () => _get(`${BASE}/admin/email-queue`)
export const getIntelligenceStatus = () => _get(`${BASE}/intelligence/status`)
export const listBatches           = () => _get(`${BASE}/dashboard/batches`)
export const listUsers             = () => _get('/auth/users')

export const listMasterAudit = (params) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return _get(`${BASE}/master/audit${qs}`)
}

export const getClientInvoiceLedger = (contractorId, from, to) =>
  _get(`${BASE}/ledgers/clients/${encodeURIComponent(contractorId)}/invoice-ledger.json?from=${encodeURIComponent(from || '')}&to=${encodeURIComponent(to || '')}`)

export const applyCustomerAddress = (draftId, updatedAt) =>
  _postM(`${BASE}/proforma/draft/${draftId}/apply-customer-address`, {
    expected_updated_at: updatedAt || '',
  })

export const suggestServiceCharges = (draftId) =>
  _get(`${BASE}/proforma/draft/${draftId}/suggest-service-charges`)

export const applyServiceCharges = (draftId, applyList, updatedAt) =>
  _postM(`${BASE}/proforma/draft/${draftId}/apply-service-charges`, {
    expected_updated_at: updatedAt || '',
    apply: applyList || [],
  })

// Convenience object — ProformaDetail.jsx uses window.PzApi.foo() pattern.
// After porting, replace window.PzApi. with PzApi. via import.
export const PzApi = Object.freeze({
  searchProformaDrafts, getProformaDrafts, previewProforma, getDraft,
  getServiceProducts, getProductOptions, patchDraft, patchDraftLine,
  addDraftLine, deleteDraftLine, addServiceCharge, deleteServiceCharge,
  deleteDraft, approveDraft, reopenDraft, cancelDraft, sendProformaEmail,
  resetDraftFromSalesPacking, postDraftToWfirma, cloneDraft, draftToInvoice,
  getDisclosureConvert, getDraftEvents, getDraftReadiness,
  resolveDraftAmbiguity, listCustomerMaster, getCustomerMaster, saveCustomerMaster,
  previewWfirmaSyncCustomer, applyWfirmaSyncCustomer, getCustomerDictionaries,
  refreshCustomerDictionaries, getPackingDocuments, linkAsSales,
  getReservationPreview, createReservation, createCarrierShipment,
  listCarrierServices, listBoxTypes, getReceiptStatus, confirmReceipt,
  approveProposal, rejectProposal, getWfirmaCapabilities, getWfirmaCustomers,
  getWfirmaProducts, searchWfirmaContractors, searchWfirmaGoods,
  listSuppliers, listProductLocal, listDesigns, listHsCodes, listFxRates,
  listVatConfig, listIncoterms, listUnits, listCarriersConfig,
  getCarrierStatus, getHealthFull, getDebugPending, getStorageHealth,
  getStorageLocks, getSystemVersion, getOpenApiSpec, getPzHealth,
  getBatchDetail, getDhlReadiness, getDhlAutoScanStatus, getDhlDailySummary,
  getDhlFollowupStatus, getEmailQueue, getIntelligenceStatus, listBatches,
  listUsers, listMasterAudit, getClientInvoiceLedger, applyCustomerAddress,
  suggestServiceCharges, applyServiceCharges,
})
