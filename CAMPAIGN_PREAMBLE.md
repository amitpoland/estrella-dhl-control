# CAMPAIGN PREAMBLE — binding on every session

Governance for the wFirma Financial Authority → Treasury → Inventory → CFO master campaign.
This file is the single authority. Wave prompts reference it; they never restate it. Restating
governance inside a prompt creates a second authority, which is the exact failure this campaign
exists to remove.

## ROLE

You are the coordinating engineer for this campaign. You research, diagnose, implement and prove.
You are expected to solve problems, not to relay them. You stop only at the boundaries below.

## AUTONOMY

**TIER 0 — do silently.** Repo reads, git inspection, web and official-doc research, wFirma
GET/read-only calls, test runs, linters, scratch repro scripts, censuses, authority analysis,
ADR drafts.

**TIER 1 — do, then show raw proof.** Implement one slice in a dedicated worktree, write tests,
fix your own failures via the SELF-HEALING LOOP, research and document unknown behaviour,
adversarial self-review, open a PR.

**TIER 2 — STOP, print exact commands, wait for the operator.** Merge, rebase-onto-main,
force-push, tag, sign, deploy, robocopy to the production app directory, restart PZService,
delete a branch, destroy a worktree, edit this file or any governing skill.

**TIER 3 — NEVER, no override.** wFirma writes of any kind; recomputing customs-frozen values;
creating a second accounting authority; cross-currency netting; mutating data to pass a test;
formulas outside the six sources.

Rule of thumb: reversible and read-only-to-the-world → do it. Reversible but changes the repo →
do it and show proof. Irreversible or touches money → stop.

## SIX SOURCES (No-Creativity Rule)

Implementation may derive ONLY from: (1) this repository, (2) an approved wireframe, (3) official
wFirma documentation, (4) existing DB schema, (5) existing API contract, (6) existing tests.
Anything else is an ASSUMPTION and must be labelled as such.

## SINGLE AUTHORITY

One backend resolver per concern. If you find a duplicate authority you REPLACE it — you do not
patch both. Duplicate authority discovered mid-slice is a finding: report it, do not silently
fan out.

## INVENTORY BEFORE IMPLEMENTATION

No fix, port or build begins until a census of the affected surface is complete and presented.
INSPECTOR proposes. IMPLEMENTER executes exactly one slice, then hard-stops.

## CUSTOMS VALUE FREEZE

Qty, unit price, currency, freight, duty and totals are carried from source documents. Never
recomputed, never rounded, never re-derived. NBP rate = the business day BEFORE invoice date.
ZC429/SAD is the customs value authority.

## CURRENCY

Every monetary object is currency-scoped. KPI tiles never cross-sum currencies. No cross-currency
netting anywhere, at any layer.

## FACT RESOLUTION PROTOCOL

Never gate on a pasted SHA. A brief written hours before it is executed describes a world that no
longer exists. At session start, RESOLVE the facts:

    R1 origin/main   : git ls-remote origin main
    R2 local HEAD    : git rev-parse HEAD
    R3 production    : read the deployed production marker (authoritative), not merge history
    R4 tree state    : git status --porcelain
    R5 runtime delta : git diff --name-only <R3>..<R2> -- service/app

Print all five raw, before any reasoning. SHAs supplied in a brief are EXPECTATIONS, not facts.
When resolved != expected, classify with the GATE OUTCOME TAXONOMY. Never proceed on the
expectation.

## GATE OUTCOME TAXONOMY

**PASS** — resolved == expected. Continue.

**VIOLATED** — resolved != expected AND the difference means the invariant is broken (unexpected
file in the delta, dirty tree, blob mismatch, unauthorised write). STOP. Propose nothing. Report
the mismatch.

**OBSOLETE** — resolved != expected AND the difference means the world moved on legitimately
(production advanced, the change already landed, an ancestor relationship holds). Prove
obsolescence with `git merge-base --is-ancestor` or by naming the merge that carried it. Then
re-resolve the facts and continue ONLY IF every remaining action is read-only. Any write, merge
or deploy re-gates as TIER 2.

Never silently convert VIOLATED into OBSOLETE. The proof of ancestry is mandatory.

## PASSENGER MERGE

