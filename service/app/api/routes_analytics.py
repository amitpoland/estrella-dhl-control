"""
Phase A — Local Analytics
Reads all audit.json files and returns aggregated reporting data.
No wFirma API calls.  Safe, read-only.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.security import require_api_key

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
_auth  = Depends(require_api_key)

_OUTPUTS = settings.storage_root / "outputs"
_MAX_BATCHES = 500


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _read_audit(batch_dir: Path) -> Optional[Dict[str, Any]]:
    p = batch_dir / "audit.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _month_from_audit(a: Dict[str, Any]) -> str:
    """Return YYYY-MM from clearance_date, then timestamp, then '0000-00'."""
    cd = (a.get("customs_declaration") or {}).get("clearance_date") or ""
    ts = a.get("timestamp") or ""
    for raw in (cd, ts):
        if raw and len(raw) >= 7:
            try:
                dt = datetime.fromisoformat(raw[:10])
                return dt.strftime("%Y-%m")
            except ValueError:
                pass
    return "0000-00"


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v or 0)
        return f if f == f else default   # NaN guard
    except (TypeError, ValueError):
        return default


def _collect_batches() -> List[Dict[str, Any]]:
    """Scan outputs directory and return all readable audit summaries."""
    if not _OUTPUTS.exists():
        return []
    dirs = sorted(
        (d for d in _OUTPUTS.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:_MAX_BATCHES]

    rows = []
    for d in dirs:
        a = _read_audit(d)
        if not a:
            continue
        rows.append(a)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Aggregators
# ─────────────────────────────────────────────────────────────────────────────

def _build_duty_by_month(batches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Card 1 — Import Duty A00 by Month.
    Groups duty_a00_pln by YYYY-MM using clearance_date (fallback: timestamp).
    Only includes batches that have a SAD-processed customs_declaration.
    """
    monthly: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"duty_pln": 0.0, "batches": 0, "batch_list": []}
    )
    for a in batches:
        cd  = a.get("customs_declaration") or {}
        mrn = cd.get("mrn") or ""
        if not mrn:
            continue   # no SAD → skip
        duty = _safe_float(cd.get("duty_a00_pln"))
        mon  = _month_from_audit(a)
        monthly[mon]["duty_pln"]   += duty
        monthly[mon]["batches"]    += 1
        monthly[mon]["batch_list"].append({
            "batch_id": a.get("batch_id", ""),
            "doc_no":   a.get("doc_no", ""),
            "duty_pln": round(duty, 2),
            "awb":      (a.get("inputs") or {}).get("awb") or a.get("tracking_no") or "",
        })

    result = []
    for mon, data in sorted(monthly.items()):
        result.append({
            "month":         mon,
            "duty_pln":      round(data["duty_pln"], 2),
            "batches":       data["batches"],
            "breakdown":     sorted(data["batch_list"], key=lambda x: x["doc_no"]),
        })
    return result


