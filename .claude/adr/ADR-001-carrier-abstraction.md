# ADR-001: Carrier abstraction layer (Adapter Protocol)

Status: Accepted
Date:   2026-05-09
Phase:  DL-A (campaign-wide foundation)

## Context

Estrella ships outbound packages exclusively via DHL today. The product
roadmap names FedEx and UPS as plausible second carriers within 12–18
months. We need a way to integrate carriers that does not couple the
operator-facing surface (coordinator, routes, dashboard) to any single
carrier's wire format or SDK.

## Decision

Three layers, with a runtime-checkable Protocol as the seam:

- **Layer 1 — Adapter:** one Python class per carrier (e.g.
  `DHLExpressLiveAdapter`) implementing `CarrierAdapter` Protocol with
  five methods: `create_shipment`, `cancel_shipment`, `fetch_label`,
  `parse_webhook_event`, `schedule_pickup`. The adapter knows the
  carrier's wire format and nothing else.
- **Layer 2 — Coordinator:** `CarrierCoordinator` owns persistence
  (registry, label store, manifest) and state-engine validation. It
  consumes `CarrierAdapter` instances and never reads their internals.
- **Layer 3 — Operator UX:** route layer, dashboard, action proposals.
  Speaks to the coordinator, never to the adapter.

`CarrierAdapter` is `@runtime_checkable`; the coordinator validates
adapter shape at construction time via `isinstance(x, CarrierAdapter)`.
Exception hierarchy is shared (`CarrierAdapterError` →
`CarrierAuthError` / `RateLimitError` / `TransportError` /
`ResponseError`).

## Rejected alternatives

- **SDK-direct integration.** Each carrier's SDK at the route layer.
  Rejected: ties operator UX to vendor breakage; no test seam.
- **Per-carrier service modules with no Protocol.** Each carrier writes
  its own coordinator. Rejected: triplicates persistence + state logic.
- **Inheritance hierarchy.** `BaseCarrierAdapter` + subclasses.
  Rejected: Protocol gives the same compile-time benefit without forcing
  a class hierarchy that surveys badly across vendor boundaries.

## Risks

- Protocol surface is fixed at five methods. A carrier needing a sixth
  capability (e.g. label correction) requires Protocol evolution.
  Mitigated by `@runtime_checkable` + isinstance test in every adapter
  test file.
- Coordinator could become a god class. Mitigated by per-method scope
  and the state-engine discipline in ADR-003.

## Rollback

Revert DL-A. Stub adapter and Protocol disappear together; live DHL
work would need to start over against a carrier-specific module.

## Future impact

FedEx and UPS land as new adapter classes only — coordinator, state
engine, label store, registry, and routes are unchanged. The shadow
adapter (ADR-004) wraps any adapter that satisfies the Protocol.
