// Master Data page — unified CRUD for all master entities.
// Edit permissions per role are scaffolded as ROLE_MATRIX; the actual role mapping
// is configured later. UI shows "edit" / "lock" affordances based on the matrix.

const ENTITY_TYPES = [
  { id: 'clients',   label: 'Clients / Importers', icon: '🏢', singular: 'Client' },
  { id: 'suppliers', label: 'Suppliers / Exporters', icon: '🏭', singular: 'Supplier' },
  { id: 'products',  label: 'Products',           icon: '◈', singular: 'Product' },
  { id: 'designs',   label: 'Designs',            icon: '✦', singular: 'Design' },
  { id: 'hs',        label: 'HS Codes',           icon: '⊟', singular: 'HS Code' },
  { id: 'fx',        label: 'FX Rates',           icon: '$', singular: 'FX Rate' },
  { id: 'vat',       label: 'VAT Rates',          icon: '%', singular: 'VAT Rate' },
  { id: 'carriers',  label: 'Carriers',           icon: '✈', singular: 'Carrier' },
  { id: 'incoterms', label: 'Incoterms',          icon: '⊡', singular: 'Incoterm' },
  { id: 'units',     label: 'Units of Measure',   icon: '⚖', singular: 'Unit' },
  { id: 'users',     label: 'Users',              icon: '◉', singular: 'User' },
  { id: 'roles',     label: 'Roles & Permissions', icon: '🔐', singular: 'Role' },
];

// Role permissions matrix — placeholder. Tweakable later per role.
const ROLE_MATRIX = {
  admin:    { create: true, edit: true,  delete: true,  lock: true  },
  manager:  { create: true, edit: true,  delete: false, lock: true  },
  operator: { create: true, edit: true,  delete: false, lock: false },
  viewer:   { create: false, edit: false, delete: false, lock: false },
};

