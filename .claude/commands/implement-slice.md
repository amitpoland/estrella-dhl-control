---
description: >
  Run slice-03 (Reports dedup) via reports-authority-implementer. Edit-only excision of the
  dead duplicate ReportsPage from pages.jsx, guarded (line-ending agnostic). Requires
  EJ_IMPLEMENT=1, EJ_CENSUS unset, and NOT plan mode.
allowed-tools: Task, Read, Grep, Glob
---

Preconditions (verify before dispatch; if any fails, STOP and tell the operator):
- EJ_IMPLEMENT=1 set and EJ_CENSUS unset (guard dual-mode fail-closed).
- Not in plan mode (plan mode is incompatible with the guard edit path).
- verify_guard.py reported ALL PASS in this environment.
- A live guard probe on the box showed a legitimate pages.jsx Edit is now PERMITTED
  (v1 wrongly blocked LF old_string against the CRLF working tree; v2 fixes this).
- pages.jsx tracked and clean at HEAD (the agent re-asserts as step 1).

Dispatch EXACTLY ONE Task to subagent_type "reports-authority-implementer":
"Execute slice-03 per your specification: assert-clean, declare ReportsPage canonical
(pages-v2.jsx) in PROJECT_STATE.md DECISIONS, excise the dead duplicate from pages.jsx via
the two Edits (BODY + REG), write the slice-record. Edit-only. No commit, no deploy. STOP.
Report honestly - do not describe a blocked step as completed."

Do not dispatch any other agent. Do not commit or deploy. After the agent returns, surface
its four-step report and slice-record path, and STOP. Commit is a separate operator step in
a plain shell with both mode flags unset.
