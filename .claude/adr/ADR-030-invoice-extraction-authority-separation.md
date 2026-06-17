# ADR-030: Invoice Extraction Authority Separation — Vision Proposal vs Operator-Confirmed Accounting Authority

**Status:** Accepted
**Date:** 2026-06-17
**Deciders:** Amit
**Phase:** campaign-wide (invoice-extraction campaign, PR #640 → PR-2)
**Related:** ADR-020 (Anthropic API sole provider), ADR-021 (detect-before-gate), ADR-023 (Master-data SSOT), ADR-024 (Product Master authority); Lesson F (authority isolation), Lesson G (cache/atomicity), Lesson M (capability visibility); `cif_resolver.py` tri-state authority; PR #632/#633 (CIF vision fallback), PR #640 (image-only invoice recovery)

## Context

A commercial invoice can arrive as an **image-only scan** that defeats the text
parser. When that happens `process_batch()` receives FOB=0, zero line items, and
no supplier — no PZ (goods receipt) can be computed. AWB 2315714531 is the
triggering case: customs-cleared (CIF USD 732 resolved via the deployed #632/#633
**CIF** vision fallback) but not purchase-accounting-ready.

PR #640 adds an **advisory** recovery layer: `run_image_only_invoice_extraction`
reads supplier / FOB / goods-lines from an image-only invoice into
`audit["vision_invoice"]`. This creates a new, dangerous class of data — a
machine-generated OCR/LLM **proposal** that *looks* exactly like booked
accounting truth (it has `fob_usd`, `line_items`, `supplier`) but has had **no
human review**.

The failure mode this ADR exists to make impossible is **authority bleed**: a
low-confidence OCR guess silently becoming a PZ line, a wFirma goods-receipt
quantity, a landed-cost input, or a customs value. This is the same class
`cif_resolver` was built to kill (the fake-zero / poisoned-authority problem),
now reappearing one domain over in purchase accounting.

The existing CIF authority model is the proven template:
- `resolve_cif(audit)` is a pure tri-state resolver (`RESOLVED` / `DECLARED_ZERO`
  / `UNKNOWN`) over an **ordered authority ladder**; it never fabricates a zero
  and never reads anything outside the ladder.
- `vision_invoice` is **deliberately absent** from that ladder.
- `test_vision_invoice_negative_scope.py` pins the isolation with a poison block
  (CIF-shaped `99999`) plus static source-contract tests asserting that
  `cif_resolver.py`, `clearance_decision.py`, and `active_shipment_monitor.py`
  never name `vision_invoice`.

This ADR generalizes that model into a permanent four-layer authority law for
invoice processing.

## Decision

**Invoice processing has exactly four authority layers, in strict order. No
service may treat a lower layer as if it were a higher one.**

| # | Layer | Key(s) | Meaning | Owner (writer) | Trust level |
|---|---|---|---|---|---|
| 1 | **vision_invoice** | `audit["vision_invoice"]` (`supplier`, `fob_usd`, `currency`, `line_items[]`, `confidence`, `operator_confirmed`) | Machine PROPOSAL from OCR/LLM on an image-only invoice. Unreviewed. | `vision_extractor.run_image_only_invoice_extraction` / `_merge_vision_invoice` | **None** — advisory only |
| 2 | **operator_confirmed** | `audit["vision_invoice"]["operator_confirmed"] == true` | Human ADOPTION of the proposal. The single write-gate that converts a proposal into engine-eligible input. | PR-2 operator-confirm endpoint (does **not exist yet**) | Human-attested |
| 3 | **engine_parsed** | `audit["rows"]` (non-empty) + `invoice_totals.total_fob_usd` (strictly positive) | Booked ACCOUNTING authority produced by `process_batch()`. Feeds PZ, landed cost, wFirma goods, exports. | `process_batch()` via `export_service` / `import_pz_builder` | Authoritative (accounting) |
| 4 | **clearance_decision** | `audit["clearance_decision"]`, CIF via `resolve_cif()` | Booked CUSTOMS authority (CIF/value, routing). Independent of 1–3. | `clearance_decision.build_clearance_decision` over `cif_resolver` | Authoritative (customs) |

### The enforcement rule (permanent invariant)

> **No service may read `vision_invoice` directly to drive PZ generation, wFirma
> posting, landed-cost computation, accounting exports, or warehouse booking
> unless `vision_invoice.operator_confirmed == true`.**

Corollaries:

1. **Customs is fully isolated from the proposal.** `cif_resolver`,
   `clearance_decision`, and any active-shipment / monitor consumer must NEVER
   read `vision_invoice` — not even when confirmed. Customs CIF authority
   (layer 4) and purchase-accounting authority (layers 1–3) are **separate
   ladders that never cross**. The vision *CIF* fallback (#632/#633) writes only
   CIF-ladder keys; the vision *invoice* layer (#640) writes only
   `vision_invoice`. Neither reads the other.

2. **The engine never reads the proposal.** `process_batch()` consumes parsed
   invoice text, not `vision_invoice`. The only path from layer 1 to layer 3 is:
   operator confirms (layer 2) → a PR-2 injection step copies the confirmed
   fields into the engine's input contract → the engine recomputes. There is no
   direct layer-1 → layer-3 edge.

3. **USD-only discipline.** `fob_usd` is a USD figure by contract.
   `_merge_vision_invoice` accepts it only when the read currency is USD; unknown
   or non-USD currency withholds the value (never mislabels a foreign amount as
   dollars), mirroring the CIF fallback's USD gate.

4. **Sticky confirmation.** Once `operator_confirmed == true`, the machine never
   overwrites the block. `_merge_vision_invoice` is sticky; the orchestrator
   re-reads `operator_confirmed` from disk immediately before its atomic write
   (TOCTOU guard) and aborts if a confirmation landed mid-run.
   `vision_invoice` is in `audit_merge.PRESERVED_KEYS` so the proposal and its
   confirmation survive engine regeneration.

### Where the enforcement gates live

| Gate | Location | Behavior |
|---|---|---|
| **Proposal write** | `vision_extractor.run_image_only_invoice_extraction` | Writes `vision_invoice` only when engine has NOT parsed (layer 3 absent), confidence ≥ `MIN_WRITE_CONFIDENCE`, document is image-only. Never touches CIF keys / `invoice_totals` / `rows` / `customs_declaration`. |
| **Confirmation write** (PR-2) | new operator-confirm endpoint in `routes_dashboard` / `routes_pz` | The ONLY writer of `operator_confirmed = true`. Requires explicit operator action (no auto-confirm, no confirm-on-mount). |
| **Engine injection** (PR-2) | the step that builds `process_batch()` inputs | May read confirmed `vision_invoice` fields ONLY when `operator_confirmed == true`; otherwise the engine sees no invoice and PZ stays blocked. |
| **PZ generation** | `routes_pz.process_pz` / `export_service` | Operates on layer 3 (`rows` + `invoice_totals`) only. If layer 3 is empty, PZ is not computable — blocked, not faked. |
| **wFirma posting** | `routes_wfirma` | Operates on layer 3 only. Must never read `vision_invoice`. |
| **Customs** | `clearance_decision` / `cif_resolver` | Reads the CIF ladder only. Must never read `vision_invoice`. |

### How this is tested (same pattern as CIF authority today)

The CIF test pattern in `test_vision_invoice_negative_scope.py` is the template
and must be extended, not replaced:

1. **Behavioral invariance with a poison block** — construct a `vision_invoice`
   carrying loud, high-value accounting-shaped fields (e.g. `fob_usd = 99999`,
   line items totalling 99999). Assert that every accounting/customs consumer's
   output is **byte-identical with and without** the block present, while
   `operator_confirmed` is false. Today this is pinned for `resolve_cif` and
   `build_clearance_decision`; PR-2 must add the same invariance test for the PZ
   input-builder and the wFirma post-payload builder.

2. **Static source contracts** — assert the substring `"vision_invoice"` does
   **not** appear in any layer-4/accounting-isolated source: `cif_resolver.py`,
   `clearance_decision.py`, `active_shipment_monitor.py` (already pinned). When
   PR-2 lands the injection step, add a positive contract: the injection module
   is the **only** non-vision_extractor source permitted to name
   `vision_invoice`, and it must reference `operator_confirmed` on the same read
   path (test greps for both tokens together).

3. **Confirmation-gate test** (PR-2) — assert the PZ input-builder reads
   confirmed fields when `operator_confirmed == true` and reads nothing when it
   is false/absent. The 0.49/0.51 confidence boundary (Issue #639) and a
   dedicated quantity-coercion test (Issue #638) attach here.

## Rejected alternatives

- **Let `process_batch()` read `vision_invoice` directly when confidence is
  high.** Rejected: confidence is a model self-report, not human attestation. A
  high-confidence wrong extraction would book a wrong goods receipt with full
  audit-trail credibility. Human confirmation is the only acceptable gate into
  accounting authority. This is the exact fake-zero failure class, one domain over.

- **Reuse the CIF ladder / `resolve_cif` for FOB too.** Rejected: customs CIF and
  purchase-accounting FOB are different authorities with different owners,
  different downstream consumers (SAD vs PZ/wFirma), and different correctness
  rules. Collapsing them recreates the multi-authority fragmentation ADR-023/024
  fought. They stay separate ladders.

- **Auto-confirm low-risk proposals (e.g. single-line invoices).** Rejected: no
  machine-decidable "low-risk" boundary exists for accounting truth that a
  customs authority or auditor would accept. Lesson M requires the capability be
  visible-and-disabled, not silently auto-actioned.

- **Block the whole shipment until a human re-keys the invoice manually.**
  Rejected as the permanent solution: it is the shipment-specific patch
  (Lesson I). The proposal layer + confirm workflow makes every future
  image-only invoice self-recovering instead of a one-off manual exception.

## Risks

- **A future contributor adds `vision_invoice` to an accounting/customs read
  path.** Mitigated by the static source-contract tests (failing-first by
  construction) and this ADR. Any PR touching `cif_resolver`,
  `clearance_decision`, the PZ input-builder, or `routes_wfirma` must be checked
  against the enforcement rule.
- **The confirmation flag is set by something other than the operator endpoint.**
  Mitigated: PR-2 must make the operator-confirm endpoint the sole writer of
  `operator_confirmed = true`, and the orchestrator's TOCTOU guard + sticky merge
  prevent the machine from clobbering or forging it.
- **Duplicate authority (the named production-safety concern).** `fob_usd` exists
  in BOTH `vision_invoice` (layer 1) and, post-parse, `invoice_totals` (layer 3).
  This is acceptable ONLY because the two are never read by the same consumer:
  accounting reads layer 3 exclusively; the proposal is display/confirm only.
  PR-2 must not introduce a consumer that reads `fob_usd` ambiguously from
  whichever layer is present — it must read layer 3, or read layer 1 strictly
  behind the `operator_confirmed` gate, never "whichever exists."

## Rollback

PR #640 is additive and advisory: removing the `vision_invoice` block and the
non-fatal orchestrator calls in `routes_upload` / `routes_dashboard` returns the
system to text-parser-only behavior (image-only invoices simply fail to produce
PZ, as before #640). No accounting or customs data is touched by a rollback
because no accounting/customs consumer reads the proposal. Cost: image-only
invoices revert to manual handling until re-deployed.

## Future impact

- Locks in the four-layer authority law for all future invoice work; any new
  extraction modality (e.g. EDI, supplier portal) plugs in as a layer-1 proposal
  and inherits the same confirm-gate.
- Establishes the test template (poison-block invariance + static source
  contract + confirm-gate) as the required proof for any new accounting authority.
- Enables PR-2 (operator confirmation workflow) and the eventual unblocking of
  PZ/wFirma for image-only shipments — without ever granting a machine the
  authority to book accounting truth unattended.
