# Sole-Coordinator Consolidation — Authority Ledger (2026-07-17)

Operator ruling: one coordinator owns sequencing; all other sessions treated as inactive; no
worktree deleted/overwritten; dirty work preserved before any disposition.

**Mid-session finding:** a concurrent, operator-directed session is executing the **transport-m1
rebase** (registry `active-campaigns.json` flipped FROZEN→READY_FOR_REBASE `updated_by: operator`;
TASK_STATE current-task = transport-m1 IN_PROGRESS; campaign-branch-guard armed, denied a read of
C:\PZ-pr7). This contradicts the "sole coordinator / transport-m1 last" premise. Operator decision:
**"Proceed with #938 only, in parallel"** — this session does NOT touch transport-m1 / C:\PZ-pr7 / main.

## Ledger

| Campaign | Tree / branch | HEAD | Dirty | Remote PR | Reusable commits | Disposition |
|---|---|---|---|---|---|---|
| Coordinator | C:\PZ-verify (detached) | db260e70 | 9 (TASK_STATE M + untracked reports/scorecards; stray `query`/`start` = `sc` output junk) | — | — | Read/verify base; no commits here |
| Integration mirror | C:\PZ-main `main` | 71a2a757 | clean | — | — | ff-only → 9417a32f (its role) |
| **transport-m1** | C:\PZ-pr7 `fix/proforma-multidraft-transport-docs` | 14d629f5 ✓ | clean | none | 14d629f5 (6 commits) | **OWNED by concurrent session — do NOT touch** (eb61a012 forbidden; 929eac57 redundant) |
| #938 reconcile-by-number | wt competent-northcutt | 79a2e926 | clean | #938 (CONFLICTING) | c92914d1, 79a2e926 | Cherry-pick SOURCE → repaired as #939 |
| **#939 repair (NEW)** | C:\PZ-wt\reconcile-938-repair `fix/reconcile-by-invoice-number-and-terminal-guard` | 398bc543 | clean | **#939 (MERGEABLE/CLEAN)** | — | **Ready; operator-only merge; close #938 on merge** |
| terminal-guard origin | wt jolly-jemison | ea889c59 | clean, local-only | none | (already folded as 79a2e926) | SUPERSEDED — never cherry-pick again; archive-tag candidate (PII review first) |
| #937 scorecards | wt xenodochial-wiles `integration/convert-persist-reconcile-authority` | 891bd602 | 3 untracked scorecards | — | — | #937 merged; branch ARCHIVED-candidate; scorecards = RULE-6 salvage |
| Phase 3A persist-hardening (task_d9a464c9) | wt eager-wu | 71a2a757 | 8 | none | writer-level guard in conversion_persistence.py + 2 new tests | **PRESERVED** → evidence-2026-07-17/eager-wu-936eb1/ (315-line patch); Phase 3A input |
| Phase 3B silent-cancel (task_b85be78f) | wt agitated-kepler | 71a2a757 | 3 | none | backfill allow-list fix | **PRESERVED** → evidence-2026-07-17/agitated-kepler-b81d6d/ (220-line patch); Phase 3B input |
| convert-modal edits | wt compassionate-moser | d5a453fd | 4 | none | — | PRESERVED; likely stale vs merged #925/#929/#930 — disposition pending |
| #932-adjacent (series cache) | wt goofy-benz (2), practical-jepsen (6, incl. status endpoint) | d5a453fd | yes | rel. #932 | dictionaries status endpoint | PRESERVED; disposition after #932 |
| dup experiments | wt friendly-blackwell, hopeful-dubinsky-ce2921 | d5a453fd | 1 each (same test file) | none | — | in place; low value |
| 11 clean stale trees | admiring-saha, affectionate-payne, blissful-goldstine, blissful-yalow, competent-lehmann, ecstatic-chandrasekhar, hopeful-dubinsky-1ac358, keen-snyder, lucid-saha, nice-chaum, issue-927(locked) | various | clean | — | — | governance debt; NO deletion this session |

