# ADR-030: Resolved-CIF is the single customs-value authority; raw parsed fields are evidence

**Status:** Accepted
**Date:** 2026-06-17
**Phase:** campaign-wide
**Deciders:** Amit
**Related:** ADR-008 (three-state DHL status), ADR-023 (master-data SSOT),
PR #627 (`cif_resolver` tri-state), PR #631 (upload e2e), PR #633 (UI + Polish-desc gate)

## Context

A shipment's customs CIF value can be produced by several layers: the
engine-verified invoice CIF, the parsed invoice CIF/FOB totals, the DHL
pre-check totals, the carrier-declared AWB Custom Val, and the OCR/AI vision
fallback. Historically each customs-adjacent surface made its own decision about
which field to trust, and several keyed directly off the raw parsed invoice CIF.

When invoice parsing failed it collapsed the invoice CIF to `0`. A raw `0` then
flowed into UI cards, generators, and routing gates *as if it were a real
declared value* — blocking shipments that were, in fact, fully routable from
another layer. AWB **2315714531** is the canonical case: its commercial invoice
never produced a parsed CIF (raw invoice CIF `0`), but its AWB Custom Val
declared **USD 732**. The legacy `generate_description` route hard-blocked it on
"CIF = 0.00", contradicting the clearance-routing layer which had already
resolved 732 and routed the shipment.

`cif_resolver.resolve_cif` (PR #627) fixed the *resolution* with a tri-state
contract — `resolved` / `declared_zero` / `unknown`, never a fabricated `0.0`.
PR #633 wired the UI and the Polish-description gate to it. But the remaining
customs/PZ surfaces (DSK generation, the customs package, the agency
routing-pending message, the action-proposal routing gates) still made
independent or raw-zero-based decisions, so the authority was not yet single.

## Decision

**The resolved CIF is the single customs-value authority for every action.
Raw parsed invoice fields are EVIDENCE, never the gate.**

1. `cif_resolver.resolve_cif` is the one resolution function. No surface
   re-implements the ladder or reads a raw invoice CIF to decide legality.

2. A shared action-layer gate, `services/cif_authority.py`, wraps the resolver:
   - `get_cif_authority(audit)` — pure, never raises; returns the resolved
     value, tri-state, source, the raw invoice CIF (flagged advisory when it is
     not the winning source), and `is_resolved` / `is_blocked` / `blocker_reason`.
   - `require_resolved_cif(audit, action=...)` — returns on `resolved`; raises
     `HTTPException(422)` with `code="cif_unresolved"` on `unknown` (extraction
     gap, surface the next action) and `code="cif_declared_zero"` on
     `declared_zero` (a genuine zero requires explicit operator review before a
     customs/PZ document is generated against it).

3. Every customs/PZ/DHL action that declares or routes on a customs value gates
   through `require_resolved_cif` (Polish description, customs package, DSK), or
   reads `get_cif_authority` for routing decisions (action proposals). An
   explicit operator-supplied value (e.g. DSK payload `value_usd`) remains the
   operator's own authority and is respected as-is.

4. A raw invoice CIF of `0` is never, on its own, a blocker, a routing input, or
   a declared value. It is displayed as advisory evidence only.

## Rejected alternatives

- **Leave each surface to read the resolver inline (status quo after #633).**
  Rejected: every new customs surface would re-derive the gate, drift is
  inevitable, and the declared-zero-vs-unknown distinction would be
  re-implemented inconsistently. A shared helper is the only way to guarantee
  one authority.
- **Treat `declared_zero` the same as `resolved` (let zero-value docs generate).**
  Rejected: a genuine no-commercial-value shipment is real, but auto-generating
  a customs/PZ document against a zero value without review is a compliance
  hazard. `declared_zero` blocks pending explicit operator review.
- **Treat `unknown` as `0`.** Rejected outright — this is the original bug.
  `unknown` is "we don't know yet", surfaced with an extraction gap and a next
  action, never a silent zero.
- **Change `build_clearance_decision` routing.** Rejected as out of scope and
  unnecessary: the decision object already consumes `resolve_cif`. This ADR
  governs the *action gates*, not the routing map.

## Risks

- **A surface gets added later that bypasses the helper.** Mitigated by the
  source-grep contract tests (`test_cif_authority.py`,
  `test_polish_desc_cif_resolved_gate.py`) and this ADR; reviewer-challenge
  flags any new customs surface that reads a raw invoice CIF.
- **A real shipment is now blocked at `declared_zero` that previously slipped
  through.** This is intended — it converts a silent zero into an explicit
  review gate. Operators see the reason and the override path.
- **No behavioural regression for resolved shipments.** The gate returns on
  `resolved` exactly as the prior inline checks did; the full pre-existing test
  baseline is unchanged (49 pre-existing environment failures are identical with
  and without this change).

## Rollback

Revert the PR. The shared helper `cif_authority.py` is additive; the four wired
call sites (`routes_dhl_clearance.generate_description` +
`generate_customs_package`, `routes_dsk.generate_dsk_endpoint`,
`routes_agency` routing-pending message, `routes_action_proposals` value gates)
revert to their prior inline/raw logic. `cif_resolver` and `clearance_decision`
are untouched, so no resolution or routing behaviour changes on rollback. Cost:
the raw-zero false-block returns for AWB-only-resolved shipments.

## Future impact

- Locks in one customs-value authority for all future customs/PZ/DHL surfaces:
  any new generator, PZ step, or comparison block calls `require_resolved_cif` /
  `get_cif_authority` rather than reading raw fields.
- Establishes the `cif_unresolved` vs `cif_declared_zero` machine-code contract
  for callers/UI to branch on the *reason* an action is blocked.
- AWB 2315714531 (invoice CIF 0, AWB Custom Val 732) is a permanent regression
  fixture proving a raw zero never wins over a usable resolved value.