def _build_shipment_value_by_month(batches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Card 2 — Monthly Shipment Value (net / gross).
    Includes all batches with totals, grouped by month.
    """
    monthly: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"net_pln": 0.0, "gross_pln": 0.0, "batches": 0}
    )
    for a in batches:
        t   = a.get("totals") or {}
        net = _safe_float(t.get("net"))
        grs = _safe_float(t.get("gross"))
        if net == 0 and grs == 0:
            continue
        mon = _month_from_audit(a)
        monthly[mon]["net_pln"]   += net
        monthly[mon]["gross_pln"] += grs
        monthly[mon]["batches"]   += 1

    result = []
    for mon, data in sorted(monthly.items()):
        result.append({
            "month":     mon,
            "net_pln":   round(data["net_pln"], 2),
            "gross_pln": round(data["gross_pln"], 2),
            "batches":   data["batches"],
        })
    return result


def _build_inventory(batches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Card 3 — Inventory / PZ Value.
    Sum of totals.net for batches with status success or partial.
    """
    total_net   = 0.0
    total_gross = 0.0
    batch_count = 0
    last_batch: Optional[Dict[str, Any]] = None
    last_ts     = ""

    for a in batches:
        status = a.get("status") or ""
        if status not in ("success", "partial"):
            continue
        t     = a.get("totals") or {}
        net   = _safe_float(t.get("net"))
        grs   = _safe_float(t.get("gross"))
        if net == 0 and grs == 0:
            continue
        total_net   += net
        total_gross += grs
        batch_count += 1
        ts = a.get("timestamp") or ""
        if ts > last_ts:
            last_ts = ts
            last_batch = {
                "batch_id": a.get("batch_id", ""),
                "doc_no":   a.get("doc_no", ""),
                "net_pln":  round(net, 2),
                "gross_pln": round(grs, 2),
                "date":     ts[:10] if ts else "",
                "awb":      (a.get("inputs") or {}).get("awb") or a.get("tracking_no") or "",
            }

    return {
        "total_net_pln":   round(total_net, 2),
        "total_gross_pln": round(total_gross, 2),
        "batch_count":     batch_count,
        "last_batch":      last_batch,
        "wfirma_live":     False,   # Phase C only
    }


def _build_wfirma_sync(batches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Card 4 — wFirma Sync Status.
    Reads wfirma_export block from each audit.json.
    """
    total_with_pz = 0
    exported      = 0
    pending_list: List[Dict[str, Any]] = []
    exported_list: List[Dict[str, Any]] = []
    last_exported_at  = ""
    last_exported_doc = ""

    for a in batches:
        # Only count batches that have a completed PZ (status success/partial)
        status = a.get("status") or ""
        if status not in ("success", "partial"):
            continue
        total_with_pz += 1

        wfe = a.get("wfirma_export") or {}
        mode = wfe.get("mode") or ""
        ts   = wfe.get("timestamp") or ""
        doc  = a.get("doc_no") or ""
        awb  = (a.get("inputs") or {}).get("awb") or a.get("tracking_no") or ""

        if mode in ("clipboard", "json", "api"):
            exported += 1
            exported_list.append({
                "batch_id":  a.get("batch_id", ""),
                "doc_no":    doc,
                "awb":       awb,
                "mode":      mode,
                "exported_at": ts,
            })
            if ts > last_exported_at:
                last_exported_at  = ts
                last_exported_doc = doc
        else:
            pending_list.append({
                "batch_id": a.get("batch_id", ""),
                "doc_no":   doc,
                "awb":      awb,
                "status":   status,
            })

    return {
        "total_pz_batches":  total_with_pz,
        "exported":          exported,
        "pending":           total_with_pz - exported,
        "last_exported_at":  last_exported_at[:19] if last_exported_at else None,
        "last_exported_doc": last_exported_doc,
        "export_mode":       "clipboard",   # Phase 1 always
        "pending_list":      sorted(pending_list, key=lambda x: x["doc_no"]),
        "exported_list":     sorted(exported_list, key=lambda x: x.get("exported_at", ""), reverse=True)[:20],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/phase-a", dependencies=[_auth])
async def phase_a_analytics() -> JSONResponse:
    """
    Phase A — Local Analytics.
    Reads all audit.json files; no external API calls.
    Returns duty-by-month, shipment-value-by-month, inventory, and wFirma sync status.
    """
    t0      = time.monotonic()
    batches = _collect_batches()

    data = {
        "generated_at":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "batches_scanned": len(batches),
        "phase":           "A",
        "wfirma_api":      False,
        "duty_by_month":              _build_duty_by_month(batches),
        "shipment_value_by_month":    _build_shipment_value_by_month(batches),
        "inventory":                  _build_inventory(batches),
        "wfirma_sync":                _build_wfirma_sync(batches),
        "elapsed_ms":      round((time.monotonic() - t0) * 1000),
    }
    return JSONResponse(content=data)
