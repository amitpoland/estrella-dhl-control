// use-dhl-account-resolution.jsx — reactive DHL account state for the AWB flow.
//
// Operator ruling 2026-07-20. The ONE resolution authority is the backend
// ``resolve_dhl_billing_account()``; this hook only *asks* it and holds the
// answer. It derives nothing:
//
//   * it never picks a default account
//   * it never decides AWB eligibility (that is the server's ``awb_blocked``)
//   * it never falls back to another party's account
//   * it never sees a full account number — the server sends masked values only
//
// Reactive contract:
//
//   sender change    → reload sender accounts, clear stale selection, re-resolve
//   receiver change  → reload receiver accounts, clear stale selection, re-resolve
//   billing change   → clear an incompatible billing_account_id, re-resolve
//
// Stale-response safety: sender/receiver can be changed faster than the network
// answers. Every request carries a sequence number and only the newest one is
// allowed to write state, so an older in-flight reply can never overwrite a
// newer selection.

function useDhlAccountResolution({ senderContractorId, receiverContractorId,
                                   thirdPartyContractorId }) {
  const [billingParty, setBillingPartyRaw] = React.useState('sender');
  const [billingAccountId, setBillingAccountId] = React.useState(null);
  const [resolution, setResolution] = React.useState(null);
  const [loading, setLoading] = React.useState(false);

  // Accounts per party — reloaded when that party changes.
  const [senderAccounts, setSenderAccounts] = React.useState([]);
  const [receiverAccounts, setReceiverAccounts] = React.useState([]);

  // Monotonic request counters; only the newest reply may commit.
  const resolveSeq = React.useRef(0);
  const senderSeq = React.useRef(0);
  const receiverSeq = React.useRef(0);

  // ── Sender change → reload accounts + clear stale selection ───────────
  React.useEffect(() => {
    const seq = ++senderSeq.current;
    setBillingAccountId(null);           // stale selection cannot survive
    if (!senderContractorId) {
      setSenderAccounts([]);
      return;
    }
    PzApi.listCarrierAccounts(senderContractorId).then(res => {
      if (seq !== senderSeq.current) return;   // superseded
      setSenderAccounts(res.ok ? ((res.data && res.data.accounts) || []) : []);
    }).catch(() => {
      if (seq !== senderSeq.current) return;
      setSenderAccounts([]);
    });
  }, [senderContractorId]);

  // ── Receiver change → reload accounts + clear stale selection ─────────
  React.useEffect(() => {
    const seq = ++receiverSeq.current;
    setBillingAccountId(null);
    if (!receiverContractorId) {
      setReceiverAccounts([]);
      return;
    }
    PzApi.listCarrierAccounts(receiverContractorId).then(res => {
      if (seq !== receiverSeq.current) return;
      setReceiverAccounts(res.ok ? ((res.data && res.data.accounts) || []) : []);
    }).catch(() => {
      if (seq !== receiverSeq.current) return;
      setReceiverAccounts([]);
    });
  }, [receiverContractorId]);

  // Billing party change clears an account id that belonged to the old party.
  const setBillingParty = React.useCallback((party) => {
    setBillingPartyRaw(party);
    setBillingAccountId(null);
  }, []);

  // ── Resolve through the canonical backend authority ───────────────────
  React.useEffect(() => {
    const seq = ++resolveSeq.current;
    if (!senderContractorId) {
      setResolution(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    PzApi.resolveDhlAccounts({
      sender_contractor_id: senderContractorId,
      receiver_contractor_id: receiverContractorId,
      billing_party: billingParty,
      third_party_contractor_id: thirdPartyContractorId,
      billing_account_id: billingAccountId,
    }).then(res => {
      if (seq !== resolveSeq.current) return;   // a newer request won
      setResolution(res.ok ? res.data : null);
      setLoading(false);
    }).catch(() => {
      if (seq !== resolveSeq.current) return;
      setResolution(null);
      setLoading(false);
    });
  }, [senderContractorId, receiverContractorId, billingParty,
      billingAccountId, thirdPartyContractorId]);

  // Server-owned verdict — never recomputed here.
  const awbBlocked = loading || !resolution || resolution.awb_blocked !== false;
  const needsChoice = !!(resolution && resolution.reason === 'account_choice_required');

  return {
    billingParty, setBillingParty,
    billingAccountId, setBillingAccountId,
    senderAccounts, receiverAccounts,
    resolution, loading,
    awbBlocked, needsChoice,
    choices: (resolution && resolution.choices) || [],
    choiceFor: resolution && resolution.choice_for,
    message: resolution && resolution.message,
    shippingAccountMasked: resolution && resolution.shipping_account
      ? resolution.shipping_account.masked : null,
    billingAccountMasked: resolution && resolution.billing_account
      ? resolution.billing_account.masked : null,
    // Fields the shipment POST needs — the server re-resolves authoritatively.
    payloadFields: {
      sender_contractor_id: senderContractorId || null,
      receiver_contractor_id: receiverContractorId || null,
      billing_party: billingParty,
      third_party_contractor_id: thirdPartyContractorId || null,
      billing_account_id: billingAccountId,
    },
  };
}

// ── Presentational panel ────────────────────────────────────────────────
// Business information only — no credentials, no technical IDs, and never a
// full account number (the server sends masked values only).
function DhlAccountPanel({ state, allowThirdParty }) {
  const {
    billingParty, setBillingParty, billingAccountId, setBillingAccountId,
    loading, needsChoice, choices, message,
    shippingAccountMasked, billingAccountMasked, resolution,
  } = state;

  const label = { fontSize: 11, fontWeight: 600, color: 'var(--text-2)', display: 'block', marginBottom: 4 };
  const parties = [['sender', 'Sender'], ['receiver', 'Receiver']]
    .concat(allowThirdParty ? [['third_party', 'Third party']] : []);

  return (
    <div data-testid="dhl-account-panel" style={{
      border: '1px solid var(--border)', borderRadius: 6,
      padding: 12, marginTop: 12, background: 'var(--bg-subtle)',
    }}>
      <div style={{
        fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10,
      }}>DHL Account</div>

      <div style={{ marginBottom: 10 }}>
        <span style={label}>Transport charges paid by</span>
        <div style={{ display: 'flex', gap: 14 }}>
          {parties.map(([value, text]) => (
            <label key={value} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, cursor: 'pointer' }}>
              <input type="radio" name="dhl-billing-party" value={value}
                data-testid={'dhl-billing-' + value}
                checked={billingParty === value}
                onChange={() => setBillingParty(value)} />
              {text}
            </label>
          ))}
        </div>
      </div>

      {loading && (
        <div data-testid="dhl-account-loading" style={{ fontSize: 11, color: 'var(--text-3)' }}>
          Resolving DHL account…
        </div>
      )}

      {!loading && shippingAccountMasked && (
        <div data-testid="dhl-shipping-account" style={{ fontSize: 12, marginBottom: 4 }}>
          <span style={{ color: 'var(--text-3)' }}>Shipping account: </span>
          <span style={{ fontFamily: 'monospace' }}>{shippingAccountMasked}</span>
        </div>
      )}
      {!loading && billingAccountMasked && (
        <div data-testid="dhl-billing-account" style={{ fontSize: 12, marginBottom: 4 }}>
          <span style={{ color: 'var(--text-3)' }}>Billed to: </span>
          <span style={{ fontFamily: 'monospace' }}>{billingAccountMasked}</span>
        </div>
      )}

      {!loading && needsChoice && (
        <div data-testid="dhl-account-choice" style={{ marginTop: 8 }}>
          <span style={label}>Choose the DHL account</span>
          <select data-testid="dhl-account-select"
            value={billingAccountId == null ? '' : String(billingAccountId)}
            onChange={e => setBillingAccountId(e.target.value ? parseInt(e.target.value, 10) : null)}
            style={{
              width: '100%', padding: '5px 8px', fontSize: 11,
              border: '1px solid var(--border)', borderRadius: 4,
              background: 'var(--card)', color: 'var(--text)',
            }}>
            <option value="">— select an account —</option>
            {choices.map(c => (
              <option key={c.id} value={c.id}>
                {[c.account_name, c.masked].filter(Boolean).join(' · ')}
                {c.is_default ? ' (default)' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {!loading && message && resolution && resolution.awb_blocked && (
        <div data-testid="dhl-account-blocked" style={{
          marginTop: 8, padding: '6px 10px',
          background: 'var(--badge-amber-bg)',
          border: '1px solid var(--badge-amber-border)', borderRadius: 4,
          fontSize: 11, color: 'var(--badge-amber-text)',
        }}>
          {message}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { useDhlAccountResolution, DhlAccountPanel });
