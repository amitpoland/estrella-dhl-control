// Master Data page — Sprint 38: live backend read authority.
//
// All 12 entity tabs render from backend GET endpoints (no hardcoded data).
// Write operations (create/edit/delete) are disabled with explicit reasons.
// Users: read-only list from GET /auth/users.
// Roles: static system definition from ROLE_MATRIX (no backend endpoint).
//
// Sprint 38b (View-enable, 2026-06-07): the per-row "View" action is now ENABLED
// for every entity. It opens a READ-ONLY detail modal rendering the already-loaded
// record's fields — no new fetch, no write path. Previously the View button was
// hardcoded disabled with a *write*-disabled reason (defect: a read action carrying
// a write justification). Edit/Delete remain unwired (separate PR) — backend
// PUT/DELETE /customer-master/{id} exist; only the UI wiring is pending.

const ENTITY_TYPES = [
  { id: 'clients',   label: 'Clients / Importers', icon: '\u{1F3E2}', singular: 'Client' },
  { id: 'suppliers', label: 'Suppliers / Exporters', icon: '\u{1F3ED}', singular: 'Supplier' },
  { id: 'products',  label: 'Products',           icon: '◈', singular: 'Product' },
  { id: 'designs',   label: 'Designs',            icon: '✦', singular: 'Design' },
  { id: 'hs',        label: 'HS Codes',           icon: '⊟', singular: 'HS Code' },
  { id: 'fx',        label: 'FX Rates',           icon: '$', singular: 'FX Rate' },
  { id: 'vat',       label: 'VAT Rates',          icon: '%', singular: 'VAT Rate' },
  { id: 'carriers',  label: 'Carriers',           icon: '✈', singular: 'Carrier' },
  { id: 'box_profiles', label: 'Box Profiles',    icon: '▣', singular: 'Box Profile' },
  { id: 'incoterms', label: 'Incoterms',          icon: '≡', singular: 'Incoterm' },
  { id: 'units',     label: 'Units of Measure',   icon: '⚖', singular: 'Unit' },
  { id: 'users',     label: 'Users',              icon: '◉', singular: 'User' },
  { id: 'roles',     label: 'Roles & Permissions', icon: '\u{1F510}', singular: 'Role' },
];

// Role permissions matrix — static system definition.
const ROLE_MATRIX = {
  admin:    { create: true, edit: true,  delete: true,  lock: true  },
  manager:  { create: true, edit: true,  delete: false, lock: true  },
  operator: { create: true, edit: true,  delete: false, lock: false },
  viewer:   { create: false, edit: false, delete: false, lock: false },
};

// ── Table column definitions per entity — match actual backend response fields
// Sprint 38b: mapping/status columns added for 7 focus entities.
// Column.mapping = true renders "not mapped" badge instead of bare "—" for nulls.
// Column.timestamp = true renders relative-time format for ISO date strings.
const ENTITY_COLUMNS = {
  clients: [
    { key: 'bill_to_name',          label: 'Company name' },
    { key: 'country',               label: 'Country' },
    { key: 'nip',                   label: 'NIP / VAT ID', mono: true },
    { key: 'default_currency',      label: 'Currency' },
    { key: 'bill_to_contractor_id', label: 'wFirma ID', mono: true, mapping: true },
    { key: 'last_wfirma_sync_at',   label: 'Last wFirma sync', timestamp: true },
    { key: 'active',                label: 'Active', toggle: true },
  ],
  suppliers: [
    { key: 'name',                  label: 'Supplier name' },
    { key: 'supplier_code',         label: 'Code', mono: true },
    { key: 'country',               label: 'Country' },
    { key: 'vat_id',                label: 'VAT ID', mono: true },
    { key: 'wfirma_id',             label: 'wFirma ID', mono: true, mapping: true },
    { key: 'last_wfirma_sync_at',   label: 'Last sync', timestamp: true },
    { key: 'active',                label: 'Active', toggle: true },
  ],
  products: [
    { key: 'product_code', label: 'Product code', mono: true },
    { key: 'design_no',    label: 'Design no.' },
    { key: 'item_type',    label: 'Item type' },
    { key: 'status',       label: 'Status', statusBadge: true },
    { key: 'is_active',    label: 'Active', toggle: true },
  ],
  designs: [
    { key: 'design_code',   label: 'Design code', mono: true },
    { key: 'display_name',  label: 'Name' },
    { key: 'collection',    label: 'Collection' },
    { key: 'metal',         label: 'Metal' },
    { key: 'design_family', label: 'Family' },
    { key: 'active',        label: 'Active', toggle: true },
  ],
  hs: [
    { key: 'hs_code',        label: 'HS code', mono: true },
    { key: 'description_pl', label: 'Description (PL)' },
    { key: 'duty_rate_pct',  label: 'Duty %' },
    { key: 'vat_rate_pct',   label: 'VAT %' },
    { key: 'active',         label: 'Active', toggle: true },
  ],
  fx: [
    { key: 'from_currency', label: 'From' },
    { key: 'to_currency',   label: 'To' },
    { key: 'rate',           label: 'Rate' },
    { key: 'rate_date',      label: 'Date' },
    { key: 'source',         label: 'Source' },
  ],
  vat: [
    { key: 'rate_code',     label: 'Code', mono: true },
    { key: 'rate_pct',      label: 'Rate %' },
    { key: 'country',       label: 'Country' },
    { key: 'product_type',  label: 'Product type' },
    { key: 'active',        label: 'Active', toggle: true },
  ],
  carriers: [
    { key: 'carrier_code', label: 'Code', mono: true },
    { key: 'name',         label: 'Name' },
    { key: 'parser_type',  label: 'Parser' },
    { key: 'api_type',     label: 'API type' },
    { key: 'inbox_email',  label: 'Inbox email' },
    { key: 'active',       label: 'Active', toggle: true },
  ],
  box_profiles: [
    { key: 'code',           label: 'Code', mono: true },
    { key: 'name',           label: 'Name' },
    { key: 'carrier',        label: 'Carrier' },
    { key: 'length_cm',      label: 'L (cm)' },
    { key: 'width_cm',       label: 'W (cm)' },
    { key: 'height_cm',      label: 'H (cm)' },
    { key: 'tare_weight_kg', label: 'Tare (kg)' },
    { key: 'max_weight_kg',  label: 'Max (kg)' },
    { key: 'package_type',   label: 'Type' },
    { key: 'sort_order',     label: 'Sort' },
    { key: 'active',         label: 'Active', toggle: true },
  ],
  incoterms: [
    { key: 'code',                label: 'Code', mono: true },
    { key: 'name',                label: 'Name' },
    { key: 'risk_transfer_point', label: 'Risk transfer' },
    { key: 'freight_included',    label: 'Freight', toggle: true },
    { key: 'insurance_included',  label: 'Insurance', toggle: true },
    { key: 'customs_included',    label: 'Customs', toggle: true },
    { key: 'active',              label: 'Active', toggle: true },
  ],
  units: [
    { key: 'code',      label: 'Code', mono: true },
    { key: 'name_pl',   label: 'Name (PL)' },
    { key: 'name_en',   label: 'Name (EN)' },
    { key: 'unit_type', label: 'Type' },
    { key: 'active',    label: 'Active', toggle: true },
  ],
  users: [
    { key: 'full_name',       label: 'Full name' },
    { key: 'email',           label: 'Email' },
    { key: 'role',            label: 'Role' },
    { key: 'is_active',       label: 'Active', toggle: true },
    { key: 'approval_status', label: 'Status' },
  ],
  roles: [
    { key: 'role',   label: 'Role' },
    { key: 'source', label: 'Authority' },
  ],
};

// ── Sprint 38b: Per-entity mapping status metadata
// Each entity declares what mapping/status authority exists (available)
// and what is missing (pending). Rendered as info banners below the table.
const MAPPING_INFO = {
  clients: {
    available: [
      'wFirma contractor ID (bill_to_contractor_id column)',
      'wFirma sync preview + apply (GET/POST /customer-master/sync-from-wfirma)',
      'Last wFirma sync timestamp visible per record',
    ],
    pending: [
      'Purchase packing list usage — no endpoint exposes which packing lists reference this client',
      'Sales packing list usage — no endpoint exposes sales packing list references',
      'Proforma/invoice history — no per-client proforma count endpoint',
      'DHL/customs shipment history — no per-client shipment count endpoint',
    ],
  },
  suppliers: {
    available: [
      'wFirma ID (wfirma_id column)',
      'wFirma sync preview + apply (GET/POST /suppliers/sync-from-wfirma)',
      'Last wFirma sync timestamp visible per record',
    ],
    pending: [
      'Purchase packing list supplier usage — no endpoint exposes which packing lists reference this supplier',
    ],
  },
  products: {
    available: [
      'Product Master registry (149 rows) — synced from purchase batches via Product Master Sync',
      'Status badge: mapping_required → needs Create & adopt in wFirma; mapped → wFirma goods linked',
      'Design number (design_no) links to Designs tab',
      'Per-row "Edit overlays" writes to local overlay (HS code / unit / design link) — does NOT modify the read-only Product Master',
      'Per-row "Create & adopt" — fiscal-gated (requires WFIRMA_CREATE_PRODUCT_ALLOWED)',
    ],
    pending: [
      'wFirma goods ID not stored in product_master — mapping lives in wFirma goods adoption record',
      'Packing list item usage — no endpoint exposes which packing lists contain this product code',
    ],
  },
  designs: {
    available: [
      'Design metadata CRUD via /api/v1/designs (Design Master authority)',
      'Full create / edit / soft-delete wired — Create Design button + per-row Edit + Delete',
    ],
    pending: [
      'design→product_code mapping is populated from purchase packing (no manual REST writer); mapping_required is resolved via Product Master sync + wFirma adopt',
    ],
  },
  vat: {
    available: [],
    pending: [
      'wFirma VAT sync — no wFirma VAT sync endpoint exists; local VAT config is the only authority',
    ],
  },
  carriers: {
    available: [
      'Parser type and API type visible per carrier',
      'Supported services list available from backend',
    ],
    pending: [
      'DHL active model/credentials status — no endpoint exposes live DHL API connection status per carrier',
      'FedEx/UPS/GLS/InPost/DPD — mapping/status only unless backend authority exists for these carriers',
    ],
  },
  incoterms: {
    available: [
      'Freight/insurance/customs inclusion flags visible per incoterm',
    ],
    pending: [
      'Usage tracking — no endpoint exposes which purchase/sales packing lists use each incoterm',
    ],
  },
  units: {
    available: [
      'Unit type classification visible per unit',
    ],
    pending: [
      'Conversion backend — no unit conversion endpoint exists',
      'Product Local usage — no endpoint counts how many products use each unit',
    ],
  },
};

// Fallback role name list for pre-load state ONLY; the authoritative list comes
// from the capability contract (auth/service.py ROLES). These are the real
// system-defined roles — never the stale admin/manager/operator/viewer set.
const STATIC_ROLES_NAMES = [
  'admin', 'accounts', 'logistics', 'auditor', 'viewer',
  'master_admin', 'master_editor', 'master_viewer',
];

// ── Disabled-reason messages for write buttons
const WRITE_DISABLED_REASON = 'Write operations not yet wired — Sprint 38 is read-only authority conversion';
const ROLES_DISABLED_REASON = 'No backend endpoint for role management — roles are system-defined';
const USERS_WRITE_DISABLED_REASON = 'User write operations require admin endpoints not yet wired to this page';
const WFIRMA_VAT_SYNC_DISABLED = 'Backend pending: wFirma VAT sync endpoint missing';

// ── Sprint 38b: format a timestamp for display
function _fmtTimestamp(isoStr) {
  if (!isoStr) return null;
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch (_) {
    return isoStr;
  }
}

// ── Sprint 38b: cell renderer supporting mapping + timestamp columns
function _renderCell(col, value) {
  if (col.toggle) return value ? '✓' : '✗';
  if (col.timestamp) {
    const formatted = _fmtTimestamp(value);
    if (!formatted) return '—';
    return formatted;
  }
  if (col.mapping) {
    if (value == null || value === '') {
      return React.createElement('span', {
        style: { fontSize: 10, color: 'var(--text-3)', fontStyle: 'italic' },
        'data-testid': 'mapping-not-mapped',
      }, 'not mapped');
    }
    return String(value);
  }
  if (col.statusBadge) {
    const v = value == null ? '' : String(value);
    const colorKey = v === 'mapping_required' ? 'amber' : v === 'mapped' ? 'green' : 'neutral';
    const label    = v === 'mapping_required' ? 'mapping required' : v || '—';
    return React.createElement('span', {
      'data-testid': 'status-badge-' + (v || 'unknown'),
      style: {
        display: 'inline-block', padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 600,
        background: 'var(--badge-' + colorKey + '-bg, rgba(212,168,83,0.12))',
        color: 'var(--badge-' + colorKey + '-text, #92400e)',
        border: '1px solid var(--badge-' + colorKey + '-border, rgba(212,168,83,0.3))',
      },
    }, label);
  }
  if (value == null || value === '') return '—';
  return String(value);
}

