# ATLAS_WORKFLOW_MAP.md — Official Workflow Spine

**Status:** Active  
**Date:** 2026-06-01  
**Repo:** estrella-dhl-control  
**Related:** ADR-023 (master data = SSOT), ADR-024 (product master), ADR-025 (E2E workflow)

This document is the authoritative workflow spine for the Estrella Atlas operating system.
All workflow decisions, button→transition bindings, write-flag assignments, and the
official build sequence live here. When this document conflicts with any other source,
this document wins.

---

## 0. Model (spec)

Two intake tracks (purchase/import, sales/export) converge on `product_code` (= design id),
then customs → PZ → wFirma → proforma → invoice, with inventory staged by DHL status.
Master data is the single source of truth (ADR-023). All validation is
**detect → inbox → approve** (soft, advisory, overridable). Only wFirma writes are
hard-gated by flags.

---

## 1. Workflow transitions WF1–WF4 (spec)

### WF1 — Import / customs / PZ chain · Owner: Shipment Detail

| Step | Action |
|---|---|
| WF1.1 | Intake: AWB + carrier + supplier + client + documents |
| WF1.2 | Parse & mint `product_code` + PL/EN description |
| WF1.3 | Validate vs masters → inbox proposals; AI reverification vs source + masters (see §1A) |
| WF1.4 | DHL customs email received (DHL pipeline §1B) |
| WF1.5 | Generate Polish description / DSK / build reply package (DHL pipeline §1B) |
| WF1.6 | SAD / MRN recorded |
| WF1.7 | Generate PZ document |
| WF1.8 | Export PZ to wFirma (**flag-gated**: WFIRMA_CREATE_PZ_ALLOWED) |

### WF2 — Sales / proforma / invoice chain · Owner: Proforma

| Step | Action |
|---|---|
| WF2.1 | Sales packing list + client |
| WF2.2 | Match designs → `product_code`; AI reverification of sales↔purchase lines → inbox proposal on mismatch (see §1A) |
| WF2.3 | Create proforma draft |
| WF2.4 | Post proforma to wFirma (**flag-gated**: WFIRMA_CREATE_PROFORMA_ALLOWED) |
| WF2.5 | Convert proforma → WDT invoice (**flag-gated**: WFIRMA_CREATE_INVOICE_ALLOWED + payload-disclosure modal) |

### WF3 — Reservation / readiness approval gate · Owner: Reservation tab

| Step | Action |
|---|---|
| WF3.1 | Reserve stock against proforma / order |
| WF3.2 | Readiness approval (customer mapped, products resolved, advisory warnings reviewed) |

### WF4 — Inventory lifecycle · Owner: Inventory

| Step | Action |
|---|---|
| WF4.1 | IN_TRANSIT (auto, from DHL events §1B) |
| WF4.2 | DELIVERED (auto, from DHL events §1B) |
| WF4.3 | Confirm received (operator: person / date / location) |
| WF4.4 | WAREHOUSE_STOCK |
| WF4.5 | Dispatch / sample / return paths |
| WF4.6 | CLOSED |

**Inbox** — cross-cutting approval, hold, override, and proposal-execution layer for all WFs.

**Rule (spec):** every state-changing button references exactly one WF transition id.
Utility actions (download, copy, export-CSV, search) carry no WF id and are not
workflow transitions.

---

## 1A. Rule-Based Reverification Layer (spec)

> **Docs-honesty correction (B9):** This layer is implemented as deterministic
> rule-based logic (`rule_based_reverification.py`), NOT an AI model. There are no
> Anthropic/LLM calls. The earlier name "AI Reverification" was aspirational;
> the implementation is rule-based comparison against local masters. If a future
> increment adds a real AI check, it will be an additional service layered on top.

**Role:** the engine of detect → inbox → approve. After document parse, this layer
re-checks extracted data for correctness using deterministic rules before it is
trusted anywhere downstream.

**Reads:**
- (a) the relevant masters (supplier, client, product, HS, company profile)
- (b) the paired track's lines (purchase ↔ sales)
- (c) invoice_lines from documents.db

**Emits:** the §7 inbox proposal types (9 active — see §7 list), each with a rule
confidence level — supplier mismatch, client mismatch, product/design mismatch,
missing HS code, price/value conflict, sales-vs-purchase line mismatch, etc.
No "AI confidence/verdict" language — confidence values are rule-derived.

