// ─────────────────────────────────────────────────────────────────────────────
// Documents Hub — REDESIGNED around the actual operator flow.
//
// The real flow (per user):
//   1. Operator uploads a sales packing list OR enters manually (client + products)
//   2. App creates a draft Proforma
//   3. Operator approves
//   4. Operator clicks "Post to wFirma" → wFirma sync
//
// Same 3-stage lifecycle for PZ (purchase receipt).
//
// Everything else (Invoice, Orders, Customs, Shipping, Email) is downstream
// read-only history — collapsed into a single "Other documents" tab.
//
// Backend hooks (stubbed):
//   POST /api/v1/proforma                       — create (manual or upload)
//   POST /api/v1/proforma/upload-packing-list   — parse upload → draft
//   POST /api/v1/proforma/{id}/approve          — Draft → Approved
//   POST /api/v1/proforma/{id}/post-to-wfirma   — Approved → Posted (calls wFirma)
//   POST /api/v1/proforma/{id}/unapprove        — Approved → Draft
//   DELETE /api/v1/proforma/{id}                — draft-only
//   (same endpoints under /api/v1/pz for inbound PZ)
// ─────────────────────────────────────────────────────────────────────────────

const Tbl    = window.Tbl;
const ApiBtn = window.ApiBtn;

// ── Sample data (lifecycle-aligned) ─────────────────────────────────────────
const SAMPLE_FLOW = {
  PI: [
    { id: 'pi_001', number: 'PI-2026/0143', party: 'Maison Royale SARL',  items: 4, amount: 9840.50,  currency: 'EUR', source: 'manual',  lane: 'draft',    created: '2026-05-11 08:14', operator: 'A. Kowalski' },
    { id: 'pi_002', number: 'PI-2026/0144', party: 'Crown Jewelers Ltd',  items: 6, amount: 24100.00, currency: 'USD', source: 'upload',  lane: 'draft',    created: '2026-05-11 09:02', operator: 'M. Nowak'    },
    { id: 'pi_003', number: 'PI-2026/0142', party: 'Aurum Watches GmbH',  items: 3, amount: 18420.00, currency: 'EUR', source: 'manual',  lane: 'approved', created: '2026-05-10 14:22', approvedBy: 'A. Kowalski', approvedAt: '2026-05-11 07:10' },
    { id: 'pi_004', number: 'PI-2026/0141', party: 'Hôtel Belle Étoile',  items: 2, amount: 4220.00,  currency: 'EUR', source: 'upload',  lane: 'approved', created: '2026-05-10 09:18', approvedBy: 'M. Nowak',    approvedAt: '2026-05-11 06:30' },
    { id: 'pi_005', number: 'PI-2026/0140', party: 'Bijoux Sélection',    items: 1, amount: 1840.00,  currency: 'EUR', source: 'manual',  lane: 'posted',   created: '2026-05-08 11:14', wfirmaId: 'wf_pi_88421', postedAt: '2026-05-09 10:42' },
    { id: 'pi_006', number: 'PI-2026/0139', party: 'Crown Jewelers Ltd',  items: 4, amount: 18200.00, currency: 'USD', source: 'manual',  lane: 'posted',   created: '2026-05-07 09:00', wfirmaId: 'wf_pi_88420', postedAt: '2026-05-08 14:18' },
  ],
  PZ: [
    { id: 'pz_001', number: 'PZ-2026/0318', party: 'Audemars Piguet',     items: 12, amount: 88400.00, currency: 'CHF', source: 'upload',  lane: 'draft',    created: '2026-05-11 07:44', operator: 'M. Nowak'    },
    { id: 'pz_002', number: 'PZ-2026/0319', party: 'Manufaktura Złota',   items: 4,  amount: 18420.00, currency: 'PLN', source: 'upload',  lane: 'approved', created: '2026-05-10 16:22', approvedBy: 'A. Kowalski', approvedAt: '2026-05-11 08:00' },
    { id: 'pz_003', number: 'PZ-2026/0317', party: 'Patek Philippe SA',   items: 7,  amount: 142000.00,currency: 'CHF', source: 'upload',  lane: 'posted',   created: '2026-05-07 13:18', wfirmaId: 'wf_pz_44712', postedAt: '2026-05-08 09:14' },
  ],
};

