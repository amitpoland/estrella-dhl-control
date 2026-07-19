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
action-bound     signature covers action (deploy|rollback) and scope (App|Engine|Both)
single-use       jti is consumed on first successful use
short-lived      expires_at is signed and enforced
never logged     the key is never read into a message; only decisions are surfaced
WhatIf-exempt    a true zero-write plan run does not call this at all

CURRENT STATE: there is no deploy signer provisioned in this environment, so every
call returns DENY. That is the intended default. Arming it is an operator action -
see `MISSING PREREQUISITE` in the campaign report.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone

VALID_ACTIONS = ("deploy", "rollback")
VALID_SCOPES = ("App", "Engine", "Both")

# Fields covered by the signature. Anything outside this tuple is untrusted decoration.
_SIGNED_FIELDS = (
    "reviewed_sha",
    "action",
    "scope",
    "repository",
    "gate_evidence_ref",
    "issued_at",
    "expires_at",
    "jti",
)


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
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def evaluate(reviewed_sha, action, scope, env=None):
    """Return (decision, reason). 'allow' only for a fully valid, unexpired,
    unconsumed authorization bound to exactly this SHA + action + scope."""
    env = env or os.environ

    if action not in VALID_ACTIONS:
        return ("deny", f"unknown action '{action}'")
    if scope not in VALID_SCOPES:
        return ("deny", f"unknown scope '{scope}'")
    if not (isinstance(reviewed_sha, str) and len(reviewed_sha) == 40
            and all(c in "0123456789abcdef" for c in reviewed_sha.lower())):
        return ("deny", "reviewed_sha is not a full 40-character commit SHA")

    key = _load_key(env)
    if not key:
        return ("deny", "no trusted deploy signing key available "
                        "(PZ_DEPLOY_AUTH_KEY_FILE / PZ_DEPLOY_AUTH_KEY unset)")

    store = _store_dir(env)
    if not store or not os.path.isdir(store):
        return ("deny", "no authorization store configured (PZ_DEPLOY_AUTH_DIR)")

    path = os.path.join(store, f"{reviewed_sha}.{action}.json")
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

    exp = _parse_iso(auth.get("expires_at"))
    iat = _parse_iso(auth.get("issued_at"))
    now = datetime.now(timezone.utc)
    if exp is None or iat is None:
        return ("deny", "authorization timestamps missing or malformed")
    if now >= exp:
        return ("deny", "authorization expired")
    if now < iat:
        return ("deny", "authorization not yet valid")

    jti = auth.get("jti")
    if not isinstance(jti, str) or not jti:
        return ("deny", "authorization jti missing")
    if not _consume(store, jti):
        return ("deny", "authorization already consumed (replay refused)")

    return ("allow", f"authorized for {reviewed_sha[:12]} {action}/{scope}")


def main(argv):
    """CLI used by Deploy-PZ.ps1. Prints ALLOW/DENY + reason; exit 0 only on allow.
    The key is never printed."""
    if len(argv) != 4:
        print("DENY usage: deploy_authorization.py <reviewed_sha> <action> <scope>")
        return 2
    decision, reason = evaluate(argv[1], argv[2], argv[3])
    print(f"{decision.upper()} {reason}")
    return 0 if decision == "allow" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
