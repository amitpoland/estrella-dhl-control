// Shipment Detail Page — light-theme redesign with clean tabbed structure
// Tabs: Overview · DHL / Customs · PZ / Accounting · Documents · Timeline
//
// Wave-3 gap-closure 2026-07-04 (SD-1 · SD-2 · SD-4 · SD-5 · SD-6 · SD-7):
//   SD-1  Header card: MRN mono + Carrier chip + packing list mono added to sub-header.
//   SD-2  Overview tab: stage-conditional contextual action tiles wired to domain tabs.
//   SD-4  DHL tab: prominent "Open DHL Console" nav per R-Q1 + inline status summary stays.
//   SD-5  PZ tab: Download XLSX · Download PDF · Mark Exported + separate Regenerate PZ added.
//   SD-6  Documents tab: 4-card wireframe layout (PL · PF · CMR · WF) plus generated files.
//   SD-7  Timeline tab: full 16-event label map + pending-milestone display.
//   SD-3  Pro Forma tab: was already closed by ProformaTabInShipment — no changes needed.

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

// ── Authority-honest value derivation ────────────────────────────────────────
// Every displayed value below comes from GET /api/v1/dashboard/batches/{batch_id}
// (returns the full audit object — same authority the V1 page reads). Any field the
// authority does not carry renders as '—'. Nothing on this page is invented.
function _dash(v) { return (v === null || v === undefined || v === '') ? '—' : v; }
function _fmtUsd(n) {
  // Route through the single V2 money authority (components.jsx fmtMoney2).
  if (window.fmtMoney2) return window.fmtMoney2(n, { currency: 'USD' });
  if (n == null || n === '') return '—';
  const x = Number(n); if (isNaN(x)) return '—';
  return 'USD ' + x.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function _fmtPln(n) {
  // Route through the single V2 money authority (components.jsx fmtMoney2).
  // Note: the old window.EstrellaShared.fmtPLN dependency was dead in V2
  // (dashboard-shared.js is intentionally not loaded) — this is the fix.
  if (window.fmtMoney2) return window.fmtMoney2(n, { currency: 'PLN', locale: 'pl-PL' });
  if (n == null || n === '') return '—';
  const x = Number(n); return isNaN(x) ? '—' : 'PLN ' + x.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function _fmtRate(n) { if (n == null || n === '') return '—'; const x = Number(n); return isNaN(x) ? '—' : x.toFixed(4); }
function _fmtDate(iso, withTime) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  let s = d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  if (withTime && /[T ]\d\d:/.test(String(iso))) {
    s += ' · ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }
  return s;
}

// ── Shipment prop normalizer ─────────────────────────────────────────────────
// Both callers (DashboardPage list row + DashboardKanban `_raw`) hand this page the
// RAW snake_case batch row from GET /api/v1/dashboard/batches, but the page was built
// for the camelCase shape produced by dashboard-kanban.jsx `_transformBatch`. Without
// this, shipment.awb / sadStatus / pzStatus / dhlStatus / overall are all `undefined`
// (the cause of the blank AWB + fake-importer + wrong workflow strip operators saw).
// Mirror _transformBatch's status mappers here so the page reads correct status strings.
function _mapOverallStatus(status) {
  const m = {
    success: 'Ready for Booking', partial: 'Ready for Booking',
    blocked: 'Action Required', failed: 'Action Required',
    awaiting_dhl_email: 'Awaiting DHL', awaiting_sad: 'Awaiting SAD',
    awaiting_clearance: 'Awaiting Clearance', in_preparation: 'In Preparation',
    draft: 'Draft', ready: 'Ready for PZ', processing: 'In Preparation', collecting: 'In Preparation',
  };
  return m[status] || (status ? status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Pending');
}
function _mapDhl(s) {
  if (!s) return '—';
  const m = {
    awaiting_dhl_email: 'Awaiting DHL Email', dhl_email_received: 'DHL Email Received',
    reply_sent: 'Reply Sent', reply_queued: 'Reply Queued', pre_check_completed: 'Pre-check Completed',
    pre_check_pending: 'Pre-check Pending', reply_package_prepared: 'Reply Package Prepared',
  };
  return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
function _mapSad(s) {
  if (!s) return 'SAD Pending';
  const m = {
    sad_pending: 'SAD Pending', sad_uploaded: 'SAD Uploaded', customs_parsed: 'Customs Parsed',
    customs_verified: 'Customs Verified', verification_needed: 'Verification Needed',
    missing: 'SAD Pending', uploaded: 'SAD Uploaded', uploaded_parsed: 'Customs Parsed',
  };
  return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
function _mapPz(s) {
  if (!s) return 'Locked';
  const m = { locked: 'Locked', ready: 'Ready for PZ', generated: 'Generated', exported: 'Exported', complete: 'Exported' };
  return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
function _normalizeShipment(s) {
  s = s || {};
  // Already in camelCase (transformed) shape → pass through unchanged.
  if (s.sadStatus || s.pzStatus || s.dhlStatus) return s;
  return Object.assign({}, s, {
    batch_id:        s.batch_id,
    awb:             s.awb || s.tracking_no || s.doc_no || s.batch_id || null,
    carrier:         s.carrier || null,
    mrn:             s.mrn || null,
    tracking_status: s.tracking_status || null,
    tracking_url:    s.tracking_url || null,
    client:          s.client || null,
    overall:         s.overall || _mapOverallStatus(s.status),
    dhlStatus:       _mapDhl(s.dhl_status),
    sadStatus:       _mapSad(s.sad_status),
    pzStatus:        _mapPz(s.pz_status),
  });
}

// Flatten the raw audit object → display fields. null wherever the authority is silent.
function deriveDetail(audit, shipment) {
  audit = audit || {};
  shipment = shipment || {};
  const cd  = audit.customs_declaration || {};
  const pc  = audit.dhl_precheck || {};
  const wf  = audit.wfirma_export || {};
  const inp = audit.inputs || {};
  const tot = audit.totals || {};
  const ver = audit.verification || {};

  const invoiceCount = Array.isArray(inp.invoices) ? inp.invoices.length
                     : Array.isArray(inp.invoice_refs) ? inp.invoice_refs.length : null;

  // Customs verification checks — only those with a real backing signal are shown.
  const checks = [];
  if (cd.values_match != null) checks.push({ label: 'CIF values match (invoice vs SAD)', ok: cd.values_match === true });
  if (ver.cif_match  != null)  checks.push({ label: 'CIF verified against declaration',   ok: ver.cif_match === true });
  if (cd.cif_alert   != null)  checks.push({ label: 'No CIF discrepancy alert',            ok: cd.cif_alert === false });
  if (cd.rate_alert  != null)  checks.push({ label: 'Exchange rate within tolerance',      ok: cd.rate_alert === false });

  return {
    loaded:   !!audit.batch_id,
    // SAD verification authority (read-only backend truth). Never infer success
    // from a SAD file merely existing — surface the decision engine's verdict.
    sadDecision:          audit.agency_sad_decision || null,
    sadInvoiceAuthority:  audit.sad_invoice_authority || null,
    sadPresent:           !!(cd.mrn || (audit.inputs || {}).zc429 || audit.zc429),
    importer: cd.importer_name || shipment.client || null,
    exporter: cd.exporter_name || null,
    lineCount:    tot.line_count != null ? tot.line_count : null,
    invoiceCount,
    awbUploaded:  !!inp.awb,
    trackingStatus: shipment.tracking_status || null,
    // CIF authority (values are USD — invoice currency, NOT EUR)
    cifUsd:       pc.invoice_cif_total_usd != null ? pc.invoice_cif_total_usd : (cd.invoice_cif_usd != null ? cd.invoice_cif_usd : null),
    thresholdUsd: pc.threshold_usd != null ? pc.threshold_usd : null,
    cifSource:    pc.cif_source || null,
    clearanceHint: pc.clearance_hint || null,
    dskRequiredHint: pc.dsk_required_hint === true,
    invoicesParsed: pc.invoices_parsed != null ? pc.invoices_parsed : null,
    // Customs / SAD authority
    mrn:          cd.mrn || shipment.mrn || null,
    lrn:          cd.lrn || null,
    clearanceDate: cd.clearance_date || null,
    customsAgent:  cd.customs_agent || null,
    sadRate:      cd.sad_customs_rate != null ? cd.sad_customs_rate : null,
    nbpRate:      cd.nbp_rate != null ? cd.nbp_rate : null,
    nbpTable:     cd.nbp_table || null,
    dutyA00Pln:   cd.duty_a00_pln != null ? cd.duty_a00_pln : null,
    vatB00Pln:    cd.vat_b00_pln != null ? cd.vat_b00_pln : null,
    vatModeLabel: cd.vat_mode_label_en || null,
    cnCode:       cd.cn_code || null,
    goodsDescription: cd.goods_description || null,
    checks,
    // PZ / wFirma authority
    pzNumber:     wf.wfirma_pz_fullnumber || null,
    pzDocId:      wf.wfirma_pz_doc_id || null,
    pzExportDate: wf.pz_created_at || wf.pz_adopted_at || wf.last_generated_at || null,
    wfirmaMode:   wf.mode || null,
    pzFileGenerated: !!(audit.pz_output && (audit.pz_output.pdf || audit.pz_output.xlsx)),
    // Document generation + pre-check — real signals from the audit, not status proxies
    precheckDone:        !!pc.completed_at,
    // Prefer the endpoint's authoritative on-disk existence flag; only fall back to a
    // stored filename pointer when the flag is absent (never show "Generated" for a
    // file the endpoint reports missing).
    polishDescGenerated: audit.polish_desc_file_exists != null ? audit.polish_desc_file_exists === true : !!audit.polish_desc_filename,
    dskGenerated:        audit.dsk_file_exists != null ? audit.dsk_file_exists === true : !!audit.dsk_filename,
    replyPackageBuilt:   !!(audit.dhl_reply_package || audit.agency_reply_package),
    // Totals (PLN) — audit totals are authoritative; fall back to the list row
    netPln:   tot.net   != null ? tot.net   : (shipment.net   != null ? shipment.net   : null),
    grossPln: tot.gross != null ? tot.gross : (shipment.gross != null ? shipment.gross : null),
    dutyPln:  tot.duty  != null ? tot.duty  : (shipment.duty  != null ? shipment.duty  : null),
    // Packing list reference — source file name if present (SD-1 header mono field)
    packingList: (inp.packing_list_filename || inp.packing_list || null),
    // Real activity log
    timeline: Array.isArray(audit.timeline) ? audit.timeline : [],
  };
}

function ShipmentDetailPage({ shipment, onBack }) {
  // Callers pass the raw snake_case batch row — normalize to the camelCase shape
  // this page reads (awb/sadStatus/pzStatus/dhlStatus/overall). Idempotent.
  shipment = _normalizeShipment(shipment);
  const [activeTab, setActiveTab] = React.useState('overview');

  // Live shipment detail — fetched from the full-audit authority endpoint.
  const [detail,        setDetail]        = React.useState(null);
  const [detailLoading, setDetailLoading] = React.useState(false);
  const [detailError,   setDetailError]   = React.useState(null);
  const batchId = shipment && shipment.batch_id;
  const [reloadNonce, setReloadNonce] = React.useState(0);
  const reloadDetail = React.useCallback(() => setReloadNonce(n => n + 1), []);

  React.useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    setDetailLoading(true); setDetailError(null);
    window.EstrellaShared.apiFetch('/api/v1/dashboard/batches/' + encodeURIComponent(batchId))
      .then(a => { if (!cancelled) { setDetail(a); setDetailLoading(false); } })
      .catch(e => { if (!cancelled) { setDetailError((e && e.message) || 'Failed to load shipment detail'); setDetailLoading(false); } });
    return () => { cancelled = true; };
  }, [batchId, reloadNonce]);

  const d = React.useMemo(() => deriveDetail(detail, shipment), [detail, shipment]);

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
    if (id === 'precheck') return d.precheckDone ? 'done' : 'active';
    if (id === 'reply')    return replySent ? 'done' : (d.precheckDone ? 'active' : 'pending');
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
        {shipment.carrier && (
          <>
            <div style={{ width: 1, height: 32, background: 'var(--border)' }} />
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>Carrier</div>
              <Badge status={shipment.carrier} small />
            </div>
          </>
        )}
        <div style={{ width: 1, height: 32, background: 'var(--border)' }} />
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>Importer</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{_dash(d.importer)}</div>
        </div>
        {d.mrn && (
          <>
            <div style={{ width: 1, height: 32, background: 'var(--border)' }} />
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>MRN</div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', fontFamily: 'monospace' }} data-testid="header-mrn">{d.mrn}</div>
            </div>
          </>
        )}
        {d.packingList && (
          <>
            <div style={{ width: 1, height: 32, background: 'var(--border)' }} />
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>Packing List</div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', fontFamily: 'monospace' }} data-testid="header-packing-list">{d.packingList}</div>
            </div>
          </>
        )}
        <div style={{ width: 1, height: 32, background: 'var(--border)' }} />
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>Lines</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{_dash(d.lineCount)}</div>
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

        {detailError && (
          <div data-testid="detail-load-error" role="alert" style={{
            padding: '12px 16px', borderRadius: 8, fontSize: 12, lineHeight: 1.5,
            background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', color: 'var(--badge-amber-text)',
          }}>
            ⚠ Could not load full shipment detail ({detailError}). Showing summary values only; some fields below may read “—”.
          </div>
        )}

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
          <OverviewTab d={d} shipment={shipment} sadUploaded={sadUploaded} pzGenerated={pzGenerated} pzExported={pzExported} replySent={replySent} dhlEmailReceived={dhlEmailReceived} setActiveTab={setActiveTab} />
        )}
        {activeTab === 'proforma' && (
          <ProformaTabInShipment shipment={shipment} />
        )}
        {activeTab === 'dhl' && (
          <DhlTab
            d={d} shipment={shipment} sadUploaded={sadUploaded}
            dhlEmailReceived={dhlEmailReceived} replySent={replySent}
            batchId={shipment && shipment.batch_id}
            onReload={reloadDetail}
          />
        )}
        {activeTab === 'pz' && (
          <PzTab
            d={d} shipment={shipment} sadUploaded={sadUploaded}
            pzGenerated={pzGenerated} pzExported={pzExported} pzNumber={pzNumber}
            batchId={shipment && shipment.batch_id}
            setActiveTab={setActiveTab}
          />
        )}
        {activeTab === 'documents' && (
          <DocumentsTab batchId={shipment && shipment.batch_id} />
        )}
        {activeTab === 'timeline' && (
          <TimelineTab d={d} detailLoading={detailLoading} />
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

function OverviewTab({ d, shipment, sadUploaded, pzGenerated, pzExported, replySent, dhlEmailReceived, setActiveTab }) {
  const wfirmaLabel = d.pzDocId ? 'Booked ✓' : (d.wfirmaMode === 'clipboard' ? 'Clipboard generated' : (pzExported ? 'Exported ✓' : 'Not exported'));

  // SD-2: Stage-conditional contextual action — one tile per incomplete milestone.
  // Navigation only (tab switch); write actions live on domain pages per Lesson M.
  const contextActions = [];
  if (!dhlEmailReceived) contextActions.push({ label: 'Scan DHL inbox for clearance email', tab: 'dhl', cta: 'Go to DHL / Customs' });
  else if (!replySent)   contextActions.push({ label: 'Build and send DHL reply package',    tab: 'dhl', cta: 'Go to DHL / Customs' });
  if (!sadUploaded)      contextActions.push({ label: 'Upload SAD / ZC429 customs document', tab: 'dhl', cta: 'Go to DHL / Customs' });
  if (sadUploaded && !pzGenerated) contextActions.push({ label: 'Generate PZ document',      tab: 'pz',  cta: 'Go to PZ / Accounting' });
  if (pzGenerated && !pzExported)  contextActions.push({ label: 'Export PZ to wFirma',       tab: 'pz',  cta: 'Go to PZ / Accounting' });

  return (
    <>
      {contextActions.length > 0 && (
        <>
          <SectionLabel>Next actions</SectionLabel>
          <div data-testid="overview-context-actions" style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 8 }}>
            {contextActions.map((a, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
                padding: '12px 20px', borderRadius: 8,
                background: i === 0 ? 'linear-gradient(135deg, #FBF5E4, #F8EDD0)' : 'var(--bg-subtle)',
                border: `1px solid ${i === 0 ? 'var(--accent-border)' : 'var(--border)'}`,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 16, fontWeight: 800, color: i === 0 ? 'var(--accent)' : 'var(--text-3)', flexShrink: 0 }}>
                    {i === 0 ? '▶' : '○'}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: i === 0 ? 600 : 500, color: i === 0 ? 'var(--text)' : 'var(--text-2)' }}>
                    {a.label}
                  </span>
                </div>
                <button
                  data-testid={`overview-action-cta-${i}`}
                  onClick={() => setActiveTab(a.tab)}
                  style={{
                    padding: '6px 14px', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 600,
                    background: i === 0 ? 'var(--text)' : 'transparent',
                    color: i === 0 ? 'var(--card)' : 'var(--text-2)',
                    border: i === 0 ? 'none' : '1px solid var(--border)',
                    flexShrink: 0,
                  }}
                >{a.cta} →</button>
              </div>
            ))}
          </div>
        </>
      )}
      <SectionLabel>Key figures</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
        <StatTile label="Lines"         value={_dash(d.lineCount)} />
        <StatTile label="Total CIF"     value={_fmtUsd(d.cifUsd)} />
        <StatTile label="Net (PLN)"     value={_fmtPln(d.netPln)} />
        <StatTile label="Duty A00"      value={_fmtPln(d.dutyPln)} />
      </div>

      <SectionLabel style={{ marginTop: 8 }}>Workflow areas</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Shipment intake diagnostics — authority: batch_detail via IntakeDiagnosticsCard */}
        <PanelCard title="Shipment intake" subtitle="Lifecycle, artifacts &amp; blocking reason" status={shipment.carrier || 'Intake'}>
          <IntakeDiagnosticsCard batchId={shipment.batch_id} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('dhl')} data-testid="ov-shipment-open-dhl" style={navLinkStyle()}>Open DHL / Customs →</button>
          </div>
        </PanelCard>

        {/* DHL clearance */}
        <PanelCard title="DHL Clearance" subtitle="Email correspondence + reply" status={replySent ? 'Reply Sent' : (dhlEmailReceived ? 'DHL Email Received' : 'Awaiting DHL Email')}>
          <InfoBlock rows={[
            { label: 'Total Invoice CIF', value: _fmtUsd(d.cifUsd) },
            { label: 'DSK Recommendation', value: _dash(d.clearanceHint) },
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
            { label: 'MRN',            value: _dash(d.mrn), mono: true },
            { label: 'Clearance Date', value: _fmtDate(d.clearanceDate) },
            { label: 'Customs Agent',  value: _dash(d.customsAgent) },
          ]} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('dhl')} data-testid="ov-customs-open-dhl" style={navLinkStyle()}>Open DHL / Customs →</button>
          </div>
        </PanelCard>

        {/* PZ / accounting */}
        <PanelCard title="PZ / Accounting" subtitle="Goods receipt & wFirma export" status={pzExported ? 'Exported' : (pzGenerated ? 'Generated' : (sadUploaded ? 'Ready for PZ' : 'Locked'))}>
          <InfoBlock rows={[
            { label: 'PZ Status',  value: pzGenerated ? 'Generated ✓' : (sadUploaded ? 'Ready' : 'Locked') },
            { label: 'PZ Number',  value: _dash(d.pzNumber), mono: true },
            { label: 'Net Value',  value: _fmtPln(d.netPln) },
            { label: 'wFirma',     value: wfirmaLabel },
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

// ── INTAKE DIAGNOSTICS

// Intake diagnostics panel — renders lifecycle stage, artifact checklist, blocking reason,
// and operator action CTA from batch_detail authority.
// Authority: GET /api/v1/dashboard/batches/{batch_id} (routes_dashboard.py:batch_detail).
// Read-only — display-only; no local readiness computation per Lesson F rule 5.
// Stale-mount guard via cancelled flag (same pattern as DhlReadinessCard).
// 404 response → batch still in working state; shows honest "intake in progress" message.
function IntakeDiagnosticsCard({ batchId }) {
  const [detail, setDetail]           = React.useState(null);
  const [loading, setLoading]         = React.useState(true);
  const [isProcessing, setIsProcessing] = React.useState(false);
  const [errType, setErrType]         = React.useState(null);

  React.useEffect(() => {
    if (!batchId) { setLoading(false); return; }
    let cancelled = false;
    window.PzApi.getBatchDetail(batchId)
      .then(r => {
        if (cancelled) return;
        if (!r.ok && r.status === 404) {
          setIsProcessing(true);
        } else if (r.ok && r.data) {
          setDetail(r.data);
        } else {
          setErrType(r.type === 'auth' ? 'auth' : 'error');
        }
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) { setErrType('error'); setLoading(false); }
      });
    return () => { cancelled = true; };
  }, [batchId]);

  if (!batchId) {
    return (
      <div style={{ padding: '12px 20px', color: 'var(--text-2)', fontSize: 12 }}>
        No batch context — intake diagnostics unavailable.
      </div>
    );
  }
  if (loading) {
    return (
      <div style={{ padding: '12px 20px', color: 'var(--text-2)', fontSize: 12 }}>
        Loading intake diagnostics…
      </div>
    );
  }
  if (isProcessing) {
    return (
      <div data-testid="intake-processing-state" style={{ padding: '12px 20px', color: 'var(--text-2)', fontSize: 12 }}>
        Intake in progress — diagnostics available after batch is finalised.
      </div>
    );
  }
  if (!detail) {
    const msg = errType === 'auth'
      ? 'Session expired — please refresh the page.'
      : 'Cannot load intake diagnostics. Check V1 Shipment Detail for current status.';
    return (
      <div data-testid="intake-diagnostics-error" style={{ padding: '12px 20px', color: 'var(--badge-red-text)', fontSize: 12 }}>
        {msg}
      </div>
    );
  }

  const src        = (detail.files_detail && detail.files_detail.source_files) || {};
  const invoices   = src.invoices || [];
  const awbFiles   = src.awb     || [];
  const sadFiles   = src.sad     || [];
  const salesHint  = detail.sales_status_hint;
  const hasSales   = salesHint === 'present';
  const salesUnknown = salesHint === 'n/a' || salesHint == null;

  const artifacts = [
    { label: 'Invoices',      present: invoices.length > 0, count: invoices.length, unknown: false },
    { label: 'AWB PDF',       present: awbFiles.length > 0,  count: awbFiles.length, unknown: false },
    { label: 'Sales packing', present: hasSales,             count: null,            unknown: salesUnknown },
    { label: 'SAD / ZC429',   present: sadFiles.length > 0,   count: sadFiles.length, unknown: false },
  ];

  const actionReason  = detail.action_reason;
  const failedChecks  = detail.failed_checks || [];
  const clearanceSt   = detail.clearance_status || '';
  const overallSt     = detail.status || '';
  const stageDisplay  = clearanceSt || overallSt || 'unknown';

  const missing = artifacts.filter(a => !a.present && !a.unknown);

  return (
    <div data-testid="intake-diagnostics-card" style={{ padding: '12px 20px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>

      {/* Lifecycle stage — verbatim from backend; labelled authority to satisfy Lesson F rule 5 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: 'var(--text-2)', flexShrink: 0 }}>Lifecycle stage</span>
        <code data-testid="intake-clearance-status" style={{ fontSize: 12, padding: '2px 7px', background: 'var(--bg-2)', borderRadius: 4, color: 'var(--text-1)' }}>
          {stageDisplay}
        </code>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
          Source: <code style={{ fontSize: 11 }}>batch_detail · clearance_status</code>
        </span>
      </div>

      {/* Artifact checklist */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
          Intake Artifacts
        </div>
        <div data-testid="intake-artifact-checklist" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {artifacts.map(a => {
            const color = a.unknown
              ? 'var(--text-3)'
              : a.present
                ? 'var(--badge-green-text)'
                : 'var(--badge-red-text)';
            const icon = a.unknown ? '?' : a.present ? '✓' : '✗';
            return (
              <div key={a.label} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 13 }}>
                <span aria-hidden="true" style={{ color, fontWeight: 700, width: 14, flexShrink: 0 }}>{icon}</span>
                <span style={{ color: a.unknown ? 'var(--text-3)' : 'var(--text-1)' }}>
                  {a.label}
                  {a.count != null && a.present ? ` (${a.count})` : ''}
                  {a.unknown ? ' — status unavailable' : ''}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Blocking reason — shown only when backend reports a reason or failed checks */}
      {(actionReason || failedChecks.length > 0) && (
        <div data-testid="intake-blocking-reason" style={{
          padding: '8px 10px',
          background: 'var(--badge-red-bg)',
          border: '1px solid var(--badge-red-border)',
          borderRadius: 6,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-red-text)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>
            Blocking reason
          </div>
          {actionReason && (
            <div style={{ fontSize: 13, color: 'var(--text-1)', marginBottom: failedChecks.length > 0 ? 6 : 0 }}>
              {actionReason}
            </div>
          )}
          {failedChecks.length > 0 && (
            <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: 'var(--text-2)' }}>
              {failedChecks.map((c, i) => <li key={i}>{c}</li>)}
            </ol>
          )}
        </div>
      )}

      {/* Operator action CTA — upload missing artifacts */}
      {missing.length > 0 && (
        <div data-testid="intake-operator-action" style={{
          fontSize: 13, color: 'var(--text-2)', padding: '6px 10px',
          background: 'var(--bg-2)', borderRadius: 4,
        }}>
          <span style={{ fontWeight: 600 }}>Action required: </span>
          Upload missing — {missing.map(a => a.label).join(', ')}
        </div>
      )}
    </div>
  );
}

// ── DHL / CUSTOMS

// 7-state DHL pipeline labels — matches V1 shipment-detail.html:8631-8637 and dhl_readiness.py:31-39.
const DHL_PIPELINE_STATES = [
  { key: 'awaiting_start',   label: 'Awaiting Start' },
  { key: 'dhl_contacted',    label: 'DHL Contacted' },
  { key: 'dhl_replied',      label: 'DHL Replied' },
  { key: 'dsk_received',     label: 'DSK / Cesja Rcvd' },
  { key: 'agency_forwarded', label: 'Agency Forwarded' },
  { key: 'sad_received',     label: 'SAD Received' },
  { key: 'customs_cleared',  label: 'Customs Cleared' },
];

// DHL customs pipeline diagnostics panel.
// Authority: GET /api/v1/dhl/readiness/{batch_id} (dhl_readiness.py:get_dhl_readiness).
// Read-only — no write-on-read side effects; no mountDelayMs stagger needed.
// Re-fetches on each tab activation (intentional: operator sees fresh pipeline state on return).
// Stale-mount guard via cancelled flag prevents setState after unmount.
// NOTE: the 7-state pipeline state (from audit timeline) is a SEPARATE authority from the
// coarse shipment.dhlStatus field (from batch summary). They should agree directionally;
// the pipeline card clearly labels its source to avoid confusion if they diverge.
function DhlReadinessCard({ batchId }) {
  const [readiness, setReadiness] = React.useState(null);
  const [loading, setLoading]     = React.useState(true);
  const [errType, setErrType]     = React.useState(null);

  React.useEffect(() => {
    if (!batchId) { setLoading(false); return; }
    let cancelled = false;
    window.PzApi.getDhlReadiness(batchId)
      .then(r => {
        if (cancelled) return;
        if (r.ok && r.data) {
          setReadiness(r.data);
        } else {
          setErrType(r.type === 'auth' ? 'auth' : 'error');
        }
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) { setErrType('error'); setLoading(false); }
      });
    return () => { cancelled = true; };
  }, [batchId]);

  if (!batchId) {
    return (
      <div data-testid="dhl-readiness-no-batch" style={{ padding: '14px 20px', color: 'var(--text-2)', fontSize: 12 }}>
        No batch context — DHL clearance pipeline state unavailable.
      </div>
    );
  }
  if (loading) {
    return (
      <div data-testid="dhl-readiness-loading" style={{ padding: '14px 20px', color: 'var(--text-2)', fontSize: 12 }}>
        Loading DHL clearance pipeline…
      </div>
    );
  }
  if (!readiness) {
    const msg = errType === 'auth'
      ? 'Session expired — please refresh the page.'
      : 'Cannot load DHL clearance pipeline state. Check V1 Shipment Detail for current status.';
    return (
      <div data-testid="dhl-readiness-error" style={{ padding: '14px 20px', color: 'var(--badge-red-text)', fontSize: 12 }}>
        {msg}
      </div>
    );
  }

  const currentIdx = DHL_PIPELINE_STATES.findIndex(s => s.key === readiness.dhl_status);

  return (
    <div data-testid="dhl-readiness-card" style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-subtle)' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 8 }}>Clearance Pipeline</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
        {DHL_PIPELINE_STATES.map((s, i) => {
          const isCurrent = i === currentIdx;
          const isPast    = i < currentIdx;
          return (
            <span
              key={s.key}
              data-testid={isCurrent ? 'dhl-stage-current' : undefined}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 3,
                padding: '3px 8px', borderRadius: 4, fontSize: 11,
                fontWeight: isCurrent ? 700 : 500,
                background: isCurrent ? 'var(--accent)' : (isPast ? 'var(--badge-green-bg)' : 'var(--badge-neutral-bg)'),
                color: isCurrent ? '#fff' : (isPast ? 'var(--badge-green-text)' : 'var(--text-3)'),
                border: `1px solid ${isCurrent ? 'var(--accent)' : (isPast ? 'var(--badge-green-border)' : 'var(--border-subtle)')}`,
              }}
            >
              {isPast && <span aria-hidden="true">✓</span>}
              {isCurrent && <span aria-hidden="true">▶</span>}
              {s.label}
            </span>
          );
        })}
      </div>

      {readiness.next_required_action && (
        <div style={{ fontSize: 12, color: 'var(--text)', background: 'var(--bg-subtle)', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border-subtle)', marginBottom: 8 }}>
          <span style={{ fontWeight: 700 }}>Next: </span>{readiness.next_required_action}
        </div>
      )}

      {/* SLA breach banner — gated strictly on sla_breach === true.
          sla_breach_reason may be truthy even when breach is suppressed (e.g. "suppressed: SAD received").
          Never show the red banner on sla_breach_reason truthiness alone (V1 precedent: shipment-detail.html:8648). */}
      {readiness.sla_breach === true && (
        <div data-testid="dhl-sla-breach" style={{
          display: 'flex', alignItems: 'flex-start', gap: 8,
          padding: '7px 10px', borderRadius: 6, marginBottom: 8,
          background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
          color: 'var(--badge-red-text)', fontSize: 12,
        }}>
          <span aria-hidden="true" style={{ fontWeight: 800, flexShrink: 0 }}>⚠</span>
          <span>SLA breach: {readiness.sla_breach_reason}</span>
        </div>
      )}

      {readiness.missing_documents && readiness.missing_documents.length > 0 && (
        <div style={{ fontSize: 12, marginBottom: 8 }}>
          <span style={{ fontWeight: 700, color: 'var(--text-3)' }}>Awaiting: </span>
          <span style={{ color: 'var(--badge-amber-text)' }}>{readiness.missing_documents.join(' · ')}</span>
        </div>
      )}

      <div style={{ fontSize: 10, color: 'var(--text-3)', borderTop: '1px solid var(--border-subtle)', paddingTop: 5, marginTop: 4 }}>
        Source: DHL clearance pipeline (audit timeline) · state: <code style={{ fontFamily: 'monospace' }}>{readiness.dhl_status}</code> · GET /api/v1/dhl/readiness/&#123;batch_id&#125;
      </div>
    </div>
  );
}

function DhlTab({ d, shipment, sadUploaded, dhlEmailReceived, replySent, batchId, onReload }) {
  const bid = batchId || '{batch_id}';
  // R-Q1: DHL is a standalone page authority. This sub-tab provides a status summary
  // and an entry point only. All DHL write actions live on the standalone /dhl page.
  const dhlConsoleUrl = batchId ? ('/v2/dhl?batch_id=' + encodeURIComponent(batchId)) : '/v2/dhl';
  return (
    <>
      {/* R-Q1 entry-point — prominent navigation to standalone DHL Console */}
      <div data-testid="dhl-console-entry" style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
        padding: '14px 20px', borderRadius: 10, marginBottom: 4,
        background: 'linear-gradient(135deg, #EDF4FF, #E0EEFF)',
        border: '1px solid #B8D0FF',
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#1A40A0', marginBottom: 2 }}>DHL Console (standalone authority)</div>
          <div style={{ fontSize: 12, color: '#4060B8', lineHeight: 1.4 }}>
            All DHL clearance actions (inbox scan, reply send, approvals) run on the DHL Console page.
            This sub-tab shows the current clearance status only.
          </div>
        </div>
        <a
          href={dhlConsoleUrl}
          data-testid="dhl-open-console-link"
          aria-label="Open DHL Console standalone page"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 18px', borderRadius: 7, fontSize: 12, fontWeight: 700,
            background: '#1A40A0', color: '#fff', textDecoration: 'none',
            border: 'none', cursor: 'pointer', flexShrink: 0, whiteSpace: 'nowrap',
          }}
        >Open DHL Console ↗</a>
      </div>
      <DhlReadinessCard batchId={batchId} />
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
            <InfoRow label="Total Invoice CIF"  value={_fmtUsd(d.cifUsd)} />
            <InfoRow label="CIF Source"         value={_dash(d.cifSource)} />
            <InfoRow label="Invoices Parsed"    value={_dash(d.invoicesParsed)} />
            <InfoRow label="DHL Threshold"      value={d.thresholdUsd != null ? (_fmtUsd(d.thresholdUsd) + (d.dskRequiredHint ? ' — Reply Required' : '')) : '—'} />
            <InfoRow label="DSK Recommendation" value={_dash(d.clearanceHint)} />
            <InfoRow label="CN Code"            value={_dash(d.cnCode)} />

          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Reply package status</div>
            <InfoRow label="DHL Email"           value={dhlEmailReceived ? 'Received ✓' : 'Awaiting'} />
            <InfoRow label="Polish Description"  value={d.polishDescGenerated ? 'Generated ✓' : '—'} />
            <InfoRow label="DSK PDF"             value={d.dskGenerated ? 'Generated ✓' : '—'} />
            <InfoRow label="Reply Package"       value={replySent ? 'Sent ✓' : (d.replyPackageBuilt ? 'Built ✓' : '—')} />
            <InfoRow label="Reply Sent"          value={replySent ? 'Sent ✓ — see Timeline for exact time' : 'Not sent'} />
          </div>
        </div>
        <BackendPendingBanner testid="dhl-actions-console-note">
          DHL correspondence (inbox scan, description/DSK generation, reply send/approve) is
          performed on the standalone <strong>DHL Console</strong>, which is the single authority
          for DHL email correspondence. This page shows clearance status read-only — it does not
          send DHL correspondence.
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
            <InfoRow label="MRN"                value={_dash(d.mrn)} mono />
            <InfoRow label="LRN"                value={_dash(d.lrn)} mono />
            <InfoRow label="Clearance Date"     value={_fmtDate(d.clearanceDate)} />
            <InfoRow label="Customs Agent"      value={_dash(d.customsAgent)} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Values & rates</div>
            <InfoRow label="SAD Customs Rate"    value={d.sadRate != null ? ('USD/PLN ' + _fmtRate(d.sadRate)) : '—'} />
            <InfoRow label="NBP Accounting Rate" value={d.nbpRate != null ? ('USD/PLN ' + _fmtRate(d.nbpRate)) : '—'} />
            <InfoRow label="A00 Duty"            value={_fmtPln(d.dutyA00Pln)} />
            <InfoRow label="B00 VAT"             value={_fmtPln(d.vatB00Pln)} />
            <InfoRow label="VAT Mode"            value={_dash(d.vatModeLabel)} />
          </div>
        </div>

        {d.checks.length > 0 && (
          <div style={{ margin: '0 20px 16px', padding: '14px 16px', background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-green-text)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Verification checks</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {d.checks.map(c => (
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

        {/* Verification decision — surfaced honestly from the SAD decision
            engine; never inferred from a SAD file merely existing. */}
        {d.sadDecision && d.sadDecision.safe_to_run_pz === false && (
          <div data-testid="sad-pz-blocked" style={{ margin: '0 20px 16px', padding: '12px 16px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 8, fontSize: 12, color: 'var(--badge-red-text)' }}>
            <strong>PZ blocked by SAD validation.</strong> Reason: {d.sadDecision.reason || 'unknown'}
            {d.sadDecision.mrn_parsed || d.sadDecision.mrn_declared
              ? <span> · parsed MRN {d.sadDecision.mrn_parsed || '—'} vs declared {d.sadDecision.mrn_declared || '—'}</span> : null}
          </div>
        )}
        {d.sadDecision && d.sadDecision.safe_to_run_pz === true && (
          <div data-testid="sad-verified" style={{ margin: '0 20px 16px', padding: '10px 16px', background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 8, fontSize: 12, color: 'var(--badge-green-text)', fontWeight: 600 }}>
            ✓ SAD validated — safe to run PZ{d.sadDecision.reason ? ` (${d.sadDecision.reason})` : ''}
          </div>
        )}

        <SadActionBar batchId={bid} onReload={onReload} sadPresent={!!d.sadPresent} />
      </PanelCard>
    </>
  );
}

// SAD/ZC429 upload + parse/recheck — canonical backend authority.
// Upload: POST /api/v1/upload/shipment/{id}/sad (require_api_key).
// Recheck: POST /dashboard/batches/{id}/recheck {mode:'sad'} (role-gated).
// Never fakes verification; reloads batch detail so parsed values + the
// decision-engine verdict refresh from backend truth.
function SadActionBar({ batchId, onReload, sadPresent }) {
  const [busy, setBusy] = React.useState('');
  const [msg, setMsg]   = React.useState(null);   // { ok, text }
  const fileRef = React.useRef(null);

  const doUpload = async (e) => {
    const f = e.target.files && e.target.files[0];
    if (fileRef.current) fileRef.current.value = '';
    if (!f) return;
    if (!/\.pdf$/i.test(f.name)) { setMsg({ ok: false, text: 'SAD upload must be a PDF.' }); return; }
    setBusy('upload'); setMsg(null);
    const res = await window.PzApi.uploadSad(batchId, f);
    setBusy('');
    if (!res.ok) { setMsg({ ok: false, text: res.error || 'SAD upload failed.' }); return; }
    setMsg({ ok: true, text: 'SAD uploaded. Run "Parse / Recheck" to verify customs values.' });
    if (onReload) onReload();
  };
  const doRecheck = async () => {
    setBusy('recheck'); setMsg(null);
    const res = await window.PzApi.recheckSad(batchId);
    setBusy('');
    if (!res.ok) {
      const auth = res.type === 'auth' || res.status === 401 || res.status === 403;
      setMsg({ ok: false, text: auth ? 'Parse/recheck needs the admin / logistics / accounts role.' : (res.error || 'Recheck failed.') });
      return;
    }
    setMsg({ ok: true, text: 'Recheck complete — customs values + verification refreshed.' });
    if (onReload) onReload();
  };

  return (
    <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <input ref={fileRef} type="file" accept=".pdf" onChange={doUpload} style={{ display: 'none' }} data-testid="sad-upload-input" />
      <Btn variant="outline" small disabled={!!busy} onClick={() => fileRef.current && fileRef.current.click()} data-testid="sad-upload">{busy === 'upload' ? 'Uploading…' : '⊞ Upload SAD / ZC429 (PDF)'}</Btn>
      <Btn variant="outline" small disabled={!!busy || !sadPresent} onClick={doRecheck} data-testid="sad-recheck" title={sadPresent ? 'Parse / re-verify the uploaded SAD' : 'Upload a SAD first'}>{busy === 'recheck' ? 'Rechecking…' : '↻ Parse / Recheck SAD'}</Btn>
      {msg && (
        <span data-testid="sad-action-msg" style={{ fontSize: 12, fontWeight: 600, color: msg.ok ? 'var(--badge-green-text)' : 'var(--badge-red-text)' }}>
          {msg.ok ? '✓ ' : '⚠ '}{msg.text}
        </span>
      )}
    </div>
  );
}

// ── PZ / ACCOUNTING

function PzTab({ d, shipment, sadUploaded, pzGenerated, pzExported, pzNumber, batchId, setActiveTab }) {
  const bid = batchId || '{batch_id}';
  const wfirmaStatus = d.pzDocId ? 'Booked ✓' : (d.wfirmaMode === 'clipboard' ? 'Clipboard generated' : (pzExported ? 'Exported ✓' : 'Not exported'));
  // Honest readiness: a SAD file existing does NOT mean PZ is ready. If the SAD
  // decision engine blocked PZ (safe_to_run_pz===false), never show "Ready".
  const pzBlocked = !!(d.sadDecision && d.sadDecision.safe_to_run_pz === false);
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
        status={pzExported ? 'Exported' : (pzGenerated ? 'Generated' : (pzBlocked ? 'PZ Blocked' : 'Ready for PZ'))}
        accent={pzExported ? '#22A06B' : (pzGenerated ? '#22A06B' : 'var(--accent)')}
      >
        {pzBlocked && !pzGenerated && (
          <div data-testid="pz-sad-blocked" style={{ margin: '12px 20px 0', padding: '12px 16px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 8, fontSize: 12, color: 'var(--badge-red-text)' }}>
            <strong>PZ blocked by SAD validation.</strong> Reason: {d.sadDecision.reason || 'unknown'}. Resolve on the DHL / Customs tab before generating PZ.
          </div>
        )}
        <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>PZ details</div>
            <InfoRow label="PZ Status"   value={pzGenerated ? 'Generated ✓' : (pzBlocked ? 'Blocked (SAD validation)' : 'Ready for PZ')} />
            <InfoRow label="PZ Number"   value={_dash(d.pzNumber)} mono />
            <InfoRow label="Net Value"   value={_fmtPln(d.netPln)} />
            <InfoRow label="Gross Value" value={_fmtPln(d.grossPln)} />
            <InfoRow label="Duty A00"    value={_fmtPln(d.dutyPln)} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>wFirma export</div>
            <InfoRow label="wFirma Status"   value={wfirmaStatus} />
            <InfoRow label="Export Date"     value={_fmtDate(d.pzExportDate, true)} />
            <InfoRow label="External Doc ID" value={_dash(d.pzDocId)} mono />
          </div>
        </div>

        <BackendPendingBanner testid="pz-actions-pending-note">
          PZ generation and wFirma export are not yet wired into this V2 page. The backend routes
          exist — run these on the V1 Shipment Detail page today. Wiring is tracked in BACKEND_GAP_REGISTER.md.
        </BackendPendingBanner>
        {/* SD-5: full 7-button set per wireframe §3.2 Tab 4 */}
        <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {/* ▶ Run PZ (gold, primary — shown when PZ not yet generated) */}
          {!pzGenerated && (
            <PendingAction label="Run PZ" icon="▶" testid="run-pz" route={'POST /api/v1/upload/shipment/' + bid + '/wfirma/pz_create'} variant="gold" />
          )}
          {/* ↺ Regenerate PZ (shown when PZ already generated) */}
          {pzGenerated && (
            <PendingAction label="Regenerate PZ" icon="↺" testid="regenerate-pz" route={'POST /api/v1/upload/shipment/' + bid + '/wfirma/pz_create'} />
          )}
          {/* ✎ Confirm PZ Number */}
          <PendingAction label="Confirm PZ Number" icon="✎" testid="confirm-pz" route={'POST /api/v1/upload/shipment/' + bid + '/wfirma/pz_confirm'} />
          {/* ↓ Download XLSX — GET /api/v1/files/{batch_id}/pz.xlsx */}
          <PendingAction label="Download XLSX" icon="↓" testid="download-xlsx" route={'GET /api/v1/files/' + bid + '/pz.xlsx'} />
          {/* ↓ Download PDF — GET /api/v1/files/{batch_id}/pz.pdf */}
          <PendingAction label="Download PDF" icon="↓" testid="download-pdf" route={'GET /api/v1/files/' + bid + '/pz.pdf'} />
          {/* ↗ Export to wFirma (gold — primary when PZ generated, not yet exported) */}
          <PendingAction label="Export to wFirma" icon="↗" testid="export-wfirma" route={'POST /api/v1/upload/shipment/' + bid + '/wfirma/pz_create'} variant={pzGenerated && !pzExported ? 'gold' : 'outline'} />
          {/* ✓ Mark Exported */}
          <PendingAction label="Mark Exported" icon="✓" testid="mark-exported" route={'POST /api/v1/upload/shipment/' + bid + '/wfirma/pz_adopt'} />
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

// ── DOCUMENTS — canonical shipment-document manifest (Wave 3)
// Authority: GET /api/v1/upload/shipment/{batch_id}/documents (routes_upload.py).
// Consumes ONLY the manifest identity contract (document_id, document_type,
// authority, is_generated, is_current, mime_type, can_view/download/replace/
// delete, view_url, download_url). The old _WIREFRAME_DOC_CARDS + the
// /dashboard/batches/{id}/files filesystem-scan endpoint are RETIRED — they
// mismapped Packing List→AWB, CMR→calc_xlsx, wFirma→audit_en. No file_path is
// ever exposed. All View/Download/Replace/Delete come from capability flags.

const _DOC_TYPE_LABELS = {
  purchase_invoice:      'Purchase Invoice',
  sales_proforma:        'Sales Proforma',
  sales_invoice:         'Sales Invoice',
  purchase_packing_list: 'Purchase Packing List',
  sales_packing_list:    'Sales Packing List',
  awb:                   'AWB / Tracking',
  service_invoice:       'Service Invoice',
  carnet:                'ATA Carnet',
  sad_pdf:               'SAD / ZC429 (PDF)',
  sad_xml:               'SAD / ZC429 (XML)',
  pz_pdf:                'PZ PDF',
  pz_xlsx:               'PZ XLSX',
  calculation_xlsx:      'Calculation XLSX',
  audit_memo:            'Audit Memo',
  audit_en:              'Audit EN',
  audit_pl:              'Audit PL',
  invoice:               'Invoice (legacy)',
  packing:               'Packing (legacy)',
  other:                 'Other Document',
};
function _docTypeLabel(t) { return _DOC_TYPE_LABELS[t] || (t || 'Document'); }

function _authorityLabel(row) {
  if (row.is_generated) return 'Generated';
  const a = row.authority || 'upload';
  if (a === 'intake' || a === 'upload' || a === 'add_document' || a === 'backfill') return 'Uploaded';
  return a;
}

function DocumentRow({ batchId, row, onChanged }) {
  const [busy, setBusy] = React.useState('');
  const [err, setErr]   = React.useState('');
  const fileRef = React.useRef(null);
  const ext = (row.original_filename || '').split('.').pop().toLowerCase();
  const superseded = row.is_current === false;

  const doReplace = async (e) => {
    const f = e.target.files && e.target.files[0];
    if (fileRef.current) fileRef.current.value = '';
    if (!f) return;
    if (!window.confirm(`Replace "${row.original_filename}" with "${f.name}"? The current file is superseded (kept in the audit trail).`)) return;
    setBusy('replace'); setErr('');
    const res = await window.PzApi.replaceDocument(batchId, row.document_id, f);
    setBusy('');
    if (!res.ok) { setErr(res.error || 'Replace failed'); return; }
    onChanged();
  };
  const doDelete = async () => {
    if (!window.confirm(`Delete "${row.original_filename}" (${_docTypeLabel(row.document_type)})? This removes the file and its registry row.`)) return;
    setBusy('delete'); setErr('');
    const res = await window.PzApi.deleteDocument(batchId, row.document_id);
    setBusy('');
    if (!res.ok) { setErr(res.error || 'Delete failed'); return; }
    onChanged();
  };

  return (
    <div data-testid={`doc-row-${row.document_id}`} data-doctype={row.document_type}
      style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px', borderRadius: 8,
        border: '1px solid var(--border)', background: superseded ? 'var(--bg-subtle)' : 'var(--card)',
        boxShadow: '0 1px 2px var(--shadow)', opacity: superseded ? 0.7 : 1 }}>
      <div style={{ width: 38, height: 38, borderRadius: 8, background: 'var(--bg-subtle)', color: 'var(--text-2)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 800, letterSpacing: '0.05em' }}>
        {ext ? ext.toUpperCase() : '?'}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {row.original_filename || '—'}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontWeight: 600 }}>{_docTypeLabel(row.document_type)}</span>
          <span style={{ color: 'var(--text-3)' }}>· {_authorityLabel(row)}</span>
          {row.created_at && <span style={{ color: 'var(--text-3)' }}>· {_fmtDate(row.created_at)}</span>}
          {superseded && <span data-testid="doc-superseded" style={{ padding: '1px 6px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', border: '1px solid var(--badge-amber-border)' }}>Superseded</span>}
          {!row.can_delete && !superseded && <span data-testid="doc-locked" style={{ padding: '1px 6px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'var(--badge-neutral-bg)', color: 'var(--text-3)', border: '1px solid var(--border-subtle)' }} title="Generated fiscal / customs document — non-deletable">🔒 Protected</span>}
        </div>
        {err && <div style={{ fontSize: 11, color: 'var(--badge-red-text)', marginTop: 4 }}>{err}</div>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {row.can_view && (
          <Btn variant="outline" small data-testid="doc-view" onClick={() => window.open(row.view_url || window.PzApi.viewDocument(batchId, row.document_id), '_blank', 'noopener')} title="View (opens inline in a new tab)">👁 View</Btn>
        )}
        {row.can_download && (
          <a data-testid="doc-download" href={row.download_url || window.PzApi.downloadDocument(batchId, row.document_id)}
            target="_blank" rel="noopener noreferrer" style={{ ..._docBtn(), textDecoration: 'none' }} title="Download document" aria-label="Download document">↓ Download</a>
        )}
        {row.can_replace && (
          <>
            <input ref={fileRef} type="file" accept={ext ? '.' + ext : undefined} onChange={doReplace} style={{ display: 'none' }} data-testid="doc-replace-input" />
            <Btn variant="outline" small data-testid="doc-replace" disabled={!!busy} onClick={() => fileRef.current && fileRef.current.click()} title="Replace document (supersedes the current file; the original is kept in the audit trail)">{busy === 'replace' ? '…' : '⇄ Replace'}</Btn>
          </>
        )}
        {row.can_delete && (
          <Btn variant="outline" small data-testid="doc-delete" disabled={!!busy} onClick={doDelete} title="Delete document (confirmation + audit)"><span style={{ color: 'var(--badge-red-text)' }}>{busy === 'delete' ? '…' : '🗑 Delete'}</span></Btn>
        )}
      </div>
    </div>
  );
}
function _docBtn() {
  return { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '5px 9px',
    borderRadius: 5, fontSize: 11, fontWeight: 600, border: '1px solid var(--border)',
    background: 'transparent', color: 'var(--text)', cursor: 'pointer' };
}

function DocumentsTab({ batchId }) {
  const [docs,    setDocs]    = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error,   setError]   = React.useState(null);

  const load = React.useCallback(() => {
    if (!batchId) return;
    setLoading(true); setError(null);
    window.PzApi.getShipmentDocuments(batchId).then(res => {
      if (res.ok) setDocs((res.data && res.data.documents) || []);
      else setError(res.error || 'Failed to load documents');
      setLoading(false);
    });
  }, [batchId]);
  React.useEffect(() => { load(); }, [load]);

  if (!batchId) {
    return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-2)', fontSize: 13 }}>No batch context — documents unavailable.</div>;
  }
  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>Loading documents…</div>;
  if (error)   return <div style={{ padding: 40, textAlign: 'center', color: 'var(--badge-red-text)', fontSize: 13 }} data-testid="documents-error">Failed to load documents: {error}</div>;

  const rows = docs || [];
  // Current (non-superseded) first, then by created_at; superseded rows kept visible.
  const sorted = [...rows].sort((a, b) => (a.is_current === b.is_current ? 0 : a.is_current ? -1 : 1));

  return (
    <div data-testid="documents-tab" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <SectionLabel>Shipment documents ({rows.length})</SectionLabel>
        <Btn variant="outline" small data-testid="documents-reload" onClick={load} title="Reload manifest">↻ Reload</Btn>
      </div>
      {sorted.length === 0
        ? <div style={{ padding: '24px 0', fontSize: 13, color: 'var(--text-3)', textAlign: 'center' }}>No documents registered for this shipment.</div>
        : <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {sorted.map(row => <DocumentRow key={row.document_id} batchId={batchId} row={row} onChanged={load} />)}
          </div>
      }
    </div>
  );
}

// ── TIMELINE
//
// SD-7: Full 16-event label map per wireframe §3.2 Tab 6. Shows:
//   - Done events (from audit.timeline) with timestamp + actor.
//   - Pending milestones (derived from shipment state) with "Pending" label.
// Authority: audit.timeline (append-only log from batch detail endpoint).
// No fabricated timestamps; pending events are state-derived not invented.

const _EVENT_LABELS = {
  // Wireframe 16-event canonical names + audit log event names
  batch_created:                   'Shipment created',
  invoice_uploaded:                'Invoice uploaded',
  awb_uploaded:                    'AWB uploaded',
  dhl_precheck_completed:          'DHL pre-check completed',
  dhl_email_received:              'DHL clearance email received',
  polish_description_generated:    'Polish description generated',
  dsk_generated:                   'DSK generated',
  reply_package_generated:         'Reply package prepared',
  reply_sent:                      'Reply sent to DHL',
  agency_forward_after_dhl_queued: 'Forwarded to customs agency',
  sad_imported:                    'SAD / ZC429 uploaded',
  sad_uploaded:                    'SAD / ZC429 uploaded',
  customs_values_parsed:           'Customs values parsed',
  customs_parsed:                  'Customs values parsed',
  verification_checks_passed:      'Verification checks passed',
  customs_verified:                'Verification checks passed',
  pz_unlocked:                     'PZ unlocked',
  pz_created:                      'PZ generated',
  pz_confirmed:                    'PZ number confirmed',
  wfirma_pz_created:               'PZ exported to wFirma',
  wfirma_exported:                 'PZ exported to wFirma',
};

function _humanizeEvent(name) {
  if (!name) return 'Event';
  if (_EVENT_LABELS[name]) return _EVENT_LABELS[name];
  return String(name).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// Wireframe 16-event ordered milestone list — used to show pending events
// when the audit log has not yet recorded them. Event presence in audit log
// is the source of truth; this list only provides the ordered display set.
const _TIMELINE_MILESTONES = [
  'batch_created',
  'invoice_uploaded',
  'awb_uploaded',
  'dhl_precheck_completed',
  'dhl_email_received',
  'polish_description_generated',
  'dsk_generated',
  'reply_package_generated',
  'reply_sent',
  'sad_imported',
  'customs_parsed',
  'verification_checks_passed',
  'pz_unlocked',
  'pz_created',
  'pz_confirmed',
  'wfirma_pz_created',
];

function TimelineTab({ d, detailLoading }) {
  const doneEvents = (d.timeline || []).slice().sort((a, b) => String(a.ts || '').localeCompare(String(b.ts || '')));
  const doneKeys = new Set(doneEvents.map(e => e.event));

  if (detailLoading && doneEvents.length === 0) {
    return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>Loading timeline…</div>;
  }

  // Build display list: done events (with timestamp) + pending milestones (no timestamp)
  // Done events appear in their audit-log order; pending milestones follow in wireframe order.
  // Pending milestones that are aliases of done events are suppressed.
  const pendingMilestones = _TIMELINE_MILESTONES.filter(key => {
    // Check the key and common aliases
    const aliases = {
      sad_imported: ['sad_uploaded', 'sad_imported'],
      customs_parsed: ['customs_values_parsed', 'customs_parsed'],
      verification_checks_passed: ['verification_checks_passed', 'customs_verified'],
      wfirma_pz_created: ['wfirma_pz_created', 'wfirma_exported'],
    };
    const checkKeys = aliases[key] || [key];
    return !checkKeys.some(k => doneKeys.has(k));
  });

  const totalEvents = doneEvents.length;
  const totalMilestones = _TIMELINE_MILESTONES.length;

  return (
    <PanelCard
      title="Activity timeline"
      subtitle={`${totalEvents} of ${totalMilestones} milestones completed`}
    >
      {doneEvents.length === 0 && pendingMilestones.length === 0 ? (
        <div data-testid="timeline-empty" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
          No timeline events recorded for this shipment yet.
        </div>
      ) : (
        <div data-testid="timeline-events" style={{ padding: '24px 28px' }}>
          <div style={{ position: 'relative', paddingLeft: 28 }}>
            <div style={{ position: 'absolute', left: 9, top: 6, bottom: 6, width: 2, background: 'var(--border)' }} />

            {/* Done events — from audit log, in timestamp order */}
            {doneEvents.map((e, i) => (
              <div key={i} data-testid="timeline-event-done" style={{ position: 'relative', marginBottom: 16, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
                <div style={{
                  position: 'absolute', left: -28,
                  width: 20, height: 20, borderRadius: 10,
                  background: '#22A06B', border: '2px solid #22A06B',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  zIndex: 1, top: 0, flexShrink: 0,
                }}>
                  <span style={{ fontSize: 10, color: '#fff', fontWeight: 800 }}>✓</span>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{_humanizeEvent(e.event)}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2, fontFamily: 'monospace' }}>
                    {_fmtDate(e.ts, true)}{e.actor ? ' · ' + e.actor : ''}
                  </div>
                </div>
              </div>
            ))}

            {/* Pending milestones — derived from state, no timestamp */}
            {pendingMilestones.length > 0 && (
              <>
                {doneEvents.length > 0 && (
                  <div style={{ position: 'relative', marginBottom: 12, marginLeft: 6 }}>
                    <div style={{ width: 8, height: 8, borderRadius: 4, background: 'var(--border)', display: 'inline-block' }} />
                  </div>
                )}
                {pendingMilestones.map((key, i) => (
                  <div key={key} data-testid="timeline-event-pending" style={{ position: 'relative', marginBottom: 12, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
                    <div style={{
                      position: 'absolute', left: -28,
                      width: 20, height: 20, borderRadius: 10,
                      background: 'var(--bg)', border: '2px solid var(--border)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      zIndex: 1, top: 0, flexShrink: 0,
                    }}>
                      <span style={{ fontSize: 8, color: 'var(--text-3)', fontWeight: 800 }}>○</span>
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-2)' }}>{_humanizeEvent(key)}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 1 }}>Pending</div>
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </PanelCard>
  );
}

// Per-draft readiness panel for active (non-terminal) draft states.
// Authority: GET /api/v1/proforma/draft/{id}/readiness?intent=approve
// Known write-on-read: idempotent bridge-write (packing_lines → design_product_mapping).
// Calls staggered by mountDelayMs to prevent concurrent SQLite lock contention.
function DraftReadinessCard({ draft, mountDelayMs }) {
  const [readiness, setReadiness] = React.useState(null);
  const [readinessLoading, setReadinessLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      window.PzApi.getDraftReadiness(draft.id, 'approve')
        .then(r => {
          if (!cancelled) {
            setReadiness((r && r.ok && r.data) ? r.data : null);
            setReadinessLoading(false);
          }
        })
        .catch(() => {
          if (!cancelled) { setReadiness(null); setReadinessLoading(false); }
        });
    }, mountDelayMs || 0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [draft.id]);

  const STATE_BADGE = { draft: 'Draft', editing: 'In Preparation', post_failed: 'Action Required' };
  const draftTitle  = draft.wfirma_proforma_fullnumber || ('#' + draft.id);
  const badgeStatus = STATE_BADGE[draft.draft_state] || 'Draft';
  const isPostFailed = draft.draft_state === 'post_failed';

  return (
    <div style={{ marginBottom: 8 }}>
      <PanelCard>
        <div style={{ padding: '16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', flex: 1 }}>
              {draft.client_name || '(no client)'}
            </div>
            <Badge status={badgeStatus} small />
            <div style={{ fontSize: 11, color: 'var(--text-2)' }} data-testid="proforma-draft-id">
              Draft {draftTitle}
            </div>
          </div>

          {/* post_failed error box — always visible for post_failed; error_hint from
              _draft_to_summary (routes_proforma.py:3838) may contain raw wFirma error text.
              Static retry guidance is always shown so the operator knows the next step. */}
          {isPostFailed && (
            <div data-testid="proforma-post-failed-error" style={{
              background: 'var(--badge-red-bg, #FBE8E6)',
              border: '1px solid var(--badge-red-border, #E0A8A0)',
              borderRadius: 6, padding: '10px 14px', marginBottom: 12,
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-red-text, #902018)',
                            textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>
                wFirma post failed
              </div>
              {draft.error_hint ? (
                <div style={{ fontSize: 11, color: 'var(--badge-red-text, #902018)',
                              fontFamily: 'monospace', wordBreak: 'break-word', marginBottom: 6 }}>
                  {draft.error_hint}
                </div>
              ) : (
                <div style={{ fontSize: 11, color: 'var(--badge-red-text, #902018)', marginBottom: 6 }}>
                  Failure reason not recorded.
                </div>
              )}
              <div style={{ fontSize: 11, color: 'var(--text-2)' }}>
                Re-open Pro Forma hub to retry posting.
              </div>
            </div>
          )}

          {readinessLoading ? (
            <div style={{ fontSize: 12, color: 'var(--text-2)' }}>Checking readiness…</div>
          ) : readiness === null ? (
            <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
              Readiness unavailable — open Pro Forma hub to retry.
            </div>
          ) : readiness.ready ? (
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--badge-green-text, #166534)' }}
                 data-testid="proforma-ready-chip">
              ✓ Ready to approve
            </div>
          ) : (
            <div data-testid="proforma-blockers">
              <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>
                {(readiness.blockers || []).length} blocker(s) preventing approval:
              </div>
              <ol style={{ margin: 0, paddingLeft: 22 }}>
                {(readiness.blockers || []).map((b, i) => (
                  <li key={i} style={{ fontSize: 12, color: 'var(--text)', marginBottom: 10 }}>
                    <div style={{ fontWeight: 600, marginBottom: 3 }}>{b.reason}</div>
                    {b.repair_action && (
                      <div style={{
                        background: 'var(--bg-subtle, var(--card))',
                        border: '1px solid var(--border)',
                        borderRadius: 4, padding: '6px 10px',
                        fontSize: 11, color: 'var(--text)',
                      }}>
                        Fix: {b.repair_action}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      </PanelCard>
    </div>
  );
}

// Pro Forma tab inside shipment detail — shows per-draft readiness so operators
// can see exactly why a draft is not ready without navigating away from the page.
// Authority: GET /api/v1/proforma/drafts/{batch_id} + GET /draft/{id}/readiness
function ProformaTabInShipment({ shipment }) {
  const batchId = shipment && shipment.batch_id;
  // Hook called unconditionally (React rules); null batchId returns empty list.
  const draftsState = window.PzState.useProformaDrafts(batchId || null);

  const goToProforma = () => {
    if (!batchId) return;
    window.location.href = '/v2/proforma?batch_id=' + encodeURIComponent(batchId);
  };

  if (!batchId) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-2)' }}>
        <div style={{ fontSize: 13 }}>No batch context — Pro Forma drafts unavailable.</div>
      </div>
    );
  }

  const allDrafts = (draftsState.data && draftsState.data.drafts) || [];

  // Partition by draft_state (API field is draft_state, confirmed from _draft_to_summary)
  // Full 8-state lifecycle: draft|editing|approved|posting|posted|post_failed|cancelled|superseded
  const READINESS_STATES = new Set(['draft', 'editing', 'post_failed']);
  const SUCCESS_STATES   = new Set(['approved', 'posted']);
  // cancelled and superseded are hidden; posting shown separately

  const activeDrafts  = allDrafts.filter(d => READINESS_STATES.has(d.draft_state));
  const postingDrafts = allDrafts.filter(d => d.draft_state === 'posting');
  const successDrafts = allDrafts.filter(d => SUCCESS_STATES.has(d.draft_state));

  return (
    <>
      <SectionLabel>Pro Forma drafts for this shipment</SectionLabel>

      {/* Navigation — always visible per Lesson M */}
      <div style={{ marginBottom: 16 }}>
        <PanelCard>
          <div style={{ padding: '20px 24px', display: 'flex', alignItems: 'center', gap: 20 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>
                Pro Forma hub — batch {batchId}
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
      </div>

      {draftsState.loading && (
        <div style={{ fontSize: 13, color: 'var(--text-2)', padding: '8px 0' }}>Loading drafts…</div>
      )}
      {draftsState.error && (
        <div style={{ fontSize: 13, color: 'var(--badge-red-text, #991b1b)', padding: '8px 0' }}>
          Could not load drafts. Open Pro Forma hub to retry.
        </div>
      )}
      {!draftsState.loading && !draftsState.error && allDrafts.length === 0 && (
        <div style={{ fontSize: 13, color: 'var(--text-2)', padding: '8px 0' }}>
          No proforma drafts yet for this batch.
        </div>
      )}

      {activeDrafts.length > 0 && (
        <>
          <SectionLabel style={{ marginTop: 12 }}>Readiness</SectionLabel>
          {activeDrafts.map((d, idx) => (
            <DraftReadinessCard key={d.id} draft={d} mountDelayMs={idx * 150} />
          ))}
        </>
      )}

      {postingDrafts.length > 0 && (
        <>
          <SectionLabel style={{ marginTop: 12 }}>Posting to wFirma</SectionLabel>
          {postingDrafts.map(d => (
            <div key={d.id} style={{ marginBottom: 8 }}>
              <PanelCard>
                <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', flex: 1 }}>
                    {d.client_name || '(no client)'}
                  </div>
                  <Badge status="Processing" small />
                  <div style={{ fontSize: 12, color: 'var(--text-2)' }}>wFirma submission in progress</div>
                </div>
              </PanelCard>
            </div>
          ))}
        </>
      )}

      {!draftsState.loading && !draftsState.error
        && allDrafts.length > 0 && activeDrafts.length === 0 && postingDrafts.length === 0
        && successDrafts.length > 0 && (
        <div data-testid="proforma-all-complete-banner" style={{
          background: 'var(--badge-green-bg, #E8F5EE)',
          border: '1px solid var(--badge-green-border, #96CCA8)',
          borderRadius: 6, padding: '12px 16px', marginBottom: 12,
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--badge-green-text, #186838)' }}>
            ✓ All active Pro Forma drafts complete
          </div>
          <div style={{ fontSize: 12, color: 'var(--badge-green-text, #186838)', opacity: 0.85, marginTop: 3 }}>
            {successDrafts.length} draft(s) approved or posted to wFirma. No action required.
          </div>
        </div>
      )}

      {successDrafts.length > 0 && (
        <>
          <SectionLabel style={{ marginTop: 12 }}>Completed</SectionLabel>
          {successDrafts.map(d => {
            const isPosted = d.draft_state === 'posted';
            const draftTitle = d.wfirma_proforma_fullnumber || ('#' + d.id);
            return (
              <div key={d.id} style={{ marginBottom: 8 }}>
                <PanelCard>
                  <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', flex: 1 }}>
                      {d.client_name || '(no client)'}
                    </div>
                    <Badge status={isPosted ? 'Exported' : 'Generated'} small />
                    <div style={{ fontSize: 12, fontWeight: 600,
                                  color: 'var(--badge-green-text, #166534)' }}>
                      ✓ {draftTitle}
                    </div>
                  </div>
                </PanelCard>
              </div>
            );
          })}
        </>
      )}
    </>
  );
}

Object.assign(window, { ShipmentDetailPage });
