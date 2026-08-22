"""Quarantine duplicated packing lines. Reversible by construction.

A file ingested twice produced two rows for one commercial line. The rows are
identified by ``packing_line_key`` and classified by ``classify_key_collision``;
this module removes the surplus copies from the live set.

It never DELETEs. Every removed row is copied whole into ``packing_line_quarantine``
as JSON, keyed by a ``repair_ref`` that names the run. ``restore`` puts them back.
That is the reversal path, and it is the same mechanism in both directions rather
than a script that has to be written correctly twice.

Deliberately NOT here:
  * anything that touches a customs figure. ``customs_declarations`` carries mrn,
    duty_pln, total_cif_usd and statistical_value_pln, all sourced from the ZC429
    declaration rather than from packing lines, so no customs value can move.
  * anything that touches wFirma. Verified: the affected batches carry only
    ``status='pending'`` reservation drafts with a NULL ``wfirma_reservation_id``.
  * an operator's confirmation. `operator_review_status='confirmed'` is a human
    decision about a specific row, and generic completeness scoring knows nothing
    about it. A confirmation therefore outranks completeness, and a group whose
    surplus still carries one the survivor lacks is deferred rather than decided.
  * inventory_state. A row there is an assertion about physical goods; five of the
    surplus scan_codes read WAREHOUSE_STOCK. Retracting those is a warehouse
    question, and this module reports them rather than deciding them.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .packing_db import (
    DUPLICATE,
    classify_key_collision,
    packing_line_key,
)

QUARANTINE_TABLE = "packing_line_quarantine"

_DDL = """
CREATE TABLE IF NOT EXISTS packing_line_quarantine (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    repair_ref         TEXT NOT NULL,
    packing_line_id    TEXT NOT NULL,
    packing_line_key   TEXT NOT NULL,
    collision_class    TEXT NOT NULL,
    kept_line_id       TEXT NOT NULL,
    row_json           TEXT NOT NULL,
    reason             TEXT NOT NULL,
    quarantined_at     TEXT NOT NULL,
    restored_at        TEXT
)
"""
_IDX = ("CREATE INDEX IF NOT EXISTS idx_plq_ref "
        "ON packing_line_quarantine(repair_ref)")


def _now(clock) -> str:
    return clock()


def ensure_quarantine_table(con: sqlite3.Connection) -> None:
    con.execute(_DDL)
    con.execute(_IDX)


def find_duplicate_groups(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Every DUPLICATE collision among live rows, newest-first within a group.

    Returns one dict per group: key, collision class, the row kept, the surplus.
    Read-only -- the caller decides what to do with it.
    """
    # Row access by name, without changing how the CALLER sees this connection.
    # Mutating con.row_factory as a side effect made an unrelated fetch in the
    # caller start returning Row objects instead of tuples.
    prior_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        return _find_duplicate_groups(con)
    finally:
        con.row_factory = prior_factory


def _find_duplicate_groups(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    docs = {r["id"]: r for r in con.execute("SELECT * FROM packing_documents")}
    totals = {
        d: con.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM packing_lines "
            "WHERE packing_document_id = ?", (d,)).fetchone()[0]
        for d in docs
    }
    rows = con.execute(
        "SELECT l.* FROM packing_lines l "
        "JOIN packing_documents d ON d.id = l.packing_document_id "
        "WHERE (d.withdrawn_reason IS NULL OR TRIM(d.withdrawn_reason) = '') "
        "  AND NOT EXISTS (SELECT 1 FROM sqlite_master WHERE name = ?) "
        "ORDER BY l.packing_document_id, l.rowid", ("__never__",)).fetchall()

    # key -> document -> rows. The key names a GROUP; several rows sharing it
    # WITHIN one document are a lot, which is by design and not a collision.
    # A collision is the same key held by more than one DOCUMENT.
    keyed: Dict[str, Dict[str, List[sqlite3.Row]]] = defaultdict(
        lambda: defaultdict(list))
    for r in rows:
        keyed[packing_line_key(dict(r))][r["packing_document_id"]].append(r)

    groups = []
    for key, per_doc in keyed.items():
        if len(per_doc) < 2:
            continue
        payload = [{
            "doc_stage": docs[d]["doc_stage"],
            "source_file_hash": docs[d]["source_file_hash"],
            "doc_total_quantity": totals[d],
        } for d in per_doc]
        cls = classify_key_collision(payload)
        if cls != DUPLICATE:
            continue
        # Keep the RICHEST document's rows, not the first-inserted: the
        # per-invoice form carries pack_sr and the per-client form does not,
        # and insertion order would otherwise decide which record survives.
        # A confirmation outranks completeness. Measured on the production
        # shape, the two differ by ONE point -- the per-invoice form carries
        # serial, bag, tray and batch number, the per-client form the operator
        # confirmed carries none of them -- so completeness decided which human
        # decision survived, by a margin nobody chose.
        ranked_docs = sorted(
            per_doc,
            key=lambda d: (any(_operator_confirmed(r) for r in per_doc[d]),
                           max(_richness(r) for r in per_doc[d])),
            reverse=True)
        kept_doc = ranked_docs[0]
        surplus = [r for d in ranked_docs[1:] for r in per_doc[d]]
        # Ranking settles one confirmation. Two documents both carrying one is a
        # disagreement between two humans, and a repair does not adjudicate that.
        confirmed_surplus = [str(r["id"]) for r in surplus if _operator_confirmed(r)]
        groups.append({"key": key, "collision_class": cls,
                       "kept": per_doc[kept_doc][0], "kept_doc": kept_doc,
                       "surplus": surplus,
                       "operator_confirmed_surplus": confirmed_surplus})
    return groups


