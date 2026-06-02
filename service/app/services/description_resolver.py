"""
description_resolver.py — Shared metal/purity fact resolver.

Sits between the description checker and the engine.  Resolves a raw invoice
token to a structured fact set (canonical_metal, purity, material_pl,
purity_gen) from operator-approved DB rows.  On a hit, the caller passes the
facts to ``customs_description_engine.normalize_item_description(resolved_facts=…)``
so the engine generates correct Polish wording without re-parsing the token.

Authority model:
    resolver.lookup(token)
        HIT  → return facts → engine uses facts, skips GOLD_PURITY scan
        MISS → engine runs GOLD_PURITY scan (existing path)
        BOTH MISS → checker emits Inbox proposal

Write authority:
    ONLY ``write_mapping()`` writes to description_mappings.
    ONLY called from the approved Inbox action handler.
    Never called by the checker, AI layer, or background process.

Auditability:
    Every row stores approved_by / approved_at / source_proposal_id /
    source_text.  "Why does PT960 resolve to platyna próby 960?" is
    answerable from the DB row without archaeology.

Governance rule (locked):
    Known token (in DB or GOLD_PURITY) → render
    Unknown token                       → Inbox proposal, empty suggestion
"""
from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings

log = logging.getLogger(__name__)

_DB_PATH: Path = settings.storage_root / "master_data.sqlite"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_path() -> Path:
    return _DB_PATH


def _ensure_table() -> None:
    """Create description_mappings if it doesn't exist (idempotent)."""
    from .master_data_db import init_db  # noqa: PLC0415
    init_db(_db_path())


# ── Public: lookup ────────────────────────────────────────────────────────────

