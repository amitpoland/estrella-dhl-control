# ADR: Proforma freight & insurance charges have one calculation authority, separate from customs CIF

Status: Accepted (operator decision, Proforma Review campaign PR-6, 2026-07-15; revised same day to add explicit charge-resolution states).
Decision: The proforma **commercial** freight + insurance subtotal is resolved ONCE, from the persisted draft snapshot (`service_charges_json`), by a single `CommercialChargeAuthority`. Each charge carries an **explicit operator resolution**; a zero amount is a valid commercial decision, never inferred from the amount and never recomputed at read. The insurance premium has exactly ONE formula, computed and **frozen only by the Calculate action (write time)**. Customs **CIF** valuation stays a completely separate import-side authority.

## Context

The proforma freight/insurance subtotal was computed independently in several places, each with slightly different rules:

- The **preview endpoint** summed the *live* editing table (`proforma_service_charges_db`) — a different source from the persisted snapshot the finance dual-write and print use, so preview and document could disagree.
- The **HTML render** and multiple **V2 UI** sites (`ProformaLinesTab` footer, AWB declared value, the print-doc renderer, the preview doc data) each ran their own `reduce(sum amount)` over `service_charges`, some with a same-currency filter and some without — so a cross-currency charge could be silently summed into a total in the wrong currency.
- Insurance had a real bug: `compute_insurance_suggestion` returned a `formula_basis` (rate + sales_total) but the persisted charge could carry `amount = 0`; the read side had no frozen premium to consume and no safe way to recover one, so the premium disappeared from totals.
- A first cut of this authority tried to *recompute* a legacy `amount = 0` from the frozen inputs at read time. That was wrong on two counts: (a) it inferred intent from the amount — a zero freight/insurance is often a legitimate decision (the client provides their own courier, the charge is waived, or it is not applicable); and (b) the recomputed premium was displayed in the preview/print total but the wFirma line builder and finance dual-write only bill a persisted positive amount, so the total over-stated what was actually billed.

There was no single answer to "what is the freight+insurance subtotal for this draft, in this currency?" — every consumer re-derived it, and a zero had no explicit meaning.

## Decision

1. **One authority, from the snapshot.** `commercial_charge_authority.resolve_commercial_charges(draft_currency, service_charges)` is the sole resolver of the commercial freight + insurance totals. Its input is the persisted draft snapshot (`service_charges_json`) — the same source finance, wFirma line-building, and print already trust. It returns `freight_total`, `insurance_total`, `service_charge_subtotal`, a resolved `charges[]` view, `cross_currency_charges[]`, `unresolved_charges[]`, and provenance `{source: "draft_snapshot", currency_rule: "same_currency_only"}`. It is a pure module: no I/O, no Customer Master read, no live-table read, and it takes no Customer Master argument.

2. **Explicit charge resolution — a zero is a decision, never inferred.** Each charge carries a persisted `resolution` ∈ {`calculated`, `manual_amount`, `customer_courier`, `waived`, `not_applicable`, `unresolved`}:
   - `calculated` / `manual_amount` — the persisted amount (which may legitimately be 0) is authoritative and billable.
   - `customer_courier` / `waived` / `not_applicable` — a valid **zero** decision: contributes 0, never blocks, surfaced with its reason.
   - `unresolved` — no explicit decision yet: **excluded** from the billable subtotal and surfaced in `unresolved_charges[]` for operator review.
   - A legacy row with **no** resolution and a **positive** amount is billable as stored. A legacy row with a **zero** amount and insurance formula/rate evidence but no resolution is classified `unresolved` (rule: never infer intent from the amount alone).

3. **Same-currency-only subtotal.** Only charges whose currency equals the draft currency enter the subtotal. A charge in another currency (e.g. PLN freight on a USD draft) is surfaced in `cross_currency_charges` and is **never converted or summed**.

4. **One insurance formula, frozen only by the Calculate action.** `insurance_premium(sales_total, rate, minimum) = max(sales_total × rate, minimum)`, cents-quantised, is the ONLY premium formula. It runs **only at write time** — the read authority NEVER recomputes. The explicit Calculate-from-Customer-Master action (`apply-service-charges`, and `apply_customer_commercial_to_draft` → `_apply_insurance_freeze`) computes the premium, persists it with its frozen evidence (`sales_total`, `rate_pct`, `minimum_*`), and stamps `resolution = calculated`. A saved zero is therefore never silently turned into a premium during a read.

5. **Explicit resolution is written by the ONE service-charge writer.** `add_draft_service_charge` / `update_draft_service_charge` persist and validate `resolution`; a new endpoint `POST /draft/{id}/service-charge-resolution` upserts a charge's decision through those same writers (no new writer, no new table). `calculated` may not be set through that endpoint — only the Calculate action produces it. UI actions: **Calculate from Customer Master**, **Enter manually**, **Client provides courier**, **Waive**, **Not applicable**.

6. **Every consumer reads the one authority — same amount + resolution.**
   - Backend: `_draft_to_full` projects `commercial_charges`; the preview endpoint sources BOTH the charge list AND the subtotal from the draft snapshot (never the live table) once a draft exists, falling back to the live editing table only before a draft snapshot exists; the HTML render's `charges_total` calls the authority.
   - wFirma posting: `_build_service_charge_lines` reads the snapshot, bills the persisted per-charge amount, applies the same same-currency gate, and **explicitly skips `unresolved`** charges (surfaced, never silently billed).
   - Finance: the dual-write reads the posted draft's `service_charges_json` and bills the persisted amount (0 → no row); it never recomputes.
   - Frontend (`proforma-detail.jsx`): the `ProformaLinesTab` footer, AWB declared value, `VatInsurancePanel`, and `previewDocData` read `commercial_charges`; the `ServiceChargesPanel` renders each charge's resolution and surfaces `unresolved_charges` for review.
   - Print (`estrella-doc-proforma.jsx`): the three variants prefer `docData.charges_total`.

7. **Customs CIF stays separate.** The commercial-charge authority does not import, call, or feed `cif_resolver` / customs valuation, and customs valuation does not read commercial charges. Duty and CIF continue to come from ZC429 / A00 by value, unchanged.

### Editing vs. authority

The live `proforma_service_charges_db` table remains a pre-create editing surface only. Once a draft exists, the draft snapshot (`service_charges_json`) is the sole financial source for every consumer — including the preview's charge list, which no longer reads the live table for an existing draft. No new charge table and no second financial writer are introduced.

## Consequences

- One subtotal, one currency rule, one premium formula — preview, print, AWB, wFirma line-building, finance dual-write, and the UI read the same persisted amount + resolution and can no longer disagree.
- A zero freight/insurance is a first-class, auditable decision (client courier / waived / not applicable / manual 0), not an error and not silently billed.
- The read authority never recomputes a saved zero, so the displayed total always equals what is billed. An ambiguous legacy zero is surfaced for an explicit operator decision rather than guessed.
- Cross-currency charges are honestly surfaced instead of being silently mis-summed. Customs valuation is untouched; the CIF/commercial separation is pinned by test.

## Rollback

Additive and reversible: revert the PR-6 commit. The new module is read-only; the writer only adds a nullable `resolution` field (and, for the Calculate action, the frozen amount + evidence) to the charge JSON — existing rows are unaffected: a legacy positive amount stays billable, and a legacy zero with evidence is surfaced as `unresolved` rather than mutated. No production data migration or correction is performed.
