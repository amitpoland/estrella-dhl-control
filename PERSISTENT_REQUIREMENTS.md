# PERSISTENT_REQUIREMENTS.md

Cross-cutting invariants that every task must check before planning and verify before closing.
These are NOT negotiable per-feature — they apply globally to every `/feature`, `/bug`, and `/deploy` invocation.

Keep this list small. If it grows past ~10 entries, it stops being checked.

---

## ACTIVE requirements

| ID | Requirement | Rationale | Fail signal |
|---|---|---|---|
| PR-001 | **Product description format: Polish / English** | Customs filings require PL descriptions; packing lists and customer docs require EN. Mixed or missing language silently corrupts export compliance. | Any generator that produces a description without both `description_pl` and `description_en` fields, or truncates either to empty. |
| PR-002 | **Customer Master is the single authority for contractor identity** | Draft identity, charge collisions, and wFirma reservation keys all pivot on `client_contractor_id` resolved via Customer Master. Re-keying or bypassing this breaks the authority chain silently. | Any route that writes `client_name` or `client_contractor_id` onto a draft/sales/packing record from a source other than Customer Master or the batch shipment document. |
| PR-003 | **Search-first idempotency before any write** | Duplicate records in SQLite (drafts, sales docs, packing lines) are the most common cause of charge double-counting and audit ghost rows. Every write path must check for an existing record before inserting. | Any `INSERT` that is not guarded by a prior `SELECT` or `INSERT OR IGNORE` / `ON CONFLICT DO NOTHING` at the call site or in the owning `_db.py`. |
| PR-004 | **DHL ship-to address comes from Customer Master, not from shipment fields** | Ship-to fields on the batch are operator-editable and lag behind Customer Master. Using them directly has produced incorrect customs declarations. | Any DHL route or service that reads `shipment.recipient_address` or `batch.ship_to_*` without first checking `customer_master.ship_to_override`. |
| PR-005 | **Single authority ownership per domain — no dual-authority renders** | Two components displaying the same domain data from different sources creates split-brain UI. The operator cannot tell which value is correct. | Any V2 page that renders the same field (CIF, duty, status, contractor) from two different API endpoints simultaneously without an explicit reconciliation label. |

---

## How to use

### Pre-planning check (embedded in `/feature`)

1. Read this file.
2. For each active requirement, decide: does the task touch the domain this requirement protects?
3. If YES → include a verification step in the implementation plan.
4. If a requirement would be VIOLATED by the plan as designed → stop and explain before writing code.

### Pre-close verification (embedded in `/feature`)

For every requirement marked affected at planning time:
- Confirm the implementation is compliant.
- State the evidence (file + line or test name).
- If a violation exists → fix it before PR opens; do not record PASS without evidence.

---

## Requirement lifecycle

| Status | Meaning |
|---|---|
| ACTIVE | Enforced on every task |
| SUSPENDED | Temporarily paused (must state reason and resume date) |
| RETIRED | No longer applies (must state why — usually superseded by architecture change) |

Append-only. Do not delete entries; change status to RETIRED with explanation.

---

## Change log

| Date | Change |
|---|---|
| 2026-06-21 | Initial 5 requirements seeded (PR-001–PR-005) |
