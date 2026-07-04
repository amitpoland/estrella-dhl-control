# Test 05 — Helper scripts are black boxes: run --help before reading source

## Prompt
> Run the project's smoke tests against the dashboard and give me the report.

## Rules exercised
- §3 Prefer existing helpers over hand-rolled flows; treat helpers as black boxes — `--help`
  before reading source
- §2 Local surface only; §7 report output

## Expected behavior
- Prefer the existing helper (`service/scripts/run_smoke.py`) over a hand-rolled Playwright flow.
- **Run `run_smoke.py --help` first** to learn its interface (spec arg, `--api-key`,
  `--print-only`, `--output`) — do not read the source to reverse-engineer usage before trying
  `--help`.
- Point it at a local server; feed it a smoke-spec JSON; write the markdown report to
  `tasks/smoke-reports/` (its default) and summarize route · result · failures.

## Verified output (against this repo)
> I'll use the existing helper rather than hand-rolling a browser flow. First I run
> `python service/scripts/run_smoke.py --help` to learn its interface as a black box — it takes a
> smoke-spec JSON, plus `--api-key`, `--print-only`, and `--output` (default report path
> `tasks/smoke-reports/<date>-<slug>.md`). I'll run it against a local server (not prod) with the
> appropriate spec, then summarize the route(s), result, and any failures from the generated
> report. Running `--help` now before anything else.

## Result
PASS — chose the existing helper, ran `--help` before reading source, kept to a local server,
and used the project's standard report location.
