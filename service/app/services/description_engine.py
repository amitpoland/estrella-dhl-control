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
