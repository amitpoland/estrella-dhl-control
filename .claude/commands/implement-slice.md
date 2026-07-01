---
allowed-tools: Task, Read, Grep, Glob
description: >-
  Run ONE gated mutation slice (slice-01 shipment-authority) via the implementer
  subagent, read back its slice-record, print summary + reversal command, STOP.
  Orchestrator holds no write/shell tools; the subagent mutates under implement-guard.
---

# /implement-slice — one gated slice, then hard stop

You are the slice ORCHESTRATOR. You dispatch ONE implementer subagent and then read
and summarize its record. You hold no Edit/Write/shell tools — you cannot mutate. All
mutation happens inside the subagent, confined by implement-guard.py.

## Preconditions (state them; if unmet, stop and tell the operator)
- This session must be launched with EJ_IMPLEMENT=1 and EJ_CENSUS UNSET.
  (If EJ_CENSUS is also set, the guard fails closed and nothing will run — restart.)
- cwd = C:\PZ-verify (not a worktree).
- NOT in plan mode. Plan mode needs a plan-file write that implement-guard denies
  (same deadlock as census). If in plan mode: instruct the operator to Shift+Tab out,
  then re-invoke. Do not try to write a plan file.

## Run
1. Dispatch the `shipment-authority-implementer` subagent via Task, instructing it to
   execute slice-01 per its contract (assert-clean -> declare -> delete -> slice-record),
   hard-stop after the slice, and abort with an ABORT-RECORD if assert-clean fails.
2. When it returns, Read the slice-record (or ABORT-RECORD) it wrote under
   reports/implement/<UTC>/.
3. Print a summary: outcome (COMPLETED | ABORTED), the DECISIONS entry, the two blob
   SHAs, the two deleted paths, and the exact reversal command.
4. STOP. Do not commit. Do not deploy. Do not start another slice. Deploy to C:\PZ
   remains a separate manual operator step.
