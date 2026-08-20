"""
test_product_resolution_invariants_awb6696117050.py — permanent regression fixture
for the AWB 6696117050 incident shape.

INCIDENT (2026-08-20). Batch SHIPMENT_6696117050_2026-08_100ab076, MRN
26PL44302D00KVH7R6, carried two product codes that existed nowhere yet:

    EJL/26-27/548-1  qty 1  @ 1649.1028 PLN   (RING, 14KT)
    EJL/26-27/549-1  qty 6  @ 6838.8889 PLN   (BRACELET, 18KT lab-grown)

Neither was in wfirma_product_mirror, and a live wFirma goods/find returned
found=false for both. The backend resolver was correct throughout — it searched
first, found nothing, and (with the create gate shut) reported them as missing.
The shipment nonetheless became a permanent dead end because the V2 UI discarded
the diagnosis. Resolution: the operator opened WFIRMA_CREATE_PRODUCT_ALLOWED, the
canonical resolver created each good exactly once (51825123, 51825187), persisted
both to the mirror, and preview flipped to ready=true.

WHAT THIS FILE PINS

The permanent product-identity contract, in the incident's own shape:

    local mirror lookup -> live wFirma search -> adopt exact existing product
    -> otherwise create exactly once if genuinely absent -> persist mirror
    -> recompute preview -> continue to PZ

Adopt-existing, create-absent-once, rerun-created=0, unresolved->resolved->ready,
and PZ second-create idempotency are already pinned in
test_wfirma_products_resolve.py, test_wfirma_pz_create.py and
test_wfirma_product_authority_endpoints.py; this file does NOT duplicate them.
It closes the four invariants that had no coverage, each of which is a "never"
from the permanent requirement:

  A. a lookup FAILURE must never be read as absence  (never create on error)
  B. an ambiguous / contested identity must never auto-create
  C. a create whose mirror write did not land must be ADOPTED on rerun,
     never created a second time  (persistence recovery)
  D. V1 and V2 must consume one authority — no second resolver, no V2 business logic

Written against the real route, not a stub (Lesson A).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List
from unittest.mock import patch

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


def _run_async(coro):
    """Own the loop — a bare get_event_loop() breaks after any asyncio.run()."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── The incident fixture ──────────────────────────────────────────────────────

_BATCH = "SHIPMENT_6696117050_2026-08_100ab076"
_CODE_RING = "EJL/26-27/548-1"
_CODE_BRAC = "EJL/26-27/549-1"

_AUDIT = {
    "batch_id": _BATCH,
    "status": "partial",                      # real stored status; in PZ_DONE
    "customs_declaration": {
        "mrn": "26PL44302D00KVH7R6",
        "clearance_date": "2026-08-20",
    },
    "inputs": {"zc429": "ZC429_26PL44302D00KVH7R6_1_PL.pdf"},
}


def _incident_rows() -> List[dict]:
    """The two real pz_rows.json rows, verbatim in shape and value."""
    return [
        {
            "product_code": _CODE_RING, "_product_code": _CODE_RING,
            "item_type": "RING",
            "description_en": "Diamond Studded 14KT Gold Jewellery RING",
            "pl_desc": "pierścionek ze złota próby 14 karatów wysadzany diamentami",
            "quantity": 1, "unit_netto_pln": 1649.1027701168912,
            "_unit_netto_pln": 1649.1027701168912,
            "invoice_no": "EJL/26-27/548",
        },
        {
            "product_code": _CODE_BRAC, "_product_code": _CODE_BRAC,
            "item_type": "BRACELET",
            "description_en": "Lab Grown Diamond Studded 18KT Gold Jewellery BRACELET",
            "pl_desc": "bransoletka ze złota próby 18 karatów z diamentami hodowanymi laboratoryjnie",
            "quantity": 6, "unit_netto_pln": 6838.888854980517,
            "_unit_netto_pln": 6838.888854980517,
            "invoice_no": "EJL/26-27/549",
        },
    ]


def _wfirma_product(wfirma_id: str, code: str, name: str = "x"):
    from app.services.wfirma_client import WFirmaProduct
    return WFirmaProduct(wfirma_id=wfirma_id, name=name, code=code)


