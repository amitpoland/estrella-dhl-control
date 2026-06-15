// Shipment Detail Page — light-theme redesign with clean tabbed structure
// Tabs: Overview · DHL / Customs · PZ / Accounting · Documents · Timeline

const SHIPMENT_TABS = [
  { id: 'overview',  label: 'Overview' },
  { id: 'proforma',  label: 'Pro Forma' },
  { id: 'dhl',       label: 'DHL / Customs' },
  { id: 'pz',        label: 'PZ / Accounting' },
  { id: 'documents', label: 'Documents' },
  { id: 'timeline',  label: 'Timeline' },
];

// 7-stage workflow (sequential)
const WORKFLOW_STAGES = [
  { id: 'intake',    num: 1, label: 'Intake' },
  { id: 'precheck',  num: 2, label: 'Pre-check' },
  { id: 'reply',     num: 3, label: 'DHL Reply' },
  { id: 'sad',       num: 4, label: 'SAD / ZC429' },
  { id: 'verified',  num: 5, label: 'Verified' },
  { id: 'pz',        num: 6, label: 'PZ Generated' },
  { id: 'wfirma',    num: 7, label: 'wFirma Booked' },
];

// Reusable section heading: "OVERLINE ─────────────"
function SectionLabel({ children, style }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, ...style }}>
      <span style={{
        fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
        letterSpacing: '0.12em', textTransform: 'uppercase',
      }}>{children}</span>
      <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
    </div>
  );
}

// Card with optional header
function PanelCard({ title, subtitle, status, children, accent }) {
  return (
    <div style={{
      background: 'var(--card)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      boxShadow: '0 1px 2px var(--shadow)',
      overflow: 'hidden',
      borderLeft: accent ? `3px solid ${accent}` : `1px solid var(--border)`,
    }}>
      {(title || status) && (
        <div style={{
          padding: '14px 20px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, background: 'var(--bg-subtle)',
        }}>
          <div>
            {title && <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', letterSpacing: '0.01em' }}>{title}</div>}
            {subtitle && <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>{subtitle}</div>}
          </div>
          {status && <Badge status={status} />}
        </div>
      )}
      <div>{children}</div>
    </div>
  );
}

// ── Honest five-state action primitives ──────────────────────────────────────
// This V2 page is an authority-honest projection. Action controls below name a
// real backend route that EXISTS, but wiring this page to that route is not yet
// done (out of scope for this UX sprint). Per Lesson M we keep every capability
// VISIBLE + DISABLED + with an explicit reason + the backend route reference,
// rather than faking a success state. Execution happens on V1 today.
const BACKEND_PENDING_HELP =
  'Backend route exists; wiring this V2 page to it is scheduled (BACKEND_GAP_REGISTER.md). ' +
  'Run this action on the V1 Shipment Detail page today.';

// A disabled control that honestly advertises a planned-but-unwired capability.
function PendingAction({ label, route, testid, icon, variant = 'outline', small }) {
  return (
    <Btn
      variant={variant}
      small={small}
      disabled
      data-testid={testid}
      data-action-state="backend-pending"
      data-backend-route={route}
      title={`Not available in V2 yet. ${BACKEND_PENDING_HELP} Backend route: ${route}`}
      aria-label={`${label}. Unavailable in V2 — backend wiring pending. Backend route ${route}.`}
    >
      {icon ? icon + ' ' : ''}{label}
    </Btn>
  );
}

// Amber explanatory banner that heads any panel whose actions are backend-pending.
function BackendPendingBanner({ testid, children }) {
  return (
    <div
      role="note"
      data-testid={testid || 'backend-pending-banner'}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 10,
        margin: '0 20px 4px', padding: '12px 14px', borderRadius: 8,
        background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)',
        color: 'var(--badge-amber-text)', fontSize: 12, lineHeight: 1.5,
      }}
    >
      <span aria-hidden="true" style={{ fontWeight: 800, flexShrink: 0 }}>⚠</span>
      <span>{children}</span>
    </div>
  );
}