**Boundaries (HARD):** read-only and proposal-only. NEVER writes a master, NEVER
writes to wFirma, NEVER auto-approves and NEVER auto-corrects. Master wins (§5);
every finding is a proposal for operator approval. No live writes in dev (mock).

**Invocation:** runs automatically at WF1.3 (purchase reverify, wired in
`routes_intake.py` post-parse) and WF2.2 (sales match reverify); re-runnable
on demand. Re-runs bind to WF1.3 / WF2.2.

**Distinct from generation:** this layer is VALIDATION. It is separate from the
existing generative-AI uses (PL/EN customs descriptions, email drafts).

**Output sink:** the Inbox layer — proposals written to `audit["action_proposals"]`
→ Inbox holds → operator approves / holds / overrides.

---

## 1B. DHL Pipeline (spec / audit)

**Role:** DHL is the carrier + customs-clearance + tracking backbone of the import
track (WF1) and the source of the inventory lifecycle events (WF4). It is a
cross-cutting pipeline, not a single transition.

**Stages / events:**

| Stage | Description |
|---|---|
| Intake pre-check (WF1.1) | "Save & Run DHL Pre-check" validates the AWB / customs basis at shipment creation |
| Tracking monitor | DHL tracking service polls the AWB and advances `clearance_status`; sets WF4.1 IN_TRANSIT |
| Customs email detection (WF1.4) | DHL customs-clearance email arrives → detected / parsed → marks `clearance_status`. Manual "✓ Mark Email Received" is the operator escape hatch when auto-detection misses |
| Clearance path selection | Routed by customs value — see below |
| Clearance actions (WF1.5) | Generate Polish Description · Generate DSK (agency package) · Build DHL Reply Package |
| Cleared → SAD / MRN (WF1.6) | ZC429 / MRN recorded → enables PZ (WF1.7) |
| Delivered (WF4.2) | DHL "delivered" event → raises the "confirm received" inbox proposal (operator: person/date/location) → WF4.3 RECEIVED |

**Clearance path selection (spec) — routed by customs value:**

| Path | Route | DHL-email gate |
|---|---|---|
| **A — DHL Agencja Celna** | Shipments under USD 2500; DHL handles clearance | Applies |
| **B — AC Spedycja / Ganther (agency / external broker)** | USD 2500+; agency clears | Skipped (agency path bypass) |

**Current state (audit):** the tracking monitor advances `clearance_status`, but the
DHL "delivered" event does NOT yet mutate inventory — the delivered→received bridge
is the Phase-7 gap. DHL self-clearance automation (Wave 1) is deployed in SHADOW mode
(`live_enabled = False`) for Path A — observing real traffic, advisory only, no live
actions.

**Boundaries:** tracking / detection are read-only; clearance actions produce
documents; the only wFirma write in this pipeline is PZ export (WF1.8, flag
`WFIRMA_CREATE_PZ_ALLOWED`). DHL self-clearance live actions stay behind
`live_enabled` (default off), consistent with the write-flag posture.

---

## 1D. WF2 VAT Resolution (spec — ADR-027)

> **Context (audit finding):** the pre-ADR-027 implementation reads `wfirma_customers.vat_id`
> and `wfirma_customers.country` to decide the VAT context. It ignores
> `customer_master.vat_eu_number`, `vat_eu_valid`, and `vat_mode`. The VAT context is not
> frozen into the draft and is not shown before Post. The verify-after-create gate only
> catches codes that wFirma *changed* — not codes that were *sent wrong from the start*.
> This is the root of the PROF 92 WDT→23% class of error.

### D1 — VAT decision source: `customer_master` is the SSOT

The VAT decision reads **`customer_master`** fields (`country`, `vat_eu_number`,
`vat_eu_valid`, `vat_mode`) — not the `wfirma_customers` mirror.

Live `wfirma_client.search_customer` is a **last-resort read-only fallback only** when
`customer_master` has no `country` AND the `wfirma_customers` row is also empty. No DB
write occurs on fallback; it fills only the in-flight decision.

### D2 — Resolution order (one context per proforma)

| Priority | Condition | Resolved context | Locked code |
|---|---|---|---|
| **1 — Operator override** | `customer_master.vat_mode` is set (non-null) | interpret as context (see map below) | same map |
| **2a** | `country == "PL"` | `domestic` | `23` |
| **2b** | `country ∈ EU-27` AND `vat_eu_number` set | `wdt` | `WDT` |
| **2c** | `country ∈ EU-27` AND `vat_eu_number` empty | `wdt-intent` (FLAGGED — see D3) | `WDT` (with warning) |
| **2d** | `country ∉ EU-27` | `export` | `EXP` |

