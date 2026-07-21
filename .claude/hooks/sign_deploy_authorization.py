"""OPERATOR TOOL — mint a signed deploy/rollback authorization artifact.

Deploy-PZ.ps1 refuses every production write without one of these. Without this tool
an operator would have to reverse-engineer the canonical body, the JSON schema, the
filename convention and the HMAC computation out of deploy_authorization.py, which
made a correctly fail-closed system effectively unusable.

THIS TOOL IS OPERATOR-ONLY. It reads the signing key, so it must run in the operator's
shell, never in an agent session. It never prints the key.

--------------------------------------------------------------------------------
ONE-TIME PROVISIONING (operator, once per machine)
--------------------------------------------------------------------------------
Choose a key location OUTSIDE this repository, generate a key, and export both vars:

    python -c "import secrets;print(secrets.token_hex(32))" > C:\\PZ-secrets\\deploy-auth.key
    setx PZ_DEPLOY_AUTH_KEY_FILE C:\\PZ-secrets\\deploy-auth.key
    setx PZ_DEPLOY_AUTH_DIR      C:\\PZ-secrets\\deploy-auth

    mkdir C:\\PZ-secrets\\deploy-auth

The key must NOT live in the repository, and must not be committed. An agent that can
read every tracked file still cannot sign an authorization.

--------------------------------------------------------------------------------
PER-DEPLOY (operator, after the 7-agent gate has approved a SHA)
--------------------------------------------------------------------------------
    python .claude/hooks/sign_deploy_authorization.py <sha> deploy Both --ttl 60

Then run the deploy with the SAME SHA:

    Deploy-PZ.ps1 -ReviewedSHA <sha>

ROLLBACK NEEDS ITS OWN ARTIFACT. Rollback is a production write and is authorized
separately. Mint it BEFORE you need it -- minting one mid-incident costs time:

    python .claude/hooks/sign_deploy_authorization.py <sha> rollback Both --ttl 1440

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy_authorization import (  # noqa: E402
    VALID_ACTIONS, VALID_SCOPES, _load_key, _store_dir, sign,
)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mint a signed deploy authorization (operator-only).")
    ap.add_argument("reviewed_sha", help="full 40-char SHA approved by the 7-agent gate")
    ap.add_argument("action", choices=VALID_ACTIONS)
    ap.add_argument("scope", choices=VALID_SCOPES)
    ap.add_argument("--ttl", type=int, default=60, help="validity in minutes (default 60)")
    ap.add_argument("--repository", default=os.environ.get("PZ_DEPLOY_AUTH_REPO", ""),
                    help="repository identity recorded in the signed body")
    ap.add_argument("--gate-evidence", default="",
                    help="reference to the 7-agent gate evidence (report path, PR comment URL)")
    args = ap.parse_args(argv)

    sha = args.reviewed_sha.strip().lower()
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        print("ERROR: reviewed_sha must be a full 40-character commit SHA")
        return 2

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
        "repository": args.repository,
        "gate_evidence_ref": args.gate_evidence,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=args.ttl)).isoformat(),
        "jti": str(uuid.uuid4()),
    }
    auth["signature"] = sign(auth, key)

    path = os.path.join(store, f"{sha}.{args.action}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(auth, fh, indent=2, sort_keys=True)

    print(f"Authorization written: {path}")
    print(f"  sha={sha[:12]} action={args.action} scope={args.scope} "
          f"ttl={args.ttl}m jti={auth['jti'][:8]} (single-use)")
    if not args.gate_evidence:
        print("  NOTE: no --gate-evidence recorded; the artifact does not reference the gate result.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
