# OPERATING MODEL reset — the full instruction (operator's words, verbatim, 2026-08-07)

> Extracted verbatim from CLAUDE.md on 2026-08-19 as part of the governance-thinning
> experiment. This is the NORMATIVE source for the CI-authority and runtime-payload
> rules summarised in CLAUDE.md. Read it when the summary is disputed or a boundary
> case is being interpreted. Do not paraphrase this text.

---

### The full reset instruction (operator's words, verbatim, 2026-08-07)

The two permanent rules above are excerpts of this ruling. The complete instruction is
recorded here verbatim and is the normative source for the CI-authority and
runtime-payload subsections below.

> RESET OPERATING MODEL.
>
> Production delivery authority is:
>
> Fix → targeted tests → ONE seven-agent gate → merge → deploy → smoke test → close.
>
> GitHub Actions CI is diagnostic only and MUST NOT gate production. Never wait for
> aggregate-green when main carries inherited failures. Do not classify historical CI
> failures unless a changed file is implicated.
>
> After seven-agent GO, production deployment becomes Priority 1. No test-only PR, docs
> PR, GATE-4 task, observer, scorecard, memory update, queue arithmetic, CI run, or
> unrelated finding may delay it.
>
> Only a new HIGH/CRITICAL executable defect in the pending runtime change may stop
> deployment.
>
> LOW/MEDIUM findings go to backlog and are not implemented during the active release.
>
> Test-only changes do not invalidate a prior production-code gate when production bytes
> are unchanged.
>
> Seven-agent review runs once per runtime payload, not once per subsequent bookkeeping
> commit.
>
> After deployment and smoke verification, resume backlog work.
