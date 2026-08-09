// Shipments Hub (V2 shell `page === 'shipments'`) — CANONICAL V2 shipments
// list/front page. Operational parity with the V1 dashboard.html
// DashboardPage: status filters, clickable operational buckets (warehouse /
// sales & accounting / DHL & customs), recheck / archive / restore actions,
// pagination, and client-side CSV export. Not an iframe of B1 — a native V2
// React re-implementation reading the same backend authority.
//
// Authority owner (backend, unchanged): routes_dashboard.py
//   GET    /api/v1/dashboard/batches                — active batches
//   GET    /api/v1/dashboard/archive                — archived batches
//   POST   /api/v1/dashboard/batches/{id}/recheck    — re-run parsers
//   DELETE /api/v1/dashboard/batches/{id}            — archive (soft)
//   POST   /api/v1/dashboard/archive/{id}/restore    — restore
//   DELETE /api/v1/dashboard/archive/{id}            — permanent delete (admin)
//
// This page never recalculates landed cost / duty / totals — those numbers
// are rendered verbatim from `_batch_summary()`. No mock data, no invented
// fields (Visa Date / Visa Generated Date have no backend authority and are
// always rendered as an em-dash with an explanatory tooltip).

// ── Status mappers (ported from V1 dashboard.html — production-proven) ─────

