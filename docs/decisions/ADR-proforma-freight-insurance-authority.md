# ADR: Proforma freight & insurance charges have one calculation authority, separate from customs CIF

Status: Accepted (operator decision, Proforma Review campaign PR-6, 2026-07-15).
Decision: The proforma **commercial** freight + insurance subtotal is resolved ONCE, from the persisted draft snapshot (`service_charges_json`), by a single `CommercialChargeAuthority`. The insurance premium has exactly ONE formula, computed and **frozen at write time**. The read authority consumes the frozen snapshot and never invents a premium. Customs **CIF** valuation stays a completely separate import-side authority.

## Context

The proforma freight/insurance subtotal was computed independently in several places, each with slightly different rules:

- The **preview endpoint** summed the *live* editing table (`proforma_service_charges_db`) — a different source from the persisted snapshot the finance dual-write and print use, so preview and document could disagree.
- The **HTML render** and multiple **V2 UI** sites (`ProformaLinesTab` footer, AWB declared value, the print-doc renderer, the preview doc data) each ran their own `reduce(sum amount)` over `service_charges`, some with a same-currency filter and some without — so a cross-currency charge could be silently summed into a total in the wrong currency.
- Insurance had a real bug: `compute_insurance_suggestion` returned a `formula_basis` (rate + sales_total) but the persisted charge could carry `amount = 0`; the read side had no frozen premium to consume and no safe way to recover one, so the premium disappeared from totals.

There was no single answer to "what is the freight+insurance subtotal for this draft, in this currency?" — every consumer re-derived it.

## Decision

1. **One authority, from the snapshot.** `commercial_charge_authority.resolve_commercial_charges(draft_currency, service_charges)` is the sole resolver of the commercial freight + insurance totals. Its input is the persisted draft snapshot (`service_charges_json`) — the same source finance and print already trust. It returns `freight_total`, `insurance_total`, `service_charge_subtotal`, `cross_currency_charges[]`, `incomplete_charges[]`, and provenance `{source: "draft_snapshot", currency_rule: "same_currency_only"}`. It is a pure module: no I/O, no Customer Master read, no live-table read.

2. **Same-currency-only subtotal.** Only charges whose currency equals the draft currency enter the subtotal. A charge in another currency (e.g. PLN freight on a USD draft) is surfaced in `cross_currency_charges` and is **never converted or summed** — no FX is performed in the commercial-charge layer. The printed total can therefore never be a cross-currency misstatement.

3. **One insurance formula, frozen at write time.** `insurance_premium(sales_total, rate, minimum) = max(sales_total × rate, minimum)`, cents-quantised, is the ONLY premium formula in the system. `customer_master.compute_insurance_suggestion` (the write/suggest path) imports and calls it — it does not re-implement the arithmetic. When Customer-Master commercial defaults are applied to a draft, the computed premium **and** its frozen evidence (`sales_total`, `rate_pct`, `minimum_eur`/`minimum_usd`) are persisted into the charge (`proforma_invoice_link_db.apply_customer_commercial_to_draft` → `_apply_insurance_freeze`), on both the existing-charge and new-charge paths.

4. **Read authority consumes frozen evidence; it never invents.** When resolving:
   - a frozen `amount > 0` is consumed verbatim (the normal path);
   - a legacy `amount == 0` is recomputed **only** from the charge's own frozen `formula_basis` (`sales_total` + `rate_pct`, `minimum` optional by design), using the one shared formula;
   - if those frozen inputs are incomplete, the charge is reported in `incomplete_charges` and contributes **zero** — the resolver never consults the live Customer Master to repair an amount, and never fabricates a premium.

5. **Every consumer reads the one authority — no independent re-sum.**
   - Backend: `_draft_to_full` projects `commercial_charges`; the preview endpoint's `service_charge_total` and the HTML render's `charges_total` both call `resolve_commercial_charges` on the draft snapshot (preview falls back to the live-list sum only when there is no draft at all).
   - Frontend (`proforma-detail.jsx`): the `ProformaLinesTab` footer, the AWB declared value, the `VatInsurancePanel` (shows the resolved premium once a charge is saved; a labelled live estimate only pre-save), and `previewDocData` all read `commercial_charges` — no `reduce(sum amount)` over `service_charges` remains in a financial path.
   - Print (`estrella-doc-proforma.jsx`): the three template variants prefer `docData.charges_total` (the authority subtotal); the row-sum fallback is retained only for callers that do not supply it.

6. **Customs CIF stays separate.** The commercial-charge authority does not import, call, or feed `cif_resolver` / customs valuation, and customs valuation does not read commercial charges. Duty and CIF continue to come from ZC429 / A00 by value, unchanged by this slice. Freight in the customs CIF and freight in the commercial proforma are deliberately two different authorities.

### Editing vs. authority

The live `proforma_service_charges_db` table remains the **editing** surface (add/update/remove a charge). Editing writes the snapshot; the snapshot — not the live table — is the financial source of truth once a charge is saved. No new charge table and no second financial writer are introduced.

## Consequences

- One subtotal, one currency rule, one premium formula — preview, print, AWB, finance dual-write, and the UI can no longer disagree.
- The `amount = 0` insurance bug is fixed at the write boundary; every persisted premium now carries frozen evidence.
- Cross-currency charges are honestly surfaced instead of being silently mis-summed.
- Customs valuation is untouched; the CIF/commercial separation is now pinned by test.

## Rollback

Additive and reversible: revert the PR-6 commit. The new module is read-only; the write-time freeze only adds fields to the charge JSON (existing rows unaffected — a legacy `amount == 0` with complete frozen inputs still resolves, and one with incomplete inputs is reported, never invented). No production data migration or correction is performed.
