# ADR-027: Proforma VAT + Document Defaults from customer_master (SSOT)

**Status:** Proposed
**Date:** 2026-06-01
**Deciders:** Amit
**Related:** ADR-023 (master data = SSOT), ADR-025 (E2E workflow),
docs/ATLAS_WORKFLOW_MAP.md §1D (WF2 VAT + document defaults)

---

## Context

A read-only audit of the proforma create → post → convert-to-invoice chain
(origin/main @ c09fdfa) revealed six compounding gaps that together produce the
PROF 92 WDT→23% class of error and cause document defaults to drift from
operator-set values.

### Audit findings

**G1 — Wrong VAT source:**
`routes_proforma.py:1218–1231` reads `wfirma_customers.country` and
`wfirma_customers.vat_id` (= NIP/tax-ID, NOT the EU VAT number) to decide
the VAT context. `customer_master.vat_eu_number` — the field that proves WDT
eligibility — is never consulted.

**G2 — VIES not checked:**
`customer_master.vat_eu_valid` is never read at VAT-decision time. WDT 0%
can be applied to a customer whose EU VAT number has not been VIES-verified.

**G3 — Operator override silently ignored:**
`customer_master.vat_mode` (operator-set numeric id, stored as an integer equal to
the wFirma account-specific vat_code id) is never read by `routes_proforma.py`.
The operator has no effective override.

**G4 — Decision not frozen; not shown before Post:**
The resolved `vat_code_id` is not stored in the draft. The decision is
re-derived at every post attempt from live `wfirma_customers`, which can
change silently between draft creation and posting. The pre-post
payload-disclosure modal does not surface the VAT treatment.

**G5 — Currency fallback not from SSOT:**
`customer_master.default_currency` exists but is not consistently used as
the proforma currency fallback when sale lines carry no currency.

**G6 — Document defaults drift:**
`payment_terms_days`, `default_language_id`, `preferred_proforma_series_id`,
`preferred_invoice_series_id` may be stored in `customer_master` by the
operator but are not reliably sent to wFirma at create/convert time —
wFirma silently applies its own contractor defaults instead.

**Root cause of the PROF 92 class:**
`decide_proforma_vat_context()` (`wfirma_client.py:1716`) returns `domestic`
(23%) when `customer_country == "PL"` for a non-PL EU customer — no error is
raised; 23% is silently applied. The verify-after-create gate catches codes
wFirma *changed* after receiving them, not codes *sent wrong from the start*
(sent == persisted → gate passes). The gate is insufficient as the sole control.

---

## Decision

Six locked sub-decisions covering VAT source, VAT resolution, VIES warning,
draft freeze, currency, and document defaults.

### D1 — Source authority: `customer_master` is the SSOT

All proforma VAT and document-default decisions are driven from `customer_master`.
`wfirma_customers` is a **last-resort read-only fallback** used only when
`customer_master` has no `country` AND `wfirma_customers` is also empty. No DB
write occurs on fallback; it fills only the in-flight decision.

**Fields owned by `customer_master` for WF2/WF3:**

| Field | Purpose | Source classification |
|---|---|---|
| `country` | D2 VAT derivation (primary) | wFirma-sync |
| `vat_eu_number` | D2 WDT eligibility | Operator |
| `vat_eu_valid` | D3 VIES warning trigger | VIES result |
| `vat_mode` | D2 operator VAT override | Operator |
| `default_currency` | D5 currency fallback | Operator |
| `payment_terms_days` | D6 payment terms | Operator |
| `preferred_payment_method` | D6 payment method | Operator |
| `default_language_id` | D6 language | Operator |
| `preferred_proforma_series_id` | D6 proforma series | Operator |
| `preferred_invoice_series_id` | D6 invoice series (WF3) | Operator |

### D2 — VAT resolution order (one context per proforma)

**Priority 1 — Operator vat_mode override (wins everything):**

`customer_master.vat_mode` stores a **numeric integer** equal to the wFirma
account-specific `vat_code` id for this installation. The resolver
(`_VMODE_TO_CONTEXT` in `wfirma_client.py`) maps the stored integer directly to
`(context, code_string)`. The UI layer maps the operator's display label ("EU
Reverse Charge", "Export", etc.) to the stored integer before writing; the backend
sees only the integer. **Any integer without a `_VMODE_TO_CONTEXT` entry raises
`ValueError` — block the draft, never guess.**

