"""Behavioural tests for the delivery pipeline (risk_lanes / lane_validation).

Deliberately named outside both metered globs (``tests/test_pz_*.py`` and
``tests/test_carrier_*.py``) so adding it cannot perturb the contract floors in
``.claude/contracts/test-baseline.md``.

The invariant under test throughout: these modules CLASSIFY and VALIDATE.
Neither ever returns authorization.
"""

import importlib.util
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
HOOKS = os.path.join(ROOT, ".claude", "hooks")


def _load(name):
    path = os.path.join(HOOKS, name + ".py")
    if not os.path.isfile(path):
        pytest.skip("%s not present" % path)
    spec = importlib.util.spec_from_file_location("_delivery_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, HOOKS)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(HOOKS)
    return mod


risk_lanes = _load("risk_lanes")
lane_validation = _load("lane_validation")


# ------------------------------------------------------------------- lanes

def lane_of(path):
    return risk_lanes.classify([path], root=ROOT).lane


@pytest.mark.parametrize("path", [
    "docs/governance/whatever.md",
    "service/tests/test_something.py",
    "reports/inspection/x.md",
    ".github/workflows/ci.yml",
    "README.md",
])
def test_non_runtime_paths_are_L0(path):
    assert lane_of(path) == risk_lanes.LANE_L0


@pytest.mark.parametrize("path", [
    "service/app/api/routes_pz.py",
    "service/app/services/ai_gateway.py",
    "service/app/static/v2/pages.jsx",
])
def test_ordinary_application_change_is_L1(path):
    assert lane_of(path) == risk_lanes.LANE_L1


@pytest.mark.parametrize("path,klass", [
    ("service/app/auth/session.py", "AUTH_SECURITY"),
    ("service/app/core/security.py", "AUTH_SECURITY"),
    ("service/app/services/reservation_db.py", "DB_SCHEMA"),
    ("service/app/core/config.py", "CONFIG_RISK"),
    ("pz_import_processor.py", "ENGINE_CORE"),
    (".claude/hooks/pz-deploy-guard.py", "GOVERNANCE"),
    (".claude/settings.json", "GOVERNANCE"),
])
def test_sensitive_paths_are_L2_with_the_declared_class(path, klass):
    result = risk_lanes.classify([path], root=ROOT)
    assert result.lane == risk_lanes.LANE_L2
    assert result.paths[0]["klass"] == klass


@pytest.mark.parametrize("path", [
    ".env",
    "service/app/.env.local",
    "storage/shipments/x.json",
    "logs/app.log",
    "outputs/pz.pdf",
    "service/app/services/reservation_queue.db",
])
def test_forbidden_paths_are_BLOCKED(path):
    result = risk_lanes.classify([path], root=ROOT)
    assert result.blocked
    assert result.lane == risk_lanes.LANE_BLOCKED


# --------------------------------------------------- the L0 safety property

def test_L0_provably_cannot_deploy():
    """The campaign's central claim, asserted rather than asserted about."""
    result = risk_lanes.classify(
        ["docs/a.md", "service/tests/test_b.py", "reports/c.md"], root=ROOT)
    assert result.lane == risk_lanes.LANE_L0
    assert result.deploy_required is False
    assert result.runtime_payload is False
    assert result.required_validation == ["targeted-tests"]


def test_blocked_changeset_cannot_deploy_either():
    result = risk_lanes.classify(["storage/x.json"], root=ROOT)
    assert result.deploy_required is False
    assert result.required_validation == []


def test_L1_requires_the_seven_agent_gate():
    result = risk_lanes.classify(["service/app/api/routes_pz.py"], root=ROOT)
    assert result.deploy_required is True
    assert "seven-agent-gate" in result.required_validation
    assert "extended-review" not in result.required_validation


def test_L2_adds_extended_review_and_golden_regression():
    result = risk_lanes.classify(["service/app/auth/session.py"], root=ROOT)
    assert result.deploy_required is True
    assert "extended-review" in result.required_validation
    assert "golden-regression" in result.required_validation


def test_gate_is_inapplicable_when_no_production_byte_changes():
    """A governance change is L2 by class but deploys nothing.

    The seven-agent gate binds to production bytes; there are none, so listing
    it would be ceremony without an object.
    """
    result = risk_lanes.classify([".claude/hooks/pz-deploy-guard.py"], root=ROOT)
    assert result.lane == risk_lanes.LANE_L2
    assert result.deploy_required is False
    assert "seven-agent-gate" not in result.required_validation
    assert "governance-review" in result.required_validation


# ------------------------------------------------------------ mixed / order

def test_highest_lane_wins_on_a_mixed_changeset():
    result = risk_lanes.classify(
        ["docs/a.md", "service/app/api/routes_pz.py", "service/app/auth/session.py"],
        root=ROOT)
    assert result.lane == risk_lanes.LANE_L2
    assert result.deploy_required is True


def test_blocked_outranks_every_other_lane():
    result = risk_lanes.classify(
        ["service/app/auth/session.py", "storage/leak.json"], root=ROOT)
    assert result.lane == risk_lanes.LANE_BLOCKED


def test_engine_files_are_flagged_for_the_separate_lesson_J_sync():
    result = risk_lanes.classify(
        ["pz_import_processor.py", "service/app/api/routes_pz.py"], root=ROOT)
    assert result.engine_paths == ["pz_import_processor.py"]


def test_engine_membership_comes_from_the_config_authority_not_a_literal():
    config, err = risk_lanes.load_config(ROOT)
    assert err is None
    assert "pz_import_processor.py" in config["engine_files"]
    for name in config["engine_files"]:
        assert risk_lanes.classify([name], root=ROOT).lane == risk_lanes.LANE_L2


# ---------------------------------------------------------------- fail closed

def test_unreadable_config_fails_closed_to_L2(tmp_path):
    """Degradation must raise ceremony, never lower it."""
    result = risk_lanes.classify(["docs/harmless.md"], root=str(tmp_path))
    assert result.lane == risk_lanes.LANE_L2
    assert result.config_error


def test_empty_changeset_is_L0_and_deploys_nothing():
    result = risk_lanes.classify([], root=ROOT)
    assert result.lane == risk_lanes.LANE_L0
    assert result.deploy_required is False


def test_windows_separators_and_dot_prefixes_normalise():
    for variant in ["service\\app\\auth\\session.py",
                    "./service/app/auth/session.py",
                    "SERVICE/APP/AUTH/SESSION.PY"]:
        assert risk_lanes.classify([variant], root=ROOT).lane == risk_lanes.LANE_L2


# --------------------------------------------------------- contract verdicts

def test_contract_parses_both_metered_floors():
    contract, err = lane_validation.load_contract(ROOT)
    assert err is None
    floors = {s["pattern"]: s["floor"] for s in contract["suites"].values()}
    assert floors["tests/test_pz_*.py"] == 260
    assert floors["tests/test_carrier_*.py"] == 604
    assert len(contract["exclusions"]) >= 3


def test_nodeid_mapping_handles_plain_and_class_nested_cases():
    assert (lane_validation._nodeid("tests.test_carrier_tab_labels", "test_x")
            == "test_carrier_tab_labels.py::test_x")
    assert (lane_validation._nodeid("tests.test_proforma.TestThing", "test_x")
            == "test_proforma.py::TestThing::test_x")


SUITE = {"name": "Carrier suite", "pattern": "tests/test_carrier_*.py", "floor": 604}
RAN = {"exit_code": 1, "timed_out": False}


def test_registered_failures_with_a_nonzero_exit_are_advanceable():
    """The measured production case: exit 1, contract satisfied.

    This is the execution-vs-authorization separation, pinned against
    regression.  Reverting the pipeline to an ``exit == 0`` gate fails here.
    """
    parsed = {"total": 761, "passed": 758, "skipped": 0,
              "failed": ["test_carrier_tab_labels.py::test_active_key_not_invented"],
              "errors": []}
    verdict = lane_validation.evaluate_suite(
        SUITE, RAN, parsed,
        {"test_carrier_tab_labels.py::test_active_key_not_invented"})
    assert verdict["verdict"] == lane_validation.VERDICT_PRE_EXISTING
    assert verdict["verdict"] in lane_validation.ADVANCEABLE
    assert verdict["exit_code"] == 1


def test_an_unregistered_failure_is_a_campaign_failure():
    parsed = {"total": 761, "passed": 758, "skipped": 0,
              "failed": ["test_carrier_new.py::test_i_broke_this"], "errors": []}
    verdict = lane_validation.evaluate_suite(SUITE, RAN, parsed, set())
    assert verdict["verdict"] == lane_validation.VERDICT_CAMPAIGN
    assert verdict["verdict"] not in lane_validation.ADVANCEABLE


def test_any_error_blocks_even_when_registered():
    """The contract makes ERROR unconditional, unlike FAILED."""
    parsed = {"total": 761, "passed": 758, "skipped": 0, "failed": [],
              "errors": ["test_carrier_x.py::test_collect"]}
    verdict = lane_validation.evaluate_suite(
        SUITE, RAN, parsed, {"test_carrier_x.py::test_collect"})
    assert verdict["verdict"] == lane_validation.VERDICT_CAMPAIGN


def test_a_pass_count_below_the_floor_blocks_even_with_exit_zero():
    """Exit 0 is not authorization in the permissive direction either."""
    parsed = {"total": 100, "passed": 100, "skipped": 0, "failed": [], "errors": []}
    verdict = lane_validation.evaluate_suite(
        SUITE, {"exit_code": 0, "timed_out": False}, parsed, set())
    assert verdict["verdict"] == lane_validation.VERDICT_FLOOR
    assert verdict["verdict"] not in lane_validation.ADVANCEABLE
    assert verdict["exit_code_agrees_with_verdict"] is False


def test_a_timeout_is_INCOMPLETE_not_a_failure():
    """Lesson S: an unfinished producer is diagnosed, never retried blindly."""
    verdict = lane_validation.evaluate_suite(
        SUITE, {"exit_code": None, "timed_out": True}, None, set())
    assert verdict["verdict"] == lane_validation.VERDICT_INCOMPLETE
    assert verdict["verdict"] not in lane_validation.ADVANCEABLE


def test_a_clean_run_passes():
    parsed = {"total": 758, "passed": 758, "skipped": 0, "failed": [], "errors": []}
    verdict = lane_validation.evaluate_suite(
        SUITE, {"exit_code": 0, "timed_out": False}, parsed, set())
    assert verdict["verdict"] == lane_validation.VERDICT_PASS


def test_an_unreadable_contract_fails_closed(tmp_path):
    contract, err = lane_validation.load_contract(str(tmp_path))
    assert contract is None
    assert err


# ----------------------------------------------------- the authority boundary

def test_no_module_in_the_pipeline_grants_authorization():
    """Neither module may expose anything that could read as permission."""
    for module in (risk_lanes, lane_validation):
        for forbidden in ("authorize", "sign", "grant", "approve"):
            offenders = [n for n in dir(module)
                         if forbidden in n.lower() and not n.startswith("_")]
            assert not offenders, "%s exports %s" % (module.__name__, offenders)


def test_classification_output_states_it_grants_nothing():
    payload = risk_lanes.classify(["service/app/api/routes_pz.py"], root=ROOT).to_dict()
    assert "deploy_authorization.py" in payload["authority_note"]
    json.dumps(payload)  # must stay machine-readable


# ------------------------------------------------- the postedit relevance gate

postedit = _load("pz-regression-postedit")


def test_golden_surface_is_root_only():
    """The measurement the postedit skip depends on, pinned.

    ``pz-regression-postedit.py`` skips the 1.46 s golden suite for edits
    outside the repository root because the golden import closure was
    measured to contain only root-level modules.  If someone later imports
    a service/ module into the engine, that skip becomes unsound -- so the
    closure is re-measured here rather than trusted.
    """
    probe = chr(10).join([
        "import sys, os, json",
        "root = os.getcwd()",
        "import golden_constants, pz_import_processor",
        "out = []",
        "for m in list(sys.modules.values()):",
        "    f = getattr(m, '__file__', None)",
        "    if f and os.path.abspath(f).startswith(root):",
        "        out.append(os.path.relpath(f, root).replace(os.sep, '/'))",
        "print(json.dumps(sorted(set(out))))",
    ])

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    reached = json.loads(proc.stdout.strip().splitlines()[-1])

    assert reached, "probe reached no repo modules -- the measurement is broken"
    nested = [m for m in reached if "/" in m]
    assert not nested, (
        "the golden import closure now reaches non-root modules %s; the "
        "postedit relevance gate would skip edits that CAN change the golden "
        "result. Widen _in_golden_surface before landing that import." % nested)


@pytest.mark.parametrize("rel,expected", [
    ("pz_import_processor.py", True),
    ("golden_constants.py", True),
    ("description_grammar.py", True),
    ("reference_batch/expected.json", True),
    ("service/app/api/routes_pz.py", False),
    ("service/tests/test_routes_pz.py", False),
    ("docs/governance/x.py", False),
])
def test_in_golden_surface(rel, expected):
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    assert postedit._in_golden_surface(path, ROOT) is expected


def test_unresolvable_path_runs_the_suite():
    """Fail-safe direction: a skip happens only on proof."""
    assert postedit._in_golden_surface("Z:" + os.sep + "elsewhere.py", ROOT) is True


def test_derive_count_reports_what_the_run_said():
    """The hook used to print a remembered 160 regardless of the run."""
    assert postedit._derive_count(b"  148/160 tests passed  |  12 failed") == "148/160"
    assert postedit._derive_count(b"  160/160 tests passed  |  0 failed") == "160/160"


def test_derive_count_admits_when_it_cannot_tell():
    assert postedit._derive_count(b"something else entirely") is None
    assert postedit._derive_count(None) is None

# --------------------------------------------- the L0 default for unknown paths

DEPLOY_CONFIG = os.path.join(ROOT, ".claude", "deploy", "windows_prod_v2.json")

# Keys whose values name repository source but are NOT copy directives: they are
# test selectors the deploy script RUNS, never files it COPIES.
_NON_COPY_SOURCE_KEYS = frozenset([
    "root_golden_script",     # the deploy RUNS the golden suite
    "carrier_test_glob",      # the deploy RUNS the carrier suite
    "authorization_helper",   # the deploy INVOKES the mint/verify helper
])

def _config_values():
    with open(DEPLOY_CONFIG, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    flat = []
    def walk(obj, key):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, k)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, key)
        elif isinstance(obj, str):
            flat.append((key, obj))
    walk(cfg, "")
    return cfg, flat