def lookup(
    token: str,
    supplier_scope: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Return resolver facts for *token* or None on miss.

    Returns a dict with keys: canonical_metal, purity, material_pl, purity_gen.
    The caller passes this directly to normalize_item_description(resolved_facts=…).

    Lookup order:
      1. Exact match: token + supplier_scope (supplier-scoped rule wins)
      2. Exact match: token + supplier_scope=NULL (global rule)
      3. None → caller falls through to engine GOLD_PURITY scan

    Only active rows (active=1) are returned.
    """
    token_up = (token or "").strip().upper()
    if not token_up:
        return None

    try:
        _ensure_table()
        with sqlite3.connect(str(_db_path())) as conn:
            conn.row_factory = sqlite3.Row
            # Supplier-scoped first
            if supplier_scope:
                row = conn.execute(
                    "SELECT canonical_metal, purity, material_pl, purity_gen "
                    "FROM description_mappings "
                    "WHERE token = ? AND supplier_scope = ? AND active = 1 "
                    "LIMIT 1",
                    (token_up, supplier_scope),
                ).fetchone()
                if row:
                    return _row_to_facts(row)
            # Global fallback
            row = conn.execute(
                "SELECT canonical_metal, purity, material_pl, purity_gen "
                "FROM description_mappings "
                "WHERE token = ? AND supplier_scope IS NULL AND active = 1 "
                "LIMIT 1",
                (token_up,),
            ).fetchone()
            if row:
                return _row_to_facts(row)
    except Exception as exc:
        log.warning("description_resolver.lookup(%r): %s", token, exc)

    return None


def _row_to_facts(row: sqlite3.Row) -> Dict[str, str]:
    return {
        "canonical_metal": row["canonical_metal"] or "",
        "purity":          row["purity"]          or "",
        "material_pl":     row["material_pl"]     or "",
        "purity_gen":      row["purity_gen"]      or row["material_pl"] or "",
    }


# ── Public: tokenize ──────────────────────────────────────────────────────────

def _tokenize(description: str) -> List[str]:
    """Extract candidate lookup tokens from a raw invoice description.

    Returns tokens in specificity order — most specific first so PT950 is
    checked before a shorter token.

    Examples:
        "PCS, PT950 Platinum, Plain RING" → ["PT950", "PLATINUM"]
        "PCS, 18KT/Y Gold, Plain Ring"   → ["18KT", "GOLD"]
        "PCS, 14KT Gold, Diamond RING"   → ["14KT", "GOLD"]
    """
    raw_up = (description or "").upper()

    # Strip punctuation, split on spaces and commas
    words = re.split(r"[\s,/\-]+", raw_up)
    words = [w for w in words if w and len(w) >= 2]

    # Deduplicate preserving order
    seen: set = set()
    result: List[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            result.append(w)

    # Sort: longer tokens first (more specific), shorter after
    result.sort(key=lambda t: -len(t))
    return result


# ── Public: suggest ───────────────────────────────────────────────────────────

def _suggest_material_pl(token: str) -> Optional[str]:
    """Suggest material_pl for a token ONLY when it matches a known entry in
    GOLD_PURITY (the engine's stable allowlist).

    Returns a suggestion string (advisory only — never written to DB or PDF
    without operator approval) or None if the token is unknown.

    Governance: no pattern-matching heuristics for unknown purities.
    PT960 → None (system declines to guess; operator investigates).
    PT950 → "platyna próby 950" (in GOLD_PURITY → suggestion populated).

    The caller populates data.suggested_material_pl in the proposal.
    An empty suggestion is valid — operator fills the field manually.
    """
    try:
        from pathlib import Path as _Path  # noqa: PLC0415
        import sys as _sys
        engine_dir = str(settings.engine_dir)
        if engine_dir not in _sys.path:
            _sys.path.insert(0, engine_dir)
        import customs_description_engine as _cde  # type: ignore
        # Direct GOLD_PURITY lookup — no regex, no pattern inference.
        token_up = (token or "").strip().upper()
        return _cde.GOLD_PURITY.get(token_up)
    except Exception as exc:
        log.warning("description_resolver._suggest_material_pl(%r): %s", token, exc)
        return None


# ── Public: write_mapping ─────────────────────────────────────────────────────

def write_mapping(
    token:              str,
    material_pl:        str,
    approved_by:        str,
    approved_at:        str,
    source_proposal_id: str,
    source_text:        str,
    canonical_metal:    str = "",
    purity:             str = "",
    purity_gen:         str = "",
    description_pl:     Optional[str] = None,
    confidence:         str = "medium",
    supplier_scope:     Optional[str] = None,
) -> str:
    """Write an operator-approved global mapping to description_mappings.

    Returns the new row id.

    Called ONLY from the Inbox approve handler (routes_action_proposals.py)
    when scope="global_mapping".  Never called from the checker, AI layer,
    or any background process.

    Non-nullable audit fields: approved_by, approved_at, source_proposal_id,
    source_text.  Raises ValueError if any are missing.
    """
    if not approved_by:
        raise ValueError("write_mapping: approved_by is required (non-nullable)")
    if not approved_at:
        raise ValueError("write_mapping: approved_at is required (non-nullable)")
    if not source_proposal_id:
        raise ValueError("write_mapping: source_proposal_id is required (non-nullable)")
    if not source_text:
        raise ValueError("write_mapping: source_text is required (non-nullable)")
    if not material_pl:
        raise ValueError("write_mapping: material_pl is required")
    if not token:
        raise ValueError("write_mapping: token is required")

    token_up = token.strip().upper()
    row_id   = str(uuid.uuid4())
    now_iso  = datetime.now(timezone.utc).isoformat()

    # Derive purity_gen from material_pl if not supplied.
    # The caller should supply it; this is a safety fallback only.
    effective_purity_gen = purity_gen or material_pl

    _ensure_table()
    try:
        with sqlite3.connect(str(_db_path())) as conn:
            conn.execute(
                """
                INSERT INTO description_mappings
                    (id, token, canonical_metal, purity, material_pl, purity_gen,
                     description_pl, approved_by, approved_at, source_proposal_id,
                     source_text, confidence, supplier_scope, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    row_id, token_up,
                    canonical_metal or None,
                    purity or None,
                    material_pl,
                    effective_purity_gen,
                    description_pl or None,
                    approved_by,
                    approved_at,
                    source_proposal_id,
                    source_text,
                    confidence,
                    supplier_scope or None,
                    now_iso,
                ),
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        # Unique constraint on (token, supplier_scope): update the existing row
        # in-place rather than deactivate+insert (which would hit the same constraint).
        log.warning(
            "description_resolver.write_mapping: token=%r scope=%r already exists "
            "— updating existing row in-place (%s).",
            token_up, supplier_scope, exc,
        )
        with sqlite3.connect(str(_db_path())) as conn:
            conn.execute(
                """
                UPDATE description_mappings
                SET canonical_metal    = ?,
                    purity             = ?,
                    material_pl        = ?,
                    purity_gen         = ?,
                    description_pl     = ?,
                    approved_by        = ?,
                    approved_at        = ?,
                    source_proposal_id = ?,
                    source_text        = ?,
                    confidence         = ?,
                    active             = 1
                WHERE token = ? AND COALESCE(supplier_scope, '') = ?
                """,
                (
                    canonical_metal or None,
                    purity or None,
                    material_pl,
                    effective_purity_gen,
                    description_pl or None,
                    approved_by,
                    approved_at,
                    source_proposal_id,
                    source_text,
                    confidence,
                    token_up,
                    supplier_scope or "",
                ),
            )
            conn.commit()

    log.info(
        "description_resolver.write_mapping: token=%r material_pl=%r "
        "approved_by=%r id=%s",
        token_up, material_pl, approved_by, row_id,
    )
    return row_id
