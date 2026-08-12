"""Read-only Customer Master usage projection over existing stores.

Authority: Customer Master presents counts; packing / proforma / carrier stores remain
owners of their rows. No usage DB. No wFirma calls. No name-only carrier matching —
shipments resolve via draft/document batch_id lineage only.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


_RECENT = 5


def _connect_ro(path: Path) -> Optional[sqlite3.Connection]:
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def _bucket(
    count: int,
    recent: Sequence[Dict[str, Any]],
    *,
    source: str,
    note: str = "",
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "count": int(count),
        "recent_refs": list(recent),
        "source": source,
    }
    if note:
        out["note"] = note
    return out


def _sales_packing(docs_db: Path, cid: str, limit: int) -> Tuple[Dict[str, Any], List[str]]:
    batch_ids: List[str] = []
    con = _connect_ro(docs_db)
    if con is None:
        return _bucket(0, [], source="documents.db.sales_documents", note="db_missing"), batch_ids
    try:
        rows = con.execute(
            """
            SELECT id, batch_id, sales_doc_no, client_name, created_at
            FROM sales_documents
            WHERE TRIM(COALESCE(client_contractor_id,'')) = ?
            ORDER BY datetime(COALESCE(updated_at, created_at)) DESC, id DESC
            """,
            (cid,),
        ).fetchall()
        count = len(rows)
        recent = []
        for r in rows[:limit]:
            bid = (r["batch_id"] or "").strip()
            if bid:
                batch_ids.append(bid)
            recent.append({
                "id": r["id"],
                "batch_id": bid,
                "ref": (r["sales_doc_no"] or r["client_name"] or r["id"] or "").strip(),
                "created_at": r["created_at"],
            })
        return _bucket(count, recent, source="documents.db.sales_documents"), batch_ids
    except sqlite3.OperationalError as exc:
        return (
            _bucket(0, [], source="documents.db.sales_documents", note=f"query_error:{exc}"),
            batch_ids,
        )
    finally:
        con.close()


def _purchase_packing(docs_db: Path, cid: str, limit: int) -> Tuple[Dict[str, Any], List[str]]:
    """Client-linked purchase packing via shipment_documents — not packing.db (supplier)."""
    batch_ids: List[str] = []
    con = _connect_ro(docs_db)
    if con is None:
        return _bucket(0, [], source="documents.db.shipment_documents", note="db_missing"), batch_ids
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(shipment_documents)").fetchall()}
        if "client_contractor_id" not in cols:
            return (
                _bucket(
                    0,
                    [],
                    source="documents.db.shipment_documents",
                    note="client_contractor_id column absent",
                ),
                batch_ids,
            )
        name_col = "original_filename" if "original_filename" in cols else (
            "filename" if "filename" in cols else "id"
        )
        rows = con.execute(
            f"""
            SELECT id, batch_id, {name_col} AS ref_name, document_type, created_at
            FROM shipment_documents
            WHERE document_type = 'purchase_packing_list'
              AND TRIM(COALESCE(client_contractor_id,'')) = ?
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            (cid,),
        ).fetchall()
        count = len(rows)
        recent = []
        for r in rows[:limit]:
            bid = (r["batch_id"] or "").strip()
            if bid:
                batch_ids.append(bid)
            recent.append({
                "id": r["id"],
                "batch_id": bid,
                "ref": (r["ref_name"] or r["id"] or "").strip(),
                "created_at": r["created_at"],
            })
        return (
            _bucket(
                count,
                recent,
                source="documents.db.shipment_documents",
                note="client_contractor_id on purchase_packing_list only",
            ),
            batch_ids,
        )
    except sqlite3.OperationalError as exc:
        return (
            _bucket(0, [], source="documents.db.shipment_documents", note=f"query_error:{exc}"),
            batch_ids,
        )
    finally:
        con.close()


