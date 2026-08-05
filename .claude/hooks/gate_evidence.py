"""Seven-agent gate evidence: a strict JSON authorization input.

WHY THIS EXISTS
---------------
`sign_deploy_authorization.py` has always accepted `--gate-evidence`, and
`gate_evidence_ref` has always been a SIGNED field. But it was free text -- a report
path or a PR comment URL -- that nothing read, nothing validated, and nothing bound to
the SHA being deployed. An operator could mint a fully valid authorization with
`--gate-evidence "looks fine to me"`, or citing a gate run for a different commit.

WHY JSON, AND NOT MARKDOWN
--------------------------
The first implementation parsed a hand-written Markdown report. Over three review
rounds the seven-agent gate found SIX distinct ways a human-visible BLOCK could be
laundered into a validated GO:

  1. a duplicate `AGENT:` block overriding an earlier BLOCK (last-wins);
  2. an agent-like bullet inside a NOTES section;
  3. a bare repeated STATUS/DISPOSITION pair with no second AGENT line;
  4. a near-miss agent name whose BLOCK was silently discarded;
  5. a verdict appearing before the first AGENT line (orphaned, dropped);
  6. a verdict written as a Markdown table row, invisible to the parser;
     plus first-wins `EXPIRES_AT` shadowing a genuine expiry.

Each was patched; the next round found the next one. That is not a run of bad luck, it
is the design. A tolerant parser strips decoration, accepts aliases, reconstructs record
boundaries, and SKIPS what it does not recognise -- so a human and the validator are not
guaranteed to be reading the same document. No finite list of patches closes that class.

This module therefore does not parse a human document at all. Evidence is strict JSON
with one schema and one meaning:

  * `json.loads` either parses or refuses -- no partial understanding;
  * duplicate keys are REFUSED via `object_pairs_hook` (stdlib json silently keeps the
    last one, which is precisely the last-wins defect that started this);
  * unknown fields are refused at both levels, so no field the validator never looks at
    can be introduced. NOTE the exact scope: `risks` is a KNOWN field whose CONTENTS are
    deliberately unvalidated (any JSON, any depth). A blocking finding transcribed into
    `risks` instead of `blockers` therefore validates -- that is intended (Lesson N:
    recorded risk is advisory, an unresolved blocker is not), but it means "nothing can
    hide" would be false. `risks` is exactly where free text lives;
  * agent names are matched EXACTLY -- no case folding, no separator equivalence, no
    `.md` tolerance. A near-miss is an unknown agent, and unknown agents are refused;
  * every status must be exactly "GO". There is no passing synonym to typo into.

Human-readable review stays Markdown. Production authorization evidence is JSON.

WHAT IT DOES NOT DO
-------------------
It does not replace the signed authorization. The HMAC artifact remains the thing that
permits a production write. Evidence gates SIGNING; the signature gates the DEPLOY. A
text file -- JSON or otherwise -- cannot be single-use, key-protected, or revoked.

HOW TAMPERING IS CAUGHT -- AND FOR WHICH ACTIONS
------------------------------------------------
The evidence file's SHA-256 is recorded inside `gate_evidence_ref`, which is already
covered by the authorization's HMAC. The digest is therefore signed WITHOUT adding a
signed field -- deliberately, because `deploy_authorization._SIGNED_FIELDS` warns that
changing the canonical body invalidates every previously minted artifact and must not be
done silently once a signer exists.

FOR `deploy` AND `reconcile` ONLY: `deploy_authorization.evaluate()` re-hashes the file
at use time, under `if action in ("deploy", "reconcile")`. Editing, moving, or deleting
the evidence after signing is a DENIAL, not a warning.

FOR `rollback` THERE IS NO SUCH CHECK. A rollback's recorded digest is audit trail -- it
says which bytes the operator held when signing -- and is never re-read. Do not describe
it as protection. (Stated explicitly because the unqualified version of the sentence
above was a Lesson Q rule 1+6 defect: an uncited safety claim, wrong in the permitting
direction, describing a stop that does not exist for one of the three actions.)

REF FORMAT
----------
    <absolute-path>@sha256:<64-hex>
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone

# The seven authorities named by CLAUDE.md's production deployment rule, one per
# `.claude/agents/deploy_*.md`. Pinned against those files by
# test_required_agents_matches_the_agent_files_on_disk -- a rename, addition or removal
# must fail a test rather than silently shrink the gate.
REQUIRED_AGENTS = frozenset({
    "deploy_git_diff_reviewer",
    "deploy_persistence_storage_reviewer",
    "deploy_backend_impact_reviewer",
    "deploy_security_reviewer",
    "deploy_qa_reviewer",
    "deploy_release_manager",
    "deploy_lead_coordinator",
})

SCHEMA_VERSION = 1

# Exact field sets. Unknown fields are refused rather than ignored: an ignored field is
# somewhere a reviewer's caveat can live while the validator sees approval.
_TOP_FIELDS = frozenset({
    "schema_version", "target_sha", "created_at", "expires_at", "agents", "lead_verdict",
})
_AGENT_FIELDS = frozenset({"agent", "status", "blockers", "risks"})

# One passing value. Not a set of synonyms -- every synonym is a token to typo into, and
# an unrecognised status must never read as approval.
_GO = "GO"

# A gate verdict is about a tree AND a moment. Beyond this the round has stopped
# describing the world it was taken in, so an unbounded window is refused rather than
# left to convention -- the contract's "hours, not days" was previously advice with no
# enforcement behind it, which is a safety property nobody was checking.
MAX_VALIDITY = timedelta(hours=24)

# Clocks disagree. A few minutes of skew must not refuse a genuine document, but a
# `created_at` hours in the future is a backdated or mis-generated file, not skew.
CLOCK_SKEW = timedelta(minutes=5)

_REF_RX = re.compile(r"\A(?P<path>.+)@sha256:(?P<digest>[0-9a-f]{64})\Z")
# `\Z`, not `$`: Python's `$` also matches immediately before a trailing newline, so
# `^[0-9a-f]{40}$` accepts "<40 hex>\n". Harmless today because the equality compare
# would then mismatch -- but a shape check that accepts a shape it names as invalid is
# a check you have to re-derive every time you read it.
_SHA_RX = re.compile(r"\A[0-9a-f]{40}\Z")


class _DuplicateKey(ValueError):
    pass


def _no_duplicate_keys(pairs):
    """object_pairs_hook that refuses duplicate keys.

    Stdlib json keeps the LAST value for a repeated key, silently. For authorization
    evidence that is the same last-wins defect the Markdown parser died of, one layer
    down: `{"status": "BLOCK", "status": "GO"}` would validate as GO.
    """
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise _DuplicateKey(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def digest_file(path):
    """SHA-256 of the file, or None if it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def format_ref(path, digest):
    return f"{path}@sha256:{digest}"


