// ─────────────────────────────────────────────────────────────────────────────
// Inbox — unified action queue (Sprint 2B.3a: type + priority filter tabs).
//
// WIRED to GET /api/v1/inbox via EstrellaShared.apiFetch (ADR-028 shim).
// NOT raw fetch — EstrellaShared.apiFetch carries credentials:'include',
// D1 network-error catch, and D2 err.status on auth.
//
// Response shape (from routes_inbox.py, committed 22cffa5):
//   { ok, count, items: [{id, type, priority, title, detail, age (ISO),
//     actor, primary_action, linked_batch_id, actionable, endpoint}],
//     sources: {proposals, email_queue, dhl_cache}: {ok, count, error?} }
//
// Filter tabs pass ?type= and ?priority= as query params — server filters
// before responding (routes_inbox.py:267-270). "All" = param omitted.
// Writes (Approve/Reject) → Sprint 2B.3b.
// ─────────────────────────────────────────────────────────────────────────────

const PRIORITY_CONF = {
  urgent: { label: 'Urgent',  icon: '⚠', color: 'var(--badge-red-text)',    bg: 'var(--badge-red-bg)',    border: 'var(--badge-red-border)' },
  high:   { label: 'High',    icon: '◐', color: 'var(--badge-amber-text)',  bg: 'var(--badge-amber-bg)',  border: 'var(--badge-amber-border)' },
  normal: { label: 'Normal',  icon: '○', color: 'var(--badge-blue-text)',   bg: 'var(--badge-blue-bg)',   border: 'var(--badge-blue-border)' },
  info:   { label: 'Info',    icon: '·', color: 'var(--badge-neutral-text)',bg: 'var(--badge-neutral-bg)',border: 'var(--badge-neutral-border)' },
};

const TYPE_CONF = {
  email:       { label: 'Email',       icon: '✉', color: 'var(--badge-purple-text)' },
  proposal:    { label: 'Proposal',    icon: '✦', color: 'var(--accent)' },
  approval:    { label: 'Approval',    icon: '◉', color: 'var(--badge-blue-text)' },
  reservation: { label: 'Reservation', icon: '⊕', color: 'var(--badge-green-text)' },
  customs:     { label: 'Customs',     icon: '◐', color: 'var(--badge-red-text)' },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function _relTime(iso) {
  // Convert ISO-8601 timestamp to a human-readable relative string.
  // age field from GET /api/v1/inbox is ISO (not pre-formatted).
  if (!iso) return '—';
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1)  return 'just now';
    if (mins < 60) return mins + 'm ago';
    const hrs = Math.floor(mins / 60);
    if (hrs < 24)  return hrs + 'h ago';
    const days = Math.floor(hrs / 24);
    return days + 'd ago';
  } catch (_) {
    return (iso || '—').slice(0, 10);
  }
}

// ── InboxRow ──────────────────────────────────────────────────────────────────

