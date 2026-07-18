#!/usr/bin/env python
"""merge_authorization.py — Council-authorized merge gate (fail-closed, default-OFF).

Replaces the pz-deploy-guard's UNCONDITIONAL `gh pr merge` denial with a narrowly
scoped, machine-verifiable authorization check. Imported by pz-deploy-guard.py.

TRUST MODEL (why this cannot be self-authorized by the candidate PR/agent):
  * The enabling flag, the signing key, and the authorization store all come from
    the OPERATOR/harness environment — NOT from any file inside the candidate
    branch and NOT from the candidate process alone.
  * An authorization is a JSON artifact carrying an HMAC-SHA256 signature over its
    canonical body, keyed by a secret the candidate does not possess. Setting the
    flag without the key yields NOTHING — the signature check fails → deny.
  * The authorized command MUST pin the head via `--match-head-commit <sha>`; the
    validator binds that SHA to the artifact's `head_sha` deterministically (no
    network call), and GitHub itself refuses the merge if the head moved.

DEFAULT BEHAVIOUR: with no flag / no key / no artifact (the current repository
state — there is no CI signer), every code path returns DENY. The merge denial is
NOT weakened. Fail closed on every missing/malformed/expired/mismatched input.

This module is PURE + testable: `evaluate_merge(command, ctx=...)` takes an
injectable context so the 15 authorization scenarios are deterministic.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone


# ── Protected paths: a PR touching ANY of these is NEVER autonomously mergeable ──
# (guard self-modification, the authorization mechanism itself, settings, prod
# tree, secrets, schema/migration, auth/security boundary). Matched as substrings
# against the artifact's signed changed-file list.
PROTECTED_PATH_MARKERS = (
    ".claude/hooks/pz-deploy-guard.py",
    ".claude/hooks/merge_authorization.py",
    ".claude/settings.json",
    ".claude/hooks/",                 # any hook change is guard-adjacent
    "docs/decisions/adr-council-authorized-merge",  # this ADR / policy
    "service/docs/production_deployment_rule",
    ".claude/contracts/governance-precedence",
    ".env",
    "secrets", "credentials", "core/security",   # bare "secrets" also matches a top-level secrets/ dir
    "service/app/auth/", "/auth/",               # JWT + session authority (operator-only)
)

# Markers in changed-file paths that indicate a protected DOMAIN / action —
# schema/migration/destructive DB + the fiscal / remote-write / identity authorities the
# ADR names as operator-merge-only (remote wFirma write, bank/currency, customs, Customer
# Master, carrier shipment creation). Over-matching here fails CLOSED (more operator merges),
# which is the intended direction. These do NOT match the ordinary proforma editing surface
# (e.g. routes_proforma.py) — only the fiscal-write authorities.
PROTECTED_DOMAIN_MARKERS = (
    "migration", "schema", "/alembic/",
    "wfirma",            # remote wFirma / fiscal write surface (routes_wfirma*, wfirma_*)
    "customs",           # customs authority
    "customer_master",   # Customer Master authority
    "carrier/",          # carrier shipment authority (booking / creation)
    "company_account",   # bank / currency-mapping authority
)

# tests that EXCLUSIVELY validate the guard must not be auto-merged either.
GUARD_TEST_MARKERS = (
    "test_council_merge_guard", "test_merge_authorization", "test_pz_deploy_guard",
)

PERMITTED_MERGE_METHODS = ("squash",)   # first implementation: squash only
_HEX40 = re.compile(r"^[0-9a-f]{40}$")

# The hook evaluates the WHOLE shell command string once. An authorized merge must be a
# LONE `gh pr merge` invocation — never chained with a second command. Otherwise
# `gh pr merge <authorized> && gh pr merge <unauthorized>` (or `&& rm -rf ...`) would run
# the whole line under one authorization. Reject any shell composition / metacharacter and
# any command carrying more than one `gh pr merge <n>`.
_SHELL_CONTROL_RX = re.compile(r"(&&|\|\||;|\||`|\$\(|>|<|\n|\r|&)")
_MERGE_INVOCATION_RX = re.compile(r"gh\s+pr\s+merge\s+\d+")


def _has_unsafe_command_composition(command):
    if _SHELL_CONTROL_RX.search(command):
        return True
    if len(_MERGE_INVOCATION_RX.findall(command.lower())) != 1:
        return True
    return False


class MergeContext:
    """Injectable trust inputs. Production defaults read the OPERATOR/harness
    environment and a store OUTSIDE the repo; tests inject fakes."""

    def __init__(self, *, enabled=None, key=None, repository=None,
                 load_authorization=None, is_consumed=None, mark_consumed=None,
                 now=None):
        env = os.environ
        # Flag: operator/harness-set. Anything other than exactly "1" = OFF.
        self.enabled = (enabled if enabled is not None
                        else env.get("PZ_AUTONOMOUS_MERGE_ENABLED", "") == "1")
        self.key = key if key is not None else _load_key_from_env(env)
        self.repository = (repository if repository is not None
                           else env.get("PZ_MERGE_AUTH_REPO", ""))
        self._load_authorization = load_authorization or _default_load_authorization
        self._is_consumed = is_consumed or _default_is_consumed
        self._mark_consumed = mark_consumed or _default_mark_consumed
        self.now = now or (lambda: datetime.now(timezone.utc))

    def load_authorization(self, pr):
        return self._load_authorization(pr)

    def is_consumed(self, jti):
        return self._is_consumed(jti)

    def mark_consumed(self, jti):
        return self._mark_consumed(jti)


def _load_key_from_env(env):
    """Signing key from a TRUSTED source outside the repo. None if unavailable."""
    key_file = env.get("PZ_MERGE_AUTH_KEY_FILE", "")
    if key_file and os.path.isfile(key_file):
        try:
            with open(key_file, "rb") as fh:
                return fh.read().strip()
        except Exception:
            return None
    raw = env.get("PZ_MERGE_AUTH_KEY", "")
    return raw.encode("utf-8") if raw else None


def _auth_dir(env=None):
    env = env or os.environ
    return env.get("PZ_MERGE_AUTH_DIR", "")   # empty → no store → deny


def _default_load_authorization(pr):
    d = _auth_dir()
    if not d or not os.path.isdir(d):
        return None
    path = os.path.join(d, f"pr-{int(pr)}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _consumed_path():
    d = _auth_dir()
    return os.path.join(d, "consumed.txt") if d else ""


def _default_is_consumed(jti):
    p = _consumed_path()
    if not p or not os.path.isfile(p):
        return False
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return jti in {ln.strip() for ln in fh}
    except Exception:
        return True   # fail closed: unreadable consumed-store ⇒ treat as consumed


def _default_mark_consumed(jti):
    # NOTE: is_consumed()→mark_consumed() is not atomic. This is safe under the current
    # invariant — the guard is a single-process hook invoked serially per tool use, so two
    # concurrent evaluations of the same jti cannot occur. A future multi-writer signer must
    # make consume atomic (e.g. O_CREAT|O_EXCL lock per jti) before relying on this store.
    p = _consumed_path()
    if not p:
        # No store configured — cannot record consumption; raise so evaluate_merge
        # fails closed rather than allowing a replayable authorization.
        raise RuntimeError("no consumed-token store configured")
    # Let write failures propagate: evaluate_merge denies if the token can't persist.
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(jti + "\n")


# ── canonical signing body + signature ────────────────────────────────────────
_SIGNED_FIELDS = (
    "version", "authorization_id", "repository", "pr_number", "head_sha",
    "base_sha", "changed_files_digest", "council_verdict", "focused_tests_ref",
    "regression_tests_ref", "merge_method", "issued_at", "expires_at",
)


def canonical_body(auth):
    """Deterministic bytes over the signed fields (sorted, compact)."""
    body = {k: auth.get(k) for k in _SIGNED_FIELDS}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(auth, key):
    return hmac.new(key, canonical_body(auth), hashlib.sha256).hexdigest()


def compute_changed_files_digest(files):
    joined = "\n".join(sorted(f.strip() for f in files if f.strip()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ── command parsing ───────────────────────────────────────────────────────────
def parse_merge_command(command):
    """Return {pr, method, match_head} for a `gh pr merge` command, else None.
    Only the exact repo-standard shape is recognised."""
    low = command.strip()
    m = re.search(r"gh\s+pr\s+merge\s+(\d+)\b", low)
    if not m:
        return None
    pr = int(m.group(1))
    method = None
    if re.search(r"--squash\b", low):
        method = "squash"
    elif re.search(r"--merge\b", low):
        method = "merge"
    elif re.search(r"--rebase\b", low):
        method = "rebase"
    mh = re.search(r"--match-head-commit[= ]([0-9a-fA-F]{40})", low)
    match_head = mh.group(1).lower() if mh else None
    admin = re.search(r"--admin\b", low) is not None
    return {"pr": pr, "method": method, "match_head": match_head, "admin": admin}


# ── the validator (fail-closed) ───────────────────────────────────────────────
def _protected_files(files):
    hits = []
    for f in files:
        fl = f.lower().replace("\\", "/")
        if any(m in fl for m in PROTECTED_PATH_MARKERS):
            hits.append(f)
        elif any(m in fl for m in PROTECTED_DOMAIN_MARKERS):
            hits.append(f)
        elif any(m in fl for m in GUARD_TEST_MARKERS):
            hits.append(f)
    return hits


def evaluate_merge(command, ctx=None):
    """Return ('allow'|'deny', reason). Deny on ANY missing/invalid/mismatched
    input. 'allow' ONLY for a fully-authorized, unexpired, unconsumed, squash
    merge of the exact PR+head with no protected files."""
    ctx = ctx or MergeContext()

    if not ctx.enabled:
        return ("deny", "autonomous merge disabled (default-off; operator-only)")

    if _has_unsafe_command_composition(command):
        return ("deny", "compound or shell-chained merge command not permitted")

    parsed = parse_merge_command(command)
    if not parsed:
        return ("deny", "unrecognised merge command shape")
    if parsed["admin"]:
        return ("deny", "--admin bypass is never permitted")
    if parsed["method"] not in PERMITTED_MERGE_METHODS:
        return ("deny", "only repository-standard squash merge is permitted")
    if not parsed["match_head"]:
        return ("deny", "authorized merge must pin head via --match-head-commit")

    if not ctx.key:
        return ("deny", "no trusted signing key available")
    if not ctx.repository:
        return ("deny", "no trusted repository identity configured")

    auth = ctx.load_authorization(parsed["pr"])
    if not isinstance(auth, dict):
        return ("deny", "no authorization artifact for this PR")

    # signature FIRST (constant-time) — never trust unsigned fields.
    sig = auth.get("signature", "")
    try:
        expected = sign(auth, ctx.key)
    except Exception:
        return ("deny", "authorization signing failed")
    if not (isinstance(sig, str) and hmac.compare_digest(sig, expected)):
        return ("deny", "authorization signature invalid")

    if auth.get("version") != "1":
        return ("deny", "unsupported authorization version")
    if auth.get("repository") != ctx.repository:
        return ("deny", "authorization repository mismatch")
    try:
        artifact_pr = int(auth.get("pr_number", -1))
    except (TypeError, ValueError):
        return ("deny", "authorization PR number malformed")
    if artifact_pr != parsed["pr"]:
        return ("deny", "authorization PR mismatch")
    if auth.get("merge_method") not in PERMITTED_MERGE_METHODS:
        return ("deny", "authorization merge method not permitted")

    head = str(auth.get("head_sha", "")).lower()
    if not _HEX40.match(head):
        return ("deny", "authorization head_sha malformed")
    if head != parsed["match_head"]:
        return ("deny", "PR head changed since review (head SHA mismatch)")

    if auth.get("council_verdict") != "PASS":
        return ("deny", "council verdict is not PASS")
    if not auth.get("focused_tests_ref") or not auth.get("regression_tests_ref"):
        return ("deny", "missing test-result references")

    # time window
    now = ctx.now()
    try:
        iat = _parse_iso(auth.get("issued_at"))
        exp = _parse_iso(auth.get("expires_at"))
    except Exception:
        return ("deny", "authorization timestamps malformed")
    if not (iat <= now < exp):
        return ("deny", "authorization expired or not yet valid")

    jti = auth.get("authorization_id", "")
    if not jti:
        return ("deny", "authorization id missing")
    try:
        already_consumed = ctx.is_consumed(jti)
    except Exception:
        return ("deny", "consumed-token store unreadable")
    if already_consumed:
        return ("deny", "authorization already consumed (replay blocked)")

    # protected files / domains / guard self-modification — from the SIGNED list
    files = auth.get("changed_files") or []
    if not isinstance(files, list) or not files:
        return ("deny", "authorization changed-file list missing")
    if compute_changed_files_digest(files) != auth.get("changed_files_digest"):
        return ("deny", "changed-file digest mismatch")
    prot = _protected_files(files)
    if prot:
        return ("deny", f"protected file(s) present — operator-only: {prot[:3]}")

    # all gates pass → consume then allow. Fail CLOSED if the consumed token
    # cannot be durably persisted (else the same artifact could replay).
    try:
        ctx.mark_consumed(jti)
    except Exception:
        return ("deny", "failed to persist consumed token — replay safety not guaranteed")
    return ("allow", f"council-authorized squash merge of PR #{parsed['pr']}")


def _parse_iso(s):
    if not isinstance(s, str) or not s:
        raise ValueError("empty timestamp")
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
