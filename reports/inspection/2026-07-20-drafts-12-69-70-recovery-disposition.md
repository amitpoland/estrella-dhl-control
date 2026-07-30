# Drafts 12 / 69 / 70 — Recovery Disposition (READ-ONLY)

**Date:** 2026-07-20 · **Authority:** production `C:\PZ\storage` (`mode=ro`, WAL present)
**Writes performed:** none. No product_code assigned, no draft re-synced, no intake replayed.

---

## Headline

**None of the three drafts can be recovered by product_code assignment.**
Phase 5 as drafted (assign via `packing_db.assign_product_code_to_unassigned_design`)
is **not applicable to any of them**, for two different reasons:

* **Drafts 69 + 70** — their sales rows are *structurally empty*. Missing `product_code`
  is not the problem; there is no design, no quantity and no price either. There is
  nothing to invoice.
* **Draft 12** — its sales rows carry real commercial data, but **zero** of its designs
  appear among the batch's coded purchase evidence, so no deterministic position match
  exists. One line is a `PND` placeholder-design, which may never be auto-assigned.

---

## Disposition table

| Draft | Batch | Customer | Expected lines | Missing codes | Exact position match | Recovery path |
|---|---|---|---|---|---|---|
| 12 | `SHIPMENT_4218922912_2026-05_bd18ec98` | Dream Ring | 4 rows / 4 pcs / **6 524.00 EUR** | 4 of 4 | **NO** — 0/4 sales designs overlap the 13 coded purchase designs in-batch | **operator** (per-line confirmation; `PND` line needs a design decision first) |
| 69 | `SHIPMENT_1201561616_2026-07_bcd042b4` | DG GmbH | 5 rows, **all blank** (qty 0, value 0) | 5 of 5 — *and every other field* | **NO** — batch has 0 coded purchase rows | **intake** (re-extract sales packing) |
| 70 | `SHIPMENT_1201561616_2026-07_bcd042b4` | MICHAEL KENNY LLP | 11 rows, **all blank** (qty 0, value 0) | 11 of 11 — *and every other field* | **NO** — batch has 0 coded purchase rows | **intake** (re-extract sales packing) |

---

## Evidence

### Drafts 69 + 70 — the sales rows are empty shells

Across all 11 rows of draft 70 (and all 5 of draft 69), the only columns holding any
value are `id`, `batch_id`, `sales_document_id`, `client_name`, `created_at`,
`client_contractor_id`. Every commercial field — `design_no`, `product_code`,
`quantity`, `unit_price`, `total_value`, `currency`, `item_type`, `karat`, `size` — is
empty or zero.

So the earlier finding "11 sales lines exist" is true only as a **row count**. The
sync did not lose priced lines; it was handed 11 placeholder rows.

`sales_documents` nonetheless records `extraction_status = 'extracted'` for both —
a second silent-success defect of the same family as the sync bug, one layer upstream.
Row-count mismatch reinforces it: the source file is `…428-…-5pcs-…MICHAEL KENNY.pdf`,
yet 11 rows were produced.

The authoritative content for this batch exists **only on the purchase side**
(`packing.db.packing_lines`), which has 4 real lines / 5 pieces carrying designs and
prices, split across the two EJL documents:

| EJL doc | pcs | designs | maps to |
|---|---|---|---|
| 427 (`d45f1f28`) | 1 | `JR07924-1.6` @ 393.00 | DG GmbH (draft 69) |
| 428 (`a4ea9563`) | 4 | `CSTR02614` @ 632.00, `JE02058-1.00` ×2 @ 104.00, `J3403R01986` @ 1 554.00 | MICHAEL KENNY LLP (draft 70) |

Those purchase rows also carry **no `product_code`** (0 of 5 coded), so they cannot
supply codes either — they can only supply design/qty/price for a re-extraction.

Note the `428` document is labelled *5pcs* but yields 4 pieces. That discrepancy must
be resolved during re-intake, not assumed away.

### Draft 12 — real data, but no deterministic evidence

| design | qty | unit | total | ccy |
|---|---|---|---|---|
| `CSTB00160` | 1 | 2 014.00 | 2 014.00 | EUR |
| `CSTP00499` | 1 | 701.00 | 701.00 | EUR |
| `PND` | 1 | 3 008.00 | 3 008.00 | EUR |
| `CSTR07800` | 1 | 801.00 | 801.00 | EUR |

The batch has 31 purchase packing rows, 26 coded across 13 distinct designs — but the
**overlap with these 4 sales designs is 0**. Auto-assignment therefore has no exact
position evidence to act on (governance rule 11), so rule 12 applies: operator
confirmation required.

`PND` is a placeholder-design. Per Lesson N it is advisory-class and is not a valid
assignment target; the operator must first decide what it represents.

---

## Recovery tooling — availability confirmed

The three referenced commits are **not** ancestors of `origin/main`
(`git cherry` marks all three `+`, and the branch carries
`archive/integration--packing-product-code-repair-2026-07-17`):

| Commit | Subject |
|---|---|
| `f0576939` | surface unassigned-packing evidence on over-bill (read-only) |
| `6fc84e7f` | operator-confirmation writer for product_code assignment |
| `76f0af47` | exact position-key resolver (replaces pack_sr sequence resolver) |

However the **capability itself did land** via a different route:
`assign_product_code_to_unassigned_design` is present in `origin/main`
(`service/app/services/packing_db.py`) **and in production**
(`C:\PZ\app\services\packing_db.py`), with call sites at
`routes_proforma.py:7242` and `:7694`; `product_authority_resolver.py` is present on
main. So the writer is deployed — it simply has no evidence to act on for these three
drafts.

---

## Recommended sequencing (no approval implied)

1. **Deploy the 33c65b4e warning first, alone.** It is what prevents the *next*
   occurrence. It changes no data and recovers nothing.
2. **Treat 69 + 70 as an intake defect, not a proforma defect.** The fix target is the
   sales packing extractor that wrote 11 empty rows while reporting `extracted`.
   Assigning product codes here would be inventing commercial data.
3. **Treat 12 separately** as an operator-confirmation case, gated on a `PND` decision.
4. **Investigate the upstream extractor as its own workflow class** (Lesson I) — an
   extractor that reports success while emitting empty rows will have produced other
   silent casualties beyond these three drafts.

---

## Constraints honoured

Read-only throughout: `mode=ro` SQLite `SELECT`s, git metadata reads, `gh pr view`.
No production writes, no product_code assignment, no draft reset/re-sync, no intake
replay, no wFirma action, no PR opened, no deployment.
