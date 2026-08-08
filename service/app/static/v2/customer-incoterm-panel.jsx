/**
 * Customer Master — Incoterm defaults operator workflow.
 *
 * Canonical authority: Customer Master.default_incoterm
 * Catalogue: GET /api/v1/incoterms (active ICC codes)
 * Never invents from country. Soft hints (e.g. UAB→DAP) show as REVIEW
 * evidence but are never preselected.
 *
 * Mounted inside MasterPage Clients tab — not a separate page.
 */
(function () {
  'use strict';

  const BADGE = {
    SET: { bg: 'var(--badge-ok-bg, #e8f5e9)', fg: 'var(--badge-ok-fg, #1b5e20)', label: 'SET' },
    REVIEW: { bg: 'var(--badge-warn-bg, #fff8e1)', fg: 'var(--badge-warn-fg, #e65100)', label: 'REVIEW' },
    'NO EVIDENCE': { bg: 'var(--badge-muted-bg, #f5f5f5)', fg: 'var(--badge-muted-fg, #616161)', label: 'NO EVIDENCE' },
  };

  function ClassBadge({ status }) {
    const s = BADGE[status] || BADGE['NO EVIDENCE'];
    return (
      <span data-testid={`incoterm-class-${(status || '').replace(/\s+/g, '-').toLowerCase()}`}
        style={{
          display: 'inline-block', padding: '2px 8px', borderRadius: 4,
          fontSize: 10, fontWeight: 700, letterSpacing: 0.3,
          background: s.bg, color: s.fg,
        }}>
        {s.label}
      </span>
    );
  }

  function evidenceSummary(row) {
    const bits = [];
    const hard = row.hard_codes || {};
    const hardKeys = Object.keys(hard);
    if (hardKeys.length) bits.push('hard: ' + hardKeys.map(k => `${k}×${hard[k]}`).join(', '));
    const hints = row.orphan_name_hints || [];
    if (hints.length) {
      bits.push('hint: ' + hints.map(h => `${h.hint_incoterm} (${h.client_name_fragment || 'name'})`).join('; '));
    }
    if (!bits.length) return '—';
    return bits.join(' · ');
  }

  function CustomerIncotermPanel() {
    const [rows, setRows] = React.useState([]);
    const [counts, setCounts] = React.useState({});
    const [catalogue, setCatalogue] = React.useState([]);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState(null);
    const [q, setQ] = React.useState('');
    const [country, setCountry] = React.useState('');
    const [missingOnly, setMissingOnly] = React.useState(true);
    const [classFilter, setClassFilter] = React.useState('');
    const [selected, setSelected] = React.useState(() => new Set());
    const [rowDraft, setRowDraft] = React.useState({}); // cid → chosen code (not saved)
    const [bulkCode, setBulkCode] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const [toast, setToast] = React.useState(null);

    const load = React.useCallback(() => {
      setLoading(true);
      setError(null);
      const params = { limit: '1000' };
      if (q.trim()) params.q = q.trim();
      if (country.trim()) params.country = country.trim().toUpperCase();
      if (missingOnly) params.missing_incoterm = 'true';
      if (classFilter) params.classification = classFilter;
      Promise.all([
        PzApi.listCustomerIncotermReview(params),
        PzApi.listIncoterms({ active: 'true' }),
      ]).then(([rev, cat]) => {
        if (!rev.ok) throw new Error((rev.data && rev.data.detail) || rev.error || 'review failed');
        const data = rev.data || {};
        setRows(data.customers || []);
        setCounts(data.classification_counts || {});
        setSelected(new Set());
        const codes = ((cat.data && cat.data.incoterms) || cat.data || [])
          .map(i => (i && i.code) || i)
          .filter(Boolean);
        setCatalogue(codes.length ? codes : ['EXW','FCA','CPT','CIP','DAP','DPU','DDP','FAS','FOB','CFR','CIF']);
      }).catch(e => setError(String(e.message || e))).finally(() => setLoading(false));
    }, [q, country, missingOnly, classFilter]);

    React.useEffect(() => { load(); }, [load]);

    const flash = (msg, ok) => {
      setToast({ msg, ok: !!ok });
      setTimeout(() => setToast(null), 4000);
    };

    const toggle = (cid) => {
      setSelected(prev => {
        const n = new Set(prev);
        if (n.has(cid)) n.delete(cid); else n.add(cid);
        return n;
      });
    };

    const toggleAllVisible = () => {
      if (selected.size === rows.length) setSelected(new Set());
      else setSelected(new Set(rows.map(r => r.contractor_id)));
    };

    const saveOne = async (cid) => {
      const code = (rowDraft[cid] !== undefined) ? rowDraft[cid] : '';
      setBusy(true);
      try {
        const res = await PzApi.saveCustomerMaster(cid, { default_incoterm: code || null });
        if (!res.ok) throw new Error((res.data && (res.data.detail || JSON.stringify(res.data))) || 'save failed');
        const seeded = (res.data && res.data.draft_reseed && res.data.draft_reseed.seeded_count) || 0;
        flash(`Saved ${cid} → ${code || '(unset)'}; drafts reseeded: ${seeded}`, true);
        load();
      } catch (e) {
        flash(String(e.message || e), false);
      } finally {
        setBusy(false);
      }
    };

    const saveBulk = async () => {
      if (!selected.size) {
        flash('Select at least one customer', false);
        return;
      }
      if (!bulkCode) {
        flash('Choose one Incoterm for bulk assignment', false);
        return;
      }
      const ok = window.confirm(
        `Assign ${bulkCode} to ${selected.size} selected customer(s)?\n\n` +
        `This writes Customer Master.default_incoterm and reseeds blank editable drafts only.\n` +
        `Posted/converted drafts are never changed.`
      );
      if (!ok) return;
      setBusy(true);
      try {
        const res = await PzApi.bulkAssignCustomerIncoterm({
          contractor_ids: Array.from(selected),
          default_incoterm: bulkCode,
          confirm: true,
        });
        if (!res.ok) throw new Error((res.data && (res.data.detail || JSON.stringify(res.data))) || 'bulk failed');
        const seeded = (res.data && res.data.draft_reseed && res.data.draft_reseed.seeded_count) || 0;
        const changed = ((res.data && res.data.updated) || []).filter(u => u.changed).length;
        flash(`Bulk OK: ${changed} updated; drafts reseeded: ${seeded}`, true);
        load();
      } catch (e) {
        flash(String(e.message || e), false);
      } finally {
        setBusy(false);
      }
    };

    const codeOptions = (
      <>
        <option value="">— unset —</option>
        {catalogue.map(c => <option key={c} value={c}>{c}</option>)}
      </>
    );

    return (
      <div data-testid="cm-incoterm-panel" style={{
        marginTop: 16, padding: 14, border: '1px solid var(--border)',
        borderRadius: 8, background: 'var(--bg)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}
              data-testid="cm-incoterm-panel-title">
              Incoterm defaults
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
              Customer Master is the canonical default. Editable drafts may keep an explicit override.
              Never inferred from country.
            </div>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-2)' }} data-testid="cm-incoterm-counts">
            REVIEW {counts.REVIEW || 0} · NO EVIDENCE {counts['NO EVIDENCE'] || 0} · SET {counts.SET || 0} · shown {rows.length}
          </div>
        </div>

        <div data-testid="cm-incoterm-filters" style={{
          display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12, alignItems: 'center',
        }}>
          <input data-testid="cm-incoterm-filter-q" type="search"
            placeholder="Search name / NIP / contractor ID"
            value={q} onChange={e => setQ(e.target.value)}
            style={{ minWidth: 220, padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--text)' }} />
          <input data-testid="cm-incoterm-filter-country" type="text" maxLength={2}
            placeholder="Country"
            value={country} onChange={e => setCountry(e.target.value.toUpperCase())}
            style={{ width: 72, padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--text)' }} />
          <select data-testid="cm-incoterm-filter-class" value={classFilter}
            onChange={e => setClassFilter(e.target.value)}
            style={{ padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--text)' }}>
            <option value="">All classifications</option>
            <option value="REVIEW">REVIEW</option>
            <option value="NO EVIDENCE">NO EVIDENCE</option>
            <option value="SET">SET</option>
          </select>
          <label style={{ fontSize: 12, color: 'var(--text-2)', display: 'flex', gap: 6, alignItems: 'center' }}>
            <input data-testid="cm-incoterm-filter-missing" type="checkbox"
              checked={missingOnly} onChange={e => setMissingOnly(e.target.checked)} />
            Missing Incoterm only
          </label>
          <button type="button" data-testid="cm-incoterm-refresh" onClick={load} disabled={loading || busy}
            style={{ padding: '6px 12px', fontSize: 12, fontWeight: 600, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg-subtle)', color: 'var(--text)', cursor: 'pointer' }}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>

        <div data-testid="cm-incoterm-bulk-bar" style={{
          display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10, alignItems: 'center',
          padding: '8px 10px', background: 'var(--bg-subtle)', borderRadius: 6,
        }}>
          <span style={{ fontSize: 12, color: 'var(--text-2)' }}>{selected.size} selected</span>
          <select data-testid="cm-incoterm-bulk-code" value={bulkCode}
            onChange={e => setBulkCode(e.target.value)}
            style={{ padding: '5px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--text)' }}>
            <option value="">Bulk Incoterm…</option>
            {catalogue.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <button type="button" data-testid="cm-incoterm-bulk-apply"
            disabled={busy || !selected.size || !bulkCode}
            onClick={saveBulk}
            style={{
              padding: '6px 12px', fontSize: 12, fontWeight: 700, border: 'none', borderRadius: 6,
              background: (!selected.size || !bulkCode) ? 'var(--border)' : 'var(--accent)',
              color: '#fff', cursor: (!selected.size || !bulkCode) ? 'not-allowed' : 'pointer',
            }}>
            Assign to selected…
          </button>
          <span style={{ fontSize: 10, color: 'var(--text-3)' }}>
            Requires confirm dialog · reseeds blank editable drafts only
          </span>
        </div>

        {toast && (
          <div data-testid="cm-incoterm-toast" style={{
            marginTop: 8, padding: '6px 10px', borderRadius: 6, fontSize: 12,
            background: toast.ok ? 'var(--badge-ok-bg, #e8f5e9)' : 'var(--badge-err-bg, #ffebee)',
            color: toast.ok ? 'var(--badge-ok-fg, #1b5e20)' : 'var(--badge-err-fg, #b71c1c)',
          }}>{toast.msg}</div>
        )}
        {error && (
          <div data-testid="cm-incoterm-error" style={{ marginTop: 8, color: 'var(--danger, #c62828)', fontSize: 12 }}>{error}</div>
        )}

        <div style={{ marginTop: 10, overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 6 }}>
          <table data-testid="cm-incoterm-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', textAlign: 'left' }}>
                <th style={{ padding: 8, width: 28 }}>
                  <input data-testid="cm-incoterm-select-all" type="checkbox"
                    checked={rows.length > 0 && selected.size === rows.length}
                    onChange={toggleAllVisible} />
                </th>
                <th style={{ padding: 8 }}>Customer</th>
                <th style={{ padding: 8 }}>Contractor</th>
                <th style={{ padding: 8 }}>Country</th>
                <th style={{ padding: 8 }}>Class</th>
                <th style={{ padding: 8 }}>Evidence / hints</th>
                <th style={{ padding: 8 }}>Current</th>
                <th style={{ padding: 8 }}>Assign</th>
                <th style={{ padding: 8 }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && !loading && (
                <tr><td colSpan={9} style={{ padding: 16, color: 'var(--text-3)' }} data-testid="cm-incoterm-empty">
                  No customers match these filters.
                </td></tr>
              )}
              {rows.map(r => {
                const cid = r.contractor_id;
                const draftVal = rowDraft[cid] !== undefined ? rowDraft[cid] : (r.current_default || '');
                // Never preselect recommended from soft hints — only SET may suggest via placeholder text
                return (
                  <tr key={cid} data-testid={`cm-incoterm-row-${cid}`}
                    style={{ borderTop: '1px solid var(--border)' }}>
                    <td style={{ padding: 8 }}>
                      <input type="checkbox" data-testid={`cm-incoterm-check-${cid}`}
                        checked={selected.has(cid)} onChange={() => toggle(cid)} />
                    </td>
                    <td style={{ padding: 8, fontWeight: 600 }}>{r.customer_name || '—'}</td>
                    <td style={{ padding: 8, fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{cid}</td>
                    <td style={{ padding: 8 }}>{r.country || '—'}</td>
                    <td style={{ padding: 8 }}><ClassBadge status={r.classification} /></td>
                    <td style={{ padding: 8, color: 'var(--text-2)', maxWidth: 280 }}
                      data-testid={`cm-incoterm-evidence-${cid}`}
                      title={evidenceSummary(r)}>
                      {evidenceSummary(r)}
                      {r.classification === 'SET' && r.recommended_incoterm && (
                        <div style={{ fontSize: 10, color: 'var(--text-3)' }}>
                          proven: {r.recommended_incoterm} (not auto-applied)
                        </div>
                      )}
                    </td>
                    <td style={{ padding: 8, fontFamily: 'ui-monospace, monospace' }}
                      data-testid={`cm-incoterm-current-${cid}`}>
                      {r.current_default || '—'}
                    </td>
                    <td style={{ padding: 8 }}>
                      <select data-testid={`cm-incoterm-select-${cid}`}
                        value={draftVal}
                        onChange={e => setRowDraft(prev => ({ ...prev, [cid]: e.target.value }))}
                        style={{ padding: '4px 6px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', color: 'var(--text)' }}>
                        {codeOptions}
                      </select>
                    </td>
                    <td style={{ padding: 8 }}>
                      <button type="button" data-testid={`cm-incoterm-save-${cid}`}
                        disabled={busy}
                        onClick={() => saveOne(cid)}
                        style={{ padding: '4px 10px', fontSize: 11, fontWeight: 600, border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg-subtle)', color: 'var(--text)', cursor: 'pointer' }}>
                        Save
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  Object.assign(window, { CustomerIncotermPanel });
})();