const DOC_KIND = {
  PI: { code: 'PI', label: 'Proforma',         party: 'Client',   color: 'var(--badge-blue-text)',   bg: 'var(--badge-blue-bg)',   border: 'var(--badge-blue-border)' },
  PZ: { code: 'PZ', label: 'Purchase Receipt', party: 'Supplier', color: 'var(--badge-purple-text)', bg: 'var(--badge-purple-bg)', border: 'var(--badge-purple-border)' },
};

const LANE_DEF = [
  { id: 'draft',    label: 'Draft',              hint: 'Created — review & approve',  accent: 'var(--badge-neutral-text)', dot: 'var(--badge-neutral-border)' },
  { id: 'approved', label: 'Approved',           hint: 'Ready to post to wFirma',     accent: 'var(--badge-blue-text)',    dot: 'var(--badge-blue-text)' },
  { id: 'posted',   label: 'Posted to wFirma',   hint: 'Synced · read-only',          accent: 'var(--badge-green-text)',   dot: 'var(--badge-green-text)' },
];

// ── Sample "other documents" (read-only history) ────────────────────────────
const OTHER_DOCS = [
  { code: 'INV',   label: 'Invoice',         num: 'FV-2026/0098',         party: 'Aurum Watches GmbH',  amount: '€18,420.00', date: '2026-05-10', wfirma: 'synced' },
  { code: 'INV',   label: 'Invoice',         num: 'FV-2026/0099',         party: 'Hôtel Belle Étoile',  amount: '€4,220.00',  date: '2026-05-10', wfirma: 'synced' },
  { code: 'ORD',   label: 'Order',           num: 'ORD-882',              party: 'Aurum Watches GmbH',  amount: '€18,420.00', date: '2026-05-08', wfirma: '—' },
  { code: 'SAD',   label: 'SAD',             num: 'SAD-PL-26-118472',     party: 'Patek Philippe SA',   amount: '—',          date: '2026-05-07', wfirma: '—' },
  { code: 'CI',    label: 'Comm. Invoice',   num: 'CI-SHIP-0421',         party: 'Aurum Watches GmbH',  amount: '€18,420.00', date: '2026-05-10', wfirma: '—' },
  { code: 'CN23',  label: 'CN23',            num: 'CN23-SHIP-0421',       party: 'Aurum Watches GmbH',  amount: '—',          date: '2026-05-10', wfirma: '—' },
  { code: 'LBL',   label: 'AWB Label',       num: 'AWB-DHL-1234567890',   party: 'Aurum Watches GmbH',  amount: '—',          date: '2026-05-10', wfirma: '—' },
  { code: 'EML',   label: 'Email PDF',       num: 'EML-DHL-inbox-2148',   party: 'DHL Express',         amount: '—',          date: '2026-05-11', wfirma: '—' },
];

// ── Small UI helpers ─────────────────────────────────────────────────────────
const docKindChip = (t) => {
  const v = DOC_KIND[t]; if (!v) return null;
  return <span style={{ display: 'inline-block', padding: '1px 7px', borderRadius: 3, fontSize: 9.5, fontWeight: 700, fontFamily: 'monospace', color: v.color, background: v.bg, border: `1px solid ${v.border}` }}>{v.code}</span>;
};

const wfirmaChip = (state) => {
  const map = {
    synced:  { c: 'var(--badge-green-text)', bg: 'var(--badge-green-bg)', label: '✓ wFirma' },
    pending: { c: 'var(--badge-amber-text)', bg: 'var(--badge-amber-bg)', label: '◷ Pending' },
    '—':     { c: 'var(--text-3)',            bg: 'var(--bg-2)',           label: '—' },
  };
  const v = map[state] || map['—'];
  return <span style={{ display: 'inline-block', padding: '1px 6px', borderRadius: 3, fontSize: 10, fontWeight: 600, color: v.c, background: v.bg, border: '1px solid var(--border)' }}>{v.label}</span>;
};

