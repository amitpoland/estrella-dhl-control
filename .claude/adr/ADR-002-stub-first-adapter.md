# ADR-002: Stub-first adapter discipline

Status: Accepted
Date:   2026-05-09
Phase:  DL-B

## Context

Live DHL calls have credentials, daily quota (500 sandbox), latency,
billing implications, and a non-trivial activation/onboarding path.
Tests, dev environments, and CI cannot make live calls — they need
deterministic, free, fast carrier behaviour. The temptation is to
mock at the HTTP layer (VCR cassettes, recorded fixtures), but that
couples test fidelity to the recording date and silently breaks when
the carrier's wire format evolves.

## Decision

Every concrete carrier ships a deterministic stub adapter as its
**first** implementation. The stub:

- Implements the full `CarrierAdapter` Protocol with the same surface
  as the live adapter.
- Generates outputs deterministically (same input → same AWB / label
  bytes / event).
- Performs zero I/O — no HTTP, no disk, no env reads.
- Is the default selection in the route factory; live is opt-in via
  feature flag (ADR-008, ADR-010).

CI and dev runs use the stub. The factory falls back to the stub for
any condition that fails live-eligibility checks.

## Rejected alternatives

- **VCR / recorded HTTP fixtures.** Captures the live wire format at
  recording time; goes silently stale when DHL evolves.
- **Sandbox-only validation.** Burns the 500/day quota on test runs;
  flaky during DHL maintenance windows.
- **Build live first, stub later.** Inverts the safety direction;
  tests would need credentials to run.

## Risks

- Stub-vs-live divergence drift: stub deterministic behaviour stops
  matching what DHL actually does. Mitigated by shadow mode (ADR-004)
  which compares both at every operator action.
- Stub becomes the de facto spec, tempting contributors to skip the
  live implementation. Mitigated by the live-flag rollout discipline
  (ADR-008).

## Rollback

Stub stays in the codebase forever — it is the canonical fixture for
tests. Removing it is never a goal. "Rollback" of live means switch
the feature flag and the factory returns the stub on the next request.

## Future impact

The same pattern applies to FedEx/UPS, customs APIs, payment APIs,
and any other vendor integration. The stub-first rule is a campaign-
wide convention, not just a DHL convention.
