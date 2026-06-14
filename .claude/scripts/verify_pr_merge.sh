#!/usr/bin/env bash
# verify_pr_merge.sh — forward-state-aware PR merge verification (C1–C6)
# =====================================================================
# Replaces the ad-hoc, prompt-embedded C1–C6 checklist that produced a
# FALSE-NEGATIVE on PR #575 (2026-06-13/14): a prior task prompt hardcoded
# `expected origin/main = 62810c2`. By re-verification time main had
# legitimately advanced to 6665597 (#574→#582). The merge was sound, but the
# stale constant flagged C6 as a defect.
#
# ROOT-CAUSE FIX: this script NEVER hardcodes a main SHA. It captures
# origin/main dynamically at run time and treats legitimate advancement as an
# INFO event, asserting the real safety invariant instead of SHA equality.
#
# Exit 0 = all criteria PASS (PR safe to merge).
# Exit 1 = a real defect (NOT triggered by main advancing).
# Exit 2 = usage / environment error.
#
# Usage:
#   .claude/scripts/verify_pr_merge.sh <PR_NUMBER> [options]
#
# Options:
#   --expect-files N        Expected changed-file count for the net diff (info; mismatch = WARN not FAIL)
#   --self-eval-file PATH    File asserted byte-identical to origin/main (C5). Repeatable.
#   --govern-token "STR"     Governance token that MUST be present in the diff (C3). Repeatable.
#   --baseline-main SHA      Optional prior-recorded main SHA. If current main differs,
#                            the advance is reported as INFO (requirement #2) — never a FAIL.
#   --doc-only               Assert net diff contains ZERO code files (C2 strict docs-only).
#
# All git work targets the current working tree (must be C:\PZ-verify per PATH GUARD).
# Windows note: colon-revision forms (git show rev:path) are MSYS-path-mangled on this
# host; every blob comparison below uses `git diff A B -- path` (the `--` separator form)
# or MSYS_NO_PATHCONV=1, never the colon form.

set -euo pipefail

# ── arg parse ────────────────────────────────────────────────────────────────
PR="${1:-}"
[[ -z "$PR" || "$PR" == --* ]] && { echo "usage: verify_pr_merge.sh <PR_NUMBER> [options]" >&2; exit 2; }
shift || true

EXPECT_FILES=""
DOC_ONLY=0
BASELINE_MAIN=""
declare -a SELF_EVAL_FILES=()
declare -a GOVERN_TOKENS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect-files)   EXPECT_FILES="${2:?}"; shift 2 ;;
    --self-eval-file) SELF_EVAL_FILES+=("${2:?}"); shift 2 ;;
    --govern-token)   GOVERN_TOKENS+=("${2:?}"); shift 2 ;;
    --baseline-main)  BASELINE_MAIN="${2:?}"; shift 2 ;;
    --doc-only)       DOC_ONLY=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v gh  >/dev/null || { echo "gh CLI not found" >&2; exit 2; }
command -v git >/dev/null || { echo "git not found"    >&2; exit 2; }

