# Canonical Proforma Setup Reader Contract (C26)

**Status:** ACTIVE
**Established:** 2026-05-21
**Origin:** C25A authority-divergence incident (PR #251)
**Owners:** `backend-api`, `system-architect`, `backend-safety-reviewer`
**Enforcement:** `service/tests/test_c26_reader_contract_enforcement.py`

---

## 1. Why this contract exists

On 2026-05-20, `/setup-detail` reported `products.missing_count=0` while
`/proforma-readiness` reported `products.missing_count=12` for the same
batch. Two endpoints in the same domain answered the same question with
two different sources of truth:

| Endpoint | Reader used | Result |
|---|---|---|
| `/dashboard/batches/{id}/proforma-readiness` | `get_invoice_lines_for_batch` | 12 missing ✓ |
| `/wfirma/shipment/{id}/setup-detail` | `query_sales_to_wfirma` (TEMP VIEW) | 0 missing ✗ |

The TEMP VIEW (`v_sales_to_wfirma`) joined `sales_packing_lines × packing_lines`
on `batch_id`; for batches where the join keys diverged, the join returned
zero rows. The endpoint reported "no missing" while invoice_lines clearly
had 12 unmapped product codes. A panel showing "0 missing" when 12 are
missing is worse than no panel — it produces false confidence and the next
operator decision builds on a phantom state.

**The lesson is not "fix the view."** The lesson is that two readers
answering the same domain question is a structural bug, regardless of
which one is right today. This contract makes the authority assignment
explicit and pins it with source-grep tests so the divergence cannot
silently recur.

---

## 2. Canonical reader map

Each row below is binding. **One domain → one canonical reader.** Any new
endpoint that answers the same domain question MUST consume the canonical
reader (or an adapter built on top of it), never re-derive the data from a
sibling source.

| Domain | Question answered | Canonical reader | Module | Notes |
|---|---|---|---|---|
| **Product codes per batch** | What product codes does this batch's invoice contain, with quantity + total_value? | `get_invoice_lines_for_batch(batch_id)` | `service/app/services/document_db.py` | Source of truth for product authority. Aggregated by `product_code` at the reader site, not at the endpoint. |
| **Product mapping state** | Is product code `X` mapped to a wFirma product_id with `sync_status='matched'`? | `wfirma_db.get_product(code)` OR `wfirma_db.get_products_batch(codes)` | `service/app/services/wfirma_db.py` | Per-code or bulk lookup. Both forms acceptable. Do NOT bulk-SELECT from `wfirma_products` inline in a route. |
| **Packing-line enrichment** | What is the `design_no` / `item_type` for a product code in this batch? | `get_packing_lines_for_batch(batch_id)` | `service/app/services/packing_db.py` | **Best-effort enrichment only.** Never authoritative for product list. |
| **Customer set — pre-draft** | What customers does this batch need mapped BEFORE drafts exist? | `sales_documents.client_name` (fallback `sales_packing_lines.client_name`), resolved via `wfirma_customer_auto_resolve._resolve_local` | `service/app/api/routes_dashboard.py` (`proforma_readiness`) | Lifecycle stage A — used by `/proforma-readiness`. |
| **Customer set — post-draft** | What customers are referenced by drafts that already exist? | `proforma_links_db.list_drafts_for_batch(batch_id)` + `customer_master.sqlite` + `wfirma_db.get_customer_by_name` | `service/app/api/routes_wfirma_capabilities.py` (`shipment_setup_detail`) | Lifecycle stage B — used by `/setup-detail`. |
| **Customer mapping state** | Is client name `Y` mapped to a wFirma `customer_id`? | `wfirma_db.get_customer_by_name(name)` (or `get_customer(name)`) | `service/app/services/wfirma_db.py` | Per-name lookup. |
| **Customer master records** | What `customer_master` rows exist for this org? | `customer_master_db.list_customers(path)` | `service/app/services/customer_master_db.py` | Local CRM-style identity store. |
| **Draft list per batch** | What proforma drafts exist for this batch? | `proforma_links_db.list_drafts_for_batch(batch_id)` | `service/app/services/proforma_links_db.py` | Source of truth for draft existence + draft_id. |
| **PZ prerequisite state** | Is the batch ready for PZ creation in wFirma? | `proforma_readiness` PZ section (which reads `pz_rows_json_present`, `wfirma_pz_doc_id`, etc. directly from `documents.db`) | `service/app/api/routes_dashboard.py` | Authority for PZ readiness gate. |
| **Posting readiness verdict** | Can this batch be posted to wFirma right now? | `proforma_readiness` `proforma.ready` + `blocking_reasons` | `service/app/api/routes_dashboard.py` | This is the gate. `/setup-detail` MAY surface the same verdict but MUST NOT compute a different one. |

### Lifecycle clarification — customers are intentionally split

The customer reader is split because the two endpoints answer DIFFERENT
questions at different lifecycle stages:

- **`/proforma-readiness`** asks: "Before any draft exists, which customers
  from the SALES side of this batch need to be mappable?" → reads
  `sales_documents` (the operator-validated client list).
- **`/setup-detail`** asks: "Given the drafts that already exist for this
  batch, which customers do those drafts reference?" → reads
  `proforma_drafts`.

Both readers MUST agree on a customer's mapping status if both happen to
list the same customer. They MAY legitimately list different customer sets
(stage A has no drafts; stage B has drafts whose `client_name` may have
been edited by the operator).

A future V2 page that needs a unified customer view across both stages
MUST consume both canonical readers and merge — not introduce a third
reader.

---

## 3. Forbidden reader patterns

These patterns are banned for the named domains. Each is enforced by a
source-grep test in `test_c26_reader_contract_enforcement.py`.

### 3.1 Product authority must not use `query_sales_to_wfirma`

`document_db.query_sales_to_wfirma` queries the TEMP VIEW
`v_sales_to_wfirma`, which joins `sales_packing_lines × packing_lines` on
`batch_id`. For batches where the join keys diverge, this returns zero
rows — the C25A failure mode. The view may exist for other purposes, but
**MUST NOT be called as the product authority** by any setup / readiness
endpoint.

**Banned call site:** any function in `routes_wfirma_capabilities.py` or
`routes_dashboard.py` whose name contains `setup_detail`, `readiness`, or
`proforma_*`.

**Allowed:** comment references documenting the C25A history are fine.
The forbidden-pattern check excludes comment-only lines.

### 3.2 Product set must not be derived from `packing_lines` alone

`get_packing_lines_for_batch` is **enrichment only** (design_no,
item_type). It is NOT the product authority because:

- Not every product_code in `invoice_lines` has a matching `packing_lines`
  row (sample lines, return-of-goods, freight-line products).
- Packing lines can outlive the invoice (operator edits a packing list
  after invoice issuance).

Setup / readiness endpoints MUST start from `get_invoice_lines_for_batch`
and join `get_packing_lines_for_batch` as enrichment, never the inverse.

### 3.3 No inline SQL against `sales_packing_lines × packing_lines`

Inline JOINs that re-implement the `v_sales_to_wfirma` view inside a
route handler reintroduce the C25A divergence in disguise. Use the
canonical readers above; if you need a new join, add it to
`document_db.py` as a named function with its own contract entry here.

### 3.4 Posting-readiness verdict must come from `proforma_readiness`

The boolean "can this batch post to wFirma right now?" is a single
domain question. `/setup-detail` may surface a subset of the gate
information (which fields are missing, which blockers are open) but
MUST NOT compute a separate `ready: True/False` from local state.

### 3.5 V2 / future panels: adapter rule

Any new endpoint or panel that displays product / customer / readiness
information for the proforma flow MUST:

1. Consume one of the canonical readers above directly, OR
2. Consume an adapter function defined in the same module as the
   canonical reader, OR
3. Register a new canonical reader here (with a corresponding test) and
   delete or wrap the prior reader in the same PR.

A new endpoint that defines its own reader without updating this contract
is a contract violation and will be blocked at code review.

---

## 4. Test coverage

Enforcement file: `service/tests/test_c26_reader_contract_enforcement.py`

Each contract row above has at least one source-grep test that:

- Asserts the canonical reader is called by the named endpoint.
- Asserts the forbidden readers are NOT called by the named endpoint
  (with comment-only lines excluded).

Tests are append-only with respect to existing C25A enforcement
(`test_c25a_data_fix_product_source.py`); this contract widens the
guardrail without replacing prior pins.

---

## 5. Out of scope

This contract is read-authority only. It does **not**:

- Authorize any write path
- Change any fiscal gate (`_guard_wfirma_export`, `WFIRMA_CREATE_*` flags)
- Change DB schema
- Change DHL / orchestrator / queue logic
- Change parser arithmetic
- Specify UI rendering rules (see `.claude/skills/frontend-design.md`)

---

## 6. Amending this contract

Adding a new canonical reader requires:

1. Append a row to §2 with module path + notes.
2. Add the matching enforcement test in
   `test_c26_reader_contract_enforcement.py`.
3. Note the addition in `PROJECT_STATE.md` FACTS.
4. PR review by `system-architect` + `backend-safety-reviewer`.

Removing or replacing a canonical reader requires:

1. The same three steps above (replacement reader registered).
2. Migration plan in the PR description listing every endpoint that
   currently calls the old reader.
3. The replacing PR MUST update all call sites in one commit — partial
   migration of a canonical reader is forbidden (that is exactly how
   C25A happened).

---

## 7. Reference

- C25A incident root cause: `service/tests/test_c25a_data_fix_product_source.py` docstring
- C25A regression scope fix: PR #250 (sha `d819b24`)
- C25A data authority fix: PR #251 (sha `403fb5c`)
- Related ADR: ADR-018 (single-authority invariant)
- Engineering Lesson A: real-builder return-shape rule
