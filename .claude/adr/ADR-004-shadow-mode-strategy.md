# ADR-004: Shadow-mode rollout strategy

Status: Accepted
Date:   2026-05-09
Phase:  DL-F2

## Context

Before flipping `carrier_dhl_live_enabled=True` for production
traffic, we need empirical evidence that the live DHL adapter
behaves identically to the stub on real operator workflows. A
single integration test cannot replicate weeks of operator
behaviour. Cutover blind is not acceptable for a system that
issues legally-binding AWBs.

## Decision

A **wrapper adapter** (`DHLExpressShadowAdapter`) that:

1. Calls the **stub** for the canonical response. The stub's
   response is what the coordinator persists and what the
   operator sees.
2. Calls the **live** adapter for **observation only**. The
   live response is captured into a separate SQLite store
   (`carrier_shadow_log`) and otherwise discarded.
3. Compares stub-vs-live at the **shape** level (label format,
   sizes, accepted booleans) — never byte-equality on labels or
   raw responses.
4. Records every call as one shadow-log row with a deterministic
   `request_hash` for cross-walk.

The wrapper is selected by the route factory only when
`carrier_dhl_live_enabled=True` AND `carrier_dhl_shadow_mode=True`
AND credentials are present. Default-OFF (ADR-010).

Promotion path:
- **F2 sandbox shadow** (≥ 1 week): `dhl_express_api_status=sandbox` +
  shadow on. Operations review diffs daily.
- **F2 production shadow** (≥ 1 week): `dhl_express_api_status=production` +
  shadow on. Operations confirm match-rate ≥ 98% before cutover.
- **Cutover**: flip `carrier_dhl_shadow_mode=False`. Live becomes
  source of truth; stub stays in the codebase as the test fixture.

## Rejected alternatives

- **A/B at HTTP layer (reverse proxy).** Couples the strategy to
  infrastructure; harder to compare at semantic level.
- **Mirror traffic via async queue.** Out-of-band; introduces lag
  between stub and live observations; breaks per-call comparison.
- **Sandbox-only validation.** Already covered earlier in the
  rollout; shadow against production is the irreplaceable signal.

## Risks

- 2× cost on live API. Mitigated by the per-instance daily quota
  counter and by limiting shadow to operator-driven traffic only
  (no synthetic shadow traffic generation).
- Operator confusion if the dashboard surfaces both stub and live
  AWBs. Mitigated by ADR-005 (no live AWB in operational registry)
  and the future shadow-only dashboard surface.
- Quota exhaustion drops live observations late in the day.
  Mitigated by `live_status="skipped"` recording (still logs the
  stub outcome).

## Rollback

Flip `carrier_dhl_shadow_mode=False` at runtime. Factory selects
plain live or stub on the next request. No schema migration,
no deploy. Shadow log rows remain for post-mortem.

## Future impact

Every future carrier integration uses shadow mode for at least
one operator-week before production cutover. The same
`DHLExpressShadowAdapter` pattern generalizes to
`FedExShadowAdapter` etc. by composition.
