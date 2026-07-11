"""Shared Client-Balance Read Authority — pins (pz-api.js + ledgers-page.jsx).

Campaign: eliminate the duplicate live ``GET /api/v1/ledgers/clients?limit=100``
read. Accounting Overview (``PzApi.listClientBalances({limit:100})``) and the
embedded Client Ledger page (previously ``EstrellaShared.apiFetch(...)``) issued
two independent live wFirma-backed roster reads per hub navigation. This slice
routes both through ONE short-lived, parameter-keyed, in-flight-aware cache
inside the PzApi transport authority.

Convention note: this repository has NO JavaScript test runtime — every V2 pin
(e.g. test_ledgers_page_live_wiring.py, test_pz_api_proforma_bridge.py) is a
Python source-assertion test. These pins therefore prove the *structure* that
guarantees each behaviour (in-flight coalescing, TTL reuse, forced refresh,
failure eviction, parameter isolation, preserved contract). The *runtime*
behaviour (one network request serves both consumers; Refresh issues exactly one
new request) is proven separately by the browser network evidence recorded in the
Phase-8 certification (Implementation Plan §7).

Governance: transport-layer caching only; Refresh bypasses cache; no fabricated
accounting data; no persistent browser storage; backend remains source of truth.
"""
from __future__ import annotations

import re
from pathlib import Path

_V2      = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
_PZ_API  = _V2 / "pz-api.js"
_LEDGERS = _V2 / "ledgers-page.jsx"


def _api() -> str:
    return _PZ_API.read_text(encoding="utf-8", errors="replace")


def _ledgers() -> str:
    return _LEDGERS.read_text(encoding="utf-8", errors="replace")


def _cache_region() -> str:
    """The shared-cache block only: from the cache declaration to the start of the
    frozen public object. Scopes 'no storage / no balance math' checks so they are
    not confused by unrelated PzApi code (e.g. the operator-name localStorage)."""
    src = _api()
    start = src.index("const _clientBalancesCache")
    end = src.index("window.PzApi = Object.freeze(")
    return src[start:end]


# ── Cache authority exists, in-process, param-keyed (Rules 6,7,9) ─────────────

def test_shared_cache_is_in_process_map():
    region = _cache_region()
    assert "_clientBalancesCache = new Map()" in region, (
        "Shared roster cache must be an in-process Map (Rule 7: cache only in "
        "process memory — not a second service, not persistent storage)"
    )


def test_no_persistent_browser_storage_in_cache():
    region = _cache_region()
    for banned in ("localStorage", "sessionStorage"):
        assert banned not in region, (
            f"Shared roster cache must not use {banned} (Rule 7 — in-process only)"
        )


def test_no_balance_math_introduced_in_cache():
    """Rule 17: the transport must never calculate authoritative financial values.
    The cache block only manages promises + timestamps; it performs no arithmetic
    on balances."""
    region = _cache_region()
    for token in ("parseFloat", "Decimal", ".toFixed(", "Number(", ".reduce("):
        assert token not in region, (
            f"Balance-math token '{token}' in the shared-read cache — the backend "
            "owns all financial calculation; transport must not compute values"
        )


def test_cache_key_is_resolved_query_string():
    """Rule 9 + Rule 14: the key is the fully-resolved query string, so distinct
    parameter sets (e.g. limit=25 vs limit=100) never share an entry."""
    region = _cache_region()
    assert "URLSearchParams(params)" in region, (
        "Cache key must derive from the fully-resolved query params"
    )
    assert "const key = _clientBalancesQs(params)" in region, (
        "Shared fetch must key the cache by the resolved query string"
    )


# ── In-flight coalescing + TTL reuse (Rules 8,10) ────────────────────────────

def test_inflight_promise_stored_immediately_for_coalescing():
    """Rule 10: the in-flight promise is stored synchronously, so two concurrent
    identical calls receive the SAME promise → one network request."""
    region = _cache_region()
    assert "entry.promise = _apiFetch(" in region, (
        "The in-flight promise must be created from the shared transport"
    )
    assert "_clientBalancesCache.set(key, entry)" in region, (
        "The entry (with its in-flight promise) must be stored immediately"
    )
    assert "return hit.promise" in region, (
        "A fresh cache hit must return the same (possibly in-flight) promise so "
        "concurrent identical calls coalesce into one request"
    )


