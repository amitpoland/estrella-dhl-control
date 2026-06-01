# ADR-027: Proforma VAT Resolution from customer_master (SSOT)

**Status:** Proposed
**Date:** 2026-06-01
**Deciders:** Amit
**Related:** ADR-023 (master data = SSOT), ADR-025 (E2E workflow),
docs/ATLAS_WORKFLOW_MAP.md §1D (WF2 VAT resolution)

---

## Context

A read-only audit of the proforma create → post → invoice chain revealed four
compounding gaps that together produce the PROF 92 WDT→23% class of error — a
proforma issued with domestic 23% VAT when the customer should have been WDT 0%.

### Audit findings (file:line on origin/main @ c09fdfa)

**G1 — Wrong VAT source:**
`routes_proforma.py:1218–1231` reads `wfirma_customers.country` and
`wfirma_customers.vat_id` (= NIP/tax-ID, NOT the EU VAT number) to decide
the VAT context. `customer_master.vat_eu_number` — the field that proves WDT
eligibility — is never consulted. For EU non-PL customers whose EU VAT number
is stored in `customer_master.vat_eu_number` but not in wFirma's NIP field,
the WDT determination may be silently wrong.

**G2 — VIES not checked:**
`customer_master.vat_eu_valid` is never read. WDT 0% can be applied to a
customer whose EU VAT number has not been VIES-verified.

**G3 — Operator override silently ignored:**
`customer_master.vat_mode` (222/228/229) is stored by the operator and shown
in the customer invoice tab UI, but `routes_proforma.py` never reads it. The
operator has no way to override the VAT context.

**G4 — Decision not frozen; not shown before Post:**
The resolved `vat_code_id` is not stored in the draft. The decision is
re-resolved at every post attempt from live `wfirma_customers` state, which
can change silently between draft creation and posting. The pre-post
payload-disclosure modal (`payload_disclosure.py`) does not surface the VAT
context, so the operator cannot verify the treatment before clicking Post.

**Root cause of the PROF 92 class:**
`decide_proforma_vat_context()` (`wfirma_client.py:1716`) returns `domestic`
(23%) when `customer_country == "PL"` for a non-PL EU customer — **no error
is raised; 23% is silently applied**. The verify-after-create gate
(`wfirma_client.py:1658`) catches codes that **wFirma changed** after
receiving them, not codes **sent wrong from the start** (sent == persisted →
gate passes). This makes the gate insufficient as the sole control.

---

## Decision

Fix the VAT decision source, freeze the resolved context, surface it in the
pre-post disclosure, and add a VIES warning — in four locked sub-decisions.

### D1 — VAT decision from `customer_master` (SSOT)

The VAT decision reads `customer_master` fields (`country`, `vat_eu_number`,
`vat_eu_valid`, `vat_mode`). The `wfirma_customers` mirror (`vat_id`,
`country`) becomes a **last-resort read-only fallback** used only when
`customer_master` has no `country` AND `wfirma_customers` is also empty.
No DB write occurs on fallback.

**Old path (replaced):**
```
wfirma_customers.country + wfirma_customers.vat_id
  → decide_proforma_vat_context() → vat_code_id
```

**New path:**
```
customer_master.country + customer_master.vat_eu_number + vat_eu_valid + vat_mode
  [fallback: wfirma_customers or live search_customer if cm.country empty]
  → resolve_vat_context_from_master() → (context, code)
  → live vat_codes/find() → vat_code_id (at post only)
```

### D2 — Resolution order

One VAT context per proforma, resolved in this strict priority order:

1. **Operator override:** `customer_master.vat_mode` is set (non-null) →
   interpret as context:
   `vat_mode=222` → `domestic` · `vat_mode=228` → `wdt` · `vat_mode=229` → `export`

2. **Derived from country + EU VAT:**
   - `country == "PL"` → `domestic` (code `"23"`)
   - `country ∈ EU-27` AND `vat_eu_number` set → `wdt` (code `"WDT"`)
   - `country ∈ EU-27` AND `vat_eu_number` empty → `wdt-intent` (FLAGGED; code
     `"WDT"` with D3 warning emitted)
   - `country ∉ EU-27` → `export` (code `"EXP"`)