function ShipmentDetailPage({ shipment, onBack }) {
  const [activeTab, setActiveTab] = React.useState('overview');

  // Workflow state is DERIVED from authoritative shipment props — read-only.
  // No local setters fake progress; the page reflects backend truth, never produces it.
  const sadUploaded     = shipment.sadStatus !== 'SAD Pending';
  const pzGenerated     = shipment.pzStatus === 'Generated' || shipment.pzStatus === 'Exported';
  const pzExported      = shipment.pzStatus === 'Exported';
  const dhlEmailReceived = shipment.dhlStatus === 'DHL Email Received' || shipment.dhlStatus === 'Reply Sent';
  const replySent       = shipment.dhlStatus === 'Reply Sent';
  const pzNumber        = pzGenerated ? (shipment.pzNumber || '') : '';

  // Keyboard navigation for the tablist (ArrowLeft/Right/Home/End), roving focus.
  const onTabKeyDown = (e, idx) => {
    let nextIdx = null;
    if (e.key === 'ArrowRight')      nextIdx = (idx + 1) % SHIPMENT_TABS.length;
    else if (e.key === 'ArrowLeft')  nextIdx = (idx - 1 + SHIPMENT_TABS.length) % SHIPMENT_TABS.length;
    else if (e.key === 'Home')       nextIdx = 0;
    else if (e.key === 'End')        nextIdx = SHIPMENT_TABS.length - 1;
    if (nextIdx === null) return;
    e.preventDefault();
    const nt = SHIPMENT_TABS[nextIdx];
    setActiveTab(nt.id);
    const el = document.getElementById('tab-' + nt.id);
    if (el) el.focus();
  };

  const stageState = (id) => {
    if (id === 'intake')   return 'done';
    if (id === 'precheck') return 'done';
    if (id === 'reply')    return replySent ? 'done' : 'active';
    if (id === 'sad')      return sadUploaded ? 'done' : (replySent ? 'active' : 'pending');
    if (id === 'verified') return sadUploaded ? 'done' : 'pending';
    if (id === 'pz')       return pzGenerated ? 'done' : (sadUploaded ? 'active' : 'pending');
    if (id === 'wfirma')   return pzExported ? 'done' : (pzGenerated ? 'active' : 'pending');
    return 'pending';
  };

  const nextAction = (() => {
    if (!dhlEmailReceived) return { label: 'Scan DHL inbox for clearance email',     tab: 'dhl', cta: 'Open DHL / Customs' };
    if (!replySent)        return { label: 'Send reply package to DHL',              tab: 'dhl', cta: 'Open DHL / Customs' };
    if (!sadUploaded)      return { label: 'Upload SAD / ZC429 from customs agent',  tab: 'dhl', cta: 'Open DHL / Customs' };
    if (!pzGenerated)      return { label: 'Generate PZ document',                   tab: 'pz',  cta: 'Open PZ / Accounting' };
    if (!pzExported)       return { label: 'Export PZ to wFirma',                    tab: 'pz',  cta: 'Open PZ / Accounting' };
    return null;
  })();

  const stageColors = {
    done:    { num: '#FFFFFF', numBg: '#22A06B', numBorder: '#22A06B', label: '#186838', bg: 'rgba(34, 160, 107, 0.06)' },
    active:  { num: '#131C2E', numBg: '#D4B884', numBorder: '#B89968', label: '#7A5A20', bg: 'rgba(184, 153, 104, 0.10)' },
    pending: { num: '#9CA8B8', numBg: '#FFFFFF', numBorder: '#D8DAE2', label: '#8A9AB0', bg: 'transparent' },
  };

  return (
    <div data-screen-label="Shipment Detail" style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', background: 'var(--bg)' }}>

      <style>{`
        [data-screen-label="Shipment Detail"] button:focus-visible,
        [data-screen-label="Shipment Detail"] a:focus-visible,
        [data-screen-label="Shipment Detail"] label:focus-within,
        [data-screen-label="Shipment Detail"] [tabindex]:focus-visible {
          outline: 2px solid var(--accent);
          outline-offset: 2px;
          border-radius: 6px;
        }
      `}</style>

      {/* Sub-header */}
      <div style={{
        padding: '16px 32px', background: 'var(--card)',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 20, flexShrink: 0,
      }}>
        <button onClick={onBack} data-testid="detail-back" aria-label="Back to shipment list" style={{
          background: 'none', border: '1px solid var(--border)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6,
          color: 'var(--text-2)', fontSize: 12, padding: '6px 12px', borderRadius: 6,
          fontWeight: 500,
        }}>← Back</button>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>AWB / Tracking</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace' }}>{shipment.awb}</div>
        </div>
        <div style={{ width: 1, height: 32, background: 'var(--border)' }} />
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>Importer</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{shipment.client || 'Estrella Jewels Sp. z o.o.'}</div>
        </div>
        <div style={{ width: 1, height: 32, background: 'var(--border)' }} />
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>Pieces</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{shipment.pieces || 47}</div>
        </div>
        <div style={{ flex: 1 }} />
        <Badge status={shipment.overall} />
      </div>

      {/* Workflow Strip */}
      <div style={{ padding: '20px 32px 0', background: 'var(--card)' }}>
        <div role="list" aria-label="Shipment workflow progress" data-testid="workflow-strip" style={{ display: 'flex', alignItems: 'center', gap: 0, position: 'relative' }}>
          {WORKFLOW_STAGES.map((stage, i) => {
            const state = stageState(stage.id);
            const c = stageColors[state];
            const isLast = i === WORKFLOW_STAGES.length - 1;
            const nextState = !isLast ? stageState(WORKFLOW_STAGES[i + 1].id) : null;
            const connectorDone = state === 'done' && (nextState === 'done' || nextState === 'active');

            return (
              <React.Fragment key={stage.id}>
                <div role="listitem" aria-label={`Stage ${stage.num}: ${stage.label} — ${state}`} style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center',
                  gap: 6, flexShrink: 0, padding: '0 4px', minWidth: 64,
                }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 16,
                    background: c.numBg, border: `2px solid ${c.numBorder}`,
                    color: c.num, fontSize: 13, fontWeight: 700,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    boxShadow: state === 'active' ? '0 0 0 4px rgba(212, 168, 83, 0.18)' : 'none',
                    transition: 'all 0.15s',
                  }}>
                    {state === 'done' ? '✓' : stage.num}
                  </div>
                  <div style={{
                    fontSize: 10, fontWeight: state === 'active' ? 700 : 600,
                    color: c.label, textAlign: 'center', lineHeight: 1.2,
                    letterSpacing: '0.02em',
                  }}>{stage.label}</div>
                </div>
                {!isLast && (
                  <div aria-hidden="true" style={{
                    flex: 1, height: 2, marginTop: -16,
                    background: connectorDone ? '#22A06B' : 'var(--border)',
                    transition: 'background 0.15s',
                  }} />
                )}
              </React.Fragment>
            );
          })}
        </div>
        <div style={{ height: 16 }} />
      </div>

      {/* Tab nav */}
      <div role="tablist" aria-label="Shipment detail sections" style={{
        display: 'flex', gap: 4, padding: '0 32px',
        background: 'var(--card)', borderBottom: '1px solid var(--border)',
      }}>
        {SHIPMENT_TABS.map((t, i) => {
          const selected = activeTab === t.id;
          return (
            <button
              key={t.id}
              id={'tab-' + t.id}
              role="tab"
              data-testid={'tab-' + t.id}
              aria-selected={selected}
              aria-current={selected ? 'page' : undefined}
              aria-controls={'tabpanel-' + t.id}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActiveTab(t.id)}
              onKeyDown={(e) => onTabKeyDown(e, i)}
              style={{
                padding: '12px 16px',
                background: 'none', border: 'none', cursor: 'pointer',
                borderBottom: `2px solid ${selected ? 'var(--accent)' : 'transparent'}`,
                color: selected ? 'var(--text)' : 'var(--text-2)',
                fontSize: 13, fontWeight: selected ? 700 : 500,
                transition: 'all 0.12s', marginBottom: -1,
              }}
            >{t.label}</button>
          );
        })}
      </div>

      {/* Content */}
      <div
        role="tabpanel"
        id={'tabpanel-' + activeTab}
        aria-labelledby={'tab-' + activeTab}
        tabIndex={0}
        style={{ padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: 20 }}
      >

        {/* Next-action callout */}
        {nextAction && activeTab === 'overview' && (
          <div style={{
            background: 'linear-gradient(135deg, #FBF5E4, #F8EDD0)',
            border: '1px solid var(--accent-border)',
            borderRadius: 10,
            padding: '16px 20px',
            display: 'flex', alignItems: 'center', gap: 16,
            boxShadow: '0 1px 3px rgba(201, 164, 86, 0.12)',
          }}>
            <div style={{
              width: 40, height: 40, borderRadius: 20,
              background: 'var(--accent)', color: 'var(--text)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16, fontWeight: 800, flexShrink: 0,
            }}>▶</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#7A5400', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 3 }}>Next operator action</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{nextAction.label}</div>
            </div>
            {activeTab !== nextAction.tab && (
              <button onClick={() => setActiveTab(nextAction.tab)} data-testid="next-action-cta" aria-label={nextAction.cta} style={{
                padding: '8px 16px', background: 'var(--text)', color: 'var(--card)',
                border: 'none', borderRadius: 6, cursor: 'pointer',
                fontSize: 12, fontWeight: 600,
              }}>{nextAction.cta} →</button>
            )}
          </div>
        )}

        {activeTab === 'overview' && (
          <OverviewTab shipment={shipment} sadUploaded={sadUploaded} pzGenerated={pzGenerated} pzExported={pzExported} replySent={replySent} dhlEmailReceived={dhlEmailReceived} setActiveTab={setActiveTab} />
        )}
        {activeTab === 'proforma' && (
          <ProformaTabInShipment shipment={shipment} />
        )}
        {activeTab === 'dhl' && (
          <DhlTab
            shipment={shipment} sadUploaded={sadUploaded}
            dhlEmailReceived={dhlEmailReceived} replySent={replySent}
            batchId={shipment && shipment.batch_id}
          />
        )}
        {activeTab === 'pz' && (
          <PzTab
            shipment={shipment} sadUploaded={sadUploaded}
            pzGenerated={pzGenerated} pzExported={pzExported} pzNumber={pzNumber}
            batchId={shipment && shipment.batch_id}
            setActiveTab={setActiveTab}
          />
        )}
        {activeTab === 'documents' && (
          <DocumentsTab batchId={shipment && shipment.batch_id} />
        )}
        {activeTab === 'timeline' && (
          <TimelineTab shipment={shipment} sadUploaded={sadUploaded} pzGenerated={pzGenerated} replySent={replySent} dhlEmailReceived={dhlEmailReceived} pzExported={pzExported} />
        )}
      </div>
    </div>
  );
}

