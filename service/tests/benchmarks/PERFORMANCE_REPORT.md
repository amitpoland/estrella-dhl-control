# PR #575 Merge-Resolution — Performance Report

> SUT: the validation suite's helper functions (`parse_governance_items`, `extract_oq_new_ids`, `renumber_governance_ids`, `extract_facts_headings`, `validate_facts_date_ordering`). There is no separate merge pipeline module; these helpers ARE the dedup / renumber / ordering logic.

## Environment
- **python**: 3.9.1
- **platform**: Windows-10-10.0.19041-SP0
- **machine**: AMD64
- **cpu_count**: 6
- **memory_profiler**: tracemalloc (Python-heap allocations, not RSS)
- **timer**: time.perf_counter
- **note**: Single-process, single-thread. No psutil. Results reflect per-call Python allocation + CPU time on an otherwise idle run.

## Category 1 — Baseline thresholds (1x, 6293 lines)

| Operation | median | p95 | mem peak (MB) | throughput |
|---|---|---|---|---|
| dedup-detect (full scan) | 42.924 ms | 44.103 ms | 0.405 | 146,608 lines/s |
| per governance item | 6.13199 ms | — | — | — |
| renumber input scan | 8.070 ms | 8.961 ms | 0.403 | 247.8 headings/s |
| FACTS ordering validate | 23.403 ms | 24.519 ms | 0.719 | 89,175 entries/s |
| **end-to-end merge** | 75.142 ms | 77.683 ms | 0.594 | 0.07514 s total |

These are the acceptance thresholds for the baseline dataset size: the complete merge operation completes in **75.142 ms median / 77.683 ms p95** with a peak Python-heap allocation of **0.59 MB**.

## Category 2 — Scalability (1x / 10x / 100x)

| Size | lines | e2e median | e2e p95 | mem peak (MB) | dedup lines/s | validate entries/s |
|---|---|---|---|---|---|---|
| 1x baseline (~6296 lines) | 6293 | 75.142 ms | 77.683 ms | 0.59 | 146,608 | 89,175 |
| 10x (~63000 lines) | 62999 | 764.978 ms | 805.409 ms | 7.10 | 147,459 | 83,654 |
| 100x (~630000 lines) | 629999 | 7774.948 ms | 7805.465 ms | 72.03 | 144,726 | 82,678 |

**Scaling assessment:** end-to-end median scales as follows (normalised to 1x):
- 1x baseline (~6296 lines): 1.0x data -> 1.0x time (1.00 time/data ratio -> linear)
- 10x (~63000 lines): 10.0x data -> 10.2x time (1.02 time/data ratio -> linear)
- 100x (~630000 lines): 100.1x data -> 103.5x time (1.03 time/data ratio -> linear)

All operations are single-pass line scans (regex match per line) or O(k) assignments, so linear scaling is the expected and observed behaviour — no performance cliffs.

## Category 3 — Worst-case collision penalty

| k (ids assigned) | distinct median | colliding median | overhead % |
|---|---|---|---|
| k=3 | 0.00180 ms | 0.00180 ms | 0.00% |
| k=10 | 0.00250 ms | 0.00260 ms | 4.00% |
| k=100 | 0.01010 ms | 0.01010 ms | 0.00% |
| k=1000 | 0.31100 ms | 0.31020 ms | -0.26% |

**Finding:** `renumber_governance_ids` assigns sequential ids from `existing_max + 1` and never inspects the old placeholder value, so a 3x (or k-x) collision is algorithmically identical to k distinct placeholders. Measured overhead is noise-level. Collisions resolve to k distinct gap-free ids (correctness asserted in-harness). **No optimization required.**

## Category 4 — Error-handling overhead

| Corrupted fixture | validation | detected | time-to-detect median | p95 |
|---|---|---|---|---|
| ledger_invalid_missing_governance | presence | True | 0.3059 ms | 0.3353 ms |
| ledger_invalid_mid_sequence_insertion | uniqueness | True | 0.3712 ms | 0.3965 ms |
| ledger_invalid_facts_date_order | ordering | True | 0.0785 ms | 0.0914 ms |

Happy-path (all three validators on the clean canonical file): **0.7637 ms median / 0.8205 ms p95**. Error detection runs the SAME O(n) scans as the happy path — rejection is not more expensive than acceptance; corrupted files are rejected in the first scan that surfaces the defect. **Error handling imposes no measurable penalty on the happy path.**

## Category 5 — Ordering-validation speed vs region complexity

| FACTS variant | entries | median | entries/s | violations |
|---|---|---|---|---|
| already_descending | 5000 | 3.0798 ms | 1,623,482 | 0 |
| requires_sorting_shuffled | 5000 | 4.4883 ms | 1,114,008 | 2500 |
| identical_dates_secondary_key | 5000 | 3.0701 ms | 1,628,611 | 0 |
| sparse_distribution | 5000 | 3.0689 ms | 1,629,248 | 0 |

**Finding:** `validate_facts_date_ordering` is a single O(n) adjacency pass; throughput is governed by entry COUNT, not by how disordered the region is. A fully-shuffled region costs the same as an already-sorted one (it does not sort — it only checks adjacency). Identical-date regions are valid (non-increasing) and validate at full speed.

