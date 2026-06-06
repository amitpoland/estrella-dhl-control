// Master Data page — Sprint 38: live backend read authority.
//
// All 12 entity tabs render from backend GET endpoints (no hardcoded data).
// Write operations (create/edit/delete) are disabled with explicit reasons.
// Users: read-only list from GET /auth/users.
// Roles: static system definition from ROLE_MATRIX (no backend endpoint).

const ENTITY_TYPES = [
  { id: 'clients',   label: 'Clients / Importers', icon: '\u{1F3E2}', singular: 'Client' },
  { id: 'suppliers', label: 'Suppliers / Exporters', icon: '\u{1F3ED}', singular: 'Supplier' },
  { id: 'products',  label: 'Products',           icon: '◈', singular: 'Product' },
  { id: 'designs',   label: 'Designs',            icon: '✦', singular: 'Design' },
  { id: 'hs',        label: 'HS Codes',           icon: '⊟', singular: 'HS Code' },
  { id: 'fx',        label: 'FX Rates',           icon: '$', singular: 'FX Rate' },
  { id: 'vat',       label: 'VAT Rates',          icon: '%', singular: 'VAT Rate' },
  { id: 'carriers',  label: 'Carriers',           icon: '✈', singular: 'Carrier' },
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
const ENTITY_COLUMNS = {
  clients: [
    { key: 'bill_to_name',   label: 'Company name' },
    { key: 'country',        label: 'Country' },
    { key: 'nip',            label: 'NIP / VAT ID', mono: true },
    { key: 'default_currency', label: 'Currency' },
    { key: 'active',         label: 'Active', toggle: true },
  ],
  suppliers: [
    { key: 'name',           label: 'Supplier name' },
    { key: 'supplier_code',  label: 'Code', mono: true },
    { key: 'country',        label: 'Country' },
    { key: 'vat_id',         label: 'VAT ID', mono: true },
    { key: 'active',         label: 'Active', toggle: true },
  ],
  products: [
    { key: 'product_code',       label: 'Product code', mono: true },
    { key: 'hs_code_override',   label: 'HS code', mono: true },
    { key: 'unit_override',      label: 'Unit' },
    { key: 'design_code_link',   label: 'Design link' },
    { key: 'active',             label: 'Active', toggle: true },
  ],
  designs: [
    { key: 'design_code',   label: 'Design code', mono: true },
    { key: 'display_name',  label: 'Name' },
    { key: 'collection',    label: 'Collection' },
    { key: 'metal',         label: 'Metal' },
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
    { key: 'inbox_email',  label: 'Inbox email' },
    { key: 'active',       label: 'Active', toggle: true },
  ],
  incoterms: [
    { key: 'code',                label: 'Code', mono: true },
    { key: 'name',                label: 'Name' },
    { key: 'risk_transfer_point', label: 'Risk transfer' },
    { key: 'freight_included',    label: 'Freight', toggle: true },
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
    { key: 'name',   label: 'Role name' },
    { key: 'desc',   label: 'Description' },
    { key: 'create', label: 'Can create', toggle: true },
    { key: 'edit',   label: 'Can edit', toggle: true },
    { key: 'delete', label: 'Can delete', toggle: true },
  ],
};

// ── Roles: static system data (no backend endpoint exists)
const STATIC_ROLES = [
  { id: 'r1', name: 'admin',    desc: 'Full access incl. role management',     create: true, edit: true, delete: true, lock: true },
  { id: 'r2', name: 'manager',  desc: 'Can edit master data, no deletions',    create: true, edit: true, delete: false, lock: true },
  { id: 'r3', name: 'operator', desc: 'Daily operations, limited master edits', create: true, edit: true, delete: false, lock: false },
  { id: 'r4', name: 'viewer',   desc: 'Read-only access',                       create: false, edit: false, delete: false, lock: false },
];

// ── Disabled-reason messages for write buttons
const WRITE_DISABLED_REASON = 'Write operations not yet wired — Sprint 38 is read-only authority conversion';
const ROLES_DISABLED_REASON = 'No backend endpoint for role management — roles are system-defined';
const USERS_WRITE_DISABLED_REASON = 'User write operations require admin endpoints not yet wired to this page';

// ── API fetch mapping: entity id -> { fetch, extractRecords, rowKey }
function _entityApi(entityId) {
  switch (entityId) {
    case 'clients':   return { fetch: () => PzApi.listCustomerMaster(),  extract: d => d.customers || [],  rowKey: r => r.id || r.bill_to_contractor_id };
    case 'suppliers':  return { fetch: () => PzApi.listSuppliers(),       extract: d => d.suppliers || [],  rowKey: r => r.id };
    case 'products':   return { fetch: () => PzApi.listProductLocal(),    extract: d => d.items || [],      rowKey: r => r.product_code };
    case 'designs':    return { fetch: () => PzApi.listDesigns(),         extract: d => d.designs || [],    rowKey: r => r.design_code };
    case 'hs':         return { fetch: () => PzApi.listHsCodes(),         extract: d => d.hs_codes || [],   rowKey: r => r.hs_code };
    case 'fx':         return { fetch: () => PzApi.listFxRates(),         extract: d => d.fx_rates || [],   rowKey: r => r.id };
    case 'vat':        return { fetch: () => PzApi.listVatConfig(),       extract: d => d.vat_config || [], rowKey: r => r.id };
    case 'carriers':   return { fetch: () => PzApi.listCarriersConfig(),  extract: d => d.carriers || [],   rowKey: r => r.carrier_code };
    case 'incoterms':  return { fetch: () => PzApi.listIncoterms(),       extract: d => d.incoterms || [],  rowKey: r => r.code };
    case 'units':      return { fetch: () => PzApi.listUnits(),           extract: d => d.units || [],      rowKey: r => r.code };
    case 'users':      return { fetch: () => PzApi.listUsers(),           extract: d => (Array.isArray(d) ? d : d.users || []), rowKey: r => r.id };
    case 'roles':      return null; // static data, no API
    default:           return null;
  }
}

function MasterPage() {
  const [entity, setEntity] = React.useState('clients');
  const [role, setRole] = React.useState('admin');
  const [search, setSearch] = React.useState('');

  // Per-entity data cache: { entityId: { records: [], loading: bool, error: string|null } }
  const [cache, setCache] = React.useState({});

  const perms = ROLE_MATRIX[role];
  const columns = ENTITY_COLUMNS[entity] || [];
  const currentEntity = ENTITY_TYPES.find(e => e.id === entity);

  // Derive state for current entity
  const entityState = cache[entity] || { records: [], loading: false, error: null };

  // ── Load entity data on tab switch
  React.useEffect(() => {
    // Roles: use static data
    if (entity === 'roles') {
      setCache(prev => ({ ...prev, roles: { records: STATIC_ROLES, loading: false, error: null } }));
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
  }, [entity]);

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
    if (eid === 'roles') return ROLES_DISABLED_REASON;
    if (eid === 'users') return USERS_WRITE_DISABLED_REASON;
    return WRITE_DISABLED_REASON;
  };

  // ── Reload current entity
  const handleReload = () => {
    setCache(prev => ({ ...prev, [entity]: { records: [], loading: false, error: null } }));
    // Re-trigger useEffect by clearing cache (useEffect checks cache[entity])
    setTimeout(() => {
      setCache(prev => {
        const next = { ...prev };
        delete next[entity];
        return next;
      });
    }, 0);
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
              color: role === r ? '#fff' : 'var(--text-2)', cursor: 'pointer', textTransform: 'capitalize',
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
              <Btn variant="outline" small disabled title={writeDisabledReason(entity)} data-testid="btn-export-csv">{'↓'} Export CSV</Btn>
              <Btn variant="outline" small disabled title={writeDisabledReason(entity)} data-testid="btn-import-csv">{'↑'} Import CSV</Btn>
              <Btn variant="gold" small disabled title={writeDisabledReason(entity)} data-testid="btn-new-record">
                + New {currentEntity.singular}
              </Btn>
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
                                {c.toggle ? (v ? '✓' : '✗') : (v == null || v === '' ? '—' : String(v))}
                              </td>
                            );
                          })}
                          <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                            <div style={{ display: 'inline-flex', gap: 4 }}>
                              <Btn small variant="outline" disabled title={writeDisabledReason(entity)}>View</Btn>
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

          {/* Roles-specific info banner */}
          {entity === 'roles' && (
            <div data-testid="roles-info-banner" style={{ marginTop: 12, padding: 12, background: 'rgba(212,168,83,0.06)', border: '1px solid rgba(212,168,83,0.2)', borderRadius: 6, fontSize: 11, color: 'var(--text-3)' }}>
              Roles are system-defined constants. No backend endpoint exists for role CRUD. Role assignment is managed per-user via the Users tab.
            </div>
          )}

          {/* Users-specific info banner */}
          {entity === 'users' && (
            <div data-testid="users-info-banner" style={{ marginTop: 12, padding: 12, background: 'rgba(212,168,83,0.06)', border: '1px solid rgba(212,168,83,0.2)', borderRadius: 6, fontSize: 11, color: 'var(--text-3)' }}>
              Users are read-only in this view. User management (approve, reject, role change, activate/deactivate) requires admin endpoints not yet wired to this page.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { MasterPage, ENTITY_TYPES, ROLE_MATRIX, ENTITY_COLUMNS });
