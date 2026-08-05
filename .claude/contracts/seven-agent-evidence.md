# Seven-Agent Gate Evidence Contract

The machine-checkable artifact recording a seven-agent production gate verdict.
Validated by `.claude/hooks/gate_evidence.py`; required by
`sign_deploy_authorization.py` for `deploy` and `reconcile`.

**Format: strict JSON.** Human-readable review stays Markdown — reviewer reports, PR
comments, the gate transcript. Production *authorization evidence* is a JSON document
with one schema and one meaning. See *Why JSON* below; this is not a stylistic choice.

**Authority model.** The seven-agent gate approves a production change; the signed
HMAC authorization permits the write. Evidence gates **signing**; the signature gates
the **deploy**. Evidence never replaces the signature — a file on disk cannot be
single-use, key-protected, or revoked, so making it the sole gate would be weaker than
what this repository already has.

**CI is not consulted.** A red inherited baseline is not a production hold. Node-ID
comparison remains a test-PR merge tool. Neither appears in this contract.

---

## Why JSON, and not Markdown

The first implementation parsed a hand-written Markdown report. Across three rounds the
seven-agent gate found **six** distinct ways a human-visible BLOCK could be laundered
into a validated GO:

1. a duplicate `AGENT:` block overriding an earlier BLOCK (last-wins);
2. an agent-like bullet inside a `NOTES:` section;
3. a bare repeated `STATUS`/`DISPOSITION` pair with no second `AGENT:` line;
4. a near-miss agent name whose BLOCK was silently discarded as unrecognised;
5. a verdict appearing before the first `AGENT:` line (orphaned, dropped);
6. a verdict written as a Markdown table row, invisible to the parser;

plus first-wins `EXPIRES_AT` shadowing a genuine expiry. Each was patched; the next
round found the next one.

That is not bad luck, it is the design. A tolerant parser strips decoration, accepts
aliases, reconstructs record boundaries, and **skips what it does not recognise** — so
a human reader and the validator are not guaranteed to be reading the same document.
No finite list of patches closes that class. JSON does: it parses or it refuses.

---

## Schema

```json
{
  "schema_version": 1,
  "target_sha": "6e1de8b1a2c34d5e6f708192a3b4c5d6e7f80912",
  "created_at": "2026-08-05T14:00:00+00:00",
  "expires_at": "2026-08-05T18:00:00+00:00",
  "agents": [
    {"agent": "deploy_git_diff_reviewer",            "status": "GO", "blockers": [], "risks": []},
    {"agent": "deploy_backend_impact_reviewer",      "status": "GO", "blockers": [], "risks": []},
    {"agent": "deploy_persistence_storage_reviewer", "status": "GO", "blockers": [], "risks": []},
    {"agent": "deploy_security_reviewer",            "status": "GO", "blockers": [], "risks": []},
    {"agent": "deploy_qa_reviewer",                  "status": "GO", "blockers": [], "risks": []},
    {"agent": "deploy_release_manager",              "status": "GO", "blockers": [], "risks": []},
    {"agent": "deploy_lead_coordinator",             "status": "GO", "blockers": [], "risks": []}
  ],
  "lead_verdict": "GO"
}
```

| field | type | meaning |
|---|---|---|
| `schema_version` | int | exactly `1` |
| `target_sha` | string | full 40-char **lowercase** commit SHA the gate approved |
| `created_at` | string | ISO 8601; when the gate round concluded |
| `expires_at` | string | ISO 8601; must be after `created_at` and in the future |
| `agents` | list | exactly seven objects, one per authority |
| `lead_verdict` | string | exactly `"GO"` — the coordinator's final decision |

Each `agents` entry has exactly four fields:

| field | type | meaning |
|---|---|---|
| `agent` | string | one of the seven names, **matched exactly** |
| `status` | string | exactly `"GO"` |
| `blockers` | list | must be **empty**; a non-empty list refuses the document |
| `risks` | list | may be non-empty — recorded risk is not a blocker |

The **field sets are exact at both levels**. Unknown fields are refused, not ignored:
an ignored field is somewhere a reviewer's caveat can live while the validator reads
approval. Prose, transcripts, and per-agent narrative belong in the Markdown report the
JSON summarises — not in this file.

## The seven agents

All seven must appear, exactly once each. A gate that ran six is not the gate CLAUDE.md
defines.

| agent | owns |
|---|---|
| `deploy_lead_coordinator` | final go/no-go |
| `deploy_git_diff_reviewer` | file classification, forbidden paths |
| `deploy_backend_impact_reviewer` | routes, auth, imports |
| `deploy_persistence_storage_reviewer` | schema, storage writes |
| `deploy_security_reviewer` | credentials, auth removal, injection |
| `deploy_qa_reviewer` | test pass/fail |
| `deploy_release_manager` | branch hygiene, rollback command |

