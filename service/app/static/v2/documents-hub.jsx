// ─────────────────────────────────────────────────────────────────────────────
// Documents Hub — Wave-3 3-lane Kanban (W3-docs-crud)
//
// Authority: DC-1 through DC-16 (census amendment 2026-07-04, A-3)
// Wireframe: bundle `99c0e873` in docs/design/estrella-dashboard-wireframe.html
//   "Documents Hub — full CRUD for every document type"
//   PageHeader subtitle: "Full create / edit / delete / view / download."
//
// Constraint (DECISIONS.md 2026-07-04, verbatim):
//   "the wireframe's 13 controls wire to EXISTING backend authorities only;
//    Post-to-wFirma and every fiscal-class action goes through the deployed
//    write-gates unchanged — a UI slice never loosens or adds a write path;
//    closed-gate/absent-backend → honest gated/pending per R-Q3; any control
//    REQUIRING a new write path = STOP and report (Wave-4/backlog intake, not
//    UI work)."
//
// STOP-REPORT (Wave-4 intake — controls requiring new write paths, not built):
//   ① DC-12 Upload packing list — needs POST /api/v1/{pi|pz}/upload-packing-list
//      (no such route exists in routes_proforma.py or routes_pz.py)
//   ② DC-13 New Purchase Receipt — needs POST /api/v1/pz (document-level PZ
//      create; routes_pz.py only has POST /pz/process for batch processing)
//   ③ DC-14 Parse & create draft (upload modal, ParseModal upload mode) — same
//      missing endpoint as ①
//   All three rendered as Lesson-M honest-disabled buttons with census tags.
//
// DC-13 New Proforma → NAVIGATE to /v2/proforma (existing proforma creation
//   flow per §D "No-duplicate plan", WIREFRAME_AUTHORITY §D: navigate/link to
//   the EXISTING proforma surface rather than duplicating its modal).
//
// Tabs:    PI (Proforma Invoice) · PZ (Purchase/Inbound) · Other
// Lanes:   Draft → Approved → Posted to wFirma   (PI and PZ tabs)
// Other:   Read-only history list (Invoice, SAD, CI, AWB PDF, etc.)
//
// PI data:  PzApi.searchProformaDrafts() → all proforma drafts
// PZ data:  PzApi.listBatches() + PzApi.getBatchDetail(id) → PZ stage
// Other:    PzApi.getBatchFiles(batchId) for selected batch
//
// Write controls (PI lane — all through EXISTING pz-api.js methods):
//   Edit    → navigate to /v2/proforma (proforma-detail canonical owner)
//   Approve → PzApi.approveDraft (routes_proforma.py:6171, write-gated)
//   Delete  → PzApi.deleteDraft  (routes_proforma.py:6395)
//   Post→wF → PzApi.postDraftToWfirma (routes_proforma.py:8095, flag-gated)
//   Unapprove → PzApi.reopenDraft (routes_proforma.py:6219)
//   View    → open preview.html in new tab (routes_proforma.py:4771)
//   Download → open document.pdf URL (routes_proforma.py:2862)
//
// Write controls (PZ lane):
//   Edit / Approve / Unapprove → Lesson-M gated (no PZ-draft CRUD routes)
//   Post to wFirma → gated (existing flag gate: WFIRMA_CREATE_PZ_ALLOWED)
//     calls PzApi.pzCreate via existing routes_wfirma.py pz_create
//   View → PzApi.getBatchDetail → wfirma_pz_doc_id present → navigate to
//     existing wfirma setup / batch view
//   Download → PzApi.getPzPdf (routes_pz.py /files/{batch_id}/{filename})
// ─────────────────────────────────────────────────────────────────────────────

const { apiFetch } = window.EstrellaShared;
const PzApi = window.PzApi;

// ── CSS custom-property colour helpers ───────────────────────────────────────

const TONE = {
  green:   { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)'   },
  blue:    { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)'    },
  amber:   { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)'   },
  red:     { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)'     },
  neutral: { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
  gold:    { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)'   },
};

function Chip({ label, tone = 'neutral' }) {
  const c = TONE[tone] || TONE.neutral;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
      fontSize: 11, fontWeight: 600, letterSpacing: '0.02em',
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
    }}>
      {label || '—'}
    </span>
  );
}

function draftTone(state) {
  if (!state) return 'neutral';
  if (state === 'approved') return 'blue';
  if (state === 'posted')   return 'green';
  if (state === 'post_failed') return 'red';
  if (state === 'cancelled') return 'neutral';
  return 'amber'; // draft / editing
}

function fmtDate(ts) {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' });
  } catch (_) { return String(ts).slice(0, 10); }
}

// ── Lane definitions ─────────────────────────────────────────────────────────

const LANE_DEF = [
  { id: 'draft',    label: 'Draft',           tone: 'amber' },
  { id: 'approved', label: 'Approved',         tone: 'blue'  },
  { id: 'posted',   label: 'Posted to wFirma', tone: 'green' },
];

function draftLane(state) {
  if (!state) return 'draft';
  if (state === 'approved')              return 'approved';
  if (state === 'posted')                return 'posted';
  if (state === 'post_failed')           return 'approved'; // stays in approved lane, action still available
  return 'draft'; // draft / editing / pending_local / cancelled / other
}

// ── Toast (minimal inline) ───────────────────────────────────────────────────

function useToast() {
  const [msg, setMsg] = React.useState(null);
  const show = React.useCallback((text, isErr) => {
    setMsg({ text, isErr });
    setTimeout(() => setMsg(null), 3500);
  }, []);
  return { msg, show };
}