> **Schema note:** `upsert_customer` (`customer_master_db.py:222`) currently
> validates `vat_mode ∈ {222, 228, 229}` only. Values marked † in the table are
> handled by the resolver but require a schema extension or direct DB write to store.

| Stored `vat_mode` (int) | UI display label (reference) | Resolved context | Frozen code string | `vat_codes/find` id |
|---|---|---|---|---|
| `222` | "Domestic / Standard 23%" | `domestic` | `23` | 222 |
| `228` | "EU Reverse Charge (WDT)" | `wdt` | `WDT` | 228 |
| `229` | "Export" | `export` | `EXP` | 229 |
| `230`† | "NP" | `np` | `NP` | 230 |
| `231`† | "NP-UE" | `npue` | `NPUE` | 231 |
| `233`† | "Zwolniony (ZW)" | `zw` | `ZW` | 233 |
| `234`† | "0%" | `zero` | `0` | 234 |
| Any other int | — | **ERROR — block post** | — | — |

The `vat_codes/find` id column shows this account's mapping. That id is resolved
**live at post time** and **never persisted** — only the context string and code
string are frozen in the draft (preventing stale-id bugs across wFirma account
migrations).

**Priority 2 — Derived from country + vat_eu_number (when vat_mode null/unset):**

| Condition | Resolved context | Frozen code | Notes |
|---|---|---|---|
| `country == "PL"` | `domestic` | `23` | |
| `country ∈ EU-27` AND `vat_eu_number` set | `wdt` | `WDT` | |
| `country ∈ EU-27` AND `vat_eu_number` empty | `wdt-intent` (FLAGGED) | `WDT` | D3 warning fires |
| `country ∉ EU-27` | `export` | `EXP` | |
| `country` empty → fallback to `wfirma_customers` → still empty | **BLOCKED** | — | ValueError; do not post |

**Locked code → wFirma account-specific numeric id (resolved LIVE at post only):**

| Code string | wFirma `<code>` field | Numeric id (this account) |
|---|---|---|
| `23` | `23` | 222 |
| `WDT` | `WDT` | 228 |
| `EXP` | `EXP` | 229 |
| `NP` | `NP` | 230 |
| `NPUE` | `NPUE` | 231 |
| `ZW` | `ZW` | 233 |
| `0` | `0` | 234 |

Only the **context string** and **code string** are frozen in the draft. The
numeric id is resolved live via `vat_codes/find` at post time (cached in-process),
preventing stale-id bugs across wFirma account migrations.

### D3 — VIES warning (NOT a block)

When resolved context is `wdt` and `customer_master.vat_eu_valid` is NOT `True`
(missing, unverified, or explicitly invalid):

1. A **WARNING** is emitted in the pre-post payload-disclosure modal.
2. A **`vies_unverified` Inbox advisory** is written to audit.json.
3. Operator may **acknowledge-and-proceed** — no hard block.
4. System does **NOT silently downgrade** to domestic (23%).
5. Operator owns the legal call; can override via `vat_mode` if needed.

Rationale for warn-not-block: hard blocks jam live shipments and stop
end-to-end testing. The operator must be informed and explicitly decide.

### D4 — Freeze and disclose

**At draft creation (WF2.3)**, store in `proforma_draft`:

| Draft field | What is stored |
|---|---|
| `vat_context` | `"domestic"` / `"wdt"` / `"export"` / `"np"` / `"npue"` / `"zw"` / `"zero"` |
| `vat_code` | Code string (e.g. `"WDT"`, `"23"`) — NOT the numeric id |
| `decision_source` | `"operator_vat_mode"` \| `"derived"` \| `"fallback_wfirma"` |

**In the payload-disclosure modal (before WF2.4 Post):**
- All three frozen fields are surfaced to the operator.
- The endpoint re-resolves the VAT context at disclosure time and **compares to
  frozen values**; a **DRIFT WARNING** fires if they differ (e.g., customer's
  country was corrected between draft creation and posting).
- Operator must acknowledge any warnings before post proceeds.

**At post (WF2.4):** numeric `vat_code_id` is resolved live from the frozen code
string via the D2 locked map and sent in the XML. Verify-after-create gate is
retained unchanged (defence-in-depth).

### D5 — Currency

- **Proforma currency** = dominant currency of the sale lines being included.
- **Fallback**: `customer_master.default_currency` when lines carry no currency.
- **Mismatch warning**: if the resolved currency differs from
  `customer_master.default_currency`, a WARN is logged and surfaced in the
  disclosure modal (not a block — sale-line authority wins).
