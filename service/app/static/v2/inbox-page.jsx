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

      {/* ── Content ────────────────────────────────────────────────────────── */}
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
    </div>
  );
}

Object.assign(window, { InboxPage });
