# Proforma Invoice — Create Workflow UX Specification

**Author:** UX/UI design pass
**Date:** 2026-06-16
**Status:** DESIGN — implementation-ready spec, no code committed
**Extends:** `docs/v2-architecture-plan.md` (Proforma V2 authority + layer rules)
**Stack:** Vanilla HTML + Babel JSX, `dashboard-shared.js` components, CSS custom properties (per `.claude/skills/frontend-design.md`)

---

## 0. Scope & relationship to the existing system

### 0.1 What this covers

A **3-screen create workflow** for proforma invoices in the Estrella jewellery (gold + diamonds) B2B context:

1. **Customer (Nabywca) Selection** — search and confirm the buyer.
2. **Product Selection & Line Items** — build the invoice line table from the product catalog.
3. **Information / Modify** — issue date, payment, currency, VAT context, jewellery/customs fields, remarks.

### 0.2 Reconciling "customer-facing" with the real app

The task brief frames this as customers creating their own proformas. In Estrella's reality the creator is an **internal sales operator** acting on behalf of a buyer (the *Nabywca*). This spec designs for the operator-as-creator. Every pattern (autocomplete buyer lookup, catalog modal, line table, info edit) maps cleanly either way; only the entry point and permissions differ.

### 0.3 Create vs. the existing draft-review flow (critical)

`proforma-v2.html` today is a **draft-review** surface: drafts are *born from sales/packing ingestion* (`auto_create_draft_from_sales_packing`) and the operator reviews, edits, approves, and posts them. This new workflow is a **manual / greenfield create** path.

**Authority-clean decision:** the create workflow must produce the **same `ProformaDraft` object** and feed the **same `draft → approved → posted` lifecycle**. It does **not** invent a parallel document type or a second posting path. The three create screens are an alternative *front door* to the existing draft lifecycle, after which the operator lands in the established review/approve/post surface.

> Consequence: screens 2 and 3 reuse the existing draft-line and draft-header APIs (`POST/PATCH/DELETE /draft/{id}/lines`, `PATCH /draft/{id}`). The only net-new backend surface required is a thin "create blank draft for a chosen customer" endpoint — see §11 Backend Gaps.

### 0.4 Authority boundaries honored (Lesson F)

| Screen | Owns | Must NOT own |
|---|---|---|
| 1 — Customer Selection | *reading* customer authority to pick a buyer; writing the buyer onto the draft | customer CRUD (NIP/address edits live in Customer Master V2) |
| 2 — Line Items | draft lines (product_code, qty, price, hs_code) | product authority CRUD; VAT rule production; warehouse/PZ |
| 3 — Information | draft header (currency, payment terms, incoterm, remarks, overrides) | VAT *decision* (backend-resolved); wFirma write toggles; customs truth |

The frontend **reflects** backend truth; it never **produces** legality (readiness, VAT code, postability are all backend-authoritative).

---

## 1. Design system alignment

### 1.1 Tokens (use exclusively — no hardcoded hex)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#F4F1EA` | page background |
| `--bg-subtle` | `#FAF8F2` | inset wells, form fields |
| `--card` | `#FFFFFF` | card surface |
| `--border` / `--border-subtle` | `#E5DECF` / `#EFE9DA` | borders |
| `--text` / `--text-2` / `--text-3` | `#1B2538` / `#4E5A72` / `#8B97AE` | primary / secondary / muted |
| `--accent` / `--accent-text` | `#B89968` (gold) / `#1B2538` | primary CTA fill / text on gold |
| `--badge-{green,amber,red,blue,…}-{bg,text,border}` | — | status semantics |

All tokens have `[data-theme="dark"]` / `prefers-color-scheme: dark` overrides. **Never** hardcode a color that changes between themes.

### 1.2 Components (from `dashboard-shared.js` → `window.EstrellaShared`)

`Btn` (variants: `primary`/`gold`, `outline`, `ghost`, `danger`, `success`), `Badge` (status or label), `Card`, `Sel`, `Toast` (success/info/error/warn), `SessionBanner`, plus V2 atoms `GateBlock`, `SectionHeader`, `CompactTable`, `StatusDot`, `EmptyState`. Font: **Plus Jakarta Sans**.

