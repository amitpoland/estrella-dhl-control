# A1 / A1.1 — Local Checkpoint Closure (FROZEN)

**Date:** 2026-07-18
**Branch:** `claude/quirky-kilby-5710b1` (NOT pushed — no upstream)
**Ledger status:** untracked campaign evidence (preserves the branch commit sequence exactly)

## Closure state

```
A1:                                COMPLETE
A1.1:                              COMPLETE
Integration-readiness corrections: COMPLETE
Local checkpoint:                  READY
Remote review:                     NOT STARTED
Production frozen:                 NO
A2:                                BLOCKED
Logistics:                         BLOCKED
```

Council verdict: **LOCAL_CHECKPOINT_READY — ACCEPTED.** A1/A1.1 additional work CLOSED.

## Preserved commits (do NOT amend / squash / rebase / cherry-pick)

| SHA | Commit |
|---|---|
| `463fbda4` | refactor(proforma): extract pure invoice comparison authority (A1) |
| `f4ecf13e` | test(proforma): A1.1 harden invoice comparison authority |
| `c175c476` | docs(proforma): mark invoice comparison ADR proposed; clarify coverage metric |
| parent `46760572` | #940 (on main history) — A1 base SHA |

## Approved architecture (frozen)

FinalInvoicePlan → `document_comparator.compare_invoice_plan` → `InvoiceComparisonResult`
→ `routes_proforma._verify_created_invoice` (blocking authority) → existing Create + Reconcile callers.
Comparator owns pure comparison only. ADR: `docs/decisions/ADR-invoice-comparison-authority.md` (status **Proposed**).

## Blocker

Not an A1 defect. Blocked solely by **GATE-2** (impl-PR cap = 3; #942, #943, #944 all OPEN;
#944 overlaps the future carrier-persistence surface) and the need to revalidate local commits
against whatever lands on `main` before a focused PR.

## Next authorized step (operator-initiated)

When one of #942/#943/#944 clears, run the **A1 Integration Gate** (NOT another hardening campaign,
NOT A2):
1. fetch current `main`; inspect every commit since `46760572`;
2. identify overlap with the A1/A1.1 file set — especially `routes_proforma.py`, verifier tests,
   reconciliation tests, ADR conventions, test baselines;
3. integrate by the repository-approved method;
4. rerun the bounded suites + root regression;
5. push one branch; open ONE focused PR (A1 + A1.1 + correction only);
6. obtain remote CI + architecture review;
7. flip ADR **Proposed → Accepted** only after approval.
A2 requires a **separate ruling after merge**.

## Standing rule added this closure — FRONTEND ADAPTABILITY GATE (permanent, refined)
FE owns adaptable presentation + reversible workflow composition; BE owns canonical data,
authorization, validation, persistence, irreversible actions, domain decisions. **Frontend-first ≠
frontend-only-at-any-cost:** frontend-only is required when the existing contract already carries
sufficient authorized data; a BE contract extension is allowed when the FE genuinely lacks canonical
data but must expose **reusable domain data/capability, not one screen's layout**. Reject UI-shaped
endpoints, business rules recreated in JS, and sensitive data sent for client-side filtering. FE
decides how data is shown, never whether a financial/customs/inventory/shipment action is valid.
Binds A2 + Campaign-4 (ShipmentCard). Canonical home = CLAUDE.md but **DEFERRED** — requires its own
explicit execution ruling + PR-cap verification (NOT auto-authorized by any "+1 docs" allowance; not
on this frozen A1 branch). Recorded: memory `feedback-frontend-adaptability-gate`, master plan §17.

## Standing prohibitions during the wait
No further A1 hardening. No push while GATE-2 full. No 4th impl PR. No A2. No logistics.
Do not touch PR #944 carrier surfaces, comparator behavior, tolerance/ordering, wFirma,
reconciliation persistence, DB schema, feature flags, or unrelated dirty files.

## Local evidence (checkpoint-valid; NOT remote CI / release approval)
Bounded gate 143 passed; root regression 160/160; mutation 11/11 killed; custom line metric
100% (65/65 executable-body lines — not coverage.py branch coverage); benchmark ~101 µs/op.
Baseline: the 5 unrelated failures reproduce on clean base `46760572` (pre-existing).