def test_short_ttl_window_5_to_10s():
    """Rule 8: a short TTL (~5–10s) briefly reuses a successful result, then a
    later call refetches."""
    region = _cache_region()
    m = re.search(r"_CLIENT_BALANCES_TTL_MS\s*=\s*(\d+)", region)
    assert m, "TTL constant _CLIENT_BALANCES_TTL_MS must be defined"
    ttl = int(m.group(1))
    assert 5000 <= ttl <= 10000, f"TTL {ttl}ms must be short (~5–10s), got {ttl}"
    assert "(now - hit.at) < _CLIENT_BALANCES_TTL_MS" in region, (
        "Reuse must be gated by the TTL window (age since insertion)"
    )


# ── Forced refresh + failure eviction (Rules 11,12,13) ───────────────────────

def test_force_evicts_then_performs_new_request():
    region = _cache_region()
    assert "if (force) {" in region and "_clientBalancesCache.delete(key)" in region, (
        "force=true must evict the matching entry before performing a new request "
        "(Rule 13 — manual Refresh bypasses the cache)"
    )


def test_failure_evicts_entry_and_rethrows_original():
    region = _cache_region()
    assert ".catch((err) =>" in region, "Shared fetch must handle rejection"
    assert "if (_clientBalancesCache.get(key) === entry) _clientBalancesCache.delete(key)" in region, (
        "A rejected request must evict its OWN entry immediately (Rule 11), "
        "identity-checked so a newer force-refresh entry is never dropped"
    )
    assert "throw err;" in region, (
        "The original error must be propagated unchanged (Rule 12), never a "
        "wrapped/synthesised error, and never cached"
    )


# ── Public contract preserved + raw method exposed (Impl. steps 12,13) ───────

def test_list_client_balances_delegates_and_preserves_contract():
    """Overview + AccClientBalance callers stay byte-identical: listClientBalances
    still returns { ok, data } / { ok:false, ... }, now backed by the shared cache."""
    api = _api()
    assert "listClientBalances:" in api, "listClientBalances must still be exposed"
    assert "_fetchClientBalancesShared(params, false)" in api, (
        "listClientBalances must delegate to the shared cache (force=false)"
    )
    assert "({ ok: true, data })" in api, (
        "Success contract { ok, data } must be preserved for existing callers"
    )
    assert "ok:     false" in api or "ok: false" in api, (
        "Error contract { ok:false, status, error, type } must be preserved"
    )


def test_shared_raw_method_exposed_and_backed_by_same_fetch():
    api = _api()
    assert "listClientBalancesShared:" in api, (
        "A raw shared method must be exposed for the Client Ledger page"
    )
    assert "_fetchClientBalancesShared(params, !!(opts && opts.force))" in api, (
        "listClientBalancesShared must delegate to the SAME shared fetch and honour "
        "an explicit { force } option"
    )


def test_both_callers_back_onto_one_shared_fetch():
    """Both public methods route through _fetchClientBalancesShared, so both
    consumers receive the same result for identical params."""
    api = _api()
    assert api.count("_fetchClientBalancesShared(") >= 3, (
        "Expected the shared fetch to be defined once and consumed by both "
        "listClientBalances and listClientBalancesShared"
    )


# ── Client Ledger page wiring (Impl. steps 14,16,17) ─────────────────────────

def test_client_ledger_roster_uses_shared_method():
    led = _ledgers()
    assert "window.PzApi.listClientBalancesShared({ limit: 100 }" in led, (
        "Client Ledger roster load must use the shared PzApi method (limit=100)"
    )
    # The old independent direct roster read must be gone (no duplicate live read).
    assert "apiFetch('/api/v1/ledgers/clients?limit=100')" not in led, (
        "The page's own direct /ledgers/clients?limit=100 read must be removed — "
        "the roster now shares Accounting Overview's single read"
    )


def test_client_ledger_refresh_forces_fresh_read():
    led = _ledgers()
    assert "force: refreshKey > 0" in led, (
        "Manual ↻ Refresh (refreshKey > 0) must force a real new backend read, "
        "bypassing the shared cache; the initial mount (refreshKey === 0) shares it"
    )


def test_statement_reads_unchanged_still_direct():
    """Only the roster read is shared. The per-client statement JSON/PDF reads are
    out of scope and must remain on the existing transport untouched."""
    led = _ledgers()
    assert "/statement.json" in led and "/statement.pdf" in led, (
        "Statement JSON + PDF authority reads must remain intact (unchanged scope)"
    )
