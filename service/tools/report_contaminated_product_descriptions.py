#!/usr/bin/env python
"""
report_contaminated_product_descriptions.py — READ-ONLY reconciliation report.

Campaign 4 residue: product_descriptions rows written before EJL 3-letter category
codes were routed through the canonical item-type normaliser.  Those writes locked
"Rng"/"Brc"/"Pnd" into description_en and the generic
"Wyrób jubilerski — wyrób jubilerski do noszenia." into description_pl with
source='auto', and get_description_block never overwrites an existing row.

This script CLASSIFIES those rows and reports which drafts still reference them.
It writes NOTHING — the contract is literal:

  * no INSERT, no UPDATE, no DELETE, no DDL
  * every connection is opened with ?mode=ro
  * no set_manual_block, no draft rewrite
  * no file creation and no file overwrite: the report goes to STDOUT ONLY
    (redirect it yourself if you want a copy — this tool never opens a path
    for writing, so it can never be mistaken for a remediation step)

Remediation of the historical rows is a separate operator-reviewed campaign.

Usage:
    python service/tools/report_contaminated_product_descriptions.py
    python service/tools/report_contaminated_product_descriptions.py --storage C:/PZ/storage
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from description_grammar import (  # noqa: E402
    ITEM_TYPE_PL, canonical_item_type, is_item_type_token,
)

# Same token list the engine and the draft-enrichment guard use.
FORBIDDEN = (
    "Wyrób jubilerski", "wyrób jubilerski", "metal szlachetny",
    "UNKNOWN", "grouped invoice aggregate",
)

# Draft states that are still editable — anything else is finalized/posted and
# must never be rewritten (its snapshot is the legal record).
EDITABLE_STATES = ("draft", "editing", "ready", "ready_to_post")


def _ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _classify(row: sqlite3.Row) -> list[str]:
    tags: list[str] = []
    pl = (row["description_pl"] or "").strip()
    en = (row["description_en"] or "").strip()
    name_pl = (row["name_pl"] or "").strip()
    item_type = (row["item_type"] or "").strip()

    if any(t in pl for t in FORBIDDEN):
        tags.append("GENERIC_PL")
    if any(t in name_pl for t in FORBIDDEN):
        tags.append("GENERIC_NAME_PL")
    if en and is_item_type_token(en):
        tags.append("CATEGORY_ABBREVIATION_EN")
    # Stored item_type is an EJL short code, not a grammar key — the marker of a
    # row written before normalisation existed.  Long names that merely fold onto
    # another key ("EARRINGS" -> "EARRING") are NOT contamination.
    if (item_type
            and item_type.upper() not in ITEM_TYPE_PL
            and canonical_item_type(item_type)):
        tags.append("SHORT_ITEM_TYPE")
    if not pl:
        tags.append("EMPTY_PL")
    return tags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--storage", default="C:/PZ/storage",
                    help="storage root holding documents.db and proforma_links.db")
    args = ap.parse_args()

    storage = Path(args.storage)
    docs = storage / "documents.db"
    links = storage / "proforma_links.db"
    if not docs.exists():
        print(f"documents.db not found under {storage}", file=sys.stderr)
        return 2

    with _ro(docs) as con:
        rows = list(con.execute(
            "SELECT product_code, item_type, name_pl, description_en, description_pl, "
            "       source, updated_at "
            "FROM product_descriptions ORDER BY product_code"
        ))

    # Draft references, counted per product_code in one pass over the drafts.
    editable: dict[str, list[int]] = {}
    finalized: dict[str, list[int]] = {}
    if links.exists():
        with _ro(links) as con:
            has = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='proforma_drafts'"
            ).fetchone()
            if has:
                for d in con.execute(
                    "SELECT id, draft_state, editable_lines_json FROM proforma_drafts"
                ):
                    try:
                        lines = json.loads(d["editable_lines_json"] or "[]") or []
                    except Exception:
                        continue
                    bucket = (editable if (d["draft_state"] or "") in EDITABLE_STATES
                              else finalized)
                    for pc in {str(ln.get("product_code") or "").strip() for ln in lines}:
                        if pc:
                            bucket.setdefault(pc, []).append(d["id"])

    report = []
    for r in rows:
        tags = _classify(r)
        if not tags:
            continue
        pc = r["product_code"]
        report.append({
            "product_code":       pc,
            "item_type":          r["item_type"],
            "description_en":     r["description_en"],
            "description_pl":     r["description_pl"],
            "source":             r["source"],
            "updated_at":         r["updated_at"],
            "editable_drafts":    ",".join(map(str, sorted(editable.get(pc, [])))),
            "finalized_drafts":   ",".join(map(str, sorted(finalized.get(pc, [])))),
            "classification":     "|".join(tags),
            # SHORT_ITEM_TYPE alone means only the item_type column is an EJL
            # code — the description itself is fine (all 19 manual rows are in
            # this bucket). Nothing there needs an operator description review.
            "severity":           ("METADATA_ONLY" if tags == ["SHORT_ITEM_TYPE"]
                                   else "DESCRIPTION_UNUSABLE"),
        })

    print(f"product_descriptions rows scanned : {len(rows)}")
    print(f"rows classified as contaminated   : {len(report)}")
    by_tag: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for rec in report:
        for t in rec["classification"].split("|"):
            by_tag[t] = by_tag.get(t, 0) + 1
        by_source[rec["source"] or "?"] = by_source.get(rec["source"] or "?", 0) + 1
    for t, n in sorted(by_tag.items(), key=lambda kv: -kv[1]):
        print(f"  {t:28s} {n}")
    print("  by source:", dict(sorted(by_source.items())))
    for sev in ("DESCRIPTION_UNUSABLE", "METADATA_ONLY"):
        print(f"  {sev:28s} {sum(1 for r in report if r['severity'] == sev)}")
    print(f"  referenced by editable drafts  : "
          f"{sum(1 for r in report if r['editable_drafts'])}")
    print(f"  referenced by finalized drafts : "
          f"{sum(1 for r in report if r['finalized_drafts'])}  (never rewrite these)")

    print()
    for rec in report:
        print(" | ".join(f"{k}={rec[k]!r}" for k in
                         ("product_code", "item_type", "description_en",
                          "source", "updated_at", "classification")))

    print("\nREAD-ONLY. No row was modified. Remediation of these rows is a separate "
          "operator-reviewed campaign (no bulk UPDATE, no automatic set_manual_block, "
          "no rewriting of posted/finalized draft snapshots).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
