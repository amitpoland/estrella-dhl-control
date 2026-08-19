// ──────────────────────────────────────────────────────────────────────────
// shipping-ops.jsx
// Shipping Operations — READ-ONLY projection of existing carrier authority.
//
// Authority owners (do NOT invent parallel APIs):
//   Queue / KPI / timeline  → GET /api/v1/dhl/logistics/projection|shipments/{awb}
//   Capability badges       → GET /api/v1/carrier/status (+ services catalogue)
//   Packages / box profiles → GET /api/v1/box-types + carrier shipment dims
//   Labels / docs           → GET /api/v1/carrier/{batch}/label|waybill-doc|receipt|epod/{awb}
//   Return drafts           → GET /api/v1/carrier/{batch}/return  (Live Create = HOLD)
//   AWB booking             → Proforma Logistics (NAVIGATE_EXISTING — no copied payload)
//
// Forbidden: parallel shipping API family, mock shipments, static false DHL
// connectivity, second tracking parser, Live Return Create, FedEx claims.
// ──────────────────────────────────────────────────────────────────────────

function CapChip({ state, label }) {
  const map = {
    ok:   { bg: 'var(--badge-green-bg, #E3F5E3)', text: 'var(--badge-green-text, #1B5E20)', border: 'var(--badge-green-border, #A5D6A7)', dot: '#22A06B' },
    warn: { bg: 'var(--badge-amber-bg)', text: 'var(--badge-amber-text)', border: 'var(--badge-amber-border)', dot: '#D4A853' },
    off:  { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)', dot: '#9CA8B8' },
    gap:  { bg: 'var(--badge-purple-bg)', text: 'var(--badge-purple-text)', border: 'var(--badge-purple-border)', dot: '#7E63C9' },
  };
  const s = map[state] || map.off;
  return (
    <span
      data-testid={'ship-ops-cap-' + (state || 'off')}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        background: s.bg, color: s.text, border: '1px solid ' + s.border,
        padding: '2px 8px', borderRadius: 10, fontSize: 10, fontWeight: 600,
        letterSpacing: '0.02em', whiteSpace: 'nowrap',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: s.dot }} />
      {label}
    </span>
  );
}

function GapBtn({ children, reason, primary }) {
  return (
    <button
      type="button"
      disabled
      title={reason || 'Capability not available'}
      data-testid="ship-ops-gap-btn"
      style={{
        padding: '6px 12px', fontSize: 11, fontWeight: 600, borderRadius: 6,
        border: primary ? '1px solid var(--accent-border)' : '1px solid var(--border)',
        background: primary ? 'var(--accent-subtle)' : 'var(--bg-subtle)',
        color: 'var(--text-3)', cursor: 'not-allowed',
        display: 'inline-flex', alignItems: 'center', gap: 6, opacity: 0.85,
      }}
    >
      {children}
      <CapChip state="gap" label="Unavailable" />
    </button>
  );
}

function EmptyState({ title, detail, testId }) {
  return (
    <div
      data-testid={testId || 'ship-ops-empty'}
      style={{
        padding: '28px 18px', textAlign: 'center',
        background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6, maxWidth: 520, margin: '0 auto' }}>{detail}</div>
    </div>
  );
}

function dhlCapFromStatus(carrierStatus) {
  const raw = ((carrierStatus && carrierStatus.carrier_api_status) || '').toString().trim().toLowerCase();
  if (raw === 'live') return { state: 'ok', label: 'DHL Express · live' };
  if (raw === 'shadow') return { state: 'warn', label: 'DHL Express · shadow' };
  if (raw === 'pending' || raw === '') return { state: 'off', label: 'DHL Express · pending / not activated' };
  return { state: 'warn', label: 'DHL Express · ' + raw };
}