function _shMapOverall(status) {
  const m = {
    success: 'Ready for Booking', partial: 'Ready for Booking',
    blocked: 'Action Required', failed: 'Action Required',
    awaiting_dhl_email: 'Awaiting DHL', awaiting_sad: 'Awaiting SAD',
    awaiting_clearance: 'Awaiting Clearance',
    in_preparation: 'In Preparation', draft: 'Draft',
    ready: 'Ready for PZ', processing: 'In Preparation',
    collecting: 'In Preparation',
  };
  return m[status] || (status ? status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Pending');
}

function _shMapDhlStatus(s) {
  if (!s) return '—';
  const m = {
    awaiting_dhl_email: 'Awaiting DHL Email',
    dhl_email_received: 'DHL Email Received',
    reply_sent: 'Reply Sent',
    reply_queued: 'Reply Queued',
    pre_check_completed: 'Pre-check Completed',
    pre_check_pending: 'Pre-check Pending',
    reply_package_prepared: 'Reply Package Prepared',
  };
  return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function _shMapSadStatus(s) {
  if (!s) return 'SAD Pending';
  const m = {
    sad_pending: 'SAD Pending', sad_uploaded: 'SAD Uploaded',
    customs_parsed: 'Customs Parsed', customs_verified: 'Customs Verified',
    verification_needed: 'Verification Needed',
    missing: 'SAD Pending', uploaded: 'SAD Uploaded', uploaded_parsed: 'Customs Parsed',
  };
  return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function _shMapPzStatus(s) {
  if (!s) return 'Locked';
  const m = { locked: 'Locked', ready: 'Ready for PZ', generated: 'Generated', exported: 'Exported' };
  return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// Backend summary → display row. Money stays numeric (formatted at render
// time via window.fmtMoney2); dates stay as raw ISO strings (formatted at
// render time). `_raw` preserves the full backend row for onViewShipment
// and for any per-row lookups the cross-batch cards need.
function _shTransformBatch(b) {
  return {
    id: b.batch_id,
    batch_id: b.batch_id,
    awb: b.tracking_no || b.doc_no || b.batch_id,
    carrier: b.carrier || '—',
    dhlStatus: _shMapDhlStatus(b.dhl_status),
    sadStatus: _shMapSadStatus(b.sad_status),
    pzStatus: _shMapPzStatus(b.pz_status),
    overall: _shMapOverall(b.status),
    warehouseHint: b.warehouse_status_hint || 'n/a',
    salesHint: b.sales_status_hint || 'n/a',
    wfirmaHint: b.wfirma_status_hint || 'n/a',
    net: b.net,
    gross: b.gross,
    duty: b.duty,
    timestamp: b.timestamp || '',
    uploaded_at: b.uploaded_at || null,
    pz_generated_at: b.pz_generated_at || null,
    has_sad: !!b.has_sad,
    mrn: b.mrn || '—',
    action_reason: b.action_reason || '',
    doc_no: b.doc_no || '',
    status: b.status || '',
    tracking_url: b.tracking_url || '',
    tracking_label: b.tracking_label || '',
    _raw: b,
  };
}

// ── UI-3.x shared operational predicates (module scope) ────────────────────
// Single source of truth for the three cross-batch cards + the active-table
// operational filter chip. Copied verbatim (behaviour) from
// dashboard.html ~9227-9290; identifiers are `_SH`-prefixed here to avoid
// any risk of colliding with other V2 scripts loaded in the same shell
// (dashboard-kanban.jsx already owns unprefixed `_mapOverall` etc.).
const _SH_PZ_DONE_LABELS = new Set(['Generated', 'Exported']);
const _SH_SAD_CLEARED_KEYS = new Set(['uploaded_parsed', 'customs_parsed', 'customs_verified']);
const _SH_TRACK_ATTENTION = new Set(['exception', 'customs']);
const _SH_DHL_FLOW_LIVE_KEYS = new Set([
  'dhl_email_received', 'reply_queued', 'reply_sent',
  'reply_package_prepared', 'pre_check_pending', 'pre_check_completed',
]);
const _SH_OP_PREDICATES = {
  warehouse: {
    unknown: (r) => (r.warehouseHint || 'n/a') === 'n/a',
    awaiting: (r) => r.warehouseHint === 'empty',
    partial_received: (r) => r.warehouseHint === 'partial',
    in_warehouse: (r) => r.warehouseHint === 'clean' && !_SH_PZ_DONE_LABELS.has(r.pzStatus || ''),
    reserved: (r) => r.warehouseHint === 'clean' && _SH_PZ_DONE_LABELS.has(r.pzStatus || ''),
  },
  sales_accounting: {
    sales_ready: (r) => (r.salesHint || 'n/a') === 'present',
    sales_missing: (r) => { const h = r.salesHint || 'n/a'; return h === 'none' || h === 'n/a'; },
    wfirma_preview: (r) => (r.wfirmaHint || 'n/a') === 'preview_built',
    wfirma_pending: (r) => { const h = r.wfirmaHint || 'n/a'; return h === 'none' || h === 'n/a'; },
    pz_done: (r) => _SH_PZ_DONE_LABELS.has(r.pzStatus || ''),
    pz_pending: (r) => !_SH_PZ_DONE_LABELS.has(r.pzStatus || ''),
  },
  dhl_customs: {
    awaiting_customs_docs: (r) => !r.has_sad && _SH_DHL_FLOW_LIVE_KEYS.has((r._raw && r._raw.dhl_status) || ''),
    sad_present: (r) => !!r.has_sad,
    sad_missing: (r) => !r.has_sad,
    customs_cleared: (r) => !!r.has_sad && _SH_SAD_CLEARED_KEYS.has((r._raw && r._raw.sad_status) || ''),
    dhl_in_transit: (r) => ((r._raw && r._raw.tracking_status_key) || '') === 'in_transit',
    dhl_delivered: (r) => ((r._raw && r._raw.tracking_status_key) || '') === 'delivered',
  },
};
const _SH_WAREHOUSE_LIFECYCLE_KEYS = ['unknown', 'awaiting', 'partial_received', 'in_warehouse', 'reserved'];
function _shDeriveWarehouseLifecycle(row) {
  for (const k of _SH_WAREHOUSE_LIFECYCLE_KEYS) {
    if (_SH_OP_PREDICATES.warehouse[k](row)) return k;
  }
  return 'unknown';
}
const _SH_ATTENTION_PREDICATES = {
  warehouse: (r) =>
    _SH_OP_PREDICATES.warehouse.awaiting(r) ||
    _SH_OP_PREDICATES.warehouse.partial_received(r),
  sales_accounting: (r) =>
    _SH_OP_PREDICATES.sales_accounting.sales_missing(r) ||
    _SH_OP_PREDICATES.sales_accounting.wfirma_pending(r) ||
    _SH_OP_PREDICATES.sales_accounting.pz_pending(r),
  dhl_customs: (r) =>
    _SH_OP_PREDICATES.dhl_customs.awaiting_customs_docs(r) ||
    (((r._raw && r._raw.sad_status) || '') === 'missing') ||
    (((r._raw && r._raw.dhl_status) || '') === 'dhl_email_received') ||
    _SH_TRACK_ATTENTION.has((r._raw && r._raw.tracking_status_key) || ''),
};
const _SH_WAREHOUSE_LIFECYCLE_LABEL = {
  unknown: 'No packing list',
  in_transit: 'In transit / Awaiting warehouse receive',
  awaiting: 'Awaiting receipt',
  partial_received: 'Partially received',
  in_warehouse: 'In warehouse',
  reserved: 'Reserved (PZ created)',
};
const _SH_WAREHOUSE_LIFECYCLE_TONE = {
  unknown: { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  in_transit: { bg: 'var(--badge-blue-bg)', text: 'var(--badge-blue-text)', border: 'var(--badge-blue-border)' },
  awaiting: { bg: 'var(--badge-red-bg)', text: 'var(--badge-red-text)', border: 'var(--badge-red-border)' },
  partial_received: { bg: 'var(--badge-amber-bg)', text: 'var(--badge-amber-text)', border: 'var(--badge-amber-border)' },
  in_warehouse: { bg: 'var(--badge-blue-bg)', text: 'var(--badge-blue-text)', border: 'var(--badge-blue-border)' },
  reserved: { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)' },
};

// Mid-process statuses — archiving warns the operator before proceeding.
const _SH_MID_PROCESS = new Set(['processing', 'awaiting_dhl_email', 'reply_queued', 'clearance_started']);

// Overall-status filter bar (matches dashboard.html `filters`).
const _SH_STATUS_FILTERS = ['all', 'Ready for PZ', 'Awaiting DHL', 'Awaiting SAD', 'Action Required', 'Ready for Booking', 'Exported'];
function _shFilterSlug(f) {
  return f === 'all' ? 'all' : f.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
}

// ── Format helpers ───────────────────────────────────────────────────────

// Textual (never timezone-shifting) YYYY-MM-DD → DD.MM.YYYY parse — same
// discipline as the previous _pzDate helper. Any absent/unparseable value
// renders as an em-dash; never fabricated.
function _shFmtDate(v) {
  if (typeof v !== 'string' || !v.trim()) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v.trim());
  return m ? `${m[3]}.${m[2]}.${m[1]}` : null;
}

// Sort key for the default 'list_date' virtual column: uploaded_at falls
// back to timestamp, then to pz_generated_at. Missing/unparseable → null so
// the shared null-last rule applies regardless of sort direction.
function _shListDateValue(row) {
  const raw = row.uploaded_at || row.timestamp || row.pz_generated_at;
  if (!raw) return null;
  const t = Date.parse(raw);
  return Number.isNaN(t) ? null : t;
}

function _shMoney(v) {
  return window.fmtMoney2 ? window.fmtMoney2(v, { locale: 'pl-PL' }) : (v === null || v === undefined || v === '' ? '—' : String(v));
}
// Alias retained for money-format contract tests / call sites that expect `_money`.
const _money = _shMoney;

// Only allow http(s) tracking links — defence in depth against a poisoned
// javascript:/data: href even though the backend field is trusted today.
function _shSafeHttpUrl(u) {
  return (typeof u === 'string' && /^https?:\/\//i.test(u)) ? u : null;
}

function _shExportCsv(headers, rows, filename) {
  const escape = (v) => {
    const s = v === null || v === undefined ? '' : String(v);
    return s.includes(',') || s.includes('"') || s.includes('\n') ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const lines = [headers.map(escape).join(',')].concat(rows.map(r => r.map(escape).join(',')));
  const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
  const blobUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl; a.download = filename || 'shipments-export.csv';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
}

// ── Transport — prefer window.PzApi, fall back to EstrellaShared.apiFetch
// against the identical canonical paths. PzApi does not yet expose
// listArchived / recheckBatch / archiveBatch / restoreBatch (only
// listBatches and a SAD-only recheckSad); every helper below checks for the
// specific method before falling back, so a future PzApi addition is picked
// up automatically with no change here. ──────────────────────────────────

function _shApiFetch(path, opts) {
  return window.EstrellaShared.apiFetch(path, opts);
}

async function _shListBatches() {
  if (window.PzApi && typeof window.PzApi.listBatches === 'function') {
    const res = await window.PzApi.listBatches();
    if (!res.ok) throw new Error(res.error || 'Failed to load shipments');
    const d = res.data;
    return Array.isArray(d) ? d : ((d && (d.batches || d.rows || d.items)) || []);
  }
  const d = await _shApiFetch('/api/v1/dashboard/batches');
  return Array.isArray(d) ? d : ((d && (d.batches || d.rows || d.items)) || []);
}

async function _shListArchived() {
  if (window.PzApi && typeof window.PzApi.listArchived === 'function') {
    const res = await window.PzApi.listArchived();
    if (!res.ok) throw new Error(res.error || 'Failed to load archived shipments');
    return Array.isArray(res.data) ? res.data : [];
  }
  const d = await _shApiFetch('/api/v1/dashboard/archive');
  return Array.isArray(d) ? d : [];
}

async function _shRecheckBatch(id) {
  if (window.PzApi && typeof window.PzApi.recheckBatch === 'function') {
    const res = await window.PzApi.recheckBatch(id);
    if (!res.ok) throw new Error(res.error || 'Recheck failed');
    return res.data;
  }
  return _shApiFetch(`/api/v1/dashboard/batches/${encodeURIComponent(id)}/recheck`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'all' }),
  });
}

async function _shArchiveBatch(id, reason) {
  if (window.PzApi && typeof window.PzApi.archiveBatch === 'function') {
    const res = await window.PzApi.archiveBatch(id, reason);
    if (!res.ok) throw new Error(res.error || 'Archive failed');
    return res.data;
  }
  return _shApiFetch(`/api/v1/dashboard/batches/${encodeURIComponent(id)}`, {
    method: 'DELETE', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason: reason || 'archived by user' }),
  });
}

async function _shRestoreBatch(id) {
  if (window.PzApi && typeof window.PzApi.restoreBatch === 'function') {
    const res = await window.PzApi.restoreBatch(id);
    if (!res.ok) throw new Error(res.error || 'Restore failed');
    return res.data;
  }
  return _shApiFetch(`/api/v1/dashboard/archive/${encodeURIComponent(id)}/restore`, { method: 'POST' });
}

async function _shPermanentlyDeleteArchived(id) {
  if (window.PzApi && typeof window.PzApi.permanentlyDeleteArchived === 'function') {
    const res = await window.PzApi.permanentlyDeleteArchived(id);
    if (!res.ok) throw new Error(res.error || 'Permanent delete failed');
    return res.data;
  }
  return _shApiFetch(`/api/v1/dashboard/archive/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

// ── Component ────────────────────────────────────────────────────────────

function DashboardPage({ onViewShipment, onToast }) {
  const [batches, setBatches] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  const [viewMode, setViewMode] = React.useState('active'); // 'active' | 'archived'
  const [archived, setArchived] = React.useState([]);
  const [archivedLoading, setArchivedLoading] = React.useState(false);
  const [archiveBusy, setArchiveBusy] = React.useState({});

  const [filter, setFilter] = React.useState('all');
  // opFilter = null | { card, key, label } — combined AND with `filter`.
  const [opFilter, setOpFilter] = React.useState(null);

  // Default sort: newest upload/activity first (virtual 'list_date' column).
  const [sortCol, setSortCol] = React.useState('list_date');
  const [sortDir, setSortDir] = React.useState('desc');

  const [page, setPage] = React.useState(1);
  const PAGE_SIZE = 25;

  const [actionMenu, setActionMenu] = React.useState(null);
  const [recheckState, setRecheckState] = React.useState({});
  const [recheckResult, setRecheckResult] = React.useState({});

  const load = React.useCallback(() => {
    setLoading(true); setError(null);
    _shListBatches()
      .then(list => { setBatches(list.map(_shTransformBatch)); setLoading(false); })
      .catch(e => { setError((e && e.message) || String(e)); setLoading(false); });
  }, []);

  const loadArchived = React.useCallback(() => {
    setArchivedLoading(true);
    _shListArchived()
      .then(list => { setArchived(list); setArchivedLoading(false); })
      .catch(() => { setArchived([]); setArchivedLoading(false); });
  }, []);

  React.useEffect(() => { load(); }, [load]);
  React.useEffect(() => { if (viewMode === 'archived') loadArchived(); }, [viewMode, loadArchived]);

  const handleReload = () => { load(); if (viewMode === 'archived') loadArchived(); };

  // ── Operational bucket filter (UI-3.3 parity) ───────────────────────────
  const clearOpFilter = React.useCallback(() => setOpFilter(null), []);
  const toggleOpFilter = React.useCallback((card, key, label) => {
    setOpFilter(prev => (prev && prev.card === card && prev.key === key) ? null : { card, key, label });
  }, []);
  const opPredicate = (row) => {
    if (!opFilter) return true;
    const fn = (_SH_OP_PREDICATES[opFilter.card] || {})[opFilter.key];
    return fn ? fn(row) : true;
  };
  const isOpActive = (card, key) => !!opFilter && opFilter.card === card && opFilter.key === key;

  const all = batches; // transformed active rows — KPI + cross-batch cards read this unfiltered

  // Status filters use overall labels except Exported (pzStatus) — B1's
  // overall===Exported never matched; V2 maps Exported to the real PZ field.
  const baseFiltered = filter === 'all'
    ? all
    : filter === 'Exported'
      ? all.filter(s => s.pzStatus === 'Exported')
      : all.filter(s => s.overall === filter || (filter === 'Ready for PZ' && s.pzStatus === 'Ready for PZ'));
  const filtered = opFilter ? baseFiltered.filter(opPredicate) : baseFiltered;

  const sorted = React.useMemo(() => {
    const copy = filtered.slice();
    const isDateCol = sortCol === 'list_date';
    const isNumCol = sortCol === 'net' || sortCol === 'gross' || sortCol === 'duty';
    const valueOf = (row) => {
      if (isDateCol) return _shListDateValue(row);
      if (isNumCol) { const n = row[sortCol]; return (n === null || n === undefined || n === '') ? null : Number(n); }
      const v = row[sortCol];
      return (v === null || v === undefined || v === '') ? null : v;
    };
    copy.sort((a, b) => {
      const av = valueOf(a), bv = valueOf(b);
      if (av === null && bv === null) return 0;
      if (av === null) return 1;  // missing sorts last — BEFORE the direction flip
      if (bv === null) return -1;
      const r = (isDateCol || isNumCol)
        ? (av < bv ? -1 : av > bv ? 1 : 0)
        : String(av).localeCompare(String(bv), undefined, { numeric: true });
      return sortDir === 'asc' ? r : -r;
    });
    return copy;
  }, [filtered, sortCol, sortDir]);

  React.useEffect(() => { setPage(1); }, [filter, opFilter, sortCol, sortDir, viewMode]);
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageStart = (safePage - 1) * PAGE_SIZE;
  const pageEnd = Math.min(pageStart + PAGE_SIZE, sorted.length);
  const paginated = sorted.slice(pageStart, pageEnd);

  const handleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
  };

  const TH = ({ col, children, title }) => (
    <th
      onClick={col ? () => handleSort(col) : undefined}
      title={title}
      style={{
        padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700,
        color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase',
        cursor: col ? 'pointer' : 'default', whiteSpace: 'nowrap',
        borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)', userSelect: 'none',
      }}
    >{children}{col && sortCol === col ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}</th>
  );

  // ── KPI cards — derived from the FULL unfiltered active list ────────────
  const counts = {
    total: all.length,
    awaitingDHL: all.filter(b => b.overall === 'Awaiting DHL').length,
    awaitingSAD: all.filter(b => b.overall === 'Awaiting SAD').length,
    readyPZ: all.filter(b => b.pzStatus === 'Ready for PZ').length,
    actionReq: all.filter(b => b.overall === 'Action Required').length,
    readyBooking: all.filter(b => b.overall === 'Ready for Booking').length,
    totalDuty: all.reduce((s, b) => s + (b.duty ? Number(b.duty) : 0), 0),
    totalGross: all.reduce((s, b) => s + (b.gross ? Number(b.gross) : 0), 0),
  };
  const cards = [
    { label: 'Total Shipments', value: counts.total, icon: '⬡', colorVar: 'var(--text)' },
    { label: 'Awaiting DHL', value: counts.awaitingDHL, icon: '✈', colorVar: 'var(--badge-amber-text)' },
    { label: 'Awaiting SAD', value: counts.awaitingSAD, icon: '⊟', colorVar: 'var(--badge-orange-text)' },
    { label: 'Ready for PZ', value: counts.readyPZ, icon: '◈', colorVar: 'var(--badge-green-text)' },
    { label: 'Action Required', value: counts.actionReq, icon: '⚠', colorVar: 'var(--badge-red-text)' },
    { label: 'Ready for Booking', value: counts.readyBooking, icon: '✓', colorVar: 'var(--badge-purple-text)' },
    { label: 'Total Duty A00', value: _shMoney(counts.totalDuty), icon: '₤', colorVar: 'var(--accent)', wide: true },
    { label: 'Total Gross Value', value: _shMoney(counts.totalGross), icon: '◈', colorVar: 'var(--badge-blue-text)', wide: true },
  ];

  const handleExportCsv = () => {
    const headers = ['AWB', 'Upload Date', 'Visa Date', 'Visa Generated Date', 'Carrier', 'DHL Status', 'SAD Status', 'MRN', 'PZ Status', 'Warehouse', 'Sales', 'wFirma', 'Net', 'Gross', 'Duty A00', 'Overall'];
    const rows = sorted.map(row => [
      row.awb,
      _shFmtDate(row.uploaded_at) || _shFmtDate(row.timestamp) || '—',
      '—', '—',
      row.carrier, row.dhlStatus, row.sadStatus, row.mrn, row.pzStatus,
      row.warehouseHint, row.salesHint, row.wfirmaHint,
      _shMoney(row.net), _shMoney(row.gross), _shMoney(row.duty), row.overall,
    ]);
    _shExportCsv(headers, rows, `shipments-export-${new Date().toISOString().slice(0, 10)}.csv`);
  };

  const doRecheck = async (row) => {
    if (!window.confirm(`Recheck shipment ${row.awb}?\n\nThis will re-run parsers against existing uploaded files.\nParsed values may change. PZ will NOT be regenerated automatically.`)) return;
    setRecheckState(s => ({ ...s, [row.id]: 'pending' }));
    setRecheckResult(s => ({ ...s, [row.id]: null }));
    try {
      const res = await _shRecheckBatch(row.id);
      setRecheckState(s => ({ ...s, [row.id]: (res && res.ok !== false) ? 'done' : 'error' }));
      setRecheckResult(s => ({ ...s, [row.id]: res }));
      load();
    } catch (e) {
      setRecheckState(s => ({ ...s, [row.id]: 'error' }));
      setRecheckResult(s => ({ ...s, [row.id]: { ok: false, errors: [e.message] } }));
    }
  };

  const doArchive = async (row) => {
    if (_SH_MID_PROCESS.has((row.status || '').toLowerCase())) {
      const proceed = window.confirm(
        `⚠️ Shipment ${row.awb} is mid-process (status: ${row.status}).\n\n` +
        `Archiving now may interrupt active clearance or DHL reply workflows.\n\nArchive anyway?`
      );
      if (!proceed) return;
    }
    const reason = window.prompt(`Archive shipment ${row.awb}?\n\nIt will be hidden from the active dashboard and kept for 14 days before becoming eligible for permanent deletion.\n\nOptional reason (or leave blank):`, '');
    if (reason === null) return; // cancelled
    try {
      await _shArchiveBatch(row.id, reason.trim() || 'archived by user');
      if (onToast) onToast('Shipment archived. It can be restored from Archived view.', 'success');
      load();
    } catch (e) {
      if (onToast) onToast(`Archive failed: ${e.message}`, 'error');
    }
  };

  return (
    <div data-testid="shipments-hub-root" style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>

      {/* Toolbar: export + reload */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, marginBottom: 12 }}>
        <Btn small variant="outline" data-testid="shipments-hub-csv-export" onClick={handleExportCsv}
          disabled={sorted.length === 0} title="Export the currently filtered + sorted rows to CSV">↓ Export CSV</Btn>
        <Btn small variant="outline" data-testid="shipments-hub-reload" onClick={handleReload} disabled={loading}>
          {loading ? '…' : '↻ Reload'}
        </Btn>
      </div>

      {error && (
        <div data-testid="shipments-hub-error" style={{ marginBottom: 14, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)' }}>
          Failed to load shipments: {error}
        </div>
      )}

      {/* KPI cards */}
      <div data-testid="shipments-hub-summary" style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 12, marginBottom: 28 }}>
        {cards.map((c, i) => (
          <Card key={i} style={{ padding: '16px 18px', gridColumn: c.wide ? 'span 2' : undefined }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-2)', fontWeight: 500, marginBottom: 6 }}>{c.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: c.colorVar, fontFamily: '"DM Serif Display",serif' }}>{loading ? '…' : c.value}</div>
              </div>
              <div style={{ width: 30, height: 30, borderRadius: 6, background: 'var(--accent-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, color: c.colorVar }}>{c.icon}</div>
            </div>
          </Card>
        ))}
      </div>

      {/* View mode toggle + status filter bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <button data-testid="shipments-hub-view-active" onClick={() => setViewMode('active')} style={{
          padding: '4px 12px', borderRadius: 20, border: viewMode === 'active' ? '1px solid var(--accent)' : '1px solid var(--border)',
          background: viewMode === 'active' ? 'var(--accent)' : 'transparent', color: viewMode === 'active' ? '#fff' : 'var(--text-2)',
          fontSize: 11, fontWeight: viewMode === 'active' ? 700 : 400, cursor: 'pointer', fontFamily: 'inherit',
        }}>● Active</button>
        <button data-testid="shipments-hub-view-archived" onClick={() => setViewMode('archived')} style={{
          padding: '4px 12px', borderRadius: 20, border: viewMode === 'archived' ? '1px solid var(--accent)' : '1px solid var(--border)',
          background: viewMode === 'archived' ? 'var(--accent)' : 'transparent', color: viewMode === 'archived' ? '#fff' : 'var(--text-2)',
          fontSize: 11, fontWeight: viewMode === 'archived' ? 700 : 400, cursor: 'pointer', fontFamily: 'inherit',
        }}>⊘ Archived</button>

        {viewMode === 'active' && <>
          <div style={{ width: 1, height: 18, background: 'var(--border)', margin: '0 4px' }} />
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Filter:</span>
          {_SH_STATUS_FILTERS.map(f => (
            <button key={f} data-testid={`shipments-hub-filter-${_shFilterSlug(f)}`} onClick={() => setFilter(f)} style={{
              padding: '4px 10px', borderRadius: 20, border: filter === f ? '1px solid var(--accent)' : '1px solid var(--border)',
              background: filter === f ? 'var(--accent-subtle)' : 'transparent', color: filter === f ? 'var(--text)' : 'var(--text-2)',
              fontSize: 11, fontWeight: filter === f ? 600 : 400, cursor: 'pointer', fontFamily: 'inherit',
            }}>{f === 'all' ? 'All' : f}</button>
          ))}
        </>}
        {viewMode === 'archived' && (
          <Btn small variant="ghost" onClick={loadArchived} style={{ marginLeft: 4 }}>↻ Refresh</Btn>
        )}
      </div>

      {/* Operational bucket filter chip */}
      {viewMode === 'active' && opFilter && (
        <div data-testid="op-filter-active-chip" data-op-card={opFilter.card} data-op-key={opFilter.key}
          style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, padding: '6px 10px', background: 'var(--accent-subtle)', border: '1px solid var(--accent)', borderRadius: 6, fontSize: 11, color: 'var(--text)' }}>
          <span style={{ fontWeight: 700, color: 'var(--text-2)' }}>Operational filter:</span>
          <span style={{ fontWeight: 700 }}>{opFilter.label}</span>
          <span style={{ color: 'var(--text-3)' }}>
            ({opFilter.card === 'warehouse' ? 'Warehouse' : opFilter.card === 'sales_accounting' ? 'Sales & Accounting' : opFilter.card === 'dhl_customs' ? 'DHL & Customs' : opFilter.card}
            {' '}— combined AND with the status filter above)
          </span>
          <button data-testid="op-filter-clear-btn" onClick={clearOpFilter}
            style={{ marginLeft: 'auto', background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-2)', fontSize: 11, padding: '2px 8px', borderRadius: 4, cursor: 'pointer', fontFamily: 'inherit' }}
            title="Clear operational filter only — status filter is unaffected">
            Clear operational filter
          </button>
        </div>
      )}

      {/* ── Warehouse Operations card ──────────────────────────────────── */}
      {viewMode === 'active' && (() => {
        const enriched = all.map(b => ({ row: b, lifecycle: _shDeriveWarehouseLifecycle(b) }));
        const whCounts = {
          unknown: all.filter(_SH_OP_PREDICATES.warehouse.unknown).length,
          awaiting: all.filter(_SH_OP_PREDICATES.warehouse.awaiting).length,
          partial_received: all.filter(_SH_OP_PREDICATES.warehouse.partial_received).length,
          in_warehouse: all.filter(_SH_OP_PREDICATES.warehouse.in_warehouse).length,
          reserved: all.filter(_SH_OP_PREDICATES.warehouse.reserved).length,
        };
        const attention = enriched.filter(e => _SH_ATTENTION_PREDICATES.warehouse(e.row))
          .sort((a, b) => { const at = a.row.timestamp || ''; const bt = b.row.timestamp || ''; return at < bt ? 1 : at > bt ? -1 : 0; });
        return (
          <Card data-testid="warehouse-operations-card" style={{ padding: 16, marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>📦 Warehouse Operations</div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>Cross-batch warehouse lifecycle — derived read-only from the batch-list payload. Open a batch for full detail.</div>
              </div>
            </div>
            <div data-testid="warehouse-operations-buckets" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 14 }}>
              {_SH_WAREHOUSE_LIFECYCLE_KEYS.map(key => {
                const tone = _SH_WAREHOUSE_LIFECYCLE_TONE[key];
                const active = isOpActive('warehouse', key);
                return (
                  <button key={key} type="button" data-testid={`warehouse-operations-bucket-${key}`} data-op-active={active ? 'true' : 'false'} aria-pressed={active}
                    onClick={() => toggleOpFilter('warehouse', key, _SH_WAREHOUSE_LIFECYCLE_LABEL[key])}
                    title={active ? 'Click to clear operational filter' : `Filter the shipments table by ${_SH_WAREHOUSE_LIFECYCLE_LABEL[key]}`}
                    style={{ textAlign: 'left', padding: '10px 12px', border: `${active ? 2 : 1}px solid ${active ? 'var(--accent)' : tone.border}`, background: tone.bg, borderRadius: 6, cursor: 'pointer', fontFamily: 'inherit', boxShadow: active ? '0 0 0 2px var(--accent-subtle)' : 'none' }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: tone.text, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{_SH_WAREHOUSE_LIFECYCLE_LABEL[key]}</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: tone.text, fontFamily: '"DM Serif Display",serif', marginTop: 2 }}>{loading ? '…' : whCounts[key]}</div>
                  </button>
                );
              })}
            </div>
            <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>Needs warehouse attention <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>(awaiting + partially received)</span></div>
              {!loading && attention.length === 0 && <div style={{ fontSize: 11, color: 'var(--text-3)', padding: '4px 0' }}>No batches need warehouse attention.</div>}
              {!loading && attention.length > 0 && (
                <table data-testid="warehouse-operations-attention-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <thead><tr>{['Shipment', 'Lifecycle', 'Warehouse Hint', 'PZ Status', 'Last activity'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', fontSize: 10, letterSpacing: '0.04em' }}>{h}</th>
                  ))}</tr></thead>
                  <tbody>
                    {attention.slice(0, 25).map(e => {
                      const tone = _SH_WAREHOUSE_LIFECYCLE_TONE[e.lifecycle];
                      const label = _SH_WAREHOUSE_LIFECYCLE_LABEL[e.lifecycle];
                      return (
                        <tr key={e.row.id}>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                            <button onClick={() => onViewShipment(e.row._raw || e.row)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--badge-blue-text)', fontSize: 11, fontWeight: 600, fontFamily: 'monospace', textDecoration: 'underline', textDecorationStyle: 'dotted', padding: 0 }}>{e.row.awb}</button>
                            {e.row.doc_no && <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 1 }}>{e.row.doc_no}</div>}
                          </td>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                            <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: tone.bg, color: tone.text, border: `1px solid ${tone.border}`, display: 'inline-block', whiteSpace: 'nowrap' }}>{label}</span>
                          </td>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-2)' }}>{e.row.warehouseHint || 'n/a'}</td>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-2)' }}>{e.row.pzStatus || '—'}</td>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-3)', fontFamily: 'monospace' }}>{e.row.timestamp || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
              {!loading && attention.length > 25 && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 6 }}>Showing first 25 of {attention.length}. Use the shipments table below to scroll the full list.</div>}
            </div>
          </Card>
        );
      })()}

      {/* ── Sales & Accounting Operations card ─────────────────────────── */}
      {viewMode === 'active' && (() => {
        const acctBucketLabel = {
          sales_ready: 'Sales ready', sales_missing: 'Sales missing',
          wfirma_preview: 'wFirma preview built', wfirma_pending: 'wFirma not prepared',
          pz_done: 'PZ generated/exported', pz_pending: 'PZ ready/locked',
        };
        const acctBucketTone = {
          sales_ready: { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)' },
          sales_missing: { bg: 'var(--badge-red-bg)', text: 'var(--badge-red-text)', border: 'var(--badge-red-border)' },
          wfirma_preview: { bg: 'var(--badge-blue-bg)', text: 'var(--badge-blue-text)', border: 'var(--badge-blue-border)' },
          wfirma_pending: { bg: 'var(--badge-amber-bg)', text: 'var(--badge-amber-text)', border: 'var(--badge-amber-border)' },
          pz_done: { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)' },
          pz_pending: { bg: 'var(--badge-amber-bg)', text: 'var(--badge-amber-text)', border: 'var(--badge-amber-border)' },
        };
        const acctSalesLabel = (row) => { const h = row.salesHint || 'n/a'; return h === 'present' ? 'Linked' : h === 'none' ? 'Not linked' : 'Unknown'; };
        const acctWfirmaLabel = (row) => { const h = row.wfirmaHint || 'n/a'; return h === 'preview_built' ? 'Preview built' : h === 'none' ? 'Not prepared' : 'Unknown'; };
        const acctSalesMissing = _SH_OP_PREDICATES.sales_accounting.sales_missing;
        const acctWfirmaMissing = _SH_OP_PREDICATES.sales_accounting.wfirma_pending;
        const acctPzPending = _SH_OP_PREDICATES.sales_accounting.pz_pending;
        const acctCounts = {
          sales_ready: all.filter(_SH_OP_PREDICATES.sales_accounting.sales_ready).length,
          sales_missing: all.filter(_SH_OP_PREDICATES.sales_accounting.sales_missing).length,
          wfirma_preview: all.filter(_SH_OP_PREDICATES.sales_accounting.wfirma_preview).length,
          wfirma_pending: all.filter(_SH_OP_PREDICATES.sales_accounting.wfirma_pending).length,
          pz_done: all.filter(_SH_OP_PREDICATES.sales_accounting.pz_done).length,
          pz_pending: all.filter(_SH_OP_PREDICATES.sales_accounting.pz_pending).length,
        };
        const acctAttention = all.filter(_SH_ATTENTION_PREDICATES.sales_accounting)
          .sort((a, b) => { const at = a.timestamp || ''; const bt = b.timestamp || ''; return at < bt ? 1 : at > bt ? -1 : 0; });
        return (
          <Card data-testid="sales-accounting-operations-card" style={{ padding: 16, marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>📑 Sales & Accounting Operations</div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>Cross-batch sales / wFirma / PZ status — derived read-only from the batch-list payload. Open a batch for full detail.</div>
              </div>
            </div>
            <div data-testid="sales-accounting-operations-buckets" style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8, marginBottom: 14 }}>
              {['sales_ready', 'sales_missing', 'wfirma_preview', 'wfirma_pending', 'pz_done', 'pz_pending'].map(key => {
                const tone = acctBucketTone[key];
                const active = isOpActive('sales_accounting', key);
                return (
                  <button key={key} type="button" data-testid={`sales-accounting-operations-bucket-${key}`} data-op-active={active ? 'true' : 'false'} aria-pressed={active}
                    onClick={() => toggleOpFilter('sales_accounting', key, acctBucketLabel[key])}
                    title={active ? 'Click to clear operational filter' : `Filter the shipments table by ${acctBucketLabel[key]}`}
                    style={{ textAlign: 'left', padding: '10px 12px', border: `${active ? 2 : 1}px solid ${active ? 'var(--accent)' : tone.border}`, background: tone.bg, borderRadius: 6, cursor: 'pointer', fontFamily: 'inherit', boxShadow: active ? '0 0 0 2px var(--accent-subtle)' : 'none' }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: tone.text, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{acctBucketLabel[key]}</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: tone.text, fontFamily: '"DM Serif Display",serif', marginTop: 2 }}>{loading ? '…' : acctCounts[key]}</div>
                  </button>
                );
              })}
            </div>
            <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>Needs accounting attention <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>(sales missing, wFirma not prepared, or PZ not yet generated)</span></div>
              {!loading && acctAttention.length === 0 && <div style={{ fontSize: 11, color: 'var(--text-3)', padding: '4px 0' }}>No batches need accounting attention.</div>}
              {!loading && acctAttention.length > 0 && (
                <table data-testid="sales-accounting-operations-attention-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <thead><tr>{['Shipment', 'Sales', 'wFirma', 'PZ', 'Last activity'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', fontSize: 10, letterSpacing: '0.04em' }}>{h}</th>
                  ))}</tr></thead>
                  <tbody>
                    {acctAttention.slice(0, 25).map(row => (
                      <tr key={row.id}>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                          <button onClick={() => onViewShipment(row._raw || row)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--badge-blue-text)', fontSize: 11, fontWeight: 600, fontFamily: 'monospace', textDecoration: 'underline', textDecorationStyle: 'dotted', padding: 0 }}>{row.awb}</button>
                          {row.doc_no && <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 1 }}>{row.doc_no}</div>}
                        </td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: acctSalesMissing(row) ? 'var(--badge-red-bg)' : 'var(--badge-green-bg)', color: acctSalesMissing(row) ? 'var(--badge-red-text)' : 'var(--badge-green-text)', border: `1px solid ${acctSalesMissing(row) ? 'var(--badge-red-border)' : 'var(--badge-green-border)'}`, display: 'inline-block', whiteSpace: 'nowrap' }}>{acctSalesLabel(row)}</span>
                        </td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: acctWfirmaMissing(row) ? 'var(--badge-amber-bg)' : 'var(--badge-blue-bg)', color: acctWfirmaMissing(row) ? 'var(--badge-amber-text)' : 'var(--badge-blue-text)', border: `1px solid ${acctWfirmaMissing(row) ? 'var(--badge-amber-border)' : 'var(--badge-blue-border)'}`, display: 'inline-block', whiteSpace: 'nowrap' }}>{acctWfirmaLabel(row)}</span>
                        </td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: acctPzPending(row) ? 'var(--badge-amber-bg)' : 'var(--badge-green-bg)', color: acctPzPending(row) ? 'var(--badge-amber-text)' : 'var(--badge-green-text)', border: `1px solid ${acctPzPending(row) ? 'var(--badge-amber-border)' : 'var(--badge-green-border)'}`, display: 'inline-block', whiteSpace: 'nowrap' }}>{row.pzStatus || '—'}</span>
                        </td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-3)', fontFamily: 'monospace' }}>{row.timestamp || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {!loading && acctAttention.length > 25 && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 6 }}>Showing first 25 of {acctAttention.length}. Use the shipments table below to scroll the full list.</div>}
            </div>
          </Card>
        );
      })()}

      {/* ── DHL & Customs Operations card ──────────────────────────────── */}
      {viewMode === 'active' && (() => {
        const dcBucketLabel = {
          awaiting_customs_docs: 'Awaiting customs docs', sad_present: 'SAD present', sad_missing: 'SAD missing',
          customs_cleared: 'Customs cleared', dhl_in_transit: 'DHL in transit', dhl_delivered: 'DHL delivered',
        };
        const dcBucketTone = {
          awaiting_customs_docs: { bg: 'var(--badge-red-bg)', text: 'var(--badge-red-text)', border: 'var(--badge-red-border)' },
          sad_present: { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)' },
          sad_missing: { bg: 'var(--badge-amber-bg)', text: 'var(--badge-amber-text)', border: 'var(--badge-amber-border)' },
          customs_cleared: { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)' },
          dhl_in_transit: { bg: 'var(--badge-blue-bg)', text: 'var(--badge-blue-text)', border: 'var(--badge-blue-border)' },
          dhl_delivered: { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)' },
        };
        const dcRawDhl = (row) => (row._raw && row._raw.dhl_status) || '';
        const dcTrackKey = (row) => (row._raw && row._raw.tracking_status_key) || '';
        const dcTrackLabel = (row) => (row._raw && row._raw.tracking_status) || '';
        const dcDhlActionPending = (row) => dcRawDhl(row) === 'dhl_email_received';
        const dcCounts = {
          awaiting_customs_docs: all.filter(_SH_OP_PREDICATES.dhl_customs.awaiting_customs_docs).length,
          sad_present: all.filter(_SH_OP_PREDICATES.dhl_customs.sad_present).length,
          sad_missing: all.filter(_SH_OP_PREDICATES.dhl_customs.sad_missing).length,
          customs_cleared: all.filter(_SH_OP_PREDICATES.dhl_customs.customs_cleared).length,
          dhl_in_transit: all.filter(_SH_OP_PREDICATES.dhl_customs.dhl_in_transit).length,
          dhl_delivered: all.filter(_SH_OP_PREDICATES.dhl_customs.dhl_delivered).length,
        };
        const dcAttention = all.filter(_SH_ATTENTION_PREDICATES.dhl_customs)
          .sort((a, b) => { const at = a.timestamp || ''; const bt = b.timestamp || ''; return at < bt ? 1 : at > bt ? -1 : 0; });
        return (
          <Card data-testid="dhl-customs-operations-card" style={{ padding: 16, marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>📨 DHL &amp; Customs Operations</div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>Cross-batch DHL / SAD / tracking status — derived read-only from the batch-list payload. Open a batch for full detail.</div>
              </div>
            </div>
            <div data-testid="dhl-customs-operations-buckets" style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8, marginBottom: 14 }}>
              {['awaiting_customs_docs', 'sad_missing', 'sad_present', 'customs_cleared', 'dhl_in_transit', 'dhl_delivered'].map(key => {
                const tone = dcBucketTone[key];
                const active = isOpActive('dhl_customs', key);
                return (
                  <button key={key} type="button" data-testid={`dhl-customs-operations-bucket-${key}`} data-op-active={active ? 'true' : 'false'} aria-pressed={active}
                    onClick={() => toggleOpFilter('dhl_customs', key, dcBucketLabel[key])}
                    title={active ? 'Click to clear operational filter' : `Filter the shipments table by ${dcBucketLabel[key]}`}
                    style={{ textAlign: 'left', padding: '10px 12px', border: `${active ? 2 : 1}px solid ${active ? 'var(--accent)' : tone.border}`, background: tone.bg, borderRadius: 6, cursor: 'pointer', fontFamily: 'inherit', boxShadow: active ? '0 0 0 2px var(--accent-subtle)' : 'none' }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: tone.text, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{dcBucketLabel[key]}</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: tone.text, fontFamily: '"DM Serif Display",serif', marginTop: 2 }}>{loading ? '…' : dcCounts[key]}</div>
                  </button>
                );
              })}
            </div>
            <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>Needs customs attention <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>(SAD missing, customs unresolved, or tracking exception)</span></div>
              {!loading && dcAttention.length === 0 && <div style={{ fontSize: 11, color: 'var(--text-3)', padding: '4px 0' }}>No batches need customs attention.</div>}
              {!loading && dcAttention.length > 0 && (
                <table data-testid="dhl-customs-operations-attention-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <thead><tr>{['Shipment', 'DHL Status', 'SAD', 'MRN', 'Tracking', 'Last activity'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', fontSize: 10, letterSpacing: '0.04em' }}>{h}</th>
                  ))}</tr></thead>
                  <tbody>
                    {dcAttention.slice(0, 25).map(row => {
                      const trackKey = dcTrackKey(row);
                      const trackLbl = dcTrackLabel(row) || (trackKey || '—');
                      const sadTone = row.has_sad ? 'var(--badge-green' : 'var(--badge-red';
                      const trackTone = trackKey === 'delivered' ? 'var(--badge-green' : trackKey === 'in_transit' ? 'var(--badge-blue' : _SH_TRACK_ATTENTION.has(trackKey) ? 'var(--badge-red' : 'var(--badge-neutral';
                      return (
                        <tr key={row.id}>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                            <button onClick={() => onViewShipment(row._raw || row)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--badge-blue-text)', fontSize: 11, fontWeight: 600, fontFamily: 'monospace', textDecoration: 'underline', textDecorationStyle: 'dotted', padding: 0 }}>{row.awb}</button>
                            {row.doc_no && <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 1 }}>{row.doc_no}</div>}
                          </td>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                            <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: dcDhlActionPending(row) ? 'var(--badge-amber-bg)' : 'var(--badge-neutral-bg)', color: dcDhlActionPending(row) ? 'var(--badge-amber-text)' : 'var(--badge-neutral-text)', border: `1px solid ${dcDhlActionPending(row) ? 'var(--badge-amber-border)' : 'var(--badge-neutral-border)'}`, display: 'inline-block', whiteSpace: 'nowrap' }}>{row.dhlStatus || '—'}</span>
                          </td>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                            <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: `${sadTone}-bg)`, color: `${sadTone}-text)`, border: `1px solid ${sadTone}-border)`, display: 'inline-block', whiteSpace: 'nowrap' }}>{row.sadStatus || '—'}</span>
                          </td>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-2)', fontFamily: 'monospace', fontSize: 10 }}>{row.mrn && row.mrn !== '—' ? row.mrn : '—'}</td>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                            <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: `${trackTone}-bg)`, color: `${trackTone}-text)`, border: `1px solid ${trackTone}-border)`, display: 'inline-block', whiteSpace: 'nowrap' }}>{trackLbl}</span>
                          </td>
                          <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-3)', fontFamily: 'monospace' }}>{row.timestamp || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
              {!loading && dcAttention.length > 25 && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 6 }}>Showing first 25 of {dcAttention.length}. Use the shipments table below to scroll the full list.</div>}
            </div>
          </Card>
        );
      })()}

      {/* ── Archived view ───────────────────────────────────────────────── */}
      {viewMode === 'archived' && (
        <Card style={{ overflow: 'hidden' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>Archived Shipments</span>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>— kept for 14 days, then eligible for permanent deletion</span>
          </div>
          {archivedLoading && <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>Loading archived shipments…</div>}
          {!archivedLoading && archived.length === 0 && <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>No archived shipments</div>}
          {!archivedLoading && archived.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>{['AWB / Batch', 'Carrier', 'Status', 'Archived At', 'Expires In', 'Reason', 'Actions'].map(h => (
                    <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}</tr>
                </thead>
                <tbody>
                  {archived.map(row => {
                    const archivedAt = row.archived_at ? new Date(row.archived_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
                    const deleteAfter = row.delete_after ? new Date(row.delete_after) : null;
                    const daysLeft = deleteAfter ? Math.ceil((deleteAfter - new Date()) / 86400000) : null;
                    const expired = daysLeft !== null && daysLeft <= 0;
                    const expiresLabel = daysLeft === null ? '—' : expired ? '⚠ Expired' : `${daysLeft}d remaining`;
                    const bKey = row.batch_id;
                    return (
                      <tr key={bKey}
                        onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                        style={{ borderBottom: '1px solid var(--border-subtle)', transition: 'background 0.1s' }}>
                        <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text)' }}>{row.awb || bKey}</td>
                        <td style={{ padding: '10px 12px', color: 'var(--text-2)' }}>{row.carrier || '—'}</td>
                        <td style={{ padding: '10px 12px' }}><Badge status={row.status} small /></td>
                        <td style={{ padding: '10px 12px', color: 'var(--text-2)', whiteSpace: 'nowrap' }}>{archivedAt}</td>
                        <td style={{ padding: '10px 12px', whiteSpace: 'nowrap', color: expired ? 'var(--badge-red-text)' : (daysLeft !== null && daysLeft <= 3) ? 'var(--badge-orange-text)' : 'var(--text-2)', fontWeight: expired ? 700 : 400 }}>{expiresLabel}</td>
                        <td style={{ padding: '10px 12px', color: 'var(--text-3)', fontSize: 11, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={row.reason}>{row.reason || '—'}</td>
                        <td style={{ padding: '8px 12px' }}>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <Btn small variant="outline" disabled={!!archiveBusy[bKey]}
                              onClick={async () => {
                                if (!window.confirm(`Restore shipment ${row.awb || bKey} to the active dashboard?`)) return;
                                setArchiveBusy(s => ({ ...s, [bKey]: true }));
                                try {
                                  await _shRestoreBatch(bKey);
                                  await loadArchived(); load();
                                  if (onToast) onToast('Shipment restored to active dashboard.', 'success');
                                } catch (e) {
                                  if (onToast) onToast(`Restore failed: ${e.message}`, 'error');
                                }
                                setArchiveBusy(s => ({ ...s, [bKey]: false }));
                              }}>{archiveBusy[bKey] ? '…' : 'Restore'}</Btn>
                            <Btn small variant="ghost" disabled={!!archiveBusy[bKey]} style={{ color: 'var(--badge-red-text)', borderColor: 'var(--badge-red-border)' }}
                              onClick={async () => {
                                if (!window.confirm(`PERMANENTLY DELETE shipment ${row.awb || bKey}?\n\nThis will permanently delete all archived files.\nThis action cannot be undone.`)) return;
                                if (!window.confirm(`Confirm: permanently delete ${row.awb || bKey}? There is no recovery after this.`)) return;
                                setArchiveBusy(s => ({ ...s, [bKey]: true }));
                                try {
                                  await _shPermanentlyDeleteArchived(bKey);
                                  await loadArchived();
                                  if (onToast) onToast('Shipment permanently deleted.', 'success');
                                } catch (e) {
                                  if (onToast) onToast(`Delete failed: ${e.message}`, 'error');
                                }
                                setArchiveBusy(s => ({ ...s, [bKey]: false }));
                              }}>Delete permanently</Btn>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text-3)' }}>{archived.length} archived shipment(s)</div>
        </Card>
      )}

      {/* ── Active shipments table ──────────────────────────────────────── */}
      {viewMode === 'active' && (
        <Card data-testid="shipments-hub-table-card" style={{ overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto', width: '100%' }}>
            <table data-testid="shipments-hub-table" style={{ minWidth: 1900, borderCollapse: 'collapse', fontSize: 12, tableLayout: 'fixed' }}>
              <colgroup>
                <col style={{ width: 200 }} />{/* AWB */}
                <col style={{ width: 110 }} />{/* Upload Date */}
                <col style={{ width: 100 }} />{/* Visa Date */}
                <col style={{ width: 130 }} />{/* Visa Generated Date */}
                <col style={{ width: 90 }} />{/* Carrier */}
                <col style={{ width: 170 }} />{/* DHL Status */}
                <col style={{ width: 140 }} />{/* SAD Status */}
                <col style={{ width: 160 }} />{/* MRN */}
                <col style={{ width: 120 }} />{/* PZ Status */}
                <col style={{ width: 100 }} />{/* Warehouse */}
                <col style={{ width: 90 }} />{/* Sales */}
                <col style={{ width: 100 }} />{/* wFirma */}
                <col style={{ width: 100 }} />{/* Net */}
                <col style={{ width: 100 }} />{/* Gross */}
                <col style={{ width: 100 }} />{/* Duty A00 */}
                <col style={{ width: 150 }} />{/* Overall */}
                <col style={{ width: 170 }} />{/* Actions */}
              </colgroup>
              <thead>
                <tr>
                  <TH col="awb">AWB / Tracking</TH>
                  <TH col="list_date">Upload Date</TH>
                  <TH title="No Visa Date authority in shipment list">Visa Date</TH>
                  <TH title="No Visa Generated Date authority in shipment list">Visa Generated Date</TH>
                  <TH col="carrier">Carrier</TH>
                  <TH col="dhlStatus">DHL Status</TH>
                  <TH col="sadStatus">SAD Status</TH>
                  <TH col="mrn">MRN</TH>
                  <TH col="pzStatus">PZ Status</TH>
                  <TH col="warehouseHint">Warehouse</TH>
                  <TH col="salesHint">Sales</TH>
                  <TH col="wfirmaHint">wFirma</TH>
                  <TH col="net">Net</TH>
                  <TH col="gross">Gross</TH>
                  <TH col="duty">Duty A00</TH>
                  <TH col="overall">Overall</TH>
                  <th style={{ padding: '10px 12px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)', position: 'sticky', right: 0, zIndex: 3, boxShadow: '-2px 0 6px rgba(0,0,0,0.06)' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && <tr><td colSpan={17} style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>Loading shipments…</td></tr>}
                {!loading && sorted.length === 0 && (
                  <tr><td colSpan={17} style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }} data-testid="shipments-hub-empty-state">
                    No shipments found{opFilter ? <span> — operational filter <b>{opFilter.label}</b> is active. <a onClick={clearOpFilter} style={{ color: 'var(--badge-blue-text)', cursor: 'pointer', textDecoration: 'underline' }}>clear filter</a></span> : null}
                  </td></tr>
                )}
                {!loading && paginated.map(row => {
                  const dhlShortLabels = {
                    'Awaiting DHL Email': 'Awaiting DHL', 'DHL Email Received': 'Email Received',
                    'Reply Package Prepared': 'Pkg Prepared', 'Pre-check Pending': 'Pre-check ⏳',
                    'Pre-check Completed': 'Pre-check ✓', 'Reply Queued': 'Reply Queued', 'Reply Sent': 'Reply Sent',
                  };
                  const dhlShort = dhlShortLabels[row.dhlStatus] || row.dhlStatus;
                  const sm = (window.STATUS_MAP || {})[row.dhlStatus] || { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' };
                  const trackUrl = _shSafeHttpUrl(row.tracking_url);
                  const uploadRaw = row.uploaded_at || row.timestamp;
                  const uploadDisplay = _shFmtDate(row.uploaded_at) || _shFmtDate(row.timestamp) || '—';
                  const uploadTitle = row.uploaded_at ? 'inputs.uploaded_at (intake stamp)' : row.timestamp ? 'audit.timestamp (creation/activity proxy)' : undefined;
                  const whMap = {
                    clean: { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)', label: 'Clean' },
                    partial: { bg: 'var(--badge-amber-bg)', text: 'var(--badge-amber-text)', border: 'var(--badge-amber-border)', label: 'Partial' },
                    empty: { bg: 'var(--badge-red-bg)', text: 'var(--badge-red-text)', border: 'var(--badge-red-border)', label: 'Empty' },
                    'n/a': { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)', label: '—' },
                  };
                  const salesMap = {
                    present: { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)', label: 'Linked' },
                    none: { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)', label: '—' },
                    'n/a': { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)', label: '—' },
                  };
                  const wfirmaMap = {
                    preview_built: { bg: 'var(--badge-blue-bg)', text: 'var(--badge-blue-text)', border: 'var(--badge-blue-border)', label: 'Preview' },
                    none: { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)', label: '—' },
                    'n/a': { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)', label: '—' },
                  };
                  const wh = whMap[row.warehouseHint] || whMap['n/a'];
                  const sl = salesMap[row.salesHint] || salesMap['n/a'];
                  const wf = wfirmaMap[row.wfirmaHint] || wfirmaMap['n/a'];
                  return (
                    <tr key={row.id}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      style={{ borderBottom: '1px solid var(--border-subtle)', transition: 'background 0.1s' }}>
                      <td style={{ padding: '10px 12px', overflow: 'hidden' }}>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                          <button onClick={() => onViewShipment(row._raw || row)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--badge-blue-text)', fontSize: 12, fontWeight: 600, fontFamily: 'monospace', textDecoration: 'underline', textDecorationStyle: 'dotted', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>{row.awb}</button>
                          {trackUrl && (
                            <a href={trackUrl} target="_blank" rel="noopener noreferrer" title={row.tracking_label || 'Open carrier tracking'} onClick={e => e.stopPropagation()} style={{ color: 'var(--text-3)', fontSize: 11, flexShrink: 0 }}>↗</a>
                          )}
                        </div>
                        {row.doc_no && <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.doc_no}</div>}
                      </td>
                      <td style={{ padding: '10px 12px', color: 'var(--text-2)', fontSize: 11, whiteSpace: 'nowrap' }} title={uploadTitle}>{uploadDisplay}</td>
                      <td style={{ padding: '10px 12px', color: 'var(--text-3)' }} title="No Visa Date authority in shipment list">—</td>
                      <td style={{ padding: '10px 12px', color: 'var(--text-3)' }} title="No Visa Generated Date authority in shipment list">—</td>
                      <td style={{ padding: '10px 12px' }}>
                        <span style={{ display: 'inline-block', padding: '1px 6px', background: row.carrier === 'DHL' ? 'var(--badge-blue-bg)' : row.carrier === 'FedEx' ? 'var(--badge-purple-bg)' : 'var(--badge-neutral-bg)', borderRadius: 4, fontSize: 10, fontWeight: 700, color: row.carrier === 'DHL' ? 'var(--badge-blue-text)' : row.carrier === 'FedEx' ? 'var(--badge-purple-text)' : 'var(--badge-neutral-text)', whiteSpace: 'nowrap' }}>{row.carrier}</span>
                      </td>
                      <td style={{ padding: '10px 12px', overflow: 'hidden' }}>
                        <span title={row.dhlStatus} style={{ display: 'inline-block', padding: '2px 7px', background: sm.bg, color: sm.text, border: `1px solid ${sm.border}`, borderRadius: 4, fontSize: 10, fontWeight: 600, whiteSpace: 'nowrap', maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }}>{dhlShort}</span>
                      </td>
                      <td style={{ padding: '10px 12px', overflow: 'hidden' }}><Badge status={row.sadStatus} small /></td>
                      <td style={{ padding: '10px 12px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.mrn}</td>
                      <td style={{ padding: '10px 12px', overflow: 'hidden' }}><Badge status={row.pzStatus} small /></td>
                      <td style={{ padding: '10px 12px', overflow: 'hidden' }}><span title={`warehouse: ${row.warehouseHint}`} style={{ display: 'inline-block', padding: '2px 7px', background: wh.bg, color: wh.text, border: `1px solid ${wh.border}`, borderRadius: 4, fontSize: 10, fontWeight: 700, whiteSpace: 'nowrap' }}>{wh.label}</span></td>
                      <td style={{ padding: '10px 12px', overflow: 'hidden' }}><span title={`sales: ${row.salesHint}`} style={{ display: 'inline-block', padding: '2px 7px', background: sl.bg, color: sl.text, border: `1px solid ${sl.border}`, borderRadius: 4, fontSize: 10, fontWeight: 700, whiteSpace: 'nowrap' }}>{sl.label}</span></td>
                      <td style={{ padding: '10px 12px', overflow: 'hidden' }}><span title={`wfirma: ${row.wfirmaHint}`} style={{ display: 'inline-block', padding: '2px 7px', background: wf.bg, color: wf.text, border: `1px solid ${wf.border}`, borderRadius: 4, fontSize: 10, fontWeight: 700, whiteSpace: 'nowrap' }}>{wf.label}</span></td>
                      <td style={{ padding: '10px 12px', color: 'var(--text)', fontWeight: 500, textAlign: 'right', whiteSpace: 'nowrap' }}>{_money(row.net)}</td>
                      <td style={{ padding: '10px 12px', color: 'var(--text)', fontWeight: 500, textAlign: 'right', whiteSpace: 'nowrap' }}>{_money(row.gross)}</td>
                      <td style={{ padding: '10px 12px', color: 'var(--accent)', fontWeight: 700, textAlign: 'right', whiteSpace: 'nowrap' }}>{_money(row.duty)}</td>
                      <td style={{ padding: '10px 12px', overflow: 'hidden' }}><Badge status={row.overall} small title={row.overall === 'Action Required' && row.action_reason ? row.action_reason : undefined} /></td>
                      <td style={{ padding: '8px 10px', position: 'sticky', right: 0, background: 'var(--card)', zIndex: 2, boxShadow: '-2px 0 6px rgba(0,0,0,0.06)' }}>
                        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'nowrap' }}>
                          <Btn small variant="outline" data-testid="shipments-hub-row-view" onClick={() => onViewShipment(row._raw || row)} title="View shipment detail">View</Btn>
                          {row.overall === 'Draft' && (
                            <Btn small variant="ghost" onClick={() => onViewShipment(row._raw || row)} title="Edit draft">Edit</Btn>
                          )}
                          <div style={{ position: 'relative' }}>
                            <Btn small variant="ghost" data-testid="shipments-hub-row-menu" onClick={() => setActionMenu(actionMenu === row.id ? null : row.id)} title="More actions">⋯</Btn>
                            {actionMenu === row.id && (
                              <div style={{ position: 'absolute', right: 0, top: '100%', zIndex: 200, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, boxShadow: '0 4px 16px var(--shadow-heavy)', minWidth: 190, overflow: 'hidden' }}>
                                {[
                                  { label: 'Open in New Tab', color: 'var(--text)', fn: () => window.open('/v2/shipments?batch_id=' + encodeURIComponent(row.id), '_blank') },
                                  { label: 'Recheck Parsed Data', color: 'var(--badge-blue-text)', fn: () => doRecheck(row) },
                                  { label: 'Archive', color: 'var(--badge-red-text)', fn: () => doArchive(row) },
                                ].map(({ label, color, fn }) => (
                                  <button key={label} onClick={() => { setActionMenu(null); fn(); }} style={{ display: 'block', width: '100%', padding: '8px 14px', textAlign: 'left', background: 'none', border: 'none', fontSize: 12, cursor: 'pointer', color, fontFamily: 'inherit' }}
                                    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-subtle)'}
                                    onMouseLeave={e => e.currentTarget.style.background = 'none'}>{label}</button>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                        {recheckState[row.id] === 'pending' && <div style={{ marginTop: 4, fontSize: 10, color: 'var(--badge-blue-text)' }}>⟳ Rechecking…</div>}
                        {recheckState[row.id] === 'done' && recheckResult[row.id] && (
                          <div style={{ marginTop: 4, padding: '4px 6px', background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 4 }}>
                            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--badge-green-text)', marginBottom: 2 }}>✓ Recheck complete</div>
                            {Object.entries((recheckResult[row.id] && recheckResult[row.id].updated) || {}).filter(([, v]) => v).map(([k]) => (
                              <div key={k} style={{ fontSize: 9, color: 'var(--badge-green-text)' }}>• {k.replace(/_/g, ' ')} updated</div>
                            ))}
                            {((recheckResult[row.id] && recheckResult[row.id].warnings) || []).map((w, i) => (
                              <div key={i} style={{ fontSize: 9, color: 'var(--badge-amber-text)' }}>⚠ {w}</div>
                            ))}
                          </div>
                        )}
                        {recheckState[row.id] === 'error' && recheckResult[row.id] && (
                          <div style={{ marginTop: 4, padding: '4px 6px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 4 }}>
                            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--badge-red-text)' }}>✗ Recheck failed</div>
                            {((recheckResult[row.id] && recheckResult[row.id].errors) || []).map((e, i) => (
                              <div key={i} style={{ fontSize: 9, color: 'var(--badge-red-text)' }}>{e}</div>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div data-testid="shipments-hub-pagination" style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
              {sorted.length === 0
                ? 'No shipments match filters'
                : `Showing ${pageStart + 1}-${pageEnd} of ${sorted.length}${sorted.length !== all.length ? ` (filtered from ${all.length})` : ''} shipments`}
            </span>
            {sorted.length > PAGE_SIZE && (
              <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <Btn small variant="outline" disabled={safePage <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>← Prev</Btn>
                <span style={{ fontSize: 11, color: 'var(--text-2)', padding: '0 8px', fontFamily: 'monospace' }}>{safePage} / {totalPages}</span>
                <Btn small variant="outline" disabled={safePage >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>Next →</Btn>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

Object.assign(window, { DashboardPage });
