#!/usr/bin/env python
"""
review_seed.py — deterministic GATE-6 review-data seeder (non-production).

Builds ONE coherent two-client transport scenario in an ISOLATED review storage
root by calling the application's CANONICAL service/persistence writers (imported
from the served tree via --app-dir): it constructs canonical input objects
(ShipmentResult via compute_idempotency_key) and calls the real writers
(auto_create_draft_from_sales_packing, create_pending_link/mark_issued,
insert_shipment/update_state, upsert_product_local) — it never re-implements
shipment / invoice-link / CMR / packing business logic. It shares the exact safety
gate with review_launch.py.

Scenario (deterministic constants, batch REVIEW-GATE6-940):
  * 2 per-client proforma drafts (Alpha / Beta) with distinct client_contractor_id.
  * Client Alpha: invoice link ISSUED with a full human number  "FV 7/2026".
  * Client Beta : NO issued invoice link            → honest-null invoice number.
  * Carrier shipments (SHADOW only): Alpha client_ref=REV-A (AWB, distinct dims),
    Beta client_ref=REV-B (AWB, distinct service product), plus a LEGACY row with
    client_ref=NULL (drives the legacy-rebook path; attributed only to single-client
    batches, so it must NOT leak to Alpha/Beta here).
  * product_local.origin_country = "IN" for the seeded product codes → #940's CMR
    ISO→full-country rendering shows "India".

Safety: refuses unless the process env is review-safe (delegates to review_launch)
AND the storage root is isolated AND the target DBs are empty unless
--reset-review-data. Emits <storage-root>/review-manifest.json. --reset-review-data
removes ONLY the isolated review storage.

Usage:
  python review_seed.py --app-dir <extracted>/service --storage-root <isolated> \
        --commit 13d442e9 [--reset-review-data]
  python review_seed.py --storage-root <isolated> --reset-review-data   # teardown only
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Reuse the ONE safety authority (same dir).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_launch as guard  # noqa: E402

# ── Deterministic scenario constants ──────────────────────────────────────────
BATCH = "REVIEW-GATE6-940"
ALPHA = {"client_name": "Review Client Alpha", "contractor_id": "REV-A",
         "client_ref": "REV-A", "product_code": "RVW-RING-A", "design_no": "RG-A-001",
         "awb": "AWB1000000001", "service_product": "EXPRESS_WORLDWIDE",
         "dimensions": {"length": 20, "width": 15, "height": 10}, "weight_kg": 1.5,
         "invoice_number": "FV 7/2026", "invoice_id": "REVINV7001",
         "proforma_id": "REVPRO7001", "proforma_number": "PROF 7/2026"}
BETA = {"client_name": "Review Client Beta", "contractor_id": "REV-B",
        "client_ref": "REV-B", "product_code": "RVW-PEND-B", "design_no": "PD-B-002",
        "awb": "AWB2000000002", "service_product": "EXPRESS_WORLDWIDE_NONDOC",
        "dimensions": {"length": 30, "width": 25, "height": 5}, "weight_kg": 2.5,
        "proforma_id": "REVPRO8002", "proforma_number": "PROF 8/2026"}
LEGACY_AWB = "AWB0000000000"  # legacy NULL-client_ref row
ORIGIN_ISO = "IN"            # #940 CMR renders → "India"

_DB_FILES = ("proforma_links.db", "master_data.sqlite",
             "carrier/carrier_shipments.db")


def _storage(args_storage_root: str) -> Path:
    sr = Path(args_storage_root).resolve()
    guard._assert_isolated_storage(sr)  # refuse a live/production root
    return sr


def _target_dbs_nonempty(sr: Path) -> list[str]:
    present = []
    for rel in _DB_FILES:
        if (sr / rel).exists():
            present.append(rel)
    return present


def _reset(sr: Path) -> None:
    guard._assert_isolated_storage(sr)   # double-check before any delete
    if sr.exists():
        # NOT ignore_errors: a silent partial delete (e.g. a running server holding
        # a SQLite/WAL lock) would leave a dirty DB that then re-seeds into duplicate
        # or mixed-schema state. Fail loudly instead.
        shutil.rmtree(sr, ignore_errors=False)
    if sr.exists():
        guard._refuse(f"reset did not fully remove {sr} (is a review server still "
                      "running against it? stop it first).")
    print(f"[review_seed] reset: removed isolated review storage {sr}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed(sr: Path, app_dir: Path, commit: str) -> dict:
    """Seed via canonical APIs imported from the served tree."""
    sys.path.insert(0, str(app_dir))
    # Canonical persistence/service modules (no logic duplicated here).
    from app.services import proforma_invoice_link_db as pildb
    from app.services import master_data_db as mddb
    from app.services.carrier.persistence import shipment_db as cardb
    from app.services.carrier.models.shipment import (
        ShipmentMode, ShipmentResult, ShipmentState, ShipmentRequest,
        compute_idempotency_key,
    )

    links_db = sr / "proforma_links.db"
    master_db = sr / "master_data.sqlite"
    carrier_db = sr / "carrier" / "carrier_shipments.db"
    carrier_db.parent.mkdir(parents=True, exist_ok=True)

    pildb.init_db(links_db)
    cardb.init_db(carrier_db)

    # #940 added per-client scoping (client_ref) to insert_shipment. Detect it so
    # this seeder stays reusable on trees that predate #940 (degrades to batch-only
    # scoping there instead of crashing).
    import dataclasses
    import inspect
    # #940 added per-client scoping (client_ref) to BOTH ShipmentRequest and
    # insert_shipment. Detect it so this seeder stays reusable on trees that
    # predate #940 (degrades to batch-only scoping there instead of crashing).
    _req_has_client_ref = any(
        f.name == "client_ref" for f in dataclasses.fields(ShipmentRequest))
    _insert_has_client_ref = "client_ref" in inspect.signature(
        cardb.insert_shipment).parameters
    _carrier_client_scoped = _req_has_client_ref and _insert_has_client_ref

    def _line(c):
        return {"product_code": c["product_code"], "design_no": c["design_no"],
                "quantity": 3, "unit_price": 100.0, "currency": "EUR",
                "price_source": "review-seed", "client_ref": c["client_ref"]}

    # 1) Two per-client drafts (canonical draft authority).
    draft_ids = {}
    for c in (ALPHA, BETA):
        draft, _ = pildb.auto_create_draft_from_sales_packing(
            links_db, batch_id=BATCH, client_name=c["client_name"], currency="EUR",
            lines=[_line(c)], operator="review-seed",
            client_contractor_id=c["contractor_id"],
        )
        draft_ids[c["contractor_id"]] = getattr(draft, "id", None)

    # 2) Alpha → issued proforma + ISSUED invoice link (full human number).
    pildb.mark_draft_issued(links_db, BATCH, ALPHA["client_name"],
                            wfirma_proforma_id=ALPHA["proforma_id"],
                            wfirma_proforma_fullnumber=ALPHA["proforma_number"])
    link = pildb.ProformaInvoiceLink(
        proforma_id=ALPHA["proforma_id"], proforma_number=ALPHA["proforma_number"],
        converted_at=_now(), operator="review-seed",
        source_total=Decimal("369.00"), currency="EUR", status="pending",
    )
    pildb.create_pending_link(links_db, link)
    pildb.mark_issued(links_db, ALPHA["proforma_id"],
                      invoice_id=ALPHA["invoice_id"],
                      invoice_number=ALPHA["invoice_number"],
                      invoice_total=Decimal("369.00"))
    # Beta: mark the proforma issued but leave the invoice link ABSENT → honest-null.
    pildb.mark_draft_issued(links_db, BATCH, BETA["client_name"],
                            wfirma_proforma_id=BETA["proforma_id"],
                            wfirma_proforma_fullnumber=BETA["proforma_number"])

    # 3) product_local origin_country = IN (CMR → India) for both product codes.
    for c in (ALPHA, BETA):
        mddb.upsert_product_local(master_db, {"product_code": c["product_code"],
                                              "origin_country": ORIGIN_ISO})

    # 4) Carrier shipments (SHADOW only). client_ref supported on this (#940) tree.
    def _shadow(req: ShipmentRequest) -> ShipmentResult:
        return ShipmentResult(idempotency_key=compute_idempotency_key(req),
                              mode=ShipmentMode.SHADOW, state=ShipmentState.PENDING,
                              simulated=True,
                              service_product=req.customer_reference,
                              dimensions_json=json.dumps(req.dimensions))

    def _mk_request(*, shipper_account, recipient, declared_value, weight_kg,
                    dimensions, customer_reference, client_ref):
        kw = dict(batch_id=BATCH, shipper_account=shipper_account,
                  recipient_address=recipient, declared_value=declared_value,
                  currency="EUR", weight_kg=weight_kg, dimensions=dimensions,
                  customer_reference=customer_reference)
        if _req_has_client_ref:
            kw["client_ref"] = client_ref
        return ShipmentRequest(**kw)

    def _book(c, client_ref):
        req = _mk_request(shipper_account="REVIEW",
                          recipient={"company": c["client_name"]},
                          declared_value=369.0, weight_kg=c["weight_kg"],
                          dimensions=c["dimensions"],
                          customer_reference=c["service_product"],
                          client_ref=client_ref)
        res = _shadow(req)
        if _carrier_client_scoped:
            cardb.insert_shipment(carrier_db, res, BATCH, client_ref=client_ref)
        else:
            cardb.insert_shipment(carrier_db, res, BATCH)
        cardb.update_state(carrier_db, res.idempotency_key, ShipmentState.COMPLETE,
                           tracking_ref=c["awb"])
        return res.idempotency_key

    key_a = _book(ALPHA, ALPHA["client_ref"])
    key_b = _book(BETA, BETA["client_ref"])
    # Legacy NULL-client_ref row (distinct base request → distinct idempotency key).
    legacy_req = _mk_request(shipper_account="REVIEW-LEGACY", recipient={},
                             declared_value=1.0, weight_kg=9.9, dimensions={},
                             customer_reference=None, client_ref=None)
    legacy_res = _shadow(legacy_req)
    if _carrier_client_scoped:
        cardb.insert_shipment(carrier_db, legacy_res, BATCH, client_ref=None)
    else:
        cardb.insert_shipment(carrier_db, legacy_res, BATCH)
    cardb.update_state(carrier_db, legacy_res.idempotency_key,
                       ShipmentState.COMPLETE, tracking_ref=LEGACY_AWB)

    return {
        "batch_id": BATCH,
        "clients": {
            "alpha": {"client_name": ALPHA["client_name"],
                      "client_ref": ALPHA["client_ref"],
                      "draft_id": draft_ids.get("REV-A"),
                      "expected_awb": ALPHA["awb"],
                      "expected_invoice_number": ALPHA["invoice_number"],
                      "carrier_idempotency_key": key_a},
            "beta": {"client_name": BETA["client_name"],
                     "client_ref": BETA["client_ref"],
                     "draft_id": draft_ids.get("REV-B"),
                     "expected_awb": BETA["awb"],
                     "expected_invoice_number": None,  # honest-null
                     "carrier_idempotency_key": key_b},
        },
        "legacy_shipment": {"client_ref": None, "expected_awb": LEGACY_AWB,
                            "idempotency_key": legacy_res.idempotency_key},
        "cmr_origin_iso": ORIGIN_ISO,
        "carrier_client_scoped": _carrier_client_scoped,
    }


def _write_manifest(sr: Path, commit: str, scenario: dict) -> Path:
    version = {}
    vjson = sr / "version.json"
    if vjson.exists():
        version = json.loads(vjson.read_text(encoding="utf-8"))
    manifest = {
        "kind": "gate6-review-manifest",
        "generated_at": _now(),
        "served_commit": version.get("commit", commit),
        "storage_root": str(sr),
        "db_files": [str(sr / f) for f in _DB_FILES],
        "review_api_key_fingerprint":
            "sha256:" + __import__("hashlib").sha256(
                (__import__("os").environ.get("API_KEY", "")).encode()).hexdigest()[:16],
        "scenario": scenario,
        "live_write_disabled": {
            "carrier_api_status": __import__("os").environ.get("CARRIER_API_STATUS"),
            "carrier_live_allowlist_empty":
                __import__("os").environ.get("CARRIER_LIVE_ALLOWLIST", "") == "",
            "dhl_credentials_present": any(
                __import__("os").environ.get(k, "").strip()
                for k in guard._LIVE_CREDENTIAL_KEYS if k.startswith("DHL")),
            "wfirma_credentials_present": any(
                __import__("os").environ.get(k, "").strip()
                for k in guard._LIVE_CREDENTIAL_KEYS if k.startswith("WFIRMA")),
            "write_flags_on": [k for k in guard._WRITE_FLAG_KEYS
                               if guard._is_truthy(__import__("os").environ.get(k))],
        },
    }
    path = sr / "review-manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Deterministic GATE-6 review seeder.")
    p.add_argument("--storage-root", required=True)
    p.add_argument("--app-dir", default="")
    p.add_argument("--commit", default="",
                   help="Served git SHA (recorded in the manifest); required to seed.")
    p.add_argument("--reset-review-data", action="store_true")
    args = p.parse_args(argv)

    sr = _storage(args.storage_root)

    if args.reset_review_data:
        _reset(sr)
        if not args.app_dir:
            return 0  # teardown-only

    if not args.app_dir:
        guard._refuse("--app-dir is required to seed (points at the served tree).")
    if not args.commit.strip():
        guard._refuse("--commit is required to seed (recorded in the manifest for traceability).")
    app_dir = Path(args.app_dir).resolve()
    if not (app_dir / "app" / "main.py").is_file():
        guard._refuse(f"--app-dir {app_dir} does not contain app/main.py")

    # Lock the process into a review-safe env (same authority as the launcher) so
    # any canonical service that reads settings sees isolated storage + no creds.
    guard._neutralise_and_configure(sr, __import__("os").environ.get("API_KEY", "")
                                    or ("rev_" + __import__("secrets").token_urlsafe(24)))

    nonempty = _target_dbs_nonempty(sr)
    if nonempty and not args.reset_review_data:
        guard._refuse(
            f"target review DBs already present {nonempty}; pass --reset-review-data "
            "to re-seed from a deterministic clean state.")

    scenario = _seed(sr, app_dir, args.commit)
    manifest_path = _write_manifest(sr, args.commit, scenario)
    print(f"[review_seed] seeded batch {BATCH}; manifest -> {manifest_path}")
    print(json.dumps(scenario, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
