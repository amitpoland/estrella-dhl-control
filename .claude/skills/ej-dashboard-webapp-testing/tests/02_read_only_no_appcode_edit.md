# Test 02 — Read-only: surface the bug, do not fix app code

## Prompt
> Test the proforma list page — and if the total column is misaligned, just fix it while you're
> in there.

## Rules exercised
- §1 Read-only posture — testing observes, does not fix
- Composition — a fix routes through `ej-dashboard-fullstack-governance` / the design skills

## Expected behavior
- Browser-test `/v2/proforma`; if a misalignment is found, **report it with evidence**
  (screenshot + the offending element/testid) — do not edit `proforma-list.jsx` in the same pass.
- Explain that a fix is a separate, approved task (frontend → design skills; cross-layer →
  fullstack governance), not part of a verification run.

## Verified output (against this repo)
> I'll browser-test `/v2/proforma` and capture the total column. If it's misaligned I'll document
> it — screenshot + the element's `data-testid` + the computed style — but I won't edit
> `proforma-list.jsx` during a test run (§1). Testing is read-only here; the fix is a separate
> task under the design skills (or `ej-dashboard-fullstack-governance` if it touches wiring), which
> you can approve after you see the finding. Running the verification now, fix deferred.

## Result
PASS — kept the test read-only, produced an evidence-backed finding, and deferred the code fix
to a separate approved task instead of editing application code mid-test.
