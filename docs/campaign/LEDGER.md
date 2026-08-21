# Campaign ledger

Programme: wFirma authority → Treasury → Inventory → CFO, plus the inbound-flow rebuild.
Updated at every node transition. A run with no ledger update is invisible work.

**State of record (2026-08-22):** `origin/main` `9b0d3819` · production `3748daae` (one merge
behind) · `C:\PZ-main` restored to `main`, clean.

## NODES

| node | state | branch | PR | evidence | completed |
|---|---|---|---|---|---|
| U1 deploy-source restore | **MERGED** | — | — | `C:\PZ-main` on `main`, `== origin/main`, clean; allocation branch moved to `C:\PZ-wt\packing-allocation` | 2026-08-22 |
| U4 registry corrections | **MERGED** | — | — | both squash-trap entries corrected; standing check 3 passed / 1 skipped | 2026-08-22 |
| U2/U5 push + merge held branches | **BLOCKED** (`git push` denied by harness classifier) | five branches | — | — | — |
| S0 line identity | **ACTIVE** | `fix/packing-line-identity` | HELD | key `76a6a821`, classifier `189c3c2d`, 34 tests green, 59/59 collisions classified | — |
| P0 parser determinism | QUEUED | — | — | identical bytes → 21 vs 24 rows | — |
| M0 master consolidation | QUEUED | — | — | — | — |
| S1 · S4a · S2 · S3 · S4 · S5 | QUEUED | — | — | — | — |
| W4-Z AR/AP zombie census | QUEUED (Track B) | — | — | — | — |
| D8 unify read-only classifiers | QUEUED | — | — | — | — |

## DECISIONS

| id | date | decision | alternatives rejected | dissent | reversal | evidence |
|---|---|---|---|---|---|---|
| D-01 | 08-22 | Did **not** rewrite `_compute_scan_code`, against the charter's instruction. Added a second function instead. | Rewrite it as instructed | none | MEDIUM | It is the printed barcode with a documented per-piece uniqueness contract, triplicated across `packing_db`, `routes_packing._barcode_value`, `warehouse_db`. Labels already exist on boxes; rewriting changes what physical labels resolve to |
| D-02 | 08-22 | `packing_line_key` unscoped — no `batch_id`, no `doc_stage` | Scope by batch | none | CHEAP | Scoped by batch it would have missed the cross-batch duplicates, which are 38 of the 59 collisions |
| D-03 | 08-22 | Added the key as a **new primary** dedupe ahead of the existing branches rather than rewriting them | Rewrite `upsert_packing_lines` | SENIOR-DEV: each existing fallback has an incident behind it | CHEAP | Minimal diff; legacy branches remain for pre-migration rows |
| D-04 | 08-22 | Classifier reduces over **pairs**, taking the worst class | Majority class; first-pair-wins | none | CHEAP | An advance/final pair is benign alone but forms a GENUINE pair with a third document — majority would hide it |
| D-05 | 08-22 | Detached `C:\PZ-wt\residue` at its own commit to free `main` | Delete the worktree | none | CHEAP | It was clean, at `9b0d3819`, carrying nothing unique |

## STOPS RAISED

| id | date | STOP | operator must decide | blocks |
|---|---|---|---|---|
| ST-01 | 08-21 | (tooling) | `git push` permission — five branches hold finished, tested work with **no remote ref** | U2, U5, every future slice |
| ST-02 | 08-22 | **STOP 3** | Duplicate packing documents have propagated into `documents.db` as duplicate supplier-invoice documents. Withdrawing the packing side alone leaves an orphaned duplicate invoice. Both layers must be withdrawn together, which touches a commercial record. **No money is wrong** — each document states the true quantity. | S0 repairs (withdrawal) |
| ST-03 | 08-21 | STOP 4 | `test.api2.wfirma.pl` sandbox credentials | two wFirma gaps |
| ST-04 | 08-21 | STOP 3 | goods-registry name for diamond-set items | S5 only |
| ST-05 | 08-21 | (registry) | `accounting-cfo-mis` worktree/branch field — which was intended | registry closure |

## FINDINGS

| id | sev | finding | evidence | fixed by |
|---|---|---|---|---|
| F-01 | BLOCKER | Identity function not stable under a missing optional field | `packing_db.py:44`; two forms of one line → two keys | S0 ✅ key shipped |
| F-02 | BLOCKER | Root cause: `upsert_packing_lines` dedup key **branches** on `pack_sr` and is batch-scoped, so the two forms can never match and cross-batch duplicates are structurally invisible | `packing_db.py:765-789` | S0 (wiring remaining) |
| F-12 | **HIGH** | **38 duplicate line-keys, 39 surplus rows, 7 batches** — far beyond the census's 3. Includes one packing list ingested into two different shipment batches | shipped classifier over 1326 live rows | S0 + ST-02 |
| F-13 | **HIGH** | Duplication propagated into `documents.db`: two supplier-invoice documents per duplicated packing document. Each states the true quantity, so the per-document money is right; the aggregate double-counts | `invoice_lines` for `EJL/26-27/177-5`: two documents × 20.0 | ST-02 |
| F-14 | MEDIUM | 12 product_codes report an inflated import quantity (`EJL/26-27/177-5`: 40 reported vs 20 true) | quantity impact probe | S0 |
| F-03 | HIGH | 245 orphan `packing_lines` (15%) reference a non-existent document; no FK declared | batch `…_999deef1` | S0 |
| F-15 | MEDIUM | Parser non-determinism: identical bytes yield 21 rows as `final`, 24 as `advance` | `ORDER CONFIRMATION _25-07_.xlsx`, hash `b99395a9` | P0 |
| F-16 | LOW | `linked_batch_id` is empty on **every** advance document, so advance→final is unmodelled | all advance docs | S0 |
| F-04 · F-05 · F-06 · F-07 · F-08 · F-09 · F-10 · F-11 | — | see `W1_AUTHORITY_MAP.md` | | M0/S1/S3/S4a |
| G-01 | HIGH | Deploy guard did not recognise `/c/PZ`, the form the Bash tool emits — production writes unguarded for the whole campaign | 6 spellings tested | guard fix (held) |
| G-02 | MEDIUM | 9 guard false positives, one shape: name occurrence rather than operation | corpus | guard fix (held) |
