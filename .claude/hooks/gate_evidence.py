"""Seven-agent gate evidence: parse, validate, and bind it to a target SHA.

WHY THIS EXISTS
---------------
`sign_deploy_authorization.py` has always accepted `--gate-evidence`, and
`gate_evidence_ref` has always been a SIGNED field. But it was free text -- a report
path or a PR comment URL -- that nothing read, nothing validated, and nothing bound to
the SHA being deployed. An operator could mint a fully valid authorization with
`--gate-evidence "looks fine to me"`, or with a reference to a gate run for a different
commit, and every downstream check would pass.

That is the shape this module closes. The seven-agent gate is the production approval
authority (CLAUDE.md, "Production deployment rule"); this makes its verdict a
machine-checkable precondition of signing rather than a note in a field.

WHAT IT DOES NOT DO
-------------------
It does not replace the signed authorization. The HMAC artifact remains the thing that
actually permits a production write. Evidence gates SIGNING; the signature gates the
DEPLOY. Making a text file the gate on its own would be strictly weaker than what this
repository already has: an operator-editable file cannot be single-use, cannot be
key-protected, and cannot be revoked.

HOW TAMPERING IS CAUGHT
-----------------------
The evidence file's SHA-256 is recorded inside `gate_evidence_ref`, which is already
covered by the authorization's HMAC. So the digest is signed without adding a signed
field -- deliberately, because `deploy_authorization._SIGNED_FIELDS` carries an explicit
warning that changing the canonical body invalidates every previously minted artifact
and must not be done silently once a signer exists. Reusing the existing field keeps
this change compatible with any artifact already in an operator's store.

At verify time the file is re-hashed. Edit the evidence after signing and the digest no
longer matches, so the authorization is refused.

REF FORMAT
----------
    <path>@sha256:<64-hex>

`path` is recorded for the audit trail. The digest is what is enforced: a moved or
renamed evidence file is a warning, a changed one is a denial.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone

# The seven agents named by CLAUDE.md's production deployment rule. All seven must
# report; a gate that ran six is not the gate this repository defines.
REQUIRED_AGENTS = (
    "deploy_lead_coordinator",
    "deploy_git_diff_reviewer",
    "deploy_backend_impact_reviewer",
    "deploy_persistence_storage_reviewer",
    "deploy_security_reviewer",
    "deploy_qa_reviewer",
    "deploy_release_manager",
)

# Per-agent verdicts, from .claude/contracts/gate_output_contract.md.
_PASSING_STATUS = ("CLEAR", "PASS", "GO")
_BLOCKING_STATUS = ("HOLD", "BLOCK", "FAIL")

_REF_RX = re.compile(r"^(?P<path>.+)@sha256:(?P<digest>[0-9a-f]{64})$")
_SHA_RX = re.compile(r"^[0-9a-f]{40}$")

# Sentinel: the document declares more than one distinct target SHA.
_CONFLICT = "CONFLICT"

# Tolerated spellings of the agent name. The gate contract writes `AGENT: <agent_name>`;
# agent files are kebab-case on disk and snake_case in CLAUDE.md, and operators
# transcribe both.
def _normalise_agent(name):
    return name.strip().lower().replace("-", "_").removesuffix(".md")


def digest_file(path):
    """SHA-256 of the evidence file, or None if it cannot be read."""
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
    """(path, digest) from a signed gate_evidence_ref, or (ref, None) if unbound.

    A legacy free-text ref returns digest=None. Callers decide whether that is
    acceptable; `evaluate` refuses it for production actions.
    """
    if not isinstance(ref, str):
        return ("", None)
    m = _REF_RX.match(ref.strip())
    if not m:
        return (ref.strip(), None)
    return (m.group("path"), m.group("digest"))


def parse_evidence(text):
    """Agent blocks from a gate evidence document.

    Deliberately tolerant about layout and strict about content. Evidence is assembled
    by a human from seven agent reports, so it arrives with varying headings, markdown
    fences and blockquotes. What must be unambiguous is which agent said what, and
    whether any of them blocked.

    Returns {normalised_agent_name: {"status", "disposition", "duplicate"}}.

    AN AGENT MAY REPORT ONCE. Records were previously last-wins, which made the
    document layout a laundering vector: a second `AGENT: x` block later in the file
    silently overwrote an earlier `STATUS: BLOCK`, and because decoration is stripped
    before parsing, a bullet inside a NOTES section (`  - AGENT: x`) was indistinguishable
    from a real verdict block. Both were confirmed to launder a BLOCK into a GO.

    The digest binding cannot catch this -- it proves the file did not change after
    signing, not that the file says what it appears to say. So a repeated agent is
    recorded as `duplicate` and refused by validate_evidence(), rather than resolved.
    Refusing is the only safe resolution: first-wins would silently drop a later BLOCK,
    and last-wins is the defect itself.
    """
    agents = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip().lstrip(">").strip()
        line = line.lstrip("#*-` ").strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().strip("`*_ ").upper()
        value = value.strip().strip("`*_").strip()
        if key == "AGENT" and value:
            current = _normalise_agent(value)
            if current in agents:
                agents[current]["duplicate"] = True
                current = None          # ignore every field of the repeat block
            else:
                agents[current] = {"status": "", "disposition": "", "duplicate": False}
        elif current and key == "STATUS" and value:
            agents[current]["status"] = value.split()[0].upper()
        elif current and key == "DISPOSITION" and value:
            agents[current]["disposition"] = value.split(":")[0].strip().upper()
    return agents


def _find_target_sha(text):
    """The full 40-char SHA the evidence declares it approved, or "" / CONFLICT.

    Required and explicit. A gate report that does not name its target cannot be bound
    to one, and inferring the SHA from context is exactly how a verdict gets attached to
    the wrong revision (Lesson Q rule 7).

    EVERY declaration is collected, not the first. This was first-wins across three
    aliases, which was a SHA-binding bypass: evidence genuinely approving commit A
    validated for commit B if a single line `APPROVED_SHA: B` was prepended, because the
    first match bound and the seven verdicts below were never cross-checked against it.
    That defeats the property this whole module exists to enforce, so a document
    declaring more than one distinct target is refused rather than resolved.
    """
    found = []
    for raw in text.splitlines():
        line = raw.strip().lstrip(">").strip().lstrip("#*-` ").strip()
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if key.strip().strip("`*_ ").upper().replace(" ", "_") in (
                "TARGET_SHA", "REVIEWED_SHA", "APPROVED_SHA"):
            candidate = value.strip().strip("`*_").strip().lower()
            if not _SHA_RX.match(candidate):
                return ""      # present but malformed: do not fall through to a guess
            found.append(candidate)
    if not found:
        return ""
    if len(set(found)) > 1:
        return _CONFLICT
    return found[0]


def _find_expiry(text):
    for raw in text.splitlines():
        line = raw.strip().lstrip(">").strip().lstrip("#*-` ").strip()
        key, sep, value = line.partition(":")
        if sep and key.strip().strip("`*_ ").upper().replace(" ", "_") in (
                "EXPIRES_AT", "VALID_UNTIL"):
            try:
                return datetime.fromisoformat(
                    value.strip().strip("`*_").strip().replace("Z", "+00:00"))
            except ValueError:
                return False   # present but malformed -> refuse, never ignore
    return None                # absent -> no expiry claimed


def validate_evidence(path, target_sha, now=None):
    """(ok, reason, digest) for evidence approving exactly `target_sha`.

    Fail-closed throughout: anything unreadable, unparseable, incomplete, blocked,
    expired, or bound to a different SHA is a refusal, never a warning.
    """
    now = now or datetime.now(timezone.utc)

    if not _SHA_RX.match((target_sha or "").lower()):
        return (False, "target_sha is not a full 40-character commit SHA", None)
    if not path:
        return (False, "no gate evidence supplied", None)
    if not os.path.isfile(path):
        return (False, f"gate evidence file not found: {path}", None)

    # ONE read. Hash exactly the bytes that get parsed: digest_file() plus a separate
    # text read was a TOCTOU window in which a file swapped between the two calls would
    # bind the signature to bytes that were never validated, then pass the use-time
    # digest check once restored.
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return (False, f"gate evidence unreadable: {path}", None)
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8", errors="replace")

    declared = _find_target_sha(text)
    if declared == _CONFLICT:
        return (False, "gate evidence declares more than one distinct target SHA "
                       "(TARGET_SHA / REVIEWED_SHA / APPROVED_SHA disagree); refusing "
                       "rather than choosing one", digest)
    if not declared:
        return (False, "gate evidence declares no TARGET_SHA (a verdict with no named "
                       "revision cannot be bound to one)", digest)
    if declared != target_sha.lower():
        return (False, f"gate evidence approves {declared[:12]}, not {target_sha[:12]} "
                       "(evidence from a different gate run)", digest)

    expiry = _find_expiry(text)
    if expiry is False:
        return (False, "gate evidence EXPIRES_AT is malformed", digest)
    if expiry is not None:
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if now >= expiry:
            return (False, f"gate evidence expired at {expiry.isoformat()}", digest)

    agents = parse_evidence(text)
    missing = [a for a in REQUIRED_AGENTS if a not in agents]
    if missing:
        return (False, "gate evidence missing agent result(s): " + ", ".join(missing), digest)

    # A repeated agent block is refused, never resolved -- see parse_evidence().
    repeated = sorted(a for a, rec in agents.items() if rec.get("duplicate"))
    if repeated:
        return (False, "gate evidence declares more than one result for: "
                       + ", ".join(repeated)
                       + " (an agent reports once; a repeated block cannot be "
                         "distinguished from a laundered verdict)", digest)

    blocked = []
    for name in REQUIRED_AGENTS:
        rec = agents[name]
        status = rec.get("status", "")
        disp = rec.get("disposition", "")
        if status in _BLOCKING_STATUS or disp in _BLOCKING_STATUS:
            blocked.append(f"{name}={status or disp}")
        elif status not in _PASSING_STATUS:
            blocked.append(f"{name}=unrecognised status '{status}'")
    if blocked:
        return (False, "gate evidence carries unresolved blocker(s): " + ", ".join(blocked), digest)

    return (True, f"seven-agent GO for {target_sha[:12]}", digest)
