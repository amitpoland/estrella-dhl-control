"""Operator authorization for production deployment.

WHY THIS EXISTS
---------------
The first version of Deploy-PZ.ps1 gated production writes on the mere PRESENCE of
an environment variable, and its own comment claimed "the agent cannot derive it".
That claim was false: any non-empty string satisfied it, and an agent could set the
variable inside a wrapper script whose command line contained no token the
deploy-guard could match. Presence-only checks are not authorization.

This module replaces that with the same mechanism the repository already uses to
gate merges (`merge_authorization.py`): an HMAC-SHA256 signed artifact whose key
lives OUTSIDE the repository, in the operator/harness environment. An agent that can
read every file in this repository still cannot mint a valid authorization, because
the key is not in the repository.

PROPERTIES
----------
fail-closed      no flag / no key / no store / no artifact  -> DENY
auditable        every decision returns a reason string; artifacts are retained
SHA-bound        signature covers reviewed_sha; an artifact for SHA A cannot deploy B
action-bound     signature covers action (deploy|rollback|reconcile) and scope (App|Engine|Both)
pair-bound       for `reconcile` the signature ALSO covers from_sha, so an authorization
                 to converge FROM one runtime identity cannot be replayed against another
single-use       jti is consumed on first successful use
short-lived      expires_at is signed and enforced
never logged     the key is never read into a message; only decisions are surfaced
WhatIf-exempt    a true zero-write plan run does not call this at all

RECONCILE
---------
`reconcile` repairs a production tree whose version marker disagrees with its bytes.
It is strictly more dangerous than `deploy`, because it is the one mode that runs
against a runtime the identity gate has already refused. Its authorization is
therefore bound to the ORDERED PAIR (from_sha -> to_sha): a generic permission to
"reconcile" would let an operator-signed artifact be reused after the runtime had
drifted again, which is exactly the class of failure that produced the mislabelled
backup this mode exists to prevent. `from_sha` is a signed field, is required for
reconcile, must differ from reviewed_sha, and must be ABSENT for deploy/rollback.

CURRENT STATE: there is no deploy signer provisioned in this environment, so every
call returns DENY. That is the intended default. Arming it is an operator action -
see `MISSING PREREQUISITE` in the campaign report.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
from datetime import datetime, timezone

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOKS_DIR not in sys.path:      # guarded: a test suite that re-executes this module
    sys.path.insert(0, _HOOKS_DIR)  # per test would otherwise stack dozens of copies
from gate_evidence import digest_file, parse_ref  # noqa: E402

VALID_ACTIONS = ("deploy", "rollback", "reconcile")
VALID_SCOPES = ("App", "Engine", "Both")

# Fields covered by the signature. Anything outside this tuple is untrusted decoration.
#
# `from_sha` was added when `reconcile` was introduced. Adding a signed field changes the
# canonical body, so artifacts minted before this change no longer verify. That is a
# deliberate, disclosed break and it is safe here for one specific reason: no signer is
# provisioned and the authorization store is empty, so there is no artifact to invalidate.
# It must NOT be repeated silently once a signer exists - rotate the key instead.
_SIGNED_FIELDS = (
    "reviewed_sha",
    "action",
    "scope",
    "from_sha",
    "repository",
    "gate_evidence_ref",
    "issued_at",
    "expires_at",
    "jti",
)


def _is_sha(value):
    return (isinstance(value, str) and len(value) == 40
            and all(c in "0123456789abcdef" for c in value.lower()))


def artifact_name(reviewed_sha, action, from_sha=None):
    """Filename of the authorization artifact for this exact operation.

    Reconcile artifacts carry BOTH SHAs in the name so a store listing shows the
    authorised direction without opening and verifying every file."""
    if action == "reconcile":
        return f"{reviewed_sha}.reconcile.{from_sha}.json"
    return f"{reviewed_sha}.{action}.json"


def _load_key(env=None):
    """Signing key from a TRUSTED source outside the repo. None if unavailable."""
    env = env or os.environ
    key_file = env.get("PZ_DEPLOY_AUTH_KEY_FILE", "")
    if key_file and os.path.isfile(key_file):
        try:
            with open(key_file, "rb") as fh:
                raw = fh.read().strip()
            return raw or None
        except OSError:
            return None
    raw = env.get("PZ_DEPLOY_AUTH_KEY", "")
    return raw.encode("utf-8") if raw else None


def _store_dir(env=None):
    env = env or os.environ
    return env.get("PZ_DEPLOY_AUTH_DIR", "")


def canonical_body(auth):
    """Deterministic bytes over the signed fields (sorted, compact)."""
    body = {k: auth.get(k) for k in _SIGNED_FIELDS}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(auth, key):
    return hmac.new(key, canonical_body(auth), hashlib.sha256).hexdigest()


def _parse_iso(value):
    """Aware datetime, or None.

    A naive value is filled to UTC rather than returned as-is. Returning it naive meant
    the `now >= exp` comparison below raised TypeError out of a function documented
    "fail-closed -> DENY" and whose main() promises to print ALLOW/DENY with a reason:
    on that path it printed neither. Not agent-reachable (the HMAC check runs first), but
    gate_evidence closes this identical hole for its own caller and the sibling that
    gates the actual write should not be the one that crashes.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# A jti is a uuid4 from the signer. Constrained because it is used as a path
