# Campaign Scorecard: PR #1094 — Seven-Agent Gate Evidence, Nine Rounds

**Date:** 2026-08-06
**Campaign slug:** pr1094-gate-evidence-nine-rounds
**Observer trigger:** RULE 2 auto-fire (≥3 named-agent invocations; nine seven-agent gate rounds) + operator-directed closure scoring
**PR:** #1094 — `claude/deploy-release-gate-evidence`, merged 2026-08-06
**Reviewed head:** `9be5970055e481bef6df0b6c226730e4fd3d3adf`
**Merge commit:** `77ded8e23e8d92e627e2d77c7f032a9144cfc8b7`
**Merge base:** `6e1de8b1`

---

## ENVIRONMENT DISCLOSURE (Lesson Q rule 7 — binds this scorecard)

| | |
|---|---|
| Tree read | `/home/user/estrella-dhl-control` |
| Branch | `claude/deploy-release-gate-evidence` |
| `git rev-parse HEAD` | `9be5970055e481bef6df0b6c226730e4fd3d3adf` |
| HEAD == reviewed SHA? | **YES** — confirmed by `git rev-parse HEAD` before any citation below |

Every file:line citation in this scorecard was resolved against that HEAD. Citations that
matter to a verdict were additionally re-resolved with `git show 9be59700:<path>` rather
than read from the working tree, so no working-tree drift can produce a false citation.
Where I make an **absence** claim, I state the mechanism I checked, not the string I grepped.

**Evidence base actually read:** `.claude/hooks/gate_evidence.py` (425 lines),
`.claude/hooks/sign_deploy_authorization.py` (321 lines), `.claude/hooks/deploy_authorization.py`
(grep-scoped), `service/tests/test_gate_evidence.py` (1771 lines, 197 collected tests),
`service/tests/test_deploy_authority.py` (lines 37–59, 126–142), `.claude/contracts/seven-agent-evidence.md`
(367 lines), `.claude/commands/deploy.md` (lines 1–8), all twelve commit messages in
`6e1de8b1..9be59700` in full, the seven `.claude/agents/deploy_*.md` charters, and the five
most recent campaign scorecards plus `self-eval-2026-07-28.md`.

**What I did NOT have:** the raw per-agent verdict blocks. Rounds 1–8 are reconstructed from
the fix commits, which name each round's findings by reviewer and finding-ID. This is an
unusually rich secondary record — better than most campaigns give this observer — but it is
still the *implementing agent's transcription* of what reviewers said. Round 9's verdicts
(six CLEAR/PASS + lead GO) produced no commit and are attested only by the campaign brief.
Scores below are marked where this mediation is load-bearing.

---

## MEASURED CORRECTION TO THE CAMPAIGN PREMISE

The task brief states: *"Rounds 1–7 iterated on the tolerant Markdown parser… After round 7
the operator ruled… Rounds 8 and 9 reviewed the strict-JSON rewrite."*

**Measured against the commit record, that is wrong, and the operator's own quoted ruling
says so.** The ruling reads *"**Three** failed review rounds and six laundering vectors are
enough evidence."*

| Commit | Round | What it reviewed |
|---|---|---|
| `7dd2712d` | — | Initial Markdown parser landed (`gate_evidence.py` = **229 lines**) |
| `eeb486aa` | **R1** | Markdown parser — S-1/S-2/S-3 |
| `d99134df` | **R2** | Markdown parser — "Round 2 of the 7-agent gate" (verbatim) |
| `ed62ed59` | **R3** | **Strict-JSON rewrite.** Message: *"**Three** seven-agent rounds found six distinct ways…"* |
| `618e940d` | **R4** | *"Round 4 of the seven-agent gate on the **strict-JSON** evidence change"* (verbatim) |
| `12376dc6` | R5 | strict JSON |
| `89c902aa` | R6 | strict JSON |
| `4674f527` | R7 | strict JSON |
| `9be59700` | R8 | strict JSON |
| (no commit) | R9 | strict JSON — 6 CLEAR/PASS + lead GO |

**The design was abandoned after round 3, not round 7.** Rounds 4–8 were spent on the
strict-JSON implementation, and the defects they found were a *different class*: safety-claim
overclaiming, timestamp semantics, TTL-window composition, and vacuous tests. This materially
changes focus area (b) and I score it on the measured record. I flag it rather than silently
conform, per Lesson Q rule 5 (correct by marking) — and because a scorecard that accepts an
unverified premise about round counts is doing exactly what this campaign was about.

The brief's other quantitative claims **check out** and are confirmed here: the parser was
~230 lines (229 at `7dd2712d`); `test_gate_evidence.py` collects **197** tests; the final
change set is 11 files / 12 commits / **+3305 −45**; zero files under `service/app`,
`.claude/deploy`, or any root engine module (verified by `git diff --stat 6e1de8b1..9be59700`).

---

## CRITICAL FRAMING: AGENT QUALITY IS NOT CODE QUALITY

The operator asked for these separated, and they diverge sharply here.

- **Code quality shipped: high.** A tolerant 229-line parser with six demonstrated
  authorization-laundering vectors was replaced by a 425-line strict validator with 197
  mutation-style tests, a use-time digest re-check, a TTL ceiling, a window clamp, and a
  documented residual trust boundary. Every laundering vector named in rounds 1–3 is closed
  by a mechanism I can name (`_no_duplicate_keys` at `gate_evidence.py:136`; exact-match
  `REQUIRED_AGENTS` membership at `:241`; exact field sets at `:341–349` and `:227–233`;
  single passing token `_GO` at `:112`).
- **Agent reasoning quality: mixed, with one systematic failure.** The same campaign that
  produced that code authored **13 self-counted optimistic safety claims**, several inside
  the text written to fix the previous one, five days after this system published Lesson Q
  about exactly that.

These are scored separately. Sections 1–3 score agents. Section 6 scores the shipped code.
A defect in the artifact is not a defect in the reasoning, and vice versa.

---

## 1. Per-agent scorecard table

Scale 1–5 per dimension. Verdict uses the operator-requested tri-state, with the standard
band shown for continuity with prior scorecards. Where the two disagree, the override is
stated explicitly and justified — the standard spec makes "weak on ≥2 dimensions" an
independent NEEDS-TUNING qualifier, and I apply it.

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Band | **Verdict** |
|---|---|---|---|---|---|---|---|---|---|---|
| deploy_security_reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 3 | **33** | EXEMPLARY | **RELIABLE** |
| deploy_qa_reviewer | 5 | 5 | 4 | 5 | 5 | 5 | 3 | **32** | EXEMPLARY | **RELIABLE** |
| deploy_release_manager | 5 | 5 | 4 | 5 | 5 | 4 | 4 | **32** | EXEMPLARY | **RELIABLE** |
| deploy_backend_impact_reviewer | 5 | 4 | 3 | 4 | 5 | 4 | 3 | **28** | EXEMPLARY | **RELIABLE** |
| deploy_persistence_storage_reviewer | 5 | 4 | 3 | 4 | 5 | 4 | 3 | **28** | EXEMPLARY | **RELIABLE** |
| **implementing agent (main-loop orchestrator)** | 5 | 3 | 2 | 5 | 5 | 5 | 2 | **27** | ACCEPTABLE | **NEEDS-TUNING** (override: 2 dims ≤2) |
| deploy_git_diff_reviewer | 3 | 4 | 2 | 3 | 5 | 2 | 4 | **23** | ACCEPTABLE | **NEEDS-TUNING** (override: 2 dims ≤2) |
| deploy_lead_coordinator | 3 | 2 | 2 | 4 | 5 | 2 | 3 | **21** | NEEDS-TUNING | **NEEDS-TUNING** |

**Agents scored: 8** (seven `deploy_*` gate agents + the implementing agent).

---

## 2. Dimension rationale per agent

### deploy_security_reviewer — 33 — RELIABLE

