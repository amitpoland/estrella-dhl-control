# ADR: Campaign-state lifecycle and SHA authority (branch-tip vs merged-main)

Status: Accepted (operator decision, campaign-state lifecycle repair, 2026-07-19).

Decision: The campaign registry remains a **branch/worktree ownership authority** and never
becomes a feature-lifecycle authority. It is *not* claimed to be the repository's sole
campaign-state store — see "Parallel campaign-state system" below. `expected_head` always means the **campaign branch-tip
SHA** and may never hold a main-side SHA. Main-side provenance lives in a new optional, inert
`merge` object `{pr, squash_sha, merged_at}` that **no guard may compare against worktree
HEAD**. One new lifecycle state, `MERGED_PENDING_ARCHIVE`, covers the window between merge
and worktree archival, and is fully write-restricted for owner and non-owner alike.
Post-merge UAT, business sign-off, deployment validation, and production completion belong to
`PROJECT_STATE.md`, not to `active-campaigns.json`.

## Context

The `transport-m1` campaign entry carried `expected_head = 4676057…`, which is the **squash-
merge commit of PR #940 on `main`** — not the campaign branch tip. The registered worktree
`C:\PZ-pr7` correctly held the branch `fix/proforma-multidraft-transport-docs` at `779c1b5f`,
its clean, unmodified pre-merge tip. Investigation (2026-07-19) classified this
**REGISTRY_STALE**: no worktree drift, no reuse, no corruption, no duplicate authority, and no
wrong physical path binding.

Two structural defects produced it:

1. **No post-merge, pre-archive lifecycle state.** `.campaigns/README.md` declares
   `MERGED` → *entry removed from the registry + worktree archived*. `transport-m1` could not
   be removed because UAT and production completion were still pending, so the merge-time
   session recorded `state: MERGED_VERIFIED` — a value present in **no** enum
   (`schema.json`, `policies.json`) — and repurposed `expected_head` to track the merged main
   SHA. Nothing validates the registry against its schema, so the invalid state persisted
   unnoticed.

2. **No home for main-side SHAs.** With only `expected_head` and `last_verified_head` (both
   branch-tip space by `README.md` §45), a merged campaign has nowhere legitimate to record
   the squash SHA. The next merge would overload `expected_head` again.

The consequence is a latent false-drift denial. `campaign-branch-guard.py` check 5 compares
`expected_head` against `git rev-parse HEAD` **in the registered worktree** — branch-tip space
on both sides, correct as written — but the stored value is main-space. The denial is
currently masked: `transport-m1` has `lock: null`, so check 4 emits `ask` and returns before
check 5 executes. It would fire as a spurious "unexpected HEAD" incident the moment a lock is
claimed.

## Decision detail

**1. `expected_head` is branch-tip space, always.** Required, unchanged, never a main SHA.

**2. New state `MERGED_PENDING_ARCHIVE`**, added to the **write-restricted** set alongside
`FROZEN` / `LOCKED` / `DEPLOYING` / `ARCHIVED`. The worktree still exists and is still
registered; the branch is merged, so no legitimate write remains.

Because the state is write-restricted, guard check 4a denies **before** check 5 is reached.
Drift detection is therefore **not disabled after merge** — it is superseded by a stricter
deny, and check 5 stays fully active in every writable state. No suppression branch and no
post-merge exception path is introduced.

**3. Optional `merge` object** `{pr, squash_sha, merged_at}` — the sole home for main-side
provenance. Inert: neither `campaign-branch-guard.py` nor `campaign-session-banner.py` reads
it for any comparison.

**4. Unknown or schema-invalid states fail closed.** Operator correction to the original
proposal: a state outside the declared enum must NOT fall through to write-permitted
behavior. This is a fail-closed enforcement boundary. The guard returns an explicit `ask`
with a diagnostic naming the offending value. All currently valid legacy states keep their
existing semantics.