Modal pattern reuses the existing `.modal-backdrop` / `.modal-box` CSS already in the V2 pages.

### 1.3 Hard UI rules inherited

- **No auto-save.** Every write is an explicit, labeled click ("Save line", "Save draft", "Add to invoice").
- **No hidden blockers.** Blocking reasons render in `GateBlock`; disabled buttons carry a `title`/adjacent reason.
- **No fake readiness, no fake stock, no wFirma write toggle in the UI.**
- **Every interactive element has a `data-testid`** (`{component}-{entity}-{qualifier}`).
- **Backend truth first:** empty value → `—`, never `0`/`null`/blank.

---

## 2. Information architecture & navigation flow

### 2.1 The wizard

A 3-step stepper persistent at the top: **1 Customer › 2 Items › 3 Information › (Review & Approve)**. Step 4 (Review/Approve/Post) is the *existing* `proforma-v2.html` surface — the wizard hands off to it; it is not re-specified here.

```
Entry (Proforma list "New proforma" / shipment context)
        │
        ▼
[1] Customer Selection ──Continue──▶ [2] Line Items ──Continue──▶ [3] Information ──Save & Continue──▶ [Review/Approve/Post]
        ▲                                  │                            │
        └──────── Back ────────────────────┴──────── Back ─────────────┘
   Cancel (any step) ──▶ confirm discard ──▶ Proforma list
```

### 2.2 Persistence model (no auto-save, but no data loss)

- A **draft is created on leaving Screen 1** (explicit "Continue" → creates a blank `ProformaDraft` in `draft_state="draft"` bound to the chosen `client_name` / `bill_to_contractor_id`). From that point the wizard has a real `draft_id` and every subsequent action is a normal draft API call.
- `draft_state="draft"` means in-progress and editable; nothing is posted to wFirma until the explicit **Post** action on the Review surface (backend-gated by `wfirma_create_proforma_allowed`).
- **Resuming:** an in-progress draft appears in the proforma list as `Draft`; reopening it deep-links back into the wizard at the furthest completed step.
- **Cancel** with unsaved edits → confirmation modal; on confirm, a never-continued Screen-1 selection discards with no draft created, a started draft transitions to `cancelled`.

### 2.3 Step gating

| To leave | Required |
|---|---|
| Screen 1 → 2 | a customer is selected and confirmed |
| Screen 2 → 3 | ≥1 valid line (product_code present, qty > 0, unit_price ≥ 0) |
| Screen 3 → Review | required header fields valid (currency postable or acknowledged, payment method/terms set) |

Each "Continue" is disabled with an inline reason until its precondition is met (Lesson M: visible + disabled + reason, never hidden).

### 2.4 Responsive (desktop + tablet)

- **Desktop ≥1024px:** two-column where useful (Screen 1 search | confirm card; Screen 2 table | totals rail).
- **Tablet 768–1023px:** single column; totals rail collapses to a sticky summary bar above the action buttons; line table becomes horizontally scrollable with frozen product column.
- Touch targets ≥40px; the catalog modal goes full-width on tablet.

---

## 3. Screen 1 — Customer (Nabywca) Selection

### 3.1 Purpose & authority

Find and confirm the **buyer** from Customer Master. This screen **reads** customer authority (`GET /api/v1/customer-master/`) and **writes the chosen buyer onto the draft**. It does **not** edit customer fields — editing NIP/address/payment defaults is Customer Master V2's job (Lesson F: one page = one domain authority).

### 3.2 Layout

