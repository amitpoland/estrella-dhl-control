# TASK_STATE.md

## Current task

- **Task:** EJ Accounting + CFO MIS — AP payment→expense persist repair
- **Worktree:** `C:\PZ-wt\accounting-cfo-mis` branch `fix/ap-payment-expense-link`
- **State:** `VALIDATING` (financial gate PASS; persist code not deployed)
- **HOLD class:** none

## HOLD reason (one line)

(none) — local AP remaining now equals live Supplier Ledger by currency. Persist code is not yet on production `b03143ee`.

## Proven (do not re-open)

- Diamond Point Client Ledger opening/closing/contiguous/PDF — PASS
- AR local vs locked 2026-08-17 — MATCH (EUR/PLN/USD)
- PR #1268 already merged/deployed: `b03143ee`; rollback unit `b03143ee-20260817-083240`
- Five-supplier AP remaining local == live (0.00)
- Full AP Class-C unexplained = ZERO (CHF/EUR/PLN/USD MATCH)
- Aging invariant local+live true per currency

## AP persist repair (2026-08-17)

Root cause: `insert_payment_snapshot` omitted `expense_id`. Fixed write path + historical backfill of `C:\PZ\storage\payment_state.db`.

Coverage: 3023/0 linked → 3058/2038 linked. Unapplied: 1018 invoice-linked AR + 2 neither.

Evidence:
- `.claude/memory/AP-PAYMENT-EXPENSE-REPAIR-2026-08-17.md`
- `.claude/memory/FINANCIAL-TRUTH-GATE-AP-POST-REPAIR-2026-08-17.json`
- DB backup: `C:\PZ\storage\payment_state.db.bak-ap-expense-2026-08-17`

## Next

1. Commit/PR persist code on `fix/ap-payment-expense-link`
2. Seven-agent gate + App deploy (required so new scheduler inserts keep `expense_id`)
3. **Deploy PR note for Finance:** first local MA / payables load after deploy will show lower open AP — backfilled `expense_id` links activating; intended correction, not a regression.

Adversarial review ([AP persist adversarial review](fdd37b72-2db0-4341-853f-fed068a3bc77)): SHIP WITH MITIGATIONS — no blockers. Mitigations applied: converge-clear WARNING log + cross-contractor knock-off test.

Do not roll back `b03143ee` for this defect.