// ── Field definitions per entity type
const ENTITY_FIELDS = {
  clients: [
    { id: 'name',      label: 'Company name',       type: 'text',   required: true },
    { id: 'short',     label: 'Short code',         type: 'text',   required: true },
    { id: 'country',   label: 'Country',            type: 'select', required: true, options: ['PL','DE','FR','IT','CH','BE','UK','AE','US'] },
    { id: 'vat_id',    label: 'NIP / VAT ID',       type: 'text',   required: true },
    { id: 'currency',  label: 'Default currency',   type: 'select', required: true, options: ['PLN','EUR','USD','CHF','GBP'] },
    { id: 'kind',      label: 'Type',               type: 'select', required: true, options: ['Importer','Buyer','Both'] },
    { id: 'address',   label: 'Address',            type: 'textarea' },
    { id: 'email',     label: 'Primary email',      type: 'text' },
    { id: 'phone',     label: 'Phone',              type: 'text' },
    { id: 'notes',     label: 'Internal notes',     type: 'textarea' },
  ],
  suppliers: [
    { id: 'name',      label: 'Supplier name',      type: 'text',   required: true },
    { id: 'short',     label: 'Short code',         type: 'text',   required: true },
    { id: 'country',   label: 'Country',            type: 'select', required: true, options: ['IT','CH','BE','FR','DE','PL','AE','US'] },
    { id: 'tax_id',    label: 'Tax / VAT ID',       type: 'text' },
    { id: 'carrier',   label: 'Default carrier',    type: 'select', options: ['DHL','FedEx','UPS','Other'] },
    { id: 'hs',        label: 'Default HS codes',   type: 'tags',   hint: 'Comma-separated' },
    { id: 'currency',  label: 'Default currency',   type: 'select', options: ['EUR','CHF','USD','GBP','PLN'] },
    { id: 'address',   label: 'Address',            type: 'textarea' },
    { id: 'contact',   label: 'Contact name',       type: 'text' },
    { id: 'email',     label: 'Email',              type: 'text' },
    { id: 'active',    label: 'Active',             type: 'toggle', default: true },
  ],
  products: [
    { id: 'name',           label: 'Product name (internal)', type: 'text',   required: true },
    { id: 'family',         label: 'Product family code',     type: 'text',   required: true, hint: 'Internal commercial family code' },
    { id: 'category',       label: 'Category',                type: 'select', options: ['Gold jewellery','Silver jewellery','Diamond pieces','Coloured stones','Imitation','Accessories'] },
    { id: 'hs',             label: 'HS code',                 type: 'select', required: true, options: ['7113.19.00','7113.11.00','7117.19.00','7102.39.00','7103.91.00'] },
    { id: 'unit',           label: 'Unit of measure',         type: 'select', options: ['piece','gram','carat','set'] },
    { id: 'wfirma_good_id', label: 'wFirma good_id',          type: 'text',   readonly: true, hint: 'External accounting reference — read-only' },
    { id: 'wfirma_code',    label: 'wFirma product code',     type: 'text',   readonly: true, hint: 'External — read-only' },
    { id: 'description_pl', label: 'Polish customs description', type: 'textarea', required: true },
    { id: 'active',         label: 'Active',                  type: 'toggle', default: true },
  ],
  designs: [
    { id: 'design_id',  label: 'Design ID',          type: 'text',   required: true, hint: 'Unique design identifier' },
    { id: 'name',       label: 'Design name',        type: 'text',   required: true },
    { id: 'product',    label: 'Linked product',     type: 'select', required: true, options: ['Gold pendant — classic','Gold ring — solitaire','Silver bracelet — chain','Diamond earrings 1ct'] },
    { id: 'collection', label: 'Collection',         type: 'text' },
    { id: 'metal',      label: 'Metal',              type: 'select', options: ['18k gold','14k gold','silver 925','platinum'] },
    { id: 'weight_g',   label: 'Avg weight (g)',     type: 'number' },
    { id: 'stones',     label: 'Stones / details',   type: 'textarea' },
    { id: 'active',     label: 'Active',             type: 'toggle', default: true },
  ],
  hs: [
    { id: 'code',       label: 'HS code (8-digit)',  type: 'text',   required: true, hint: 'e.g. 7113.19.00' },
    { id: 'desc',       label: 'Description',        type: 'textarea', required: true },
    { id: 'duty',       label: 'Duty %',             type: 'number', required: true },
    { id: 'vat',        label: 'VAT rate',           type: 'select', options: ['23%','8%','5%','0%'] },
    { id: 'note',       label: 'Note',               type: 'textarea' },
    { id: 'locked',     label: 'Locked (read-only)', type: 'toggle', default: true, hint: 'Locked formulas cannot be edited by operators' },
  ],
  fx: [
    { id: 'currency',   label: 'Currency',           type: 'select', required: true, options: ['EUR','USD','CHF','GBP','JPY'] },
    { id: 'rate',       label: 'Rate to PLN',        type: 'number', required: true },
    { id: 'source',     label: 'Source',             type: 'select', options: ['NBP table A','NBP table B','Manual'] },
    { id: 'effective',  label: 'Effective date',     type: 'date',   required: true },
  ],
  vat: [
    { id: 'rate',       label: 'Rate',               type: 'text',   required: true },
    { id: 'code',       label: 'Code',               type: 'text',   required: true },
    { id: 'applies',    label: 'Applies to',         type: 'textarea' },
    { id: 'locked',     label: 'Locked',             type: 'toggle', default: true },
  ],
  carriers: [
    { id: 'name',       label: 'Carrier name',       type: 'text',   required: true },
    { id: 'inbox_email', label: 'Customs inbox email', type: 'text' },
    { id: 'reply_email', label: 'Reply-to address',  type: 'text' },
    { id: 'parser',     label: 'Email parser',       type: 'select', options: ['DHL Poland v3','FedEx EU v2','UPS EU v1','Generic'] },
    { id: 'active',     label: 'Active',             type: 'toggle', default: true },
  ],
  incoterms: [
    { id: 'code',       label: 'Code',               type: 'text', required: true, hint: 'e.g. DAP, EXW, CIF' },
    { id: 'name',       label: 'Name',               type: 'text', required: true },
    { id: 'desc',       label: 'Description',        type: 'textarea' },
  ],
  units: [
    { id: 'code',       label: 'Code',               type: 'text', required: true },
    { id: 'name',       label: 'Name',               type: 'text', required: true },
    { id: 'category',   label: 'Category',           type: 'select', options: ['Count','Weight','Volume','Length'] },
  ],
  users: [
    { id: 'name',       label: 'Full name',          type: 'text',   required: true },
    { id: 'email',      label: 'Email',              type: 'text',   required: true },
    { id: 'role',       label: 'Role',               type: 'select', required: true, options: ['admin','manager','operator','viewer'] },
    { id: 'active',     label: 'Active',             type: 'toggle', default: true },
  ],
  roles: [
    { id: 'name',       label: 'Role name',          type: 'text', required: true },
    { id: 'desc',       label: 'Description',        type: 'textarea' },
    { id: 'create',     label: 'Can create',         type: 'toggle' },
    { id: 'edit',       label: 'Can edit',           type: 'toggle' },
    { id: 'delete',     label: 'Can delete',         type: 'toggle' },
    { id: 'lock',       label: 'Can lock / unlock',  type: 'toggle' },
  ],
};