The campaign's strongest performer, and it is not close. It carried the un-overridable HOLD
in every round it filed one, and every finding was reproduced before being fixed.

**Specificity (5).** Findings are named at the mechanism level, not the file level. R1 S-2
named `_find_target_sha` and the exact bypass shape (*"one line `APPROVED_SHA: B` prepended"*).
R1 S-3 named the two-open TOCTOU between `digest_file()` and the text read. R5 F-3 supplied a
worked counter-example — `created_at 12:00+12:00` / `expires_at 12:00-11:00` resolving to a
23-hour window — which is now transcribed verbatim into `gate_evidence.py:184–190`. R6 F-1
cited the operator's `+02:00` stamps in `TASK_STATE.md` as the evidence that a naive timestamp
buys two hours. That is a citation to a real artifact establishing a real magnitude.

**Coverage (5).** It covered the classes its charter names — credential exposure, auth bypass,
injection — and correctly recognised that in *this* diff the "auth bypass" surface **is** the
evidence validator. It found bypasses at every layer: the parser (R1–R3), the schema (R4), the
timestamp semantics (R5–R6), the compensating control (R6 F-3, the unbounded `--ttl`), and the
composition of two individually-bounded windows (R7 S-2). R7 S-3 is the standout coverage
move: it checked whether the naive-timestamp class had been closed in the *sibling* module
that gates the actual write, and found it crashed instead of denying.

**Severity (5).** Used BLOCK exactly once — R2, on the finding that the R1 fix was incomplete —
and HOLD otherwise. That is correct calibration: an incomplete fix to an authorization bypass,
shipped under a docstring claiming the class was closed, is categorically worse than the
individual gaps that followed. No inflation (it returned findings, never a blanket BLOCK), no
deflation (it never let an optimistic claim pass as cosmetic). It repeatedly and correctly
classified *documentation* defects as security defects, on the correct reasoning that the
code's own refusal message points the operator at the contract (R7 S-1) — so stale prose
routes around the guard by its own error text.

**Actionability (5).** Every finding names the mechanism and the remedy. R6 F-1 did not merely
say "the message is wrong"; it identified that the message offered *"or no offset at all"* as a
remedy, so an operator refused for `+02:00` would follow the advice and land on the **wider**
window. That is a finding whose fix is fully determined by the finding.

**Substitution (5).** Canonical `.claude/agents/deploy_security_reviewer.md`. GATE 5 N/A.

