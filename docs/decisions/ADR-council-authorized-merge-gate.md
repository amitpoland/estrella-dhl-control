# ADR — Council-Authorized Merge Gate (pz-deploy-guard)

**Status:** Proposed (operator-approved campaign; this ADR/guard PR is operator-merge-only)
**Date:** 2026-07-19
**Scope:** `.claude/hooks/pz-deploy-guard.py` rule 2 (`gh pr merge`) enforcement
**Supersedes:** the unconditional `gh pr merge` denial (the other three deny rules are unchanged)

---

## Context
`pz-deploy-guard.py` (PreToolUse hook) unconditionally denies four operator-only actions:
prod-tree writes, **`gh pr merge`**, `git push` to main, and edits under `C:\PZ`. The unconditional
merge denial forces an operator to hand-merge even fully Council-reviewed, technically-mergeable PRs
on an **unprotected** `main` (GitHub imposes no branch protection; the agent token has admin). The
operator ruled: an agent may merge an ordinary PR **only** on deterministic, machine-verifiable
Council authorization — never on conversational "Council PASS", never on branch-controlled files a
candidate PR can edit to authorize itself, never via API/browser bypass.

## Decision
Replace rule 2's unconditional denial with a narrowly-scoped, **fail-closed** authorization check
(`merge_authorization.evaluate_merge`). An agent-initiated merge is permitted **only** when ALL hold:
1. flag `PZ_AUTONOMOUS_MERGE_ENABLED == "1"` (operator/harness env; default OFF);
2. command is a **lone** `gh pr merge <PR> --squash --match-head-commit <head_sha>` (squash only; no `--admin`; **no shell chaining / second command** — any `&&`, `||`, `;`, `|`, redirection, or a second `gh pr merge` denies, so an authorized merge can never piggyback an unauthorized action);
3. a trusted signing key is available (`PZ_MERGE_AUTH_KEY[_FILE]`, outside the repo);
4. a signed authorization artifact exists for that PR in the trusted store (`PZ_MERGE_AUTH_DIR`, outside the repo);
5. HMAC-SHA256 signature valid (constant-time) over the canonical body;
6. repository + PR match; **`head_sha` == the command's `--match-head-commit`** (deterministic head binding; GitHub also refuses on head drift);
7. `council_verdict == "PASS"` and both test-result refs present;
8. `issued_at <= now < expires_at`; `authorization_id` (jti) not already consumed (replay blocked; consumed on allow);
9. signed `changed_files` match `changed_files_digest` and contain **no protected path/domain** (below);
10. merge method permitted by policy = **squash only** (first implementation).

Any missing / malformed / expired / mismatched / unsigned input, or any validator/import error → **DENY**.

## Trust model (why the candidate cannot self-authorize)
The flag, key and store all come from the **operator/harness environment**, never from a file inside
the candidate branch and never from the candidate process alone. The artifact is HMAC-signed with a
secret the candidate does not possess — setting the flag without the key yields nothing (signature
fails → deny). The head is pinned via `--match-head-commit`, bound to the signed `head_sha`, so a
changed head invalidates the authorization deterministically (no network call) and GitHub enforces it.

## Protected actions / domains — ALWAYS operator-only (never auto-mergeable)
A PR whose signed `changed_files` touch any of these is denied even with a valid signature. The
enforcement is by matched markers in the signed file list, in two layers:
- **`PROTECTED_PATH_MARKERS`** — the guard itself (`pz-deploy-guard.py`, `merge_authorization.py`),
  `.claude/settings.json`, any `.claude/hooks/`, this ADR/policy, production_deployment_rule /
  governance-precedence, `.env` / `secrets` / `credentials` / `core/security`, `service/app/auth/`
  (JWT + session), and guard-validating tests.
- **`PROTECTED_DOMAIN_MARKERS`** — migrations/schema/`/alembic/`, plus the fiscal / remote-write /
  identity authorities: `wfirma` (remote wFirma write), `customs`, `customer_master`,
  `carrier/` (shipment creation), `company_account` (bank/currency mapping). Over-matching here fails
  **closed** (more operator merges) and deliberately does **not** match the ordinary proforma editing
  surface (`routes_proforma.py`) — only the fiscal-write authorities.

