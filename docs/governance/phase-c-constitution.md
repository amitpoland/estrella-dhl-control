# EJ Dashboard Phase-C Constitution (Final)

> Extracted verbatim from CLAUDE.md on 2026-08-19 as part of the governance-thinning
> experiment. This file is the AUTHORITATIVE source of the operator's R4 wording.
> CLAUDE.md retains the binding summary and points here. Do not paraphrase this text.

---

## EJ Dashboard Phase-C Constitution (Final) — standing Phase-C preamble (operator-ratified 2026-07-03, VERBATIM R4)

> The text below is the operator's exact wording (R4 — not reconstructed, not
> paraphrased). It is the governing preamble for all Phase-C work.

**EJ Dashboard Phase-C Constitution (Final)**

**0. Mission**
Implement only inside the existing EJ Dashboard architecture. The objective is not to create software. The objective is to extend the existing business system without introducing any new authority.

**1. Existing Authorities (Immutable)**
Claude must first identify the authority before writing a single line of code. There are only these authorities.
wFirma → (API / Webhook) → Mirror Layer → EJ Dashboard Masters (Product Master, Customer Master, Warehouse, Invoice, Packing, Inventory) → All business modules
Nothing is allowed to bypass this chain.

**2. Product Authority**
This is now fixed forever.
wFirma Product → Product Mirror (sync only) → Product Master (EJ Dashboard authority) → Inventory, Reservation, Packing, Invoice, Sample, Consignment, Returns
Inventory MUST NEVER read directly from wFirma.

**3. Customer Authority**
wFirma Customer → Customer Mirror → Customer Master → Inventory, Invoice, Packing, Consignment, Returns
Inventory must never call wFirma customer APIs.

**4. Design Number Rule (NEW)**
Product Code remains the immutable system identifier. Design Number becomes the business identifier. Mapping: Product Code → Design Number. Product Master owns this mapping. Only Product Master may edit it. Everything else reads it. No module may maintain another Design Number table.

**5. wFirma Custom Field Rule**
The new custom field created inside wFirma becomes the sync source. Example: Product Code ABC001 → Custom Field Design Number = RG-10025 → Mirror → Product Master → Inventory. Inventory never asks wFirma for Design Number. It always comes through Product Master.

**6. Product Master Structure**
Minimal authority: wFirma ID, Product Code, Design Number, Status, Sync Version, Last Sync, Active. No duplicated business information. No second master.

**7. Customer Master Structure**
Existing Customer Master remains authority. Mirror only synchronizes. No new customer tables. No duplicate cache.

**8. Warehouse Documents**
These stay inside wFirma: PZ, WZ, MM, Warehouse, Invoice. The app mirrors them. The app never becomes the fiscal authority.

**9. Sample Workflow**
Main Warehouse → MM → Sample Warehouse → Customer → Return → MM → Main Warehouse. Every movement produces a document. Inventory stores workflow state. wFirma stores warehouse documents.

**10. Consignment Workflow**
Main Warehouse → MM → Consignment Warehouse → Customer. Monthly: Customer reports sold items → Select sold pieces → Create Invoice → Invoice creates WZ only from Consignment Warehouse. No second WZ from Main Warehouse. This permanently removes the double-WZ problem.

**11. Product Selection**
Never type IDs. Never paste IDs. Always: Customer → Product → Design Number → Checkbox → Execute. Barcode remains optional. Search remains optional.

**12. Inventory UI**
Inventory UI is exactly the supplied wireframe. Never redesign. Never simplify. Never invent. Wireframe is the UI authority.

**13. Existing Pages Rule**
No new pages. Never. If functionality belongs to Inventory, extend Inventory. Do not create Inventory2, MoveStockPage2, SamplePage2, ProductPage2. Everything extends the existing authority page.

**14. Existing Backend Rule**
No duplicate services. No duplicate APIs. No duplicate routes. No duplicate mirrors. Extend existing services.

**15. Authority Violation**
Immediately STOP if code does this: Inventory → wFirma API. Correct path: Inventory → Product Master → Mirror → wFirma.

**16. Implementation Order (Locked)**
1. Product Master Authority → 2. Customer Master Authority → 3. Reservation → 4. Inventory → 5. Sample → 6. Consignment → 7. Returns → 8. Invoice Selection → 9. MM Integration → 10. Webhook Synchronization. Nothing may skip this order.

**17. Scope Rules**
Every slice must declare: Authority owner, Existing page, Existing API, Existing DB, Existing service. If any of these cannot be identified, STOP.

**18. No Creativity Rule**
Claude must not invent architecture, invent workflow, invent fields, invent tables, invent pages, invent APIs. If information is missing, STOP.

**19. Research Rule**
If work involves wFirma, Claude must search wFirma API documentation, webhook documentation, existing repository, existing mirror — before proposing code. Never guess a wFirma capability.

**20. Final Rule**
Before writing code Claude must prove: This feature extends EXISTING AUTHORITY → EXISTING PAGE → EXISTING SERVICE → EXISTING DATABASE → EXISTING API. If any arrow cannot be proven, STOP and ask.

**Application Authority Rule**
The EJ Dashboard application is the operational authority. wFirma is an external ERP. Claude must always start by identifying which existing EJ Dashboard module owns the business process. The implementation must extend that module. It must never start from wFirma and build inward. It must start from the existing EJ Dashboard authority and extend outward to wFirma only through the approved sync layer.

**Advisor reconciliation (NOT operator text — advisor notes, recorded 574a6932):**
(a) §6 = the LOGICAL view of the product authority; the physical layering stays as built (Mirror = the six sync fields only; Master = business fields incl. status / is_active). Reversible on operator word. (b) §16 mapping to execution: step 1 (Product) = C-1a..C-1d; step 2 (Customer) = C-2; steps 3–10 renumber the old queue (MM = step 9, Webhook Sync = step 10). (c) §4/§5 Design Number custom-field sync = NEW scope, gated on OPERATOR-INPUT (field created in wFirma + its API name + whether the goods API returns custom fields — wFirma email item #3, after MM (#1) and contractor_id (#2)); §19 research rule applies.

---