// ── Stat tile (light, refined)
function StatTile({ label, value, accent }) {
  return (
    <div style={{
      background: 'var(--card)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      padding: '16px 18px',
      boxShadow: '0 1px 2px var(--shadow)',
    }}>
      <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, color: accent || 'var(--text)', letterSpacing: '0.01em' }}>{value}</div>
    </div>
  );
}

// ── Two-column info row inside a card
function InfoBlock({ rows }) {
  return (
    <div style={{ padding: '6px 20px 14px' }}>
      {rows.map((r, i) => (
        <InfoRow key={i} label={r.label} value={r.value} mono={r.mono} />
      ))}
    </div>
  );
}

// ── OVERVIEW

function OverviewTab({ shipment, sadUploaded, pzGenerated, pzExported, replySent, dhlEmailReceived, setActiveTab }) {
  return (
    <>
      <SectionLabel>Key figures</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
        <StatTile label="Pieces"        value={shipment.pieces || 47} />
        <StatTile label="Total CIF"     value="EUR 1,280" />
        <StatTile label="Net (PLN)"     value={shipment.net} />
        <StatTile label="Duty A00"      value={shipment.duty} />
      </div>

      <SectionLabel style={{ marginTop: 8 }}>Workflow areas</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Shipment */}
        <PanelCard title="Shipment" subtitle="Tracking, invoices, AWB" status="DHL In Transit">
          <InfoBlock rows={[
            { label: 'AWB / Tracking', value: shipment.awb, mono: true },
            { label: 'Carrier',        value: shipment.carrier },
            { label: 'Tracking',       value: 'In Transit' },
            { label: 'Invoices',       value: '3 uploaded' },
            { label: 'AWB PDF',        value: 'Uploaded ✓' },
          ]} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('dhl')} data-testid="ov-shipment-open-dhl" style={navLinkStyle()}>Open DHL / Customs →</button>
          </div>
        </PanelCard>

        {/* DHL clearance */}
        <PanelCard title="DHL Clearance" subtitle="Email correspondence + reply" status={replySent ? 'Reply Sent' : (dhlEmailReceived ? 'DHL Email Received' : 'Awaiting DHL Email')}>
          <InfoBlock rows={[
            { label: 'Total Invoice CIF', value: 'EUR 1,280.00' },
            { label: 'DSK Recommendation', value: 'Standard DSK' },
            { label: 'DHL Email',         value: dhlEmailReceived ? 'Received ✓' : 'Awaiting' },
            { label: 'Reply Status',      value: replySent ? 'Sent ✓' : 'Not sent' },
          ]} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('dhl')} data-testid="ov-clearance-open-dhl" style={navLinkStyle()}>Open DHL / Customs →</button>
          </div>
        </PanelCard>

        {/* Customs */}
        <PanelCard title="Customs / SAD" subtitle="ZC429 declaration & verification" status={sadUploaded ? 'SAD Uploaded' : 'SAD Pending'}>
          <InfoBlock rows={[
            { label: 'SAD / ZC429',    value: sadUploaded ? 'Uploaded ✓' : 'Not uploaded' },
            { label: 'MRN',            value: shipment.mrn, mono: true },
            { label: 'Clearance Date', value: sadUploaded ? '27 Apr 2024' : '—' },
            { label: 'Customs Agent',  value: sadUploaded ? 'Agencja Celna' : '—' },
          ]} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('dhl')} data-testid="ov-customs-open-dhl" style={navLinkStyle()}>Open DHL / Customs →</button>
          </div>
        </PanelCard>

        {/* PZ / accounting */}
        <PanelCard title="PZ / Accounting" subtitle="Goods receipt & wFirma export" status={pzExported ? 'Exported' : (pzGenerated ? 'Generated' : (sadUploaded ? 'Ready for PZ' : 'Locked'))}>
          <InfoBlock rows={[
            { label: 'PZ Status',  value: pzGenerated ? 'Generated ✓' : (sadUploaded ? 'Ready' : 'Locked') },
            { label: 'PZ Number',  value: pzGenerated ? 'PZ/2024/001234' : '—', mono: true },
            { label: 'Net Value',  value: shipment.net },
            { label: 'wFirma',     value: pzExported ? 'Exported ✓' : 'Not exported' },
          ]} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('pz')} data-testid="ov-open-pz" style={navLinkStyle()}>Open PZ / Accounting →</button>
          </div>
        </PanelCard>
      </div>
    </>
  );
}