## Categories 1R / 3R / 5R — real committed fixtures

> **Named-fixture vs generated-size.** The task spec names `ledger_head_premerge_with_duplicates.txt (6296 lines)` as the baseline. That line count is a **fake constant** — the actual committed fixture is **69 lines**, and the real PROJECT_STATE.md ledger it distils is ~6261 lines. Categories 1–2 above GENERATE valid ledgers at 6296 / 63000 / 630000 lines to measure scan cost *at size*, but those generated ledgers carry one clean governance set — they do not contain the duplicate-governance / colliding-placeholder conflict that the merge actually resolved. This section runs the helpers against the real fixtures that DO contain that conflict, so both the size figure and the conflict-resolution figure are reported honestly.

### 1R — Baseline against the real pre-merge conflict fixture

Fixture: `deduplication/ledger_head_premerge_with_duplicates.txt` (69 lines). Scenario: real merge conflict: 5 governance anchors duplicated; OQ-NEW 14/15 each listed twice -> dedup -> renumber to 19/20 after baseline max 18.

| Operation | median | p95 | mem peak (MB) | throughput |
|---|---|---|---|---|
| dedup-detect (full scan) | 0.46290 ms | 0.48790 ms | 0.0080 | 149,060 lines/s |
| OQ-NEW input scan | 0.07950 ms | 0.08610 ms | 0.0073 | found 4 (dedup -> [14, 15]) |
| renumber assign | 0.00170 ms | 0.00190 ms | 0.0004 | oq-new-14=19, oq-new-15=20 |
| FACTS ordering validate | 0.09800 ms | 0.10680 ms | 0.0079 | — |
| **end-to-end merge** | 0.64620 ms | 0.68730 ms | 0.0082 | 0.000646 s total |

This is the real conflict-resolution workload: **5** governance anchors arrive duplicated and OQ-NEW-14/15 each appear twice; the helpers detect the duplication, dedup the OQ ids to `[14, 15]`, and renumber them gap-free to `oq-new-14=19, oq-new-15=20` from baseline max 18. End-to-end completes in **0.64620 ms median / 0.68730 ms p95**, vs the generated 1x row at 75.142 ms — about **116× faster** because the real fixture is **91× smaller** (69 vs 6293 lines), consistent with the linear scaling measured in Category 2. The size rows bound scan cost; this row bounds the cost of the work that actually happened.

### 3R — Worst-case collision against the real 3x-collision fixture

Fixture: `renumbering/ledger_edge_case_multiple_collisions_3x.txt`. Pinned params from fixture metadata: existing_max=18, num_to_assign=3, colliding placeholders=True.

| placeholders | median | p95 | overhead vs distinct | assigned ids |
|---|---|---|---|---|
| 3× colliding (all same old id) | 0.00180 ms | 0.00190 ms | 0.00% | [19, 20, 21] |
| 3 distinct (control) | 0.00180 ms | — | (baseline) | — |

The fixture's three placeholders all collide on one old id; they resolve to gap-free **[19, 20, 21]** (asserted in-harness). Measured overhead vs three distinct placeholders is **0.00%** — noise-level, confirming the placeholder-blind assignment on the real fixture, not just the synthetic k-sweep in Category 3.

### 5R — Ordering validation against the real descending-FACTS fixture

Fixture: `facts_integrity/facts_region_descending_order.txt`. Real FACTS dates (document order): ['2026-06-13', '2026-06-12', '2026-06-11', '2026-06-10'].

| entries | median | p95 | entries/s | violations |
|---|---|---|---|---|
| 4 | 0.04330 ms | 0.04780 ms | 92,379 | 0 |

The real descending FACTS region validates clean (**0** violations), confirming the ordering helper on the actual fixture content, not only the synthetic 5000-entry sequences in Category 5.

## Bottleneck analysis

- **Dominant cost: per-line regex matching in `parse_governance_items`.** It compiles 7 anchors once, then runs up to 7 `re.match` calls per line. At 100x (629999 lines) this is the largest single contributor to end-to-end time (4353.1 ms median dedup scan).
  - *When problematic:* only at 100x+ (hundreds of thousands of lines). The real ledger is ~6261 lines, ~100x smaller than the largest synthetic case, so production is firmly in the sub-millisecond-to-low-ms regime.
  - *Acceptable for production?* **Yes.** Even the 100x case completes the full merge in 7774.9 ms. No optimization needed for current or foreseeable ledger sizes. If a future ledger reached millions of lines, a single combined alternation regex or an early-exit once all 7 anchors are found + counted would cut the per-line constant.
- **Renumbering: not a bottleneck.** O(k), placeholder-blind, k is tiny in practice (2 at the real merge). Zero collision penalty (Category 3).
- **Ordering validation: not a bottleneck.** Single O(n) adjacency pass, count-bound (Category 5).
- **Error handling: not a bottleneck.** Same scans as the happy path; rejection is no costlier than acceptance (Category 4).

## Reproducibility

Re-run: `python service/tests/benchmarks/benchmark_pr575_merge_resolution.py`. Generated ledgers are deterministic (no RNG; dates are computed by ordinal). Absolute ms values are machine-dependent; the scaling RATIOS and the structural findings (linear scans, zero collision penalty, no error-path penalty) are the portable results.

