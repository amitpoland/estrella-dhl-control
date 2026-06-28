// shared.jsx — Shared UI primitives for Proforma V2 React.
// Named exports only. CSS custom properties only (no hardcoded hex).
// Verbatim port of components.jsx: Badge, Card, Btn, Select, Modal.

// Status badge colors — kept semantic, work in both modes
const STATUS_MAP = {
  'Draft':                 { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  'In Transit':            { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  'Pre-check Pending':     { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
  'Pre-check Completed':   { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  'Awaiting DHL Email':    { bg: 'var(--badge-orange-bg)',  text: 'var(--badge-orange-text)',  border: 'var(--badge-orange-border)' },
  'DHL Email Received':    { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  'Reply Package Prepared':{ bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  'Reply Sent':            { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  'SAD Pending':           { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
  'SAD Uploaded':          { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  'Customs Parsed':        { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  'Verification Needed':   { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
  'Customs Verified':      { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  'Locked':                { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  'Ready for PZ':          { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  'Processing':            { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  'Generated':             { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  'Ready for Booking':     { bg: 'var(--badge-purple-bg)',  text: 'var(--badge-purple-text)',  border: 'var(--badge-purple-border)' },
  'Exported':              { bg: 'var(--badge-accent-bg)',  text: 'var(--badge-accent-text)',  border: 'var(--badge-accent-border)' },
  'Awaiting DHL':          { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
  'Awaiting SAD':          { bg: 'var(--badge-orange-bg)',  text: 'var(--badge-orange-text)',  border: 'var(--badge-orange-border)' },
  'Action Required':       { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
  'In Preparation':        { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  'Live':                  { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  'Pending':               { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
}

export function Badge({ status, small }) {
  const s = STATUS_MAP[status] || STATUS_MAP['Draft']
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: s.bg, color: s.text, border: `1px solid ${s.border}`,
      borderRadius: 4, padding: small ? '1px 6px' : '2px 8px',
      fontSize: small ? 10 : 11, fontWeight: 600, letterSpacing: '0.03em', whiteSpace: 'nowrap',
    }}>{status}</span>
  )
}

export function Card({ children, style, onClick, ...rest }) {
  return (
    <div onClick={onClick} {...rest} style={{
      background: 'var(--card)', borderRadius: 8,
      border: '1px solid var(--border)',
      boxShadow: '0 1px 3px var(--shadow)',
      ...style,
    }}>{children}</div>
  )
}

// Forwards ...rest (data-testid, title, aria-*) to the <button> element.
export function Btn({ children, onClick, variant = 'default', small, disabled, style: extraStyle, ...rest }) {
  const variants = {
    default: { background: 'var(--text)',           color: 'var(--card)',             border: '1px solid var(--text)' },
    primary: { background: 'var(--accent)',          color: 'var(--accent-text)',       border: '1px solid var(--accent)' },
    gold:    { background: 'var(--accent)',          color: 'var(--accent-text)',       border: '1px solid var(--accent)' },
    outline: { background: 'transparent',            color: 'var(--text)',              border: '1px solid var(--border)' },
    ghost:   { background: 'transparent',            color: 'var(--text-2)',            border: '1px solid transparent' },
    danger:  { background: 'var(--badge-red-bg)',    color: 'var(--badge-red-text)',    border: '1px solid var(--badge-red-border)' },
    success: { background: 'var(--badge-green-bg)',  color: 'var(--badge-green-text)',  border: '1px solid var(--badge-green-border)' },
  }
  const v = variants[variant] || variants.default
  return (
    <button onClick={onClick} disabled={disabled} {...rest} style={{
      ...v, borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
      padding: small ? '4px 10px' : '7px 14px',
      fontSize: small ? 11 : 12, fontWeight: 600,
      opacity: disabled ? 0.45 : 1,
      display: 'inline-flex', alignItems: 'center', gap: 4,
      whiteSpace: 'nowrap', transition: 'opacity 0.15s',
      ...extraStyle,
    }}>{children}</button>
  )
}

export function Select({ value, onChange, children, style: s }) {
  return (
    <select value={value} onChange={onChange} style={{
      width: '100%', padding: '8px 10px', borderRadius: 6,
      border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
      background: 'var(--bg-subtle)', outline: 'none', boxSizing: 'border-box', ...s,
    }}>{children}</select>
  )
}

export function InfoRow({ label, value, mono }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}>
      <span style={{ fontSize: 11, color: 'var(--text-2)', fontWeight: 500 }}>{label}</span>
      <span style={{ fontSize: 11, color: 'var(--text)', fontWeight: 600, fontFamily: mono ? 'monospace' : 'inherit' }}>{value ?? '—'}</span>
    </div>
  )
}

export function Modal({ title, onClose, children, wide }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000, padding: 24,
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: 'var(--card)', borderRadius: 10,
        width: wide ? 680 : 480, maxWidth: '100%',
        maxHeight: '90vh', overflow: 'auto',
        boxShadow: '0 20px 60px var(--shadow-heavy)',
        border: '1px solid var(--border)',
      }}>
        <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)' }}>{title}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-3)' }}>×</button>
        </div>
        <div style={{ padding: 24 }}>{children}</div>
      </div>
    </div>
  )
}
