// ─────────────────────────────────────────────────────────────────────────────
// DashboardKanban — workflow-first operational cockpit (Sprint 40).
// Live pipeline board: every batch from GET /api/v1/dashboard/batches is placed
// into the lane matching its PZ workflow stage. One-glance situational awareness.
//
// Authority owner: routes_dashboard.py → _batch_summary() → operational_authority.py
// Transport:       PzApi.listBatches()  → GET /api/v1/dashboard/batches
//
// Lane derivation + status mappers ported from V1 production dashboard.html
// (proven live since Sprint 32). No invented data; empty lanes show "—".
//
// Sprint 40 (2026-06-07): full rewrite from MOCK to authority-honest.
//   - DELETED: PIPELINE_SHIPMENTS (15 fake shipments)
//   - DELETED: fake client names, AWBs, values, ages, lane assignments
//   - ADDED: live fetch, transformBatch, _batchLane, status mappers from V1
//   - CORRECTED: lanes from generic shipping to PZ accounting workflow
//   - KPIs: Active, Urgent, Awaiting DHL, Awaiting SAD, Ready to book
// ─────────────────────────────────────────────────────────────────────────────

const { useState, useEffect } = React;

// ═══════════════════════════════════════════════════════════════════════════
// LANES — PZ accounting workflow (matches V1 production)
// ═══════════════════════════════════════════════════════════════════════════

const KANBAN_LANES = [
  { id: 'new',     label: 'New / Drafting',     hint: 'no PI yet',                color: 'var(--badge-neutral-text)', bg: 'var(--badge-neutral-bg)',  border: 'var(--badge-neutral-border)' },
  { id: 'docs',    label: 'Awaiting Documents', hint: 'DHL · SAD pending',        color: 'var(--badge-amber-text)',   bg: 'var(--badge-amber-bg)',    border: 'var(--badge-amber-border)' },
  { id: 'customs', label: 'Customs Clearance',  hint: 'SAD · ZC429 in progress',  color: 'var(--badge-red-text)',     bg: 'var(--badge-red-bg)',      border: 'var(--badge-red-border)' },
  { id: 'ready',   label: 'Ready for PZ',       hint: 'verified · awaiting PZ',   color: 'var(--badge-purple-text)',  bg: 'var(--badge-purple-bg)',   border: 'var(--badge-purple-border)' },
  { id: 'booked',  label: 'PZ Generated',       hint: 'awaiting wFirma export',   color: 'var(--badge-blue-text)',    bg: 'var(--badge-blue-bg)',     border: 'var(--badge-blue-border)' },
  { id: 'done',    label: 'Exported',           hint: 'wFirma booked · closed',   color: 'var(--badge-green-text)',   bg: 'var(--badge-green-bg)',    border: 'var(--badge-green-border)' },
];

// ═══════════════════════════════════════════════════════════════════════════
// QUICK FLOWS — real navigation CTAs
// ═══════════════════════════════════════════════════════════════════════════

const QUICK_FLOWS = [
  { id: 'inbound',  icon: '📥', label: 'Receive shipment',  hint: 'Inbound · PZ · SAD',     color: 'var(--badge-blue-text)',   bg: 'var(--badge-blue-bg)',   border: 'var(--badge-blue-border)' },
  { id: 'outbound', icon: '📤', label: 'New shipment',       hint: 'AWB · Invoice · Pack',    color: 'var(--accent)',            bg: 'var(--accent-subtle)',   border: 'var(--accent-border)' },
  { id: 'email',    icon: '✉',  label: 'Scan DHL inbox',     hint: 'Parse · Match · Reply',   color: 'var(--badge-purple-text)', bg: 'var(--badge-purple-bg)', border: 'var(--badge-purple-border)' },
  { id: 'pz',       icon: '⊞', label: 'Generate PZ',        hint: 'Verify · Generate · Send',color: 'var(--badge-green-text)',  bg: 'var(--badge-green-bg)',  border: 'var(--badge-green-border)' },
];

// ═══════════════════════════════════════════════════════════════════════════
// STATUS MAPPERS — ported from V1 dashboard.html (production-proven)
// ═══════════════════════════════════════════════════════════════════════════

