# Seven-Agent Gate Evidence Contract

The machine-checkable artifact recording a seven-agent production gate verdict.
Validated by `.claude/hooks/gate_evidence.py`; required by
`sign_deploy_authorization.py` for `deploy` and `reconcile`.

**Authority model.** The seven-agent gate approves a production change; the signed
HMAC authorization permits the write. Evidence gates **signing**; the signature gates
the **deploy**. Evidence never replaces the signature — a text file cannot be
single-use, key-protected, or revoked, so making it the sole gate would be weaker than
what this repository already has.

**CI is not consulted.** A red inherited baseline is not a production hold. Node-ID
comparison remains a test-PR merge tool. Neither appears in this contract.

---

## Required fields

```
TARGET_SHA: <full 40-character lowercase commit SHA>
EXPIRES_AT: <ISO 8601 timestamp>          # optional; enforced when present
```

Then one block per agent, per `gate_output_contract.md`:

```
AGENT: <agent_name>
STATUS: CLEAR | PASS | GO | HOLD | BLOCK | FAIL
DISPOSITION: GO | HOLD:<reason> | BLOCK:<reason> | N/A
```

Other `gate_output_contract.md` fields (`BLOCKERS`, `CHANGED_FILES`, `TESTS`, `RISKS`,
`NOTES`) may be present and are ignored by the validator — they are for the human
reader. Only agent identity and verdict are enforced.

## The seven agents

All seven must appear. A gate that ran six is not the gate CLAUDE.md defines.

| agent | owns |
|---|---|
| `deploy_lead_coordinator` | final go/no-go |
| `deploy_git_diff_reviewer` | file classification, forbidden paths |
| `deploy_backend_impact_reviewer` | routes, auth, imports |
| `deploy_persistence_storage_reviewer` | schema, storage writes |
| `deploy_security_reviewer` | credentials, auth removal, injection |
| `deploy_qa_reviewer` | test pass/fail |
| `deploy_release_manager` | branch hygiene, rollback command |

Names are matched case-insensitively with `-`/`_` interchangeable and a trailing `.md`
tolerated, so `deploy-security-reviewer.md` and `deploy_security_reviewer` are the
same agent.

## Validation rules

Every rule fails **closed** — refusal, never a warning.

1. `TARGET_SHA` present, well-formed, and **equal to the SHA being signed**. Absent or
   malformed is a refusal; it is never inferred from context. A verdict that does not
   name its revision cannot be bound to one (Lesson Q rule 7).
2. All seven agents present.
3. No agent in `HOLD` / `BLOCK` / `FAIL`, by `STATUS` or `DISPOSITION`.
4. Every agent's `STATUS` is one of `CLEAR` / `PASS` / `GO`. An unrecognised status is
   a refusal, not a pass — a typo must not read as approval.
5. `EXPIRES_AT`, when present, must be in the future. Malformed is a refusal.
6. The file must be readable and non-empty.

## Tamper binding

The signer records `gate_evidence_ref` as:

```
<absolute-path>@sha256:<64-hex-digest>
```

`gate_evidence_ref` is already inside `_SIGNED_FIELDS`, so the digest is covered by the
authorization's HMAC **without adding a signed field**. That is deliberate:
`deploy_authorization._SIGNED_FIELDS` warns that changing the canonical body
invalidates every previously minted artifact and must not be done silently once a
signer exists. Reusing the field keeps existing artifacts valid.

At **use** time `deploy_authorization.evaluate()` re-hashes the file and refuses on
mismatch. Signing and deploying are different moments; the gap between them is exactly
when an evidence file gets edited.

An artifact whose ref carries no digest is refused for `deploy` and `reconcile` — the
pre-binding shape is not grandfathered.

## Rollback is exempt

`rollback` does not require evidence. It is the incident path, its artifact is meant to
be minted in advance, and gating a recovery on assembling a fresh seven-agent report
lengthens outages. When evidence *is* supplied for a rollback it is still digest-bound.

---

## Example

```
TARGET_SHA: 6e1de8b1a2c34d5e6f708192a3b4c5d6e7f80912
EXPIRES_AT: 2026-08-04T18:00:00+00:00

AGENT: deploy_git_diff_reviewer
STATUS: CLEAR
DISPOSITION: GO

AGENT: deploy_backend_impact_reviewer
STATUS: PASS
DISPOSITION: GO

AGENT: deploy_persistence_storage_reviewer
STATUS: CLEAR
DISPOSITION: GO

AGENT: deploy_security_reviewer
STATUS: CLEAR
DISPOSITION: GO

AGENT: deploy_qa_reviewer
STATUS: PASS
DISPOSITION: GO

AGENT: deploy_release_manager
STATUS: PASS
DISPOSITION: GO

AGENT: deploy_lead_coordinator
STATUS: GO
DISPOSITION: GO
```

Then:

```
python .claude/hooks/sign_deploy_authorization.py <sha> deploy Both \
    --gate-evidence <path-to-this-file> --ttl 60
```

The signer refuses if any rule above fails, so an unapproved SHA never reaches the key.
