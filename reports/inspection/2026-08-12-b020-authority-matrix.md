# B-020 — Authority matrix (consumer-side contractor)

**Tree:** `C:\PZ-main` @ `dbfd45f25b8725472f2b2b84a31e46b93c7b79b0` (+ branch `fix/b020-consumer-contractor-authority`)  
**Date:** 2026-08-12  

## Production evidence (RO)

| Observation | Count / note |
|---|---|
| Batches with >1 distinct `supplier_contractor_id` | 0 (today) — still unsafe under LIMIT 1 once multiparty intake lands |
| Batches with >1 distinct `client_contractor_id` | **13** |
| `awb` rows carrying supplier / client IDs | 20 AWBs; dsup=2, dcli=12 — **inherited identity**, not party authority |
| Authoritative supplier types | `purchase_invoice`, `purchase_packing_list` |
| Authoritative client types | `sales_packing_list` (+ sales invoice if present) |

## Matrix

| consumer | business operation | required party role | current query | canonical authority | multi-party behavior | failure impact | proposed disposition |
|---|---|---|---|---|---|---|---|
| `routes_dhl_clearance._resolve_customs_identities` | PDF consignor (customs) | **supplier / exporter** | `shipment_documents` `supplier_contractor_id != '' LIMIT 1` | purchase_* document slots (#1198) → suppliers master | picks arbitrary first non-empty (may be AWB inherit) | wrong consignor on customs PDF | **SAFE_TO_FIX:** resolve via document-party helper; 0→unresolved sentinel; >1→sentinel + log AMBIGUOUS; never AWB-only when purchase rows exist |
| `ai_reverification.build_masters_snapshot` | AI re-verify masters | supplier + client | two LIMIT 1 queries | same document slots + CM/suppliers | wrong master rows fed to AI | misleading advisory (non-fiscal) | **SAFE_TO_FIX:** same helper; AMBIGUOUS → leave row None |
| `rule_based_reverification.build_masters_snapshot` | rule re-verify masters | supplier + client | duplicate of AI LIMIT 1 | same | same | same | **SAFE_TO_FIX:** share helper with AI module |
| `carrier.doc_package._resolve_customer_from_batch` | MyDHL/doc package ship-to | **buyer / client** | name match then `client_contractor_id LIMIT 1` | sales packing document slot → customer master | wrong ship-to; name match before ID | wrong carrier party if used | **SAFE_TO_FIX:** contractor ID from helper **before** name; AMBIGUOUS→None (fail closed). HOLD live MyDHL payload change verification to non-live unit tests only |
| `intelligence_graph._resolve_supplier_contractor_id` | graph supplier node | supplier | LIMIT 1 | purchase_* docs | arbitrary supplier | wrong graph edge | **SAFE_TO_FIX:** DISTINCT; >1 → None / conflict like client path |
| `intelligence_graph._resolve_client_contractor_ids` | graph customer node | client | DISTINCT already | sales docs | returns list (conflict) | OK | **KEEP** — already fail-aware |
| `packing_contractor_resolution` consumers | packing/proforma seed | role-scoped UNIQUE(batch_id,role) | N/A batch seed | intake #1201 when merged | multiparty seed defect is intake | out of B-020 consumer scope | **HOLD / defer to #1201** — do not invent second seed authority |
| fiscal PZ `resolve_supplier_contractor_id_for_batch` | wFirma PZ supplier | supplier via **audit name → master** | not documents LIMIT 1 | suppliers master | name path | fiscal | **DO NOT TOUCH** — different authority; B-020 is documents consumers only |

## Role encoding (consumer boundary)

| Role | Document-type authority set | Column |
|---|---|---|
| `supplier` | `purchase_invoice`, `purchase_packing_list` | `supplier_contractor_id` |
| `client` | `sales_packing_list`, `sales_invoice` | `client_contractor_id` |

Inherited carriers (`awb`, `sad_pdf`, `pz_*`, …) are **not** batch-level party authority for B-020 resolution.

## Shared helper (existing documents.db — no new DB)

`service/app/services/document_party_authority.py`:

- `list_distinct_party_ids(docs_db, batch_id, role)`  
- `resolve_party_id(docs_db, batch_id, role, *, document_id=None)` → `NONE | SINGLE | AMBIGUOUS`  

On `document_id`: read that row only (document-specific contractor).  
Never `ORDER BY` + `LIMIT 1` to hide ambiguity.