function _mapOverall(status) {
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

function _mapDhlStatus(s) {
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

function _mapSadStatus(s) {
  if (!s) return 'SAD Pending';
  const m = {
    sad_pending:          'SAD Pending',
    sad_uploaded:         'SAD Uploaded',
    customs_parsed:       'Customs Parsed',
    customs_verified:     'Customs Verified',
    verification_needed:  'Verification Needed',
    missing:              'SAD Pending',
    uploaded:             'SAD Uploaded',
    uploaded_parsed:      'Customs Parsed',
  };
  return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function _mapPzStatus(s) {
  if (!s) return 'Locked';
  const m = { locked: 'Locked', ready: 'Ready for PZ', generated: 'Generated', exported: 'Exported', complete: 'Exported' };
  return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function _fmtPLN(v) {
  if (v == null || v === '' || v === 0) return '—';
  return Number(v).toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ═══════════════════════════════════════════════════════════════════════════
// transformBatch — raw API batch → card-friendly shape (from V1)
// ═══════════════════════════════════════════════════════════════════════════

function _transformBatch(b) {
  return {
    id:        b.batch_id,
    batch_id:  b.batch_id,
    awb:       b.tracking_no || b.doc_no || b.batch_id,
    carrier:   b.carrier || '—',
    dhlStatus: _mapDhlStatus(b.dhl_status),
    sadStatus: _mapSadStatus(b.sad_status),
    mrn:       b.mrn || '—',
    pzStatus:  _mapPzStatus(b.pz_status),
    net:       _fmtPLN(b.net),
    gross:     _fmtPLN(b.gross),
    duty:      _fmtPLN(b.duty),
    overall:   _mapOverall(b.status),
    action_reason: b.action_reason || '',
    doc_no:    b.doc_no || '',
    timestamp: b.timestamp || '',
    has_sad:   b.has_sad,
    invoice_refs: b.invoice_refs || [],
    warehouseHint: b.warehouse_status_hint || 'n/a',
    salesHint:     b.sales_status_hint || 'n/a',
    wfirmaHint:    b.wfirma_status_hint || 'n/a',
    _raw:      b,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// _batchLane — derive pipeline lane from batch status (from V1 production)
// ═══════════════════════════════════════════════════════════════════════════

function _batchLane(b) {
  const pz      = (b.pzStatus || '').toString();
  const sad     = (b.sadStatus || '').toString();
  const dhl     = (b.dhlStatus || '').toString();
  const overall = (b.overall || '').toString();
  if (pz === 'Exported' || overall === 'Completed') return 'done';
  if (pz === 'Generated' || overall === 'Ready for Booking') return 'booked';
  if (pz === 'Ready for PZ' || overall === 'Ready for PZ' || sad === 'Customs Verified') return 'ready';
  if (sad === 'SAD Uploaded' || sad === 'Customs Parsed' || sad === 'Verification Needed' || overall === 'Awaiting Clearance') return 'customs';
  if (dhl === 'DHL Email Received' || dhl === 'Reply Sent' || dhl === 'Reply Queued' || dhl === 'Reply Package Prepared' || overall === 'Awaiting SAD' || overall === 'Awaiting DHL' || sad === 'SAD Pending') return 'docs';
  return 'new';
}

// ═══════════════════════════════════════════════════════════════════════════
// _fmtAge — human-readable age from timestamp (from V1)
// ═══════════════════════════════════════════════════════════════════════════

function _fmtAge(ts) {
  if (!ts) return '';
  const t = new Date(ts).getTime();
  if (isNaN(t)) return '';
  const diffMs = Date.now() - t;
  if (diffMs < 0) return '';
  const m = Math.floor(diffMs / 60000);
  if (m < 60) return m + 'm';
  const h = Math.floor(m / 60);
  if (h < 24) return h + 'h';
  const d = Math.floor(h / 24);
  if (d < 30) return d + 'd';
  const mo = Math.floor(d / 30);
  return mo + 'mo';
}

function _shortId(s) {
  if (!s) return '';
  const parts = String(s).split('_');
  if (parts.length >= 4) return parts.slice(2).join('-');
  return String(s).slice(-12);
}

// ═══════════════════════════════════════════════════════════════════════════
// KanbanCard — single batch card (authority-honest, from live data)
// ═══════════════════════════════════════════════════════════════════════════

function KanbanCard({ batch, onClick }) {
  const isUrgent = (batch.overall === 'Action Required' || batch.sadStatus === 'Verification Needed');
  const isHigh   = (batch.overall === 'Awaiting DHL' || batch.overall === 'Awaiting SAD');
  const age      = _fmtAge(batch.timestamp);
  const raw      = batch._raw || {};
  const invCount = Array.isArray(batch.invoice_refs) ? batch.invoice_refs.length : 0;
  return (
    <button data-testid="kanban-card" onClick={onClick} style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 5, padding: '8px 10px', cursor: 'pointer', textAlign: 'left',
      borderLeft: isUrgent ? '3px solid var(--badge-red-text)' : isHigh ? '3px solid var(--badge-amber-text)' : '1px solid var(--border)',
      transition: 'transform 0.12s, box-shadow 0.12s',
      display: 'flex', flexDirection: 'column', gap: 4, width: '100%',
      fontFamily: 'inherit',
    }}
      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = '0 3px 10px var(--shadow)'; }}
      onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none'; }}>
      {/* Top row: short id · age */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{
          fontSize: 9, padding: '0px 4px', borderRadius: 2,
          background: 'var(--badge-blue-bg)', color: 'var(--badge-blue-text)',
          border: '1px solid var(--badge-blue-border)',
          fontWeight: 700, letterSpacing: '0.04em',
        }}>IN</span>
        <span style={{ fontSize: 10.5, fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{_shortId(batch.batch_id)}</span>
        <span style={{ flex: 1 }} />
        {age && <span style={{ fontSize: 9.5, color: 'var(--text-3)' }}>{age}</span>}
      </div>
      {/* Title row: doc_no or AWB */}
      <div style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {batch.doc_no || batch.awb || batch.batch_id}
      </div>
      {/* Meta row: carrier · invoices · net value */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 9.5, color: 'var(--text-3)', flexWrap: 'wrap' }}>
        <span style={{ fontFamily: 'monospace' }}>{batch.carrier || '—'}</span>
        {invCount > 0 && <><span>&middot;</span><span>{invCount} inv</span></>}
        {batch.net && batch.net !== '—' && <><span>&middot;</span><span style={{ fontFamily: 'monospace' }}>{batch.net}</span></>}
      </div>
      {/* Flag row: urgent / high */}
      {(isUrgent || isHigh) && (
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 2,
          fontSize: 9.5, fontWeight: 600,
          color: isUrgent ? 'var(--badge-red-text)' : 'var(--badge-amber-text)',
        }}>
          <span>{isUrgent ? '⚠' : '◐'}</span>
          <span>{batch.action_reason || (isUrgent ? 'needs attention' : batch.overall)}</span>
        </div>
      )}
    </button>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// KanbanLane — single lane column
// ═══════════════════════════════════════════════════════════════════════════

function KanbanLane({ lane, cards, onCardClick }) {
  return (
    <div data-testid="kanban-lane" style={{ display: 'flex', flexDirection: 'column', minWidth: 220, background: 'var(--bg-subtle)', borderRadius: 8, border: '1px solid var(--border)' }}>
      <div style={{ padding: '10px 12px', borderBottom: '2px solid ' + lane.border, background: lane.bg, borderRadius: '8px 8px 0 0' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 2 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: lane.color, letterSpacing: '0.02em' }}>{lane.label}</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: lane.color, fontFamily: 'monospace' }}>{cards.length}</span>
        </div>
        <div style={{ fontSize: 9.5, color: lane.color, opacity: 0.75 }}>{lane.hint}</div>
      </div>
      <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 6, minHeight: 200, maxHeight: 480, overflowY: 'auto' }}>
        {cards.length === 0 && <div style={{ padding: 16, textAlign: 'center', fontSize: 10.5, color: 'var(--text-3)', fontStyle: 'italic' }}>{'—'}</div>}
        {cards.map(c => <KanbanCard key={c.batch_id || c.id} batch={c} onClick={() => onCardClick && onCardClick(c)} />)}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// CompactKpi — single KPI tile (presentational, no data dependency)
// ═══════════════════════════════════════════════════════════════════════════

function CompactKpi({ label, value, hint, accent }) {
  return (
    <div data-testid="compact-kpi" style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 14px' }}>
      <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent || 'var(--text)', marginTop: 4, fontFamily: '"DM Serif Display", serif' }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// DashboardKanban — main component (fetches live data)
// ═══════════════════════════════════════════════════════════════════════════

function DashboardKanban({ onNav, onOpenNewShipment, onOpenSearch, onViewShipment }) {
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    PzApi.listBatches().then(res => {
      if (cancelled) return;
      if (!res.ok) {
        setError(res.error || 'Failed to load batches');
        setLoading(false);
        return;
      }
      const d = res.data;
      const list = Array.isArray(d) ? d : ((d && (d.batches || d.rows || d.items)) || []);
      setBatches(list);
      setLoading(false);
    }).catch(err => {
      if (!cancelled) {
        setError(err.message || String(err));
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, []);

  // Transform raw batches through V1 mappers
  const rows = batches.map(_transformBatch);

  // Derive lane assignments
  const byLane = KANBAN_LANES.reduce((acc, l) => {
    acc[l.id] = rows.filter(b => _batchLane(b) === l.id);
    return acc;
  }, {});

  // Derive KPIs from live data
  const active         = rows.filter(b => _batchLane(b) !== 'done');
  const urgentCount    = active.filter(b => b.overall === 'Action Required' || b.sadStatus === 'Verification Needed').length;
  const awaitingDhl    = active.filter(b => b.overall === 'Awaiting DHL').length;
  const awaitingSad    = active.filter(b => b.overall === 'Awaiting SAD').length;
  const readyForBooking = rows.filter(b => b.overall === 'Ready for Booking' || b.pzStatus === 'Generated').length;

  const handleCardClick = (b) => {
    if (onViewShipment) {
      onViewShipment(b._raw || b);
    } else if (onNav) {
      onNav('shipments');
    }
  };

  return (
    <div data-testid="dashboard-kanban" style={{ flex: 1, overflowY: 'auto', padding: '20px 32px 40px' }}>
      {/* Quick-start CTA strip */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Start a workflow</div>
        <div className="responsive-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
          {QUICK_FLOWS.map(f => (
            <button key={f.id} data-testid={'quick-flow-' + f.id} onClick={() => {
                if (f.id === 'outbound') onOpenNewShipment && onOpenNewShipment();
                else if (f.id === 'email') onNav && onNav('dhl');
                else if (f.id === 'inbound') onNav && onNav('shipments');
                else if (f.id === 'pz') onNav && onNav('shipments');
              }}
              style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px', background: f.bg, border: '1px solid ' + f.border, borderRadius: 8, cursor: 'pointer', textAlign: 'left', transition: 'transform 0.15s, box-shadow 0.15s', fontFamily: 'inherit' }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = '0 4px 12px var(--shadow)'; }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none'; }}>
              <span style={{ fontSize: 22 }}>{f.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 2 }}>{f.label}</div>
                <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>{f.hint}</div>
              </div>
              <span style={{ fontSize: 14, color: f.color }}>{'→'}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Loading / error states */}
      {loading && (
        <div data-testid="dashboard-loading" style={{ fontSize: 12, color: 'var(--text-3)', padding: '12px 4px' }}>Loading batches...</div>
      )}
      {error && (
        <div data-testid="dashboard-error" style={{ fontSize: 12, color: 'var(--badge-red-text)', padding: '12px 4px' }}>
          Failed to load batches: {error}
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Compact KPI strip — derived from live batches */}
          <div data-testid="dashboard-kpi-strip" className="responsive-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 18 }}>
            <CompactKpi label="Active" value={active.length} hint="in pipeline" />
            <CompactKpi label="Urgent" value={urgentCount} hint="needs attention now" accent="var(--badge-red-text)" />
            <CompactKpi label="Awaiting DHL" value={awaitingDhl} hint="email not received" accent="var(--badge-amber-text)" />
            <CompactKpi label="Awaiting SAD" value={awaitingSad} hint="customs document" accent="var(--badge-orange-text)" />
            <CompactKpi label="Ready for booking" value={readyForBooking} hint="PZ → wFirma" accent="var(--accent)" />
          </div>

          {/* Empty state */}
          {rows.length === 0 && (
            <div data-testid="dashboard-empty" style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13, lineHeight: 1.6 }}>
              <div style={{ fontSize: 28, marginBottom: 8 }}>{'∅'}</div>
              No completed batches yet. Use the workflow buttons above to start processing.
            </div>
          )}

          {rows.length > 0 && (
            <>
              {/* Pipeline header */}
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>Pipeline</h2>
                  <p style={{ margin: '2px 0 0', fontSize: 11, color: 'var(--text-3)' }}>Each shipment shown in its current stage — click a card to open detail</p>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  {onOpenSearch && (
                    <button data-testid="dashboard-search-btn" onClick={onOpenSearch} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 6, padding: '5px 10px', fontSize: 11, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
                      {'⌕'} Search <span style={{ fontFamily: 'monospace', padding: '0px 5px', background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 3, fontSize: 9.5 }}>{'⌘'}K</span>
                    </button>
                  )}
                  <button data-testid="dashboard-list-view-btn" onClick={() => onNav && onNav('shipments')} style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 6, padding: '5px 10px', fontSize: 11, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
                    {'⊟'} List view
                  </button>
                </div>
              </div>

              {/* Kanban board */}
              <div data-testid="kanban-board" style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(220px, 1fr))', gap: 12, overflowX: 'auto', paddingBottom: 4 }}>
                {KANBAN_LANES.map(lane => (
                  <KanbanLane key={lane.id} lane={lane} cards={byLane[lane.id]} onCardClick={handleCardClick} />
                ))}
              </div>

              {/* Bottom helper */}
              <div style={{ marginTop: 18, padding: 12, background: 'var(--bg-subtle)', border: '1px dashed var(--border)', borderRadius: 6, fontSize: 11.5, color: 'var(--text-2)', lineHeight: 1.55 }}>
                <strong style={{ color: 'var(--text)' }}>How this works:</strong> shipments move left-to-right as they progress through the PZ workflow. Urgent items (red flag, {'⚠'} icon) need your attention now — usually customs holds or missing docs. Use the quick-start cards above to begin a new workflow.
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

window.DashboardKanban = DashboardKanban;