```
┌── Stepper: ●1 Customer ─ 2 Items ─ 3 Information ─ Review ──────────────┐
├────────────────────────────────────────────────────────────────────────┤
│  Buyer (Nabywca)  *required                                              │
│  ┌──────────────────────────────────────────────┐  [ + New customer ]   │
│  │ 🔍  Search by name, NIP, or short code…       │   (→ Customer Master) │
│  └──────────────────────────────────────────────┘                       │
│  ▾ autocomplete results (name · NIP · city · VAT-EU dot)                 │
│                                                                          │
│  ── Selected buyer ──────────────────────────────────────────────────   │
│  ┌── CustomerAuthorityCard ────────────────────────────────────────┐    │
│  │  UAB Tomas Gold                       [ Matched ✓ ]              │    │
│  │  NIP 1234567890  ·  EU VAT LT1234… ● valid                       │    │
│  │  Vilnius, LT · import@…              default currency: EUR       │    │
│  │  Payment: transfer · 14 days        [ View in Customer Master → ]│    │
│  │  ── Ship-to ──  ◉ Same as buyer   ○ Alternate address           │    │
│  └──────────────────────────────────────────────────────────────────┘   │
├────────────────────────────────────────────────────────────────────────┤
│                                  [ Cancel ]   [ Continue to items → ]    │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Autocomplete behavior

- **Trigger:** ≥2 characters; **debounce** 250 ms; calls `GET /api/v1/customer-master/?q=…` (filter client-side if the endpoint returns the full list).
- **Match fields:** `bill_to_name`, `nip`, `vat_eu_number`, `short_code`.
- **Result row:** name (primary) · NIP · city/country · a `StatusDot` for VIES (`vat_eu_valid`: green=valid, amber=unchecked/`None`, red=invalid).
- **Keyboard:** ↑/↓ to move, Enter to select, Esc to close. ARIA combobox roles.
- **No match:** `EmptyState` "No customer matches '…'." + `Btn ghost` **"Create in Customer Master →"** (deep link, opens in new tab; returning re-runs the search).

### 3.4 Data fields (all read-only here; source = Customer Master)

| UI label | Backend field | Shown | Required to proceed |
|---|---|---|---|
| Buyer name | `bill_to_name` | always | ✓ |
| Tax ID (NIP) | `nip` | always | — (warn if absent) |
| EU VAT | `vat_eu_number` + `vat_eu_valid` | when present | — |
| Address | `bill_to_street/city/postal_code` + `country` | always | — |
| Contact | `bill_to_email` / `bill_to_phone` | when present | — |
| Default currency | `default_currency` (PLN/USD/EUR) | always | seeds Screen 3 |
| Payment method / terms | `preferred_payment_method` / `payment_terms_days` | always | seeds Screen 3 |
| wFirma contractor id | `bill_to_contractor_id` | hidden (key) | ✓ (identity) |
| Ship-to | `ship_to_*` (alternate) or `ship_to_contractor_id` | toggle | — |

### 3.5 VAT-EU / VIES surfacing

The card shows a tri-state VIES indicator from `vat_eu_valid` (`True`/`False`/`None`) — **display only**, mirroring backend three-state semantics (`None` is "not verified", not an error). It foreshadows the VAT context resolved on Screen 3 (a non-valid EU VAT is what later forces `ManualReviewRequired`).

### 3.6 Validation & states

| Condition | UI |
|---|---|
| Nothing selected | "Continue" disabled, reason "Select a buyer to continue" |
| Selected, NIP missing | amber inline note "No tax ID on file — VAT may need manual review" (non-blocking) |
| Selected, alternate ship-to chosen but incomplete | ship-to fields show required markers; "Continue" disabled |
| List fetch fails | `EmptyState state="error"` + Retry |

### 3.7 Actions

- `Cancel` (`outline`, `btn-proforma-cancel`) → discard confirm.
- `Continue to items →` (`primary`, `btn-proforma-customer-continue`) → **creates the blank draft** for the buyer, advances to Screen 2.

---

## 4. Screen 2 — Product Selection & Line Items

### 4.1 Purpose & authority

Build the invoice line table. Owns **draft lines** only. Product attributes (names, VAT default, jewellery specs) are **read** from product authority via the catalog modal; they are not edited here.

### 4.2 Layout

```
┌── Stepper: 1 Customer ─ ●2 Items ─ 3 Information ─ Review ──────────────┐
│  Buyer: UAB Tomas Gold · EUR                         [ change buyer ]   │
├─────────────────────────────────────────────────────────────┬──────────┤
│  Line items                       [ + Add from catalog ]      │ TOTALS   │
│  ┌─────────────────────────────────────────────────────────┐ │ rail     │
│  │ # Product      Design  Qty  Unit  Unit price  Disc  Net  │ │          │
│  │ 1 EJL/26-27/.. R-1180   3   szt   1,250.00 €  —  3,750€ ⌄│ │ Items 2  │
│  │   └ 18K · yellow · diamond 0.45ct · GIA · HS 7113…       │ │ Subtot.  │
│  │ 2 EJL/26-27/.. B-204    1   szt   4,900.00 €  —  4,900€ ⌄│ │ 8,650 €  │
│  │ + add line                                               │ │ Freight  │
│  └─────────────────────────────────────────────────────────┘ │ + add    │
│                                                               │ Insur.   │
│  VAT context (resolved at document level → Screen 3):         │ + add    │
│  [ derived from buyer country + EU-VAT — shown on Information ]│ ───────  │
│                                                               │ Total    │
│                                                               │ 8,650 €  │
├───────────────────────────────────────────────────────────────┴──────────┤
│                       [ ← Back ]  [ Cancel ]  [ Continue to info → ]      │
└────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Catalog search modal ("Wyszukiwanie produktu w katalogu")

