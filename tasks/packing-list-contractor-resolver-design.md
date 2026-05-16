# Packing-list contractor resolver — design

**Status:** Design / inspection only. **No code in this PR.**
**Date:** 2026-05-17
**Production SHA at design time:** `fbd2159`
**Foundation in place (do not re-design):**
- PR #154 — Client Master deep-fetch verified XML
- PR #155 — Client Profile UI bound + 11-country generic
- PR #156 — Bulk re-sync of 21 client rows (0 violations)
- PR #158 — Live wFirma `series/find` refresh
- PR #159 — Supplier Master symmetric deep-fetch

The local identity-cache foundation is complete. **This document
defines the resolver that consumes that foundation.** It does NOT
specify the consumer of the resolver (proforma posting, PZ flow,
DHL/customs) — those remain out of scope per the permanent hard
stops.

---

## Phase 1 — Existing packing-list flow (mapped against current code)

### Upload entry point
- `POST /api/v1/packing/upload` (`service/app/api/routes_packing.py:299` —
  `upload_packing_list`). Operator uploads `.xlsx` or `.pdf`; parser
  extracts line items + a best-effort client-name guess.

### Client / customer extraction today
Currently `routes_packing.py` performs a heuristic guess only:
- **`_guess_client_from_filename`** (line 637): parses filename like
  `"148 Client SUOKKO.xlsx"` for a "Client" or "Cilent" token.
- **`_guess_client_from_preamble`** (line 683): scans the top 12 rows
  of the Excel preamble for `Client:` / `Consignee:` / `Buyer:` /
  `Ship To:` regex (line 632).
- The matched string is surfaced as `suggested_client_name` (line 750)
  in `get_packing_documents()`. Operator confirms / overrides via
  `link_packing_as_sales` (line 803).