3. **Fallback (last resort):** `customer_master.country` empty → read
   `wfirma_customers.country` + `wfirma_customers.vat_id`; if still empty →
   live `search_customer` (read-only); if all fail → `BLOCKED` (ValueError,
   post prevented).

**Locked code → wFirma account-specific numeric id (resolved live at post):**

| Code string | wFirma `<code>` field | Numeric id (this account) |
|---|---|---|
| `23` | `23` | 222 |
| `WDT` | `WDT` | 228 |
| `EXP` | `EXP` | 229 |
| `NP` | `NP` | 230 |
| `NPUE` | `NPUE` | 231 |
| `ZW` | `ZW` | 233 |
| `0` | `0` | 234 |

Only the **code string** is frozen in the draft. The numeric id is resolved
live at post via `vat_codes/find` (cached in-process), preventing stale-id
bugs across wFirma account migrations.

### D3 — VIES warning (NOT a block)

When resolved context is `wdt` and `customer_master.vat_eu_valid` is NOT
`True` (missing / unverified / invalid):

1. A **WARNING** is emitted in the pre-post payload-disclosure modal.
2. A **`vies_unverified` Inbox advisory proposal** is written to audit.json.
3. Operator may **acknowledge-and-proceed** — no hard block.
4. System does **NOT silently downgrade** to domestic (23%).
5. Operator owns the legal call; can override via `vat_mode` if needed.

Rationale for warn-not-block: hard blocks jam live shipments and stop
end-to-end testing. The operator must be informed of the risk and must
explicitly decide.

### D4 — Freeze and disclose

**At draft creation (WF2.3)**, store in `proforma_draft`:
- `vat_context`: `"domestic"` / `"wdt"` / `"export"`
- `vat_code`: `"23"` / `"WDT"` / `"EXP"` (code string, NOT numeric id)
- `decision_source`: `"operator_vat_mode"` | `"derived"` | `"fallback_wfirma"`

**In the payload-disclosure modal (before WF2.4 Post):**
- All three frozen fields are shown.
- The modal re-resolves the VAT context at disclosure time and **compares to
  frozen values**; a DRIFT WARNING is shown if they differ.

**At post (WF2.4):** numeric `vat_code_id` is resolved live from the code
string and sent. Verify-after-create gate is retained unchanged (defence-in-
depth for codes changed by wFirma after receipt).

---

## Field map: customer\_master → proforma\_draft → wFirma post

| customer\_master field | Pre-ADR-027 source | Post-ADR-027 role | Stored in draft? | Sent to wFirma? |
|---|---|---|---|---|
| `country` | `wfirma_customers.country` | **Primary D2 input** | No (used at creation) | No |
| `vat_eu_number` | **Not consulted** | **Primary D2 WDT input** | No | No |
| `vat_eu_valid` | **Not consulted** | D3 VIES warning trigger | No | No |
| `vat_mode` | **Not consulted** | D2 operator override (wins) | No (→ `decision_source`) | No |
| `nip` | `wfirma_customers.vat_id` | Fallback only | No | No |
| `preferred_proforma_series_id` | customer\_master ✓ | Unchanged — series | No (read at post) | Yes (`<series><id>`) |
| `preferred_payment_method` | customer\_master ✓ | Unchanged — payment method | No (read at post) | Yes (`<paymentmethod>`) |
| `default_language_id` | Not sent | Unchanged — gap | No | No (wFirma uses own default) |
| **`vat_context`** (NEW draft field) | N/A | Frozen resolved context | **Yes** | No |
| **`vat_code`** (NEW draft field) | N/A | Frozen code string | **Yes** | No (id resolved live) |
| **`decision_source`** (NEW draft field) | N/A | Provenance of decision | **Yes** | No |
| `vat_code_id` (numeric, in-process) | `vat_codes/find` live ✓ | Unchanged — resolved at post | **No** | Yes (`<vat_code><id>`) |

