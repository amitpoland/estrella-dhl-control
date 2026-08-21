# ADR: wFirma service-product IDs are configuration metadata and do not appear on a posted Proforma

Status: Accepted (operator decision, Proforma Overview consolidation, ratified 2026-08-21; implemented in PR #1309, deployed at `3748daae3bae137927fc7d77f9b330f36bba67f6`).

Decision: A **posted** Proforma is a business document and presents business charge facts only. The raw wFirma service-product identifier stored on each charge line (`wfirma_service_id`, rendered as `svc:<id>`) is **configuration metadata**: it names the registry row a charge maps to. It is gated behind `canEdit`, so it renders while the draft is still editable — where the operator is actually choosing that mapping — and disappears once the document is posted. The value itself is **preserved everywhere it has authority**: on the draft, in the API response, in the audit trail, and in the service-product registry.

## Context

The Proforma Overview consolidation removed duplicated and internal presentation from the operator-facing document. Two related things were true at the same time:

- `ServiceProductRegistryPanel` — the surface that **manages** those mappings, and whose write is an org-wide `PUT /api/v1/proforma/service-products/{charge_type}` — was already `canEdit`-gated in intent. Its own docstring says it belongs on the page "when `canEdit === true`", but the guard had never been written, so a posted document rendered the panel *and* its edit controls.
- The per-charge `svc:<wfirma_service_id>` annotation next to Freight and Insurance was rendered unconditionally, on every draft state.

So a posted fiscal document displayed the identifier of a registry row whose management surface was (intended to be) unavailable from that same document. The annotation had outlived its own context: nothing an operator reads on a posted proforma depends on it, and they cannot act on it there.

This is a **presentation** decision, not an authority change. No duplicate authority existed to repair — the identifier has exactly one owner (the service-product registry) and one storage location (the draft charge line).

## Decision

1. **Posted business surface shows business facts.** On a posted Proforma the Service Charges panel shows Freight, Insurance, the stored insurance rate, and the `basis × rate = premium` provenance. It does not show `svc:<id>`.

2. **The identifier is gated, never deleted.** The render is `{canEdit && c.wfirma_service_id && …}`, where `canEdit = ['draft', 'editing', 'post_failed'].includes(draftState)` — provably false for `posted`. The value remains:
   - on the draft (`service_charges_json`),
   - in the draft API response (`GET /api/v1/proforma/draft/{id}` returns `wfirma_service_id` per charge),
   - in the audit trail,
   - in the registry authority (`GET /api/v1/proforma/service-products`),
   - and on screen in the editable/configuration context.

3. **The registry panel is gated to the same boundary.** `{canEdit && <ServiceProductRegistryPanel />}`. Org-wide registry configuration is not a property of one fiscal document, and its write must not be reachable from a posted one.

4. **This is a Lesson M relocation, not a removal.** No operator-visible capability is cancelled: the capability moves to the state that owns it. This ADR is the formal record Lesson M requires for changing where an operator-visible element appears.

## Consequences

- An operator who needs the mapping for a posted document reads it from Master Data / the registry, or from the Audit Trail — the authorities that own it — not from the fiscal document.
- Reverting the gate would put org-wide configuration metadata back onto a posted business document and re-expose the registry write surface there. `service/tests/test_posted_proforma_no_registry_ids.py` pins both halves: the id is absent from the posted surface **and** the value, its testid, the charge amounts, the rate and the premium formula all survive.
- The pin deliberately asserts preservation as well as suppression, so a future change cannot satisfy it by deleting the field.

## Scope

This ADR covers presentation only. It does not change any wFirma mapping, any charge amount, any calculation, or any fiscal behaviour, and it does not alter the `CommercialChargeAuthority` contract recorded in `ADR-proforma-freight-insurance-authority.md`.
