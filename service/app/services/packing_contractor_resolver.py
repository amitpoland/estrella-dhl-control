"""packing_contractor_resolver.py — B0.X R1 deterministic resolver.

Given parsed packing-list contractor data, returns a verdict that pre-selects
a matching Client Master or Supplier Master row when possible. Pure
read-only: consults ``customer_master.sqlite`` and ``suppliers.sqlite``
directly. NEVER calls wFirma. NEVER writes to any DB.

Design reference: ``tasks/packing-list-contractor-resolver-design.md``.

Public API
----------
``resolve_contractor(parsed: dict, role: str, *, cm_db_path=None,
sup_db_path=None) -> dict`` — returns the verdict structure documented
in the design's Tier-output schema.

Matching tiers (deterministic, ordered, higher tier wins)
---------------------------------------------------------
1.  wFirma id exact         — confidence 1.00
2.  Tax/VAT id exact         — 0.95
3.  Normalised name+country  — 0.85
4.  Alias / short_code       — 0.80
5.  Fuzzy name+country       — capped at 0.70 (ratio≥85 to be returned)
6.  Unresolved (no match)    — 0.00, top-5 candidates surfaced anyway

Fuzzy library
-------------
RapidFuzz is the preferred fuzzy backend (design doc) but is NOT a
project dependency yet. R1 uses ``difflib.SequenceMatcher.ratio()``
(stdlib). Quality is sufficient for the 0.85 cap-rule; upgrading to
RapidFuzz is a one-line swap inside ``_fuzzy_ratio`` if the operator
later approves the dependency update.

Hard rules (verified by tests in test_packing_contractor_resolver.py)
---------------------------------------------------------------------
- No wFirma write call (source-grep + monkey-patch trip-wire).
- No master-table write (trip-wire on customer_master_db.upsert_*
  and suppliers_db.upsert*/create_supplier).
- No proforma / PZ / DHL / customs / finance imports.
- No `.env` change.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import settings


# ── Default DB paths (overridable in tests) ──────────────────────────────────

_CM_DEFAULT_PATH  = settings.storage_root / "customer_master.sqlite"
_SUP_DEFAULT_PATH = settings.storage_root / "suppliers.sqlite"


# ── Normalisation ────────────────────────────────────────────────────────────

# Order matters — longer suffixes first so "Sp. z o.o." beats "z o.o."
# Patterns are matched as case-insensitive whole-word-or-end-of-string.
_LEGAL_SUFFIXES = (
    r"spółka z ograniczoną odpowiedzialnością",
    r"sp\.?\s*z\s*o\.?\s*o\.?",
    r"pvt\.?\s*ltd\.?",
    r"private\s+limited",
    r"s\.r\.o\.?",
    r"co\.?\s*,?\s*ltd\.?",
    r"co\.?\s*ltd\.?",
    r"limited",
    r"llp\.?",
    r"ltd\.?",
    r"gmbh",
    r"a\.?g\.?",
    r"s\.?a\.?s\.?",
    r"s\.?a\.?",
    r"b\.?v\.?",
    r"oy",
    r"ab",
    r"inc\.?",
    r"llc",
    r"eood",
    r"corp\.?",
)
_LEGAL_SUFFIXES_RE = re.compile(
    r"\b(?:" + "|".join(_LEGAL_SUFFIXES) + r")\b\s*\.?\s*$",
    re.IGNORECASE,
)


# Manual ASCII fallback table for letters that NFKD does not decompose.
# Polish ł/Ł, Nordic ø/Ø/æ/Æ/å/Å, German ß, Icelandic þ/Þ/ð/Ð.
_ASCII_FALLBACK = str.maketrans({
    "ł": "l", "Ł": "L",
    "ø": "o", "Ø": "O",
    "æ": "ae", "Æ": "AE",
    "å": "a", "Å": "A",
    "ß": "ss",
    "þ": "th", "Þ": "Th",
    "ð": "d",  "Ð": "D",
})


def _strip_accents(s: str) -> str:
    """Strip combining accents AND apply manual ASCII fallback for letters
    NFKD does not decompose (Polish ł, Nordic ø/æ/å, German ß, etc.)."""
    nfkd = unicodedata.normalize("NFKD", s)
    base = "".join(c for c in nfkd if not unicodedata.combining(c))
    return base.translate(_ASCII_FALLBACK)


def normalise_name(name: Optional[str]) -> str:
    """Operator-stable normalised key.

    1. lowercase
    2. strip accents
    3. drop punctuation (keep alphanumerics + spaces)
    4. drop legal-form suffixes ("Sp. z o.o.", "LLP", "GmbH", ...)
    5. collapse whitespace

    Empty / None → "".  Pure function, no I/O.
    """
    if not name:
        return ""
    s = _strip_accents(str(name)).lower().strip()
    # Drop trailing non-word punctuation BEFORE suffix detection so that
    # "beta, GMBH!" reaches the suffix regex as "beta, gmbh".
    s = re.sub(r"[^\w\s,.\-]+$", "", s).strip()
    # Drop trailing legal suffix once or twice (handles "Co., Ltd." → "" path).
    for _ in range(2):
        before = s
        s = _LEGAL_SUFFIXES_RE.sub("", s).strip(" ,.;:-")
        if s == before:
            break
    # Drop punctuation except spaces.
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    # Collapse whitespace.
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalise_tax_id(tax_id: Optional[str]) -> str:
    """Strip whitespace, hyphens, and country-prefix sensitivity from a
    tax id so 'PL1234567890' and '1234567890' and 'PL 123 456 78 90'
    compare equal."""
    if not tax_id:
        return ""
    s = re.sub(r"[\s\-_.]+", "", str(tax_id)).upper()
    # Drop a 2-letter country prefix if it matches an ISO alpha-2 shape.
    if len(s) > 2 and s[:2].isalpha():
        s = s[2:]
    return s


def normalise_country(country: Optional[str]) -> str:
    """Uppercase ISO alpha-2. Empty / None / non-ISO → ""."""
    if not country:
        return ""
    s = str(country).strip().upper()
    return s if len(s) == 2 and s.isalpha() else ""


# ── Fuzzy ratio (stdlib for R1) ──────────────────────────────────────────────

def _fuzzy_ratio(a: str, b: str) -> int:
    """Return a 0-100 score. SequenceMatcher.ratio() is 0.0-1.0."""
    if not a or not b:
        return 0
    return int(round(SequenceMatcher(None, a, b).ratio() * 100))


# ── Master accessors (read-only) ─────────────────────────────────────────────

def _load_client_master(db_path: Path) -> List[Dict[str, Any]]:
    """Return all Client Master rows as dicts. Read-only."""
    from . import customer_master_db as cmdb
    try:
        recs = cmdb.list_customers(db_path, limit=10_000)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in recs:
        out.append({
            "master_type":    "client_master",
            "master_id":      r.id,
            "display_name":   r.bill_to_name or "",
            "country":        r.country or "",
            "wfirma_id":      r.bill_to_contractor_id or "",
            "tax_id":         r.nip or "",
            "tax_id_eu":      r.vat_eu_number or "",
            "alias":          r.short_code or "",
            "normalised":     normalise_name(r.bill_to_name),
        })
    return out


def _load_supplier_master(db_path: Path) -> List[Dict[str, Any]]:
    """Return all Supplier Master rows as dicts. Read-only."""
    from . import suppliers_db as sdb
    try:
        recs = sdb.list_suppliers(db_path, limit=10_000)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in recs:
        out.append({
            "master_type":    "supplier_master",
            "master_id":      r.id,
            "display_name":   r.name or "",
            "country":        r.country or "",
            "wfirma_id":      r.wfirma_id or "",
            "tax_id":         r.vat_id or "",
            "tax_id_eu":      "",
            "alias":          r.supplier_code or "",
            "normalised":     normalise_name(r.name),
        })
    return out


# ── Public API ───────────────────────────────────────────────────────────────

_ALLOWED_ROLES = ("client", "supplier")


def resolve_contractor(
    parsed: Dict[str, Any],
    role: str,
    *,
    cm_db_path:  Optional[Path] = None,
    sup_db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Deterministic contractor resolver. See module docstring for tiers.

    No DB writes. No wFirma calls. Pure read against the local master
    SQLite files. Verdict shape matches the design doc.
    """
    if role not in _ALLOWED_ROLES:
        raise ValueError(f"role must be one of {_ALLOWED_ROLES}, got {role!r}")

    parsed_name    = (parsed or {}).get("parsed_name") or ""
    parsed_tax_id  = (parsed or {}).get("parsed_tax_id") or ""
    parsed_country = (parsed or {}).get("parsed_country") or ""
    parsed_wfid    = (parsed or {}).get("parsed_wfirma_id") or ""

    nm_norm   = normalise_name(parsed_name)
    tx_norm   = normalise_tax_id(parsed_tax_id)
    cty_norm  = normalise_country(parsed_country)
    wfid_norm = (str(parsed_wfid) or "").strip()

    master = (_load_client_master(cm_db_path or _CM_DEFAULT_PATH)
              if role == "client"
              else _load_supplier_master(sup_db_path or _SUP_DEFAULT_PATH))

    # ── Tier 1: exact wFirma id match ────────────────────────────────────────
    if wfid_norm:
        for row in master:
            if row["wfirma_id"] and row["wfirma_id"] == wfid_norm:
                return _build_verdict(
                    role, parsed_name, parsed_tax_id, parsed_country,
                    tier=1, confidence=1.00, reason="wfirma_id_exact",
                    matched=row,
                    evidence={"matched_on": "wfirma_id", "wfirma_id": wfid_norm},
                    candidates=_top_candidates(master, nm_norm, cty_norm, top=5),
                    status="auto",
                )

    # ── Tier 2: exact tax / VAT id match ─────────────────────────────────────
    if tx_norm:
        for row in master:
            local_tax_norm    = normalise_tax_id(row["tax_id"])
            local_tax_eu_norm = normalise_tax_id(row["tax_id_eu"])
            if local_tax_norm and local_tax_norm == tx_norm:
                return _build_verdict(
                    role, parsed_name, parsed_tax_id, parsed_country,
                    tier=2, confidence=0.95, reason="tax_id_exact",
                    matched=row,
                    evidence={"matched_on": "tax_id", "parsed_tax_id": tx_norm,
                              "local_tax_id": local_tax_norm},
                    candidates=_top_candidates(master, nm_norm, cty_norm, top=5),
                    status="auto",
                )
            if local_tax_eu_norm and local_tax_eu_norm == tx_norm:
                return _build_verdict(
                    role, parsed_name, parsed_tax_id, parsed_country,
                    tier=2, confidence=0.95, reason="vat_eu_exact",
                    matched=row,
                    evidence={"matched_on": "vat_eu_number", "parsed_tax_id": tx_norm,
                              "local_vat_eu": local_tax_eu_norm},
                    candidates=_top_candidates(master, nm_norm, cty_norm, top=5),
                    status="auto",
                )

    # ── Tier 3: exact normalised name + country ─────────────────────────────
    if nm_norm and cty_norm:
        exact_name_country = [
            row for row in master
            if row["normalised"] and row["normalised"] == nm_norm
               and row["country"] == cty_norm
        ]
        if len(exact_name_country) == 1:
            return _build_verdict(
                role, parsed_name, parsed_tax_id, parsed_country,
                tier=3, confidence=0.85, reason="name_plus_country_exact",
                matched=exact_name_country[0],
                evidence={"matched_on": "name+country",
                          "normalised_name": nm_norm, "country": cty_norm},
                candidates=_top_candidates(master, nm_norm, cty_norm, top=5),
                status="auto",
            )
        if len(exact_name_country) > 1:
            # Ambiguous — multiple master rows share the same normalised
            # name + country. Operator must pick. We still surface all
            # candidates including the colliding rows.
            ambig_candidates = [
                {"master_type": r["master_type"], "master_id": r["master_id"],
                 "display_name": r["display_name"], "country": r["country"],
                 "wfirma_id": r["wfirma_id"], "tax_id": r["tax_id"],
                 "score": 100, "reason": "name_plus_country_exact_collision"}
                for r in exact_name_country[:5]
            ]
            return _build_verdict(
                role, parsed_name, parsed_tax_id, parsed_country,
                tier=6, confidence=0.0, reason="name_plus_country_ambiguous",
                matched=None,
                evidence={"normalised_name": nm_norm, "country": cty_norm,
                          "duplicate_count": len(exact_name_country)},
                candidates=ambig_candidates,
                status="unresolved",
            )

    # ── Tier 4: alias / short_code exact match ──────────────────────────────
    if parsed_name:
        # Operators often paste the short code as the "client name". Match
        # against alias case-insensitively, both with and without legal-suffix
        # normalisation on the alias side.
        parsed_raw = parsed_name.strip().lower()
        for row in master:
            alias_raw = (row.get("alias") or "").strip().lower()
            if alias_raw and (alias_raw == parsed_raw or alias_raw == nm_norm):
                return _build_verdict(
                    role, parsed_name, parsed_tax_id, parsed_country,
                    tier=4, confidence=0.80, reason="alias_exact",
                    matched=row,
                    evidence={"matched_on": "alias", "alias": alias_raw,
                              "parsed_name": parsed_name},
                    candidates=_top_candidates(master, nm_norm, cty_norm, top=5),
                    status="auto",
                )

    # ── Tier 5: fuzzy name + country ────────────────────────────────────────
    if nm_norm:
        country_filtered = (
            [r for r in master if r["country"] == cty_norm] if cty_norm else master
        )
        ranked = sorted(
            (
                (r, _fuzzy_ratio(nm_norm, r["normalised"] or ""))
                for r in country_filtered if r["normalised"]
            ),
            key=lambda x: x[1], reverse=True,
        )
        if ranked and ranked[0][1] >= 85:
            best_row, best_score = ranked[0]
            # Cap fuzzy confidence at 0.70 so it never beats an exact tier.
            conf = min(0.70, best_score / 100.0)
            return _build_verdict(
                role, parsed_name, parsed_tax_id, parsed_country,
                tier=5, confidence=conf,
                reason=f"fuzzy_name_country:{best_score}",
                matched=best_row,
                evidence={"matched_on": "fuzzy",
                          "normalised_name": nm_norm, "country": cty_norm,
                          "score": best_score},
                candidates=_top_candidates_from_ranked(ranked, top=5),
                status="auto",
            )

    # ── Tier 6: unresolved ──────────────────────────────────────────────────
    return _build_verdict(
        role, parsed_name, parsed_tax_id, parsed_country,
        tier=6, confidence=0.0, reason="no_match",
        matched=None,
        evidence={"normalised_name": nm_norm, "country": cty_norm,
                  "had_tax_id": bool(tx_norm), "had_wfirma_id": bool(wfid_norm)},
        candidates=_top_candidates(master, nm_norm, cty_norm, top=5),
        status="unresolved",
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_verdict(
    role: str,
    parsed_name: str,
    parsed_tax_id: str,
    parsed_country: str,
    *,
    tier: int,
    confidence: float,
    reason: str,
    matched: Optional[Dict[str, Any]],
    evidence: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    status: str,
) -> Dict[str, Any]:
    return {
        "role":                role,
        "parsed_name":         parsed_name,
        "parsed_tax_id":       parsed_tax_id,
        "parsed_country":      parsed_country,
        "matched_master_type": (matched or {}).get("master_type"),
        "matched_master_id":   (matched or {}).get("master_id"),
        "matched_wfirma_id":   (matched or {}).get("wfirma_id"),
        "tier":                tier,
        "confidence":          round(float(confidence), 4),
        "reason":              reason,
        "evidence":            evidence,
        "candidates":          candidates,
        "status":              status,
    }


def _top_candidates(
    master: List[Dict[str, Any]],
    nm_norm: str,
    cty_norm: str,
    *,
    top: int,
) -> List[Dict[str, Any]]:
    """Always-return top-N fuzzy candidates regardless of tier verdict.

    Filters by country if known so the operator's override list stays
    relevant. If country empty, scans the full master.
    """
    if not master:
        return []
    pool = ([r for r in master if r["country"] == cty_norm]
            if cty_norm else list(master))
    ranked: List[Tuple[Dict[str, Any], int]] = []
    for r in pool:
        score = _fuzzy_ratio(nm_norm, r.get("normalised") or "") if nm_norm else 0
        ranked.append((r, score))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return _top_candidates_from_ranked(ranked, top=top)


def _top_candidates_from_ranked(
    ranked: List[Tuple[Dict[str, Any], int]],
    *,
    top: int,
) -> List[Dict[str, Any]]:
    return [
        {
            "master_type":  r["master_type"],
            "master_id":    r["master_id"],
            "display_name": r["display_name"],
            "country":      r["country"],
            "wfirma_id":    r["wfirma_id"],
            "tax_id":       r["tax_id"],
            "score":        score,
            "reason":       f"fuzzy_ratio:{score}",
        }
        for r, score in ranked[:top]
    ]


__all__ = [
    "resolve_contractor",
    "normalise_name",
    "normalise_tax_id",
    "normalise_country",
]