_CONFIRMED = "confirmed"


def _operator_confirmed(row: sqlite3.Row) -> bool:
    """Did a human explicitly confirm THIS row?

    Only ``operator_review_status == 'confirmed'`` counts. A populated
    ``operator_confirmed_by`` or a draft/pending status is not a decision, and
    must not acquire the protection a decision gets -- otherwise every row that
    accumulated metadata becomes unrepairable and the repair quietly stops
    working.

    The allocation columns that once carried this meaning were retired in #1323
    and are deliberately not consulted: there is one human-decision authority on
    a packing line now, and this is it.
    """
    if "operator_review_status" not in row.keys():
        return False
    return str(row["operator_review_status"] or "").strip().lower() == _CONFIRMED


def _richness(row: sqlite3.Row) -> tuple:
    """How much does this row actually say? More populated fields wins."""
    filled = sum(1 for k in row.keys()
                 if row[k] not in (None, "", 0, 0.0))
    has_sr = 1 if row["pack_sr"] not in (None, "") else 0
    return (filled, has_sr, str(row["id"]))


def quarantine_duplicates(con: sqlite3.Connection, *, repair_ref: str,
                          reason: str, clock, dry_run: bool = True) -> Dict[str, Any]:
    """Move surplus copies into quarantine. ``dry_run`` reports without writing."""
    groups = find_duplicate_groups(con)
    deferred = [g for g in groups if g["operator_confirmed_surplus"]]
    surplus = [(g, s) for g in groups if not g["operator_confirmed_surplus"]
               for s in g["surplus"]]
    report = {
        "repair_ref": repair_ref,
        "groups": len(groups),
        "surplus_rows": len(surplus),
        "batches": sorted({s["batch_id"] for _g, s in surplus}),
        "dry_run": dry_run,
        "quarantined": 0,
        "deferred_groups": len(deferred),
        "deferred_operator_confirmed": sorted(
            lid for g in deferred for lid in g["operator_confirmed_surplus"]),
    }
    if dry_run or not surplus:
        return report

    ensure_quarantine_table(con)
    stamp = _now(clock)
    for group, row in surplus:
        con.execute(
            "INSERT INTO packing_line_quarantine "
            "(repair_ref, packing_line_id, packing_line_key, collision_class, "
            " kept_line_id, row_json, reason, quarantined_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (repair_ref, str(row["id"]), group["key"], group["collision_class"],
             str(group["kept"]["id"]),
             json.dumps({k: row[k] for k in row.keys()}, default=str),
             reason, stamp))
        con.execute("DELETE FROM packing_lines WHERE id = ?", (row["id"],))
        report["quarantined"] += 1
    return report


def restore(con: sqlite3.Connection, *, repair_ref: str, clock) -> Dict[str, Any]:
    """Put a repair back. The reversal path, exercised by the same test that
    exercises the repair -- a reversal nobody runs is a reversal nobody has."""
    ensure_quarantine_table(con)
    prior_factory = con.row_factory
    con.row_factory = sqlite3.Row
    held = con.execute(
        "SELECT * FROM packing_line_quarantine "
        "WHERE repair_ref = ? AND restored_at IS NULL", (repair_ref,)).fetchall()
    cols = [r[1] for r in con.execute("PRAGMA table_info(packing_lines)")]
    stamp = _now(clock)
    restored = 0
    for q in held:
        row = json.loads(q["row_json"])
        present = [c for c in cols if c in row]
        con.execute(
            "INSERT OR REPLACE INTO packing_lines (%s) VALUES (%s)"
            % (",".join(present), ",".join("?" * len(present))),
            [row[c] for c in present])
        con.execute("UPDATE packing_line_quarantine SET restored_at = ? WHERE id = ?",
                    (stamp, q["id"]))
        restored += 1
    con.row_factory = prior_factory
    return {"repair_ref": repair_ref, "restored": restored}
