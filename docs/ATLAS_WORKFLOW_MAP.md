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

## 1C. WF4.5 OUTBOUND DISPATCH (carrier / DHL label) (spec + audit)

### Overview

WF4.5 ("Dispatch / sample / return paths") in the §1 table covers the outbound
physical dispatch of goods to a customer. The key sub-path is:

```
DIRECT_DISPATCH_READY  →  [Generate DHL label]  →  CLIENT_DISPATCHED  →  CLOSED
```

### Existing carrier subsystem (audit — Phase C complete, Phase D pending)

All file:line citations are from origin/main @ c09fdfa.

| Component | File:line | Status |
|---|---|---|
| **Shipment-creation endpoint** | `routes_carrier_actions.py:98` — `POST /api/v1/carrier/{batch_id}/shipment` | **Registered + live** (503 when `carrier_api_status=pending`) |
| **Coordinator (idempotency + shadow log)** | `services/carrier/coordinator.py:127` — `CarrierCoordinator.create_shipment()` | **Complete** — full idempotency key, PENDING anchor, shadow log, COMPLETE transition |
| **Live adapter** | `services/carrier/adapters/live.py:44` — `DhlExpressLiveAdapter.create_shipment()` | **Raises `NotImplementedError`** — "Phase D will add the httpx call, idempotency write, and label handling." Guards: allowlist + credential checks pass first. |
| **Shadow adapter** | `services/carrier/adapters/shadow.py:32` — `DhlExpressShadowAdapter.create_shipment()` | **Complete** — deterministic `SIM-{hash}` tracking ref, `simulated=True`, no HTTP |
| **PLT eligibility** | `services/carrier/models/plt.py`, `services/carrier/plt/eligibility.py` | **Complete** — gate-checks `carrier_plt_status`, invoice paths, customs doc path, country allowlist |
| **Response redactor** | `services/carrier/persistence/redactor.py:38` — strips `labelData`, `pdfData`, `shipmentLabel`, `labelImage`, `content`, `*Data`, `*Bytes`, `*Base64`, credentials, and (in LIVE mode) `awbNumber`, `trackingNumber`, `shipmentTrackingNumber` | **Complete** — defense-in-depth binary detection |
| **Data model** | `services/carrier/models/shipment.py:31` — `ShipmentRequest` (batch_id, shipper_account, recipient_address: dict, declared_value, currency, weight_kg, dimensions: dict, special_instructions); `ShipmentResult` (idempotency_key, mode, state, tracking_ref, service_product, dimensions_json) | **Complete** — no label-bytes field yet |

### Gate fields (config.py:305–324)

| Setting | Default | Role |
|---|---|---|
| `carrier_api_status` | `"pending"` | Master gate: `pending` → 503; `shadow` → shadow adapter (no HTTP, offline sim); `sandbox` → live adapter against `DHL_EXPRESS_API_URL` **test base** (`https://express.api.dhl.com/mydhlapi/test`), creds required, allowlist NOT enforced, non-billable; `live` → live adapter against prod base (`https://express.api.dhl.com/mydhlapi`), creds required, allowlist enforced, billable |
| `carrier_plt_status` | `"pending"` | PLT (Paperless Trade) gate — independent of `carrier_api_status` |
| `carrier_live_allowlist` | `""` | CSV of batch_ids permitted for live calls (empty = no live calls even when status=live) |
| `DHL_EXPRESS_API_KEY` | None | Shipment-creation credential (NOT the same as tracking/clearance DHL client) |
| `DHL_EXPRESS_API_SECRET` | None | Shipment-creation credential |
| `DHL_EXPRESS_ACCOUNT_NUMBER` | None | Shipper billing account |
| `DHL_EXPRESS_API_URL` | `https://express.api.dhl.com` | Express API endpoint |

All five `DHL_EXPRESS_*` fields are unset in production today. `carrier_api_status`
is `"pending"`. No live call has ever been made.

### Inventory dispatch states (inventory_state_engine.py)

```
PURCHASE_TRANSIT  →  DIRECT_DISPATCH_READY  (trigger: direct_dispatch_marked)
                      ↓
                    CLIENT_DISPATCHED        (trigger: client_dispatched)
                      ↓
                    CLOSED                   (trigger: delivery_confirmed)

WAREHOUSE_STOCK   →  SALES_TRANSIT           (trigger: invoice_issued)
                      ↓
                    CLOSED                   (trigger: delivery_confirmed)
```

