"""
test_rbac_structural_allowlist.py — Phase B: RBAC structural integrity gate.

PURPOSE
-------
Freeze the current set of bare-auth mutation routes so that no new
POST/PUT/PATCH/DELETE route may land with only ``require_api_key`` or
``get_current_user`` as its auth guard unless it is explicitly listed in
``_BARE_AUTH_ALLOWLIST``.

WHAT IS A "BARE" MUTATION ROUTE?
---------------------------------
A mutation route (POST / PUT / PATCH / DELETE) is "bare" when its only
authentication is one of:

    require_api_key   — valid API key OR any logged-in session, no role check
    get_current_user  — any logged-in session, no role check

A route is "privileged" (and therefore RBAC-clean) if it also uses any of:

    require_role(...)         — explicit role list
    require_admin             — admin-only gate
    require_role_or_apikey(…) — master-data role enforcement

WHAT THIS TEST DOES
--------------------
1. Parses every ``routes_*.py`` file with ``ast`` — no imports, no DB.
2. Detects bare-auth mutation routes via three surfaces:
   (a) ``dependencies=[_auth]`` in a route decorator where ``_auth``
       resolves to a bare-auth Depends at module level
   (b) ``dependencies=[Depends(require_api_key)]`` inline in decorator
   (c) ``APIRouter(dependencies=[...])`` router-level inheritance
   (d) Function-parameter ``Depends(require_api_key)`` / typed Annotated
3. Asserts that every found bare route is in ``_BARE_AUTH_ALLOWLIST``.
4. Reports new violations (not in allowlist) as test failures with the
   exact allowlist key needed — making Phase C burn-down self-documenting.

WHAT THIS TEST DOES NOT DO
---------------------------
- No behavior changes. No route guards are modified.
- Does NOT report "no-auth" routes (those are a separate Phase C item).
- Does NOT need the FastAPI app to be importable — pure source analysis.

ALLOWLIST GOVERNANCE
--------------------
Adding a route to ``_BARE_AUTH_ALLOWLIST`` requires:
  1. The route genuinely exists in the codebase (checked by test_no_stale_allowlist_entries)
  2. A comment in the PR explaining why it is temporarily excluded
  3. A Phase C issue/task filed for the area it belongs to

Removing a route from the allowlist (by upgrading its guard to privileged)
is always welcome — the test continues to pass, the allowlist shrinks.

Generated: 2026-06-08 (Phase A inventory scan across 68 route files)
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ROUTES_DIR = Path(__file__).resolve().parents[1] / "app" / "api"

# Auth function names considered "bare" — valid authentication but no RBAC.
_BARE_AUTH_NAMES: frozenset[str] = frozenset({
    "require_api_key",
    "get_current_user",
})

# Auth function names that satisfy RBAC (adds role check beyond bare auth).
_PRIVILEGED_AUTH_NAMES: frozenset[str] = frozenset({
    "require_role",
    "require_admin",
    "require_role_or_apikey",
    # extend here when new privileged guards are introduced
})

_MUTATION_METHODS: frozenset[str] = frozenset({"post", "put", "patch", "delete"})

# ---------------------------------------------------------------------------
# Allowlist — Phase A inventory (2026-06-08)
#
# Every entry here is a KNOWN bare-auth mutation route as of 2026-06-08.
# Format: "<filename>:<METHOD>:<path_template>"
#
# Phase C burn-down plan:
#   Area 1 — Proposals / control / dashboard ops
#   Area 2 — DHL ops
#   Area 3 — PZ / warehouse / intake / inventory
#   Area 4 — Proforma
#   Area 5 — wFirma / accounting-sensitive routes
#
# Entries are grouped by area so Phase C PRs can remove whole blocks.
# ---------------------------------------------------------------------------

# Area 1 — Proposals / control / dashboard ops
_AREA1_ROUTES: frozenset[str] = frozenset({
    "routes_action_proposals.py:POST:/{batch_id}/refresh",
    "routes_action_proposals.py:POST:/{proposal_id}/approve",
    "routes_action_proposals.py:POST:/{proposal_id}/queue",
    "routes_action_proposals.py:POST:/{proposal_id}/reject",
    "routes_action_proposals.py:POST:/{proposal_id}/resolve",
    "routes_admin_dhl_clearance.py:POST:/proactive-dispatch/{batch_id}",
    "routes_admin_runtime_flags.py:POST:/self-clearance",
    "routes_correction_registry.py:POST:",
    "routes_customer_master.py:POST:/dictionaries/refresh",
    "routes_customer_master.py:POST:/sync-from-wfirma/apply",
    "routes_dashboard.py:DELETE:/batches/{batch_id}",
    "routes_dashboard.py:DELETE:/batches/{batch_id}/files/source/{category}/{filename}",
    "routes_dashboard.py:DELETE:/batches/{batch_id}/files/{filename}",
    "routes_dashboard.py:DELETE:/batches/{batch_id}/polish-description",
    "routes_dashboard.py:POST:/archive/{batch_id}/restore",
    "routes_dashboard.py:POST:/batches/{batch_id}/cn-decision/accept-sad",
    "routes_dashboard.py:POST:/batches/{batch_id}/cn-decision/correct-internal",
    "routes_dashboard.py:POST:/batches/{batch_id}/cn-decision/escalate-agent",
    "routes_dashboard.py:POST:/batches/{batch_id}/email-evidence/process",
    "routes_dashboard.py:POST:/batches/{batch_id}/email-evidence/rescan",
    "routes_dashboard.py:POST:/batches/{batch_id}/operator-override",
    "routes_dashboard.py:POST:/batches/{batch_id}/recheck",
    "routes_dashboard.py:POST:/batches/{batch_id}/regenerate",
    "routes_dashboard.py:POST:/batches/{batch_id}/resend",
    "routes_dashboard.py:POST:/broker-followups/{batch_id}/send",
    "routes_dashboard.py:POST:/broker-reply/analyze",
    "routes_debug.py:POST:/clear-test-sessions",
    "routes_debug.py:POST:/post-pz-test",
    "routes_monitor.py:POST:/active-shipments/run",
    "routes_orchestrator.py:POST:/dry-run",
    "routes_orchestrator.py:POST:/tick",
    "routes_proposals.py:POST:/capture",
    "routes_proposals.py:POST:/{proposal_id}/approve",
    "routes_proposals.py:POST:/{proposal_id}/reject",
    "routes_settings.py:PATCH:/company-profile",
    "routes_suppliers.py:POST:/sync-from-wfirma",
    "routes_suppliers.py:POST:/sync-from-wfirma/apply",
})

# Area 2 — DHL ops
_AREA2_ROUTES: frozenset[str] = frozenset({
    "routes_agency.py:POST:/email-package/{batch_id}",
    "routes_dhl_clearance.py:POST:/approve/{batch_id}",
    "routes_dhl_clearance.py:POST:/generate-customs-package/{batch_id}",
    "routes_dhl_clearance.py:POST:/generate-description/{batch_id}",
    "routes_dhl_clearance.py:POST:/mark-email-received/{batch_id}",
    "routes_dhl_clearance.py:POST:/match-and-handle",
    "routes_dhl_clearance.py:POST:/proactive-dispatch/{batch_id}",
    "routes_dhl_clearance.py:POST:/send-reply/{batch_id}",
    "routes_dhl_documents.py:POST:/{batch_id}/received",
    "routes_dhl_documents.py:POST:/{batch_id}/upload",
    "routes_dhl_followup.py:POST:/{batch_id}/mode",
    "routes_dhl_followup.py:POST:/{batch_id}/recalculate",
    "routes_dhl_followup.py:POST:/{batch_id}/send-now",
    "routes_dhl_followup.py:POST:/{batch_id}/stop",
    "routes_dsk.py:POST:/email-package",
    "routes_dsk.py:POST:/generate",
    "routes_tracking.py:POST:/batch/{batch_id}/update",
    "routes_tracking.py:POST:/{awb}/cowork-result",
    "routes_tracking.py:POST:/{tracking_no}/refresh",
    "routes_tracking_db.py:POST:/events/export",
})

# Area 3 — PZ / warehouse / intake / inventory
_AREA3_ROUTES: frozenset[str] = frozenset({
    "routes_batch.py:POST:/add",
    "routes_batch.py:POST:/cancel",
    "routes_batch.py:POST:/scan-chat",
    "routes_batch.py:POST:/start",
    "routes_batch.py:POST:/status",
    "routes_batch.py:POST:/submit",
    "routes_execute.py:POST:/{action}",
    "routes_intake.py:POST:/intake",
    "routes_intake.py:POST:/sales-packing/reingest",
    "routes_intake.py:POST:/{batch_id}/add-document",
    "routes_intake.py:POST:/{batch_id}/packing_list",
    "routes_inventory_returns.py:POST:/pieces/{piece_id}/return-from-client",
    "routes_inventory_returns.py:POST:/pieces/{piece_id}/return-from-producer",
    "routes_inventory_returns.py:POST:/pieces/{piece_id}/return-to-producer",
    "routes_inventory_sample.py:POST:/pieces/{piece_id}/sample-out",
    "routes_inventory_sample.py:POST:/pieces/{piece_id}/sample-return",
    "routes_inventory_writes.py:POST:/pieces/{piece_id}/location",
    "routes_learning.py:DELETE:/patterns/{supplier_key}",
    "routes_learning.py:POST:/feedback",
    "routes_lifecycle.py:POST:/agency-documents/{batch_id}/received",
    "routes_lifecycle.py:POST:/agency-documents/{batch_id}/upload",
    "routes_lifecycle.py:POST:/closure/{batch_id}/evaluate",
    "routes_lifecycle.py:POST:/inventory-state/mark-direct-dispatch",
    "routes_lifecycle.py:POST:/lifecycle/agency-followup",
    "routes_lifecycle.py:POST:/service-invoices/{batch_id}/received",
    "routes_lifecycle.py:POST:/service-invoices/{batch_id}/upload",
    "routes_packing.py:POST:/{batch_id}/barcode/print",
    "routes_packing.py:POST:/{batch_id}/link-as-sales",
    "routes_packing.py:POST:/{batch_id}/reprocess",
    "routes_packing.py:POST:/{batch_id}/reprocess-prices",
    "routes_packing.py:POST:/{batch_id}/upload",
    "routes_packing_resolution.py:POST:/{batch_id}/contractor-resolution",
    "routes_packing_resolution.py:POST:/{batch_id}/contractor-resolution/confirm",
    "routes_pz.py:DELETE:/pz/lineage/{batch_id}/correction-stage",
    "routes_pz.py:POST:/feedback",
    "routes_pz.py:POST:/pz/lineage/{batch_id}/correction-commit",
    "routes_pz.py:POST:/pz/lineage/{batch_id}/correction-execute",
    "routes_pz.py:POST:/pz/lineage/{batch_id}/correction-push-wfirma",
    "routes_pz.py:POST:/pz/lineage/{batch_id}/correction-stage",
    "routes_pz.py:POST:/pz/lineage/{batch_id}/correction-suppress",
    "routes_pz.py:POST:/pz/process",
    "routes_pz.py:POST:/pz/process/_legacy",
    "routes_upload.py:POST:/dhl-zc429/intake",
    "routes_upload.py:POST:/shipment",
    "routes_upload.py:POST:/shipment/{batch_id}/process",
    "routes_upload.py:POST:/shipment/{batch_id}/sad",
    "routes_upload.py:POST:/shipment/{batch_id}/set_pz",
    "routes_warehouse.py:POST:/locations",
    "routes_warehouse.py:POST:/scan",
})

# Area 4 — Proforma
_AREA4_ROUTES: frozenset[str] = frozenset({
    "routes_proforma.py:DELETE:/draft/{draft_id}/lines/{line_id}",
    "routes_proforma.py:DELETE:/draft/{draft_id}/service-charges/{charge_id}",
    "routes_proforma.py:DELETE:/service-charges/{batch_id}/{client_name}/{charge_type}",
    "routes_proforma.py:PATCH:/draft/{draft_id}",
    "routes_proforma.py:PATCH:/draft/{draft_id}/lines/{line_id}",
    "routes_proforma.py:POST:/adopt-issued/{batch_id}/{client_name:path}",
    "routes_proforma.py:POST:/cancel-issued-for-reissue/{batch_id}/{client_name:path}",
    "routes_proforma.py:POST:/create/{batch_id}/{client_name:path}",
    "routes_proforma.py:POST:/draft/{draft_id}/approve",
    "routes_proforma.py:POST:/draft/{draft_id}/bulk-price-recovery",
    "routes_proforma.py:POST:/draft/{draft_id}/cancel",
    "routes_proforma.py:POST:/draft/{draft_id}/clone",
    "routes_proforma.py:POST:/draft/{draft_id}/enrich-from-product-descriptions",
    "routes_proforma.py:POST:/draft/{draft_id}/lines",
    "routes_proforma.py:POST:/draft/{draft_id}/post",
    "routes_proforma.py:POST:/draft/{draft_id}/re-open",
    "routes_proforma.py:POST:/draft/{draft_id}/reset-from-sales-packing",
    "routes_proforma.py:POST:/draft/{draft_id}/service-charges",
    "routes_proforma.py:POST:/draft/{draft_id}/to-invoice",
    "routes_proforma.py:POST:/preview/{batch_id}/{client_name:path}",
    "routes_proforma.py:POST:/service-charges/{batch_id}/{client_name:path}",
    "routes_proforma.py:POST:/to-invoice/{batch_id}/{client_name:path}",
    "routes_proforma.py:POST:/{wfirma_id}/refresh-line-names",
    "routes_proforma.py:PUT:/service-products/{charge_type}",
    "routes_proforma_adopt.py:POST:/adopt-issued/{batch_id}",
    "routes_proforma_adopt.py:POST:/enrich-fullnumber/{batch_id}",
    "routes_reservations.py:POST:/products/import-purchase-packing",
    "routes_reservations.py:POST:/reservations/import-sales-packing",
    "routes_reservations.py:POST:/reservations/process-pending",
    "routes_reservations.py:POST:/reservations/{queue_id}/reset",
    "routes_reservations.py:POST:/wfirma/products/sync-by-codes",
})

# Area 5 — wFirma / accounting-sensitive / carrier / AI
_AREA5_ROUTES: frozenset[str] = frozenset({
    "routes_ai_bridge.py:POST:/results/{task_id}",
    "routes_ai_bridge.py:POST:/tasks/{batch_id}",
    "routes_bot.py:POST:/bot-event",
    "routes_carrier_actions.py:POST:/{batch_id}/label-package",
    "routes_carrier_actions.py:POST:/{batch_id}/shipment",
    "routes_wfirma.py:POST:/shipment/{batch_id}/wfirma/clipboard",
    "routes_wfirma.py:POST:/shipment/{batch_id}/wfirma/products/resolve",
    "routes_wfirma.py:POST:/shipment/{batch_id}/wfirma/products/sync-names",
    "routes_wfirma.py:POST:/shipment/{batch_id}/wfirma/pz/clear-mapping",
    "routes_wfirma.py:POST:/shipment/{batch_id}/wfirma/pz/refresh-mapping",
    "routes_wfirma.py:POST:/shipment/{batch_id}/wfirma/pz_adopt",
    "routes_wfirma.py:POST:/shipment/{batch_id}/wfirma/pz_confirm",
    "routes_wfirma.py:POST:/shipment/{batch_id}/wfirma/pz_create",
    "routes_wfirma_capabilities.py:POST:/customers/auto-create-from-name",
    "routes_wfirma_capabilities.py:POST:/customers/auto-resolve-preview/{batch_id:path}",
    "routes_wfirma_capabilities.py:POST:/customers/create-internal-test",
    "routes_wfirma_capabilities.py:POST:/customers/sync",
    "routes_wfirma_capabilities.py:POST:/customers/sync-from-wfirma/apply",
    "routes_wfirma_capabilities.py:POST:/goods/adopt/{product_code:path}",
    "routes_wfirma_capabilities.py:POST:/goods/auto-register-preview/{batch_id:path}",
    "routes_wfirma_capabilities.py:POST:/goods/auto-register/{batch_id:path}",
    "routes_wfirma_capabilities.py:POST:/goods/create-and-adopt/{product_code:path}",
    "routes_wfirma_capabilities.py:POST:/goods/create-from-product-code/{product_code:path}",
    "routes_wfirma_capabilities.py:POST:/goods/refresh-name-from-block/{product_code:path}",
    "routes_wfirma_capabilities.py:POST:/goods/search-bulk",
    "routes_wfirma_capabilities.py:POST:/goods/update-and-adopt/{product_code:path}",
    "routes_wfirma_capabilities.py:PUT:/customers/{client_name:path}",
    "routes_wfirma_capabilities.py:PUT:/customers/{client_name:path}/default-currency",
    "routes_wfirma_capabilities.py:PUT:/customers/{client_name:path}/ship-to",
    "routes_wfirma_capabilities.py:PUT:/products/{product_code:path}",
    "routes_wfirma_reservation.py:POST:/reservations/create",
    "routes_wfirma_reservation.py:POST:/reservations/{draft_id}/reset-stuck",
})

# Master allowlist — union of all five areas.
_BARE_AUTH_ALLOWLIST: frozenset[str] = (
    _AREA1_ROUTES | _AREA2_ROUTES | _AREA3_ROUTES | _AREA4_ROUTES | _AREA5_ROUTES
)

# ---------------------------------------------------------------------------
# AST helpers — pure source analysis, no imports
# ---------------------------------------------------------------------------


class _RouteInfo(NamedTuple):
    filename: str
    method: str
    path_template: str
    auth_level: str   # "bare" | "privileged" | "none"

    @property
    def allowlist_key(self) -> str:
        return f"{self.filename}:{self.method}:{self.path_template}"


def _depends_name(node: ast.AST) -> str | None:
    """Return the name passed as first arg to Depends(), or None."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not (isinstance(func, ast.Name) and func.id == "Depends"):
        return None
    if not node.args:
        return None
    arg = node.args[0]
    if isinstance(arg, ast.Name):
        return arg.id
    # Depends(require_role("admin")) — factory call, outer name matters.
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
        return arg.func.id
    return None


