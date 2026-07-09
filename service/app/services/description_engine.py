"""
description_engine.py — Single source of truth for product description blocks.

Implements the rule from docs/wfirma.skill.md:

    ONE PRODUCT_CODE = ONE LOCKED DESCRIPTION_BLOCK

The block is generated once from the existing item-type translations
(ITEM_TRANSLATIONS in polish_description_generator), persisted by
product_code, and reused everywhere — PZ/customs PDF, future wFirma
product creation, future proforma/invoice flows.

Manual overrides (source='manual') are never overwritten by the default
generator. Default rows (source='auto') are also stable: once written,
subsequent calls return the persisted block byte-for-byte.

Pure deterministic. No AI, no live API calls, no proforma side-effects.
"""
from __future__ import annotations

import sys
import threading as _threading
from typing import Any, Dict, Optional

from ..core.config import settings
from ..core.logging import get_logger
from . import document_db as ddb

log = get_logger(__name__)


# ── Bilingual block builder (locked 3-section format) ───────────────────────

def build_description_line(description_pl: str, description_en: str) -> str:
    """
    Polish-first / English-after-slash composed product description line.

    Example:
      pierścionek z platyny próby 950 z diamentami i kamieniami /
      Diamond & Colour Stone PT950 Platinum Jewellery RING

    If English is empty, returns just the Polish text (no trailing slash).
    """
    pl = (description_pl or "").strip()
    en = (description_en or "").strip()
    if pl and en:
        return f"{pl} / {en}"
    return pl or en


def build_description_block(*,
                             description_pl: str,
                             material_pl:    str,
                             purpose_pl:     str,
                             description_en: str = "") -> str:
    """
    Render the locked bilingual block. Polish-first/English-after-slash
    rule applies to the product-description content line ("Co to za towar")
    when an English description is present. Material and Purpose remain
    Polish-only — there is no agreed English source for those today.
    """
    desc_line = build_description_line(description_pl, description_en)
    return (
        f"Co to za towar / What is this:        {desc_line}\n"
        f"Z jakiego materiału / Material:       {material_pl}\n"
        f"Do czego służy / Purpose:             {purpose_pl}"
    )


# ── Translation lookup (defers to engine_dir module) ────────────────────────

_TRANSLATIONS_CACHE: Optional[Dict[str, Dict[str, str]]] = None
_DEFAULT_CACHE:       Optional[Dict[str, str]]            = None
_CUSTOMS_ENGINE_CACHE = None  # lazy-imported customs_description_engine
# Threading lock — protects all three module-level caches above.
# NSSM/Windows multi-threaded FastAPI workers can race on first load without this.
_cache_lock = _threading.Lock()


# ── PR-208: explicit cache-reset helper ────────────────────────────────────
#
# REPL / debug / admin-only utility.  NEVER invoke from request-handling
# paths or any automatic intake / generation flow — the loader caches
# are intentionally sticky inside a process so request lifecycles see a
# stable environment.  This helper exists ONLY for the operator-driven
# scenario where an REPL session attempted regeneration with the wrong
# sys.path, surfaced fallback_used=True via PR-207, and then fixed
# sys.path mid-session.  Without this helper, the operator must restart
# the Python process to retry; with it, the next _load_* call re-attempts
# the import naturally.
#
# Pure / synchronous / no DB / no HTTP / no wFirma / PZ / DHL.
#
# Returns serializable disposition dict for operator logs.
def reset_caches() -> Dict[str, bool]:
    """Reset the three module-level loader caches to their pre-load
    sentinel state (``None``).

    Use case
    --------
    After an REPL run reported ``fallback_used=True`` (see
    :func:`regenerate_descriptions_for_invoice_lines`'s PR-207 metadata)
    and the operator has corrected ``sys.path`` so
    ``customs_description_engine`` / ``polish_description_generator``
    can now be imported, calling ``reset_caches()`` clears the cached
    ``False`` sentinels so the very next ``_load_customs_engine()`` /
    ``_load_translations()`` call attempts the import again.

    DO NOT invoke this function from:
      - any HTTP route handler
      - any automatic intake / parser / generator pipeline
      - any scheduled background task

    Returns
    -------
    dict[str, bool]
        ``{"customs_engine_cache_reset": True,
           "translations_cache_reset":   True,
           "default_cache_reset":        True}``
        — fully JSON-serialisable; safe to print, log, or echo to an
        operator REPL.

    Side effects
    ------------
    Resets three module-level globals.  Performs no DB query, no HTTP
    request, no wFirma / PZ / DHL / proforma execution.  Does not log
    (the caller is the operator; log noise would be unhelpful).
    """
    global _TRANSLATIONS_CACHE, _DEFAULT_CACHE, _CUSTOMS_ENGINE_CACHE
    with _cache_lock:
        _CUSTOMS_ENGINE_CACHE = None
        _TRANSLATIONS_CACHE   = None
        _DEFAULT_CACHE        = None
    return {
        "customs_engine_cache_reset": True,
        "translations_cache_reset":   True,
        "default_cache_reset":        True,
    }


