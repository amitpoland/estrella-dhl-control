// ─────────────────────────────────────────────────────────────────────────────
// AccountingHub — consolidated accounting workspace.
//
// Wave-3 Accounting Hub — 6-tab live wiring (census §A Accounting rows AC-1..AC-9)
//
// Tab authority map:
//   Tab A  Purchase Ledger  — LIVE: GET /api/v1/dashboard/batches (batch list
//                             filtered to PZ-received; routes_dashboard.py)
//   Tab B  Sales/Proforma   — LIVE: GET /api/v1/proforma/search
//                             (routes_proforma.py searchProformaDrafts)
//   Tab C  Client Ledger    — LIVE: LedgersPage (ledgers-page.jsx) embedded;
//                             GET /api/v1/ledgers/clients/{id}/invoice-ledger.json
//   Tab D  wFirma Sync      — NAVIGATE to /v2/wfirma_setup (AC-6: no duplicate;
//                             wfirma_setup LIVE Sprint 37)
//   Tab E  Master Data      — NAVIGATE to /v2/master (AC-7: no duplicate;
//                             master LIVE Sprint 38)
//   Tab F  Audit Trail      — LIVE: GET /api/v1/master/audit/
//                             (PzApi.listMasterAudit; routes_master.py)
//
// Wave-4 (doc-register — WZ/PZ/PW/RW/MM): kept as gated tabs in the rail,
//   honest-gated per R-Q3 ("Shown as Disabled / Planned / Backend Required").
//   Warehouse doc APIs unverified → gated with BACKEND-REQUIRED tag.
//
// No fake data anywhere. MOCK banner removed (accounting slug added to
//   WIRED_PAGES — all 6 census tabs are LIVE or NAVIGATE to LIVE pages).
// ─────────────────────────────────────────────────────────────────────────────

// ── Section registry ──────────────────────────────────────────────────────────
// group: 'live'      — wired to a real endpoint
// group: 'navigate'  — button navigates to the canonical authority page
// group: 'gated'     — visible, backend required (Wave 4)
const ACC_SECTIONS = [
  // FULL HTML PORT — document-type rail (pinned wireframe f7dd5e38). grp = HTML section.
  { id: 'overview',       label: 'Overview',         icon: '◈', group: 'live', code: null,  color: 'var(--accent)',           grp: 'top' },
  // SALES DOCUMENTS
  { id: 'pi',             label: 'Proforma',         icon: '✎', group: 'live', code: 'PI',  color: 'var(--badge-blue-text)',  grp: 'sales' },
  { id: 'inv',            label: 'Invoice',          icon: '⊞', group: 'live', code: 'INV', color: 'var(--badge-green-text)', grp: 'sales' },
  { id: 'cn',             label: 'Credit Note',      icon: '↩', group: 'live', code: 'CN',  color: 'var(--badge-amber-text)', grp: 'sales' },
  // WAREHOUSE DOCUMENTS
  { id: 'wz',             label: 'WZ — Outbound',    icon: '↗', group: 'live', code: 'WZ',  color: 'var(--badge-purple-text)',grp: 'wh' },
  { id: 'pz',             label: 'PZ — Inbound',     icon: '↘', group: 'live', code: 'PZ',  color: 'var(--accent)',           grp: 'wh' },
  { id: 'pw',             label: 'PW — Internal in', icon: '⊕', group: 'live', code: 'PW',  color: 'var(--badge-blue-text)',  grp: 'wh' },
  { id: 'rw',             label: 'RW — Internal out',icon: '⊖', group: 'live', code: 'RW',  color: 'var(--badge-red-text)',   grp: 'wh' },
  { id: 'mm',             label: 'MM — Transfer',    icon: '⇄', group: 'live', code: 'MM',  color: 'var(--badge-neutral-text)',grp: 'wh' },
  // LEDGERS
  { id: 'balance',        label: 'Client Balance',   icon: '⊜', group: 'live', code: null,  color: null,                      grp: 'ledger' },
  { id: 'clientLedger',   label: 'Client Ledger',    icon: '☷', group: 'live', code: 'STM', color: 'var(--badge-green-text)', grp: 'ledger' },
  { id: 'supplierLedger', label: 'Supplier Ledger',  icon: '☷', group: 'live', code: null,  color: null,                      grp: 'ledger' },
  // SYSTEM
  { id: 'wfirma',         label: 'wFirma Sync',      icon: '↻', group: 'live', code: null,  color: null,                      grp: 'system' },
  // EJ EXTENSIONS — existing capabilities absent from the HTML; preserved (never deleted), relocated here.
  { id: 'master',         label: 'Master Data',      icon: '⊟', group: 'navigate', code: null, color: null,                   grp: 'ej' },
  { id: 'audit',          label: 'Audit Trail',      icon: '◉', group: 'live', code: 'LOG', color: 'var(--badge-purple-text)',grp: 'ej' },
];

// ── Shared chip styles ─────────────────────────────────────────────────────────
const accBtnOutline = {
  background: 'transparent', border: '1px solid var(--border)',
  color: 'var(--text-2)', borderRadius: 4, padding: '5px 10px',
  fontSize: 11, fontWeight: 600, cursor: 'pointer',
};
const accBtnGold = {
  background: 'var(--accent)', border: '1px solid var(--accent)',
  color: 'var(--accent-text)', borderRadius: 4, padding: '5px 12px',
  fontSize: 11, fontWeight: 700, cursor: 'pointer',
};