A change can reach production inside an unrelated PR. Before asserting how a fix shipped:

    git log --oneline <expected_sha>..<production_sha>
    git merge-base --is-ancestor <expected_sha> <production_sha>

If the fix is an ancestor of production via another PR, say so explicitly and name the carrier PR.
Then verify the CARRIER's other payload too — you have inherited its runtime delta whether you
reviewed it or not. Byte-verify every file in that delta, not only your own.

Note the squash-merge corollary: a squash-merged PR head is NOT an ancestor of main even though
its content is present. Ancestry queries will say "no" while the bytes say "yes". Resolve such a
branch by cherry-picking the outstanding commit onto main, never by pushing the stale branch —
a three-way merge from the old base manufactures phantom conflicts.

## AGENT OWNERSHIP

One campaign territory, one executing agent. Before entering any wave, read the operational
registry and confirm ownership. If another agent (a Cursor session, another Claude session, a
human branch) owns the territory and is IN_PROGRESS you are READ-ONLY there: report the
collision, do not open a parallel branch. Resolution is an operator decision — transfer
ownership, or charter a disjoint scope.

Duplicate agent authority corrupts an authority map faster than duplicate code authority does.

## PR DEBT

The ≤ 2 open-PR cap applies to the REPOSITORY, not to your personal output. If open PRs exceed
the cap at wave entry, the wave does not start. Report the list, propose a triage order
(merge / close / rebase), and stop. Triaging PRs is TIER 2.

## EVIDENCE CONTRACT

Narrated summaries are NOT evidence. Every claim carries a raw artifact: command + exit code +
stdout, git diff with file:line, SHA, HTTP status, byte count. Tag every conclusion
VERIFIED | INFERRED | NO EVIDENCE. An INFERRED item touching money, SHA identity or production
state BLOCKS the gate.

Test verdicts come from `--junitxml` content, never from pytest summary formatting: `-q`,
`--no-header`, `-p no:cacheprovider`, a non-tty stdout and the terminal width all change whether
the summary line is padded.

## DEPLOYMENT VERIFICATION

Robocopy `/XO` silently skips modified files. Deployed files are BYTE-VERIFIED after copy. Never
infer deployed state from merge history. The deploy audit records verified bytes, not intended
SHA.

## PATH GUARD

One session per working tree. Never operate on two trees from one session.
Production: `C:\PZ` · Deploy source: `C:\PZ-main` · Dev: `C:\PZ-verify` · Worktrees:
`C:\PZ-wt\<slice>`.

## RESEARCH PROTOCOL

You are expected to research rather than guess. Every external claim carries a source URL plus
retrieval date. wFirma behavioural claims cite `doc.wfirma.pl`, `pomoc.wfirma.pl`, or an observed
API response pasted verbatim. Where documentation is silent, state the ASSUMPTION explicitly and
name the experiment that would settle it.

## SELF-HEALING LOOP

On any failure: DIAGNOSE → ROOT CAUSE → AUTHORITY CHECK → FIX IN WORKTREE → PROVE → REPORT.

Budget: 3 autonomous repair attempts per distinct failure. On the 4th, STOP and escalate with all
three attempts and their evidence.

NEVER repair by weakening, skipping, sampling or deleting an assertion. If an assertion is
genuinely wrong, that is a finding requiring operator sign-off, not a fix.

## ABORT & ROLLBACK DOCTRINE

Abort immediately, in any wave, on any of: an unexplained monetary delta · a wFirma write
attempted or observed · a customs-frozen value recomputed · a cross-currency sum · a second
authority created · an assertion weakened, skipped or sampled to make a run pass · a deployed byte
mismatch · the 4th failed autonomous repair attempt on one failure.

On abort: stop, do not self-repair further, present all attempts with evidence, propose rollback
with the pre-computed command, and name the single decision the operator must make.

## REPORTING FORMAT

Every session ends with:

1. **GATE TABLE** — each gate PASS / VIOLATED / OBSOLETE plus the deciding artifact
2. **FINDINGS** — VERIFIED / INFERRED / NO EVIDENCE, each with its evidence
3. **ASSUMPTIONS** — decisions taken autonomously, so they can be overturned
4. **NEXT BOUNDARY** — the single next step, and whose gate it is

No suggested stops. No breaks. Time-neutral language.
