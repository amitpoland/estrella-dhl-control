// ─────────────────────────────────────────────────────────────────────────────
// Inbox — unified action queue (Sprint 2B.2, Option A: read-only display).
//
// WIRED to GET /api/v1/inbox via EstrellaShared.apiFetch (ADR-028 shim).
// NOT raw fetch — EstrellaShared.apiFetch carries credentials:'include',
// D1 network-error catch, and D2 err.status on auth.
//
// Response shape (from routes_inbox.py, committed d6a3a36):
//   { ok, count, items: [{id, type, priority, title, detail, age (ISO),
//     actor, primary_action, linked_batch_id, actionable, endpoint}],
//     sources: {proposals, email_queue, dhl_cache}: {ok, count, error?} }
//
// Writes (Approve/Reject) → Sprint 2B.3.
// Filter tabs (type/priority) → deferred chip.
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

function InboxRow({ item, selected, onSelect }) {
  const p = PRIORITY_CONF[item.priority] || PRIORITY_CONF.info;
  const t = TYPE_CONF[item.type]         || { label: item.type || '?', icon: '?', color: 'var(--text-3)' };

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

      {/* Action affordance — Option A: disabled, labelled for 2B.3 */}
      <div>
        <button
          disabled
          title={item.primary_action + ' — wiring in Sprint 2B.3'}
          style={{
            background: 'var(--bg-subtle)', color: 'var(--text-3)',
            border: '1px solid var(--border)', borderRadius: 4,
            padding: '4px 12px', fontSize: 11, fontWeight: 700,
            cursor: 'not-allowed', whiteSpace: 'nowrap', opacity: 0.6,
          }}
        >{item.primary_action} →</button>
      </div>
    </div>
  );
}

// ── InboxPage ─────────────────────────────────────────────────────────────────

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
  var seq      = _useState5[0], setSeq      = _useState5[1];   // increment to trigger refresh

  React.useEffect(function() {
    setLoading(true);
    setError(null);
    window.EstrellaShared.apiFetch('/api/v1/inbox')
      .then(function(d) {
        setItems(d.items   || []);
        setSources(d.sources || {});
        setLoading(false);
      })
      .catch(function(err) {
        setError(err.message || String(err));
        setLoading(false);
      });
  }, [seq]);

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
            />
          );
        })}

      </div>
    </div>
  );
}

Object.assign(window, { InboxPage });