// ── Sample seed data
const SEED = {
  clients: [
    { id: 'c1', name: 'Estrella Jewels Sp. z o.o.', short: 'EJ-PL', country: 'PL', vat_id: 'PL5252312345', currency: 'PLN', kind: 'Importer', email: 'ops@estrella-jewels.pl' },
    { id: 'c2', name: 'Atelier Bonacchi SRL',       short: 'AB-IT', country: 'IT', vat_id: 'IT04520119872', currency: 'EUR', kind: 'Buyer',    email: 'office@bonacchi.it' },
    { id: 'c3', name: 'Geneva Imports SA',          short: 'GI-CH', country: 'CH', vat_id: 'CHE-115.823.554', currency: 'CHF', kind: 'Buyer', email: 'imports@geneva.ch' },
    { id: 'c4', name: 'Estrella Boutique Warsaw',   short: 'EBW-PL', country: 'PL', vat_id: 'PL5252312399', currency: 'PLN', kind: 'Buyer', email: 'warsaw@estrella.pl' },
  ],
  suppliers: [
    { id: 's1', name: 'Bonacchi Atelier',     short: 'BON-IT', country: 'IT', carrier: 'DHL',   currency: 'EUR', active: true },
    { id: 's2', name: 'Maison de Vicenza',    short: 'VIC-IT', country: 'IT', carrier: 'FedEx', currency: 'EUR', active: true },
    { id: 's3', name: 'Antwerp Stones',       short: 'ANT-BE', country: 'BE', carrier: 'DHL',   currency: 'EUR', active: true },
    { id: 's4', name: 'Geneva Goldworks',     short: 'GEN-CH', country: 'CH', carrier: 'DHL',   currency: 'CHF', active: true },
  ],
  products: [
    { id: 'p1', name: 'Gold pendant — classic', family: 'GP-CL',  category: 'Gold jewellery',   hs: '7113.19.00', unit: 'piece', wfirma_good_id: 'WF-2210', wfirma_code: 'GP-CL-001', description_pl: 'Wisior złoty 18k', active: true },
    { id: 'p2', name: 'Gold ring — solitaire',  family: 'GR-SOL', category: 'Gold jewellery',   hs: '7113.19.00', unit: 'piece', wfirma_good_id: 'WF-2241', wfirma_code: 'GR-SOL-001', description_pl: 'Pierścionek złoty z brylantem', active: true },
    { id: 'p3', name: 'Silver bracelet — chain', family: 'SB-CH', category: 'Silver jewellery', hs: '7113.11.00', unit: 'piece', wfirma_good_id: 'WF-2256', wfirma_code: 'SB-CH-001', description_pl: 'Bransoletka srebrna 925', active: true },
  ],
  designs: [
    { id: 'd1', design_id: 'GP-CL-V01', name: 'Classic teardrop',  product: 'Gold pendant — classic',  collection: 'Heritage 2024', metal: '18k gold', weight_g: 4.2, active: true },
    { id: 'd2', design_id: 'GR-SOL-V03', name: 'Solitaire 0.5ct',  product: 'Gold ring — solitaire',   collection: 'Bridal',         metal: '18k gold', weight_g: 3.8, active: true },
  ],
  hs: [
    { id: 'h1', code: '7113.19.00', desc: 'Articles of jewellery, precious metal (excl. silver)', duty: 2.5, vat: '23%', locked: true },
    { id: 'h2', code: '7113.11.00', desc: 'Articles of jewellery of silver',                       duty: 2.5, vat: '23%', locked: true },
    { id: 'h3', code: '7117.19.00', desc: 'Imitation jewellery, base metal',                       duty: 4.0, vat: '23%', locked: true },
    { id: 'h4', code: '7102.39.00', desc: 'Diamonds, non-industrial, worked',                      duty: 0,   vat: '23%', locked: true },
    { id: 'h5', code: '7103.91.00', desc: 'Rubies, sapphires, emeralds — worked',                  duty: 0,   vat: '23%', locked: true },
  ],
  fx: [
    { id: 'f1', currency: 'EUR', rate: 4.3128, source: 'NBP table A', effective: '2024-04-27' },
    { id: 'f2', currency: 'USD', rate: 4.0214, source: 'NBP table A', effective: '2024-04-27' },
    { id: 'f3', currency: 'CHF', rate: 4.4502, source: 'NBP table A', effective: '2024-04-27' },
    { id: 'f4', currency: 'GBP', rate: 5.0388, source: 'NBP table A', effective: '2024-04-27' },
  ],
  vat: [
    { id: 'v1', rate: '23%', code: 'VAT-23', applies: 'Standard rate', locked: true },
    { id: 'v2', rate: '8%',  code: 'VAT-8',  applies: 'Reduced',       locked: true },
    { id: 'v3', rate: '0%',  code: 'VAT-0',  applies: 'Exports',       locked: true },
  ],
  carriers: [
    { id: 'cr1', name: 'DHL',   inbox_email: 'clearance@dhl.com.pl', reply_email: 'estrella@example.com', parser: 'DHL Poland v3', active: true },
    { id: 'cr2', name: 'FedEx', inbox_email: 'eu-clearance@fedex.com', reply_email: 'estrella@example.com', parser: 'FedEx EU v2',   active: true },
    { id: 'cr3', name: 'UPS',   inbox_email: 'eu-customs@ups.com',     reply_email: 'estrella@example.com', parser: 'UPS EU v1',     active: false },
  ],
  incoterms: [
    { id: 'i1', code: 'DAP', name: 'Delivered at Place' },
    { id: 'i2', code: 'EXW', name: 'Ex Works' },
    { id: 'i3', code: 'CIF', name: 'Cost, Insurance, Freight' },
    { id: 'i4', code: 'DDP', name: 'Delivered Duty Paid' },
  ],
  units: [
    { id: 'u1', code: 'pcs', name: 'Pieces',     category: 'Count' },
    { id: 'u2', code: 'g',   name: 'Grams',      category: 'Weight' },
    { id: 'u3', code: 'ct',  name: 'Carats',     category: 'Weight' },
    { id: 'u4', code: 'set', name: 'Set',        category: 'Count' },
  ],
  users: [
    { id: 'us1', name: 'Anna Kowalska', email: 'anna.k@estrella-jewels.pl', role: 'admin',    active: true },
    { id: 'us2', name: 'Tomek Wiśniewski', email: 'tomek.w@estrella-jewels.pl', role: 'manager',  active: true },
    { id: 'us3', name: 'Maria Nowak',   email: 'maria.n@estrella-jewels.pl', role: 'operator', active: true },
    { id: 'us4', name: 'Customs Audit', email: 'audit@estrella-jewels.pl', role: 'viewer',   active: true },
  ],
  roles: [
    { id: 'r1', name: 'admin',    desc: 'Full access incl. role management',     create: true, edit: true, delete: true, lock: true },
    { id: 'r2', name: 'manager',  desc: 'Can edit master data, no deletions',    create: true, edit: true, delete: false, lock: true },
    { id: 'r3', name: 'operator', desc: 'Daily operations, limited master edits', create: true, edit: true, delete: false, lock: false },
    { id: 'r4', name: 'viewer',   desc: 'Read-only access',                       create: false, edit: false, delete: false, lock: false },
  ],
};