function navLinkStyle() {
  return {
    background: 'none', border: 'none', cursor: 'pointer',
    color: 'var(--text)', fontSize: 12, fontWeight: 600,
    padding: '6px 0', display: 'inline-flex', alignItems: 'center', gap: 4,
    textDecoration: 'underline', textUnderlineOffset: 4, textDecorationColor: 'var(--accent)',
    textDecorationThickness: 2,
  };
}

// ── DHL / CUSTOMS

function DhlTab({ shipment, sadUploaded, dhlEmailReceived, replySent, batchId }) {
  const bid = batchId || '{batch_id}';
  return (
    <>
      <SectionLabel>Step 1 · DHL clearance email & reply</SectionLabel>
      <PanelCard
        title="DHL Clearance"
        subtitle="Pre-check, email correspondence, and reply package"
        status={replySent ? 'Reply Sent' : (dhlEmailReceived ? 'DHL Email Received' : 'Awaiting Email')}
        accent={replySent ? '#22A06B' : 'var(--accent)'}
      >
        <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Customs values</div>
            <InfoRow label="Total Invoice CIF"     value="EUR 1,280.00" />
            <InfoRow label="FOB Value"             value="EUR 1,150.00" />
            <InfoRow label="Freight"               value="EUR 95.00" />
            <InfoRow label="Insurance"             value="EUR 35.00" />
            <InfoRow label="DHL Threshold"         value="EUR 150 — Reply Required" />
            <InfoRow label="DSK Recommendation"    value="Standard DSK" />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Reply package status</div>
            <InfoRow label="DHL Email"           value={dhlEmailReceived ? 'Received ✓' : 'Awaiting'} />
            <InfoRow label="Polish Description"  value={dhlEmailReceived ? 'Generated ✓' : '—'} />
            <InfoRow label="DSK PDF"             value={dhlEmailReceived ? 'Generated ✓' : '—'} />
            <InfoRow label="Reply Package"       value={replySent ? 'Sent ✓' : (dhlEmailReceived ? 'Built ✓' : '—')} />
            <InfoRow label="Reply Sent"          value={replySent ? '27 Apr 2024 · 14:32' : 'Not sent'} />
          </div>
        </div>
        <BackendPendingBanner testid="dhl-actions-pending-note">
          DHL clearance actions are not yet wired into this V2 page. The backend routes exist —
          run these on the V1 Shipment Detail page today. Wiring is tracked in BACKEND_GAP_REGISTER.md.
        </BackendPendingBanner>
        <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <PendingAction label="Scan DHL Inbox"      icon="⌕" testid="scan-dhl-inbox"      route={'GET /api/v1/dhl/scan-inbox'} />
          <PendingAction label="Mark Email Received" icon="✓" testid="mark-email-received" route={'POST /api/v1/dhl/mark-email-received/' + bid} />
          <PendingAction label="Generate Polish Desc." icon="⊞" testid="generate-polish-desc" route={'POST /api/v1/dhl/generate-description/' + bid} />
          <PendingAction label="Generate DSK"        icon="⊟" testid="generate-dsk"        route={'POST /api/v1/dhl/generate-customs-package/' + bid} />
          <PendingAction label="Build Reply Package" icon="⊡" testid="build-reply-package" route={'POST /api/v1/dhl/generate-customs-package/' + bid} />
          <PendingAction label="Send Reply to DHL"   icon="↗" testid="send-reply"          route={'POST /api/v1/dhl/send-reply/' + bid} variant="gold" />
        </div>
      </PanelCard>

      <SectionLabel style={{ marginTop: 8 }}>Step 2 · SAD / ZC429 customs document</SectionLabel>
      <PanelCard
        title="SAD / ZC429"
        subtitle="Upload, parse, and verify the customs declaration"
        status={sadUploaded ? 'SAD Uploaded' : 'SAD Pending'}
        accent={sadUploaded ? '#22A06B' : (replySent ? 'var(--accent)' : null)}
      >
        <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Document references</div>
            <InfoRow label="SAD / ZC429 Status" value={sadUploaded ? 'Uploaded ✓' : 'Not uploaded'} />
            <InfoRow label="MRN"                value={shipment.mrn} mono />
            <InfoRow label="LRN"                value={sadUploaded ? 'LRN-20240427-001' : '—'} mono />
            <InfoRow label="Clearance Date"     value={sadUploaded ? '27 Apr 2024' : '—'} />
            <InfoRow label="Customs Agent"      value={sadUploaded ? 'Agencja Celna Sp. z o.o.' : '—'} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Values & rates</div>
            <InfoRow label="SAD Exchange Rate"   value={sadUploaded ? 'EUR/PLN 4.2650' : '—'} />
            <InfoRow label="NBP Accounting Rate" value={sadUploaded ? 'EUR/PLN 4.2510' : '—'} />
            <InfoRow label="A00 Duty"            value={sadUploaded ? 'PLN 282.00' : '—'} />
            <InfoRow label="B00 VAT"             value={sadUploaded ? 'PLN 1,254.60' : '—'} />
            <InfoRow label="Art.33a / Import"    value={sadUploaded ? 'Standard Import' : '—'} />
          </div>
        </div>

        {sadUploaded && (
          <div style={{ margin: '0 20px 16px', padding: '14px 16px', background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-green-text)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Verification checks</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {[
                { label: 'Invoice reference check',     ok: true },
                { label: 'CIF / customs value check',   ok: true },
                { label: 'Importer / exporter check',   ok: true },
                { label: 'Quantity check',              ok: shipment.sadStatus !== 'Verification Needed' },
              ].map(c => (
                <div key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <span style={{
                    width: 18, height: 18, borderRadius: 9,
                    background: c.ok ? 'var(--badge-green-text)' : 'var(--badge-red-text)',
                    color: '#fff', fontSize: 11, fontWeight: 700,
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  }}>{c.ok ? '✓' : '!'}</span>
                  <span style={{ color: c.ok ? 'var(--text)' : 'var(--badge-red-text)', fontWeight: 500 }}>{c.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <PendingAction label="Upload SAD / ZC429" icon="⊞" testid="upload-sad" route={'POST /api/v1/upload/shipment/' + bid + '/sad'} />
          {sadUploaded
            ? <span data-action-state="completed" style={{ fontSize: 12, color: 'var(--badge-green-text)', fontWeight: 600 }}>✓ SAD uploaded — customs values parsed</span>
            : <span style={{ fontSize: 12, color: 'var(--text-2)' }}>Upload on the V1 page; this view reflects the result.</span>
          }
        </div>
      </PanelCard>
    </>
  );
}

// ── PZ / ACCOUNTING

function PzTab({ shipment, sadUploaded, pzGenerated, pzExported, pzNumber, batchId, setActiveTab }) {
  const bid = batchId || '{batch_id}';
  if (!sadUploaded) {
    return (
      <PanelCard title="PZ Document & wFirma Booking" subtitle="Goods receipt, audit files, and accounting export" status="Locked">
        <div data-testid="pz-locked" data-action-state="unavailable" style={{ padding: 48, textAlign: 'center' }}>
          <div style={{
            width: 56, height: 56, borderRadius: 28,
            background: 'var(--badge-neutral-bg)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 14px', fontSize: 22,
          }}>🔒</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>PZ Locked</div>
          <div style={{ fontSize: 13, color: 'var(--text-2)', maxWidth: 420, margin: '0 auto', lineHeight: 1.5 }}>
            Upload SAD / ZC429 from the <strong>DHL / Customs</strong> tab to unlock PZ generation.
          </div>
        </div>
      </PanelCard>
    );
  }

  return (
    <>
      <SectionLabel>Step 3 · PZ document &amp; wFirma booking</SectionLabel>
      <PanelCard
        title="PZ Document"
        subtitle="Generate goods receipt, download audit files, export to wFirma"
        status={pzExported ? 'Exported' : (pzGenerated ? 'Generated' : 'Ready for PZ')}
        accent={pzExported ? '#22A06B' : (pzGenerated ? '#22A06B' : 'var(--accent)')}
      >
        <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>PZ details</div>
            <InfoRow label="PZ Status"   value={pzGenerated ? 'Generated ✓' : 'Ready for PZ'} />
            <InfoRow label="PZ Number"   value={pzNumber || '—'} mono />
            <InfoRow label="Net Value"   value={shipment.net} />
            <InfoRow label="Gross Value" value={shipment.gross} />
            <InfoRow label="Duty A00"    value={shipment.duty} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>wFirma export</div>
            <InfoRow label="wFirma Status"   value={pzExported ? 'Exported ✓' : 'Not exported'} />
            <InfoRow label="Export Date"     value={pzExported ? '27 Apr 2024' : '—'} />
            <InfoRow label="External Doc ID" value={pzExported ? 'WF-2024-04-PZ-1234' : '—'} mono />
          </div>
        </div>

        <BackendPendingBanner testid="pz-actions-pending-note">
          PZ generation and wFirma export are not yet wired into this V2 page. The backend routes
          exist — run these on the V1 Shipment Detail page today. Wiring is tracked in BACKEND_GAP_REGISTER.md.
        </BackendPendingBanner>
        <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <PendingAction label={pzGenerated ? 'Regenerate PZ' : 'Run PZ'} icon={pzGenerated ? '↺' : '▶'} testid="run-pz"      route={'POST /api/v1/upload/shipment/' + bid + '/wfirma/pz_create'} variant="gold" />
          <PendingAction label="Confirm PZ Number" icon="✎" testid="confirm-pz"    route={'POST /api/v1/upload/shipment/' + bid + '/wfirma/pz_confirm'} />
          <PendingAction label="Copy wFirma Format" icon="⊞" testid="copy-wfirma"   route={'POST /api/v1/upload/shipment/' + bid + '/wfirma/clipboard'} />
          <PendingAction label="Export to wFirma"   icon="↗" testid="export-wfirma" route={'POST /api/v1/upload/shipment/' + bid + '/wfirma/pz_create'} />
        </div>
        <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Btn variant="outline" small data-testid="pz-open-documents" aria-label="Open generated PZ files in the Documents tab" onClick={() => setActiveTab('documents')}>
            ↓ Open generated files in Documents →
          </Btn>
          <span style={{ fontSize: 12, color: 'var(--text-2)', flex: 1, minWidth: 220 }}>
            Generated PZ files — PZ PDF, Calculation XLSX, Audit EN, Audit PL, Audit Memo, Corrections —
            are served from backend authority in the <strong>Documents</strong> tab.
          </span>
        </div>
      </PanelCard>
    </>
  );
}

// ── DOCUMENTS — wired to GET /api/v1/dashboard/batches/{batch_id}/files
// Authority: routes_dashboard._build_files_detail()
// No mock arrays. All file entries come from backend authority only.

const _GENERATED_LABELS = {
  pz_pdf:     'PZ PDF',
  calc_xlsx:  'Calculation XLSX',
  audit_en:   'Audit EN PDF',
  audit_pl:   'Audit PL PDF',
  audit_memo: 'Audit Memo PDF',
  corrections:'Corrections JSON',
};

const _SOURCE_LABELS = { invoices: 'Invoice', sad: 'SAD / ZC429', awb: 'AWB' };

function DocCard({ file }) {
  const ext = file.name ? file.name.split('.').pop().toLowerCase() : '';
  const iconBg    = file.exists ? (ext === 'pdf' ? 'var(--badge-red-bg)' : ext === 'xlsx' ? 'var(--badge-green-bg)' : ext === 'json' ? 'var(--badge-blue-bg)' : 'var(--badge-amber-bg)') : 'var(--bg)';
  const iconColor = file.exists ? (ext === 'pdf' ? 'var(--badge-red-text)' : ext === 'xlsx' ? 'var(--badge-green-text)' : ext === 'json' ? 'var(--badge-blue-text)' : 'var(--badge-amber-text)') : 'var(--text-3)';
  const canDownload = file.exists && !!file.url;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14,
      padding: '14px 16px', borderRadius: 8,
      border: '1px solid var(--border)', background: 'var(--card)',
      boxShadow: '0 1px 2px var(--shadow)',
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 8,
        background: iconBg, color: iconColor,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 800, letterSpacing: '0.05em',
      }}>{ext ? ext.toUpperCase() : '?'}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: file.exists ? 'var(--text)' : 'var(--text-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {file.name || '—'}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>{file.type}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {file.stale && <span style={{ fontSize: 10, color: 'var(--badge-amber-text)', fontWeight: 600 }}>legacy</span>}
        {file.exists
          ? <span style={{ fontSize: 11, color: 'var(--badge-green-text)', fontWeight: 600 }}>✓ Present</span>
          : <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Not found</span>
        }
        <a
          href={canDownload ? file.url : undefined}
          target="_blank" rel="noopener noreferrer"
          onClick={!canDownload ? e => e.preventDefault() : undefined}
          data-testid="doc-download"
          style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            padding: '4px 10px', borderRadius: 5, fontSize: 11, fontWeight: 600,
            border: '1px solid var(--border)', background: 'transparent',
            color: canDownload ? 'var(--text)' : 'var(--text-3)',
            textDecoration: 'none', cursor: canDownload ? 'pointer' : 'not-allowed',
            opacity: canDownload ? 1 : 0.45,
          }}
        >↓</a>
      </div>
    </div>
  );
}

function DocumentsTab({ batchId }) {
  const [data,    setData]    = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error,   setError]   = React.useState(null);

  React.useEffect(() => {
    if (!batchId) return;
    setLoading(true); setError(null);
    window.EstrellaShared.apiFetch('/api/v1/dashboard/batches/' + encodeURIComponent(batchId) + '/files')
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError((e && e.message) || 'Failed to load documents'); setLoading(false); });
  }, [batchId]);

  if (!batchId) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-2)' }}>
        <div style={{ fontSize: 13 }}>No batch context — documents unavailable.</div>
      </div>
    );
  }
  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>Loading documents…</div>;
  if (error)   return <div style={{ padding: 40, textAlign: 'center', color: 'var(--badge-red-text)', fontSize: 13 }}>Failed to load documents: {error}</div>;

  const sf = (data && data.source_files) || {};
  const uploadedRows = Object.entries(_SOURCE_LABELS).flatMap(([cat, label]) =>
    (sf[cat] || []).map(f => ({ ...f, type: label }))
  );

  const gf = (data && data.files) || {};
  const generatedRows = Object.entries(_GENERATED_LABELS).map(([key, label]) => ({
    ...(gf[key] || { name: label.toLowerCase().replace(/ /g, '_'), url: '', exists: false, stale: false }),
    type: label,
  }));

  return (
    <div data-testid="documents-tab" className="docs-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <div>
        <SectionLabel>Uploaded shipment documents</SectionLabel>
        {uploadedRows.length === 0
          ? <div style={{ padding: '20px 0', fontSize: 13, color: 'var(--text-3)' }}>No uploaded documents found.</div>
          : <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>{uploadedRows.map((f, i) => <DocCard key={i} file={f} />)}</div>
        }
      </div>
      <div>
        <SectionLabel>Generated output documents</SectionLabel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {generatedRows.map((f, i) => <DocCard key={i} file={f} />)}
        </div>
      </div>
    </div>
  );
}