**`vat_mode` → context mapping:**
`vat_mode=222` → `domestic` · `vat_mode=228` → `wdt` · `vat_mode=229` → `export`

**Locked code → wFirma account-specific id (resolved LIVE at post):**

| Code string | wFirma vat_code `<code>` | Numeric id (this account) |
|---|---|---|
| `23` | `23` | 222 |
| `WDT` | `WDT` | 228 |
| `EXP` | `EXP` | 229 |
| `NP` | `NP` | 230 |
| `NPUE` | `NPUE` | 231 |
| `ZW` | `ZW` | 233 |
| `0` | `0` | 234 |

The numeric id is looked up live via `vat_codes/find` at post time and cached in-process.
Only the **context string** (`domestic`/`wdt`/`export`) and the **code string** (`23`/`WDT`/`EXP`)
are stored in the draft — the numeric id is never persisted, preventing stale-id bugs.

### D3 — VIES warning (NOT a block)

When the resolved context is `wdt` and `customer_master.vat_eu_valid` is **not `True`**
(missing, unverified, or invalid):

1. A **WARNING** is emitted in the pre-post payload-disclosure modal.
2. A **`vies_unverified` Inbox advisory proposal** is written (see §7).
3. The operator may **acknowledge-and-proceed** — the system does NOT hard-block.
4. The system does **NOT silently downgrade** to domestic (23%); the VAT treatment
   remains `wdt` unless the operator explicitly overrides `vat_mode`.
5. The operator owns the legal call.

### D4 — Freeze and disclose

**At draft creation (WF2.3)**, the resolved VAT fields are stored in `proforma_draft`:

| Draft field | What is stored |
|---|---|
| `vat_context` | `"domestic"` / `"wdt"` / `"export"` |
| `vat_code` | `"23"` / `"WDT"` / `"EXP"` (code string, NOT numeric id) |
| `decision_source` | `"operator_vat_mode"` \| `"derived"` \| `"fallback_wfirma"` |

**In the payload-disclosure modal (before WF2.4 Post):**
- All three frozen fields are surfaced to the operator.
- The modal fetches `/api/v1/proforma/draft/{id}/disclose-post` which re-resolves
  the VAT context at that moment and **compares to the frozen values**.
- If they differ (e.g., the customer's country was corrected between draft creation
  and posting), a **DRIFT WARNING** is displayed — no silent change.

**At post (WF2.4)**, the numeric `vat_code_id` is resolved live (D2 map) and sent to
wFirma. The verify-after-create gate checks the persisted id matches what was sent.

### VAT field map: customer_master → draft → wFirma post

| customer\_master field | Old source | New role | Stored in draft? | Sent to wFirma? |
|---|---|---|---|---|
| `country` | `wfirma_customers.country` | **Primary D2 input** | No (used at draft creation) | No |
| `vat_eu_number` | **Not consulted** | **Primary D2 input (EU VAT for WDT)** | No | No |
| `vat_eu_valid` | **Not consulted** | D3 VIES warning trigger | No | No |
| `vat_mode` | **Not consulted** | D2 operator override (wins) | No (→ `decision_source`) | No |
| `nip` | `wfirma_customers.vat_id` | Fallback only (live wFirma search) | No | No |
| `preferred_proforma_series_id` | customer\_master (unchanged) | Series id → `<series><id>` | No (read at post) | Yes |
| `preferred_payment_method` | customer\_master (unchanged) | Payment method → `<paymentmethod>` | No (read at post) | Yes |
| **`vat_context`** (draft field) | **NEW** | Frozen resolved context | **Yes** | No |
| **`vat_code`** (draft field) | **NEW** | Frozen code string | **Yes** | No (id resolved live) |
| **`decision_source`** (draft field) | **NEW** | Provenance of the decision | **Yes** | No |
| `vat_code_id` (numeric, in-process) | Live `vat_codes/find` (unchanged) | Account-specific id resolved at post | **No** | Yes (`<vat_code><id>`) |

### Why verify-after-create is insufficient alone

`create_proforma_draft()` fetches the created proforma back from wFirma and checks
that the persisted `vat_code.id` on each line matches `req.vat_code_id`. This catches
codes that **wFirma changed** after receiving them. It does **not** catch a code that
was **sent wrong from the start** — because sent == persisted, the check passes.

