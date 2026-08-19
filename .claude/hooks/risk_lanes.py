"""Risk-lane classifier for the delivery pipeline.

WHAT THIS IS
------------
A pure, side-effect-free mapping from *changed file paths* to a delivery lane:

    L0  non-runtime      docs, tests, CI, reports, state files
    L1  standard runtime ordinary application change
    L2  high risk        the repository's own Block/sensitive classes
    BLOCKED              a path on the forbidden-paths blocklist

WHAT THIS IS NOT
----------------
This module has **no authority**. It answers "how much ceremony does this change
need?"  It never answers "may this deploy?"  Deployment authorization remains
solely with ``deploy_authorization.py`` (HMAC-signed, SHA-bound, single-use).
Exit status 0 from anything in this module means *classification succeeded*, and
never *permission granted*.

SOURCES (this module invents no taxonomy of its own)
----------------------------------------------------
* Runtime-payload membership -- ``.claude/deploy/windows_prod_v2.json``
  (``source_app`` + the 16 ``engine_files``), the declared SOLE configuration
  authority.  CLAUDE.md "Runtime payload" defines a gate verdict as binding to
  exactly this set.
* File risk classes -- ``.claude/agents/deploy_git_diff_reviewer.md`` already
  declares SAFE_CODE / CONFIG_RISK / DB_SCHEMA / STORAGE_WRITE / ROUTE_API /
  AUTH_SECURITY / FORBIDDEN_PATH / ENGINE_CORE / TEST_ONLY / DOCS_ONLY.  Lanes
  are a mapping over those existing classes.
* Sensitive-change list -- CLAUDE.md OPERATING MODEL mode 3.
* Forbidden paths -- ``.claude/contracts/forbidden-paths.md``.
* Lesson J -- root-level engine files deploy via a SEPARATE sync.

FAIL-CLOSED
-----------
If the configuration authority cannot be read, every path classifies L2 with
reason ``config-unavailable``.  Degradation raises ceremony, never lowers it.
"""

from __future__ import annotations

import json
import os
import posixpath
import re

LANE_L0 = "L0"
LANE_L1 = "L1"
LANE_L2 = "L2"
LANE_BLOCKED = "BLOCKED"

# Ordering used for "highest lane wins" on a mixed changeset.
LANE_ORDER = {LANE_L0: 0, LANE_L1: 1, LANE_L2: 2, LANE_BLOCKED: 3}

CONFIG_RELPATH = ".claude/deploy/windows_prod_v2.json"


# --------------------------------------------------------------------------
# repository / configuration discovery
# --------------------------------------------------------------------------

def repo_root(start=None):
    """Walk up from *start* until the deploy configuration authority is found."""
    here = os.path.abspath(start or os.path.dirname(os.path.abspath(__file__)))
    while True:
        if os.path.isfile(os.path.join(here, CONFIG_RELPATH.replace("/", os.sep))):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def load_config(root=None):
    """Return (config_dict, error_string). Never raises."""
    root = root or repo_root()
    if not root:
        return None, "repo root not found (no %s)" % CONFIG_RELPATH
    path = os.path.join(root, CONFIG_RELPATH.replace("/", os.sep))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as exc:  # unreadable / malformed -> fail closed upstream
        return None, "%s: %s" % (type(exc).__name__, exc)


def _norm(path):
    """Repo-relative, forward-slashed, lower-cased."""
    p = str(path).strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return posixpath.normpath(p).lower() if p else ""


def _app_prefix(config):
    """Runtime app tree as a repo-relative prefix, derived from source_app."""
    src = _norm(config.get("source_app", ""))
    root = _norm(config.get("source_root", ""))
    if src and root and src.startswith(root):
        rel = src[len(root):].strip("/")
        if rel:
            return rel + "/"
    return "service/app/"


def _engine_names(config):
    return set(_norm(n) for n in config.get("engine_files", []) if n)


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

# .claude/contracts/forbidden-paths.md, relative-path patterns only.
_FORBIDDEN = (
    (re.compile(r"(^|/)\.env($|\.)"), "credentials"),
    (re.compile(r"^storage/"), "production data"),
    (re.compile(r"^outputs/"), "production outputs"),
    (re.compile(r"^logs/"), "production logs"),
    (re.compile(r"\.db$"), "database file"),
    (re.compile(r"^cloudflared/"), "tunnel config"),
)

