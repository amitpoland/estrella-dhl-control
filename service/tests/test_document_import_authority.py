"""Import authority for the shipment-document family.

Production raised, at request time:

    ImportError: cannot import name 'resolve_document_parties' from partially
    initialized module 'app.services.commercial_document_parties'
    (most likely due to a circular import)

There is no circular import. ``commercial_document_parties`` imports nothing
from the application — it is a leaf. CPython appends the "circular import"
guess whenever a module is still initialising, and here it was initialising
because the whole document family was first imported *inside a FastAPI
threadpool worker*: two concurrent first-touches, one sees the half-built
module. Same race, same wording, already diagnosed and fixed once for
``storage_health`` in routes_debug.py (PR #582, "BUG 2").

The fix is the same one: import the family eagerly, so it is built once at
startup on a single thread. These tests pin both halves — that the family is
eager, and that the party authority stays a leaf, which is what makes eager
import safe rather than a startup cycle waiting to happen.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parent.parent
APP = SERVICE / "app"

# Every module that must be resident before the first request is served.
DOCUMENT_FAMILY = (
    "app.services.commercial_cmr",
    "app.services.commercial_packing_list",
    "app.services.commercial_packing_list_html",
    "app.services.commercial_document_parties",
)


def _module_level_app_imports(path: Path):
    """Names this module imports from the application at module scope."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    out = []
    for node in tree.body:                       # module scope only
        if isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                out.append("." * node.level + (node.module or ""))
            elif (node.module or "").startswith("app"):
                out.append(node.module)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app."):
                    out.append(a.name)
    return out


def test_document_family_is_resident_after_route_import():
    """Importing the router must build the family — not defer it to a worker.

    main.py imports routes_shipment_documents at startup, single-threaded. If
    the family rides in on that import there is no first-touch left to race.
    """
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "import app.api.routes_shipment_documents\n"
        "missing = [m for m in %r if m not in sys.modules]\n"
        "print(','.join(missing))\n" % (str(SERVICE), DOCUMENT_FAMILY)
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    missing = [m for m in proc.stdout.strip().split(",") if m]
    assert not missing, (
        "first-imported inside a threadpool worker, so a concurrent first "
        "touch can see a half-initialised module: %s" % ", ".join(missing)
    )


def test_party_authority_is_a_leaf():
    """The safety proof for importing it eagerly: it depends on nothing here.

    A module-level application import in the party authority would put it back
    in cycle range, and eager import would then be a startup failure instead of
    a request-time one.
    """
    imports = _module_level_app_imports(APP / "services" / "commercial_document_parties.py")
    assert imports == [], (
        "party authority gained module-level application imports %s — eager "
        "import is only safe while it is a leaf" % imports
    )


def test_resolve_document_parties_has_exactly_one_owner():
    """One canonical resolver. No second implementation, no fallback."""
    owners = [
        p.relative_to(SERVICE).as_posix()
        for p in APP.rglob("*.py")
        for node in ast.parse(p.read_text(encoding="utf-8-sig")).body
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_document_parties"
    ]
    assert owners == ["app/services/commercial_document_parties.py"], owners


def test_no_document_service_imports_a_route_module():
    """Authority runs downward: services never import the API layer."""
    offenders = {}
    for name in DOCUMENT_FAMILY:
        path = APP / Path(name.split("app.", 1)[1].replace(".", "/") + ".py")
        bad = [i for i in _module_level_app_imports(path) if "api" in i or "routes" in i]
        if bad:
            offenders[name] = bad
    assert offenders == {}, offenders