def _resolve(tmp_path, *, search, create=None, register=None, cache=None, mirror=None):
    """Invoke the REAL resolver route with the incident rows.

    `search` / `create` / `register` are the three seams that decide identity.
    `mirror` is a live {product_code: wfirma_id} store: successful registrations
    write into it and the route's readiness recompute reads back from it, so a
    test can prove the full persist -> recompute -> ready chain rather than
    asserting against a frozen empty map.

    Returns (response_body, calls) where calls records what was actually invoked.
    """
    mirror = {} if mirror is None else mirror
    calls = {"search": [], "create": [], "register": []}

    def _search(code):
        calls["search"].append(code)
        return search(code)

    def _create_via_master(*a, **kw):
        calls["create"].append(kw.get("product_code") or (a[1] if len(a) > 1 else None))
        if create is None:
            raise AssertionError("create path must not run in this scenario")
        return create(*a, **kw)

    def _register(db_path, *, wfirma_id, product_code, cache_kwargs=None, **kw):
        calls["register"].append({"wfirma_id": wfirma_id, "product_code": product_code})
        outcome = ({"collision": False, "cache_row_id": len(calls["register"])}
                   if register is None
                   else register(wfirma_id=wfirma_id, product_code=product_code))
        # Only a NON-collided registration persists identity — a collision must
        # leave the mirror untouched, which is what makes the rerun re-search.
        if not outcome.get("collision"):
            mirror[product_code] = wfirma_id
        return outcome

    def _list_mirror(_db):
        return [{"product_code": pc, "wfirma_id": wid} for pc, wid in mirror.items()]

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=_incident_rows()),
        patch("app.api.routes_wfirma._par.get_registered_goods_state_batch",
              return_value=cache or {}),
        patch("app.api.routes_wfirma.rdb.lookup_wfirma_product", side_effect=_search),
        patch("app.api.routes_wfirma.rdb.register_product_identity", side_effect=_register),
        patch("app.api.routes_wfirma.rdb.create_wfirma_product_via_master",
              side_effect=_create_via_master),
        patch("app.api.routes_wfirma.rdb.upsert_product_master"),
        patch("app.api.routes_wfirma.rdb.set_product_master_status"),
        patch("app.api.routes_wfirma.rdb.list_mirror_products", side_effect=_list_mirror),
        patch("app.api.routes_wfirma.wfirma_client.find_vat_code_id", return_value="12345"),
        patch("app.api.routes_wfirma.settings") as mock_settings,
    ):
        mock_settings.wfirma_create_product_allowed = True     # gate OPEN on purpose
        mock_settings.wfirma_supplier_contractor_id = "38142296"
        mock_settings.wfirma_warehouse_id = "347088"
        mock_settings.storage_root = tmp_path
        from app.api.routes_wfirma import wfirma_products_resolve
        resp = _run_async(wfirma_products_resolve(_BATCH))
        return json.loads(resp.body), calls


# ── A. A lookup FAILURE is never absence ──────────────────────────────────────

def test_wfirma_lookup_failure_creates_nothing(tmp_path):
    """The gate is OPEN and the product is not mapped locally, but the live
    wFirma search ERRORS. That is 'unknown', not 'absent'. Creating here would
    duplicate a product that may well exist — the exact failure mode the
    permanent requirement forbids."""
    def boom(code):
        raise ConnectionError("wFirma API unreachable (simulated network failure)")

    body, calls = _resolve(tmp_path, search=boom, create=None)

    assert calls["create"] == [], (
        "a failed lookup was treated as absence and a product was created — "
        "this is the duplicate-inventory failure mode"
    )
    assert calls["register"] == [], "no identity may be persisted from a failed lookup"
    assert body["created"] == 0
    assert body["found_and_mapped"] == 0
    assert body["failed"] == 2, "both codes must be reported as FAILED, not missing"
    assert body["missing_codes"] == [], (
        "a lookup error must not be reported as 'missing' — missing means "
        "confirmed-absent, and would invite an operator to create a duplicate"
    )
    assert body["ready_for_pz"] is False


def test_lookup_failure_is_reported_as_retryable_not_absent(tmp_path):
    """The failure detail must name the search step, so the operator can tell a
    transient integration fault from a genuine new SKU."""
    def boom(code):
        raise TimeoutError("read timed out")

    body, _ = _resolve(tmp_path, search=boom, create=None)
    assert body["failed_details"], "a failed lookup must produce failure detail"
    for detail in body["failed_details"]:
        assert "goods/find" in detail["error"], (
            f"failure detail {detail!r} does not identify the search step"
        )


# ── B. Contested identity never auto-creates ──────────────────────────────────