function InboxRow({ item, selected, onSelect, onActed }) {
  const p = PRIORITY_CONF[item.priority] || PRIORITY_CONF.info;
  const t = TYPE_CONF[item.type]         || { label: item.type || '?', icon: '?', color: 'var(--text-3)' };

  // Write wiring (Sprint 2B.3b): Approve/Reject only for actionable proposals
  // that carry an /approve endpoint. All other types keep their read-only
  // labelled affordance (no Send control here -- OQ-4).
  var isProposalAction = item.type === 'proposal'
    && typeof item.endpoint === 'string'
    && /\/approve$/.test(item.endpoint);

  var _a0 = React.useState(false);
  var acting = _a0[0], setActing = _a0[1];     // GUARD 4: in-flight disables both buttons
  var _a1 = React.useState('');
  var actErr = _a1[0], setActErr = _a1[1];     // GUARD 3: failure surfaces here, item stays

  function doApprove(e) {
    e.stopPropagation();
    if (acting) return;                        // GUARD 4: no concurrent fire
    setActing(true); setActErr('');
    // GUARD 2: operator resolved + blank-refused inside PzApi.approveProposal
    // (attribution sent in body as approved_by). No pre-removal of the item.
    window.PzApi.approveProposal(item.endpoint).then(function(res) {
      if (res.ok) {
        onActed && onActed();                  // GUARD 3: confirmed success -> parent refetch
                                               // drops the now-non-pending proposal. acting
                                               // stays true; row unmounts on refetch.
      } else if (res.status === 409) {
        onActed && onActed();                  // 409 = already resolved; re-fetch, row leaves inbox
      } else {
        setActErr(res.error || 'Approve failed.');
        setActing(false);                      // item REMAINS visible; operator may retry
      }
    });
  }

  function doReject(e) {
    e.stopPropagation();
    if (acting) return;
    // GUARD 1: reason prompt; cancel or blank aborts BEFORE any POST.
    var reason = (window.prompt('Reason for rejecting this proposal (recorded in audit):', '') || '').trim();
    if (!reason) return;                       // GUARD 1: no POST on cancel/blank
    var rejectUrl = item.endpoint.replace(/\/approve$/, '/reject');
    setActing(true); setActErr('');
    window.PzApi.rejectProposal(rejectUrl, reason).then(function(res) {
      if (res.ok) {
        onActed && onActed();
      } else if (res.status === 409) {
        onActed && onActed();                  // 409 = already resolved; re-fetch, row leaves inbox
      } else {
        setActErr(res.error || 'Reject failed.');
        setActing(false);
      }
    });
  }

  // batch_id chip: shorten for display but keep full value for navigation
  const batchShort = item.linked_batch_id
    ? item.linked_batch_id.replace(/^SHIPMENT_(\d+)_.*/, 'SI-$1')
    : null;

  function openBatch(e) {
    e.stopPropagation();
    if (item.linked_batch_id) {
      window.location.href = '/v2/proforma?batch_id=' + encodeURIComponent(item.linked_batch_id);
    }
  }

  return (
    <div
      onClick={onSelect}
      data-testid={'inbox-row-' + item.id}
      style={{
        display: 'grid',
        gridTemplateColumns: '6px 24px 1fr auto',
        gap: 12, alignItems: 'center',
        padding: '14px 24px',
        borderBottom: '1px solid var(--border-subtle)',
        cursor: 'pointer',
        background: selected ? 'var(--accent-subtle)' : 'transparent',
        borderLeft: selected ? '3px solid var(--accent)' : '3px solid transparent',
        transition: 'background 0.12s',
      }}
      onMouseEnter={function(e) { if (!selected) e.currentTarget.style.background = 'var(--bg-subtle)'; }}
      onMouseLeave={function(e) { if (!selected) e.currentTarget.style.background = 'transparent'; }}
    >
      {/* Priority dot */}
      <div style={{ width: 6, height: 6, borderRadius: '50%', background: p.color }}></div>

      {/* Type icon */}
      <div style={{
        width: 24, height: 24, borderRadius: 4,
        background: p.bg, color: t.color, border: '1px solid ' + p.border,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 700,
      }}>{t.icon}</div>

      {/* Content */}
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {item.title}
          </span>
          <span style={{
            fontSize: 9, padding: '0px 5px', borderRadius: 2,
            background: p.bg, color: p.color, border: '1px solid ' + p.border,
            fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
          }}>{p.label}</span>
          {batchShort && (
            <span
              onClick={openBatch}
              title={'Open Pro Forma for ' + item.linked_batch_id}
              style={{
                fontSize: 9, padding: '0px 5px', borderRadius: 2, fontFamily: 'monospace',
                background: 'var(--accent-subtle)', color: 'var(--accent)',
                border: '1px solid var(--accent-border)', cursor: 'pointer',
              }}
            >{batchShort}</span>
          )}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {item.detail}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
          <span>{t.label}</span>
          <span style={{ margin: '0 6px' }}>·</span>
          <span>{item.actor}</span>
          <span style={{ margin: '0 6px' }}>·</span>
          <span>{_relTime(item.age)}</span>
        </div>
      </div>

      {/* Action affordance */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
        {isProposalAction ? (
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              onClick={doApprove}
              disabled={acting}
              data-testid={'inbox-approve-' + item.id}
              title={acting ? 'Working…' : 'Approve this proposal'}
              style={{
                background: acting ? 'var(--bg-subtle)' : 'var(--badge-green-bg)',
                color: acting ? 'var(--text-3)' : 'var(--badge-green-text)',
                border: '1px solid ' + (acting ? 'var(--border)' : 'var(--badge-green-border)'),
                borderRadius: 4, padding: '4px 12px', fontSize: 11, fontWeight: 700,
                cursor: acting ? 'default' : 'pointer', whiteSpace: 'nowrap',
                opacity: acting ? 0.6 : 1,
              }}
            >{acting ? '…' : 'Approve'}</button>
            <button
              onClick={doReject}
              disabled={acting}
              data-testid={'inbox-reject-' + item.id}
              title={acting ? 'Working…' : 'Reject this proposal'}
              style={{
                background: 'transparent',
                color: acting ? 'var(--text-3)' : 'var(--badge-red-text)',
                border: '1px solid ' + (acting ? 'var(--border)' : 'var(--badge-red-border)'),
                borderRadius: 4, padding: '4px 12px', fontSize: 11, fontWeight: 700,
                cursor: acting ? 'default' : 'pointer', whiteSpace: 'nowrap',
                opacity: acting ? 0.6 : 1,
              }}
            >Reject</button>
          </div>
        ) : (
          <button
            disabled
            title={item.primary_action + ' — handled on its source page'}
            style={{
              background: 'var(--bg-subtle)', color: 'var(--text-3)',
              border: '1px solid var(--border)', borderRadius: 4,
              padding: '4px 12px', fontSize: 11, fontWeight: 700,
              cursor: 'not-allowed', whiteSpace: 'nowrap', opacity: 0.6,
            }}
          >{item.primary_action} →</button>
        )}
        {actErr && (
          <div
            data-testid={'inbox-acterr-' + item.id}
            style={{ fontSize: 10, color: 'var(--badge-red-text)', maxWidth: 200, textAlign: 'right' }}
          >{actErr}</div>
        )}
      </div>
    </div>
  );
}

// ── EvidencePanel ─────────────────────────────────────────────────────────────
//
// Read-only projection of GET /api/v1/inbox/evidence/{item_id} (PR-E3a, #614).
// Frontend-only consumer: renders ONLY the fields the endpoint already projects.
// No raw evidence is fetched or rendered beyond what the endpoint returns — the
// no-leak posture (subject-only, no body/to/cc/attachments) is enforced backend-
// side and this panel never asks for more.
//
// apiFetch (dashboard-shared.js) semantics this panel relies on:
//   • 2xx  -> resolves parsed JSON. In-band markers {ok:false, gone:true} and
//             {ok:false, degraded:true} arrive in .then (they are 200s).
//   • 401/403 -> throws Error with .type='auth' + .status (forbidden email-*).
//   • other non-2xx (404) -> throws Error('HTTP 404: ...') (no .status, no body).
//   • network failure -> throws Error with .type='network'.

function EvField({ label, value, testid, mono }) {
  // One label/value row. Renders nothing when the value is absent so the
  // projection stays honest (no empty "—" rows implying data we don't have).
  if (value === null || value === undefined || value === '') return null;
  return (
    <div data-testid={testid} style={{ display: 'flex', gap: 10, padding: '5px 0', borderBottom: '1px solid var(--border-subtle)' }}>
      <div style={{ fontSize: 10.5, color: 'var(--text-3)', minWidth: 116, textTransform: 'uppercase', letterSpacing: '0.04em', flexShrink: 0 }}>{label}</div>
      <div style={{
        fontSize: 12, color: 'var(--text)', wordBreak: 'break-word',
        fontFamily: mono ? 'monospace' : 'inherit',
      }}>{value}</div>
    </div>
  );
}

function renderEvidence(kind, ev) {
  // Per-kind projection. Each branch renders ONLY the keys the endpoint
  // contract (routes_inbox.py) is documented to return for that kind.
  if (kind === 'proposal') {
    return (
      <div data-testid="inbox-ev-proposal">
        <EvField label="Proposal type" value={ev.proposal_type} testid="ev-proposal-type" />
        <EvField label="Status"        value={ev.status} testid="ev-proposal-status" />
        <EvField label="Draft subject" value={ev.draft_subject} testid="ev-proposal-subject" />
        <EvField label="Reason"        value={ev.reason} testid="ev-proposal-reason" />
        <EvField label="Linked batch"  value={ev.linked_batch_id} testid="ev-proposal-batch" mono />
        <EvField label="Created"       value={_relTime(ev.created_at)} testid="ev-proposal-created" />
      </div>
    );
  }
  if (kind === 'email') {
    return (
      <div data-testid="inbox-ev-email">
        <EvField label="Subject"      value={ev.subject} testid="ev-email-subject" />
        <EvField label="To"           value={ev.to} testid="ev-email-to" />
        <EvField label="Status"       value={ev.status} testid="ev-email-status" />
        <EvField label="Queued"       value={_relTime(ev.queued_at)} testid="ev-email-queued" />
        <EvField label="Linked batch" value={ev.linked_batch_id} testid="ev-email-batch" mono />
      </div>
    );
  }
  if (kind === 'customs') {
    var na = ev.next_action;  // {title, priority} | null — NEVER render the object directly
    var naP = (na && PRIORITY_CONF[na.priority]) || null;
    var flags = ev.summary && typeof ev.summary === 'object'
      ? Object.keys(ev.summary).filter(function(k) { return ev.summary[k] === true; })
      : [];
    var lineage = Array.isArray(ev.thread_lineage) ? ev.thread_lineage : [];
    return (
      <div data-testid="inbox-ev-customs">
        <EvField label="AWB"        value={ev.awb} testid="ev-customs-awb" mono />
        <EvField label="Batches"    value={Array.isArray(ev.batch_ids) ? ev.batch_ids.join(', ') : null} testid="ev-customs-batches" mono />
        {na && (
          <div data-testid="ev-customs-next-action" style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', minWidth: 116, textTransform: 'uppercase', letterSpacing: '0.04em', flexShrink: 0 }}>Next action</div>
            <div style={{ fontSize: 12, color: 'var(--text)' }}>{na.title}</div>
            {naP && (
              <span style={{
                fontSize: 9, padding: '0px 5px', borderRadius: 2,
                background: naP.bg, color: naP.color, border: '1px solid ' + naP.border,
                fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
              }}>{naP.label}</span>
            )}
          </div>
        )}
        <EvField label="Last message" value={_relTime(ev.last_message_at)} testid="ev-customs-last-message" />
        <EvField label="Last scan"    value={_relTime(ev.last_scan_at)} testid="ev-customs-last-scan" />
        {flags.length > 0 && (
          <div data-testid="ev-customs-flags" style={{ padding: '8px 0' }}>
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Evidence collected</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {flags.map(function(k) {
                return (
                  <span key={k} style={{
                    fontSize: 10, padding: '2px 7px', borderRadius: 3,
                    background: 'var(--badge-green-bg)', color: 'var(--badge-green-text)',
                    border: '1px solid var(--badge-green-border)', fontWeight: 600,
                  }}>{k.replace(/_/g, ' ')}</span>
                );
              })}
            </div>
          </div>
        )}
        {lineage.length > 0 && (
          <div data-testid="ev-customs-lineage" style={{ padding: '8px 0' }}>
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Thread lineage</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {lineage.map(function(ln, i) {
                return (
                  <div key={i} style={{ borderLeft: '2px solid var(--border)', paddingLeft: 10 }}>
                    <div style={{ fontSize: 11.5, color: 'var(--text)', fontWeight: 600, wordBreak: 'break-word' }}>{ln.subject || '(no subject)'}</div>
                    <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 1 }}>
                      <span>{ln.direction}</span>
                      <span style={{ margin: '0 5px' }}>·</span>
                      <span>{ln.event_type}</span>
                      <span style={{ margin: '0 5px' }}>·</span>
                      <span>{ln.sender}</span>
                      <span style={{ margin: '0 5px' }}>·</span>
                      <span>{_relTime(ln.timestamp)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  }
  if (kind === 'proforma_draft') {
    return (
      <div data-testid="inbox-ev-proforma-draft">
        <EvField label="Draft state"  value={ev.draft_state} testid="ev-draft-state" />
        <EvField label="Client"       value={ev.client_name} testid="ev-draft-client" />
        <EvField label="Batch"        value={ev.batch_id} testid="ev-draft-batch" mono />
        <EvField label="Currency"     value={ev.currency} testid="ev-draft-currency" />
        <EvField label="Number"       value={ev.fullnumber} testid="ev-draft-number" mono />
        <EvField label="Created"      value={_relTime(ev.created_at)} testid="ev-draft-created" />
        <EvField label="Updated"      value={_relTime(ev.updated_at)} testid="ev-draft-updated" />
        <EvField label="Post failed"  value={ev.post_failed_at ? _relTime(ev.post_failed_at) : null} testid="ev-draft-post-failed" />
      </div>
    );
  }
  return (
    <div data-testid="inbox-ev-unknown" style={{ fontSize: 12, color: 'var(--text-3)', fontStyle: 'italic', padding: '8px 0' }}>
      No projection available for this evidence type.
    </div>
  );
}

function EvidencePanel({ itemId, item, onClose }) {
  var _ep0 = React.useState(true);
  var loading = _ep0[0], setLoading = _ep0[1];
  var _ep1 = React.useState(null);
  var data    = _ep1[0], setData    = _ep1[1];
  var _ep2 = React.useState(null);
  var err     = _ep2[0], setErr     = _ep2[1];
  var _ep3 = React.useState(0);
  var epSeq   = _ep3[0], setEpSeq   = _ep3[1];

  React.useEffect(function() {
    if (!itemId) return;
    var cancelled = false;
    setLoading(true); setData(null); setErr(null);
    window.EstrellaShared.apiFetch('/api/v1/inbox/evidence/' + encodeURIComponent(itemId))
      .then(function(d) {
        if (cancelled) return;
        setData(d);            // includes in-band markers {ok:false, gone/degraded}
        setLoading(false);
      })
      .catch(function(e) {
        if (cancelled) return;
        // Distinguish auth / network / not-found / generic for an honest message.
        var kind = e && e.type ? e.type : (/HTTP 404/.test(e && e.message || '') ? 'notfound' : 'generic');
        setErr({ kind: kind, message: (e && e.message) || String(e) });
        setLoading(false);
      });
    return function() { cancelled = true; };
  }, [itemId, epSeq]);

  function retry() { setEpSeq(function(s) { return s + 1; }); }

  var headerTitle = (item && item.title) || itemId;

  return (
    <div
      data-testid="inbox-evidence-panel"
      style={{
        width: 360, flexShrink: 0, borderLeft: '1px solid var(--border)',
        background: 'var(--card)', display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Panel header */}
      <div style={{
        padding: '12px 16px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'flex-start', gap: 10, flexShrink: 0,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>Evidence</div>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)', wordBreak: 'break-word' }}>{headerTitle}</div>
        </div>
        <button
          onClick={onClose}
          data-testid="inbox-evidence-close"
          aria-label="Close evidence panel"
          title="Close"
          style={{
            background: 'transparent', border: '1px solid var(--border)', borderRadius: 4,
            width: 24, height: 24, cursor: 'pointer', color: 'var(--text-2)',
            fontSize: 13, lineHeight: 1, flexShrink: 0,
          }}
        >×</button>
      </div>

      {/* Panel body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>

        {loading && (
          <div data-testid="inbox-evidence-loading" style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-2)', fontSize: 12 }}>
            <span className="spinner" /> Loading evidence…
          </div>
        )}

        {!loading && err && (
          <div data-testid="inbox-evidence-error" style={{ padding: '16px 0', color: 'var(--badge-red-text)', fontSize: 12 }}>
            {err.kind === 'auth'     && 'Not authorized to view this evidence.'}
            {err.kind === 'network'  && 'Network error — could not reach the server.'}
            {err.kind === 'notfound' && 'Evidence not found — the item may have been removed.'}
            {err.kind === 'generic'  && ('Could not load evidence: ' + err.message)}
            {err.kind !== 'auth' && (
              <div>
                <button
                  onClick={retry}
                  data-testid="inbox-evidence-retry"
                  style={{
                    marginTop: 12, cursor: 'pointer', padding: '5px 12px',
                    borderRadius: 4, border: '1px solid var(--badge-red-border)',
                    background: 'transparent', color: 'var(--badge-red-text)',
                    fontSize: 11, fontWeight: 600,
                  }}
                >Retry</button>
              </div>
            )}
          </div>
        )}

        {!loading && !err && data && data.ok === false && data.gone && (
          <div data-testid="inbox-evidence-gone" style={{ padding: '16px 0', color: 'var(--text-2)', fontSize: 12 }}>
            This item has already been resolved{data.status ? ' (' + data.status + ')' : ''}. There is nothing left to action.
          </div>
        )}

        {!loading && !err && data && data.ok === false && data.degraded && (
          <div data-testid="inbox-evidence-degraded" style={{ padding: '16px 0', color: 'var(--badge-amber-text)', fontSize: 12 }}>
            Evidence is temporarily unavailable — the source could not be read.
            <div>
              <button
                onClick={retry}
                data-testid="inbox-evidence-degraded-retry"
                style={{
                  marginTop: 12, cursor: 'pointer', padding: '5px 12px',
                  borderRadius: 4, border: '1px solid var(--badge-amber-border)',
                  background: 'transparent', color: 'var(--badge-amber-text)',
                  fontSize: 11, fontWeight: 600,
                }}
              >Retry</button>
            </div>
          </div>
        )}

        {!loading && !err && data && data.ok && data.evidence && (
          <div data-testid="inbox-evidence-body">
            {renderEvidence(data.kind, data.evidence)}
          </div>
        )}

      </div>
    </div>
  );
}

// ── InboxPage ─────────────────────────────────────────────────────────────────

// ── Filter constants (must match server values in routes_inbox.py) ────────────

var TYPE_FILTERS = [
  { id: 'all',      label: 'All types' },
  { id: 'proposal', label: 'Proposals' },
  { id: 'email',    label: 'Email' },
  { id: 'customs',  label: 'Customs' },
  { id: 'approval', label: 'Approvals' },
];

var PRIORITY_FILTERS = [
  { id: 'all',    label: 'All priorities', color: null },
  { id: 'urgent', label: 'Urgent',         color: 'var(--badge-red-text)' },
  { id: 'high',   label: 'High',           color: 'var(--badge-amber-text)' },
  { id: 'normal', label: 'Normal',         color: 'var(--badge-blue-text)' },
  { id: 'info',   label: 'Info',           color: 'var(--badge-neutral-text)' },
];

function InboxPage({ onNav }) {
  var _useState0 = React.useState([]);
  var items    = _useState0[0], setItems    = _useState0[1];
  var _useState1 = React.useState({});
  var sources  = _useState1[0], setSources  = _useState1[1];
  var _useState2 = React.useState(true);
  var loading  = _useState2[0], setLoading  = _useState2[1];
  var _useState3 = React.useState(null);
  var error    = _useState3[0], setError    = _useState3[1];
  var _useState4 = React.useState(null);
  var selected = _useState4[0], setSelected = _useState4[1];
  var _useState5 = React.useState(0);
  var seq           = _useState5[0], setSeq           = _useState5[1];  // refresh trigger
  var _useState6 = React.useState('all');
  var typeFilter    = _useState6[0], setTypeFilter    = _useState6[1];  // type filter
  var _useState7 = React.useState('all');
  var priorityFilter = _useState7[0], setPriorityFilter = _useState7[1]; // priority filter

  React.useEffect(function() {
    setLoading(true);
    setError(null);
    // Build URL with active filter params; omit param when "all" (server returns full list).
    var url = '/api/v1/inbox';
    var params = [];
    if (typeFilter     && typeFilter     !== 'all') params.push('type='     + encodeURIComponent(typeFilter));
    if (priorityFilter && priorityFilter !== 'all') params.push('priority=' + encodeURIComponent(priorityFilter));
    if (params.length) url = url + '?' + params.join('&');
    window.EstrellaShared.apiFetch(url)
      .then(function(d) {
        setItems(d.items   || []);
        setSources(d.sources || {});
        setLoading(false);
      })
      .catch(function(err) {
        setError(err.message || String(err));
        setLoading(false);
      });
  }, [seq, typeFilter, priorityFilter]);  // refetch on filter change or manual refresh

  function refresh() { setSeq(function(s) { return s + 1; }); }

  var deadSources = Object.entries(sources).filter(function(entry) { return !entry[1].ok; });

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div style={{
        padding: '14px 24px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 12, background: 'var(--card)',
        flexShrink: 0,
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>
          Action Inbox
          {!loading && !error && (
            <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 400, color: 'var(--text-3)' }}>
              {items.length} item{items.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <span style={{ flex: 1 }}></span>
        <button
          onClick={refresh}
          disabled={loading}
          title="Refresh inbox"
          style={{
            background: 'transparent', border: '1px solid var(--border)', borderRadius: 4,
            padding: '5px 10px', cursor: loading ? 'default' : 'pointer',
            color: 'var(--text-2)', fontSize: 11, fontWeight: 600,
          }}
        >{loading ? '…' : '↻ Refresh'}</button>
      </div>

      {/* ── Filter bar ──────────────────────────────────────────────────────── */}
      <div
        data-testid="inbox-filter-bar"
        style={{
          padding: '8px 24px', borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap',
          background: 'var(--bg-subtle)', flexShrink: 0,
        }}
      >
        {/* Type pills */}
        {TYPE_FILTERS.map(function(t) {
          var active = typeFilter === t.id;
          return (
            <button
              key={t.id}
              onClick={function() { setTypeFilter(t.id); }}
              data-testid={'inbox-type-' + t.id}
              style={{
                padding: '3px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                border: '1px solid ' + (active ? 'var(--accent)' : 'var(--border)'),
                background: active ? 'var(--accent-subtle)' : 'transparent',
                color: active ? 'var(--accent)' : 'var(--text-2)',
                cursor: 'pointer',
              }}
            >{t.label}</button>
          );
        })}

        <span style={{ margin: '0 6px', color: 'var(--border-subtle)', userSelect: 'none' }}>│</span>

        {/* Priority pills */}
        {PRIORITY_FILTERS.map(function(p) {
          var active = priorityFilter === p.id;
          var col    = p.color || 'var(--accent)';
          return (
            <button
              key={p.id}
              onClick={function() { setPriorityFilter(p.id); }}
              data-testid={'inbox-priority-' + p.id}
              style={{
                padding: '3px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                border: '1px solid ' + (active ? col : 'var(--border)'),
                background: active ? 'var(--bg-subtle)' : 'transparent',
                color: active ? col : 'var(--text-2)',
                cursor: 'pointer',
              }}
            >{p.label}</button>
          );
        })}
      </div>

      {/* ── Per-source degradation notices ─────────────────────────────────── */}
      {deadSources.map(function(entry) {
        var name = entry[0], s = entry[1];
        return (
          <div key={name} style={{
            margin: '8px 16px 0', padding: '8px 12px',
            background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)',
            borderRadius: 6, fontSize: 11.5, color: 'var(--badge-amber-text)', flexShrink: 0,
          }}>
            ⚠ <strong>{name}</strong> unavailable — {s.error || 'unknown error'}. Other sources still shown.
          </div>
        );
      })}

      {/* ── Content (list left, evidence panel right) ──────────────────────── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

      <div style={{ flex: 1, overflowY: 'auto' }}>

        {/* Loading */}
        {loading && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-2)', fontSize: 13 }}>
            <span className="spinner" /> Loading inbox…
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--badge-red-text)', fontSize: 13 }}>
            Failed to load inbox: {error}
            <br />
            <button
              onClick={refresh}
              style={{
                marginTop: 12, cursor: 'pointer', padding: '6px 14px',
                borderRadius: 4, border: '1px solid var(--badge-red-border)',
                background: 'transparent', color: 'var(--badge-red-text)',
                fontSize: 12, fontWeight: 600,
              }}
            >Retry</button>
          </div>
        )}

        {/* Empty */}
        {!loading && !error && items.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12, fontStyle: 'italic' }}>
            ✓ Nothing here — inbox is empty.
          </div>
        )}

        {/* Item list */}
        {!loading && !error && items.map(function(item) {
          return (
            <InboxRow
              key={item.id}
              item={item}
              selected={selected === item.id}
              onSelect={function() { setSelected(item.id); }}
              onActed={refresh}
            />
          );
        })}

      </div>

      {/* Evidence panel — opens when a row is selected (read-only projection) */}
      {selected && (
        <EvidencePanel
          itemId={selected}
          item={items.find(function(i) { return i.id === selected; })}
          onClose={function() { setSelected(null); }}
        />
      )}

      </div>
    </div>
  );
}

Object.assign(window, { InboxPage });