# Paths that change the safety system itself.  merge_authorization.py already
# treats these as PROTECTED_PATH_MARKERS; they are not runtime payload, but a
# defect here disables a control rather than a feature.
_GOVERNANCE = re.compile(
    r"^\.claude/(hooks/|deploy/|contracts/|settings\.json$|agents/deploy_)"
)

# AUTH_SECURITY (reviewer action: Block) + OPERATING MODEL mode 3.
_AUTH_SECURITY = re.compile(
    r"^service/app/(auth/|core/(security|guards|role_gate|audit)\.py$)"
)

# DB_SCHEMA (reviewer action: Block).
_DB_SCHEMA = re.compile(
    r"^service/app/db/|(^|/)migrations?/|(^|/)[^/]*migration[^/]*\.py$"
)

# Each service/app/services/*_db.py owns a database; schema lives there.
_DB_OWNER = re.compile(r"^service/app/services/[^/]*_db\.py$")

# CONFIG_RISK -- runtime feature flags gate production behaviour.
_CONFIG_RISK = re.compile(r"^service/app/core/config\.py$")

# Non-runtime trees: present in the repo, never copied to production.
_NON_RUNTIME = re.compile(
    r"^(docs/|reports/|\.github/|\.engineering-os/|service/tests/|tests/|"
    r"reference_batch/|\.campaigns/|scripts/docs/)"
)


def classify_path(path, config=None, config_error=None):
    """Classify one repo-relative path.

    Returns a dict: {path, lane, klass, why}.
    """
    p = _norm(path)
    if not p:
        return {"path": path, "lane": LANE_L2, "klass": "UNKNOWN",
                "why": "empty path -- fail closed"}

    if config is None:
        return {"path": p, "lane": LANE_L2, "klass": "UNKNOWN",
                "why": "config-unavailable (%s) -- fail closed" % (config_error or "?")}

    # 1. hard blocklist wins over everything
    for rx, why in _FORBIDDEN:
        if rx.search(p):
            return {"path": p, "lane": LANE_BLOCKED, "klass": "FORBIDDEN_PATH",
                    "why": "forbidden-paths.md: %s" % why}

    # 2. the safety system itself
    if _GOVERNANCE.search(p):
        return {"path": p, "lane": LANE_L2, "klass": "GOVERNANCE",
                "why": "deploy/authorization machinery "
                       "(merge_authorization PROTECTED_PATH_MARKERS)"}

    app = _app_prefix(config)
    engines = _engine_names(config)

    in_app = p.startswith(app)
    is_engine = ("/" not in p) and (p in engines)

    # 3. sensitive classes inside the runtime payload
    if in_app:
        if _AUTH_SECURITY.search(p):
            return {"path": p, "lane": LANE_L2, "klass": "AUTH_SECURITY",
                    "why": "auth/security authority "
                           "(reviewer action: Block; OPERATING MODEL mode 3)"}
        if _DB_SCHEMA.search(p) or _DB_OWNER.search(p):
            return {"path": p, "lane": LANE_L2, "klass": "DB_SCHEMA",
                    "why": "schema authority "
                           "(reviewer action: Block; OPERATING MODEL mode 3)"}
        if _CONFIG_RISK.search(p):
            return {"path": p, "lane": LANE_L2, "klass": "CONFIG_RISK",
                    "why": "runtime feature flags gate production behaviour"}
        return {"path": p, "lane": LANE_L1, "klass": "SAFE_CODE",
                "why": "runtime payload, ordinary application change"}

    if is_engine:
        return {"path": p, "lane": LANE_L2, "klass": "ENGINE_CORE",
                "why": "engine_files -- calculation authority + Lesson J separate sync"}

    # 4. everything else is not copied to production
    if _NON_RUNTIME.search(p) or p.endswith(".md"):
        klass = "TEST_ONLY" if "test" in p else "DOCS_ONLY"
        return {"path": p, "lane": LANE_L0, "klass": klass,
                "why": "outside the runtime payload -- never copied to production"}

    return {"path": p, "lane": LANE_L0, "klass": "NON_RUNTIME",
            "why": "outside the runtime payload -- never copied to production"}


