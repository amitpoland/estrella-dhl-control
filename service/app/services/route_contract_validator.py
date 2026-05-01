"""
Dashboard Action V2 — route contract validator.

Walks the FastAPI app's mounted routes and confirms every endpoint emitted by
the action registry resolves to a real route with a matching method.

Path-template aware: /api/v1/files/{batch_id}/{filename} matches a registered
/api/v1/files/{batch_id}/{filename} route even when the registry emits a
substituted concrete path like /api/v1/files/SHIPMENT_X/PZ_X.pdf.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Set, Tuple

from .dashboard_action_types import BrokenRoute


# A registered route template like "/api/v1/files/{batch_id}/{filename}"
# matches concrete paths "/api/v1/files/.../...". We normalize both sides into
# a regex pattern.

def _template_to_pattern(tpl: str) -> re.Pattern[str]:
    # Strip query string from template (shouldn't be there but be safe)
    tpl = tpl.split("?", 1)[0]
    # Replace {name:path} with .+ and {name} with [^/]+
    pat = re.sub(r"\{[^}/:]+:path\}", ".+", tpl)
    pat = re.sub(r"\{[^}/]+\}",        r"[^/]+", pat)
    return re.compile("^" + pat + "$")


def collect_app_routes(app) -> Set[Tuple[str, str]]:
    """
    Return set of (method, path_template) for every route mounted on the app.
    """
    out: Set[Tuple[str, str]] = set()
    for r in getattr(app, "routes", []):
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if not path:
            continue
        for m in methods:
            out.add((m.upper(), path))
    return out


def validate_endpoints(
    app,
    endpoints: Iterable[Tuple[str, str, str]],
) -> List[BrokenRoute]:
    """
    `endpoints` is an iterable of (action_id, method, concrete_endpoint).
    Returns list of BrokenRoute for any endpoint that doesn't resolve.
    """
    routes = collect_app_routes(app)
    # Pre-compile patterns for each registered template
    compiled: list[Tuple[str, str, re.Pattern[str]]] = [
        (m, p, _template_to_pattern(p)) for (m, p) in routes
    ]

    broken: List[BrokenRoute] = []
    for action_id, method, endpoint in endpoints:
        # Strip query string from concrete endpoint before matching
        path_only = endpoint.split("?", 1)[0]
        method_u = method.upper()
        path_match  = False
        method_match = False
        for (m, _tpl, pat) in compiled:
            if pat.match(path_only):
                path_match = True
                if m == method_u:
                    method_match = True
                    break
        if not path_match:
            broken.append(BrokenRoute(action_id=action_id, endpoint=endpoint, method=method_u, reason="not_mounted"))
        elif not method_match:
            broken.append(BrokenRoute(action_id=action_id, endpoint=endpoint, method=method_u, reason="method_mismatch"))
    return broken