**5. No deployment lifecycle fields in the campaign registry.** UAT, business-owner sign-off,
production validation and production completion are owned by the Business Feature
Completeness Standard and recorded in `PROJECT_STATE.md`. Duplicating them here would make the
registry a second feature-lifecycle authority.

## Consequences

- `transport-m1` becomes migratable: `expected_head` → `779c1b5f…`, squash SHA → `merge`,
  `state` → `MERGED_PENDING_ARCHIVE`, UAT/production fields → `PROJECT_STATE.md`.
  The migration is an **operator data edit performed after this code lands**; the guard never
  mutates registry state (`OWNERSHIP-GUARD-SPEC.md` non-goals).
- `C:\PZ-pr7` is retained — a registered worktree is expected in this state by definition.
- Old-format records without `merge` are unaffected; the field is optional and additive.
- Rollback ordering is load-bearing: reverting the code while a record carries the new state
  would downgrade it to unknown-state handling. With the fail-closed correction that is now an
  `ask`, not a silent allow — but code and data must still be reverted together.

## Rejected alternatives

- **Additive `merged_main_sha` scalar only** — gives the SHA a home but leaves `MERGED`
  write-permissive and the entry in an undeclared state. Symptom, not cause.
- **Full `merge` + `deployment` objects** — the `deployment` half duplicates the seven-stage
  feature lifecycle already owned by `PROJECT_STATE.md`. Duplicate authority.
- **Revised lifecycle semantics alone** — without a main-SHA home, the next merge overloads
  `expected_head` again.
- **Silent fall-through for unknown states** — rejected by operator ruling; a fail-closed
  enforcement boundary must not degrade to permit-by-default.

## Parallel campaign-state system (disclosed, not addressed here)

`active-campaigns.json` is **not** the repository's only campaign-state store. A second,
independent one exists:

- `tasks/campaign-state.json` — live on disk (~50 KB), shape `{schema_version, campaigns[]}`
  with its own `campaign_id` / `status` vocabulary.
- `service/scripts/campaign_status.py` — its sole reader/writer; resolves the file via
  `_find_repo_root`. Notably it *does* carry deployment fields (`deployed_sha`,
  `previous_main_sha`), which is precisely the coupling this ADR forbids in the ownership
  registry.

It is **dormant**, not competing: a standalone CLI with zero references from `service/app`,
any `Makefile`, route, or scheduler. It does not read `active-campaigns.json`, so the schema
change in this ADR cannot affect it, and the `transport-m1` migration cannot break it — the
59 `deployed_sha` matches in the repository all belong to that separate file's schema.

Consolidating or retiring the parallel system is **separate follow-up governance debt** and is
deliberately out of scope here. What this ADR asserts is narrower and accurate: within the
`active-campaigns.json` registry, branch-tip authority and merged-main provenance are
separate fields, and the registry does not own feature/deployment lifecycle.

## Known follow-up debt (not in scope)

The state enum and the per-state operation matrix are duplicated across `schema.json`,
`policies.json`, `OWNERSHIP-GUARD-SPEC.md`, and two hardcoded Python sets — one concept, five
homes. Consolidating them is deliberately **out of scope** for this campaign. This ADR instead
mandates a **parity test** that fails if the five ever diverge, converting silent drift into a
loud test failure until the consolidation is separately chartered.

## References

- `.campaigns/README.md` (§45 SHA semantics, §60 lifecycle), `.campaigns/schema.json`,
  `.campaigns/policies.json`, `.campaigns/OWNERSHIP-GUARD-SPEC.md`
- `.claude/hooks/campaign-branch-guard.py`, `.claude/hooks/campaign-session-banner.py`
- `service/tests/test_campaign_branch_guard.py` (added by this campaign)
- PR #940 squash `4676057…`; campaign branch tip `779c1b5f…`
- Separate and unrelated: PR #955 (deployment-source authority) — disjoint file set,
  different authority owner; must not be combined.
