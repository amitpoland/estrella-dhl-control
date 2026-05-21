// pz-components.js — Domain rendering primitives for V2 pages.
//
// Exposes window.PzComponents. Stateless by default; local UI state
// only where needed (inline editing, confirmation visibility).
//
// Loaded by V2 pages as:
//   <script type="text/babel" data-presets="env,react" src="/dashboard/pz-components.js"></script>
// MUST load AFTER dashboard-shared.js (uses EstrellaShared atoms).
//
// Layer rules (see docs/v2-architecture-plan.md §4):
//   ALLOWED:  domain-aware rendering primitives, onSave/onAction callbacks
//   FORBIDDEN: data fetching, workflow decisions, multi-domain logic,
//              computing ready/blocked from local state

(function () {
  'use strict';

  const { useState } = React;

  // Lazy accessors — EstrellaShared is set when dashboard-shared.js IIFE runs,
  // which precedes this script in document order.
  const S = () => window.EstrellaShared;
  const Badge       = (p) => React.createElement(S().Badge,        p);
  const Btn         = (p) => React.createElement(S().Btn,          p);
  const GateBlock   = (p) => React.createElement(S().GateBlock,    p);
  const StatusDot   = (p) => React.createElement(S().StatusDot,    p);
  const SectionHeader = (p) => React.createElement(S().SectionHeader, p);

  // ── DRAFT_STATE_MAP ───────────────────────────────────────────────────────
  // Mapping from draft_state → display label + Badge status token.
  // Badge.status must be a token in STATUS_MAP (dashboard-shared.js).
  const DRAFT_STATE_MAP = {
    pending_local: { label: 'Draft',       statusToken: 'Draft'             },
    draft:         { label: 'Draft',       statusToken: 'Draft'             },
    approved:      { label: 'Approved',    statusToken: 'Completed'         },
    cancelled:     { label: 'Cancelled',   statusToken: 'Action Required'   },
    failed:        { label: 'Failed',      statusToken: 'Action Required'   },
    post_failed:   { label: 'Post Failed', statusToken: 'Action Required'   },
    issued:        { label: 'Issued',      statusToken: 'Completed'         },
    posted:        { label: 'Posted',      statusToken: 'Completed'         },
  };

  // ── DraftStateChip ────────────────────────────────────────────────────────
  function DraftStateChip({ state }) {
    const m = DRAFT_STATE_MAP[state] || { label: state || 'Unknown', statusToken: 'Draft' };
    return React.createElement(S().Badge, { status: m.statusToken, label: m.label, 'data-testid': 'draft-state-chip' });
  }

  // ── ProformaReadinessGate ─────────────────────────────────────────────────
  // Renders readiness from backend preview object.
  // Does NOT compute ready locally — that is forbidden.
  // preview.ready, preview.blocking_reasons, preview.export_blockers are backend truth.
  function ProformaReadinessGate({ preview, onReload }) {
    if (!preview) return null;

    const { ready, blocking_reasons = [], export_blockers = [], warehouse_blockers = [] } = preview;

    if (ready) {
      return (
        <div data-testid="readiness-gate-ready" style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 12px',
          background: 'var(--badge-green-bg)',
          border: '1px solid var(--badge-green-border)',
          borderRadius: 6,
        }}>
          <span style={{ fontSize: 13, color: 'var(--badge-green-text)' }}>✓</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--badge-green-text)', flex: 1 }}>
            Ready to Issue
          </span>
          {onReload && (
            <Btn variant="ghost" small onClick={onReload} data-testid="readiness-refresh-btn">
              ↻
            </Btn>
          )}
        </div>
      );
    }

    return (
      <div data-testid="readiness-gate-blocked">
        {blocking_reasons.length > 0 && (
          <GateBlock
            variant="error"
            title="Blocked — cannot issue proforma"
            reasons={blocking_reasons}
          />
        )}
        {export_blockers.length > 0 && (
          <GateBlock
            variant="warn"
            title="Export warning — preview allowed, issue blocked"
            reasons={export_blockers}
          />
        )}
        {warehouse_blockers.length > 0 && (
          <GateBlock
            variant="warn"
            title="Warehouse blockers"
            reasons={warehouse_blockers}
          />
        )}
        {onReload && (
          <div style={{ marginTop: 6 }}>
            <Btn variant="ghost" small onClick={onReload} data-testid="readiness-refresh-btn">
              ↻ Refresh readiness
            </Btn>
          </div>
        )}
      </div>
    );
  }

  // ── DevBypassBanner ───────────────────────────────────────────────────────
  // Shown when EJ_DEV_WORKFLOW_BYPASS is active on the backend.
  // active: boolean (comes from preview.export_blockers containing '[DEV-BYPASS]')
  function DevBypassBanner({ active }) {
    if (!active) return null;
    return (
      <div data-testid="dev-bypass-banner" style={{
        background: 'var(--badge-amber-bg)',
        border: '1px solid var(--badge-amber-border)',
        borderRadius: 6, padding: '8px 12px', marginBottom: 6,
        fontSize: 11, fontWeight: 600, color: 'var(--badge-amber-text)',
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <span>⚠️</span>
        <span>
          DEV BYPASS active — missing customer is demoted to a warning (not a hard blocker).
          wFirma issue remains blocked until customer is mapped.
        </span>
      </div>
    );
  }

  // ── DraftLineRow ──────────────────────────────────────────────────────────
  // Inline-editable row in the draft line table.
  // Calls onSave(lineId, patch, draftUpdatedAt) to save — never calls PzApi directly.
  // Calls onDelete(lineId) to delete.
  function DraftLineRow({ line, editable, draftUpdatedAt, onSave, onDelete }) {
    const lid = line.line_id;
    const [editing,   setEditing]   = useState(false);
    const [qty,       setQty]       = useState(String(line.qty ?? ''));
    const [unitPrice, setUnitPrice] = useState(String(line.unit_price ?? ''));
    const [saving,    setSaving]    = useState(false);

    const startEdit = () => {
      setQty(String(line.qty ?? ''));
      setUnitPrice(String(line.unit_price ?? ''));
      setEditing(true);
    };

    const cancelEdit = () => {
      setQty(String(line.qty ?? ''));
      setUnitPrice(String(line.unit_price ?? ''));
      setEditing(false);
    };

    const handleSave = async () => {
      setSaving(true);
      await onSave(lid, {
        qty:        parseFloat(qty)       || 0,
        unit_price: parseFloat(unitPrice) || null,
      }, draftUpdatedAt);
      setSaving(false);
      setEditing(false);
    };

    const displayValue = editing
      ? ((parseFloat(unitPrice) || 0) * (parseFloat(qty) || 0)).toFixed(2)
      : (line.line_value != null ? Number(line.line_value).toFixed(2) : null);

    const ccy = line.currency || '';
    const priceOk = line.unit_price != null && line.unit_price > 0;

    return (
      <tr data-testid={`draft-line-row-${lid}`}>
        <td style={{ padding: '6px 8px' }}>
          <StatusDot status={line.product_match ? 'ok' : 'error'} title={line.product_match ? 'Matched' : 'Not matched'} />
          {' '}<span style={{ fontSize: 11 }}>{line.product_code || '—'}</span>
        </td>
        <td style={{ padding: '6px 8px', fontSize: 11, color: 'var(--text-2)' }}>
          {line.design_no || '—'}
        </td>
        <td style={{ padding: '6px 8px', fontSize: 11 }}>
          {editing
            ? <input
                type="number" min="0" step="1"
                value={qty}
                onChange={e => setQty(e.target.value)}
                style={{ width: 56, padding: '2px 5px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 4, fontFamily: 'inherit' }}
              />
            : line.qty}
        </td>
        <td style={{ padding: '6px 8px', fontSize: 11 }}>
          {editing
            ? <input
                type="number" min="0" step="0.01"
                value={unitPrice}
                onChange={e => setUnitPrice(e.target.value)}
                style={{ width: 72, padding: '2px 5px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 4, fontFamily: 'inherit' }}
              />
            : priceOk
              ? `${line.unit_price} ${ccy}`
              : <span style={{ color: 'var(--badge-red-text)', fontWeight: 600 }}>missing</span>
          }
        </td>
        <td style={{ padding: '6px 8px', fontSize: 11 }}>
          {displayValue ? `${displayValue} ${ccy}` : '—'}
        </td>
        <td style={{ padding: '6px 8px', fontSize: 11 }}>
          <StatusDot status={line.stock_ok ? 'ok' : 'warn'} title={line.stock_status || ''} />
          {' '}<span style={{ color: 'var(--text-2)' }}>{line.stock_status || '—'}</span>
        </td>
        <td style={{ padding: '6px 4px', whiteSpace: 'nowrap' }}>
          {editable && (
            editing ? (
              <>
                <Btn variant="primary" small onClick={handleSave} disabled={saving}
                     data-testid={`save-line-${lid}`}>
                  {saving ? '…' : 'Save Line'}
                </Btn>
                <Btn variant="ghost" small onClick={cancelEdit} style={{ marginLeft: 4 }}>
                  Cancel
                </Btn>
              </>
            ) : (
              <>
                <Btn variant="outline" small onClick={startEdit}
                     data-testid={`edit-line-${lid}`}>
                  Edit
                </Btn>
                {onDelete && (
                  <Btn variant="ghost" small
                       onClick={() => onDelete(lid)}
                       style={{ marginLeft: 4, color: 'var(--badge-red-text)' }}
                       data-testid={`delete-line-${lid}`}>
                    ✕
                  </Btn>
                )}
              </>
            )
          )}
        </td>
      </tr>
    );
  }

  // ── CustomerAuthorityCard ─────────────────────────────────────────────────
  // Displays customer resolution status from draft.customer_resolution or preview.customer_resolution.
  // Read-only display — remap action is handled by the page layer.
  function CustomerAuthorityCard({ resolution, clientName }) {
    if (!resolution) {
      return (
        <div style={{ padding: '10px', fontSize: 12, color: 'var(--text-2)' }}>
          No customer resolution data.
        </div>
      );
    }

    const {
      found, ambiguous, match_strategy,
      resolved_wfirma_name, wfirma_customer_id,
      candidates = [],
    } = resolution;

    const statusDotStatus = found ? 'ok' : ambiguous ? 'warn' : 'error';

    return (
      <div data-testid="customer-authority-card" style={{ fontSize: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <StatusDot status={statusDotStatus} />
          <span style={{ fontWeight: 600 }}>{clientName || resolution.raw_input || '—'}</span>
          {found     && <Badge label="Matched"    status="Completed"       small />}
          {ambiguous && <Badge label="Ambiguous"  status="Verification Needed" small />}
          {!found && !ambiguous && <Badge label="No Mapping" status="Action Required" small />}
        </div>

        {found && (
          <div style={{ color: 'var(--text-2)', marginTop: 2, fontSize: 11 }}>
            wFirma: <strong style={{ color: 'var(--text)' }}>{resolved_wfirma_name}</strong>
            {' · '}id: {wfirma_customer_id}
            {' · '}<span style={{ opacity: 0.7 }}>via {match_strategy}</span>
          </div>
        )}
        {ambiguous && (
          <div style={{ marginTop: 4, fontSize: 11, color: 'var(--badge-amber-text)' }}>
            Multiple candidates:&nbsp;
            {candidates.map((c, i) => <strong key={i} style={{ marginRight: 6 }}>{c}</strong>)}
          </div>
        )}
        {!found && !ambiguous && (
          <div style={{ color: 'var(--badge-red-text)', marginTop: 2, fontSize: 11 }}>
            No wFirma customer match. Add via Customer Master.
          </div>
        )}
      </div>
    );
  }

  // ── ProductAuthorityRow ───────────────────────────────────────────────────
  // Per-line product authority status (read-only).
  // Used in the ProductMappingSection to show match + stock per line.
  function ProductAuthorityRow({ line }) {
    const key = line.product_code || line.design_no || String(Math.random());
    return (
      <tr data-testid={`product-authority-row-${key}`}>
        <td style={{ padding: '5px 8px', fontSize: 11, fontFamily: 'monospace' }}>
          {line.product_code || '—'}
        </td>
        <td style={{ padding: '5px 8px', fontSize: 11, color: 'var(--text-2)' }}>
          {line.design_no || '—'}
        </td>
        <td style={{ padding: '5px 8px', fontSize: 11 }}>
          <StatusDot status={line.product_match ? 'ok' : 'error'} />
          {' '}{line.product_match ? 'Matched' : 'Not matched'}
        </td>
        <td style={{ padding: '5px 8px', fontSize: 11 }}>
          <StatusDot status={line.stock_ok ? 'ok' : 'warn'} />
          {' '}{line.stock_status || '—'}
        </td>
        <td style={{ padding: '5px 8px', fontSize: 11, color: 'var(--text-2)' }}>
          {line.price_source || '—'}
        </td>
        <td style={{ padding: '5px 8px', fontSize: 11 }}>
          {line.unit_price != null
            ? `${line.unit_price} ${line.currency || ''}`
            : <span style={{ color: 'var(--badge-red-text)' }}>missing</span>}
        </td>
      </tr>
    );
  }

  // ── Export ────────────────────────────────────────────────────────────────
  window.PzComponents = Object.freeze({
    DraftStateChip,
    ProformaReadinessGate,
    DevBypassBanner,
    DraftLineRow,
    CustomerAuthorityCard,
    ProductAuthorityRow,
  });
})();
