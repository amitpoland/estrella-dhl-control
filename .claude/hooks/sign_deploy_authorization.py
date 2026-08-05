r"""OPERATOR TOOL — mint a signed deploy/rollback authorization artifact.

Deploy-PZ.ps1 refuses every production write without one of these. Without this tool
an operator would have to reverse-engineer the canonical body, the JSON schema, the
filename convention and the HMAC computation out of deploy_authorization.py, which
made a correctly fail-closed system effectively unusable.

THIS TOOL IS OPERATOR-ONLY. It reads the signing key, so it must run in the operator's
shell, never in an agent session. It never prints the key.

--------------------------------------------------------------------------------
ONE-TIME PROVISIONING (operator, once per machine)
--------------------------------------------------------------------------------
Choose a key location OUTSIDE this repository, generate a key, and export both vars.
These are PowerShell commands, run on the production host, IN THIS ORDER -- each mkdir
creates both levels, and the key write below fails with "could not find a part of the
path" if C:\PZ-secrets does not exist yet:

    mkdir C:\PZ-secrets\deploy-auth
    mkdir C:\PZ-secrets\gate-evidence
    python -c "import secrets;print(secrets.token_hex(32))" > C:\PZ-secrets\deploy-auth.key
    setx PZ_DEPLOY_AUTH_KEY_FILE C:\PZ-secrets\deploy-auth.key
    setx PZ_DEPLOY_AUTH_DIR      C:\PZ-secrets\deploy-auth
    $env:PZ_DEPLOY_AUTH_KEY_FILE = 'C:\PZ-secrets\deploy-auth.key'
    $env:PZ_DEPLOY_AUTH_DIR      = 'C:\PZ-secrets\deploy-auth'

`setx` writes the registry for FUTURE shells and does NOT touch the running session, so
without the two `$env:` lines the very next command in the same window fails with
"no signing key" and exit 2. The `setx` lines make it survive a reboot; the `$env:` lines
make it work now. (Opening a fresh PowerShell window instead is equally fine.)

The key file's ENCODING is irrelevant and must not be "cleaned up": `>` writes UTF-16LE
on PowerShell 5.1, and both the signer and the verifier read the key as raw bytes, so it
signs and verifies consistently. Rewriting that file in a different encoding changes the
key and silently invalidates every outstanding authorization as "signature invalid".

The second directory holds the gate evidence files the PER-DEPLOY step below reads.
Creating it here is not decoration: without it, an operator's very first evidence write
fails on a fresh machine with the same "could not find a part of the path" error.

The key must NOT live in the repository, and must not be committed. An agent that can
read every tracked file still cannot sign an authorization.

NOTE ON THE COMMANDS BELOW: run them from the deploy source checkout (C:\PZ-main on the
production host) -- the `.claude/hooks/...` paths are relative to the repository root.
Every command is written on a SINGLE line. The operator shell on
the production host is PowerShell, which does not treat a trailing backslash as a line
continuation -- a wrapped command pastes as two broken commands, and argparse exits 2 on
the stray argument.

--------------------------------------------------------------------------------
PER-DEPLOY (operator, after the 7-agent gate has approved a SHA)
--------------------------------------------------------------------------------
--gate-evidence is REQUIRED for deploy and reconcile. It is the path to the strict
JSON record of the seven-agent round for THIS sha -- schema, storage convention and
validation rules in .claude/contracts/seven-agent-evidence.md. It is validated before
the signing key is loaded, so an unapproved SHA never reaches the key:

    python .claude/hooks/sign_deploy_authorization.py <sha> deploy Both --gate-evidence C:\PZ-secrets\gate-evidence\<sha>.json --ttl 60

Do NOT edit, reformat, move or delete the evidence file after signing. Its SHA-256 is
recorded in the signed body and re-checked at deploy time; any change is a denial.

Then run the deploy with the SAME SHA:

    Deploy-PZ.ps1 -ReviewedSHA <sha>

ROLLBACK NEEDS ITS OWN ARTIFACT. Rollback is a production write and is authorized
separately. Mint it BEFORE you need it -- minting one mid-incident costs time:

    python .claude/hooks/sign_deploy_authorization.py <sha> rollback Both --ttl 1440

RECONCILE NEEDS BOTH SHAs. When production's bytes and its version marker disagree,
Deploy-PZ.ps1 -Reconcile repairs the marker, and its authorization is bound to the
ordered PAIR so an artifact minted for one drift cannot repair a different one. Pass
the identity production ACTUALLY holds as --from-sha:

    python .claude/hooks/sign_deploy_authorization.py <to-sha> reconcile Both --from-sha <proved-current-sha> --gate-evidence C:\PZ-secrets\gate-evidence\<to-sha>.json --ttl 60

    Deploy-PZ.ps1 -Reconcile -FromSha <proved-current-sha> -ToSha <to-sha>

Reconcile writes new bytes to production, so it needs evidence exactly as deploy does,
and that evidence must approve the TARGET sha -- not the identity production currently
holds. A gate report for the drifted SHA does not authorise converging away from it.

--from-sha is REQUIRED for reconcile and REFUSED for deploy/rollback: it is a signed
field, so a deploy artifact carrying one is a different operation shape and the
verifier denies it.

Artifacts are single-use: the jti is consumed on first successful use, so a repeat
deploy or a second rollback needs a freshly minted artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOKS_DIR not in sys.path:      # guarded: see deploy_authorization.py
    sys.path.insert(0, _HOOKS_DIR)
from deploy_authorization import (  # noqa: E402
    VALID_ACTIONS, VALID_SCOPES, _load_key, _store_dir, artifact_name, sign,
)
from gate_evidence import (  # noqa: E402
    MAX_VALIDITY, digest_file, format_ref, validate_evidence,
)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mint a signed deploy authorization (operator-only).")
    ap.add_argument("reviewed_sha", help="full 40-char SHA approved by the 7-agent gate")
    ap.add_argument("action", choices=VALID_ACTIONS)
    ap.add_argument("scope", choices=VALID_SCOPES)
    ap.add_argument("--ttl", type=int, default=60,
                    help="validity in minutes (default 60, maximum 1440 = 24h). The "
                         "artifact TTL is the only bound on the deploy window, because "
                         "evaluate() re-hashes the evidence but never re-validates it.")
    ap.add_argument("--repository", default=os.environ.get("PZ_DEPLOY_AUTH_REPO", ""),
                    help="repository identity recorded in the signed body")
    ap.add_argument("--gate-evidence", default="",
                    help="PATH to the 7-agent gate evidence file (strict JSON). REQUIRED "
                         "for deploy and reconcile: it is validated (all seven agents GO, "
                         "no unresolved blocker, target_sha == reviewed_sha, not expired) "
                         "and its SHA-256 is recorded in the signed body, so editing it "
                         "afterwards invalidates the authorization for those two actions.")
    ap.add_argument("--from-sha", default=None,
                    help="reconcile ONLY: the identity production actually holds right now, "
                         "proved against the runtime bytes. The signature covers this, so the "
                         "artifact authorises exactly one (from -> to) direction.")
    args = ap.parse_args(argv)

    sha = args.reviewed_sha.strip().lower()
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        print("ERROR: reviewed_sha must be a full 40-character commit SHA")
        return 2

    # The artifact TTL is the ONLY bound on the deploy window: evaluate() re-hashes the
    # evidence at use time but never re-runs validate_evidence, so the evidence rules --
    # including its own expiry and the 24h MAX_VALIDITY -- are enforced at signing time
    # only. An unbounded --ttl therefore let `--ttl 43200` mint a 30-day authorization
    # off a document the validator capped at 24 hours, while the contract described the
    # artifact TTL as "shorter". That was a safety word with nothing enforcing it -- the
    # identical defect this tooling fixed for evidence, sitting in the compensating
    # control. Capped at the same 24h ceiling; the documented rollback TTL (1440) is
    # exactly at it.
    max_ttl = int(MAX_VALIDITY.total_seconds() // 60)
    if args.ttl < 1:
        print(f"ERROR: --ttl must be at least 1 minute (got {args.ttl})")
        return 2
    if args.ttl > max_ttl:
        print(f"ERROR: --ttl {args.ttl} exceeds the {max_ttl}-minute maximum. The signed "
              f"artifact is the only bound on the deploy window, so it may not outlive "
              f"the {max_ttl}-minute ceiling the gate evidence itself is held to.")
        return 2

    # from_sha is a SIGNED field, so its presence defines the operation shape. Mint only
    # what the verifier will honour: reconcile is pair-bound and everything else must
    # carry no direction at all.
    from_sha = (args.from_sha or "").strip().lower() or None
    if args.action == "reconcile":
        if not from_sha:
            print("ERROR: reconcile requires --from-sha (the identity production actually "
                  "holds). Prove it against the runtime bytes first; if you do not know "
                  "it, do not guess -- an artifact minted for the wrong starting identity "
                  "authorises nothing and the gate will refuse it.")
            return 2
        if len(from_sha) != 40 or any(c not in "0123456789abcdef" for c in from_sha):
            print("ERROR: --from-sha must be a full 40-character commit SHA")
            return 2
        if from_sha == sha:
            print("ERROR: --from-sha and reviewed_sha are identical; nothing to reconcile")
            return 2
    elif from_sha:
        print(f"ERROR: --from-sha is only meaningful for reconcile, not '{args.action}'")
        return 2

    # Gate evidence is validated BEFORE the key is loaded: an operator who cannot
    # produce a seven-agent GO for this exact SHA should never reach the signing step.
    #
    # Required for deploy and reconcile -- the two actions that write new bytes to
    # production. NOT required for rollback: rollback is the incident path, its
    # artifact is meant to be minted in advance (see the header), and gating a
    # recovery on assembling a fresh seven-agent report is how an outage gets longer.
    evidence_ref = args.gate_evidence.strip()
    if args.action in ("deploy", "reconcile"):
        ok, reason, digest = validate_evidence(evidence_ref, sha)
        if not ok:
            print(f"ERROR: {reason}")
            print("       The 7-agent gate is the production approval authority. "
                  "Pass --gate-evidence <path-to-gate-report>; see "
                  ".claude/contracts/seven-agent-evidence.md for the required fields.")
            return 2
        print(f"  gate evidence: {reason}")
        evidence_ref = format_ref(os.path.abspath(evidence_ref), digest)
    elif evidence_ref:
        # Record a digest when evidence is supplied for a non-production action.
        #
        # This is tamper-RECORDED, not tamper-EVIDENT: deploy_authorization.evaluate()
        # re-checks the digest for deploy and reconcile only, so a rollback's digest is
        # never verified at use time. An earlier comment here claimed it was "still
        # tamper-evident", which was an uncited optimistic safety claim (Lesson Q rules
        # 1 and 6) — it described a check that does not run. The value is audit-trail
        # only: it says which bytes the operator held when signing.
        digest = digest_file(evidence_ref)
        if digest:
            evidence_ref = format_ref(os.path.abspath(evidence_ref), digest)

    key = _load_key()
    if not key:
        print("ERROR: no signing key. Set PZ_DEPLOY_AUTH_KEY_FILE (preferred) or "
              "PZ_DEPLOY_AUTH_KEY to a location OUTSIDE this repository. See the "
              "provisioning block at the top of this file.")
        return 2

    store = _store_dir()
    if not store:
        print("ERROR: PZ_DEPLOY_AUTH_DIR is not set (the authorization store, outside the repo)")
        return 2
    os.makedirs(store, exist_ok=True)

    now = datetime.now(timezone.utc)
    auth = {
        "reviewed_sha": sha,
        "action": args.action,
        "scope": args.scope,
        "from_sha": from_sha,
        "repository": args.repository,
        "gate_evidence_ref": evidence_ref,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=args.ttl)).isoformat(),
        "jti": str(uuid.uuid4()),
    }
    auth["signature"] = sign(auth, key)

    # The filename is derived by the same authority the verifier looks the artifact up
    # with; reconcile artifacts carry BOTH SHAs so a store listing shows the authorised
    # direction without opening every file.
    path = os.path.join(store, artifact_name(sha, args.action, from_sha))
    # Write-then-rename: a crash mid-write would otherwise leave a truncated artifact at
    # the exact path the verifier looks up. That is fail-closed today (the verifier
    # refuses unreadable JSON), but an authorization store should not contain a
    # half-written authorization at all.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(auth, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)

    print(f"Authorization written: {path}")
    direction = f" direction={from_sha[:12]}->{sha[:12]}" if from_sha else ""
    print(f"  sha={sha[:12]} action={args.action} scope={args.scope}{direction} "
          f"ttl={args.ttl}m jti={auth['jti'][:8]} (single-use)")
    if not evidence_ref:
        print("  NOTE: no --gate-evidence recorded; the artifact does not reference the gate result.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
