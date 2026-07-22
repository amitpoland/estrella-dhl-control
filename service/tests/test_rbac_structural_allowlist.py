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
# PHASE C AREA 1 COMPLETE (2026-06-08) — all 33 routes upgraded to privileged guards.
# routes_action_proposals: require_role("admin","logistics","accounts") [5]
# routes_correction_registry: require_admin [1]
# routes_customer_master: require_admin [2]
# routes_dashboard: require_admin (DELETE+override+restore) + require_role(...) (ops) [16]
# routes_monitor: require_admin [1]
# routes_orchestrator: require_admin [2]
# routes_proposals: require_role("admin","logistics","accounts") [3]
# routes_settings: require_admin [1]
# routes_suppliers: require_admin [2]
_AREA1_ROUTES: frozenset[str] = frozenset()

# Area 2 — DHL ops
# PHASE C AREA 2 COMPLETE (2026-06-08) — 18 routes upgraded to require_role("admin","logistics").
# routes_agency: require_role [1]
# routes_dhl_clearance: require_role (7 operator routes; 2 scheduler routes retained below) [7]
# routes_dhl_documents: require_role [2]
# routes_dhl_followup: require_role [4]
# routes_dsk: require_role [2]
# routes_tracking: require_role (batch/update + cowork-result) [2]
_AREA2_ROUTES: frozenset[str] = frozenset({
    # AUTOMATION — Windows Task Scheduler (API key callers); cannot use require_role.
    # Lane A: dhl-email-auto-scan.ps1 — confirmed X-API-Key caller.
    # Lane B: scheduled follow-up; same pattern when Lane B .ps1 is written.
    "routes_dhl_clearance.py:POST:/scheduled-inbox-check",
    "routes_dhl_clearance.py:POST:/scheduled-followup-check",
    # Deferred to later area — not in Area 2 implementation scope.
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
    # ── Wave 5–7 additions (recorded 2026-07-13) ──────────────────────────────
    # Operator-facing PZ / warehouse / intake / inventory surfaces added across
    # Waves 5–7. All are session-cookie operator actions with NO api-key-only
    # automation caller (verified: no .ps1 / scripts caller; only static UI JS).
    # They remain bare pending the Area 3 guard burn-down (every Area 3 sibling
    # above is still bare — upgrading these individually would fork the area).
    "routes_inventory.py:POST:/fiscal-reconciliation/run",
    "routes_inventory_returns.py:POST:/pieces/{piece_id}/correction/archive-proposal",
    "routes_inventory_returns.py:POST:/pieces/{piece_id}/correction/identity",
    "routes_inventory_returns.py:POST:/pieces/{piece_id}/qc-disposition",
    "routes_inventory_returns.py:POST:/pieces/{piece_id}/reversal/{reversal_target}",
    "routes_packing.py:DELETE:/{batch_id}/document/{document_id}",
    "routes_packing.py:POST:/{batch_id}/approve-header-mapping",
    "routes_packing.py:POST:/{batch_id}/manual-sales-allocation",
    "routes_packing.py:POST:/{batch_id}/scored-pending/confirm",
    "routes_packing.py:POST:/{batch_id}/suggest-column-mapping",
    "routes_supplier_invoice_ocr.py:POST:/upload",
    # NB: routes_upload document delete/replace are NOT listed here — Wave 8
    # hardening (PR #910, MEDIUM-2) upgraded both to _write_auth (privileged),
    # so they are no longer bare and must not appear in this allowlist.
    "routes_warehouse_receipt.py:POST:/confirm",
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
    "routes_proforma.py:POST:/draft/{draft_id}/send-email",
    "routes_proforma.py:POST:/draft/{draft_id}/service-charges",
    # 2026-07-17 consolidation: both to-invoice execute routes upgraded to
    # _auth_write (privileged) — removed from the bare allowlist.
    "routes_proforma.py:POST:/preview/{batch_id}/{client_name:path}",
    "routes_proforma.py:POST:/service-charges/{batch_id}/{client_name:path}",
    "routes_proforma.py:POST:/{wfirma_id}/refresh-line-names",
    "routes_proforma.py:PUT:/service-products/{charge_type}",
    "routes_proforma_adopt.py:POST:/adopt-issued/{batch_id}",
    "routes_proforma_adopt.py:POST:/enrich-fullnumber/{batch_id}",
    "routes_reservations.py:POST:/products/import-purchase-packing",
    "routes_reservations.py:POST:/reservations/import-sales-packing",
    "routes_reservations.py:POST:/reservations/process-pending",
    "routes_reservations.py:POST:/reservations/{queue_id}/reset",
    "routes_reservations.py:POST:/wfirma/products/sync-by-codes",
    # ── Wave 5–7 additions (recorded 2026-07-13) ──────────────────────────────
    # Proforma draft edit/conflict/pricing operator surfaces + product-master
    # auto-sync trigger added across Waves 5–7. Session-cookie operator actions
    # with NO api-key-only automation caller (verified: static UI JS only).
    # Bare pending the Area 4 guard burn-down (all Area 4 siblings above are
    # still bare).
    "routes_proforma.py:DELETE:/draft/{draft_id}",
    "routes_proforma.py:POST:/draft/{draft_id}/apply-customer-address",
    "routes_proforma.py:POST:/draft/{draft_id}/apply-service-charges",
    "routes_proforma.py:POST:/draft/{draft_id}/conflicts/scan",
    "routes_proforma.py:POST:/draft/{draft_id}/conflicts/{conflict_id}/resolve",
    "routes_proforma.py:POST:/draft/{draft_id}/import-sales-prices",
    "routes_proforma.py:POST:/draft/{draft_id}/resolve-ambiguity",
    # 2B manual wFirma link: read-only PREVIEW POST on require_api_key. Writes
    # nothing (pinned by test_resolve_writes_nothing / test_resolve_no_remote_mutation);
    # the state-changing confirm-wfirma-link sits on require_api_key_privileged and
    # is intentionally NOT here. Same read-only-POST shape as resolve-ambiguity above.
    "routes_proforma.py:POST:/draft/{draft_id}/resolve-wfirma-document",
    "routes_reservations.py:POST:/product-master/sync/{batch_id}",
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
    # /customers/sync-from-wfirma/apply upgraded to require_admin (Wave 8
    # hardening MEDIUM-1) — parity with routes_customer_master; now privileged.
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
    # ── Wave 5–7 additions (recorded 2026-07-13) ──────────────────────────────
    # wFirma / accounting-sensitive / carrier surfaces added across Waves 5–7.
    # carrier /events/process is the carrier-webhook event processor (Run Now +
    # webhook automation origin). The rest are session-cookie operator "Run Now"
    # / edit surfaces with NO api-key-only automation caller (verified: static
    # UI JS only; no .ps1 / scripts caller). Bare pending the Area 5 guard
    # burn-down (all Area 5 siblings above are still bare).
    "routes_carrier_actions.py:POST:/{batch_id}/shipment/{tracking_ref}/do-not-use",
    "routes_carrier_shadow.py:POST:/events/process",
    "routes_description_admin.py:POST:/product/{product_code:path}/validate",
    "routes_description_admin.py:PUT:/product/{product_code:path}",
    "routes_wfirma_capabilities.py:POST:/shipment/{batch_id:path}/adopt-pending-found",
    "routes_wfirma_contractors.py:POST:/contractors/scan",
    "routes_wfirma_sync_pull.py:POST:/payments-pull",
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

        Allowlist total at Phase A inventory (2026-06-08): 167 routes.
        (Updated 2026-06-08: -5 stale from deleted files, +3 new from ingestion sprint PRs.)
        (Phase C Area 1 complete 2026-06-08: -33 routes upgraded to privileged. Total: 134.)
        (Phase C Area 2 complete 2026-06-08: -18 routes upgraded to privileged. Total: 116.)
        (Wave 5–7 drift reconciliation 2026-07-13: +29 new bare routes allowlisted
         across Areas 3–5; routes_customer_master validate-vat upgraded to _write_auth
         (-0 net, not allowlisted). Total: 145.)
        (Wave 8 reconciliation into PR #910 2026-07-13: -1 wfirma customers
         sync-from-wfirma/apply upgraded to require_admin (MEDIUM-1); -2 routes_upload
         document delete/replace upgraded to _write_auth (MEDIUM-2), so both were
         withheld from the Area 3 additions above. Net Wave 5–7 additions: 27.
         Total: 142.)
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
