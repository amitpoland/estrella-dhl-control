#!/usr/bin/env python3
"""Read-only commercial authority gap audit across all proforma drafts.

Groups by ROOT CAUSE, not draft ID. Never invents values.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

VARIANT_KEYS = (
    "client_po",
    "karat",
    "metal_color",
    "quality_string",
    "size",
    "diamond_weight",
    "color_weight",
)


def _ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return float(v) != 0.0
    s = str(v).strip()
    return bool(s) and s not in ("—", "-", "0", "0.0")


def _line_variant_score(ln: dict) -> Tuple[int, List[str]]:
    missing = []
    for k in VARIANT_KEYS:
        if not _truthy(ln.get(k)):
            missing.append(k)
    return len(VARIANT_KEYS) - len(missing), missing


def load_sales_index(con: sqlite3.Connection) -> Dict[Tuple[str, str], List[dict]]:
    """(batch_id, client_name_norm) -> sales packing lines."""
    out: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    tabs = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "sales_packing_lines" not in tabs:
        return out
    cols = {r[1] for r in con.execute("PRAGMA table_info(sales_packing_lines)")}
    client_col = "client_name" if "client_name" in cols else (
        "contractor_name" if "contractor_name" in cols else None
    )
    for r in con.execute("SELECT * FROM sales_packing_lines"):
        d = dict(r)
        batch = str(d.get("batch_id") or "").strip()
        client = str(d.get(client_col) or d.get("client") or "").strip()
        if not batch:
            continue
        out[(batch, client.casefold())].append(d)
    return out


def sales_has_variants(rows: List[dict]) -> Dict[str, int]:
    counts = {k: 0 for k in VARIANT_KEYS}
    for r in rows:
        for k in VARIANT_KEYS:
            if _truthy(r.get(k)):
                counts[k] += 1
    return counts


def load_origin_index(con: sqlite3.Connection) -> Dict[str, str]:
    out: Dict[str, str] = {}
    tabs = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "product_local" not in tabs:
        return out
    for r in con.execute(
        "SELECT product_code, origin_country FROM product_local "
        "WHERE COALESCE(active,1)=1"
    ):
        pc = (r["product_code"] or "").strip()
        oc = (r["origin_country"] or "").strip()
        if pc and oc:
            out[pc] = oc
            out[pc.casefold()] = oc
    return out


def scan_gaps(storage_root: Path) -> Dict[str, Any]:
    """Scan storage_root DBs and return the grouped gap report."""
    storage = Path(storage_root)
    links_path = storage / "proforma_links.db"
    docs_path = storage / "documents.db"
    master_path = storage / "master_data.sqlite"

    if not links_path.exists():
        raise FileNotFoundError(f"MISSING {links_path}")

    links = _ro(links_path)
    docs = _ro(docs_path) if docs_path.exists() else None
    master = _ro(master_path) if master_path.exists() else None

    sales_idx = load_sales_index(docs) if docs else {}
    origin_idx = load_origin_index(master) if master else {}

    cohorts: Dict[str, List[dict]] = defaultdict(list)
    master_missing_skus: Set[str] = set()
    repairable: List[dict] = []

    drafts = links.execute(
        "SELECT id, batch_id, client_name, draft_state, status, "
        "editable_lines_json, updated_at FROM proforma_drafts "
        "ORDER BY id"
    ).fetchall()

    summary = {
        "drafts_total": 0,
        "drafts_with_lines": 0,
        "lines_total": 0,
    }

    for d in drafts:
        summary["drafts_total"] += 1
        lines = json.loads(d["editable_lines_json"] or "[]")
        if not lines:
            cohorts["EMPTY_EDITABLE_LINES"].append({
                "draft_id": d["id"], "batch_id": d["batch_id"],
                "client": d["client_name"], "state": d["draft_state"],
            })
            continue
        summary["drafts_with_lines"] += 1
        summary["lines_total"] += len(lines)

        batch = str(d["batch_id"] or "").strip()
        client = str(d["client_name"] or "").strip()
        sales = list(sales_idx.get((batch, client.casefold()), []))
        if not sales:
            for (b, _c), rows in sales_idx.items():
                if b == batch:
                    sales.extend(rows)

        sales_counts = sales_has_variants(sales) if sales else {}
        sales_has_any = any(sales_counts.get(k, 0) > 0 for k in VARIANT_KEYS)

        missing_po = sum(1 for ln in lines if not _truthy(ln.get("client_po")))
        missing_quality = sum(1 for ln in lines if not _truthy(ln.get("quality_string")))
        missing_kt = sum(
            1 for ln in lines
            if not (_truthy(ln.get("karat")) or _truthy(ln.get("metal")))
        )
        missing_size = sum(1 for ln in lines if not _truthy(ln.get("size")))
        missing_origin = 0
        inventable_origin = 0
        for ln in lines:
            pc = str(ln.get("product_code") or "").strip()
            if _truthy(ln.get("origin")):
                continue
            missing_origin += 1
            if pc and (origin_idx.get(pc) or origin_idx.get(pc.casefold())):
                inventable_origin += 1
            elif pc:
                master_missing_skus.add(pc)

        variant_gap_lines = sum(
            1 for ln in lines if _line_variant_score(ln)[0] < 3
        )

        # Field-level staleness with 1:1 greedy pairing. Same product_code can
        # appear on many sales rows with different PO/size/weights — never
        # compare a draft line against an arbitrary sibling SKU row.
        unused_draft = [dict(ln) for ln in lines]
        stale_fields = 0
        unmatched_sales = 0
        for src in sales:
            pc = str(src.get("product_code") or "").strip()
            if not pc:
                continue
            best_i = None
            best_score = -1
            for i, ln in enumerate(unused_draft):
                if str(ln.get("product_code") or "").strip() != pc:
                    continue
                score = 0
                for k in ("client_po", "size", "metal_color", "karat"):
                    sv = str(src.get(k) or "").strip()
                    dv = str(ln.get(k) or "").strip()
                    if sv and sv == dv:
                        score += 2
                    elif not sv and not dv:
                        score += 1
                if score > best_score:
                    best_score = score
                    best_i = i
            if best_i is None:
                unmatched_sales += 1
                continue
            ln = unused_draft.pop(best_i)
            for k in VARIANT_KEYS:
                if _truthy(src.get(k)) and not _truthy(ln.get(k)):
                    stale_fields += 1

        entry = {
            "draft_id": d["id"],
            "batch_id": batch,
            "client": client,
            "state": d["draft_state"] or d["status"],
            "n_lines": len(lines),
            "missing_po": missing_po,
            "missing_quality": missing_quality,
            "missing_kt": missing_kt,
            "missing_size": missing_size,
            "missing_origin": missing_origin,
            "origin_enrichable_via_pm": inventable_origin,
            "variant_gap_lines": variant_gap_lines,
            "stale_field_hits": stale_fields,
            "unmatched_sales_rows": unmatched_sales,
            "sales_rows": len(sales),
            "sales_has_variants": sales_has_any,
            "sales_variant_counts": sales_counts,
            "updated_at": d["updated_at"],
        }

        if stale_fields > 0 or unmatched_sales > 0:
            cohorts["STALE_DRAFT_SALES_VARIANTS_AVAILABLE"].append(entry)
            if (d["draft_state"] or "") in ("draft", "editing", "post_failed", ""):
                repairable.append(entry)
        elif variant_gap_lines > 0 and sales and not sales_has_any:
            cohorts["SALES_PACKING_LACKS_VARIANTS"].append(entry)
        elif variant_gap_lines > 0 and not sales:
            cohorts["NO_SALES_PACKING_FOR_DRAFT"].append(entry)
        elif variant_gap_lines > 0 and sales_has_any:
            # Draft matches sales; both thin — incomplete upstream, not stale.
            cohorts["INCOMPLETE_UPSTREAM_VARIANTS"].append(entry)
        elif missing_origin > 0 and inventable_origin == missing_origin:
            cohorts["ORIGIN_ONLY_ENRICHABLE_AT_READ"].append(entry)
        elif missing_origin > 0:
            cohorts["ORIGIN_PRODUCT_MASTER_MISSING"].append(entry)
        elif variant_gap_lines == 0 and missing_origin == 0:
            cohorts["HEALTHY"].append(entry)
        else:
            cohorts["OTHER"].append(entry)

    links.close()
    if docs:
        docs.close()
    if master:
        master.close()

    return {
        "summary": summary,
        "cohort_counts": {k: len(v) for k, v in sorted(cohorts.items())},
        "repairable_via_reset_from_sales": {
            "count": len(repairable),
            "draft_ids": [e["draft_id"] for e in repairable],
            "states_ok": "draft/editing/post_failed only",
        },
        "product_master_origin_missing_skus": {
            "count": len(master_missing_skus),
            "sample": sorted(master_missing_skus)[:80],
            "all": sorted(master_missing_skus),
        },
        "cohorts": {
            k: {
                "count": len(v),
                "draft_ids": [e["draft_id"] for e in v],
                "drafts": v,
                "sample": v[:8],
            }
            for k, v in sorted(cohorts.items())
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--storage-root",
        type=Path,
        default=Path(r"C:\PZ\storage"),
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(r"C:\PZ-verify\tasks\smoke-reports\commercial-authority-audit"),
    )
    args = ap.parse_args()

    try:
        report = scan_gaps(args.storage_root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_file = args.out_dir / "gap_report.json"
    out_file.write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({
        "summary": report["summary"],
        "cohort_counts": report["cohort_counts"],
        "repairable": report["repairable_via_reset_from_sales"]["count"],
        "repairable_ids": report["repairable_via_reset_from_sales"]["draft_ids"],
        "pm_origin_missing_skus": report["product_master_origin_missing_skus"]["count"],
        "report": str(out_file),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
