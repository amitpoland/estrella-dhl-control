# Phase 6F.5 — Operator Decision Memo

> **Status:** decision-aid for operator. NOT a sign-off. NOT an
> implementation kick-off. The operator must sign §13 of the
> `phase-6f-5-dual-write-approval-package.md` for implementation to begin.
> **Date:** 2026-05-16.

This memo is a one-page traffic-light review of the 6F.5 approval package
against the operator's 10 mandatory checks, plus a recommendation.

---

## 1 — Where we are today

| Item | State |
|---|---|
| 6F.1 / 6F.1.5 / 6F.3 / 6F.4 | Deployed and smoked. Read-only Diagnostics panel live (PR #118, merge `acc92dc`). |
| 6F.2.a (backfill engine) | Merged (PR #117). Engine + 33 unit tests on `main`. |
| 6F.2.b (dry-run vs prod) | Executed. Source rows: **0**. |
| 6F.2.d (live backfill) | **BLOCKED — deferred.** Production `proforma_service_charges` table is empty. |
| 6F.5 approval package | Merged (PR #119, `0b485a0`). 14 sections, 13 hard stops, 3-path rollback. |
| 6F.5 implementation | **BLOCKED — pending §13 sign-off.** |

PZ regression: **160/160** across this session's runs.  
Hard-rule contract suites: **all green** (88 tests in the gate sweep just before this memo).

---

## 2 — Operator's 10 mandatory checks vs approval package evidence

| # | Operator requirement | Evidence in approval package | Verdict |
|---|---|---|---|
| 1 | Feature flags default OFF | §2 — `FINANCE_DUAL_WRITE_ENABLED=false`, `FINANCE_DUAL_WRITE_SHADOW=false` are both `Field(default=False, env=...)` in Pydantic Settings. Explicit early-return guard before any DB open. | 🟢 GREEN |
| 2 | Dual-write fires only AFTER `mark_post_succeeded` | §3 sequencing diagram + §10 H7 (hard stop on firing before). The hook attaches between `mark_post_succeeded` and the audit append in `routes_proforma.py::post_proforma_draft_to_wfirma`. | 🟢 GREEN |
| 3 | Errors swallowed/logged, never roll back legacy commit | §1 ("Failure isolation"), §10 H4 (no shared transaction), §12 R4 (Catastrophic-severity row with mandatory test `test_finance_dual_write_error_swallow.py`). | 🟢 GREEN |
| 4 | No `/post` response shape change | §1 ("does NOT alter the /post route's HTTP response body or status code"), §10 H6 (hard stop). | 🟢 GREEN |
| 5 | No wFirma behavior change | §1 ("Does NOT trigger any wFirma API call"), §10 H2 (no `service/app/services/wfirma*` edits). | 🟢 GREEN |
| 6 | No FX / PZ / settlement behavior change | §1 (no FX, no settle, no allocate), §10 H3 (no `landed_cost.py`, `fx_*`, `golden_constants.py` edits), §11.4 (deferred to 6F.6). | 🟢 GREEN |
| 7 | No UI write button | §10 H12 (hard stop on any "post charge"/"create charge"/"trigger dual-write"/"post payment" button). | 🟢 GREEN |
| 8 | Idempotency key required | §5 — sha1 over `"live_psc:<batch>:<client>:<type>"`, stored as `[live:sha1=<hex>]` prefix in `charges.notes`; postings keyed via `LIVE-<sha1[:16]>` in `wfirma_invoice_id`. Read-only probe before insert. Namespace-disjoint from 6F.2.a backfill keys. | 🟢 GREEN |
| 9 | Source-grep contracts enforce above | §8 lists `test_dual_write_source_grep.py` mandatory checks: hook order, no `try/except` swallowing `mark_post_succeeded`, no `proforma_service_charges_db` import in helper, no `int(.*\*.*100)` (Decimal pin), no wFirma/FX/settlement imports, flag check appears textually before any `create_charge` / `create_posting` call. | 🟢 GREEN |
| 10 | Production deploy keeps flags OFF until separate operator activation | §1 + §2 ("Enabling sequence" is a 4-step gated rollout via env var, not via deploy itself); §10 H10 (hard stop on flipping default to `true` for any environment); §10 H11 (no API-driven flag flip). | 🟢 GREEN |

**Score: 10/10 GREEN.** The approval package addresses every requirement
the operator listed.

---

## 3 — Residual risks the operator should weigh

Even with 10/10 GREEN, three risks deserve explicit operator attention
before signing:

| # | Risk | Operator action implied |
|---|---|---|
| OR1 | The existing `/post` route currently raises `ValueError` on drafts with non-empty `service_charges_json` (line ~3538 of `routes_proforma.py`). Until that block is lifted in a SEPARATE batch, 6F.5 dual-write fires only for **charge-free** drafts. So 6F.5 in isolation produces **zero** new rows in production. | Decide whether to: (a) approve 6F.5 anyway as scaffolding for a future block-lift batch, or (b) defer until the block-lift batch is scoped and gated. The approval package treats this as Risk R1 in §12. |
| OR2 | 6F.2.d remains blocked because production has 0 legacy rows. 6F.5 dual-write rows would be the FIRST data ever written into `finance_postings.sqlite`. The 6F.4 panel will show them; no other surface will. | Decide whether early presence of `LIVE-` postings without any `BACKFILL-` postings is acceptable. (Approval package §5 confirms namespace disjointness — they cannot collide — but operator may want to ensure the order matches the documented "backfill first" assumption.) |
| OR3 | The implementer must NOT relax §10 H1–H13 even under test pressure. Lesson A (real-builder regression) and Lesson D (LOCAL-COMMIT-ONLY disclosure) apply: a `test_finance_dual_write_error_swallow.py` that stubs `create_charge` without a parallel real-builder test would mask a production bug. | Require the implementer to deliver BOTH a stub-based test AND a real-builder integration test in the same PR (per Lesson A). The approval package §8 already lists both styles; confirm this is non-negotiable. |

---

## 4 — Two other live blockers (out of 6F.5 scope but related)

| Blocker | Reason | Why mentioned here |
|---|---|---|
| **6F.2.d live backfill** | Production `proforma_service_charges` has 0 rows. | If the operator wants 6F.5 to ride on top of an already-populated table, 6F.2.d cannot help today — there is nothing to backfill. 6F.5 still works (and writes 0 rows until the `/post` block is lifted), but operator should be aware the panels will remain mostly empty. |
| **`/post` route's hard block on non-empty `service_charges_json`** | Existing safety guard (line ~3538). | NOT in 6F.5 scope. Removing this guard is a separate write-bearing batch with its own approval. The 6F.5 hook is harmless against the current guard; it simply produces no rows. |

---

## 5 — Recommendation

**Recommend: APPROVE 6F.5 implementation, with two binding conditions:**

1. **Implementer MUST honour Lesson A pattern.** Every stub-based dual-write
   test MUST be paired with a real-builder integration test in the same PR.
   No exceptions. (Codified in approval package §8.)
2. **Deploy MUST land with both flags `false` in production env.** The
   implementer's PR description must explicitly state the post-deploy
   env-var verification step:
   ```
   Get-ChildItem env:FINANCE_DUAL_WRITE_*
   # Expected: no entries OR both = "false"
   ```
   Before the operator separately enables shadow, AND before separately
   enabling live, the production NSSM env must be inspected and the change
   recorded with timestamp.

**Why "approve" is sound:**

- All 10 operator requirements are met in the package.
- Default-OFF behaviour means the deploy itself is a no-op (no observable
  production change until env-var flip).
- The hook is failure-isolated by design — a bug in the dual-write cannot
  damage the legacy commit path.
- Idempotency keys + namespace disjointness mean re-runs and concurrent
  posts are safe.
- 13 hard stops + 7 source-grep contracts pin the boundary mechanically.

**Why "defer" remains defensible:**

- Production has 0 legacy rows and `/post` blocks non-empty charges. 6F.5
  is currently a no-op surface. Operator may prefer to do less, not more.
- 6F.5 is the first write-bearing batch in Phase 6F. Operator may prefer
  to stabilize 6F.4 in production for ≥ 1 week before adding any new
  write path, even a default-OFF one.

---

## 6 — If operator APPROVES

Exact next command:

```bash
cd "C:/Users/Super Fashion/PZ APP"
git checkout main && git pull --ff-only origin main
git checkout -b feat/phase-6f-5-dual-write

# Files to create/modify (no others without re-approval):
#  - service/app/core/config.py: +2 Field(default=False, env=...) lines
#  - service/app/services/finance_dual_write.py: NEW helper (with __all__ = ["dual_write_proforma_post"])
#  - service/app/api/routes_proforma.py: 5-line hook between mark_post_succeeded and audit.append
#  - service/tests/test_finance_dual_write_default_off.py (NEW)
#  - service/tests/test_finance_dual_write_idempotent_rerun.py (NEW)
#  - service/tests/test_finance_dual_write_decimal_safety.py (NEW)
#  - service/tests/test_finance_dual_write_legacy_isolation.py (NEW)
#  - service/tests/test_finance_dual_write_error_swallow.py (NEW)
#  - service/tests/test_finance_dual_write_no_collision_with_backfill.py (NEW)
#  - service/tests/test_dual_write_source_grep.py (NEW contract)
#  - service/tests/test_finance_dual_write_real_builder.py (NEW — Lesson A real-builder)
#  - tasks/campaign-state.json: 6F.5 blocked -> active -> pr_open

# Verify gates before pushing:
cd service
python -m pytest tests/test_finance_dual_write_*.py tests/test_dual_write_source_grep.py -v
python -m pytest tests/test_finance_postings_contracts.py tests/test_finance_panel_contracts.py tests/test_master_data_hard_rules.py tests/test_runner_v2_hard_rules.py -q
cd ..
PYTHONIOENCODING=utf-8 python test_pz_regression.py  # must be 160/160
```

After PR opens, run the standard 7-agent deploy gate. The dashboard is
unaffected; the only deploy surface is the backend (`config.py`,
`finance_dual_write.py`, `routes_proforma.py`).

---

## 7 — If operator DEFERS

Mark 6F.5 explicit-deferred reason in `tasks/campaign-state.json`:

```
"block_reason": "Operator deferred 6F.5 dual-write implementation. Reason: <operator-supplied>. Re-evaluate after <criterion>."
```

Then recommend the next safe batch:

| Candidate | Classification | Why safe |
|---|---|---|
| **6F.6 settlement-close + FX delta capture** | Write-bearing | NOT safer than 6F.5 — defers a different write-bearing batch but still requires its own approval package. Probably not a good "next safe" pick. |
| **6F.7 legacy `proforma_service_charges` deprecation** | Destructive | EXPLICITLY out of order; requires 6F.5 to have run in production for ≥ 1 month per §10.7 of `phase-6f-readiness-2026-05-16.md`. |
| **6F.2.f standalone audit/freeze** | Docs-only | Permitted as standalone no-op audit per §6F.2.f planned state. Safest "do less" option: closes the 6F.2 sub-campaign with a final freeze doc, leaving 6F.2.d in deferred state. |
| **Browser smoke completion for 6F.4** | Manual operator task | Open Diagnostics, exercise the panel, record screenshots into `tasks/smoke-reports/2026-05-16-phase-6f-4-finance-panel.md`. Zero implementation risk. |
| **`/post` route block-lift inspection (read-only)** | Inspection-only | Read `routes_proforma.py` line ~3538 area + write an inspection report on what would need to change to allow non-empty `service_charges_json` on /post. Builds the foundation for a future block-lift batch without writing code. |

**Top recommendation if deferred:** Close 6F.2.f (audit/freeze) AND
complete the 6F.4 browser smoke. Both are zero-implementation-risk and
leave Phase 6F in a tidy paused state until operator is ready to revisit
6F.5.

---

## 8 — Sign-off

The operator's response to this memo must be one of:

```
( ) APPROVE 6F.5 implementation with binding conditions §5.1 + §5.2.
    Implementer: proceed with the §6 next command.

( ) DEFER 6F.5. Reason: ______________________________
    Re-evaluate after: ____________________________
    Implementer: proceed with §7 alternative (specify which):

( ) REJECT 6F.5 indefinitely. Reason: ______________
    Mark batch in campaign-state with block_reason and depends_on=[].
```

Signed: __________________________  
Date/time: __________________________
