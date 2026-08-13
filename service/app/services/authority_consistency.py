"""Read-only authority consistency + safe derived-projection repair.

Authorities (unchanged):
  product_descriptions     = description truth
  wfirma_product_mirror + wfirma_products.sync_status='matched' = mapping truth
  product_master.status    = derived projection only

This module does not create wFirma goods, fabricate IDs, alter descriptions,
prices, qty, stock, or posted/converted drafts. Repair is local projection only.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPAIRABLE = "repairable_projection"
BLOCKED = "blocked_authority_missing"
CONFLICT = "conflict"

KIND_DESC_STALE = "description_projection_stale"
KIND_DESC_INVALID = "description_authority_invalid"
KIND_MAP_STALE = "mapping_projection_stale"
KIND_MAP_CONFLICT = "mapping_conflict"
KIND_WAREHOUSE = "warehouse_config_invalid"

_EDITABLE = ("draft", "editing", "post_failed")
_SAMPLE = 50


def _ro(path: Path) -> Optional[sqlite3.Connection]:
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _close(con: Optional[sqlite3.Connection]) -> None:
    if con is not None:
        con.close()


def warehouse_config_invalid() -> Optional[Dict[str, Any]]:
    """Module enabled but configured warehouse id is missing/blank."""
    from ..core.config import settings

    module_on = bool(getattr(settings, "wfirma_warehouse_module_enabled", False))
    wid = str(getattr(settings, "wfirma_warehouse_id", None) or "").strip()
    if module_on and not wid:
        return {
            "kind": KIND_WAREHOUSE,
            "class": BLOCKED,
            "product_code": None,
            "detail": (
                "WFIRMA_WAREHOUSE_MODULE_ENABLED is true but "
                "WFIRMA_WAREHOUSE_ID is empty"
            ),
        }
    return None


def _product_description_rows(docs: sqlite3.Connection) -> Dict[str, Dict[str, str]]:
    """product_code → persisted product_descriptions fields (may be unusable)."""
    out: Dict[str, Dict[str, str]] = {}
    try:
        rows = docs.execute(
            "SELECT product_code, name_pl, description_pl, description_en, "
            "material_pl FROM product_descriptions"
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for r in rows:
        pc = str(r["product_code"] or "").strip()
        if not pc:
            continue
        out[pc] = {
            "product_code": pc,
            "name_pl": str(r["name_pl"] or ""),
            "description_pl": str(r["description_pl"] or ""),
            "description_en": str(r["description_en"] or ""),
            "material_pl": str(r["material_pl"] or ""),
        }
    return out


def _editable_draft_lines(proforma: sqlite3.Connection) -> List[Tuple[int, str, str, str]]:
    """(draft_id, product_code, name_pl, draft_state) for editable drafts."""
    out: List[Tuple[int, str, str, str]] = []
    try:
        rows = proforma.execute(
            "SELECT id, draft_state, editable_lines_json FROM proforma_drafts"
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for r in rows:
        state = str(r["draft_state"] or "")
        if state not in _EDITABLE:
            continue
        try:
            lines = json.loads(r["editable_lines_json"] or "[]") or []
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        did = int(r["id"])
        for ln in lines:
            if not isinstance(ln, dict):
                continue
            pc = str(ln.get("product_code") or "").strip()
            if not pc:
                continue
            name_pl = str(ln.get("name_pl") or "").strip()
            out.append((did, pc, name_pl, state))
    return out


def _mapping_rows(
    reservation: sqlite3.Connection,
    cache: Optional[sqlite3.Connection],
) -> Dict[str, Dict[str, str]]:
    """product_code → {mirror_id, cache_id, sync_status, master_status}."""
    by_code: Dict[str, Dict[str, str]] = {}

    def slot(pc: str) -> Dict[str, str]:
        return by_code.setdefault(
            pc,
            {"mirror_id": "", "cache_id": "", "sync_status": "", "master_status": ""},
        )

    try:
        for r in reservation.execute(
            "SELECT product_code, status FROM product_master"
        ):
            pc = str(r["product_code"] or "").strip()
            if pc:
                slot(pc)["master_status"] = str(r["status"] or "")
    except sqlite3.OperationalError:
        pass
    try:
        for r in reservation.execute(
            "SELECT product_code, wfirma_id FROM wfirma_product_mirror"
        ):
            pc = str(r["product_code"] or "").strip()
            if pc:
                slot(pc)["mirror_id"] = str(r["wfirma_id"] or "").strip()
    except sqlite3.OperationalError:
        pass
    if cache is not None:
        try:
            for r in cache.execute(
                "SELECT product_code, wfirma_product_id, sync_status "
                "FROM wfirma_products"
            ):
                pc = str(r["product_code"] or "").strip()
                if pc:
                    s = slot(pc)
                    s["cache_id"] = str(r["wfirma_product_id"] or "").strip()
                    s["sync_status"] = str(r["sync_status"] or "").strip()
        except sqlite3.OperationalError:
            pass
    return by_code


def _confirmed_match(row: Dict[str, str]) -> bool:
    mid = row.get("mirror_id") or ""
    cid = row.get("cache_id") or ""
    return bool(mid) and cid == mid and row.get("sync_status") == "matched"


def evaluate_authority_consistency(storage_root: Path) -> Dict[str, Any]:
    """Read-only scan. Never writes. Never calls wFirma."""
    root = Path(storage_root)
    docs = _ro(root / "documents.db")
    proforma = _ro(root / "proforma_links.db")
    reservation = _ro(root / "reservation_queue.db")
    cache = _ro(root / "wfirma.db")
    findings: List[Dict[str, Any]] = []
    try:
        from .description_engine import validate_product_description_row

        pd_rows = _product_description_rows(docs) if docs else {}
        draft_lines = _editable_draft_lines(proforma) if proforma else []
        mapping = _mapping_rows(reservation, cache) if reservation else {}

        seen_invalid: set = set()
        for pc, row in pd_rows.items():
            has_text = bool(
                str(row.get("description_pl") or "").strip()
                or str(row.get("name_pl") or "").strip()
            )
            if not has_text:
                continue
            validity = validate_product_description_row(row)
            if validity.is_usable:
                continue
            if pc in seen_invalid:
                continue
            seen_invalid.add(pc)
            findings.append({
                "kind": KIND_DESC_INVALID,
                "class": BLOCKED,
                "product_code": pc,
                "detail": (
                    "canonical product_descriptions row is not commercially "
                    "usable: " + "; ".join(validity.reasons)
                ),
                "reasons": list(validity.reasons),
            })

        seen_desc: set = set()
        for draft_id, pc, name_pl, _state in draft_lines:
            if pc in seen_invalid:
                continue
            row = pd_rows.get(pc)
            if not row:
                continue
            validity = validate_product_description_row(row)
            if not validity.is_usable:
                continue
            key = (draft_id, pc)
            if key in seen_desc:
                continue
            if not name_pl:
                seen_desc.add(key)
                findings.append({
                    "kind": KIND_DESC_STALE,
                    "class": REPAIRABLE,
                    "product_code": pc,
                    "draft_id": draft_id,
                    "detail": (
                        "usable canonical description exists; "
                        "editable draft name_pl is blank"
                    ),
                })

        for pc, row in mapping.items():
            matched = _confirmed_match(row)
            master = row.get("master_status") or ""
            if matched and master != "mapped":
                master_exists = bool(master)
                findings.append({
                    "kind": KIND_MAP_STALE,
                    "class": REPAIRABLE if master_exists else BLOCKED,
                    "product_code": pc,
                    "detail": (
                        f"canonical mapping matched id={row.get('mirror_id')}; "
                        f"product_master.status={master or 'missing'}"
                    ),
                    "wfirma_id": row.get("mirror_id"),
                    "master_exists": master_exists,
                })
            elif master == "mapped" and not matched:
                findings.append({
                    "kind": KIND_MAP_CONFLICT,
                    "class": CONFLICT,
                    "product_code": pc,
                    "detail": (
                        "product_master.status=mapped but canonical mapping is "
                        f"missing/mismatched (mirror={row.get('mirror_id')!r} "
                        f"cache={row.get('cache_id')!r} sync={row.get('sync_status')!r})"
                    ),
                })

        wh = warehouse_config_invalid()
        if wh:
            findings.append(wh)
    finally:
        for con in (docs, proforma, reservation, cache):
            _close(con)

    counts = {
        KIND_DESC_STALE: 0,
        KIND_DESC_INVALID: 0,
        KIND_MAP_STALE: 0,
        KIND_MAP_CONFLICT: 0,
        KIND_WAREHOUSE: 0,
        "mapping_master_missing": 0,
    }
    by_class = {REPAIRABLE: 0, BLOCKED: 0, CONFLICT: 0}
    for f in findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        by_class[f["class"]] = by_class.get(f["class"], 0) + 1
        if f["kind"] == KIND_MAP_STALE and not f.get("master_exists", True):
            counts["mapping_master_missing"] += 1

    sample: Dict[str, List[Dict[str, Any]]] = {k: [] for k in counts}
    for f in findings:
        bucket = sample[f["kind"]]
        if len(bucket) < _SAMPLE:
            bucket.append(f)

    return {
        "ok": all(v == 0 for v in counts.values()),
        "counts": counts,
        "by_class": by_class,
        "findings": findings,
        "sample": sample,
        "wfirma_writes": False,
    }


def _assert_description_projection(
    storage_root: Path, product_codes: Iterable[str]
) -> bool:
    """True when no editable draft for these codes still has a blank name_pl
    while a *usable* canonical description exists."""
    wanted = {str(c).strip() for c in product_codes if str(c).strip()}
    if not wanted:
        return True
    report = evaluate_authority_consistency(storage_root)
    for f in report["findings"]:
        if f["kind"] == KIND_DESC_STALE and f.get("product_code") in wanted:
            return False
    return True


def repair_derived_projections(
    storage_root: Path,
    *,
    product_codes: Optional[Iterable[str]] = None,
    draft_ids: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """Repair only proven local projections. Never writes wFirma or descriptions.

    Optional ``product_codes`` / ``draft_ids`` switch the run to scoped mode:
    only matching repairable findings are touched. Missing Product Master
    rows are never inserted.
    """
    from . import reservation_db as rdb
    from .commercial_authority import enrich_editable_drafts_for_product_code

    root = Path(storage_root)
    report = evaluate_authority_consistency(root)
    repaired_desc: List[str] = []
    repaired_map: List[str] = []
    skipped: List[Dict[str, Any]] = []
    wanted_codes = {
        str(c).strip() for c in (product_codes or []) if str(c).strip()
    }
    wanted_drafts = {int(i) for i in (draft_ids or [])}
    scoped = bool(wanted_codes or wanted_drafts)

    links = root / "proforma_links.db"
    res_db = root / "reservation_queue.db"
    if res_db.exists():
        rdb.init_reservation_db(res_db)

    seen_pc: set = set()
    for f in report["findings"]:
        pc = f.get("product_code")
        if scoped:
            if f["kind"] == KIND_DESC_STALE:
                if wanted_codes and pc not in wanted_codes:
                    skipped.append({
                        "product_code": pc, "kind": f["kind"],
                        "reason": "out_of_scope",
                    })
                    continue
                if wanted_drafts and int(f.get("draft_id") or 0) not in wanted_drafts:
                    skipped.append({
                        "product_code": pc, "kind": f["kind"],
                        "draft_id": f.get("draft_id"),
                        "reason": "out_of_scope",
                    })
                    continue
            elif f["kind"] == KIND_MAP_STALE:
                if not wanted_codes or pc not in wanted_codes:
                    skipped.append({
                        "product_code": pc, "kind": f["kind"],
                        "reason": "out_of_scope",
                    })
                    continue
            else:
                skipped.append({
                    "product_code": pc, "kind": f["kind"],
                    "reason": "out_of_scope",
                })
                continue
        if f["class"] != REPAIRABLE:
            skipped.append({
                "product_code": f.get("product_code"),
                "kind": f["kind"],
                "class": f["class"],
                "reason": "not repairable_projection",
            })
            continue
        if f["kind"] == KIND_DESC_STALE and pc:
            if pc in seen_pc:
                continue
            seen_pc.add(pc)
            enrich_editable_drafts_for_product_code(
                pc, proforma_db=links, operator="authority-consistency-repair",
                draft_ids=wanted_drafts or None,
            )
            repaired_desc.append(pc)
        elif f["kind"] == KIND_MAP_STALE and pc:
            row_id = str(f.get("wfirma_id") or "").strip()
            if not row_id:
                skipped.append({
                    "product_code": pc,
                    "kind": f["kind"],
                    "reason": "missing proven wfirma_id",
                })
                continue
            if not rdb.get_product_master(res_db, pc):
                skipped.append({
                    "product_code": pc,
                    "kind": f["kind"],
                    "reason": "product_master row missing; refusing to insert",
                })
                continue
            rdb.upsert_product_mirror(
                res_db,
                wfirma_id=row_id,
                product_code=pc,
                also_set_master_status="mapped",
            )
            repaired_map.append(pc)

    after = evaluate_authority_consistency(root)
    return {
        "ok": after["ok"] or (
            after["counts"][KIND_DESC_STALE] == 0
            and after["counts"][KIND_MAP_STALE] == 0
        ),
        "repaired_description_codes": repaired_desc,
        "repaired_mapping_codes": repaired_map,
        "skipped": skipped,
        "before": report["counts"],
        "after": after["counts"],
        "scope": {
            "product_codes": sorted(wanted_codes),
            "draft_ids": sorted(wanted_drafts),
        },
        "wfirma_writes": False,
        "descriptions_mutated": False,
        "posted_drafts_touched": False,
    }


def assert_mapping_projected(db_path: Path, product_code: str) -> bool:
    """True when Product Master status is mapped after a confirmed match.

    Retries the existing Master setter once. Does not invent a mapping.
    """
    from . import reservation_db as rdb
    from . import wfirma_db as wfdb

    pc = (product_code or "").strip()
    if not pc:
        return True
    mirror = rdb.get_mirror_product(db_path, pc) or {}
    mid = str(mirror.get("wfirma_id") or "").strip()
    cache = wfdb.get_product(pc) or {}
    cid = str(cache.get("wfirma_product_id") or "").strip()
    sync = str(cache.get("sync_status") or "").strip()
    if not (mid and cid == mid and sync == "matched"):
        return True
    master = rdb.get_product_master(db_path, pc) or {}
    if master.get("status") == "mapped":
        return True
    rdb.upsert_product_mirror(
        db_path, wfirma_id=mid, product_code=pc, also_set_master_status="mapped",
    )
    master = rdb.get_product_master(db_path, pc) or {}
    return master.get("status") == "mapped"