**Names are matched byte-for-byte.** There is no case folding, no `-`/`_` equivalence,
no `.md` tolerance, no whitespace trimming. `deploy-security-reviewer` is an *unknown*
agent and refuses the document. That strictness is deliberate: name tolerance is
laundering vector 4 — a BLOCK attributed to a near-miss name was discarded as
unrecognised while a clean entry registered as the only record for that authority.

The roster is pinned to `.claude/agents/deploy_*.md` by
`test_required_agents_matches_the_agent_files_on_disk`, so renaming or removing an
agent file fails a test rather than silently narrowing the gate.

## Transcribing an agent's report into this schema

The reviewers do not emit this JSON. They emit Markdown per
`.claude/contracts/gate_output_contract.md`, whose vocabulary is deliberately wider:
`STATUS: CLEAR | PASS | GO | HOLD | BLOCK | FAIL` plus a separate
`DISPOSITION: GO | HOLD:<reason> | BLOCK:<reason> | N/A`. **The evidence schema accepts
only `"GO"`**, so a verbatim copy of `STATUS: CLEAR` is refused with
`status is 'CLEAR', not 'GO'`. That is fail-closed — a faithful transcription is
*denied*, never wrongly accepted — but it will surprise the first operator who tries it,
so the mapping is stated here:

| the agent wrote | evidence `status` | evidence `blockers` |
|---|---|---|
| `STATUS: CLEAR` / `PASS` / `GO`, `DISPOSITION: GO` | `"GO"` | `[]` |
| any `HOLD` / `BLOCK` / `FAIL`, or `DISPOSITION: HOLD:…` / `BLOCK:…` | — | **there is nothing to transcribe** |

A round in which any agent returned HOLD, BLOCK, or FAIL produces **no evidence file at
all**. This schema has no way to record a non-approving verdict, and that is deliberate:
its only purpose is to answer "did all seven approve this SHA". Fix the finding and run
a fresh round. Per-agent reasoning, caveats and the `DISPOSITION` text live in the
Markdown reports, which are the human record — the JSON is the machine assertion drawn
from them.

**The transcription step is the residual trust boundary.** The validator checks that the
document is internally consistent and complete; it cannot check that it faithfully
reflects what seven agents actually returned. All six Markdown laundering vectors are
closed inside the parser, so this is now the only unverified link, and it is a human
one. Keep the seven Markdown reports alongside the JSON.

## Validation rules

Every rule fails **closed** — refusal, never a warning. In order:

1. The file exists and is readable; it is read **once**, and the digest is taken over
   exactly the bytes that are parsed (a second read is a TOCTOU window in which a
   swapped file binds a signature to bytes that were never validated).
2. Valid UTF-8, valid JSON, and a JSON **object** at the top level.
3. **No duplicate keys**, at any depth. Stdlib `json` silently keeps the last value for
   a repeated key — the same last-wins defect the Markdown parser died of, one layer
   down. `object_pairs_hook` refuses instead.
4. Top-level field set is exactly the six above — none missing, none extra.
5. `schema_version == 1`.
6. `target_sha` is a full 40-char lowercase SHA **and equal to the SHA being signed**.
   It is never inferred from context: a verdict that does not name its revision cannot
   be bound to one (Lesson Q rule 7).
7. `created_at` and `expires_at` parse as ISO 8601; `expires_at > created_at`;
   `created_at` is not in the future (5 minutes of clock skew allowed); the window
   `expires_at - created_at` is at most **24 hours** (`gate_evidence.MAX_VALIDITY`); and
   `expires_at` is in the future. A timestamp with no offset is read as UTC.

   **Write timestamps as `datetime.isoformat()` output** — e.g.
   `2026-08-05T14:00:00+00:00`, or with a trailing `Z`, which is rewritten to `+00:00`
   before parsing. The grammar is whatever the running interpreter's
   `datetime.fromisoformat` accepts, and that widened in Python 3.11: basic format
   (`20260805`), ISO week dates, `,` as decimal separator and 1–2 digit fractional
   seconds parse on 3.11+ and are **refused on 3.9**, which is what CI and the
   production host run. The older interpreter is the stricter one, so this cannot
   launder anything — but an exotic spelling accepted on your laptop may be refused
   where it counts, and a reviewer on 3.9 could not re-validate it.
8. `agents` is a list of objects, each with exactly the four fields above.
9. Every `agent` name is in the roster, **exactly**. Unknown → refusal.
10. Every `status` is exactly `"GO"`. There is no passing synonym — every synonym is a
    token to typo into, and an unrecognised status must never read as approval.
11. Every `blockers` list is empty.
12. No agent appears twice, none of the seven is absent, and the list length is exactly
    seven.
13. `lead_verdict` is exactly `"GO"`.

## Storage, authorship, and validity