// ── Sprint 38b: Mapping info banner component
function MappingInfoBanner({ entityId }) {
  const info = MAPPING_INFO[entityId];
  if (!info) return null;
  if (info.available.length === 0 && info.pending.length === 0) return null;

  return React.createElement('div', {
    'data-testid': 'mapping-info-' + entityId,
    style: {
      marginTop: 12, padding: 14,
      background: 'var(--bg-subtle)',
      border: '1px solid var(--border)',
      borderRadius: 6, fontSize: 11,
    },
  },
    React.createElement('div', {
      style: { fontWeight: 700, fontSize: 10, textTransform: 'uppercase',
               letterSpacing: '0.06em', color: 'var(--text-3)', marginBottom: 8 },
    }, 'Mapping & integration status'),

    info.available.length > 0 && React.createElement('div', { style: { marginBottom: info.pending.length > 0 ? 8 : 0 } },
      info.available.map(function(item, i) {
        return React.createElement('div', { key: 'a' + i, style: { color: 'var(--text-2)', marginBottom: 2 } },
          '✓ ', item);
      })
    ),

    info.pending.length > 0 && React.createElement('div', null,
      info.pending.map(function(item, i) {
        return React.createElement('div', {
          key: 'p' + i,
          'data-testid': 'mapping-pending-' + entityId + '-' + i,
          style: { color: 'var(--badge-amber-text, #92400e)', marginBottom: 2 },
        }, '○ Backend pending: ', item);
      })
    )
  );
}

// ── API fetch mapping: entity id -> { fetch, extractRecords, rowKey }
function _entityApi(entityId) {
  switch (entityId) {
    case 'clients':   return { fetch: () => PzApi.listCustomerMaster(),  extract: d => d.customers || [],  rowKey: r => r.id || r.bill_to_contractor_id };
    case 'suppliers':  return { fetch: () => PzApi.listSuppliers(),       extract: d => d.suppliers || [],  rowKey: r => r.id };
    case 'products':   return { fetch: () => PzApi.listProductMaster(),   extract: d => d.rows  || [],       rowKey: r => r.product_code };
    case 'designs':    return { fetch: () => PzApi.listDesigns(),         extract: d => d.designs || [],    rowKey: r => r.design_code };
    case 'hs':         return { fetch: () => PzApi.listHsCodes(),         extract: d => d.hs_codes || [],   rowKey: r => r.hs_code };
    case 'fx':         return { fetch: () => PzApi.listFxRates(),         extract: d => d.fx_rates || [],   rowKey: r => r.id };
    case 'vat':        return { fetch: () => PzApi.listVatConfig(),       extract: d => d.vat_config || [], rowKey: r => r.id };
    case 'carriers':   return { fetch: () => PzApi.listCarriersConfig(),  extract: d => d.carriers || [],   rowKey: r => r.carrier_code };
    case 'box_profiles': return { fetch: () => PzApi.listBoxTypes('all'), extract: d => d.box_types || [],  rowKey: r => r.code };
    case 'incoterms':  return { fetch: () => PzApi.listIncoterms(),       extract: d => d.incoterms || [],  rowKey: r => r.code };
    case 'units':      return { fetch: () => PzApi.listUnits(),           extract: d => d.units || [],      rowKey: r => r.code };
    case 'users':      return { fetch: () => PzApi.listUsers(),           extract: d => (Array.isArray(d) ? d : d.users || []), rowKey: r => r.id };
    case 'roles':      return null; // static data, no API
    default:           return null;
  }
}

// ── Sprint 38b: read-only record detail modal.
// Renders the fields present on the already-loaded record as a key/value grid.
// No fetch, no write — pure display of data the table already holds.
//
// Defense-in-depth: the master list endpoints return sanitised records (e.g.
// GET /auth/users uses _safe_user, an allow-list that already strips
// password_hash/tokens). This modal additionally REDACTS any key that looks
// sensitive, so a future endpoint regression can never surface a secret here.
const SENSITIVE_KEY_RE = /(pass(word)?|secret|token|hash|salt|api[_-]?key|priv(ate)?[_-]?key|credential|session|otp|pin)/i;
function RecordDetailModal({ record, entityLabel, onClose }) {
  if (!record) return null;
  const allEntries = Object.entries(record).filter(([k]) => k !== '__proto__');
  const entries = allEntries.filter(([k]) => !SENSITIVE_KEY_RE.test(k));
  const redactedCount = allEntries.length - entries.length;
  const fmtKey = (k) => String(k).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  const fmtVal = (v) => {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v === 'boolean') return v ? '✓ Yes' : '✗ No';
    if (typeof v === 'object') { try { return JSON.stringify(v); } catch (_) { return String(v); } }
    return String(v);
  };
  return React.createElement('div', {
    'data-testid': 'record-detail-modal',
    onClick: onClose,
    style: {
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'var(--overlay, rgba(0,0,0,0.45))',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    },
  },
    React.createElement('div', {
      onClick: e => e.stopPropagation(),
      style: {
        background: 'var(--bg)', color: 'var(--text)',
        border: '1px solid var(--border)', borderRadius: 8,
        maxWidth: 560, width: '100%', maxHeight: '80vh', overflowY: 'auto',
        boxShadow: '0 12px 40px var(--shadow-heavy, rgba(0,0,0,0.35))',
      },
    },
      // Header
      React.createElement('div', {
        style: {
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 18px', borderBottom: '1px solid var(--border-subtle)',
          position: 'sticky', top: 0, background: 'var(--bg)',
        },
      },
        React.createElement('div', null,
          React.createElement('div', { style: { fontSize: 14, fontWeight: 700 } }, (entityLabel || 'Record') + ' — Details'),
          React.createElement('div', { style: { fontSize: 10.5, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 2 } }, 'Read-only')
        ),
        React.createElement(Btn, { small: true, variant: 'outline', onClick: onClose, 'data-testid': 'btn-close-detail' }, '✕ Close')
      ),
      // Body — key/value grid
      React.createElement('div', { style: { padding: '12px 18px' } },
        entries.map(([k, v], i) =>
          React.createElement('div', {
            key: k,
            style: {
              display: 'grid', gridTemplateColumns: '180px 1fr', gap: 12,
              padding: '7px 0',
              borderBottom: i < entries.length - 1 ? '1px solid var(--border-subtle)' : 'none',
            },
          },
            React.createElement('div', { style: { fontSize: 11, color: 'var(--text-3)', fontWeight: 600 } }, fmtKey(k)),
            React.createElement('div', { style: { fontSize: 12, color: 'var(--text)', wordBreak: 'break-word', fontFamily: 'monospace' } }, fmtVal(v))
          )
        ),
        redactedCount > 0 && React.createElement('div', {
          'data-testid': 'redacted-note',
          style: { marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border-subtle)', fontSize: 10.5, color: 'var(--text-3)', fontStyle: 'italic' },
        }, redactedCount + ' sensitive field' + (redactedCount === 1 ? '' : 's') + ' hidden')
      )
    )
  );
}

// ── ScanStatusPanel — Phase 3B authority port ─────────────────────────────
// Displays contractor scan health, last run, and counters (Clients tab only).
// Ported from customer-master-v2.html (legacy) into this authority file.
function ScanStatusPanel({ status, onRefresh }) {
  if (!status) return null;
  const fmtTs = s => s ? s.replace('T', ' ').slice(0, 19) + ' UTC' : '—';
  const healthColor = status.healthy ? 'var(--badge-green-text)' : 'var(--badge-red-text)';
  const healthBg    = status.healthy ? 'var(--badge-green-bg)'   : 'var(--badge-red-bg)';
  const healthBdr   = status.healthy ? 'var(--badge-green-border)' : 'var(--badge-red-border)';
  return (
    <div data-testid="scan-status-panel" style={{
      background: 'var(--bg-subtle)', border: '1px solid var(--border)',
      borderRadius: 7, padding: '10px 14px', marginTop: 10, marginBottom: 2, fontSize: 12,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontWeight: 600, color: 'var(--text-2)', fontSize: 11 }}>Full Contractor Scan</span>
        {status.running ? (
          <span style={{
            display: 'inline-flex', alignItems: 'center', padding: '2px 7px',
            borderRadius: 20, fontSize: 10, fontWeight: 600, border: '1px solid',
            background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)',
            borderColor: 'var(--badge-amber-border)',
          }} data-testid="scan-badge-running">⏳ running</span>
        ) : (
          <span style={{
            display: 'inline-flex', alignItems: 'center', padding: '2px 7px',
            borderRadius: 20, fontSize: 10, fontWeight: 600, border: '1px solid',
            background: healthBg, color: healthColor, borderColor: healthBdr,
          }} data-testid="scan-badge-health">
            {status.healthy ? '✅ healthy' : '⚠ error'}
          </span>
        )}
        <button onClick={onRefresh} style={{
          marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--text-3)', fontSize: 12, padding: '2px 5px',
        }} title="Refresh scan status" data-testid="btn-scan-status-refresh">↻</button>
      </div>
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
        <div><span style={{ color: 'var(--text-3)' }}>Last run</span> <strong>{fmtTs(status.last_completed_at)}</strong></div>
        <div><span style={{ color: 'var(--text-3)' }}>Processed</span> <strong data-testid="scan-stat-processed">{status.processed ?? '—'}</strong></div>
        <div><span style={{ color: 'var(--badge-green-text)' }}>Created</span> <strong data-testid="scan-stat-created">{status.created ?? '—'}</strong></div>
        <div><span style={{ color: 'var(--badge-blue-text)' }}>Updated</span> <strong data-testid="scan-stat-updated">{status.updated ?? '—'}</strong></div>
        <div><span style={{ color: 'var(--text-3)' }}>Skipped</span> <strong data-testid="scan-stat-skipped">{status.skipped ?? '—'}</strong></div>
        {status.errors > 0 && (
          <div><span style={{ color: 'var(--badge-red-text)' }}>Errors</span> <strong data-testid="scan-stat-errors">{status.errors}</strong></div>
        )}
      </div>
      {status.last_error && (
        <div style={{ marginTop: 6, color: 'var(--badge-red-text)', fontSize: 11 }} data-testid="scan-last-error">
          {status.last_error}
        </div>
      )}
    </div>
  );
}

