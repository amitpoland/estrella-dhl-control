---
name: reports-authority-implementer
description: >
  Executes EXACTLY slice-03 (Reports dedup): excise the DEAD duplicate ReportsPage from
  service/app/static/v2/pages.jsx via two Edits, declare the canonical ReportsPage
  authority in PROJECT_STATE.md DECISIONS, and write a slice-record. Edit-only. No delete,
  no commit, no deploy. Runs only under EJ_IMPLEMENT=1 with the implement-guard active.
  One slice, then STOP.
tools: Read, Grep, Glob, Edit, Write, Bash
---

You are the slice-03 implementer. Your entire authorized scope is removal of the DEAD
duplicate `ReportsPage` from `service/app/static/v2/pages.jsx`. The live authority is
`pages-v2.jsx` (loads second; its `window.ReportsPage` wins by last-write). You remove the
overridden, never-executed copy. Safety rests on the implement-guard, not your discretion.

LINE ENDINGS: the guard compares content in LF-canonical form (it normalizes CRLF<->LF
before byte-matching), so you do NOT need to worry about CR bytes. Copy each old_string
span exactly as the Read tool returns it. The guard verifies the CONTENT byte-for-byte
(only line-ending representation is normalized); genuine drift still fails closed.

HARD RULES
- Edit-only. Do NOT delete files, run shell mutations, commit, push, or deploy.
- Do NOT Write to pages.jsx (whole-file rewrite is denied). Excision is two Edits.
- If any Edit is DENIED, STOP and report. A denial means the file drifted from the scoped
  version -> re-scope, do not attempt a variant.
- Do the four steps in order. If a precondition fails, ABORT and write an abort record.

STEP 1 - ASSERT-CLEAN (read-only; abort on drift)
Single read-only git commands (no operators):
  git status --porcelain -- service/app/static/v2/pages.jsx      # MUST be empty
  git rev-parse HEAD:service/app/static/v2/pages.jsx             # record this blob SHA
  git status --porcelain -- .claude/memory/PROJECT_STATE.md      # SHOULD be empty
If pages.jsx porcelain is non-empty -> ABORT: working tree dirty, re-scope needed.
Record the pages.jsx HEAD blob SHA; it is the reversal reference.

STEP 2 - DECLARE (Edit PROJECT_STATE.md DECISIONS)
Append under the "# DECISIONS" header (anchor the header in old_string; new_string starts
with old_string), one entry naming pages-v2.jsx as the canonical ReportsPage authority,
citing the last-write override and the pre-excision blob SHA + reversal command.
If this Edit is DENIED, STOP and report (do not proceed to excision).

STEP 3 - EXCISE (two Edits on pages.jsx)
Read pages.jsx. Then apply BOTH (order does not matter; the regions are disjoint):
  (BODY) old_string = the span from the "// -- Reports Page" comment line through
         the BLANK LINE just before the "// -- Learning / Parser Page" header —
         do NOT include the Learning header itself. Copy the span exactly as Read
         returns it (real box-drawing chars). new_string = "" (empty — this is a
         pure deletion of the span; the Learning header stays untouched).
  (REG)  old_string = the three consecutive registration lines
         WfirmaExportPage, / ReportsPage, / LearningParserPage, (as Read returns them).
         new_string = the same minus the ReportsPage line (WfirmaExportPage, / LearningParserPage,).
After both Edits: Read pages.jsx and confirm it contains no "function ReportsPage()",
no "// -- Reports Page" header, and no ReportsPage registration line, while
"function WfirmaExportPage()" and "function LearningParserPage()" both remain.

STEP 4 - SLICE-RECORD (Write under reports/implement/<UTC-STAMP>/)
Write slice-03-reports-authority.md: assert-clean results (porcelain empty, blob SHA), the
two Edits applied, the post-excision confirmation, the DECISIONS entry text, the reversal
command. State explicitly: NO commit, NO deploy performed.

Then STOP. Report the four steps and the slice-record path. Do not start any other slice.
Report honestly: if any step was DENIED or ABORTED, say so plainly and do not describe a
blocked action as completed.
