# PR Merge Verification Contract (C1–C6) — forward-state-aware

**Status:** ACTIVE · **Owner:** orchestrator / git-workflow · **Created:** 2026-06-14
**Tooling:** `.claude/scripts/verify_pr_merge.sh`
**Origin incident:** PR #575 false-negative — a task prompt hardcoded `expected origin/main = 62810c2`; by re-verification time main had legitimately advanced to `6665597` (#574→#582). The merge was sound; the *validation framework* was stale.

---

## 1. Where C1–C6 are defined and executed

There is **no GitHub Actions CI** in this repository (no `.github/workflows/`), by deliberate
design — deploys are operator-gated robocopy to a Windows NSSM service, not Actions-driven.
`verify.sh` / `make verify` are the **engine golden-batch gate** (PZ calculation correctness);
they do **not** inspect git/PR state and are unrelated to C1–C6.

Consequently, C1–C6 are an **agent-run verification process**, historically transcribed into
each task prompt by hand. The hand-transcription is exactly where staleness entered: the
expected main SHA was a literal constant captured at authoring time, with nothing re-reading
current `origin/main`.

**Canonical executor (this contract):** `.claude/scripts/verify_pr_merge.sh <PR>`.
The six criteria are now code, not prose, and main state is captured dynamically.

| Criterion | What it asserts | Implementation |
|---|---|---|
| C1 | Zero conflict markers in changed files | `git grep -nE '^(<<<<<<<\|>>>>>>>)' <head> -- <changed>` |
| C2 | Diff scope (file count; `--doc-only` ⇒ zero code files) | `git diff --name-only origin/main...<head>` |
| C3 | Governance tokens preserved in merged head | `git grep -qF -- "<tok>" <head> -- <changed>` |
| C4 | No **PR-introduced** duplicate `OQ-NEW-N` heading defs | `git diff origin/main...<head>` `+` lines only |
| C5 | Named file byte-identical to `origin/main` | `git diff origin/main <head> -- <file>` empty |
| C6 | **Live-main safety invariant** (see §2) | `git merge-base --is-ancestor` **OR** gh CLEAN/MERGEABLE |

---

## 2. C6 — the fix: never assert a static main SHA

### Anti-pattern (what caused the incident)
```
# FORBIDDEN — stale the moment main advances:
[ "$(git rev-parse --short origin/main)" = "62810c2" ] || FAIL
```
A pinned main SHA encodes a point-in-time snapshot. Main legitimately advancing
(another PR merging) then reads as a defect even when the PR under test is perfectly safe.

### Required pattern
1. **Capture main dynamically** at the start of every verification:
   `git fetch origin && MAIN=$(git rev-parse origin/main)`.
2. **Assert the safety invariant, not SHA equality.** The PR is C6-safe if *either*:
   - **(a) ancestor/fast-forward:** `git merge-base --is-ancestor origin/main <head>`
     (the branch already contains all of current main), **or**
   - **(b) GitHub-clean:** `mergeStateStatus == CLEAN && mergeable == MERGEABLE`
     (GitHub recomputed no conflict against *current* main).
3. **Report advancement as INFO, never FAIL.** If an optional prior baseline SHA is
   supplied (`--baseline-main`), the delta is printed as
   `main ADVANCED <old> → <new> (+N commits) — EXPECTED, not a defect`.

This satisfies all four required cases simultaneously: main advances · branch contains
main's new work (ancestor passes) · GitHub confirms mergeability · none trigger a failure.

### 2.1 Mergeability is LAZY — poll, and never read UNKNOWN as a conflict

GitHub computes `mergeable` / `mergeStateStatus` **asynchronously**. The *first*
`gh pr view` after main moves (or after any push) routinely returns
`mergeable=UNKNOWN` while it recomputes, then resolves to `MERGEABLE` or
`CONFLICTING` on a later read. Observed on this repo 2026-06-14: a clean,
mergeable PR (#522) returned `UNKNOWN/UNKNOWN` on poll 1 and `MERGEABLE/CLEAN` on
poll 2. A single-call verifier that maps UNKNOWN to the conflict branch would
**false-FAIL a perfectly mergeable PR** — the very false-negative this contract exists
to eliminate. The executor therefore **polls** until mergeability resolves (OPEN PRs
only) before judging C6.

The three GitHub states are **not interchangeable**. C6 maps them as:

| Condition | C6 verdict |
|---|---|
| PR `state == MERGED` | **PASS (N/A)** — already landed; conflict check is moot |
| branch contains all of current main (ancestor) | **PASS** — fast-forward-safe |
| `mergeable==MERGEABLE && mergeState==CLEAN` | **PASS** — no conflict vs current main |
| `mergeable==CONFLICTING \|\| mergeState==DIRTY` | **FAIL** — real conflict, rebase required |
| `UNKNOWN` (after polling) / `BLOCKED` / `BEHIND` / `UNSTABLE` | **WARN (INDETERMINATE)** — never a hard FAIL |

Only `CONFLICTING`/`DIRTY` is a conflict. `UNKNOWN` is "not computed yet"; a `MERGED`
PR is moot. Both were previously mis-scored as FAIL and are now handled explicitly.

---

## 3. Authoring rule (binds task prompts)

Any task prompt that specifies merge-verification criteria **MUST NOT** embed a literal
expected `origin/main` SHA as a pass/fail assertion. A specific SHA may appear only as an
*informational baseline* (`--baseline-main`) for advancement reporting. The pass/fail signal
for live-main state is the §2 invariant, evaluated against dynamically-captured `origin/main`.

A prompt that hardcodes a main SHA as a C6 assertion is **non-conformant** and must be
rewritten to call `verify_pr_merge.sh` (or reproduce its dynamic capture + invariant).

---

## 4. Usage

```
.claude/scripts/verify_pr_merge.sh <PR_NUMBER> \
  --doc-only \                         # assert zero code files (docs/memory PRs)
  --expect-files 12 \                  # informational file-count check (WARN on mismatch)
  --baseline-main <sha> \              # optional: report advancement vs this baseline
  --self-eval-file <path> \            # C5 byte-identity (repeatable)
  --govern-token "<string>"            # C3 presence (repeatable)
```
Exit 0 = all pass · Exit 1 = real defect · Exit 2 = usage/env error.
Main advancement **never** contributes to exit 1.

---

## 5. Cross-references
- Path guard / source-of-truth tree: `CLAUDE.md` → Canonical working-tree registry (`C:\PZ-verify`).
- Deploy gate (specialises GATE 1 for production syncs): `.claude/agents/deploy_*.md`.
- Windows colon-revision mangling workaround: prefer `git grep <tree-ish> -- <path>` and
  `git diff A B -- <path>` over `git show rev:path`.