The D1–D4 fixes are required to ensure the correct code is sent in the first place.
The verify-after-create gate is retained as a defence-in-depth layer but is no longer
the primary correctness control.

### Scope and write-flag posture

- Posting remains behind `WFIRMA_CREATE_PROFORMA_ALLOWED` (unchanged).
- wFirma is mocked in all tests (no live API calls in dev).
- No new flag is introduced; the VAT source fix is a behaviour change behind the
  existing flag.

---

## 2. Button → transition binding (spec; endpoints to be confirmed in Phase 12)

| Screen | Button label | WF id | Gate |
|---|---|---|---|
| New Shipment | Save Draft | WF1.1 | — |
| New Shipment | Save & Run DHL Pre-check | WF1.1 | — |
| Shipment Detail | ✓ Mark Email Received | WF1.4 (DHL pipeline §1B) | — |
| Shipment Detail | Generate Polish Desc. | WF1.5 (DHL pipeline §1B) | advisory (DHL email) |
| Shipment Detail | Generate DSK | WF1.5 (DHL pipeline §1B) | advisory |
| Shipment Detail | Build Reply Package | WF1.5 (DHL pipeline §1B) | — |
| Shipment Detail | Generate PZ document | WF1.7 | advisory (SAD/MRN) |
| Shipment Detail | ✎ Confirm PZ Number | WF1.7 | — |
| Shipment Detail | Export PZ to wFirma | WF1.8 | WFIRMA_CREATE_PZ_ALLOWED |
| Shipment Detail | + Create Pro Forma Draft | WF2.3 | — |
| Proforma detail | Post to wFirma | WF2.4 | WFIRMA_CREATE_PROFORMA_ALLOWED |
| Proforma detail | Convert to Invoice | WF2.5 | WFIRMA_CREATE_INVOICE_ALLOWED + payload-disclosure modal |
| Reservation tab | Approve readiness | WF3.2 | — |
| Inventory | Receive (confirm received) | WF4.3 | — |
| Inventory | Move Stock | WF4.4/4.5 | — |
| Inbox | Approve / Hold / Override / Execute | cross-cutting | per-proposal |
| Utility (no WF) | Download PZ/Audit EN/PL/Memo/Calc XLSX/Correction | — | — |
| Utility (no WF) | Copy wFirma Format | — | — |
| Utility (no WF) | Export CSV | — | — |
| Utility (no WF) | Search | — | — |

---

## 3. wFirma write flags (spec) — hard gates, all default OFF, dev uses mock

| Flag | Guards |
|---|---|
| WFIRMA_CREATE_PRODUCT_ALLOWED | Product registration |
| WFIRMA_CREATE_PZ_ALLOWED | PZ export (WF1.8) |
| WFIRMA_CREATE_PROFORMA_ALLOWED | Proforma post (WF2.4) |
| WFIRMA_CREATE_INVOICE_ALLOWED | Convert to invoice (WF2.5) |

**Phase-0 finding for WFIRMA_CREATE_PZ_ALLOWED:** EXISTS in config.py

**Rule (spec):** no wFirma write may exist without its own explicit flag.

---

## 4. Product master authority (spec — ADR-024 / D1 resolved)

**Implemented authority model (ADR-024 — per-line product_code):**
The row identity is `product_code` (= `invoice_no-N`, minted at purchase intake).
This is the per-line identity that flows through PZ, inventory, proforma, and invoice.

The columns `supplier_id`, `supplier_product_code`, and `normalized_design_attributes`
are **additive metadata** — not a composite primary key. They record which supplier the
product came from and enable disambiguation lookups, but the actual uniqueness constraint
remains on `product_code`.

The **canonical composite-collapse** (making `supplier_id + supplier_product_code +
normalized_design_attributes` the primary key) was **rejected** in ADR-024 because:
- Product codes are already globally unique for EJL-class codes (by construction)
- Collapsing across invoices would require renaming existing codes in production
- The per-line `product_code` model is what every downstream system (PZ, inventory,
  proforma) actually uses

For 417G non-globally-unique codes: `supplier_id` is stored as metadata; the composite
partial index `(supplier_id, product_code)` disambiguates when supplier context is
available. No `disambiguation_417g` inbox proposal is emitted (proposal type removed
as unimplemented).

**GAP-17 closed (advisory):** `validate_product_code_in_master()` is called at
`seed_purchase_transit` (inventory seed) and `upsert_pending_draft` (proforma create).
Missing codes emit an advisory `GAP17_PRODUCT_NOT_IN_MASTER` action_proposal — NOT a
hard block.