class Classification(object):
    """Result of classifying a changeset. Data only -- grants nothing."""

    def __init__(self, lane, paths, config_error=None):
        self.lane = lane
        self.paths = paths
        self.config_error = config_error

    @property
    def blocked(self):
        return self.lane == LANE_BLOCKED

    @property
    def blocked_paths(self):
        return [d for d in self.paths if d["lane"] == LANE_BLOCKED]

    @property
    def runtime_payload(self):
        """True when any changed path is copied to production."""
        return any(
            d["klass"] not in ("DOCS_ONLY", "TEST_ONLY", "NON_RUNTIME", "GOVERNANCE")
            for d in self.paths
        )

    @property
    def engine_paths(self):
        """Lesson J: these need the SEPARATE engine sync."""
        return [d["path"] for d in self.paths if d["klass"] == "ENGINE_CORE"]

    @property
    def deploy_required(self):
        """L0 provably cannot deploy: nothing it touches reaches production."""
        return (not self.blocked) and self.runtime_payload

    @property
    def required_validation(self):
        """Validation the changeset must pass, derived from lane AND payload.

        The seven-agent gate binds to *production bytes* (CLAUDE.md "Runtime
        payload"), so it is listed only when bytes actually reach production.
        A change that is high-risk by class but deploys nothing -- editing the
        guards themselves -- is reviewed, not gated: its operative control is
        the protected-path merge boundary in ``merge_authorization.py``, which
        already makes such a change non-autonomously-mergeable.
        """
        if self.blocked:
            return []
        if self.lane == LANE_L0:
            return ["targeted-tests"]
        if not self.runtime_payload:
            return ["targeted-tests", "metered-floors", "governance-review"]
        if self.lane == LANE_L1:
            return ["targeted-tests", "metered-floors", "seven-agent-gate"]
        return ["targeted-tests", "metered-floors", "golden-regression",
                "seven-agent-gate", "extended-review"]

    @property
    def reasons(self):
        """Distinct (klass, why) pairs that drove the lane."""
        seen, out = set(), []
        for d in self.paths:
            if d["lane"] == self.lane and (d["klass"], d["why"]) not in seen:
                seen.add((d["klass"], d["why"]))
                out.append({"klass": d["klass"], "why": d["why"]})
        return out

    def to_dict(self):
        return {
            "lane": self.lane,
            "blocked": self.blocked,
            "blocked_paths": [d["path"] for d in self.blocked_paths],
            "runtime_payload": self.runtime_payload,
            "engine_paths": self.engine_paths,
            "deploy_required": self.deploy_required,
            "required_validation": self.required_validation,
            "reasons": self.reasons,
            "paths": self.paths,
            "config_error": self.config_error,
            "authority_note": (
                "classification only -- deployment authorization remains with "
                "deploy_authorization.py"
            ),
        }


def classify(paths, root=None):
    """Classify a changeset. Highest lane wins; an empty changeset is L0."""
    config, err = load_config(root)
    decided = [classify_path(p, config, err) for p in paths if str(p).strip()]
    if not decided:
        return Classification(LANE_L0, [], err)
    lane = max((d["lane"] for d in decided), key=lambda lane_name: LANE_ORDER[lane_name])
    return Classification(lane, decided, err)


# --------------------------------------------------------------------------
# CLI: reads paths from argv or stdin, prints JSON.  Exit status is EXECUTION
# evidence (0 = classification ran), never authorization.
# --------------------------------------------------------------------------

def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--changed":
        import subprocess
        base = argv[1] if len(argv) > 1 else "origin/main"
        try:
            out = subprocess.run(
                ["git", "diff", "--name-only", "%s...HEAD" % base],
                capture_output=True, text=True, timeout=30,
            )
            argv = out.stdout.split()
        except Exception as exc:
            print(json.dumps({"error": "git diff failed: %s" % exc}))
            return 1
    if not argv:
        argv = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    print(json.dumps(classify(argv).to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
