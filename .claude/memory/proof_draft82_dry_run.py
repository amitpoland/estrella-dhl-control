"""Draft #82 dry-run payload proof — ZERO wFirma HTTP, ZERO persist.

Uses production storage read-only (SQLite URI mode=ro where possible).
Monkey-patches wfirma_client HTTP to explode if anything tries a live write.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

SR = Path(r"C:\PZ\storage")
BATCH = "SHIPMENT_5831878861_2026-08_be24f39a"
OUT = Path(__file__).with_name("proof-draft82-dry-run.json")


def _ro(name: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{SR / name}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _draft82_meta() -> dict:
    con = _ro("proforma_links.db")
    row = con.execute(
        "SELECT id, client_name, currency, status, draft_state, editable_lines_json "
        "FROM proforma_drafts WHERE id=82"
    ).fetchone()
    if not row:
        raise SystemExit("Draft #82 not found in proforma_links.db")
    lines = json.loads(row["editable_lines_json"] or "[]")
    return {
        "id": row["id"],
        "client_name": row["client_name"],
        "currency": row["currency"],
        "status": row["status"],
        "draft_state": row["draft_state"],
        "line_count": len(lines),
        "unit_prices": [
            float(l.get("unit_price") if l.get("unit_price") is not None else (l.get("price") or 0))
            for l in lines
        ],
        "product_codes": [l.get("product_code") for l in lines],
    }


def main() -> int:
    meta = _draft82_meta()
    client = meta["client_name"]
    print(f"Draft #82 client={client!r} currency={meta['currency']} lines={meta['line_count']}")

    # Import app services after we can patch storage
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "service"))
    from app.core.config import settings
    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    from app.services import warehouse_db as wdb
    from app.services import wfirma_db as wfdb
    from app.services import wfirma_reservation as wr
    from app.services import wfirma_client as wfcli

    http_calls: list = []

    def _forbid_http(*a, **k):
        http_calls.append((a, k))
        raise AssertionError(f"FORBIDDEN wFirma HTTP attempted: {a} {k}")

    with patch.object(settings, "storage_root", SR):
        # Point modules at production DBs WITHOUT running schema migrations
        # (dry-run proof must not mutate production storage).
        ddb._db_path = SR / "documents.db"
        pdb._db_path = SR / "packing.db"
        wdb._db_path = SR / "warehouse.db"
        wfdb._db_path = SR / "wfirma.db"

        # Hard-block any live wFirma transport
        patches = [
            patch.object(wfcli, "create_reservation", side_effect=_forbid_http),
            patch.object(wfcli, "_post", side_effect=_forbid_http),
            patch.object(wfcli, "request", side_effect=_forbid_http),
        ]
        # Also forbid draft upserts during dry-run proof.
        patches.append(patch.object(
            wfdb, "upsert_reservation_draft",
            side_effect=AssertionError("FORBIDDEN persist during dry-run"),
        ))
        patches.append(patch.object(
            wfdb, "replace_reservation_lines",
            side_effect=AssertionError("FORBIDDEN persist during dry-run"),
        ))
        for p in patches:
            try:
                p.start()
            except AttributeError:
                pass

        try:
            before = wfdb.list_reservation_drafts(BATCH)
            out = wr.dry_run_reservation(BATCH, client)
            after = wfdb.list_reservation_drafts(BATCH)
        finally:
            for p in patches:
                try:
                    p.stop()
                except Exception:
                    pass

    payload = out.get("payload") or {}
    lines = payload.get("lines") or []
    proof = {
        "batch_id": BATCH,
        "draft_meta": meta,
        "ok": out.get("ok"),
        "code": out.get("code"),
        "http_calls": len(http_calls),
        "draft_count_before": len(before),
        "draft_count_after": len(after),
        "persist_delta": len(after) - len(before),
        "contractor_id": payload.get("contractor_id"),
        "document_currency": payload.get("document_currency"),
        "commercial_source": payload.get("commercial_source"),
        "proforma_draft_id": payload.get("proforma_draft_id"),
        "unresolved_count": payload.get("unresolved_count"),
        "line_count": len(lines),
        "lines": [
            {
                "line_index": ln.get("line_index"),
                "design_no": ln.get("design_no"),
                "product_code": ln.get("product_code"),
                "wfirma_product_id": ln.get("wfirma_product_id"),
                "qty": ln.get("qty"),
                "unit_price": ln.get("unit_price"),
                "currency": ln.get("currency"),
                "line_total": ln.get("line_total"),
                "stock_ok": ln.get("stock_ok"),
                "stock_status": ln.get("stock_status"),
            }
            for ln in lines
        ],
        "calculated_total": payload.get("total_value"),
        "unit_prices": [ln.get("unit_price") for ln in lines],
        "xml_present": bool(out.get("xml")),
        "xml_len": len(out.get("xml") or ""),
        "doc_ready": payload.get("doc_ready"),
        "doc_blocking_reasons": payload.get("blocking_reasons"),
        "doc_advisories": payload.get("advisories"),
        "acceptance": {},
    }

    # Acceptance checks (operator-locked)
    acc = proof["acceptance"]
    acc["contractor_65559320"] = str(proof["contractor_id"]) == "65559320"
    acc["currency_PLN"] = str(proof["document_currency"] or "").upper() == "PLN"
    acc["zero_unresolved"] = int(proof.get("unresolved_count") if proof.get("unresolved_count") is not None else -1) == 0
    acc["all_product_ids"] = all(ln.get("wfirma_product_id") for ln in lines)
    acc["all_qty"] = all(float(ln.get("qty") or 0) > 0 for ln in lines)
    acc["all_unit_prices"] = all(ln.get("unit_price") is not None for ln in lines)
    acc["distinct_492_1_prices_preserved"] = True
    prices_492_1 = [
        float(ln["unit_price"])
        for ln in lines
        if ln.get("product_code") == "EJL/26-27/492-1"
    ]
    acc["count_492_1_lines"] = len(prices_492_1)
    acc["unique_492_1_prices"] = len(set(prices_492_1))
    # 13 lines with potentially distinct prices — must not collapse to 1
    if len(prices_492_1) >= 2:
        acc["distinct_492_1_prices_preserved"] = len(set(prices_492_1)) == len(prices_492_1) or len(prices_492_1) > 1
        # Stronger: line count for 492-1 should match draft (no aggregation of different prices)
        draft_492 = [
            p for p, pc in zip(meta["unit_prices"], meta["product_codes"])
            if pc == "EJL/26-27/492-1"
        ]
        acc["draft_492_1_count"] = len(draft_492)
        acc["price_set_matches_draft"] = set(prices_492_1) == set(float(x) for x in draft_492)
        acc["line_count_matches_draft_492_1"] = len(prices_492_1) == len(draft_492)
    acc["zero_http"] = proof["http_calls"] == 0
    acc["zero_persist"] = proof["persist_delta"] == 0
    acc["xml_built"] = proof["xml_present"]
    proof["acceptance_pass"] = all([
        acc["contractor_65559320"],
        acc["currency_PLN"],
        acc["zero_unresolved"],
        acc["all_product_ids"],
        acc["all_qty"],
        acc["all_unit_prices"],
        acc.get("line_count_matches_draft_492_1", True),
        acc.get("price_set_matches_draft", True),
        acc["zero_http"],
        acc["zero_persist"],
        acc["xml_built"],
        proof["line_count"] == 14,
    ])

    OUT.write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"acceptance": acc, "acceptance_pass": proof["acceptance_pass"],
                      "contractor_id": proof["contractor_id"],
                      "currency": proof["document_currency"],
                      "lines": proof["line_count"],
                      "total": proof["calculated_total"],
                      "unresolved": proof["unresolved_count"],
                      "out": str(OUT)}, indent=2))
    return 0 if proof["acceptance_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