# component in _consume().
_JTI_RX = re.compile(r"\A[0-9a-fA-F-]{8,64}\Z")


def _consume(store, jti):
    """Mark jti used. Returns False if already consumed (replay)."""
    marker = os.path.join(store, "consumed", f"{jti}.used")
    if os.path.exists(marker):
        return False
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        # O_EXCL makes consumption atomic against a concurrent second use.
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            fh.write(datetime.now(timezone.utc).isoformat())
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def evaluate(reviewed_sha, action, scope, from_sha=None, env=None):
    """Return (decision, reason). 'allow' only for a fully valid, unexpired,
    unconsumed authorization bound to exactly this SHA + action + scope, and - for
    reconcile - to exactly this (from_sha -> reviewed_sha) direction."""
    env = env or os.environ

    if action not in VALID_ACTIONS:
        return ("deny", f"unknown action '{action}'")
    if scope not in VALID_SCOPES:
        return ("deny", f"unknown scope '{scope}'")
    if not _is_sha(reviewed_sha):
        return ("deny", "reviewed_sha is not a full 40-character commit SHA")

    # Argument shape is validated before the key is even loaded: a reconcile call with
    # no from_sha is a caller bug, and must never be able to fall through to a
    # deploy-shaped artifact lookup.
    if action == "reconcile":
        if not _is_sha(from_sha):
            return ("deny", "reconcile requires from_sha as a full 40-character commit SHA")
        if from_sha.lower() == reviewed_sha.lower():
            return ("deny", "reconcile from_sha and to_sha are identical; nothing to reconcile")
    elif from_sha is not None:
        return ("deny", f"from_sha is only meaningful for reconcile, not '{action}'")

    key = _load_key(env)
    if not key:
        return ("deny", "no trusted deploy signing key available "
                        "(PZ_DEPLOY_AUTH_KEY_FILE / PZ_DEPLOY_AUTH_KEY unset)")

    store = _store_dir(env)
    if not store or not os.path.isdir(store):
        return ("deny", "no authorization store configured (PZ_DEPLOY_AUTH_DIR)")

    path = os.path.join(store, artifact_name(reviewed_sha, action, from_sha))
    if not os.path.isfile(path):
        return ("deny", f"no authorization artifact for {reviewed_sha[:12]} {action}")

    try:
        with open(path, "r", encoding="utf-8") as fh:
            auth = json.load(fh)
    except (OSError, ValueError):
        return ("deny", "authorization artifact unreadable or malformed")
    if not isinstance(auth, dict):
        return ("deny", "authorization artifact is not an object")

    # Signature FIRST, constant-time. Never trust an unsigned field.
    sig = auth.get("signature", "")
    try:
        expected = sign(auth, key)
    except Exception:
        return ("deny", "authorization signing failed")
    if not (isinstance(sig, str) and hmac.compare_digest(sig, expected)):
        return ("deny", "authorization signature invalid")

    # Signed fields must match what is actually being attempted.
    if auth.get("reviewed_sha") != reviewed_sha:
        return ("deny", "authorization reviewed_sha mismatch")
    if auth.get("action") != action:
        return ("deny", "authorization action mismatch")
    if auth.get("scope") != scope:
        return ("deny", "authorization scope mismatch")

    # Direction binding. For reconcile the artifact authorises ONE ordered pair; for every
    # other action a present from_sha means the artifact was minted for a different
    # operation shape and must not be honoured.
    if action == "reconcile":
        if auth.get("from_sha") != from_sha:
            return ("deny", "authorization from_sha mismatch "
                            "(this artifact authorises a different starting identity)")
    elif auth.get("from_sha") is not None:
        return ("deny", f"authorization carries from_sha but action is '{action}'")

    # `repository` is signed but was not previously cross-checked: an artifact minted
    # for one repository would validate against another if the key were reused.
    expected_repo = env.get("PZ_DEPLOY_AUTH_REPO", "")
    if expected_repo and auth.get("repository") != expected_repo:
        return ("deny", "authorization repository mismatch")

    exp = _parse_iso(auth.get("expires_at"))
    iat = _parse_iso(auth.get("issued_at"))
    now = datetime.now(timezone.utc)
    if exp is None or iat is None:
        return ("deny", "authorization timestamps missing or malformed")
    if now >= exp:
        return ("deny", "authorization expired")
    if now < iat:
        return ("deny", "authorization not yet valid")

    # Gate evidence, re-checked at USE time. The digest is inside the signed
    # `gate_evidence_ref`, so the signature already proves which bytes the operator
    # signed for -- this proves the file still holds those bytes. Signing time and
    # deploy time are different moments, and the window between them is exactly when an
    # evidence file gets "tidied up".
    #
    # Enforced for deploy/reconcile only, matching the signer. A legacy artifact whose
    # ref carries no digest is refused for those actions rather than waved through:
    # accepting it would leave the pre-binding shape permanently available.
    if action in ("deploy", "reconcile"):
        ev_path, ev_digest = parse_ref(auth.get("gate_evidence_ref"))
        if not ev_digest:
            return ("deny", "authorization carries no digest-bound gate evidence "
                            "(re-mint it with --gate-evidence <path>)")
        actual = digest_file(ev_path)
        if actual is None:
            return ("deny", f"gate evidence no longer readable at {ev_path}")
        if not hmac.compare_digest(actual, ev_digest):
            return ("deny", "gate evidence has changed since the authorization was "
                            "signed (digest mismatch)")

    jti = auth.get("jti")
    if not isinstance(jti, str) or not jti:
        return ("deny", "authorization jti missing")
    # The jti becomes a PATH COMPONENT in _consume (store/consumed/<jti>.used), so a
    # non-empty check is not enough: "../x" would place the single-use marker outside the
    # store, and that marker IS the replay record. Minting one requires the signing key,
    # so this is not agent-reachable -- but a durable safety record should not depend on
    # the attacker not having a key. uuid4 is what the signer emits; pin that shape.
    if not _JTI_RX.match(jti):
        return ("deny", f"authorization jti is not a well-formed identifier: {jti!r}")
    if not _consume(store, jti):
        return ("deny", "authorization already consumed (replay refused)")

    if action == "reconcile":
        return ("allow", f"authorized for reconcile {from_sha[:12]} -> "
                         f"{reviewed_sha[:12]} /{scope}")
    return ("allow", f"authorized for {reviewed_sha[:12]} {action}/{scope}")


def main(argv):
    """CLI used by Deploy-PZ.ps1. Prints ALLOW/DENY + reason; exit 0 only on allow.
    The key is never printed."""
    if len(argv) not in (4, 5):
        print("DENY usage: deploy_authorization.py <reviewed_sha> <action> <scope> [from_sha]")
        return 2
    from_sha = argv[4] if len(argv) == 5 else None
    decision, reason = evaluate(argv[1], argv[2], argv[3], from_sha)
    print(f"{decision.upper()} {reason}")
    return 0 if decision == "allow" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
