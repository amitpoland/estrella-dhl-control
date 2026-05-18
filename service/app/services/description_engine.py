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


def _load_customs_engine():
    """
    Lazily import customs_description_engine for rich per-line Polish
    customs phrasing (e.g. "Pierścionek ze złota próby 585 z diamentami
    laboratoryjnymi") rather than the generic ITEM_TRANSLATIONS default
    ("Biżuteria — pierścionek"). Returns None if the engine module isn't
    importable — caller falls back to ITEM_TRANSLATIONS.
    """
    global _CUSTOMS_ENGINE_CACHE
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
