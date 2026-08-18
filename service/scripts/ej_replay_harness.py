#!/usr/bin/env python3
"""
ej_replay_harness.py — EJ DASHBOARD HISTORICAL REPLAY CERTIFICATION HARNESS
===========================================================================
Operational verification tooling. NOT an application module, NOT an authority.
An isolated verifier of the EXISTING authorities.

Architecture baseline : c0416e88d5934775ea5dd90ef92463d6a3aab0e2
Lineage               : v2, hardened IN PLACE from v1
                        V1_SOURCE_SHA256 =
                        4079c621c63fde4e0bb7b1261db86d6eb3a4827b4103f3169123cca3ffbcddc7

═══════════════════════════════════════════════════════════════════════════
 WHY WHOLE-STORAGE-ROOT ISOLATION (not a curated DB list)
═══════════════════════════════════════════════════════════════════════════
A repository sweep at c0416e88 found 48 import-time storage captures across
29 modules, referencing 47 distinct children of settings.storage_root --
databases, JSON state files, JSONL audit logs and whole directories:

    _OUTPUTS  = settings.storage_root / "outputs"        (9 modules)
    _DB_PATH  = settings.storage_root / "customer_master.sqlite"
    _POLL_DB  = settings.storage_root / "contractor_poll.db"
    _ARCHIVED = settings.storage_root / "archived"
    ... plus finance_postings.sqlite, packing_resolutions.sqlite,
        tracking_events.db, intelligence_*.json, version.json,
        polish_descriptions/, sad_ready/, sessions/, working/ ...

These bind AT IMPORT TIME. No init_*() seam covers most of them. Therefore:
  * isolation MUST operate on the ENTIRE storage root, and
  * settings.storage_root MUST be redirected BEFORE any application import.

v1 curated a DB list and redirected only DB pointers. Both hazards below were
live in v1 and are fixed here.

  HAZARD A  core/audit.py resolves master_audit.sqlite from settings.storage_root
            (audit_db_path(), core/audit.py:90-92); audit_safe() is called by
            cpa_product_service -- the product_master writer. v1 omitted
            master_audit.sqlite from snapshot AND hash protection, so an audit
            write could reach LIVE storage undetected.

  HAZARD B  29 modules capture storage_root-derived paths at import time. v1 did
            not redirect storage_root before importing them, so those constants
            would have pointed at LIVE storage for the whole run.

Other verified write-on-read hazards (reads here are NOT pure):

  H1  init_*() run idempotent ALTER migrations AT INIT (measured: 5/8 DB hashes
      change from the init calls alone, before any resolver runs)
  H2  routes_proforma._build_preview -> design_product_bridge.populate_from_packing()
      WRITES design_product_mapping (routes_proforma.py:798-806); and
      _derive_draft_readiness calls _build_preview -> READINESS IS A WRITER
  H3  description_engine.get_description_block() persists + LOCKS on first call
      (description_engine.py:286-293)
  H6  wFirma / carrier / email / HTTP writers reachable from imported modules

═══════════════════════════════════════════════════════════════════════════
 MANDATORY STARTUP ORDER (load-bearing -- do not reorder)
═══════════════════════════════════════════════════════════════════════════
   1 parse CLI
   2 locate live storage root
   3 hash all live authorities (WHOLE TREE)
   4 create isolated snapshot root
   5 SQLite online-backup every DB incl. master_audit.sqlite
   6 copy session/output evidence into snapshot
   7 redirect settings.storage_root -> snapshot root
   8 install network / write kill-switches
   9 ONLY THEN import application modules
  10 initialise application DB services against snapshot
  11 run requested phase
  12 hash live sources again
  13 fail if anything changed

Snapshot mutations are ALLOWED and EXPECTED. Live mutations are FORBIDDEN.

USAGE
    python service/scripts/ej_replay_harness.py --storage <live> --out <dir> --self-test
    python service/scripts/ej_replay_harness.py --storage <live> --out <dir> --phase 1
    ... --phase 3 | --phase 4 | --phase 5 | --all

EXIT CODES   0 ok | 2 precondition/usage | 3 SAFETY_FAILURE
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASELINE = "c0416e88d5934775ea5dd90ef92463d6a3aab0e2"
V1_SOURCE_SHA256 = "4079c621c63fde4e0bb7b1261db86d6eb3a4827b4103f3169123cca3ffbcddc7"
V2_HARDENED_SHA256 = "ec4e53925d9b2ca1c04a9a2a26f2c0ec26e67cefef1ca2cb68df005689ff5d71"
# v3 adds Phase 1b (Product Fiscal Convergence, local-evidence-only) and the
# D-6 readiness-impact measurement. Extending the file necessarily changes its
# hash: v3 carries a NEW SHA-256 and the v1/v2 lineage is recorded above rather
# than the old hash being claimed for new content.
HARNESS_VERSION = 3

SQLITE_SUFFIXES = (".db", ".sqlite")

# Modules whose import-time storage constants must resolve INSIDE the snapshot
# (OUTPUT_PATH_REDIRECTION gate). Representative across the 29 found.
REDIRECTION_PROBES: Tuple[Tuple[str, str], ...] = (
    ("app.api.routes_dashboard",              "_OUTPUTS"),
    ("app.api.routes_dashboard",              "_ARCHIVED"),
    ("app.api.routes_dashboard",              "_WORKING"),
    ("app.api.routes_customer_master",        "_DB_PATH"),
    ("app.api.routes_master_data",            "_DB_PATH"),
    ("app.api.routes_suppliers",              "_DB_PATH"),
    ("app.api.routes_packing_resolution",     "_DB_PATH"),
    ("app.api.routes_wfirma_contractors",     "_POLL_DB"),
    ("app.api.routes_tracking",               "_OUTPUTS"),
    ("app.services.operational_authority",    "_OUTPUTS"),
    ("app.services.search_engine",            "_DOC_DB"),
    ("app.services.intelligence_graph",       "_TRACKING_DB"),
    ("app.services.master_data_intelligence", "_CM_DB"),
    ("app.services.action_email_builder",     "_OUTPUTS"),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════
#  SAFETY PRIMITIVES
# ══════════════════════════════════════════════════════════════════════════

def hash_tree(root: Path) -> Dict[str, str]:
    """SHA-256 of EVERY file under root, recursively.

    Whole-tree, not a known-file list: an undiscovered writer that creates or
    edits any file under live storage must still be caught. WAL/SHM sidecars are
    excluded -- SQLite may legitimately checkpoint them even on read-only access;
    durable .db content is what must not change.
    """
    out: Dict[str, str] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.endswith(("-wal", "-shm")):
            continue
        h = hashlib.sha256()
        try:
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out[str(p.relative_to(root))] = h.hexdigest()
        except Exception as exc:
            out[str(p.relative_to(root))] = f"UNREADABLE:{type(exc).__name__}"
    return out


def diff_hashes(pre: Dict[str, str], post: Dict[str, str]) -> Dict[str, List[str]]:
    return {"changed": sorted(k for k in pre if k in post and pre[k] != post[k]),
            "removed": sorted(k for k in pre if k not in post),
            "added":   sorted(k for k in post if k not in pre)}


def snapshot_storage_root(live: Path, snap: Path, log) -> Dict[str, Any]:
    """STEP 4/5/6 — mirror the ENTIRE storage root into an isolated snapshot.

    SQLite files use the online-backup API from a READ-ONLY connection (a bare
    copy of a WAL-mode DB can capture a torn image). Everything else -- JSON
    state, JSONL audit logs, outputs/ sessions/ working/ evidence trees -- is
    copied verbatim so every import-time path constant resolves inside snap.
    """
    snap.mkdir(parents=True, exist_ok=True)
    stats: Dict[str, Any] = {"sqlite_backup": 0, "sqlite_copy_fallback": 0,
                             "files_copied": 0, "dirs_copied": 0, "errors": []}
    for item in sorted(live.iterdir()):
        if item.name.endswith(("-wal", "-shm")):
            continue
        dst = snap / item.name
        try:
            if item.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(item, dst)
                stats["dirs_copied"] += 1
                log(f"    dir                {item.name}/")
            elif item.suffix in SQLITE_SUFFIXES:
                try:
                    con = sqlite3.connect(f"file:{item.as_posix()}?mode=ro",
                                          uri=True, timeout=15)
                    try:
                        tgt = sqlite3.connect(str(dst))
                        try:
                            con.backup(tgt)
                        finally:
                            tgt.close()
                    finally:
                        con.close()
                    stats["sqlite_backup"] += 1
                    log(f"    sqlite(.backup)    {item.name}")
                except Exception as exc:
                    shutil.copy2(item, dst)
                    for ext in ("-wal", "-shm"):
                        if (qq := Path(str(item) + ext)).exists():
                            shutil.copy2(qq, str(dst) + ext)
                    stats["sqlite_copy_fallback"] += 1
                    log(f"    sqlite(copy+wal)   {item.name}  [{type(exc).__name__}]")
            else:
                shutil.copy2(item, dst)
                stats["files_copied"] += 1
                log(f"    file               {item.name}")
        except Exception as exc:
            stats["errors"].append(f"{item.name}: {type(exc).__name__}: {exc}")
            log(f"    ERROR              {item.name}: {exc}")

    for d in ("outputs", "sessions", "working", "archived", "polish_descriptions",
              "sad_ready", "incoming", "system"):
        (snap / d).mkdir(parents=True, exist_ok=True)
    return stats


class NetworkBlocked(RuntimeError):
    """Raised when code under the harness attempts an outbound connection."""


def install_network_killswitch(log) -> Dict[str, Any]:
    """STEP 8 — DEFAULT-ON. Historical replay makes ZERO external calls.

    Any attempt to reach wFirma, a carrier API, email, cloud storage or generic
    HTTP fails hard AND identifies the calling frame. Loopback is permitted but
    recorded.
    """
    import socket
    state: Dict[str, Any] = {"attempts": [], "blocked": 0, "armed": True}
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def _caller() -> str:
        for fr in reversed(traceback.extract_stack()[:-2]):
            if "ej_replay_harness" not in fr.filename and "socket.py" not in fr.filename:
                return f"{fr.filename}:{fr.lineno} in {fr.name}"
        return "<unknown>"

    def _guard(addr) -> None:
        host = str(addr[0]) if isinstance(addr, tuple) and addr else ""
        who = _caller()
        state["attempts"].append({"ts": now(), "addr": repr(addr), "caller": who})
        if host in ("127.0.0.1", "::1", "localhost"):
            return
        state["blocked"] += 1
        raise NetworkBlocked(
            f"OUTBOUND NETWORK BLOCKED by replay harness.\n"
            f"  target : {addr!r}\n  caller : {who}\n"
            f"  The harness must never call wFirma, carriers, email or any "
            f"external service during historical replay.")

    def patched_connect(self, addr):        # type: ignore[no-untyped-def]
        _guard(addr); return real_connect(self, addr)

    def patched_connect_ex(self, addr):     # type: ignore[no-untyped-def]
        _guard(addr); return real_connect_ex(self, addr)

    socket.socket.connect = patched_connect        # type: ignore[assignment]
    socket.socket.connect_ex = patched_connect_ex  # type: ignore[assignment]
    log("    network kill-switch ARMED (loopback allowed; external = hard fail + caller id)")
    return state


def assert_import_order_guard(log) -> Dict[str, Any]:
    """STEP 7 precondition — the application must NOT already be imported.

    If any app.* module is in sys.modules before redirection, its import-time
    storage constants already point at LIVE storage and isolation is void.
    """
    leaked = sorted(m for m in sys.modules if m == "app" or m.startswith("app."))
    ok = not leaked
    log(f"    IMPORT_ORDER_GUARD: {'PASS' if ok else 'FAIL'} "
        f"({len(leaked)} app modules pre-imported)")
    for m in leaked[:15]:
        log(f"      leaked: {m}")
    return {"pass": ok, "pre_imported": leaked}


def redirect_storage_root(snap: Path, log) -> Dict[str, Any]:
    """STEP 7 — patch settings.storage_root BEFORE any application import."""
    from app.core.config import settings
    settings.storage_root = snap
    from app.core.audit import audit_db_path
    audit_path = audit_db_path()
    inside = (audit_path.parent == snap) or (snap in audit_path.parents)
    log(f"    settings.storage_root -> {snap}")
    log(f"    audit_db_path()       -> {audit_path}   [{'INSIDE' if inside else 'OUTSIDE'}]")
    return {"storage_root": str(snap), "audit_db_path": str(audit_path),
            "master_audit_redirected": bool(inside)}


def verify_path_redirection(snap: Path, log) -> Dict[str, Any]:
    """OUTPUT_PATH_REDIRECTION gate — import the modules that capture storage
    paths at import time and prove each constant resolves INSIDE the snapshot."""
    import importlib
    results: List[Dict[str, Any]] = []
    for mod_name, attr in REDIRECTION_PROBES:
        try:
            mod = importlib.import_module(mod_name)
            val = getattr(mod, attr, None)
            if val is None:
                results.append({"module": mod_name, "attr": attr,
                                "status": "ABSENT", "value": None})
                continue
            p = Path(str(val))
            inside = (snap == p) or (snap in p.parents)
            results.append({"module": mod_name, "attr": attr,
                            "status": "INSIDE" if inside else "OUTSIDE", "value": str(p)})
        except Exception as exc:
            results.append({"module": mod_name, "attr": attr,
                            "status": f"IMPORT_ERROR:{type(exc).__name__}", "value": None})
    outside = [r for r in results if r["status"] == "OUTSIDE"]
    for r in results:
        log(f"      [{'ok  ' if r['status'] == 'INSIDE' else 'WARN'}] "
            f"{r['module']}.{r['attr']:<14} {r['status']}")
        if r["status"] == "OUTSIDE":
            log(f"              -> {r['value']}")
    return {"probes": results, "inside": sum(1 for r in results if r["status"] == "INSIDE"),
            "total": len(results), "pass": not outside, "outside": outside}


def redirect_databases(snap: Path, log) -> Dict[str, bool]:
    """STEP 10 — point every DB authority at the snapshot (H1)."""
    ok: Dict[str, bool] = {}
    from app.services.packing_db import init_packing_db
    from app.services.warehouse_db import init_warehouse_db
    from app.services.document_db import init_document_db
    for label, fn, db in (("packing_db", init_packing_db, "packing.db"),
                          ("warehouse_db", init_warehouse_db, "warehouse.db"),
                          ("document_db", init_document_db, "documents.db")):
        try:
            fn(snap / db); ok[label] = True
        except Exception as exc:
            ok[label] = False; log(f"    WARN init {label}: {exc}")
    try:
        from app.services.reservation_db import init_reservation_db
        init_reservation_db(snap / "reservation_queue.db"); ok["reservation_db"] = True
    except Exception as exc:
        ok["reservation_db"] = False; log(f"    WARN init reservation_db: {exc}")
    try:
        from app.services import proforma_invoice_link_db as pildb
        pildb.init_db(snap / "proforma_links.db"); ok["proforma_links"] = True
    except Exception as exc:
        ok["proforma_links"] = False; log(f"    WARN init proforma_links: {exc}")
    return ok


def ro(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def q(db: Path, sql: str, args: tuple = ()) -> List[sqlite3.Row]:
    try:
        with ro(db) as con:
            return con.execute(sql, args).fetchall()
    except Exception:
        return []


def scalar(db: Path, sql: str, args: tuple = ()) -> int:
    r = q(db, sql, args)
    return int(r[0][0]) if r and r[0][0] is not None else 0


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 1 — CORPUS DISCOVERY
# ══════════════════════════════════════════════════════════════════════════

def phase1_discover(snap: Path) -> Dict[str, Dict[str, Any]]:
    pack, docs, prof, wh = (snap / "packing.db", snap / "documents.db",
                            snap / "proforma_links.db", snap / "warehouse.db")
    acc: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def tally(rows, key):
        for r in rows:
            b = (r[0] or "").strip()
            if b:
                acc[b][key] = int(r[1] or 0)

    tally(q(pack, "SELECT batch_id, COUNT(*) FROM packing_lines GROUP BY batch_id"), "purchase_rows")
    tally(q(pack, "SELECT batch_id, COUNT(*) FROM packing_documents GROUP BY batch_id"), "packing_docs")
    tally(q(docs, "SELECT batch_id, COUNT(*) FROM sales_packing_lines GROUP BY batch_id"), "sales_rows")
    tally(q(docs, "SELECT batch_id, COUNT(*) FROM invoice_lines WHERE active=1 GROUP BY batch_id"), "invoice_lines")
    tally(q(docs, "SELECT batch_id, COUNT(*) FROM pz_documents GROUP BY batch_id"), "pz_docs")
    tally(q(prof, "SELECT batch_id, COUNT(*) FROM proforma_drafts GROUP BY batch_id"), "drafts")
    tally(q(prof, "SELECT batch_id, COUNT(*) FROM proforma_drafts WHERE posted_at IS NOT NULL GROUP BY batch_id"), "posted_drafts")
    tally(q(wh,   "SELECT batch_id, COUNT(*) FROM inventory_state GROUP BY batch_id"), "inventory_rows")

    out: Dict[str, Dict[str, Any]] = {}
    for b, ev in acc.items():
        e: Dict[str, Any] = {k: int(ev.get(k, 0)) for k in
                             ("purchase_rows", "packing_docs", "sales_rows", "invoice_lines",
                              "pz_docs", "drafts", "posted_drafts", "inventory_rows")}
        e["distinct_designs"] = scalar(pack, "SELECT COUNT(DISTINCT design_no) FROM packing_lines "
                                             "WHERE batch_id=? AND TRIM(COALESCE(design_no,''))<>''", (b,))
        e["distinct_products"] = scalar(pack, "SELECT COUNT(DISTINCT product_code) FROM packing_lines "
                                              "WHERE batch_id=? AND TRIM(COALESCE(product_code,''))<>''", (b,))
        e["sales_design_only"] = scalar(docs, "SELECT COUNT(*) FROM sales_packing_lines WHERE batch_id=? "
                                              "AND TRIM(COALESCE(design_no,''))<>'' "
                                              "AND TRIM(COALESCE(product_code,''))=''", (b,))
        e["purchase_design_only"] = scalar(pack, "SELECT COUNT(*) FROM packing_lines WHERE batch_id=? "
                                                 "AND TRIM(COALESCE(design_no,''))<>'' "
                                                 "AND TRIM(COALESCE(product_code,''))=''", (b,))
        if e["purchase_rows"] and e["sales_rows"] and e["drafts"]:
            cls = "COMPLETE_REPLAY_ELIGIBLE"
        elif e["purchase_rows"] or e["sales_rows"]:
            cls = "PARTIAL_REPLAY_ELIGIBLE"
        else:
            cls = "INSUFFICIENT_EVIDENCE"
        e.update(classification=cls, batch_id=b, is_shipment=b.startswith("SHIPMENT_"))
        out[b] = e
    return out


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 1b — PRODUCT FISCAL CONVERGENCE CENSUS  (LOCAL EVIDENCE ONLY)
# ══════════════════════════════════════════════════════════════════════════
#
# Canonical Product identity and fiscal registration are DIFFERENT states.
# A resolved product_code with no wfirma_product_id is
# WFIRMA_REGISTRATION_REQUIRED -- NOT PRODUCT_MAPPING_REQUIRED.
#
# NO EXTERNAL wFIRMA CALL IS PERMITTED HERE. Classification uses only local
# mirror/mapping/cache tables, in the SAME precedence the application uses
# (routes_proforma._c1f_mirror_good_id: "mirror-first fiscal read, cache
# fallback"), so the census reflects what the running system would decide.
#
# Local evidence:
#   reservation_queue.wfirma_product_mirror   wfirma_id, deleted_flag   [Mirror]
#   reservation_queue.wfirma_product_mapping  wfirma_product_id, sync_status
#   wfirma.wfirma_products                    wfirma_product_id, sync_status [cache]

FISCAL_STATES = ("WFIRMA_MAPPING_EXISTS", "WFIRMA_REGISTRATION_REQUIRED",
                 "WFIRMA_PENDING_ADOPTION", "WFIRMA_MAPPING_CONFLICT",
                 "WFIRMA_LOCAL_EVIDENCE_UNAVAILABLE")


def _fiscal_evidence(snap: Path) -> Dict[str, Any]:
    """Load local wFirma evidence once. Absent tables => evidence unavailable."""
    rq, wf = snap / "reservation_queue.db", snap / "wfirma.db"
    ev: Dict[str, Any] = {"mirror": {}, "mapping": {}, "cache": {}, "available": False}
    mirror = q(rq, "SELECT product_code, wfirma_id, deleted_flag FROM wfirma_product_mirror")
    mapping = q(rq, "SELECT product_code, wfirma_product_id, sync_status "
                    "FROM wfirma_product_mapping")
    cache = q(wf, "SELECT product_code, wfirma_product_id, sync_status FROM wfirma_products")
    for r in mirror:
        ev["mirror"][(r["product_code"] or "").strip()] = {
            "wfirma_id": (r["wfirma_id"] or "").strip(),
            "deleted": int(r["deleted_flag"] or 0)}
    for r in mapping:
        ev["mapping"][(r["product_code"] or "").strip()] = {
            "wfirma_product_id": (r["wfirma_product_id"] or "").strip(),
            "sync_status": (r["sync_status"] or "").strip()}
    for r in cache:
        ev["cache"][(r["product_code"] or "").strip()] = {
            "wfirma_product_id": (r["wfirma_product_id"] or "").strip(),
            "sync_status": (r["sync_status"] or "").strip()}
    # "available" means we could READ the evidence, even if it holds zero rows.
    ev["available"] = any([
        mirror, mapping, cache,
        bool(q(rq, "SELECT name FROM sqlite_master WHERE type='table' "
                   "AND name='wfirma_product_mirror'"))])
    return ev


def classify_fiscal_state(product_code: str, ev: Dict[str, Any]) -> Dict[str, Any]:
    """LOCAL-ONLY fiscal classification for one canonical product_code."""
    pc = (product_code or "").strip()
    if not pc:
        return {"product_code": pc, "identity": "UNRESOLVED",
                "fiscal_state": "WFIRMA_LOCAL_EVIDENCE_UNAVAILABLE", "wfirma_id": ""}
    if not ev.get("available"):
        return {"product_code": pc, "identity": "PRODUCT_IDENTITY_RESOLVED",
                "fiscal_state": "WFIRMA_LOCAL_EVIDENCE_UNAVAILABLE", "wfirma_id": ""}

    m = ev["mirror"].get(pc) or {}
    g = ev["mapping"].get(pc) or {}
    c = ev["cache"].get(pc) or {}
    mirror_id = "" if m.get("deleted") else (m.get("wfirma_id") or "")
    map_id = g.get("wfirma_product_id") or ""
    cache_id = c.get("wfirma_product_id") or ""
    status = (g.get("sync_status") or c.get("sync_status") or "").lower()

    ids = {i for i in (mirror_id, map_id, cache_id) if i}
    if len(ids) > 1:
        state = "WFIRMA_MAPPING_CONFLICT"
    elif mirror_id or map_id or cache_id:          # mirror-first, cache fallback
        state = "WFIRMA_MAPPING_EXISTS"
    elif status == "pending_adoption":
        state = "WFIRMA_PENDING_ADOPTION"
    else:
        state = "WFIRMA_REGISTRATION_REQUIRED"
    return {"product_code": pc, "identity": "PRODUCT_IDENTITY_RESOLVED",
            "fiscal_state": state, "wfirma_id": mirror_id or map_id or cache_id,
            "sync_status": status,
            "sources": {"mirror": mirror_id, "mapping": map_id, "cache": cache_id}}


def phase1_fiscal_convergence(snap: Path) -> Dict[str, Any]:
    """Census every canonical product_code seen in packing evidence."""
    ev = _fiscal_evidence(snap)
    codes = sorted({(r[0] or "").strip() for r in
                    q(snap / "packing.db",
                      "SELECT DISTINCT product_code FROM packing_lines "
                      "WHERE TRIM(COALESCE(product_code,''))<>''") if (r[0] or "").strip()})
    rows = [classify_fiscal_state(pc, ev) for pc in codes]
    return {"evidence_available": ev["available"],
            "products_examined": len(rows),
            "by_state": dict(Counter(r["fiscal_state"] for r in rows)),
            "registration_required": [r["product_code"] for r in rows
                                      if r["fiscal_state"] == "WFIRMA_REGISTRATION_REQUIRED"],
            "conflicts": [r for r in rows if r["fiscal_state"] == "WFIRMA_MAPPING_CONFLICT"],
            "pending_adoption": [r["product_code"] for r in rows
                                 if r["fiscal_state"] == "WFIRMA_PENDING_ADOPTION"],
            "rows": rows}


def phase1_d6_impact(snap: Path) -> Dict[str, Any]:
    """Measure the D-6 target semantics against real drafts (read-only).

        Draft/Approve : product identity required, wFirma ID NOT required
        Post/Convert  : both required

    A draft is 'blocked SOLELY by missing wfirma_product_id' when at least one
    billable line lacks a fiscal mapping AND no other LOCALLY DETECTABLE
    blocker exists (blank product_code line, or missing/zero price).

    Honesty limit: other blocker classes (design ambiguity, WDT EU-VAT,
    over-bill, duplicate-document) require _derive_draft_readiness, which calls
    _build_preview -- a WRITER (routes_proforma.py:798-806). Phase 1 stays
    read-only, so those are reported as not-locally-determinable rather than
    assumed absent.
    """
    ev = _fiscal_evidence(snap)
    out: Dict[str, Any] = {"drafts_examined": 0,
                           "blocked_solely_by_missing_wfirma_id": 0,
                           "would_become_commercial_ready": 0,
                           "post_convert_blockers_correctly_remain": 0,
                           "has_other_local_blockers": 0,
                           "no_fiscal_blocker": 0,
                           "not_locally_determinable_note":
                               "design ambiguity / WDT EU-VAT / over-bill / duplicate-doc "
                               "require readiness derivation (a writer) — deferred to Phase 3",
                           "details": []}
    for d_ in q(snap / "proforma_links.db",
                "SELECT id, batch_id, client_name, draft_state, posted_at, "
                "editable_lines_json FROM proforma_drafts"):
        out["drafts_examined"] += 1
        try:
            lines = json.loads(d_["editable_lines_json"] or "[]") or []
        except Exception:
            lines = []
        billable = [ln for ln in lines if str(ln.get("product_code") or "").strip()]
        blank_lines = len(lines) - len(billable)
        missing_price = sum(
            1 for ln in billable
            if not str(ln.get("unit_price") or "").strip()
            or _safe_float(ln.get("unit_price")) <= 0)
        unmapped = [pc for pc in {str(ln.get("product_code")).strip() for ln in billable}
                    if classify_fiscal_state(pc, ev)["fiscal_state"]
                    != "WFIRMA_MAPPING_EXISTS"]
        other_local = bool(blank_lines or missing_price)

        if not unmapped:
            out["no_fiscal_blocker"] += 1
            bucket = "NO_FISCAL_BLOCKER"
        else:
            out["post_convert_blockers_correctly_remain"] += 1
            if other_local:
                out["has_other_local_blockers"] += 1
                bucket = "FISCAL_PLUS_OTHER_LOCAL_BLOCKERS"
            else:
                out["blocked_solely_by_missing_wfirma_id"] += 1
                out["would_become_commercial_ready"] += 1
                bucket = "SOLELY_MISSING_WFIRMA_ID"
        out["details"].append({
            "draft_id": d_["id"], "batch_id": d_["batch_id"],
            "client": d_["client_name"], "state": d_["draft_state"],
            "posted": bool(d_["posted_at"]), "lines": len(lines),
            "billable": len(billable), "blank_product_code_lines": blank_lines,
            "missing_price_lines": missing_price,
            "unmapped_product_codes": sorted(unmapped), "bucket": bucket})
    return out


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 3 — HISTORICAL REPLAY
# ══════════════════════════════════════════════════════════════════════════

def phase3_replay(batch_id: str, snap: Path) -> Dict[str, Any]:
    from app.services import product_authority_resolver as par
    pack, docs, prof = snap / "packing.db", snap / "documents.db", snap / "proforma_links.db"
    res: Dict[str, Any] = {"batch_id": batch_id, "errors": [], "diffs": [], "counts": Counter()}

    try:
        auth = par.resolve_batch_product_authority(batch_id, packing_db_path=pack)
    except Exception as exc:
        res["errors"].append(f"resolver: {type(exc).__name__}: {exc}")
        return res

    res["authority_available"] = auth.get("authority_available")
    d2p: Dict[str, List[str]] = auth.get("design_to_product_codes") or {}
    avail: Dict[str, float] = auth.get("available_by_product_code") or {}
    res.update(replay_design_count=len(d2p), replay_product_count=len(avail),
               unassigned_designs=len(auth.get("unassigned_by_design") or {}),
               replay_available_qty=round(sum(avail.values()), 4))

    def cands_for(d: str) -> List[str]:
        return d2p.get(d) or d2p.get(d.strip()) or d2p.get(d.strip().upper()) or []

    prows = q(pack, "SELECT design_no, product_code, quantity FROM packing_lines WHERE batch_id=?", (batch_id,))
    res["purchase_rows"] = len(prows)
    res["purchase_pieces"] = round(sum(float(r["quantity"] or 0) for r in prows), 4)
    for r in prows:
        d, p = (r["design_no"] or "").strip(), (r["product_code"] or "").strip()
        if not d or not p:
            res["counts"]["purchase_blank_side"] += 1
        elif p in (d2p.get(d) or []):
            res["counts"]["EXACT_SAME"] += 1
        elif p in cands_for(d):
            res["counts"]["NORMALIZATION_ONLY"] += 1
        else:
            res["counts"]["UNKNOWN"] += 1
            res["diffs"].append({"kind": "PURCHASE_IDENTITY", "class": "UNKNOWN",
                                 "design_no": d, "historical_product_code": p,
                                 "replay_candidates": cands_for(d)})

    srows = q(docs, "SELECT design_no, product_code, quantity FROM sales_packing_lines WHERE batch_id=?", (batch_id,))
    res["sales_rows"] = len(srows)
    for r in srows:
        d, hist = (r["design_no"] or "").strip(), (r["product_code"] or "").strip()
        c = cands_for(d)
        if not d:
            res["counts"]["sales_no_design"] += 1
        elif not hist:
            res["counts"]["sales_unresolved_historically"] += 1
        elif len(c) == 1 and c[0] == hist:
            res["counts"]["SALES_TIER1_REPRODUCED"] += 1
        elif hist in c:
            res["counts"]["SALES_CANDIDATE_PRESENT"] += 1
        else:
            res["counts"]["UNKNOWN"] += 1
            res["diffs"].append({"kind": "SALES_IDENTITY", "class": "UNKNOWN",
                                 "design_no": d, "historical_product_code": hist,
                                 "replay_candidates": c})

    res["drafts"] = []
    for d_ in q(prof, "SELECT id, client_name, draft_state, posted_at, currency, "
                      "editable_lines_json FROM proforma_drafts WHERE batch_id=?", (batch_id,)):
        try:
            lines = json.loads(d_["editable_lines_json"] or "[]") or []
        except Exception:
            lines = []
            res["errors"].append(f"draft {d_['id']}: editable_lines_json unparseable")
            res["counts"]["DATA_QUALITY_PROBLEM"] += 1
        billable = [ln for ln in lines if str(ln.get("product_code") or "").strip()]
        res["drafts"].append({
            "draft_id": d_["id"], "client": d_["client_name"], "state": d_["draft_state"],
            "posted": bool(d_["posted_at"]), "currency": d_["currency"],
            "line_count": len(lines), "billable_line_count": len(billable),
            "provisional_line_count": len(lines) - len(billable),
            "resolution_sources": dict(Counter(
                (ln.get("resolution_source") or "").strip() or "(none)" for ln in lines)),
            "total_qty": round(sum(float(ln.get("quantity") or 0) for ln in lines), 4)})
    return res


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 4 — D-2 RESOLUTION ANALYSIS
# ══════════════════════════════════════════════════════════════════════════

def phase4_d2(replays: List[Dict[str, Any]]) -> Dict[str, Any]:
    srcs: Counter = Counter()
    for r in replays:
        for d_ in r.get("drafts", []):
            for k, v in (d_.get("resolution_sources") or {}).items():
                srcs[k] += v
    hits = sum(r["counts"].get("SALES_CANDIDATE_PRESENT", 0)
               + r["counts"].get("SALES_TIER1_REPRODUCED", 0) for r in replays)
    miss = sum(1 for r in replays for d in r.get("diffs", []) if d.get("kind") == "SALES_IDENTITY")
    tot = hits + miss
    return {"resolution_source_distribution": dict(srcs),
            "deterministic_rows": srcs.get("batch_packing_lines", 0) + srcs.get("exact_variant_match", 0),
            "heuristic_rows_to_migrate": srcs.get("spec_reconciliation", 0),
            "candidate_recall": {"hits": hits, "misses": miss, "total": tot,
                                 "pct": round(100.0 * hits / tot, 3) if tot else None,
                                 "target": 100.0}}


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 5 — REVERSE ADVANCE SIMULATION (arithmetic; writes nothing)
# ══════════════════════════════════════════════════════════════════════════

def phase5_reverse(batch_id: str, snap: Path) -> Dict[str, Any]:
    pack, docs, wh = snap / "packing.db", snap / "documents.db", snap / "warehouse.db"
    expected = round(sum(float(r["quantity"] or 0) for r in
                     q(pack, "SELECT quantity FROM packing_lines WHERE batch_id=?", (batch_id,))), 4)
    planned = round(sum(float(r["quantity"] or 0) for r in
                    q(docs, "SELECT quantity FROM sales_packing_lines WHERE batch_id=?", (batch_id,))), 4)
    physical_hist = scalar(wh, "SELECT COUNT(*) FROM inventory_state WHERE batch_id=? "
                               "AND state='WAREHOUSE_STOCK'", (batch_id,))
    design_only = scalar(docs, "SELECT COUNT(*) FROM sales_packing_lines WHERE batch_id=? "
                               "AND TRIM(COALESCE(design_no,''))<>'' "
                               "AND TRIM(COALESCE(product_code,''))=''", (batch_id,))
    pre = {"PHYSICAL": 0.0, "RESERVED_PHYSICAL": 0.0, "AVAILABLE_PHYSICAL": 0.0,
           "EXPECTED_INBOUND": expected, "PLANNED_ALLOCATION": planned,
           "UNALLOCATED_EXPECTED": round(expected - planned, 4)}
    post_physical = float(physical_hist) if physical_hist else expected
    conv = {"expected_collapses_to_zero": True,
            "planned_within_expected": (planned <= expected) if expected else (planned == 0),
            "shortfall": round(max(0.0, planned - post_physical), 4),
            "design_only_rows_retained": design_only}
    conv["converged"] = bool(conv["planned_within_expected"] and conv["shortfall"] == 0.0)
    return {"batch_id": batch_id, "pre_pz": pre,
            "post_receipt": {"PHYSICAL": post_physical, "EXPECTED_INBOUND": 0.0,
                             "PLANNED_ALLOCATION": planned},
            "convergence": conv,
            "note": ("shortfall>0 = Scenario-3: advisory pre-arrival, TRUE blocker "
                     "post-arrival (Lesson N over-bill)") if conv["shortfall"] else ""}


# ══════════════════════════════════════════════════════════════════════════
#  ADVERSARIAL ISOLATION TEST
# ══════════════════════════════════════════════════════════════════════════

def adversarial_isolation_test(app_parent: Path, live: Path, workdir: Path,
                               log) -> Dict[str, Any]:
    """Deliberately invoke known writer-capable paths and prove the snapshot may
    change while LIVE storage does not. This is the load-bearing gate."""
    log("\n" + "=" * 78 + "\n  ADVERSARIAL ISOLATION TEST\n" + "=" * 78)
    snap = workdir / "selftest-snap"
    if snap.exists():
        shutil.rmtree(snap)
    gates: Dict[str, Any] = {}

    log("  [3] hash live storage root (whole tree)")
    pre = hash_tree(live)
    log(f"      {len(pre)} files hashed")

    log("  [4/5/6] snapshot ENTIRE storage root")
    st = snapshot_storage_root(live, snap, log)
    log(f"      sqlite(.backup)={st['sqlite_backup']} fallback={st['sqlite_copy_fallback']} "
        f"files={st['files_copied']} dirs={st['dirs_copied']}")
    snap_pre = hash_tree(snap)

    log("  [7pre] import-order guard (BEFORE any app import)")
    sys.path.insert(0, str(app_parent))
    guard = assert_import_order_guard(log)
    gates["IMPORT_ORDER_GUARD"] = guard["pass"]

    log("  [8] network kill-switch")
    net = install_network_killswitch(log)

    log("  [7] redirect storage_root")
    red = redirect_storage_root(snap, log)
    gates["MASTER_AUDIT_REDIRECTION"] = red["master_audit_redirected"]

    log("  [9] import application modules + verify path redirection")
    pathres = verify_path_redirection(snap, log)
    gates["OUTPUT_PATH_REDIRECTION"] = pathres["pass"]

    log("  [10] redirect DB authorities")
    dbs = redirect_databases(snap, log)
    for k, v in dbs.items():
        log(f"      {k:<18} {'OK' if v else 'FAILED'}")

    log("  [11] invoke WRITER-CAPABLE paths ON PURPOSE")
    invoked: List[str] = []

    try:                                                   # H2
        from app.services.design_product_bridge import populate_from_packing
        populate_from_packing("SELFTEST_BATCH",
                              packing_db_path=snap / "packing.db",
                              reservation_db_path=snap / "reservation_queue.db")
        invoked.append("populate_from_packing (H2) OK")
    except Exception as exc:
        invoked.append(f"populate_from_packing (H2) raised {type(exc).__name__}")

    try:                                                   # H3
        from app.services import description_engine as de
        fn = getattr(de, "get_description_block", None)
        if fn:
            fn("SELFTEST-DESC-1", item_type="RING")
            invoked.append("description_engine.get_description_block (H3) OK")
        else:
            invoked.append("description_engine.get_description_block ABSENT")
    except Exception as exc:
        invoked.append(f"description_engine (H3) raised {type(exc).__name__}")

    try:                                                   # Product Master upsert
        from app.services.reservation_db import upsert_product_master
        upsert_product_master(snap / "reservation_queue.db",
                              "SELFTEST-PM-1", "SELFTEST-D1")
        invoked.append("upsert_product_master OK")
    except Exception as exc:
        invoked.append(f"upsert_product_master raised {type(exc).__name__}")

    try:                                                   # HAZARD A
        from app.core.audit import audit_safe, audit_db_path
        from app.core.config import settings as _s
        p = audit_db_path()
        if (snap == p.parent) or (snap in p.parents):
            # audit_safe is flag-gated (audit_hardening_enabled default False ->
            # returns -1, writes nothing). Force ON in-process only, restored in
            # finally; otherwise this gate silently proves nothing. Production may
            # legitimately run with it ON.
            _prev = getattr(_s, "audit_hardening_enabled", False)
            try:
                _s.audit_hardening_enabled = True
                rc = audit_safe("replay_harness_selftest", "upsert", "isolation-proof",
                                actor="ej_replay_harness", reason="HAZARD-A proof")
            finally:
                _s.audit_hardening_enabled = _prev
            invoked.append(f"audit_safe (HAZARD A) rc={rc} "
                           f"{'WROTE' if isinstance(rc, int) and rc > 0 else 'no-op'}")
        else:
            invoked.append(f"audit_safe REFUSED — path outside snapshot: {p}")
    except Exception as exc:
        invoked.append(f"audit_safe (HAZARD A) raised {type(exc).__name__}")

    for i in invoked:
        log(f"      {i}")

    log("  [12] verify network kill-switch fires")
    try:
        import socket
        s = socket.socket(); s.settimeout(2)
        s.connect(("203.0.113.1", 80))          # TEST-NET-3 — must never be reached
        gates["NETWORK_KILL_SWITCH"] = False
        log("      *** KILL-SWITCH FAILED — outbound connect permitted ***")
    except NetworkBlocked:
        gates["NETWORK_KILL_SWITCH"] = True
        log("      NetworkBlocked raised — kill-switch works")
    except Exception as exc:
        gates["NETWORK_KILL_SWITCH"] = False
        log(f"      inconclusive ({type(exc).__name__}) — guard not reached")

    log("  [13] re-hash live + snapshot")
    post, snap_post = hash_tree(live), hash_tree(snap)
    live_d, snap_d = diff_hashes(pre, post), diff_hashes(snap_pre, snap_post)
    live_clean = not (live_d["changed"] or live_d["removed"] or live_d["added"])
    snap_moved = bool(snap_d["changed"] or snap_d["added"])
    gates["SOURCE_STORAGE_HASH_SAFETY"] = live_clean
    gates["SOURCE_DB_HASH_SAFETY"] = not [k for k in live_d["changed"]
                                          if k.endswith(SQLITE_SUFFIXES)]

    log(f"      live : changed={len(live_d['changed'])} added={len(live_d['added'])} "
        f"removed={len(live_d['removed'])}")
    log(f"      snap : changed={len(snap_d['changed'])} added={len(snap_d['added'])}")
    for k in live_d["changed"][:10]:
        log(f"        LIVE CHANGED: {k}")

    verdict = all(gates.values())
    log("\n  SAFETY GATES")
    for g in ("SOURCE_DB_HASH_SAFETY", "SOURCE_STORAGE_HASH_SAFETY",
              "MASTER_AUDIT_REDIRECTION", "OUTPUT_PATH_REDIRECTION",
              "NETWORK_KILL_SWITCH", "IMPORT_ORDER_GUARD"):
        log(f"    {g:<32} {'PASS' if gates.get(g) else 'FAIL'}")
    log(f"    {'writers moved snapshot':<32} {'observed' if snap_moved else 'not observed'}")
    log(f"    {'VERDICT':<32} {'PASS' if verdict else 'FAIL'}")

    return {"gates": gates, "verdict": verdict, "live_diff": live_d,
            "snapshot_diff": snap_d, "invoked": invoked, "snapshot_stats": st,
            "path_redirection": pathres,
            "network": {"attempts": len(net["attempts"]), "blocked": net["blocked"]}}


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="EJ historical replay certification harness")
    ap.add_argument("--storage", required=True, help=r"live storage root, e.g. C:\PZ\app\storage")
    ap.add_argument("--out", required=True, help=r"output dir, e.g. C:\PZ-archive\replay-2026-08-18")
    ap.add_argument("--app-parent", default="", help=r"parent of app\ (default: storage's grandparent)")
    ap.add_argument("--phase", default=None, choices=["1", "3", "4", "5"])
    ap.add_argument("--all", action="store_true", help="run phases 1,3,4,5")
    ap.add_argument("--self-test", action="store_true", help="adversarial isolation test only")
    ap.add_argument("--limit", type=int, default=0, help="0 = ALL eligible (required for certification)")
    a = ap.parse_args()

    if not a.self_test and not a.phase and not a.all:
        ap.error("choose --phase {1,3,4,5} or --all or --self-test "
                 "(no phase is ever run implicitly)")

    storage, out = Path(a.storage), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    snap = out / "snap"
    logf = (out / "replay.log").open("w", encoding="utf-8")

    def log(m: str = "") -> None:
        print(m); logf.write(m + "\n"); logf.flush()

    log(f"EJ HISTORICAL REPLAY CERTIFICATION HARNESS v{HARNESS_VERSION}   {now()}")
    log(f"architecture baseline : {BASELINE}")
    log(f"V1_SOURCE_SHA256      : {V1_SOURCE_SHA256}")
    log(f"live storage root     : {storage}")
    log(f"out                   : {out}")

    if not storage.exists():
        log(f"FATAL: storage not found: {storage}"); return 2
    if snap.resolve() == storage.resolve():
        log("FATAL: snapshot root == live storage root. Refusing."); return 2

    app_parent = Path(a.app_parent) if a.app_parent else storage.parent.parent

    if a.self_test:
        r = adversarial_isolation_test(app_parent, storage, out, log)
        (out / "selftest-report.json").write_text(
            json.dumps(r, indent=2, default=str), encoding="utf-8")
        log(f"\nJSON -> {out / 'selftest-report.json'}")
        logf.close()
        return 0 if r["verdict"] else 3

    log("\n== [3] hashing live storage root (whole tree) ==")
    pre = hash_tree(storage)
    log(f"   {len(pre)} files hashed")

    log("\n== [4/5/6] snapshot ENTIRE storage root ==")
    st = snapshot_storage_root(storage, snap, log)
    log(f"   sqlite(.backup)={st['sqlite_backup']} fallback={st['sqlite_copy_fallback']} "
        f"files={st['files_copied']} dirs={st['dirs_copied']}")

    log("\n== [7pre] import-order guard ==")
    sys.path.insert(0, str(app_parent))
    guard = assert_import_order_guard(log)
    if not guard["pass"]:
        log("FATAL: application modules already imported — isolation void."); return 2

    log("\n== [8] network kill-switch ==")
    net = install_network_killswitch(log)

    log("\n== [7] redirect storage_root ==")
    try:
        red = redirect_storage_root(snap, log)
    except Exception as exc:
        log(f"FATAL: redirection failed: {exc}")
        log(traceback.format_exc()[-1200:]); return 2
    if not red["master_audit_redirected"]:
        log("FATAL: master_audit.sqlite not redirected (HAZARD A)."); return 3

    log("\n== [9] import application + verify path redirection ==")
    try:
        import app  # noqa: F401
        log("    import app: OK")
    except Exception as exc:
        log(f"FATAL: cannot import app: {exc}")
        log(traceback.format_exc()[-1200:]); return 2
    pathres = verify_path_redirection(snap, log)
    if not pathres["pass"]:
        log("FATAL: an import-time storage path resolves OUTSIDE the snapshot."); return 3

    log("\n== [10] redirect DB authorities ==")
    redirected = redirect_databases(snap, log)
    for k, v in redirected.items():
        log(f"    {k:<18} {'OK' if v else 'FAILED'}")
    if not redirected.get("packing_db"):
        log("FATAL: packing_db not redirected."); return 2

    report: Dict[str, Any] = {
        "harness_version": HARNESS_VERSION, "generated_at": now(),
        "architecture_baseline": BASELINE, "v1_source_sha256": V1_SOURCE_SHA256,
        "storage": str(storage), "snapshot": str(snap), "snapshot_stats": st,
        "import_order_guard": guard, "storage_root_redirect": red,
        "path_redirection": pathres, "live_file_count_pre": len(pre)}
    phases = {"1", "3", "4", "5"} if a.all else {a.phase}

    corpus: Dict[str, Dict[str, Any]] = {}
    eligible: List[str] = []
    if "1" in phases or phases & {"3", "4", "5"}:
        log("\n" + "=" * 78 + "\n  PHASE 1 — CORPUS DISCOVERY\n" + "=" * 78)
        corpus = phase1_discover(snap)
        report["corpus"] = corpus
        for k, v in Counter(v["classification"] for v in corpus.values()).items():
            log(f"  {k:<30} {v}")
        log(f"  {'TOTAL':<30} {len(corpus)}")
        if corpus:
            hdr = (f"\n{'batch_id':<50}{'classification':<26}{'pur':>6}{'sal':>6}"
                   f"{'inv':>6}{'pz':>4}{'drf':>5}{'pst':>4}{'d-only':>7}")
            log(hdr); log("-" * (len(hdr) - 1))
            for b in sorted(corpus, key=lambda x: -corpus[x]["purchase_rows"]):
                e = corpus[b]
                log(f"{b[:49]:<50}{e['classification']:<26}{e['purchase_rows']:>6}"
                    f"{e['sales_rows']:>6}{e['inventory_rows']:>6}{e['pz_docs']:>4}"
                    f"{e['drafts']:>5}{e['posted_drafts']:>4}{e['sales_design_only']:>7}")
        eligible = [b for b, e in corpus.items()
                    if e["classification"] in ("COMPLETE_REPLAY_ELIGIBLE", "PARTIAL_REPLAY_ELIGIBLE")]
        if a.limit:
            log(f"\n  *** --limit {a.limit}: NOT a certification run ({len(eligible)} eligible) ***")
            eligible = eligible[:a.limit]

        # ── PHASE 1b — Product Fiscal Convergence (LOCAL EVIDENCE ONLY) ──
        log("\n" + "=" * 78 + "\n  PHASE 1b — PRODUCT FISCAL CONVERGENCE (local evidence only)\n"
            + "=" * 78)
        fis = phase1_fiscal_convergence(snap)
        report["fiscal_convergence"] = fis
        log(f"  local wFirma evidence available ....... {fis['evidence_available']}")
        log(f"  canonical product codes examined ...... {fis['products_examined']}")
        for st in FISCAL_STATES:
            log(f"    {st:<38} {fis['by_state'].get(st, 0)}")
        if fis["conflicts"]:
            log("\n  *** MAPPING CONFLICTS (differing wfirma ids across local sources) ***")
            for c in fis["conflicts"][:20]:
                log(f"      {c['product_code']}  {c['sources']}")
        if fis["registration_required"]:
            log(f"\n  registration-required sample (first 20 of "
                f"{len(fis['registration_required'])}):")
            for pc in fis["registration_required"][:20]:
                log(f"      {pc}")
        log("\n  NOTE: no external wFirma call was made. Classification uses local "
            "mirror/mapping/cache only, mirror-first (matching _c1f_mirror_good_id).")

        # ── D-6 readiness impact ──────────────────────────────────────────
        log("\n" + "=" * 78 + "\n  D-6 READINESS IMPACT (measurement only — nothing changed)\n"
            + "=" * 78)
        d6 = phase1_d6_impact(snap)
        report["d6_impact"] = d6
        log(f"  drafts examined ....................................... {d6['drafts_examined']}")
        log(f"  approve blocked SOLELY by missing wfirma_product_id ... "
            f"{d6['blocked_solely_by_missing_wfirma_id']}")
        log(f"  would become Commercial-Ready under D-6 ............... "
            f"{d6['would_become_commercial_ready']}")
        log(f"  Post/Convert blockers correctly remaining ............. "
            f"{d6['post_convert_blockers_correctly_remain']}")
        log(f"  drafts with other locally-detectable blockers ......... "
            f"{d6['has_other_local_blockers']}")
        log(f"  drafts with no fiscal blocker ......................... "
            f"{d6['no_fiscal_blocker']}")
        log(f"  LIMIT: {d6['not_locally_determinable_note']}")

    replays: List[Dict[str, Any]] = []
    if "3" in phases or "4" in phases:
        log("\n" + "=" * 78 + "\n  PHASE 3 — HISTORICAL REPLAY\n" + "=" * 78)
        agg: Counter = Counter()
        for b in eligible:
            r = phase3_replay(b, snap); replays.append(r)
            for k, v in r["counts"].items():
                agg[k] += v
            bad = r["counts"].get("UNKNOWN", 0) or r["counts"].get("DATA_QUALITY_PROBLEM", 0)
            log(f"  [{'FAIL' if bad else ' ok '}] {b[:46]:<48} pur={r.get('purchase_rows',0):>5} "
                f"sal={r.get('sales_rows',0):>5} diffs={len(r['diffs']):>3} err={len(r['errors'])}")
        report["replays"], report["aggregate"] = replays, dict(agg)
        report["certification_blocking_unknowns"] = int(agg.get("UNKNOWN", 0))
        log("\n  -- aggregate --")
        for k in sorted(agg):
            log(f"    {k:<46} {agg[k]}")

    if "4" in phases:
        log("\n" + "=" * 78 + "\n  PHASE 4 — D-2 RESOLUTION ANALYSIS\n" + "=" * 78)
        d2 = phase4_d2(replays); report["phase4"] = d2
        for k, v in d2["resolution_source_distribution"].items():
            log(f"    {k:<40} {v}")
        log(f"    deterministic rows (tier 0-2) ......... {d2['deterministic_rows']}")
        log(f"    heuristic rows to migrate (D-2) ....... {d2['heuristic_rows_to_migrate']}")
        log(f"    candidate recall ...................... {d2['candidate_recall']}")

    if "5" in phases:
        log("\n" + "=" * 78 + "\n  PHASE 5 — REVERSE ADVANCE SIMULATION\n" + "=" * 78)
        sims, conv = [], 0
        for b in eligible:
            s = phase5_reverse(b, snap); sims.append(s)
            conv += 1 if s["convergence"]["converged"] else 0
            c = s["convergence"]
            log(f"  [{'conv' if c['converged'] else 'DIFF'}] {b[:44]:<46} "
                f"exp={s['pre_pz']['EXPECTED_INBOUND']:>9} plan={s['pre_pz']['PLANNED_ALLOCATION']:>9} "
                f"unalloc={s['pre_pz']['UNALLOCATED_EXPECTED']:>9} short={c['shortfall']}")
        report["reverse_simulation"] = sims
        report["reverse_convergence"] = f"{conv}/{len(sims)}"
        log(f"\n  convergence: {conv}/{len(sims)}")

    log("\n" + "=" * 78 + "\n  SAFETY PROOF — LIVE STORAGE ROOT UNCHANGED\n" + "=" * 78)
    post = hash_tree(storage)
    d = diff_hashes(pre, post)
    db_changed = [k for k in d["changed"] if k.endswith(SQLITE_SUFFIXES)]
    breach = bool(d["changed"] or d["removed"] or d["added"])
    gates = {"SOURCE_DB_HASH_SAFETY": not db_changed,
             "SOURCE_STORAGE_HASH_SAFETY": not breach,
             "MASTER_AUDIT_REDIRECTION": red["master_audit_redirected"],
             "OUTPUT_PATH_REDIRECTION": pathres["pass"],
             "NETWORK_KILL_SWITCH": net["armed"],
             "IMPORT_ORDER_GUARD": guard["pass"]}
    report["safety"] = {"live_hash_diff": d, "gates": gates,
                        "network_attempts": len(net["attempts"]),
                        "network_blocked": net["blocked"]}
    for g, v in gates.items():
        log(f"  {g:<32} {'PASS' if v else 'FAIL'}")
    if breach:
        log("\n  *** SAFETY_FAILURE — live storage CHANGED ***")
        for k in (d["changed"] + d["added"] + d["removed"])[:20]:
            log(f"      {k}")
        report["verdict"] = "SAFETY_FAILURE"
    else:
        log(f"\n  all {len(pre)} live files byte-identical — ZERO WRITES CONFIRMED")
        report["verdict"] = "SAFE"

    (out / "replay-report.json").write_text(json.dumps(report, indent=2, default=str),
                                            encoding="utf-8")
    log(f"\nJSON -> {out / 'replay-report.json'}")
    log(f"LOG  -> {out / 'replay.log'}")
    logf.close()
    return 3 if (breach or not all(gates.values())) else 0


if __name__ == "__main__":
    sys.exit(main())