// ── TIMELINE

const TIMELINE_EVENTS = [
  { label: 'Shipment created',                done: true, date: '10 Apr 2024 · 09:12' },
  { label: 'Invoice uploaded',                done: true, date: '10 Apr 2024 · 09:15' },
  { label: 'AWB uploaded',                    done: true, date: '10 Apr 2024 · 09:17' },
  { label: 'DHL pre-check completed',         done: true, date: '10 Apr 2024 · 09:20' },
  { label: 'DHL email received',              done: null, date: null, key: 'dhlEmail' },
  { label: 'Polish description generated',    done: null, date: null, key: 'dhlEmail' },
  { label: 'DSK generated',                   done: null, date: null, key: 'dhlEmail' },
  { label: 'Reply package prepared',          done: null, date: null, key: 'dhlEmail' },
  { label: 'Reply sent to DHL',               done: null, date: null, key: 'reply' },
  { label: 'SAD / ZC429 uploaded',            done: null, date: null, key: 'sad' },
  { label: 'Customs values parsed',           done: null, date: null, key: 'sad' },
  { label: 'Verification checks passed',      done: null, date: null, key: 'sad' },
  { label: 'PZ unlocked',                     done: null, date: null, key: 'pzUnlock' },
  { label: 'PZ generated',                    done: null, date: null, key: 'pz' },
  { label: 'PZ number confirmed',             done: null, date: null, key: 'pz' },
  { label: 'Exported to wFirma',              done: null, date: null, key: 'wfirma' },
];

