# wFirma → Client Master / Supplier Master ownership model

**Date:** 2026-05-16
**Status:** Operational. Implemented in `customer_master_db.upsert_identity_only` (PR #145, extended in B0 deep-enrichment 2026-05-16) and `suppliers_db.sync_from_wfirma` (PR #141, extended PR #145).

This document is the authoritative reference for **who owns what field**
when wFirma data flows into local masters.

---

## Core rule

> **wFirma is the source of contractor defaults.**
> **Local Client Master is the operational authority for commercial settings.**

Therefore identity sync is always **fill-when-empty**, never blind replace.

The exception: the operator can explicitly refresh `bill_to_name` and
`country` (the two SQL-NOT-NULL identity columns) on every sync because
these are the canonical reference values an operator-entered local copy
should track against the wFirma master.

---

## Ownership matrix

### wFirma-owned defaults (read-only source)

These fields originate in wFirma. The local row is filled when empty
from wFirma; the local row is preserved when non-empty.

| Local column | wFirma source | Fill rule |
|---|---|---|
| `bill_to_contractor_id` | `<contractor><id>` | **Always rewritten** (identity key) |
| `bill_to_name` | `<name>` | **Always rewritten** (canonical wFirma name) |
| `country` | `<country>` | **Always rewritten** (uppercase ISO-2) |
| `nip` | `<nip>` | Fill-when-empty (operator-set VAT IDs preserved) |
| `bill_to_email` | `<email>` | Fill-when-empty |
| `bill_to_phone` | `<phone>` / `<tel>` | Fill-when-empty |
| `bill_to_mobile` | `<mobile>` | Fill-when-empty |
| `bank_account` | `<account_payments>` | Fill-when-empty |
| `default_currency` | `<default_currency>` | Fill-when-empty (uppercase) |
| `payment_terms_days` | `<payment_term>` (int days) | Fill-when-empty |
| `default_language_id` | `<translation_language_id>` | Fill-when-empty |
| `preferred_proforma_series_id` | `<proformaseries_id>` | Fill-when-empty |
| `preferred_invoice_series_id` | `<invoiceseries_id>` | Fill-when-empty |
| `last_wfirma_sync_at` | (timestamp at apply) | **Always rewritten** |
| `wfirma_sync_source` | (`"review_assign"`) | **Always rewritten** |

### Local-owned (operator authority — never touched by sync)

These columns are the operator's exclusive territory. They are NEVER
written by `upsert_identity_only` — neither on INSERT (left at SQL NULL
or table default) nor on UPDATE (no `SET` clause covers them).

| Local column | Owner | Notes |
|---|---|---|
| `freight_service_id` | operator | Defaulted to `13002743` (Fedex Courier) at INSERT |
| `freight_fixed_amount_eur` | operator | Standing freight amount EUR drafts |
| `freight_fixed_amount_usd` | operator | Standing freight amount USD drafts |
| `freight_currency` | operator | |
| `freight_mode` | operator | `fixed` / `variable` / `manual` / `no_data` |
| `freight_label_pl` / `freight_label_en` | operator | Billing labels |
| `freight_last_amount` / `freight_avg_amount` | operator | Historical |
| `insurance_service_id` | operator | Defaulted to `13102217` at INSERT |
| `insurance_rate` | operator | Decimal, e.g. `0.0035` |
| `insurance_fixed_amount_eur` / `_usd` | operator | |
| `insurance_min_eur` / `_usd` | operator | Formula floor |
| `insurance_min_amount` / `insurance_min_override` | operator | Legacy |
| `insurance_label_pl` / `insurance_label_en` | operator | |
| `insurance_enabled` | operator | Default `1` |
| `insurance_mode` | operator | `fixed` / `formula` / `manual` / `no_data` |
| `credit_limit` / `credit_currency` | operator | |
| `kuke_approved` / `kuke_limit` / `kuke_currency` / `kuke_expiry_date` | operator | KUKE policy state |
| `kuke_policy_number` / `kuke_self_retention_pct` | operator | |
| `kyc_status` / `kyc_approved_on` / `kyc_expiry` | operator | KYC state |
| `beneficial_owner` / `owner_id_type` / `owner_id_number` | operator | |
| `aml_risk_rating` / `pep_check_result` / `compliance_notes` | operator | |
| `risk_status` | operator | |
| `vat_mode` | operator | `222` / `228` / `229` — operator-curated locally; not pulled from wFirma master |
| `ship_to_use_alternate` | operator | |
| `ship_to_name` / `ship_to_person` / `ship_to_street` / … | operator | |
| `ship_to_phone` / `ship_to_email` | operator | "Copy billing address" affordance pre-fills from wFirma-sourced billing fields |
| `ship_to_contractor_id` | operator | Alternative ship-to legal entity |
| `vat_eu_number` / `vat_eu_valid` / `vat_eu_validated_at` | operator | VAT verification state |
| `notes` | operator | Free-form notes |

### Mixed / pull-through fields

These start out wFirma-sourced and become operator-owned after first
edit. Practically: same fill-when-empty rule, but the operator UI
exposes them as freely editable.

| Field | First fill | Edit semantics |
|---|---|---|
| `bill_to_email` | from wFirma | operator can override locally; wFirma sync never blanks |
| `bill_to_phone` | from wFirma | same |
| `bank_account` | from wFirma | same |
| `default_currency` | from wFirma | operator-curated overrides win |
| `payment_terms_days` | from wFirma | operator-curated overrides win |

---

## Implementation guarantees

### Code-level enforcement

`upsert_identity_only` in `customer_master_db.py`:

- **INSERT path:** writes only the columns enumerated in the
  wFirma-owned matrix above. All other columns are SQL NULL or take
  their table default.
- **UPDATE path:** every COLUMN write uses the pattern
  ```sql
  col = COALESCE(NULLIF(col, ''), NULLIF(?, ''))
  ```
  except for `bill_to_name`, `country`, `last_wfirma_sync_at`,
  `wfirma_sync_source`, `updated_at` — those are always rewritten.

- Validation runs **before** any DB write: missing
  `bill_to_contractor_id`, `bill_to_name`, or `country` raises a clean
  `ValueError`. No dataclass `TypeError` can leak as HTTP 422.

### Test-level enforcement

`test_master_data_cm_wfirma_review.py` enforces:
1. **Parametrised preservation test** over three distinct client
   shapes (ALPHA / BETA / GAMMA, different countries, different
   field combinations). 21 commercial / settings fields verified
   byte-identical pre/post sync for every shape.
2. **Email-not-overwritten test:** an operator-entered
   `bill_to_email = "kept@local.example"` survives a wFirma sync that
   carries `email = "wfirma@remote.example"`.
3. **Mismatch surfacing test:** the preview endpoint surfaces a
   `mismatches[]` entry per drift field; apply NEVER overwrites.

---

## Resolver verdicts (closed set)

The wFirma fetch resolver emits exactly one of:

| Verdict | Meaning |
|---|---|
| `client_master` | Likely buyer — apply writes to customer_master |
| `supplier_master` | Likely exporter/vendor — apply writes to suppliers |
| `ignore` | Expense / carrier / tax office / etc. — never applied |
| `needs_operator_review` | Ambiguous — operator must change Assign-to before apply |

Apply rejects `ignore` and `needs_operator_review` rows even if the
operator explicitly requests them. Test:
`test_cm_apply_rejects_missing_country_gracefully`.

---

## Future-batch open items (NOT in scope of this doc)

These need explicit operator sign-off before implementation:

1. **Dictionary cache** — fetch `invoiceseries/find`,
   `proformaseries/find`, `languages/find` from wFirma and cache locally.
   Replaces the raw-ID inputs in the KYC Invoices Advanced disclosure
   with human-label dropdowns ("Standard EUR series", "English",
   "Reverse Charge (228)").
2. **vat_mode dictionary** — wFirma exposes VAT-mode codes in its
   documentation; we currently hardcode `222 / 228 / 229`. A future
   dictionary table would centralise the labels and enable extension.
3. **Currency dictionary** — currently hardcoded EUR / USD / PLN / GBP.
4. **Auto-deep-fetch on preview** — currently the per-row deep fetch
   happens only at apply time. A future optimisation could batch
   deep-fetch the proposals shown in the review panel so the operator
   sees payment_term / currency / series before clicking Save/Assign.
   Trade-off: 221 fetches per preview is slow; deep-fetch only the row
   the operator hovers over may be a better UX.
5. **Supplier deep-fetch** — `suppliers_db.sync_from_wfirma` currently
   uses the list-page enrichment only. A future symmetric deep-fetch
   would mirror the Client Master implementation.

---

## Related artefacts

- `service/app/services/customer_master_db.py` — `upsert_identity_only`
- `service/app/api/routes_customer_master.py` — `_cm_wfirma_proposals` + apply with deep-fetch
- `service/app/services/wfirma_client.py` — `WFirmaContractor`, `ContractorFetchResult`, `list_contractors_page`, `fetch_contractor_by_id`
- `service/app/services/suppliers_db.py` — supplier-side proposals + apply
- `service/tests/test_master_data_cm_wfirma_review.py` — full contract suite
- `tasks/client-master-surface-consolidation-plan.md` — UI consolidation plan (Option A, implemented in PR #150)
