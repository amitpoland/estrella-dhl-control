# Phase 6F.2 — Backfill from `proforma_service_charges` (Inspection Only)

> **INSPECTION REPORT. NO CODE. NO SCRIPTS. NO DATA WRITES.**
> 2026-05-16 · author: claude-session
> Based on live read of `proforma_service_charges_db.py` (175 lines) +
> `proforma_invoice_link_db.py` (linkage table) at post-6F.3 main SHA
> `ba9017d`.

---

## 1 — Source surface

### 1.1 — Legacy table: `proforma_service_charges` (file: `proforma_links.db`)

```sql
CREATE TABLE proforma_service_charges (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     TEXT NOT NULL,
    client_name  TEXT NOT NULL,
    charge_type  TEXT NOT NULL,        -- {freight, insurance}
    amount       REAL NOT NULL DEFAULT 0,   -- ⚠️ FLOAT
    currency     TEXT NOT NULL DEFAULT '',  -- ISO 4217, upper-cased
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    created_by   TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL,
    UNIQUE(batch_id, client_name, charge_type)
);
CREATE INDEX idx_psc_batch_client ON proforma_service_charges (batch_id, client_name);
```

Allow-list: `ALLOWED_CHARGE_TYPES = frozenset({"freight", "insurance"})`.
Currency normalised upper-case at write time. Note: legacy uses `REAL` for amount.

### 1.2 — Linkage table: `proforma_invoice_link` (file: `proforma_links.db`, same file as charges)

```sql
CREATE TABLE proforma_invoice_link (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proforma_id     TEXT NOT NULL UNIQUE,   -- wFirma proforma id
    proforma_number TEXT,
    invoice_id      TEXT,                   -- wFirma invoice id (post-conversion)
    invoice_number  TEXT,
    ...
);
```

This table connects `(batch_id, client_name)` → wFirma proforma/invoice ids,
but indirectly: the table is keyed on `proforma_id`, not `(batch, client)`.
The forward query path is: charges → `(batch_id, client_name)` → existing
proforma resolution in `routes_proforma.py` → `proforma_id` / `invoice_id`.

### 1.3 — Files relevant to backfill

| File | Role | Read by 6F.2? |
|---|---|---|
| `service/app/services/proforma_service_charges_db.py` | Source of legacy rows | YES (read-only) |
| `service/app/services/proforma_invoice_link_db.py` | wFirma id resolution | YES (read-only, optional) |
| `service/app/services/finance_postings_db.py` | Backfill destination | YES (writes via existing `create_posting` + `create_charge`) |
| `service/app/api/routes_proforma.py` | Operator-facing context only | NO |
| wFirma API | Operator system of record | NO |

---

## 2 — Mapping from legacy → new schema

### 2.1 — Charges (1:1)

| Legacy column | New `charges` column | Transformation |
|---|---|---|
| `batch_id`    | `batch_id`     | passthrough |
| `client_name` | `client_name`  | passthrough |
| `charge_type` | `charge_type`  | passthrough (legacy values `freight` / `insurance` are both in new allow-list) |
| `amount`      | `amount_minor` | **float → minor units: `int(round(amount * 100))`** |
| `currency`    | `currency`     | passthrough (already upper-case) |
| `note`        | `notes`        | passthrough (empty string → null) |
| —             | `source`       | constant `"legacy_backfill"` (matches `CHARGE_SOURCES`) |
| —             | `posting_id`   | NULL on initial backfill — see §2.3 |

### 2.2 — Postings (synthetic)

Legacy `proforma_service_charges` has no `posting_id` column. The new schema
groups charges by posting. For backfill we have three choices:

| Strategy | Description | Idempotency anchor |
|---|---|---|
| **A. One synthetic posting per (batch_id, client_name)** | Insert one `postings` row per unique tuple; attach all charges for that tuple via `link_charge_to_posting`. | `(batch_id, client_name)` |
| **B. One synthetic posting per legacy row** | Each charge gets its own posting. Loses grouping semantics. | `legacy_charges.id` |
| **C. No posting; leave `posting_id = NULL`** | Defer posting creation to 6F.5 (`/post` dual-write). Backfill only fills the charges table. | `legacy_charges.id` |