function Toast({ msg }) {
  if (!msg) return null;
  const tone = msg.isErr ? TONE.red : TONE.green;
  return (
    <div
      data-testid="documents-hub-toast"
      style={{
        position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
        padding: '10px 18px', borderRadius: 8,
        background: tone.bg, color: tone.fg, border: `1px solid ${tone.bd}`,
        fontSize: 12.5, fontWeight: 600, boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
        maxWidth: 400,
      }}
    >
      {msg.text}
    </div>
  );
}

// ── Confirm modal ─────────────────────────────────────────────────────────────

function ConfirmModal({ title, body, confirmLabel, onConfirm, onCancel, danger }) {
  return (
    <div
      data-testid="documents-hub-confirm-modal"
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onCancel}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 12,
          padding: '24px 28px', maxWidth: 420, width: '90vw',
          boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>{title}</div>
        <div style={{ fontSize: 12.5, color: 'var(--text-2)', marginBottom: 20, lineHeight: 1.5 }}>{body}</div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            data-testid="documents-hub-confirm-cancel"
            onClick={onCancel}
            style={{
              padding: '7px 16px', borderRadius: 6, border: '1px solid var(--border)',
              background: 'var(--card)', color: 'var(--text)', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            data-testid="documents-hub-confirm-ok"
            onClick={onConfirm}
            style={{
              padding: '7px 16px', borderRadius: 6, border: 'none',
              background: danger ? 'var(--badge-red-bg)' : 'var(--badge-green-bg)',
              color: danger ? 'var(--badge-red-text)' : 'var(--badge-green-text)',
              fontSize: 12, fontWeight: 700, cursor: 'pointer',
            }}
          >
            {confirmLabel || 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── PI (Proforma Invoice) Kanban ──────────────────────────────────────────────

function PiKanban({ toast, reload }) {
  const [drafts,  setDrafts]  = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error,   setError]   = React.useState(null);
  const [confirm, setConfirm] = React.useState(null); // {kind, draft}

  const load = React.useCallback(() => {
    setLoading(true); setError(null);
    apiFetch('/api/v1/proforma/search?limit=200')
      .then(res => { setDrafts(res && res.drafts ? res.drafts : (Array.isArray(res) ? res : [])); setLoading(false); })
      .catch(e  => { setError((e && e.message) || String(e)); setLoading(false); });
  }, []);

  React.useEffect(() => { load(); }, [load]);

  // Group by lane
  const byLane = React.useMemo(() => {
    const m = { draft: [], approved: [], posted: [] };
    if (!drafts) return m;
    drafts.forEach(d => { const l = draftLane(d.state); (m[l] || (m.draft)).push(d); });
    return m;
  }, [drafts]);

  const doApprove = (d) => {
    setConfirm({ kind: 'approve', draft: d });
  };
  const doDelete = (d) => {
    setConfirm({ kind: 'delete', draft: d });
  };
  const doPostToWfirma = (d) => {
    setConfirm({ kind: 'post', draft: d });
  };
  const doUnapprove = (d) => {
    setConfirm({ kind: 'unapprove', draft: d });
  };

  const execConfirm = async () => {
    if (!confirm) return;
    const { kind, draft } = confirm;
    setConfirm(null);
    try {
      if (kind === 'approve') {
        const res = await PzApi.approveDraft(draft.id, {
          expected_updated_at: draft.updated_at || '',
          confirm_token: 'YES_APPROVE_LOCAL_PROFORMA_DRAFT',
        });
        if (res && res.ok) { toast('Draft approved.'); load(); }
        else throw new Error((res && res.data && res.data.detail) || 'Approve failed');
      }
      if (kind === 'delete') {
        // cancel first then delete (cancel is required before hard-delete)
        const c = await PzApi.cancelDraft(draft.id, { confirm_token: 'YES_CANCEL_LOCAL_PROFORMA_DRAFT' });
        if (c && c.ok) {
          const d2 = await PzApi.deleteDraft(draft.id);
          if (d2 && d2.ok) { toast('Draft deleted.'); load(); }
          else throw new Error((d2 && d2.data && d2.data.detail) || 'Delete failed');
        } else {
          // If draft is already cancelled, try delete directly
          const d2 = await PzApi.deleteDraft(draft.id);
          if (d2 && d2.ok) { toast('Draft deleted.'); load(); }
          else throw new Error((c && c.data && c.data.detail) || 'Cancel/delete failed');
        }
      }
      if (kind === 'post') {
        const res = await PzApi.postDraftToWfirma(draft.id, {
          expected_updated_at: draft.updated_at || '',
          confirm_token: 'YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA',
        });
        if (res && res.ok) {
          const status = res.data && res.data.status;
          if (status === 'posted') { toast('Posted to wFirma.'); load(); }
          else if (status === 'failed') { toast('wFirma rejected the post — check readiness.', true); load(); }
          else { toast('Post response: ' + (status || JSON.stringify(res.data || ''))); load(); }
        } else throw new Error((res && res.data && res.data.detail) || 'Post failed');
      }
      if (kind === 'unapprove') {
        const res = await PzApi.reopenDraft(draft.id, {
          expected_updated_at: draft.updated_at || '',
          confirm_token: 'YES_REOPEN_LOCAL_PROFORMA_DRAFT',
        });
        if (res && res.ok) { toast('Draft re-opened to editing.'); load(); }
        else throw new Error((res && res.data && res.data.detail) || 'Re-open failed');
      }
    } catch (e) {
      toast((e && e.message) || String(e), true);
    }
  };

  if (loading) return <div style={{ color: 'var(--text-3)', padding: 32, textAlign: 'center' }}>Loading proforma drafts…</div>;
  if (error)   return <div style={{ color: 'var(--badge-red-text)', padding: 16, fontSize: 12 }}>Error: {error}</div>;

  return (
    <div>
      {confirm && (
        <ConfirmModal
          title={
            confirm.kind === 'approve'   ? 'Approve Draft'          :
            confirm.kind === 'delete'    ? 'Delete Draft'           :
            confirm.kind === 'post'      ? 'Post to wFirma'         :
                                           'Re-open Draft'
          }
          body={
            confirm.kind === 'approve'   ? `Approve draft for ${confirm.draft.client_name || confirm.draft.id}? This will lock it for wFirma posting.` :
            confirm.kind === 'delete'    ? `Permanently delete draft ${confirm.draft.id} (${confirm.draft.client_name || ''})? This cannot be undone.` :
            confirm.kind === 'post'      ? `Post draft ${confirm.draft.id} to wFirma? This will create a proforma invoice in wFirma. The write-gate must be open.` :
                                           `Re-open draft ${confirm.draft.id} back to editing?`
          }
          confirmLabel={
            confirm.kind === 'approve'   ? '✓ Approve'     :
            confirm.kind === 'delete'    ? '🗑 Delete'      :
            confirm.kind === 'post'      ? '↻ Post'         :
                                           '↶ Re-open'
          }
          danger={confirm.kind === 'delete'}
          onConfirm={execConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}

      {/* Flow legend — wireframe parity (W3-docs); static guide, no wiring change */}
      <div
        data-testid="documents-hub-pi-flow"
        style={{ marginBottom: 12, padding: '8px 14px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11.5, color: 'var(--text-2)', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}
      >
        <span style={{ fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 10 }}>Flow</span>
        <span><strong style={{ color: 'var(--text)' }}>1.</strong> Upload sales packing list or manual entry</span>
        <span style={{ color: 'var(--text-3)' }}>→</span>
        <span><strong style={{ color: 'var(--text)' }}>2.</strong> Draft created in app</span>
        <span style={{ color: 'var(--text-3)' }}>→</span>
        <span><strong style={{ color: 'var(--text)' }}>3.</strong> Operator approves</span>
        <span style={{ color: 'var(--text-3)' }}>→</span>
        <span><strong style={{ color: 'var(--text)' }}>4.</strong> One click → post to wFirma</span>
      </div>

      {/* Kanban 3-lane grid */}
      <div
        data-testid="documents-hub-pi-kanban"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, alignItems: 'start' }}
      >
        {LANE_DEF.map(lane => (
          <PiLane
            key={lane.id}
            lane={lane}
            items={byLane[lane.id] || []}
            onApprove={doApprove}
            onDelete={doDelete}
            onPost={doPostToWfirma}
            onUnapprove={doUnapprove}
          />
        ))}
      </div>

      {/* Upload packing list — DC-12 — Wave-4 gated (no POST /api/v1/pi/upload-packing-list) */}
      <div
        data-testid="documents-hub-pi-upload-gated"
        style={{ marginTop: 12, padding: '10px 14px', background: 'var(--bg-subtle)', border: '1px dashed var(--border)', borderRadius: 8, display: 'flex', gap: 10, alignItems: 'center' }}
      >
        <button
          data-testid="documents-hub-btn-upload-packing-list"
          disabled
          title="DC-12 · Wave-4: requires POST /api/v1/pi/upload-packing-list (not yet deployed)"
          style={{ padding: '6px 14px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11.5, fontWeight: 600, cursor: 'not-allowed', opacity: 0.55 }}
        >
          ⬆ Upload packing list
        </button>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>DC-12 · Backend pending — POST /api/v1/pi/upload-packing-list (Wave-4)</span>
      </div>
    </div>
  );
}

function PiLane({ lane, items, onApprove, onDelete, onPost, onUnapprove }) {
  const tone = TONE[lane.tone] || TONE.neutral;
  return (
    <div
      data-testid={`documents-hub-pi-lane-${lane.id}`}
      style={{
        background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10,
        overflow: 'hidden', minHeight: 120,
      }}
    >
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--border)',
        background: tone.bg, display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{ fontSize: 11.5, fontWeight: 700, color: tone.fg }}>{lane.label}</span>
        <span style={{
          marginLeft: 'auto', fontSize: 11, fontWeight: 700, color: tone.fg,
          background: 'rgba(255,255,255,0.35)', borderRadius: 10, padding: '1px 7px',
        }}>{items.length}</span>
      </div>

      {items.length === 0 && (
        <div style={{ padding: '20px 14px', color: 'var(--text-3)', fontSize: 11.5, textAlign: 'center' }}>
          No drafts in this lane
        </div>
      )}

      {items.map(d => <PiCard key={d.id} draft={d} lane={lane.id} onApprove={onApprove} onDelete={onDelete} onPost={onPost} onUnapprove={onUnapprove} />)}
    </div>
  );
}

function PiCard({ draft, lane, onApprove, onDelete, onPost, onUnapprove }) {
  const BASE = window.location.origin;
  const previewUrl = `${BASE}/api/v1/proforma/draft/${draft.id}/preview.html`;
  const pdfUrl     = draft.batch_id && draft.client_name
    ? `${BASE}/api/v1/proforma/${encodeURIComponent(draft.batch_id)}/${encodeURIComponent(draft.client_name)}/document.pdf`
    : null;

  return (
    <div
      data-testid={`documents-hub-pi-card-${draft.id}`}
      style={{
        margin: '8px 10px', padding: '10px 12px', background: 'var(--bg-subtle)',
        border: '1px solid var(--border-subtle)', borderRadius: 8, fontSize: 12,
      }}
    >
      {/* Card header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, color: 'var(--text)', fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {draft.client_name || `Draft #${draft.id}`}
          </div>
          {draft.batch_id && (
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2, fontFamily: 'monospace' }}>
              {draft.batch_id}
            </div>
          )}
        </div>
        <Chip label={draft.state || 'draft'} tone={draftTone(draft.state)} />
      </div>

      {/* Meta row */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 10, fontSize: 11, color: 'var(--text-2)' }}>
        {draft.currency && <span>{draft.currency}</span>}
        {draft.total_value !== undefined && draft.total_value !== null && (
          <span style={{ fontFamily: 'monospace' }}>{Number(draft.total_value).toFixed(2)}</span>
        )}
        {draft.updated_at && <span>{fmtDate(draft.updated_at)}</span>}
      </div>

      {/* Lane-specific actions */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>

        {/* DRAFT LANE — DC-4 Edit, DC-5/DC-6 Approve, DC-7 Delete */}
        {lane === 'draft' && (
          <>
            {/* DC-4 Edit → navigate to proforma detail (§D canonical owner) */}
            <a
              data-testid={`documents-hub-pi-btn-edit-${draft.id}`}
              href={`/v2/proforma?draft_id=${draft.id}`}
              title="DC-4 · Edit — opens proforma detail page (canonical owner per §D)"
              style={{
                display: 'inline-flex', alignItems: 'center', padding: '4px 10px',
                borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)',
                color: 'var(--text)', fontSize: 11, fontWeight: 600, textDecoration: 'none',
                cursor: 'pointer',
              }}
            >
              Edit
            </a>

            {/* DC-5 Approve */}
            <button
              data-testid={`documents-hub-pi-btn-approve-${draft.id}`}
              onClick={() => onApprove(draft)}
              title="DC-5 · Approve — POST /api/v1/proforma/draft/{id}/approve (routes_proforma.py:6171)"
              style={{
                padding: '4px 10px', borderRadius: 4, border: 'none',
                background: TONE.blue.bg, color: TONE.blue.fg,
                fontSize: 11, fontWeight: 700, cursor: 'pointer',
              }}
            >
              ✓ Approve
            </button>

            {/* DC-6 Delete */}
            <button
              data-testid={`documents-hub-pi-btn-delete-${draft.id}`}
              onClick={() => onDelete(draft)}
              title="DC-6 · Delete — DELETE /api/v1/proforma/draft/{id} (routes_proforma.py:6395)"
              style={{
                padding: '4px 10px', borderRadius: 4, border: `1px solid ${TONE.red.bd}`,
                background: TONE.red.bg, color: TONE.red.fg,
                fontSize: 11, fontWeight: 600, cursor: 'pointer',
              }}
            >
              🗑
            </button>
          </>
        )}

        {/* APPROVED LANE — DC-8 Post to wFirma, DC-9 Unapprove */}
        {lane === 'approved' && (
          <>
            {/* DC-8 Post to wFirma */}
            <button
              data-testid={`documents-hub-pi-btn-post-${draft.id}`}
              onClick={() => onPost(draft)}
              title="DC-8 · Post to wFirma — POST /api/v1/proforma/draft/{id}/post (routes_proforma.py:8095) — write-gate WFIRMA_CREATE_PROFORMA_ALLOWED"
              style={{
                padding: '4px 10px', borderRadius: 4, border: 'none',
                background: TONE.amber.bg, color: TONE.amber.fg,
                fontSize: 11, fontWeight: 700, cursor: 'pointer',
              }}
            >
              ↻ Post to wFirma
            </button>

            {/* DC-9 Unapprove */}
            <button
              data-testid={`documents-hub-pi-btn-unapprove-${draft.id}`}
              onClick={() => onUnapprove(draft)}
              title="DC-9 · Unapprove — POST /api/v1/proforma/draft/{id}/re-open (routes_proforma.py:6219)"
              style={{
                padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)',
                background: 'var(--card)', color: 'var(--text)',
                fontSize: 11, fontWeight: 600, cursor: 'pointer',
              }}
            >
              ↶ Unapprove
            </button>
          </>
        )}

        {/* POSTED LANE — DC-10 View, DC-11 Download */}
        {lane === 'posted' && (
          <>
            {/* DC-10 View */}
            <a
              data-testid={`documents-hub-pi-btn-view-${draft.id}`}
              href={previewUrl}
              target="_blank"
              rel="noopener noreferrer"
              title="DC-10 · View — GET /api/v1/proforma/draft/{id}/preview.html (routes_proforma.py:4771)"
              style={{
                display: 'inline-flex', alignItems: 'center', padding: '4px 10px',
                borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)',
                color: 'var(--text)', fontSize: 11, fontWeight: 600, textDecoration: 'none',
              }}
            >
              👁 View
            </a>

            {/* DC-11 Download */}
            {pdfUrl ? (
              <a
                data-testid={`documents-hub-pi-btn-download-${draft.id}`}
                href={pdfUrl}
                target="_blank"
                rel="noopener noreferrer"
                title="DC-11 · Download PDF — GET /api/v1/proforma/{batch_id}/{client}/document.pdf (routes_proforma.py:2862)"
                style={{
                  display: 'inline-flex', alignItems: 'center', padding: '4px 10px',
                  borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)',
                  color: 'var(--text)', fontSize: 11, fontWeight: 600, textDecoration: 'none',
                }}
              >
                ↓ Download
              </a>
            ) : (
              <button
                data-testid={`documents-hub-pi-btn-download-${draft.id}`}
                disabled
                title="DC-11 · Download — batch_id or client_name missing on draft"
                style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11, fontWeight: 600, opacity: 0.5, cursor: 'not-allowed' }}
              >
                ↓ Download
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── PZ (Purchase/Inbound) Kanban ─────────────────────────────────────────────

function pzLane(batch) {
  // Map batch pz_status → kanban lane
  const s = (batch.pz_status || '').toLowerCase();
  if (s.includes('exported') || s.includes('posted'))    return 'posted';
  if (s.includes('generated') || s.includes('ready'))    return 'approved'; // PZ generated = "approved" equivalent
  return 'draft'; // pending / blocked / etc.
}

function PzKanban({ toast }) {
  const [batches, setBatches] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error,   setError]   = React.useState(null);

  const load = React.useCallback(() => {
    setLoading(true); setError(null);
    PzApi.listBatches()
      .then(res => {
        const rows = res && res.ok && Array.isArray(res.data) ? res.data
          : (Array.isArray(res) ? res : []);
        setBatches(rows);
        setLoading(false);
      })
      .catch(e => { setError((e && e.message) || String(e)); setLoading(false); });
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const byLane = React.useMemo(() => {
    const m = { draft: [], approved: [], posted: [] };
    if (!batches) return m;
    batches.forEach(b => { const l = pzLane(b); (m[l] || (m.draft)).push(b); });
    return m;
  }, [batches]);

  if (loading) return <div style={{ color: 'var(--text-3)', padding: 32, textAlign: 'center' }}>Loading PZ batches…</div>;
  if (error)   return <div style={{ color: 'var(--badge-red-text)', padding: 16, fontSize: 12 }}>Error: {error}</div>;

  return (
    <div>
      <div
        data-testid="documents-hub-pz-kanban"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, alignItems: 'start' }}
      >
        {LANE_DEF.map(lane => (
          <PzLane key={lane.id} lane={lane} items={byLane[lane.id] || []} toast={toast} />
        ))}
      </div>

      {/* New Purchase Receipt — DC-13 PZ part — Wave-4 gated */}
      <div
        data-testid="documents-hub-pz-new-gated"
        style={{ marginTop: 12, padding: '10px 14px', background: 'var(--bg-subtle)', border: '1px dashed var(--border)', borderRadius: 8, display: 'flex', gap: 10, alignItems: 'center' }}
      >
        <button
          data-testid="documents-hub-btn-new-pz"
          disabled
          title="DC-13 · Wave-4: requires POST /api/v1/pz (document-level PZ create — not yet deployed; routes_pz.py has POST /pz/process for batch processing only)"
          style={{ padding: '6px 14px', borderRadius: 5, border: 'none', background: TONE.amber.bg, color: TONE.amber.fg, fontSize: 11.5, fontWeight: 600, cursor: 'not-allowed', opacity: 0.55 }}
        >
          + New Purchase Receipt
        </button>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>DC-13 · Backend pending — POST /api/v1/pz document-level create (Wave-4)</span>
      </div>
    </div>
  );
}

function PzLane({ lane, items, toast }) {
  const tone = TONE[lane.tone] || TONE.neutral;
  return (
    <div
      data-testid={`documents-hub-pz-lane-${lane.id}`}
      style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', minHeight: 120 }}
    >
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', background: tone.bg, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11.5, fontWeight: 700, color: tone.fg }}>{lane.label}</span>
        <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 700, color: tone.fg, background: 'rgba(255,255,255,0.35)', borderRadius: 10, padding: '1px 7px' }}>{items.length}</span>
      </div>
      {items.length === 0 && (
        <div style={{ padding: '20px 14px', color: 'var(--text-3)', fontSize: 11.5, textAlign: 'center' }}>No batches in this lane</div>
      )}
      {items.map(b => <PzCard key={b.batch_id} batch={b} lane={lane.id} toast={toast} />)}
    </div>
  );
}

function PzCard({ batch, lane, toast }) {
  const BASE = window.location.origin;
  const batchId = batch.batch_id;
  // PZ PDF: GET /api/v1/files/{batch_id}/PZ_NNNN_YYYY.pdf (routes_pz.py:1421)
  // We use the known output filename pattern; if not known, show gated button
  const pzFilename = batch.pz_filename || null;
  const pdfUrl = pzFilename ? `${BASE}/api/v1/files/${encodeURIComponent(batchId)}/${encodeURIComponent(pzFilename)}` : null;

  // PZ View: if wfirma_pz_doc_id present → navigate to batch detail or wfirma view
  const pzDocId = batch.wfirma_pz_doc_id || null;
  const viewUrl = pzDocId
    ? `${BASE}/api/v1/dashboard/batches/${encodeURIComponent(batchId)}`
    : null;

  return (
    <div
      data-testid={`documents-hub-pz-card-${batchId}`}
      style={{ margin: '8px 10px', padding: '10px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)', borderRadius: 8, fontSize: 12 }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, color: 'var(--text)', fontSize: 12, fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {batch.doc_no || batch.tracking_no || batchId}
          </div>
          {batch.tracking_no && batch.doc_no && (
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2, fontFamily: 'monospace' }}>{batch.tracking_no}</div>
          )}
        </div>
        <Chip label={batch.pz_status || 'Pending'} tone={
          (batch.pz_status || '').toLowerCase().includes('export') || (batch.pz_status || '').toLowerCase().includes('post') ? 'green' :
          (batch.pz_status || '').toLowerCase().includes('generat') || (batch.pz_status || '').toLowerCase().includes('ready') ? 'blue' :
          (batch.pz_status || '').toLowerCase().includes('block') ? 'red' : 'amber'
        } />
      </div>

      <div style={{ display: 'flex', gap: 12, marginBottom: 10, fontSize: 11, color: 'var(--text-2)' }}>
        {batch.timestamp && <span>{fmtDate(batch.timestamp)}</span>}
        {pzDocId && <span style={{ fontFamily: 'monospace', fontSize: 10.5 }}>wF:{pzDocId}</span>}
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>

        {/* DRAFT LANE — Edit/Approve/Delete — gated: no PZ draft CRUD routes */}
        {lane === 'draft' && (
          <>
            <button
              data-testid={`documents-hub-pz-btn-edit-${batchId}`}
              disabled
              title="Edit PZ — Lesson M: no PZ draft CRUD route exists; PZ documents are managed through batch processing (routes_pz.py). Wave-4 scope."
              style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11, fontWeight: 600, cursor: 'not-allowed', opacity: 0.5 }}
            >
              Edit
            </button>
            <button
              data-testid={`documents-hub-pz-btn-approve-${batchId}`}
              disabled
              title="Approve PZ — Lesson M: no PZ draft approve route; approval happens through PZ process (routes_pz.py). Wave-4 scope."
              style={{ padding: '4px 10px', borderRadius: 4, border: 'none', background: TONE.blue.bg, color: TONE.blue.fg, fontSize: 11, fontWeight: 700, cursor: 'not-allowed', opacity: 0.5 }}
            >
              ✓ Approve
            </button>
          </>
        )}

        {/* APPROVED LANE — Post to wFirma (gated), Unapprove (gated) */}
        {lane === 'approved' && (
          <>
            {/* Post to wFirma — existing flag-gated route routes_wfirma.py pz_create */}
            <a
              data-testid={`documents-hub-pz-btn-post-${batchId}`}
              href={`/v2/shipment_detail?batch_id=${encodeURIComponent(batchId)}`}
              title="Post PZ to wFirma — navigates to Shipment Detail Tab 4 where POST /shipment/{batch_id}/wfirma/pz_create is wired (write-gate: WFIRMA_CREATE_PZ_ALLOWED)"
              style={{
                display: 'inline-flex', alignItems: 'center', padding: '4px 10px',
                borderRadius: 4, border: 'none', background: TONE.amber.bg, color: TONE.amber.fg,
                fontSize: 11, fontWeight: 700, textDecoration: 'none',
              }}
            >
              ↻ Post to wFirma
            </a>
            <button
              data-testid={`documents-hub-pz-btn-unapprove-${batchId}`}
              disabled
              title="Unapprove PZ — Lesson M: no PZ unapprove route. Wave-4 scope."
              style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11, fontWeight: 600, cursor: 'not-allowed', opacity: 0.5 }}
            >
              ↶ Unapprove
            </button>
          </>
        )}

        {/* POSTED LANE — View, Download */}
        {lane === 'posted' && (
          <>
            {/* DC-10 equivalent for PZ — View */}
            {viewUrl ? (
              <a
                data-testid={`documents-hub-pz-btn-view-${batchId}`}
                href={viewUrl}
                target="_blank"
                rel="noopener noreferrer"
                title="View PZ — GET /api/v1/dashboard/batches/{batch_id} (routes_dashboard.py:569)"
                style={{
                  display: 'inline-flex', alignItems: 'center', padding: '4px 10px',
                  borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)',
                  color: 'var(--text)', fontSize: 11, fontWeight: 600, textDecoration: 'none',
                }}
              >
                👁 View
              </a>
            ) : (
              <button
                data-testid={`documents-hub-pz-btn-view-${batchId}`}
                disabled
                title="View PZ — wfirma_pz_doc_id not yet assigned"
                style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11, fontWeight: 600, opacity: 0.5, cursor: 'not-allowed' }}
              >
                👁 View
              </button>
            )}

            {/* DC-11 equivalent for PZ — Download */}
            {pdfUrl ? (
              <a
                data-testid={`documents-hub-pz-btn-download-${batchId}`}
                href={pdfUrl}
                target="_blank"
                rel="noopener noreferrer"
                title="Download PZ — GET /api/v1/files/{batch_id}/{filename} (routes_pz.py:1421)"
                style={{
                  display: 'inline-flex', alignItems: 'center', padding: '4px 10px',
                  borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)',
                  color: 'var(--text)', fontSize: 11, fontWeight: 600, textDecoration: 'none',
                }}
              >
                ↓ Download
              </a>
            ) : (
              <a
                data-testid={`documents-hub-pz-btn-download-${batchId}`}
                href={`/v2/shipment_detail?batch_id=${encodeURIComponent(batchId)}`}
                title="Download PZ — opens Shipment Detail where file links are available (GET /api/v1/dashboard/batches/{id}/files)"
                style={{
                  display: 'inline-flex', alignItems: 'center', padding: '4px 10px',
                  borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)',
                  color: 'var(--text)', fontSize: 11, fontWeight: 600, textDecoration: 'none',
                }}
              >
                ↓ Download
              </a>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Other Documents tab ───────────────────────────────────────────────────────

