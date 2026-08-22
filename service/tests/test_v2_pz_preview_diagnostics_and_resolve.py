"""
test_v2_pz_preview_diagnostics_and_resolve.py — V2 Shipment Detail must consume
the canonical pz_preview authority instead of collapsing it to "Preview not ready".

Incident (AWB 6696117050, 2026-08-20): a shipment with PZ generated, SAD present
and both totals correct could not be exported. The backend preview authority was
correct and explicit — ready=false, blockers=[], unresolved_product_codes=
["EJL/26-27/548-1", "EJL/26-27/549-1"], pz_lifecycle.hide_resolve_products=false.
V2 dropped all of it:

  * it read only `blocking_reasons || blockers` (blockers rows are OBJECTS, so a
    non-empty list would have rendered "[object Object]"), never
    `unresolved_product_codes` / `price_conflicts` / `engine_error`;
  * it had no Resolve Products control at all, although V1 (shipment-detail.html)
    has had one since PR #281 — a Lesson M capability regression in the V2
    migration, which made an ordinary resolvable state a permanent dead end.

The repair is UI-only: the search → adopt → create-once product authority
(`POST …/wfirma/products/resolve`) already existed and is unchanged. These
assertions are the regression fence — static source-grep only, no server.
"""
from __future__ import annotations

from pathlib import Path

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_DETAIL = _V2 / "shipment-detail-page.jsx"
_API = _V2 / "pz-api.js"


def _detail() -> str:
    return _DETAIL.read_text(encoding="utf-8")


def _api() -> str:
    return _API.read_text(encoding="utf-8")


# ── A. Diagnostics are surfaced, not collapsed ────────────────────────────────

def test_preview_reasons_helper_exists():
    """A single helper renders the backend's preview diagnostics."""
    assert "_pzPreviewReasons" in _detail(), (
        "V2 has no pz_preview diagnostics renderer — export failures collapse "
        "to a generic message again"
    )


def test_unresolved_product_codes_are_rendered():
    src = _detail()
    assert "unresolved_product_codes" in src, (
        "V2 never reads unresolved_product_codes — the operator cannot see WHICH "
        "product codes block the export"
    )


def test_price_conflicts_are_rendered():
    assert "price_conflicts" in _detail(), (
        "V2 never reads price_conflicts — a real pricing blocker would show as "
        "a generic 'not ready'"
    )


def test_blocker_rows_are_read_as_objects_not_joined_as_strings():
    """`blockers` rows are {code, message, severity, source}. Joining the raw
    array yields '[object Object]'."""
    src = _detail()
    assert "b.message" in src, (
        "blocker rows must be read via .message — a bare join over blockers "
        "renders [object Object]"
    )
    assert "(pdata.blocking_reasons || pdata.blockers || []).join" not in src, (
        "the old string-join over blocker OBJECTS is back"
    )


def test_generic_message_is_only_the_last_fallback():
    """'Preview not ready' may remain, but only when the backend supplied
    nothing at all."""
    src = _detail()
    assert src.count("'Preview not ready'") <= 2, (
        "'Preview not ready' is used in more places than the helper's fallbacks "
        "— diagnostics are being discarded again"
    )


def test_blockers_panel_has_testid():
    assert 'data-testid="pz-preview-blockers"' in _detail(), (
        "no operator-visible panel for preview blockers"
    )


# ── B. Resolve Products capability (Lesson M — present in V1, must exist in V2) ─

def test_api_wrapper_targets_the_canonical_resolve_endpoint():
    api = _api()
    assert "wfirmaProductsResolve" in api, "V2 API wrapper has no products/resolve transport"
    assert "wfirma/products/resolve" in api, (
        "the resolve wrapper does not point at the canonical backend endpoint"
    )


def test_resolve_button_is_wired_to_the_wrapper():
    src = _detail()
    # DhlActionButton renders its `testid` prop as data-testid on the button.
    assert 'testid="resolve-products"' in src, "V2 has no Resolve Products control"
    assert "window.PzApi.wfirmaProductsResolve(batchId)" in src, (
        "Resolve Products is not wired to the canonical API wrapper"
    )


def test_resolve_visibility_obeys_the_backend_lifecycle_authority():
    """V1 hides the control when pz_lifecycle says so (e.g. PZ_RECOVERY_REQUIRED).
    V2 must obey the same single authority instead of inventing its own rule."""
    assert "hide_resolve_products" in _detail(), (
        "V2 ignores pz_lifecycle.hide_resolve_products — duplicate UI authority"
    )


def test_unresolvable_code_names_the_operator_gate_not_a_dead_end():
    """When a code is genuinely absent from wFirma and the create gate is shut,
    the operator must be told which gate — otherwise Resolve looks like a no-op."""
    src = _detail()
    assert "missing_codes" in src, "V2 discards the resolver's missing_codes"
    assert "WFIRMA_CREATE_PRODUCT_ALLOWED" in src, (
        "V2 never names the create gate — an absent product reads as an "
        "unexplained dead end instead of an operator decision"
    )
    assert "create_product_allowed" in src, (
        "the gate state must be read from the capabilities authority, not assumed"
    )


def test_preview_is_reloaded_after_resolve():
    src = _detail()
    assert "doResolveProducts" in src and "loadPreview" in src, (
        "resolve must re-read the preview authority; a stale preview leaves the "
        "operator looking at a blocker that no longer exists"
    )


# ── C. No duplicate product authority in the frontend ─────────────────────────

def test_v2_does_not_implement_its_own_search_or_create(  # noqa: D103
) -> None:
    src = _detail()
    for forbidden in ("goods/add", "goods/search", "create-and-adopt", "goods/adopt"):
        assert forbidden not in src, (
            f"V2 references {forbidden!r} — product search/create/adopt is a "
            "backend authority; the frontend must only call products/resolve"
        )


def test_v2_does_not_force_readiness():
    src = _detail()
    assert "ready = true" not in src and "ready: true" not in src, (
        "V2 must never synthesise readiness — pz_preview.ready is the authority"
    )
