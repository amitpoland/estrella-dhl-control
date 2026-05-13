# ADR-008: Three-state DHL API status lifecycle

Status: Accepted
Date:   2026-05-09
Phase:  DL-F1

## Context

DHL provisions API access in stages. An account moves through:

1. Onboarding paperwork submitted, no credentials yet.
2. Sandbox credentials issued (500 calls/day, test base URL).
3. Production credentials issued, contract signed, billing live.

A boolean "live enabled" flag does not capture this lifecycle.
Operators need to flip from sandbox to production without code
changes, and the system must default to "not yet" when nothing has
been provisioned.

## Decision

`dhl_express_api_status` is a tri-state string config:

| Value | Meaning | Behaviour |
|-------|---------|-----------|
| `"pending"` | Default. DHL has not approved this account. | Factory returns stub regardless of other settings. No live call ever. |
| `"sandbox"` | Test credentials issued. | Live adapter targets `https://express.api.dhl.com/mydhlapi/test`. 500/day quota enforced by the in-process counter. |
| `"production"` | Production credentials issued. | Live adapter targets `https://express.api.dhl.com/mydhlapi`. Production quota negotiated. |

Status promotion is an explicit operator action: edit `.env`,
restart service. There is no implicit promotion (no auto-detect by
URL or by credential shape). Any unknown status value falls back
to `pending` semantics.

The status gate composes with `carrier_dhl_live_enabled` (ADR-010)
and credential completeness. Even with `status="production"`, if
`carrier_dhl_live_enabled=False` or any credential is empty, the
factory returns the stub.

## Rejected alternatives

- **Boolean `dhl_live`.** Cannot distinguish sandbox from production.
- **Environment-driven implicit promotion.** Sandbox in dev, prod in
  prod. Couples the contract to deployment and breaks for staging /
  preview environments where we want sandbox in a "production-class"
  hostname.
- **Auto-detect from URL.** Brittle; URLs change.

## Risks

- Operator may misread "sandbox" as "active" when sharing with
  finance (sandbox is free; production bills). Mitigated by the
  future dashboard surface naming the URL host explicitly.
- A typo in `.env` (`sandbx`, `Production` with capital P) falls
  through to stub silently. Mitigated by case-insensitive
  comparison + a future startup log line that announces the
  selected adapter and URL.

## Rollback

Set `dhl_express_api_status=pending` in `.env`. On the next
service restart, the factory returns the stub. Existing in-flight
requests complete on whichever adapter they were dispatched to.

## Future impact

The same pattern applies to FedEx (already in config slots:
`fedex_client_id` etc.) and any future carrier. The tri-state
lifecycle is a campaign convention; new carrier integrations
inherit it.
