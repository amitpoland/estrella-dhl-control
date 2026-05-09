# ADR-009: DHL webhook handshake + IP allowlist

Status: Accepted
Date:   2026-05-09
Phase:  DL-E1

## Context

DHL Tracking-Unified-Push is operator-uninitiated traffic: DHL's
servers POST events to a webhook URL we register. We cannot
pre-share an API key with DHL (they publish a single static URL,
they call us). The DHL docs do NOT define a per-event HMAC or
signature scheme; the only shared secret is the one DHL sends in
the activation handshake.

We need to:
- prove ownership of the webhook URL at activation time,
- gate event traffic against unauthorised callers,
- never write to operational state on a forged event.

## Decision

Two-layer gate:

1. **Activation handshake** (one-time per subscription):
   - DHL POSTs to `/api/v1/carrier/webhook/dhl/activate` with a
     `secret` in BOTH a request header (`DHL-Hook-Secret`) and the
     JSON body (`{"secret": "..."}`).
   - We verify the two values match.
   - We persist `sha256(secret)` only — never the raw secret.
   - We echo the secret back in the response body so DHL marks the
     subscription active.

2. **Steady-state event traffic** (every push):
   - `DHL-API-Key` header check. When `settings.api_key` is set,
     missing or wrong header → 401. Empty `api_key` (dev mode) → no
     check.
   - Source IP allowlist. When `carrier_dhl_webhook_ip_allowlist`
     is non-empty, source IP must fall inside one of the listed
     CIDRs. Empty allowlist (dev mode) → no check.
   - **Mandatory rule (DL-F3.5):** when `carrier_dhl_live_enabled=True`,
     the IP allowlist MUST be non-empty. Startup config validator
     enforces this. Without IP gating, the only structural
     mitigation against URL-leak replay is the API key, which DHL
     itself does not honour.

No per-event HMAC. The DHL contract does not provide one and we do
not invent one. Source-grep tests pin the absence of HMAC code in
the route file.

## Rejected alternatives

- **HMAC over body.** DHL doesn't sign; we'd be validating against
  nothing.
- **mTLS.** Operationally heavy; DHL doesn't offer a client-cert
  channel.
- **Pull-based polling.** Loses event ordering; doubles cost on
  the read API quota.

## Risks

- Webhook URL leak → unauthorised replay. Mitigated by IP allowlist
  (mandatory when live). Without that, the `DHL-API-Key` check is
  the only gate — acceptable for sandbox shadow but NOT for
  production.
- DHL secret rotation. We persist multiple rows per subscription_id
  (composite PK on `secret_hash`) so a rotated secret doesn't
  invalidate the old one until ops explicitly disables.

## Rollback

Flip `carrier_dhl_webhook_enabled=False`. Both endpoints return
HTTP 503 on the next request. No subscription state is destroyed;
re-enabling restores activation.

## Future impact

DL-F3.5 adds the startup config validator that enforces non-empty
IP allowlist when `live_enabled=True`. The same handshake pattern
generalizes to FedEx / UPS push if those carriers offer
push-style APIs.