def test_copy_surface_is_exactly_app_plus_engine_files():
    """The invariant the L0 default rests on.

    ``classify_path`` grants L0 -- 'outside the runtime payload, never copied
    to production' -- to every path it does not positively recognise.  That is
    truthful ONLY while the deployment procedure copies exactly two things:
    the ``source_app`` tree and the named ``engine_files``.  If a third copy
    directive is ever added to the deploy config, those files would reach
    production while classifying L0 with deploy_required=False -- an
    optimistic-by-default misclassification (Lesson Q rule 6).

    So the correspondence is measured here rather than assumed.  If this test
    fails, widen risk_lanes.classify_path BEFORE landing the config change.
    """
    cfg, flat = _config_values()
    engines = set(cfg["engine_files"])

    unexpected = []
    for key, value in flat:
        if " " in value:          # prose (a _note/_authority narrative), not a path
            continue
        if ":" in value:          # absolute Windows path: a machine location
            continue
        if value in engines or key == "engine_files":
            continue
        if key in _NON_COPY_SOURCE_KEYS:
            continue
        if "service/" in value or value.endswith(".py"):
            unexpected.append((key, value))

    assert not unexpected, (
        "the deploy config names repository source outside the two known copy "
        "directives: %r -- if this is a new copy directive, risk_lanes must "
        "learn it before the L0 default is safe" % (unexpected,))

    assert cfg["source_app"].replace(chr(92), "/").endswith("service/app")
    assert len(engines) == 16, "engine_files count changed: %d" % len(engines)

def test_unrecognised_path_is_l0_and_says_why():
    """The default is explicit and reasoned, not a silent fallthrough."""
    row = risk_lanes.classify(["totally_new_toplevel_dir/thing.py"], root=ROOT).to_dict()
    assert row["lane"] == "L0"
    assert row["deploy_required"] is False
    why = row["paths"][0]["why"]
    assert "never copied to production" in why, why

def test_config_failure_fails_closed_for_every_path():
    """A changeset classified without config must not be advanceable as L0."""
    for path in ["docs/x.md", "service/app/api/routes_pz.py", "unknown/x.py"]:
        row = risk_lanes.classify_path(path, None, "simulated config failure")
        assert row["lane"] == "L2", (path, row)
        assert row["klass"] == "UNKNOWN"
        assert "fail closed" in row["why"]