def test_identity_collision_creates_nothing_and_is_surfaced(tmp_path):
    """wFirma returns a product whose wfirma_id is ALREADY owned by a different
    product_code in the mirror. Identity is contested — the resolver must refuse
    and surface it, never guess and never create a parallel good."""
    def found(code):
        # Both codes resolve to the SAME wfirma_id — a contested identity.
        return _wfirma_product("51825123", code)

    def register(*, wfirma_id, product_code):
        return {"collision": True, "owner": "EJL/26-27/999-1"}

    body, calls = _resolve(tmp_path, search=found, create=None, register=register)

    assert calls["create"] == [], "a contested identity must never trigger a create"
    assert body["created"] == 0
    assert body["found_and_mapped"] == 0, "a collided identity is not a successful mapping"
    assert body["failed"] == 2
    owners = [d.get("existing_owner") for d in body["failed_details"]]
    assert all(o == "EJL/26-27/999-1" for o in owners), (
        "the conflicting owner must be surfaced so an operator can resolve identity"
    )
    assert body["ready_for_pz"] is False


# ── C. Persistence recovery — never create twice ──────────────────────────────

def test_create_then_failed_mirror_write_is_adopted_on_rerun(tmp_path):
    """Run 1: the good is genuinely absent, is created, but the mirror write does
    not land (collision/crash). Run 2 MUST find the now-existing good by search
    and ADOPT it. Creating a second time would duplicate real inventory.

    This is the invariant that makes the resolver crash-safe: because search
    always precedes create, an interrupted run self-heals."""
    created_ids = {_CODE_RING: "51825123", _CODE_BRAC: "51825187"}
    wfirma_side: dict = {}          # what wFirma holds after run 1

    # ---- Run 1: absent -> created, but mirror persistence FAILS -------------
    def search_run1(code):
        return None                                     # genuinely absent

    def create_run1(*a, **kw):
        code = kw.get("product_code")
        wfirma_side[code] = created_ids[code]           # the good now EXISTS
        return (_wfirma_product(created_ids[code], code),
                {"collision": True, "owner": "OTHER/CODE"})

    mirror: dict = {}       # survives BOTH runs, as the real mirror would
    body1, calls1 = _resolve(tmp_path, search=search_run1, create=create_run1,
                             mirror=mirror)

    assert body1["created"] == 0, (
        "a create whose mirror write collided must NOT be counted as created"
    )
    assert body1["failed"] == 2
    assert body1["ready_for_pz"] is False
    assert wfirma_side == created_ids, "run 1 did leave real goods in wFirma"
    assert mirror == {}, (
        "the collided registration must NOT have persisted — otherwise run 2 "
        "would not re-search and the recovery path would be untested"
    )

    # ---- Run 2: search now finds them -> ADOPT, never create ----------------
    def search_run2(code):
        wid = wfirma_side.get(code)
        return _wfirma_product(wid, code) if wid else None

    body2, calls2 = _resolve(tmp_path, search=search_run2, create=None, mirror=mirror)

    assert calls2["create"] == [], (
        "RERUN CREATED A DUPLICATE — search-before-create did not protect the "
        "interrupted-persistence case"
    )
    assert body2["created"] == 0
    assert body2["found_and_mapped"] == 2, "both goods must be adopted on rerun"
    assert body2["ready_for_pz"] is True
    assert body2["unresolved_product_codes"] == []
    assert body2["price_conflicts"] == []
    # The adopted ids must be the ones wFirma actually returned — never invented.
    assert {r["wfirma_id"] for r in calls2["register"]} == set(created_ids.values())
    # persist -> recompute -> ready: the mirror now carries exactly one identity
    # per code, and readiness was derived from that store, not asserted directly.
    assert mirror == created_ids


def test_search_always_precedes_create(tmp_path):
    """Structural pin for 'never create before search': for every code that gets
    created, a search for that same code must have happened first."""
    order: List[str] = []

    def search(code):
        order.append(f"search:{code}")
        return None

    def create(*a, **kw):
        code = kw.get("product_code")
        order.append(f"create:{code}")
        return _wfirma_product("999", code), {"collision": False}

    _resolve(tmp_path, search=search, create=create)

    for code in (_CODE_RING, _CODE_BRAC):
        assert f"search:{code}" in order, f"no search was issued for {code}"
        assert f"create:{code}" in order, f"no create was issued for {code}"
        assert order.index(f"search:{code}") < order.index(f"create:{code}"), (
            f"{code} was created BEFORE it was searched — duplicate-creation risk"
        )


