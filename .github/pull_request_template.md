<!--
PR closure contract. Fill every section. A PR that leaves a required section blank
is not ready to merge (CLAUDE.md GATE 1 + docs/EXECUTION_PROTOCOL.md closure gate).
The builder does not grade itself — a separate reviewer checks this against the
frozen acceptance criteria.
-->

## Summary

<!-- One PR-sized slice. What changed and why, in 2–4 lines. -->

## Authority owner

<!-- The ONE system that owns the truth this PR changes (named BEFORE coding).
     e.g. PZ lifecycle · Customs · wFirma · awb_address_authority.py · Customer Master.
     If this PR touches truth owned elsewhere, that is duplicate authority — explain. -->

## Acceptance criteria (frozen before implementation)

<!-- Paste or link the criteria as agreed BEFORE coding. Reviewer marks each. -->

- [ ] <criterion 1> — PASS / FAIL / VERIFY-GAP
- [ ] <criterion 2> — PASS / FAIL / VERIFY-GAP

## Tests

<!-- Exact command(s) + pass/fail counts vs baseline. State failures honestly.
     Baselines: PZ regression, carrier suite (.claude/contracts/test-baseline.md). -->

```
<command + result>
```

## Browser / API verification

<!-- UI: pages loaded + console (no new red) + network (no unexpected 4xx/5xx).
     Backend/admin: curl + audit-log evidence.
     "N/A — no operator-facing surface" only when literally true. -->

## Rollback plan

<!-- Exact command / SHA to revert this slice. -->

## PROJECT_STATE.md updated

- [ ] `PROJECT_STATE.md` updated — slice moved to its correct section (Completed /
      In Progress / Blocked / Next), with evidence cited.

## Sensitive-system impact

<!-- Declare explicitly. Tick the first box OR list the systems + paste operator approval. -->

- [ ] This PR does **not** touch financial / customs / inventory / DHL / wFirma /
      accounting / production-write logic.
- [ ] This PR **does** touch one or more of the above. Systems: __________________.
      Operator approval (required, paste/link): __________________.

## Gate checklist

- [ ] One PR-sized slice; no out-of-scope file edits
- [ ] Authority owner named before coding
- [ ] Acceptance criteria were frozen before implementation
- [ ] Built and reviewed by different parties (no self-grading)
- [ ] No operator-visible capability suppressed without a cancellation record (Lesson M)
- [ ] For production sync: the 7-agent deploy gate is run separately and is operator-gated
