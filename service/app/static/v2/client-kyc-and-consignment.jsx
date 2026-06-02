// ── Client KYC modal + Consignment Goods tab + Doc Action buttons
// Three additions wired together: rich client form (multiple addresses, KUKE,
// credit limit, carriers, invoices), consignment tracking under inventory,
// and reusable view/download buttons for proforma/invoice rows.

// ── Reusable: View + Download buttons ─────────────────────────────────
function DocActions({ docId, onView }) {
  return (
    <div style={{ display: 'inline-flex', gap: 6 }}>
      <Btn small variant="ghost" onClick={() => onView && onView(docId)}>View</Btn>
      <Btn small variant="outline">↓ PDF</Btn>
    </div>
  );
}

// ── New Client KYC modal ──────────────────────────────────────────────
function ClientKycModal({ onClose, onSave }) {
  const [tab, setTab] = React.useState('basic');
  const [addresses, setAddresses] = React.useState([
    { id: 1, type: 'Bill to', street: '', city: '', postal: '', country: 'PL',
      contactName: '', phone: '', mobile: '', email: '', notes: '' },
  ]);
  const [invoices] = React.useState([
    { num: 'INV 2026/0140', date: '02 Apr 2026', net: 'EUR 1,840.00', status: 'Paid' },
    { num: 'INV 2026/0144', date: '06 Apr 2026', net: 'EUR 2,150.00', status: 'Paid' },
    { num: 'INV 2026/0148', date: '04 Apr 2026', net: 'EUR 480.00',   status: 'Open' },
  ]);

  const addAddress = () => setAddresses([...addresses, {
    id: Date.now(), type: 'Ship to', street: '', city: '', postal: '', country: 'PL',
    contactName: '', phone: '', mobile: '', email: '', notes: '',
  }]);
  const removeAddress = (id) => setAddresses(addresses.filter(a => a.id !== id));
  const updateAddress = (id, field, value) =>
    setAddresses(addresses.map(a => a.id === id ? { ...a, [field]: value } : a));

  const TABS = [
    { id: 'basic',     label: 'Company / Basic' },
    { id: 'shipping',  label: `Shipping (${addresses.length})` },
    { id: 'carriers',  label: 'Carriers' },
    { id: 'kyc',       label: 'KYC / Compliance' },
    { id: 'finance',   label: 'KUKE & Credit' },
    { id: 'invoices',  label: `Invoices (${invoices.length})` },
  ];

  const fieldStyle = {
    width: '100%', padding: '8px 10px', fontSize: 13,
    border: '1px solid var(--border)', borderRadius: 6,
    background: 'var(--card)', color: 'var(--text)',
  };
  const labelStyle = { fontSize: 11, fontWeight: 600, color: 'var(--text-2)', display: 'block', marginBottom: 4 };

  const Field = ({ label, children, span }) => (
    <div style={{ gridColumn: span ? `span ${span}` : 'span 1' }}>
      <label style={labelStyle}>{label}</label>
      {children}
    </div>
  );

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
    }} onClick={onClose}>
      <div style={{
        background: 'var(--card)', borderRadius: 12, width: '100%', maxWidth: 920,
        maxHeight: '92vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
        border: '1px solid var(--border)', boxShadow: '0 12px 48px rgba(0,0,0,0.25)',
      }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>New Client</div>
            <div style={{ fontSize: 12, color: 'var(--text-3)' }}>KYC · Shipping · Carriers · Insurance · Credit</div>
          </div>
          <Btn small variant="ghost" onClick={onClose}>✕</Btn>
        </div>

        <div style={{ display: 'flex', gap: 0, padding: '0 24px', borderBottom: '1px solid var(--border)' }}>
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding: '12px 14px', background: 'none', border: 'none', cursor: 'pointer',
              borderBottom: `2px solid ${tab === t.id ? 'var(--accent)' : 'transparent'}`,
              color: tab === t.id ? 'var(--text)' : 'var(--text-2)',
              fontSize: 12.5, fontWeight: tab === t.id ? 700 : 500, marginBottom: -1,
            }}>{t.label}</button>
          ))}
        </div>

        <div style={{ overflowY: 'auto', flex: 1, padding: 24 }}>
          {tab === 'basic' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Field label="Company name *" span={2}><input style={fieldStyle} placeholder="e.g. Juliany EOOD" /></Field>
              <Field label="Short code *"><input style={fieldStyle} placeholder="JLY" /></Field>
              <Field label="Client type"><select style={fieldStyle}><option>Importer</option><option>Buyer</option><option>Both</option></select></Field>
              <Field label="Country *"><select style={fieldStyle}><option>PL</option><option>BG</option><option>DE</option><option>NL</option><option>BE</option></select></Field>
              <Field label="Default currency *"><select style={fieldStyle}><option>EUR</option><option>PLN</option><option>USD</option><option>CHF</option></select></Field>
              <Field label="VAT / NIP"><input style={fieldStyle} placeholder="BG121281167" /></Field>
              <Field label="EORI"><input style={fieldStyle} placeholder="—" /></Field>
              <Field label="REGON / Reg. no."><input style={fieldStyle} /></Field>
              <Field label="Industry"><select style={fieldStyle}><option>Jewelry retail</option><option>Wholesale</option><option>Distributor</option><option>Other</option></select></Field>
              <Field label="Internal notes" span={2}><textarea rows={3} style={{ ...fieldStyle, resize: 'vertical' }} /></Field>
            </div>
          )}

          {tab === 'shipping' && (
            <div>
              {addresses.map((a, idx) => (
                <div key={a.id} style={{
                  border: '1px solid var(--border)', borderRadius: 8, padding: 16, marginBottom: 12, background: 'var(--bg-subtle)',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Address #{idx + 1}</span>
                      <select style={{ ...fieldStyle, width: 130, padding: '4px 8px', fontSize: 12 }} value={a.type} onChange={e => updateAddress(a.id, 'type', e.target.value)}>
                        <option>Bill to</option><option>Ship to</option><option>Both</option>
                      </select>
                    </div>
                    {addresses.length > 1 && <Btn small variant="ghost" onClick={() => removeAddress(a.id)}>Remove</Btn>}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 10, marginBottom: 10 }}>
                    <div><label style={labelStyle}>Street</label><input style={fieldStyle} value={a.street} onChange={e => updateAddress(a.id, 'street', e.target.value)} /></div>
                    <div><label style={labelStyle}>City</label><input style={fieldStyle} value={a.city} onChange={e => updateAddress(a.id, 'city', e.target.value)} /></div>
                    <div><label style={labelStyle}>Postal</label><input style={fieldStyle} value={a.postal} onChange={e => updateAddress(a.id, 'postal', e.target.value)} /></div>
                    <div><label style={labelStyle}>Country</label><input style={fieldStyle} value={a.country} onChange={e => updateAddress(a.id, 'country', e.target.value)} /></div>
                  </div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', margin: '14px 0 8px' }}>Courier contact at this address</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                    <div><label style={labelStyle}>Contact name</label><input style={fieldStyle} value={a.contactName} onChange={e => updateAddress(a.id, 'contactName', e.target.value)} /></div>
                    <div><label style={labelStyle}>Email</label><input style={fieldStyle} value={a.email} onChange={e => updateAddress(a.id, 'email', e.target.value)} /></div>
                    <div><label style={labelStyle}>Phone</label><input style={fieldStyle} value={a.phone} onChange={e => updateAddress(a.id, 'phone', e.target.value)} /></div>
                    <div><label style={labelStyle}>Mobile</label><input style={fieldStyle} value={a.mobile} onChange={e => updateAddress(a.id, 'mobile', e.target.value)} /></div>
                  </div>
                  <div><label style={labelStyle}>Delivery notes</label><input style={fieldStyle} value={a.notes} onChange={e => updateAddress(a.id, 'notes', e.target.value)} placeholder="Loading bay 3 · Ring before 16:00" /></div>
                </div>
              ))}
              <Btn small variant="outline" onClick={addAddress}>+ Add another address</Btn>
            </div>
          )}

          {tab === 'carriers' && (
            <div>
              <div style={{ background: 'var(--accent-bg)', border: '1px solid var(--accent-border)', borderRadius: 8, padding: 12, marginBottom: 16, fontSize: 12, color: 'var(--text-2)' }}>
                Set client-preferred carrier and per-carrier account numbers. The selection drives default carrier on new shipments.
              </div>
              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>Preferred carrier</label>
                <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
                  {[{ id: 'dhl', label: 'DHL' }, { id: 'fedex', label: 'FedEx' }, { id: 'either', label: 'Either' }].map(c => (
                    <label key={c.id} style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer', background: 'var(--card)' }}>
                      <input type="radio" name="carrier" defaultChecked={c.id === 'dhl'} />
                      <span style={{ fontWeight: 600 }}>{c.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>DHL Account</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <Field label="DHL account number"><input style={fieldStyle} placeholder="123456789" /></Field>
                  <Field label="Account name"><input style={fieldStyle} /></Field>
                  <Field label="Pay-by"><select style={fieldStyle}><option>Shipper</option><option>Consignee</option><option>Third party</option></select></Field>
                  <Field label="Service level"><select style={fieldStyle}><option>Express 9:00</option><option>Express 12:00</option><option>Express WW</option></select></Field>
                </div>
              </div>
              <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>FedEx Account</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <Field label="FedEx account number"><input style={fieldStyle} placeholder="—" /></Field>
                  <Field label="Account name"><input style={fieldStyle} /></Field>
                  <Field label="Pay-by"><select style={fieldStyle}><option>Shipper</option><option>Consignee</option><option>Third party</option></select></Field>
                  <Field label="Service level"><select style={fieldStyle}><option>International Priority</option><option>International Economy</option></select></Field>
                </div>
              </div>
            </div>
          )}

          {tab === 'kyc' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Field label="KYC status" span={2}>
                <select style={fieldStyle}><option>Pending</option><option>In review</option><option>Approved</option><option>Rejected</option><option>Expired</option></select>
              </Field>
              <Field label="KYC approved on"><input type="date" style={fieldStyle} /></Field>
              <Field label="KYC expiry"><input type="date" style={fieldStyle} /></Field>
              <Field label="Beneficial owner"><input style={fieldStyle} /></Field>
              <Field label="Owner ID type"><select style={fieldStyle}><option>Passport</option><option>National ID</option><option>Driver's license</option></select></Field>
              <Field label="Owner ID number"><input style={fieldStyle} /></Field>
              <Field label="PEP / Sanctions check"><select style={fieldStyle}><option>Cleared</option><option>Pending</option><option>Flagged</option></select></Field>
              <Field label="AML risk rating" span={2}><select style={fieldStyle}><option>Low</option><option>Medium</option><option>High</option></select></Field>
              <Field label="KYC documents" span={2}>
                <div style={{ border: '1px dashed var(--border)', borderRadius: 6, padding: 14, textAlign: 'center', color: 'var(--text-3)', fontSize: 12, background: 'var(--bg-subtle)' }}>
                  Drag KYC files here or <a href="#" style={{ color: 'var(--accent)' }}>browse</a> · ID, registration certificate, address proof, beneficial-owner declaration
                </div>
              </Field>
              <Field label="Compliance notes" span={2}><textarea rows={3} style={{ ...fieldStyle, resize: 'vertical' }} /></Field>
            </div>
          )}

          {tab === 'finance' && (
            <div>
              <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>KUKE Insurance</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <Field label="Insured?"><select style={fieldStyle}><option>Yes</option><option>No</option><option>Pending</option></select></Field>
                  <Field label="KUKE policy #"><input style={fieldStyle} placeholder="KU-2026-…" /></Field>
                  <Field label="Insured limit"><input style={fieldStyle} placeholder="EUR 50,000" /></Field>
                  <Field label="Currency"><select style={fieldStyle}><option>EUR</option><option>PLN</option><option>USD</option></select></Field>
                  <Field label="Effective from"><input type="date" style={fieldStyle} /></Field>
                  <Field label="Expiry"><input type="date" style={fieldStyle} /></Field>
                  <Field label="Self-retention %"><input type="number" style={fieldStyle} placeholder="10" /></Field>
                  <Field label="Status"><select style={fieldStyle}><option>Active</option><option>Suspended</option><option>Expired</option></select></Field>
                </div>
              </div>
              <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>Credit Limit</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 12 }}>
                  <Field label="Credit limit"><input style={fieldStyle} placeholder="50,000" /></Field>
                  <Field label="Currency"><select style={fieldStyle}><option>EUR</option><option>PLN</option></select></Field>
                  <Field label="Payment terms (days)"><input type="number" style={fieldStyle} placeholder="30" /></Field>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
                  <div style={{ background: 'var(--bg-subtle)', padding: 10, borderRadius: 6 }}>
                    <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Open</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginTop: 4 }}>EUR 12,400</div>
                  </div>
                  <div style={{ background: 'var(--bg-subtle)', padding: 10, borderRadius: 6 }}>
                    <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Overdue</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--badge-amber-text)', marginTop: 4 }}>EUR 0</div>
                  </div>
                  <div style={{ background: 'var(--bg-subtle)', padding: 10, borderRadius: 6 }}>
                    <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Available</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--badge-green-text)', marginTop: 4 }}>EUR 37,600</div>
                  </div>
                  <div style={{ background: 'var(--bg-subtle)', padding: 10, borderRadius: 6 }}>
                    <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Utilization</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginTop: 4 }}>24.8%</div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {tab === 'invoices' && (
            <div>
              <div style={{ marginBottom: 12, fontSize: 12, color: 'var(--text-3)' }}>Total invoices: <strong style={{ color: 'var(--text)' }}>{invoices.length}</strong> · Open: <strong style={{ color: 'var(--text)' }}>1</strong></div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                    {['Invoice #','Date','Net','Status',''].map(h => (
                      <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {invoices.map(i => (
                    <tr key={i.num} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontWeight: 600 }}>{i.num}</td>
                      <td style={{ padding: '10px 12px', color: 'var(--text-2)' }}>{i.date}</td>
                      <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>{i.net}</td>
                      <td style={{ padding: '10px 12px' }}><InvBadge label={i.status} tone={i.status === 'Paid' ? 'green' : 'amber'} /></td>
                      <td style={{ padding: '10px 12px', textAlign: 'right' }}><DocActions docId={i.num} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div style={{ padding: '14px 24px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>* Required fields</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="outline" onClick={onClose}>Cancel</Btn>
            <Btn onClick={() => { onSave && onSave(); onClose(); }}>Save Client</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Consignment Goods tab (Inventory sub-page) ────────────────────────
function ConsignmentTab() {
  const issued = [
    { consId: 'CON-2604-001', client: 'Juliany EOOD',     designNo: 'EJ-PND-0142-A', qty: 4, valueEur: '1,920.00', issued: '04 Apr 2026', dueBack: '04 May 2026', daysOut: 4,  proforma: 'PROF 70/2026',  status: 'Out' },
    { consId: 'CON-2604-002', client: 'Verhoeven',         designNo: 'EJ-RNG-0098',   qty: 3, valueEur: '885.00',   issued: '02 Apr 2026', dueBack: '02 May 2026', daysOut: 6,  proforma: 'PROF 71/2026',  status: 'Out' },
    { consId: 'CON-2603-018', client: '38-10 Juliany',     designNo: 'EJ-NCK-0211-A', qty: 2, valueEur: '590.00',   issued: '15 Mar 2026', dueBack: '14 Apr 2026', daysOut: 24, proforma: 'PROF 64/2026',  status: 'Closing soon' },
    { consId: 'CON-2603-007', client: 'Bijou & Co',        designNo: 'EJ-EAR-0357',   qty: 5, valueEur: '1,600.00', issued: '08 Mar 2026', dueBack: '07 Apr 2026', daysOut: 31, proforma: 'PROF 58/2026',  status: 'Overdue' },
  ];

  const proformaIssued = [
    { consId: 'CON-2604-001', proforma: 'PROF 70/2026',  client: 'Juliany EOOD',  qty: 4, valueEur: '1,920.00', issued: '04 Apr 2026', sold: 2, balanceQty: 2, balanceEur: '960.00',   status: 'Partially sold' },
    { consId: 'CON-2604-002', proforma: 'PROF 71/2026',  client: 'Verhoeven',     qty: 3, valueEur: '885.00',   issued: '02 Apr 2026', sold: 0, balanceQty: 3, balanceEur: '885.00',   status: 'Unsold' },
    { consId: 'CON-2603-018', proforma: 'PROF 64/2026',  client: '38-10 Juliany', qty: 2, valueEur: '590.00',   issued: '15 Mar 2026', sold: 1, balanceQty: 1, balanceEur: '295.00',   status: 'Partially sold' },
    { consId: 'CON-2603-007', proforma: 'PROF 58/2026',  client: 'Bijou & Co',    qty: 5, valueEur: '1,600.00', issued: '08 Mar 2026', sold: 0, balanceQty: 5, balanceEur: '1,600.00', status: 'Unsold (overdue)' },
  ];

  const [sub, setSub] = React.useState('issue');

  return (
    <div>
      <div style={{ background: 'var(--accent-bg)', border: '1px solid var(--accent-border)', borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 12, color: 'var(--text-2)' }}>
        <strong style={{ color: 'var(--text)' }}>Consignment goods.</strong> Stock physically with the client (or salesperson) but legally owned by Estrella until sold. Tracks unsold balance, aging, and value at risk. Sales-invoice trigger fires only on the <em>sold</em> portion.
      </div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
        {[
          { id: 'issue',    label: 'Issue' },
          { id: 'proforma', label: 'Proforma Issue' },
          { id: 'balance',  label: 'Balance / Valuation' },
        ].map(s => (
          <button key={s.id} onClick={() => setSub(s.id)} style={{
            padding: '8px 14px', background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: `2px solid ${sub === s.id ? 'var(--accent)' : 'transparent'}`,
            color: sub === s.id ? 'var(--text)' : 'var(--text-2)',
            fontSize: 12.5, fontWeight: sub === s.id ? 700 : 500, marginBottom: -1,
          }}>{s.label}</button>
        ))}
      </div>

      {sub === 'issue' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
            <InvStatTile label="Active out"      value="14" />
            <InvStatTile label="Closing soon"    value="2" tone="amber" />
            <InvStatTile label="Overdue"         value="3" tone="red" />
            <InvStatTile label="Total at risk"   value="EUR 8,420" />
          </div>
          <Card>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Consignment goods issued</span>
              <Btn small>+ Issue Consignment</Btn>
            </div>
            <InvTable
              columns={[
                { key: 'consId',    label: 'Cons. ID', mono: true, bold: true },
                { key: 'client',    label: 'Client' },
                { key: 'designNo',  label: 'Design', mono: true },
                { key: 'qty',       label: 'Qty', align: 'right', bold: true },
                { key: 'valueEur',  label: 'Value (EUR)', align: 'right', mono: true },
                { key: 'issued',    label: 'Issued' },
                { key: 'dueBack',   label: 'Due back' },
                { key: 'daysOut',   label: 'Days out', align: 'right',
                  render: r => <span style={{ fontWeight: 700, color: r.daysOut > 28 ? 'var(--badge-red-text)' : r.daysOut > 21 ? 'var(--badge-amber-text)' : 'var(--text)' }}>{r.daysOut}</span> },
                { key: 'proforma',  label: 'Proforma', mono: true, muted: true },
                { key: 'status',    label: 'Status',
                  render: r => <InvBadge label={r.status} tone={r.status === 'Out' ? 'blue' : r.status === 'Closing soon' ? 'amber' : 'red'} /> },
                { key: 'actions',   label: '',
                  render: () => (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <Btn small variant="outline">Convert to sale</Btn>
                      <Btn small variant="ghost">Recall</Btn>
                    </div>
                  ) },
              ]}
              rows={issued}
            />
          </Card>
        </>
      )}

      {sub === 'proforma' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
            <InvStatTile label="Open proformas"   value="11" />
            <InvStatTile label="Partially sold"   value="6" />
            <InvStatTile label="Fully unsold"     value="3" tone="amber" />
            <InvStatTile label="Overdue unsold"   value="1" tone="red" />
          </div>
          <Card>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Proformas with consignment goods · sold vs balance</span>
            </div>
            <InvTable
              columns={[
                { key: 'proforma',   label: 'Proforma', mono: true, bold: true },
                { key: 'client',     label: 'Client' },
                { key: 'qty',        label: 'Issued', align: 'right' },
                { key: 'valueEur',   label: 'Issued (EUR)', align: 'right', mono: true },
                { key: 'sold',       label: 'Sold', align: 'right',
                  render: r => <span style={{ fontWeight: 700, color: r.sold > 0 ? 'var(--badge-green-text)' : 'var(--text-2)' }}>{r.sold}</span> },
                { key: 'balanceQty', label: 'Balance Qty', align: 'right', bold: true },
                { key: 'balanceEur', label: 'Balance (EUR)', align: 'right', mono: true, bold: true },
                { key: 'issued',     label: 'Issued' },
                { key: 'status',     label: 'Status',
                  render: r => <InvBadge label={r.status} tone={r.status === 'Unsold (overdue)' ? 'red' : r.status === 'Unsold' ? 'amber' : 'blue'} /> },
                { key: 'actions',    label: '',
                  render: r => (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <DocActions docId={r.proforma} />
                    </div>
                  ) },
              ]}
              rows={proformaIssued}
            />
          </Card>
        </>
      )}

      {sub === 'balance' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
            <InvStatTile label="Total balance qty"  value="64" />
            <InvStatTile label="Balance value"      value="EUR 22,140" hint="At cost" />
            <InvStatTile label="Aging > 30 days"    value="EUR 3,485" tone="amber" />
            <InvStatTile label="Aging > 60 days"    value="EUR 1,600" tone="red" />
          </div>
          <Card>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Balance valuation by client &amp; aging</span>
              <Btn small variant="outline">↓ Export valuation</Btn>
            </div>
            <InvTable
              columns={[
                { key: 'client',    label: 'Client', bold: true },
                { key: 'open',      label: 'Open lines', align: 'right' },
                { key: 'qty',       label: 'Balance qty', align: 'right', bold: true },
                { key: 'valueCost', label: 'At cost (EUR)', align: 'right', mono: true },
                { key: 'valuePln',  label: 'At cost (PLN)', align: 'right', mono: true },
                { key: 'a0_30',     label: '0–30d', align: 'right', mono: true },
                { key: 'a31_60',    label: '31–60d', align: 'right', mono: true },
                { key: 'a60p',      label: '60d+', align: 'right', mono: true,
                  render: r => <span style={{ color: r.a60p && r.a60p !== '—' ? 'var(--badge-red-text)' : 'var(--text-2)', fontWeight: 700, fontFamily: 'monospace' }}>{r.a60p || '—'}</span> },
                { key: 'oldest',    label: 'Oldest line', muted: true },
              ]}
              rows={[
                { client: 'Juliany EOOD',   open: 4, qty: 18, valueCost: '7,840.00',  valuePln: '34,250.00', a0_30: '7,840.00', a31_60: '—', a60p: '—', oldest: '02 Apr 2026' },
                { client: 'Verhoeven',      open: 3, qty: 12, valueCost: '4,120.00',  valuePln: '17,950.00', a0_30: '4,120.00', a31_60: '—', a60p: '—', oldest: '02 Apr 2026' },
                { client: '38-10 Juliany',  open: 2, qty: 14, valueCost: '4,985.00',  valuePln: '21,720.00', a0_30: '1,500.00', a31_60: '3,485.00', a60p: '—', oldest: '15 Mar 2026' },
                { client: 'Bijou & Co',     open: 2, qty: 20, valueCost: '5,195.00',  valuePln: '22,640.00', a0_30: '—',        a31_60: '3,595.00', a60p: '1,600.00', oldest: '08 Mar 2026' },
              ]}
            />
          </Card>
        </>
      )}
    </div>
  );
}

Object.assign(window, { ClientKycModal, ConsignmentTab, DocActions });