- **Who creates it.** The operator, after all seven reviewers have returned a verdict
  against **one frozen head**. It is a transcription of the round's outcome — if any
  agent returned HOLD or BLOCK, there is nothing to transcribe: fix the finding and run
  a fresh round.
- **Where it lives.** Outside the repository, alongside the signing key store — e.g.
  `C:\PZ-secrets\gate-evidence\<sha>.json`. It is not committed. A file inside the repo
  can be changed by any agent session that can write tracked files; the whole point is
  that this one cannot.
- **One file per gate round.** Name it by the SHA it approves. A round that fails
  produces no evidence file.
- **How long it is valid.** `expires_at` is set by whoever writes the file, and the
  window is **capped at 24 hours** — enforced, not advised (`gate_evidence.MAX_VALIDITY`;
  a longer window is refused). Keep it far shorter in practice. The window exists because
  a gate verdict is about a tree and a moment; the longer it stays valid, the more likely
  the world has moved. The signed authorization has its own, shorter TTL (`--ttl`,
  default 60 minutes) on top.
- **Write it in UTF-8 without a BOM.** On Windows, PowerShell 5.1's `Out-File` and
  `Set-Content` default to UTF-16LE, and `Out-File -Encoding utf8` emits a BOM — all
  three are refused (`not valid UTF-8` / `not valid JSON`). Use
  `Set-Content -Encoding utf8NoBOM` on PowerShell 7+, or write the file with Python.
- **Signer and verifier must read the same immutable file.** The digest is taken at
  signing time and re-checked at use time, so the file must not be edited, regenerated,
  reformatted, moved, or deleted between minting the authorization and running the
  deploy. Two documents being *equally valid* is not enough — a superseded round's
  evidence, still valid on its own terms, is a denial if substituted for the one that
  was signed.

## Tamper binding

The signer records `gate_evidence_ref` as:

```
<absolute-path>@sha256:<64-hex-digest>
```

`gate_evidence_ref` is already inside `_SIGNED_FIELDS`, so the digest is covered by the
authorization's HMAC **without adding a signed field**. That is deliberate:
`deploy_authorization._SIGNED_FIELDS` warns that changing the canonical body invalidates
every previously minted artifact and must not be done silently once a signer exists.
Reusing the field keeps existing artifacts valid.

At **use** time `deploy_authorization.evaluate()` re-hashes the file and refuses on
mismatch. Signing and deploying are different moments; the gap between them is exactly
when an evidence file gets "tidied up".

- **Edited after signing → DENY** (digest mismatch), including a reformat that preserves
  the meaning.
- **Moved or renamed after signing → DENY.** The ref records an absolute path so
  relocation cannot silently resolve elsewhere. This is a denial, not a warning. Note
  the path is `os.path.abspath`, not `realpath`: reaching the same file by an equivalent
  but differently-spelled path (mapped drive vs UNC, a junction) also denies. Fail-closed,
  but sign and deploy from the same shell to avoid the surprise.
- **Deleted after signing → DENY.**
- An artifact whose ref carries **no digest** is refused for `deploy` and `reconcile`.
  The pre-binding shape is not grandfathered.

## Which actions require evidence

| action | evidence required at signing | digest re-checked at use |
|---|---|---|
| `deploy` | **yes** | yes |
| `reconcile` | **yes**, approving the **target** SHA | yes |
| `rollback` | no | no |

`reconcile` writes new bytes to production, so it is gated exactly like `deploy`. Its
evidence must approve the SHA being converged **to** — not the one production currently
holds — and a stale file from the drifted identity's own gate round is refused.

`rollback` is exempt. It is the incident path, its artifact is meant to be minted in
advance (see the header of `sign_deploy_authorization.py`), and gating a recovery on
assembling a fresh seven-agent report lengthens outages. When evidence *is* supplied for
a rollback its digest is **recorded but never re-checked** — that is audit trail, not
tamper evidence. Do not describe it as protection.

---

## Use

One line — the operator shell on the production host is PowerShell, which does **not**
treat a trailing `\` as a line continuation. Pasted wrapped, argparse gets a stray `\`
and exits 2:

```powershell
python .claude/hooks/sign_deploy_authorization.py <sha> deploy Both --gate-evidence C:\PZ-secrets\gate-evidence\<sha>.json --ttl 60
```

Evidence is validated **before the signing key is loaded** — `validate_evidence()` is
called at the top of `sign_deploy_authorization.main()`, ahead of `_load_key()` — so an
operator who cannot produce a seven-agent GO for that exact SHA never reaches the key.
That ordering is pinned by
`test_evidence_is_validated_before_the_signing_key_is_loaded`.

Coverage: `service/tests/test_gate_evidence.py` — every field is mutated independently
and the refusal asserted, plus the signing and use-time integration paths.
