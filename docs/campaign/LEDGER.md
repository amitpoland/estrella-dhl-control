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
| S0 line identity | **ACTIVE** | `fix/packing-line-identity` | HELD | key `76a6a821`, classifier `189c3c2d`, repair `35b50a45`, pin `1fb84dc9`; 105 tests green. Key REDESIGN pending — see D-06 | — |
| P0 parser determinism | QUEUED | — | — | identical bytes → 21 vs 24 rows | — |
| M0 master consolidation | QUEUED | — | — | — | — |
| S1 · S4a · S2 · S3 · S4 · S5 | QUEUED | — | — | — | — |
| W4-Z AR/AP zombie census | **MERGED** | — | — | census complete: 772 AR / 2176 AP rows; scope, basis and currency integrity all CLEAN | 2026-08-22 |
| TB-1 contractor identity | **ACTIVE** | `fix/ar-ap-contractor-identity` | HELD | `c7ce03c9`, 6 new tests, 72 accounting-hub tests green | 2026-08-22 |
| D8 unify read-only classifiers | QUEUED | — | — | — | — |

## DECISIONS

| id | date | decision | alternatives rejected | dissent | reversal | evidence |
|---|---|---|---|---|---|---|
| D-01 | 08-22 | Did **not** rewrite `_compute_scan_code`, against the charter's instruction. Added a second function instead. | Rewrite it as instructed | none | MEDIUM | It is the printed barcode with a documented per-piece uniqueness contract, triplicated across `packing_db`, `routes_packing._barcode_value`, `warehouse_db`. Labels already exist on boxes; rewriting changes what physical labels resolve to |
| D-02 | 08-22 | `packing_line_key` unscoped — no `batch_id`, no `doc_stage` | Scope by batch | none | CHEAP | Scoped by batch it would have missed the cross-batch duplicates, which are 38 of the 59 collisions |
| D-03 | 08-22 | Added the key as a **new primary** dedupe ahead of the existing branches rather than rewriting them | Rewrite `upsert_packing_lines` | SENIOR-DEV: each existing fallback has an incident behind it | CHEAP | Minimal diff; legacy branches remain for pre-migration rows |
| D-04 | 08-22 | Classifier reduces over **pairs**, taking the worst class | Majority class; first-pair-wins | none | CHEAP | An advance/final pair is benign alone but forms a GENUINE pair with a third document — majority would hide it |
| D-05 | 08-22 | Detached `C:\PZ-wt\residue` at its own commit to free `main` | Delete the worktree | none | CHEAP | It was clean, at `9b0d3819`, carrying nothing unique |
| D-06 | 08-22 | The ordinal must leave the packing key. Wiring it into the write path proved it cannot be a pure function of the row: the upsert is called per-line, so every call sees a list of one and both lines of a lot key identically. Ranking against stored rows fixed that but made the key a function of *the row and the database* — IDENTITY STABILITY violated more subtly than the original bug. Key becomes f(invoice_no, product_code, design_no, quantity); multiplicity is a count, matching R8's quantity-scoped ruling. | Keep the ordinal and special-case per-line callers; rank against DB state | none — the ADVERSARY tests forced it | MEDIUM | 7 tests red at attempt 3; reverted to green at `1fb84dc9` |
| D-07 | 08-22 | Removed the `contractor_detail/id` fallback outright rather than making it conditional | Keep it when the CRM id is absent; log and continue | none | CHEAP | The snapshot id changes per document, so a fallback invents a party per invoice. An absent id is a real condition and now stays visible |

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
| F-17 | **HIGH** | **Duplicate customer masters are live, not theoretical.** Two legal entities are reported as four positions, so a credit under one id can never offset an invoice under the other. | SYNINVEST/Synalia FR58479048548: cid 38533073 (32 docs, +$43,510.80, −$3,777.00) and cid 38534870 (19 docs, +$18,195.00, −$4,527.00). Goto Jewellery BG202532349: cid 91979891 (31 docs, $219,583.27) and cid 91967768 (1 doc, $13,282.00) | TB-1 (cause) + M0 (the merge itself is operator-only) |
| F-18 | MED | `contractor_detail/id` fallback at `accounting_documents.py:132` and `:211` — the exact wFirma trap: a per-document snapshot id keyed as a contractor | census Z4b | TB-1 ✅ fixed `c7ce03c9` |
| F-19 | **HIGH** | 13 AR + 2 AP ZOMBIE positions: unpaid invoices AND unlinked credits in one currency. The payment matcher applies payment facts only — there is no correction-to-invoice path, so `correction_of_id` is set by wFirma and ignored by the aggregator | Z2: EUR 4 / PLN 1 / USD 8 AR; USD 2 AP. Railing PLN 557,610 against a PLN 31,297 credit | W4-Z10 decision package |
| F-20 | MED | 3 exact-match orphaned credits — the unallocated-pair signature, invoice gross equal to the credit to the cent. The oldest is **four years** old | UAB Tomas Gold $52,940 (2021); Esency Diamonds $9,323.74 (2024); Juliany EOOD $2,843.00 (2026). All carry `correction_of_id` | needs a ruling: refund owed, or write-off |
| F-21 | HIGH | The legacy fallback dedup key is identical for every row of a lot when `pack_sr` is absent, so it **over-dedupes and silently loses goods**. Live today, independent of S0 | surfaced by `test_dedup_pack_sr_distinct_serials_inserted` while wiring S0 | S0 redesign |
| G-01 | HIGH | Deploy guard did not recognise `/c/PZ`, the form the Bash tool emits — production writes unguarded for the whole campaign | 6 spellings tested | guard fix (held) |
| G-02 | MEDIUM | 9 guard false positives, one shape: name occurrence rather than operation | corpus | guard fix (held) |