def _auth_level_from_name(name: str | None) -> str | None:
    if name in _BARE_AUTH_NAMES:
        return "bare"
    if name in _PRIVILEGED_AUTH_NAMES:
        return "privileged"
    return None


def _auth_set_from_dep_list(
    dep_list_node: ast.AST,
    dep_vars: dict[str, str],
) -> set[str]:
    """Extract auth levels from a ``dependencies=[...]`` list node."""
    found: set[str] = set()
    if not isinstance(dep_list_node, ast.List):
        return found
    for elt in dep_list_node.elts:
        if isinstance(elt, ast.Name):
            # Variable reference — resolve via module-level dep_vars map.
            level = dep_vars.get(elt.id)
            if level:
                found.add(level)
        elif isinstance(elt, ast.Call):
            level = _auth_level_from_name(_depends_name(elt))
            if level:
                found.add(level)
    return found


def _auth_set_from_func_params(
    func_def: ast.FunctionDef | ast.AsyncFunctionDef,
    dep_vars: dict[str, str],
) -> set[str]:
    """Extract auth levels from function parameters using Depends."""
    found: set[str] = set()
    # Plain defaults: def f(user=Depends(require_api_key))
    all_defaults = list(func_def.args.defaults) + [
        x for x in (func_def.args.kw_defaults or []) if x is not None
    ]
    for d in all_defaults:
        level = _auth_level_from_name(_depends_name(d))
        if level:
            found.add(level)
    # Annotated[X, Depends(...)] style
    for arg in list(func_def.args.args) + list(func_def.args.kwonlyargs):
        ann = arg.annotation
        if not (ann and isinstance(ann, ast.Subscript)):
            continue
        val = ann.value
        if not (isinstance(val, ast.Name) and val.id == "Annotated"):
            continue
        sl = ann.slice
        elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
        for e in elts:
            level = _auth_level_from_name(_depends_name(e))
            if level:
                found.add(level)
    return found


