"""
wfirma_fiscal_inventory.py — Canonical FISCAL inventory reader (WF-2, READ-ONLY).

This is the single, canonical source of wFirma *fiscal* warehouse quantity for
the WF-2 Inventory Reconciliation layer. It answers exactly one question:
"how many units of each product does wFirma hold, per warehouse?" — and nothing
else. It NEVER writes to wFirma and NEVER writes to any Dashboard authority.

AUTHORITY (WF-1A Inventory Ownership Constitution):
  * wFirma owns fiscal warehouse quantity. Dashboard owns operational piece-stock.
  * The ONLY sanctioned fiscal-quantity read is ``goods/find`` filtered by
    ``warehouse_id``; warehouse ids come from ``warehouses/find``. There is no
    alternative stock source (WF-2 requirement 1).

LAYER: this is a wFirma-facing sync-layer service (the fiscal analog of
``wfirma_reservation.py``). All transport goes through the sole client
``wfirma_client``; business/observability code consumes THIS reader — it never
calls wFirma or the mirror directly.

DEGRADATION: when wFirma is not configured or is unreachable, the reader returns
``available=False`` with a reason and NO quantities. It never guesses a number —
a reconciliation with no fiscal side is reported honestly as fiscal-unavailable,
never as "everything missing in wFirma".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import wfirma_client
from ..core.config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_configured() -> bool:
    """True only when the 3-header API key + company id are all present."""
    return all(
        bool((getattr(settings, k, "") or "").strip())
        for k in ("wfirma_access_key", "wfirma_secret_key",
                  "wfirma_app_key", "wfirma_company_id")
    )


def _unavailable(reason: str) -> Dict[str, Any]:
    return {
        "available": False,
        "unavailable_reason": reason,
        "generated_at": _now_iso(),
        "warehouses": [],
        "unknown_warehouses": [],
        "entries": [],
    }


def read_fiscal_inventory(warehouse_id: Optional[str] = None) -> Dict[str, Any]:
    """Read wFirma fiscal inventory (READ-ONLY).

    Returns a structured result:
        {
          "available": bool,
          "unavailable_reason": str | None,
          "generated_at": ISO8601,
          "warehouses": [{"id", "name"}],          # warehouses actually read
          "unknown_warehouses": [warehouse_id, …], # requested but absent in wFirma
          "entries": [                              # one row per good per warehouse
             {"warehouse_id", "warehouse_name", "product_code",
              "wfirma_id", "count", "reserved"}
          ],
        }

    ``warehouse_id`` optionally narrows the read to a single warehouse; otherwise
    the configured ``wfirma_warehouse_id`` is used, else all warehouses.
    """
    if not _api_configured():
        return _unavailable("wFirma API not configured")

    # Warehouse ids come from warehouses/find — the canonical warehouse authority.
    try:
        wh_list = wfirma_client.list_warehouses()
    except (ConnectionError, RuntimeError) as exc:
        return _unavailable(f"warehouses/find failed: {exc}")
    except Exception as exc:  # defensive: never raise into the reconciliation layer
        return _unavailable(f"warehouses/find error: {exc}")

    wh_by_id: Dict[str, str] = {
        str(w.get("id") or ""): (w.get("name") or "") for w in wh_list if w.get("id")
    }

    # Choose target warehouse(s): explicit arg → configured id → all.
    configured = (getattr(settings, "wfirma_warehouse_id", "") or "").strip()
    if warehouse_id:
        targets = [str(warehouse_id).strip()]
    elif configured:
        targets = [configured]
    else:
        targets = list(wh_by_id.keys())

    entries: List[Dict[str, Any]] = []
    warehouses_read: List[Dict[str, str]] = []
    unknown: List[str] = []

    for wid in targets:
        if wid not in wh_by_id:
            unknown.append(wid)
            continue
        try:
            goods = wfirma_client.list_goods_in_warehouse(wid)
        except (ConnectionError, RuntimeError) as exc:
            return _unavailable(f"goods/find failed for warehouse {wid}: {exc}")
        except Exception as exc:  # defensive
            return _unavailable(f"goods/find error for warehouse {wid}: {exc}")

        warehouses_read.append({"id": wid, "name": wh_by_id[wid]})
        for g in goods:
            entries.append({
                "warehouse_id": wid,
                "warehouse_name": wh_by_id[wid],
                "product_code": (g.code or "").strip(),
                "wfirma_id": g.wfirma_id,
                "count": float(g.count or 0.0),
                "reserved": float(g.reserved or 0.0),
            })

    return {
        "available": True,
        "unavailable_reason": None,
        "generated_at": _now_iso(),
        "warehouses": warehouses_read,
        "unknown_warehouses": unknown,
        "entries": entries,
    }