- Currency is **not** frozen in the draft; it is re-derived at post from
  current sale-line state.

### D6 — Document defaults sent to wFirma

On proforma create (WF2.4), include the following `customer_master` fields in the
wFirma XML, **overriding** whatever wFirma would infer from its own contractor record:

| customer\_master field | wFirma XML element | Behaviour when null |
|---|---|---|
| `payment_terms_days` | `<paymentdays>` | Omit — let wFirma use contractor default |
| `preferred_payment_method` | `<paymentmethod>` | Omit |
| `default_language_id` | `<lang>` | Omit |
| `preferred_proforma_series_id` | `<series><id>` | Omit |

On **convert-to-invoice** (WF3):

| customer\_master field | wFirma XML element | Behaviour when null |
|---|---|---|
| `preferred_invoice_series_id` | `<series><id>` | Omit — let wFirma use default |

**Rule**: if a field is null in `customer_master`, the XML element is **omitted**
entirely — no hardcoded fallback, no guessing. wFirma uses its own contractor default
for missing elements.

---

## Full field map: customer\_master → proforma\_draft → wFirma post

| customer\_master field | Source classification | Old source | Post-ADR-027 role | Frozen in draft? | Sent to wFirma? |
|---|---|---|---|---|---|
| `country` | wFirma-sync | `wfirma_customers.country` | **Primary D2 VAT input** | No | No |
| `vat_eu_number` | Operator | **Not consulted** | **D2 WDT eligibility** | No | No |
| `vat_eu_valid` | VIES result | **Not consulted** | **D3 VIES warning trigger** | No | No |
| `vat_mode` | Operator | **Not consulted** | **D2 override — wins all derived logic** | No (→ `decision_source`) | No |
| `nip` | wFirma-sync | `wfirma_customers.vat_id` | D2 fallback (last resort, read-only) | No | No |
| `default_currency` | Operator | Partial | D5 currency fallback | No | No (sale-line authority) |
| `payment_terms_days` | Operator | wFirma contractor default | D6 → `<paymentdays>` | No (read at post) | **Yes** (if set) |
| `preferred_payment_method` | Operator | customer\_master ✓ | D6 → `<paymentmethod>` | No (read at post) | **Yes** (if set) |
| `default_language_id` | Operator | **Not sent** | D6 → `<lang>` | No (read at post) | **Yes** (if set) |
| `preferred_proforma_series_id` | Operator | customer\_master ✓ | D6 → `<series><id>` (proforma) | No (read at post) | **Yes** (if set) |
| `preferred_invoice_series_id` | Operator | **Not sent** | D6 → `<series><id>` (invoice, WF3) | No (read at convert) | **Yes** at WF3 (if set) |
| **`vat_context`** (NEW draft field) | — | N/A | Frozen resolved context | **Yes** | No |
| **`vat_code`** (NEW draft field) | — | N/A | Frozen code string (not numeric) | **Yes** | No (id live at post) |
| **`decision_source`** (NEW draft field) | — | N/A | Provenance of the decision | **Yes** | No |
| `vat_code_id` (numeric, in-process) | — | Live `vat_codes/find` (unchanged) | Account-specific id resolved at post | **No** | Yes (`<vat_code><id>`) |

---

## Why verify-after-create is insufficient as the sole control

`create_proforma_draft()` (`wfirma_client.py:1625–1681`) fetches the created proforma
back and checks that each line's persisted `vat_code.id` matches `req.vat_code_id`.
This catches codes that **wFirma changed** after receiving them.

It does **not** catch a code **sent wrong from the start**: if `req.vat_code_id = 222`
(domestic 23%) was sent for a WDT customer, the persisted value is 222, the check
compares 222 == 222, and passes. D1–D4 ensure the correct code is sent. The gate
is retained unchanged as a defence-in-depth layer.

---

## Options considered

### Option A — Fix VAT source only (D1, no freeze or defaults)
Reads `customer_master` but doesn't freeze, surface, or send document defaults.

**Rejected:** G4–G6 remain open; operator cannot verify treatment before Post;
drift can still occur silently; document defaults still drift.

### Option B — Fix VAT source + freeze numeric id (D1+D4 with numeric id stored)
Freeze the account-specific numeric id (222/228/229) into the draft.

**Rejected:** numeric ids are account-specific and can change if wFirma migrates.
Freezing the id would produce stale-id bugs after a wFirma account change. The
code string is stable across accounts; live resolution at post is safer.