Preservation: all dirty reuse-work snapshotted to `C:\PZ-archive\evidence-2026-07-17\<tree>\`
(tracked `.patch` + `BASE_HEAD.txt` + new test files). No worktree deleted or overwritten.

## Phase 2 result (#938 → #939)

- Repair method: fresh branch off `9417a32f` (squashed #937), cherry-pick `c92914d1 → 79a2e926` only.
- Correctness: `tree(9417a32f)==tree(891bd602)==bca7d2e9` ⇒ zero-conflict; result tree `7f8e5128`
  == byte-identical to `tree(79a2e926)`. Never re-picked ea889c59; never reset to c92914d1.
- Tests: reconcile 54; golden 160/160; PZ 257 (1 #613 env red); carrier 584 (4 DHL-creds env reds);
  proforma-adjacent 118. Worktree clean → tests == commit.
- Reviews (fresh, read-only): reviewer-challenge SHIP-WITH-MITIGATIONS; backend-safety SAFE-WITH-NOTES;
  security-write-action PASS-WITH-MITIGATIONS. Zero HIGH/CRITICAL. GATE 1 satisfied.
- Lesson J N/A (no root engine files in diff).
- #939 OPEN MERGEABLE/CLEAN, base main. **Merge operator-only** (pz-deploy-guard). Close #938 on merge.
- **STOPPED before deployment** (as instructed).

## GATE-4 dispositions (SCHEDULED — filed as a chip; pre-existing in #938, affect the id path too)

1. MED — number path issues read-only `invoices/find` before the terminal guard (wasted round-trip, no write); add `_http_request`-level pin for cancelled+number.
2. MED — two-step split-brain repair completion event de-duplicated in audit.json (state correct; auditability gap).
3. LOW — empty `snap.proforma_number` skips back-reference cross-check (verify matrix still runs); make fail-closed.
4. LOW — `pid` URL path lacks the `.isdigit()` guard the invoice-id path has (bounded).
5. LOW — add `max_length` to `wfirma_invoice_number`.

## Next exact step

Operator: squash-merge #939 (or direct me), then close #938. This session HOLDS Phase 3 (A/B/D)
pending operator go — Phase 3C (transport-m1) is owned by the concurrent session and out of scope here.

## Merge record + final status (2026-07-17)

| PR | Outcome | SHA / state |
|---|---|---|
| #937 | MERGED (squash) | `9417a32f` |
| #939 (repair of #938) | **MERGED (squash)** | `9d137850` — result tree byte-identical to #938 head |
| #938 | **CLOSED** superseded by #939 | — |
| #932 (series-dictionary refresh) | **MERGED (squash)** | **`11023d13e43f840de8409f90f9597001e533b8fc`** — revalidated on current main (44-suite + golden 160/160 + PZ 257 + carrier 584; no duplicate authority; extends shared `refresh_from_wfirma()`) |
| #940 (transport-m1) | **OPEN / DRAFT / HELD** | head `13d442e9`; registry lock NOT transferred (owner still M1-gate session); NOT modified |

**#940 merge-safety pre-check (integration evidence only — NOT GATE-6):** three-way test-merge of
`13d442e9` into current main is clean and PRESERVES #939 (`find_invoices_by_fullnumber`=1,
`_terminal_draft_refusal`=3, `wfirma_invoice_number`=25); merged battery green (proforma-adjacent 172,
carrier/CMR 86, PZ 257, carrier **596**, golden 160/160). The scary two-dot `−439/−100` was a
merge-base artifact (#940 branched off `9417a32f`, pre-#939), not a revert.

**#940 remaining before merge:** (1) real GATE-6 browser verification against an environment that
serves #940's code with authenticated representative carrier/shipment data — NOT claimable from the
wrong worktree / source-grep / backend tests; (2) post-merge follow-up: carrier baseline `584→596`
(path A — floor stays 584 for the PR since 596 ≥ 584; bump lands after #940 merges).

**GATE-6 verification attempt 2026-07-17 → HOLD (environment, not code):** all three prerequisites
absent — no server that serves 13d442e9 (preview_start serves C:\PZ-verify; only staging ref is an
Atlas hardcoded mockup), no non-prod auth account (no local .env / no auth-bypass; only prod
X-API-Key), no safe representative multi-DB dataset (only wFirma-live seeder + layer-isolated pytest
fixtures). Live-DHL risk on this creds-present host for the AWB-booking flow. #940 code NOT modified
(no defect found), registry lock NOT transferred, C:\PZ-pr7 NOT touched. Full evidence + minimal
repair plan: reports/campaigns/2026-07-17-pr940-gate6-hold.md. #940 stays DRAFT/HELD.

**No production deployment performed. Transport-m1 registry lock untouched.**