**Recommendation: Strategy A.** It preserves the architectural property that
"a posting is one issuance event grouping its charges" without inventing
artificial 1-row postings. The synthetic posting carries:
- `batch_id`, `client_name` from the legacy tuple
- `posting_kind = "proforma"` (legacy table is `proforma_service_charges`)
- `wfirma_invoice_id`, `wfirma_doc_number` — populated via `proforma_invoice_link` lookup when present, else NULL
- `posted_at` — earliest `created_at` of the legacy charges in the group
- `issued_total_minor` — sum of `amount_minor` across the group (legacy did not store this)
- `currency` — the currency of the group (must be uniform; see §5)
- `fx_rate_at_issue` — NULL (legacy did not record it)

### 2.3 — Payments + allocations + settlements

Out of scope for 6F.2. The legacy table did not record payments. The
backfill creates only `charges` (+ synthetic `postings` per Strategy A).
Payments / allocations / settlements will be populated by 6F.5 / 6F.6 once
the wFirma payments probe (Phase 10A.5) lands.

---

## 3 — Idempotency design

### 3.1 — Recommended deterministic key

**Composite key on the new `charges` table:**

```
backfill_idempotency_key = sha1(
    "legacy_psc:"
  + batch_id + ":"
  + client_name + ":"
  + charge_type
)
```

Reasons:
- The legacy table already has `UNIQUE(batch_id, client_name, charge_type)`,
  so there is exactly one legacy row per tuple. Hashing the tuple gives a
  collision-free, deterministic, re-runnable key.
- Storing the hash in `charges.notes` as a structured prefix (e.g.
  `"[backfill:sha1=<hash>]\n<original note>"`) avoids schema changes.
- A 6F.2 idempotency contract: before inserting, query `charges` for
  `WHERE source='legacy_backfill' AND notes LIKE '[backfill:sha1=<hash>]%'`
  — if found, **skip insert** (already backfilled).

### 3.2 — Why not a new column

Adding a column would alter the 6F.1 schema (forbidden by hard rule
"additive only"; would also break the 6F.1.5 idempotency contract test
that asserts identical `PRAGMA table_info` snapshot across `init_db` calls).
The `notes` field is already a free-form string per architecture and is
the right home for an idempotency marker.

### 3.3 — Postings idempotency

For Strategy A (one posting per `(batch_id, client_name)`), the synthetic
posting's idempotency key is:

```
sha1("legacy_psc_posting:" + batch_id + ":" + client_name)
```

stored similarly in `postings.wfirma_doc_number` only when the
`proforma_invoice_link` lookup returns no real `proforma_number` — that is:

- If a real `wfirma_doc_number` exists → use it.
- If not → the synthetic posting carries `wfirma_doc_number = NULL` and the
  backfill records the deterministic synthetic id in a new comment-style
  field. **Recommend:** add the sha1 to the `wfirma_invoice_id` field
  prefixed with `"BACKFILL-"` (e.g. `BACKFILL-3f2a1b...`). This makes
  "is this a backfilled posting" trivially queryable.

---

## 4 — Expected row counts

(Read-only inspection — no Python executed against production data.)

### 4.1 — Source row count

`proforma_service_charges` has the size of the operator's accumulated
freight + insurance entries across all clients × all batches:
- 1 entry per (batch, client, charge_type)
- Each batch typically has 1-3 clients
- Each client has up to 2 charges (freight, insurance)
- → roughly `2 × clients × batches`

A typical operator who has run ~100 batches over the past year would have
**~200-400 rows**. Conservative upper bound: ~1000 rows.

### 4.2 — Destination row count after backfill

| Table | Rows | Notes |
|---|---|---|
| `charges` | = legacy row count | exactly 1:1 |
| `postings` | = unique `(batch_id, client_name)` tuples | ~1/3 to 1/2 of charges count |
| `payments` | 0 | not in scope |
| `payment_allocations` | 0 | not in scope |
| `settlements` | 0 | not in scope |

---