SEP="──────────────────────────────────────────────────────"
PASS=0; FAIL=0; WARN=0
ok()   { echo "  ✅ PASS  $*"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ FAIL  $*"; FAIL=$((FAIL+1)); }
warn() { echo "  ⚠️  WARN  $*"; WARN=$((WARN+1)); }
info() { echo "  ℹ️  INFO  $*"; }

echo ""; echo "$SEP"; echo "  PR #$PR — forward-state-aware merge verification"; echo "$SEP"

# ── dynamic anchoring (the fix) ──────────────────────────────────────────────
git fetch origin --quiet
MAIN_SHA="$(git rev-parse origin/main)"
MAIN_SHORT="${MAIN_SHA:0:7}"
# GitHub computes mergeability LAZILY: the first `gh pr view` after main moves (or
# after any push) routinely returns mergeable=UNKNOWN while it recomputes in the
# background, then resolves to MERGEABLE/CONFLICTING on a subsequent read. A single
# call therefore cannot tell "not computed yet" from "genuine conflict" — treating
# that first UNKNOWN as a conflict is itself a false-negative. We poll until it
# resolves (OPEN PRs only; MERGED/CLOSED PRs stay UNKNOWN forever and are handled
# by the C6 short-circuit).
poll_pr() {
  gh pr view "$PR" --json state,mergeable,mergeStateStatus,headRefName,headRefOid \
    -q '[.state,.mergeable,.mergeStateStatus,.headRefName,.headRefOid] | @tsv'
}
read -r PR_STATE PR_MERGEABLE PR_MERGESTATE HEAD_REF HEAD_OID < <(poll_pr)
if [[ "$PR_STATE" == "OPEN" ]]; then
  tries=0
  while [[ "$PR_MERGEABLE" == "UNKNOWN" && $tries -lt 8 ]]; do
    sleep 2; tries=$((tries+1))
    read -r PR_STATE PR_MERGEABLE PR_MERGESTATE HEAD_REF HEAD_OID < <(poll_pr)
  done
  [[ "$PR_MERGEABLE" == "UNKNOWN" ]] && \
    info "GitHub mergeability still UNKNOWN after $tries polls — treated as INDETERMINATE (WARN), never as conflict"
fi
HEAD_SHORT="${HEAD_OID:0:7}"
info "origin/main (captured live): $MAIN_SHORT"
info "PR head:  $HEAD_REF @ $HEAD_SHORT   state=$PR_STATE mergeable=$PR_MERGEABLE mergeState=$PR_MERGESTATE"

# Report legitimate advancement vs an optional prior baseline — INFO, never FAIL.
if [[ -n "$BASELINE_MAIN" ]]; then
  BSHORT="${BASELINE_MAIN:0:7}"
  if [[ "$BASELINE_MAIN" == "$MAIN_SHA"* || "$MAIN_SHA" == "$BASELINE_MAIN"* ]]; then
    info "main unchanged since baseline $BSHORT"
  else
    N="$(git rev-list --count "$BASELINE_MAIN".."$MAIN_SHA" 2>/dev/null || echo '?')"
    info "main ADVANCED $BSHORT → $MAIN_SHORT (+$N commits) — EXPECTED, not a defect"
  fi
fi

CHANGED="$(git diff --name-only origin/main...$HEAD_OID)"
[[ -z "$CHANGED" ]] && { warn "net diff is empty against current main"; }
# Pathspec array of changed files — reused by C1/C3. `git grep <tree-ish> -- <paths>`
# is colon-free and immune to the MSYS path-mangling that breaks `git show rev:path`.
declare -a CH_ARR=()
if [[ -n "$CHANGED" ]]; then mapfile -t CH_ARR <<< "$CHANGED"; fi

echo ""; echo "  -- C1 conflict markers --"
# `<<<<<<<` and `>>>>>>>` are unambiguous conflict markers; the bare `=======`
# divider never appears without them, so checking the angle markers avoids false
# positives on RST/Markdown `====` underlines.
if [[ ${#CH_ARR[@]} -gt 0 ]] && git grep -nE '^(<<<<<<<|>>>>>>>)' "$HEAD_OID" -- "${CH_ARR[@]}" 2>/dev/null; then
  bad "conflict marker(s) found (see above)"
else
  ok "zero conflict markers in all changed files"
fi

echo ""; echo "  -- C2 diff scope --"
NFILES="$(printf '%s\n' "$CHANGED" | grep -c . || true)"
info "$NFILES file(s) changed: $(git diff --shortstat origin/main...$HEAD_OID)"
if [[ -n "$EXPECT_FILES" ]]; then
  [[ "$NFILES" == "$EXPECT_FILES" ]] && ok "file count = expected $EXPECT_FILES" || warn "file count $NFILES != expected $EXPECT_FILES (review)"
fi
if [[ $DOC_ONLY -eq 1 ]]; then
  CODEF="$(printf '%s\n' "$CHANGED" | grep -cE '\.(py|js|ts|tsx|jsx|html|css|sql|sh|ps1|bat)$' || true)"
  [[ "$CODEF" == "0" ]] && ok "zero code files (docs/memory only)" || bad "$CODEF code file(s) in a docs-only PR"
fi

echo ""; echo "  -- C3 governance preservation --"
if [[ ${#GOVERN_TOKENS[@]} -eq 0 ]]; then info "no --govern-token supplied (skipped)"; fi
for tok in "${GOVERN_TOKENS[@]:-}"; do
  [[ -z "$tok" ]] && continue
  # Token must be present in the merged head, within the files this PR touches.
  # git grep over the head tree-ish restricted to changed paths — colon-free, robust.
  if [[ ${#CH_ARR[@]} -gt 0 ]] && git grep -qF -- "$tok" "$HEAD_OID" -- "${CH_ARR[@]}" 2>/dev/null; then
    ok "governance token present: $tok"
  else
    bad "governance token MISSING: $tok"
  fi
done

echo ""; echo "  -- C4 renumbered-heading uniqueness (PR-introduced only) --"
# Only flag duplicate OQ-NEW heading DEFINITIONS that THIS PR adds (three-dot '+' lines).
# Pre-existing duplicate headings already in main are out of scope and ignored.
DUP="$(git diff origin/main...$HEAD_OID -- '.claude/memory/PROJECT_STATE.md' 2>/dev/null \
        | grep -E '^\+#{2,3} OQ-NEW-[0-9]+' \
        | sed -E 's/^\+(#{2,3} OQ-NEW-[0-9]+).*/\1/' \
        | grep -oE 'OQ-NEW-[0-9]+' | sort | uniq -d || true)"
if [[ -z "$DUP" ]]; then ok "no PR-introduced duplicate OQ-NEW heading definitions"
else while IFS= read -r d; do bad "PR introduces duplicate OQ heading: $d"; done <<< "$DUP"; fi

echo ""; echo "  -- C5 byte-identity vs origin/main --"
if [[ ${#SELF_EVAL_FILES[@]} -eq 0 ]]; then info "no --self-eval-file supplied (skipped)"; fi
for f in "${SELF_EVAL_FILES[@]:-}"; do
  [[ -z "$f" ]] && continue
  if [[ -z "$(git diff origin/main "$HEAD_OID" -- "$f")" ]]; then ok "byte-identical to origin/main: $f"
  else bad "differs from origin/main: $f"; fi
done

echo ""; echo "  -- C6 live-main safety invariant (forward-state-aware) --"
# THE FIX: do NOT assert main == <constant>. Assert the merge is safe against
# WHATEVER main is right now. Two independent sufficient conditions:
#   (a) branch contains all of current main  → fast-forward-safe, OR
#   (b) GitHub reports CLEAN + MERGEABLE     → no conflict vs current main.
# HARDENED state machine — three GitHub states are NOT interchangeable:
#   MERGED      → already landed; live-main conflict check is moot (PASS / N-A)
#   ancestor    → branch contains all of current main → fast-forward-safe (PASS)
#   MERGEABLE+CLEAN → GitHub recomputed no conflict vs current main (PASS)
#   CONFLICTING / DIRTY → a REAL conflict; rebase required (FAIL)
#   UNKNOWN / BLOCKED / BEHIND / UNSTABLE → INDETERMINATE; not computed or
#       !CLEAN for a non-conflict reason → WARN, never a hard FAIL.
C6=0
if [[ "$PR_STATE" == "MERGED" ]]; then
  ok "PR already MERGED — live-main conflict check is moot (verification N/A)"; C6=1
elif git merge-base --is-ancestor "$MAIN_SHA" "$HEAD_OID" 2>/dev/null; then
  AHEAD="$(git rev-list --count "$MAIN_SHA".."$HEAD_OID")"
  ok "branch is strictly ahead of current main ($MAIN_SHORT) by $AHEAD commit(s) — fast-forward-safe"; C6=1
elif [[ "$PR_MERGEABLE" == "MERGEABLE" && "$PR_MERGESTATE" == "CLEAN" ]]; then
  ok "GitHub reports CLEAN/MERGEABLE against current main ($MAIN_SHORT) — no conflict"; C6=1
elif [[ "$PR_MERGEABLE" == "CONFLICTING" || "$PR_MERGESTATE" == "DIRTY" ]]; then
  bad "GitHub reports CONFLICTING/DIRTY against current main ($MAIN_SHORT) — real conflict, rebase required"
else
  warn "mergeability INDETERMINATE (mergeable=$PR_MERGEABLE state=$PR_MERGESTATE) — not computed or non-conflict !CLEAN; re-run after GitHub settles. NOT scored as a conflict."
fi
[[ $C6 -eq 1 ]] && info "main-head value itself is NOT an assertion target; advancement is expected"

echo ""; echo "$SEP"
echo "  RESULT: $PASS pass / $WARN warn / $FAIL fail   (main=$MAIN_SHORT, pr=#$PR @ $HEAD_SHORT)"
echo "$SEP"; echo ""
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