function OtherDocs() {
  const [batches, setBatches] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error,   setError]   = React.useState(null);
  const [selBatch, setSelBatch] = React.useState('');
  const [files, setFiles]     = React.useState(null);
  const [filesLoading, setFilesLoading] = React.useState(false);

  const load = React.useCallback(() => {
    setLoading(true); setError(null);
    PzApi.listBatches()
      .then(res => {
        const rows = res && res.ok && Array.isArray(res.data) ? res.data : (Array.isArray(res) ? res : []);
        setBatches(rows);
        setLoading(false);
        if (rows.length > 0 && !selBatch) setSelBatch(rows[0].batch_id);
      })
      .catch(e => { setError((e && e.message) || String(e)); setLoading(false); });
  }, [selBatch]);

  React.useEffect(() => { load(); }, []);

  React.useEffect(() => {
    if (!selBatch) return;
    setFilesLoading(true);
    PzApi.getBatchFiles(selBatch)
      .then(res => {
        const f = res && res.ok ? (res.data || {}) : {};
        setFiles(f);
        setFilesLoading(false);
      })
      .catch(() => { setFiles({}); setFilesLoading(false); });
  }, [selBatch]);

  if (loading) return <div style={{ color: 'var(--text-3)', padding: 32, textAlign: 'center' }}>Loading…</div>;
  if (error)   return <div style={{ color: 'var(--badge-red-text)', padding: 16 }}>Error: {error}</div>;

  const BASE = window.location.origin;

  // Flatten files object to rows
  const fileRows = [];
  if (files) {
    Object.entries(files).forEach(([key, val]) => {
      if (typeof val === 'string') fileRows.push({ name: key, url: val });
      else if (val && typeof val === 'object' && val.filename) {
        fileRows.push({
          name: val.doc_type || val.filename || key,
          url: `${BASE}/api/v1/files/${encodeURIComponent(selBatch)}/${encodeURIComponent(val.filename)}`,
        });
      }
    });
  }

  return (
    <div data-testid="documents-hub-other-tab">
      {/* Batch selector */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16 }}>
        <label style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-2)' }}>Batch:</label>
        <select
          data-testid="documents-hub-other-batch-select"
          value={selBatch}
          onChange={e => setSelBatch(e.target.value)}
          style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', fontSize: 12 }}
        >
          {(batches || []).map(b => (
            <option key={b.batch_id} value={b.batch_id}>
              {b.doc_no || b.tracking_no || b.batch_id}
            </option>
          ))}
        </select>
      </div>

      {filesLoading && <div style={{ color: 'var(--text-3)', fontSize: 12 }}>Loading files…</div>}

      {!filesLoading && fileRows.length === 0 && (
        <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)', border: '1px dashed var(--border)', borderRadius: 10, fontSize: 13 }}>
          No documents found for this batch.
        </div>
      )}

      {!filesLoading && fileRows.length > 0 && (
        <div
          data-testid="documents-hub-other-files-table"
          style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}
        >
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)' }}>
                {['Document', 'View', 'Download'].map(h => (
                  <th key={h} style={{ padding: '9px 14px', textAlign: 'left', fontWeight: 700, color: 'var(--text-3)', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.07em', borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fileRows.map((f, i) => (
                <tr
                  key={i}
                  data-testid={`documents-hub-other-file-row-${i}`}
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '10px 14px', color: 'var(--text)', fontWeight: 600 }}>{f.name}</td>
                  {/* DC-15 View */}
                  <td style={{ padding: '10px 14px' }}>
                    <a
                      data-testid={`documents-hub-other-btn-view-${i}`}
                      href={f.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="DC-15 · View — GET /api/v1/files/{batch_id}/{filename} (routes_pz.py:1421)"
                      style={{
                        display: 'inline-flex', alignItems: 'center', padding: '4px 10px',
                        borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg-subtle)',
                        color: 'var(--text)', fontSize: 11, fontWeight: 600, textDecoration: 'none',
                      }}
                    >
                      👁 View
                    </a>
                  </td>
                  {/* DC-15 Download */}
                  <td style={{ padding: '10px 14px' }}>
                    <a
                      data-testid={`documents-hub-other-btn-download-${i}`}
                      href={f.url}
                      download
                      title="DC-15 · Download — GET /api/v1/files/{batch_id}/{filename} (routes_pz.py:1421)"
                      style={{
                        display: 'inline-flex', alignItems: 'center', padding: '4px 10px',
                        borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg-subtle)',
                        color: 'var(--text)', fontSize: 11, fontWeight: 600, textDecoration: 'none',
                      }}
                    >
                      ↓ Download
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Main DocumentsHubPage ─────────────────────────────────────────────────────

const DOC_KIND = {
  PI:    { label: 'Proforma',          code: 'PI' },
  PZ:    { label: 'Purchase Receipt',  code: 'PZ' },
  other: { label: 'Other Documents',   code: 'other' },
};

function DocumentsHubPage() {
  const [tab, setTab] = React.useState('PI');
  const { msg, show: toast } = useToast();

  // Summary counts (DC-1 3-tab counts)
  const [summary, setSummary] = React.useState(null);

  React.useEffect(() => {
    // Load summary counters from dashboard batches (lightweight)
    PzApi.listBatches().then(res => {
      const rows = res && res.ok && Array.isArray(res.data) ? res.data : (Array.isArray(res) ? res : []);
      setSummary({
        pz_total:      rows.length,
        pz_posted:     rows.filter(b => (b.pz_status || '').toLowerCase().includes('export') || (b.pz_status || '').toLowerCase().includes('post')).length,
        sad_present:   rows.filter(b => (b.sad_status || '').toLowerCase() !== 'missing').length,
      });
    }).catch(() => {});
  }, []);

  return (
    <div
      data-testid="documents-hub-root"
      style={{ flex: 1, overflow: 'auto', padding: '16px 32px 32px', display: 'flex', flexDirection: 'column', gap: 16 }}
    >
      {/* Header — DC-1 (3 tabs), DC-16 (Export CSV disabled) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 4 }}>
            Documents Hub
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-2)' }}>
            Full create / edit / delete / view / download
          </div>
        </div>

        {/* DC-16 — Export CSV (disabled, per wireframe bundle 99c0e873 App.jsx template line 666) */}
        <button
          data-testid="documents-hub-btn-export-csv"
          disabled
          title="DC-16 · Export CSV — disabled in wireframe (App.jsx template line 666: opacity 0.7, cursor not-allowed)"
          style={{
            padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)',
            background: 'var(--card)', color: 'var(--text-3)', fontSize: 12,
            fontWeight: 600, cursor: 'not-allowed', opacity: 0.7,
          }}
        >
          ⬇ Export CSV
        </button>
      </div>

      {/* Summary strip */}
      {summary && (
        <div data-testid="documents-hub-summary" style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {[
            { label: 'PZ Batches',     value: summary.pz_total },
            { label: 'PZ Posted',      value: summary.pz_posted },
            { label: 'SAD Present',    value: summary.sad_present },
          ].map(({ label, value }) => (
            <div key={label} style={{ padding: '10px 18px', background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, boxShadow: '0 1px 2px var(--shadow)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* DC-1 — 3-tab bar: PI / PZ / Other */}
      <div
        data-testid="documents-hub-tabs"
        style={{ display: 'flex', gap: 0, borderBottom: '2px solid var(--border)', marginBottom: 4 }}
      >
        {Object.entries(DOC_KIND).map(([key, kind]) => {
          const active = tab === key;
          return (
            <button
              key={key}
              data-testid={`documents-hub-tab-${key.toLowerCase()}`}
              onClick={() => setTab(key)}
              style={{
                padding: '9px 20px', fontSize: 12.5, fontWeight: active ? 700 : 500,
                color: active ? 'var(--text)' : 'var(--text-3)',
                background: 'transparent', border: 'none', borderBottom: active ? '2px solid var(--text)' : '2px solid transparent',
                marginBottom: -2, cursor: 'pointer', transition: 'color 0.15s',
              }}
            >
              {kind.label}
            </button>
          );
        })}

        {/* DC-2 lane-count annotation per active tab (shown inline in tab bar) */}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center', paddingBottom: 6 }}>
          {LANE_DEF.map(l => (
            <span key={l.id} style={{ fontSize: 10.5, color: 'var(--text-3)', display: 'flex', alignItems: 'center', gap: 3 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: TONE[l.tone].bg, border: `1px solid ${TONE[l.tone].bd}`, display: 'inline-block' }} />
              {l.label}
            </span>
          ))}
        </div>
      </div>

      {/* Tab-level toolbar (DC-3 per-tab) */}
      {tab !== 'other' && (
        <div
          data-testid={`documents-hub-toolbar-${tab.toLowerCase()}`}
          style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}
        >
          {/* Upload packing list — DC-12 — Wave-4 gated for both tabs */}
          {/* (also shown inside PiKanban/PzKanban per-tab; this is the canonical toolbar position) */}

          {/* + New Proforma — PI tab — NAVIGATE to /v2/proforma (§D canonical owner) */}
          {tab === 'PI' && (
            <a
              data-testid="documents-hub-btn-new-pi"
              href="/v2/proforma"
              title="DC-13 (PI part) · New Proforma — navigates to /v2/proforma (canonical proforma creation flow per §D, WIREFRAME_AUTHORITY §D no-duplicate plan)"
              style={{
                display: 'inline-flex', alignItems: 'center', padding: '7px 14px',
                borderRadius: 6, border: 'none', background: TONE.amber.bg, color: TONE.amber.fg,
                fontSize: 12, fontWeight: 700, textDecoration: 'none',
              }}
            >
              + New Proforma
            </a>
          )}

          {/* + New Purchase Receipt — PZ tab — DC-13 gated */}
          {tab === 'PZ' && (
            <button
              data-testid="documents-hub-btn-new-pz-toolbar"
              disabled
              title="DC-13 (PZ part) · New Purchase Receipt — Wave-4: requires POST /api/v1/pz document-level create (routes_pz.py has only POST /pz/process for batch processing)"
              style={{ padding: '7px 14px', borderRadius: 6, border: 'none', background: TONE.amber.bg, color: TONE.amber.fg, fontSize: 12, fontWeight: 700, cursor: 'not-allowed', opacity: 0.55 }}
            >
              + New Purchase Receipt
            </button>
          )}

          {/* Upload packing list — DC-12 — Wave-4 gated */}
          <button
            data-testid={`documents-hub-btn-upload-${tab.toLowerCase()}`}
            disabled
            title={`DC-12 · Upload packing list — Wave-4: requires POST /api/v1/${tab.toLowerCase()}/upload-packing-list (not yet deployed)`}
            style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 12, fontWeight: 600, cursor: 'not-allowed', opacity: 0.55 }}
          >
            ⬆ Upload packing list
          </button>

          {/* DC-14 CreateModal — Wave-4 gated */}
          {/* CreateModal is intentionally absent: Parse & create draft requires the same missing endpoints (DC-12) */}
          {/* Lesson-M honest pending note rendered via disabled Upload button above */}
        </div>
      )}

      {/* Tab body */}
      <div data-testid="documents-hub-tab-body">
        {tab === 'PI'    && <PiKanban toast={toast} />}
        {tab === 'PZ'    && <PzKanban toast={toast} />}
        {tab === 'other' && <OtherDocs />}
      </div>

      <Toast msg={msg} />
    </div>
  );
}

window.DocumentsHubPage = DocumentsHubPage;
