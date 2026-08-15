// ─────────────────────────────────────────────────────────────────────────────
// InsuranceExportTab — Insurance Export Statement & Declaration Composer.
//
// Read-only Accounting Hub section. Two layers:
//   FACTUAL REPORT   — GET /api/v1/accounting/insurance-export (immutable totals)
//   DECLARATION      — ephemeral IDs-only selection; totals come EXCLUSIVELY
//                      from the debounced POST /declaration-preview response.
//
// GOVERNANCE (pinned by test_insurance_export_no_recomputation.py):
//   • Zero client-side monetary math. Every money value rendered here is a
//     server-formatted string. No arithmetic on monetary fields.
//   • Selection sends identifiers and presentation choices only; the server
//     re-resolves everything from canonical authority.
// ─────────────────────────────────────────────────────────────────────────────

const INS_MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function insPad2(n) {
  return n < 10 ? `0${n}` : `${n}`;
}

// Period bounds for a monthly selection. month = 0 means "All year".
function insMonthlyPeriod(year, month) {
  if (!month) {
    return { from: `${year}-01-01`, to: `${year}-12-31` };
  }
  const lastDay = new Date(year, month, 0).getDate();
  return {
    from: `${year}-${insPad2(month)}-01`,
    to: `${year}-${insPad2(month)}-${insPad2(lastDay)}`,
  };
}