def _load_customs_engine():
    """
    Lazily import customs_description_engine for rich per-line Polish
    customs phrasing (e.g. "Pierścionek ze złota próby 585 z diamentami
    laboratoryjnymi") rather than the generic ITEM_TRANSLATIONS default
    ("Biżuteria — pierścionek"). Returns None if the engine module isn't
    importable — caller falls back to ITEM_TRANSLATIONS.
    """
    global _CUSTOMS_ENGINE_CACHE
    # Fast path (no lock) — cache already set.
    if _CUSTOMS_ENGINE_CACHE is not None:
        return _CUSTOMS_ENGINE_CACHE if _CUSTOMS_ENGINE_CACHE is not False else None

    with _cache_lock:
        # Re-check under lock in case a concurrent thread populated while we waited.
        if _CUSTOMS_ENGINE_CACHE is not None:
            return _CUSTOMS_ENGINE_CACHE if _CUSTOMS_ENGINE_CACHE is not False else None

        engine = str(settings.engine_dir)
        if engine not in sys.path:
            sys.path.insert(0, engine)
        try:
            import customs_description_engine as _cde  # type: ignore
            _CUSTOMS_ENGINE_CACHE = _cde
            return _cde
        except Exception as exc:
            log.warning("description_engine: customs_description_engine import "
                        "failed (%s) — falling back to ITEM_TRANSLATIONS", exc)
            _CUSTOMS_ENGINE_CACHE = False
            return None


def _customs_grade_translation(item_type: str,
                                description_en: str
                                ) -> Optional[Dict[str, str]]:
    """
    Try to derive a customs-grade Polish translation from the invoice's
    English description. Returns a dict shaped like ITEM_TRANSLATIONS
    (name_pl, description_pl, material_pl, purpose_pl) when successful,
    None otherwise. Never raises.

    Matches the format used by the customs/PZ description PDF — both
    consumers must show identical wording (docs/wfirma.skill.md §3).
    """
    if not (description_en or "").strip():
        return None
    cde = _load_customs_engine()
    if cde is None:
        return None
    try:
        norm = cde.normalize_item_description(
            description_en,
            item_type=_normalise_item_type(item_type),
            hsn_from_invoice="",
        )
    except Exception as exc:
        log.warning("description_engine: normalize_item_description failed "
                    "for item_type=%r: %s", item_type, exc)
        return None
    desc_pl = (norm.get("polish_customs_description") or "").strip()
    if not desc_pl:
        return None
    return {
        "name_pl":        (norm.get("item_type_pl") or "").strip()
                          or "Wyrób jubilerski",
        "description_pl": desc_pl,
        "material_pl":    (norm.get("material_pl")  or "").strip()
                          or "metal szlachetny",
        "purpose_pl":     (norm.get("purpose_pl")   or "").strip()
                          or "Ozdoba — biżuteria do noszenia.",
    }


def _load_translations() -> tuple:
    """
    Lazily import ITEM_TRANSLATIONS / DEFAULT_TRANSLATION from the engine
    module that lives at the project root (engine_dir). Cached on first
    call. Adding engine_dir to sys.path mirrors the convention used by
    routes_dhl_clearance.py:50-52 and others.
    """
    global _TRANSLATIONS_CACHE, _DEFAULT_CACHE
    # Fast path (no lock) — cache already set.
    if _TRANSLATIONS_CACHE is not None:
        return _TRANSLATIONS_CACHE, _DEFAULT_CACHE

    with _cache_lock:
        # Re-check under lock in case a concurrent thread populated while we waited.
        if _TRANSLATIONS_CACHE is not None:
            return _TRANSLATIONS_CACHE, _DEFAULT_CACHE

        engine = str(settings.engine_dir)
        if engine not in sys.path:
            sys.path.insert(0, engine)

        try:
            import polish_description_generator as _pdg  # type: ignore
            _TRANSLATIONS_CACHE = dict(_pdg.ITEM_TRANSLATIONS)
            _DEFAULT_CACHE      = dict(_pdg.DEFAULT_TRANSLATION)
        except Exception as exc:
            log.warning("description_engine: ITEM_TRANSLATIONS import failed (%s) "
                        "— using minimal in-module fallback", exc)
            _TRANSLATIONS_CACHE = {}
            _DEFAULT_CACHE = {
                "name_pl":        "Biżuteria",
                "description_pl": "Wyrób jubilerski",
                "material_pl":    "Metal z kamieniami ozdobnymi",
                "purpose_pl":     "Ozdoba",
            }
    return _TRANSLATIONS_CACHE, _DEFAULT_CACHE


def _normalise_item_type(item_type: str) -> str:
    return (item_type or "").strip().upper()


def _resolve_translation(item_type: str) -> Dict[str, str]:
    """Pick the translation dict for *item_type*. Falls back to default."""
    translations, default = _load_translations()
    key = _normalise_item_type(item_type)
    if key in translations:
        return translations[key]
    return default


# ── Public API ──────────────────────────────────────────────────────────────