Triggered by **"+ Add from catalog"**. Mirrors the wFirma catalog-search pattern but jewellery-aware.

- **Source:** `GET /api/v1/proforma/product-options` (product picker list).
- **Search:** by `product_code` (SKU), `name_pl`, `item_type`; debounce 250 ms.
- **Columns:** code · Polish name (`product_name_pl` / `name_pl`) · item type · jewellery summary (karat · metal color · stone) · unit (`unit`, default `szt.`) · default VAT (`vat_rate`, display) · sync status (`StatusDot` from `sync_status`: matched/created/ready=ok, pending=pending, not_found/error=warn/error) · last price (`unit_price_eur`/`unit_price_usd` if known).
- **Multi-select:** checkbox per row; "Add N to invoice" inserts N lines via `POST /api/v1/proforma/draft/{draft_id}/lines` each.
- **On add:** line pre-fills `product_code`, `name_pl`, `item_type`, `unit` (from product), `hs_code` (from `product_local.hs_code_override` if present), and last-known `unit_price` (operator confirms/edits). `qty` defaults to 1.
- **Empty/no-match:** `EmptyState` + note that brand-new SKUs are created in Products V2 (Lesson F — product CRUD is not owned here).

### 4.4 Line table columns

| Column | Backend field | Editable | Notes |
|---|---|---|---|
| Product | `product_code` | via catalog / inline picker | **required**, non-blank |
| Design # | `design_no` | inline | optional style ref |
| Name (PL) | `name_pl` | inline | from product, operator-overridable |
| Qty | `qty` | inline number | **> 0** |
| Unit | `unit` (product) | display | `szt.`/`g`/`ct` — **not a draft-line field**; shown from product authority |
| Unit price | `unit_price` | inline number | **≥ 0**, Decimal |
| Currency | `currency` | inline `Sel` | per-line; in `ALLOWED_CURRENCIES` |
| Discount % | — | **see §4.6** | **not in schema** — gap |
| Net | computed | display | `qty × unit_price`, rounded 2dp |
| HS code | `hs_code` | inline / from product | 6–10 digits; **required before Post** (not before Continue) |
| ⌄ detail | jewellery attrs | expand | read-only, see §6 |

Inline edits persist via `PATCH /api/v1/proforma/draft/{draft_id}/lines/{line_id}` on an explicit **per-row "Save line"** action (or row blur → "unsaved" pill + Save; never silent auto-save). Remove via `DELETE …/lines/{line_id}` with row-level confirm.

### 4.5 Running totals (totals rail)

- **Subtotal** = Σ(`qty × unit_price`) per currency. Mixed-currency lines are flagged amber ("Mixed currencies — resolve on Information") because wFirma posts a single document currency.
- **Freight / Insurance** = service charges (`service_charges_json`, types `freight`/`insurance`) via `POST /api/v1/proforma/draft/{draft_id}/service-charges`; suggestions available from `…/suggest-freight` / `…/suggest-insurance`.
- **Grand total** = subtotal + freight + insurance (Decimal, 2dp). Mirrors server math `product_subtotal + freight + insurance`.
- **VAT/gross is intentionally not shown here** — VAT is resolved at document level (Screen 3). The rail shows **net** totals with a note "VAT applied on Information step."

### 4.6 Discount handling — GOVERNANCE GAP (do not fake)

