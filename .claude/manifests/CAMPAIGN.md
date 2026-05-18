# Commercial Document Platform — Campaign Manifest
**Campaign slug:** `commercial-doc-platform`
**Branch:** `feat/commercial-document-platform`
**Started:** 2026-05-18
**Status:** ACTIVE — Phase 1 in progress

---

## Architecture Pillars

| Layer | Role | Storage | Owner |
|---|---|---|---|
| Operational shipment | AWB, carrier, audit.json | audit.json / document_db | batch pipeline |
| Master/defaults | CustomerMaster, product_descriptions, product_local, hs_codes | master_data.sqlite / documents.db | operator |
| Company profile | Seller identity, bank IBANs, legal boilerplate | master_data.sqlite (company_profile table) | operator |
| AI enrichment | name enrichment, HS code suggestions | editable_lines_json, product_descriptions | assistive only |
| Snapshot engine | ProformaDraft, editable_lines_json | proforma_links.db | system |
| Readiness engine | draft_state machine | proforma_drafts.draft_state | system |
| Renderer | preview.html, PDF path | routes_proforma.py | renderer |
| wFirma bridge | accounting, doc number, issue_date | wfirma_client.py | wFirma authority |

## Critical Rules (binding on all agents)

1. Preparation flows stay open — draft creation never fails due to missing optional fields.
2. Only irreversible actions are gated — posting to wFirma, converting to invoice.
3. wFirma is accounting authority only — owns doc number, issue_date, payment_due. We store snapshots; we do not set them.
4. Estrella owns commercial orchestration — seller block, shipment block, bank details are LOCAL.
5. Snapshot freezes commercial truth — once posted, ProformaDraft fields are immutable.
6. AI is assistive only — enrichment suggestions must be operator-reviewable; never auto-applied post-posting.
7. Use PL + EN descriptions only in this phase — no SK yet (Phase 4 deferred).
8. 22 shipments are reference corpus, not system limit — schema must accept arbitrary batch_ids.
9. Future unknown shipment formats must remain ingestible — no hard-coded shipment format assumptions.

## GATE: Max 3 simultaneous coding agents at any time.
## GATE: Freeze interfaces before dispatching parallel lanes.
## GATE: Research agents are inspection-only.

---

## Phase Map

### Phase 1 — Data Foundation (CURRENT)
**Parallel:** Lane 1-A (company_profile) + Lane 1-B (ProformaDraft schema)

Lane 1-A deliverables:
- `CompanyProfile` dataclass in `master_data_db.py`
- `company_profile` table (additive ALTER, single-row, `master_data.sqlite`)
- `get_company_profile()` + `upsert_company_profile()` service functions
- `GET /api/v1/settings/company-profile` + `PATCH /api/v1/settings/company-profile`
- Seed script: populate from known wFirma company_account IDs
- Tests: `test_company_profile_db.py` + `test_routes_settings.py`

Lane 1-B deliverables:
- `ProformaDraft` 4 new fields: `fx_rate_date`, `fx_rate_source`, `incoterm`, `insurance_eur`
- `_ADDITIVE_DRAFT_COLUMNS` additions in `_ensure_drafts_table()`
- `proforma_draft_sync.py` populates `fx_rate_date` + `fx_rate_source` at draft creation
- Tests: migration safe (existing drafts get None/default)

**Interface contract frozen at Phase 1 end:** `INTERFACE_CONTRACTS.md`

### Phase 2 — Renderer Completion
**Parallel:** Lane 2-A (preview.html) + Lane 2-B (dashboard UI wiring)
- Depends on: Phase 1 complete

Lane 2-A deliverables (preview.html renderer):
- Seller block (reads company_profile)
- Bank details (EUR/USD/PLN IBANs + SWIFT from company_profile)
- PLN reference total row (exchange_rate × grand_total)
- fx_rate_date + fx_rate_source display
- Shipment block (AWB + carrier + clearance_path read-through from audit.json)
- name_en column in line table
- HS code column in line table
- Tax code label per line (from document-level VAT context)
- incoterm, insurance_eur display
- Conditional doc number (shows wfirma_proforma_fullnumber if posted)

Lane 2-B deliverables (dashboard UI):
- Wire preview button → `GET /api/v1/proforma/draft/{id}/preview.html`
- incoterm selector (per draft)
- insurance_eur input (per draft)

### Phase 3 — wFirma Post-Posting Enrichment
- `company_accounts/get/{id}` client function → fetch real IBANs at seed time
- Post-posting: fetch issue_date, payment_due, payment_method from `invoices/get/{id}`
- Store in 3 new ProformaDraft columns: `wfirma_issue_date`, `wfirma_payment_due`, `wfirma_payment_method`
- Renderer shows these when posted

### Phase 4 — Product Data Extensions
- `product_local.origin_country` column + seed 'IN' for all current products
- `product_descriptions.name_sk` column (nullable, operator-populated)
- HS code resolution logic in draft sync: product_local → designs → product_master priority order
- Store resolved code in `editable_lines_json[].hs_code`

### Phase 5 — Shipment Capture Hardening
- Persist `service_product` + `dimensions` from carrier API response to `carrier_shipments`
- Expose in ProformaDraft shipment block when available

---

## Scorecard targets (per phase)
- Zero regressions on existing test suites (PZ 160/160, carrier 366/366)
- New tests: min 10 per phase
- No wFirma write calls during draft/preview operations
- No post-posting mutation of frozen fields