function AccStateChip({ state }) {
  const conf = {
    draft:    { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
    approved: { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)' },
    posted:   { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    cancelled:{ bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)' },
    sent:     { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)' },
    received: { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    done:     { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    customs:  { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
    ready:    { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    new:      { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
    docs:     { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
    booked:   { bg: 'var(--badge-purple-bg)',  fg: 'var(--badge-purple-text)',  bd: 'var(--badge-purple-border)' },
    error:    { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)' },
  };
  const c = conf[(state || '').toLowerCase()] || conf.draft;
  return (
    <span data-testid="acc-state-chip" style={{
      fontSize: 9, padding: '1px 6px', borderRadius: 2,
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
      fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
    }}>{state}</span>
  );
}

function AccEmptyState({ msg }) {
  return (
    <div data-testid="acc-empty-state" style={{
      padding: '48px 24px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13,
    }}>
      <div style={{ fontSize: 28, marginBottom: 10 }}>◎</div>
      {msg || 'No records found.'}
    </div>
  );
}

function AccError({ msg }) {
  return (
    <div data-testid="acc-error" style={{
      margin: '16px 0', padding: '14px 16px', borderRadius: 8,
      background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
      color: 'var(--badge-red-text)', fontSize: 12,
    }}>
      {msg || 'Failed to load data.'}
    </div>
  );
}

function AccLoading() {
  return (
    <div data-testid="acc-loading" style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
      <span className="spinner" /> Loading…
    </div>
  );
}

// ── Left rail ─────────────────────────────────────────────────────────────────
function AccRailGroup({ label, sections, active, onClick }) {
  if (!sections.length) return null;
  return (
    <div style={{ marginBottom: 14 }}>
      {label && (
        <div style={{
          padding: '4px 16px 6px', fontSize: 9.5, fontWeight: 700,
          color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em',
        }}>{label}</div>
      )}
      {sections.map(s => {
        const isGated = s.group === 'gated';
        const isNav   = s.group === 'navigate';
        const a = active === s.id;
        return (
          <button
            key={s.id}
            data-testid={`acc-rail-${s.id}`}
            onClick={() => !isGated && onClick(s.id)}
            title={isGated ? 'Backend required — Wave 4' : undefined}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 10,
              padding: '7px 16px',
              background: a ? 'var(--card)' : 'transparent',
              border: 'none', cursor: isGated ? 'not-allowed' : 'pointer',
              textAlign: 'left', opacity: isGated ? 0.45 : 1,
              borderLeft: a ? '3px solid var(--accent)' : '3px solid transparent',
            }}
          >
            <span style={{ width: 14, fontSize: 12, color: a ? 'var(--accent)' : 'var(--text-3)' }}>{s.icon}</span>
            <span style={{
              flex: 1, fontSize: 11.5,
              color: a ? 'var(--text)' : 'var(--text-2)',
              fontWeight: a ? 600 : 400,
            }}>{s.label}</span>
            {s.code && !isGated && (
              <span style={{
                fontSize: 8.5, padding: '0px 4px', borderRadius: 2,
                background: 'var(--bg-subtle)', color: s.color,
                border: '1px solid var(--border)', fontWeight: 700, fontFamily: 'monospace',
              }}>{s.code}</span>
            )}
            {isGated && (
              <span style={{
                fontSize: 8, padding: '0px 4px', borderRadius: 2,
                background: 'var(--badge-neutral-bg)', color: 'var(--badge-neutral-text)',
                border: '1px solid var(--badge-neutral-border)', fontWeight: 700, letterSpacing: '0.04em',
              }}>W4</span>
            )}
            {isNav && !a && (
              <span style={{ fontSize: 10, color: 'var(--text-3)' }}>↗</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB A — Purchase Ledger
// Backend: GET /api/v1/dashboard/batches  (PzApi.listBatches — LIVE)
// Columns: Doc No · Date · Supplier/AWB · Items · Net · Gross · Status · wFirma
// ═══════════════════════════════════════════════════════════════════════════════
function PurchaseLedgerTab() {
  const [data, setData]   = React.useState(null);
  const [error, setError] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [filter, setFilter]   = React.useState('');

  React.useEffect(() => {
    (async () => {
      setLoading(true);
      const r = await window.PzApi.listBatches();
      if (r.ok) {
        setData(r.data);
      } else {
        setError(r.error || 'Failed to load batches');
      }
      setLoading(false);
    })();
  }, []);

  if (loading) return <AccLoading />;
  if (error)   return <AccError msg={error} />;

  // Normalise: batches is the array (API returns array directly)
  const batches = Array.isArray(data) ? data : (data && data.batches) || [];
  const q = filter.toLowerCase();
  const rows = batches.filter(b =>
    !q ||
    (b.batch_id || '').toLowerCase().includes(q) ||
    (b.doc_no   || '').toLowerCase().includes(q) ||
    (b.awb      || '').toLowerCase().includes(q) ||
    (b.status   || '').toLowerCase().includes(q)
  );

  // KPI tiles from live data
  const total      = batches.length;
  const done       = batches.filter(b => (b.status || '').toLowerCase() === 'done').length;
  const wfirmaSync = batches.filter(b => b.wfirma_posted).length;
  const inProgress = batches.filter(b => !['done', 'error'].includes((b.status || '').toLowerCase())).length;

  return (
    <div style={{ padding: '20px 28px 40px' }} data-testid="tab-purchase-ledger">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>
          Purchase Ledger
        </span>
        <span style={{ fontSize: 9, fontFamily: 'monospace', padding: '2px 6px', borderRadius: 2, background: 'var(--accent-subtle)', color: 'var(--accent)', fontWeight: 700 }}>PZ</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: 'var(--text-3)' }}>Source: EJ Dashboard batches</span>
        <input
          data-testid="purchase-filter"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Filter by batch / AWB / status…"
          style={{
            padding: '5px 10px', fontSize: 11, borderRadius: 4,
            border: '1px solid var(--border)', background: 'var(--card)',
            color: 'var(--text)', width: 220,
          }}
        />
      </div>

      {/* KPI tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
        <AccKpiTile label="Total batches"   value={String(total)}      hint="all time" accent="var(--text)" />
        <AccKpiTile label="In progress"     value={String(inProgress)} hint="open PZ"  accent="var(--badge-amber-text)" />
        <AccKpiTile label="Completed"       value={String(done)}       hint="status: done" accent="var(--badge-green-text)" />
        <AccKpiTile label="Synced to wFirma" value={String(wfirmaSync)} hint="wfirma_posted" accent="var(--accent)" />
      </div>

      {/* Table */}
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '160px 100px 1fr 80px 120px 100px 90px 110px 80px',
          padding: '10px 14px', background: 'var(--bg-subtle)',
          borderBottom: '1px solid var(--border)',
          fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
          textTransform: 'uppercase', letterSpacing: '0.06em',
        }}>
          <div>Doc No</div>
          <div>Date</div>
          <div>AWB / Batch</div>
          <div style={{ textAlign: 'right' }}>Lines</div>
          <div style={{ textAlign: 'right' }}>Net (PLN)</div>
          <div style={{ textAlign: 'right' }}>Gross (PLN)</div>
          <div>Status</div>
          <div>wFirma</div>
          <div />
        </div>

        {rows.length === 0 ? (
          <AccEmptyState msg={filter ? 'No batches match your filter.' : 'No purchase batches found.'} />
        ) : rows.map(b => {
          const docNo  = b.doc_no || b.batch_id || '—';
          const date   = b.created_at ? b.created_at.slice(0, 10) : '—';
          const awb    = b.awb || b.batch_id || '—';
          const lines  = b.invoice_line_count ?? b.line_count ?? '—';
          const net    = typeof b.net_pln === 'number' ? b.net_pln.toFixed(2) : (typeof b.net === 'number' ? b.net.toFixed(2) : '—');
          const gross  = typeof b.gross_pln === 'number' ? b.gross_pln.toFixed(2) : (typeof b.gross === 'number' ? b.gross.toFixed(2) : '—');
          const status = b.status || '—';
          const wf     = b.wfirma_posted ? 'synced' : (b.wfirma_doc_id ? 'partial' : 'pending');
          return (
            <div
              key={b.batch_id}
              data-testid={`purchase-row-${b.batch_id}`}
              style={{
                display: 'grid',
                gridTemplateColumns: '160px 100px 1fr 80px 120px 100px 90px 110px 80px',
                padding: '10px 14px',
                borderBottom: '1px solid var(--border-subtle)',
                fontSize: 11.5, color: 'var(--text-2)', alignItems: 'center',
              }}
            >
              <div style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)', fontSize: 10.5 }}>{docNo}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 10.5 }}>{date}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 10.5, color: 'var(--accent)' }}>{awb}</div>
              <div style={{ textAlign: 'right', fontFamily: 'monospace' }}>{lines}</div>
              <div style={{ textAlign: 'right', fontFamily: 'monospace' }}>{net}</div>
              <div style={{ textAlign: 'right', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{gross}</div>
              <div><AccStateChip state={status} /></div>
              <div>
                <span style={{
                  fontSize: 9, padding: '1px 6px', borderRadius: 2, fontWeight: 700,
                  letterSpacing: '0.04em', textTransform: 'uppercase',
                  background: wf === 'synced' ? 'var(--badge-green-bg)' : wf === 'partial' ? 'var(--badge-amber-bg)' : 'var(--badge-neutral-bg)',
                  color:      wf === 'synced' ? 'var(--badge-green-text)' : wf === 'partial' ? 'var(--badge-amber-text)' : 'var(--badge-neutral-text)',
                  border:     `1px solid ${wf === 'synced' ? 'var(--badge-green-border)' : wf === 'partial' ? 'var(--badge-amber-border)' : 'var(--badge-neutral-border)'}`,
                }}>wF · {wf}</span>
              </div>
              <div>
                <button data-testid={`view-batch-${b.batch_id}`} style={{
                  background: 'transparent', border: '1px solid var(--border)',
                  color: 'var(--text-2)', borderRadius: 3, padding: '2px 6px',
                  fontSize: 10, cursor: 'pointer',
                }}>View</button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB B — Sales / Proforma
// Backend: GET /api/v1/proforma/search  (PzApi.searchProformaDrafts — LIVE)
// Columns: Draft No · Date · Client · Currency · Net · Gross · State · wFirma · Actions
// ═══════════════════════════════════════════════════════════════════════════════
function SalesProformaTab() {
  const [data, setData]     = React.useState(null);
  const [error, setError]   = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [stateFilter, setStateFilter] = React.useState('');

  React.useEffect(() => {
    (async () => {
      setLoading(true);
      const params = {};
      if (stateFilter) params.draft_state = stateFilter;
      params.page_size = 200;
      const r = await window.PzApi.searchProformaDrafts(params);
      if (r.ok) {
        setData(r.data);
      } else {
        setError(r.error || 'Failed to load proforma drafts');
      }
      setLoading(false);
    })();
  }, [stateFilter]);

  if (loading) return <AccLoading />;
  if (error)   return <AccError msg={error} />;

  const results = (data && data.results) || [];
  const total   = (data && data.total)   || results.length;

  // KPI counts from results
  const countByState = results.reduce((acc, r) => {
    acc[r.draft_state] = (acc[r.draft_state] || 0) + 1;
    return acc;
  }, {});

  return (
    <div style={{ padding: '20px 28px 40px' }} data-testid="tab-sales-proforma">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>
          Sales / Proforma
        </span>
        <span style={{ fontSize: 9, fontFamily: 'monospace', padding: '2px 6px', borderRadius: 2, background: 'var(--accent-subtle)', color: 'var(--accent)', fontWeight: 700 }}>PI</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: 'var(--text-3)' }}>Source: proforma_drafts</span>
        <select
          data-testid="proforma-state-filter"
          value={stateFilter}
          onChange={e => setStateFilter(e.target.value)}
          style={{
            padding: '5px 10px', fontSize: 11, borderRadius: 4,
            border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)',
          }}
        >
          <option value="">All states</option>
          <option value="draft">Draft</option>
          <option value="approved">Approved</option>
          <option value="posted">Posted</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <span style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'monospace' }}>{total} total</span>
      </div>

      {/* KPI tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
        <AccKpiTile label="Draft"     value={String(countByState['draft']     || 0)} hint="awaiting approval" accent="var(--badge-neutral-text)" />
        <AccKpiTile label="Approved"  value={String(countByState['approved']  || 0)} hint="ready to post"     accent="var(--badge-blue-text)" />
        <AccKpiTile label="Posted"    value={String(countByState['posted']    || 0)} hint="in wFirma"         accent="var(--badge-green-text)" />
        <AccKpiTile label="Cancelled" value={String(countByState['cancelled'] || 0)} hint="voided"            accent="var(--badge-red-text)" />
      </div>

      {/* Table */}
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '180px 100px 1.4fr 70px 90px 100px 80px 70px',
          padding: '10px 14px', background: 'var(--bg-subtle)',
          borderBottom: '1px solid var(--border)',
          fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
          textTransform: 'uppercase', letterSpacing: '0.06em',
        }}>
          <div>Draft No / wFirma No</div>
          <div>Date</div>
          <div>Client</div>
          <div>Cur</div>
          <div>Batch</div>
          <div>State</div>
          <div>wFirma</div>
          <div />
        </div>

        {results.length === 0 ? (
          <AccEmptyState msg="No proforma drafts found." />
        ) : results.map(r => {
          const draftNo = r.wfirma_proforma_fullnumber || r.id || '—';
          const date    = r.created_at ? r.created_at.slice(0, 10) : '—';
          const client  = r.client_name || '—';
          const cur     = r.currency || '—';
          const batch   = r.batch_id ? r.batch_id.slice(-12) : '—';
          const hasWf   = !!(r.wfirma_proforma_id);
          return (
            <div
              key={r.id}
              data-testid={`proforma-row-${r.id}`}
              style={{
                display: 'grid',
                gridTemplateColumns: '180px 100px 1.4fr 70px 90px 100px 80px 70px',
                padding: '10px 14px',
                borderBottom: '1px solid var(--border-subtle)',
                fontSize: 11.5, color: 'var(--text-2)', alignItems: 'center',
              }}
            >
              <div style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)', fontSize: 10.5 }}>{draftNo}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 10.5 }}>{date}</div>
              <div style={{ color: 'var(--text)' }}>{client}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 10 }}>{cur}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 9.5, color: 'var(--text-3)' }}>{batch}</div>
              <div><AccStateChip state={r.draft_state || '—'} /></div>
              <div>
                <span style={{
                  fontSize: 9, padding: '1px 6px', borderRadius: 2, fontWeight: 700,
                  letterSpacing: '0.04em', textTransform: 'uppercase',
                  background: hasWf ? 'var(--badge-green-bg)' : 'var(--badge-neutral-bg)',
                  color:      hasWf ? 'var(--badge-green-text)' : 'var(--badge-neutral-text)',
                  border:     `1px solid ${hasWf ? 'var(--badge-green-border)' : 'var(--badge-neutral-border)'}`,
                }}>{hasWf ? 'synced' : 'local'}</span>
              </div>
              <div>
                <button data-testid={`view-draft-${r.id}`} style={{
                  background: 'transparent', border: '1px solid var(--border)',
                  color: 'var(--text-2)', borderRadius: 3, padding: '2px 6px',
                  fontSize: 10, cursor: 'pointer',
                }}>View</button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB C — Client Ledger
// Authority: LedgersPage (ledgers-page.jsx) — embedded.
// No duplicate: ledgers-page.jsx is the authority; AccountingHub mounts it.
// The census (AC-5) says "ledgers-page.jsx loaded but not mounted under
// accounting". This fixes that.
// ═══════════════════════════════════════════════════════════════════════════════
function ClientLedgerTab() {
  const LedgersPage = window.LedgersPage;
  if (typeof LedgersPage !== 'function') {
    return (
      <div style={{ padding: '32px 28px' }} data-testid="tab-client-ledger-fallback">
        <AccError msg="LedgersPage component not loaded. Check script load order in index.html." />
      </div>
    );
  }
  return (
    <div style={{ padding: '0 0 40px' }} data-testid="tab-client-ledger">
      <LedgersPage />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB D — wFirma Sync (NAVIGATE)
// No duplicate: WfirmaMappingPage is the authority at /v2/wfirma_setup.
// Shows live contractor scan status + navigate button.
// ═══════════════════════════════════════════════════════════════════════════════
function WfirmaSyncTab({ onNav }) {
  const [status, setStatus]   = React.useState(null);
  const [error, setError]     = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    (async () => {
      setLoading(true);
      const r = await window.PzApi.getWfirmaContractorScanStatus();
      if (r.ok) {
        setStatus(r.data);
      } else {
        setError(r.error || 'Could not load sync status');
      }
      setLoading(false);
    })();
  }, []);

  const fmtTime = (ts) => {
    if (!ts) return '—';
    try { return new Date(ts).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' }); }
    catch { return ts; }
  };

  return (
    <div style={{ padding: '20px 28px 40px' }} data-testid="tab-wfirma-sync">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>
          wFirma Sync
        </span>
        <span style={{ flex: 1 }} />
        <button
          data-testid="navigate-wfirma-setup"
          onClick={() => onNav && onNav('wfirma_setup')}
          style={accBtnGold}
        >
          ↗ Open full wFirma Setup
        </button>
      </div>

      {/* Status panel */}
      {loading && <AccLoading />}
      {error && !loading && (
        <div style={{
          padding: '14px 16px', borderRadius: 8, marginBottom: 16,
          background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)',
          color: 'var(--badge-amber-text)', fontSize: 12,
        }}>
          Sync status unavailable: {error}
        </div>
      )}
      {status && !loading && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 20 }}>
          <AccKpiTile
            label="Health"
            value={status.healthy ? 'Healthy' : 'Error'}
            hint={status.running ? 'scan running' : 'idle'}
            accent={status.healthy ? 'var(--badge-green-text)' : 'var(--badge-red-text)'}
          />
          <AccKpiTile
            label="Last completed"
            value={fmtTime(status.last_completed_at)}
            hint={status.duration_ms ? `${status.duration_ms}ms` : ''}
            accent="var(--accent)"
          />
          <AccKpiTile
            label="Processed / Created"
            value={`${status.processed ?? '—'} / ${status.created ?? '—'}`}
            hint={`updated: ${status.updated ?? '—'} · skipped: ${status.skipped ?? '—'}`}
            accent="var(--text)"
          />
          <AccKpiTile
            label="Errors"
            value={String(status.errors ?? '—')}
            hint={status.last_error || 'none'}
            accent={status.errors ? 'var(--badge-red-text)' : 'var(--badge-green-text)'}
          />
        </div>
      )}

      {/* Navigation card */}
      <div style={{
        background: 'var(--card)', border: '1px solid var(--accent-border)',
        borderRadius: 8, padding: 20,
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
          <div style={{ fontSize: 28, color: 'var(--accent)' }}>↻</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>
              wFirma Mapping &amp; Sync Configuration
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 12 }}>
              Full wFirma capabilities, customer and product mapping, contractor sync, and
              API configuration live at the Setup → wFirma page. No duplicate UI here.
            </div>
            <button
              data-testid="navigate-wfirma-setup-card"
              onClick={() => onNav && onNav('wfirma_setup')}
              style={accBtnGold}
            >
              ↗ Go to wFirma Setup
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB E — Master Data (NAVIGATE)
// No duplicate: MasterPage is the authority at /v2/master.
// ═══════════════════════════════════════════════════════════════════════════════
function MasterDataTab({ onNav }) {
  return (
    <div style={{ padding: '20px 28px 40px' }} data-testid="tab-master-data">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>
          Master Data
        </span>
        <span style={{ flex: 1 }} />
        <button
          data-testid="navigate-master"
          onClick={() => onNav && onNav('master')}
          style={accBtnGold}
        >
          ↗ Open Master Data
        </button>
      </div>

      <div style={{
        background: 'var(--card)', border: '1px solid var(--accent-border)',
        borderRadius: 8, padding: 20,
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
          <div style={{ fontSize: 28, color: 'var(--accent)' }}>⊟</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>
              EJ Dashboard Master Data
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>
              Clients/Importers · Suppliers/Exporters · Products · Designs · HS Codes ·
              FX Rates · VAT Rates · Carriers · Incoterms · Units of Measure ·
              Users · Roles &amp; Permissions
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 14 }}>
              All 12 entity tabs wired to live GET endpoints (Sprint 38). Authority: master-page.jsx.
              Accounting Tab E navigates there; no duplicate master table is held here.
            </div>
            <button
              data-testid="navigate-master-card"
              onClick={() => onNav && onNav('master')}
              style={accBtnGold}
            >
              ↗ Go to Master Data
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB F — Audit Trail
// Backend: GET /api/v1/master/audit/  (PzApi.listMasterAudit — LIVE)
// Columns: Timestamp · User · Entity · Action · Details
// ═══════════════════════════════════════════════════════════════════════════════
function AuditTrailTab() {
  const [data, setData]     = React.useState(null);
  const [error, setError]   = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [entityFilter, setEntityFilter] = React.useState('');

  React.useEffect(() => {
    (async () => {
      setLoading(true);
      const params = { limit: 200 };
      if (entityFilter) params.entity_type = entityFilter;
      const r = await window.PzApi.listMasterAudit(params);
      if (r.ok) {
        setData(r.data);
      } else {
        setError(r.error || 'Failed to load audit trail');
      }
      setLoading(false);
    })();
  }, [entityFilter]);

  if (loading) return <AccLoading />;
  if (error)   return <AccError msg={error} />;

  const entries = (data && data.entries) || [];
  const count   = (data && data.count) ?? entries.length;

  // Entity type options derived from data
  const entityTypes = [...new Set(entries.map(e => e.entity_type).filter(Boolean))].sort();

  const fmtTs = (ts) => {
    if (!ts) return '—';
    try { return new Date(ts).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'medium' }); }
    catch { return ts; }
  };

  return (
    <div style={{ padding: '20px 28px 40px' }} data-testid="tab-audit-trail">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>
          Audit Trail
        </span>
        <span style={{ fontSize: 9, fontFamily: 'monospace', padding: '2px 6px', borderRadius: 2, background: 'var(--accent-subtle)', color: 'var(--accent)', fontWeight: 700 }}>LOG</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: 'var(--text-3)' }}>Source: /api/v1/master/audit · {count} entries</span>
        <select
          data-testid="audit-entity-filter"
          value={entityFilter}
          onChange={e => setEntityFilter(e.target.value)}
          style={{
            padding: '5px 10px', fontSize: 11, borderRadius: 4,
            border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)',
          }}
        >
          <option value="">All entity types</option>
          {entityTypes.map(et => (
            <option key={et} value={et}>{et}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '150px 130px 130px 110px 1fr',
          padding: '10px 14px', background: 'var(--bg-subtle)',
          borderBottom: '1px solid var(--border)',
          fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
          textTransform: 'uppercase', letterSpacing: '0.06em',
        }}>
          <div>Timestamp</div>
          <div>User</div>
          <div>Entity</div>
          <div>Action</div>
          <div>Details</div>
        </div>

        {entries.length === 0 ? (
          <AccEmptyState msg={entityFilter ? 'No audit entries for this entity type.' : 'No audit entries found.'} />
        ) : entries.map((e, i) => (
          <div
            key={i}
            data-testid={`audit-row-${i}`}
            style={{
              display: 'grid',
              gridTemplateColumns: '150px 130px 130px 110px 1fr',
              padding: '9px 14px',
              borderBottom: '1px solid var(--border-subtle)',
              fontSize: 11, color: 'var(--text-2)', alignItems: 'start',
            }}
          >
            <div style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--text-3)' }}>
              {fmtTs(e.created_at || e.timestamp)}
            </div>
            <div style={{ fontWeight: 500, color: 'var(--text)' }}>{e.operator || e.user || '—'}</div>
            <div style={{ fontFamily: 'monospace', fontSize: 10.5, color: 'var(--accent)' }}>
              {e.entity_type || '—'}
            </div>
            <div>
              <span style={{
                fontSize: 9, padding: '1px 6px', borderRadius: 2, fontWeight: 700,
                textTransform: 'uppercase', letterSpacing: '0.04em',
                background: 'var(--badge-blue-bg)', color: 'var(--badge-blue-text)',
                border: '1px solid var(--badge-blue-border)',
              }}>
                {e.action || e.event_type || '—'}
              </span>
            </div>
            <div style={{ fontSize: 10.5, color: 'var(--text-2)', wordBreak: 'break-word' }}>
              {e.details || e.note || e.description || '—'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Gated placeholder for Wave-4 doc-register tabs (WZ/PZ/PW/RW/MM)
// R-Q3: "Shown as Disabled / Planned / Backend Required. Honest UI is our policy."
// ═══════════════════════════════════════════════════════════════════════════════
function GatedDocTab({ conf }) {
  return (
    <div style={{ padding: '32px 28px 40px' }} data-testid={`tab-gated-${conf.id}`}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>
          {conf.label}
        </span>
        <span style={{ fontSize: 9, fontFamily: 'monospace', padding: '2px 6px', borderRadius: 2, background: 'var(--badge-neutral-bg)', color: 'var(--badge-neutral-text)', border: '1px solid var(--badge-neutral-border)', fontWeight: 700 }}>W4</span>
      </div>
      <div style={{
        background: 'var(--card)', border: '1px solid var(--badge-neutral-border)',
        borderRadius: 8, padding: 24, textAlign: 'center',
      }}>
        <div style={{ fontSize: 32, marginBottom: 12, color: 'var(--text-3)' }}>{conf.icon}</div>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
          {conf.label} — Backend Required
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-2)', maxWidth: 420, margin: '0 auto 16px' }}>
          The {conf.code} document register tab is planned for Wave 4.
          Backend API verification for warehouse document listing is pending.
          This tab is visible per R-Q3 (honest UI policy) — it will activate when
          the document API is confirmed live.
        </div>
        <span style={{
          display: 'inline-block', padding: '4px 12px', borderRadius: 4, fontSize: 11,
          background: 'var(--badge-neutral-bg)', color: 'var(--badge-neutral-text)',
          border: '1px solid var(--badge-neutral-border)', fontWeight: 600,
        }}>
          BACKEND-REQUIRED · Wave 4
        </span>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Shared KPI tile
// ═══════════════════════════════════════════════════════════════════════════════
function AccKpiTile({ label, value, hint, accent }) {
  return (
    <div data-testid="acc-kpi-tile" style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 6, padding: '12px 14px',
    }}>
      <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color: accent || 'var(--text)', marginTop: 4, fontFamily: 'monospace' }}>
        {value}
      </div>
      {hint && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Root: AccountingHub
// ═══════════════════════════════════════════════════════════════════════════════
// ── AccountingOverview — HYBRID landing (wireframe Overview) ───────────────────
// Wireframe (accounting-authority-comparison LEFT): 4 KPI + Sales-docs & Warehouse-
// docs count panels + Document-map diagram. No aggregate endpoints exist for the
// KPI figures / doc counts, so they render honestly ("—" · Backend Pending) per the
// HYBRID ruling — never fabricated. The document map is a static diagram (no backend).
// Additive landing: no new endpoint, no write path; existing tabs unchanged.
function _AccKpi({ label }) {
  return (
    <div data-testid="acc-ov-kpi" style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px', flex: 1, minWidth: 150 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-3)', marginTop: 6, fontFamily: '"DM Serif Display", serif' }}>—</div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>Backend Pending</div>
    </div>
  );
}
function _AccDocPanel({ title, rows, onJump }) {
  return (
    <div style={{ flex: 1, minWidth: 240, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>{title} <span style={{ fontWeight: 400, color: 'var(--text-3)', fontSize: 10 }}>· Backend Pending</span></div>
      {rows.map((r, i) => (
        <button key={r.label} data-testid={`acc-ov-jump-${r.to}`} onClick={() => onJump && onJump(r.to)}
          style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 14px', borderBottom: i < rows.length - 1 ? '1px solid var(--border-subtle)' : 'none', fontSize: 12, color: 'var(--text-2)', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit' }}>
          <span>{r.label}</span><span style={{ color: 'var(--text-3)', fontFamily: 'monospace' }}>— ›</span>
        </button>
      ))}
    </div>
  );
}
function AccountingOverview({ onJump }) {
  const mapStep = (code, name) => (
    <div style={{ flex: 1, minWidth: 110, background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.04em' }}>{code}</div>
      <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 3 }}>{name}</div>
    </div>
  );
  const arrow = <div style={{ alignSelf: 'center', color: 'var(--text-3)', fontSize: 14 }}>→</div>;
  return (
    <div data-testid="accounting-overview" style={{ padding: '20px 28px' }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>Accounting</h2>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 3 }}>Proforma · Invoice · WZ · PZ · PW · RW · MM · Client Balance · Client Ledger · Supplier Ledger — all mapped from wFirma</div>
      </div>
      <div style={{ display: 'flex', gap: 12, margin: '14px 0', flexWrap: 'wrap' }}>
        <_AccKpi label="Sales Receivable" />
        <_AccKpi label="Sales Overdue" />
        <_AccKpi label="Supplier Payable" />
        <_AccKpi label="Last wFirma Sync" />
      </div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <_AccDocPanel title="Sales documents" onJump={onJump} rows={[{ label: 'Proforma issued', to: 'pi' }, { label: 'Invoices issued', to: 'inv' }, { label: 'Credit notes', to: 'cn' }, { label: 'WZ releases', to: 'wz' }]} />
        <_AccDocPanel title="Warehouse documents" onJump={onJump} rows={[{ label: 'PZ (external receipt)', to: 'pz' }, { label: 'PW (internal receipt)', to: 'pw' }, { label: 'RW (internal release)', to: 'rw' }, { label: 'MM (transfer)', to: 'mm' }]} />
      </div>
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>Document map <span style={{ fontWeight: 400, color: 'var(--text-3)' }}>— how sales &amp; warehouse documents connect</span></div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {mapStep('PI', 'Proforma')}{arrow}
          {mapStep('INV', 'Sales Invoice')}{arrow}
          {mapStep('WZ', 'Outbound release')}{arrow}
          {mapStep('PZ', 'Inbound receipt')}{arrow}
          {mapStep('CN', 'Credit Note')}
        </div>
      </div>
    </div>
  );
}

// ── Document-type section components (FULL HTML PORT) ──────────────────────────
// Render the wireframe grid/table structure. GET /accounting/{type}, /ledger/*,
// POST /wfirma/sync/{type} do NOT exist yet → honest Backend Pending body
// (UI-before-backend: complete UI rendered; only execution is pending; no fabricated data).
function _AccGridHeader({ title, code, color, actions }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>{title}</h2>
      {code && <span style={{ fontSize: 9, fontWeight: 700, fontFamily: 'monospace', color: color || 'var(--accent)', background: 'var(--accent-subtle)', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 6px' }}>{code}</span>}
      <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Source: wFirma</span>
      <div style={{ flex: 1 }} />
      {(actions || []).map(a => (
        <button key={a} disabled title="Backend Pending — endpoint not yet available" style={{ padding: '5px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11, fontWeight: 600, cursor: 'not-allowed', opacity: 0.6 }}>{a}</button>
      ))}
    </div>
  );
}
function _AccPendingTable({ cols, note }) {
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
          {cols.map((c, i) => <th key={c || i} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{c}</th>)}
        </tr></thead>
        <tbody><tr><td colSpan={cols.length} style={{ padding: '28px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>— · Backend Pending{note ? ` · ${note}` : ''}</td></tr></tbody>
      </table>
    </div>
  );
}
const _ACC_DOC_TITLES = {
  inv: { t: 'Invoice', c: 'INV', color: 'var(--badge-green-text)', wh: false },
  cn:  { t: 'Credit Note', c: 'CN', color: 'var(--badge-amber-text)', wh: false },
  wz:  { t: 'WZ — Outbound', c: 'WZ', color: 'var(--badge-purple-text)', wh: true },
  pw:  { t: 'PW — Internal in', c: 'PW', color: 'var(--badge-blue-text)', wh: true },
  rw:  { t: 'RW — Internal out', c: 'RW', color: 'var(--badge-red-text)', wh: true },
  mm:  { t: 'MM — Transfer', c: 'MM', color: 'var(--badge-neutral-text)', wh: true },
};
// Documented live reads (Wave 4 Item 3A): Invoice / Credit Note via wFirma
// invoices/find. WZ/PW/RW/MM stay Backend Pending (Item 3B — undocumented).
const _ACC_DOC_LIVE = { inv: 'invoice', cn: 'credit_note' };
function AccDocGrid({ sectionId }) {
  const m = _ACC_DOC_TITLES[sectionId] || { t: sectionId, c: null, wh: false };
  const cols = m.wh
    ? ['Number', 'Date', 'Party', 'Items', 'Linked', 'State', 'wFirma', 'View']
    : ['Number', 'Date', 'Party', 'Net', 'Tax', 'Gross', 'Cur', 'State', 'wFirma', 'View'];
  const docType = _ACC_DOC_LIVE[sectionId];
  const [st, setSt] = React.useState({ loading: !!docType, error: null, rows: null });
  React.useEffect(() => {
    if (!docType) return;
    let cancelled = false;
    setSt({ loading: true, error: null, rows: null });
    window.PzApi.listAccountingDocs(docType).then(res => {
      if (cancelled) return;
      if (!res || !res.ok) { setSt({ loading: false, error: (res && res.error) || 'Load failed', rows: null }); return; }
      setSt({ loading: false, error: null, rows: (res.data && res.data.rows) || [] });
    }).catch(e => { if (!cancelled) setSt({ loading: false, error: (e && e.message) || String(e), rows: null }); });
    return () => { cancelled = true; };
  }, [docType]);
  const td = { padding: '9px 12px', fontSize: 11.5, color: 'var(--text-2)' };
  const tdm = { ...td, fontFamily: 'monospace' };
  return (
    <div data-testid={`acc-grid-${sectionId}`} style={{ padding: '20px 28px' }}>
      <_AccGridHeader title={m.t} code={m.c} color={m.color} actions={['↻ Sync', '↓ Export', `+ New ${m.c || ''}`]} />
      {!docType && <_AccPendingTable cols={cols} note="GET /api/v1/accounting/{type}" />}
      {docType && (
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              {cols.map(c => <th key={c} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{c}</th>)}
            </tr></thead>
            <tbody>
              {st.loading && <tr><td colSpan={cols.length} style={{ padding: '28px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}><span className="spinner" /> Loading from wFirma…</td></tr>}
              {st.error && !st.loading && <tr><td colSpan={cols.length} data-testid={`acc-grid-${sectionId}-error`} style={{ padding: '20px 16px', textAlign: 'center', color: 'var(--badge-red-text)', fontSize: 12 }}>wFirma read unavailable: {st.error}</td></tr>}
              {!st.loading && !st.error && st.rows && st.rows.length === 0 && <tr><td colSpan={cols.length} style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>No {m.t.toLowerCase()} documents.</td></tr>}
              {!st.loading && !st.error && st.rows && st.rows.map((r, i) => (
                <tr key={r.wfirma_id || i} data-testid={`acc-grid-${sectionId}-row`} style={{ borderBottom: i < st.rows.length - 1 ? '1px solid var(--border-subtle)' : 'none' }}>
                  <td style={{ ...tdm, color: 'var(--text)' }}>{r.number}</td>
                  <td style={td}>{r.date}</td>
                  <td style={{ ...td, color: 'var(--text)' }}>{r.party}</td>
                  <td style={tdm}>{r.net}</td>
                  <td style={tdm}>{r.tax}</td>
                  <td style={{ ...tdm, color: 'var(--text)' }}>{r.gross}</td>
                  <td style={td}>{r.currency}</td>
                  <td style={{ ...td, fontSize: 11 }}>{r.state}</td>
                  <td style={{ ...td, fontSize: 11, color: 'var(--text-3)' }}>{r.wfirma_id ? 'wF' : '—'}</td>
                  <td style={{ ...td, fontSize: 11, color: 'var(--text-3)' }}>View</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
// Wave 4 Item 4 — live Client Balance roster (GET /api/v1/ledgers/clients).
// Open / Overdue(invoice-age) / YTD / Cur / State are DOCUMENTED (reuse the
// Statement authority). "Last 30d" and due-date Overdue are Backend Pending —
// rendered honestly ("—", disclosed), never faked.
const _ACC_BAL_COLS = ['Client', 'Open', 'Overdue', 'Last 30d', 'YTD', 'Cur', 'State'];
function AccClientBalance() {
  const [st, setSt] = React.useState({ loading: true, error: null, rows: null, period: null });
  React.useEffect(() => {
    let cancelled = false;
    setSt({ loading: true, error: null, rows: null, period: null });
    window.PzApi.listClientBalances({ limit: 25 }).then(res => {
      if (cancelled) return;
      if (!res || !res.ok) { setSt({ loading: false, error: (res && res.error) || 'Load failed', rows: null, period: null }); return; }
      const d = res.data || {};
      setSt({ loading: false, error: null, rows: d.rows || [], period: d.period || null });
    }).catch(e => { if (!cancelled) setSt({ loading: false, error: (e && e.message) || String(e), rows: null, period: null }); });
    return () => { cancelled = true; };
  }, []);
  const td = { padding: '9px 12px', fontSize: 11.5, color: 'var(--text-2)' };
  const tdm = { ...td, fontFamily: 'monospace' };
  const dash = <span style={{ color: 'var(--text-3)' }}>—</span>;
  return (
    <div data-testid="acc-balance" style={{ padding: '20px 28px' }}>
      <_AccGridHeader title="Client Balance" actions={['↻ Refresh', '↓ Export']} />
      {st.period && (
        <div style={{ fontSize: 10.5, color: 'var(--text-3)', margin: '-6px 0 10px' }}>
          Period {st.period.from} → {st.period.to} (YTD default) · Overdue = invoice-age basis · Last 30d Backend Pending
        </div>
      )}
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
            {_ACC_BAL_COLS.map(c => <th key={c} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{c}</th>)}
          </tr></thead>
          <tbody>
            {st.loading && <tr><td colSpan={_ACC_BAL_COLS.length} style={{ padding: '28px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}><span className="spinner" /> Loading balances from wFirma…</td></tr>}
            {st.error && !st.loading && <tr><td colSpan={_ACC_BAL_COLS.length} data-testid="acc-balance-error" style={{ padding: '20px 16px', textAlign: 'center', color: 'var(--badge-red-text)', fontSize: 12 }}>wFirma read unavailable: {st.error}</td></tr>}
            {!st.loading && !st.error && st.rows && st.rows.length === 0 && <tr><td colSpan={_ACC_BAL_COLS.length} style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>No clients in Customer Master.</td></tr>}
            {!st.loading && !st.error && st.rows && st.rows.map((r, i) => (
              <tr key={r.contractor_id || i} data-testid="acc-balance-row" style={{ borderBottom: i < st.rows.length - 1 ? '1px solid var(--border-subtle)' : 'none' }}>
                <td style={{ ...td, color: 'var(--text)' }}>{r.name || r.contractor_id || '—'}</td>
                <td style={tdm}>{r.balance_available ? (r.open != null ? r.open : <span title="Multi-currency — see per-currency breakdown" style={{ color: 'var(--text-3)' }}>multi</span>) : dash}</td>
                <td style={tdm} title="Invoice-age basis; due-date overdue Backend Pending">{r.balance_available && r.overdue_invoice_age != null ? r.overdue_invoice_age : dash}</td>
                <td style={td} title="Backend Pending — no existing authority">{dash}</td>
                <td style={tdm}>{r.balance_available && r.ytd_invoiced != null ? r.ytd_invoiced : dash}</td>
                <td style={td}>{r.currency || '—'}</td>
                <td style={{ ...td, fontSize: 11 }}>{r.balance_available ? r.state : <span title={r.note || ''} style={{ color: 'var(--text-3)' }}>unknown</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
function AccSupplierLedger() {
  return (
    <div data-testid="acc-supplier-ledger" style={{ padding: '20px 28px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>Supplier Ledger</h2>
        <select data-testid="acc-supplier-select" disabled style={{ fontSize: 11, padding: '4px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)' }}><option>All suppliers</option></select>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Source: wFirma</span>
        <div style={{ flex: 1 }} />
        <button disabled title="Backend Pending" style={{ padding: '5px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11, fontWeight: 600, cursor: 'not-allowed', opacity: 0.6 }}>↓ Export</button>
      </div>
      <_AccPendingTable cols={['Date', 'Supplier', 'Reference', 'Description', 'Debit', 'Credit', 'Balance']} note="GET /api/v1/ledger/suppliers" />
    </div>
  );
}
function AccWfirmaSyncInline({ onNav }) {
  const kpis = [['Synced types', '1 pending'], ['Last full sync', 'auto every 6h'], ['Failed events', 'last 24h']];
  return (
    <div data-testid="acc-wfirma-sync" style={{ padding: '20px 28px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>wFirma Sync</h2>
        <div style={{ flex: 1 }} />
        <button disabled title="Backend Pending — POST /api/v1/wfirma/sync/{type}" style={{ padding: '5px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11, fontWeight: 600, cursor: 'not-allowed', opacity: 0.6 }}>↻ Sync all now</button>
        <button data-testid="acc-wfirma-open-setup" onClick={() => onNav && onNav('wfirma_setup')} title="EJ Extension — open the full wFirma setup" style={{ padding: '5px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}>Open full wFirma setup →</button>
      </div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        {kpis.map(([l, n]) => (
          <div key={l} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 16px', flex: 1, minWidth: 150 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{l}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-3)', marginTop: 6, fontFamily: '"DM Serif Display", serif' }}>—</div>
            <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>Backend Pending · {n}</div>
          </div>
        ))}
      </div>
      <_AccPendingTable cols={['Local type', 'Code', 'wFirma endpoint', 'Count', 'State', 'Last sync', '']} note="POST /api/v1/wfirma/sync/{type}" />
    </div>
  );
}

function AccountingHub({ onNav }) {
  const [section, setSection] = React.useState('overview');

  const handleSection = (id) => {
    const conf = ACC_SECTIONS.find(s => s.id === id);
    if (!conf) return;
    // EJ Extension that lives on its own canonical page — navigate, do not duplicate.
    if (conf.group === 'navigate' && id === 'master' && onNav) { onNav('master'); return; }
    setSection(id);
  };

  const railGroups = [
    { label: null,                  ids: ['overview'] },
    { label: 'Sales Documents',     ids: ['pi', 'inv', 'cn'] },
    { label: 'Warehouse Documents', ids: ['wz', 'pz', 'pw', 'rw', 'mm'] },
    { label: 'Ledgers',             ids: ['balance', 'clientLedger', 'supplierLedger'] },
    { label: 'System',              ids: ['wfirma'] },
    { label: 'EJ Extensions',       ids: ['master', 'audit'] },
  ];

  return (
    <div data-testid="accounting-hub-root" style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      {/* Left rail — document-type organization (HTML) + preserved EJ Extensions */}
      <div style={{ width: 224, flexShrink: 0, background: 'var(--bg-subtle)', borderRight: '1px solid var(--border)', padding: '12px 0', overflowY: 'auto' }}>
        {railGroups.map(g => (
          <AccRailGroup key={g.label || 'top'} label={g.label}
            sections={ACC_SECTIONS.filter(s => g.ids.includes(s.id))}
            active={section} onClick={handleSection} />
        ))}
        {/* Source note */}
        <div style={{ margin: '16px 14px', padding: 10, background: 'var(--card)', border: '1px solid var(--accent-border)', borderRadius: 6 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Source</div>
          <div style={{ fontSize: 10.5, color: 'var(--text-2)', lineHeight: 1.4 }}>All documents and balances are mapped <strong>from wFirma</strong> · last sync via wFirma Sync.</div>
        </div>
      </div>

      {/* Main area */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {section === 'overview'       && <AccountingOverview onJump={setSection} />}
        {section === 'pi'             && <SalesProformaTab />}
        {section === 'pz'             && <PurchaseLedgerTab />}
        {section === 'clientLedger'   && <ClientLedgerTab />}
        {['inv', 'cn', 'wz', 'pw', 'rw', 'mm'].includes(section) && <AccDocGrid sectionId={section} />}
        {section === 'balance'        && <AccClientBalance />}
        {section === 'supplierLedger' && <AccSupplierLedger />}
        {section === 'wfirma'         && <AccWfirmaSyncInline onNav={onNav} />}
        {section === 'audit'          && <AuditTrailTab />}
      </div>
    </div>
  );
}

window.AccountingHub = AccountingHub;