## 5 — Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | Legacy `amount REAL` → float-to-int conversion loses precision (e.g. `3.49 * 100 = 348.99999...`) | MEDIUM | Use `int(round(Decimal(str(amount)) * 100))` not `int(amount * 100)`. Add a backfill contract test asserting round-trip. |
| **R2** | Legacy currency may be empty string (DEFAULT '') in old rows; ISO 4217 validator in new schema rejects empty | MEDIUM | Backfill DRYs first; rows with empty currency need operator decision (skip / assign default / reject). Recommend: skip + log + return error report. |
| **R3** | Synthetic posting groups charges with different currencies | LOW | The legacy table is keyed on `(batch_id, client_name, charge_type)` — currencies should already be uniform per tuple. Assert this in backfill and abort the group if mixed. |
| **R4** | Linkage to `proforma_invoice_link` is fuzzy — the link table is keyed by `proforma_id`, not `(batch, client)` | MEDIUM | Backfill is allowed to leave `wfirma_invoice_id = NULL` for any group where no link is found. Document in §3.3. |
| **R5** | Legacy `created_at` may not be ISO-8601 (`datetime.now(timezone.utc).isoformat()` is the source; should be fine, but old rows from a different code version might not be) | LOW | Backfill validates each `created_at` against `_ISO_DATE_RE` and falls back to `_now()` with a log message if invalid. |
| **R6** | Backfill re-run after partial failure leaves the destination in an inconsistent state | MEDIUM | Idempotency key on charges (§3.1) + transactional batch processing (§7) make re-runs safe. |
| **R7** | Concurrent operator activity during backfill could insert NEW legacy rows that backfill misses | LOW | Backfill snapshots `MAX(legacy_charges.id)` at start; only backfills rows with `id ≤ snapshot`. Operator must re-run backfill after any new legacy writes (the idempotency key makes re-runs safe). |
| **R8** | Production storage might already have a `finance_postings.sqlite` file from 6F.3 production deploy (now lazily created on first GET) | LOW | The 6F.3 production smoke just created it (size = 81920 bytes, all tables empty). Backfill must not re-init or alter; just `INSERT INTO charges` / `INSERT INTO postings`. |
| **R9** | Legacy table's `amount = 0` rows (operator-cleared but not deleted) leak into backfill | LOW | Backfill filters `amount > 0` OR documents that zero rows are preserved for audit. **Recommend: preserve them** with `source='legacy_backfill'` and `notes` indicating zero-value source. |

**No HIGH risk.**

---

## 6 — Currency normalisation strategy

The new `charges` schema requires ISO 4217 currency (3 uppercase letters,
validated by `_ISO_4217_RE`). Legacy `currency` is already `.strip().upper()`-ed
at write time, but historical rows might predate that normalisation.

Recommendation:
- Backfill normalises with the same logic: `(currency or "").strip().upper()`.
- If the result is not ISO 4217 → **skip the row + log to a backfill-error
  report**. Do NOT assign a default (would silently corrupt audit trail).
- Empty-currency rows are a known operator-cleanup task; the backfill
  surfaces them in the error report for explicit operator triage.

---

## 7 — Batching strategy

| Option | Pros | Cons |
|---|---|---|
| **One-shot in-memory** | Simplest. Atomic if wrapped in single transaction. | Memory cost for ~1k rows is trivial; doesn't help recoverability for larger sets. |
| **Chunked (e.g. 100/chunk)** | Bounded transaction size; partial progress recorded after each chunk. | More complex; needs progress tracking. |
| **Resumable streaming** | Continues from last-successful `id` after a crash. | Complex; over-engineered for ~1k rows. |

**Recommendation: Chunked (Option 2) with 100 rows per chunk.** Reasons:
- Bounds transaction size.
- After each chunk, the idempotency key on `charges` makes a re-run a no-op
  for already-backfilled rows; resume-after-crash is automatic.
- Progress can be logged to stdout / a structured `backfill_progress.json`
  file under `tasks/` for operator visibility.

---

## 8 — Dry-run mode

**MANDATORY.** The first batch in 6F.2 must be a `--dry-run` mode that:
1. Reads every legacy row
2. Computes the proposed new `charges` + `postings` rows
3. Reports counts + any errors (empty currency, malformed `created_at`, etc.)
4. Writes a JSON report under `tasks/6f-2-backfill-dryrun-<date>.json`
5. **Writes nothing to `finance_postings.sqlite`**

