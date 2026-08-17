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
//                             GET /api/v1/ledgers/clients/{id}/statement.json (Phase 10B)
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
  // ONE entry: LedgersPage renders its own Client / Management Analysis /
  // Supplier strip. A second rail entry mounted it twice (PR-005 violation).
  { id: 'clientLedger',   label: 'Ledgers',          icon: '☷', group: 'live', code: 'STM', color: 'var(--badge-green-text)', grp: 'ledger' },
  { id: 'insuranceExport',label: 'Insurance Export', icon: '⛨', group: 'live', code: 'INS', color: 'var(--badge-blue-text)',  grp: 'ledger' },
  { id: 'treasury',       label: 'Treasury',         icon: '₿', group: 'live', code: 'TSY', color: 'var(--badge-green-text)', grp: 'ledger' },
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

// P0: Accounting PZ register = wFirma warehouse PZ (AccDocGrid). Batch pipeline removed.

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
// TAB C — Ledgers (Client · Management Analysis · Supplier)
// Authority: LedgersPage (ledgers-page.jsx) — mounted ONCE.
//
// This used to be two rail entries (Client Ledger and Supplier Ledger), each
// mounting the whole LedgersPage with its own period state. Because LedgersPage
// renders its own Client / Management Analysis / Supplier strip, Management
// Analysis — and its AP Status filter — was reachable down two paths as two
// unsynchronised instances. That is the "duplicate filter" operators reported.
// One entry, one mount, one period authority (PR-005).
// ═══════════════════════════════════════════════════════════════════════════════
function LedgersTab() {
  const LedgersPage = window.LedgersPage;
  if (typeof LedgersPage !== 'function') {
    return (
      <div style={{ padding: '32px 28px' }} data-testid="tab-client-ledger-fallback">
        <AccError msg="LedgersPage component not loaded. Check script load order in index.html." />
      </div>
    );
  }
  // No period props: LedgersPage owns the window and renders the period bar.
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
// Wave 4 Item 1A — pure reducer for CURRENCY-AWARE Sales Receivable.
// Sums outstanding PER currency across /ledgers/clients rows. NEVER sums across
// currencies (operator ruling): PLN/EUR/USD stay separate. Unavailable rows and
// unparseable values are skipped. Returns [{ currency, amount:"0.00" }] sorted.
// Exposed on window for the reducer unit test (no cross-currency total is ever
// produced by this function — there is no single-number code path).
function accReceivableByCurrency(rows) {
  const byCcy = {};
  (rows || []).forEach(r => {
    if (!r || r.balance_available === false) return;
    const obc = r.open_by_currency;
    if (obc && typeof obc === 'object') {
      Object.keys(obc).forEach(ccy => {
        const v = parseFloat(obc[ccy]);
        if (!isNaN(v)) byCcy[ccy] = (byCcy[ccy] || 0) + v;
      });
    } else if (r.currency && r.currency !== 'multi' && r.open != null) {
      const v = parseFloat(r.open);
      if (!isNaN(v)) byCcy[r.currency] = (byCcy[r.currency] || 0) + v;
    }
  });
  return Object.keys(byCcy).sort().map(ccy => ({ currency: ccy, amount: byCcy[ccy].toFixed(2) }));
}
if (typeof window !== 'undefined') { window._accReceivableByCurrency = accReceivableByCurrency; }

// Live per-currency KPI tile — never a mixed FX total.
function _AccCcyKpi({ testid, label, rows, loading, error, hint }) {
  let body;
  let sub = hint || '';
  if (loading) { body = '—'; sub = 'Loading…'; }
  else if (error) { body = '—'; sub = 'read unavailable'; }
  else {
    const list = rows || [];
    if (list.length === 0) { body = '0.00'; sub = sub || 'None'; }
    else {
      body = (
        <div>
          {list.map(r => (
            <div key={r.currency} data-testid={`${testid}-${r.currency}`} style={{ fontSize: list.length > 1 ? 16 : 24, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace', lineHeight: 1.35 }}>
              <span style={{ fontSize: 11, color: 'var(--text-3)', marginRight: 6, fontFamily: 'inherit' }}>{r.currency}</span>{r.amount}
            </div>
          ))}
        </div>
      );
      if (list.length > 1) sub = (sub ? sub + ' · ' : '') + 'Per currency — not summed';
    }
  }
  return (
    <div data-testid={testid} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px', flex: 1, minWidth: 150 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ marginTop: 6, fontFamily: '"DM Serif Display", serif', fontSize: 24, fontWeight: 700, color: 'var(--text)' }}>{body}</div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{sub}</div>
    </div>
  );
}

// Backend-Pending KPI tile (kept for honest gated placeholders).
function _AccKpi({ label, pendingNote }) {
  return (
    <div data-testid="acc-ov-kpi" style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px', flex: 1, minWidth: 150 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-3)', marginTop: 6, fontFamily: '"DM Serif Display", serif' }}>—</div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>Backend Pending{pendingNote ? ` — ${pendingNote}` : ''}</div>
    </div>
  );
}

// Live Sales Receivable tile — per-currency, never a mixed total.
function _AccReceivableKpi({ state }) {
  let body, hint;
  if (state.loading) { body = '—'; hint = 'Loading…'; }
  else if (state.error) { body = '—'; hint = 'wFirma read unavailable'; }
  else {
    const rows = state.receivable || [];
    if (rows.length === 0) { body = '0.00'; hint = 'No open receivables'; }
    else {
      body = (
        <div data-testid="acc-ov-receivable-values">
          {rows.map(r => (
            <div key={r.currency} data-testid={`acc-ov-receivable-${r.currency}`} style={{ fontSize: rows.length > 1 ? 16 : 24, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace', lineHeight: 1.35 }}>
              <span style={{ fontSize: 11, color: 'var(--text-3)', marginRight: 6, fontFamily: 'inherit' }}>{r.currency}</span>{r.amount}
            </div>
          ))}
        </div>
      );
      hint = rows.length > 1 ? 'Per currency — not summed' : 'Outstanding';
    }
  }
  return (
    <div data-testid="acc-ov-kpi-receivable" style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px', flex: 1, minWidth: 150 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Sales Receivable</div>
      <div style={{ marginTop: 6, fontFamily: '"DM Serif Display", serif', fontSize: 24, fontWeight: 700, color: 'var(--text)' }}>{body}</div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>
    </div>
  );
}

// Live Last wFirma Sync tile — reuses analytics/phase-a wfirma_sync.
function _AccLastSyncKpi({ state }) {
  let body, hint;
  if (state.loading) { body = '—'; hint = 'Loading…'; }
  else if (state.error) { body = '—'; hint = 'analytics unavailable'; }
  else {
    const sync = state.sync || {};
    body = sync.last_exported_at ? String(sync.last_exported_at).replace('T', ' ') : '—';
    hint = sync.last_exported_at
      ? `${sync.exported != null ? sync.exported + ' exported' : ''}${sync.last_exported_doc ? ' · ' + sync.last_exported_doc : ''}`.trim() || 'last export'
      : 'no export recorded';
  }
  return (
    <div data-testid="acc-ov-kpi-lastsync" style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px', flex: 1, minWidth: 150 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Last wFirma Sync</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', marginTop: 6, fontFamily: 'monospace' }}>{body}</div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>
    </div>
  );
}

// Overview KPI row — Sales Receivable from bulk MA (zero per-customer calls).
// Never calls /ledgers/clients?limit=100 (that path was the N+1 timeout).
function AccountingOverviewKpis() {
  const [recv, setRecv] = React.useState({ loading: true, error: null, receivable: null, overdue: null });
  const [pay, setPay] = React.useState({ loading: true, error: null, payable: null });
  const [sync, setSync] = React.useState({ loading: true, error: null, sync: null });
  React.useEffect(() => {
    let cancelled = false;
    const today = new Date().toISOString().slice(0, 10);
    window.PzApi.getManagementAnalysis({ as_of: today, scope: 'all_outstanding' }).then(res => {
      if (cancelled) return;
      if (!res || !res.ok) { setRecv({ loading: false, error: (res && res.error) || 'Load failed', receivable: null, overdue: null }); return; }
      const summaries = (res.data && res.data.currency_summaries) || [];
      setRecv({
        loading: false, error: null,
        receivable: summaries.map(s => ({ currency: s.currency, amount: String(s.total_receivable != null ? s.total_receivable : '0.00') })),
        overdue: summaries.map(s => ({ currency: s.currency, amount: String(s.overdue != null ? s.overdue : '0.00') })),
        source: res.data && (res.data.source || 'local'),
        as_of: (res.data && res.data.as_of) || today,
        freshness: res.data && res.data.freshness,
      });
    }).catch(e => { if (!cancelled) setRecv({ loading: false, error: (e && e.message) || String(e), receivable: null, overdue: null }); });
    window.PzApi.getPayablesAnalysis({ as_of: today, scope: 'all_outstanding' }).then(res => {
      if (cancelled) return;
      if (!res || !res.ok) { setPay({ loading: false, error: (res && res.error) || 'Load failed', payable: null }); return; }
      const summaries = (res.data && res.data.currency_summaries) || [];
      setPay({
        loading: false, error: null,
        payable: summaries.map(s => ({ currency: s.currency, amount: String(s.net_payable != null ? s.net_payable : '0.00') })),
        source: res.data && (res.data.source || 'local'),
        as_of: (res.data && res.data.as_of) || today,
        freshness: res.data && res.data.freshness,
      });
    }).catch(e => { if (!cancelled) setPay({ loading: false, error: (e && e.message) || String(e), payable: null }); });
    window.PzApi.getAnalyticsPhaseA().then(res => {
      if (cancelled) return;
      if (!res || !res.ok) { setSync({ loading: false, error: (res && res.error) || 'Load failed', sync: null }); return; }
      setSync({ loading: false, error: null, sync: (res.data && res.data.wfirma_sync) || {} });
    }).catch(e => { if (!cancelled) setSync({ loading: false, error: (e && e.message) || String(e), sync: null }); });
    return () => { cancelled = true; };
  }, []);
  return (
    <div style={{ display: 'flex', gap: 12, margin: '14px 0', flexWrap: 'wrap' }}>
      <_AccReceivableKpi state={recv} />
      <_AccCcyKpi testid="acc-ov-kpi-overdue" label="Sales Overdue" rows={recv.overdue} loading={recv.loading} error={recv.error}
        hint={recv.as_of ? `Due-date aging · as of ${recv.as_of} · ${recv.source || 'local'}` : 'Due-date aging'} />
      <_AccCcyKpi testid="acc-ov-kpi-payable" label="Supplier Payable" rows={pay.payable} loading={pay.loading} error={pay.error}
        hint={pay.as_of ? `Net payable · as of ${pay.as_of} · ${pay.source || 'local'}` : 'Net payable'} />
      <_AccLastSyncKpi state={sync} />
    </div>
  );
}
// Doc-count panel (Wave 4 Item 2). Each row shows a LIVE count only when a
// provable count exists in `counts` (keyed by row.to); otherwise the value stays
// "—" with an honest per-row Backend-Pending reason (from `reasons`). No count is
// fabricated, approximated, or summed across currencies. Layout is the wireframe's
// unchanged: label · value · jump. The panel-level "Backend Pending" chip shows
// only when EVERY row in the panel is still pending.
function _AccDocPanel({ title, rows, onJump, counts, reasons }) {
  const _c = counts || {};
  const _r = reasons || {};
  const allPending = rows.every(r => typeof _c[r.to] !== 'number');
  return (
    <div style={{ flex: 1, minWidth: 240, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>{title}{allPending ? <span style={{ fontWeight: 400, color: 'var(--text-3)', fontSize: 10 }}> · Backend Pending</span> : null}</div>
      {rows.map((r, i) => {
        const live = typeof _c[r.to] === 'number';
        return (
          <button key={r.label} data-testid={`acc-ov-jump-${r.to}`} onClick={() => onJump && onJump(r.to)}
            style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 14px', borderBottom: i < rows.length - 1 ? '1px solid var(--border-subtle)' : 'none', fontSize: 12, color: 'var(--text-2)', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit' }}>
            <span>{r.label}</span>
            {live ? (
              <span data-testid={`acc-ov-count-${r.to}`} title={_r[r.to] || undefined} style={{ color: 'var(--text)', fontFamily: 'monospace', fontWeight: 700 }}>{_c[r.to]} ›</span>
            ) : (
              <span data-testid={`acc-ov-count-${r.to}`} title={_r[r.to] || 'Backend Pending'} style={{ color: 'var(--text-3)', fontFamily: 'monospace' }}>— ›</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
function AccountingOverview({ onJump }) {
  // Wave 4 Item 2 — wire ONLY provable doc counts. Proforma has a true unbounded
  // count (GET /proforma/search → data.total = COUNT(*) of proforma_drafts). All
  // other counts stay Backend Pending: invoices/credit-notes come from wFirma
  // invoices/find which returns a PAGE (count = page length, not a grand total);
  // WZ/PW/RW/MM are Item 3B (undocumented wFirma warehouse-doc reads); PZ has no
  // warehouse-document total authority (dashboard/batches is a capped import
  // pipeline proxy, not the wFirma PZ-document count). Read-only; no aggregate
  // engine, no cache, no cross-currency sum.
  const [counts, setCounts] = React.useState({});
  React.useEffect(() => {
    let cancelled = false;
    window.PzApi.searchProformaDrafts({ page_size: 1 }).then(res => {
      if (cancelled) return;
      const total = res && res.ok && res.data && typeof res.data.total === 'number' ? res.data.total : null;
      if (typeof total === 'number') setCounts(c => ({ ...c, pi: total }));
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  const _reasons = {
    pi: 'Source: proforma_drafts (all states) · GET /api/v1/proforma/search total',
    inv: 'Page from wFirma invoices/find (no grand total)',
    cn:  'Page from wFirma invoices/find (no grand total)',
    wz:  'Page from wFirma warehouse_documents (WZ)',
    pz:  'Page from wFirma warehouse_documents (PZ) — not the import batch pipeline',
    pw:  'Page from wFirma warehouse_documents (PW)',
    rw:  'Page from wFirma warehouse_documents (RW)',
    mm:  'Unavailable — wFirma MM controller not found',
  };
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
      <AccountingOverviewKpis />

      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <_AccDocPanel title="Sales documents" onJump={onJump} counts={counts} reasons={_reasons} rows={[{ label: 'Proforma issued', to: 'pi' }, { label: 'Invoices issued', to: 'inv' }, { label: 'Credit notes', to: 'cn' }, { label: 'WZ releases', to: 'wz' }]} />
        <_AccDocPanel title="Warehouse documents" onJump={onJump} counts={counts} reasons={_reasons} rows={[{ label: 'PZ (external receipt)', to: 'pz' }, { label: 'PW (internal receipt)', to: 'pw' }, { label: 'RW (internal release)', to: 'rw' }, { label: 'MM (transfer)', to: 'mm' }]} />
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
      {(actions || []).map(a => {
        const nav = a && a.nav;
        const label = typeof a === 'string' ? a : a.label;
        const click = (a && typeof a.onClick === 'function')
          ? a.onClick
          : (nav ? () => { if (typeof window !== 'undefined' && window.location) { window.location.hash = nav; } } : null);
        const disabled = !click;
        return (
          <button
            key={label}
            type="button"
            data-testid={'acc-grid-action-' + String(label).replace(/[^a-z0-9]+/gi, '-').toLowerCase().replace(/^-+|-+$/g, '')}
            disabled={disabled}
            title={disabled ? ((a && a.title) || 'Not available from Accounting Hub (read-only)') : ((a && a.title) || label)}
            onClick={() => { if (click) click(); }}
            style={{ padding: '5px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: disabled ? 'var(--text-3)' : 'var(--text)', fontSize: 11, fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.6 : 1 }}
          >{label}</button>
        );
      })}
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
        <tbody><tr><td colSpan={cols.length} style={{ padding: '28px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>— · Unavailable{note ? ` · ${note}` : ''}</td></tr></tbody>
      </table>
    </div>
  );
}
const _ACC_DOC_TITLES = {
  inv: { t: 'Invoice', c: 'INV', color: 'var(--badge-green-text)', wh: false },
  cn:  { t: 'Credit Note', c: 'CN', color: 'var(--badge-amber-text)', wh: false },
  wz:  { t: 'WZ — Outbound', c: 'WZ', color: 'var(--badge-purple-text)', wh: true },
  pz:  { t: 'PZ — Inbound', c: 'PZ', color: 'var(--accent)', wh: true },
  pw:  { t: 'PW — Internal in', c: 'PW', color: 'var(--badge-blue-text)', wh: true },
  rw:  { t: 'RW — Internal out', c: 'RW', color: 'var(--badge-red-text)', wh: true },
  mm:  { t: 'MM — Transfer', c: 'MM', color: 'var(--badge-neutral-text)', wh: true, blocked: true },
};
// Live reads: Invoice/CN + warehouse WZ/PZ/PW/RW. MM blocked (controller not found).
// Shared register contract: year/month/custom + page + limit=20 + sort=date_desc.
const _ACC_DOC_LIVE = { inv: 'invoice', cn: 'credit_note', wz: 'wz', pz: 'pz', pw: 'pw', rw: 'rw' };
const _ACC_PAGE_LIMIT = 20;

function formatAccUpstreamError(err) {
  const s = String(err == null ? '' : err);
  if (!s) return 'Retry shortly.';
  if (/<!DOCTYPE|<html[\s>]|cloudflare/i.test(s)) {
    return 'Wait a moment, then retry.';
  }
  if (s === '[object Object]') return 'Retry shortly.';
  const cleaned = s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  return cleaned.length > 160 ? `${cleaned.slice(0, 157)}…` : cleaned;
}

function AccAwbCell({ docType, wfirmaId }) {
  const [st, setSt] = React.useState({ loading: false, awbs: null, err: null });
  React.useEffect(() => {
    if (!docType || !wfirmaId || !window.PzApi.getAccountingDocAwbs) return;
    let cancelled = false;
    setSt({ loading: true, awbs: null, err: null });
    window.PzApi.getAccountingDocAwbs(docType, wfirmaId).then((res) => {
      if (cancelled) return;
      if (!res || !res.ok) {
        setSt({ loading: false, awbs: [], err: (res && res.error) || 'AWB unavailable' });
        return;
      }
      setSt({ loading: false, awbs: (res.data && res.data.awbs) || [], err: null });
    }).catch((e) => {
      if (!cancelled) setSt({ loading: false, awbs: [], err: (e && e.message) || String(e) });
    });
    return () => { cancelled = true; };
  }, [docType, wfirmaId]);

  if (st.loading) return <span style={{ color: 'var(--text-3)', fontSize: 10 }}>…</span>;
  if (!st.awbs || st.awbs.length === 0) {
    return <span style={{ color: 'var(--text-3)', fontSize: 10 }} title={st.err || 'No AWB'}>—</span>;
  }
  const runAction = (awb, action) => {
    const a = (awb || '').trim();
    if (!a) return;
    if (action === 'Open Shipment' || action === 'Resolve in Logistics') {
      window.location.hash = `#logistics/${encodeURIComponent(a)}`;
      return;
    }
    if (action === 'Track') {
      window.location.hash = `#logistics/${encodeURIComponent(a)}?tab=track`;
      return;
    }
    if (action === 'Waybill' || action === 'Label') {
      window.location.hash = `#logistics/${encodeURIComponent(a)}?tab=documents`;
    }
  };
  return (
    <div data-testid={`acc-awb-cell-${wfirmaId}`} style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 120 }}>
      {st.awbs.map((a) => (
        <div key={a.awb} style={{ fontSize: 10, lineHeight: 1.3 }}>
          <span style={{ fontFamily: 'monospace', color: 'var(--text)' }}>{a.awb}</span>
          <span style={{ color: 'var(--text-3)', marginLeft: 4 }}>{a.carrier}</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 2 }}>
            {(a.actions || []).map((act) => (
              <button key={act} type="button" data-testid={`acc-awb-action-${act.replace(/\s+/g, '-').toLowerCase()}`}
                onClick={() => runAction(a.awb, act)}
                style={{ padding: '1px 5px', fontSize: 9, borderRadius: 3, border: '1px solid var(--border)', background: 'var(--card)', cursor: 'pointer' }}>
                {act}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
function _accDefaultYear() { return String(new Date().getFullYear()); }
function AccRegisterPager({ page, hasMore, loading, onPrev, onNext, year, years, onYear, testId }) {
  const btn = {
    padding: '5px 12px', fontSize: 11, borderRadius: 5, border: '1px solid var(--border)',
    background: 'var(--card)', color: 'var(--text)', cursor: 'pointer',
  };
  const btnDis = { ...btn, opacity: 0.45, cursor: 'not-allowed' };
  return (
    <div data-testid={testId || 'acc-register-pager'} style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, maxWidth: '100%' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', minWidth: 0 }}>
        <label style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 700 }}>Year</label>
        <select data-testid="acc-register-year" value={year} onChange={(e) => onYear(e.target.value)}
          style={{ padding: '5px 8px', fontSize: 12, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', maxWidth: '100%' }}>
          {(years || []).map(y => <option key={y} value={String(y)}>{y}</option>)}
          <option value="all">All Years</option>
        </select>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>latest first · {_ACC_PAGE_LIMIT}/page</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <button type="button" data-testid="acc-register-prev" disabled={loading || page <= 1} onClick={onPrev} style={loading || page <= 1 ? btnDis : btn}>Previous</button>
        <span data-testid="acc-register-page-label" style={{ fontSize: 12, color: 'var(--text-2)', minWidth: 72, textAlign: 'center' }}>Page {page}</span>
        <button type="button" data-testid="acc-register-next" disabled={loading || !hasMore} onClick={onNext} style={loading || !hasMore ? btnDis : btn}>Next</button>
      </div>
    </div>
  );
}
function AccDocGrid({ sectionId, onNav }) {
  const m = _ACC_DOC_TITLES[sectionId] || { t: sectionId, c: null, wh: false };
  const cols = m.wh
    ? ['Type', 'Number', 'Date', 'Party', 'Net', 'Gross', 'AWB / Logistics', 'Actions']
    : ['Number', 'Date', 'Party', 'Net', 'Tax', 'Gross', 'Cur', 'Payment', 'Due', 'Actions'];
  const docType = m.blocked ? null : _ACC_DOC_LIVE[sectionId];
  const RegFilter = window.AccountingRegisterFilter;
  const [filter, setFilter] = React.useState(null);
  const [years, setYears] = React.useState(() => {
    const y = new Date().getFullYear();
    return Array.from({ length: 11 }, (_, i) => y - i);
  });
  const [st, setSt] = React.useState({ loading: !!docType, error: null, rows: null, hasMore: false });

  const yearParam = React.useMemo(() => {
    if (!filter || !filter.period) return _accDefaultYear();
    const y = (filter.year != null ? filter.year : new Date(filter.period.from).getFullYear());
    if (String(y) === 'all') return 'all';
    return String(y);
  }, [filter]);

  React.useEffect(() => {
    if (!docType || !filter) return;
    let cancelled = false;
    setSt((s) => ({ ...s, loading: true, error: null }));
    const params = {
      page: filter.page || 1,
      limit: _ACC_PAGE_LIMIT,
      year: yearParam,
      sort: 'date_desc',
      date_from: filter.period.from,
      date_to: filter.period.to,
    };
    window.PzApi.listAccountingDocs(docType, params).then((res) => {
      if (cancelled) return;
      if (!res || !res.ok) {
        setSt({ loading: false, error: formatAccUpstreamError((res && res.error) || 'Load failed'), rows: null, hasMore: false });
        return;
      }
      const d = res.data || {};
      if (Array.isArray(d.years_available) && d.years_available.length) {
        setYears(d.years_available.map(Number));
      }
      setSt({
        loading: false,
        error: null,
        rows: d.rows || [],
        hasMore: !!d.has_more,
      });
    }).catch((e) => {
      if (!cancelled) setSt({ loading: false, error: formatAccUpstreamError((e && e.message) || String(e)), rows: null, hasMore: false });
    });
    return () => { cancelled = true; };
  }, [docType, filter, yearParam]);

  const filteredRows = React.useMemo(() => {
    let rows = st.rows || [];
    const q = ((filter && filter.search) || '').trim().toLowerCase();
    if (q) {
      rows = rows.filter((r) => {
        const hay = [r.number, r.party_name, r.party, r.contractor_id].filter(Boolean).join(' ').toLowerCase();
        return hay.includes(q);
      });
    }
    const ccy = ((filter && filter.currency) || '').trim().toUpperCase();
    if (ccy) rows = rows.filter((r) => (r.currency || '').toUpperCase() === ccy);
    const stf = ((filter && filter.status) || '').trim().toLowerCase();
    if (stf) {
      rows = rows.filter((r) => {
        const ps = (r.payment_state || r.state || '').toLowerCase();
        return ps.includes(stf) || ps === stf;
      });
    }
    return rows;
  }, [st.rows, filter]);
  const actions = m.wh
    ? (
        m.c === 'PZ'
          ? [{ label: '+ New PZ', nav: '#dashboard', title: 'Open canonical PZ / goods-receipt workflow (navigate only)' }]
          : [{ label: `+ New ${m.c}`, nav: null, title: `${m.c} create is not owned by Accounting Hub — create in wFirma if needed` }]
      )
    : sectionId === 'cn'
      ? [{ label: 'Create in wFirma', nav: null, title: 'Credit Notes are fiscal wFirma documents. Atlas Accounting has no approved CN write authority — create/correct in wFirma.' }]
      : [{ label: '+ New Proforma', nav: '#proforma', title: 'Open canonical Proforma workflow' }];
  if (onNav && !m.wh && sectionId !== 'cn') {
    actions[0] = {
      label: '+ New Proforma',
      nav: null,
      title: 'Open canonical Proforma workflow',
      onClick: () => onNav('proforma'),
    };
  }
  if (onNav && m.c === 'PZ') {
    actions[0] = {
      label: '+ New PZ',
      nav: null,
      title: 'Open canonical PZ workflow (navigate only)',
      onClick: () => onNav('dashboard'),
    };
  }
  const td = { padding: '7px 10px', fontSize: 11.5, color: 'var(--text-2)', whiteSpace: 'nowrap' };
  const tdm = { ...td, fontFamily: 'monospace', textAlign: 'right' };
  const thAmt = { padding: '8px 10px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', position: 'sticky', top: 0, background: 'var(--bg-subtle)' };
  const th = { padding: '8px 10px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', position: 'sticky', top: 0, background: 'var(--bg-subtle)' };
  const openPdf = (row, disposition) => {
    if (!row || !row.wfirma_id || !window.PzApi.openAccountingDocPdf) return;
    window.PzApi.openAccountingDocPdf(docType, row.wfirma_id, disposition, row.number);
  };
  return (
    <div data-testid={`acc-grid-${sectionId}`} style={{ padding: '20px 28px' }}>
      <_AccGridHeader title={m.t} code={m.c} color={m.color} actions={actions} />
      {m.blocked && (
        <div data-testid={`acc-grid-${sectionId}-mm-unsupported`} style={{
          padding: '20px 16px', marginBottom: 12, borderRadius: 8,
          background: 'var(--badge-neutral-bg)', border: '1px solid var(--badge-neutral-border)',
          color: 'var(--badge-neutral-text)', fontSize: 12,
        }}>
          MM warehouse transfers are <strong>unsupported</strong> — wFirma controller
          <code style={{ margin: '0 4px' }}>warehouse_document_m_m</code> was not found in live checks.
          This is not Backend Pending; do not expect a future MM register here without a new wFirma authority probe.
        </div>
      )}
      {m.blocked && <_AccPendingTable cols={cols} note="MM unavailable — wFirma controller not found (unsupported)" />}
      {!m.blocked && !docType && <_AccPendingTable cols={cols} note="GET /api/v1/accounting/{type}" />}
      {docType && (
        <>
          {typeof RegFilter === 'function' ? (
            <RegFilter
              testIdPrefix={`acc-pager-${sectionId}`}
              pageSize={_ACC_PAGE_LIMIT}
              showSearch
              showCurrency={!m.wh}
              showStatus={!m.wh}
              statusOptions={['', 'Outstanding', 'Paid', 'Not specified']}
              loading={st.loading}
              hasMore={st.hasMore}
              onChange={setFilter}
            />
          ) : (
            <AccRegisterPager
              page={(filter && filter.page) || 1} hasMore={st.hasMore} loading={st.loading}
              year={yearParam} years={years} onYear={() => {}}
              onPrev={() => {}} onNext={() => {}}
              testId={`acc-pager-${sectionId}`}
            />
          )}
          <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'auto', maxHeight: 'calc(100vh - 260px)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                {cols.map(c => <th key={c} style={['Net', 'Tax', 'Gross'].includes(c) ? thAmt : th}>{c}</th>)}
              </tr></thead>
              <tbody>
                {st.loading && <tr><td colSpan={cols.length} style={{ padding: '28px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}><span className="spinner" /> Loading from wFirma…</td></tr>}
                {st.error && !st.loading && <tr><td colSpan={cols.length} data-testid={`acc-grid-${sectionId}-error`} style={{ padding: '20px 16px', textAlign: 'center', color: 'var(--badge-red-text)', fontSize: 12 }}>
                  {/temporarily unavailable|502|503|unreachable/i.test(String(st.error))
                    ? `${m.t} temporarily unavailable from wFirma. `
                    : 'wFirma read unavailable. '}
                  <button type="button" data-testid={`acc-grid-${sectionId}-retry`} onClick={() => setFilter((f) => (f ? { ...f } : f))} style={{ marginLeft: 8, fontSize: 11, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: 'pointer' }}>Retry</button>
                  <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-3)' }}>{formatAccUpstreamError(st.error)}</div>
                </td></tr>}
                {!st.loading && !st.error && filteredRows && filteredRows.length === 0 && <tr><td colSpan={cols.length} data-testid={`acc-grid-${sectionId}-empty`} style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>No {m.t.toLowerCase()} documents found.</td></tr>}
                {!st.loading && !st.error && filteredRows && filteredRows.map((r, i) => (
                  <tr key={r.wfirma_id || i} data-testid={`acc-grid-${sectionId}-row`} style={{ borderBottom: i < filteredRows.length - 1 ? '1px solid var(--border-subtle)' : 'none' }}>
                    {m.wh && <td style={{ ...td, color: 'var(--text)', fontWeight: 700 }}>{r.doc_type || m.c}</td>}
                    <td style={{ ...td, fontFamily: 'monospace', color: 'var(--text)' }}>{r.number}</td>
                    <td style={td}>{r.date || '—'}</td>
                    <td style={{ ...td, color: 'var(--text)', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.party_name || r.party}</td>
                    {m.wh ? (
                      <>
                        <td style={tdm}>{r.net}</td>
                        <td style={{ ...tdm, color: 'var(--text)' }}>{r.gross}</td>
                        <td style={{ ...td, color: 'var(--text-3)' }}>
                          {(m.c === 'WZ' || m.c === 'PZ') && r.wfirma_id
                            ? <AccAwbCell docType={docType} wfirmaId={r.wfirma_id} />
                            : (r.awb || '—')}
                        </td>
                      </>
                    ) : (
                      <>
                        <td style={tdm}>{r.net}</td>
                        <td style={tdm}>{r.tax}</td>
                        <td style={{ ...tdm, color: 'var(--text)' }}>{r.gross}</td>
                        <td style={td}>{r.currency}</td>
                        <td style={{ ...td, fontSize: 11 }}>{r.payment_state || r.state}</td>
                        <td style={td}>{r.payment_due_date || '—'}</td>
                      </>
                    )}
                    <td style={{ ...td }}>
                      {!m.wh && r.pdf_available !== false && r.wfirma_id ? (
                        <span style={{ display: 'inline-flex', gap: 6 }}>
                          <button type="button" data-testid={`acc-pdf-view-${sectionId}`} onClick={() => openPdf(r, 'inline')} style={{ padding: '3px 8px', fontSize: 10, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }}>View PDF</button>
                          <button type="button" data-testid={`acc-pdf-dl-${sectionId}`} onClick={() => openPdf(r, 'attachment')} style={{ padding: '3px 8px', fontSize: 10, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }}>Download</button>
                        </span>
                      ) : m.wh ? (
                        <span style={{ color: 'var(--text-3)', fontSize: 10 }} title="Warehouse PDF unproven">—</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
// Wave 4 Item 4 — live Client Balance roster (GET /api/v1/ledgers/clients).
// Open / Overdue(invoice-age) / YTD / Cur / State are DOCUMENTED (reuse the
// Statement authority). "Last 30d" and due-date Overdue are Backend Pending —
// rendered honestly ("—", disclosed), never faked.
const _ACC_BAL_COLS = ['Client', 'Open', 'Overdue', 'Last 30d', 'YTD', 'Cur', 'State'];
function AccClientBalance({ onOpenLedger }) {
  const [st, setSt] = React.useState({ loading: true, error: null, rows: null, asOf: null, source: null });
  React.useEffect(() => {
    let cancelled = false;
    setSt({ loading: true, error: null, rows: null, asOf: null, source: null });
    const today = new Date().toISOString().slice(0, 10);
    // Position view: current outstanding as-of today. Activity YTD stays on Client Ledger.
    window.PzApi.getManagementAnalysis({ as_of: today, scope: 'all_outstanding' }).then(res => {
      if (cancelled) return;
      if (!res || !res.ok) { setSt({ loading: false, error: (res && res.error) || 'Load failed', rows: null, asOf: null, source: null }); return; }
      const d = res.data || {};
      const rows = (d.customers || []).slice(0, 20).map(r => ({
        contractor_id: r.contractor_id,
        name: r.customer_name,
        open: r.outstanding,
        overdue_invoice_age: r.overdue,
        currency: r.currency,
        state: Number(r.overdue) > 0 ? 'overdue' : (Number(r.outstanding) > 0 ? 'outstanding' : 'clear'),
        balance_available: true,
      }));
      setSt({ loading: false, error: null, rows, asOf: d.as_of || today, source: d.source || 'local' });
    }).catch(e => { if (!cancelled) setSt({ loading: false, error: (e && e.message) || String(e), rows: null, asOf: null, source: null }); });
    return () => { cancelled = true; };
  }, []);
  const td = { padding: '9px 12px', fontSize: 11.5, color: 'var(--text-2)' };
  const tdm = { ...td, fontFamily: 'monospace', textAlign: 'right' };
  const dash = <span style={{ color: 'var(--text-3)' }}>—</span>;
  return (
    <div data-testid="acc-balance" style={{ padding: '20px 28px' }}>
      <_AccGridHeader title="Client Balance" actions={[
        { label: 'Open Client Ledger', nav: null, title: 'Reuse existing statement authority' },
      ]} />
      <div style={{ marginBottom: 10 }}>
        <button type="button" data-testid="acc-balance-open-ledger" onClick={() => onOpenLedger && onOpenLedger()}
          style={{ padding: '5px 12px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}>
          Open Client Ledger (statement authority)
        </button>
      </div>
      {st.asOf && (
        <div style={{ fontSize: 10.5, color: 'var(--text-3)', margin: '-6px 0 10px' }}>
          Position as of {st.asOf} · source {st.source || 'local'} · overdue = due-date aging · YTD / last 30d are activity views on Client Ledger
        </div>
      )}
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
            {_ACC_BAL_COLS.map(c => <th key={c} style={{ padding: '10px 12px', textAlign: ['Open', 'Overdue', 'YTD'].includes(c) ? 'right' : 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{c}</th>)}
          </tr></thead>
          <tbody>
            {st.loading && <tr><td colSpan={_ACC_BAL_COLS.length} style={{ padding: '28px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}><span className="spinner" /> Loading client position…</td></tr>}
            {st.error && !st.loading && <tr><td colSpan={_ACC_BAL_COLS.length} data-testid="acc-balance-error" style={{ padding: '20px 16px', textAlign: 'center', color: 'var(--badge-red-text)', fontSize: 12 }}>wFirma read unavailable. {formatAccUpstreamError(st.error)}</td></tr>}
            {!st.loading && !st.error && st.rows && st.rows.length === 0 && <tr><td colSpan={_ACC_BAL_COLS.length} style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>No clients in Customer Master.</td></tr>}
            {!st.loading && !st.error && st.rows && st.rows.map((r, i) => (
              <tr key={r.contractor_id || i} data-testid="acc-balance-row"
                onClick={() => onOpenLedger && onOpenLedger()}
                style={{ borderBottom: i < st.rows.length - 1 ? '1px solid var(--border-subtle)' : 'none', cursor: onOpenLedger ? 'pointer' : 'default' }}>
                <td style={{ ...td, color: 'var(--text)' }}>{r.name || r.contractor_id || '—'}</td>
                <td style={tdm}>{r.balance_available ? (r.open != null ? r.open : <span title="Multi-currency — see Client Ledger" style={{ color: 'var(--text-3)' }}>multi</span>) : dash}</td>
                <td style={tdm} title="Due-date aging">{r.balance_available && r.overdue_invoice_age != null ? r.overdue_invoice_age : dash}</td>
                <td style={td} title="Activity view — open Client Ledger">{dash}</td>
                <td style={td} title="Activity view — open Client Ledger">{dash}</td>
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
// Wave 4 Item 7 — PULL-ONLY wFirma sync. Approved pull actions are wired to
// read-only endpoints; every PUSH action is visible but DISABLED as CP4-gated
// (writes to live wFirma need separate operator approval). Per-source status is
// shown honestly — there is deliberately NO single unified "synced" indicator.
function _SyncSrcCard({ testid, title, direction, children }) {
  const push = direction === 'PUSH';
  return (
    <div data-testid={testid} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 14px', flex: 1, minWidth: 220 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>{title}</span>
        <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, textTransform: 'uppercase', letterSpacing: '0.04em',
          background: push ? 'var(--badge-red-bg)' : 'var(--badge-green-bg)', color: push ? 'var(--badge-red-text)' : 'var(--badge-green-text)' }}>
          {push ? 'PUSH · CP4' : 'PULL'}
        </span>
      </div>
      {children}
    </div>
  );
}
function AccWfirmaSyncInline({ onNav }) {
  const [cust, setCust] = React.useState({ busy: false, msg: null });
  const [pay, setPay]   = React.useState({ busy: false, msg: null, cid: '' });
  const [hook, setHook] = React.useState({ busy: false, msg: null, data: null });

  const doWebhookStatus = () => {
    setHook(s => ({ ...s, busy: true, msg: null }));
    window.PzApi.getWfirmaWebhookStatus().then(r => {
      if (!r || !r.ok) { setHook({ busy: false, msg: 'status unavailable', data: null }); return; }
      const d = r.data || {};
      const svc = d.service || {};
      const q = d.queue || {};
      const recon = d.reconciliation || {};
      const sched = svc.scheduler_running ? 'running' : 'idle';
      const last = svc.last_tick_at ? String(svc.last_tick_at).replace('T', ' ').slice(0, 16) : '';
      setHook({
        busy: false,
        data: d,
        msg: `scheduler ${sched}${last ? ' · last tick ' + last : ''} · queue ${q.total || 0} · dead letter ${q.dead_letter || 0}${recon.stale_pending ? ' · stale pending ' + recon.stale_pending : ''}`,
      });
    }).catch(() => setHook({ busy: false, msg: 'status error', data: null }));
  };

  React.useEffect(() => { doWebhookStatus(); }, []);

  const doCustomerPreview = () => {
    setCust({ busy: true, msg: null });
    window.PzApi.previewWfirmaSyncCustomer().then(r => {
      if (!r || !r.ok) { setCust({ busy: false, msg: 'preview unavailable' }); return; }
      const d = r.data || {};
      const n = (d.insert || d.insertions || []).length, u = (d.update_fill || []).length + (d.update_match || []).length;
      setCust({ busy: false, msg: `preview: ${n} new · ${u} fill/match (apply from Customer Master)` });
    }).catch(() => setCust({ busy: false, msg: 'preview error' }));
  };
  const doPaymentsPull = () => {
    const cid = (pay.cid || '').trim();
    if (!cid) { setPay(s => ({ ...s, msg: 'enter a contractor id' })); return; }
    setPay(s => ({ ...s, busy: true, msg: null }));
    window.PzApi.pullPayments(cid).then(r => {
      if (!r || !r.ok) { setPay(s => ({ ...s, busy: false, msg: (r && r.error) || 'pull failed' })); return; }
      const d = r.data || {};
      setPay(s => ({ ...s, busy: false, msg: `pulled: ${d.new != null ? d.new : '?'} new · ${d.existing != null ? d.existing : '?'} existing` }));
    }).catch(e => setPay(s => ({ ...s, busy: false, msg: (e && e.message) || 'error' })));
  };

  const pullBtn = { padding: '5px 10px', borderRadius: 5, border: '1px solid var(--accent-border)', background: 'var(--accent)', color: 'var(--accent-text)', fontSize: 11, fontWeight: 600, cursor: 'pointer' };
  const cp4Btn  = { padding: '5px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11, fontWeight: 600, cursor: 'not-allowed', opacity: 0.6 };
  const msg = (m) => m ? <div style={{ fontSize: 10.5, color: 'var(--text-2)', marginTop: 6 }}>{m}</div> : null;

  return (
    <div data-testid="acc-wfirma-sync" style={{ padding: '20px 28px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>wFirma Sync</h2>
        <div style={{ flex: 1 }} />
        <button data-testid="acc-wfirma-open-setup" onClick={() => onNav && onNav('wfirma_setup')} title="EJ Extension — open the full wFirma setup" style={{ padding: '5px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}>Open full wFirma setup →</button>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 12 }}>Pull actions read from wFirma (read-only). Push actions that write to live wFirma are <strong>CP4-gated</strong> and disabled here. Status is per-source — no single unified indicator.</div>

      {/* PULL — read-only from wFirma */}
      <div data-testid="acc-wfirma-pull" style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Pull — read-only from wFirma</div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 18, flexWrap: 'wrap' }}>
        <_SyncSrcCard testid="acc-wfirma-src-customer" title="Customer ← wFirma" direction="PULL">
          <button data-testid="acc-wfirma-customer-pull" disabled={cust.busy} onClick={doCustomerPreview} style={pullBtn}>{cust.busy ? 'Loading…' : 'Preview pull'}</button>
          <span style={{ fontSize: 10, color: 'var(--text-3)', marginLeft: 8 }}>reuses sync-from-wfirma/preview</span>
          {msg(cust.msg)}
        </_SyncSrcCard>
        <_SyncSrcCard testid="acc-wfirma-src-payments" title="Payments ← wFirma" direction="PULL">
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <input data-testid="acc-wfirma-payments-contractor" value={pay.cid} onChange={e => setPay(s => ({ ...s, cid: e.target.value }))}
              placeholder="contractor id" style={{ width: 110, padding: '4px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 11 }} />
            <button data-testid="acc-wfirma-payments-pull" disabled={pay.busy} onClick={doPaymentsPull} style={pullBtn}>{pay.busy ? 'Pulling…' : 'Pull now'}</button>
          </div>
          {msg(pay.msg)}
        </_SyncSrcCard>
        <_SyncSrcCard testid="acc-wfirma-src-webhook" title="Webhook status" direction="PULL">
          <button data-testid="acc-wfirma-webhook-status" disabled={hook.busy} onClick={doWebhookStatus} style={pullBtn}>{hook.busy ? '…' : 'Refresh status'}</button>
          <span style={{ fontSize: 10, color: 'var(--text-3)', marginLeft: 8 }}>reuses webhooks/wfirma/status</span>
          {msg(hook.msg)}
          {hook.data && (hook.data.queue || hook.data.reconciliation) && (
            <div data-testid="acc-wfirma-webhook-detail" style={{ marginTop: 8, fontSize: 10.5, color: 'var(--text-2)' }}>
              <div>Completed {(hook.data.queue && hook.data.queue.completed) || 0} · unmatched {(hook.data.queue && hook.data.queue.unmatched) || 0} · failed {(hook.data.queue && hook.data.queue.enrichment_failed) || 0}</div>
              {(hook.data.reconciliation && hook.data.reconciliation.events_without_processing > 0) && (
                <div data-testid="acc-wfirma-webhook-wh009">Watchdog: {hook.data.reconciliation.events_without_processing} events without processing row</div>
              )}
              {(hook.data.recent_dead_letters || []).slice(0, 5).map((dl, i) => (
                <div key={i} data-testid={`acc-wfirma-dead-letter-${i}`} style={{ color: 'var(--badge-red-text)', marginTop: 2 }}>
                  Dead letter {dl.event_id || '—'}{dl.retry_count != null ? ` · retries ${dl.retry_count}` : ''}{dl.last_error ? ` · ${formatAccUpstreamError(dl.last_error)}` : ''}
                </div>
              ))}
            </div>
          )}
        </_SyncSrcCard>
        <_SyncSrcCard testid="acc-wfirma-src-invoice" title="Invoice read" direction="PULL">
          <button data-testid="acc-wfirma-invoice-jump" onClick={() => onNav && onNav('inv')} style={pullBtn}>Open Invoices →</button>
          <div style={{ fontSize: 10.5, color: 'var(--text-2)', marginTop: 6 }}>read live via Invoice / Credit Note grids (invoices/find)</div>
        </_SyncSrcCard>
        <_SyncSrcCard testid="acc-wfirma-src-stock" title="Stock ← wFirma" direction="PULL">
          <div data-testid="acc-wfirma-stock-pending" style={{ fontSize: 10.5, color: 'var(--badge-amber-text)' }}>Backend Pending</div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 4 }}>get_stock is read-only (GET goods/find), but no persistence target exists yet (OI-10).</div>
        </_SyncSrcCard>
      </div>

      {/* PUSH — CP4-gated, disabled */}
      <div data-testid="acc-wfirma-push-cp4" style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Push — writes to wFirma · CP4-gated (disabled)</div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {[['acc-wfirma-push-customer', 'Customer → wFirma'], ['acc-wfirma-push-product', 'Product → wFirma'], ['acc-wfirma-push-invoice', 'Invoice / Proforma create'], ['acc-wfirma-push-goods', 'Goods edit (names)']].map(([tid, label]) => (
          <_SyncSrcCard key={tid} testid={`${tid}-card`} title={label} direction="PUSH">
            <button data-testid={tid} disabled title="CP4-gated — requires separate explicit operator approval" style={cp4Btn}>Blocked · CP4</button>
          </_SyncSrcCard>
        ))}
      </div>
    </div>
  );
}

// ── Treasury — balances, manual entry, bank import, daily CFO close ───────────
function AccTreasuryPanel() {
  const today = new Date().toISOString().slice(0, 10);
  const [asOf, setAsOf] = React.useState(today);
  const [rows, setRows] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const [msg, setMsg] = React.useState(null);
  const [manual, setManual] = React.useState({
    effective_date: today, account_location: '', currency: 'PLN',
    closing_balance: '', reference_note: '',
  });
  const [preview, setPreview] = React.useState(null);
  const [closeForm, setCloseForm] = React.useState({
    close_date: today, status: 'READY_TO_CLOSE',
    bank_balances_ok: false, cash_captured_ok: false,
    ar_refreshed_ok: false, ap_refreshed_ok: false,
    statements_ok: false, exceptions_reviewed: false, notes: '',
  });
  const fileRef = React.useRef(null);

  const loadBalances = React.useCallback(() => {
    if (!window.PzApi || !window.PzApi.getTreasuryBalances) {
      setErr('PzApi.getTreasuryBalances missing');
      return;
    }
    setLoading(true); setErr(null);
    window.PzApi.getTreasuryBalances(asOf).then((res) => {
      setLoading(false);
      if (!res || res.ok === false) {
        setErr((res && res.error) || 'treasury balances failed');
        setRows([]);
        return;
      }
      const body = res.data || res;
      setRows(body.rows || []);
    }).catch((e) => {
      setLoading(false);
      setErr((e && e.message) || 'treasury balances failed');
    });
  }, [asOf]);

  React.useEffect(() => { loadBalances(); }, [loadBalances]);

  const submitManual = () => {
    setMsg(null); setErr(null);
    window.PzApi.postTreasuryManualBalance(manual).then((res) => {
      if (!res || res.ok === false) {
        setErr((res && res.error) || 'manual balance write failed');
        return;
      }
      setMsg(`Manual balance saved (id=${(res.data || res).id}).`);
      loadBalances();
    });
  };

  const onPickFile = (ev) => {
    const f = ev.target.files && ev.target.files[0];
    if (!f) return;
    setMsg(null); setErr(null); setPreview(null);
    window.PzApi.previewTreasuryBankImport(f).then((res) => {
      if (!res || res.ok === false) {
        setErr((res && res.error) || 'import preview failed');
        return;
      }
      setPreview(res.data || res);
    });
  };

  const confirmImport = () => {
    if (!preview || !preview.batch_id) return;
    setMsg(null); setErr(null);
    window.PzApi.confirmTreasuryBankImport(preview.batch_id).then((res) => {
      if (!res || res.ok === false) {
        setErr((res && res.error) || 'import confirm failed');
        return;
      }
      const body = res.data || res;
      setMsg(`Import confirmed — inserted=${body.inserted}.`);
      setPreview(null);
      if (fileRef.current) fileRef.current.value = '';
      loadBalances();
    });
  };

  const submitClose = () => {
    setMsg(null); setErr(null);
    window.PzApi.postTreasuryDailyClose(closeForm).then((res) => {
      if (!res || res.ok === false) {
        setErr((res && res.error) || 'daily close write failed');
        return;
      }
      setMsg(`Daily close recorded (id=${(res.data || res).id}, status=${closeForm.status}).`);
    });
  };

  const inp = {
    display: 'block', marginTop: 4, padding: '5px 8px', width: '100%',
    border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', fontSize: 12,
  };
  const card = {
    padding: 14, border: '1px solid var(--border)', borderRadius: 8,
    background: 'var(--card)', marginBottom: 14,
  };

  return (
    <div data-testid="acc-treasury-root" style={{ padding: '20px 24px' }}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>Treasury</div>
      <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 14 }}>
        Local bank/cash closing balances and Daily CFO Close — not a wFirma authority.
        Writes require admin/accounts. Currencies stay separate.
      </div>
      {err && <div data-testid="acc-treasury-error" style={{ ...card, borderColor: 'var(--badge-red-border)', background: 'var(--badge-red-bg)', color: 'var(--badge-red-text)', fontSize: 12 }}>{err}</div>}
      {msg && <div data-testid="acc-treasury-msg" style={{ ...card, fontSize: 12, color: 'var(--badge-green-text)' }}>{msg}</div>}

      <div style={card} data-testid="acc-treasury-balances">
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', marginBottom: 10, flexWrap: 'wrap' }}>
          <label style={{ fontSize: 11, color: 'var(--text-3)' }}>As of
            <input data-testid="acc-treasury-asof" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} style={inp} />
          </label>
          <window.Btn small data-testid="acc-treasury-reload" onClick={loadBalances} disabled={loading}>
            {loading ? 'Loading…' : 'Reload balances'}
          </window.Btn>
          <a href={(window.PzApi.treasuryBalancesPdfUrl && window.PzApi.treasuryBalancesPdfUrl(asOf)) || `/api/v1/treasury/balances.pdf?as_of=${encodeURIComponent(asOf)}`}
             target="_blank" rel="noopener" data-testid="acc-treasury-pdf"
             style={{ fontSize: 11, fontWeight: 600, padding: '5px 10px', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', textDecoration: 'none' }}>
            ↓ Treasury PDF
          </a>
        </div>
        {!rows.length && !loading && (
          <div style={{ fontSize: 12, color: 'var(--text-3)' }}>No snapshots for this as-of date.</div>
        )}
        {!!rows.length && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--text-3)' }}>
                <th style={{ padding: '6px 8px' }}>Account</th>
                <th style={{ padding: '6px 8px' }}>Ccy</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Closing</th>
                <th style={{ padding: '6px 8px' }}>Source</th>
                <th style={{ padding: '6px 8px' }}>Effective</th>
                <th style={{ padding: '6px 8px' }}>Operator</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} data-testid={`acc-treasury-row-${r.id}`}>
                  <td style={{ padding: '6px 8px' }}>{r.account_location}</td>
                  <td style={{ padding: '6px 8px' }}>{r.currency}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{r.closing_balance}</td>
                  <td style={{ padding: '6px 8px' }}>{r.source}</td>
                  <td style={{ padding: '6px 8px' }}>{r.effective_date}</td>
                  <td style={{ padding: '6px 8px' }}>{r.operator || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={card} data-testid="acc-treasury-manual">
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>1 · Daily bank / cash entry</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
          <label style={{ fontSize: 11, color: 'var(--text-3)' }}>Effective date
            <input type="date" value={manual.effective_date} onChange={(e) => setManual({ ...manual, effective_date: e.target.value })} style={inp} data-testid="acc-treasury-manual-date" />
          </label>
          <label style={{ fontSize: 11, color: 'var(--text-3)' }}>Account / location
            <input value={manual.account_location} onChange={(e) => setManual({ ...manual, account_location: e.target.value })} style={inp} data-testid="acc-treasury-manual-account" placeholder="e.g. mBank PLN" />
          </label>
          <label style={{ fontSize: 11, color: 'var(--text-3)' }}>Currency
            <select value={manual.currency} onChange={(e) => setManual({ ...manual, currency: e.target.value })} style={inp} data-testid="acc-treasury-manual-ccy">
              <option>PLN</option><option>EUR</option><option>USD</option><option>CHF</option>
            </select>
          </label>
          <label style={{ fontSize: 11, color: 'var(--text-3)' }}>Closing balance
            <input value={manual.closing_balance} onChange={(e) => setManual({ ...manual, closing_balance: e.target.value })} style={inp} data-testid="acc-treasury-manual-balance" />
          </label>
          <label style={{ fontSize: 11, color: 'var(--text-3)', gridColumn: '1 / -1' }}>Note
            <input value={manual.reference_note} onChange={(e) => setManual({ ...manual, reference_note: e.target.value })} style={inp} data-testid="acc-treasury-manual-note" />
          </label>
        </div>
        <div style={{ marginTop: 10 }}>
          <window.Btn small data-testid="acc-treasury-manual-save" onClick={submitManual}>Write manual balance</window.Btn>
        </div>
      </div>

      <div style={card} data-testid="acc-treasury-import">
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>2 · Bank statement import (CSV / XLSX)</div>
        <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" data-testid="acc-treasury-import-file" onChange={onPickFile} />
        {preview && (
          <div style={{ marginTop: 10, fontSize: 12 }}>
            <div data-testid="acc-treasury-import-preview">
              Preview batch {preview.batch_id} — rows={ (preview.rows || []).length }
              {preview.valid === false ? ' · INVALID' : ' · valid'}
              {(preview.errors || []).length ? ` · errors=${preview.errors.length}` : ''}
            </div>
            <div style={{ marginTop: 8 }}>
              <window.Btn small data-testid="acc-treasury-import-confirm" onClick={confirmImport}
                disabled={preview.valid === false || (preview.errors || []).length > 0}>
                Confirm import
              </window.Btn>
            </div>
          </div>
        )}
      </div>

      <div style={card} data-testid="acc-treasury-daily-close">
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>3 · Daily CFO close</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>
          <label style={{ fontSize: 11, color: 'var(--text-3)' }}>Close date
            <input type="date" value={closeForm.close_date} onChange={(e) => setCloseForm({ ...closeForm, close_date: e.target.value })} style={inp} data-testid="acc-treasury-close-date" />
          </label>
          <label style={{ fontSize: 11, color: 'var(--text-3)' }}>Status
            <select value={closeForm.status} onChange={(e) => setCloseForm({ ...closeForm, status: e.target.value })} style={inp} data-testid="acc-treasury-close-status">
              <option value="INCOMPLETE">INCOMPLETE</option>
              <option value="READY_TO_CLOSE">READY_TO_CLOSE</option>
              <option value="CLOSED">CLOSED</option>
              <option value="CORRECTED">CORRECTED</option>
            </select>
          </label>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 10, fontSize: 12 }}>
          {[
            ['bank_balances_ok', 'Bank balances OK'],
            ['cash_captured_ok', 'Cash captured OK'],
            ['ar_refreshed_ok', 'AR refreshed OK'],
            ['ap_refreshed_ok', 'AP refreshed OK'],
            ['statements_ok', 'Statements OK'],
            ['exceptions_reviewed', 'Exceptions reviewed'],
          ].map(([k, lab]) => (
            <label key={k} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={!!closeForm[k]} data-testid={`acc-treasury-close-${k}`}
                onChange={(e) => setCloseForm({ ...closeForm, [k]: e.target.checked })} />
              {lab}
            </label>
          ))}
        </div>
        <label style={{ fontSize: 11, color: 'var(--text-3)', display: 'block', marginTop: 10 }}>Notes
          <input value={closeForm.notes} onChange={(e) => setCloseForm({ ...closeForm, notes: e.target.value })} style={inp} data-testid="acc-treasury-close-notes" />
        </label>
        <div style={{ marginTop: 10 }}>
          <window.Btn small data-testid="acc-treasury-close-save" onClick={submitClose}>Write daily close</window.Btn>
        </div>
      </div>
    </div>
  );
}

// ── Insurance Export Statement (read-only; component lives in insurance-export-tab.jsx) ──
function AccInsuranceExportSection() {
  const InsuranceExportTab = window.InsuranceExportTab;
  if (typeof InsuranceExportTab !== 'function') {
    return (
      <div style={{ padding: '32px 28px' }} data-testid="ins-export-missing">
        <AccError msg="InsuranceExportTab component not loaded. Check script load order in index.html." />
      </div>
    );
  }
  return <InsuranceExportTab />;
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
    { label: 'Ledgers',             ids: ['balance', 'clientLedger', 'insuranceExport', 'treasury'] },
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
        {section === 'clientLedger'   && <LedgersTab />}
        {section === 'insuranceExport' && <AccInsuranceExportSection />}
        {section === 'treasury'       && <AccTreasuryPanel />}
        {['inv', 'cn', 'wz', 'pz', 'pw', 'rw', 'mm'].includes(section) && <AccDocGrid sectionId={section} onNav={onNav} />}
        {section === 'balance'        && <AccClientBalance onOpenLedger={() => setSection('clientLedger')} />}
        {section === 'wfirma'         && <AccWfirmaSyncInline onNav={onNav} />}
        {section === 'audit'          && <AuditTrailTab />}
      </div>
    </div>
  );
}

window.AccountingHub = AccountingHub;
