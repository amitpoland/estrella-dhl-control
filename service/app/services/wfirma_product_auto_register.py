"""
wfirma_product_auto_register.py — Batch wrapper around the existing single-
product wFirma create flow.

The single-product create endpoint
``POST /api/v1/wfirma/goods/create-from-product-code/{product_code}``
([routes_wfirma_capabilities.py:279]) is the proven, search-first,
flag-gated path for registering one product. This service composes that
exact logic over a whole batch, so an operator (or a future observer)
can register every invoice-line code in one call.

Hard rules:
  * The service NEVER calls ``create_product`` in dry-run mode.
  * The service NEVER writes to ``wfirma_products`` unless wFirma
    confirms the product (search hit OR successful goods/add with a
    non-empty ``wfirma_id``). No fake mappings.
  * The service ALWAYS honors ``settings.wfirma_create_product_allowed``
    when ``dry_run=False``. There is no service-actor bypass.
  * Idempotent: re-running on the same batch produces ``created=0`` once
    every code is mapped (search-first short-circuits to
    ``existing_mapped``).

Public API
----------
``ensure_products_for_batch(batch_id, *, dry_run=False) -> dict``

Returns::

    {
      'batch_id':         str,
      'dry_run':          bool,
      'scanned':          int,
      'existing_mapped':  int,
      'missing':          int,    # dry_run only — codes NOT in wFirma
      'created':          int,
      'blocked':          int,    # write-mode + flag off OR description block missing
      'failed':           int,
      'errors':           [str],
      'results': [
         {
           'product_code':       str,
           'item_type':          str,
           'description_en':     str,
           'status':             'existing_mapped' | 'missing' | 'created'
                                  | 'blocked' | 'failed' | 'search_failed',
           'wfirma_product_id':  str (when known) | '',
           'error':              str (when status is failed/blocked/search_failed) | '',
         },
         ...
      ],
    }
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from ..core.config import settings
from . import document_db as ddb
from . import wfirma_client
from . import wfirma_db as wfdb

log = logging.getLogger(__name__)


# ── Secondary-registry mirror (reservation_queue.wfirma_product_mapping) ──
# `reservation_db` keeps a parallel `wfirma_product_mapping` table that the
# reservation_worker / PZ chain consults. We mirror successful registrations
# into it so both registries stay in sync. A failure here NEVER flips the
# product result to `failed` — the authoritative wFirma side already
# succeeded; we just record a warning.

def _reservation_db_path():
    return settings.storage_root / "reservation_queue.db"


def _mirror_to_reservation_mapping(
    *,
    product_code:      str,
    wfirma_product_id: str,
    wfirma_code:       str = "",
    wfirma_name:       str = "",
    unit:              str = "szt.",
) -> str:
    """Upsert into reservation_queue.wfirma_product_mapping.
    Returns "" on success, error string on failure (caller surfaces as
    a per-code warning without changing the product status)."""
    rdb_path = _reservation_db_path()
    try:
        if not rdb_path or not rdb_path.exists():
            return f"reservation_queue.db not found at {rdb_path}"
        # Imported lazily so the auto-register service stays importable
        # in environments where reservation_db's own deps are absent.
        from . import reservation_db
        reservation_db.upsert_wfirma_product_mapping(
            rdb_path,
            product_code      = product_code,
            wfirma_product_id = wfirma_product_id or "",
            wfirma_code       = wfirma_code or product_code,
            wfirma_name       = wfirma_name or "",
            sync_status       = "matched",
        )
        return ""
    except Exception as exc:
        return f"reservation_mapping mirror failed: {type(exc).__name__}: {exc}"


# ── item_type derivation from invoice description ──────────────────────────
# `invoice_lines.description` looks like:
#   "PCS, 14KT Gold,Stud With Diam Jewel RING"
#   "PRS, SL925 SILVERLGD Silver Std Jewellery EARRINGS"
# The trailing uppercase token is the item type. We support the canonical
# set used by description_engine.

_ITEM_TYPES = {
    "RING", "RINGS", "PENDANT", "PENDANTS", "EARRING", "EARRINGS",
    "BRACELET", "BRACELETS", "NECKLACE", "NECKLACES",
    "BANGLE", "BANGLES", "ANKLET", "ANKLETS",
    "CUFFLINK", "CUFFLINKS", "SET", "SETS",
}


def _derive_item_type(description: str) -> str:
    """Pick the trailing item-type token from an invoice description.
    Falls back to the empty string when no canonical token is found —
    description_engine.get_description_block then uses the english fallback."""
    if not description:
        return ""
    tokens = re.findall(r"[A-Z][A-Z]+", description.upper())
    for t in reversed(tokens):
        if t in _ITEM_TYPES:
            return t
    return ""


# ── Per-code worker (mirrors routes_wfirma_capabilities.create_good_…) ───
def _log_correction_safe(**kwargs) -> str:
    """Append-only correction-registry logging that never raises.

    Returns the warning string ("" on success, non-empty on failure).
    Logging failure must NEVER break the operator action — the caller
    surfaces the warning in `result["warnings"]`.
    """
    try:
        from . import correction_registry as _cr
        _cr.record_correction(**kwargs)
        return ""
    except Exception as exc:  # pragma: no cover (defensive)
        return f"correction_registry log failed: {type(exc).__name__}: {exc}"


def _register_one(
    *,
    product_code:    str,
    item_type:       str,
    description_en:  str,
    dry_run:         bool,
    operator:        str = "operator",
    batch_id:        str = "",
) -> Dict[str, Any]:
    """Search-first single-code register. Mirrors the HTTP endpoint logic
    so the surface area is identical. Returns the per-code result dict."""
    out: Dict[str, Any] = {
        "product_code":       product_code,
        "item_type":          item_type,
        "description_en":     description_en,
        "status":             "",
        "wfirma_product_id":  "",
        "error":              "",
        # Non-fatal warnings (e.g. reservation_queue mirror failure when
        # the wFirma + local mirror both succeeded). The status remains
        # `existing_mapped` / `created`; the operator can re-run later.
        "warnings":           [],
    }

    # 1. Search wFirma first (read-only)
    try:
        existing = wfirma_client.get_product_by_code(product_code)
    except Exception as exc:
        out["status"] = "search_failed"
        out["error"]  = f"{type(exc).__name__}: {exc}"
        return out

    if existing is not None:
        # Mirror locally — same behaviour as the HTTP endpoint's
        # existing_mapped branch.
        try:
            wfdb.upsert_product(
                product_code      = product_code,
                wfirma_product_id = existing.wfirma_id,
                product_name_pl   = existing.name or "",
                unit              = existing.unit or "szt.",
                vat_rate          = "23",
                sync_status       = "matched",
            )
        except Exception as exc:
            # Local-mirror failure is reported as failed but never overrides
            # the wFirma side — operator can re-run.
            out["status"] = "failed"
            out["error"]  = f"local mirror failed: {type(exc).__name__}: {exc}"
            return out
        # Mirror into the secondary reservation registry so the
        # PZ/reservation chain sees the same mapping. Non-fatal.
        warn = _mirror_to_reservation_mapping(
            product_code      = product_code,
            wfirma_product_id = existing.wfirma_id or "",
            wfirma_code       = (getattr(existing, "code", "") or product_code),
            wfirma_name       = existing.name or "",
            unit              = existing.unit or "szt.",
        )
        if warn:
            out["warnings"].append(warn)
        out["status"]            = "existing_mapped"
        out["wfirma_product_id"] = existing.wfirma_id
        # Append-only correction registry — operator-approved mapping outcome.
        log_warn = _log_correction_safe(
            correction_type = "product_mapping_override",
            entity_type     = "product",
            entity_key      = product_code,
            old_value       = "missing",
            new_value       = existing.wfirma_id,
            batch_id        = batch_id,
            operator        = operator,
            module_source   = "wfirma_product_auto_register",
            confidence      = 1.0,
            approved        = True,
            notes           = "existing_mapped",
            evidence_refs   = [
                {"type": "endpoint",     "ref": "/api/v1/wfirma/goods/auto-register"},
                {"type": "product_code", "ref": product_code},
            ],
        )
        if log_warn:
            out["warnings"].append(log_warn)
        return out

    # 2. Not in wFirma — dry-run reports missing without any write attempt.
    if dry_run:
        out["status"] = "missing"
        return out

    # 3. Write mode — honor the existing operator-only flag.
    if not getattr(settings, "wfirma_create_product_allowed", False):
        out["status"] = "blocked"
        out["error"]  = (
            "wfirma_create_product_allowed is false — "
            "operator must enable WFIRMA_CREATE_PRODUCT_ALLOWED to create"
        )
        return out

    # 4. Build payload via description_engine (locked block) and create.
    try:
        from . import description_engine as deng
        block = deng.get_description_block(
            product_code   = product_code,
            item_type      = item_type,
            description_en = description_en,
        )
    except Exception as exc:
        out["status"] = "blocked"
        out["error"]  = (
            f"description_block resolution failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return out

    wf_name = (
        (block.get("description_line") or "").strip()
        or (block.get("name_pl") or "").strip()
        or product_code
    )
    try:
        result = wfirma_client.create_product(
            product_code = product_code,
            name         = wf_name,
            unit         = "szt.",
            netto        = 0.0,
            vat_code_id  = wfirma_client.find_vat_code_id(23),
            description  = block.get("description_block") or "",
        )
    except Exception as exc:
        out["status"] = "failed"
        out["error"]  = f"{type(exc).__name__}: {exc}"
        return out

    if not result.wfirma_id:
        out["status"] = "failed"
        out["error"]  = "goods/add returned no wfirma_id — refusing fake mapping"
        return out

    # 5. Mirror locally only on confirmed success.
    try:
        wfdb.upsert_product(
            product_code      = product_code,
            wfirma_product_id = result.wfirma_id,
            product_name_pl   = block.get("name_pl") or "",
            unit              = "szt.",
            vat_rate          = "23",
            sync_status       = "matched",
        )
    except Exception as exc:
        out["status"] = "failed"
        out["error"]  = f"local mirror failed after create: {type(exc).__name__}: {exc}"
        out["wfirma_product_id"] = result.wfirma_id   # at least surface what wFirma assigned
        return out

    # Mirror into the secondary reservation registry. Non-fatal: a
    # mirror failure here does NOT roll back the wFirma create — that
    # ship has sailed. Operator can re-run; second run will see the
    # product as existing_mapped and re-mirror.
    warn = _mirror_to_reservation_mapping(
        product_code      = product_code,
        wfirma_product_id = result.wfirma_id or "",
        wfirma_code       = (getattr(result, "code", "") or product_code),
        wfirma_name       = result.name or wf_name,
        unit              = result.unit or "szt.",
    )
    if warn:
        out["warnings"].append(warn)
    out["status"]            = "created"
    out["wfirma_product_id"] = result.wfirma_id
    # Append-only correction registry — operator-approved create outcome.
    log_warn = _log_correction_safe(
        correction_type = "product_mapping_override",
        entity_type     = "product",
        entity_key      = product_code,
        old_value       = "missing",
        new_value       = result.wfirma_id,
        batch_id        = batch_id,
        operator        = operator,
        module_source   = "wfirma_product_auto_register",
        confidence      = 1.0,
        approved        = True,
        notes           = "created",
        evidence_refs   = [
            {"type": "endpoint",     "ref": "/api/v1/wfirma/goods/auto-register"},
            {"type": "product_code", "ref": product_code},
        ],
    )
    if log_warn:
        out["warnings"].append(log_warn)
    return out


# ── Batch entrypoint ──────────────────────────────────────────────────────
def ensure_products_for_batch(
    batch_id: str,
    *,
    dry_run:  bool = False,
    operator: str  = "operator",
) -> Dict[str, Any]:
    """Register every distinct invoice-line ``product_code`` in *batch_id*
    in wFirma. Idempotent. Search-first per code. Honors
    ``wfirma_create_product_allowed`` in write mode.

    See module docstring for the full result shape.
    """
    out: Dict[str, Any] = {
        "batch_id":         batch_id,
        "dry_run":          bool(dry_run),
        "scanned":          0,
        "existing_mapped":  0,
        "missing":          0,
        "created":          0,
        "blocked":          0,
        "failed":           0,
        "errors":           [],
        "results":          [],
    }

    if not batch_id:
        out["errors"].append("batch_id is required")
        return out

    try:
        rows = ddb.get_invoice_lines_for_batch(batch_id) or []
    except Exception as exc:
        out["errors"].append(f"invoice_lines read failed: {exc}")
        return out

    # De-duplicate by product_code (multiple rows for same code → register once).
    # First-seen wins for item_type / description_en derivation.
    by_code: Dict[str, Dict[str, str]] = {}
    for r in rows:
        pc = (r.get("product_code") or "").strip()
        if not pc or pc in by_code:
            continue
        desc = r.get("description") or ""
        by_code[pc] = {
            "item_type":      _derive_item_type(desc),
            "description_en": desc,
        }

    out["scanned"] = len(by_code)

    for pc, ctx in by_code.items():
        res = _register_one(
            product_code   = pc,
            item_type      = ctx["item_type"],
            description_en = ctx["description_en"],
            dry_run        = dry_run,
            operator       = operator,
            batch_id       = batch_id,
        )
        out["results"].append(res)
        st = res["status"]
        if st == "existing_mapped":
            out["existing_mapped"] += 1
        elif st == "missing":
            out["missing"] += 1
        elif st == "created":
            out["created"] += 1
        elif st == "blocked":
            out["blocked"] += 1
        elif st == "failed":
            out["failed"] += 1
        elif st == "search_failed":
            out["failed"] += 1

    log.info(
        "[wfirma_auto_register] batch=%s dry_run=%s scanned=%d "
        "existing=%d missing=%d created=%d blocked=%d failed=%d",
        batch_id, dry_run, out["scanned"], out["existing_mapped"],
        out["missing"], out["created"], out["blocked"], out["failed"],
    )
    return out