function MasterPage() {
  const [entity, setEntity] = React.useState('clients');
  const [role, setRole] = React.useState('admin');
  const [search, setSearch] = React.useState('');
  const [data, setData] = React.useState(SEED);
  const [editing, setEditing] = React.useState(null); // { entity, record } or null
  const [creating, setCreating] = React.useState(null); // entity id or null

  const perms = ROLE_MATRIX[role];
  const fields = ENTITY_FIELDS[entity];
  const records = (data[entity] || []).filter(r => {
    if (!search) return true;
    return Object.values(r).some(v => String(v).toLowerCase().includes(search.toLowerCase()));
  });

  const handleSave = (record, isNew) => {
    setData(prev => {
      const list = prev[entity] || [];
      if (isNew) {
        return { ...prev, [entity]: [...list, { ...record, id: 'new-' + Date.now() }] };
      } else {
        return { ...prev, [entity]: list.map(r => r.id === record.id ? record : r) };
      }
    });
    setEditing(null);
    setCreating(null);
  };

  const handleDelete = (record) => {
    if (!confirm(`Delete "${record.name || record.code || record.id}"?`)) return;
    setData(prev => ({ ...prev, [entity]: prev[entity].filter(r => r.id !== record.id) }));
  };

  const currentEntity = ENTITY_TYPES.find(e => e.id === entity);

  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Role banner */}
      <div style={{ padding: 12, background: 'rgba(212,168,83,0.08)', border: '1px solid rgba(212,168,83,0.3)', borderRadius: 6, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Acting as role</div>
        <div style={{ display: 'flex', gap: 4 }}>
          {Object.keys(ROLE_MATRIX).map(r => (
            <button key={r} onClick={() => setRole(r)} style={{
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
            <button key={e.id} onClick={() => setEntity(e.id)} style={{
              width: '100%', padding: '10px 12px', textAlign: 'left',
              background: entity === e.id ? 'var(--bg-subtle)' : 'transparent',
              border: 'none', borderRadius: 4, cursor: 'pointer',
              fontSize: 12, fontWeight: entity === e.id ? 600 : 500,
              color: entity === e.id ? 'var(--text)' : 'var(--text-2)',
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ fontSize: 14 }}>{e.icon}</span>
              <span style={{ flex: 1 }}>{e.label}</span>
              <span style={{ fontSize: 10, color: 'var(--text-3)' }}>{(data[e.id] || []).length}</span>
            </button>
          ))}
        </Card>

        {/* Right pane */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, gap: 8, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, fontFamily: '"DM Serif Display", serif', color: 'var(--text)' }}>{currentEntity.label}</div>
              <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{records.length} record{records.length === 1 ? '' : 's'}</div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Input value={search} onChange={e => setSearch(e.target.value)} placeholder={`Search ${currentEntity.label.toLowerCase()}…`} />
              <Btn variant="outline" small>↓ Export CSV</Btn>
              <Btn variant="outline" small>↑ Import CSV</Btn>
              <Btn variant="gold" small disabled={!perms.create} onClick={() => setCreating(entity)}>
                + New {currentEntity.singular}
              </Btn>
            </div>
          </div>

          <Card style={{ overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)' }}>
                    {fields.slice(0, 5).map(f => (
                      <th key={f.id} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>
                        {f.label}{f.readonly && ' 🔒'}
                      </th>
                    ))}
                    <th style={{ padding: '10px 12px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map(r => (
                    <tr key={r.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                      {fields.slice(0, 5).map((f, i) => {
                        const v = r[f.id];
                        return (
                          <td key={f.id} style={{ padding: '10px 12px', fontSize: 12, color: i === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: i === 0 ? 600 : 400, fontFamily: f.id === 'code' || f.id === 'design_id' || f.id === 'wfirma_good_id' || f.id === 'wfirma_code' ? 'monospace' : 'inherit' }}>
                            {f.type === 'toggle' ? (v ? '✓' : '✗') : (v == null || v === '' ? '—' : String(v))}
                          </td>
                        );
                      })}
                      <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: 4 }}>
                          <Btn small variant="outline" onClick={() => setEditing({ entity, record: r })}>{perms.edit ? 'Edit' : 'View'}</Btn>
                          {perms.delete && <Btn small variant="outline" onClick={() => handleDelete(r)}>Delete</Btn>}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {records.length === 0 && (
                    <tr>
                      <td colSpan={fields.slice(0, 5).length + 1} style={{ padding: 48, textAlign: 'center', color: 'var(--text-3)' }}>
                        <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.4 }}>{currentEntity.icon}</div>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>No {currentEntity.label.toLowerCase()} yet</div>
                        <div style={{ fontSize: 11, marginTop: 4 }}>Click "+ New {currentEntity.singular}" to create one</div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </div>

      {creating === 'clients' && window.ClientKycModal && (
        <window.ClientKycModal
          onClose={() => setCreating(null)}
          onSave={(rec) => { handleSave(rec, true); setCreating(null); }}
        />
      )}
      {((editing && editing.entity !== 'clients') || (creating && creating !== 'clients')) && (
        <RecordModal
          entity={editing ? editing.entity : creating}
          record={editing ? editing.record : null}
          fields={editing ? ENTITY_FIELDS[editing.entity] : ENTITY_FIELDS[creating]}
          isNew={!editing}
          readonly={!perms.edit && !!editing}
          onSave={(rec) => handleSave(rec, !editing)}
          onClose={() => { setEditing(null); setCreating(null); }}
        />
      )}
      {editing && editing.entity === 'clients' && window.ClientKycModal && (
        <window.ClientKycModal
          onClose={() => setEditing(null)}
          onSave={(rec) => { handleSave(rec, false); setEditing(null); }}
        />
      )}
    </div>
  );
}

function RecordModal({ entity, record, fields, isNew, readonly, onSave, onClose }) {
  const initial = {};
  fields.forEach(f => { initial[f.id] = record ? (record[f.id] ?? '') : (f.default != null ? f.default : ''); });
  const [form, setForm] = React.useState(initial);
  const [errors, setErrors] = React.useState({});

  const update = (id, v) => setForm(p => ({ ...p, [id]: v }));

  const handleSubmit = () => {
    const errs = {};
    fields.forEach(f => {
      if (f.required && (form[f.id] === '' || form[f.id] == null)) errs[f.id] = 'Required';
    });
    if (Object.keys(errs).length) { setErrors(errs); return; }
    onSave({ ...record, ...form });
  };

  const entityType = ENTITY_TYPES.find(e => e.id === entity);

  return (
    <Modal title={`${isNew ? 'New' : readonly ? 'View' : 'Edit'} ${entityType.singular}`} onClose={onClose} wide>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        {fields.map(f => (
          <div key={f.id} style={{
            gridColumn: f.type === 'textarea' ? '1 / -1' : 'auto',
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
              {f.label}
              {f.required && <span style={{ color: 'var(--badge-red-text)' }}>*</span>}
              {f.readonly && <Pill tone="neutral" small>read-only</Pill>}
            </div>
            {f.type === 'select' ? (
              <Select value={form[f.id] || ''} onChange={e => update(f.id, e.target.value)}>
                <option value="">Select…</option>
                {(f.options || []).map(o => <option key={o} value={o}>{o}</option>)}
              </Select>
            ) : f.type === 'textarea' ? (
              <textarea
                value={form[f.id] || ''} onChange={e => update(f.id, e.target.value)}
                disabled={readonly || f.readonly}
                rows={3}
                style={{
                  width: '100%', padding: '8px 10px', borderRadius: 6,
                  border: '1px solid ' + (errors[f.id] ? 'var(--badge-red-text)' : 'var(--border)'),
                  fontSize: 12, color: 'var(--text)', background: (readonly || f.readonly) ? 'var(--bg-subtle)' : 'var(--card)',
                  outline: 'none', resize: 'vertical', boxSizing: 'border-box', fontFamily: 'inherit',
                }}
              />
            ) : f.type === 'toggle' ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
                <input type="checkbox" checked={!!form[f.id]} onChange={e => update(f.id, e.target.checked)} disabled={readonly || f.readonly} style={{ accentColor: 'var(--accent)' }} />
                <span style={{ fontSize: 12, color: 'var(--text-2)' }}>{form[f.id] ? 'Enabled' : 'Disabled'}</span>
              </div>
            ) : f.type === 'number' ? (
              <Input type="number" value={form[f.id] || ''} onChange={e => update(f.id, e.target.value)} />
            ) : f.type === 'date' ? (
              <Input type="date" value={form[f.id] || ''} onChange={e => update(f.id, e.target.value)} />
            ) : (
              <Input value={form[f.id] || ''} onChange={e => update(f.id, e.target.value)} placeholder={f.hint} />
            )}
            {f.hint && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 3 }}>{f.hint}</div>}
            {errors[f.id] && <div style={{ fontSize: 10, color: 'var(--badge-red-text)', marginTop: 3 }}>{errors[f.id]}</div>}
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
          {!isNew && record && (
            <>Last edited: <span style={{ color: 'var(--text-2)' }}>2 days ago by anna.k</span> · Audit ID: <span style={{ fontFamily: 'monospace' }}>{record.id}</span></>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn variant="outline" onClick={onClose}>{readonly ? 'Close' : 'Cancel'}</Btn>
          {!readonly && <Btn variant="gold" onClick={handleSubmit}>{isNew ? `Create ${entityType.singular}` : 'Save Changes'}</Btn>}
        </div>
      </div>
    </Modal>
  );
}

Object.assign(window, { MasterPage, ENTITY_TYPES, ROLE_MATRIX });