def test_absent_product_is_created_exactly_once_per_code(tmp_path):
    """Create-once, in the incident's own shape: two absent codes produce exactly
    two creates, never more, and each lands one mirror identity."""
    def search(code):
        return None

    def create(*a, **kw):
        code = kw.get("product_code")
        return _wfirma_product({"EJL/26-27/548-1": "51825123",
                                "EJL/26-27/549-1": "51825187"}[code], code), \
               {"collision": False}

    mirror: dict = {}
    body, calls = _resolve(tmp_path, search=search, create=create, mirror=mirror)

    assert calls["create"] == [_CODE_RING, _CODE_BRAC]
    assert len(calls["create"]) == len(set(calls["create"])) == 2
    assert body["created"] == 2
    assert body["ready_for_pz"] is True
    assert mirror == {_CODE_RING: "51825123", _CODE_BRAC: "51825187"}


# ── D. One authority — V1 and V2 parity ───────────────────────────────────────

_V1 = _svc / "app" / "static" / "shipment-detail.html"
_V2 = _svc / "app" / "static" / "v2" / "shipment-detail-page.jsx"
_V2_API = _svc / "app" / "static" / "v2" / "pz-api.js"

_CANONICAL_ENDPOINT = "wfirma/products/resolve"


def test_v1_and_v2_call_the_same_resolver_endpoint():
    v1 = _V1.read_text(encoding="utf-8", errors="replace")
    v2_api = _V2_API.read_text(encoding="utf-8", errors="replace")
    assert _CANONICAL_ENDPOINT in v1, "V1 lost the canonical resolver endpoint"
    assert _CANONICAL_ENDPOINT in v2_api, "V2 lost the canonical resolver endpoint"


def test_v1_and_v2_gate_resolve_on_the_same_lifecycle_field():
    """Both surfaces must obey the backend's single lifecycle authority rather
    than inventing their own visibility rule."""
    v1 = _V1.read_text(encoding="utf-8", errors="replace")
    v2 = _V2.read_text(encoding="utf-8", errors="replace")
    for name, src in (("V1", v1), ("V2", v2)):
        assert "hide_resolve_products" in src, (
            f"{name} does not consume pz_lifecycle.hide_resolve_products — "
            "duplicate UI authority"
        )


def test_exactly_one_resolver_owns_the_search_create_persist_chain():
    """Proof of no duplicate authority: the batch search->create->mirror chain
    must be implemented in exactly one route module."""
    api_dir = _svc / "app" / "api"
    owners = []
    for path in sorted(api_dir.glob("routes_*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        if f"/{_CANONICAL_ENDPOINT}" in src and "@router.post" in src:
            # only count a module that DEFINES the route, not one that mentions it
            if f'"/shipment/{{batch_id}}/{_CANONICAL_ENDPOINT}"' in src:
                owners.append(path.name)
    assert owners == ["routes_wfirma.py"], (
        f"the canonical batch resolver must have exactly one owner, found: {owners}"
    )


def test_shipment_detail_v2_does_not_drive_product_identity_itself():
    """No V2 business logic on the shipment page: it may fire the canonical
    resolver, never drive search/create/adopt itself.

    Deliberately scoped to the PAGE, not to pz-api.js. pz-api.js is the transport
    layer (Lesson F) and legitimately carries a read-only `goods/search` wrapper
    used by other surfaces; banning the string there would be an over-broad pin
    of exactly the kind test-baseline.md already records twice.
    """
    src = _V2.read_text(encoding="utf-8", errors="replace")
    for forbidden in ("goods/add", "goods/search", "goods/create-and-adopt",
                      "goods/adopt", "goods/update-and-adopt"):
        assert forbidden not in src, (
            f"shipment-detail-page.jsx references {forbidden!r} — product "
            "identity is a backend authority"
        )


def test_v2_resolver_wrapper_is_transport_only():
    """The resolver wrapper in pz-api.js must be a bare POST — no branching, no
    retry policy, no identity decisions smuggled into the transport layer."""
    src = _V2_API.read_text(encoding="utf-8", errors="replace")
    idx = src.index("wfirmaProductsResolve")
    defn = src[idx: idx + 240]
    assert "_postM(" in defn, "resolver wrapper must post via the shared helper"
    for smell in ("if (", "catch", "while (", "for ("):
        assert smell not in defn, (
            f"transport wrapper contains {smell!r} — logic belongs in the backend"
        )


def test_mirror_schema_is_the_only_identity_store():
    """No second mirror: wfirma_product_mirror stays exactly the six permitted
    columns (MASTER CONSUMPTION RULE)."""
    from app.services import reservation_db as rdb  # noqa: PLC0415

    src = Path(rdb.__file__).read_text(encoding="utf-8", errors="replace")
    idx = src.index("wfirma_product_mirror")
    block = src[idx: idx + 900]
    for col in ("wfirma_id", "product_code", "sync_version",
                "last_sync", "hash", "deleted_flag"):
        assert col in block, f"mirror lost the {col!r} column"
