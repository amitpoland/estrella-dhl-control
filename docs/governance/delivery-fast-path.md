# Delivery fast path — risk-based governance

**Status:** implemented 2026-08-20. Subordinate to CLAUDE.md § OPERATING MODEL,
the Engineering Lessons and the seven-agent gate. It **adds no authority**: it
classifies, validates and reports. Deployment authorization remains solely with
`.claude/hooks/deploy_authorization.py` + `gate_evidence.py`.

## 1. Why

Validation cost was **risk-blind**. Every `.py` edit anywhere in the repository
paid the 1.46 s root golden regression suite, including edits to files the
golden suite cannot reach. 1,656 of 1,776 tracked `.py` files live under
`service/` and are outside the golden import closure entirely.

## 2. Entry point

One command. There is no second way in.

```bash
python .claude/hooks/deliver.py plan
```

| Command | Does |
|---|---|
| `deliver.py plan` | classify the changeset, print lane + required validation, write a revision-bound checkpoint |
| `deliver.py validate` | run only the validation the lane requires; emit contract verdicts |
| `deliver.py status` | re-derive branch/HEAD/worktree/payload-digest and report FRESH or **STALE** |
| `deliver.py next` | the single next action |

It **deliberately cannot** deploy, authorize a deploy, merge, or sign anything.

## 3. Risk lanes

A **mapping** over the repository's pre-existing 10-class file taxonomy, not a
new taxonomy. `.claude/hooks/risk_lanes.py`, function `classify_path`.

| Lane | Contents | Deploy | Required validation |
|---|---|---|---|
| **BLOCKED** | forbidden paths (`.env`, `storage/`, `outputs/`, `logs/`, `*.db`, `cloudflared/`) | never | none — nothing may proceed |
| **L2** | AUTH_SECURITY, DB_SCHEMA, CONFIG_RISK inside the payload; ENGINE_CORE; GOVERNANCE | yes, if payload | targeted + floors + golden + seven-agent gate + extended review |
| **L1** | ordinary application change inside `service/app` | yes | targeted + floors + seven-agent gate |
| **L0** | everything outside the runtime payload (docs, tests, CI) | **never** | targeted only |

Measured surface: about **64 of 530 runtime files are L2 (12%)**; 88% are L1.

**Lane and `deploy_required` are independent axes.** A changeset can be L2 —
strongest review — while carrying zero runtime bytes and therefore
`deploy_required=False`. This campaign's own changeset is exactly that case.

### 3.1 The L0 default rests on a pinned invariant

`classify_path` grants L0 to any path it does not positively recognise, on the
stated ground that it is *never copied to production*. That is truthful only
while the deployment procedure copies exactly two things: the `source_app` tree
and the 16 named `engine_files`. Nothing in the config enforced that
correspondence, so it is pinned by
`service/tests/test_delivery_pipeline.py::test_copy_surface_is_exactly_app_plus_engine_files`.
**If a third copy directive is added to `windows_prod_v2.json`, that test fails
and `risk_lanes` must learn it before the config change lands** — otherwise real
production bytes would classify L0 with `deploy_required=False`, the
optimistic-by-default error class of Lesson Q rule 6.

When the config cannot be loaded, `classify()` threads the error into every
path and the whole changeset fails closed to **L2/UNKNOWN**.

## 4. Exit code is execution evidence, not authorization

Measured, not theoretical:

```
service/tests/test_carrier_*.py   ->  exit 1, 758 passed, 3 failed
contract floor                    ->  604 required  (PASS, +154)
all 3 failures                    ->  registered in the known-failing exclusions
```

A pipeline gating on `exit == 0` blocks that deploy. A pipeline gating on
`.claude/contracts/test-baseline.md` passes it, correctly. `lane_validation.py`
computes the verdict from the **contract**, reads *content* from `--junitxml`
(Lesson S rule 8 — never from summary-line formatting), and reports
`exit_code_agrees_with_verdict` so disagreement is visible rather than silent.

Verdicts: `PASS` · `PRE_EXISTING_FAILURE` · `CAMPAIGN_FAILURE` · `FLOOR_BREACH`
· `INCOMPLETE`. Only the first two are advanceable.

## 5. Self-healing protocol