def parse_ref(ref):
    """(path, digest) from a signed gate_evidence_ref, or (ref, None) if unbound."""
    if not isinstance(ref, str):
        return ("", None)
    m = _REF_RX.match(ref.strip())
    if not m:
        return (ref.strip(), None)
    return (m.group("path"), m.group("digest"))


def _parse_ts(value, label):
    """(datetime, None) or (None, reason). Naive timestamps are read as UTC.

    A non-UTC offset is REFUSED. Not pedantry: offsets are the one place left where a
    human reader and the validator can read the same document differently. Given

        "created_at": "2026-08-05T12:00:00+12:00",
        "expires_at": "2026-08-05T12:00:00-11:00"

    a reader sees two identical wall-clock instants and expects the
    "expires_at is not after created_at" refusal. The validator resolves 00:00Z and
    23:00Z -- a 23-hour window, inside MAX_VALIDITY, ACCEPTED. Requiring UTC removes the
    divergence instead of documenting it, which is the same argument that turned the
    validity window from advice into MAX_VALIDITY.
    """
    if not isinstance(value, str):
        return (None, f"{label} must be a string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return (None, f"{label} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        return (dt.replace(tzinfo=timezone.utc), None)
    if dt.utcoffset() != timedelta(0):
        return (None, f"{label} must be UTC (offset +00:00, a trailing 'Z', or no "
                      f"offset at all); got {value!r}")
    return (dt, None)


def _check_agent(entry, index):
    """None if the entry is a well-formed GO, else a refusal reason."""
    if not isinstance(entry, dict):
        return f"agents[{index}] is not an object"

    fields = set(entry)
    missing = _AGENT_FIELDS - fields
    if missing:
        return f"agents[{index}] is missing field(s): {', '.join(sorted(missing))}"
    unknown = fields - _AGENT_FIELDS
    if unknown:
        return f"agents[{index}] has unknown field(s): {', '.join(sorted(unknown))}"

    name = entry["agent"]
    if not isinstance(name, str):
        return f"agents[{index}].agent must be a string"
    # Exact match. No normalisation: a near-miss is an unknown agent, and the caller
    # refuses unknown agents. Tolerance here is what let "deploy_security_reviewer
    # (round 1)" carry a BLOCK that was then discarded.
    if name not in REQUIRED_AGENTS:
        return f"unknown agent {name!r} (names must match exactly)"

    status = entry["status"]
    if status != _GO:
        return f"{name} status is {status!r}, not {_GO!r}"

    blockers = entry["blockers"]
    if not isinstance(blockers, list):
        return f"{name}.blockers must be a list"
    if blockers:
        return f"{name} reports {len(blockers)} unresolved blocker(s)"

    if not isinstance(entry["risks"], list):
        return f"{name}.risks must be a list"
    return None


def validate_evidence(path, target_sha, now=None):
    """(ok, reason, digest) for strict-JSON evidence approving exactly `target_sha`.

    Fail-closed throughout. `digest` is the SHA-256 of the bytes that were parsed, and
    is returned on every post-read refusal so a caller can record what it rejected.
    """
    now = now or datetime.now(timezone.utc)
    # A naive `now` from a caller would raise TypeError on the comparisons below --
    # the one hole in "fail closed throughout". Fill it rather than crash.
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if not isinstance(target_sha, str) or not _SHA_RX.match(target_sha.lower()):
        return (False, "target_sha is not a full 40-character commit SHA", None)
    if not path:
        return (False, "no gate evidence supplied", None)
    if not os.path.isfile(path):
        return (False, f"gate evidence file not found: {path}", None)

    # ONE read: hash exactly the bytes that get parsed. Two reads is a TOCTOU window in
    # which a swapped file binds a signature to bytes that were never validated.
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return (False, f"gate evidence unreadable: {path}", None)
    digest = hashlib.sha256(raw).hexdigest()

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return (False, "gate evidence is not valid UTF-8", digest)
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except _DuplicateKey as exc:
        return (False, f"gate evidence has a {exc}", digest)
    except ValueError as exc:
        return (False, f"gate evidence is not valid JSON: {exc}", digest)
    except (RecursionError, MemoryError):
        # Deeply nested JSON exhausts the decoder's recursion budget. RecursionError is
        # a RuntimeError, not a ValueError, so without this it propagates out of a
        # function whose contract is "fail closed throughout" -- fail-closed in effect,
        # since the caller aborts, but a traceback is not a refusal reason.
        #
        # MemoryError is here for Windows specifically: CPython compiles
        # _Py_CheckRecursiveCall with USE_STACKCHECK there, and PyOS_CheckStack() raises
        # MemoryError("Stack overflow") rather than RecursionError when the native stack
        # is the binding limit. Catching only RecursionError would leave exactly this
        # path open on exactly the platform that runs the deploy.
        return (False, "gate evidence is nested too deeply to parse", digest)

    if not isinstance(doc, dict):
        return (False, "gate evidence must be a JSON object", digest)

    fields = set(doc)
    missing = _TOP_FIELDS - fields
    if missing:
        return (False, "gate evidence is missing field(s): "
                       + ", ".join(sorted(missing)), digest)
    unknown = fields - _TOP_FIELDS
    if unknown:
        return (False, "gate evidence has unknown field(s): "
                       + ", ".join(sorted(unknown)), digest)

    version = doc["schema_version"]
    # `isinstance(True, int)` is True and `True == 1`, so a bare `!= SCHEMA_VERSION`
    # accepts `"schema_version": true`. Likewise `1.0 == 1`. Neither can reach a verdict
    # -- every approval-bearing field compares against a str -- but a module whose whole
    # thesis is "no tolerance" should not have a tolerated value anywhere in it.
    if isinstance(version, bool) or not isinstance(version, int):
        return (False, f"gate evidence schema_version must be an integer, got "
                       f"{version!r}", digest)
    if version != SCHEMA_VERSION:
        return (False, f"gate evidence schema_version is {version!r}, "
                       f"expected {SCHEMA_VERSION}", digest)

    declared = doc["target_sha"]
    if not isinstance(declared, str) or not _SHA_RX.match(declared):
        return (False, "gate evidence target_sha is not a full 40-character "
                       "lowercase commit SHA", digest)
    if declared != target_sha.lower():
        return (False, f"gate evidence approves {declared[:12]}, not "
                       f"{target_sha[:12].lower()} (evidence from a different gate run)",
                digest)

    created, err = _parse_ts(doc["created_at"], "created_at")
    if err:
        return (False, f"gate evidence {err}", digest)
    expires, err = _parse_ts(doc["expires_at"], "expires_at")
    if err:
        return (False, f"gate evidence {err}", digest)
    if expires <= created:
        return (False, "gate evidence expires_at is not after created_at", digest)
    if created > now + CLOCK_SKEW:
        # A gate round cannot have concluded in the future. Without this, `created_at`
        # is a field the validator reads and never constrains -- and a future-dated pair
        # is how an unbounded window gets written while still satisfying every other
        # rule.
        return (False, f"gate evidence created_at is in the future "
                       f"({created.isoformat()})", digest)
    if expires - created > MAX_VALIDITY:
        return (False, f"gate evidence is valid for "
                       f"{expires - created}, longer than the {MAX_VALIDITY} maximum",
                digest)
    if now >= expires:
        return (False, f"gate evidence expired at {expires.isoformat()}", digest)

    agents = doc["agents"]
    if not isinstance(agents, list):
        return (False, "gate evidence agents must be a list", digest)

    names = []
    for i, entry in enumerate(agents):
        reason = _check_agent(entry, i)
        if reason:
            return (False, f"gate evidence: {reason}", digest)
        names.append(entry["agent"])

    seen = set()
    dupes = sorted({n for n in names if n in seen or seen.add(n)})
    if dupes:
        return (False, "gate evidence declares more than one result for: "
                       + ", ".join(dupes), digest)

    absent = REQUIRED_AGENTS - set(names)
    if absent:
        return (False, "gate evidence missing agent result(s): "
                       + ", ".join(sorted(absent)), digest)
    # Count is implied by "no duplicates, no unknown names, none absent", but assert it
    # anyway: an eighth entry must never be able to ride along unexamined.
    if len(names) != len(REQUIRED_AGENTS):
        return (False, f"gate evidence declares {len(names)} agent results, "
                       f"expected exactly {len(REQUIRED_AGENTS)}", digest)

    if doc["lead_verdict"] != _GO:
        return (False, f"gate evidence lead_verdict is {doc['lead_verdict']!r}, "
                       f"not {_GO!r}", digest)

    return (True, f"seven-agent {_GO} for {declared[:12]}", digest)