### Supplier / exporter extraction today
- **Not extracted from packing list.** Estrella ships out of one
  exporter today (the operator's company in wFirma); supplier
  identity flows from the SAD / ZC429 customs document, not the
  packing list.
- `document_db.py` schema carries `exporter_name` (SAD line 141) and
  `shipper_name` / `consignee_name` (AWB line 163) for inbound customs
  documents — those are an ADJACENT identity surface, not the packing
  list.

### Storage
- `packing_documents` and `packing_lines` (in `packing_db.py`) — store
  the parsed line items and the operator-chosen `client_name` once
  `link_packing_as_sales` lands.
- **No structured contractor-resolution table exists today.** All
  identity is a free-form `client_name` string per document.

### Existing matching helpers
Limited. The system has:
- `normalise_client_name()` in `wfirma_customer_sync.py` — used for
  the wFirma identity cache.
- `customer_master_db.get_customer(db, contractor_id)` — direct
  primary-key lookup.

**No fuzzy / score-based matching helper exists.**

---

## Phase 2 — Data sources available to the resolver

### Source A — Packing list parsed data
| Field | Availability today | Notes |
|---|---|---|
| Client / buyer name (free-form string) | YES | from filename or preamble regex |
| Consignee name | Sometimes | preamble regex matches `Consignee:` |
| Ship-to address | Rare | format varies wildly across operator files |
| Buyer tax ID | NO | not in packing list shape today |
| Buyer country | Sometimes | preamble or filename context |
| Supplier / exporter name | NO | not on the packing list at all |
| Invoice / proforma number | YES | `invoice_no` per line |

**Implication:** the resolver can only match the CLIENT side from
packing-list data. The supplier side is supplied by the operator
when they pick the shipment exporter (Estrella in practice) or by
the SAD/ZC429 customs document (a separate identity flow that already
populates `document_db.exporter_name`).

### Source B — Client Master (`customer_master.sqlite`)
| Field | Use in resolver |
|---|---|
| `bill_to_name` | primary normalised-name match key |
| `nip` | exact tax-id match (PL) |
| `vat_eu_number` | exact tax-id match (EU non-PL) |
| `country` | name-disambiguation |
| `bill_to_contractor_id` | wFirma identity key |
| `bill_to_email` / `bill_to_phone` | evidence-only (no match) |
| `bill_to_street/city/postal_code` | tie-breaker for ambiguous names |
| existing `short_code` | operator alias |

26 rows today, 11 countries. Production-tested generic across
PL/GB/FI/SE/LV/FR/EE/BE/NO/CZ/NL/IN/DE.

### Source C — Supplier Master (`suppliers.sqlite`)
| Field | Use in resolver |
|---|---|
| `wfirma_id` | wFirma identity key |
| `name` + `country` | normalised-name match |
| `vat_id` | exact tax-id match |
| `street/city/postal_code` | tie-breaker |
| `supplier_code` | operator alias |

4 rows today, all IN-based exporters (Estrella + 3 manufacturers).

### Source D — wFirma contractor cache (read-only)
- Used as the source-of-truth for identity verification AT ASSIGN
  TIME. The resolver does NOT call wFirma live during packing
  upload by default — Client Master + Supplier Master are sufficient.
- Live wFirma is available as an OPTIONAL "re-fetch this contractor"
  affordance the operator can trigger inside the resolver UI.

---

## Phase 3 — Resolver matching tiers

Deterministic, ordered. Higher tier wins. Each tier emits a
**confidence** score, a **reason** string, and an **evidence** field
set. The resolver returns the highest-scoring tier verdict per
contractor role (client + supplier).

### Tier 1 — exact wFirma ID
- **Match key:** the parsed value matches an existing master row's
  `bill_to_contractor_id` (client) or `wfirma_id` (supplier).
- **Confidence:** 1.00
- **Reason:** `"wfirma_id_exact"`
- **Evidence:** `wfirma_id`
- **Trigger:** rare from packing lists (operator-entered alias or
  paste). Always wins when present.

### Tier 2 — exact tax / VAT ID
- **Match key:** `nip == parsed_tax_id` OR `vat_eu_number == parsed_tax_id`
  (client) OR `vat_id == parsed_tax_id` (supplier).
- **Confidence:** 0.95
- **Reason:** `"tax_id_exact"`
- **Evidence:** `tax_id` + matched master row
- **Trigger:** when packing list carries a tax id (rare today, but
  the design must support it).

### Tier 3 — exact normalised name + country
- **Match key:** `normalise(name) == normalise(master.bill_to_name)`
  AND `country == master.country`.
- **Normalisation:** lowercase, strip diacritics, collapse whitespace,
  drop legal-form suffixes (`Sp. z o.o.`, `LLP`, `GmbH`, `LTD`,
  `Pvt. Ltd.`, `OY`, `AB`, `S.R.O.`, etc.).
- **Confidence:** 0.85
- **Reason:** `"name_plus_country_exact"`
- **Evidence:** parsed name, normalised key, country
- **Trigger:** the most common path for operator-recognised clients.

### Tier 4 — alias / known mapping
- **Match key:** `parsed_name == short_code` (Client Master) or
  `parsed_name == supplier_code` (Supplier Master). Also matches a
  future explicit `client_aliases` table if the operator wants to
  curate.
- **Confidence:** 0.80
- **Reason:** `"alias_exact"`
- **Evidence:** alias source field, master row
- **Trigger:** filename short codes (`SUOKKO.xlsx` → match
  `short_code='SUOKKO'`). Powers the existing filename heuristic
  cleanly inside the resolver model.

### Tier 5 — fuzzy name with country support
- **Match algorithm:** RapidFuzz `token_set_ratio` (or `partial_ratio`
  fallback) on the normalised names. Country must match exactly.
- **Confidence:** `min(0.70, score/100)` (capped at 0.70 so it never
  beats an exact tier).
- **Threshold:** ratio ≥ 85 to be returned at all; ratio < 85 falls
  through to Tier 6.
- **Reason:** `"fuzzy_name_country"` with the score embedded.
- **Evidence:** parsed name, master candidate name, ratio.
- **Trigger:** typo handling ("Suokko" vs "SUOKKO" — handled cleanly;
  "Suoko" missing-letter — handled with score).

### Tier 6 — unresolved
- No match passes Tier 5 threshold. Resolver returns a list of
  **top 5 candidates** ranked by Tier 5 score (regardless of
  threshold) and marks `status = "unresolved"`.
- **Confidence:** 0.00
- **Reason:** `"no_match"`
- **Evidence:** parsed name, parsed country, top-5 fuzzy candidates
  with their scores.
- **UI:** operator chooses from the top-5 dropdown OR clicks
  "Open Client Master" to inspect, OR explicitly creates a new master
  row.

### Tier-output schema

Each resolution emits exactly one verdict:

```python
{
  "role":              "client" | "supplier",
  "parsed_name":       str,
  "parsed_tax_id":     Optional[str],
  "parsed_country":    Optional[str],
  "tier":              1 | 2 | 3 | 4 | 5 | 6,
  "confidence":        float,            # 0.00 - 1.00
  "reason":            str,              # short snake_case
  "matched_master_type": "client_master" | "supplier_master" | None,
  "matched_master_id":   Optional[int],
  "matched_wfirma_id":   Optional[str],
  "evidence":          dict,
  "candidates":        list[dict],       # top-5 fuzzy, even for high-tier matches
                                          # — gives operator the override choice
  "status":            "auto" | "unresolved",   # auto = tier 1-4 win, unresolved = tier 5/6
}
```

`status = "auto"` does **NOT** mean the assignment is locked-in —
operator can still override via the UI. It only means the resolver
is confident enough to pre-select a row.

---

## Phase 4 — Operator UX

### Packing upload screen — new "Contractor resolution" panel

Inserted between "Parsed lines" and "Confirm sales draft" steps.

```
┌─ Contractor resolution ─────────────────────────────────────────┐
│                                                                 │
│ CLIENT (from packing list)                                      │
│  Parsed name:  SUOKKO                              [parsed: PL] │
│  ┌─ Suggested match ────────────────────────────────────────┐   │
│  │ ● SUOKKO  ·  PL  ·  bill_to_contractor_id=145067816      │   │
│  │   wFirma  ·  Tier 1 wfirma_id_exact                      │   │
│  │   confidence 1.00                                        │   │
│  │   [Use this match]  [Open Client Master]                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│  Override:   [▼ select another Client Master row]               │
│              [+ Create new from parsed data]   (requires confirm) │
│                                                                 │
│ SUPPLIER (from operator selection — wFirma exporter)            │
│  Active exporter:  ESTRELLA JEWELS LLP. (38142296)              │
│  Override:   [▼ pick another Supplier Master row]               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Per-suggestion controls

- **Use this match** — confirms the auto-pick; saves to
  `packing_contractor_resolution` (see Phase 5).
- **Open Client Master / Open Supplier Master** — opens the existing
  KYC modal so the operator can verify identity before confirming.
- **Override dropdown** — top 5 candidates + a free search field.
- **"+ Create new from parsed data"** — disabled by default. Click
  shows a confirmation modal with the parsed name / country / address.
  Operator must explicitly tick "Yes, create this client in Client
  Master from packing-list data". Creates a minimum-identity row via
  the existing `PUT /api/v1/customer-master/{contractor_id}` route
  with `bill_to_contractor_id` set to a synthetic placeholder until
  the operator assigns the real wFirma id. **No wFirma write.**

### Confidence badge

| Tier | Badge | Colour |
|---|---|---|
| 1 — wfirma_id_exact | `wFirma ID` | green |
| 2 — tax_id_exact | `Tax ID` | green |
| 3 — name+country | `Name + Country` | green |
| 4 — alias | `Alias` | amber |
| 5 — fuzzy | `Fuzzy ${score}%` | amber |
| 6 — unresolved | `Operator review` | red |

### Hard UX rules

- **No automatic creation on upload.** The resolver never inserts a
  Client Master or Supplier Master row unless the operator clicks
  "Create new" and confirms.
- **No PZ / proforma generation** until the resolver verdict for
  CLIENT is `status="auto"` OR the operator confirms an override.
- **Operator override is always available** even when confidence=1.00.
- **Every override is audit-logged** (Phase 5 column `operator_override`
  + timestamps).

---

## Phase 5 — DB / model proposal (no migration yet)

### New table — `packing_contractor_resolution`

One row per (batch, role) pair. Lives alongside `packing_documents`
in the same `packing_documents.sqlite` (or a new
`packing_resolutions.sqlite` if file-size concerns appear — TBD at
implementation).

```sql
CREATE TABLE IF NOT EXISTS packing_contractor_resolution (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id              TEXT NOT NULL,
    role                  TEXT NOT NULL CHECK (role IN ('client','supplier')),
    parsed_name           TEXT NOT NULL,
    parsed_tax_id         TEXT,
    parsed_country        TEXT,
    matched_master_type   TEXT,           -- 'client_master' | 'supplier_master' | NULL
    matched_master_id     INTEGER,        -- FK soft-ref to customer_master.id or suppliers.id
    matched_wfirma_id     TEXT,
    tier                  INTEGER NOT NULL,  -- 1..6
    confidence            REAL NOT NULL,     -- 0.00 - 1.00
    reason                TEXT NOT NULL,
    evidence_json         TEXT,              -- JSON blob, parsed-name/normalised-name/etc.
    candidates_json       TEXT,              -- top-5 fuzzy candidates
    status                TEXT NOT NULL CHECK (status IN ('auto','unresolved','confirmed','overridden')),
    operator_override     INTEGER NOT NULL DEFAULT 0,  -- bool: did operator change the auto pick?
    operator_user         TEXT,
    operator_at           TEXT,              -- ISO timestamp
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE (batch_id, role)
);
CREATE INDEX IF NOT EXISTS idx_pcr_batch    ON packing_contractor_resolution (batch_id);
CREATE INDEX IF NOT EXISTS idx_pcr_role     ON packing_contractor_resolution (role);
CREATE INDEX IF NOT EXISTS idx_pcr_status   ON packing_contractor_resolution (status);
CREATE INDEX IF NOT EXISTS idx_pcr_wfirma   ON packing_contractor_resolution (matched_wfirma_id);
```

### Soft-reference rules
- `matched_master_id` is a SOFT reference. No SQL FK to
  `customer_master.id` / `suppliers.id` (consistent with the
  existing master-data pattern). If the operator hard-deletes a
  master row, the resolution row stays — the application surfaces
  it as `status='unresolved'` on next read.
- `matched_wfirma_id` is the durable identity anchor (wFirma ids
  are immutable in practice).

### Migration plan
- Additive table only. No changes to `packing_documents` /
  `packing_lines` / `customer_master` / `suppliers`. **Zero
  destructive migration.**
- The legacy `packing_documents.client_name` free-form string stays
  as-is; the resolver row is the canonical source going forward.

---

## Phase 6 — Safety rules

| # | Rule | Enforcement |
|---|---|---|
| 1 | No live wFirma call during packing upload (by default) | Resolver consults `customer_master.sqlite` + `suppliers.sqlite` only. Live re-fetch is an explicit operator click. |
| 2 | No automatic Client/Supplier creation | "Create new from parsed data" requires explicit confirmation modal. Tracked via `operator_override` + reason. |
| 3 | No PZ / proforma generation until resolver confirms client | Downstream consumers (proforma posting, PZ flow) must read `packing_contractor_resolution.status IN ('auto','confirmed','overridden')` — never act on `unresolved`. |
| 4 | No master-record overwrite from packing list | Resolver READS the master tables; it never writes to them. The only path that creates a master row is the explicit operator "Create new" action, which uses the existing PUT endpoints. |
| 5 | Operator override is audit-logged | `operator_user`, `operator_at`, `operator_override` columns capture every change. |
| 6 | No wFirma write | Hard. Verified by source-grep test in the implementation PR. |
| 7 | No DHL/customs/finance/proforma flow change in resolver scope | The resolver lives in `service/app/services/packing_contractor_resolver.py` and a new sub-route. It does not call any of those subsystems. |
| 8 | No packing-list side effect on `customer_master` / `suppliers` | Resolver UI never auto-saves to those tables. Confirmed by test. |

---

## Phase 7 — Tests required (for the future implementation PR)

| # | Test | Form |
|---|---|---|
| 1 | Exact VAT match → client_master row, confidence 0.95 | unit, seed customer_master |
| 2 | Exact VAT match → supplier_master row | unit, seed suppliers |
| 3 | Normalised name + country match → 0.85 | unit, multiple legal-form suffixes |
| 4 | Ambiguous duplicate name → returns top-5, status=unresolved | unit |
| 5 | No match → status=unresolved, candidates list bounded to 5 | unit |
| 6 | Fuzzy below threshold (ratio < 85) → status=unresolved | unit |
| 7 | Operator override path persists override + audit | integration |
| 8 | "Create new" path requires explicit confirm + audit_logs operator | integration |
| 9 | Resolver never calls any `wfirma_client.create_*` / `update_contractor` | source-grep + monkey-patch trip-wire |
| 10 | Resolver never writes to `customer_master` / `suppliers` tables | trip-wire on `customer_master_db.upsert_*` and `suppliers_db.upsert_*` |
| 11 | Packing upload with no client name → `status=unresolved`, no DB writes outside `packing_contractor_resolution` | integration |
| 12 | Generic-across-countries (PL / DE / IN client) — same resolver path, same tier outputs | parametrised |
| 13 | PZ regression remains 160/160 | regression |
| 14 | `campaign_status doctor` clean after implementation | regression |

---

## Phase 8 — Implementation plan (NOT this PR)

Three sub-batches, each independently deployable, each with its own PR:

### Batch R1 — Resolver core (backend-only)
- New module: `service/app/services/packing_contractor_resolver.py`
- Implements `resolve_contractor(parsed: dict, role: str) -> dict` per Phase 3 spec
- Reads `customer_master.sqlite` + `suppliers.sqlite` directly (read-only)
- No DB writes; returns the verdict structure
- 12 unit tests (Phase 7 #1-6 + #9 + #12)
- No UI change in this batch

### Batch R2 — `packing_contractor_resolution` table + persistence
- New `service/app/services/packing_resolution_db.py` (analogous to `packing_db`)
- Schema from Phase 5
- Route: `POST /api/v1/packing/{batch_id}/contractor-resolution` (persist a verdict + optional operator override)
- Route: `GET /api/v1/packing/{batch_id}/contractor-resolution` (return current verdicts for the batch)
- 4 integration tests (Phase 7 #7, #8, #10, #11)
- Still no UI change

### Batch R3 — Operator UX (frontend)
- New "Contractor resolution" panel inserted between Parsed Lines and Confirm Sales Draft
- "Use this match" / Override dropdown / "Create new from parsed data" affordances
- KYC modal "Open ..." link reuse
- Source-grep tests for the panel testids
- Browser smoke after deploy

Each batch is mergeable on its own; if the operator changes the
design between batches, only the unstarted batches are revised.

---

## Out of scope for the resolver itself

- Product / design resolver (separate batch — packing lines reference
  product codes, but matching them to local product master is a
  different code path)
- Proforma posting consumer of the verdict
- PZ flow consumer of the verdict
- DHL / customs consumer of the verdict
- Live wFirma write to register a new contractor (permanent hard stop)
- Cross-batch deduplication of resolutions (each batch resolves
  independently; aggregation is reporting, not resolver work)

---

## Related artefacts

- `service/app/api/routes_packing.py` — current upload + heuristic
  client-name guess
- `service/app/services/packing_db.py` — packing_documents +
  packing_lines schema
- `service/app/services/customer_master_db.py` — Client Master
- `service/app/services/suppliers_db.py` — Supplier Master
- `service/app/services/wfirma_customer_sync.py::normalise_client_name`
  — reusable normalisation helper
- `tasks/wfirma-enrichment-ownership-model.md` — established
  preservation rules
- `tasks/client-master-surface-consolidation-plan.md` — UI consolidation
  precedent for inserting a new panel without churning legacy testids
