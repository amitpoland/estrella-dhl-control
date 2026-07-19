# Campaign governance (`.campaigns/`)

Operator design ruling (2026-07-17), superseding the first tracked-registry draft. Born from
the 2026-07-16 MEDIUM-2 incident: one campaign branch was reset by three different writers in
under an hour because ownership and the chartered tip lived only in chat threads, session
memory, and reflog archaeology. Two lessons: (1) mutable campaign state must NOT live in a
tracked file — every feature PR would carry governance churn, two campaigns conflict on one
file, a registry commit is never atomic with the branch move it describes, and a stale tracked
file could itself drive a bad reset; (2) a file that sessions merely READ would not have
stopped the incident — **only an enforced guard does**.

## The split

| Layer | Where | Tracked? |
|---|---|---|
| Policy (this dir): rules, schema, guard spec | `.campaigns/README.md`, `policies.json`, `schema.json`, `OWNERSHIP-GUARD-SPEC.md` | YES — permanent policy only |
| Operational registry: live campaign state | `C:\PZ-main\.claude\state\active-campaigns.json` (fallback `<repo>\.claude\state\`) | **NO — gitignored** (`.claude/state/`) |
| Enforcement | `.claude/hooks/campaign-branch-guard.py` (PreToolUse, fail closed) | YES |

The operational registry holds per-campaign `{branch, worktree, owner, expected_head,
last_verified_head, state, phase, superseded[], lock/heartbeat}` and is edited ONLY by the
named owner session or the operator. `state` is the lifecycle stage; `phase` is the gate being
waited on (e.g. `state: FROZEN`, `phase: WAITING_FOR_PR924`) — a session reads the whole
campaign lifecycle, not merely which branch exists (§5; designed for 10–20 parallel campaigns).

**State beats ownership (§6):** in FROZEN / LOCKED / DEPLOYING / ARCHIVED states the guard
denies commit/reset/rebase/cherry-pick/merge for ALL sessions — including the owner. Ownership
match alone is never sufficient to permit a write.

**Session-start banner (§7):** `.claude/hooks/campaign-session-banner.py` emits the compact
campaign card (Campaign / Owner / State / Expected HEAD / Worktree / Allowed operations) at
every session open — context comes from the registry, never from chat archaeology.

## The rules (machine-readable copy: `policies.json`)

1. **One branch = one implementation owner.** Everyone else is READ-ONLY on it, regardless of
   any chat message or review verdict.
2. **One campaign = one worktree.** Reuse it; a new worktree needs explicit operator approval
   (the guard's `ask` on `git worktree add` IS that gate) and lives under `C:\PZ-wt\<slug>`.
3. **Only the owner moves a campaign branch.** Any move by a non-owner, or onto a superseded
   SHA, is an incident.
4. **Read the operational registry before any campaign-branch write.** Never reconstruct
   ownership or the chartered decision from reflog, chat, or memory files.

## SHA semantics — branch-tip space vs main space

- `expected_head` — the operator-approved target. **Always the campaign BRANCH-TIP SHA.**
- `last_verified_head` — what read-only verification actually found (also branch-tip space).
- `merge` *(optional)* — `{pr, squash_sha, merged_at}`: main-side provenance for a merged
  campaign. **Inert** — no guard compares any field here against worktree HEAD.

**A main-side / squash-merge SHA may never be stored in `expected_head`.** Doing so produced
the `transport-m1` false-drift incident (2026-07-18): `expected_head` held the PR #940 squash
commit `4676057…` while the registered worktree correctly sat on the branch tip `779c1b5f…`,
so the guard's check 5 would have raised a spurious "unexpected HEAD" incident the moment a
lock was claimed. Rationale + rejected alternatives:
`docs/decisions/ADR-campaign-state-lifecycle-sha-authority.md`.

**Deployment lifecycle does not live here.** UAT, business-owner sign-off, deployment
validation and production completion belong to `PROJECT_STATE.md` under the Business Feature
Completeness Standard. This registry is a branch/worktree **ownership** authority; growing
deployment fields would make it a second feature-lifecycle authority.

If they diverge (or the real tip diverges from `expected_head`): **file an incident report and
request an operator ruling. No session may auto-"correct" the branch.** A stale registry must
never be able to drive a reset. (This replaces both the self-referential `canonical_sha`
equality gate and the single `last_known_tip` of earlier drafts.)

## Superseded SHAs

Recorded, tagged, and dispositioned (e.g. "NEVER cherry-pick, NEVER merge") in the registry
entry — never merely deleted.

## Status + lifecycle

`IN_PROGRESS` → `READY_FOR_REBASE_AFTER_<gate>` → `REBASED_PENDING_REVIEW` → `PR_OPEN` →
`MERGED` → entry removed from the registry + worktree archived (WORKTREE DISCIPLINE).

If the worktree cannot be archived immediately at merge — post-merge follow-up still open,
as with `transport-m1` — the entry moves to **`MERGED_PENDING_ARCHIVE`** instead of lingering
in an undeclared state. That state is **write-restricted**: the branch is merged and the
worktree is still registered, so no legitimate write remains, and the guard denies for owner
and non-owner alike. The entry leaves the registry when the worktree is archived.

**Unknown states fail closed.** A `state` outside the enum (or absent) is never treated as
writable: the guard emits an explicit `ask` naming the value and requires an operator ruling.
`MERGED_VERIFIED` — invented at merge time, present in no enum, and unnoticed because nothing
validates the registry against its schema — is the reason this rule exists.

## Why this design (worked example)

In the 2026-07-16 incident, a second session — instructed to run an independent candidate
comparison — reset the campaign branch to a superseded candidate. With this model: the guard
reads owner + lock before the reset executes, the session holds neither, the write is DENIED
with an explicit report (registered owner, current session, expected vs actual HEAD). The
churn cannot happen, regardless of what any relayed instruction claims.
