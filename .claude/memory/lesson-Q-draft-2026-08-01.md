# DRAFT — Engineering Lesson Q (not yet landed)

Raised by the observer scorecard `.claude/memory/scorecards/2026-08-01-pr1062-amendment-register-refresh.md`
(2026-08-01), dispositioned **GATE-4 SCHEDULED**.

**Both target files are TRACKED**, so landing this needs a commit + PR. GATE-2 is at its 4-PR
ceiling (#1053, #1062, #1063 impl + #1061 docs), and #1061's published scope is exactly one file
(`TASK_STATE.md`) — adding CLAUDE.md there would falsify that scope the same way a TASK_STATE
commit on #1062 would have. So: **draft now, land when a slot frees** (or on operator word to
stack it onto #1061 and amend that PR's body).

Letter: **Q**. (Note a pre-existing collision in CLAUDE.md — there are two `### Lesson N` headers,
dated 2026-06-23 and 2026-06-22. Not fixed here; flagged as separate governance debt.)

---

## ARTIFACT 1 — insert into `CLAUDE.md` after Lesson P (currently ends line 855, before the `---` at 857)

### Lesson Q — A state-file claim about a safety property is worthless without a source citation; cite the function or re-verify before you rely on it (2026-08-01)

**GATE-1 + GATE-4 + every state-file / handoff register.** A resume note recorded in `TASK_STATE.md` asserted that a straight signed deploy against the HYBRID production runtime would be caught: that the post-#1039 `restored_sha` was **content-derived**, would "resolve to no single clean SHA", and that "the backup-provenance stop condition fires by design." Read against the deploy tooling, **both halves were false.** `restored_sha` is **marker-derived** — `New-BackupUnit` takes it from `Read-VersionMarker` — and the production marker was perfectly readable and well-formed, so nothing resolved to "no single clean SHA" and **no stop condition fired.** `Resolve-RestoredSha` refuses on only two conditions (`unit.json` disagreeing with `version.pre.txt`, or both absent); neither applied. The claim was not merely wrong, it was wrong **in the operator's favour**: it described a tripwire where there was none, and so concealed the real hazard — a straight deploy would have **silently** minted a backup unit labelled with the old marker while holding different bytes, surfacing only later as a rollback that restores one commit's files and then stamps a different commit's SHA.

**Binding rules:**
1. **A safety-property claim in a state file requires a source citation.** Any assertion that a gate blocks, a guard fires, a check refuses, or an operation is "safe by design" must name the **function** (and file) that implements it — e.g. "`Resolve-RestoredSha` refuses when …". A claim with no citation is an **assumption wearing a fact's clothes** and must be written as one.
2. **Cite the function, not just a line number.** Line numbers drift across branches: `Assert-ProductionMatchesRecordedSha` sits at a given line on the feature branch and **does not exist at all** on `main`. A citation that cannot be resolved on the reader's branch is not a citation.
3. **Verify before relying, not before writing.** A recorded safety claim must be re-verified against source at the moment it is about to be *acted on* — a resume, a handoff, a deploy decision — not trusted because a prior session wrote it down. State files are memory, not authority; the code is the authority.
4. **Name where the protection lives.** If the protection exists only on an unmerged branch, the state file must say so. "This is caught" and "this is caught by an open PR that has not merged" are opposite operational facts.
5. **Correct by marking, never by deleting.** When a recorded claim is found wrong, mark it **WITHDRAWN** with the corrected mechanism beside it. Deleting the old claim destroys the audit trail of *why the reasoning changed* — which is the part a future session needs in order to not re-derive the same error.
6. **Wrong-in-your-favour is the severe class.** A pessimistic error (claiming a block that is really permitted) costs a wasted stop. An optimistic error (claiming a tripwire that does not exist) removes a stop the operator believed they had. Treat any safety claim that *permits* proceeding as the higher-scrutiny case: it needs the citation, and it warrants a `reviewer-challenge` second pass before commit.

**Where it binds**: every `TASK_STATE.md` / `PROJECT_STATE.md` entry asserting a gate, guard, block, or stop condition; every handoff `next_command` or resume note; every `EXECUTION_BLOCKED` checkpoint validation. `reviewer-challenge` must flag an uncited safety claim in any state-file diff.

**Reference**: 2026-08-01 register refresh (`b5853935`, PR #1061). Caution recorded 2026-07-31, found wrong 2026-08-01 by reading `.claude/deploy/Deploy-PZ.ps1` (`Read-VersionMarker`, `New-BackupUnit`, `Resolve-RestoredSha`) rather than trusting the register. It had sat wrong for one day, over a HYBRID production runtime, while the only real protection (`Assert-ProductionMatchesRecordedSha`) existed solely in the still-unmerged PR #1062. The withdrawn claim was marked, not deleted. Observer scorecard: `.claude/memory/scorecards/2026-08-01-pr1062-amendment-register-refresh.md`.

---

## ARTIFACT 2 — one-line addition to the "Enforcement surfaces" paragraph in CLAUDE.md (the paragraph just under `## Engineering Lessons (permanent)`)

Append to the end of that paragraph:

> **Lesson Q binds at every state-file write that asserts a safety property** — `reviewer-challenge` must flag any claim that a gate blocks / a guard fires / an operation is safe-by-design when the claim names no implementing function, and must treat an *optimistic* uncited claim (one that permits proceeding) as the higher-severity case.

---

## ARTIFACT 3 — full narrative for `.claude/memory/engineering_lessons.md` (append at end, matching existing entry style)

### Lesson Q — Uncited safety claims in state files (2026-08-01)

**Origin.** PR #1043's deploy handoff left production in a HYBRID condition: the version marker
recorded one commit while the application bytes were another. (Operator ruling 2026-08-01: all 529
files match `423fa3cb`; only `version.txt` is false — a deployment-provenance defect, not a runtime
overlay.) The 2026-07-31 register recorded a resume caution explaining why the recorded
`next_command` was no longer valid. The explanation it gave was invented, not read.

**What the register claimed:**
> "Running it as-is now snapshots the hybrid tree into the pre-deploy backup → the post-#1039
> content-derived `restored_sha` resolves to no single clean SHA → the backup-provenance stop
> condition fires by design."

**What the source says.** `New-BackupUnit` sets the restored identity from
`Read-VersionMarker -Path $Cfg.version_file` — the **marker**, not a content hash. The marker on the
hybrid runtime was a valid, well-formed SHA. `Resolve-RestoredSha` refuses in exactly two cases:
`unit.json`'s `restored_sha` disagreeing with `version.pre.txt`, or both being absent. Neither
applied. **No stop fires.**

**The actual hazard the false claim concealed.** A straight signed deploy would have minted a backup
unit labelled with the old marker while holding the other commit's bytes — an untruthfully-labelled
unit, minted **silently**, with no error at deploy time. It surfaces only on a later rollback, which
restores one commit's files and then stamps production with a different commit's SHA. The single
thing that actually detects this — `Assert-ProductionMatchesRecordedSha`, which compares runtime
bytes to the marker by git object id before the backup is taken — lives only in PR #1062, still open,
**not on `main`**. So for the day the claim stood, the register asserted a tripwire that did not
exist anywhere in shipped code.

**Why it survived.** Nothing in the process required the claim to cite anything. It was written by a
session reasoning about how the tooling *ought* to behave, in a file whose entries are otherwise
mostly verified facts (SHAs, test counts, file lists) — so it inherited their credibility without
earning it. The correction came only because a later session re-read the source while doing
unrelated work.

**Detection signals** — treat any of these in a state file as an uncited safety claim until proven
otherwise: "fires by design", "is caught", "blocks", "fails closed", "will refuse", "is safe" —
appearing without a function name beside it. Also: any `next_command` whose *justification* is a
behavioural claim rather than a checkpoint fact.

**Worked example (the correct form).** Not: "the stop condition fires by design." But: "no stop
fires — `Resolve-RestoredSha` refuses only on `unit.json` vs `version.pre.txt` disagreement or both
absent, and neither applies here. The detection that would catch this is
`Assert-ProductionMatchesRecordedSha`, which is in PR #1062 and **not on `main`**."

**Relationship to other lessons.** Lesson A is the same failure one layer down — a stub asserting a
return shape nobody read from the real builder. Lesson P is its deploy-side sibling — trusting a
tool's copy log instead of verifying content. Lesson Q generalises both to the register itself: **the
artifact that records what is safe is not itself evidence of safety.**

**Governance note.** Raised by `agent-performance-observer` on a session that dispatched zero
subagents. The observer judged that defensible for the low-blast-radius work but named the
safety-claim rewrite as the one act that warranted an independent reviewer — which is why binding
rule 6 routes optimistic safety claims to `reviewer-challenge` rather than leaving it to judgement.

---

## Landing checklist (when a GATE-2 slot frees)

- [ ] Insert Artifact 1 into `CLAUDE.md` after Lesson P (before the `---` preceding "## Frontend Design Standard")
- [ ] Append Artifact 2 sentence to the "Enforcement surfaces" paragraph
- [ ] Append Artifact 3 to `.claude/memory/engineering_lessons.md`
- [ ] Commit in a CLEAN worktree — NOT the root tree while it is parked on #1062
- [ ] Docs-only → GATE-1 docs-only reviewer-waiver applies (per #1060, merged `9408f3d2`); forbidden-files check still required
- [ ] Consider batching with the other SCHEDULED GATE-4 finding (GATE-1 docs-only waiver text) from `2026-07-31-gate4-lean-execution-disposition.md`
- [ ] Separately: the duplicate `### Lesson N` header collision in CLAUDE.md