**Evidence (5).** Reproduction is attested for every finding in the fix commits ("Both confirmed
to launder a BLOCK into a GO"; "confirmed by reproduction"). Its counter-examples are executable
and several are now pinned as tests.

**Environment (3).** No per-agent worktree/branch/HEAD disclosure in the reconstructed record.
No path-drift failure occurred (single branch, known heads throughout), so this is the standard
missing-disclosure-with-no-impact 3, consistent with the convention in the 2026-07-30 and
2026-07-28 scorecards. This is Issue #597 carrying forward, not a new fault.

**The one thing it did not do:** it never challenged the *design*. See focus area (b).

---

### deploy_qa_reviewer — 32 — RELIABLE

The only agent that systematically attacked the tests rather than the code, and it produced the
campaign's most transferable findings.

**Specificity (5).** Every vacuous-test finding names the test and the reason it cannot fail.
R5 F1: the documentation pin was *"a universal quantifier over a possibly-empty match set."*
R5 F3: *"MAX_VALIDITY/CLOCK_SKEW tests derived their inputs from the constants, so a 30-day cap
survived the suite while the contract published 24 hours."* R7 F-1: the expiry test injected a
`now` that `evaluate()` never reads. R8 F-1: the POSIX assertion looped over `as_posix()`
output, *"which cannot contain a backslash on any platform."* Each is a precise statement of
why the assertion is unfalsifiable — not "this test looks weak."

**Coverage (5).** Its charter is regression counts and coverage gaps. It went well beyond that
into mutation reasoning, and the extension was the right one for a diff whose entire product is
a safety validator. R8 F-2 is the deepest single finding in the campaign by any agent: it
mutated a **published claim** — deleting `"reconcile"` from the `if action in ("deploy",
"reconcile")` tuple that `gate_evidence.py:65–67` advertises — and found it killed zero tests.
That is testing the documentation as an executable assertion.

**Severity (4).** HOLD/GAP throughout, correctly. One deduction: by R7 it had found the same
class recurring inside its own fixes twice (R6 F-1 explicitly notes *"F5 recurring inside the
fix for F5"*), and by R8 it was on the eighth vacuous guard. A reviewer seeing its own finding
class recur inside its own remediation three times has grounds to escalate from HOLD to BLOCK
on process, not just on instance. It did not.

**Actionability (5).** Each finding states the replacement property, not just the defect. R7
F-1 did not say "delete this test"; it said repoint it at *"an artifact digest-bound to a
MARKDOWN evidence file still verifies"* — a property that is both observable and the actual
migration hazard.

**Substitution (5).** Canonical. GATE 5 N/A.

**Evidence (5).** Findings are mutation-attested — the standard applied is "delete the branch,
does a test fail," and the answer is reported per finding.

**Environment (3).** No disclosure; no impact. Standard.

---

### deploy_release_manager — 32 — RELIABLE

Consistently found real defects on the **Windows production host** that no reviewer reading the
diff on Linux could have found, and that the implementing agent's local runs structurally could
not surface.

**Specificity (5).** R4 D-1: the provisioning block wrote the key into a directory *its own next
line created*. R4 D-2: three documented commands used backslash line continuations, which
PowerShell does not honour — *"each pasted as two broken commands and exited 2."* R5 M-2: the
encoding guidance warned about UTF-16 when PowerShell 5.1 `Set-Content` writes **ANSI** —
*"it warned of a stop that does not fire while missing the intermittent one that does."*
R6 M-1: `setx` writes the registry but not the running shell. R6 L-1: the create command
hardcoded timestamps, so editing only `<sha>` produced a document valid for four hours on one
day in the past. Each names the exact operator keystroke that fails and the exit code.

**Coverage (5).** Its charter is branch hygiene, rollback command, sync plan, post-deploy
checklist. It correctly read "the operator-facing surface" as its scope for a change whose
entire deliverable is an operator procedure, and it swept that surface repeatedly. R5 M-4 is a
governance-completeness catch: `production_deployment_rule.md`, named by `deploy.md` as the
governance authority, *did not mention gate evidence at all* — closed, not deferred.

**Severity (4).** HOLD-class throughout, appropriately. Deduction: R4 D-2 and R6 M-1 are both
"the documented procedure exits 2 on the production host," which is arguably a blocker for a
change whose sole purpose is to make an operator procedure enforceable. Filed as HOLD, which is
defensible but sits at the low end.

**Actionability (5).** Every finding ships the corrected command. The R6 L-1 fix was
*"executed end to end to confirm the validator accepts its output"* — the remedy was verified,
not proposed.

**Substitution (5).** Canonical. GATE 5 N/A.

**Evidence (4).** Findings cite PowerShell version-specific behaviour precisely (5.1 vs 7+
defaults), which is verifiable, but the record does not show the commands being executed on a
Windows host by the reviewer — the verification is by knowledge, not by run. Deduct 1.

**Environment (4).** The only reviewer that consistently and explicitly reasoned about **which
machine the artifact runs on** as distinct from the machine the diff was read on. That is
environment honesty in the sense the dimension exists to measure, even without a worktree
disclosure line. Score 4, above the campaign's standard 3.

---

### deploy_backend_impact_reviewer — 28 — RELIABLE

Technically deep advisories, undermined by filing them under CLEAR.

**Specificity (5).** R5's advisory set is the most platform-precise reasoning in the campaign
by any agent: *"`MemoryError("Stack overflow")` is what Windows raises instead of
`RecursionError` when the native stack binds, which would have slipped past the catch on the
platform that runs the deploy."* That finding is now `gate_evidence.py:325–336`, with the
CPython `USE_STACKCHECK` mechanism named in the comment. Also named: a naive `now=` raising
TypeError out of a function documented fail-closed (now handled at `:284–286`), `_REF_RX` using
`^...$`, and unguarded `sys.path.insert` stacking duplicate entries.

**Coverage (4).** Charter is route auth guards, router registration, interface breaks, platform
imports. Zero routes changed in this diff, so it correctly redirected to platform-behaviour
review — the right call. Deduction: R8 D1 (the contract documenting the clamp and then
contradicting it eighty lines later) is the *same* contract-consistency class it had already
seen in R7 D-1, and it caught one instance while a second instance of that identical class
survived at `seven-agent-evidence.md:240`. See §6 Finding C.

**Severity (3).** Returned **CLEAR** in R4, R5, R6 and R8 while filing findings that changed
the shipped code each time. A `MemoryError` path open on exactly the platform that runs the
deploy, in a function whose contract is "fail closed throughout," is not an advisory — it is a
fail-open hole on the production platform. CLEAR-with-substantive-advisories is severity
deflation: it hands the coordinator a green light and buries the finding in prose.

**Actionability (4).** Findings are fixable as stated; the CLEAR label weakens the signal that
they must be.

**Substitution (5).** Canonical. GATE 5 N/A.

**Evidence (4).** Mechanism-level and verifiable (the CPython behaviour is checkable), but no
run output — the Windows `MemoryError` path is asserted from knowledge, not demonstrated.

**Environment (3).** Standard.

---

### deploy_persistence_storage_reviewer — 28 — RELIABLE

Same profile as backend-impact: excellent findings, filed at the wrong severity.

**Specificity (5).** R6: *"`jti` is used as a path component in `_consume`, so `"../x"` would
place the single-use replay marker outside the store."* Verified present at
`deploy_authorization.py:165–167` (`os.path.join(store, "consumed", f"{jti}.used")`) with the
resulting `_JTI_RX` guard at `:300`. Also R6: the artifact write was not atomic (now
write-then-`os.replace` at `sign_deploy_authorization.py:299–302`); and the doc-pin walk read
gitignored operator-local files *including `PROJECT_STATE.md`, which carries PII* — a finding
that is simultaneously a correctness bug and a privacy bug, and the only PII finding in the
campaign.

**Coverage (4).** Charter is schema mutations, storage writes, hardcoded production paths. No
schema in this diff; it correctly reinterpreted "storage" as the authorization store and swept
it. R8's born-dead-artifact finding is a genuine storage-lifecycle catch. Deduction: the
`jti` path-traversal is a security finding surfaced by persistence and, on the record available,
**not** surfaced by security — a coverage gap in the pairing rather than in this agent.

**Severity (3).** The sharpest deflation in the campaign. In R8 it returned **CLEAR/PASS**
while reporting that the new clamp *"could write a BORN-DEAD artifact… `expires_at <= now` with
exit 0. The operator could then neither use it nor re-mint."* That is an exit-0 success report
producing an unusable authorization at the canonical lookup path during an incident window,
with no recovery path — a blocker by any reading, filed under a passing verdict. Score 3.

**Actionability (4).** Remedies clear; severity label undercuts urgency.

**Substitution (5).** Canonical. GATE 5 N/A.

**Evidence (4).** Mechanisms named and verifiable in the shipped code; no reproduction output.

**Environment (3).** Standard.

---

### implementing agent (main-loop orchestrator) — 27 — **NEEDS-TUNING**

**Verdict override stated explicitly:** total 27 sits in the ACCEPTABLE band (22–27), but two
dimensions score ≤2 (Severity 2, Environment 2), and the spec makes "weak on ≥2 dimensions OR
systematic gap" an independent NEEDS-TUNING qualifier. Both conditions hold. NEEDS-TUNING.

**A necessary honesty note about the number.** The operator's brief predicted this agent would
be "the campaign's weakest performer, and a scorecard that says otherwise is not worth writing."
On **defect authorship** it unambiguously is: it authored all 13 overclaims and all 8 vacuous
tests — every defect rounds 1–8 found. Its numeric total is nonetheless higher than
`deploy_lead_coordinator` (21) and `deploy_git_diff_reviewer` (23), because five of the seven
dimensions measure *reporting quality*, and this agent's reporting was genuinely outstanding.
**That is an instrument limitation, not a defence of the agent**, and I record it rather than
bending the numbers to match the prediction. The instrument rewards eloquent self-disclosure:
an agent that authors a defect and then writes a superb commit message about it scores 5 on
Specificity and 5 on Evidence for the same event that should cost it. I carry this to the
self-eval as a proposed amendment (`self-eval-2026-08-06.md`, §Instrument).

**Specificity (5).** The twelve commit messages are the best primary record this observer has
received from any campaign. They name the function, the mechanism, the reviewer that found it,
the finding ID, the reproduction, and the mutation count (17, 21, 16, 13, 16 across rounds
4–8). `ed62ed59` states the design argument in full and is the reason focus area (b) is
answerable at all.

**Coverage (3).** It closed every finding raised, in the round it was raised, without deferral —
that is real. But its binding obligation was not only "close the findings." Lesson Q, published
**five days earlier by this same system** (2026-08-01, PR #1062, scorecard
`.claude/memory/scorecards/2026-08-01-pr1062-amendment-register-refresh.md`), requires that a
safety-property claim name the function implementing it. It wrote 13 claims that did not, in a
PR whose own docstring cites Lesson Q by rule number. Coverage of the *standing* requirement
failed 13 times.

**Severity (2).** This is the campaign's defining failure and it is a severity-calibration
failure specifically: the agent consistently rated its own claims as safe to write. Lesson Q
rule 6 states plainly that a claim which *permits* proceeding is the higher-scrutiny class and
"warrants a `reviewer-challenge` second pass before commit." Every one of the 13 was in the
permitting direction. It was tracking the count in its own commit messages — R4 *"the fifth
instance of this exact class on this PR"*, R5 *"Sixth instance of this class on this PR, **and I
wrote it inside the round-4 fix for it**"*, R8 *"the 13th instance… **again inside the text
written to fix the 12th**"* — and the count kept rising. Knowing the rate and not changing the
procedure is a severity mis-calibration, not an oversight. Score 2.

**Actionability (5).** Every fix was landed, reproduced first, and mutation-verified after.
`7dd2712d` states falsifiability was *"checked, not assumed"* and names the two tests that fail
when the use-time re-check is removed. This is the discipline the score reflects.

**Substitution (5).** Canonical main-loop orchestrator; no substitution event. GATE 5 N/A.

**Evidence (5).** Reproduction-before-fix, mutation-after-fix, and — notably — CI treated as a
measurement rather than a verdict: R5 and R7 both report a **node-ID set-difference against
merge base `6e1de8b1`**, establishing that 234 aggregate failures are inherited rather than
introduced. That is the correct way to make an absence claim about regressions, and it is the
same rigour Lesson Q rule 7 demands. R7 F-5 shows it correcting its **own** prior baseline row
that had claimed "identical sets, zero new" when the measurement showed exactly one new failure —
its own Windows path defect. Self-correction by measurement, marked not deleted.

**Environment (2).** The sharp deduction, and it is the Lesson Q rule 7 dimension.
- It ran locally on **Linux** while the sole deploy target is a **Windows** host, and shipped
  platform-divergent defects to CI **twice**: `98e98711` (CRLF from `Path.write_text`) and the
  R6 `str(Path.relative_to())`-yields-backslashes defect. Both were green locally and red on the
  platform that runs the deploy. The disclosure of that structural gap came *after* CI failed,
  not before.
- `e958e625` discloses a suite *"I had not run locally"* — an environment gap admitted only
  once CI surfaced it.
- The R8 finding that `_parse_iso` *"resolved the naive-timestamp hole by ACCEPTING where the
  sibling validator REFUSES (opposite resolutions, mine permitting)"* is an environment-of-
  reasoning failure: it fixed a class in one module and did not check the module next to it that
  gates the actual write.

Score 2: missing disclosure that **masked a failure**, per the dimension definition, twice.

---

### deploy_git_diff_reviewer — 23 — **NEEDS-TUNING**

**Verdict override stated explicitly:** total 23 sits in ACCEPTABLE, but Severity (2) and
Evidence (2) are both weak, triggering the "weak on ≥2 dimensions" qualifier. NEEDS-TUNING.

This agent produced both the campaign's best environment-aware finding and its only **false
blocker** — and the false blocker is precisely the failure mode the campaign was about.

**The false-absence claim, verified as false at the reviewed SHA.** R5 F1 held that
`.claude/commands/deploy.md:5` — *"Pinned by `service/tests/test_deploy_authority.py`"* —
asserts a pin that does not exist. I resolved this at `9be59700` by the mechanism, not the
string:

- `service/tests/test_deploy_authority.py:37–43` — `PRESCRIPTIVE_DIRS` includes
  `REPO / ".claude" / "commands"` (line 38).
- `service/tests/test_deploy_authority.py:53–59` — `_prescriptive_markdown()` iterates
  `PRESCRIPTIVE_DIRS` and `d.rglob("*.md")` (line 57), so `deploy.md` is in the scanned set.
- `service/tests/test_deploy_authority.py:126–142` —
  `test_no_executable_deploy_logic_in_prescriptive_markdown` scans every file from
  `_prescriptive_markdown()` for `EXEC_RX` inside fenced blocks and asserts no offenders.

`deploy.md:5` claims the file *"must never contain executable deployment commands"* and that
this is pinned. It is pinned, by a directory glob. **The reviewer grepped for the literal
filename and reported absence.** The implementing agent's rejection at `12376dc6` is correct
and correctly evidenced, and I independently confirm it here.

Under Lesson Q rule 7 an absence claim is *"the highest-risk form, because a stale tree produces
it silently and it reads as decisive."* This reviewer produced one by a stale *method* rather
than a stale tree, in a campaign about uncited claims, while nominally applying that lesson.

**Specificity (3).** Its CLEAR verdicts and file classification were correct throughout (I
confirm the classification independently: zero files under `service/app`, `.claude/deploy`, or
any root engine module). But the R5 finding was specific about the wrong thing — it cited a
grep result rather than the pin mechanism.

**Coverage (4).** Charter scope — file classification, forbidden paths — fully executed and
correct in every round.

**Severity (2).** Filed a HOLD on a non-defect. A false blocker on a nine-round campaign costs
a round and, worse, trains the reader to discount this reviewer's next finding. Inflation in
the decisive direction.

**Actionability (3).** The finding was actionable in form (it named a file:line and a claim) —
which is exactly why it was expensive: it was refutable only by someone willing to resolve the
mechanism rather than repeat the grep.

**Substitution (5).** Canonical. GATE 5 N/A.

**Evidence (2).** The evidence offered did not support the claim made. A grep for a filename
cannot establish that no pin exists; establishing that requires enumerating what the test file
*scans*. This is the dimension the finding fails on most cleanly.

**Environment (4).** Offsetting credit, and it is substantial. In R6 this agent found that
`TASK_STATE.md` claimed `Assert-ProductionMatchesRecordedSha` was in an unmerged PR and *"does
not exist in the deploy authority"*, and **measured it at the reviewed SHA** — present, and
inherited from main — then had it *"withdrawn by marking, not deleting."* That is Lesson Q
rules 3, 5 and 7 executed correctly, against a stale claim in a state file, by the same agent
that got rule 7 wrong one round earlier. Score 4, and it is earned.

---

### deploy_lead_coordinator — 21 — **NEEDS-TUNING**

The final arbiter, and the agent whose miss is the most consequential in the campaign.

**The round-9 GO was issued over a live, verifiable instance of the campaign's signature
defect class.** Verified at `git show 9be59700`, both files in the same reviewed diff:

| Source | Text |
|---|---|
| `.claude/hooks/sign_deploy_authorization.py:248–252` | *"it said the chain is bounded **'at 24h from the moment the gate round concluded'**. **It is not.** It is bounded at 24h from the `created_at` the evidence ASSERTS… Round Monday, `created_at` Tuesday, deploy Wednesday: ~47h after the real verdict, with every check passing."* |
| `.claude/contracts/seven-agent-evidence.md:240` | *"The whole chain is therefore **bounded at 24 hours from the moment the round concluded**."* |

The contract is *self*-contradictory too: line 240 asserts the property that lines 141–144 of
the same file explicitly refute (*"`created_at` is equally operator-asserted… A round concluded
on Monday can be written with Tuesday's `created_at` and deployed on Wednesday with every check
passing"*). And the contract — not the code comment — is the **schema authority** the code's own
refusal messages point operators to (`sign_deploy_authorization.py:196–198`,
`gate_evidence.py` header). This is instance **#14**, and it shipped.

That the round-8 fix commit enumerated this exact false half, in this exact wording, and the
round-9 gate then passed the surviving copy of it, is a coordinator-level failure: six
specialists returned CLEAR/PASS and the arbiter did not ask the one question nine rounds of
history had made mandatory.

**Specificity (3).** Round-level verdicts are recorded as aggregate counts (*"3 CLEAR, 3 HOLD"*)
with the specialist findings carried through by name. Adequate but not itself specific; the
coordinator's own reasoning is not visible in the record.

**Coverage (2).** By round 8 the coordinator had presided over **13 instances of one defect
class**, four of them written inside the fix for the previous one. Nothing in the record shows
it converting that rate into an exit criterion — e.g. "before GO, every safety-property sentence
in the contract must name its implementing function." Had it done so, #14 is caught by
construction. Presiding over a recurrence rate and not making the recurrence a gate condition is
the coverage failure.

**Severity (2).** GO at the decisive moment over a live instance. Deflation where it costs most.

**Actionability (4).** A GO/HOLD decision is inherently actionable, and its per-round
consolidation demonstrably drove the fix commits.

**Substitution (5).** Canonical `.claude/agents/deploy_lead_coordinator.md`. GATE 5 N/A.

**Evidence (2).** No coordinator-level verification evidence in the record — the verdict is a
roll-up of six inputs with no independent check. For the agent holding *final* authority, and
whose charter (`deploy_lead_coordinator.md`) makes it the "final arbiter," a roll-up with no
independent probe is thin. The round-9 outcome demonstrates the cost.

**Environment (3).** Standard; no disclosure, and no path-drift failure occurred.

**Mitigating, and stated:** rounds 1–8 the coordinator correctly routed six specialists,
honoured the security reviewer's un-overridable HOLDs without dilution, and never issued a GO
that a later round overturned on a *code* defect. The failure is specific and it is at the end.

---

## 3. Focus areas — scored explicitly

### (a) Repeated overclaiming of safety properties — **SYSTEMATIC FAILURE**

**Did Lesson Q change behaviour? No. It changed vocabulary.**

That is the plain answer the operator asked for, and the evidence is unusually clean.
Lesson Q was published 2026-08-01, five days before this merge, by this same system, from the
`b5853935` register refresh whose scorecard is
`.claude/memory/scorecards/2026-08-01-pr1062-amendment-register-refresh.md`. Rules 1, 5 and 6
address exactly this defect.

Across this campaign the implementing agent:
- **cited Lesson Q by rule number** in `gate_evidence.py`'s docstring (`:72–73` — *"a Lesson Q
  rule 1+6 defect"*), in `sign_deploy_authorization.py:208–209`, and in commit messages at
  `7dd2712d`, `d99134df`, `618e940d`;
- **applied rule 5 correctly and consistently** — WITHDRAWN markers rather than deletions, at
  `seven-agent-evidence.md:183` and three places in `TASK_STATE.md`;
- **and wrote the same defect 13 times anyway**, four of them inside the text written to fix the
  previous instance (R5: *"Sixth instance… and I wrote it inside the round-4 fix for it"*;
  R8: *"the 13th instance… again inside the text written to fix the 12th"*).

The lesson was fully internalised as *narration* and not at all as *procedure*. The agent could
name the defect class, count its instances, and cite the governing rule — while producing the
next instance in the same paragraph. Rule 6's own prescribed remedy (*"warrants a
`reviewer-challenge` second pass before commit"*) was, on the record available, never invoked.
That is the actionable gap: rule 6 names a procedure and the procedure was not run.

**Severity of the class, restated:** every one of the 13 was in the **permitting** direction —
each described a stop the operator did not have. Lesson Q rule 6 defines that as the severe
class. A pessimistic error costs a wasted stop; these cost a stop the reader believed existed.

**Instance #14 shipped** (contract line 240, §2 lead-coordinator above). The class is not
closed. Two contract-prose pins were built to close it and both are scoped narrower than the
class — see §6 Finding C.

**Score for this focus area: 1/5** for the implementing agent's claim discipline; **5/5** for
the security reviewer's detection of it (it caught instances 3–13 and reproduced each);
**2/5** for the gate as a whole, which let #14 through on a clean round.

### (b) Parser design churn — **CORRECTED: 3 rounds, not 7; and no agent was chartered to call it**

**At which round was the evidence sufficient to abandon the design?** Round 2. The R1 fix closed
two demonstrated vectors and asserted the class was closed; R2 found two more by the *same*
mechanism (last-wins on a different field; a near-miss name silently discarded). At that point
the pattern — "patch the demonstrated instance, the next round finds the next instance" — was
established with two independent confirmations, and the generalisation was available. The
operator ruled after round 3, i.e. **one round later than the evidence supported**. Measured
against the brief's premise of seven rounds, this is a substantially better outcome than
assumed: the design was abandoned fast.

**Who could have called it and did not?**
- **The implementing agent could, and eventually did — but only after being told.** Its own
  `ed62ed59` message contains the complete argument (*"That is the design, not bad luck… No
  finite list of patches closes that class"*), and `d99134df` (round 2) already contains the
  diagnosis in miniature: *"Fixing demonstrated vectors instead of the class is what made it
  wrong."* It wrote the correct generalisation at round 2 and then patched instances anyway at
  round 3. It had the argument and did not act on it.
- **The security reviewer could have, and did not.** It found four of the six vectors and had
  the strongest possible standing to say "this is a class, not a list." Its findings were always
  instance-shaped. This is the single most valuable behaviour change available to that agent.
- **The lead coordinator could have, and did not.** Escalating "three rounds, six vectors, same
  mechanism" from a finding into a design question is precisely an arbiter's job.

**Was any reviewer chartered to challenge the design rather than the diff? No — verified.**
I read all seven `.claude/agents/deploy_*.md` frontmatter descriptions. Every one is
artifact-scoped: *"Inspects changed Python files…"* (backend-impact), *"Inspects git diff
between local HEAD and origin/main…"* (git-diff), *"Inspects changed files for database schema
mutations…"* (persistence), *"Inspects every changed file for credential exposure…"* (security),
*"Verifies PZ regression… and carrier test suite results"* (QA), *"Verifies branch hygiene…"*
(release-manager). The lead coordinator *"**Collects findings** from the other 6… **resolves
conflicts**, and issues the written deployment decision."* None is chartered to ask whether the
change should exist in its current shape. **The gate is structurally incapable of returning
"this design is wrong" — it can only return "this diff is wrong."**

**The operator made the call, and no agent did.** That is the correct reading and it is a
charter finding, not a per-agent failure. `reviewer-challenge` exists in this repository and is
chartered for exactly this, and it was not in the seven-agent deploy gate roster. See §5
disposition D-4.

**Score for this focus area: 3/5** — fast abandonment (3 rounds), correct final design, but
zero agent-originated design challenge, and a structural charter gap that guarantees the same
outcome next time.

### (c) Missed adjacent test coverage — **8 vacuous tests, 2 inside the fix for that class**

Every named instance verified against the record and, where it survives, against the shipped
file:

| # | Round | Vacuous test | Why it could not fail |
|---|---|---|---|
| 1 | R1 | (self-caught) helper derived a BLOCK disposition | blocking branch fired before the branch under test (`7dd2712d`) |
| 2 | R2 | `test_digest_covers_exactly_the_bytes_that_were_parsed` | hashed an unmodified file twice — *"could only fail if SHA-256 were broken"* |
| 3 | R4→R5 F1 | the documentation pin | *"universal quantifier over a possibly-empty match set"* — **no `assert matched` precondition**, so a failed regex silently passed |
| 4 | R5 F3 | `MAX_VALIDITY`/`CLOCK_SKEW` tests | inputs derived from the constants — *"a 30-day cap survived the suite while the contract published 24 hours"* |
| 5 | R6 F-2 | naive-`now` test | asserted only `ok=True`, so an implementation **discarding** the caller's value passed |
| 6 | R6 F-3 | the R5 pin's own precondition | guarded the discovery set while two later filters could still empty it |
| 7 | R7 F-1 | *"expiry is not re-checked at use time"* | injected a `now` that **`evaluate()` never reads** — it reads the wall clock, when the evidence was still valid |
| 8 | R8 F-1 | the POSIX-path guard | looped over `as_posix()` output, *"which cannot contain a backslash on any platform"* — asserting a post-condition of the call, not the behaviour |

**Instances 6 and 8 are inside tests written to close that very class** (R6 F-3 is the
precondition added by R5 F1; R8 F-1 is the fix for the R6 Windows path defect). The class
recurred inside its own remediation twice, exactly as the overclaim class did — the same
underlying failure in a different medium: **the agent verifies that its fix is present, not that
its fix can fail.**

**Weak substring pins — assessed, and the campaign fixed them.** The brief names `"24 h" in
contract` matching inside `"1024 h"`, and a bare number satisfied by a worked example. Both are
real and both are now closed at `test_gate_evidence.py:353–359`, which says so in the comment
(*"a bare `"24 h" in contract` also matches inside `"1024 h"`"*) and replaces the substring with
anchored patterns `r"\*\*at most 24 h\*\*"` and `r"\b5 min(?:utes)? skew\b|\(5 min skew allowed\)"`.
This is a genuine quality improvement and the QA reviewer earned it.

**The residual, which I checked rather than assumed:** anchoring the *magnitude* pins does not
close the *claim* class. `test_the_time_constants_match_the_figures_the_contract_publishes`
(`:338`) pins only the two numbers; `test_the_contract_does_not_document_a_timestamp_form_the_code_refuses`
(`:362`) executes exactly four **timestamp forms** (`+00:00`, `Z`, `+02:00`, `naive`) against the
validator. Neither can observe a window-**bounding** claim. That is why #14 survives at contract
line 240 with both pins green. See §6 Finding C.

**Score for this focus area: 5/5** for QA detection (it found all 8 and named the falsifiability
failure each time); **2/5** for the implementing agent's test authorship (8 vacuous tests, 2
recursive); **3/5** for the resulting suite, which is now strong on mutation coverage and still
has a scope-limited prose pin.

### (d) Where reviewers caught what local verification missed — and reviewer *precision*

**Caught by review or CI, not by the implementing agent's local run:**

1. **The Windows POSIX-path defect (caught by CI, not by any agent, not locally).** The doc pin
   compared `str(Path.relative_to(...))` against POSIX literals; `str()` yields **backslashes**
   on Windows. Green on Linux CI-equivalent local runs, red on the Windows runner — *"the only
   new failure vs merge base"* (`89c902aa`). This is the cleanest demonstration in the campaign
   that the implementing agent's local environment cannot verify the deploy target. Fixed with
   `as_posix()` at `test_deploy_authority.py:390` — and then the **fix's own test was vacuous**
   (R8 F-1, row 8 above), so the same defect class needed two rounds.
2. **The round-7 contract/code contradiction — five of six reviewers, independently.** Security
   S-1, release HIGH-1, git-diff H-1, backend D-1, persistence M-1 all found that round 6 had
   changed the validator to refuse naive timestamps while the contract still said *"A timestamp
   with no offset is read as UTC."* Five independent confirmations is the campaign's strongest
   signal, and its diagnosis is the sharpest sentence any reviewer produced: *"the guard was
   routed around by its own error text."* Local verification could not catch this — the code was
   correct and the tests passed; only a reader holding both documents sees it.
3. **The `--ttl` ceiling gap (security R6 F-3).** `--ttl` was unbounded while the contract called
   it *"shorter"* and leaned the whole time-bound property on it: `--ttl 43200` minted a 30-day
   authorization off evidence capped at 24 hours. *"The identical 'advice with no enforcement'
   defect this PR fixed for evidence, sitting in the compensating control."* Now capped at
   `sign_deploy_authorization.py:150–158`. No test could have found this — every test passed;
   the defect was that a safety word had nothing behind it.
4. **The composed-windows defect (security R7 S-2).** Capping `--ttl` was insufficient alone:
   evidence valid to T+24h, minted at T+23h59m with `--ttl 1440`, deploys at T+47h58m —
   *"invisible to `evaluate()`, which re-hashes the evidence without re-validating it."* The
   implementing agent's own note is the finding's weight: *"Every step was pinned by a test I had
   written."* A complete, green, individually-correct test suite could not see the composition.
   Now clamped at `sign_deploy_authorization.py:260–264`.
5. **The born-dead artifact (persistence R8).** `now` is captured after the key load and
   `makedirs`, so evidence valid at validation time can expire in that gap and the clamp writes
   `expires_at <= now` with **exit 0** — an authorization the operator can neither use nor
   re-mint (the evidence is expired too). This is a lifecycle race no unit test targets, found by
   reading the ordering. Now refused at `sign_deploy_authorization.py:272–276`.
6. **The `jti` path-traversal (persistence R6).** `jti` becomes a path component in `_consume`
   (`deploy_authorization.py:165–167`), so `"../x"` places the replay marker outside the store,
   defeating single-use. Guarded at `:300` by `_JTI_RX`.
7. **The `MemoryError("Stack overflow")` Windows path (backend R5).** Catching only
   `RecursionError` left the hole open *on exactly the platform that runs the deploy*.

**Reviewer precision — the inverse, and it must be scored.** Recall without precision is not
review quality; it is noise with a good hit rate.

- **One reviewer finding was rejected with evidence, and the rejection was correct.** git-diff
  R5 F1's claim that `deploy.md:5`'s pin does not exist is **false**, verified independently in
  §2 above at `test_deploy_authority.py:38 / :57 / :126`. The reviewer grepped for a literal
  filename; the pin is a directory glob. Under Lesson Q rule 7 this is a **false absence
  claim — the highest-risk form** — produced by a reviewer nominally applying that lesson. The
  implementing agent rejected it with the correct mechanism cited (`12376dc6`), which is itself
  a quality data point: it did not capitulate to a reviewer to close a round.
- **Rejection discipline overall was sound.** This is the only rejected finding in nine rounds;
  every other finding across ~90+ items was reproduced and closed. A 1-in-90 false-positive rate
  is good precision in absolute terms — but the one false positive was in the highest-risk
  category and cost a round on a nine-round campaign.
- **Round-7's five-of-six convergence was genuine, not herding.** Each of the five framed the
  same defect from its own charter angle (security: guard routed around by error text; release:
  operator-facing remedy; git-diff/backend/persistence: document consistency), which is
  independent confirmation rather than echo.

**Score for this focus area: 5/5** for reviewer recall (seven distinct defect classes caught
that local verification structurally could not); **3/5** for precision (one false absence claim,
in the highest-risk form, by the reviewer applying the lesson about it).

---

## 4. Finding-rate by round — did the campaign converge?

Counts are distinct findings named in each round's fix commit; "HOLD" counts are the
non-passing verdicts each commit reports verbatim.

| Round | Commit | Verdicts | Distinct findings | Subject |
|---|---|---|---|---|
| R1 | `eeb486aa` | BLOCK-class (S-1 found by *"3 of 4 reviewers"*) | 3 | Markdown parser |
| R2 | `d99134df` | Security **BLOCK**, QA HOLD | ~7 | Markdown parser |
| R3 | `ed62ed59` | (operator ruling) | ~3 | **Design abandoned → strict JSON** |
| R4 | `618e940d` | 3 CLEAR / 3 HOLD | ~12 | strict JSON |
| R5 | `12376dc6` | 2 CLEAR / 4 HOLD (1 rejected) | ~20 | strict JSON |
| R6 | `89c902aa` | 3 CLEAR / 3 HOLD | ~21 | strict JSON |
| R7 | `4674f527` | 1 CLEAR / **5 HOLD** | ~13 | strict JSON |
| R8 | `9be59700` | 3 CLEAR-PASS / 3 HOLD | ~17 | strict JSON |
| R9 | — | **6 CLEAR/PASS + lead GO** | 0 reported | strict JSON |

**Did it converge? Not monotonically, and the convergence signal is weaker than the round-9
result suggests.**

- Finding-rate **rose** from R4 (~12) through R6 (~21) — the strict-JSON rewrite *increased* the
  defect discovery rate for three rounds. That is expected and healthy: a stricter artifact with
  more surface area and more published claims gives reviewers more to falsify.
- R7's CLEAR count fell to **1 of 6** — the campaign's worst round by verdict, and the reason is
  informative: five reviewers found the *same* defect. Distinct-defect count (~13) fell while
  HOLD count rose. **HOLD count is a misleading convergence metric here**; distinct findings is
  the right one, and by that measure R7 was an improvement on R6.
- R8 (~17) shows no clear downward trend from R7 (~13). Two consecutive rounds without decline,
  followed by a zero-finding round, is a thin basis for declaring convergence.
- **R9's zero is contradicted by measurement.** Instance #14 was present and verifiable at the
  reviewed head (`seven-agent-evidence.md:240`, §2 above). The true R9 finding count is **≥1**.
  The campaign did not converge; it **stopped**.

**The honest summary:** eight rounds of genuine, high-yield review followed by one clean round
that was not clean. The convergence claim rests entirely on the round that is measurably wrong.

---

## 5. Weak-verdict warnings and GATE-4 dispositions

Per CLAUDE.md RULE 6, every NEEDS-TUNING or UNRELIABLE verdict is a GATE-4 salvage finding and
carries exactly one disposition: SCHEDULED, ISSUE, or REJECTED. *"Recommendation noted"* is not
a disposition and appears nowhere below.

### D-1 — implementing agent (main-loop orchestrator): NEEDS-TUNING → **ISSUE**

**Failed dimensions:** Severity (2), Environment (2), Coverage (3).

**Supporting excerpts** (verbatim, from the fix commits):
> *"Sixth instance of this class on this PR, and I wrote it inside the round-4 fix for it."* — `12376dc6`
> *"the 13th instance of the optimistic-claim defect, again inside the text written to fix the 12th."* — `9be59700`
> *"CI caught 4 branch-only failures in test_deploy_reconcile_signing.py, a suite I had not run locally."* — `e958e625`

**Disposition: ISSUE**, tagged `agent-tuning`. Two concrete, testable asks:
1. **Make Lesson Q rule 6's prescribed procedure mandatory rather than advisory.** Rule 6 already
   says a permitting safety claim *"warrants a `reviewer-challenge` second pass before commit."*
   On the record available it was never run in nine rounds. Ask: before committing any text
   asserting a gate/guard/stop, dispatch `reviewer-challenge` scoped to that text alone.
2. **Require a claim-to-function citation table in the commit body** for any commit touching a
   safety-property document. Every sentence asserting a stop names the implementing function, or
   is rewritten as an assumption. This is Lesson Q rules 1+2 made procedural instead of
   aspirational — and it is the mechanism that catches #14.

**Re-dispatch against the same task? No.** The work merged and is correct. The tuning target is
the procedure, not this campaign's output.

### D-2 — deploy_lead_coordinator: NEEDS-TUNING → **ISSUE**

**Failed dimensions:** Coverage (2), Severity (2), Evidence (2).

**Supporting excerpt** — round 9 GO issued while, at the reviewed head `9be59700`:
> `sign_deploy_authorization.py:248` — *"it said the chain is bounded 'at 24h from the moment the gate round concluded'. **It is not.**"*
> `seven-agent-evidence.md:240` — *"The whole chain is therefore **bounded at 24 hours from the moment the round concluded**."*

**Disposition: ISSUE**, tagged `agent-tuning`. Ask: add a **recurrence-aware exit criterion** to
`.claude/agents/deploy_lead_coordinator.md`. When a defect class has recurred across ≥3 rounds,
the coordinator may not issue GO on specialist CLEARs alone; it must name the class and state
the check that establishes its absence at the reviewed SHA. Concretely, for this campaign that
check is: *every safety-property sentence in the changed contract names its implementing
function.* Applied at round 9, it catches #14.

**Re-dispatch against the same task? Not for #1094 — the PR is merged and this is a closure
task.** But #14 is live in `main` and needs a follow-up fix (see §6 Finding A, disposition D-5).

### D-3 — deploy_git_diff_reviewer: NEEDS-TUNING → **ISSUE**

**Failed dimensions:** Severity (2), Evidence (2), Specificity (3).

**Supporting excerpt** — R5 F1, rejected with evidence at `12376dc6`:
> *"git-diff F1 claimed `.claude/commands/deploy.md:5` ('Pinned by test_deploy_authority.py') asserts a pin that does not exist. It does exist… The reviewer grepped for the literal filename; the pin is a directory glob. A false absence claim — the highest-risk form under Lesson Q rule 7."*

Independently confirmed false in this scorecard at `test_deploy_authority.py:38 / :57 / :126`.

**Disposition: ISSUE**, tagged `agent-tuning`. Ask: add an **absence-claim protocol** to
`.claude/agents/deploy_git_diff_reviewer.md` (and, by extension, to every `deploy_*` charter,
since Lesson Q rule 7 binds all seven): *before asserting that a symbol, pin, guard, or flag does
not exist, resolve the mechanism that would implement it — enumerate the sets, globs, and
imports the candidate implementation actually scans — and state that enumeration as the
evidence. A grep miss is not an absence.*

**Re-dispatch against the same task? No.** Its classification work was correct in every round
and its R6 at-this-SHA measurement was exemplary; the fault is one specific verification method.

### D-4 — Charter gap: the seven-agent gate cannot challenge a design → **SCHEDULED**

Not a per-agent verdict; a structural finding from focus area (b), and it is the finding most
likely to prevent the next multi-round campaign.

**Evidence:** all seven `.claude/agents/deploy_*.md` frontmatter descriptions are artifact-scoped
(*"Inspects changed Python files…"*, *"Inspects git diff…"*, *"Verifies branch hygiene…"*); the
coordinator *"collects findings… resolves conflicts."* None asks whether the change should exist
in its current shape. Consequence, measured: three rounds of instance-patching where the
implementing agent had already written the correct generalisation at round 2, and the operator —
not any agent — made the call.

**Disposition: SCHEDULED** for the next governance session. Two options for the operator to rule
between:
- **(a)** Add `reviewer-challenge` (already canonical in this repository, already chartered to
  challenge premises) as a **non-blocking eighth voice** on deploy gates that reach round 3+.
- **(b)** Extend `deploy_lead_coordinator.md` with an explicit design-escalation duty: *"when the
  same defect class recurs across ≥2 rounds, state the generalisation and ask whether the design,
  not the diff, is the defect."*

Option (b) is lighter and does not change the seven-agent gate's composition, so it does not
disturb the *"7 required agents"* rule in `CLAUDE.md`. **Recommended: (b).** Note Lesson B —
an agent-file change is not reliably invocable until the next session.

### D-5 — Instance #14 is live in `main` → **SCHEDULED**

See §6 Finding A. This is a code/documentation finding, not an agent verdict, but it needs a
disposition and it should not wait on the agent-tuning items.

---

## 6. CODE-QUALITY FINDINGS (separate from agent quality)

These are defects in the shipped artifact at `9be59700`. They are **not** scored against any
agent and do not affect any verdict above. Findings A and C are live at the merged head; B is
an assessment of what shipped correctly.

### Finding A — **LIVE: instance #14 of the overclaim class, in the schema authority**

**Severity: MEDIUM.** Not a fail-open in code — the *code* is correct and bounds nothing it
claims not to bound. The defect is that the **authority document** tells the operator a stronger
property than the system provides, and the code's own refusal messages route operators to that
document (`sign_deploy_authorization.py:196–198`).

**Location:** `.claude/contracts/seven-agent-evidence.md:240` (verified via
`git show 9be59700:.claude/contracts/seven-agent-evidence.md`).

> *"The whole chain is therefore bounded at 24 hours from the moment the round concluded."*

**Refuted by, in the same merged diff:**
- `sign_deploy_authorization.py:248–254` — *"It is not. It is bounded at 24h from the `created_at`
  the evidence ASSERTS, and nothing ties that field to when the round actually ran."*
- `seven-agent-evidence.md:141–144` — the **same file**, 97 lines earlier: *"A round concluded on
  Monday can be written with Tuesday's `created_at` and deployed on Wednesday with every check
  passing."*

**Concrete exposure:** an operator reading line 240 believes a deploy cannot occur more than 24h
after the gate verdict. The actual bound is 24h after an operator-asserted, unverified
`created_at`. The Monday/Tuesday/Wednesday sequence yields ~47h with every check green — stated
in the code, denied by the contract.

**Disposition (D-5): SCHEDULED** — one-line documentation fix on `main`. Suggested replacement,
consistent with what the code guarantees: *"The clamp therefore guarantees that an authorization
never outlives the evidence that justified it, so the two windows cannot compose. It does not
bound the chain from the moment the round concluded — `created_at` is operator-asserted and
unverifiable (see 'the transcription step is the residual trust boundary' above)."*

### Finding B — what shipped correctly (stated, because a scorecard that only lists defects misrepresents the campaign)

Each claim below names the implementing mechanism, per Lesson Q rules 1–2 binding this document:

- All six Markdown laundering vectors are closed **by construction**, not by patch: duplicate
  keys refused at `gate_evidence.py:136–148` (`_no_duplicate_keys` via `object_pairs_hook`);
  exact-match agent names at `:241–242`; exact field sets at `:341–349` (top) and `:227–233`
  (per-agent); single passing token `_GO = "GO"` at `:112`, compared at `:245` and `:421`.
- SHA binding: `:363–370`, refusing evidence whose `target_sha` ≠ the SHA being signed.
- TOCTOU closed: one read at `:304–311`, digest computed from exactly the bytes parsed.
- Use-time re-check: `deploy_authorization.py:280–281`, scoped `if action in ("deploy",
  "reconcile")` — and the rollback **exemption is documented as an exemption** at
  `gate_evidence.py:69–73`, which is the correction of instance #3 and is correct.
- Window composition closed: `sign_deploy_authorization.py:260–264` (clamp) plus `:150–158`
  (`--ttl` ceiling) plus `:272–276` (born-dead refusal).
- Residual trust boundary named honestly at `seven-agent-evidence.md:137–146` and
  `gate_evidence.py:37–44` — including the `risks`-field escape hatch, disclosed rather than
  papered over.
- 197 tests, mutation-verified (17/21/16/13/16 single-line mutations across rounds 4–8, each
  attested to fail the suite).

**This is a materially safer authorization path than what existed at `6e1de8b1`, and the campaign
should be recorded as a success on artifact quality.**

### Finding C — the contract-prose pins are scoped narrower than the class they were built to close

**Severity: LOW-MEDIUM.** This is *why* Finding A survived nine rounds with a green suite.

Two pins exist to prevent contract/code divergence, and I checked what each actually observes:
- `test_gate_evidence.py:338` `test_the_time_constants_match_the_figures_the_contract_publishes`
  — pins two **magnitudes** (24h, 5min) with anchored regexes at `:356` and `:358`. Cannot
  observe a claim about *what the window is measured from*.
- `test_gate_evidence.py:362` `test_the_contract_does_not_document_a_timestamp_form_the_code_refuses`
  — executes exactly four **timestamp forms** (`+00:00`, `Z`, `+02:00`, `naive`) at `:379–397`.
  Cannot observe a window-**bounding** claim.

Both are green at `9be59700` with #14 present. The pins close *timestamp-form* divergence and
*magnitude* divergence; the surviving class is *provenance* divergence — "measured from what."

**Disposition: folded into D-5.** When Finding A is fixed, add a pin covering the class rather
than the instance. The generalisable form, and the one that would have caught #14: *every
sentence in `seven-agent-evidence.md` asserting a bound or a stop must be traceable to a named
function in `gate_evidence.py` or `sign_deploy_authorization.py`.* That is Lesson Q rules 1+2 as
an executable test, and it is the single highest-value artifact this campaign could still
produce.

---

## 7. Repeated failure hints — cross-campaign trend

Read: the five most recent campaign scorecards in `.claude/memory/scorecards/`
(`2026-07-28-advisory-service-id-draft-fallback.md`,
`2026-07-30-c7903686-wfirma-breaker-deploy-closure.md`,
`2026-07-30-pr1041-pr1040-deploy-gate.md`,
`2026-07-31-gate4-lean-execution-disposition.md`,
`2026-08-01-pr1062-amendment-register-refresh.md`).

### REPEATED-WEAK: none of the eight agents meets the ≥2-prior-cards threshold

Checked per agent against the window. The `deploy_*` agents appear in exactly two prior cards:

| Agent | 2026-07-11 | 2026-07-30 (#1041/#1040) | 2026-07-30 (closure) | **2026-08-06** |
|---|---|---|---|---|
| deploy_git_diff_reviewer | — | 28 EXEMPLARY | 20 NEEDS-TUNING (evidence-limited) | **23 NEEDS-TUNING** |
| deploy_lead_coordinator | — | 33 EXEMPLARY | 27 ACCEPTABLE | **21 NEEDS-TUNING** |
| deploy_security_reviewer | 27 ACCEPTABLE | 27 ACCEPTABLE | 20 (grouped, evidence-limited) | **33 RELIABLE** |
| deploy_qa_reviewer | — | 33 EXEMPLARY | 20 (grouped, evidence-limited) | **32 RELIABLE** |
| deploy_release_manager | 26 ACCEPTABLE | 28 EXEMPLARY | 20 (grouped, evidence-limited) | **32 RELIABLE** |
| deploy_persistence_storage_reviewer | — | 31 EXEMPLARY | 20 (grouped, evidence-limited) | **28 RELIABLE** |
| deploy_backend_impact_reviewer | — | 30 EXEMPLARY | 20 (grouped, evidence-limited) | **28 RELIABLE** |

The 2026-07-30 closure card's ≤20 scores are explicitly marked *"(evidence-limited)"* by that
card itself — *"a documentation-coverage gap, NOT a confirmed performance failure"* — and are
grouped across six agents rather than individually measured. **I do not count them toward
REPEATED-WEAK**, because doing so would build a trend on scores their own author disclaimed. No
`REPEATED-WEAK` flag fires this run.

### Two trends worth naming (not yet REPEATED-WEAK — first or second observation)

**T-1 — `deploy_lead_coordinator` is on a three-card decline: 33 → 27 → 21.** All three are
independent measurements with real evidence (unlike the grouped rows above). The failure mode is
consistent across the last two: at 2026-07-30 it scored Evidence 5 / Environment 4 and was the
campaign's strongest; here it scores Evidence 2 with **no independent verification behind a GO**.
If the next deploy-gate card scores it ≤21 again, that is `REPEATED-WEAK` and D-2's ISSUE should
escalate to a charter amendment rather than a tuning note. **Flagging now so the next observer
run has the baseline.**

**T-2 — Environment disclosure has scored 3/5 across every deploy agent in every card since
2026-07-11.** That is Issue #597 carrying forward for four consecutive campaigns. Two agents
broke the pattern this run and both did so by *reasoning about the target environment* rather than
by disclosing a worktree path — `deploy_release_manager` (4, Windows-host reasoning) and
`deploy_git_diff_reviewer` (4, at-this-SHA measurement of a `TASK_STATE.md` claim). **That is the
behaviour the dimension should reward**, and it suggests the standing ask should be reframed:
not "disclose your worktree" but "name the revision and platform your finding is true at."
Recommend folding this into D-3's absence-claim protocol.

### The Lesson Q trend — the finding this section exists for

`.claude/memory/scorecards/2026-08-01-pr1062-amendment-register-refresh.md` recorded the
originating instance five days ago and its Section 2 Finding A recommended the lesson.
This campaign is the **first measurement of whether that lesson took**, and the answer is
recorded in §3(a): **it did not change behaviour, and produced 13 further instances plus one
that shipped.** That is a strictly worse outcome than the single instance that motivated the
lesson. A lesson that is cited by rule number in the code it is being violated in is not
functioning as a control — it is functioning as vocabulary. **D-1 and D-2 are the two
dispositions that convert it into a procedure**, and they are the highest-value items on this
scorecard.

---

## 8. RULE 5 self-evaluation

**Triggered** — the most recent self-eval is `.claude/memory/scorecards/self-eval-2026-07-28.md`,
**nine calendar days** old, past the seven-day cadence.

Produced as a separate file: `.claude/memory/scorecards/self-eval-2026-08-06.md`.

**Result: SELF-DEGRADATION DETECTED** (2 dimensions declined). Summary and the instrument
amendment it proposes are in that file; per the forbidden-surfaces rule, this agent does not
downgrade its own degradation flag — the operator decides.

---

## 9. Summary

| | |
|---|---|
| Agents scored | 8 |
| RELIABLE | deploy_security_reviewer (33), deploy_qa_reviewer (32), deploy_release_manager (32), deploy_backend_impact_reviewer (28), deploy_persistence_storage_reviewer (28) |
| NEEDS-TUNING | implementing agent (27), deploy_git_diff_reviewer (23), deploy_lead_coordinator (21) |
| UNRELIABLE | none |
| GATE-4 dispositions | D-1 ISSUE, D-2 ISSUE, D-3 ISSUE, D-4 SCHEDULED, D-5 SCHEDULED |
| REPEATED-WEAK flags | 0 (two trends flagged for the next run: T-1, T-2) |
| Live code/doc findings | 1 MEDIUM (contract:240, instance #14), 1 LOW-MEDIUM (pin scope) |
| Campaign converged? | **No — it stopped.** Round 9's zero-finding result is contradicted by measurement at the reviewed SHA. |

**The one-sentence finding.** The seven-agent gate performed strongly as a *diff* reviewer —
seven distinct defect classes caught that local verification structurally could not reach — and
failed in the two places its charters do not reach: it could not question the design (the
operator did that), and it could not stop a nine-round campaign from shipping the fourteenth
instance of the defect it spent nine rounds on.