The brief asks for a per-line **discount %**. **No discount field exists** anywhere in the proforma schema; pricing is strictly `qty × unit_price` with `Decimal` math, and the net→gross engine is **frozen** (`project_three_authority_pz_engine_freeze.md`). Per Lesson M (five-state truth model) the column is shown but **must not silently invent math**. Two compliant options:

| Option | Behavior | Trade-off |
|---|---|---|
| **A — Effective unit price (recommended, zero backend change)** | Operator enters list price + discount %; UI computes `unit_price = list × (1 − disc)` and **stores only the resulting `unit_price`**. Discount shown as a derived helper, persisted in line `remarks` for audit ("list 1,500 − 10%"). | Discount not a first-class queryable field |
| **B — First-class discount field** | Add `discount_pct` to the line schema + adjust net computation. | Touches frozen valuation path; requires backend PR, regression tests, and a DECISIONS entry — **out of scope for UI work** |

Until B is decided, render the Discount column in state **`backend-pending`**: editable as an input that resolves to effective `unit_price` (Option A), with a tooltip "Discount is applied to unit price; not stored as a separate field." This keeps the capability visible and honest (Lesson M) without faking a schema field.

### 4.7 Validation & states

| Condition | UI |
|---|---|
| 0 lines | `EmptyState` "No items yet — add from catalog"; "Continue" disabled |
| `qty ≤ 0` | red cell, inline "Quantity must be greater than 0"; row Save disabled |
| `unit_price < 0` or non-numeric | red cell, inline reason |
| Currency mix across lines | amber banner; resolved on Screen 3 (single doc currency) |
| `hs_code` missing | amber `StatusDot` on row; **non-blocking here**, surfaced as a pre-Post blocker on Review |
| Add-line API fails | row reverts, error `Toast`, no partial state |

### 4.8 Actions

`← Back` (`outline`) · `Cancel` (`ghost`) · `Continue to info →` (`primary`, `btn-proforma-items-continue`, disabled until ≥1 valid line).

---

## 5. Screen 3 — Information / Modify

### 5.1 Purpose & authority

Edit the **draft header**. Sections instead of tabs keep all fields scannable on desktop; on tablet they become an accordion (one open at a time). All writes go through `PATCH /api/v1/proforma/draft/{draft_id}` on an explicit **"Save draft"**.

> Implementation note: the brief says "tabs or sections." Wireframes show sections expanded (best for review); the production page MAY collapse sections 4–5 into `<details>` accordions per the legacy-collapse convention, but sections 1–3 stay expanded (primary workflow).

### 5.2 Sections

**Section 1 — Document**
| Field | Backend field | Control | Notes |
|---|---|---|---|
| Document currency | `currency` | `Sel` PLN/USD/EUR (+GBP/CHF/JPY draft-only) | seeded from buyer `default_currency`; see §5.3 |
| Exchange rate (FX) | `exchange_rate` / `fx_rate_date` | display + "Refresh NBP" | source `NBP`; shown when doc currency ≠ PLN |
| Issue date | `wfirma_issue_date` (post) / intent pre-post | date picker | **see §5.4** — authoritative value assigned by wFirma at Post |
| Incoterm | `incoterm` | `Sel` (DAP/FCA/…) | optional |

**Section 2 — Payment**
| Field | Backend field | Control | Notes |
|---|---|---|---|
| Payment method | `payment_terms_json.method` | `Sel` transfer/cash/card/compensation | seeded from buyer |
| Payment terms (days) | `payment_terms_json.days` | number ≥ 0 | seeded from buyer |
| Payment due date | `wfirma_payment_due` (post) / derived | display | = issue date + terms; finalized at Post |
| Bank account | resolved by `currency` | display | PLN/USD/EUR → fixed company accounts; non-postable currency shows warning |

**Section 3 — Parties (overrides)**
| Field | Backend field | Notes |
|---|---|---|
| Buyer override | `buyer_override_json` (name/street/city/zip/country/nip/vat_eu/email/phone) | defaults to Customer Master; edit only to override **on this document** (does not write back to CM) |
| Ship-to override | `ship_to_override_json` | same shape |
| **VAT context** | `vat_context` / `vat_code` (display) | **derived, read-only** — see §5.3 |