def get_description_block(
    product_code:   str,
    item_type:      str,
    *,
    description_en: Optional[str] = None,
    description_pl: Optional[str] = None,
    material_pl:    Optional[str] = None,
    purpose_pl:     Optional[str] = None,
    name_pl:        Optional[str] = None,
    authoritative_pl: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Return the locked description block for *product_code*.

    First call for a product_code derives the block from item_type's
    translation. Optional caller-supplied Polish strings (description_pl,
    material_pl, purpose_pl, name_pl) override the type-default on first
    write — useful when an upstream pipeline has richer per-line Polish
    (e.g. customs_description_engine.normalize_item_description()).
    Subsequent calls return the persisted row unchanged.

    Manual overrides (source='manual', written via set_manual_block) are
    never replaced by this function.

    *description_en* (optional) populates the English half on first write.
    The Polish-first/English-after-slash composed line is exposed as
    `description_line`. Once persisted, the line is locked.

    Returned shape:
      {
        product_code, item_type, name_pl, description_pl, description_en,
        material_pl, purpose_pl, description_block, description_line,
        source, created_at, updated_at
      }
    """
    pc = (product_code or "").strip()
    if not pc:
        raise ValueError("product_code is required")

    # ── Authoritative resolver override ───────────────────────────────────────
    # When the caller (customs PDF generation) has already resolved the APPROVED
    # customs description via resolve_product_description_for_customs(), it is the
    # single source of truth. Return it directly as a pure formatter — do NOT
    # read or first-write product_descriptions, so a stale/poisoned source='auto'
    # row can never override the approved value, and no generic default is
    # persisted. Approved 'manual' rows are already what the resolver returns
    # here, so this stays consistent with the Product Description Authority.
    _auth = (authoritative_pl or "").strip()
    if _auth:
        eff_en = (description_en or "").strip()
        eff_mat = (material_pl or "").strip()
        eff_pur = (purpose_pl or "").strip() or "Ozdoba — biżuteria do noszenia."
        eff_name = (name_pl or "").strip() or _auth
        return {
            "product_code":      pc,
            "item_type":         _normalise_item_type(item_type),
            "name_pl":           eff_name,
            "description_pl":    _auth,
            "description_en":    eff_en,
            "material_pl":       eff_mat,
            "purpose_pl":        eff_pur,
            "description_block": build_description_block(
                description_pl=_auth, material_pl=eff_mat,
                purpose_pl=eff_pur, description_en=eff_en),
            "description_line":  build_description_line(_auth, eff_en),
            "source":            "resolver",
            "created_at":        None,
            "updated_at":        None,
        }

    existing = ddb.get_product_description(pc)
    if existing is not None:
        return existing

    eff_desc_en = (description_en or "").strip()

    # Customs-grade Polish text takes priority over the generic
    # ITEM_TRANSLATIONS default — but only when the caller hasn't passed
    # description_pl explicitly AND we have an English source to feed
    # normalize_item_description. This keeps the wFirma product master
    # name visually identical to the customs/PZ description PDF for the
    # same product (docs/wfirma.skill.md §3).
    customs_trans: Optional[Dict[str, str]] = None
    if description_pl is None and eff_desc_en:
        customs_trans = _customs_grade_translation(item_type, eff_desc_en)

    base = customs_trans or _resolve_translation(item_type)
    eff_name_pl    = (name_pl        or base["name_pl"]).strip()
    eff_desc_pl    = (description_pl or base["description_pl"]).strip()
    eff_material   = (material_pl    or base["material_pl"]).strip()
    eff_purpose    = (purpose_pl     or base["purpose_pl"]).strip()

    block = build_description_block(
        description_pl = eff_desc_pl,
        material_pl    = eff_material,
        purpose_pl     = eff_purpose,
        description_en = eff_desc_en,
    )
    line = build_description_line(eff_desc_pl, eff_desc_en)

    if ddb._db_path is None:
        return {
            "product_code":      pc,
            "item_type":         _normalise_item_type(item_type),
            "name_pl":           eff_name_pl,
            "description_pl":    eff_desc_pl,
            "description_en":    eff_desc_en,
            "material_pl":       eff_material,
            "purpose_pl":        eff_purpose,
            "description_block": block,
            "description_line":  line,
            "source":            "auto",
            "created_at":        None,
            "updated_at":        None,
        }

    ddb.upsert_product_description(
        product_code      = pc,
        item_type         = _normalise_item_type(item_type),
        name_pl           = eff_name_pl,
        description_pl    = eff_desc_pl,
        description_en    = eff_desc_en,
        material_pl       = eff_material,
        purpose_pl        = eff_purpose,
        description_block = block,
        description_line  = line,
        source            = "auto",
    )
    row = ddb.get_product_description(pc)
    if row is None:
        raise RuntimeError(
            f"description_engine: row vanished after upsert for {pc!r}"
        )
    return row


def set_manual_block(*,
                     product_code:   str,
                     item_type:      str,
                     name_pl:        str,
                     description_pl: str,
                     material_pl:    str,
                     purpose_pl:     str,
                     description_en: str = "") -> Dict[str, Any]:
    """
    Operator-driven override. Writes source='manual'. Subsequent calls to
    get_description_block return the manual block; the auto generator
    will not replace it.
    """
    pc = (product_code or "").strip()
    if not pc:
        raise ValueError("product_code is required")
    eff_desc_en = (description_en or "").strip()
    block = build_description_block(
        description_pl = description_pl,
        material_pl    = material_pl,
        purpose_pl     = purpose_pl,
        description_en = eff_desc_en,
    )
    line = build_description_line(description_pl, eff_desc_en)
    ddb.upsert_product_description(
        product_code      = pc,
        item_type         = _normalise_item_type(item_type),
        name_pl           = name_pl,
        description_pl    = description_pl,
        description_en    = eff_desc_en,
        material_pl       = material_pl,
        purpose_pl        = purpose_pl,
        description_block = block,
        description_line  = line,
        source            = "manual",
    )
    row = ddb.get_product_description(pc)
    if row is None:
        raise RuntimeError(
            f"description_engine: row vanished after manual upsert for {pc!r}"
        )
    return row


# ── Per-line backfill from invoice_lines (PR for line-vs-header bug) ────────
#
# Source-priority rule:
#   1. invoice_lines.description  — per-line, per-product_code (canonical
#                                   intake source from purchase invoices)
#   2. product_master.description — per-line projection written by
#                                   store_invoice_lines at intake time
#                                   (fallback when invoice_lines query
#                                   returns nothing for the code)
#   3. ""                          — fed to description_engine, which then
#                                   falls back to the item_type generic
#                                   template in ITEM_TRANSLATIONS.
#
# Never invents product_code.  Never aliases design_no as product_code.
# Never overwrites source='manual' rows.  No wFirma / PZ / DHL calls.

# Canonical item-type tokens — kept inline to avoid importing
# wfirma_product_auto_register (which depends on wfirma_client at import).
_ITEM_TYPE_TOKENS = frozenset({
    "RING", "RINGS",
    "PENDANT", "PENDANTS",
    "EARRING", "EARRINGS",
    "BRACELET", "BRACELETS", "BANGLE", "BANGLES",
    "NECKLACE", "NECKLACES",
    "CHAIN", "CHAINS",
    "CUFFLINK", "CUFFLINKS",
    "SET", "SETS",
})


def _derive_item_type_from_description(description: str) -> str:
    """Pick the trailing item-type token from an invoice-line description.

    Returns the canonical singular form (RING / PENDANT / EARRINGS /
    BRACELET / NECKLACE / CHAIN / CUFFLINK / SET) or '' if no token is
    found.  Operator-facing surfaces always see one of the singular forms
    after _normalise_item_type runs inside get_description_block.
    """
    import re as _re
    if not description:
        return ""
    tokens = _re.findall(r"[A-Z][A-Z]+", str(description).upper())
    for t in reversed(tokens):
        if t in _ITEM_TYPE_TOKENS:
            return t
    return ""


def regenerate_descriptions_for_invoice_lines(
    *,
    batch_id:      Optional[str] = None,
    product_code:  Optional[str] = None,
    dry_run:       bool          = True,
) -> Dict[str, Any]:
    """Walk ``invoice_lines`` and ensure every per-line ``product_code``
    has a corresponding ``product_descriptions`` row generated from its
    OWN per-line description text — never from the overall invoice
    header.

    Scope:
      - ``batch_id``     filters to one shipment batch
      - ``product_code`` filters to one canonical code (overrides batch)
      - if both omitted, walks all invoice_lines (use with care)

    Behaviour:
      - ``dry_run=True`` (default): no writes; returns ``would_write`` /
        ``would_skip_existing`` / ``would_skip_manual`` counts plus the
        per-code plan list.
      - ``dry_run=False``: invokes :func:`get_description_block` per
        code.  Existing rows with ``source='manual'`` are NEVER replaced
        (enforced inside ``upsert_product_description``).  Existing
        ``source='auto'`` (or ``'pz_rows_backfill'``) rows are also
        preserved — ``get_description_block`` is idempotent and returns
        the existing row unchanged.

    Returns::

        {
          "scanned":             int,
          "written":             int,
          "would_write":         int,    # dry-run only
          "skipped_existing":    int,    # row already present (any source)
          "skipped_manual":      int,    # row present with source='manual'
          "skipped_blank":       int,    # neither invoice_lines nor
                                          # product_master had a usable
                                          # English source AND no item_type
                                          # could be derived
          "errors":              list[dict],
          "dry_run":             bool,
          "filter":              {"batch_id": str|None,
                                   "product_code": str|None},
          # ── PR-207 fallback-visibility metadata ────────────────────
          "engine_import_ok":       bool,  # customs_description_engine reachable
          "translations_import_ok": bool,  # polish_description_generator
                                            # ITEM_TRANSLATIONS reachable
          "fallback_used":          bool,  # True when EITHER import failed
                                            # — generated rows will use the
                                            # in-module DEFAULT_TRANSLATION
                                            # ("Biżuteria"); operator-visible
                                            # signal that a REPL run is in
                                            # the wrong runtime context.
          "fallback_reason":        list[str],
        }

    No wFirma / PZ / DHL / proforma post path is touched.  Pure local-DB
    read-and-write.
    """
    out: Dict[str, Any] = {
        "scanned":           0,
        "written":           0,
        "would_write":       0,
        "skipped_existing":  0,
        "skipped_manual":    0,
        "skipped_blank":     0,
        "errors":            [],
        "dry_run":           bool(dry_run),
        "filter":            {"batch_id":     batch_id,
                              "product_code": product_code},
        # PR-207: engine fallback visibility — see docstring above.
        "engine_import_ok":       False,
        "translations_import_ok": False,
        "fallback_used":          False,
        "fallback_reason":        [],
    }

    # ── PR-207: probe engine + translations reachability once ────────────
    # We call the loaders so any cached "False" sentinel left from a prior
    # failed attempt is honoured, and so a healthy call refreshes the cache
    # state for downstream get_description_block consumers.  Errors here
    # are NEVER fatal — the function still runs, but produces minimal
    # DEFAULT_TRANSLATION text and reports `fallback_used=True` so callers
    # can flag the run as low quality and / or re-execute from a context
    # where settings.engine_dir is on sys.path.
    fallback_reasons: List[str] = []
    try:
        _cde = _load_customs_engine()
        out["engine_import_ok"] = _cde is not None
    except Exception as _exc:
        out["engine_import_ok"] = False
        fallback_reasons.append(
            f"customs_description_engine probe raised "
            f"{type(_exc).__name__}: {_exc}"
        )
    try:
        _trans, _default = _load_translations()
        out["translations_import_ok"] = bool(_trans)
    except Exception as _exc:
        out["translations_import_ok"] = False
        fallback_reasons.append(
            f"polish_description_generator probe raised "
            f"{type(_exc).__name__}: {_exc}"
        )
    if not out["engine_import_ok"]:
        fallback_reasons.append(
            "customs_description_engine not importable from "
            "settings.engine_dir — descriptions will lack rich "
            "customs phrasing"
        )
    if not out["translations_import_ok"]:
        fallback_reasons.append(
            "polish_description_generator.ITEM_TRANSLATIONS not "
            "importable — using minimal in-module DEFAULT_TRANSLATION "
            "('Biżuteria' / 'Wyrób jubilerski')"
        )
    if fallback_reasons:
        out["fallback_used"]   = True
        out["fallback_reason"] = fallback_reasons
        log.error(
            "regenerate_descriptions_for_invoice_lines: ENGINE FALLBACK "
            "ACTIVE — generated rows will use the minimal "
            "DEFAULT_TRANSLATION ('Biżuteria').  Re-run from a context "
            "where settings.engine_dir (currently %r) is on sys.path "
            "before invoking with dry_run=False.  Reasons: %s",
            str(getattr(settings, "engine_dir", "")),
            "; ".join(fallback_reasons),
        )

    if ddb._db_path is None:
        out["errors"].append({"stage": "init",
                              "detail": "document_db not initialised"})
        return out

    # Build the read SQL with the requested scope.  Read-only.
    where_clauses: list = []
    params:        list = []
    if product_code:
        where_clauses.append("product_code = ?")
        params.append(str(product_code).strip())
    if batch_id and not product_code:
        where_clauses.append("batch_id = ?")
        params.append(str(batch_id).strip())
    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        from . import reservation_db as _rdb  # for product_master fallback
        _rdb_path = settings.storage_root / "reservation_queue.db"
        if _rdb_path.exists():
            pm_rows = _rdb.list_product_masters(_rdb_path) or []
        else:
            pm_rows = []
    except Exception as exc:
        log.warning("regenerate_descriptions: product_master fallback "
                    "unavailable (non-fatal): %s", exc)
        pm_rows = []
    pm_by_code = {(r.get("product_code") or "").strip(): r for r in pm_rows
                  if (r.get("product_code") or "").strip()}

    # De-duplicate by product_code so a code appearing on N invoice_lines
    # rows triggers only one get_description_block call.  First-seen
    # invoice description wins as the English source.
    seen_codes: dict = {}
    try:
        import sqlite3 as _sql
        with _sql.connect(str(ddb._db_path)) as con:
            con.row_factory = _sql.Row
            sql = (
                "SELECT product_code, description "
                "FROM invoice_lines"
                + where_sql
                + " ORDER BY batch_id, invoice_no, line_position"
            )
            for r in con.execute(sql, params).fetchall():
                pc   = (r["product_code"] or "").strip()
                desc = (r["description"]  or "").strip()
                if not pc or pc in seen_codes:
                    continue
                seen_codes[pc] = desc
    except Exception as exc:
        out["errors"].append({"stage": "read_invoice_lines",
                              "detail": f"{type(exc).__name__}: {exc}"})
        return out

    out["scanned"] = len(seen_codes)

    for pc, line_desc in seen_codes.items():
        # Pre-existing row check — guard order mirrors upsert semantics
        # so the dry-run plan matches the write-mode outcome exactly.
        try:
            existing = ddb.get_product_description(pc)
        except Exception as exc:
            out["errors"].append({"product_code": pc,
                                  "stage": "read_existing",
                                  "detail": f"{type(exc).__name__}: {exc}"})
            continue

        if existing is not None:
            if (existing.get("source") or "") == "manual":
                out["skipped_manual"] += 1
            else:
                out["skipped_existing"] += 1
            continue

        # Build the English source per the documented priority order.
        #   1. invoice_lines.description (per-line)  ←  primary
        #   2. product_master.description (per-line projection)  ←  fallback
        #   3. ""  →  description_engine falls back to ITEM_TRANSLATIONS
        eff_desc_en = line_desc
        if not eff_desc_en:
            pm = pm_by_code.get(pc) or {}
            eff_desc_en = str(pm.get("description") or "").strip()

        item_type = _derive_item_type_from_description(eff_desc_en)
        if not item_type and not eff_desc_en:
            # Nothing to seed: no per-line description, no item type.
            # Skipping is safer than writing a generic stub.
            out["skipped_blank"] += 1
            continue

        if dry_run:
            out["would_write"] += 1
            continue

        try:
            get_description_block(
                product_code   = pc,
                item_type      = item_type,
                description_en = eff_desc_en,
            )
            out["written"] += 1
        except Exception as exc:
            out["errors"].append({"product_code": pc,
                                  "stage": "get_description_block",
                                  "detail": f"{type(exc).__name__}: {exc}"})

    return out


# ── Global Jewellery description path ────────────────────────────────────────

def _english_description_from_item_type(item_type: str) -> str:
    """Return the canonical legal English description for *item_type*.

    Global / packing-only batches have no per-line English invoice text — only
    an ``item_type`` column.  A design number is NOT an English description, so
    it must never be used as ``description_en``.  This helper delegates to the
    SINGLE English-description authority,
    ``customs_description_engine.render_product_description_en`` — the same
    renderer that produces ``product_description_en`` inside
    ``normalize_item_description`` and that the customs PDF uses.  It is called
    with empty purity/stones so only the item-type noun is rendered; this is
    deliberate — the noun carries no metal/stone tokens, so feeding it to
    ``get_description_block`` leaves the Polish half (``description_pl``)
    keyword-equivalent to the prior design-number input.  Polish behaviour is
    unchanged; only the English half is corrected.

    No second translation layer is introduced: ``ITEM_TYPE_EN`` is read solely
    through the canonical renderer.  When the customs engine is unreachable the
    helper returns ``""`` (English omitted — the same honest degradation the
    Polish path already takes via ``_customs_grade_translation``).  Never
    raises.
    """
    if not _normalise_item_type(item_type):
        return ""
    cde = _load_customs_engine()
    if cde is None:
        return ""
    try:
        # Noun only: empty purity + empty stones → no metal/stone tokens.
        return (cde.render_product_description_en(item_type, "", "") or "").strip()
    except Exception as exc:  # pragma: no cover — defensive only
        log.warning("description_engine: render_product_description_en failed "
                    "for item_type=%r: %s", item_type, exc)
        return ""


def regenerate_descriptions_for_packing_lines(
    *,
    batch_id: str,
    dry_run:  bool = True,
) -> Dict[str, Any]:
    """Generate product descriptions from packing_lines for Global Jewellery.

    Global Jewellery packing lists are the authority for item rows — there
    are no per-item invoice_lines.  This function reads packing_lines for
    the batch and calls :func:`get_description_block` per product_code.

    Behaviour is identical to ``regenerate_descriptions_for_invoice_lines``
    except the source table is ``packing_lines`` (via packing_db) instead
    of ``invoice_lines`` (via document_db).

    ``dry_run=True``  (default): no writes, returns ``would_write`` count.
    ``dry_run=False``:           writes descriptions for all product codes.

    Returns::

        {
            "scanned":   int,
            "written":   int,
            "would_write":  int,   # dry-run only
            "skipped":   int,
            "errors":    list[dict],
            "dry_run":   bool,
            "batch_id":  str,
        }
    """
    from .packing_db import get_packing_lines_for_batch

    out: Dict[str, Any] = {
        "scanned":    0,
        "written":    0,
        "would_write": 0,
        "skipped":    0,
        "errors":     [],
        "dry_run":    bool(dry_run),
        "batch_id":   batch_id,
    }

    try:
        lines = get_packing_lines_for_batch(batch_id)
    except Exception as exc:
        out["errors"].append({"stage": "get_packing_lines", "detail": str(exc)})
        return out

    for ln in lines:
        out["scanned"] += 1

        pc = ln.get("product_code")
        if not pc:
            out["skipped"] += 1
            continue

        item_type  = str(ln.get("item_type", "") or "").strip()
        # Legal English comes from item_type, NOT design_no.  A design number
        # is an internal identifier, not an English product description; using
        # it produced a weak/incorrect English half and degraded the customs-
        # grade Polish parse.  Delegate to the single English-description
        # authority (customs_description_engine.render_product_description_en).
        desc_en    = _english_description_from_item_type(item_type)

        if dry_run:
            out["would_write"] += 1
            continue

        try:
            get_description_block(
                product_code   = pc,
                item_type      = item_type,
                description_en = desc_en,
            )
            out["written"] += 1
        except Exception as exc:
            out["errors"].append({
                "product_code": pc,
                "stage": "get_description_block",
                "detail": f"{type(exc).__name__}: {exc}",
            })

    return out


# ── Canonical customs-description resolver (single authority, V1 + V2) ────────
#
# The customs Polish-description pipeline (customs_description_engine →
# process_batch_items → normalize_item_description) is a text classifier that
# fabricates generic placeholder text ("Wyrób jubilerski", "metal szlachetny")
# when it cannot classify a line. That generic text is correctly rejected by
# the post-generation `polish_desc_forbidden_tokens` read-back — but only AFTER
# the PDF is built, with no per-row explanation. This resolver is the single
# authority both V1 and V2 consult (via the shared route
# POST /api/v1/dhl/generate-description/{batch_id}) to decide, per line and
# BEFORE generation, whether an APPROVED, non-generic description exists.
#
# Reuse-only: it consults the existing Product Description Authority
# (`product_descriptions` table via document_db, source='manual' = approved),
# shipment-level operator corrections (audit["description_corrections"], written
# by the existing action-proposals approve route), and the invoice classifier
# (customs_description_engine.normalize_item_description) — it introduces NO new
# table and writes nothing. It never returns a generic fallback; a line with no
# approved, non-generic description resolves to status="missing_description".

# Generic placeholder strings that must NEVER reach a generated customs
# document. THIS is the single source of truth — the route-level and the
# engine-internal forbidden-token read-backs both import from here (do not
# re-declare a divergent local copy).
FORBIDDEN_DESC_TOKENS = (
    "Wyrób jubilerski",
    "wyrób jubilerski",
    "metal szlachetny",
    "UNKNOWN",
    "grouped invoice aggregate",
)

# PDF byte-level read-back set: the description tokens above PLUS the U+25A0
# BLACK SQUARE glyph that appears when Polish diacritics fail to render (font
# missing). Only meaningful against rendered PDF text, so it lives here as the
# superset used by every post-generation PDF read-back.
PDF_FORBIDDEN_TOKENS = FORBIDDEN_DESC_TOKENS + ("■",)


def _contains_forbidden_desc_token(*texts: str) -> Optional[str]:
    """Return the first forbidden/generic token found across *texts*, else None."""
    for t in texts:
        s = (t or "")
        for tok in FORBIDDEN_DESC_TOKENS:
            if tok in s:
                return tok
    return None


def resolve_product_description_for_customs(
    product_code: str,
    invoice_row:  Optional[Dict[str, Any]] = None,
    product_master: Optional[Dict[str, Any]] = None,
    corrections:  Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve the approved customs Polish description for one product line.

    Single authority for V1 and V2. Source priority (never fabricates):
      a. shipment-level operator correction (audit["description_corrections"][pc])
      b. approved Product Description Authority row (product_descriptions,
         source='manual')
      c. safe invoice classifier result — only if it is NON-generic
      d. STOP → status="missing_description"

    ``product_master`` is accepted for API completeness / future use; the
    approved description text is owned by ``product_descriptions`` (source
    ='manual'), not the master identity row.

    Returns dict:
      {product_code, description_pl, source, status, reason, invoice, row,
       extracted_description, forbidden_token}
    where status ∈ {"ok", "missing_description"}, source ∈
    {"operator_correction_shipment", "product_master_manual",
     "invoice_classifier", None}.
    """
    row = invoice_row or {}
    pc = (product_code or "").strip()
    extracted = str(
        row.get("original_description")
        or row.get("description")
        or row.get("desc")
        or ""
    ).strip()
    ctx = {
        "product_code":          pc,
        "invoice":               str(row.get("invoice_number") or row.get("invoice_no") or ""),
        "row":                   row.get("line_position") or row.get("line_order"),
        "extracted_description": extracted,
    }

    def _ok(description_pl: str, source: str,
            material_pl: str = "", name_pl: str = "",
            description_en: str = "") -> Dict[str, Any]:
        return {**ctx, "description_pl": description_pl,
                "material_pl": material_pl or "", "name_pl": name_pl or "",
                "description_en": description_en or "",
                "source": source, "status": "ok", "reason": None,
                "forbidden_token": None}

    def _missing(reason: str, forbidden_token: Optional[str]) -> Dict[str, Any]:
        return {**ctx, "description_pl": None, "material_pl": "", "name_pl": "",
                "source": None, "status": "missing_description", "reason": reason,
                "forbidden_token": forbidden_token}

    if not pc:
        return _missing("Line has no product_code — cannot resolve an "
                        "approved description.", None)

    # (a) shipment-level operator correction
    corr = (corrections or {}).get(pc) or {}
    corr_pl = str(corr.get("description_pl") or corr.get("material_pl") or "").strip()
    if corr_pl:
        bad = _contains_forbidden_desc_token(corr_pl, str(corr.get("material_pl") or ""))
        if not bad:
            return _ok(corr_pl, "operator_correction_shipment",
                       material_pl=str(corr.get("material_pl") or ""),
                       description_en=str(corr.get("description_en") or ""))
        # A correction that still contains generic text is not a valid fix.
        return _missing("Saved correction still contains generic placeholder "
                        f"text ({bad!r}).", bad)

    # (b) approved Product Description Authority (product_descriptions, manual)
    try:
        pd = ddb.get_product_description(pc)
    except Exception as exc:  # never let a read error fabricate a pass
        log.warning("resolver: get_product_description(%r) failed: %s", pc, exc)
        pd = None
    if pd and str(pd.get("source") or "").strip() == "manual":
        pd_pl = str(pd.get("description_pl") or "").strip()
        bad = _contains_forbidden_desc_token(pd_pl, str(pd.get("material_pl") or ""))
        if pd_pl and not bad:
            return _ok(pd_pl, "product_master_manual",
                       material_pl=str(pd.get("material_pl") or ""),
                       name_pl=str(pd.get("name_pl") or ""),
                       description_en=str(pd.get("description_en") or ""))
        # else: an approved row that is empty/generic is not usable — fall through

    # (c) safe invoice classifier — accepted ONLY if non-generic
    cde = _load_customs_engine()
    if cde is not None and extracted:
        try:
            norm = cde.normalize_item_description(
                extracted,
                item_type=_normalise_item_type(str(row.get("item_type", "") or "")),
                hsn_from_invoice="",
            )
        except Exception as exc:
            log.warning("resolver: normalize_item_description failed for %r: %s", pc, exc)
            norm = None
        if norm:
            desc_pl  = str(norm.get("polish_customs_description") or "").strip()
            item_pl  = str(norm.get("item_type_pl") or "")
            mat_pl   = str(norm.get("material_pl") or "")
            bad = _contains_forbidden_desc_token(desc_pl, item_pl, mat_pl)
            if desc_pl and not bad:
                return _ok(desc_pl, "invoice_classifier",
                           material_pl=mat_pl, name_pl=item_pl)
            # generic classifier output → block below with the offending token
            return _missing(
                "No approved description; the invoice text could not be "
                "classified and would fall back to generic placeholder text.",
                bad or "Wyrób jubilerski",
            )

    # (d) nothing usable
    return _missing(
        "No approved product description and no usable invoice description.",
        None,
    )


def find_missing_customs_descriptions(
    rows: Any,
    corrections: Optional[Dict[str, Any]] = None,
) -> list:
    """Batch helper for the pre-generation guard.

    Runs :func:`resolve_product_description_for_customs` over every projected
    row and returns the row-level detail for each line that does NOT resolve to
    an approved, non-generic description. Empty list ⇒ safe to generate.
    """
    missing: list = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        res = resolve_product_description_for_customs(
            product_code=str(r.get("product_code") or ""),
            invoice_row=r,
            corrections=corrections or {},
        )
        if res.get("status") != "ok":
            missing.append({
                "invoice":               res["invoice"],
                "row":                   res["row"],
                "product_code":          res["product_code"],
                "extracted_description": res["extracted_description"],
                "reason":                res["reason"],
                "forbidden_token":       res["forbidden_token"],
                "suggested_correction_route":
                    "POST /api/v1/action-proposals/{proposal_id}/approve "
                    "(scope=shipment) or set an approved product_descriptions "
                    "row (source='manual')",
            })
    return missing


def resolve_and_stamp_customs_descriptions(
    rows: Any,
    corrections: Optional[Dict[str, Any]] = None,
) -> list:
    """Resolve every row through the canonical authority and STAMP the approved
    value onto the row so downstream generation (process_batch_items → SAD JSON
    → Polish Description PDF) consumes the RESOLVER output, not the classifier's
    own text. This is what makes the resolver the generation *source of truth*,
    not merely a validation layer.

    For each row that resolves to status="ok" the following authoritative fields
    are stamped (consumed by customs_description_engine.process_batch_items and
    _generate_pdf):
        row["_resolved_description_pl"]  — approved Polish customs description
        row["_resolved_material_pl"]     — approved material (may be "")
        row["_resolved_name_pl"]         — approved item-type noun (may be "")
        row["_resolved_source"]          — provenance
        row["_desc_authoritative"] = True

    Returns the list of row-level detail for lines that could NOT be approved
    (identical shape to :func:`find_missing_customs_descriptions`). A non-empty
    return MUST block generation with 422 descriptions_missing_for_customs — no
    generic fallback may reach a customs document.
    """
    missing: list = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        res = resolve_product_description_for_customs(
            product_code=str(r.get("product_code") or ""),
            invoice_row=r,
            corrections=corrections or {},
        )
        if res.get("status") == "ok":
            r["_resolved_description_pl"] = res["description_pl"]
            r["_resolved_material_pl"]    = res.get("material_pl") or ""
            r["_resolved_name_pl"]        = res.get("name_pl") or ""
            # Approved English half (operator correction / manual block). Empty
            # for classifier-sourced rows, where the invoice English is used.
            r["_resolved_description_en"] = res.get("description_en") or ""
            r["_resolved_source"]         = res["source"]
            r["_desc_authoritative"]      = True
        else:
            # Never leave a stale authoritative stamp on a now-unapproved row.
            for k in ("_resolved_description_pl", "_resolved_material_pl",
                      "_resolved_name_pl", "_resolved_description_en",
                      "_resolved_source", "_desc_authoritative"):
                r.pop(k, None)
            missing.append({
                "invoice":               res["invoice"],
                "row":                   res["row"],
                "product_code":          res["product_code"],
                "extracted_description": res["extracted_description"],
                "reason":                res["reason"],
                "forbidden_token":       res["forbidden_token"],
                "suggested_correction_route":
                    "POST /api/v1/action-proposals/{proposal_id}/approve "
                    "(scope=shipment) or set an approved product_descriptions "
                    "row (source='manual')",
            })
    return missing