const sourceBadge = (s) => (
  <span style={{ fontSize: 9.5, color: 'var(--text-3)', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
    {s === 'upload' ? '⬆ Packing list' : '✎ Manual'}
  </span>
);

const fmtMoney = (n, cur) => cur ? `${cur === 'EUR' ? '€' : cur === 'USD' ? '$' : cur === 'CHF' ? 'CHF ' : cur === 'PLN' ? 'zł ' : ''}${Number(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';

// ─────────────────────────────────────────────────────────────────────────────
// Lane card — visual representation of one document in its current stage.
// Buttons surfaced depend on lane: draft → Approve/Edit/Delete; approved →
// Post to wFirma / Unapprove; posted → View/Download.
// ─────────────────────────────────────────────────────────────────────────────
function LaneCard({ doc, kind, onApprove, onPost, onUnapprove, onEdit, onDelete }) {
  const k = DOC_KIND[kind];
  return (
    <div style={{
      background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 8,
      padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8,
      boxShadow: '0 1px 0 rgba(15,15,15,0.02)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {docKindChip(kind)}
            <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-1)', fontFamily: 'monospace' }}>{doc.number}</span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.party}</div>
        </div>
        {sourceBadge(doc.source)}
      </div>

      <div style={{ display: 'flex', gap: 10, fontSize: 11, color: 'var(--text-3)' }}>
        <span><b style={{ color: 'var(--text-2)' }}>{doc.items}</b> items</span>
        <span>·</span>
        <span style={{ color: 'var(--text-1)', fontWeight: 700 }}>{fmtMoney(doc.amount, doc.currency)}</span>
      </div>

      {doc.lane === 'draft' && (
        <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>
          Created {doc.created} {doc.operator && `· ${doc.operator}`}
        </div>
      )}
      {doc.lane === 'approved' && (
        <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>
          ✓ Approved {doc.approvedAt} {doc.approvedBy && `· ${doc.approvedBy}`}
        </div>
      )}
      {doc.lane === 'posted' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>↻ Posted {doc.postedAt}</div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'monospace' }}>wFirma id: {doc.wfirmaId}</div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
        {doc.lane === 'draft' && (
          <>
            <ApiBtn label="Edit" endpoint={`PATCH /api/v1/${kind.toLowerCase()}/${doc.id}`} small onClick={() => onEdit && onEdit(doc)} />
            <ApiBtn label="✓ Approve" endpoint={`POST /api/v1/${kind.toLowerCase()}/${doc.id}/approve`} small variant="gold" onClick={() => onApprove && onApprove(doc)} />
            <ApiBtn label="🗑" endpoint={`DELETE /api/v1/${kind.toLowerCase()}/${doc.id}`} small variant="outline-danger" onClick={() => onDelete && onDelete(doc)} />
          </>
        )}
        {doc.lane === 'approved' && (
          <>
            <ApiBtn label="↻ Post to wFirma" endpoint={`POST /api/v1/${kind.toLowerCase()}/${doc.id}/post-to-wfirma`} small variant="gold" onClick={() => onPost && onPost(doc)} />
            <ApiBtn label="↶ Unapprove" endpoint={`POST /api/v1/${kind.toLowerCase()}/${doc.id}/unapprove`} small onClick={() => onUnapprove && onUnapprove(doc)} />
          </>
        )}
        {doc.lane === 'posted' && (
          <>
            <ApiBtn label="👁 View" endpoint={`GET /api/v1/${kind.toLowerCase()}/${doc.id}/view`} small />
            <ApiBtn label="↓ Download" endpoint={`GET /api/v1/${kind.toLowerCase()}/${doc.id}/download`} small />
          </>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Lane — column for one stage of the lifecycle.
// ─────────────────────────────────────────────────────────────────────────────
function Lane({ def, kind, docs, handlers }) {
  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 10, background: 'var(--bg-2)', borderRadius: 10, padding: 12, border: '1px solid var(--border-soft)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: def.dot }}></span>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-1)' }}>{def.label}</span>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>· {docs.length}</span>
      </div>
      <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: -4 }}>{def.hint}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto', minHeight: 0 }}>
        {docs.length === 0
          ? <div style={{ padding: 18, fontSize: 11, color: 'var(--text-3)', textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 8 }}>No documents in {def.label.toLowerCase()}</div>
          : docs.map(d => <LaneCard key={d.id} doc={d} kind={kind} {...handlers} />)
        }
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Create modal — two entry methods: upload packing list OR manual entry.
// ─────────────────────────────────────────────────────────────────────────────
function CreateModal({ kind, onClose }) {
  const [mode, setMode] = React.useState(null); // 'upload' | 'manual'
  const k = DOC_KIND[kind];

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg-1)', borderRadius: 12, width: 560, maxWidth: '92vw', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Create document</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-1)', marginTop: 2 }}>New {k.label}</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-3)' }}>×</button>
        </div>

        {!mode && (
          <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 4 }}>Choose how you want to create this {k.label.toLowerCase()}:</div>
            <button onClick={() => setMode('upload')} style={{ textAlign: 'left', padding: 16, border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg-1)', cursor: 'pointer', display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <div style={{ fontSize: 22 }}>⬆</div>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--text-1)' }}>Upload {kind === 'PI' ? 'sales' : 'supplier'} packing list</div>
                <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 3 }}>Drop a CSV / XLS / PDF · parser extracts {k.party.toLowerCase()} + line items → creates a draft.</div>
              </div>
            </button>
            <button onClick={() => setMode('manual')} style={{ textAlign: 'left', padding: 16, border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg-1)', cursor: 'pointer', display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <div style={{ fontSize: 22 }}>✎</div>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--text-1)' }}>Manual entry</div>
                <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 3 }}>Select {k.party.toLowerCase()}, pick products from catalog, set quantity & price.</div>
              </div>
            </button>
          </div>
        )}

        {mode === 'upload' && (
          <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <button onClick={() => setMode(null)} style={{ alignSelf: 'flex-start', background: 'none', border: 'none', fontSize: 11, color: 'var(--text-3)', cursor: 'pointer' }}>← Back</button>
            <div style={{ border: '2px dashed var(--border)', borderRadius: 10, padding: 32, textAlign: 'center', background: 'var(--bg-2)' }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>⬆</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>Drop packing list here</div>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>or click to browse · CSV · XLS · XLSX · PDF</div>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>Parser will extract {k.party.toLowerCase()}, line items, quantities, prices · review on the next step.</div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 6 }}>
              <ApiBtn label="Cancel" endpoint="" small onClick={onClose} />
              <ApiBtn label="Parse & create draft" endpoint={`POST /api/v1/${kind.toLowerCase()}/upload-packing-list`} small variant="gold" onClick={onClose} />
            </div>
          </div>
        )}

        {mode === 'manual' && (
          <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <button onClick={() => setMode(null)} style={{ alignSelf: 'flex-start', background: 'none', border: 'none', fontSize: 11, color: 'var(--text-3)', cursor: 'pointer' }}>← Back</button>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{k.party}</label>
              <select style={{ padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 6, fontSize: 12.5, background: 'var(--bg-1)', color: 'var(--text-1)' }}>
                <option>Select {k.party.toLowerCase()}…</option>
                {kind === 'PI' ? <>
                  <option>Aurum Watches GmbH</option>
                  <option>Crown Jewelers Ltd</option>
                  <option>Maison Royale SARL</option>
                  <option>Hôtel Belle Étoile</option>
                </> : <>
                  <option>Patek Philippe SA</option>
                  <option>Audemars Piguet</option>
                  <option>Manufaktura Złota</option>
                </>}
              </select>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Line items</label>
              <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 12, background: 'var(--bg-2)', fontSize: 11.5, color: 'var(--text-3)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 0.6fr 0.8fr 0.8fr', gap: 8, padding: '4px 0', fontSize: 10.5, color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  <span>Product</span><span>Qty</span><span>Unit price</span><span>Total</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 0.6fr 0.8fr 0.8fr', gap: 8, padding: '6px 0', borderTop: '1px solid var(--border)' }}>
                  <input placeholder="Search product…" style={{ padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, fontSize: 12, background: 'var(--bg-1)' }} />
                  <input placeholder="0" style={{ padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, fontSize: 12, background: 'var(--bg-1)' }} />
                  <input placeholder="0.00" style={{ padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, fontSize: 12, background: 'var(--bg-1)' }} />
                  <span style={{ fontSize: 11.5, color: 'var(--text-2)', alignSelf: 'center' }}>—</span>
                </div>
                <button style={{ marginTop: 8, padding: '4px 10px', fontSize: 11, background: 'none', border: '1px dashed var(--border)', borderRadius: 4, color: 'var(--text-3)', cursor: 'pointer' }}>+ Add line</button>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 6 }}>
              <ApiBtn label="Cancel" endpoint="" small onClick={onClose} />
              <ApiBtn label="Save as draft" endpoint={`POST /api/v1/${kind.toLowerCase()}`} small variant="gold" onClick={onClose} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Other documents (read-only history list)
// ─────────────────────────────────────────────────────────────────────────────
function OtherDocsList() {
  return (
    <div style={{ padding: 16, background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 10 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-1)' }}>Other documents</div>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>· read-only history (Invoice, Order, Customs, Shipping, Email)</span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 10, padding: '8px 10px', background: 'var(--badge-blue-bg)', border: '1px solid var(--badge-blue-border)', borderRadius: 6 }}>
        These are downstream documents generated automatically (from Proforma → Invoice, Order fulfillment, customs declarations, shipping paperwork, parsed emails). No create/approve workflow here — they're produced by upstream processes.
      </div>
      <Tbl
        columns={[
          { id: 'code',   header: 'Type',    cell: r => <span style={{ fontFamily: 'monospace', fontSize: 10.5, fontWeight: 700, color: 'var(--text-2)' }}>{r.code}</span>, width: 70 },
          { id: 'num',    header: 'Number',  cell: r => <span style={{ fontFamily: 'monospace', fontSize: 11.5, fontWeight: 600 }}>{r.num}</span> },
          { id: 'party',  header: 'Party',   cell: r => r.party },
          { id: 'amount', header: 'Amount',  cell: r => r.amount, align: 'right' },
          { id: 'date',   header: 'Date',    cell: r => <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{r.date}</span> },
          { id: 'wf',     header: 'wFirma',  cell: r => wfirmaChip(r.wfirma) },
          { id: 'act',    header: '',        cell: r => <div style={{ display: 'flex', gap: 4 }}>
              <ApiBtn label="👁" endpoint={`GET /api/v1/documents/${r.num}/view`} small />
              <ApiBtn label="↓" endpoint={`GET /api/v1/documents/${r.num}/download`} small />
            </div>, width: 80 },
        ]}
        rows={OTHER_DOCS}
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────
function DocumentsHubPage() {
  const [tab, setTab] = React.useState('PI'); // 'PI' | 'PZ' | 'other'
  const [docs, setDocs] = React.useState(SAMPLE_FLOW);
  const [creating, setCreating] = React.useState(null); // 'PI' | 'PZ' | null

  // Stub state transitions (visual only)
  const move = (kind, id, toLane, extra = {}) => {
    setDocs(prev => ({
      ...prev,
      [kind]: prev[kind].map(d => d.id === id ? { ...d, lane: toLane, ...extra } : d),
    }));
  };

  const handlers = (kind) => ({
    onApprove:   (d) => move(kind, d.id, 'approved', { approvedAt: new Date().toISOString().slice(0,16).replace('T',' '), approvedBy: 'You' }),
    onPost:      (d) => move(kind, d.id, 'posted',   { postedAt:   new Date().toISOString().slice(0,16).replace('T',' '), wfirmaId: `wf_${kind.toLowerCase()}_${Math.floor(Math.random()*99999)}` }),
    onUnapprove: (d) => move(kind, d.id, 'draft'),
    onEdit:      (d) => alert(`Edit → ${d.number} (stub)`),
    onDelete:    (d) => setDocs(prev => ({ ...prev, [kind]: prev[kind].filter(x => x.id !== d.id) })),
  });

  const kind = tab; // 'PI' or 'PZ'
  const list = (kind === 'PI' || kind === 'PZ') ? docs[kind] : [];
  const lanes = LANE_DEF.map(def => ({ def, docs: list.filter(d => d.lane === def.id) }));

  const tabBtn = (id, label, count) => {
    const active = tab === id;
    return (
      <button key={id} onClick={() => setTab(id)} style={{
        padding: '8px 14px', border: 'none', background: active ? 'var(--text-1)' : 'transparent',
        color: active ? 'var(--bg-1)' : 'var(--text-2)', borderRadius: 6, fontSize: 12.5,
        fontWeight: 700, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8,
      }}>
        {label}
        {count != null && <span style={{ fontSize: 11, fontWeight: 600, color: active ? 'var(--bg-1)' : 'var(--text-3)', opacity: 0.8 }}>· {count}</span>}
      </button>
    );
  };

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '16px 32px 32px', display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* Tabs + create CTA */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'inline-flex', gap: 4, background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 8, padding: 3 }}>
          {tabBtn('PI',    'Proforma',         docs.PI.length)}
          {tabBtn('PZ',    'PZ — Inbound',     docs.PZ.length)}
          {tabBtn('other', 'Other documents',  OTHER_DOCS.length)}
        </div>
        {(tab === 'PI' || tab === 'PZ') && (
          <div style={{ display: 'flex', gap: 8 }}>
            <ApiBtn label="⬆ Upload packing list" endpoint={`POST /api/v1/${tab.toLowerCase()}/upload-packing-list`} small onClick={() => setCreating(tab)} />
            <ApiBtn label={`+ New ${DOC_KIND[tab].label}`} endpoint={`POST /api/v1/${tab.toLowerCase()}`} small variant="gold" onClick={() => setCreating(tab)} />
          </div>
        )}
      </div>

      {/* Workflow explainer (concise, one-line) */}
      {(tab === 'PI' || tab === 'PZ') && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11.5, color: 'var(--text-2)', flexWrap: 'wrap' }}>
          <b style={{ color: 'var(--text-1)' }}>Flow:</b>
          <span><b>1.</b> Upload {tab === 'PI' ? 'sales' : 'supplier'} packing list <i>or</i> manual entry</span>
          <span style={{ color: 'var(--text-3)' }}>→</span>
          <span><b>2.</b> Draft created in app</span>
          <span style={{ color: 'var(--text-3)' }}>→</span>
          <span><b>3.</b> Operator approves</span>
          <span style={{ color: 'var(--text-3)' }}>→</span>
          <span><b>4.</b> One click → post to wFirma</span>
        </div>
      )}

      {/* Lanes */}
      {(tab === 'PI' || tab === 'PZ') && (
        <div style={{ display: 'flex', gap: 14, minHeight: 0, flex: 1 }}>
          {lanes.map(({ def, docs: laneDocs }) => (
            <Lane key={def.id} def={def} kind={kind} docs={laneDocs} handlers={handlers(kind)} />
          ))}
        </div>
      )}

      {/* Other documents tab */}
      {tab === 'other' && <OtherDocsList />}

      {creating && <CreateModal kind={creating} onClose={() => setCreating(null)} />}
    </div>
  );
}

window.DocumentsHubPage = DocumentsHubPage;