**wFirma post payload — unchanged fields** (wFirma fills from its own contractor record):
- Customer billing address (from `<contractor><id>`)
- Customer language / payment days

---

## Why verify-after-create is insufficient as the sole control

`create_proforma_draft()` (`wfirma_client.py:1625–1681`) fetches the created
proforma back and checks that every line's persisted `vat_code.id` matches
`req.vat_code_id`. This catches codes that **wFirma changed** after receiving
them (e.g., wFirma ignores the sent code and uses a product default).

It does **not** catch a code that was **sent wrong from the start**: if
`req.vat_code_id = 222` (domestic 23%) was sent for a WDT customer, the
persisted value is 222, the check compares 222 == 222, and passes.

D1–D4 ensure the correct code is sent. The verify-after-create gate is
retained unchanged as a defence-in-depth layer for codes changed by wFirma.

---

## Options considered

### Option A — Fix source only (D1, no freeze)
Reads `customer_master` but doesn't freeze or disclose. Same blind-spot: the
operator still can't verify the VAT treatment before clicking Post, and the
decision can drift silently between draft creation and posting.

**Rejected:** incomplete. D4 freeze+disclose is required to close the loop.

### Option B — Freeze numeric id (store 222/228/229 in draft)
Freeze the account-specific numeric id instead of the code string.

**Rejected:** numeric ids are account-specific and can change if wFirma
migrates. Freezing the account-specific id would produce stale-id bugs after
a wFirma account change. The code string (`"WDT"`, `"23"`) is stable across
accounts; the numeric resolution stays live.

### Option C (chosen) — Fix source + freeze code string + disclose + warn
Implements D1–D4 as specified. Operator has full visibility; no hard blocks;
wFirma account-specific id resolved live at post.

---

## Invariants preserved

- `WFIRMA_CREATE_PROFORMA_ALLOWED` flag gate unchanged.
- `wfirma_client.create_proforma_draft()` interface unchanged (callers still
  pass a `ProformaRequest` with `vat_code_id`).
- Verify-after-create gate unchanged and retained.
- wFirma mocked in all tests; no live writes in dev.
- No new feature flag introduced — this is a correctness fix under the
  existing flag.
- Operator-set `vat_mode` wins as an override; operator retains full control.

---

## Consequences

- **Easier:** VAT treatment is visible to the operator before posting; PROF
  92 class of error is prevented at source.
- **Harder:** three new fields on `proforma_draft` (additive migration);
  `_build_proforma_request` and `_build_proforma_request_from_draft` must
  be updated to read `customer_master` instead of `wfirma_customers`.
- **Revisit:** whether `vat_eu_valid` should ever become a hard block
  (current decision: warn-not-block; revisit if legal risk materialises).
- **Remaining gap (D4, docs-only):** `default_language_id` is not sent to
  wFirma; wFirma uses its own contractor language default. This is a
  separate gap, not addressed in this ADR.

## Action items (implementation — separate PR, WF2 track)

1. [ ] Add `vat_context TEXT`, `vat_code TEXT`, `decision_source TEXT` columns
       to `proforma_drafts` (additive migration, nullable).
2. [ ] New service function `resolve_vat_context_from_master(customer_master_row)`
       implementing D2 resolution order, returning `(context, code, source)`.
3. [ ] Update `_build_proforma_request()` and `_build_proforma_request_from_draft()`
       to call `resolve_vat_context_from_master` instead of
       `decide_proforma_vat_context(wfirma_customers.country, wfirma_customers.vat_id)`.
4. [ ] Freeze resolved fields into draft at creation (WF2.3).
5. [ ] Update `payload_disclosure.build_proforma_post_disclosure()` to surface
       `vat_context`, `vat_code`, `decision_source`.
6. [ ] Add drift comparison at disclosure time; emit DRIFT WARNING if re-resolved
       context differs from frozen.
7. [ ] Emit `vies_unverified` Inbox advisory when D3 condition fires.
8. [ ] Tests: wFirma mocked; `customer_master.vat_eu_number` drives WDT
       decision; `vat_mode` override wins; VIES warning on `vat_eu_valid=False`;
       drift warning on context change between creation and post.
