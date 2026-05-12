# ADR-010: Default-OFF feature flags

Status: Accepted
Date:   2026-05-09
Phase:  campaign-wide

## Context

The carrier campaign introduces four feature flags, each gating a
behaviour with potential to bill the company, leak PII, or commit
state to an external carrier:

- `carrier_dhl_live_enabled` — gate on real DHL transport.
- `carrier_dhl_shadow_mode` — gate on stub-vs-live observation.
- `carrier_dhl_webhook_enabled` — gate on inbound DHL push events.
- `carrier_dhl_paperless_trade_enabled` — gate on customs invoice
  inlining.

The temptation, especially during shadow rollout, is to set
`shadow_mode=True` as the default once it's "well-tested." That
path leads to inevitable accidental flip in a fork / branch / CI
matrix that wasn't part of the rollout plan.

## Decision

Every carrier feature flag ships `default=False`. **Without
exception.** Operators flip flags in `.env`; nothing else.

CI enforcement:
- `grep "default=False" service/app/core/config.py` returns the
  full set of carrier flags in every PR.
- A test asserts `settings.carrier_dhl_live_enabled is False` and
  the same for the other three flags using the in-process default
  (no `.env` loaded).
- The factory's selection logic returns the stub at every
  inspection of those defaults.

Promotion is operator action only:
1. Edit `.env` in the production environment.
2. Restart the service.
3. Verify on the dashboard that the chosen adapter / URL / mode is
   what was intended.
4. Watch the post-flip telemetry per the rollback doctrine.

## Rejected alternatives

- **Default-ON for shadow mode.** Reduces operator burden during
  rollout but breaks the rule on dev / CI / preview environments.
- **Percentage rollout via flag.** Adds complexity without
  reducing risk for legally-binding actions like AWB issuance.
- **Auto-promotion when telemetry looks healthy.** Removes the
  human-in-the-loop on a high-stakes change.

## Risks

- Flag sprawl. Mitigated by quarterly flag review (added to the
  observability charter).
- A future flag accidentally lands `default=True`. Mitigated by
  the CI grep + the test that asserts default state.

## Rollback

Set the flag to `False` in `.env`, restart. Flag flip is the
fastest rollback in the system — milliseconds for the in-process
config refresh, restart-bounded for FastAPI workers.

## Future impact

Every future carrier flag (FedEx, UPS, customs APIs) inherits this
default. The rule is campaign-wide, not DHL-specific. New flags
that don't fit (e.g., a debug-mode toggle that should default ON
for dev) require a new ADR explaining why the rule is being
broken.