On failure, do not stop and hand the error over. In order:

1. capture the exact failure (command, exit status, stderr);
2. classify it — campaign-introduced / pre-existing / environmental /
   operator-only / transient / evidence the design is wrong;
3. investigate root cause; read primary documentation if the behaviour is a
   platform question;
4. choose the smallest sound repair;
5. implement it if it is inside campaign authority;
6. re-run the **narrowest decisive** validation;
7. continue.

**A retry must follow either a repair or evidence that the failure was
transient.** Arbitrary retry loops are prohibited. An operator-only boundary is
a stop; inconvenience is not.

## 6. Hook performance — disposition

`p95 > 500 ms` is a **review threshold, not an automatic deletion trigger**.

> **WITHDRAWN (Lesson Q rule 5 — marked, not deleted):** an earlier measurement
> in this campaign reported the PreToolUse:Bash chain at **p50 333 ms / p95
> 377 ms**. That figure was a *sum of per-hook timings* and was wrong. The
> Claude Code hooks documentation states verbatim that **"All matching hooks
> run in parallel."** Corrected by re-measurement, 9 samples each, warm cache:

```
  SERIAL   (the withdrawn sum-of-parts model): p50 359.4 ms   p95 363.6 ms
  PARALLEL (what the harness actually does):   p50 104.2 ms   p95 128.3 ms
```

Per-guard isolated p50: `pz-deploy-guard` 69.8 · `pz-danger-guard` 69.7 ·
`campaign-branch-guard` 82.6 · `census-guard` 69.1 · `implement-guard` 68.3 ms.
The floor is interpreter start, not hook logic.

**Disposition for all five PreToolUse guards: KEEP SYNCHRONOUS, unconsolidated.**
Consolidating them into one dispatcher could save at most ~34 ms (104 -> ~70 ms
interpreter floor) while merging five independent security guards into a single
failure domain. 128 ms p95 is far below the 500 ms review threshold. Trading
blast-radius isolation for 34 ms would be weakening a high-risk control to buy
wall-clock time.

`hooks/pre-commit` (core.hooksPath) is **conditional, not duplication** — it
runs the golden suite only when `golden_constants.py` is staged.

## 7. What actually got faster

The removed duplication is the risk-blind golden run in
`.claude/hooks/pz-regression-postedit.py`, which now runs the suite only for
edits inside the measured golden import closure:

```
pz_import_processor.py          exit=0  wall= 1626 ms  'regression: 160/160 green'
service/app/api/routes_pz.py    exit=0  wall=   79 ms
service/tests/test_routes_pz.py exit=0  wall=   73 ms
docs/notes.md                   exit=0  wall=   72 ms
```

About **95%** off the per-edit tax for out-of-surface `.py` files. The closure
is re-measured empirically, not trusted, by
`test_delivery_pipeline.py::test_golden_surface_is_root_only`; the skip is
fail-safe (anything unresolvable runs the suite). The reported count is now
derived from the run's own output — it was previously a hardcoded `160`.

## 8. Resuming (Lesson Q rule 7)

`deliver.py` records a **runtime-payload digest** — the `service/app` tree
object id plus the 16 engine blob ids — not merely the commit SHA. Two commits
with identical runtime bytes share a digest; a docs-only commit on top of a
gated head does not invalidate the gate, which is exactly what the OPERATING
MODEL says. `status` re-derives branch, HEAD, worktree and digest and reports
**STALE** rather than trusting the checkpoint file.

## 9. Residual risks

1. **PostToolUse matcher gap.** The regression gate is registered on
   `Edit|Write`. A `.py` file modified through Bash (`sed`, heredoc) does not
   trigger it. This predates the campaign and is unchanged by it; the gate is a
   convenience, not an authority — the metered floors and the seven-agent gate
   are the real controls.
2. **Contract parsing is regex-based** over `test-baseline.md`. It fails closed
   (fewer than 2 metered suites parsed = refuse), but a table reformat would
   surface as `INCOMPLETE` rather than a precise error.
3. **Two inert guards** (`census-guard`, `implement-guard`) cost ~69 ms each
   while env-gated OFF. Kept: they are cheap in parallel and removal would be a
   security-surface change for no measured gain.