def _proformas_and_invoices(
    links_db: Path, cid: str, limit: int
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    batch_ids: List[str] = []
    con = _connect_ro(links_db)
    if con is None:
        empty = _bucket(0, [], source="proforma_links.db.proforma_drafts", note="db_missing")
        inv = _bucket(0, [], source="proforma_links.db.proforma_invoice_links", note="db_missing")
        return empty, inv, batch_ids
    try:
        drafts = con.execute(
            """
            SELECT id, batch_id, client_name, status, draft_state,
                   wfirma_proforma_fullnumber, wfirma_proforma_id, created_at
            FROM proforma_drafts
            WHERE TRIM(COALESCE(client_contractor_id,'')) = ?
            ORDER BY datetime(COALESCE(updated_at, created_at)) DESC, id DESC
            """,
            (cid,),
        ).fetchall()
        pf_recent = []
        draft_ids: List[str] = []
        for r in drafts[:limit]:
            bid = (r["batch_id"] or "").strip()
            if bid:
                batch_ids.append(bid)
            did = str(r["id"])
            draft_ids.append(did)
            ref = (
                (r["wfirma_proforma_fullnumber"] or "").strip()
                or (r["wfirma_proforma_id"] or "").strip()
                or (r["client_name"] or "").strip()
                or did
            )
            pf_recent.append({
                "id": r["id"],
                "batch_id": bid,
                "ref": ref,
                "status": r["status"],
                "draft_state": r["draft_state"] if "draft_state" in r.keys() else None,
                "created_at": r["created_at"],
            })
        proformas = _bucket(
            len(drafts), pf_recent, source="proforma_links.db.proforma_drafts"
        )

        # Invoices via issued links for this client's drafts (proforma_id / draft id)
        inv_rows = con.execute(
            """
            SELECT l.id, l.proforma_id, l.invoice_id, l.invoice_number, l.status,
                   l.converted_at, d.batch_id
            FROM proforma_invoice_links l
            JOIN proforma_drafts d
              ON TRIM(COALESCE(d.wfirma_proforma_id,'')) = TRIM(COALESCE(l.proforma_id,''))
                 OR CAST(d.id AS TEXT) = TRIM(COALESCE(l.proforma_id,''))
            WHERE TRIM(COALESCE(d.client_contractor_id,'')) = ?
              AND TRIM(COALESCE(l.invoice_id,'')) <> ''
            ORDER BY datetime(COALESCE(l.converted_at, '')) DESC, l.id DESC
            """,
            (cid,),
        ).fetchall()
        # Dedup by invoice_id
        seen = set()
        inv_recent = []
        for r in inv_rows:
            iid = (r["invoice_id"] or "").strip()
            if not iid or iid in seen:
                continue
            seen.add(iid)
            bid = (r["batch_id"] or "").strip()
            if bid:
                batch_ids.append(bid)
            if len(inv_recent) < limit:
                inv_recent.append({
                    "id": r["id"],
                    "invoice_id": iid,
                    "ref": (r["invoice_number"] or iid).strip(),
                    "proforma_id": r["proforma_id"],
                    "batch_id": bid,
                    "status": r["status"],
                    "created_at": r["converted_at"],
                })
        invoices = _bucket(
            len(seen),
            inv_recent,
            source="proforma_links.db.proforma_invoice_links",
        )
        return proformas, invoices, batch_ids
    except sqlite3.OperationalError as exc:
        # Table/column drift — honest empty with note
        note = f"query_error:{exc}"
        return (
            _bucket(0, [], source="proforma_links.db.proforma_drafts", note=note),
            _bucket(0, [], source="proforma_links.db.proforma_invoice_links", note=note),
            batch_ids,
        )
    finally:
        con.close()


def _shipments_via_batches(
    carrier_db: Path, batch_ids: Sequence[str], limit: int
) -> Dict[str, Any]:
    unique = []
    seen_b = set()
    for b in batch_ids:
        b = (b or "").strip()
        if b and b not in seen_b:
            seen_b.add(b)
            unique.append(b)
    if not unique:
        return _bucket(
            0,
            [],
            source="carrier_shipments via batch lineage",
            note="no_linked_batches",
        )
    con = _connect_ro(carrier_db)
    if con is None:
        return _bucket(
            0,
            [],
            source="carrier/carrier_shipments.db",
            note="db_missing",
        )
    try:
        placeholders = ",".join("?" for _ in unique)
        rows = con.execute(
            f"""
            SELECT id, batch_id, client_ref, tracking_ref, state, created_at
            FROM carrier_shipments
            WHERE batch_id IN ({placeholders})
              AND COALESCE(state,'') != 'failed'
            ORDER BY datetime(COALESCE(updated_at, created_at)) DESC, id DESC
            """,
            tuple(unique),
        ).fetchall()
        # Prefer distinct tracking_ref / id
        seen = set()
        recent = []
        for r in rows:
            key = (r["tracking_ref"] or "").strip() or str(r["id"])
            if key in seen:
                continue
            seen.add(key)
            if len(recent) < limit:
                recent.append({
                    "id": r["id"],
                    "batch_id": r["batch_id"],
                    "awb": (r["tracking_ref"] or "").strip(),
                    "client_ref": r["client_ref"],
                    "state": r["state"],
                    "created_at": r["created_at"],
                })
        return _bucket(
            len(seen),
            recent,
            source="carrier_shipments via batch lineage",
            note="joined through documents/proforma batch_id — not client_ref name match",
        )
    except sqlite3.OperationalError as exc:
        return _bucket(
            0,
            [],
            source="carrier/carrier_shipments.db",
            note=f"query_error:{exc}",
        )
    finally:
        con.close()


def project_customer_usage(
    storage_root: Path,
    contractor_id: str,
    *,
    customer_identity: Optional[Dict[str, Any]] = None,
    recent_limit: int = _RECENT,
) -> Dict[str, Any]:
    cid = (contractor_id or "").strip()
    root = Path(storage_root)
    docs_db = root / "documents.db"
    links_db = root / "proforma_links.db"
    # Prefer storage_root/carrier/carrier_shipments.db; fall back to flat path
    carrier_db = root / "carrier" / "carrier_shipments.db"
    if not carrier_db.exists():
        alt = root / "carrier_shipments.db"
        if alt.exists():
            carrier_db = alt

    sales, sales_batches = _sales_packing(docs_db, cid, recent_limit)
    purchase, purchase_batches = _purchase_packing(docs_db, cid, recent_limit)
    proformas, invoices, draft_batches = _proformas_and_invoices(
        links_db, cid, recent_limit
    )
    lineage_batches = sales_batches + purchase_batches + draft_batches
    shipments = _shipments_via_batches(carrier_db, lineage_batches, recent_limit)

    sources_ok = {
        "documents_db": docs_db.exists(),
        "proforma_links_db": links_db.exists(),
        "carrier_shipments_db": carrier_db.exists(),
    }
    return {
        "customer_identity": customer_identity
        or {"bill_to_contractor_id": cid},
        "sales_packing": sales,
        "purchase_packing": purchase,
        "proformas": proformas,
        "invoices": invoices,
        "shipments": shipments,
        "source_health": {
            "ok": any(sources_ok.values()),
            "sources": sources_ok,
            "join_rule": "client_contractor_id exact; carrier via batch_id lineage only",
        },
    }