### Option C — Fix VAT + freeze code string + vat_mode numeric id mapping + disclose
D1+D2+D3+D4 as specified.

**Rejected as partial:** G5 (currency) and G6 (document defaults) left open.

### Option D (chosen) — Full D1–D6
All six decisions. Operator has full visibility of VAT treatment and document
defaults; no hard blocks; wFirma account-specific ids resolved live; currency and
terms driven from SSOT; vat_mode numeric id→context mapping is explicit and errors
on unknown integers.

---

## Invariants preserved

- `WFIRMA_CREATE_PROFORMA_ALLOWED` gate unchanged.
- `WFIRMA_CREATE_INVOICE_ALLOWED` gate unchanged.
- `wfirma_client.create_proforma_draft()` interface unchanged (callers pass a
  `ProformaRequest` with `vat_code_id`; the resolution of what to put there changes).
- Verify-after-create gate unchanged and retained.
- wFirma mocked in all tests; no live writes in dev.
- No new feature flag — D1–D6 are correctness fixes behind the existing flags.
- Operator-set `vat_mode` wins as an override; operator retains full control.
- For fields null in `customer_master`, no hardcoded fallback — wFirma contractor
  default applies (omit the XML element, do not substitute).

---

## Consequences

- **Easier:** PROF 92 class prevented at source; document defaults respect
  operator configuration; operator can see and verify VAT treatment before Post.
- **Harder:** three new columns on `proforma_drafts` (additive migration);
  `_build_proforma_request` and `_build_proforma_request_from_draft` updated;
  vat_mode numeric id→context mapping (`_VMODE_TO_CONTEXT`) added to the service
  layer; D6 fields wired into the XML builder.
- **Revisit:** whether `vat_eu_valid` should become a hard block (current
  decision: warn-not-block; revisit if legal risk materialises).
- **Remaining gap:** `default_language_id` was previously not sent; wFirma uses
  its own contractor language default for missing elements — addressed by D6.

---

## Action items — implementation status

> Items 1–9 were implemented in `feat/wf2-vat-from-master` (HEAD 7a2e621).
> Items 5 and 6 are partially done — backend returns the data; modal wiring and
> inbox advisory are deferred to the post-#418 reconcile (Steps 1–3).

1. [x] Add `vat_context TEXT`, `vat_code TEXT`, `decision_source TEXT` to
       `proforma_drafts` (additive migration, nullable). **DONE** (`proforma_invoice_link_db.py`).
2. [x] New `resolve_vat_context_from_master(cm_row)` implementing D2 resolution
       (Priority 1: numeric id via `_VMODE_TO_CONTEXT` → Priority 2: derived →
       fallback → BLOCKED). Unknown vat_mode int → `ValueError`. **DONE** (`wfirma_client.py`).
3. [x] Update `_build_proforma_request()` and `_build_proforma_request_from_draft()`
       to call `resolve_vat_context_from_master`. **DONE** (`routes_proforma.py`).
4. [x] Freeze `vat_context`, `vat_code`, `decision_source` into draft after
       `start_post` (avoids optimistic-lock conflict). **DONE** (`routes_proforma.py`
       + `freeze_draft_vat_context()` in `proforma_invoice_link_db.py`).
5. [ ] Update payload-disclosure modal to surface frozen VAT fields and re-resolve;
       emit DRIFT WARNING on mismatch. **DEFERRED** — backend already returns the
       fields; modal wiring awaits #418 B5 post-merge reconcile.
6. [ ] Emit `vies_unverified` Inbox advisory when D3 condition fires. **DEFERRED**
       — backend returns warning in `vat_warnings[]`; advisory write awaits #418
       B2 helper post-merge reconcile.
7. [x] D5 currency: draft currency vs `customer_master.default_currency`; mismatch
       → `"currency_mismatch"` in `vat_warnings[]`. **DONE** (`routes_proforma.py`).
8. [x] D6 document defaults in WF2.4 XML: `<paymentdays>` `<paymentmethod>`
       `<translation_language>` `<series><id>` — all four sent when set, omitted when
       null. **DONE** (`wfirma_client.py`; `preferred_invoice_series_id` at WF3 noted).
9. [x] Tests: 22 tests (U1-U11 + I1-I11), wFirma mocked, all green. **DONE**
       (`test_adr027_vat_from_master.py`).
       warning on context change between creation and post; D6 fields appear in
       XML when set; D6 fields absent from XML when null.