---

## 5. Conflict rule (spec)

**Master wins.** A parsed document that disagrees with a master becomes an inbox
proposal, never a silent overwrite.

---

## 6. Dual valuation (spec)

- Purchase invoice value → customs / SAD / PZ cost basis.
- Sales packing / proforma value → warehouse / sales value.
- One backend resolver owns this rule; UI displays both values side-by-side.

---

## 7. Inbox proposal types (spec) — the detect → inbox → approve set

Emitted by the Rule-Based Reverification Layer (§1A):

1. Supplier mismatch
2. Client mismatch
3. Product / design mismatch
4. Missing HS code
5. Price / value conflict
6. Sales-vs-purchase line mismatch
7. DHL-delivered-not-received
8. Product-not-synced-to-wFirma
9. PZ / proforma / invoice ready-for-approval
~~10. 417G disambiguation~~ *(removed — proposal type was defined but never implemented; see ADR-024)*

---

## 8. Build sequence (spec) — official 12-phase order

> **This is the canonical build order.** It supersedes the earlier flat increment list
> in ADR-025. Phases must be executed in order; no phase begins until the previous
> is merged, deployed, and smoke-tested.

| Phase | Deliverable |
|---|---|
| **1** | Create process authority: this map + WF1–WF4 + button binding + amend ADR-025 *(IN PROGRESS)* |
| **2** | Soften the 3 hard-stops (DHL email, SAD/MRN, product-sync/PZ-before-proforma) to advisory/inbox; keep the 4 write flags hard. Note: softening the DHL-email gate is part of the DHL pipeline (§1B); Path B (agency) already bypasses it |
| **3** | Build detect→inbox→approve via the Rule-Based Reverification Layer (§1A): deterministic rules check parsed data vs masters, emit the §7 proposal types; read-only / proposal-only. Wired at WF1.3 in `routes_intake.py`. |
| **4** | Product master authority per ADR-024 (per-line product_code model; composite columns as metadata; GAP-17 advisory validation at write paths) |
| **5** | Dual-valuation resolver (§6) + UI shows both values |
| **6** | wFirma product registration at intake via inbox proposal → operator approves → push only if flag on |
| **7** | DHL→inventory lifecycle (§1B delivered→received bridge): IN_TRANSIT auto; DELIVERED → "confirm received" proposal → RECEIVED (person/date/location); scan → final/dispatch |
| **8** | Sales↔purchase line matching by `product_code`; mismatch → inbox proposal with exact reason (approve/correct/split) |
| **9** | Proforma/invoice closure: draft always creatable; post requires customer mapped + products resolved + advisory warnings reviewed + flag; convert requires payload-disclosure modal + explicit confirmation |
| **10** | Master backfill (company profile → supplier → client/importer → HS → product authority) + conflict rule §5 |
| **11** | UI wiring: Dashboard visual-only; Shipment Detail owns WF1; Proforma owns WF2; Reservation owns WF3; Inventory owns WF4; Inbox owns approval/hold/override |
| **12** | Verification: run one full safe shipment path with NO live writes; run one gated write path in test/staging ONLY; produce the §9 truth table; then enable production write flags one by one |

---

## 9. Phase-12 truth-table template (spec)

> Filled during Phase 12 verification. One row per state-changing transition.

| transition | button | endpoint | gate | inbox proposal | output document | status |
|---|---|---|---|---|---|---|
| WF1.1 | Save Draft | — | — | — | — | ☐ |
| WF1.4 | Mark Email Received | — | — | — | — | ☐ |
| WF1.7 | Generate PZ | — | advisory (SAD/MRN) | — | PZ PDF/XLSX | ☐ |
| WF1.8 | Export PZ to wFirma | — | WFIRMA_CREATE_PZ_ALLOWED | — | wFirma PZ record | ☐ |
| WF2.3 | Create Proforma Draft | — | — | — | draft | ☐ |
| WF2.4 | Post to wFirma | — | WFIRMA_CREATE_PROFORMA_ALLOWED | — | wFirma proforma | ☐ |
| WF2.5 | Convert to Invoice | — | WFIRMA_CREATE_INVOICE_ALLOWED | payload-disclosure | wFirma invoice | ☐ |
| WF3.2 | Approve readiness | — | — | — | — | ☐ |
| WF4.3 | Confirm received | — | — | — | — | ☐ |

---

*This map is append-only for §1–§7. §8 phase checkboxes are updated per merge. §9 truth table is populated during Phase 12.*