const INS_STATUS_CHIP = {
  included:             { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
  excluded:             { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
  personal_pickup:      { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
  no_insurance_charged: { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)' },
  needs_review:         { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)' },
  return:               { bg: 'var(--badge-purple-bg)',  fg: 'var(--badge-purple-text)',  bd: 'var(--badge-purple-border)' },
  cancelled:            { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)' },
};

function InsStatusChip({ status, label }) {
  const c = INS_STATUS_CHIP[status] || INS_STATUS_CHIP.excluded;
  return (
    <span data-testid={`ins-export-status-${status}`} style={{
      fontSize: 9, padding: '1px 6px', borderRadius: 2, whiteSpace: 'nowrap',
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
      fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
    }}>{label || status}</span>
  );
}

function InsKpiTile({ testid, label, value, sub }) {
  return (
    <div data-testid={testid} style={{
      flex: '1 1 120px', minWidth: 120, padding: '10px 14px', borderRadius: 8,
      background: 'var(--surface-2, var(--surface))', border: '1px solid var(--border)',
    }}>
      <div style={{
        fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)',
        textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4,
      }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      {sub ? <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{sub}</div> : null}
    </div>
  );
}

// Money cell — renders the server-formatted string verbatim; red for negatives.
function InsMoney({ value }) {
  const s = value === null || value === undefined || value === '' ? '—' : String(value);
  const neg = s.charAt(0) === '-';
  return (
    <span style={{
      fontVariantNumeric: 'tabular-nums',
      color: neg ? 'var(--badge-red-text)' : 'inherit',
    }}>{s}</span>
  );
}

function InsuranceExportTab() {
  const now = new Date();
  const [periodMode, setPeriodMode] = React.useState('monthly');
  const [year, setYear]   = React.useState(now.getFullYear());
  const [month, setMonth] = React.useState(now.getMonth() + 1); // 0 = All year
  const [customFrom, setCustomFrom] = React.useState('');
  const [customTo, setCustomTo]     = React.useState('');
  const [period, setPeriod] = React.useState(insMonthlyPeriod(now.getFullYear(), now.getMonth() + 1));

  const [report, setReport]   = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError]     = React.useState(null);

  const [selDocs, setSelDocs] = React.useState(() => new Set());
  const [selAdjs, setSelAdjs] = React.useState(() => new Set());
  const [viewFilter, setViewFilter] = React.useState('all');

  const [preview, setPreview]             = React.useState(null);
  const [previewLoading, setPreviewLoading] = React.useState(false);
  const [previewError, setPreviewError]   = React.useState(null);

  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [pdfOptions, setPdfOptions] = React.useState({
    includeDocuments: true, includeAdjustments: true, recoveredColumn: true,
  });
  const [downloading, setDownloading] = React.useState(false);
  const [downloadError, setDownloadError] = React.useState(null);

  const loadReport = React.useCallback(async (p, refresh) => {
    setLoading(true); setError(null);
    const r = await window.PzApi.getInsuranceExport(p.from, p.to, !!refresh);
    if (r.ok) {
      setReport(r.data);
    } else {
      setReport(null);
      setError(r.error || 'Failed to load the insurance export report.');
    }
    setLoading(false);
  }, []);

  // Load on period change; selection is ephemeral and resets with the period.
  React.useEffect(() => {
    setSelDocs(new Set()); setSelAdjs(new Set());
    setPreview(null); setPreviewError(null);
    loadReport(period, false);
  }, [period, loadReport]);

  // Debounced (500 ms) declaration preview — the ONLY source of selected totals.
  React.useEffect(() => {
    if (!report) return undefined;
    if (selDocs.size === 0 && selAdjs.size === 0) {
      setPreview(null); setPreviewError(null); setPreviewLoading(false);
      return undefined;
    }
    setPreviewLoading(true); setPreviewError(null);
    const docIds = Array.from(selDocs).sort();
    const adjIds = Array.from(selAdjs).sort();
    const timer = setTimeout(async () => {
      const r = await window.PzApi.previewInsuranceDeclaration({
        period_from: period.from,
        period_to: period.to,
        selected_document_ids: docIds,
        selected_adjustment_ids: adjIds,
      });
      if (r.ok) {
        setPreview(r.data);
      } else {
        setPreview(null);
        setPreviewError(r.error || 'Preview failed.');
      }
      setPreviewLoading(false);
    }, 500);
    return () => clearTimeout(timer);
  }, [report, selDocs, selAdjs, period]);

  // ── Selection helpers (IDs only — never values) ──────────────────────────
  const toggleDoc = (id) => {
    setSelDocs(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleAdj = (id) => {
    setSelAdjs(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const groupIds = (grp) => {
    const docs = (grp.rows || []).map(r => r.invoice_id);
    const adjs = [];
    (grp.rows || []).forEach(r => (r.adjustments || []).forEach(a => adjs.push(a.invoice_id)));
    (grp.unattached_adjustments || []).forEach(a => adjs.push(a.invoice_id));
    return { docs, adjs };
  };

  const toggleGroup = (grp) => {
    const ids = groupIds(grp);
    const allSelected =
      ids.docs.every(id => selDocs.has(id)) && ids.adjs.every(id => selAdjs.has(id));
    setSelDocs(prev => {
      const next = new Set(prev);
      ids.docs.forEach(id => { if (allSelected) next.delete(id); else next.add(id); });
      return next;
    });
    setSelAdjs(prev => {
      const next = new Set(prev);
      ids.adjs.forEach(id => { if (allSelected) next.delete(id); else next.add(id); });
      return next;
    });
  };

  const selectAllEligible = () => {
    if (!report) return;
    const docs = new Set();
    const adjs = new Set();
    (report.contractors || []).forEach(grp => {
      (grp.rows || []).forEach(r => {
        if (r.recommendation === 'recommend_include') docs.add(r.invoice_id);
        (r.adjustments || []).forEach(a => {
          if (a.recommendation === 'recommend_include') adjs.add(a.invoice_id);
        });
      });
      (grp.unattached_adjustments || []).forEach(a => {
        if (a.recommendation === 'recommend_include') adjs.add(a.invoice_id);
      });
    });
    setSelDocs(docs); setSelAdjs(adjs);
  };

  const clearSelection = () => { setSelDocs(new Set()); setSelAdjs(new Set()); };

  // ── View filter ──────────────────────────────────────────────────────────
  const rowVisible = (row, isAdj) => {
    if (viewFilter === 'all') return true;
    const selected = isAdj ? selAdjs.has(row.invoice_id) : selDocs.has(row.invoice_id);
    if (viewFilter === 'selected') return selected;
    if (viewFilter === 'excluded') return row.recommendation === 'recommend_exclude';
    if (viewFilter === 'review') return row.status === 'needs_review';
    return true;
  };

  // ── Period controls ──────────────────────────────────────────────────────
  const applyMonthly = (y, m) => {
    setYear(y); setMonth(m);
    setPeriod(insMonthlyPeriod(y, m));
  };
  const stepMonth = (dir) => {
    if (!month) { applyMonthly(year + dir, 0); return; }
    let m = month + dir;
    let y = year;
    if (m < 1)  { m = 12; y = y - 1; }
    if (m > 12) { m = 1;  y = y + 1; }
    applyMonthly(y, m);
  };
  const goToday = () => {
    const d = new Date();
    setPeriodMode('monthly');
    applyMonthly(d.getFullYear(), d.getMonth() + 1);
  };
  const applyCustom = () => {
    if (!customFrom || !customTo) return;
    setPeriod({ from: customFrom, to: customTo });
  };

  const downloadPdf = async () => {
    setDownloading(true); setDownloadError(null);
    const r = await window.PzApi.downloadInsuranceExportPdf({
      period_from: period.from,
      period_to: period.to,
      selected_document_ids: Array.from(selDocs).sort(),
      selected_adjustment_ids: Array.from(selAdjs).sort(),
      include_documents: pdfOptions.includeDocuments,
      include_adjustments: pdfOptions.includeAdjustments,
      columns: { insurance_recovered: pdfOptions.recoveredColumn },
    }, `insurance-export-${period.from}-${period.to}.pdf`);
    if (!r.ok) setDownloadError(r.error || 'Download failed.');
    setDownloading(false);
  };

  const yearOptions = [];
  for (let y = now.getFullYear() + 1; y >= now.getFullYear() - 5; y--) yearOptions.push(y);

  const kpi = (report && report.kpi) || {};
  const recovered = kpi.insurance_recovered || {};
  const recoveredEntries = Object.keys(recovered).sort().slice(0, 4);
  const reportTotals = (report && report.report_totals) || {};
  const selectedCount = selDocs.size + selAdjs.size;

  const declarationTotal = preview && preview.declaration_totals
    ? preview.declaration_totals.sum_insured_inr_grand
    : null;

  const inputStyle = {
    background: 'var(--surface)', border: '1px solid var(--border)',
    color: 'var(--text)', borderRadius: 4, padding: '4px 8px', fontSize: 11,
  };
  const btnOutline = {
    background: 'transparent', border: '1px solid var(--border)',
    color: 'var(--text-2)', borderRadius: 4, padding: '5px 10px',
    fontSize: 11, fontWeight: 600, cursor: 'pointer',
  };
  const btnGold = {
    background: 'var(--accent)', border: '1px solid var(--accent)',
    color: 'var(--accent-text)', borderRadius: 4, padding: '5px 12px',
    fontSize: 11, fontWeight: 700, cursor: 'pointer',
  };
  const thStyle = {
    padding: '6px 8px', fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)',
    textTransform: 'uppercase', letterSpacing: '0.06em', textAlign: 'right',
    borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
  };
  const tdStyle = {
    padding: '5px 8px', fontSize: 11.5, color: 'var(--text)',
    borderBottom: '1px solid var(--border)', textAlign: 'right', whiteSpace: 'nowrap',
  };

  const filterChip = (id, label) => (
    <button
      key={id}
      data-testid={`ins-export-filter-${id}`}
      onClick={() => setViewFilter(id)}
      style={{
        ...btnOutline,
        ...(viewFilter === id
          ? { background: 'var(--accent)', color: 'var(--accent-text)', borderColor: 'var(--accent)' }
          : {}),
      }}
    >{label}</button>
  );

  return (
    <div data-testid="ins-export-root" style={{ padding: '20px 24px', position: 'relative' }}>
      {/* Header */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 17, fontWeight: 800, color: 'var(--text)' }}>
          Insurance Export Statement
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--text-2)', marginTop: 2 }}>
          Monthly export insurance declaration and recovery reconciliation
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
          Source: wFirma · Commercial Charges · Shipment Authority
        </div>
      </div>

      {/* Period selector */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8,
        padding: '10px 12px', borderRadius: 8, marginBottom: 14,
        background: 'var(--surface-2, var(--surface))', border: '1px solid var(--border)',
      }}>
        <select
          data-testid="ins-export-period-mode"
          value={periodMode}
          onChange={e => setPeriodMode(e.target.value)}
          style={inputStyle}
        >
          <option value="monthly">Monthly</option>
          <option value="custom">Custom range</option>
        </select>

        {periodMode === 'monthly' ? (
          <React.Fragment>
            <select
              data-testid="ins-export-year"
              value={year}
              onChange={e => applyMonthly(Number(e.target.value), month)}
              style={inputStyle}
            >
              {yearOptions.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
            <select
              data-testid="ins-export-month"
              value={month}
              onChange={e => applyMonthly(year, Number(e.target.value))}
              style={inputStyle}
            >
              <option value={0}>All year</option>
              {INS_MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
            <button data-testid="ins-export-prev" onClick={() => stepMonth(-1)} style={btnOutline}>‹ Prev</button>
            <button data-testid="ins-export-today" onClick={goToday} style={btnOutline}>Today</button>
            <button data-testid="ins-export-next" onClick={() => stepMonth(1)} style={btnOutline}>Next ›</button>
          </React.Fragment>
        ) : (
          <React.Fragment>
            <input
              data-testid="ins-export-from" type="date" value={customFrom}
              onChange={e => setCustomFrom(e.target.value)} style={inputStyle}
            />
            <span style={{ color: 'var(--text-3)', fontSize: 11 }}>→</span>
            <input
              data-testid="ins-export-to" type="date" value={customTo}
              onChange={e => setCustomTo(e.target.value)} style={inputStyle}
            />
            <button data-testid="ins-export-apply" onClick={applyCustom} style={btnGold}>Apply</button>
          </React.Fragment>
        )}

        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 10.5, color: 'var(--text-3)' }}>
          {period.from} → {period.to}
        </span>
        <button
          data-testid="ins-export-refresh"
          onClick={() => loadReport(period, true)}
          style={btnOutline}
        >↻ Refresh</button>
      </div>

      {loading && (
        <div data-testid="ins-export-loading" style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
          <span className="spinner" /> Loading insurance export report…
        </div>
      )}
      {!loading && error && (
        <div data-testid="ins-export-error" style={{
          margin: '16px 0', padding: '14px 16px', borderRadius: 8,
          background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
          color: 'var(--badge-red-text)', fontSize: 12,
        }}>{error}</div>
      )}

      {!loading && !error && report && (
        <React.Fragment>
          {/* KPI row */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
            <InsKpiTile testid="ins-export-kpi-invoices" label="Invoices" value={kpi.invoices} />
            <InsKpiTile testid="ins-export-kpi-gross" label="Gross insured INR"
              value={<InsMoney value={kpi.gross_insured_inr} />} />
            <InsKpiTile testid="ins-export-kpi-adjustments" label="Return adjustments" value={kpi.adjustments} />
            <InsKpiTile testid="ins-export-kpi-net" label="Net insured INR"
              value={<InsMoney value={kpi.net_insured_inr} />} />
            <InsKpiTile testid="ins-export-kpi-review" label="Needs review" value={kpi.needs_review} />
            {recoveredEntries.length === 0 ? (
              <InsKpiTile testid="ins-export-kpi-recovered-none" label="Insurance recovered" value="—" />
            ) : recoveredEntries.map(ccy => (
              <InsKpiTile
                key={ccy}
                testid={`ins-export-kpi-recovered-${ccy}`}
                label={`Recovered ${ccy}`}
                value={<InsMoney value={recovered[ccy]} />}
              />
            ))}
          </div>

          {/* Toolbar: filters + selection actions */}
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            {filterChip('all', 'All')}
            {filterChip('selected', 'Selected')}
            {filterChip('excluded', 'Excluded')}
            {filterChip('review', 'Needs review')}
            <div style={{ flex: 1 }} />
            <button data-testid="ins-export-select-eligible" onClick={selectAllEligible} style={btnOutline}>
              Select all eligible
            </button>
            <button data-testid="ins-export-clear" onClick={clearSelection} style={btnOutline}>
              Clear selection
            </button>
            <button data-testid="ins-export-prepare-pdf" onClick={() => setDrawerOpen(true)} style={btnGold}>
              Prepare PDF
            </button>
          </div>

          {/* Grouped table */}
          {(report.contractors || []).length === 0 ? (
            <div data-testid="ins-export-empty" style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
              <div style={{ fontSize: 28, marginBottom: 10 }}>◎</div>
              No export invoices in this period.
            </div>
          ) : (
            <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 8 }}>
              <table data-testid="ins-export-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{ ...thStyle, textAlign: 'center', width: 34 }}>✓</th>
                    <th style={{ ...thStyle, textAlign: 'left' }}>Document</th>
                    <th style={{ ...thStyle, textAlign: 'left' }}>Date</th>
                    <th style={{ ...thStyle, textAlign: 'left' }}>Status</th>
                    <th style={thStyle}>Ccy</th>
                    <th style={thStyle}>Inv CIF</th>
                    <th style={thStyle}>+10%</th>
                    <th style={thStyle}>Sum Insured</th>
                    <th style={thStyle}>Exch Rate</th>
                    <th style={thStyle}>Sum Insured INR</th>
                    <th style={thStyle}>Recovered</th>
                  </tr>
                </thead>
                <tbody>
                  {(report.contractors || []).map(grp => {
                    const ids = groupIds(grp);
                    const totalCount = ids.docs.length + ids.adjs.length;
                    const selCount =
                      ids.docs.filter(id => selDocs.has(id)).length +
                      ids.adjs.filter(id => selAdjs.has(id)).length;
                    const allSel = totalCount > 0 && selCount === totalCount;
                    const someSel = selCount > 0 && !allSel;
                    const sub = grp.subtotals || {};
                    const groupKey = grp.contractor_id || grp.contractor_name;

                    const renderRow = (r, isAdj, nested) => {
                      if (!rowVisible(r, isAdj)) return null;
                      const checked = isAdj ? selAdjs.has(r.invoice_id) : selDocs.has(r.invoice_id);
                      const rec = r.insurance_recovered || {};
                      return (
                        <tr key={`${isAdj ? 'adj' : 'doc'}-${r.invoice_id}`}
                            style={checked ? { background: 'var(--badge-green-bg)' } : undefined}>
                          <td style={{ ...tdStyle, textAlign: 'center' }}>
                            <input
                              type="checkbox"
                              data-testid={isAdj
                                ? `ins-export-adj-check-${r.invoice_id}`
                                : `ins-export-row-check-${r.invoice_id}`}
                              checked={checked}
                              onChange={() => (isAdj ? toggleAdj(r.invoice_id) : toggleDoc(r.invoice_id))}
                            />
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'left', paddingLeft: nested ? 26 : 8 }}>
                            {nested ? <span style={{ color: 'var(--text-3)' }}>— </span> : null}
                            {r.fullnumber}
                            {r.fx_error ? (
                              <span title={r.fx_error} style={{ marginLeft: 6, color: 'var(--badge-red-text)', fontSize: 10 }}>⚠ FX</span>
                            ) : null}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'left' }}>{r.date}</td>
                          <td style={{ ...tdStyle, textAlign: 'left' }}>
                            <InsStatusChip status={r.status} label={r.status_label} />
                          </td>
                          <td style={tdStyle}>{r.currency}</td>
                          <td style={tdStyle}><InsMoney value={r.inv_cif} /></td>
                          <td style={tdStyle}><InsMoney value={r.plus_10_pct} /></td>
                          <td style={tdStyle}><InsMoney value={r.sum_insured} /></td>
                          <td style={tdStyle}>{r.fx_rate || '—'}</td>
                          <td style={tdStyle}><InsMoney value={r.sum_insured_inr} /></td>
                          <td style={tdStyle}>
                            {rec.amount && rec.amount !== '0.00'
                              ? <span><InsMoney value={rec.amount} /> {rec.currency}</span>
                              : '—'}
                          </td>
                        </tr>
                      );
                    };

                    const bodyRows = [];
                    (grp.rows || []).forEach(r => {
                      const el = renderRow(r, false, false);
                      if (el) bodyRows.push(el);
                      (r.adjustments || []).forEach(a => {
                        const ael = renderRow(a, true, true);
                        if (ael) bodyRows.push(ael);
                      });
                    });
                    (grp.unattached_adjustments || []).forEach(a => {
                      const ael = renderRow(a, true, true);
                      if (ael) bodyRows.push(ael);
                    });
                    if (bodyRows.length === 0) return null;

                    return (
                      <React.Fragment key={groupKey}>
                        <tr style={{ background: 'var(--surface-2, var(--surface))' }}>
                          <td style={{ ...tdStyle, textAlign: 'center' }}>
                            <input
                              type="checkbox"
                              data-testid={`ins-export-group-checkbox-${groupKey}`}
                              checked={allSel}
                              ref={el => { if (el) el.indeterminate = someSel; }}
                              onChange={() => toggleGroup(grp)}
                            />
                          </td>
                          <td colSpan={8} style={{ ...tdStyle, textAlign: 'left', fontWeight: 700 }}>
                            {grp.contractor_name}
                            <span style={{ color: 'var(--text-3)', fontWeight: 400, marginLeft: 8, fontSize: 10 }}>
                              {sub.documents} document{sub.documents === 1 ? '' : 's'}
                              {sub.adjustments ? ` · ${sub.adjustments} adjustment${sub.adjustments === 1 ? '' : 's'}` : ''}
                            </span>
                          </td>
                          <td style={{ ...tdStyle, fontWeight: 700 }} data-testid={`ins-export-group-subtotal-${groupKey}`}>
                            <InsMoney value={sub.sum_insured_inr} />
                          </td>
                          <td style={tdStyle} />
                        </tr>
                        {bodyRows}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Footer totals */}
          <div style={{
            display: 'flex', flexWrap: 'wrap', gap: 18, alignItems: 'center',
            marginTop: 12, padding: '12px 16px', borderRadius: 8,
            background: 'var(--surface-2, var(--surface))', border: '1px solid var(--border)',
          }}>
            <div>
              <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                Report total (fixed)
              </div>
              <div data-testid="ins-export-report-total" style={{ fontSize: 15, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                <InsMoney value={reportTotals.sum_insured_inr_grand} /> INR
              </div>
            </div>
            <div style={{ width: 1, alignSelf: 'stretch', background: 'var(--border)' }} />
            <div>
              <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                Selected for declaration ({selectedCount} row{selectedCount === 1 ? '' : 's'})
              </div>
              <div data-testid="ins-export-declaration-total" style={{ fontSize: 15, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                {previewLoading
                  ? <span><span className="spinner" /> …</span>
                  : (selectedCount === 0
                      ? '—'
                      : (declarationTotal !== null ? <span><InsMoney value={declarationTotal} /> INR</span> : '—'))}
              </div>
              {previewError ? (
                <div data-testid="ins-export-preview-error" style={{ fontSize: 10.5, color: 'var(--badge-red-text)', marginTop: 2 }}>
                  {previewError}
                </div>
              ) : null}
            </div>
            {reportTotals.rows_without_inr ? (
              <div style={{ fontSize: 10.5, color: 'var(--badge-amber-text)' }}>
                ⚠ {reportTotals.rows_without_inr} row(s) missing INR (FX unavailable) — excluded from INR totals.
              </div>
            ) : null}
          </div>
        </React.Fragment>
      )}

      {/* PDF review drawer */}
      {drawerOpen && (
        <div data-testid="ins-export-drawer" style={{
          position: 'fixed', top: 0, right: 0, bottom: 0, width: 320, zIndex: 60,
          background: 'var(--surface)', borderLeft: '1px solid var(--border)',
          boxShadow: '-8px 0 24px rgba(0,0,0,0.25)', padding: '20px 18px',
          display: 'flex', flexDirection: 'column', gap: 14,
        }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ fontSize: 14, fontWeight: 800, flex: 1 }}>Declaration PDF</div>
            <button data-testid="ins-export-drawer-close" onClick={() => setDrawerOpen(false)} style={btnOutline}>✕</button>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-2)' }}>
            Period {period.from} → {period.to}. The server re-resolves the {selectedCount} selected
            row{selectedCount === 1 ? '' : 's'} from canonical authority before rendering.
          </div>

          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, cursor: 'pointer' }}>
            <input
              type="checkbox" data-testid="ins-export-opt-documents"
              checked={pdfOptions.includeDocuments}
              onChange={e => setPdfOptions(o => ({ ...o, includeDocuments: e.target.checked }))}
            />
            Include documents
          </label>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, cursor: 'pointer' }}>
            <input
              type="checkbox" data-testid="ins-export-opt-adjustments"
              checked={pdfOptions.includeAdjustments}
              onChange={e => setPdfOptions(o => ({ ...o, includeAdjustments: e.target.checked }))}
            />
            Include return adjustments
          </label>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, cursor: 'pointer' }}>
            <input
              type="checkbox" data-testid="ins-export-opt-recovered"
              checked={pdfOptions.recoveredColumn}
              onChange={e => setPdfOptions(o => ({ ...o, recoveredColumn: e.target.checked }))}
            />
            Insurance Recovered column
          </label>

          {downloadError ? (
            <div data-testid="ins-export-download-error" style={{
              padding: '10px 12px', borderRadius: 6, fontSize: 11,
              background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
              color: 'var(--badge-red-text)',
            }}>{downloadError}</div>
          ) : null}

          <div style={{ flex: 1 }} />
          <button
            data-testid="ins-export-download"
            onClick={downloadPdf}
            disabled={downloading || selectedCount === 0}
            style={{
              ...btnGold, padding: '9px 12px', fontSize: 12,
              opacity: downloading || selectedCount === 0 ? 0.6 : 1,
              cursor: downloading || selectedCount === 0 ? 'not-allowed' : 'pointer',
            }}
          >
            {downloading ? 'Rendering…' : 'Download PDF'}
          </button>
          {selectedCount === 0 ? (
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', textAlign: 'center' }}>
              Select at least one row to generate the declaration.
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

window.InsuranceExportTab = InsuranceExportTab;