// ── Box Profile edit/create modal — writes via PUT /api/v1/box-types/{code}.
// Deactivation = active:false toggle (profiles are never deleted).
function BoxProfileEditModal({ record, onClose, onSaved }) {
  const isNew = !record.code;
  const [form, setForm] = React.useState({
    code:           record.code || '',
    name:           record.name || '',
    carrier:        record.carrier || '',
    length_cm:      record.length_cm != null ? String(record.length_cm) : '',
    width_cm:       record.width_cm  != null ? String(record.width_cm)  : '',
    height_cm:      record.height_cm != null ? String(record.height_cm) : '',
    tare_weight_kg: record.tare_weight_kg != null ? String(record.tare_weight_kg) : '',
    max_weight_kg:  record.max_weight_kg  != null ? String(record.max_weight_kg)  : '',
    package_type:   record.package_type || '',
    sort_order:     record.sort_order != null ? String(record.sort_order) : '0',
    active:         record.active !== false,
    notes:          record.notes || '',
  });
  const [saving, setSaving] = React.useState(false);
  const [error, setError]   = React.useState(null);
  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));
  const num = (v) => (v === '' || v == null ? null : Number(v));

  const save = async () => {
    if (saving) return;
    const code = form.code.trim().toUpperCase();
    if (!code) { setError('Code is required.'); return; }
    setSaving(true); setError(null);
    const res = await PzApi.upsertBoxType(code, {
      name:           form.name.trim() || null,
      carrier:        form.carrier.trim() || null,
      length_cm:      num(form.length_cm),
      width_cm:       num(form.width_cm),
      height_cm:      num(form.height_cm),
      tare_weight_kg: num(form.tare_weight_kg),
      max_weight_kg:  num(form.max_weight_kg),
      package_type:   form.package_type.trim() || null,
      sort_order:     num(form.sort_order) || 0,
      active:         !!form.active,
      notes:          form.notes.trim() || null,
    });
    setSaving(false);
    if (res.ok) { onSaved && onSaved(); }
    else setError(res.error || (res.data && res.data.detail) || 'Save failed.');
  };

  const field = (label, key, props = {}) => (
    <div style={{ marginBottom: 10 }}>
      <label style={{ display: 'block', fontSize: 11, color: 'var(--text-3)', marginBottom: 3 }}>{label}</label>
      <Input value={form[key]} onChange={e => set(key, e.target.value)}
        data-testid={'box-field-' + key} {...props} />
    </div>
  );

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'var(--overlay, rgba(0,0,0,0.45))', zIndex: 60, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      data-testid="box-profile-edit-modal">
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--card)', borderRadius: 10, width: 520, maxWidth: '94vw', maxHeight: '90vh', overflowY: 'auto', padding: 20, boxShadow: '0 20px 60px var(--shadow-heavy)' }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14, color: 'var(--text)' }}>
          {isNew ? 'New Box Profile' : `Edit Box Profile — ${record.code}`}
        </div>
        {field('Code *', 'code', { disabled: !isNew, placeholder: 'e.g. DHL-JEWEL-S' })}
        {field('Name', 'name', { placeholder: 'e.g. DHL Small Jewellery Box' })}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {field('Carrier (optional)', 'carrier', { placeholder: 'DHL' })}
          {field('Package type / hint', 'package_type', { placeholder: 'jewellery / ring / bracelet' })}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
          {field('Length (cm)', 'length_cm')}
          {field('Width (cm)', 'width_cm')}
          {field('Height (cm)', 'height_cm')}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
          {field('Tare weight (kg)', 'tare_weight_kg')}
          {field('Max weight (kg)', 'max_weight_kg')}
          {field('Sort order', 'sort_order')}
        </div>
        {field('Notes', 'notes')}
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-2)', marginBottom: 14 }}>
          <input type="checkbox" checked={form.active}
            onChange={e => set('active', e.target.checked)} data-testid="box-field-active" />
          Active (inactive profiles stay stored but leave the AWB modal dropdown)
        </label>
        {error && (
          <div style={{ marginBottom: 12, fontSize: 12, color: 'var(--badge-red-text)' }} data-testid="box-edit-error">{error}</div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Btn variant="outline" small onClick={onClose} data-testid="btn-cancel-box-profile">Cancel</Btn>
          <Btn variant="gold" small onClick={save} disabled={saving} data-testid="btn-save-box-profile">
            {saving ? 'Saving…' : (isNew ? 'Create Box Profile' : 'Save Box Profile')}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ── Slice 1: Product Master Sync panel (Products tab only).
// Advisory-only. Reads the Product Master (reservation authority, wFirma-goods-bound)
// and drives the observable purchase-packing → Product Master sync. Dry-run first.
// This is DISTINCT from the Product Local augmentation table above (see the
// products mapping banner): the local table augments HS/unit/design; this panel is
// the purchase-derived Product Master consumed by wFirma goods mapping.
function _fmtWhen(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  } catch (_) { return String(iso); }
}

function ProductMasterSyncPanel() {
  const [batchId, setBatchId]       = React.useState('');
  const [dryRun, setDryRun]         = React.useState(true);   // dry-run first
  const [running, setRunning]       = React.useState(false);
  const [status, setStatus]         = React.useState(null);
  const [lastResult, setLastResult] = React.useState(null);
  const [pmRows, setPmRows]         = React.useState(null);
  const [error, setError]           = React.useState(null);

  const loadStatus = React.useCallback((bid) => {
    PzApi.getProductMasterSyncStatus(bid || undefined).then(res => {
      setStatus(res.ok ? res.data : null);
    });
  }, []);

  const loadMaster = React.useCallback((bid) => {
    PzApi.listProductMaster(bid || undefined).then(res => {
      if (res.ok) setPmRows(res.data.rows || []);
      else { setPmRows(null); setError(res.error || 'Failed to load Product Master'); }
    });
  }, []);

  React.useEffect(() => { loadStatus(''); loadMaster(''); }, [loadStatus, loadMaster]);

  const runSync = () => {
    const bid = batchId.trim();
    if (!bid) { setError('Enter a batch_id to sync'); return; }
    setError(null);
    setRunning(true);
    PzApi.productMasterSync(bid, { dryRun }).then(res => {
      setRunning(false);
      if (res.ok) {
        setLastResult(res.data);
        loadStatus(bid);
        loadMaster(bid);
      } else {
        setError(res.error || 'Sync failed');
      }
    }).catch(err => { setRunning(false); setError(String(err)); });
  };

  const healthy = status ? status.healthy : true;
  const isRunning = status ? status.running : false;

  return (
    <div data-testid="product-master-sync-panel" style={{ marginTop: 16 }}>
      <Card style={{ padding: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Product Master Sync</div>
          <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em',
                         color: 'var(--text-3)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 6px' }}>
            Advisory
          </span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 14 }}>
          Syncs the Product Master from a batch's <b>purchase packing list</b> (product_master + variant
          signature → design mapping → descriptions → wFirma goods <i>preview</i>). Never mints product codes,
          never creates wFirma products, and gates nothing.
        </div>

        {/* ── Run control ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
          <Input
            data-testid="pm-sync-batch-input"
            value={batchId}
            onChange={e => setBatchId(e.target.value)}
            placeholder="batch_id (e.g. SHIPMENT_…)"
            style={{ minWidth: 280 }}
          />
          <label data-testid="pm-sync-dryrun-label" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-2)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              data-testid="pm-sync-dryrun"
              checked={dryRun}
              onChange={e => setDryRun(e.target.checked)}
            />
            Dry-run (preview only)
          </label>
          <Btn
            variant={dryRun ? 'outline' : 'gold'}
            small
            disabled={running || !batchId.trim()}
            onClick={runSync}
            data-testid="pm-sync-run-btn"
            title={dryRun ? 'Preview the sync without writing' : 'Run the sync — writes the Product Master (advisory)'}>
            {running ? '… Running' : (dryRun ? '▷ Preview (dry-run)' : '▷ Run Sync — writes Product Master')}
          </Btn>
          <Btn variant="outline" small onClick={() => { loadStatus(batchId.trim()); loadMaster(batchId.trim()); }} data-testid="pm-sync-reload-btn">
            {'↻'} Refresh
          </Btn>
        </div>

        {/* ── Error ── */}
        {error && (
          <div data-testid="pm-sync-error" style={{ marginBottom: 12, padding: 10, borderRadius: 6,
               background: 'var(--badge-red-bg, rgba(220,38,38,0.08))', border: '1px solid var(--badge-red-text, #dc2626)',
               fontSize: 11, color: 'var(--badge-red-text, #dc2626)' }}>
            {'⚠ '}{error}
          </div>
        )}

        {/* ── Status panel — the four completeness questions ── */}
        <div data-testid="pm-sync-status" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 14 }}>
          <_Stat label="State" value={
            !status || !status.ever_run ? 'Never run'
              : isRunning ? 'Running…'
              : healthy ? 'Healthy' : 'Errors'
          } tone={!status || !status.ever_run ? 'muted' : isRunning ? 'info' : healthy ? 'ok' : 'bad'} testid="pm-stat-state" />
          <_Stat label="Last completed" value={_fmtWhen(status && status.last_completed_at)} testid="pm-stat-completed" />
          <_Stat label="Processed / Created" value={status ? `${status.processed || 0} / ${status.created || 0}` : '—'} testid="pm-stat-processed" />
          <_Stat label="Updated / Skipped" value={status ? `${status.updated || 0} / ${status.skipped || 0}` : '—'} testid="pm-stat-updated" />
          <_Stat label="Errors" value={status ? String(status.errors || 0) : '—'} tone={status && status.errors ? 'bad' : 'muted'} testid="pm-stat-errors" />
        </div>
        {status && status.last_error && (
          <div data-testid="pm-sync-last-error" style={{ marginBottom: 14, fontSize: 11, color: 'var(--badge-amber-text, #92400e)' }}>
            Last error: {status.last_error}
          </div>
        )}

        {/* ── Last sync result table ── */}
        {lastResult && (
          <div data-testid="pm-sync-result" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-3)', marginBottom: 6 }}>
              Last sync result {lastResult.dry_run ? '(dry-run / preview)' : '(live)'} — {lastResult.batch_id}
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead><tr style={{ background: 'var(--bg-subtle)' }}>
                  {['processed', 'created', 'updated', 'skipped', 'errors', 'duration_ms'].map(k => (
                    <th key={k} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', borderBottom: '1px solid var(--border)' }}>{k.replace('_', ' ')}</th>
                  ))}
                </tr></thead>
                <tbody><tr>
                  {['processed', 'created', 'updated', 'skipped', 'errors', 'duration_ms'].map(k => (
                    <td key={k} data-testid={'pm-result-' + k} style={{ padding: '8px 10px', fontSize: 12, color: 'var(--text-2)' }}>{lastResult[k] != null ? lastResult[k] : 0}</td>
                  ))}
                </tr></tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Product Master list (GET /product-master) ── */}
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-3)', marginBottom: 6 }}>
            Product Master {batchId.trim() ? '(batch ' + batchId.trim() + ')' : '(all)'} — {pmRows ? pmRows.length : 0} rows
          </div>
          <div style={{ overflowX: 'auto', maxHeight: 320, overflowY: 'auto' }}>
            <table data-testid="pm-master-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead><tr style={{ background: 'var(--bg-subtle)' }}>
                {['product_code', 'design_no', 'normalized_design_attributes', 'status', 'source_batch_id'].map(k => (
                  <th key={k} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', borderBottom: '1px solid var(--border)' }}>{k.replace(/_/g, ' ')}</th>
                ))}
              </tr></thead>
              <tbody>
                {(pmRows || []).map((r, i) => (
                  <tr key={r.product_code || i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '8px 10px', fontFamily: 'monospace', color: 'var(--text)', fontWeight: 600 }}>{r.product_code || '—'}</td>
                    <td style={{ padding: '8px 10px', color: 'var(--text-2)' }}>{r.design_no || '—'}</td>
                    <td style={{ padding: '8px 10px', fontFamily: 'monospace', fontSize: 10.5, color: 'var(--text-3)', wordBreak: 'break-all' }}>{r.normalized_design_attributes || '—'}</td>
                    <td style={{ padding: '8px 10px', color: 'var(--text-2)' }}>{r.status || '—'}</td>
                    <td style={{ padding: '8px 10px', fontSize: 10.5, color: 'var(--text-3)' }}>{r.source_batch_id || '—'}</td>
                  </tr>
                ))}
                {(!pmRows || pmRows.length === 0) && (
                  <tr><td colSpan={5} data-testid="pm-master-empty" style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>
                    No Product Master rows{batchId.trim() ? ' for this batch' : ''} yet — run a sync from a purchase-packing batch.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </Card>
    </div>
  );
}

// Small status stat cell for the sync panel.
function _Stat({ label, value, tone, testid }) {
  const color = tone === 'ok' ? 'var(--badge-green-text, #16a34a)'
    : tone === 'bad' ? 'var(--badge-red-text, #dc2626)'
    : tone === 'info' ? 'var(--accent)'
    : 'var(--text)';
  return React.createElement('div', {
    'data-testid': testid,
    style: { padding: '10px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6 },
  },
    React.createElement('div', { style: { fontSize: 9.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-3)', marginBottom: 4 } }, label),
    React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color } }, value)
  );
}

