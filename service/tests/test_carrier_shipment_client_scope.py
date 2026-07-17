"""Per-client carrier shipment ownership — 2026-07-16 cross-client AWB leak fix.

One import batch is split into several per-client proforma drafts. The carrier
shipment belongs to exactly one client, so a draft must never resolve to another
client's AWB/CMR. These tests pin:

  * client_ref is stored and round-trips
  * compute_idempotency_key is client-scoped (different clients ⇒ different keys)
    and byte-identical to the pre-change key when client_ref is absent
  * get_shipment_for_draft: exact per-client match, honest-missing for a
    multi-client batch with no exact row, and the single-client legacy fallback
  * the GET route retains distinct AWBs across A→B→A navigation (no leak)

All tests use tmp_path. No production paths. No live calls.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
    compute_idempotency_key,
)
from app.services.carrier.persistence.shipment_db import (
    get_shipment,
    get_shipment_for_draft,
    init_db,
    insert_shipment,
    update_state,
)
from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb


def _db(tmp_path):
    path = tmp_path / "carrier_shipments.db"
    init_db(path)
    return path


def _seed_proforma_drafts(storage_root, batch_id, client_names):
    """Seed proforma_links.db under *storage_root* with one active v=1 draft per
    client name, via the canonical create-path (no raw SQL). This is exactly what
    `_batch_not_multi_client` reads (settings.storage_root / "proforma_links.db")
    to decide whether the batch is single- or multi-client. Returns the db path."""
    link_db = storage_root / "proforma_links.db"
    pildb.init_db(link_db)
    line = [{"product_code": "RNG-1", "design_no": "D1", "qty": 1, "unit_price": 10.0,
             "currency": "EUR", "price_source": "sales_packing_list"}]
    for cn in client_names:
        pildb.auto_create_draft_from_sales_packing(
            link_db, batch_id=batch_id, client_name=cn,
            currency="EUR", lines=line, operator="test")
    return link_db


def _pending(key: str) -> ShipmentResult:
    return ShipmentResult(
        idempotency_key=key,
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING,
        simulated=True,
    )


def _book(db, key, batch, client_ref, awb):
    """Insert a PENDING per-client row then complete it with an AWB."""
    insert_shipment(db, _pending(key), batch, client_ref)
    update_state(db, key, ShipmentState.COMPLETE, tracking_ref=awb)


def _req(batch="B1", client_ref=None) -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=batch,
        shipper_account="ACC",
        recipient_address={},
        declared_value=100.0,
        currency="EUR",
        weight_kg=1.0,
        dimensions={},
        client_ref=client_ref,
    )


# ── client_ref persistence ────────────────────────────────────────────────────


def test_client_ref_round_trips(tmp_path):
    db = _db(tmp_path)
    insert_shipment(db, _pending("k1"), "B1", "Client A")
    row = get_shipment(db, "k1")
    assert row["client_ref"] == "Client A"


def test_client_ref_defaults_null_for_legacy_callers(tmp_path):
    db = _db(tmp_path)
    insert_shipment(db, _pending("k1"), "B1")  # no client_ref
    row = get_shipment(db, "k1")
    assert row["client_ref"] is None


# ── idempotency key is client-scoped ───────────────────────────────────────────


def test_idempotency_key_differs_by_client(tmp_path):
    a = compute_idempotency_key(_req(client_ref="Client A"))
    b = compute_idempotency_key(_req(client_ref="Client B"))
    assert a != b


def test_idempotency_key_backward_compatible_without_client(tmp_path):
    """No client_ref ⇒ exactly the pre-change key (legacy rows unaffected)."""
    import hashlib
    import json
    r = _req(client_ref=None)
    legacy = hashlib.sha256(
        json.dumps(
            {
                "batch_id": r.batch_id,
                "shipper_account": r.shipper_account,
                "weight_kg": r.weight_kg,
                "declared_value": r.declared_value,
                "currency": r.currency,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert compute_idempotency_key(r) == legacy


# ── resolver: exact match, honest-missing, single-client fallback ──────────────


def test_exact_per_client_match_no_leak(tmp_path):
    db = _db(tmp_path)
    _book(db, "kA", "B1", "Client A", "AWB-A")
    _book(db, "kB", "B1", "Client B", "AWB-B")

    a = get_shipment_for_draft(db, "B1", "Client A")
    b = get_shipment_for_draft(db, "B1", "Client B")
    assert a["tracking_ref"] == "AWB-A"
    assert b["tracking_ref"] == "AWB-B"


def test_multi_client_no_exact_row_is_honest_missing(tmp_path):
    """A client with no booking must NOT inherit a sibling's row, even with
    the single-client fallback allowed (batch is not single-client)."""
    db = _db(tmp_path)
    _book(db, "kA", "B1", "Client A", "AWB-A")
    _book(db, "kB", "B1", "Client B", "AWB-B")

    # Client C has no shipment; fallback allowed but batch has >1 row ⇒ None.
    assert get_shipment_for_draft(
        db, "B1", "Client C", allow_single_client_fallback=True
    ) is None


def test_single_client_legacy_fallback_resolves(tmp_path):
    """A legacy NULL-client_ref row is attributed to the draft only when the
    batch is single-client (exactly one row)."""
    db = _db(tmp_path)
    _book(db, "kLegacy", "B1", None, "AWB-LEGACY")

    row = get_shipment_for_draft(
        db, "B1", "Client A", allow_single_client_fallback=True
    )
    assert row is not None
    assert row["tracking_ref"] == "AWB-LEGACY"


def test_single_client_fallback_denied_when_not_single(tmp_path):
    db = _db(tmp_path)
    _book(db, "k1", "B1", None, "AWB-1")
    _book(db, "k2", "B1", None, "AWB-2")
    # Two rows ⇒ ambiguous ⇒ honest-missing even with fallback allowed.
    assert get_shipment_for_draft(
        db, "B1", "Client A", allow_single_client_fallback=True
    ) is None


def test_fallback_disabled_by_default(tmp_path):
    db = _db(tmp_path)
    _book(db, "kLegacy", "B1", None, "AWB-LEGACY")
    # Default allow_single_client_fallback=False ⇒ no exact row ⇒ None.
    assert get_shipment_for_draft(db, "B1", "Client A") is None


# ── route: A→B→A retains distinct AWBs (no cross-draft leak) ────────────────────


def _client_for(db_path):
    from app.api import routes_carrier_actions as rca
    from app.api.routes_carrier_actions import router
    from app.core.security import require_api_key

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[rca._get_carrier_config] = lambda: object()
    app.dependency_overrides[rca._get_shipment_db_path] = lambda: db_path
    return TestClient(app)


def test_route_A_B_A_no_awb_leak(tmp_path):
    db = _db(tmp_path)
    _book(db, "kA", "B1", "Client A", "AWB-A")
    _book(db, "kB", "B1", "Client B", "AWB-B")
    client = _client_for(db)

    def awb(cn):
        r = client.get(f"/api/v1/carrier/B1/shipment?client_ref={cn}")
        assert r.status_code == 200, r.text
        return r.json()["tracking_ref"]

    assert awb("Client A") == "AWB-A"
    assert awb("Client B") == "AWB-B"
    assert awb("Client A") == "AWB-A"  # back to A — still A, never B


def test_route_unknown_client_multi_batch_404(tmp_path):
    db = _db(tmp_path)
    _book(db, "kA", "B1", "Client A", "AWB-A")
    _book(db, "kB", "B1", "Client B", "AWB-B")
    client = _client_for(db)
    r = client.get("/api/v1/carrier/B1/shipment?client_ref=Client%20C")
    assert r.status_code == 404


def test_fallback_never_returns_other_clients_scoped_row(tmp_path):
    """Defence-in-depth (2026-07-16 review POST-1): even with the fallback gate
    OPEN (simulating a misfired/absent multi-client check), a single row scoped
    to a DIFFERENT client must never be attributed to the requestor. Only a
    legacy NULL-client_ref row may fall back."""
    db = _db(tmp_path)
    _book(db, "kA", "B1", "Client A", "AWB-A")   # scoped to A, only row in batch

    # Client B must NOT inherit A's row even though the batch is single-row
    # and the caller (wrongly) allows the fallback.
    assert get_shipment_for_draft(
        db, "B1", "Client B", allow_single_client_fallback=True
    ) is None

    # The owner still resolves via exact match; an unscoped (no client_ref)
    # legacy-style read of a single-row batch still resolves.
    assert get_shipment_for_draft(
        db, "B1", "Client A", allow_single_client_fallback=True
    )["tracking_ref"] == "AWB-A"
    assert get_shipment_for_draft(
        db, "B1", None, allow_single_client_fallback=True
    )["tracking_ref"] == "AWB-A"


# ── route path: `_batch_not_multi_client` proforma-DB guard (2026-07-17 gate) ───
# The pre-existing route tests above override `_get_shipment_db_path` but NOT
# `settings.storage_root`, so the proforma multi-client guard read by the route
# (`allow_single_client_fallback=_batch_not_multi_client(batch_id)`) was never
# exercised — the batch always looked single-client (no proforma_links.db). These
# tests seed the canonical proforma_links.db so the guard fires through the route,
# and prove the 404 is caused by the proforma guard, NOT carrier-side row logic.


def test_route_no_client_ref_multi_client_proforma_denies_legacy_fallback(tmp_path, monkeypatch):
    """No-client_ref GET on a MULTI-CLIENT proforma batch that has a single legacy
    NULL-client_ref carrier row → 404. `_batch_not_multi_client` counts 2 distinct
    client drafts, denies the single-row fallback, and the legacy AWB is NOT returned."""
    carrier_db = _db(tmp_path)
    _book(carrier_db, "kLegacy", "MC1", None, "AWB-LEGACY")          # ONE legacy NULL-client row
    _seed_proforma_drafts(tmp_path, "MC1", ["Client A", "Client B"])  # TWO distinct clients
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    client = _client_for(carrier_db)

    r = client.get("/api/v1/carrier/MC1/shipment")   # NO client_ref
    assert r.status_code == 404, r.text
    assert "AWB-LEGACY" not in r.text                # no legacy shipment payload leaks


def test_route_no_client_ref_single_client_proforma_resolves_legacy(tmp_path, monkeypatch):
    """CAUSATION CONTROL — identical carrier state (the SAME single legacy row), but a
    SINGLE-CLIENT proforma batch → `_batch_not_multi_client` allows the fallback → 200
    with the legacy AWB. The ONLY variable vs the 404 test is the proforma client count,
    proving the 404 is caused by the proforma multi-client guard, not by carrier-side
    duplicate-row logic (there is exactly ONE carrier row in both cases)."""
    carrier_db = _db(tmp_path)
    _book(carrier_db, "kLegacy", "SC1", None, "AWB-LEGACY")   # SAME single legacy row
    _seed_proforma_drafts(tmp_path, "SC1", ["Client A"])      # ONE client only
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    client = _client_for(carrier_db)

    r = client.get("/api/v1/carrier/SC1/shipment")   # NO client_ref
    assert r.status_code == 200, r.text
    assert r.json()["tracking_ref"] == "AWB-LEGACY"


def test_batch_not_multi_client_reads_proforma_db(tmp_path, monkeypatch):
    """Direct unit pin on the guard function itself (the specific untested surface):
    it reads settings.storage_root/proforma_links.db and returns False for a
    multi-client batch, True for a single-client batch, and True when the proforma DB
    is absent (permissive — no proforma data to contradict)."""
    from app.api.routes_carrier_actions import _batch_not_multi_client

    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    assert _batch_not_multi_client("ABSENT") is True          # no proforma_links.db yet

    _seed_proforma_drafts(tmp_path, "B1", ["Client A", "Client B"])
    _seed_proforma_drafts(tmp_path, "B2", ["Client A"])
    assert _batch_not_multi_client("B1") is False             # 2 distinct clients → deny fallback
    assert _batch_not_multi_client("B2") is True              # 1 client → allow fallback