Only after operator inspects the dry-run report should the live backfill run.

The dry-run / live flag should be required (no default — operator must
explicitly choose), preventing accidental live runs.

---

## 9 — Rollback strategy

| Strategy | Description | Recommended? |
|---|---|---|
| **Delete-by-source** | `DELETE FROM charges WHERE source='legacy_backfill'`; same for `postings`. | ✅ **YES.** Architecture §M2 already declared this exact rollback path. |
| **Snapshot restore** | Copy `finance_postings.sqlite` before backfill; restore on rollback. | Belt-and-braces option. Easy because the file is small (~80 KB). |
| **Tombstone / reversal** | Add reversal rows with negative amounts. | NOT recommended — pollutes audit trail; reversal semantics conflict with append-only `settlements`. |

**Recommendation:**
1. Take a snapshot copy of `finance_postings.sqlite` to
   `storage/snapshots/finance_postings.pre-6F2.sqlite` immediately before
   the live backfill (cost: 80KB copy).
2. Live backfill writes with `source='legacy_backfill'` on every row.
3. Rollback command:
   ```sql
   DELETE FROM charges WHERE source='legacy_backfill';
   DELETE FROM postings WHERE wfirma_invoice_id LIKE 'BACKFILL-%';
   ```
4. Worst-case rollback: restore the snapshot file (operator-acknowledged
   manual step).

---

## 10 — Implementation batches inside 6F.2

| Step | Description | Type |
|---|---|---|
| 6F.2.a | Add backfill script `service/scripts/backfill_proforma_service_charges.py` | AUTO_SAFE (code only) |
| 6F.2.b | Add tests covering dry-run, live, idempotency, currency normalisation, posting grouping (target: 25+ tests) | AUTO_SAFE |
| 6F.2.c | Add operator-runbook section + state-tracker entry | AUTO_SAFE (docs) |
| 6F.2.d | Operator runs dry-run in production; reviews report | OPERATOR-GATED |
| 6F.2.e | Operator takes snapshot + runs live backfill | OPERATOR-GATED |
| 6F.2.f | Operator verifies row counts via the 6F.3 breakdown endpoint | OPERATOR-GATED |

Steps 6F.2.a-c are PR-able as one batch. Steps 6F.2.d-f are operator-driven
post-merge.

---

## 11 — Open questions for operator (before 6F.2 implementation starts)

1. **Strategy A vs C for `postings`:** create synthetic postings (A) or
   leave `posting_id` NULL on backfilled charges (C)? Architecture §5.4
   implies A is required for the `/breakdown` endpoint to display
   meaningful groupings; recommend A.
2. **Empty-currency policy:** skip + report (recommended) or assign a
   default (e.g. PLN)?
3. **Zero-amount rows:** preserve (audit) or skip (cleanup)?
4. **Snapshot location:** operator confirms `C:\PZ\storage\snapshots\` is
   the right place for the pre-backfill `.sqlite` copy?
5. **Dry-run report destination:** `tasks/6f-2-backfill-dryrun-<date>.json`
   (in-repo, committed via PR) or `C:\PZ\storage\6f2-dryrun.json` (out-of-
   repo, audit-only)?

These five answers go into the 6F.2 implementation PR description.
Without them, the implementation will proceed with the defaults marked
(recommended).

---

## 12 — Compliance with hard rules

| Hard rule | Compliance in 6F.2 (planned, pre-implementation) |
|---|---|
| No wFirma live write | ✅ — backfill only reads `proforma_service_charges` |
| No proforma posting | ✅ — backfill doesn't issue proformas |
| No PZ/customs/DHL calculation change | ✅ — no engine touched |
| No FX override | ✅ — `fx_rate_at_issue` stays NULL |
| No `.env` change | ✅ |
| No direct production DB edit | ✅ — backfill is a versioned script; runs via operator command, writes via `create_charge` / `create_posting` (audited paths) |
| No external services | ✅ |
| No accounting mutation | ✅ — legacy `proforma_service_charges` is untouched; only `charges` + `postings` in the new namespace receive rows |

**6F.2 inspection report ends here.** Operator approval of §11 questions is
required before any 6F.2 implementation work begins.