def _router_level_auth(
    tree: ast.Module,
    dep_vars: dict[str, str],
) -> str | None:
    """
    Return the auth level declared on the ``APIRouter(dependencies=[...])``
    call, or None if not present.  When found this is inherited by every
    route in the file that has no route-level override.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        val = node.value
        if not isinstance(val, ast.Call):
            continue
        func = val.func
        is_apirouter = (
            isinstance(func, ast.Name) and func.id == "APIRouter"
        ) or (
            isinstance(func, ast.Attribute) and func.attr == "APIRouter"
        )
        if not is_apirouter:
            continue
        for kw in val.keywords:
            if kw.arg == "dependencies":
                levels = _auth_set_from_dep_list(kw.value, dep_vars)
                if "privileged" in levels:
                    return "privileged"
                if "bare" in levels:
                    return "bare"
    return None


def _scan_route_file(path: Path) -> list[_RouteInfo]:
    """Return all mutation routes found in ``path`` with their auth level."""
    try:
        src = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError):
        return []

    # Build module-level variable → auth-level mapping.
    dep_vars: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if not isinstance(t, ast.Name):
                continue
            level = _auth_level_from_name(_depends_name(node.value))
            if level:
                dep_vars[t.id] = level

    router_auth = _router_level_auth(tree, dep_vars)

    results: list[_RouteInfo] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            attr = dec.func
            if not isinstance(attr, ast.Attribute):
                continue
            method = attr.attr
            if method not in _MUTATION_METHODS:
                continue

            path_str = ""
            if dec.args and isinstance(dec.args[0], ast.Constant):
                path_str = str(dec.args[0].value)

            # Collect auth signals from all three surfaces.
            auth: set[str] = set()
            for kw in dec.keywords:
                if kw.arg == "dependencies":
                    auth |= _auth_set_from_dep_list(kw.value, dep_vars)
            auth |= _auth_set_from_func_params(node, dep_vars)
            # Fall back to router-level when route has no explicit auth.
            if not auth and router_auth:
                auth.add(router_auth)

            if not auth:
                level = "none"
            elif "privileged" in auth:
                level = "privileged"
            else:
                level = "bare"

            results.append(_RouteInfo(
                filename=path.name,
                method=method.upper(),
                path_template=path_str,
                auth_level=level,
            ))
    return results


def _all_mutation_routes() -> list[_RouteInfo]:
    routes: list[_RouteInfo] = []
    for f in sorted(_ROUTES_DIR.glob("routes_*.py")):
        routes.extend(_scan_route_file(f))
    return routes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRbacStructuralAllowlist:
    """
    Structural RBAC integrity tests — Phase B gate.

    These tests run entirely from source file parsing.
    No database, no app import, no network.
    """

    def test_no_new_bare_mutation_routes(self) -> None:
        """
        GATE: Every bare-auth mutation route must be in the allowlist.

        If this test fails, a new POST/PUT/PATCH/DELETE route was added with
        only ``require_api_key`` or ``get_current_user`` as its auth guard.

        To fix:
          Option A (preferred): upgrade the guard to a privileged dependency
                                before merging — no allowlist change needed.
          Option B (temporary): add the route key to the relevant _AREA*_ROUTES
                                set with a comment, and file a Phase C task.
        """
        routes = _all_mutation_routes()
        bare = [r for r in routes if r.auth_level == "bare"]

        violations = [r for r in bare if r.allowlist_key not in _BARE_AUTH_ALLOWLIST]

        if violations:
            keys = "\n".join(f'    "{r.allowlist_key}",' for r in sorted(violations, key=lambda r: r.allowlist_key))
            pytest.fail(
                f"\n{len(violations)} NEW bare-auth mutation route(s) detected outside the allowlist.\n"
                f"Either upgrade to a privileged guard, or add to the appropriate _AREA*_ROUTES set:\n\n"
                f"{keys}\n"
            )

    def test_no_stale_allowlist_entries(self) -> None:
        """
        Allowlist hygiene: every allowlist entry must correspond to a real route.

        A stale entry means either:
          - The route was renamed / deleted (allowlist needs cleanup), or
          - The route's auth was upgraded to privileged (allowlist should shrink).

        This test prevents the allowlist from accumulating dead entries that
        mask future violations.
        """
        routes = _all_mutation_routes()
        all_bare_keys = {r.allowlist_key for r in routes if r.auth_level == "bare"}

        stale = sorted(_BARE_AUTH_ALLOWLIST - all_bare_keys)

        if stale:
            keys = "\n".join(f'    "{k}",' for k in stale)
            pytest.fail(
                f"\n{len(stale)} stale allowlist entry(ies) no longer match any bare route.\n"
                f"Remove them from the appropriate _AREA*_ROUTES set:\n\n"
                f"{keys}\n"
            )

    def test_allowlist_count_matches_scan(self) -> None:
        """
        Snapshot: total bare route count matches the allowlist size.

        This is a secondary sanity check. The exact count is documented
        here so that any bulk rename / deletion is visible in review diffs.

        Allowlist total at Phase A inventory (2026-06-08): 169 routes.
        """
        routes = _all_mutation_routes()
        bare_count = sum(1 for r in routes if r.auth_level == "bare")
        allowlist_size = len(_BARE_AUTH_ALLOWLIST)

        assert bare_count == allowlist_size, (
            f"Bare route count ({bare_count}) != allowlist size ({allowlist_size}).\n"
            f"If routes were added/removed, update the allowlist to match.\n"
            f"If the diff is negative (bare_count < allowlist_size), run "
            f"test_no_stale_allowlist_entries to find stale entries.\n"
            f"If the diff is positive (bare_count > allowlist_size), run "
            f"test_no_new_bare_mutation_routes to find new violations."
        )

    def test_scanner_finds_mutation_routes(self) -> None:
        """Smoke test: scanner must find at least 200 mutation routes total."""
        routes = _all_mutation_routes()
        assert len(routes) >= 200, (
            f"Scanner returned only {len(routes)} mutation routes — "
            "something is wrong with the AST analysis."
        )

    def test_privileged_routes_still_present(self) -> None:
        """Regression: Phase C upgrades must not accidentally remove real guards."""
        routes = _all_mutation_routes()
        privileged_count = sum(1 for r in routes if r.auth_level == "privileged")
        assert privileged_count >= 60, (
            f"Privileged route count dropped to {privileged_count} — "
            "a Phase C guard upgrade may have accidentally removed a real RBAC guard."
        )