// ── Wave 5: New Client mini-modal ────────────────────────────────────────────
// Creates a Customer Master record keyed to the wFirma contractor ID.
// Minimum required: contractor_id (the URL key), bill_to_name, country.
function NewClientModal({ onClose, onSaved }) {
  const [form, setFormNc]  = React.useState({ contractor_id: '', bill_to_name: '', country: '' });
  const [saving, setSaving] = React.useState(false);
  const [error, setError]   = React.useState(null);
  const [errs, setErrs]     = React.useState({});

  function ncSet(k, v) {
    setFormNc(prev => Object.assign({}, prev, { [k]: v }));
    setError(null);
    setErrs(prev => Object.assign({}, prev, { [k]: null }));
  }

  async function ncSave() {
    const ve = {};
    if (!form.contractor_id.trim())  ve.contractor_id  = 'Required — numeric wFirma contractor ID';
    if (!form.bill_to_name.trim())   ve.bill_to_name   = 'Required';
    const c = form.country.trim();
    if (!c)              ve.country = 'Required';
    else if (c.length !== 2) ve.country = '2-letter ISO country code (e.g. PL)';
    if (Object.keys(ve).length) { setErrs(ve); return; }
    setSaving(true);
    const res = await PzApi.saveCustomerMaster(form.contractor_id.trim(), {
      bill_to_name: form.bill_to_name.trim(),
      country: form.country.trim().toUpperCase(),
    });
    setSaving(false);
    if (res.ok) { if (onSaved) onSaved(); onClose(); }
    else setError(res.error || (res.data && res.data.detail) || 'Create failed');
  }

  const ncInpStyle = {
    width: '100%', padding: '8px 10px', fontSize: 13, boxSizing: 'border-box',
    border: '1px solid var(--border)', borderRadius: 6,
    background: 'var(--card)', color: 'var(--text)',
  };

  function ncField(label, key, placeholder, hint) {
    const hasErr = !!errs[key];
    return (
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>{label}</label>
        <input data-testid={'nc-' + key}
          style={Object.assign({}, ncInpStyle, { borderColor: hasErr ? 'var(--badge-red-border, rgba(220,38,38,0.7))' : 'var(--border)' })}
          value={form[key]} placeholder={placeholder || ''}
          onChange={e => ncSet(key, e.target.value)} />
        {hasErr && <div style={{ fontSize: 10, color: 'var(--badge-red-text, rgba(220,38,38,0.9))', marginTop: 2 }}>{errs[key]}</div>}
        {hint && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>}
      </div>
    );
  }

  return (
    <div data-testid="new-client-modal" onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'var(--overlay, rgba(0,0,0,0.45))', zIndex: 1050,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--bg)', borderRadius: 10, maxWidth: 460, width: '100%',
        border: '1px solid var(--border)', boxShadow: '0 12px 40px rgba(0,0,0,0.25)',
        padding: 24, color: 'var(--text)',
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>New Client</div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 16 }}>
          Creates a Customer Master record. Use Edit for full field access after creation.
        </div>
        {ncField('wFirma contractor ID *', 'contractor_id', 'e.g. 12345678',
          'Numeric ID from wFirma (Settings → Contractors → ID column)')}
        {ncField('Company name *', 'bill_to_name', 'Legal company name')}
        {ncField('Country * (ISO-2)', 'country', 'PL')}
        {error && (
          <div style={{ marginBottom: 12, fontSize: 12, color: 'var(--badge-red-text, rgba(220,38,38,0.9))', padding: '8px 10px', background: 'var(--badge-red-bg, rgba(220,38,38,0.08))', border: '1px solid var(--badge-red-border, rgba(220,38,38,0.2))', borderRadius: 6 }}>
            {error}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Btn variant="outline" small onClick={onClose} data-testid="nc-cancel">Cancel</Btn>
          <Btn variant="gold" small onClick={ncSave} disabled={saving} data-testid="nc-save">
            {saving ? 'Creating...' : 'Save to Customer Master'}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ── Wave 5: Import CSV preview / apply modal ──────────────────────────────────
function _ImportPreviewModal({ entityId, preview, applying, onApply, onClose }) {
  const d = preview || {};
  const rejected = d.rejected || [];
  const dupAdvisories = d.duplicate_vat_advisories || [];
  return (
    <div data-testid="import-preview-modal" onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'var(--overlay, rgba(0,0,0,0.45))', zIndex: 1050,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--bg)', borderRadius: 10, maxWidth: 560, width: '100%', maxHeight: '80vh',
        overflowY: 'auto', border: '1px solid var(--border)', boxShadow: '0 12px 40px rgba(0,0,0,0.25)',
        padding: 24, color: 'var(--text)',
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Import CSV — preview</div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 14 }}>
          Dry-run complete. Review, then click <b>Apply import</b> to write changes.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: 14 }}>
          {[['Total rows', d.total_rows, 'import-preview-total'], ['Will create', d.created, 'import-preview-created'], ['Will update', d.updated, 'import-preview-updated'], ['Skipped', d.skipped, 'import-preview-skipped']].map(pair => (
            <div key={pair[0]} style={{ padding: '10px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6 }}>
              <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-3)', marginBottom: 4 }}>{pair[0]}</div>
              <div data-testid={pair[2]} style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>{pair[1] != null ? pair[1] : '—'}</div>
            </div>
          ))}
        </div>
        {rejected.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-red-text, rgba(220,38,38,0.9))', marginBottom: 6 }}>
              {rejected.length} rejected row(s)
            </div>
            <div style={{ maxHeight: 120, overflowY: 'auto', fontSize: 11 }}>
              {rejected.map((r, i) => (
                <div key={i} style={{ padding: '3px 0', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-2)' }}>
                  Row {r.row}: {r.reason || r.error || String(r)}
                </div>
              ))}
            </div>
          </div>
        )}
        {dupAdvisories.length > 0 && (
          <div style={{ marginBottom: 12, padding: 10, background: 'var(--badge-amber-bg, rgba(212,168,83,0.08))', border: '1px solid var(--badge-amber-border, rgba(212,168,83,0.3))', borderRadius: 6 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-2)', marginBottom: 4 }}>
              {dupAdvisories.length} duplicate NIP advisory/ies (advisory only — will still import)
            </div>
            {dupAdvisories.slice(0, 5).map((a, i) => (
              <div key={i} style={{ fontSize: 10, color: 'var(--text-3)', marginBottom: 1 }}>
                Row {a.row}: NIP {a.nip} exists in contractor IDs {(a.existing_contractor_ids || []).join(', ')}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Btn variant="outline" small onClick={onClose} data-testid="import-cancel">Cancel</Btn>
          <Btn variant="gold" small onClick={onApply} disabled={applying} data-testid="import-apply">
            {applying ? 'Applying...' : 'Apply import (' + ((d.created || 0) + (d.updated || 0)) + ' rows)'}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ── Wave 5: Soft-delete confirm dialog ────────────────────────────────────────
function _DeleteConfirmMini({ record, entityId, onConfirm, onCancel }) {
  const label = entityId === 'clients'
    ? (record.bill_to_name || record.bill_to_contractor_id || record.id)
    : entityId === 'designs'
    ? (record.display_name || record.design_code)
    : entityId === 'hs'
    ? (record.hs_code || record.id)
    : entityId === 'units'
    ? (record.code || record.id)
    : entityId === 'incoterms'
    ? (record.code || record.id)
    : entityId === 'carriers'
    ? (record.carrier_code || record.id)
    : entityId === 'vat'
    ? (record.rate_code || record.id)
    : entityId === 'fx'
    ? ((record.from_currency && record.to_currency) ? (record.from_currency + '→' + record.to_currency) : record.id)
    : (record.name || record.id);
  return (
    <div data-testid="delete-confirm-dialog" onClick={onCancel} style={{
      position: 'fixed', inset: 0, zIndex: 1100, background: 'var(--overlay, rgba(0,0,0,0.45))',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8,
        maxWidth: 400, width: '100%', padding: 20,
        boxShadow: '0 8px 30px rgba(0,0,0,0.25)', color: 'var(--text)',
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>Soft-delete record?</div>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 16 }}>
          <b>{label}</b> will be soft-deleted and hidden from default lists. It can be restored later.
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Btn variant="outline" small onClick={onCancel} data-testid="delete-confirm-cancel">Cancel</Btn>
          <Btn variant="danger" small onClick={onConfirm} data-testid="delete-confirm-ok">
            Soft-delete
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ── Wave 6: Edit local overlay for a product_master row ──────────────────────
// Writes to product_local (augmentation only). NEVER modifies product_master.
function ProductOverlayEditModal({ productCode, existing, onClose, onSaved }) {
  var init = existing || {};
  var [form, setFormOv] = React.useState({
    hs_code_override: init.hs_code_override || '',
    unit_override:    init.unit_override    || '',
    design_code_link: init.design_code_link || '',
    notes:            init.notes            || '',
    active:           init.active !== false,
  });
  var [saving, setSaving] = React.useState(false);
  var [error, setError]   = React.useState(null);

  async function save() {
    setSaving(true); setError(null);
    const res = await PzApi.saveProductLocal(productCode, {
      hs_code_override:  form.hs_code_override.trim() || null,
      unit_override:     form.unit_override.trim()    || null,
      design_code_link:  form.design_code_link.trim() || null,
      notes:             form.notes.trim()            || null,
      active:            form.active,
    });
    setSaving(false);
    if (res.ok) { if (onSaved) onSaved(); onClose(); }
    else setError(res.error || (res.data && res.data.detail) || 'Save failed');
  }

  function ovField(label, key, hint) {
    return (
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>{label}</label>
        <input data-testid={'ov-' + key} value={form[key]}
          style={{ width: '100%', padding: '8px 10px', fontSize: 13, boxSizing: 'border-box', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--card)', color: 'var(--text)' }}
          onChange={e => setFormOv(prev => Object.assign({}, prev, { [key]: e.target.value }))} />
        {hint && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>}
      </div>
    );
  }

  return (
    <div data-testid="product-overlay-edit-modal" onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'var(--overlay, rgba(0,0,0,0.45))', zIndex: 1050,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--bg)', borderRadius: 10, maxWidth: 480, width: '100%',
        border: '1px solid var(--border)', boxShadow: '0 12px 40px rgba(0,0,0,0.25)',
        padding: 24, color: 'var(--text)',
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Edit Local Overlay — {productCode}</div>
        <div style={{ fontSize: 11, color: 'var(--badge-amber-text, #92400e)', marginBottom: 14, padding: '6px 10px', background: 'var(--badge-amber-bg, rgba(212,168,83,0.1))', border: '1px solid var(--badge-amber-border, rgba(212,168,83,0.3))', borderRadius: 6 }}>
          Edits the <b>local overlay</b> (augmentation: HS code, unit, design link, notes). The Product Master is <b>read-only</b>.
        </div>
        {ovField('HS code override', 'hs_code_override', 'Leave blank to use the default from HS Codes tab')}
        {ovField('Unit override', 'unit_override', 'Leave blank to use the product default')}
        {ovField('Design code link', 'design_code_link', 'Link to a Design in the Designs tab')}
        {ovField('Notes', 'notes')}
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-2)', marginBottom: 14 }}>
          <input type="checkbox" data-testid="ov-active" checked={form.active}
            onChange={e => setFormOv(prev => Object.assign({}, prev, { active: e.target.checked }))} />
          Active overlay
        </label>
        {error && <div style={{ marginBottom: 12, fontSize: 12, color: 'var(--badge-red-text)', padding: '6px 10px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Btn variant="outline" small onClick={onClose} data-testid="ov-cancel">Cancel</Btn>
          <Btn variant="gold" small onClick={save} disabled={saving} data-testid="ov-save">
            {saving ? 'Saving...' : 'Save Local Overlay'}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ── Wave 6: Create product in wFirma + adopt into Product Master ──────────────
// Fiscal-gated: 403 = WFIRMA_CREATE_PRODUCT_ALLOWED is false.
// 409 = product already exists in wFirma → offer Adopt only path.
function ProductAdoptModal({ productCode, showToast, onClose, onSaved }) {
  var [form, setFormAd]     = React.useState({ item_type: '', description_en: '' });
  var [saving, setSaving]   = React.useState(false);
  var [error, setError]     = React.useState(null);
  var [adoptOnly, setAdoptOnly] = React.useState(false);
  var [confirming, setConfirming] = React.useState(false);

  async function doCreate() {
    if (!form.item_type.trim()) { setError('Item type is required'); return; }
    setSaving(true); setError(null);
    const res = await PzApi.wfirmaGoodsCreateAndAdopt(productCode, {
      item_type:      form.item_type.trim(),
      description_en: form.description_en.trim() || undefined,
    });
    setSaving(false);
    if (res.ok) {
      if (showToast) showToast('Product created and adopted in wFirma', 'ok');
      if (onSaved) onSaved(); onClose();
    } else {
      var msg = (res.data && res.data.detail) ? String(res.data.detail) : (res.error || '');
      if (res.status === 403 || msg.toLowerCase().includes('block') || msg.toLowerCase().includes('not allowed')) {
        setError('wFirma product creation is disabled — enable WFIRMA_CREATE_PRODUCT_ALLOWED in the backend configuration');
      } else if (res.status === 409 || msg.toLowerCase().includes('already_in_wfirma') || msg.toLowerCase().includes('already exists')) {
        setError('Product already exists in wFirma — use the Adopt button below instead');
        setAdoptOnly(true);
      } else {
        setError(msg || 'Create & adopt failed');
      }
    }
  }

  async function doAdopt() {
    setSaving(true); setError(null);
    const res = await PzApi.wfirmaGoodsAdopt(productCode);
    setSaving(false);
    if (res.ok) {
      if (showToast) showToast('Product adopted from wFirma', 'ok');
      if (onSaved) onSaved(); onClose();
    } else {
      var msg = (res.data && res.data.detail) ? String(res.data.detail) : (res.error || '');
      if (res.status === 403 || msg.toLowerCase().includes('block') || msg.toLowerCase().includes('not allowed')) {
        setError('wFirma adopt is disabled by the backend configuration');
      } else {
        setError(msg || 'Adopt failed');
      }
    }
  }

  return (
    <div data-testid="product-adopt-modal" onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'var(--overlay, rgba(0,0,0,0.45))', zIndex: 1050,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--bg)', borderRadius: 10, maxWidth: 460, width: '100%',
        border: '1px solid var(--border)', boxShadow: '0 12px 40px rgba(0,0,0,0.25)',
        padding: 24, color: 'var(--text)',
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Create & adopt in wFirma — {productCode}</div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 16 }}>
          Creates the product in wFirma and adopts it into the Product Master. Fiscal-gated — requires WFIRMA_CREATE_PRODUCT_ALLOWED.
        </div>
        {!adoptOnly && (
          <>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>Item type *</label>
              <input data-testid="adopt-item-type"
                style={{ width: '100%', padding: '8px 10px', fontSize: 13, boxSizing: 'border-box', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--card)', color: 'var(--text)' }}
                value={form.item_type} placeholder="e.g. jewellery, ring, bracelet"
                onChange={e => setFormAd(prev => Object.assign({}, prev, { item_type: e.target.value }))} />
            </div>
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>Description (EN) — optional</label>
              <input data-testid="adopt-description-en"
                style={{ width: '100%', padding: '8px 10px', fontSize: 13, boxSizing: 'border-box', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--card)', color: 'var(--text)' }}
                value={form.description_en} placeholder="English product description"
                onChange={e => setFormAd(prev => Object.assign({}, prev, { description_en: e.target.value }))} />
            </div>
          </>
        )}
        {confirming && !adoptOnly && (
          <div data-testid="adopt-confirm-block" style={{ marginBottom: 12, padding: '10px 12px', background: 'var(--badge-amber-bg, rgba(212,168,83,0.1))', border: '1px solid var(--badge-amber-border, rgba(212,168,83,0.3))', borderRadius: 6, fontSize: 12, color: 'var(--badge-amber-text, #92400e)' }}>
            Create product <b>{productCode}</b> in wFirma with item type <b>'{form.item_type.trim()}'</b>? This writes to the live wFirma ERP.
          </div>
        )}
        {error && <div data-testid="adopt-error" style={{ marginBottom: 12, fontSize: 12, color: 'var(--badge-red-text)', padding: '8px 10px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Btn variant="outline" small onClick={onClose} data-testid="adopt-cancel">Cancel</Btn>
          {adoptOnly ? (
            <Btn variant="gold" small onClick={doAdopt} disabled={saving} data-testid="adopt-only-btn">
              {saving ? 'Adopting...' : 'Adopt from wFirma'}
            </Btn>
          ) : confirming ? (
            <>
              <Btn variant="outline" small onClick={() => setConfirming(false)} data-testid="adopt-back">Back</Btn>
              <Btn variant="gold" small onClick={doCreate} disabled={saving} data-testid="btn-create-adopt-confirm">
                {saving ? 'Creating...' : 'Confirm — create in wFirma'}
              </Btn>
            </>
          ) : (
            <Btn variant="gold" small onClick={() => {
              if (!form.item_type.trim()) { setError('Item type is required'); return; }
              setError(null);
              setConfirming(true);
            }} disabled={saving} data-testid="adopt-create-btn">
              Create &amp; adopt in wFirma
            </Btn>
          )}
        </div>
      </div>
    </div>
  );
}

function MasterPage() {
  const [entity, setEntity] = React.useState('clients');
  const [role, setRole] = React.useState('admin');
  const [search, setSearch] = React.useState('');
  // Sprint 38b: record selected for the read-only View detail modal (null = closed).
  const [viewRecord, setViewRecord] = React.useState(null);
  // Step 3: record selected for Client Detail edit modal (null = closed).
  const [editRecord, setEditRecord] = React.useState(null);
  // Phase 3B: contractor scan state (clients tab only).
  const [scanStatus, setScanStatus] = React.useState(null);
  const [scanRunning, setScanRunning] = React.useState(false);
  // Box Profile master: edit/create modal record (null = closed, {} = new).
  const [boxEdit, setBoxEdit] = React.useState(null);
  const [seedingBoxes, setSeedingBoxes] = React.useState(false);

  // ── Wave 5 state ──────────────────────────────────────────────────────────
  // supplierModal: null (closed) | { supplierId: null (create) | id (edit) }
  const [supplierModal, setSupplierModal]         = React.useState(null);
  const [showNewClient, setShowNewClient]         = React.useState(false);
  // importState: null | { entityId, file, preview }
  const [importState, setImportState]             = React.useState(null);
  const [importApplying, setImportApplying]       = React.useState(false);
  // deleteConfirm: null | { entityId, record }
  const [deleteConfirm, setDeleteConfirm]         = React.useState(null);
  const [wfirmaSyncClients, setWfirmaSyncClients]     = React.useState({
    previewing: false, applying: false, proposals: null, selectedIds: [], error: null,
  });
  const [wfirmaSyncSuppliers, setWfirmaSyncSuppliers] = React.useState({
    previewing: false, applying: false, proposals: null, selectedIds: [], error: null,
  });
  // mpToast: null | { msg, type: 'ok' | 'error' }
  const [mpToast, setMpToast]                     = React.useState(null);
  // reloadTick: bumped by handleReload to re-trigger the load effect after write operations
  const [reloadTick, setReloadTick]               = React.useState(0);

  // ── Wave 6 state ──────────────────────────────────────────────────────────
  // productOverlayCodes: Set of product_codes that have a product_local row (overlay indicator)
  const [productOverlayCodes, setProductOverlayCodes] = React.useState(new Set());
  // productOverlayData: map of product_code → product_local row (for prefilling overlay edit)
  const [productOverlayData, setProductOverlayData]   = React.useState({});
  // productOverlayEdit: null (closed) | { product_code, overlay: row|null }
  const [productOverlayEdit, setProductOverlayEdit]   = React.useState(null);
  // productAdoptModal: null (closed) | { product_code }
  const [productAdoptModal, setProductAdoptModal]     = React.useState(null);
  // designModal: null (closed) | { designCode: null (create) | string (edit) }
  const [designModal, setDesignModal]                 = React.useState(null);
  // designDeleteConfirm: null (closed) | design record
  const [designDeleteConfirm, setDesignDeleteConfirm] = React.useState(null);

  // ── Wave 7 state ──────────────────────────────────────────────────────────
  // capabilities: null (not loaded) | { capabilities: {}, flags: {} } from getMasterCapabilities
  const [capabilities, setCapabilities]             = React.useState(null);
  // masterEditModal: null | { domain, record } (null record = create mode)
  const [masterEditModal, setMasterEditModal]       = React.useState(null);
  // userActionConfirm: null | { action: 'approve'|'reject'|'activate'|'deactivate', userId, label }
  const [userActionConfirm, setUserActionConfirm]   = React.useState(null);
  // userSetRole: null | { userId, currentRole }
  const [userSetRole, setUserSetRole]               = React.useState(null);
  // userActionRunning: true while user admin action is in flight
  const [userActionRunning, setUserActionRunning]   = React.useState(false);

  // Per-entity data cache: { entityId: { records: [], loading: bool, error: string|null } }
  const [cache, setCache] = React.useState({});

  const perms = ROLE_MATRIX[role];
  // Wave 7: per-entity capability descriptor from contract (null if not loaded)
  const capForEntity = (capabilities && capabilities.capabilities && capabilities.capabilities[entity]) || null;
  const columns = ENTITY_COLUMNS[entity] || [];
  const currentEntity = ENTITY_TYPES.find(e => e.id === entity);

  // Derive state for current entity
  const entityState = cache[entity] || { records: [], loading: false, error: null };

  // ── Load entity data on tab switch
  React.useEffect(() => {
    // Roles: build from capability contract when available, fallback to STATIC_ROLES_NAMES.
    // capabilities is in the deps so re-entering or staying on the Roles tab after the
    // contract loads will automatically render the real values instead of the fallback.
    if (entity === 'roles') {
      var vals = (capabilities && capabilities.capabilities && capabilities.capabilities.roles && capabilities.capabilities.roles.values) || STATIC_ROLES_NAMES;
      var roleRows = vals.map(function(v) {
        return { role: (typeof v === 'string' ? v : (v.name || v.role || String(v))), source: 'System-defined (auth/service.py)' };
      });
      setCache(prev => ({ ...prev, roles: { records: roleRows, loading: false, error: null } }));
      return;
    }

    const api = _entityApi(entity);
    if (!api) return;

    // Skip if already loaded
    if (cache[entity] && cache[entity].records.length > 0 && !cache[entity].error) return;

    // Mark loading
    setCache(prev => ({ ...prev, [entity]: { records: [], loading: true, error: null } }));

    api.fetch().then(res => {
      if (res.ok) {
        const records = api.extract(res.data);
        setCache(prev => ({ ...prev, [entity]: { records, loading: false, error: null } }));
      } else {
        setCache(prev => ({ ...prev, [entity]: { records: [], loading: false, error: res.error || 'Failed to load' } }));
      }
    }).catch(err => {
      setCache(prev => ({ ...prev, [entity]: { records: [], loading: false, error: String(err) } }));
    });
  }, [entity, reloadTick, capabilities]);

  // ── Wave 6: load product_local overlay Set when on the products tab
  React.useEffect(() => {
    if (entity !== 'products') return;
    PzApi.listProductLocal().then(res => {
      if (res.ok) {
        const items = (res.data && res.data.items) || [];
        const codeSet = new Set(items.map(i => i.product_code));
        const dataMap = {};
        items.forEach(i => { dataMap[i.product_code] = i; });
        setProductOverlayCodes(codeSet);
        setProductOverlayData(dataMap);
      }
    }).catch(() => {});
  }, [entity, reloadTick]);

  // ── Wave 7: load capability contract once on mount ────────────────────────
  React.useEffect(function() {
    PzApi.getMasterCapabilities().then(function(res) {
      if (res.ok) setCapabilities(res.data);
    }).catch(function() {});
  }, []);

  // ── Filtered records
  const records = (entityState.records || []).filter(r => {
    if (!search) return true;
    return Object.values(r).some(v => v != null && String(v).toLowerCase().includes(search.toLowerCase()));
  });

  // ── Sidebar count
  const sidebarCount = (eid) => {
    const st = cache[eid];
    if (!st) return '...';
    if (st.loading) return '...';
    if (st.error) return '!';
    return st.records.length;
  };

  // ── Determine disabled reason for write buttons
  const writeDisabledReason = (eid) => {
    if (eid === 'roles')    return ROLES_DISABLED_REASON;
    if (eid === 'users')    return USERS_WRITE_DISABLED_REASON;
    if (eid === 'products') return 'Product CSV export/import is not available — products enter via Product Master sync from a purchase batch';
    if (eid === 'designs')  return 'Design CSV export/import is not available in this wave — manage designs individually via Create/Edit/Delete buttons';
    // Wave 7: use capability contract reason_unavailable when available
    if (capabilities && capabilities.capabilities && capabilities.capabilities[eid]) {
      const cap = capabilities.capabilities[eid];
      if (!cap.available && cap.reason_unavailable) return cap.reason_unavailable;
    }
    return WRITE_DISABLED_REASON;
  };

  // ── Reload current entity
  // Deletes cache[entity] so the load effect's "skip if already loaded" guard passes,
  // then bumps reloadTick to actually re-run the effect.
  const handleReload = () => {
    setCache(prev => { const n = { ...prev }; delete n[entity]; return n; });
    setReloadTick(t => t + 1);
  };

  // ── Phase 3B: contractor scan callbacks (clients tab only)
  const loadScanStatus = React.useCallback(async () => {
    const res = await PzApi.getContractorScanStatus();
    if (res.ok) setScanStatus(res.data.scan);
  }, []);

  React.useEffect(() => {
    if (entity === 'clients') loadScanStatus();
  }, [entity, loadScanStatus]);

  const runFullScan = React.useCallback(async () => {
    setScanRunning(true);
    const res = await PzApi.runContractorScan();
    setScanRunning(false);
    if (res.ok) {
      setScanStatus(res.data.scan);
      // Reload clients table to reflect any newly created records
      setCache(prev => {
        const next = { ...prev };
        delete next['clients'];
        return next;
      });
    }
  }, []);

  // ── Wave 5: toast auto-clear ──────────────────────────────────────────────
  React.useEffect(() => {
    if (!mpToast) return;
    const t = setTimeout(() => setMpToast(null), 4500);
    return () => clearTimeout(t);
  }, [mpToast]);

  // ── Wave 5: Export CSV (triggers browser download via PzApi._download) ────
  const handleExportCsv = async (eid) => {
    let res;
    if (eid === 'clients')        res = await PzApi.exportCustomersCsv();
    else if (eid === 'suppliers') res = await PzApi.exportSuppliersCsv();
    else return;
    if (res && !res.ok) setMpToast({ msg: 'Export failed: ' + (res.error || 'Unknown error'), type: 'error' });
  };

  // ── Wave 5: Import CSV — dry-run preview, then apply ─────────────────────
  const handleImportSelect = async (eid, file) => {
    if (!file) return;
    setImportApplying(false);
    let res;
    if (eid === 'clients')        res = await PzApi.importCustomersCsv(file, false);
    else if (eid === 'suppliers') res = await PzApi.importSuppliersCsv(file, false);
    if (!res) return;
    if (res.ok) setImportState({ entityId: eid, file, preview: res.data });
    else setMpToast({ msg: 'Import preview failed: ' + (res.error || 'Unknown error'), type: 'error' });
  };

  const handleImportApply = async () => {
    if (!importState) return;
    setImportApplying(true);
    let res;
    if (importState.entityId === 'clients')        res = await PzApi.importCustomersCsv(importState.file, true);
    else if (importState.entityId === 'suppliers') res = await PzApi.importSuppliersCsv(importState.file, true);
    setImportApplying(false);
    if (res && res.ok) {
      const d = res.data || {};
      setMpToast({
        msg: 'Import applied: ' + (d.created || 0) + ' created, ' + (d.updated || 0) + ' updated, ' + (d.skipped || 0) + ' skipped, ' + ((d.rejected || []).length) + ' rejected',
        type: 'ok',
      });
      setImportState(null);
      handleReload();
    } else {
      setMpToast({ msg: 'Import apply failed: ' + (res ? (res.error || 'Unknown error') : 'No response'), type: 'error' });
    }
  };

  // ── Wave 5 / Wave 7: Soft delete ─────────────────────────────────────────
  const handleDeleteRecord = async (eid, record) => {
    let res;
    if (eid === 'clients') {
      const key = record.bill_to_contractor_id || record.id;
      res = await PzApi.deleteCustomerMaster(key, false);
    } else if (eid === 'suppliers') {
      res = await PzApi.deleteSupplier(record.id, false);
    } else if (eid === 'hs') {
      res = await PzApi.deleteHsCode(record.hs_code, false);
    } else if (eid === 'units') {
      res = await PzApi.deleteUnit(record.code, false);
    } else if (eid === 'incoterms') {
      res = await PzApi.deleteIncoterm(record.code, false);
    } else if (eid === 'carriers') {
      res = await PzApi.deleteCarrierConfig(record.carrier_code, false);
    } else if (eid === 'vat') {
      res = await PzApi.deleteVatConfig(record.vat_id || record.id, false);
    } else if (eid === 'fx') {
      res = await PzApi.deleteFxRate(record.fx_id || record.id, false);
    }
    setDeleteConfirm(null);
    if (res && res.ok) {
      setMpToast({ msg: 'Record soft-deleted', type: 'ok' });
      handleReload();
    } else {
      setMpToast({ msg: 'Delete failed: ' + (res ? (res.error || 'Unknown') : 'No response'), type: 'error' });
    }
  };

  // ── Wave 5: wFirma sync preview → apply ──────────────────────────────────
  const handleWfirmaSyncPreview = async (eid) => {
    const setter = eid === 'clients' ? setWfirmaSyncClients : setWfirmaSyncSuppliers;
    setter(s => Object.assign({}, s, { previewing: true, proposals: null, error: null, selectedIds: [] }));
    let res;
    if (eid === 'clients')        res = await PzApi.previewWfirmaSyncCustomer();
    else if (eid === 'suppliers') res = await PzApi.previewWfirmaSyncSupplier();
    if (res && res.ok) {
      setter(s => Object.assign({}, s, { previewing: false, proposals: res.data.proposals || [] }));
    } else {
      setter(s => Object.assign({}, s, { previewing: false, error: (res && res.error) || 'Preview failed' }));
    }
  };

  // ── Wave 6: soft-delete a design ─────────────────────────────────────────
  const handleDeleteDesign = async (record) => {
    const res = await PzApi.deleteDesign(record.design_code, false); // soft delete
    setDesignDeleteConfirm(null);
    if (res && res.ok) {
      setMpToast({ msg: 'Design soft-deleted', type: 'ok' });
      handleReload();
    } else {
      setMpToast({ msg: 'Delete failed: ' + (res ? (res.error || 'Unknown') : 'No response'), type: 'error' });
    }
  };

  const handleWfirmaSyncApply = async (eid) => {
    const syncData = eid === 'clients' ? wfirmaSyncClients : wfirmaSyncSuppliers;
    const setter   = eid === 'clients' ? setWfirmaSyncClients : setWfirmaSyncSuppliers;
    if (!syncData.selectedIds.length) return;
    setter(s => Object.assign({}, s, { applying: true, error: null }));
    let res;
    if (eid === 'clients')        res = await PzApi.applyWfirmaSyncCustomer(syncData.selectedIds);
    else if (eid === 'suppliers') res = await PzApi.applyWfirmaSyncSupplier(syncData.selectedIds);
    setter(s => Object.assign({}, s, { applying: false }));
    if (res && res.ok) {
      setMpToast({ msg: 'wFirma sync applied successfully — reloading...', type: 'ok' });
      setter(s => Object.assign({}, s, { proposals: null, selectedIds: [] }));
      handleReload();
    } else {
      setter(s => Object.assign({}, s, { error: (res && res.error) || 'Apply failed' }));
    }
  };

  return (
    <div data-testid="master-data-page" style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Role banner */}
      <div style={{ padding: 12, background: 'rgba(212,168,83,0.08)', border: '1px solid rgba(212,168,83,0.3)', borderRadius: 6, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Acting as role</div>
        <div style={{ display: 'flex', gap: 4 }}>
          {Object.keys(ROLE_MATRIX).map(r => (
            <button key={r} onClick={() => setRole(r)} data-testid={'role-btn-' + r} style={{
              padding: '4px 12px', background: role === r ? 'var(--accent)' : 'transparent',
              border: '1px solid ' + (role === r ? 'var(--accent)' : 'var(--border)'),
              borderRadius: 4, fontSize: 11, fontWeight: 600,
              color: role === r ? 'var(--accent-text)' : 'var(--text-2)', cursor: 'pointer', textTransform: 'capitalize',
            }}>{r}</button>
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
          {perms.create ? '✓ create  ' : '✗ create  '}
          {perms.edit   ? '✓ edit  '   : '✗ edit  '}
          {perms.delete ? '✓ delete  ' : '✗ delete  '}
          {perms.lock   ? '✓ lock'     : '✗ lock'}
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>Final role-to-permission mapping is configured under Master · Roles & Permissions</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 16 }}>
        {/* Sidebar */}
        <Card style={{ padding: 6, height: 'fit-content', position: 'sticky', top: 0 }}>
          {ENTITY_TYPES.map(e => (
            <button key={e.id} data-testid={'entity-tab-' + e.id} onClick={() => { setEntity(e.id); setSearch(''); }} style={{
              width: '100%', padding: '10px 12px', textAlign: 'left',
              background: entity === e.id ? 'var(--bg-subtle)' : 'transparent',
              border: 'none', borderRadius: 4, cursor: 'pointer',
              fontSize: 12, fontWeight: entity === e.id ? 600 : 500,
              color: entity === e.id ? 'var(--text)' : 'var(--text-2)',
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ fontSize: 14 }}>{e.icon}</span>
              <span style={{ flex: 1 }}>{e.label}</span>
              <span data-testid={'count-' + e.id} style={{ fontSize: 10, color: 'var(--text-3)' }}>{sidebarCount(e.id)}</span>
            </button>
          ))}
        </Card>

        {/* Right pane */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, gap: 8, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, fontFamily: '"DM Serif Display", serif', color: 'var(--text)' }}>{currentEntity.label}</div>
              <div data-testid="record-count" style={{ fontSize: 11, color: 'var(--text-3)' }}>
                {entityState.loading ? 'Loading...' : `${records.length} record${records.length === 1 ? '' : 's'}`}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Input data-testid="master-search" value={search} onChange={e => setSearch(e.target.value)} placeholder={'Search ' + currentEntity.label.toLowerCase() + '…'} />
              {(entity === 'clients' || entity === 'suppliers') ? (
                <Btn variant="outline" small data-testid="btn-export-csv"
                  onClick={() => handleExportCsv(entity)}>
                  {'↓'} Export CSV
                </Btn>
              ) : (
                <Btn variant="outline" small disabled title={writeDisabledReason(entity)} data-testid="btn-export-csv">{'↓'} Export CSV</Btn>
              )}
              {(entity === 'clients' || entity === 'suppliers') ? (
                <Btn variant="outline" small data-testid="btn-import-csv"
                  disabled={!perms.create}
                  title={!perms.create ? 'Role has no create permission' : undefined}
                  onClick={() => {
                    const fi = document.createElement('input');
                    fi.type = 'file'; fi.accept = '.csv';
                    fi.onchange = ev => handleImportSelect(entity, ev.target.files && ev.target.files[0]);
                    fi.click();
                  }}>
                  {'↑'} Import CSV
                </Btn>
              ) : (
                <Btn variant="outline" small disabled title={writeDisabledReason(entity)} data-testid="btn-import-csv">{'↑'} Import CSV</Btn>
              )}
              {entity === 'box_profiles' ? (
                <Btn variant="gold" small disabled={!perms.create}
                  title={perms.create ? 'Create a new Box Profile (writes to Box Master)' : 'Role has no create permission'}
                  onClick={() => setBoxEdit({})} data-testid="btn-new-record">
                  + New Box Profile
                </Btn>
              ) : entity === 'clients' ? (
                <Btn variant="gold" small onClick={() => setShowNewClient(true)}
                  disabled={!perms.create}
                  title={perms.create ? 'Create a new Client (writes to Customer Master)' : 'Role has no create permission'}
                  data-testid="btn-new-record">
                  + New Client
                </Btn>
              ) : entity === 'suppliers' ? (
                <Btn variant="gold" small onClick={() => setSupplierModal({ supplierId: null })}
                  disabled={!perms.create}
                  title={perms.create ? 'Create a new Supplier (writes to Supplier Master)' : 'Role has no create permission'}
                  data-testid="btn-new-record">
                  + New Supplier
                </Btn>
              ) : entity === 'products' ? (
                <Btn variant="gold" small disabled
                  title="Products enter via Product Master sync from a purchase batch, then per-row Create &amp; adopt — they are not minted manually here"
                  data-testid="btn-new-record">
                  + New Product
                </Btn>
              ) : entity === 'designs' ? (
                <Btn variant="gold" small onClick={() => setDesignModal({ designCode: null })}
                  disabled={!perms.create}
                  title={perms.create ? 'Create a new Design record (Design Master authority)' : 'Role has no create permission'}
                  data-testid="btn-new-record">
                  + New Design
                </Btn>
              ) : (['hs', 'fx', 'vat', 'carriers', 'incoterms', 'units'].indexOf(entity) !== -1 && capForEntity && capForEntity.available) ? (
                <Btn variant="gold" small
                  disabled={!perms.create}
                  title={perms.create ? 'Create a new ' + currentEntity.singular + ' record' : 'Role has no create permission'}
                  onClick={() => setMasterEditModal({ domain: entity, record: null })}
                  data-testid="btn-new-record">
                  + New {currentEntity.singular}
                </Btn>
              ) : (
                <Btn variant="gold" small disabled title={writeDisabledReason(entity)} data-testid="btn-new-record">
                  + New {currentEntity.singular}
                </Btn>
              )}
              {entity === 'box_profiles' && (
                <Btn variant="outline" small disabled={!perms.create || seedingBoxes}
                  title="Insert the default DHL profiles (DHL-JEWEL-S, DHL-RING, DHL-BRACELET, CUSTOM). Insert-only — never overwrites."
                  onClick={async () => {
                    setSeedingBoxes(true);
                    const res = await PzApi.seedBoxTypeDefaults();
                    setSeedingBoxes(false);
                    if (res.ok) handleReload();
                  }} data-testid="btn-seed-box-defaults">
                  {seedingBoxes ? '⏳ Seeding…' : '⇊ Seed DHL defaults'}
                </Btn>
              )}
              <Btn variant="outline" small onClick={handleReload} data-testid="btn-reload">{'↻'} Reload</Btn>
            </div>
          </div>

          {/* Error state */}
          {entityState.error && (
            <Card data-testid="error-state" style={{ padding: 24, marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 20 }}>{'⚠'}</span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--badge-red-text)' }}>Failed to load {currentEntity.label.toLowerCase()}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>{entityState.error}</div>
                </div>
                <div style={{ flex: 1 }} />
                <Btn variant="outline" small onClick={handleReload}>Retry</Btn>
              </div>
            </Card>
          )}

          {/* Loading state */}
          {entityState.loading && (
            <Card data-testid="loading-state" style={{ padding: 48, textAlign: 'center' }}>
              <div style={{ fontSize: 13, color: 'var(--text-3)' }}>Loading {currentEntity.label.toLowerCase()}...</div>
            </Card>
          )}

          {/* Data table */}
          {!entityState.loading && !entityState.error && (
            <Card style={{ overflow: 'hidden' }}>
              <div style={{ overflowX: 'auto' }}>
                <table data-testid={'table-' + entity} style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: 'var(--bg-subtle)' }}>
                      {columns.map(c => (
                        <th key={c.key} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>
                          {c.label}
                        </th>
                      ))}
                      <th style={{ padding: '10px 12px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((r, ri) => {
                      const api = _entityApi(entity);
                      const rk = api ? api.rowKey(r) : (r.id || ri);
                      return (
                        <tr key={rk} style={{ borderBottom: '1px solid var(--border-subtle)' }}
                          onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                          {columns.map((c, ci) => {
                            const v = r[c.key];
                            return (
                              <td key={c.key} style={{
                                padding: '10px 12px', fontSize: 12,
                                color: ci === 0 ? 'var(--text)' : 'var(--text-2)',
                                fontWeight: ci === 0 ? 600 : 400,
                                fontFamily: c.mono ? 'monospace' : 'inherit',
                              }}>
                                {_renderCell(c, v)}
                              </td>
                            );
                          })}
                          <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                            <div style={{ display: 'inline-flex', gap: 4 }}>
                              <Btn small variant="outline"
                                onClick={() => setViewRecord(r)}
                                title="View full record (read-only)"
                                data-testid="btn-view-record">View</Btn>
                              {entity === 'clients' && (
                                <Btn small variant="gold"
                                  onClick={() => setEditRecord(r)}
                                  disabled={!perms.edit}
                                  title={perms.edit ? 'Edit client record (writes to Customer Master)' : 'Role has no edit permission'}
                                  data-testid="btn-edit-record">Edit</Btn>
                              )}
                              {entity === 'box_profiles' && (
                                <Btn small variant="gold" disabled={!perms.edit}
                                  onClick={() => setBoxEdit(r)}
                                  title={perms.edit ? 'Edit Box Profile (writes to Box Master)' : 'Role has no edit permission'}
                                  data-testid="btn-edit-box-profile">Edit</Btn>
                              )}
                              {entity === 'suppliers' && (
                                <Btn small variant="gold"
                                  onClick={() => setSupplierModal({ supplierId: r.id })}
                                  disabled={!perms.edit}
                                  title={perms.edit ? 'Edit supplier record (writes to Supplier Master)' : 'Role has no edit permission'}
                                  data-testid="btn-edit-supplier">Edit</Btn>
                              )}
                              {(entity === 'clients' || entity === 'suppliers') && (
                                <Btn small variant="outline"
                                  onClick={() => setDeleteConfirm({ entityId: entity, record: r })}
                                  disabled={!perms.delete}
                                  title={perms.delete ? 'Soft-delete this record (can be restored)' : 'Role has no delete permission'}
                                  data-testid="btn-delete-record"
                                  style={{ color: 'var(--badge-red-text, rgba(220,38,38,0.85))', borderColor: 'var(--badge-red-border, rgba(220,38,38,0.3))' }}>
                                  Delete
                                </Btn>
                              )}
                              {entity === 'products' && productOverlayCodes.has(r.product_code) && (
                                <span data-testid="overlay-badge" style={{
                                  display: 'inline-block', padding: '1px 6px', borderRadius: 10, fontSize: 9, fontWeight: 600,
                                  background: 'var(--badge-blue-bg, rgba(59,130,246,0.12))',
                                  color: 'var(--badge-blue-text, #1d4ed8)',
                                  border: '1px solid var(--badge-blue-border, rgba(59,130,246,0.3))',
                                  verticalAlign: 'middle', marginRight: 2,
                                }}>HS/unit</span>
                              )}
                              {entity === 'products' && (
                                <Btn small variant="outline"
                                  onClick={() => setProductOverlayEdit({ product_code: r.product_code, overlay: productOverlayData[r.product_code] || null })}
                                  disabled={!perms.edit}
                                  title={perms.edit ? 'Edit local overlay (HS code / unit / design link) — does NOT modify the read-only Product Master' : 'Role has no edit permission'}
                                  data-testid={`btn-edit-product-overlay-${r.product_code}`}>
                                  Edit overlays
                                </Btn>
                              )}
                              {entity === 'products' && r.status === 'mapping_required' && (
                                <Btn small variant="gold"
                                  onClick={() => setProductAdoptModal({ product_code: r.product_code })}
                                  disabled={!perms.create}
                                  title={perms.create ? 'Create this product in wFirma and adopt (fiscal-gated)' : 'Role has no create permission'}
                                  data-testid={`btn-create-adopt-${r.product_code}`}>
                                  Create &amp; adopt
                                </Btn>
                              )}
                              {entity === 'designs' && (
                                <Btn small variant="gold"
                                  onClick={() => setDesignModal({ designCode: r.design_code })}
                                  disabled={!perms.edit}
                                  title={perms.edit ? 'Edit design record' : 'Role has no edit permission'}
                                  data-testid={`btn-edit-design-${r.design_code}`}>
                                  Edit
                                </Btn>
                              )}
                              {entity === 'designs' && (
                                <Btn small variant="outline"
                                  onClick={() => setDesignDeleteConfirm(r)}
                                  disabled={!perms.delete}
                                  title={perms.delete ? 'Soft-delete this design' : 'Role has no delete permission'}
                                  data-testid={`btn-delete-design-${r.design_code}`}
                                  style={{ color: 'var(--badge-red-text, rgba(220,38,38,0.85))', borderColor: 'var(--badge-red-border, rgba(220,38,38,0.3))' }}>
                                  Delete
                                </Btn>
                              )}
                              {/* Wave 7: Edit for 6 capability-driven CRUD domains */}
                              {(['hs', 'fx', 'vat', 'carriers', 'incoterms', 'units'].indexOf(entity) !== -1 && capForEntity && capForEntity.available) && (
                                <Btn small variant="gold"
                                  disabled={!perms.edit}
                                  title={perms.edit ? 'Edit ' + (currentEntity && currentEntity.singular) : 'Role has no edit permission'}
                                  onClick={() => setMasterEditModal({ domain: entity, record: r })}
                                  data-testid={'btn-edit-' + entity + '-' + rk}>
                                  Edit
                                </Btn>
                              )}
                              {/* FIX D: loading fallback while capabilities contract not yet loaded */}
                              {(['hs', 'fx', 'vat', 'carriers', 'incoterms', 'units'].indexOf(entity) !== -1 && !capForEntity) && (
                                <Btn small disabled title="Loading capabilities…" data-testid={'btn-edit-' + entity + '-loading'}>Edit</Btn>
                              )}
                              {/* Wave 7: Delete for 6 capability-driven CRUD domains (only if delete_route exists) */}
                              {(['hs', 'fx', 'vat', 'carriers', 'incoterms', 'units'].indexOf(entity) !== -1 && capForEntity && capForEntity.available && capForEntity.delete_route) && (
                                <Btn small variant="outline"
                                  disabled={!perms.delete}
                                  title={perms.delete ? 'Soft-delete this record (restorable)' : 'Role has no delete permission'}
                                  onClick={() => setDeleteConfirm({ entityId: entity, record: r })}
                                  data-testid={'btn-delete-' + entity + '-' + rk}
                                  style={{ color: 'var(--badge-red-text, rgba(220,38,38,0.85))', borderColor: 'var(--badge-red-border, rgba(220,38,38,0.3))' }}>
                                  Delete
                                </Btn>
                              )}
                              {/* Wave 7: User admin actions — admin role only */}
                              {entity === 'users' && role === 'admin' && (
                                <React.Fragment>
                                  {r.approval_status === 'pending' && (
                                    <Btn small variant="gold"
                                      onClick={() => setUserActionConfirm({ action: 'approve', userId: r.id, label: r.email || r.full_name })}
                                      data-testid={'btn-approve-user-' + rk}>
                                      Approve
                                    </Btn>
                                  )}
                                  {r.approval_status === 'pending' && (
                                    <Btn small variant="outline"
                                      onClick={() => setUserActionConfirm({ action: 'reject', userId: r.id, label: r.email || r.full_name })}
                                      data-testid={'btn-reject-user-' + rk}
                                      style={{ color: 'var(--badge-red-text, rgba(220,38,38,0.85))', borderColor: 'var(--badge-red-border, rgba(220,38,38,0.3))' }}>
                                      Reject
                                    </Btn>
                                  )}
                                  <Btn small variant="outline"
                                    onClick={() => setUserSetRole({ userId: r.id, currentRole: r.role, userLabel: r.email || r.full_name })}
                                    data-testid={'btn-set-role-user-' + rk}>
                                    Set Role
                                  </Btn>
                                  {r.is_active ? (
                                    <Btn small variant="outline"
                                      onClick={() => setUserActionConfirm({ action: 'deactivate', userId: r.id, label: r.email || r.full_name })}
                                      data-testid={'btn-deactivate-user-' + rk}>
                                      Deactivate
                                    </Btn>
                                  ) : (
                                    <Btn small variant="gold"
                                      onClick={() => setUserActionConfirm({ action: 'activate', userId: r.id, label: r.email || r.full_name })}
                                      data-testid={'btn-activate-user-' + rk}>
                                      Activate
                                    </Btn>
                                  )}
                                </React.Fragment>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    {records.length === 0 && !entityState.loading && (
                      <tr>
                        <td colSpan={columns.length + 1} data-testid="empty-state" style={{ padding: 48, textAlign: 'center', color: 'var(--text-3)' }}>
                          <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.4 }}>{currentEntity.icon}</div>
                          <div style={{ fontSize: 13, fontWeight: 600 }}>No {currentEntity.label.toLowerCase()} found</div>
                          <div style={{ fontSize: 11, marginTop: 4 }}>
                            {entity === 'roles' ? 'Roles are system-defined above' : 'Records will appear here once created in the backend'}
                          </div>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {/* Roles-specific info banner — uses capability contract reason_unavailable when loaded */}
          {entity === 'roles' && (
            <div data-testid="roles-info-banner" style={{ marginTop: 12, padding: 12, background: 'rgba(212,168,83,0.06)', border: '1px solid rgba(212,168,83,0.2)', borderRadius: 6, fontSize: 11, color: 'var(--text-3)' }}>
              {(capForEntity && capForEntity.reason_unavailable)
                ? capForEntity.reason_unavailable
                : 'Roles are system-defined constants. No backend endpoint exists for role CRUD. Role assignment is managed per-user via the Users tab.'}
            </div>
          )}

          {/* Users-specific info banner — shows admin action hint when acting as admin */}
          {entity === 'users' && (
            <div data-testid="users-info-banner" style={{ marginTop: 12, padding: 12, background: 'rgba(212,168,83,0.06)', border: '1px solid rgba(212,168,83,0.2)', borderRadius: 6, fontSize: 11, color: 'var(--text-3)' }}>
              {(capForEntity && capForEntity.note)
                ? capForEntity.note
                : role === 'admin'
                  ? 'Admin user management: approve, reject, set role, activate, deactivate — visible per row above. These actions write to the auth system.'
                  : 'User management actions (approve, reject, role change, activate/deactivate) are visible to admin role only.'}
            </div>
          )}

          {/* Wave 5: Suppliers wFirma sync — preview → select → apply */}
          {entity === 'suppliers' && (
            <div data-testid="wfirma-sync-section-suppliers" style={{ marginTop: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <Btn variant="outline" small
                  onClick={() => handleWfirmaSyncPreview('suppliers')}
                  disabled={wfirmaSyncSuppliers.previewing || wfirmaSyncSuppliers.applying}
                  data-testid="btn-wfirma-sync-suppliers">
                  {wfirmaSyncSuppliers.previewing ? '⏳ Loading...' : '⟳ Sync from wFirma'}
                </Btn>
                {wfirmaSyncSuppliers.proposals !== null && wfirmaSyncSuppliers.selectedIds.length > 0 && (
                  <Btn variant="gold" small
                    onClick={() => handleWfirmaSyncApply('suppliers')}
                    disabled={!perms.edit || wfirmaSyncSuppliers.applying}
                    title={!perms.edit ? 'Role has no edit permission' : undefined}
                    data-testid="btn-wfirma-apply-suppliers">
                    {wfirmaSyncSuppliers.applying ? '⏳ Applying...' : 'Apply ' + wfirmaSyncSuppliers.selectedIds.length + ' selected'}
                  </Btn>
                )}
              </div>
              {wfirmaSyncSuppliers.error && (
                <div style={{ marginTop: 8, padding: '8px 12px', background: 'var(--badge-red-bg, rgba(220,38,38,0.08))', border: '1px solid var(--badge-red-border, rgba(220,38,38,0.2))', borderRadius: 6, fontSize: 11, color: 'var(--badge-red-text, rgba(220,38,38,0.9))' }}>
                  {wfirmaSyncSuppliers.error}
                </div>
              )}
              {wfirmaSyncSuppliers.proposals !== null && (
                <div data-testid="wfirma-sync-proposals-suppliers" style={{ marginTop: 8, border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', fontSize: 11 }}>
                  <div style={{ padding: '6px 12px', background: 'var(--bg-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-3)' }}>{wfirmaSyncSuppliers.proposals.length} proposal{wfirmaSyncSuppliers.proposals.length === 1 ? '' : 's'} from wFirma</span>
                    <Btn variant="ghost" small onClick={() => {
                      const all = wfirmaSyncSuppliers.proposals.filter(p => p.status !== 'skipped_invalid').map(p => p.wfirma_id);
                      setWfirmaSyncSuppliers(s => Object.assign({}, s, { selectedIds: all }));
                    }} data-testid="btn-wfirma-select-all-suppliers">
                      Select all actionable
                    </Btn>
                  </div>
                  <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead><tr style={{ background: 'var(--bg-subtle)' }}>
                        <th style={{ padding: '5px 8px', width: 28 }}></th>
                        {['wFirma ID', 'Name', 'Country', 'Status'].map(h => (
                          <th key={h} style={{ padding: '5px 8px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', borderBottom: '1px solid var(--border)' }}>{h}</th>
                        ))}
                      </tr></thead>
                      <tbody>
                        {wfirmaSyncSuppliers.proposals.map((p, i) => {
                          const actionable = p.status !== 'skipped_invalid';
                          const sel = wfirmaSyncSuppliers.selectedIds.indexOf(p.wfirma_id) !== -1;
                          const statusColor = p.status === 'new_candidate' ? 'var(--badge-green-text)' : p.status === 'matched_existing' ? 'var(--badge-blue-text)' : 'var(--text-3)';
                          return (
                            <tr key={p.wfirma_id || i} style={{ borderBottom: '1px solid var(--border-subtle)', opacity: actionable ? 1 : 0.45 }}>
                              <td style={{ padding: '5px 8px', textAlign: 'center' }}>
                                {actionable && (
                                  <input type="checkbox" checked={sel} data-testid={'wfirma-chk-su-' + (p.wfirma_id || i)}
                                    onChange={() => setWfirmaSyncSuppliers(s => {
                                      const ids = sel ? s.selectedIds.filter(x => x !== p.wfirma_id) : s.selectedIds.concat([p.wfirma_id]);
                                      return Object.assign({}, s, { selectedIds: ids });
                                    })} />
                                )}
                              </td>
                              <td style={{ padding: '5px 8px', fontFamily: 'monospace' }}>{p.wfirma_id || '—'}</td>
                              <td style={{ padding: '5px 8px' }}>{p.name || '—'}</td>
                              <td style={{ padding: '5px 8px' }}>{p.country || '—'}</td>
                              <td style={{ padding: '5px 8px', color: statusColor }}>{(p.status || '—').replace(/_/g, ' ')}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
          {/* Wave 5: Clients wFirma sync — preview → select → apply */}
          {entity === 'clients' && (
            <div data-testid="wfirma-sync-section-clients" style={{ marginTop: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <Btn variant="outline" small
                  onClick={() => handleWfirmaSyncPreview('clients')}
                  disabled={wfirmaSyncClients.previewing || wfirmaSyncClients.applying}
                  data-testid="btn-wfirma-sync-clients">
                  {wfirmaSyncClients.previewing ? '⏳ Loading...' : '⟳ Sync from wFirma'}
                </Btn>
                {wfirmaSyncClients.proposals !== null && wfirmaSyncClients.selectedIds.length > 0 && (
                  <Btn variant="gold" small
                    onClick={() => handleWfirmaSyncApply('clients')}
                    disabled={!perms.edit || wfirmaSyncClients.applying}
                    title={!perms.edit ? 'Role has no edit permission' : undefined}
                    data-testid="btn-wfirma-apply-clients">
                    {wfirmaSyncClients.applying ? '⏳ Applying...' : 'Apply ' + wfirmaSyncClients.selectedIds.length + ' selected'}
                  </Btn>
                )}
                <Btn variant="primary" small onClick={runFullScan} disabled={scanRunning} data-testid="btn-full-contractor-scan">
                  {scanRunning ? '⏳ Scanning…' : '⇅ Full Scan'}
                </Btn>
              </div>
              {wfirmaSyncClients.error && (
                <div style={{ marginTop: 8, padding: '8px 12px', background: 'var(--badge-red-bg, rgba(220,38,38,0.08))', border: '1px solid var(--badge-red-border, rgba(220,38,38,0.2))', borderRadius: 6, fontSize: 11, color: 'var(--badge-red-text, rgba(220,38,38,0.9))' }}>
                  {wfirmaSyncClients.error}
                </div>
              )}
              {wfirmaSyncClients.proposals !== null && (
                <div data-testid="wfirma-sync-proposals-clients" style={{ marginTop: 8, border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', fontSize: 11 }}>
                  <div style={{ padding: '6px 12px', background: 'var(--bg-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-3)' }}>{wfirmaSyncClients.proposals.length} proposal{wfirmaSyncClients.proposals.length === 1 ? '' : 's'} from wFirma</span>
                    <Btn variant="ghost" small onClick={() => {
                      const all = wfirmaSyncClients.proposals.filter(p => p.status !== 'skipped_invalid').map(p => p.wfirma_id);
                      setWfirmaSyncClients(s => Object.assign({}, s, { selectedIds: all }));
                    }} data-testid="btn-wfirma-select-all-clients">
                      Select all actionable
                    </Btn>
                  </div>
                  <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead><tr style={{ background: 'var(--bg-subtle)' }}>
                        <th style={{ padding: '5px 8px', width: 28 }}></th>
                        {['wFirma ID', 'Name', 'Country', 'Status'].map(h => (
                          <th key={h} style={{ padding: '5px 8px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', borderBottom: '1px solid var(--border)' }}>{h}</th>
                        ))}
                      </tr></thead>
                      <tbody>
                        {wfirmaSyncClients.proposals.map((p, i) => {
                          const actionable = p.status !== 'skipped_invalid';
                          const sel = wfirmaSyncClients.selectedIds.indexOf(p.wfirma_id) !== -1;
                          const statusColor = p.status === 'new_candidate' ? 'var(--badge-green-text)' : p.status === 'matched_existing' ? 'var(--badge-blue-text)' : 'var(--text-3)';
                          return (
                            <tr key={p.wfirma_id || i} style={{ borderBottom: '1px solid var(--border-subtle)', opacity: actionable ? 1 : 0.45 }}>
                              <td style={{ padding: '5px 8px', textAlign: 'center' }}>
                                {actionable && (
                                  <input type="checkbox" checked={sel} data-testid={'wfirma-chk-cl-' + (p.wfirma_id || i)}
                                    onChange={() => setWfirmaSyncClients(s => {
                                      const ids = sel ? s.selectedIds.filter(x => x !== p.wfirma_id) : s.selectedIds.concat([p.wfirma_id]);
                                      return Object.assign({}, s, { selectedIds: ids });
                                    })} />
                                )}
                              </td>
                              <td style={{ padding: '5px 8px', fontFamily: 'monospace' }}>{p.wfirma_id || '—'}</td>
                              <td style={{ padding: '5px 8px' }}>{p.name || '—'}</td>
                              <td style={{ padding: '5px 8px' }}>{p.country || '—'}</td>
                              <td style={{ padding: '5px 8px', color: statusColor }}>{(p.status || '—').replace(/_/g, ' ')}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              <ScanStatusPanel status={scanStatus} onRefresh={loadScanStatus} />
            </div>
          )}

          {/* Sprint 38b: VAT sync button — disabled, endpoint missing */}
          {entity === 'vat' && (
            <div data-testid="wfirma-sync-section-vat" style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Btn variant="outline" small disabled title={WFIRMA_VAT_SYNC_DISABLED} data-testid="btn-wfirma-sync-vat">
                {'⟳'} Sync from wFirma
              </Btn>
              <span style={{ fontSize: 11, color: 'var(--badge-amber-text, #92400e)' }}>
                Backend pending: wFirma VAT sync endpoint missing
              </span>
            </div>
          )}

          {/* Slice 1: Product Master Sync panel — Products tab only */}
          {entity === 'products' && <ProductMasterSyncPanel />}

          {/* Wave 7: Capability note banner — FX and VAT render test-pinned disclaimer notes */}
          {(entity === 'fx' || entity === 'vat' || (capForEntity && capForEntity.note)) && (
            <div data-testid={'capability-note-' + entity} style={{
              marginTop: 12, padding: 12, fontSize: 11, color: 'var(--text-2)',
              background: 'var(--badge-blue-bg)', border: '1px solid var(--badge-blue-border)', borderRadius: 6,
            }}>
              {entity === 'fx'
                ? ((capForEntity && capForEntity.note) || 'Reference only — FX Rates in this table are NEVER read by the calculation engine. The engine uses the ZC429/SAD exchange rate from the customs document. This table is for operator reference only.')
                : entity === 'vat'
                ? ((capForEntity && capForEntity.note) || 'Local VAT configuration reference. wFirma invoice VAT codes are not overridden by this table — wFirma manages its own VAT codes independently.')
                : (capForEntity && capForEntity.note)}
            </div>
          )}

          {/* Sprint 38b: Mapping info banner for focus entities */}
          <MappingInfoBanner entityId={entity} />
        </div>
      </div>

      {/* Sprint 38b: read-only record detail modal */}
      <RecordDetailModal
        record={viewRecord}
        entityLabel={currentEntity ? currentEntity.singular : 'Record'}
        onClose={() => setViewRecord(null)}
      />

      {/* Box Profile master: create/edit modal */}
      {boxEdit !== null && (
        <BoxProfileEditModal
          record={boxEdit}
          onClose={() => setBoxEdit(null)}
          onSaved={() => { setBoxEdit(null); handleReload(); }}
        />
      )}

      {/* Step 3: Client Detail edit modal */}
      {editRecord && (
        <ClientDetailModal
          clientKey={editRecord.bill_to_contractor_id || editRecord.id}
          onClose={() => setEditRecord(null)}
          onSaved={() => { setEditRecord(null); handleReload(); }}
        />
      )}

      {/* Wave 5: Supplier edit / create modal */}
      {supplierModal !== null && (
        <SupplierDetailModal
          supplierId={supplierModal.supplierId}
          onClose={() => setSupplierModal(null)}
          onSaved={() => { setSupplierModal(null); handleReload(); }}
        />
      )}

      {/* Wave 5: New Client modal */}
      {showNewClient && (
        <NewClientModal
          onClose={() => setShowNewClient(false)}
          onSaved={() => { setShowNewClient(false); handleReload(); }}
        />
      )}

      {/* Wave 5: Import CSV preview / apply modal */}
      {importState && (
        <_ImportPreviewModal
          entityId={importState.entityId}
          preview={importState.preview}
          applying={importApplying}
          onApply={handleImportApply}
          onClose={() => setImportState(null)}
        />
      )}

      {/* Wave 5: Soft-delete confirm dialog */}
      {deleteConfirm && (
        <_DeleteConfirmMini
          record={deleteConfirm.record}
          entityId={deleteConfirm.entityId}
          onConfirm={() => handleDeleteRecord(deleteConfirm.entityId, deleteConfirm.record)}
          onCancel={() => setDeleteConfirm(null)}
        />
      )}

      {/* Wave 6: Product overlay edit modal */}
      {productOverlayEdit !== null && (
        <ProductOverlayEditModal
          productCode={productOverlayEdit.product_code}
          existing={productOverlayEdit.overlay}
          onClose={() => setProductOverlayEdit(null)}
          onSaved={() => { setProductOverlayEdit(null); handleReload(); }}
        />
      )}

      {/* Wave 6: Product create-and-adopt modal */}
      {productAdoptModal !== null && (
        <ProductAdoptModal
          productCode={productAdoptModal.product_code}
          showToast={(msg, type) => setMpToast({ msg, type })}
          onClose={() => setProductAdoptModal(null)}
          onSaved={() => { setProductAdoptModal(null); handleReload(); }}
        />
      )}

      {/* Wave 6: Design detail create / edit modal */}
      {designModal !== null && (
        <DesignDetailModal
          designCode={designModal.designCode}
          onClose={() => setDesignModal(null)}
          onSaved={() => { setDesignModal(null); handleReload(); }}
        />
      )}

      {/* Wave 6: Design soft-delete confirm */}
      {designDeleteConfirm !== null && (
        <_DeleteConfirmMini
          record={designDeleteConfirm}
          entityId="designs"
          onConfirm={() => handleDeleteDesign(designDeleteConfirm)}
          onCancel={() => setDesignDeleteConfirm(null)}
        />
      )}

      {/* Wave 7: Generic master record create/edit modal */}
      {masterEditModal !== null && (
        <MasterRecordEditModal
          domain={masterEditModal.domain}
          capability={capabilities && capabilities.capabilities && capabilities.capabilities[masterEditModal.domain]}
          columns={ENTITY_COLUMNS[masterEditModal.domain] || []}
          record={masterEditModal.record}
          onClose={() => setMasterEditModal(null)}
          onSaved={() => { setMasterEditModal(null); handleReload(); }}
        />
      )}

      {/* Wave 7: User admin action confirm dialog */}
      {userActionConfirm !== null && (
        <div data-testid="user-action-confirm" onClick={() => setUserActionConfirm(null)} style={{
          position: 'fixed', inset: 0, zIndex: 1150,
          background: 'var(--overlay, rgba(0,0,0,0.45))',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
        }}>
          <div onClick={e => e.stopPropagation()} style={{
            background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
            maxWidth: 400, width: '100%', padding: 20,
            boxShadow: '0 8px 30px var(--shadow-heavy, rgba(0,0,0,0.25))',
            color: 'var(--text)',
          }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8, textTransform: userActionConfirm.action === 'set_role' ? 'none' : 'capitalize' }}>
              {userActionConfirm.action === 'set_role' ? 'Change user role?' : (userActionConfirm.action + ' user?')}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 16 }}>
              {userActionConfirm.action === 'set_role'
                ? <span>Change role of <b>{userActionConfirm.label}</b> to <b>{userActionConfirm.newRole}</b>? This is an access change.</span>
                : <span><b>{userActionConfirm.label}</b> — confirm {userActionConfirm.action}.</span>}
            </div>
            {userActionRunning && (
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }}>Working...</div>
            )}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <Btn variant="outline" small onClick={() => setUserActionConfirm(null)}
                disabled={userActionRunning} data-testid="user-action-cancel">Cancel</Btn>
              <Btn variant="gold" small disabled={userActionRunning}
                data-testid="user-action-ok"
                onClick={async () => {
                  setUserActionRunning(true);
                  let res;
                  try {
                    const { action, userId } = userActionConfirm;
                    if (action === 'approve')    res = await PzApi.approveUser(userId);
                    if (action === 'reject')     res = await PzApi.rejectUser(userId);
                    if (action === 'activate')   res = await PzApi.activateUser(userId);
                    if (action === 'deactivate') res = await PzApi.deactivateUser(userId);
                    if (action === 'set_role')   res = await PzApi.setUserRole(userId, userActionConfirm.newRole);
                  } catch (ex) { res = { ok: false, error: String(ex) }; }
                  const confirmedAction = userActionConfirm.action;
                  const confirmedNewRole = userActionConfirm.newRole;
                  setUserActionRunning(false);
                  setUserActionConfirm(null);
                  if (res && res.ok) {
                    setMpToast({
                      msg: confirmedAction === 'set_role'
                        ? 'Role changed to ' + confirmedNewRole
                        : 'User ' + confirmedAction + ' applied',
                      type: 'ok',
                    });
                    handleReload();
                  } else {
                    setMpToast({
                      msg: confirmedAction === 'set_role'
                        ? 'Set role to ' + confirmedNewRole + ' failed: ' + (res ? (res.error || 'Unknown') : 'No response')
                        : 'Action failed: ' + (res ? (res.error || 'Unknown') : 'No response'),
                      type: 'error',
                    });
                  }
                }}>
                {userActionConfirm.action === 'set_role' ? 'Confirm role change' : 'Confirm ' + userActionConfirm.action}
              </Btn>
            </div>
          </div>
        </div>
      )}

      {/* Wave 7: User set-role picker modal */}
      {userSetRole !== null && (
        <div data-testid="user-set-role-modal" onClick={() => setUserSetRole(null)} style={{
          position: 'fixed', inset: 0, zIndex: 1150,
          background: 'var(--overlay, rgba(0,0,0,0.45))',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
        }}>
          <div onClick={e => e.stopPropagation()} style={{
            background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
            maxWidth: 360, width: '100%', padding: 20,
            boxShadow: '0 8px 30px var(--shadow-heavy, rgba(0,0,0,0.25))',
            color: 'var(--text)',
          }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>Set User Role</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }}>
              Select a new role — you will be asked to confirm before the change is applied.
            </div>
            <div style={{ marginBottom: 16 }}>
              {(capabilities && capabilities.capabilities && capabilities.capabilities.roles && Array.isArray(capabilities.capabilities.roles.values)
                ? capabilities.capabilities.roles.values
                : Object.keys(ROLE_MATRIX)
              ).map(function(rv) {
                const isCurrent = userSetRole && userSetRole.currentRole === rv;
                return (
                  <Btn key={rv}
                    data-testid={'set-role-btn-' + rv}
                    variant={isCurrent ? 'outline' : 'ghost'}
                    small
                    onClick={() => {
                      const uid = userSetRole.userId;
                      const userLabel = userSetRole.userLabel;
                      setUserSetRole(null);
                      setUserActionConfirm({ action: 'set_role', userId: uid, label: userLabel || uid, newRole: rv });
                    }}
                    style={{
                      display: 'block', width: '100%', textAlign: 'left',
                      marginBottom: 4, fontWeight: isCurrent ? 700 : 400,
                    }}>
                    {rv}{isCurrent ? ' (current)' : ''}
                  </Btn>
                );
              })}
            </div>
            <Btn variant="outline" small onClick={() => setUserSetRole(null)} data-testid="set-role-cancel">Cancel</Btn>
          </div>
        </div>
      )}

      {/* Wave 5: inline toast notification (auto-clears after 4.5 s) */}
      {mpToast && (
        <div data-testid="mp-toast" style={{
          position: 'fixed', bottom: 24, right: 24, zIndex: 2000,
          padding: '10px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600,
          background: mpToast.type === 'ok' ? 'var(--badge-green-bg)' : 'var(--badge-red-bg, rgba(220,38,38,0.1))',
          color: mpToast.type === 'ok' ? 'var(--badge-green-text)' : 'var(--badge-red-text, rgba(220,38,38,0.9))',
          border: '1px solid ' + (mpToast.type === 'ok' ? 'var(--badge-green-border)' : 'var(--badge-red-border, rgba(220,38,38,0.3))'),
          boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
        }}>
          {mpToast.msg}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { MasterPage, RecordDetailModal, ScanStatusPanel, ENTITY_TYPES, ROLE_MATRIX, ENTITY_COLUMNS, MAPPING_INFO, MappingInfoBanner, ProductMasterSyncPanel, ProductOverlayEditModal, ProductAdoptModal });