`POST /api/v1/lifecycle/inventory-state/mark-direct-dispatch` (routes_lifecycle.py:469)
transitions scan_codes to `DIRECT_DISPATCH_READY`. Requires customs/PZ clearance
evidence in `audit.json`, operator name, and customer allocation.

`dispatch_reference` (inventory_state_engine.py:476) — free-text field on the
`transition()` call, used for outbound waybill / RMA reference. Currently manually
entered; no label generator populates it.

### Two dispatch paths

#### Path-LIVE — real DHL Express API label (Phase D)

Triggers the existing `POST /api/v1/carrier/{batch_id}/shipment` endpoint with
`carrier_api_status=live`, credentials set, and the batch in `carrier_live_allowlist`.

**Phase D deliverables** (as stated in `adapters/live.py:49`):
1. `httpx` call to `DHL_EXPRESS_API_URL/shipments` (REST JSON, not SOAP)
2. Parse label from response (`labelData` / `shipmentLabel` — currently redacted)
3. Idempotency write via existing coordinator
4. Store real AWB in a dedicated field (see AWB storage decision below)
5. Consume `client_carrier_accounts.account_number` as `shipper_account`

#### Path-DOC — document package, no API (always-works floor)

Generates a PDF package containing:
- DHL CN23 customs declaration (for international shipments)
- Commercial invoice (from proforma or wFirma invoice)
- Packing list / weight declaration

This path requires **no carrier credentials**, works in all environments, and is
the guaranteed fallback. It produces documents the operator prints and hands to DHL
at a service point. No API call, no AWB generated — the AWB is obtained physically
at the counter.

### "Generate DHL label" button logic

```
operator clicks "Generate DHL label" (WF4.5)
  ↓
if carrier_api_status == "sandbox":
     → attempt Path-LIVE against DHL test endpoint (allowlist NOT enforced, non-billable)
     on success: store test AWB (flagged sandbox), show result
     on failure: surface error; Path-DOC available as manual fallback
if carrier_api_status == "live"
   AND DHL_EXPRESS_API_KEY + DHL_EXPRESS_API_SECRET + DHL_EXPRESS_ACCOUNT_NUMBER set
   AND batch_id in carrier_live_allowlist:
     → attempt Path-LIVE (prod endpoint)
     on success: store real AWB, mark CLIENT_DISPATCHED, show tracking ref
     on failure: fall back to Path-DOC, surface error in Inbox
  else:
     → Path-DOC (generate document package; operator takes to DHL counter)
```

Mandatory input at label-generation time (both Path-LIVE and Path-DOC): **box_type_id** — the operator selects a box type from the `box_types` master table (`master_data.sqlite`). The box type carries `length_cm`, `width_cm`, `height_cm`, and `tare_weight_kg`. Total package weight = sum of `packing_lines.gross_weight` (all lines for the batch) + `box.tare_weight_kg`.

**Gate = existing `carrier_api_status` progression** (`pending → shadow → sandbox → live`).
The `sandbox` value is new: routes through the live adapter against DHL's non-billable test endpoint (`https://express.api.dhl.com/mydhlapi/test`); allowlist NOT enforced; requires sandbox credentials (≠ production credentials — separate DHL provisioning step). Auth = HTTP Basic `Authorization: Basic base64(API_KEY:API_SECRET)` — `API_KEY` is the username, `API_SECRET` is the password — for both `sandbox` and `live`. `shadow` mode is the offline fallback (no HTTP, no credentials required).
**No new boolean flag is introduced.** The progression is deliberate and operator-driven.

### Prerequisites and gaps