This keeps schema migration, new persistence authority, historical backfill, remote wFirma/financial
writes, bank/accounting/tax/customs/Customer-Master authority changes, identity replacement, carrier
shipment creation, credential/auth-policy changes, **and modification of the merge-authorization
mechanism itself** operator-merge-only. **Fiscal writes are additionally hard-gated** by their own
`WFIRMA_CREATE_*_ALLOWED` operator flags regardless of any merge decision — this gate is defence in
depth, not the sole control. Changes to the guard remain operator-merge-only.

## Fallback (this repository, today) — structure built, denial NOT weakened
There is **no CI signer, no `.github/workflows`, no key, no authorization store**, and the in-session
Council is the candidate process (cannot self-authorize). Therefore the flag is **default OFF** and
every path returns **DENY** — behaviour identical to today's unconditional denial. The policy +
validator + tests are in place, ready to activate only when the operator provisions a trusted signer
(e.g. a CI job holding the key, issuing artifacts into the out-of-repo store).

**Self-referential bootstrap (honest disclosure):** the mechanism cannot authorize its own
introduction — the PR that *adds* the gate touches the guard files (a `PROTECTED_PATH_MARKER`) and
runs before any signer exists. That is exactly why this PR is **operator-merge-only**; its approval is
a human operator directive, not a machine artifact, and is not claimed to be self-verified.

**Deferred to a separate activation ADR (not in scope here):** the concrete signer, the key-management
/ rotation model, the requirement that `PZ_MERGE_AUTH_DIR` live **outside** the repository tree, and
who/what performs the review the `council_verdict=="PASS"` field attests to. Until that ADR is written
and the operator provisions the signer, the gate stays default-OFF and deny-only. The validator
verifies an externally-issued artifact; it does not itself adjudicate review quality.

## Authorization artifact (v1)
`{version, authorization_id, repository, pr_number, head_sha, base_sha, changed_files,
changed_files_digest, council_verdict, focused_tests_ref, regression_tests_ref, merge_method,
issued_at, expires_at, signature}` — `signature` = HMAC-SHA256 over the sorted-compact canonical body
of all fields except `signature`.

## Security rules honored
Fail closed everywhere; missing/malformed/expired/mismatched → deny; changed head → deny; consumed →
deny (replay); never log secrets/tokens (only rule labels + short reasons); env set by the candidate
alone does not authorize (a signed artifact is still required); API/browser bypass is out of scope —
the guard denies `gh pr merge` unless authorized and other bypass verbs (`git push` main) stay denied.

## Security review (applied)
A focused security review of the enforcement logic found no self-authorization path (the candidate
cannot forge an artifact without the out-of-repo HMAC key) and two hardening items, both fixed here:
(1) MEDIUM — the `secrets` protected marker had a leading slash and missed a top-level `secrets/`
directory; now bare `secrets` (over-matches toward denial); (2) LOW — `mark_consumed` swallowed write
failures, leaving a replay window; now `evaluate_merge` denies if the consumed token cannot be
persisted, and the default writer raises rather than passing silently. Both pinned by tests.

## Rollback
Unset `PZ_AUTONOMOUS_MERGE_ENABLED` (→ deny-all merges, current behaviour) or revert this PR. Operator
merge capability is preserved. Deployment restrictions (rules 1/3/4) are untouched. Audit/decision
evidence is not deleted.

## Consequences / testing
`.claude/hooks/merge_authorization.py` (validator) + `test_council_merge_guard.py` (36 tests: the 15
required scenarios + fail-closed guarantees + hook integration proving default-deny and unchanged
rules 1/3/4 + the Level-3 Council follow-ups: compound-command denial, auth-side merge-method / not-
yet-valid / version / unreadable-consumed branches, end-to-end replay sequence, fiscal-domain
denial). `pz-deploy-guard.py` rule 2 now delegates; rules 1/3/4 unchanged. **This PR changes the
merge-enforcement authority and is therefore operator-merge-only.**

## Council review (Level 3)
Security seat **PASS** (no self-authorization path; 2 hardening items applied). Backend seat **PASS**
(pure injectable validator; 3 minor items applied). QA seat **CHANGES REQUIRED** → repaired
(wrong-PR test now reaches the validator's own check; added the untested branches). Principal-
Architect/challenge seat **CHANGES REQUIRED** → repaired (DEFECT-1 compound-command guard added;
DEFECT-2 ADR/code protected-domain mismatch reconciled). All findings resolved; suite green (36).