**Section 4 — Jewellery & customs** (collapsible) — summary of per-line `hs_code`, `origin_country` (default `IN`), and certificate presence; jump-back link to fix lines. See §6.

**Section 5 — Remarks** (collapsible) — `remarks` free text (document notes / UWAGI).

### 5.3 Currency & VAT authority (do not fake)

**Currency:** `ALLOWED_CURRENCIES` = EUR, USD, PLN, GBP, CHF, JPY for staging, but **only PLN/USD/EUR are postable** (fixed company bank accounts). Selecting GBP/CHF/JPY shows an amber inline note: "Draft only — cannot post to wFirma in this currency. Switch to PLN/USD/EUR before posting." (Visible + reasoned, not blocked at draft time.)

**VAT is backend-resolved, not an operator free-field.** The resolver (`vat_resolver.pick_vat_code`) decides:

| Code | Rate | Condition |
|---|---|---|
| `222` | 23% domestic PL | buyer country = PL |
| `228` | 0% WDT (intra-EU) | EU buyer with `vat_eu_valid = True` |
| `229` | 0% export | non-EU buyer |
| *(none)* | — | EU buyer without valid VAT-EU, or unknown country → **`ManualReviewRequired`** |

UI shows the resolved `vat_context`/`vat_code` as a **read-only `Badge` with a reason line** ("0% WDT — EU buyer, VAT-EU validated"). On `ManualReviewRequired` it shows an amber `GateBlock`: "VAT cannot be auto-determined — validate the buyer's EU VAT in Customer Master." There is **no per-line tax-rate editor** (the brief's "tax rate per row" does not match backend authority; see §11).

### 5.4 Issue / due date reality

There is **no draft-level `issue_date`/`due_date` field**; the authoritative values (`wfirma_issue_date`, `wfirma_payment_due`) are assigned **by wFirma at Post**. Pre-post, the date pickers capture **operator intent** (stored via `payment_terms_json` / overrides) and the UI labels them clearly: "Requested issue date — final number and date are assigned when the proforma is posted." This prevents the false impression that a number/date is already reserved.

### 5.5 Validation & states

| Condition | UI |
|---|---|
| Non-postable currency | amber note (non-blocking at draft) |
| Payment terms days blank/<0 | red, "Enter 0 or more days" |
| VAT = ManualReviewRequired | amber `GateBlock` with fix path; Save allowed, Post later blocked |
| Mixed line currencies vs doc currency | amber: "N lines differ from document currency" + jump-back |

### 5.6 Actions

`← Back` (`outline`) · `Save draft` (`outline`, `btn-proforma-info-save`) · `Save & continue →` (`primary`, `btn-proforma-info-continue`) → persists header and hands off to the existing **Review / Approve / Post** surface (`proforma-v2.html?...&draft_id=…`).

---

## 6. Jewellery-specific considerations

Generic e-commerce line items are `name + qty + price`. Jewellery requires **material, stone, certification, and customs** attributes that drive customs valuation and buyer trust. The good news: **most already exist as real backend fields** — the proforma surfaces them, it does not invent them.

### 6.1 Real attributes (display on the line `⌄` detail panel)

| Attribute | Backend field | Source table | Values |
|---|---|---|---|
| Metal type | `metal_type` | `metals_db.Metal` | gold / silver / platinum / palladium / other |
| Purity (fineness) | `purity_pct` | `metals_db.Metal` | 375 / 585 / 750 / 916 / 925 / 950 / 999 |
| Purity label | `purity_label` | `metals_db.Metal` | e.g. "18K", "925" |
| Karat (parsed) | `karat` | `product_descriptions` | text from packing XLSX |
| Metal color | `metal_color` | `product_descriptions` | yellow / white / rose … |
| Stone type | `stone_type` | `product_descriptions` | diamond / … |
| Stone carat weight | `carat_weight` | `stones_db.Stone` | decimal ct |
| Stone shape | `shape` | `stones_db.Stone` | round / princess / oval … |
| Color / clarity / cut | `color_grade` / `clarity_grade` / `cut_grade` | `stones_db.Stone` | grading scales |
| Certificate | `cert_type` / `cert_id` / `cert_lab` | `stones_db.Stone` | GIA / IGI / HRD / SGL / none / other |
| HS/customs code | `hs_code` (line) / `hs_code_override` (`product_local`) | line + `product_local` | 6–10 digits |
| Country of origin | `origin_country` | `product_local` | default `IN` (India) |

**Detail panel render (per line, collapsed by default):**
`18K · yellow gold (750) · diamond 0.45 ct round · F/VS1 · GIA 2185… · HS 7113.19 · origin IN`

Editing these attributes is **Products V2 / metals / stones authority** (`GET/PUT /api/v1/metals/{code}`, `/api/v1/stones/{code}`), not the proforma. The proforma line shows them and lets the operator set the per-document **`hs_code`** (the one customs-critical field that legitimately belongs on the line).

### 6.2 Net-new attributes (NOT in backend — propose, don't fake)

| Wanted | Status | Recommendation |
|---|---|---|
| Per-line **gram weight** on the proforma | not a draft-line field | propose `weight_g` line field if customs needs per-line metal weight on the document |
| **Hallmark / assay** mark | no field | low priority; capture in `remarks` if needed |
| Per-line **karat** propagated onto the draft line | karat lives on product/packing layer only | derive for display from product authority; don't duplicate-store |
| **Diamond** as standalone product attribute | exists only as a `stone_type` value | keep as `stone_type`; no new field |

### 6.3 Why this matters for the line table

HS code + origin + purity are **customs-blocking** downstream (DHL self-clearance, SAD). Surfacing them on the line (read) and requiring `hs_code` before Post means the proforma is born customs-aware, which prevents the "wrong data generated → authority chain" class of incident (Lesson I). The line table's `⌄` detail is the single render of these values (no duplicate renderer).

---

## 7. Consolidated validation rules

| # | Field / rule | Rule | Enforced |
|---|---|---|---|
| V1 | Buyer | a customer must be selected (has `bill_to_contractor_id`) | Screen 1 → 2 gate |
| V2 | Ship-to alternate | if "alternate" chosen, name + street + city + country required | Screen 1 |
| V3 | `product_code` | non-blank | per line, Screen 2 |
| V4 | `qty` | numeric, > 0 | per line |
| V5 | `unit_price` | numeric, ≥ 0 | per line |
| V6 | `currency` (line) | ∈ {EUR,USD,PLN,GBP,CHF,JPY} | per line |
| V7 | ≥1 valid line | required to leave Screen 2 | Screen 2 → 3 gate |
| V8 | `hs_code` | 6–10 digits | warned Screen 2; **blocks Post** |
| V9 | Document currency | postable = PLN/USD/EUR | warned Screen 3; **blocks Post** |
| V10 | `payment_terms.days` | integer ≥ 0 | Screen 3 |
| V11 | VAT context | must resolve (not `ManualReviewRequired`) | warned Screen 3; **blocks Post** |
| V12 | Mixed currency | all lines should match document currency | warned Screen 2/3 |

Post-time blockers (V8/V9/V11) are deliberately **non-blocking during create** but surfaced early — the operator can build a draft and resolve customs/VAT before the gated Post. This matches backend authority: readiness/postability is computed server-side, never faked in JS.

## 8. Field → backend → API mapping

| UI field | Backend key | Create/edit API |
|---|---|---|
| Buyer | `client_name` + `bill_to_contractor_id` | blank-draft create (see §11) |
| Line product | `product_code` | `POST /api/v1/proforma/draft/{id}/lines` |
| Line qty/price/etc. | `qty`,`unit_price`,`currency`,`design_no`,`name_pl`,`client_ref`,`remarks`,`hs_code` | `PATCH /api/v1/proforma/draft/{id}/lines/{line_id}` |
| Remove line | — | `DELETE /api/v1/proforma/draft/{id}/lines/{line_id}` |
| Freight/insurance | `service_charges_json` | `POST/DELETE /api/v1/proforma/draft/{id}/service-charges` |
| Currency / FX / incoterm / insurance | `currency`,`exchange_rate`,`incoterm`,`insurance_eur` | `PATCH /api/v1/proforma/draft/{id}` |
| Payment terms / overrides / remarks | `payment_terms_json`,`buyer_override_json`,`ship_to_override_json`,`remarks` | `PATCH /api/v1/proforma/draft/{id}` |
| Customer lookup | read | `GET /api/v1/customer-master/` , `/{contractor_id}` |
| Product catalog | read | `GET /api/v1/proforma/product-options` |
| Jewellery specs | read | `GET /api/v1/metals/`, `/api/v1/stones/` |
| Hand-off | — | `POST …/approve`, `…/post` (existing Review surface) |

## 9. Component & `data-testid` inventory

| Surface | Component | testid |
|---|---|---|
| Stepper | custom (atoms) | `proforma-create-stepper` |
| Buyer search | `Sel`/combobox | `input-proforma-buyer-search` |
| Buyer result row | row | `proforma-buyer-option-{contractorId}` |
| Selected buyer | `CustomerAuthorityCard` | `proforma-buyer-card` |
| Add from catalog | `Btn primary` | `btn-proforma-add-from-catalog` |
| Catalog modal | `.modal-box` | `modal-product-catalog` |
| Catalog row | row + checkbox | `catalog-product-{code}` |
| Line row | `CompactTable` row | `proforma-line-{lineId}` |
| Line save | `Btn` | `btn-proforma-line-save-{lineId}` |
| Line remove | `Btn danger` | `btn-proforma-line-remove-{lineId}` |
| Totals rail | `Card` | `proforma-totals-rail` |
| VAT context | `Badge`/`GateBlock` | `proforma-vat-context` |
| Section headers | `SectionHeader` | `proforma-info-section-{n}` |
| Wizard actions | `Btn` | `btn-proforma-{step}-{action}` |

## 10. Authority & governance compliance

| Rule | How this design complies |
|---|---|
| **Lesson F** — one page = one domain | each screen owns one domain; customer/product/metals CRUD deep-link out, not in-page |
| **Lesson F** — no V1 renderer reuse | builds fresh against the layer spec; reuses only `dashboard-shared.js` atoms + existing draft APIs |
| **Lesson M** — capability visibility (5-state) | discount/VAT/currency limits shown as `available`/`backend-pending`/reasoned-disabled, never deleted or faked |
| **Save discipline** | no auto-save; every write labeled and explicit |
| **No fake readiness** | VAT/postability/HS gates are backend-derived and rendered read-only with reasons |
| **No wFirma write toggle** | Post stays behind existing backend gate on the Review surface; not exposed here |
| **Frozen valuation** | discount = effective unit price (Option A); no change to net→gross engine |
| **Backend truth first** | empty → `—`; all money via `fmtPLN`-style Decimal-safe formatting |

## 11. Backend gaps register (GATE 4 dispositions required)

| Gap | Impact | Recommended disposition |
|---|---|---|
| **No blank-draft create endpoint** (`POST /api/v1/proforma/draft` for a chosen customer, no batch) | the manual create flow needs to mint a draft not born from packing | **SCHEDULED** — thin additive endpoint reusing `ProformaDraft` + draft lifecycle |
| **No `discount_pct` line field** | brief asks per-line discount | **REJECTED for now** (frozen engine) → use Option A effective-price; revisit only with a DECISIONS entry |
| **No per-line tax-rate override** | brief asks per-row tax | **REJECTED** — VAT is document-level backend authority (`vat_resolver`); per-line override would fork customs truth |
| **No per-line `weight_g`** | possible customs need | **ISSUE** — file to evaluate whether SAD needs per-line metal weight on the proforma |

Each gap above is a Lesson-M / GATE-4 finding and must carry an explicit SCHEDULED / ISSUE / REJECTED disposition in `PROJECT_STATE.md` before implementation, not "noted."

## 12. Open questions for operator

1. **Manual create vs. packing-born only?** Confirm the business wants a fully manual proforma (no shipment/packing) — this determines whether the blank-draft endpoint (§11) is built.
2. **Discount:** accept Option A (effective unit price, recommended) or commit to a backend `discount_pct` change (engine unfreeze + regression)?
3. **Per-line gram weight** on the proforma — needed for customs, or is purity + HS code sufficient?
4. **New-customer inline:** keep deep-link to Customer Master (recommended, Lesson F) or allow a minimal inline create?
5. **Default issue date** — today, or operator-chosen, given the real value is assigned at Post?