| Prerequisite | Paths | Status |
|---|---|---|
| `company_profile.legal_name + address` for shipper | **BOTH** | ⚠ **REQUIRED** — currently no row in production. Must be populated before either path can print a valid shipper identity. (PR #416 wires the UI; operator must fill the data.) |
| `company_profile.eori` for shipper EORI | **BOTH** (Path-LIVE customs data + Path-DOC CN23) | ⚠ **REQUIRED for international shipments** — EORI is mandatory on the customs declaration (CN23 / PLT data). `company_profile.eori` (TEXT, nullable) is the sole source of truth for Estrella's EORI; must be populated. |
| `client_carrier_accounts.account_number` for per-client DHL billing | Path-LIVE | **GAP-8** — table populated (5 rows in production), not consumed by carrier subsystem (`ShipmentRequest.shipper_account` is a free-text field today) |
| Recipient address completeness | **BOTH** | Advisory → Inbox — `customer_master.ship_to_*` / `bill_to_*` fields exist but are often empty. Advisory validation should emit an `INBOX` proposal if ship-to fields are blank before label generation proceeds. |
| `box_type_id` → dimensions + tare | **BOTH** | **REQUIRED** — operator selects a box type at label time. `box_types` master table (`master_data.sqlite`) holds `length_cm`, `width_cm`, `height_cm`, `tare_weight_kg`. Missing or unknown `box_type_id` → 422 gap `{field:"box_type"}`. Goods weight from `packing_lines.gross_weight`; total = goods + tare. |
| Receiver label address | **BOTH** | `customer_master.ship_to_*` (primary); fallback to `bill_to_*` when `ship_to_street` is absent + advisory proposal `ship_to_missing` written to audit Inbox. Currently 12/61 customers have `ship_to_street`. |
| Incoterm | **BOTH** (CN23 / commercial invoice) | **GAP-7** — `proforma_draft.incoterm` is nullable, often NULL. Required on CN23 for customs. Must be resolved before dispatch. |
| DHL Express credentials in .env | Path-LIVE only | **MISSING** in production — `DHL_EXPRESS_API_KEY`, `DHL_EXPRESS_API_SECRET`, `DHL_EXPRESS_ACCOUNT_NUMBER` all unset. |
| `carrier_api_status` advanced to `"sandbox"` then `"live"` | Path-LIVE only | **operator step** — currently `"pending"` in production; must progress `pending → shadow → sandbox → live`. `sandbox` validates end-to-end against DHL test endpoint before production enablement. |
| PLT eligibility (Paperless Trade) | Path-LIVE international | `carrier_plt_status` currently `"pending"`; invoice + customs doc paths + country allowlist all checked by existing `plt/eligibility.py`. Gated separately. |

### AWB storage decision (ASSUMPTION — to confirm)

> **Assumption (recorded, not decided):** the real AWB returned from Phase-D
> Path-LIVE should be stored in a **dedicated field** on a `dispatch_record`
> (new row, additive migration, atomic writer/reader) rather than overloaded into
> the free-text `dispatch_reference` field on `inventory_state`. Rationale:
> `dispatch_reference` is used for RMA/return references too; a structured `awb`
> field enables downstream tracking queries. Implementation decision deferred to
> the Phase-D PR.

### Button binding additions for §2

| Screen | Button label | WF id | Gate |
|---|---|---|---|
| Inventory / Dispatch | Generate DHL label | WF4.5 | `carrier_api_status` + creds + allowlist (Path-LIVE) or always (Path-DOC) |
| Inventory / Dispatch | Mark as Dispatched | WF4.5→CLIENT_DISPATCHED | — |

---

## 1D. WF2 VAT + Document Defaults from customer_master (spec — ADR-027)

> **Context (audit finding, origin/main @ c09fdfa):** the pre-ADR-027 implementation
> reads `wfirma_customers.vat_id` and `wfirma_customers.country` to decide the VAT
> context. It ignores `customer_master.vat_eu_number`, `vat_eu_valid`, and `vat_mode`.
> Document-default fields (`payment_terms_days`, `default_language_id`,
> `preferred_proforma_series_id`) may be read from `customer_master` (where they exist)
> but the currency fallback and terms are not consistently applied from SSOT.
> The VAT context is not frozen into the draft and not shown before Post.
> The verify-after-create gate catches codes wFirma *changed*, not codes *sent wrong
> from the start*. This is the root of the PROF 92 WDT→23% class of error.

### D1 — Source authority: `customer_master` is the SSOT for VAT + document defaults

All proforma VAT and document-default fields are driven from **`customer_master`**.
The `wfirma_customers` mirror is a **last-resort read-only fallback** used only when
`customer_master` has no `country` AND `wfirma_customers` is also empty. No DB write
occurs on fallback; it fills only the in-flight decision.

**Fields owned by `customer_master` for proforma creation:**

| Field | Purpose |
|---|---|
| `country` | D2 VAT derivation (primary) |
| `vat_eu_number` | D2 WDT eligibility |
| `vat_eu_valid` | D3 VIES warning trigger |
| `vat_mode` | D2 operator VAT override (wins all derived logic) |
| `default_currency` | D5 currency fallback |
| `payment_terms_days` | D6 payment terms → `<paymentmethod>` days |
| `preferred_payment_method` | D6 payment method code |
| `default_language_id` | D6 language sent to wFirma |
| `preferred_proforma_series_id` | D6 proforma series at create |
| `preferred_invoice_series_id` | D6 invoice series at convert-to-invoice |

### D2 — VAT resolution order (one context per proforma)

**Priority 1 — Operator vat_mode override (wins everything):**

`customer_master.vat_mode` stores a **numeric integer** equal to the wFirma
account-specific `vat_code` id. The code uses `_VMODE_TO_CONTEXT` (`wfirma_client.py`)
to map the stored integer directly to `(context, code_string)`. The UI layer maps
the operator's display label to the numeric id before writing; the backend only
ever sees the integer. Any integer without a `_VMODE_TO_CONTEXT` entry raises
`ValueError` (blocks draft — never guesses).

> **Schema note:** `upsert_customer` (`customer_master_db.py`) currently validates
> `vat_mode ∈ {222, 228, 229}` only. Entries marked † in the table are handled by
> the resolver but require a schema extension or direct DB write to store.

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

Note: the `vat_codes/find` id column shows this account's mapping. The id is
**resolved live at post** (via `resolve_vat_code_id_for_context`) and **never
persisted** — only the context string and code string are frozen in the draft.

**Priority 2 — Derived from country + vat_eu_number (when vat_mode is null/unset):**

| Condition | Resolved context | Frozen code | Notes |
|---|---|---|---|
| `country == "PL"` | `domestic` | `23` | |
| `country ∈ EU-27` AND `vat_eu_number` set | `wdt` | `WDT` | |
| `country ∈ EU-27` AND `vat_eu_number` empty | `wdt-intent` (FLAGGED) | `WDT` | D3 warning fires |
| `country ∉ EU-27` | `export` | `EXP` | |
| `country` empty (cm) → fallback `wfirma_customers` → still empty | **BLOCKED** | — | ValueError; do not post |

Numeric ids for derived-path codes are resolved live via `vat_codes/find` at post
time (in-process cache). Only the context string and code string are frozen.

### D3 — VIES warning (NOT a block)

When the resolved context is `wdt` and `customer_master.vat_eu_valid` is **not `True`**
(missing, unverified, or explicitly invalid):

1. A **WARNING** is shown in the pre-post payload-disclosure modal.
2. A **`vies_unverified` Inbox advisory** is written (see §7).
3. The operator may **acknowledge-and-proceed** — no hard block.
4. The system does **NOT silently downgrade** to domestic (23%).
5. The operator owns the legal call; can override via `vat_mode` if needed.

Rationale: hard blocks jam live shipments. The operator is informed; they decide.

### D4 — Freeze and disclose

**At draft creation (WF2.3)**, freeze into `proforma_draft`:

| Draft field | What is stored |
|---|---|
| `vat_context` | `"domestic"` / `"wdt"` / `"export"` / `"np"` / `"npue"` / `"zw"` / `"zero"` |
| `vat_code` | Code string (`"23"` / `"WDT"` / `"EXP"` / etc.) — NOT numeric id |
| `decision_source` | `"operator_vat_mode"` \| `"derived"` \| `"fallback_wfirma"` |

**In the payload-disclosure modal (before WF2.4 Post):**
- All three frozen fields are surfaced.
- `/api/v1/proforma/draft/{id}/disclose-post` re-resolves the VAT context and
  **compares to frozen values**. A **DRIFT WARNING** fires if they differ.
- Operator must acknowledge warnings before post proceeds.

**At post (WF2.4):** the numeric `vat_code_id` is resolved live (D2 locked map) and
sent. Verify-after-create gate checks the persisted id matches what was sent (retained
as defence-in-depth; insufficient alone — see note below).

### D5 — Currency

- **Proforma currency** = dominant currency of the sale lines being included.
- **Fallback**: `customer_master.default_currency` when lines carry no currency.
- **Mismatch warning**: if the resolved currency differs from `customer_master.default_currency`,
  a WARN is logged and surfaced in the disclosure modal (not a block).
- Currency is **not** frozen in the draft — it is re-derived at post from current sale-line state.

### D6 — Document defaults sent to wFirma at proforma create

On proforma create (WF2.4 post), the following `customer_master` fields are included
in the wFirma XML payload, **overriding** whatever wFirma would infer from its own
contractor record:

| customer\_master field | wFirma XML element | Notes |
|---|---|---|
| `payment_terms_days` | `<paymentdays>` | Integer days; if null → wFirma default |
| `preferred_payment_method` | `<paymentmethod>` | e.g. `"transfer"` |
| `default_language_id` | `<lang>` | e.g. `"en"` / `"pl"` |
| `preferred_proforma_series_id` | `<series><id>` | Proforma numbering series |

On **convert-to-invoice** (WF3):

| customer\_master field | wFirma XML element | Notes |
|---|---|---|
| `preferred_invoice_series_id` | `<series><id>` | Invoice numbering series |

If a field is null in `customer_master`, **do not send the element** — let wFirma
use its contractor default. Do not substitute a hardcoded fallback.

### Full field map: customer\_master → proforma\_draft → wFirma post

| customer\_master field | Source classification | Old source | Post-ADR-027 role | Frozen in draft? | Sent to wFirma? |
|---|---|---|---|---|---|
| `country` | wFirma-sync | `wfirma_customers.country` | **Primary D2 VAT input** | No | No |
| `vat_eu_number` | Operator | Not consulted | **D2 WDT eligibility** | No | No |
| `vat_eu_valid` | VIES result | Not consulted | **D3 VIES warning trigger** | No | No |
| `vat_mode` | Operator | Not consulted | **D2 override — wins all** | No (→ `decision_source`) | No |
| `nip` | wFirma-sync | `wfirma_customers.vat_id` | D2 fallback (last resort) | No | No |
| `default_currency` | Operator | Partial | D5 currency fallback | No | No (sale-line driven) |
| `payment_terms_days` | Operator | wFirma contractor default | D6 → `<paymentdays>` | No (read at post) | **Yes** (if set) |
| `preferred_payment_method` | Operator | customer\_master ✓ | D6 → `<paymentmethod>` | No (read at post) | **Yes** (if set) |
| `default_language_id` | Operator | Not sent | D6 → `<lang>` | No (read at post) | **Yes** (if set) |
| `preferred_proforma_series_id` | Operator | customer\_master ✓ | D6 → `<series><id>` (proforma) | No (read at post) | **Yes** (if set) |
| `preferred_invoice_series_id` | Operator | Not sent | D6 → `<series><id>` (invoice) | No (read at convert) | **Yes** at WF3 (if set) |
| **`vat_context`** (NEW draft field) | — | N/A | Frozen resolved context | **Yes** | No |
| **`vat_code`** (NEW draft field) | — | N/A | Frozen code string | **Yes** | No (id live at post) |
| **`decision_source`** (NEW draft field) | — | N/A | Provenance of decision | **Yes** | No |
| `vat_code_id` (in-process) | — | Live `vat_codes/find` | Account-specific id at post | **No** | Yes (`<vat_code><id>`) |

### Why verify-after-create is insufficient alone

`create_proforma_draft()` fetches the created proforma back and checks that each
line's persisted `vat_code.id` matches `req.vat_code_id`. This catches codes that
**wFirma changed** after receiving them. It does **not** catch a code **sent wrong
from the start** — because sent == persisted, the check passes.

D1–D4 ensure the correct code is sent. The verify-after-create gate is retained
unchanged as defence-in-depth; it is no longer the primary correctness control.

### Scope and write-flag posture

- Posting remains behind `WFIRMA_CREATE_PROFORMA_ALLOWED` (unchanged).
- wFirma mocked in all tests; no live writes in dev.
- No new feature flag introduced — D1–D6 are correctness fixes under the existing flag.
- Convert-to-invoice remains behind `WFIRMA_CREATE_INVOICE_ALLOWED` (unchanged).

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
| Inventory / Dispatch | Generate DHL label | WF4.5 (see §1C) | body: {box_type_id, incoterm?, receiver_eori?, client_name?}; carrier_api_status + creds + allowlist (Path-LIVE) or always (Path-DOC) |
| Inventory / Dispatch | Mark as Dispatched (CLIENT_DISPATCHED) | WF4.5 (see §1C) | — |
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