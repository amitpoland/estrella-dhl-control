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

  // ──────────────────────────────────────────────────────────────────────────
  // PZ Correction V2 — operator-first workflow surface
  //
  // Authority: this module is the SINGLE renderer for the PZ Correction
  // workflow after Phase B. No other file may render correction UI.
  //
  // Layer rules:
  //   * Stateless components receive props only (proposal, lcState, callbacks)
  //   * Container handles fetching + action dispatch; phase components render
  //   * Diagnostics accordion is the only place lifecycle state names and
  //     flag names are visible — outside diagnostics, only operator language
  //   * Phase mapping is owned by PzState.correctionUiPhase (single authority)
  //
  // Test contracts:
  //   * test_correction_ui_phase_mapping — pins phase mapping
  //   * test_operator_language_gate     — pins no forbidden tokens outside details
  //   * test_single_renderer_authority  — pins zero V1 surface in static/
  // ──────────────────────────────────────────────────────────────────────────

  const { useState: _useState, useEffect: _useEffect, useRef: _useRef, useMemo: _useMemo, useCallback: _useCallback } = React;

  // ── PZCorrectionV2Badge ───────────────────────────────────────────────────
  // Maps operator-facing phase to a Badge label + color status token.
  function PZCorrectionV2Badge({ phase }) {
    const map = {
      'not-enabled':    { label: 'N/A',              statusToken: 'Locked'           },
      'review':         { label: 'Draft',            statusToken: 'Draft'            },
      'accepted':       { label: 'Ready',            statusToken: 'In Transit'       },
      'push-enabled':   { label: 'Ready to post',    statusToken: 'Completed'        },
      'push-disabled':  { label: 'Held',             statusToken: 'Pending'          },
      'working':        { label: 'Working',          statusToken: 'Processing'       },
      'done':           { label: 'Done',             statusToken: 'Completed'        },
      'needs-attention':{ label: 'Needs attention',  statusToken: 'Pending'          },
      'closed':         { label: 'Closed',           statusToken: 'Locked'           },
    };
    const m = map[phase] || { label: 'Loading…', statusToken: 'Pending' };
    return React.createElement(S().Badge, { status: m.statusToken, label: m.label, 'data-testid': `pz-correction-v2-badge-${phase}` });
  }

  // ── PZCorrectionV2Diagnostics (collapsed by default) ──────────────────────
  // The ONLY place engineer-facing tokens are permitted to render.
  // Operator-language gate G3 sees forbidden tokens here and ignores them
  // because they appear inside <details data-testid="pz-correction-v2-diagnostics">.
  function PZCorrectionV2Diagnostics({ proposal, lcState, lifecycleEnabled, pushDisabledDetected, idempotencyKey }) {
    return (
      <details data-testid="pz-correction-v2-diagnostics" style={{ marginTop: 14, fontSize: 11, color: 'var(--text-2)' }}>
        <summary style={{ cursor: 'pointer', fontSize: 11, fontWeight: 600, color: 'var(--text-2)', padding: '4px 0' }}>
          Diagnostics
        </summary>
        <div style={{ padding: '8px 0', fontFamily: 'monospace', fontSize: 10, lineHeight: 1.6 }}>
          <div>Workflow state:           <strong>{lcState?.state || '(none)'}</strong></div>
          <div>Workflow option:          <strong>{lcState?.staged_option_id || '(none)'}</strong></div>
          <div>Recommended:              <strong>{proposal?.recommended_option || '(unknown)'}</strong></div>
          <div>Current PZ lines:         <strong>{proposal?.current_pz_line_count ?? '—'}</strong></div>
          <div>Authority rows:           <strong>{proposal?.authority_row_count ?? '—'}</strong></div>
          <div>Lineage links:            <strong>{proposal?.lineage_link_count ?? '—'}</strong></div>
          <div>Lifecycle flag:           <strong>{String(lifecycleEnabled)}</strong></div>
          <div>Push disabled detected:   <strong>{String(!!pushDisabledDetected)}</strong></div>
          <div>Idempotency key:          <strong>{idempotencyKey || '(not yet generated)'}</strong></div>
          <div>Last review_ts:           <strong>{lcState?.review_ts || '—'}</strong></div>
          <div>Last stage_ts:            <strong>{lcState?.stage_ts || '—'}</strong></div>
          <div>Last execute_ts:          <strong>{lcState?.execute_ts || '—'}</strong></div>
          <div>Last complete_ts:         <strong>{lcState?.complete_ts || '—'}</strong></div>
          <div style={{ marginTop: 6 }}>Endpoints in use:</div>
          <div>&nbsp;&nbsp;GET&nbsp; correction-proposal</div>
          <div>&nbsp;&nbsp;GET&nbsp; correction-state</div>
          <div>&nbsp;&nbsp;POST correction-stage / DELETE correction-stage</div>
          <div>&nbsp;&nbsp;POST correction-commit</div>
          <div>&nbsp;&nbsp;POST correction-suppress</div>
        </div>
      </details>
    );
  }

  // ── PZCorrectionV2NotEnabled ──────────────────────────────────────────────
  function PZCorrectionV2NotEnabled() {
    return (
      <div data-testid="pz-correction-v2-not-enabled" style={{ padding: '16px 4px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
          PZ Correction is not available on this environment.
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.5 }}>
          Contact your administrator if you expected this workflow to be available here.
        </div>
      </div>
    );
  }

  // ── PZCorrectionV2Review ──────────────────────────────────────────────────
  // Presents the recommendation + alternative options inline.
  // Operator chooses one option → onChoose(optionId, reason) fires.
  function PZCorrectionV2Review({ proposal, onChoose, onClose, busy }) {
    const rec = proposal.recommended_option || 'KEEP_CURRENT';
    const options = (proposal.options || []).filter(o => o.option_id !== 'CANCEL_AND_RECREATE');
    const [picked, setPicked] = _useState(null);
    const [reason, setReason] = _useState('');
    const labelFor = (opt) => {
      if (opt.option_id === 'KEEP_CURRENT')         return 'Keep current structure';
      if (opt.option_id === 'ALIGN_TO_AUTHORITY')   return 'Align prices to authority';
      if (opt.option_id === 'SPLIT_TO_STYLE_LEVEL') return 'Split to style level';
      if (opt.option_id === 'NO_ACTION')            return 'Close (no action)';
      return opt.label || opt.option_id;
    };
    const recOpt = options.find(o => o.option_id === rec) || options[0];
    return (
      <div data-testid="pz-correction-v2-review" style={{ padding: '4px 0' }}>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>Recommendation</div>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }} data-testid="pz-correction-v2-rec-label">
          {recOpt ? labelFor(recOpt) : '(no recommendation available)'}
        </div>
        {recOpt && recOpt.description && (
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 10, lineHeight: 1.5 }} data-testid="pz-correction-v2-rec-why">
            {recOpt.description}
          </div>
        )}
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 12 }} data-testid="pz-correction-v2-rec-safety">
          Validated against {proposal.lineage_link_count} lineage links and {proposal.authority_row_count} authority rows.
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
          {options.map(opt => (
            <label key={opt.option_id} data-testid={`pz-correction-v2-option-${opt.option_id}`}
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 10px',
                border: `1px solid ${picked === opt.option_id ? 'var(--accent)' : 'var(--border-subtle)'}`,
                background: picked === opt.option_id ? 'var(--bg-subtle)' : 'transparent',
                borderRadius: 6, cursor: 'pointer', fontSize: 12,
              }}>
              <input type="radio" name="pz-correction-v2-option" value={opt.option_id}
                checked={picked === opt.option_id}
                onChange={() => setPicked(opt.option_id)}
                data-testid={`pz-correction-v2-option-radio-${opt.option_id}`}
                style={{ marginTop: 2 }} />
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600 }}>{labelFor(opt)}{opt.option_id === rec && <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--accent)' }}>· Recommended</span>}</div>
                {opt.description && <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>{opt.description}</div>}
              </div>
            </label>
          ))}
        </div>
        {picked && (
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 4 }}>
              Reason for your choice (required)
            </label>
            <textarea value={reason} onChange={e => setReason(e.target.value)} rows={2}
              data-testid="pz-correction-v2-reason-input"
              placeholder="Brief explanation for the audit trail."
              style={{ width: '100%', resize: 'vertical', fontSize: 12, padding: '6px 8px',
                       border: '1px solid var(--border)', borderRadius: 4,
                       fontFamily: 'inherit', color: 'var(--text)', background: 'var(--bg-subtle)' }} />
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="primary" small disabled={busy || !picked || !reason.trim()}
            onClick={() => onChoose(picked, reason.trim())}
            data-testid="pz-correction-v2-choose-btn">
            {busy === 'choose' ? '…' : 'Record decision'}
          </Btn>
          <Btn variant="outline" small disabled={busy} onClick={onClose}
            data-testid="pz-correction-v2-close-btn">
            Close workflow
          </Btn>
        </div>
      </div>
    );
  }

  // ── PZCorrectionV2Accepted ────────────────────────────────────────────────
  // Decision recorded; operator may finalize (stage for posting) or change.
  function PZCorrectionV2Accepted({ lcState, onFinalize, onChange, busy }) {
    return (
      <div data-testid="pz-correction-v2-accepted" style={{ padding: '4px 0' }}>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>Your decision</div>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }} data-testid="pz-correction-v2-decision-label">
          {humanOption(lcState?.staged_option_id) || 'Decision pending'}
        </div>
        {lcState?.review_ts && (
          <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 10 }}>
            Recorded · {fmtTs(lcState.review_ts)}
          </div>
        )}
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 12, lineHeight: 1.5 }}>
          Next: finalize to prepare this decision for posting to wFirma. Posting itself is gated by company policy.
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="primary" small disabled={busy} onClick={onFinalize}
            data-testid="pz-correction-v2-finalize-btn">
            {busy === 'finalize' ? '…' : 'Finalize decision'}
          </Btn>
          <Btn variant="outline" small disabled={busy} onClick={onChange}
            data-testid="pz-correction-v2-change-btn">
            Change decision
          </Btn>
        </div>
      </div>
    );
  }

  // ── PZCorrectionV2PushDisabled ────────────────────────────────────────────
  // Decision held; posting unavailable by policy. AMBER not RED (Lesson I + brief §6.4).
  function PZCorrectionV2PushDisabled({ lcState, onChange, onClose, busy }) {
    return (
      <div data-testid="pz-correction-v2-push-disabled" style={{ padding: '4px 0' }}>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>Decision finalized</div>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>
          {humanOption(lcState?.staged_option_id)}
        </div>
        <div data-testid="pz-correction-v2-push-disabled-banner" style={{
          padding: '10px 12px', borderRadius: 6, marginBottom: 12,
          background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)',
          color: 'var(--badge-amber-text)', fontSize: 12, lineHeight: 1.5,
        }}>
          <strong>External posting unavailable.</strong>
          {' '}Your decision is held safely and will post when posting is re-enabled by the administrator.
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="outline" small disabled={busy} onClick={onChange}
            data-testid="pz-correction-v2-pd-change-btn">
            Change decision
          </Btn>
          <Btn variant="ghost" small disabled={busy} onClick={onClose}
            data-testid="pz-correction-v2-pd-close-btn">
            Close without posting
          </Btn>
        </div>
      </div>
    );
  }

  // ── PZCorrectionV2PushEnabled ─────────────────────────────────────────────
  // Final commit step. Sentinel + idempotency key sent verbatim.
  function PZCorrectionV2PushEnabled({ lcState, idempotencyKey, onCommit, onChange, onCancel, busy }) {
    const [reason, setReason] = _useState('');
    const [acknowledged, setAcknowledged] = _useState(false);
    const canCommit = !busy && reason.trim().length >= 10 && acknowledged;
    return (
      <div data-testid="pz-correction-v2-push-enabled" style={{ padding: '4px 0' }}>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>Decision finalized</div>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>
          {humanOption(lcState?.staged_option_id)}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 14, lineHeight: 1.5 }}>
          Ready to create the corrected document in wFirma. This creates a new accounting document and cannot be undone without manual wFirma intervention.
        </div>
        <div style={{ padding: 12, background: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)', borderRadius: 6, marginBottom: 12 }}>
          <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 4 }}>
            Reason for correction (required, 10+ chars)
          </label>
          <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3}
            data-testid="pz-correction-v2-commit-reason-input"
            style={{ width: '100%', resize: 'vertical', fontSize: 12, padding: '6px 8px',
                     border: '1px solid var(--border)', borderRadius: 4,
                     fontFamily: 'inherit', color: 'var(--text)', background: 'var(--card)' }} />
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: 6, marginTop: 8, fontSize: 11, cursor: 'pointer' }}>
            <input type="checkbox" checked={acknowledged} onChange={e => setAcknowledged(e.target.checked)}
              data-testid="pz-correction-v2-commit-ack-checkbox"
              style={{ marginTop: 1 }} />
            <span>I understand this creates a new accounting document.</span>
          </label>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="primary" small disabled={!canCommit} onClick={() => onCommit(reason.trim())}
            data-testid="pz-correction-v2-commit-btn">
            {busy === 'commit' ? '…' : 'Create document'}
          </Btn>
          <Btn variant="outline" small disabled={busy} onClick={onChange}
            data-testid="pz-correction-v2-pe-change-btn">
            Change decision
          </Btn>
          <Btn variant="ghost" small disabled={busy} onClick={onCancel}
            data-testid="pz-correction-v2-pe-cancel-btn">
            Cancel
          </Btn>
        </div>
      </div>
    );
  }

  // ── PZCorrectionV2Working ─────────────────────────────────────────────────
  function PZCorrectionV2Working({ lcState, pollCount, atCap, onManualRefresh }) {
    return (
      <div data-testid="pz-correction-v2-working" style={{ padding: '4px 0' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Creating document — please wait…
        </div>
        {!atCap && (
          <div style={{ fontSize: 11, color: 'var(--text-3)' }} data-testid="pz-correction-v2-working-polls">
            Checking status… ({pollCount})
          </div>
        )}
        {atCap && (
          <div data-testid="pz-correction-v2-working-cap" style={{
            padding: '10px 12px', borderRadius: 6,
            background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)',
            color: 'var(--badge-amber-text)', fontSize: 12, marginTop: 8,
          }}>
            Still working — refresh manually to check progress.
            <div style={{ marginTop: 8 }}>
              <Btn variant="outline" small onClick={onManualRefresh}
                data-testid="pz-correction-v2-working-refresh-btn">
                Refresh now
              </Btn>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── PZCorrectionV2Done ────────────────────────────────────────────────────
  function PZCorrectionV2Done({ lcState }) {
    return (
      <div data-testid="pz-correction-v2-done" style={{ padding: '4px 0' }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8, color: 'var(--badge-green-text)' }}>
          Corrected document created.
        </div>
        {lcState?.result_summary && (
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }} data-testid="pz-correction-v2-done-summary">
            {lcState.result_summary}
          </div>
        )}
        {lcState?.complete_ts && (
          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
            Completed · {fmtTs(lcState.complete_ts)}
          </div>
        )}
      </div>
    );
  }

  // ── PZCorrectionV2NeedsAttention ──────────────────────────────────────────
  // Amber, not red. Operator's decision is preserved.
  function PZCorrectionV2NeedsAttention({ lcState, onRetry, onChange, onClose, busy }) {
    return (
      <div data-testid="pz-correction-v2-needs-attention" style={{ padding: '4px 0' }}>
        <div data-testid="pz-correction-v2-needs-attention-banner" style={{
          padding: '10px 12px', borderRadius: 6, marginBottom: 12,
          background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)',
          color: 'var(--badge-amber-text)', fontSize: 12, lineHeight: 1.5,
        }}>
          <strong>External posting did not complete.</strong>
          {' '}Your decision is preserved. You can retry, change your decision, or close the workflow.
        </div>
        {lcState?.result_summary && (
          <details style={{ marginBottom: 12, fontSize: 11, color: 'var(--text-2)' }}>
            <summary style={{ cursor: 'pointer' }}>Technical detail</summary>
            <div style={{ marginTop: 6, fontFamily: 'monospace', fontSize: 10 }}>{lcState.result_summary}</div>
          </details>
        )}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="primary" small disabled={busy} onClick={onRetry}
            data-testid="pz-correction-v2-retry-btn">
            {busy === 'retry' ? '…' : 'Retry'}
          </Btn>
          <Btn variant="outline" small disabled={busy} onClick={onChange}
            data-testid="pz-correction-v2-na-change-btn">
            Change decision
          </Btn>
          <Btn variant="ghost" small disabled={busy} onClick={onClose}
            data-testid="pz-correction-v2-na-close-btn">
            Close workflow
          </Btn>
        </div>
      </div>
    );
  }

  // ── PZCorrectionV2Closed ──────────────────────────────────────────────────
  function PZCorrectionV2Closed({ lcState }) {
    return (
      <div data-testid="pz-correction-v2-closed" style={{ padding: '4px 0' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Workflow closed.
        </div>
        {lcState?.suppression_reason && (
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6, lineHeight: 1.5 }}
            data-testid="pz-correction-v2-closed-reason">
            Reason: {lcState.suppression_reason}
          </div>
        )}
      </div>
    );
  }

  // ── PZCorrectionV2Container ───────────────────────────────────────────────
  // Owns: data fetching, polling cleanup, idempotency key lifecycle, action
  // dispatch, push-disabled detection. Stateless phase components below.
  function PZCorrectionV2Container({ batchId }) {
    const { proposal, lcState, lifecycleEnabled, loading, error, reload } = window.PzState.useCorrectionData(batchId);
    const [busy, setBusy] = _useState(null);
    const [toast, setToast] = _useState(null);
    const [pushDisabledDetected, setPushDisabledDetected] = _useState(false);
    const [idempotencyKey, setIdempotencyKey] = _useState(null);
    const [pollCount, setPollCount] = _useState(0);
    const [atCap, setAtCap] = _useState(false);
    const pollGenRef = _useRef(0);
    const pollTimerRef = _useRef(null);
    const mountedRef = _useRef(true);
    _useEffect(() => () => {
      mountedRef.current = false;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    }, []);

    const phase = window.PzState.correctionUiPhase({ proposal, lcState, lifecycleEnabled, pushDisabledDetected });

    // Generate / refresh idempotency key when entering push-enabled phase
    // with a fresh (batch_id, staged_option_id, stage_ts) tuple.
    _useEffect(() => {
      let cancelled = false;
      if (phase === 'push-enabled' && lcState && lcState.staged_option_id) {
        const ts = lcState.stage_ts || lcState.review_ts || '';
        window.PzApi.buildCommitIdempotencyKey(batchId, lcState.staged_option_id, ts).then(k => {
          if (!cancelled) setIdempotencyKey(k);
        });
      } else if (phase !== 'push-enabled' && phase !== 'push-disabled' && phase !== 'working') {
        setIdempotencyKey(null);
      }
      return () => { cancelled = true; };
    }, [phase, lcState?.staged_option_id, lcState?.stage_ts, batchId]);

    // Polling while in working phase. 3s cadence, hard cap at 60 attempts.
    _useEffect(() => {
      if (phase !== 'working') {
        if (pollTimerRef.current) { clearTimeout(pollTimerRef.current); pollTimerRef.current = null; }
        setPollCount(0); setAtCap(false);
        return;
      }
      const myGen = ++pollGenRef.current;
      let attempts = 0;
      const tick = async () => {
        if (!mountedRef.current || myGen !== pollGenRef.current) return;
        attempts += 1;
        if (attempts > 60) { setAtCap(true); return; }
        setPollCount(attempts);
        await reload();
        if (!mountedRef.current || myGen !== pollGenRef.current) return;
        pollTimerRef.current = setTimeout(tick, 3000);
      };
      pollTimerRef.current = setTimeout(tick, 3000);
      return () => {
        if (pollTimerRef.current) { clearTimeout(pollTimerRef.current); pollTimerRef.current = null; }
      };
    }, [phase, reload]);

    const showToast = (msg, type = 'info') => {
      setToast({ msg, type });
      setTimeout(() => { if (mountedRef.current) setToast(null); }, 3500);
    };

    // Action: record decision (POSTs correction-stage with chosen option)
    const handleChoose = async (optionId, reasonText) => {
      setBusy('choose');
      pollGenRef.current += 1; // invalidate any in-flight poll
      const res = await window.PzApi.postCorrectionStage(batchId, {
        option_id: optionId,
        operator_reason: reasonText,
      });
      setBusy(null);
      if (res.ok) { showToast('Decision recorded.', 'success'); reload(); }
      else        { showToast(res.error || 'Decision could not be recorded.', 'error'); }
    };

    // Finalize (alias for reload — STAGED already happened at choose) / retry (alias).
    const _reloadAction = async (label) => { setBusy(label); pollGenRef.current += 1; await reload(); setBusy(null); };
    const handleFinalize = () => _reloadAction('finalize');
    const handleRetry    = () => _reloadAction('retry');

    // Change decision (DELETE correction-stage → returns to OPERATOR_REVIEWED)
    const handleChange = async () => {
      setBusy('change'); pollGenRef.current += 1;
      setPushDisabledDetected(false); setIdempotencyKey(null);
      const res = await window.PzApi.deleteCorrectionStage(batchId);
      setBusy(null);
      if (res.ok) { showToast('Decision reset.', 'info'); reload(); }
      else        { showToast(res.error || 'Reset failed.', 'error'); }
    };

    // Action: commit (POST correction-commit with sentinel + idempotency key)
    const handleCommit = async (reasonText) => {
      if (!idempotencyKey) { showToast('Please wait — preparing.', 'info'); return; }
      setBusy('commit');
      pollGenRef.current += 1;
      const res = await window.PzApi.postCorrectionCommit(batchId, {
        operator_reason:       reasonText,
        idempotency_key:       idempotencyKey,
        confirm_understanding: window.PzApi._CONFIRM_SENTINEL,
      });
      setBusy(null);
      if (res.ok) { showToast('Document created.', 'success'); reload(); }
      else if (res.status === 503) {
        setPushDisabledDetected(true);
        showToast('Posting unavailable. Decision held.', 'warn');
      } else {
        showToast(res.error || 'Posting did not complete.', 'error');
      }
    };

    // Close workflow (POST correction-suppress)
    const handleClose = async () => {
      const reasonText = (window.prompt('Reason for closing this workflow?', '') || '').trim();
      if (!reasonText) return;
      setBusy('close');
      pollGenRef.current += 1;
      const res = await window.PzApi.postCorrectionSuppress(batchId, { reason: reasonText });
      setBusy(null);
      if (res.ok) { showToast('Workflow closed.', 'info'); reload(); }
      else        { showToast(res.error || 'Close failed.', 'error'); }
    };

    if (loading) return <div data-testid="pz-correction-v2-loading" style={{ padding: 16, fontSize: 12, color: 'var(--text-3)' }}><span className="spinner" /> Loading…</div>;
    if (error)   return <div data-testid="pz-correction-v2-error"   style={{ padding: 16, fontSize: 12, color: 'var(--badge-amber-text)' }}>Could not load workflow. <Btn variant="ghost" small onClick={reload}>Retry</Btn></div>;
    if (phase === null) return <div data-testid="pz-correction-v2-not-applicable" style={{ padding: 16, fontSize: 12, color: 'var(--text-3)' }}>This batch does not have a correction workflow.</div>;

    return (
      <div data-testid="pz-correction-v2-container">
        {toast && React.createElement(S().Toast, { msg: toast.msg, type: toast.type })}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>PZ Correction</div>
          <PZCorrectionV2Badge phase={phase} />
        </div>
        {phase === 'not-enabled'    && <PZCorrectionV2NotEnabled />}
        {phase === 'review'         && <PZCorrectionV2Review proposal={proposal} onChoose={handleChoose} onClose={handleClose} busy={busy} />}
        {phase === 'accepted'       && <PZCorrectionV2Accepted lcState={lcState} onFinalize={handleFinalize} onChange={handleChange} busy={busy} />}
        {phase === 'push-disabled'  && <PZCorrectionV2PushDisabled lcState={lcState} onChange={handleChange} onClose={handleClose} busy={busy} />}
        {phase === 'push-enabled'   && <PZCorrectionV2PushEnabled lcState={lcState} idempotencyKey={idempotencyKey} onCommit={handleCommit} onChange={handleChange} onCancel={handleClose} busy={busy} />}
        {phase === 'working'        && <PZCorrectionV2Working lcState={lcState} pollCount={pollCount} atCap={atCap} onManualRefresh={reload} />}
        {phase === 'done'           && <PZCorrectionV2Done lcState={lcState} />}
        {phase === 'needs-attention'&& <PZCorrectionV2NeedsAttention lcState={lcState} onRetry={handleRetry} onChange={handleChange} onClose={handleClose} busy={busy} />}
        {phase === 'closed'         && <PZCorrectionV2Closed lcState={lcState} />}
        <PZCorrectionV2Diagnostics proposal={proposal} lcState={lcState} lifecycleEnabled={lifecycleEnabled}
          pushDisabledDetected={pushDisabledDetected} idempotencyKey={idempotencyKey} />
      </div>
    );
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function humanOption(optionId) {
    if (!optionId) return '';
    if (optionId === 'KEEP_CURRENT')         return 'Keep current structure';
    if (optionId === 'ALIGN_TO_AUTHORITY')   return 'Align prices to authority';
    if (optionId === 'SPLIT_TO_STYLE_LEVEL') return 'Split to style level';
    if (optionId === 'NO_ACTION')            return 'Close (no action)';
    return optionId;
  }
  function fmtTs(iso) {
    if (!iso) return '';
    return String(iso).slice(0, 16).replace('T', ' ');
  }

  // ── Export ────────────────────────────────────────────────────────────────
  window.PzComponents = Object.freeze({
    DraftStateChip,
    ProformaReadinessGate,
    DevBypassBanner,
    DraftLineRow,
    CustomerAuthorityCard,
    ProductAuthorityRow,
    // PZ Correction V2 — single rendering authority for correction workflow.
    PZCorrectionV2Container,
    PZCorrectionV2NotEnabled,
    PZCorrectionV2Review,
    PZCorrectionV2Accepted,
    PZCorrectionV2PushDisabled,
    PZCorrectionV2PushEnabled,
    PZCorrectionV2Working,
    PZCorrectionV2Done,
    PZCorrectionV2NeedsAttention,
    PZCorrectionV2Closed,
    PZCorrectionV2Diagnostics,
    PZCorrectionV2Badge,
  });
})();
