// estrella-outbound-tracking.jsx — Shared OUTBOUND customer shipment tracking card.
// Authority: GET/POST /api/v1/tracking/{awb} via PzApi.getDhlTracking / refreshDhlTracking.
// Distinct from inbound import clearance. Never invents a second tracker.
// Used by Proforma Logistics (OutboundShipmentTracking) and Shipment Detail (DhlTrackingCard).

(function () {
  'use strict';

  function pickPrim(e, keys) {
    for (var i = 0; i < keys.length; i++) {
      var v = e && e[keys[i]];
      if (v != null && typeof v !== 'object') return v;
    }
    return '';
  }

  function statusTone(label) {
    var s = String(label || '').toLowerCase();
    if (!s) return { bg: 'var(--badge-neutral-bg)', fg: 'var(--text-2)', bd: 'var(--border)', key: 'pending' };
    if (/deliver/.test(s))
      return { bg: 'var(--badge-green-bg)', fg: 'var(--badge-green-text)', bd: 'var(--badge-green-border, var(--border))', key: 'delivered' };
    if (/exception|fail|undeliver|delay|hold|error/.test(s))
      return { bg: 'var(--badge-amber-bg)', fg: 'var(--badge-amber-text)', bd: 'var(--badge-amber-border, var(--border))', key: 'exception' };
    if (/transit|depart|customs|process|scan|pick|out for/.test(s))
      return { bg: 'var(--badge-blue-bg)', fg: 'var(--badge-blue-text)', bd: 'var(--badge-blue-border, var(--border))', key: 'transit' };
    if (/information received|pre-transit|label|booked|created/.test(s))
      return { bg: 'var(--badge-neutral-bg)', fg: 'var(--text)', bd: 'var(--border)', key: 'info' };
    return { bg: 'var(--badge-neutral-bg)', fg: 'var(--text)', bd: 'var(--border)', key: 'unknown' };
  }

  function humanTime(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d.getTime())) {
      var s = String(iso);
      return s.length > 19 ? s.slice(0, 16).replace('T', ' ') : s;
    }
    try {
      return d.toLocaleString(undefined, {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
    } catch (e) {
      return String(iso).slice(0, 16).replace('T', ' ');
    }
  }

  function eventText(ev) {
    if (ev == null) return '';
    if (typeof ev === 'string') return ev;
    return pickPrim(ev, ['description', 'status', 'message', 'label', 'event', 'type']) || '';
  }

  function LifecycleStrip({ trackingStatus, delivery }) {
    var st = String(trackingStatus || '').toLowerCase();
    var booked = true;
    var inTransit = /transit|depart|customs|process|scan|pick|out for|deliver|exception/.test(st);
    var delivered = /deliver/.test(st);
    var conf = delivery || null;
    var emailPending = conf && (conf.operator_status === 'awaiting_customer' || conf.notification_status);
    var emailFailed = conf && conf.notification_status === 'failed';
    var emailSent = conf && (conf.notification_status === 'sent' || conf.notification_status === 'queued' || conf.operator_status === 'awaiting_customer' || conf.operator_status === 'confirmed_good' || conf.operator_status === 'issue_reported');
    var confirmedGood = conf && conf.operator_status === 'confirmed_good';
    var issueReported = conf && conf.operator_status === 'issue_reported';

    var steps;
    if (issueReported) {
      steps = [
        { id: 'booked', label: 'Created', on: booked },
        { id: 'transit', label: 'In transit', on: inTransit || delivered },
        { id: 'delivered', label: 'Delivered', on: delivered },
        { id: 'issue', label: 'Issue reported', on: true, alert: true },
      ];
    } else {
      steps = [
        { id: 'booked', label: 'Created', on: booked },
        { id: 'transit', label: 'In transit', on: inTransit || delivered },
        { id: 'delivered', label: 'Delivered', on: delivered },
        { id: 'email', label: emailFailed ? 'Email failed' : (emailSent ? 'Confirm sent' : 'Confirm pending'), on: !!emailSent, warn: emailFailed || (delivered && !emailSent) },
        { id: 'customer', label: confirmedGood ? 'Confirmed' : 'Awaiting customer', on: !!confirmedGood },
      ];
    }

    return (
      <div data-testid="ej-outbound-lifecycle" style={{
        display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12, paddingTop: 12,
        borderTop: '1px solid var(--border)',
      }}>
        {steps.map(function (step, i) {
          var bg = step.alert
            ? 'var(--badge-red-bg, var(--badge-amber-bg))'
            : step.warn && step.on
              ? 'var(--badge-amber-bg)'
              : step.on
                ? 'var(--badge-green-bg)'
                : 'var(--bg-subtle)';
          var fg = step.alert
            ? 'var(--badge-red-text, var(--badge-amber-text))'
            : step.warn && step.on
              ? 'var(--badge-amber-text)'
              : step.on
                ? 'var(--badge-green-text)'
                : 'var(--text-3)';
          return (
            <span key={step.id} data-testid={'ej-outbound-lifecycle-' + step.id}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4,
                padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700,
                background: bg, color: fg, border: '1px solid var(--border)',
              }}>
              <span style={{ opacity: 0.7 }}>{i + 1}</span> {step.label}
            </span>
          );
        })}
      </div>
    );
  }

  function EJOutboundTrackingCard(props) {
    var awb = props.awb || '';
    var batchId = props.batchId || '';
    var carrier = props.carrier || 'DHL';
    var draftId = props.draftId || null;
    var reloadNonce = props.reloadNonce;
    var testIdRoot = props.testIdRoot || 'ej-outbound-tracking';

    var _s = React.useState(null); var tracking = _s[0]; var setTracking = _s[1];
    var _l = React.useState(!!awb); var loading = _l[0]; var setLoading = _l[1];
    var _r = React.useState(false); var refreshing = _r[0]; var setRefreshing = _r[1];
    var _e = React.useState(null); var err = _e[0]; var setErr = _e[1];
    var _d = React.useState(null); var delivery = _d[0]; var setDelivery = _d[1];

    var load = React.useCallback(function (forceRefresh) {
      if (!awb) {
        setTracking(null);
        setLoading(false);
        return Promise.resolve();
      }
      if (forceRefresh) setRefreshing(true);
      else setLoading(true);
      setErr(null);
      var chain = Promise.resolve();
      if (forceRefresh && window.PzApi && window.PzApi.refreshDhlTracking) {
        chain = window.PzApi.refreshDhlTracking(awb, batchId || '');
      }
      return chain
        .then(function () {
          if (!window.PzApi || !window.PzApi.getDhlTracking) {
            return { ok: false, error: 'PzApi.getDhlTracking unavailable' };
          }
          return window.PzApi.getDhlTracking(awb, batchId || '', {
            carrier: carrier || '',
            refresh: !!forceRefresh,
          });
        })
        .then(function (r) {
          if (r && r.ok) setTracking(r.data || null);
          else {
            setTracking(null);
            setErr((r && r.error) || 'tracking unavailable');
          }
        })
        .catch(function (e) {
          setTracking(null);
          setErr((e && e.message) || 'tracking unavailable');
        })
        .then(function () {
          setLoading(false);
          setRefreshing(false);
        });
    }, [awb, batchId, carrier]);

    var loadDelivery = React.useCallback(function () {
      if (!draftId || !window.PzApi || !window.PzApi.getShipmentDeliveryConfirmation) {
        setDelivery(null);
        return;
      }
      window.PzApi.getShipmentDeliveryConfirmation(draftId)
        .then(function (r) {
          if (r && r.ok) {
            var body = r.data || {};
            setDelivery(body.delivery_confirmation || body || null);
          } else setDelivery(null);
        })
        .catch(function () { setDelivery(null); });
    }, [draftId]);

    React.useEffect(function () {
      var alive = true;
      load(false);
      loadDelivery();
      var t = awb ? setInterval(function () {
        if (alive) { load(true); loadDelivery(); }
      }, 120000) : null;
      return function () { alive = false; if (t) clearInterval(t); };
    }, [load, loadDelivery, awb, reloadNonce]);

    var events = (tracking && Array.isArray(tracking.events))
      ? tracking.events.slice().reverse().slice(0, 8)
      : [];
    var statusLabel = (tracking && (tracking.status_label || tracking.status)) || '';
    var tone = statusTone(statusLabel);
    var carrierLabel = (tracking && tracking.carrier) || carrier || 'DHL';
    var awbShow = (tracking && tracking.tracking_no) || awb;
    var lastEvent = tracking ? eventText(tracking.last_event) : '';
    var loc = (tracking && tracking.last_location) || '';
    var when = (tracking && (tracking.last_update || tracking.last_update_display)) || '';

    var btn = {
      fontSize: 12, fontWeight: 600, padding: '8px 12px', borderRadius: 8, cursor: 'pointer',
      background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)',
      minHeight: 40, textDecoration: 'none', display: 'inline-flex', alignItems: 'center',
    };

    return (
      <div data-testid={testIdRoot} style={{
        marginTop: 16, padding: '16px 18px', borderRadius: 12,
        background: 'var(--card, var(--bg))', border: '1px solid var(--border)',
        boxShadow: '0 1px 2px var(--shadow, transparent)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Outbound shipment tracking
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>
              Customer shipment · not import clearance
            </div>
          </div>
          <button
            type="button"
            data-testid={testIdRoot + '-refresh'}
            disabled={!awb || loading || refreshing}
            onClick={function () { load(true); loadDelivery(); }}
            aria-label="Refresh outbound tracking"
            style={Object.assign({}, btn, { opacity: (!awb || loading || refreshing) ? 0.55 : 1, cursor: (!awb || loading || refreshing) ? 'default' : 'pointer' })}
          >
            {refreshing ? '… Refreshing' : '↻ Refresh'}
          </button>
        </div>

        {!awb && (
          <div data-testid={testIdRoot + '-empty'} style={{ marginTop: 12, fontSize: 12.5, color: 'var(--text-3)' }}>
            No outbound AWB linked yet. Book the customer shipment first — import clearance is shown separately and is not this timeline.
          </div>
        )}

        {awb && loading && (
          <div data-testid={testIdRoot + '-loading'} style={{ marginTop: 12, fontSize: 13, color: 'var(--text-3)' }}>
            Loading tracking for AWB {awb}…
          </div>
        )}

        {awb && !loading && tracking && (
          <div data-testid={testIdRoot + '-status'} style={{ marginTop: 14 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <span data-testid={testIdRoot + '-carrier'} style={{
                fontSize: 12, fontWeight: 800, letterSpacing: '0.04em', color: 'var(--text-2)',
                padding: '4px 8px', borderRadius: 6, background: 'var(--bg-subtle)', border: '1px solid var(--border)',
              }}>{String(carrierLabel).toUpperCase()}</span>
              <span data-testid={testIdRoot + '-awb'} style={{
                fontSize: 14, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: 'var(--text)',
              }}>AWB {awbShow}</span>
              <span data-testid={testIdRoot + '-status-badge'} style={{
                display: 'inline-flex', alignItems: 'center', padding: '5px 12px', borderRadius: 999,
                background: tone.bg, color: tone.fg, border: '1px solid ' + tone.bd,
                fontSize: 12, fontWeight: 800, letterSpacing: '0.03em', textTransform: 'uppercase',
              }}>{statusLabel || 'PENDING'}</span>
            </div>

            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: '12px 18px', marginBottom: 10,
            }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 3 }}>Location</div>
                <div data-testid={testIdRoot + '-location'} style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text)' }}>{loc || '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 3 }}>Event time</div>
                <div data-testid={testIdRoot + '-event-time'} style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text)' }}>{humanTime(when)}</div>
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 3 }}>Latest event</div>
                <div data-testid={testIdRoot + '-last-event'} style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text)', lineHeight: 1.4 }}>
                  {lastEvent || '—'}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              {tracking.tracking_url ? (
                <a href={tracking.tracking_url} target="_blank" rel="noopener noreferrer"
                  data-testid={testIdRoot + '-url'} style={Object.assign({}, btn, { color: 'var(--accent)', borderColor: 'var(--accent)' })}>
                  Open DHL tracking ↗
                </a>
              ) : null}
              <span data-testid={testIdRoot + '-freshness'} style={{ fontSize: 11, color: 'var(--text-3)' }}>
                {tracking.source ? ('Source · ' + tracking.source) : 'Source · —'}
                {when ? (' · updated ' + humanTime(when)) : ''}
                {tracking.available === false ? ' · unavailable/fallback' : ''}
              </span>
            </div>

            <details style={{ marginTop: 8 }}>
              <summary style={{ fontSize: 11, color: 'var(--text-3)', cursor: 'pointer' }}>Diagnostic</summary>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4, fontFamily: 'ui-monospace, monospace' }}>
                GET /api/v1/tracking/&#123;awb&#125; · outbound customer AWB only
              </div>
            </details>

            {draftId ? (
              <LifecycleStrip trackingStatus={statusLabel} delivery={delivery} />
            ) : null}

            {delivery ? (
              <div data-testid={testIdRoot + '-delivery'} style={{ marginTop: 10, fontSize: 12, color: 'var(--text-2)' }}>
                Estrella confirmation: <strong>{delivery.operator_status || '—'}</strong>
                {delivery.notification_status ? (' · email ' + delivery.notification_status) : ''}
                {delivery.evidence_count ? (' · ' + delivery.evidence_count + ' photo(s)') : ''}
              </div>
            ) : null}

            <div data-testid={testIdRoot + '-dhl-notify-note'} style={{ marginTop: 8, fontSize: 11, color: 'var(--text-3)' }}>
              DHL carrier email/SMS: requested on booking when recipient contact is present (MyDHL shipmentNotification) — separate from Estrella delivery confirmation.
            </div>
          </div>
        )}

        {awb && !loading && !tracking && (
          <div data-testid={testIdRoot + '-err'} style={{ marginTop: 14 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <span data-testid={testIdRoot + '-carrier'} style={{
                fontSize: 12, fontWeight: 800, letterSpacing: '0.04em', color: 'var(--text-2)',
                padding: '4px 8px', borderRadius: 6, background: 'var(--bg-subtle)', border: '1px solid var(--border)',
              }}>{String(carrier || 'DHL').toUpperCase()}</span>
              <span data-testid={testIdRoot + '-awb'} style={{
                fontSize: 14, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: 'var(--text)',
              }}>AWB {awb}</span>
              <span data-testid={testIdRoot + '-status-badge'} style={{
                display: 'inline-flex', alignItems: 'center', padding: '5px 12px', borderRadius: 999,
                background: 'var(--badge-neutral-bg)', color: 'var(--text-2)', border: '1px solid var(--border)',
                fontSize: 12, fontWeight: 800, letterSpacing: '0.03em', textTransform: 'uppercase',
              }}>PENDING</span>
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--text-3)', marginBottom: 10 }}>
              Live tracking unavailable{err ? (' — ' + err) : ''}. You can still open DHL’s public tracker.
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              <a
                href={'https://www.dhl.com/pl-en/home/tracking/tracking-express.html?submit=1&tracking-id=' + encodeURIComponent(awb)}
                target="_blank" rel="noopener noreferrer"
                data-testid={testIdRoot + '-url'}
                style={Object.assign({}, btn, { color: 'var(--accent)', borderColor: 'var(--accent)' })}
              >
                Open DHL tracking ↗
              </a>
            </div>
            <details style={{ marginTop: 8 }}>
              <summary style={{ fontSize: 11, color: 'var(--text-3)', cursor: 'pointer' }}>Diagnostic</summary>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4, fontFamily: 'ui-monospace, monospace' }}>
                GET /api/v1/tracking/&#123;awb&#125; · outbound customer AWB only
              </div>
            </details>
            {draftId ? <LifecycleStrip trackingStatus="" delivery={delivery} /> : null}
            <div data-testid={testIdRoot + '-dhl-notify-note'} style={{ marginTop: 8, fontSize: 11, color: 'var(--text-3)' }}>
              DHL carrier email/SMS: requested on booking when recipient contact is present (MyDHL shipmentNotification) — separate from Estrella delivery confirmation.
            </div>
          </div>
        )}

        {awb && !loading && events.length > 0 && (
          <div data-testid={testIdRoot + '-timeline'} style={{
            marginTop: 14, borderRadius: 10, border: '1px solid var(--border)', overflow: 'hidden',
          }}>
            <div style={{
              padding: '8px 14px', fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
              textTransform: 'uppercase', color: 'var(--text-3)', background: 'var(--bg-subtle)',
              borderBottom: '1px solid var(--border)',
            }}>Progress</div>
            {events.map(function (ev, i) {
              var ts = pickPrim(ev, ['timestamp', 'time', 'at', 'date']);
              var desc = pickPrim(ev, ['description', 'status', 'label', 'event', 'type']) || '—';
              var where = pickPrim(ev, ['location', 'where', 'place']);
              return (
                <div key={i} data-testid={testIdRoot + '-timeline-row'}
                  style={{
                    display: 'flex', gap: 12, padding: '10px 14px',
                    borderBottom: i < events.length - 1 ? '1px solid var(--border)' : 'none',
                    background: i === 0 ? 'var(--bg-subtle)' : 'transparent',
                  }}>
                  <span style={{
                    width: 8, height: 8, borderRadius: 999, marginTop: 5, flexShrink: 0,
                    background: i === 0 ? 'var(--accent)' : 'var(--border)',
                  }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text)' }}>{desc}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                      {humanTime(ts)}{where ? (' · ' + where) : ''}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  window.EJOutboundTrackingCard = EJOutboundTrackingCard;
})();