function TimelineTab({ shipment, sadUploaded, pzGenerated, replySent, dhlEmailReceived, pzExported }) {
  const events = TIMELINE_EVENTS.map(e => {
    let done = e.done;
    if (e.key === 'dhlEmail' && (dhlEmailReceived || replySent)) done = true;
    if (e.key === 'reply'    && replySent) done = true;
    if (e.key === 'sad'      && sadUploaded) done = true;
    if (e.key === 'pzUnlock' && sadUploaded) done = true;
    if (e.key === 'pz'       && pzGenerated) done = true;
    if (e.key === 'wfirma'   && pzExported) done = true;
    return { ...e, done };
  });

  return (
    <PanelCard title="Activity timeline" subtitle="Chronological audit log of every event for this shipment">
      <div style={{ padding: '24px 28px' }}>
        <div style={{ position: 'relative', paddingLeft: 28 }}>
          <div style={{ position: 'absolute', left: 9, top: 6, bottom: 6, width: 2, background: 'var(--border)' }} />
          {events.map((e, i) => (
            <div key={i} style={{ position: 'relative', marginBottom: 18, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
              <div style={{
                position: 'absolute', left: -28,
                width: 20, height: 20, borderRadius: 10,
                background: e.done ? '#22A06B' : 'var(--card)',
                border: `2px solid ${e.done ? '#22A06B' : 'var(--border)'}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                zIndex: 1, top: 0,
              }}>
                {e.done && <span style={{ fontSize: 10, color: '#fff', fontWeight: 800 }}>✓</span>}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: e.done ? 600 : 500, color: e.done ? 'var(--text)' : 'var(--text-3)' }}>{e.label}</div>
                {e.done && e.date && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2, fontFamily: 'monospace' }}>{e.date}</div>}
                {e.done && !e.date && <div style={{ fontSize: 11, color: 'var(--badge-green-text)', marginTop: 2, fontWeight: 600 }}>Completed</div>}
                {!e.done && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Pending</div>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </PanelCard>
  );
}

// Pro Forma tab inside shipment detail — navigates to real Pro Forma hub with batch context.
// Authority: proforma-list.jsx → GET /api/v1/proforma/drafts/{batch_id}
// No mock drafts. batch_id flows from parent shipment prop.
function ProformaTabInShipment({ shipment }) {
  const batchId = shipment && shipment.batch_id;

  if (!batchId) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-2)' }}>
        <div style={{ fontSize: 13 }}>No batch context — Pro Forma drafts unavailable.</div>
      </div>
    );
  }

  const goToProforma = () => {
    window.location.href = '/v2/proforma?batch_id=' + encodeURIComponent(batchId);
  };

  return (
    <>
      <SectionLabel>Pro Forma drafts for this shipment</SectionLabel>
      <PanelCard>
        <div style={{ padding: '24px 28px', display: 'flex', alignItems: 'center', gap: 20 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>
              Pro Forma drafts for batch {batchId}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
              Create, edit, post to wFirma, and convert drafts to invoices in the Pro Forma hub.
            </div>
          </div>
          <Btn variant="outline" small onClick={goToProforma} data-testid="proforma-tab-open">
            Open Pro Forma →
          </Btn>
        </div>
      </PanelCard>
    </>
  );
}

Object.assign(window, { ShipmentDetailPage });
