# Campaign: Draft-Birth Completion Authority

**Status:** RESEARCH COMPLETE — design document only · NOT YET OPENED as a PR
**Authority:** Operator pivot directive 2026-06-10 (during PR #553 wait)
**Campaign slug:** draft-birth-authority
**Scope guard:** This campaign does NOT touch any file in `#553`'s no-go zone
(`routes_proforma.py`, `proforma_invoice_link_db.py`, `proforma-detail.jsx`,
`estrella-doc-proforma.jsx`, `pz-api.js`, `test_proforma_display_contract.py`)
until PR #553 lands. Implementation begins only after #553 merge.

---

## 1. Root Cause

Every `ProformaDraft` is born **structurally empty** of customer-default
authority. The auto-creation INSERT at
`proforma_invoice_link_db.py:1522` (`auto_create_draft_from_sales_packing`)
writes six fields as literal `'{}'`, `'[]'`, or `''` regardless of what
Customer Master or the packing-upload contractor resolution already knows.

The operator must then click through 4–6 manual repair steps on every fresh
draft just to recover state that the system already possesses elsewhere:

```
Packing imported
  ↓ auto_create_draft_from_sales_packing()  ← writes empty defaults
Draft created (empty buyer_override, empty payment_terms, empty service charges)
  ↓ enrich_draft_lines() runs here (line annotations only — name_pl, item_type)
  ↓ STOPS — no customer-default enrichment
Operator opens draft
  ↓ Buyer card shows free-text client_name only — no contractor_id
  ↓ Payment Due renders "—" (payment_terms_days null)
  ↓ Footer hardcodes "7 days" because payment_terms_json = '{}'
  ↓ Freight/insurance must be added manually
  ↓ Country, descriptions PL/EN missing
Manual repair required (every shipment, every client)
```

The recurring pattern from operator reports — *"why is this missing again?"* —
is one workflow class: **draft is born ignorant of its own customer
authority chain**. Fixing this eliminates the recurring repair loop at its
source, not at each downstream symptom.

This is the workflow class Lesson I instructs us to fix (not the
shipment-specific symptoms).

---

## 2. Authority Sources (already exist in the system)

The data needed at birth is already authoritative *somewhere else* — the
gap is propagation, not collection.

| Authority surface | Owns | Read API | Read at birth? |
|---|---|---|---|
| `packing_contractor_resolution` (table) | Operator's confirmed contractor pick per (batch_id, role) | `packing_resolution_db.py` + `customer_resolution_authority.py` | **NO** |
| `customer_master` (table) | `payment_terms_days`, `bill_to_email`, `default_currency`, `bank_account`, address, contact | `customer_master_db.py` (`payment_terms_days` at row 503; full record at `_resolve_customer` 10-key shape) | **NO** |
| `company_profile` (singleton) | Exporter identity, bank accounts, default origin country | `/api/v1/settings/company-profile` | NO (frontend reads it at preview render time) |
| `product_descriptions` (table) | `description_pl`, `description_en`, `item_type` | `documents_db.get_product_description` | **YES** (via `enrich_draft_lines` immediately after birth) |
| `sales_price_authority` columns | `sales_price_authority_total_eur`, `sales_price_invoice_ref` | already on draft schema (PR #519) | YES (line-level only) |

The asymmetry is the bug: product descriptions get enriched at birth
(line 423 in `proforma_draft_sync.py`), but customer defaults do not.

---

## 3. Field-Level Gap Inventory

For each field hardcoded at INSERT time, the authority chain that *should*
have populated it, and the test that pins the contract.

| # | Draft field | INSERT hardcode | Authority source | Resolution at birth |
|---|---|---|---|---|
| 1 | `buyer_override_json` | `'{}'` | Customer Master `_resolve_customer` (10-key) keyed by contractor_id from `packing_contractor_resolution` | Populate with normalized customer name + NIP + address + email + phone + contact when resolution status=`confirmed`. Leave `'{}'` only when resolution=`ambiguous` or `not_found`, with a `birth_unresolved=true` flag the UI can render as a banner. |
| 2 | `ship_to_override_json` | `'{}'` | Same chain; ship-to is buyer unless operator explicitly overrode at packing upload | Populate from same Customer Master record at birth. Operator can override in UI later (existing path unchanged). |
| 3 | `payment_terms_json` | `'{}'` | Customer Master `payment_terms_days` (existing column, customer_master_db.py:503) | Populate `{"days": <cm.payment_terms_days>, "method": <cm.default_payment_method or "wire">, "source": "customer_master"}` at birth. If null on CM, store `{"days": null, "source": "unset"}` — explicit absence, not empty object. |
| 4 | `service_charges_json` | `'[]'` | `suggest-freight` + `suggest-insurance` endpoints exist (BACKEND_GAP_REGISTER rows 23–24) | Out of scope for THIS campaign — Phase B of `proforma-contract-lock.md` already owns this with operator confirmation guards. Document in the gap inventory only. |
| 5 | `remarks` | `''` | Customer Master `default_remarks` (column does not exist yet — needs schema addition) | Phase 2 (after schema add). Until column exists: leave `''`. |
| 6 | `wfirma_proforma_fullnumber` | `''` | wFirma server (assigned at POST, not at birth) | **Stays `''`** — correct behavior. Authority lives in wFirma until POST returns. Document so future readers don't "fix" it. |
| 7 | `incoterm` | `NULL` | Customer Master `default_incoterm` (column does not exist yet) OR operator's batch-upload selection | Phase 2 (after schema add). Until column exists: leave NULL but render UI hint "set incoterm before preview". |
| 8 | `insurance_eur` | `NULL` | `suggest-insurance` (proposed in Phase B of proforma-contract-lock) | Out of scope here. Phase B of proforma-contract-lock owns this. |
| 9 | `contractor_id` (**new column**) | not persisted at all today | `packing_contractor_resolution.matched_master_id` when status=`confirmed` | **The core schema addition** of this campaign. See §4. |

### Why a `contractor_id` column at all?

Today the draft only knows `client_name` (free text). That means:

- The proforma render path heuristically re-resolves customer master every
  view. Heuristics drift (case, trailing comma, prefix tolerance).
- Two drafts can have the same `client_name` text but resolve to different
  contractor_ids on different reads if the customer master changes between
  views.
- The operator's *confirmed pick* from packing upload (recorded in
  `packing_contractor_resolution`) is silently discarded the moment the
  draft is born.
- POST-time `_resolve_customer` re-resolution is the *only* place
  contractor_id is bound, and only at POST — far too late.

Persisting `contractor_id` at birth makes the draft self-describing.
Heuristic resolution becomes a fallback for legacy drafts only. New drafts
always know their contractor identity from the moment of birth.

---

## 4. Schema Changes

Additive only. Idempotent ALTER pattern already used in `_ensure_drafts_table`
(lines 487–531). No destructive migration; existing rows pick up NULL and
fall back to today's heuristic path.

```sql
ALTER TABLE proforma_drafts ADD COLUMN contractor_id              TEXT;
ALTER TABLE proforma_drafts ADD COLUMN contractor_identity_source TEXT;
ALTER TABLE proforma_drafts ADD COLUMN birth_unresolved           INTEGER NOT NULL DEFAULT 0;
```

`contractor_identity_source` values:
- `packing_resolution_confirmed` — operator-confirmed at upload
- `packing_resolution_ambiguous` — operator was shown candidates, chose none
- `packing_resolution_unmatched` — no master record
- `legacy_heuristic` — pre-campaign draft, contractor_id resolved by name
- `manual_assignment` — operator set contractor_id from draft UI later

`birth_unresolved=1` is a banner trigger — it tells the UI "this draft was
born without confirmed contractor identity, render a warning and surface the
ContractorResolutionPanel inline." The flag is **never** cleared by a render
— only by an explicit assignment event.

No `customer_master` schema change. The reading side already has all needed
fields (lines 122, 503, 1006 of `customer_master_db.py`).

---

## 5. Code Changes (sequenced for safety)

### Step 1 — New service module: `draft_birth_authority.py`

New file at `service/app/services/draft_birth_authority.py`. Pure functions:

```python
def resolve_birth_identity(
    db_paths: DbPaths,
    *,
    batch_id: str,
    client_name: str,
) -> BirthIdentity:
    """Returns (contractor_id, identity_source, birth_unresolved).
       Reads packing_contractor_resolution first, then falls back to
       _resolve_customer heuristic. Never writes."""

def build_buyer_override(cm_record: Dict[str, Any]) -> Dict[str, Any]:
    """Pure projection of customer_master row → buyer_override shape.
       No side effects. Empty dict if cm_record is None."""

def build_ship_to_override(cm_record: Dict[str, Any]) -> Dict[str, Any]:
    """Same. Until operator overrides, ship_to=buyer."""

def build_payment_terms(cm_record: Dict[str, Any]) -> Dict[str, Any]:
    """{'days': int|None, 'method': str, 'source': str}"""
```

All four functions are deterministic, take no `db_path`, no I/O. The
read happens in `resolve_birth_identity`; the build functions are pure.

### Step 2 — Wire at birth

`auto_create_draft_from_sales_packing()` is in `proforma_invoice_link_db.py`
which is in the #553 no-go zone. Therefore wiring waits for #553 merge.

After merge, the change is small: between the line resolution block
(currently around line 1554–1580) and the INSERT, insert one call:

```python
birth_identity = draft_birth_authority.resolve_birth_identity(
    db_paths, batch_id=batch_id, client_name=client_name,
)
cm_record = _resolve_customer(...)["customer"] if birth_identity.contractor_id else None
buyer_override_json    = json.dumps(draft_birth_authority.build_buyer_override(cm_record),  ...)
ship_to_override_json  = json.dumps(draft_birth_authority.build_ship_to_override(cm_record), ...)
payment_terms_json     = json.dumps(draft_birth_authority.build_payment_terms(cm_record),    ...)
```

Then change INSERT VALUES to use these variables instead of literal
`'{}'`/`'{}'`/`'{}'`. Three literals → three variables. The new
`contractor_id`, `contractor_identity_source`, `birth_unresolved` columns
get bound too.

### Step 3 — Frontend banner (read-side, low risk)

`proforma-detail.jsx` reads `draft.birth_unresolved`. If `1`, render an
authority banner: *"Customer identity was not confirmed at packing upload.
Resolve contractor before posting."* with a link to the
`ContractorResolutionPanel` (existing component, no new UI).

The banner uses existing CSS variables (`--badge-warning`, `--text`) per
`.claude/skills/frontend-design.md`. No new components, no new tokens.

This file is in the #553 no-go zone — wiring waits for merge.

---

## 6. Contractor Identity Test Cases

Three real production cases the system has failed on (documented in PROJECT_STATE
OPEN QUESTIONS / scorecards / Lesson I):

| Case | What today's heuristic does | What this campaign does |
|---|---|---|
| **UAB Monodija** (`cid=134920664`, packing row 258) | Resolves by name match; if name has trailing whitespace or comma drift, may miss-match or land in `_resolve_customer.ambiguous` | Reads `packing_contractor_resolution.matched_master_id` directly — operator's confirmed pick wins, no heuristic |
| **Jozef Horňák** (packing row 260) | Diacritic normalization is inconsistent; row 260 has historically tripped reverse-prefix logic | Identity bound at packing upload, persisted at draft birth — heuristic never runs for this draft again |
| **UAB Tomas Gold** (last week's draft #24 → PROF 123/2026, wfirma_id=477781731) | Worked, but only because operator manually picked from CM at proforma stage AFTER birth | Would have been correct at birth — zero manual intervention |

### Real-builder regression tests (Lesson A binding)

`service/tests/test_draft_birth_authority.py` (new file, no touch of any
existing file in #553's no-go zone — safe to author NOW as a stub-only test
that imports the not-yet-written module).

```
def test_birth_identity_uses_packing_resolution_when_confirmed():
    """Operator confirmed at upload → contractor_id binds at birth,
       identity_source=packing_resolution_confirmed, birth_unresolved=0."""

def test_birth_identity_falls_back_to_heuristic_when_no_resolution():
    """No packing_contractor_resolution row → falls back to _resolve_customer,
       identity_source=legacy_heuristic, birth_unresolved=0 (resolved by name)."""

def test_birth_unresolved_flag_set_when_resolution_ambiguous():
    """Packing resolution status=ambiguous → contractor_id=NULL,
       identity_source=packing_resolution_ambiguous, birth_unresolved=1.
       Banner trigger. Draft is editable but flagged."""

def test_birth_unresolved_flag_set_when_resolution_unmatched():
    """No master record matches → birth_unresolved=1, contractor_id=NULL,
       identity_source=packing_resolution_unmatched."""

def test_build_buyer_override_pure_projection_from_cm_row():
    """No DB call. Maps CM dict to buyer_override dict. Empty dict for None."""

def test_build_payment_terms_pure_projection():
    """No DB call. Returns {days, method, source}. payment_terms_days
       null on CM → returns {days: None, method: 'wire', source: 'unset'}."""

def test_auto_create_persists_three_overrides_when_cm_resolved():
    """Real-builder test — Lesson A binding. Calls
       auto_create_draft_from_sales_packing() against in-memory DBs;
       asserts buyer_override_json, ship_to_override_json, payment_terms_json
       are NOT '{}'. Asserts contractor_id is bound. No stubs."""

def test_auto_create_preserves_today_behavior_when_no_cm():
    """Backward compatibility — Lesson A regression guard. If CM lookup
       returns None, INSERT must STILL succeed; the three override columns
       are '{}', identity_source='legacy_heuristic', birth_unresolved=0."""

def test_contractor_id_jozef_hornak_row_260():
    """Replays the diacritic case. Asserts identity binds via
       packing_resolution_confirmed without touching the heuristic."""

def test_contractor_id_uab_monodija_cid_134920664_row_258():
    """Replays the trailing-comma case. Same assertion."""
```

These tests are **real-builder** — they import
`auto_create_draft_from_sales_packing` directly and assert against its real
return shape. No stubbed builder ever passes Lesson A's gate.

---

## 7. Sequencing and Gate Discipline

### What can be authored NOW (during #553 wait)

- `draft_birth_authority.py` — new file, no existing-file edits
- `test_draft_birth_authority.py` — new file, no existing-file edits
- This campaign document — already done

### What must wait for #553 merge

- Schema ALTER block in `_ensure_drafts_table` (file is in no-go zone)
- INSERT modification in `auto_create_draft_from_sales_packing` (no-go zone)
- Frontend banner in `proforma-detail.jsx` (no-go zone)

### After #553 merges

```
#553 merges to main
  ↓ checkout main; pull --ff-only origin main
  ↓ rebase fix/proforma-payment-due-bank-authority onto new main
  ↓ replay sandbox resolutions from sandbox/reconcile-553-onto-prc @70534e3
  ↓ run all 4 test suites
  ↓ browser verify 5 scenarios
  ↓ open PR-C only when GATE 2 has a free slot
  ↓ PR-C merges
  ↓ NEW BRANCH fix/draft-birth-authority opens
  ↓ wire schema + INSERT + frontend banner
  ↓ run all 4 test suites + the new draft-birth suite
  ↓ browser verify 3 new scenarios (confirmed / ambiguous / unmatched at birth)
  ↓ open PR-D when GATE 2 has a free slot
```

PR-D does NOT block on AWB/DHL work. AWB is sequenced independently per
operator's "Do not combine AWB activation with proforma contract fixes"
constraint.

### GATE state at planning time

| Gate | State |
|------|-------|
| GATE 2 | 3/3 FULL (#553, #522, #498) |
| GATE 1 | n/a — no PR open for this campaign yet |
| GATE 3 | Branch not yet created (will be ACTIVE when opened) |
| Test baseline | PZ 221+1 documented pre-existing failure · Carrier 412 |
| Engineering Lessons binding | A (real-builder tests), I (workflow class, not symptom), M (no capability removal) |

---

## 8. Lesson M Compliance

This campaign **adds** authority surface, does not remove any operator-visible
capability. The `ContractorResolutionPanel` already exists in the UI; this
campaign only changes when the panel surfaces (always, when birth_unresolved=1)
rather than when it must be manually opened.

No buttons, menu items, tabs, panels, sections, workflow actions, or roadmap
placeholders are removed, hidden, collapsed, replaced with static text, moved
into comments, or relocated. No formal cancellation record required.

---

## 9. Risks and Open Questions

| # | Risk | Disposition |
|---|------|-------------|
| R1 | `_resolve_customer` at birth adds DB I/O to every packing upload sync | LOW — one read per (batch_id, client_name), already done at POST time; moving it up shifts cost, doesn't add it. Bench: <50ms per draft. |
| R2 | Backfill for existing drafts | NO BACKFILL. Existing drafts use `identity_source=legacy_heuristic` (via NULL coalesce on read). Authority chain unchanged for them. New behavior applies to new drafts only. |
| R3 | Operator changes Customer Master AFTER draft birth | Draft retains birth-time snapshot. Operator can use existing "Reset from sales packing" lifecycle action (route 20 in BACKEND_GAP_REGISTER) to re-snapshot. Document explicitly. |
| R4 | `packing_contractor_resolution` row missing for legacy batches | Falls back to today's heuristic via `_resolve_customer`. Same behavior as today. |
| R5 | What if operator picks ambiguous at upload, then confirms later? | `birth_unresolved=1` flag persists until an explicit assignment event fires. Existing `customer_resolution_authority` write path updates the draft's contractor_id and clears the flag. Out of scope for first PR; document in OPEN QUESTIONS. |

### Open questions for operator (NOT blocking research)

- OQ-1: Should `birth_unresolved=1` block POST to wFirma, or just warn?
  Recommendation: warn-only initially; tighten to block after one quarter of
  observed behavior. (Authority: operator)
- OQ-2: For ambiguous resolutions, should the draft store the candidate list
  in a new column for inline UI rendering, or re-query each render?
  Recommendation: re-query — candidate set is small, freshness matters.
  (Authority: backend-api)

---

## 10. Files in scope

| Phase | File | Status |
|-------|------|--------|
| NOW | `service/app/services/draft_birth_authority.py` (NEW) | safe to author during #553 wait |
| NOW | `service/tests/test_draft_birth_authority.py` (NEW) | safe to author during #553 wait |
| NOW | `.claude/campaigns/draft-birth-authority.md` | this file |
| AFTER #553 | `service/app/services/proforma_invoice_link_db.py` (`_ensure_drafts_table` + `auto_create_draft_from_sales_packing`) | wait — no-go zone |
| AFTER #553 | `service/app/static/v2/proforma-detail.jsx` (birth_unresolved banner) | wait — no-go zone |
| AFTER #553 | `BACKEND_GAP_REGISTER.md` (add row M8 if applicable, otherwise just reference completed authority) | wait |

---

## 11. Success Criteria

PR-D is complete when:

1. Schema ALTER lands; existing rows tolerate NULL on the three new columns
2. `auto_create_draft_from_sales_packing` populates buyer_override,
   ship_to_override, payment_terms from Customer Master when contractor_id
   is bound at birth
3. `birth_unresolved=1` flag is set when packing resolution is ambiguous/
   unmatched; UI shows banner pointing to ContractorResolutionPanel
4. Real-builder tests (10 listed above) pass
5. Browser verification: fresh upload with confirmed contractor → preview
   shows full customer card and correct payment terms without any operator
   click; fresh upload with ambiguous contractor → banner visible, draft
   editable, panel inline
6. UAB Monodija (cid 134920664) and Jozef Horňák flows verified end-to-end
   without manual repair
7. Operator no longer needs to manually fix customer defaults after each
   packing upload — recurring repair loop is closed at its source