function ShippingOpsPage({ onViewShipment, onNav }) {
  const [tab, setTab] = React.useState('queue');
  const [projection, setProjection] = React.useState(null);
  const [projErr, setProjErr] = React.useState(null);
  const [projLoading, setProjLoading] = React.useState(true);
  const [carrierStatus, setCarrierStatus] = React.useState(null);
  const [services, setServices] = React.useState([]);
  const [boxTypes, setBoxTypes] = React.useState([]);
  const [selectedKey, setSelectedKey] = React.useState(null);
  const [carrierShipment, setCarrierShipment] = React.useState(null);
  const [carrierShipErr, setCarrierShipErr] = React.useState(null);
  const [detail, setDetail] = React.useState(null);
  const [detailErr, setDetailErr] = React.useState(null);
  const [returnDraft, setReturnDraft] = React.useState(null);
  const [returnErr, setReturnErr] = React.useState(null);
  const [unified, setUnified] = React.useState([]);

  const rows = (projection && projection.rows) || [];
  const kpis = (projection && projection.kpis) || {};
  const selected = rows.find((r) => _rowKey(r) === selectedKey) || null;
  const dhlCap = dhlCapFromStatus(carrierStatus);

  const loadProjection = React.useCallback(() => {
    if (!window.PzApi || typeof window.PzApi.getDhlLogisticsProjection !== 'function') {
      setProjErr('PzApi.getDhlLogisticsProjection unavailable');
      setProjLoading(false);
      return;
    }
    setProjLoading(true);
    setProjErr(null);
    window.PzApi.getDhlLogisticsProjection({ direction: 'all', view: 'all' })
      .then((data) => { setProjection(data || { rows: [], kpis: {} }); setProjLoading(false); })
      .catch((e) => { setProjErr((e && e.message) || String(e)); setProjection(null); setProjLoading(false); });
  }, []);

  React.useEffect(() => { loadProjection(); }, [loadProjection]);

  React.useEffect(() => {
    if (!window.PzApi) return;
    if (typeof window.PzApi.getCarrierStatus === 'function') {
      window.PzApi.getCarrierStatus()
        .then((s) => setCarrierStatus(s || null))
        .catch(() => setCarrierStatus(null));
    }
    if (typeof window.PzApi.listCarrierServices === 'function') {
      window.PzApi.listCarrierServices()
        .then((list) => setServices(Array.isArray(list) ? list : (list && list.services) || []))
        .catch(() => setServices([]));
    }
    if (typeof window.PzApi.listBoxTypes === 'function') {
      window.PzApi.listBoxTypes(true)
        .then((data) => setBoxTypes((data && data.box_types) || []))
        .catch(() => setBoxTypes([]));
    }
  }, []);

  React.useEffect(() => {
    setCarrierShipment(null);
    setCarrierShipErr(null);
    setDetail(null);
    setDetailErr(null);
    setReturnDraft(null);
    setReturnErr(null);
    setUnified([]);
    if (!selected || !window.PzApi) return;
    const batchId = selected.batch_id;
    const awb = selected.awb;
    const party = selected.party;

    if (batchId && typeof window.PzApi.getCarrierShipment === 'function') {
      window.PzApi.getCarrierShipment(batchId, party || undefined)
        .then((s) => setCarrierShipment(s || null))
        .catch((e) => {
          setCarrierShipment(null);
          setCarrierShipErr((e && e.message) || 'No carrier shipment row for this selection');
        });
    }

    if (awb && typeof window.PzApi.getDhlLogisticsShipment === 'function') {
      window.PzApi.getDhlLogisticsShipment(awb)
        .then((d) => setDetail(d || null))
        .catch((e) => { setDetail(null); setDetailErr((e && e.message) || String(e)); });
    }

    if (batchId && typeof window.PzApi.getShipmentTimeline === 'function') {
      window.PzApi.getShipmentTimeline(batchId)
        .then((t) => setUnified((t && t.unified_timeline) || []))
        .catch(() => setUnified([]));
    }

    if (batchId && awb && typeof window.PzApi.getReturnDraft === 'function') {
      window.PzApi.getReturnDraft(batchId, { parent_tracking_ref: awb })
        .then((r) => setReturnDraft((r && r.draft) || r || null))
        .catch((e) => {
          setReturnDraft(null);
          const msg = (e && e.message) || String(e);
          if (!/404|not found|no draft/i.test(msg)) setReturnErr(msg);
        });
    }
  }, [selectedKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const openShipment = (row) => {
    if (!row || !row.batch_id) return;
    if (typeof onViewShipment === 'function') {
      onViewShipment({
        batch_id: row.batch_id,
        awb: row.awb,
        tracking_no: row.awb,
        carrier: row.carrier || 'DHL Express',
        status: row.current_status || row.classification,
      });
      return;
    }
    // Fallback without shell callback: full navigation (hydrates via URL).
    window.location.assign('/v2/shipments?batch_id=' + encodeURIComponent(row.batch_id));
  };

  const goProformaBooking = () => {
    if (typeof onNav === 'function') {
      onNav('proforma');
      return;
    }
    window.location.assign('/v2/proforma');
  };

  const tabs = [
    ['queue', 'Shipment Queue'],
    ['create', 'Create Shipment'],
    ['packages', 'Package Builder'],
    ['labels', 'Labels & Documents'],
    ['timeline', 'Tracking Timeline'],
    ['handoff', 'Warehouse Handoff'],
    ['returns', 'Return Shipments'],
    ['audit', 'Shipment Facts'],
    ['capabilities', 'Authority & Capability'],
  ];

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }} data-testid="ship-ops-page">
      <div style={{
        display: 'flex', gap: 2, padding: '0 16px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-subtle)', flexShrink: 0, overflowX: 'auto',
      }}>
        {tabs.map(([id, label]) => (
          <button
            key={id}
            type="button"
            data-testid={'ship-ops-tab-' + id}
            onClick={() => setTab(id)}
            style={{
              padding: '9px 14px', background: 'transparent', border: 'none',
              borderBottom: tab === id ? '2px solid var(--accent)' : '2px solid transparent',
              color: tab === id ? 'var(--text)' : 'var(--text-2)',
              fontSize: 12, fontWeight: tab === id ? 700 : 500, cursor: 'pointer', whiteSpace: 'nowrap',
            }}
          >{label}</button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 16px 28px' }}>
        {tab === 'queue' && (
          <SOQueue
            loading={projLoading}
            err={projErr}
            kpis={kpis}
            rows={rows}
            selectedKey={selectedKey}
            onSelect={(row) => setSelectedKey(_rowKey(row))}
            onOpen={openShipment}
            onRefresh={loadProjection}
            onBook={goProformaBooking}
            dhlCap={dhlCap}
          />
        )}
        {tab === 'create' && (
          <SOCreate onBook={goProformaBooking} dhlCap={dhlCap} services={services} />
        )}
        {tab === 'packages' && (
          <SOPackages
            boxTypes={boxTypes}
            selected={selected}
            carrierShipment={carrierShipment}
            carrierShipErr={carrierShipErr}
          />
        )}
        {tab === 'labels' && (
          <SOLabels
            selected={selected}
            carrierShipment={carrierShipment}
            carrierShipErr={carrierShipErr}
          />
        )}
        {tab === 'timeline' && (
          <SOTimeline selected={selected} detail={detail} detailErr={detailErr} unified={unified} />
        )}
        {tab === 'handoff' && <SOHandoff />}
        {tab === 'returns' && (
          <SOReturns
            selected={selected}
            returnDraft={returnDraft}
            returnErr={returnErr}
          />
        )}
        {tab === 'audit' && (
          <SOAudit selected={selected} carrierShipment={carrierShipment} carrierShipErr={carrierShipErr} />
        )}
        {tab === 'capabilities' && (
          <SOCapabilities
            dhlCap={dhlCap}
            carrierStatus={carrierStatus}
            services={services}
            projectionMeta={projection}
          />
        )}
      </div>
    </div>
  );
}

function _rowKey(row) {
  if (!row) return '';
  return String(row.batch_id || '') + '|' + String(row.awb || '') + '|' + String(row.direction || '');
}

function SOQueue({ loading, err, kpis, rows, selectedKey, onSelect, onOpen, onRefresh, onBook, dhlCap }) {
  const cards = [
    ['Active', kpis.operational_active],
    ['Exceptions', kpis.operational_exceptions],
    ['Needs attention', kpis.needs_attention],
    ['Delivered today', kpis.delivered_today],
    ['Historical open', kpis.historical_unresolved],
  ];

  return (
    <div data-testid="ship-ops-queue">
      <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        {cards.map(([label, value]) => (
          <div
            key={label}
            data-testid={'ship-ops-kpi-' + label.toLowerCase().replace(/\s+/g, '-')}
            style={{
              flex: '1 1 120px', minWidth: 110, padding: '10px 14px',
              background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
            }}
          >
            <div style={{ fontFamily: '"DM Serif Display", serif', fontSize: 24, color: 'var(--text)' }}>
              {loading ? '…' : (value == null ? '—' : String(value))}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <button
          type="button"
          data-testid="ship-ops-new-shipment"
          onClick={onBook}
          style={{
            padding: '6px 12px', fontSize: 11, fontWeight: 600, borderRadius: 6,
            border: '1px solid var(--accent-border)', background: 'var(--accent-subtle)',
            color: 'var(--text)', cursor: 'pointer',
          }}
        >+ New shipment (via Proforma)</button>
        <GapBtn reason="No bulk-dispatch API on canonical carrier authority">Bulk dispatch</GapBtn>
        <GapBtn reason="Pickup scheduling not enabled (MyDHL pickup.isRequested is false)">Pickup request</GapBtn>
        <GapBtn reason="No EOD / close-manifest endpoint on canonical carrier authority">Generate manifest</GapBtn>
        <button
          type="button"
          data-testid="ship-ops-refresh"
          onClick={onRefresh}
          style={{
            padding: '6px 12px', fontSize: 11, fontWeight: 600, borderRadius: 6,
            border: '1px solid var(--border)', background: 'var(--bg-subtle)',
            color: 'var(--text-2)', cursor: 'pointer',
          }}
        >Refresh</button>
        <span style={{ flex: 1 }} />
        <CapChip state={dhlCap.state} label={dhlCap.label} />
        <CapChip state="off" label="FedEx · unavailable" />
      </div>

      {err && (
        <div data-testid="ship-ops-queue-error" style={{
          marginBottom: 10, padding: 10, borderRadius: 8,
          background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
          color: 'var(--badge-red-text)', fontSize: 12,
        }}>{err}</div>
      )}

      {!loading && !err && rows.length === 0 && (
        <EmptyState
          testId="ship-ops-queue-empty"
          title="No shipments in logistics projection"
          detail="The DHL Logistics projector returned zero rows for the current filters. This is an empty live result — not sample data."
        />
      )}

      {(loading || rows.length > 0) && (
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 720 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                {['AWB', 'Direction', 'Party', 'Carrier', 'Classification', 'Status', 'Stage', 'Batch', ''].map((h) => (
                  <th key={h} style={{
                    textAlign: 'left', padding: '8px 10px', fontWeight: 700, color: 'var(--text-2)',
                    fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={9} style={{ padding: 16, color: 'var(--text-3)' }}>Loading logistics projection…</td></tr>
              )}
              {!loading && rows.map((r) => {
                const key = _rowKey(r);
                const sel = key === selectedKey;
                return (
                  <tr
                    key={key}
                    data-testid="ship-ops-queue-row"
                    onClick={() => onSelect(r)}
                    style={{
                      borderBottom: '1px solid var(--border-subtle)',
                      background: sel ? 'var(--accent-subtle)' : 'transparent',
                      cursor: 'pointer',
                    }}
                  >
                    <td style={{ padding: '8px 10px', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{r.awb || '—'}</td>
                    <td style={{ padding: '8px 10px', color: 'var(--text-2)' }}>{r.direction || '—'}</td>
                    <td style={{ padding: '8px 10px' }}>{r.party || '—'}</td>
                    <td style={{ padding: '8px 10px', color: 'var(--text-2)' }}>{r.carrier || '—'}</td>
                    <td style={{ padding: '8px 10px' }}>{r.classification || '—'}</td>
                    <td style={{ padding: '8px 10px', color: 'var(--text-2)' }}>{r.current_status || '—'}</td>
                    <td style={{ padding: '8px 10px', color: 'var(--text-2)' }}>{r.stage_label || r.current_stage || '—'}</td>
                    <td style={{ padding: '8px 10px', fontFamily: 'ui-monospace, monospace', fontSize: 10, color: 'var(--text-3)' }}>
                      {r.batch_id ? String(r.batch_id).slice(0, 28) : '—'}
                    </td>
                    <td style={{ padding: '8px 10px', textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        data-testid="ship-ops-open-shipment"
                        disabled={!r.batch_id}
                        title={r.batch_id ? 'Open shipment detail' : 'No batch_id on this row'}
                        onClick={() => onOpen(r)}
                        style={{
                          padding: '4px 10px', fontSize: 11, fontWeight: 600, borderRadius: 6,
                          border: '1px solid var(--border)', background: 'var(--bg-subtle)',
                          color: r.batch_id ? 'var(--text)' : 'var(--text-3)',
                          cursor: r.batch_id ? 'pointer' : 'not-allowed',
                        }}
                      >Open</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{
            padding: '10px 12px', background: 'var(--bg-subtle)', fontSize: 11, color: 'var(--text-3)',
            borderTop: '1px solid var(--border-subtle)',
          }}>
            Source: GET /api/v1/dhl/logistics/projection · {rows.length} row(s)
            {projectionAuthorityNote(kpis)}
          </div>
        </div>
      )}
    </div>
  );
}

function projectionAuthorityNote() {
  return '';
}

function SOCreate({ onBook, dhlCap, services }) {
  return (
    <div data-testid="ship-ops-create">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 14, color: 'var(--text)' }}>Create shipment</h3>
        <CapChip state={dhlCap.state} label={dhlCap.label} />
        <CapChip state="off" label="FedEx · unavailable" />
      </div>
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
        padding: 16, maxWidth: 720, lineHeight: 1.7, fontSize: 12, color: 'var(--text-2)',
      }}>
        <p style={{ marginTop: 0, color: 'var(--text)' }}>
          AWB booking authority stays on <strong>Proforma Logistics</strong>
          (<code>POST /api/v1/carrier/&#123;batch&#125;/shipment</code>). Shipping Ops does not copy that booking form or payload logic.
        </p>
        <p>
          Open an existing proforma draft and use <strong>Generate AWB</strong> on the logistics toolbar.
          That path already owns account resolution, box profiles, dimensions, and label URLs.
        </p>
        <button
          type="button"
          data-testid="ship-ops-goto-proforma"
          onClick={onBook}
          style={{
            marginTop: 8, padding: '8px 14px', fontSize: 12, fontWeight: 600, borderRadius: 6,
            border: '1px solid var(--accent-border)', background: 'var(--accent-subtle)',
            color: 'var(--text)', cursor: 'pointer',
          }}
        >Open Proforma hub</button>
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
            DHL service catalogue (read-only)
          </div>
          {services.length === 0 ? (
            <div style={{ color: 'var(--text-3)' }}>No services returned from GET /api/v1/carrier/services</div>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {services.slice(0, 12).map((s) => (
                <li key={s.code || s.name}>{s.code} — {s.name}{s.delivery ? ' · ' + s.delivery : ''}</li>
              ))}
            </ul>
          )}
        </div>
        <div style={{ marginTop: 14, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <GapBtn reason="Temporary shipment lifecycle API does not exist on carrier authority">Save as Temporary</GapBtn>
          <GapBtn reason="No public rate-quote endpoint; rates exist only inside live create">Validate / quote</GapBtn>
          <GapBtn reason="DHL cancel/void is not exposed; local do-not-use is Proforma/ops only">Cancel at carrier</GapBtn>
        </div>
      </div>
    </div>
  );
}

function SOPackages({ boxTypes, selected, carrierShipment, carrierShipErr }) {
  let dims = null;
  try {
    if (carrierShipment && carrierShipment.dimensions_json) {
      dims = typeof carrierShipment.dimensions_json === 'string'
        ? JSON.parse(carrierShipment.dimensions_json)
        : carrierShipment.dimensions_json;
    } else if (carrierShipment && carrierShipment.dimensions) {
      dims = carrierShipment.dimensions;
    }
  } catch (e) { dims = null; }

  return (
    <div data-testid="ship-ops-packages">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 14, color: 'var(--text)' }}>Package builder</h3>
        <CapChip state="ok" label="Box Profiles · master" />
        <span style={{ flex: 1 }} />
        <GapBtn reason="No package-grid editor API; packages are set at AWB booking">+ Add package</GapBtn>
        <GapBtn reason="No barcode scanner package API">Scan barcode</GapBtn>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 12 }}>
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)', fontWeight: 700, fontSize: 12 }}>
            Box Profiles ({boxTypes.length})
          </div>
          {boxTypes.length === 0 ? (
            <div style={{ padding: 14, fontSize: 12, color: 'var(--text-3)' }}>No active box profiles from GET /api/v1/box-types</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)' }}>
                  {['Code', 'Name', 'L×W×H', 'Tare', 'Max'].map((h) => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 10px', fontSize: 10, color: 'var(--text-3)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {boxTypes.map((b) => (
                  <tr key={b.code} data-testid="ship-ops-box-row" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '6px 10px', fontFamily: 'ui-monospace, monospace' }}>{b.code}</td>
                    <td style={{ padding: '6px 10px' }}>{b.name}</td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>{b.length_cm}×{b.width_cm}×{b.height_cm}</td>
                    <td style={{ padding: '6px 10px' }}>{b.tare_weight_kg}</td>
                    <td style={{ padding: '6px 10px' }}>{b.max_weight_kg}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>Selected shipment packages</div>
          {!selected && (
            <EmptyState
              testId="ship-ops-packages-noselect"
              title="Select a queue row"
              detail="Package dimensions come from the booked carrier shipment (dimensions_json / box_type_code). There is no separate package-grid store."
            />
          )}
          {selected && carrierShipErr && !carrierShipment && (
            <div style={{ fontSize: 12, color: 'var(--text-2)' }}>{carrierShipErr}</div>
          )}
          {selected && carrierShipment && (
            <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.7 }} data-testid="ship-ops-package-dims">
              <div>AWB: <code>{carrierShipment.tracking_ref || selected.awb || '—'}</code></div>
              <div>Box profile: <code>{carrierShipment.box_type_code || '—'}</code></div>
              <div>Weight kg: {carrierShipment.weight_kg != null ? carrierShipment.weight_kg : '—'}</div>
              <div>Dimensions: {dims ? JSON.stringify(dims) : '—'}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SOLabels({ selected, carrierShipment, carrierShipErr }) {
  const fromShipment = carrierShipment ? {
    label: carrierShipment.label_download_url,
    waybill: carrierShipment.waybill_doc_download_url,
    receipt: carrierShipment.shipment_receipt_download_url,
    epod: carrierShipment.epod_download_url,
  } : null;
  const hasAnyFromShipment = !!(fromShipment && (fromShipment.label || fromShipment.waybill || fromShipment.receipt || fromShipment.epod));
  const built = (selected && selected.batch_id && selected.awb)
    ? ((window.PzApi && typeof window.PzApi.carrierDocumentUrls === 'function')
      ? window.PzApi.carrierDocumentUrls(selected.batch_id, selected.awb)
      : {
        label: '/api/v1/carrier/' + encodeURIComponent(selected.batch_id) + '/label/' + encodeURIComponent(selected.awb),
        waybill: '/api/v1/carrier/' + encodeURIComponent(selected.batch_id) + '/waybill-doc/' + encodeURIComponent(selected.awb),
        receipt: '/api/v1/carrier/' + encodeURIComponent(selected.batch_id) + '/receipt/' + encodeURIComponent(selected.awb),
        epod: '/api/v1/carrier/' + encodeURIComponent(selected.batch_id) + '/epod/' + encodeURIComponent(selected.awb),
      })
    : null;
  const links = hasAnyFromShipment ? fromShipment : built;

  return (
    <div data-testid="ship-ops-labels">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 14, color: 'var(--text)' }}>Labels &amp; documents</h3>
        <CapChip state="ok" label="Carrier document downloads" />
        <span style={{ flex: 1 }} />
        <GapBtn reason="No print-queue database or print-job state machine">Print queue</GapBtn>
      </div>
      {!selected && (
        <EmptyState
          testId="ship-ops-labels-noselect"
          title="Select a queue row"
          detail="Label, waybill, receipt, and ePOD downloads use the existing carrier document endpoints for that batch AWB."
        />
      )}
      {selected && (
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
          <div style={{ fontSize: 12, marginBottom: 10, color: 'var(--text-2)' }}>
            {selected.awb || '—'} · {selected.batch_id || '—'}
            {carrierShipErr ? ' · ' + carrierShipErr : ''}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {[
              ['Transport label', links && links.label],
              ['Waybill', links && links.waybill],
              ['Receipt', links && links.receipt],
              ['ePOD', links && links.epod],
            ].map(([name, href]) => (
              href ? (
                <a
                  key={name}
                  data-testid={'ship-ops-doc-' + name.toLowerCase().replace(/\s+/g, '-')}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    padding: '6px 12px', fontSize: 11, fontWeight: 600, borderRadius: 6,
                    border: '1px solid var(--accent-border)', background: 'var(--accent-subtle)',
                    color: 'var(--text)', textDecoration: 'none',
                  }}
                >⬇ {name}</a>
              ) : (
                <GapBtn key={name} reason="Document URL not available for this selection">{name}</GapBtn>
              )
            ))}
          </div>
          <p style={{ marginTop: 12, fontSize: 11, color: 'var(--text-3)', lineHeight: 1.6 }}>
            Downloads are read-only GETs on /api/v1/carrier/&#123;batch&#125;/… — no MyDHL create and no print-job store.
          </p>
        </div>
      )}
    </div>
  );
}

function SOTimeline({ selected, detail, detailErr, unified }) {
  const milestones = (detail && (detail.milestones || (detail.shipment && detail.shipment.milestones))) || [];
  const rowMilestones = (selected && selected.milestones) || [];
  const events = milestones.length ? milestones : rowMilestones;

  return (
    <div data-testid="ship-ops-timeline">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 14, color: 'var(--text)' }}>Tracking timeline</h3>
        <CapChip state="ok" label="Logistics projector authority" />
      </div>
      {!selected && (
        <EmptyState
          testId="ship-ops-timeline-noselect"
          title="Select a queue row"
          detail="Timeline events come from GET /api/v1/dhl/logistics/shipments/{awb} (and projection milestones). This page does not parse Delivered separately."
        />
      )}
      {selected && (
        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)', marginBottom: 8 }}>
            Unified stream — workflow + carrier, chronological
          </div>
          <UnifiedTimeline events={unified} />
        </div>
      )}
      {selected && (
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)', marginBottom: 8 }}>
          Projector milestones
        </div>
      )}
      {selected && detailErr && events.length === 0 && (
        <div data-testid="ship-ops-timeline-error" style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>{detailErr}</div>
      )}
      {selected && events.length === 0 && !detailErr && (
        <EmptyState
          testId="ship-ops-timeline-empty"
          title="No milestones for this AWB"
          detail="Live projector returned no milestone events for the selected shipment."
        />
      )}
      {selected && events.length > 0 && (
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px' }}>
          {events.map((e, i) => (
            <div
              key={i}
              data-testid="ship-ops-timeline-event"
              style={{
                display: 'flex', gap: 12, padding: '8px 0',
                borderBottom: i < events.length - 1 ? '1px solid var(--border-subtle)' : 'none',
              }}
            >
              <div style={{ width: 140, flexShrink: 0, fontSize: 11, color: 'var(--text-3)', fontFamily: 'ui-monospace, monospace' }}>
                {e.at || e.ts || e.timestamp || e.time || '—'}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>
                  {e.label || e.stage || e.status || e.description || e.name || 'Event'}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
                  {[e.location, e.source].filter(Boolean).join(' · ') || 'logistics projector'}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SOHandoff() {
  return (
    <div data-testid="ship-ops-handoff">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, color: 'var(--text)' }}>Warehouse → carrier handoff</h3>
        <CapChip state="gap" label="No handoff API" />
      </div>
      <EmptyState
        testId="ship-ops-handoff-gap"
        title="Capability not implemented"
        detail="Pick / pack / tender / EOD manifest handoff is not a canonical carrier endpoint. Label download remains available from Labels & Documents; booking remains on Proforma Logistics."
      />
      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <GapBtn reason="No warehouse tender API">Tender to courier</GapBtn>
        <GapBtn reason="No EOD manifest close API">Close manifest</GapBtn>
      </div>
    </div>
  );
}

function SOReturns({ selected, returnDraft, returnErr }) {
  return (
    <div data-testid="ship-ops-returns">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 14, color: 'var(--text)' }}>Return shipments</h3>
        <CapChip state="warn" label="Prepare Return only" />
        <span style={{ flex: 1 }} />
        <GapBtn reason="Live Create Return unavailable: DHL capability pending (endpoint returns 422)">+ Live Create Return</GapBtn>
      </div>
      <div style={{
        marginBottom: 12, padding: 12, borderRadius: 8, fontSize: 12, lineHeight: 1.6,
        background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)', color: 'var(--text-2)',
      }} data-testid="ship-ops-return-hold-banner">
        <strong style={{ color: 'var(--text)' }}>Live Create Return unavailable: DHL capability pending.</strong>
        {' '}Prepare/get/patch draft endpoints remain; <code>POST …/return/create</code> stays blocked (422).
      </div>
      {!selected && (
        <EmptyState
          testId="ship-ops-returns-noselect"
          title="Select a queue row"
          detail="Return drafts are loaded with GET /api/v1/carrier/{batch}/return?parent_tracking_ref={awb}."
        />
      )}
      {selected && returnErr && (
        <div data-testid="ship-ops-returns-error" style={{ fontSize: 12, color: 'var(--badge-red-text)', marginBottom: 8 }}>{returnErr}</div>
      )}
      {selected && !returnDraft && !returnErr && (
        <EmptyState
          testId="ship-ops-returns-empty"
          title="No return draft for this AWB"
          detail="Prepare Return from Proforma/carrier flows when needed. Shipping Ops does not invent return rows."
        />
      )}
      {selected && returnDraft && (
        <div data-testid="ship-ops-return-draft" style={{
          background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, fontSize: 12,
        }}>
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-2)' }}>
            {JSON.stringify(returnDraft, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function SOAudit({ selected, carrierShipment, carrierShipErr }) {
  return (
    <div data-testid="ship-ops-audit">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, color: 'var(--text)' }}>Shipment facts</h3>
        <CapChip state="ok" label="carrier_shipments fields" />
      </div>
      {!selected && (
        <EmptyState
          testId="ship-ops-audit-noselect"
          title="Select a queue row"
          detail="There is no separate Shipping Ops audit database. Facts come from the booked carrier shipment row when present."
        />
      )}
      {selected && !carrierShipment && (
        <EmptyState
          testId="ship-ops-audit-empty"
          title="No carrier shipment row"
          detail={carrierShipErr || 'GET /api/v1/carrier/{batch}/shipment returned no row for this selection.'}
        />
      )}
      {selected && carrierShipment && (
        <div data-testid="ship-ops-audit-facts" style={{
          background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, fontSize: 12,
        }}>
          {[
            ['tracking_ref', carrierShipment.tracking_ref],
            ['state', carrierShipment.state],
            ['booked_by', carrierShipment.booked_by],
            ['client_ref', carrierShipment.client_ref],
            ['box_type_code', carrierShipment.box_type_code],
            ['service_code', carrierShipment.service_code || carrierShipment.service_product],
            ['created_at', carrierShipment.created_at],
            ['do_not_use', carrierShipment.do_not_use],
          ].map(([k, v]) => (
            <div key={k} style={{ display: 'flex', gap: 12, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
              <div style={{ width: 140, color: 'var(--text-3)', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{k}</div>
              <div style={{ color: 'var(--text)' }}>{v == null || v === '' ? '—' : String(v)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SOCapabilities({ dhlCap, carrierStatus, services, projectionMeta }) {
  const groups = [
    {
      title: 'DHL Express (canonical)',
      items: [
        ['GET /api/v1/carrier/status', dhlCap.label],
        ['GET /api/v1/carrier/services', services.length ? (services.length + ' products') : 'catalogue'],
        ['POST /api/v1/carrier/{batch}/shipment', 'AWB create — Proforma Logistics'],
        ['GET /api/v1/carrier/{batch}/label|waybill-doc|receipt|epod/{awb}', 'Document downloads'],
        ['POST /api/v1/carrier/webhook/dhl', 'Tracking ingest'],
        ['GET /api/v1/dhl/logistics/projection', 'Queue / KPI / timeline'],
        ['GET/PATCH …/return', 'Return draft only'],
        ['POST …/return/create', 'HOLD — DHL capability pending'],
      ],
    },
    {
      title: 'FedEx',
      items: [
        ['FedEx adapter / routes', 'Unavailable — not implemented'],
      ],
    },
    {
      title: 'Masters consumed (read-only)',
      items: [
        ['GET /api/v1/box-types', 'Box Profiles'],
        ['GET /api/v1/customer-master/{id}/shipping-addresses/', 'Addresses'],
        ['GET /api/v1/customer-master/{id}/carrier-accounts/', 'Carrier accounts'],
      ],
    },
    {
      title: 'Explicit gaps (not simulated)',
      items: [
        ['Pickup scheduling', 'Unavailable'],
        ['EOD / close manifest', 'Unavailable'],
        ['Bulk dispatch', 'Unavailable'],
        ['Print-queue DB', 'Unavailable'],
        ['Warehouse tender handoff API', 'Unavailable'],
        ['Parallel shipping API family', 'Forbidden — do not implement'],
      ],
    },
  ];

  return (
    <div data-testid="ship-ops-capabilities">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 14, color: 'var(--text)' }}>Authority &amp; capability map</h3>
        <CapChip state={dhlCap.state} label={dhlCap.label} />
        <CapChip state="off" label="FedEx · unavailable" />
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }}>
        carrier_api_status={((carrierStatus && carrierStatus.carrier_api_status) || '—')}
        {' · '}plt={((carrierStatus && carrierStatus.carrier_plt_status) || '—')}
        {projectionMeta && projectionMeta.generated_at_utc ? (' · projection ' + projectionMeta.generated_at_utc) : ''}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
        {groups.map((g) => (
          <div key={g.title} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>{g.title}</div>
            <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none', fontSize: 11, color: 'var(--text-2)' }}>
              {g.items.map(([path, note]) => (
                <li key={path} style={{
                  display: 'flex', justifyContent: 'space-between', gap: 10,
                  padding: '4px 0', borderBottom: '1px solid var(--border-subtle)',
                }}>
                  <code style={{ fontFamily: 'ui-monospace, monospace', fontSize: 10.5, color: 'var(--text)' }}>{path}</code>
                  <span style={{ color: 'var(--text-3)', fontSize: 10.5, textAlign: 'right' }}>{note}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div style={{
        marginTop: 14, padding: 12, borderRadius: 8, fontSize: 11, lineHeight: 1.7,
        background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-2)',
      }}>
        Shipping Ops owns <strong>no</strong> operational shipment truth and must never introduce a parallel shipping API family.
      </div>
    </div>
  );
}

// Back-compat export name used by older comments/tests; prefer CapChip.
function ShipStatus({ kind, label }) {
  const state = kind === 'api' || kind === 'carrier' ? 'gap'
    : kind === 'backend' || kind === 'planned' || kind === 'temporary' ? 'off'
      : 'off';
  return <CapChip state={state} label={label || kind || 'status'} />;
}

Object.assign(window, { ShippingOpsPage, ShipStatus, CapChip });
